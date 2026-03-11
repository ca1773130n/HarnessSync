from __future__ import annotations

"""
/sync-import slash command implementation.

Reads an existing Cursor .mdc rules file or Aider CONVENTIONS.md and merges
its content into CLAUDE.md — the reverse of the normal sync direction.

Lets users who start in another tool migrate their existing configuration
into Claude Code without losing months of accumulated rules.

Bidirectional sync (item 1):
When another harness config has been edited directly, /sync-import --reconcile
detects the drift between CLAUDE.md and the target harness config and surfaces
a summary of sections that differ. This prevents silent data loss when target
configs get edited and then overwritten on the next /sync.

Usage:
    /sync-import --from cursor [--file PATH] [--dry-run]
    /sync-import --from aider [--file PATH] [--dry-run]
    /sync-import --from codex [--file PATH] [--dry-run]
    /sync-import --from gemini [--file PATH] [--dry-run]
    /sync-import --from codex --reconcile [--dry-run]
    /sync-import --from codex --pull-mode [--interactive]

Options:
    --from HARNESS    Source harness to import from (cursor/aider/codex/gemini)
    --file PATH       Specific file to import (auto-detected if omitted)
    --dry-run         Preview what would be added without writing
    --pull-mode       Find rules in target that don't exist in CLAUDE.md
    --reconcile       Detect drift and show a diff (bidirectional sync mode)
    --interactive     With --pull-mode: ask before adding each proposed rule
    --project-dir     Project directory (default: cwd)
"""

import os
import re
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)


# Managed section markers to skip when importing (these were written by HarnessSync)
_MANAGED_START = "<!-- Managed by HarnessSync -->"
_MANAGED_END = "<!-- End HarnessSync managed content -->"

# YAML frontmatter pattern for .mdc files
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?---\s*\n", re.DOTALL)

# Auto-detect source files per harness
_DEFAULT_FILES: dict[str, list[str]] = {
    "cursor": [".cursor/rules/claude-code-rules.mdc", ".cursor/rules/*.mdc"],
    "aider":  ["CONVENTIONS.md"],
    "codex":  ["AGENTS.md"],
    "gemini": ["GEMINI.md"],
}

# CLAUDE.md import section header/footer
_IMPORT_HEADER = "<!-- Imported from {harness} by HarnessSync ({timestamp}) -->"
_IMPORT_FOOTER = "<!-- End import from {harness} -->"


def _strip_managed_sections(content: str) -> str:
    """Remove HarnessSync-managed blocks from content.

    Strips everything between <!-- Managed by HarnessSync --> and
    <!-- End HarnessSync managed content --> markers, including the markers.
    """
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    in_managed = False

    for line in lines:
        stripped = line.strip()
        if stripped == _MANAGED_START:
            in_managed = True
            continue
        if stripped == _MANAGED_END:
            in_managed = False
            continue
        if not in_managed:
            out.append(line)

    return "".join(out)


