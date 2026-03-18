from __future__ import annotations

"""
/sync-test slash command implementation.

Verifies that key CLAUDE.md rules actually made it into each harness
config after sync. Sends a set of canonical "expectation probes" —
regex patterns derived from your CLAUDE.md rules — against each synced
target config file, flagging targets where rules are missing or degraded.

This catches cases where:
- A rule was added to CLAUDE.md but the adapter silently dropped it
- A harness-specific format strips content (e.g. very long lines truncated)
- A conflict/merge overwrote synced content with older manual edits

Usage:
    /sync-test                          # Test all configured harnesses
    /sync-test --target codex           # Test one harness
    /sync-test --verbose                # Show matched probes per file
    /sync-test --format json            # Machine-readable output

Exit codes:
    0 — all tests passed
    1 — one or more harnesses failed consistency checks
    2 — could not read source config (config error)
"""

from __future__ import annotations

import json
import os
import re
import sys
import shlex
import argparse
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)


# ──────────────────────────────────────────────────────────────────────────────
# Probe extraction — derive testable assertions from CLAUDE.md
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class RuleProbe:
    """A single testable assertion derived from a CLAUDE.md rule."""
    source_heading: str       # Section heading in CLAUDE.md
    pattern: re.Pattern       # Regex that must match in target config
    description: str          # Human-readable description
    severity: str = "error"   # "error" | "warning"


def _extract_probes(rules: list[dict]) -> list[RuleProbe]:
    """Derive RuleProbe objects from a list of source rules.

    For each rule block, extract the first imperative sentence and build
    a loose regex probe that checks for the key terms in the target file.

    Args:
        rules: List of rule dicts from SourceReader (each has 'content' key).

    Returns:
        List of RuleProbe objects.
    """
    probes: list[RuleProbe] = []
    for rule in rules:
        content = rule.get("content", "")
        if not content:
            continue

        # Extract section heading
        heading_match = re.search(r"^#{1,3}\s+(.+?)$", content, re.MULTILINE)
        heading = heading_match.group(1).strip() if heading_match else "(unnamed)"

        # Build probes from imperative lines (bullets, "Always", "Never", "Use")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip markdown list markers
            line = re.sub(r"^[-*]\s+", "", line).strip()
            if len(line) < 15 or len(line) > 200:
                continue
            # Look for strong imperative forms
            if not re.match(
                r"(always|never|use\s|avoid|do\s+not|must|require|prefer|enforce|run\s)",
                line,
                re.IGNORECASE,
            ):
                continue

            # Extract 2-4 key content words (skip stop words)
            _STOP = {
                "a", "an", "the", "and", "or", "in", "on", "at", "to",
                "for", "of", "with", "by", "as", "is", "are", "be",
                "that", "this", "when", "than", "all", "any", "use",
            }
            words = [
                w for w in re.findall(r"[A-Za-z]{4,}", line)
                if w.lower() not in _STOP
            ][:3]
            if len(words) < 2:
                continue

            # Build a loose regex that requires the key words in any order
            pattern_str = r"(?i)" + "".join(
                rf"(?=.*\b{re.escape(w)}\b)" for w in words
            )
            try:
                pat = re.compile(pattern_str, re.DOTALL)
            except re.error:
                continue

            probes.append(RuleProbe(
                source_heading=heading,
                pattern=pat,
                description=f"Rule '{heading}': expects keywords {words!r}",
                severity="warning",  # Missing words = warning, not hard error
            ))
            # Only generate one probe per rule section to avoid noise
            break

    return probes


# ──────────────────────────────────────────────────────────────────────────────
# Target file discovery — find the main config file per harness
# ──────────────────────────────────────────────────────────────────────────────

# Map harness name → candidate config file paths (relative to project_dir or HOME)
_HARNESS_CONFIG_PATHS: dict[str, list[str]] = {
    "codex":     ["AGENTS.md", ".codex/AGENTS.md"],
    "gemini":    ["GEMINI.md", ".gemini/GEMINI.md"],
    "opencode":  ["AGENTS.md", ".opencode/AGENTS.md"],
    "cursor":    [".cursor/rules/harnesssync.mdc", ".cursor/rules/CLAUDE.mdc"],
    "aider":     ["CONVENTIONS.md", ".aider/CONVENTIONS.md"],
    "windsurf":  [".windsurfrules", ".windsurf/rules.md"],
    "cline":     [".clinerules", ".cline/rules.md"],
    "continue":  [".continue/config.json", ".continue/rules.md"],
    "zed":       [".zed/settings.json", ".zed/assistant.md"],
    "vscode":    [".vscode/claude.md", ".vscode/CLAUDE.md"],
    "neovim":    [".config/nvim/claude.md", ".claude/neovim-rules.md"],
}


