from __future__ import annotations

"""
/sync-test slash command implementation.

Verifies that key CLAUDE.md rules actually made it into each harness
config after sync. Sends a set of canonical "expectation probes" --
regex patterns derived from your CLAUDE.md rules -- against each synced
target config file, flagging targets where rules are missing or degraded.

Implementation split across:
- test_probes.py -- probe extraction and execution
- test_structural.py -- structural validation checks
"""

import json
import os
import sys
import shlex
import argparse
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.commands.test_probes import (  # noqa: E402
    HARNESS_CONFIG_PATHS as _HARNESS_CONFIG_PATHS,
    ProbeResult,
    RuleProbe,
    extract_probes as _extract_probes,
    find_target_file as _find_target_file,
    run_probes as _run_probes,
)
from src.commands.test_structural import (  # noqa: E402
    StructuralCheck,
    run_structural_checks,
)


# ──────────────────────────────────────────────────────────────────────────────
# Test runner
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class HarnessTestResult:
    """Aggregated test result for a single harness."""
    target: str
    config_file: Path | None
    probe_results: list[ProbeResult] = field(default_factory=list)
    structural_checks: list[StructuralCheck] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        struct_ok = all(c.passed for c in self.structural_checks)
        return not self.error and all(r.matched for r in self.probe_results) and struct_ok

    @property
    def failed_probes(self) -> list[ProbeResult]:
        return [r for r in self.probe_results if not r.matched]

    @property
    def failed_structural(self) -> list[StructuralCheck]:
        return [c for c in self.structural_checks if not c.passed]

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.probe_results if r.matched)

    @property
    def total_count(self) -> int:
        return len(self.probe_results)

    def format(self, verbose: bool = False) -> str:
        if self.error:
            return f"  {self.target:<12}  ERROR: {self.error}"

        if not self.config_file:
            return f"  {self.target:<12}  SKIP — config file not found (run /sync first)"

        status_icon = "\u2713" if self.passed else "\u2717"
        bar_pct = (self.pass_count / self.total_count * 100) if self.total_count else 100
        status_str = (
            f"{self.pass_count}/{self.total_count} probes passed  ({bar_pct:.0f}%)"
        )
        struct_failed = self.failed_structural
        struct_str = f"  {len(struct_failed)} structural issue(s)" if struct_failed else ""
        lines = [f"  {status_icon} {self.target:<12}  {status_str}  [{self.config_file.name}]{struct_str}"]

        if verbose or not self.passed:
            for pr in self.probe_results:
                icon = "  \u2713" if pr.matched else "  \u2717"
                lines.append(f"      {icon} {pr.probe.description}")
            for sc in self.structural_checks:
                if not sc.passed or verbose:
                    icon = "  \u2713" if sc.passed else "  \u2717"
                    lines.append(f"      {icon} [struct] {sc.message}")

        return "\n".join(lines)


def run_consistency_test(
    project_dir: Path,
    targets: list[str],
    probes: list[RuleProbe],
    structural: bool = True,
) -> list[HarnessTestResult]:
    """Run all probes and structural checks against all targets.

    Args:
        project_dir: Project root directory.
        targets: Harness names to test.
        probes: Semantic rule probes derived from CLAUDE.md.
        structural: If True, also run structural validation checks.

    Returns:
        List of HarnessTestResult, one per target.
    """
    results: list[HarnessTestResult] = []
    for target in targets:
        config_file = _find_target_file(target, project_dir)
        if not config_file:
            results.append(HarnessTestResult(target=target, config_file=None))
            continue
        try:
            probe_results = _run_probes(target, config_file, probes)
            struct_checks = run_structural_checks(config_file) if structural else []
        except Exception as e:
            results.append(HarnessTestResult(
                target=target, config_file=config_file, error=str(e),
            ))
            continue
        results.append(HarnessTestResult(
            target=target,
            config_file=config_file,
            probe_results=probe_results,
            structural_checks=struct_checks,
        ))
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Output formatting
# ──────────────────────────────────────────────────────────────────────────────