def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter block from .mdc or markdown files."""
    return _FRONTMATTER_RE.sub("", content, count=1)


def _strip_timestamp_comments(content: str) -> str:
    """Remove <!-- Last synced: ... --> lines inserted by HarnessSync."""
    return re.sub(r"<!--\s*Last synced:[^>]+-->\s*\n?", "", content)


def _clean_import_content(content: str, source: str) -> str:
    """Strip all HarnessSync metadata from source content.

    Args:
        content: Raw content of the source file.
        source: Harness name for context-specific cleaning.

    Returns:
        Clean content ready to be merged into CLAUDE.md.
    """
    content = _strip_managed_sections(content)
    content = _strip_frontmatter(content)
    content = _strip_timestamp_comments(content)
    content = content.strip()
    return content


def _find_source_files(harness: str, project_dir: Path) -> list[Path]:
    """Auto-detect source files for the given harness.

    Args:
        harness: Source harness name.
        project_dir: Project root.

    Returns:
        List of existing file paths to import from.
    """
    patterns = _DEFAULT_FILES.get(harness, [])
    found: list[Path] = []

    for pattern in patterns:
        if "*" in pattern:
            # Glob pattern
            matches = sorted(project_dir.glob(pattern))
            found.extend(m for m in matches if m.is_file())
        else:
            p = project_dir / pattern
            if p.is_file():
                found.append(p)

    return found


def _already_imported(claude_md: str, section_header: str) -> bool:
    """Check if content was already imported (avoid duplicates)."""
    # Strip dynamic timestamp for comparison — check harness name only
    harness_pattern = re.sub(r"\{[^}]+\}", ".*", re.escape(section_header))
    return bool(re.search(harness_pattern, claude_md))


def _merge_into_claude_md(
    claude_md_path: Path,
    import_content: str,
    harness: str,
    dry_run: bool,
) -> tuple[str, bool]:
    """Merge imported content into CLAUDE.md.

    Appends a clearly labelled section to CLAUDE.md with the imported rules.
    Skips if content is empty after cleaning.

    Args:
        claude_md_path: Path to CLAUDE.md (created if missing).
        import_content: Cleaned content to merge.
        harness: Source harness name (for labelling).
        dry_run: If True, preview without writing.

    Returns:
        (result_message, changed) tuple.
    """
    from datetime import datetime

    if not import_content.strip():
        return "No content to import after stripping managed sections.", False

    existing = ""
    if claude_md_path.exists():
        existing = claude_md_path.read_text(encoding="utf-8")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = _IMPORT_HEADER.format(harness=harness, timestamp=timestamp)
    footer = _IMPORT_FOOTER.format(harness=harness)

    # Build the import block
    import_block = f"\n\n{header}\n\n{import_content}\n\n{footer}\n"

    new_content = existing.rstrip() + import_block

    if dry_run:
        lines_added = import_content.count("\n") + 1
        return (
            f"[dry-run] Would append {lines_added} lines to {claude_md_path}:\n\n"
            f"{header}\n\n{import_content[:500]}{'...' if len(import_content) > 500 else ''}\n\n{footer}",
            True,
        )

    claude_md_path.write_text(new_content, encoding="utf-8")
    lines_added = import_content.count("\n") + 1
    return f"Merged {lines_added} lines into {claude_md_path}", True


def import_from_harness(
    harness: str,
    project_dir: Path,
    file_path: Path | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Import configuration from a target harness into CLAUDE.md.

    Args:
        harness: Source harness ("cursor", "aider", "codex", "gemini").
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
    but are absent from CLAUDE.md — candidate additions for bidirectional sync.

    Args:
        harness: Source harness to pull from.
        project_dir: Project root directory.
        file_path: Specific file to scan (auto-detected if None).

    Returns:
        List of dicts with keys:
          - rule: Rule text (stripped of bullet marker)
          - source_file: File it was found in
          - harness: Source harness name
    """
    import re

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
    """Bidirectional Sync Pull Mode — propose target-only rules as CLAUDE.md additions.

    Finds rules in the target harness that don't exist in CLAUDE.md and either
    shows them (dry_run / non-interactive) or asks the user to accept each one
    (interactive). Accepted rules are appended to CLAUDE.md under a labeled section.

    Args:
        harness: Target harness to pull from.
        project_dir: Project root directory.
        file_path: Specific file to scan (auto-detected if None).
        dry_run: If True, show proposals without writing.
        interactive: If True, ask the user to confirm each rule.

    Returns:
        List of result message strings.
    """
    import sys

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


def detect_drift(
    harness: str,
    project_dir: Path,
    file_path: Path | None = None,
) -> dict:
    """Detect drift between CLAUDE.md and a target harness config (item 1).

    Compares the content of CLAUDE.md against the target harness file to
    surface sections that exist in one but not the other, or sections that
    have diverged. This is the bidirectional drift detection that prevents
    silent data loss.

    Args:
        harness: Target harness to compare against.
        project_dir: Project root directory.
        file_path: Specific target file (auto-detected if None).

    Returns:
        Dict with keys:
            - harness: Harness name
            - source_file: Path to the target harness file checked
            - source_only: Sections only in CLAUDE.md (would be lost on next pull)
            - target_only: Sections only in the target (would be overwritten on sync)
            - diverged: Sections present in both but with different content
            - identical: Count of sections that match
            - drift_detected: True if any difference found
    """
    import difflib

    _SECTION_RE = re.compile(r"^#{1,3}\s+(.+?)(?:\s+#+)?$", re.MULTILINE)

    def _split_by_heading(text: str) -> dict[str, str]:
        matches = list(_SECTION_RE.finditer(text))
        sections: dict[str, str] = {}
        for i, m in enumerate(matches):
            heading = m.group(0).strip()
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections[heading] = text[start:end].strip()
        return sections

    claude_md = project_dir / "CLAUDE.md"
    source_text = ""
    if claude_md.exists():
        source_text = claude_md.read_text(encoding="utf-8", errors="replace")

    # Find target file
    source_files = [file_path] if file_path and file_path.is_file() else _find_source_files(harness, project_dir)
    if not source_files:
        return {
            "harness": harness,
            "source_file": None,
            "source_only": [],
            "target_only": [],
            "diverged": [],
            "identical": 0,
            "drift_detected": False,
            "error": f"No {harness} config file found",
        }

    target_path = source_files[0]
    target_text = _clean_import_content(
        target_path.read_text(encoding="utf-8", errors="replace"),
        harness,
    )

    source_sections = _split_by_heading(source_text)
    target_sections = _split_by_heading(target_text)

    # Remove HarnessSync-managed sections from CLAUDE.md before comparison
    # (these were written by HarnessSync itself, not user content)
    managed_re = re.compile(
        r"<!-- Managed by HarnessSync -->.*?<!-- End HarnessSync managed content -->",
        re.DOTALL,
    )
    source_cleaned = managed_re.sub("", source_text)
    source_sections = _split_by_heading(source_cleaned)

    all_headings = set(source_sections) | set(target_sections)
    source_only: list[str] = []
    target_only: list[str] = []
    diverged: list[dict] = []
    identical = 0

    for heading in sorted(all_headings):
        in_source = heading in source_sections
        in_target = heading in target_sections

        if in_source and not in_target:
            source_only.append(heading)
        elif in_target and not in_source:
            target_only.append(heading)
        else:
            s_body = source_sections.get(heading, "")
            t_body = target_sections.get(heading, "")
            if s_body.strip() != t_body.strip():
                diff = "".join(difflib.unified_diff(
                    s_body.splitlines(keepends=True),
                    t_body.splitlines(keepends=True),
                    fromfile="CLAUDE.md",
                    tofile=target_path.name,
                    lineterm="\n",
                ))
                diverged.append({"heading": heading, "diff": diff[:1000]})
            else:
                identical += 1

    drift_detected = bool(source_only or target_only or diverged)
    return {
        "harness": harness,
        "source_file": str(target_path),
        "source_only": source_only,
        "target_only": target_only,
        "diverged": diverged,
        "identical": identical,
        "drift_detected": drift_detected,
    }