def _find_target_file(harness: str, project_dir: Path) -> Path | None:
    """Return the first existing config file for the given harness."""
    candidates = _HARNESS_CONFIG_PATHS.get(harness, [])
    for rel in candidates:
        path = project_dir / rel
        if path.exists():
            return path
        # Also try relative to HOME for user-level configs
        home_path = Path.home() / rel
        if home_path.exists():
            return home_path
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Test runner
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ProbeResult:
    """Result of running one probe against one target."""
    probe: RuleProbe
    matched: bool
    target: str


@dataclass
class HarnessTestResult:
    """Aggregated test result for a single harness."""
    target: str
    config_file: Path | None
    probe_results: list[ProbeResult] = field(default_factory=list)
    structural_checks: list["StructuralCheck"] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        struct_ok = all(c.passed for c in self.structural_checks)
        return not self.error and all(r.matched for r in self.probe_results) and struct_ok

    @property
    def failed_probes(self) -> list[ProbeResult]:
        return [r for r in self.probe_results if not r.matched]

    @property
    def failed_structural(self) -> list["StructuralCheck"]:
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

        status_icon = "✓" if self.passed else "✗"
        bar_pct = (self.pass_count / self.total_count * 100) if self.total_count else 100
        status_str = (
            f"{self.pass_count}/{self.total_count} probes passed  ({bar_pct:.0f}%)"
        )
        struct_failed = self.failed_structural
        struct_str = f"  {len(struct_failed)} structural issue(s)" if struct_failed else ""
        lines = [f"  {status_icon} {self.target:<12}  {status_str}  [{self.config_file.name}]{struct_str}"]

        if verbose or not self.passed:
            for pr in self.probe_results:
                icon = "  ✓" if pr.matched else "  ✗"
                lines.append(f"      {icon} {pr.probe.description}")
            for sc in self.structural_checks:
                if not sc.passed or verbose:
                    icon = "  ✓" if sc.passed else "  ✗"
                    lines.append(f"      {icon} [struct] {sc.message}")

        return "\n".join(lines)


def _run_probes(
    harness: str,
    config_path: Path,
    probes: list[RuleProbe],
) -> list[ProbeResult]:
    """Run all probes against a single target config file."""
    try:
        content = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []  # Caller handles via HarnessTestResult.error

    results: list[ProbeResult] = []
    for probe in probes:
        matched = bool(probe.pattern.search(content))
        results.append(ProbeResult(probe=probe, matched=matched, target=harness))
    return results


# ──────────────────────────────────────────────────────────────────────────────
# Structural validation (item 28 — Sync Correctness Test Suite)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class StructuralCheck:
    """Result of a single structural validation check on a target config file."""

    name: str          # Short check identifier
    passed: bool
    message: str       # Human-readable detail


def _validate_json(path: Path) -> list[StructuralCheck]:
    """Validate that a .json file is well-formed."""
    try:
        import json as _json
        text = path.read_text(encoding="utf-8")
        _json.loads(text)
        return [StructuralCheck("valid-json", True, f"{path.name}: valid JSON")]
    except Exception as exc:
        return [StructuralCheck("valid-json", False, f"{path.name}: invalid JSON — {exc}")]


def _validate_yaml(path: Path) -> list[StructuralCheck]:
    """Validate that a .yml/.yaml file is well-formed (stdlib only)."""
    # Python stdlib has no YAML parser; do a minimum sanity check
    try:
        text = path.read_text(encoding="utf-8")
        # Check for the most common YAML corruption: tabs used for indentation
        for line_no, line in enumerate(text.splitlines(), 1):
            if line.startswith("\t"):
                return [StructuralCheck(
                    "valid-yaml", False,
                    f"{path.name}:{line_no}: YAML files must not use tabs for indentation",
                )]
        return [StructuralCheck("valid-yaml", True, f"{path.name}: YAML structure looks OK")]
    except OSError as exc:
        return [StructuralCheck("valid-yaml", False, f"{path.name}: unreadable — {exc}")]