def _format_report(results: list[HarnessTestResult], verbose: bool = False) -> str:
    """Format a complete consistency test report."""
    total_targets = len(results)
    passed = sum(1 for r in results if r.passed and r.config_file)
    skipped = sum(1 for r in results if not r.config_file and not r.error)
    failed = total_targets - passed - skipped

    lines = [
        "Cross-Harness Behavior Consistency Test",
        "=" * 50,
        "",
    ]

    for result in results:
        lines.append(result.format(verbose=verbose))

    lines.append("")
    lines.append("\u2500" * 50)
    summary_parts = [f"{passed} passed"]
    if failed:
        summary_parts.append(f"{failed} FAILED")
    if skipped:
        summary_parts.append(f"{skipped} skipped (not synced)")
    lines.append("  " + " | ".join(summary_parts))

    if any(not r.passed and r.config_file for r in results):
        lines.append("")
        lines.append("  Tip: Run /sync to update harness configs, then re-run /sync-test.")
        lines.append(
            "  Rules missing from harness configs may have been dropped by the adapter,"
        )
        lines.append("  manually overwritten, or are unsupported by that harness.")

    return "\n".join(lines)


def _format_json(results: list[HarnessTestResult]) -> str:
    """Format results as JSON for machine-readable output."""
    output = []
    for r in results:
        entry: dict = {
            "target": r.target,
            "config_file": str(r.config_file) if r.config_file else None,
            "passed": r.passed,
            "error": r.error or None,
            "probe_results": [
                {
                    "description": pr.probe.description,
                    "heading": pr.probe.source_heading,
                    "matched": pr.matched,
                    "severity": pr.probe.severity,
                }
                for pr in r.probe_results
            ],
        }
        output.append(entry)
    return json.dumps(output, indent=2)


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Entry point for /sync-test command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-test",
        description=(
            "Verify that CLAUDE.md rules are consistently present across all "
            "synced harness config files."
        ),
    )
    parser.add_argument("--target", "-t", metavar="TARGET",
                        help="Test only this harness (e.g. codex, gemini).")
    parser.add_argument("--verbose", "-v", action="store_true", default=False,
                        help="Show all probe results, not just failures.")
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="Output format (default: text).")
    parser.add_argument("--project-dir", metavar="DIR", default="",
                        help="Project directory containing CLAUDE.md.")
    parser.add_argument("--min-probes", type=int, default=1,
                        help="Minimum number of probes required to consider a test meaningful.")

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    # Discover registered targets
    if args.target:
        targets = [args.target]
    else:
        try:
            from src.adapters import AdapterRegistry
            reg = AdapterRegistry(project_dir=project_dir)
            targets = list(reg.list_targets())
        except Exception:
            targets = list(_HARNESS_CONFIG_PATHS.keys())

    # Read source config
    try:
        from src.source_reader import SourceReader
        reader = SourceReader(project_dir=project_dir)
        source_data = reader.discover_all()
        rules = source_data.get("rules", [])
    except Exception as e:
        print(f"Error: could not read source config: {e}", file=sys.stderr)
        sys.exit(2)

    if not rules:
        print("No rules found in CLAUDE.md. Nothing to test.")
        print("Add rules to CLAUDE.md, run /sync, then re-run /sync-test.")
        sys.exit(0)

    # Extract probes from rules
    probes = _extract_probes(rules)

    if len(probes) < args.min_probes:
        print(
            f"Only {len(probes)} probe(s) could be derived from your rules "
            f"(minimum: {args.min_probes}). Rules must contain imperative "
            "phrases like 'always', 'never', 'must', etc. to be testable."
        )
        if args.min_probes > 1:
            sys.exit(0)

    if not probes:
        print("No testable probes found. Add rules with imperative language to CLAUDE.md.")
        sys.exit(0)

    # Run tests
    results = run_consistency_test(project_dir, targets, probes)

    # Output
    if args.format == "json":
        print(_format_json(results))
    else:
        print(_format_report(results, verbose=args.verbose))

    # Exit code
    any_failed = any(not r.passed and r.config_file and not r.error for r in results)
    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
