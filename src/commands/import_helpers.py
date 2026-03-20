from __future__ import annotations

"""Helper functions for /sync-import: content cleaning, merging, drift detection.

Extracted from sync_import.py to keep the main command file focused on
the CLI entry point and high-level import/pull/reconcile flows.
"""

import difflib
import re
from pathlib import Path


# Managed section markers to skip when importing (these were written by HarnessSync)
_MANAGED_START = "<!-- Managed by HarnessSync -->"
_MANAGED_END = "<!-- End HarnessSync managed content -->"

# YAML frontmatter pattern for .mdc files
_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?---\s*\n", re.DOTALL)

# Auto-detect source files per harness
DEFAULT_FILES: dict[str, list[str]] = {
    "cursor":    [".cursor/rules/claude-code-rules.mdc", ".cursor/rules/*.mdc",
                  ".cursorrules"],
    "aider":     ["CONVENTIONS.md", ".aider.conf.yml"],
    "codex":     ["AGENTS.md"],
    "gemini":    ["GEMINI.md"],
    "windsurf":  [".windsurfrules"],
    "opencode":  ["AGENTS.md"],
    "cline":     [".cline/rules.md", ".clinerules"],
}

# CLAUDE.md import section header/footer
IMPORT_HEADER = "<!-- Imported from {harness} by HarnessSync ({timestamp}) -->"
IMPORT_FOOTER = "<!-- End import from {harness} -->"


def strip_managed_sections(content: str) -> str:
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


def strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter block from .mdc or markdown files."""
    return _FRONTMATTER_RE.sub("", content, count=1)


def strip_timestamp_comments(content: str) -> str:
    """Remove <!-- Last synced: ... --> lines inserted by HarnessSync."""
    return re.sub(r"<!--\s*Last synced:[^>]+-->\s*\n?", "", content)


def clean_import_content(content: str, source: str) -> str:
    """Strip all HarnessSync metadata from source content.

    Args:
        content: Raw content of the source file.
        source: Harness name for context-specific cleaning.

    Returns:
        Clean content ready to be merged into CLAUDE.md.
    """
    content = strip_managed_sections(content)
    content = strip_frontmatter(content)
    content = strip_timestamp_comments(content)
    content = content.strip()
    return content


def find_source_files(harness: str, project_dir: Path) -> list[Path]:
    """Auto-detect source files for the given harness.

    Args:
        harness: Source harness name.
        project_dir: Project root.

    Returns:
        List of existing file paths to import from.
    """
    patterns = DEFAULT_FILES.get(harness, [])
    found: list[Path] = []

    for pattern in patterns:
        if "*" in pattern:
            matches = sorted(project_dir.glob(pattern))
            found.extend(m for m in matches if m.is_file())
        else:
            p = project_dir / pattern
            if p.is_file():
                found.append(p)

    return found


def merge_into_claude_md(
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
    header = IMPORT_HEADER.format(harness=harness, timestamp=timestamp)
    footer = IMPORT_FOOTER.format(harness=harness)

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


def detect_drift(
    harness: str,
    project_dir: Path,
    file_path: Path | None = None,
) -> dict:
    """Detect drift between CLAUDE.md and a target harness config.

    Compares the content of CLAUDE.md against the target harness file to
    surface sections that exist in one but not the other, or sections that
    have diverged.

    Args:
        harness: Target harness to compare against.
        project_dir: Project root directory.
        file_path: Specific target file (auto-detected if None).

    Returns:
        Dict with keys: harness, source_file, source_only, target_only,
        diverged, identical, drift_detected.
    """
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

    source_files = [file_path] if file_path and file_path.is_file() else find_source_files(harness, project_dir)
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
    target_text = clean_import_content(
        target_path.read_text(encoding="utf-8", errors="replace"),
        harness,
    )

    # Remove HarnessSync-managed sections from CLAUDE.md before comparison
    managed_re = re.compile(
        r"<!-- Managed by HarnessSync -->.*?<!-- End HarnessSync managed content -->",
        re.DOTALL,
    )
    source_cleaned = managed_re.sub("", source_text)
    source_sections = _split_by_heading(source_cleaned)
    target_sections = _split_by_heading(target_text)

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