def _validate_toml(path: Path) -> list[StructuralCheck]:
    """Validate that a .toml file is well-formed."""
    try:
        text = path.read_text(encoding="utf-8")
        # Python 3.11+ has tomllib; fall back to basic bracket-balance check
        try:
            import tomllib  # type: ignore[import]
            tomllib.loads(text)
            return [StructuralCheck("valid-toml", True, f"{path.name}: valid TOML")]
        except ImportError:
            pass
        # Fallback: check bracket balance
        opens = text.count("[")
        closes = text.count("]")
        if opens != closes:
            return [StructuralCheck(
                "valid-toml", False,
                f"{path.name}: mismatched brackets ([={opens} ]={closes})",
            )]
        return [StructuralCheck("valid-toml", True, f"{path.name}: TOML brackets balanced")]
    except OSError as exc:
        return [StructuralCheck("valid-toml", False, f"{path.name}: unreadable — {exc}")]


def _validate_non_empty(path: Path) -> StructuralCheck:
    """Check that the file has meaningful content (not empty or stub)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        stripped = text.strip()
        if not stripped:
            return StructuralCheck("non-empty", False, f"{path.name}: file is empty")
        if len(stripped) < 20:
            return StructuralCheck(
                "non-empty", False,
                f"{path.name}: suspiciously short ({len(stripped)} chars) — may be a stub",
            )
        return StructuralCheck("non-empty", True, f"{path.name}: {len(stripped)} chars")
    except OSError as exc:
        return StructuralCheck("non-empty", False, f"{path.name}: unreadable — {exc}")


def _validate_symlinks(path: Path) -> list[StructuralCheck]:
    """Check that the file (if a symlink) resolves to an existing target."""
    if not path.is_symlink():
        return []
    resolved = path.resolve()
    if resolved.exists():
        return [StructuralCheck("symlink-resolves", True, f"{path.name}: symlink → {resolved}")]
    return [StructuralCheck(
        "symlink-resolves", False,
        f"{path.name}: broken symlink → {resolved} does not exist",
    )]


def _validate_no_truncation(path: Path) -> list[StructuralCheck]:
    """Warn when any line is suspiciously long (>8000 chars), which may indicate truncation."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if len(line) > 8000:
                return [StructuralCheck(
                    "no-truncation", False,
                    f"{path.name}:{line_no}: line is {len(line)} chars — possible runaway concatenation",
                )]
        return [StructuralCheck("no-truncation", True, f"{path.name}: line lengths OK")]
    except OSError:
        return []


def run_structural_checks(config_path: Path) -> list[StructuralCheck]:
    """Run all structural validation checks for a single target config file.

    Checks performed:
    - File is non-empty / not a stub
    - JSON validity (for .json files)
    - YAML basic sanity (for .yml/.yaml files)
    - TOML validity (for .toml files)
    - Symlink resolution (if applicable)
    - No suspiciously long lines (truncation guard)

    Args:
        config_path: Path to the synced target config file.

    Returns:
        List of StructuralCheck results, one per check performed.
    """
    checks: list[StructuralCheck] = []
    suffix = config_path.suffix.lower()

    checks.append(_validate_non_empty(config_path))
    checks.extend(_validate_symlinks(config_path))
    checks.extend(_validate_no_truncation(config_path))

    if suffix == ".json":
        checks.extend(_validate_json(config_path))
    elif suffix in (".yml", ".yaml"):
        checks.extend(_validate_yaml(config_path))
    elif suffix == ".toml":
        checks.extend(_validate_toml(config_path))

    return checks


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
        structural: If True, also run structural validation checks (JSON
                    validity, symlink resolution, non-empty, etc.).

    Returns:
        List of HarnessTestResult, one per target.
    """
    results: list[HarnessTestResult] = []
    for target in targets:
        config_file = _find_target_file(target, project_dir)
        if not config_file:
            results.append(HarnessTestResult(
                target=target,
                config_file=None,
            ))
            continue
        try:
            probe_results = _run_probes(target, config_file, probes)
            struct_checks = run_structural_checks(config_file) if structural else []
        except Exception as e:
            results.append(HarnessTestResult(
                target=target,
                config_file=config_file,
                error=str(e),
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
    lines.append("─" * 50)
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
            "synced harness config files. Flags targets where key rules are "
            "missing or were dropped during translation."
        ),
    )
    parser.add_argument(
        "--target", "-t",
        metavar="TARGET",
        help="Test only this harness (e.g. codex, gemini). Default: all registered targets.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Show all probe results, not just failures.",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument(
        "--project-dir",
        metavar="DIR",
        default="",
        help="Project directory containing CLAUDE.md (default: current directory).",
    )
    parser.add_argument(
        "--min-probes",
        type=int,
        default=1,
        help="Minimum number of probes required to consider a test meaningful (default: 1).",
    )

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
