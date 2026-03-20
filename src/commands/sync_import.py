from __future__ import annotations

"""
/sync-import slash command implementation.

Reads an existing Cursor .mdc rules file or Aider CONVENTIONS.md and merges
its content into CLAUDE.md -- the reverse of the normal sync direction.

Implementation split: import_helpers.py contains content cleaning, merging,
and drift detection logic.
"""

import os
import re
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.commands.import_helpers import (  # noqa: E402
    DEFAULT_FILES as _DEFAULT_FILES,
    clean_import_content as _clean_import_content,
    detect_drift,
    find_source_files as _find_source_files,
    merge_into_claude_md as _merge_into_claude_md,
)


def import_from_harness(
    harness: str,
    project_dir: Path,
    file_path: Path | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Import configuration from a target harness into CLAUDE.md.

    Args:
        harness: Source harness ("cursor", "aider", "codex", "gemini", "windsurf",
                 "opencode", "cline").
        project_dir: Project root directory.
        file_path: Specific file to import (auto-detected if None).
        dry_run: If True, preview only.

    Returns:
        List of result message strings.
    """
    messages: list[str] = []

    if file_path:
        source_files = [file_path] if file_path.is_file() else []
        if not source_files:
            return [f"Error: file not found: {file_path}"]
    else:
        source_files = _find_source_files(harness, project_dir)

    if not source_files:
        return [
            f"No {harness} config files found in {project_dir}.\n"
            f"Expected: {', '.join(_DEFAULT_FILES.get(harness, ['?']))}",
        ]

    claude_md_path = project_dir / "CLAUDE.md"

    for src in source_files:
        try:
            raw = src.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            messages.append(f"Error reading {src}: {e}")
            continue

        clean = _clean_import_content(raw, harness)

        if not clean.strip():
            messages.append(f"Skipped {src}: no user content after stripping managed sections.")
            continue

        msg, changed = _merge_into_claude_md(claude_md_path, clean, harness, dry_run)
        messages.append(f"{'[dry-run] ' if dry_run else ''}{src.name}: {msg}")

    if not dry_run and any("Merged" in m for m in messages):
        messages.append(
            f"\nImport complete. Review {claude_md_path} and remove duplicate rules."
        )

    return messages


def find_unique_rules(
    harness: str,
    project_dir: Path,
    file_path: Path | None = None,
) -> list[dict]:
    """Pull Mode: find rules in target harness that don't exist in CLAUDE.md.

    Scans the target harness config for bullet-point rules and compares them
    against what's already in CLAUDE.md. Returns rules that exist in the target
    but are absent from CLAUDE.md.

    Args:
        harness: Source harness to pull from.
        project_dir: Project root directory.
        file_path: Specific file to scan (auto-detected if None).

    Returns:
        List of dicts with keys: rule, source_file, harness.
    """
    _RULE_BULLET_RE = re.compile(r"^[-*]\s+(.+)$")

    def _extract_rules_from_text(text: str) -> set[str]:
        rules: set[str] = set()
        for line in text.splitlines():
            m = _RULE_BULLET_RE.match(line.strip())
            if m:
                rules.add(m.group(1).strip())
        return rules

    # Load existing CLAUDE.md rules
    claude_md = project_dir / "CLAUDE.md"
    existing_rules: set[str] = set()
    if claude_md.exists():
        try:
            existing_rules = _extract_rules_from_text(
                claude_md.read_text(encoding="utf-8", errors="replace")
            )
        except OSError:
            pass

    # Load target harness rules
    source_files = [file_path] if file_path and file_path.is_file() else _find_source_files(harness, project_dir)

    unique: list[dict] = []
    for src in source_files:
        try:
            raw = src.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        clean = _clean_import_content(raw, harness)
        target_rules = _extract_rules_from_text(clean)

        for rule in sorted(target_rules - existing_rules):
            unique.append({
                "rule": rule,
                "source_file": str(src),
                "harness": harness,
            })

    return unique


def pull_mode(
    harness: str,
    project_dir: Path,
    file_path: Path | None = None,
    dry_run: bool = False,
    interactive: bool = False,
) -> list[str]:
    """Bidirectional Sync Pull Mode -- propose target-only rules as CLAUDE.md additions.

    Args:
        harness: Target harness to pull from.
        project_dir: Project root directory.
        file_path: Specific file to scan (auto-detected if None).
        dry_run: If True, show proposals without writing.
        interactive: If True, ask the user to confirm each rule.

    Returns:
        List of result message strings.
    """
    unique = find_unique_rules(harness, project_dir, file_path)
    if not unique:
        return [f"No unique rules found in {harness} config that aren't already in CLAUDE.md."]

    messages: list[str] = [
        f"Found {len(unique)} rule(s) in {harness} not present in CLAUDE.md:"
    ]
    for item in unique:
        messages.append(f"  - {item['rule']}")

    if dry_run:
        messages.append("\n[dry-run] No changes written.")
        return messages

    # Decide which rules to accept
    accepted: list[str] = []
    if interactive and sys.stdin.isatty():
        for item in unique:
            try:
                choice = input(f"\n  Add? [{item['rule'][:80]}]  [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                break
            if choice in ("y", "yes"):
                accepted.append(item["rule"])
    else:
        accepted = [item["rule"] for item in unique]

    if not accepted:
        return messages + ["No rules selected."]

    # Append accepted rules to CLAUDE.md
    claude_md = project_dir / "CLAUDE.md"
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d")
    section_header = f"\n\n<!-- Pulled from {harness} by HarnessSync ({timestamp}) -->\n"
    section_footer = f"\n<!-- End pull from {harness} -->\n"
    rule_lines = "\n".join(f"- {r}" for r in accepted)

    try:
        existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
        claude_md.write_text(
            existing + section_header + rule_lines + section_footer,
            encoding="utf-8",
        )
        messages.append(f"\nAdded {len(accepted)} rule(s) to {claude_md}.")
    except OSError as e:
        messages.append(f"Error writing {claude_md}: {e}")

    return messages


def reconcile_drift(
    harness: str,
    project_dir: Path,
    file_path: Path | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Surface a drift report and offer to pull target-only sections into CLAUDE.md.

    Args:
        harness: Target harness to reconcile with.
        project_dir: Project root directory.
        file_path: Specific target file (auto-detected if None).
        dry_run: If True, report but don't write any changes.

    Returns:
        List of formatted message strings.
    """
    drift = detect_drift(harness, project_dir, file_path)

    if "error" in drift:
        return [f"Error: {drift['error']}"]

    messages: list[str] = [
        f"\nBidirectional Drift Report: CLAUDE.md \u2194 {harness} ({drift['source_file']})",
        "=" * 60,
    ]

    if not drift["drift_detected"]:
        messages.append(f"\u2713 No drift detected. {drift['identical']} section(s) are in sync.")
        return messages

    if drift["source_only"]:
        messages.append(f"\n\u2192 {len(drift['source_only'])} section(s) only in CLAUDE.md (would NOT appear in {harness}):")
        for h in drift["source_only"]:
            messages.append(f"  \u00b7 {h}")

    if drift["target_only"]:
        messages.append(f"\n\u2190 {len(drift['target_only'])} section(s) only in {harness} (at risk of being overwritten):")
        for h in drift["target_only"]:
            messages.append(f"  \u00b7 {h}")
        if not dry_run:
            messages.append(f"\nPulling {len(drift['target_only'])} target-only section(s) into CLAUDE.md...")
            pull_results = pull_mode(harness, project_dir, file_path, dry_run=dry_run)
            messages.extend(pull_results)

    if drift["diverged"]:
        messages.append(f"\n\u2260 {len(drift['diverged'])} section(s) differ between CLAUDE.md and {harness}:")
        for item in drift["diverged"]:
            messages.append(f"  \u00b7 {item['heading']}")
            if item.get("diff"):
                diff_preview = "\n".join(item["diff"].splitlines()[:8])
                messages.append(f"    {diff_preview}")

    if dry_run:
        messages.append("\n[dry-run] No changes written.")
    else:
        messages.append(f"\nReconcile complete. Run /sync to propagate CLAUDE.md to {harness}.")

    return messages


def main() -> None:
    """Entry point for /sync-import command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-import",
        description="Import rules from another harness into CLAUDE.md",
    )
    parser.add_argument("--from", dest="harness",
                        choices=["cursor", "aider", "codex", "gemini", "windsurf", "opencode", "cline"],
                        required=True, help="Source harness to import from")
    parser.add_argument("--file", type=str, default=None,
                        help="Specific file to import (auto-detected if omitted)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview what would be added without writing")
    parser.add_argument("--pull-mode", action="store_true",
                        help="Bidirectional: find rules in target that don't exist in CLAUDE.md")
    parser.add_argument("--reconcile", action="store_true",
                        help="Bidirectional: detect drift between CLAUDE.md and target harness")
    parser.add_argument("--interactive", action="store_true",
                        help="With --pull-mode: ask before adding each proposed rule")
    parser.add_argument("--project-dir", type=str, default=None,
                        help="Project directory (default: cwd)")

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    file_path = Path(args.file) if args.file else None

    if getattr(args, "reconcile", False):
        results = reconcile_drift(
            harness=args.harness, project_dir=project_dir,
            file_path=file_path, dry_run=args.dry_run,
        )
    elif args.pull_mode:
        results = pull_mode(
            harness=args.harness, project_dir=project_dir,
            file_path=file_path, dry_run=args.dry_run,
            interactive=args.interactive,
        )
    else:
        results = import_from_harness(
            harness=args.harness, project_dir=project_dir,
            file_path=file_path, dry_run=args.dry_run,
        )

    for line in results:
        print(line)


if __name__ == "__main__":
    main()