def reconcile_drift(
    harness: str,
    project_dir: Path,
    file_path: Path | None = None,
    dry_run: bool = False,
) -> list[str]:
    """Surface a drift report and offer to pull target-only sections into CLAUDE.md.

    This is the bidirectional reconciliation flow (item 1). It detects drift
    between CLAUDE.md and the target harness config and reports what's different,
    preventing the silent data-loss scenario where a user edits AGENTS.md directly
    and then runs /sync which overwrites their changes.

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
        f"\nBidirectional Drift Report: CLAUDE.md ↔ {harness} ({drift['source_file']})",
        "=" * 60,
    ]

    if not drift["drift_detected"]:
        messages.append(f"✓ No drift detected. {drift['identical']} section(s) are in sync.")
        return messages

    if drift["source_only"]:
        messages.append(f"\n→ {len(drift['source_only'])} section(s) only in CLAUDE.md (would NOT appear in {harness}):")
        for h in drift["source_only"]:
            messages.append(f"  · {h}")

    if drift["target_only"]:
        messages.append(f"\n← {len(drift['target_only'])} section(s) only in {harness} (at risk of being overwritten):")
        for h in drift["target_only"]:
            messages.append(f"  · {h}")
        if not dry_run:
            # Pull target-only sections into CLAUDE.md
            messages.append(f"\nPulling {len(drift['target_only'])} target-only section(s) into CLAUDE.md...")
            pull_results = pull_mode(harness, project_dir, file_path, dry_run=dry_run)
            messages.extend(pull_results)

    if drift["diverged"]:
        messages.append(f"\n≠ {len(drift['diverged'])} section(s) differ between CLAUDE.md and {harness}:")
        for item in drift["diverged"]:
            messages.append(f"  · {item['heading']}")
            if item.get("diff"):
                # Show first few lines of diff
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
    parser.add_argument(
        "--from",
        dest="harness",
        choices=["cursor", "aider", "codex", "gemini"],
        required=True,
        help="Source harness to import from",
    )
    parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Specific file to import (auto-detected if omitted)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be added without writing",
    )
    parser.add_argument(
        "--pull-mode",
        action="store_true",
        help="Bidirectional: find rules in target that don't exist in CLAUDE.md",
    )
    parser.add_argument(
        "--reconcile",
        action="store_true",
        help="Bidirectional: detect drift between CLAUDE.md and target harness, "
             "then offer to pull target-only sections back into CLAUDE.md",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="With --pull-mode: ask before adding each proposed rule",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        help="Project directory (default: cwd)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    file_path = Path(args.file) if args.file else None

    if getattr(args, "reconcile", False):
        results = reconcile_drift(
            harness=args.harness,
            project_dir=project_dir,
            file_path=file_path,
            dry_run=args.dry_run,
        )
    elif args.pull_mode:
        results = pull_mode(
            harness=args.harness,
            project_dir=project_dir,
            file_path=file_path,
            dry_run=args.dry_run,
            interactive=args.interactive,
        )
    else:
        results = import_from_harness(
            harness=args.harness,
            project_dir=project_dir,
            file_path=file_path,
            dry_run=args.dry_run,
        )

    for line in results:
        print(line)


if __name__ == "__main__":
    main()
