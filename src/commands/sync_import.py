from __future__ import annotations

"""
/sync-import slash command implementation.

Reads an existing Cursor .mdc rules file or Aider CONVENTIONS.md and merges
its content into CLAUDE.md — the reverse of the normal sync direction.

Lets users who start in another tool migrate their existing configuration
into Claude Code without losing months of accumulated rules.

Usage:
    /sync-import --from cursor [--file PATH] [--dry-run]
    /sync-import --from aider [--file PATH] [--dry-run]
    /sync-import --from codex [--file PATH] [--dry-run]
    /sync-import --from gemini [--file PATH] [--dry-run]

Options:
    --from HARNESS    Source harness to import from (cursor/aider/codex/gemini)
    --file PATH       Specific file to import (auto-detected if omitted)
    --dry-run         Preview what would be added without writing
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
