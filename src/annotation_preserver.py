from __future__ import annotations

"""Harness annotation preservation for HarnessSync re-syncs.

When re-syncing, detects and preserves user annotations or comments added
directly to target harness files (e.g., notes added to Cursor .mdc files
or Aider CONVENTIONS.md) by extracting non-managed content and merging it
back after the sync overwrites the file.

Users who add contextual notes in their other tools lose them every time
HarnessSync runs. This module prevents that by extracting unmanaged content
before sync and re-injecting it afterward.

Annotation extraction strategy:
- Content OUTSIDE HarnessSync managed markers is "user annotations".
- Lines before the first marker are prepended back to the synced file.
- Lines after the last marker are appended back to the synced file.
- Free-standing comment blocks interspersed within managed content are
  best-effort preserved by scanning for "## User Notes" sections.

Managed marker pattern (all adapters):
  <!-- Managed by HarnessSync -->
  ... synced content ...
  <!-- End HarnessSync managed content -->
"""

import re
from dataclasses import dataclass
from pathlib import Path


# HarnessSync managed block markers (must match adapters exactly)
MANAGED_START = "<!-- Managed by HarnessSync -->"
MANAGED_END = "<!-- End HarnessSync managed content -->"

# Pattern for detecting user annotation sections
_USER_ANNOTATION_SECTION_RE = re.compile(
    r"##\s+(?:User Notes?|My Notes?|Local Notes?|Personal Notes?|Annotations?)",
    re.IGNORECASE,
)


@dataclass
class FileAnnotations:
    """User annotations extracted from a target harness file.

    Stores content that appears before and after the HarnessSync managed block,
    plus any free-standing annotation sections found within the file.

    These annotations are re-injected after each sync to prevent data loss.
    """

    file_path: str
    preamble: str         # Content before first managed block
    postamble: str        # Content after last managed block
    annotation_sections: list[str]  # Freestanding "## User Notes" sections


def extract_annotations(file_path: Path) -> FileAnnotations | None:
    """Extract user annotations from a target harness file.

    Reads the file and separates content into:
    - preamble: lines before the first managed block
    - postamble: lines after the last managed block
    - annotation_sections: free-standing user note sections

    Returns None if the file doesn't exist or has no managed content.

    Args:
        file_path: Path to target harness file.

    Returns:
        FileAnnotations if managed markers found, None otherwise.
    """
    if not file_path.is_file():
        return None

    try:
        content = file_path.read_text(encoding="utf-8")
    except OSError:
        return None

    if MANAGED_START not in content:
        # File has no HarnessSync content — no annotations to preserve separately
        return None

    lines = content.splitlines(keepends=True)

    preamble_lines: list[str] = []
    postamble_lines: list[str] = []
    annotation_sections: list[str] = []

    # State machine: before / inside / after managed block
    state = "before"
    first_managed_seen = False
    annotation_buffer: list[str] = []
    in_annotation = False

    for line in lines:
        stripped = line.strip()

        if stripped == MANAGED_START:
            if not first_managed_seen:
                first_managed_seen = True
            state = "inside"
            if annotation_buffer:
                annotation_sections.append("".join(annotation_buffer))
                annotation_buffer = []
            in_annotation = False
            continue

        if stripped == MANAGED_END:
            state = "after_managed"
            continue

        if state == "before":
            preamble_lines.append(line)

        elif state == "after_managed":
            # Content after managed block — could be more managed blocks or user content
            if stripped.startswith("<!-- Managed by HarnessSync"):
                state = "inside"
                continue
            postamble_lines.append(line)

            # Detect annotation sections in postamble
            if _USER_ANNOTATION_SECTION_RE.match(stripped):
                in_annotation = True
                annotation_buffer = [line]
            elif in_annotation:
                if stripped.startswith("##") and not _USER_ANNOTATION_SECTION_RE.match(stripped):
                    # End of annotation section
                    annotation_sections.append("".join(annotation_buffer))
                    annotation_buffer = []
                    in_annotation = False
                else:
                    annotation_buffer.append(line)

    if annotation_buffer:
        annotation_sections.append("".join(annotation_buffer))

    preamble = "".join(preamble_lines).rstrip()
    postamble = "".join(postamble_lines).rstrip()

    # Only return annotations if there's something worth preserving
    if not preamble and not postamble and not annotation_sections:
        return None

    return FileAnnotations(
        file_path=str(file_path),
        preamble=preamble,
        postamble=postamble,
        annotation_sections=annotation_sections,
    )


def restore_annotations(
    file_path: Path,
    annotations: FileAnnotations,
) -> bool:
    """Re-inject user annotations into a target file after sync.

    Reads the freshly-synced file and:
    1. Prepends the preamble (if non-empty) before the managed block.
    2. Appends the postamble (if non-empty) after the managed block.

    The managed block itself is left untouched — only the surrounding
    user content is re-inserted.

    Args:
        file_path: Target file that was just synced.
        annotations: Annotations extracted before the sync.

    Returns:
        True if annotations were restored, False if nothing to restore.
    """
    if not file_path.is_file():
        return False

    if not annotations.preamble and not annotations.postamble:
        return False

    try:
        synced_content = file_path.read_text(encoding="utf-8")
    except OSError:
        return False

    parts: list[str] = []

    if annotations.preamble:
        parts.append(annotations.preamble)
        parts.append("\n\n")

    parts.append(synced_content.rstrip())

    if annotations.postamble:
        parts.append("\n\n")
        parts.append("<!-- User annotations (preserved by HarnessSync) -->")
        parts.append("\n\n")
        parts.append(annotations.postamble)

    restored = "".join(parts) + "\n"

    try:
        file_path.write_text(restored, encoding="utf-8")
        return True
    except OSError:
        return False


def get_target_file_paths(target: str, project_dir: Path) -> list[Path]:
    """Return the primary config file paths for a target harness.

    These are the files HarnessSync writes to and therefore the ones
    where user annotations need preservation.

    Args:
        target: Target harness name.
        project_dir: Project root directory.

    Returns:
        List of file paths to check for user annotations.
    """
    mapping: dict[str, list[str]] = {
        "codex":    ["AGENTS.md"],
        "gemini":   ["GEMINI.md"],
        "opencode": ["AGENTS.md"],
        "cursor":   [".cursor/rules/claude-code-rules.mdc"],
        "aider":    ["CONVENTIONS.md"],
        "windsurf": [".windsurfrules"],
    }
    paths = [project_dir / p for p in mapping.get(target, [])]
    return [p for p in paths if p.exists()]


class AnnotationPreserver:
    """Coordinates annotation extraction and restoration around sync operations.

    Usage pattern:
        preserver = AnnotationPreserver(project_dir)
        captured = preserver.capture_all()      # before sync
        # ... run sync ...
        preserver.restore_all(captured)         # after sync
    """

    def __init__(self, project_dir: Path):
        """Initialize.

        Args:
            project_dir: Project root directory.
        """
        self.project_dir = project_dir

    def capture_all(self, targets: list[str] | None = None) -> dict[str, list[FileAnnotations]]:
        """Extract annotations from all target harness files before sync.

        Args:
            targets: List of targets to check (default: all known targets).

        Returns:
            Dict mapping target_name -> list of FileAnnotations.
        """
        if targets is None:
            targets = ["codex", "gemini", "opencode", "cursor", "aider", "windsurf"]

        captured: dict[str, list[FileAnnotations]] = {}

        for target in targets:
            file_paths = get_target_file_paths(target, self.project_dir)
            target_annotations: list[FileAnnotations] = []

            for fpath in file_paths:
                ann = extract_annotations(fpath)
                if ann:
                    target_annotations.append(ann)

            if target_annotations:
                captured[target] = target_annotations

        return captured

    def restore_all(
        self,
        captured: dict[str, list[FileAnnotations]],
    ) -> dict[str, int]:
        """Re-inject captured annotations after sync.

        Args:
            captured: Output of capture_all().

        Returns:
            Dict mapping target_name -> number of files with annotations restored.
        """
        restored: dict[str, int] = {}

        for target, annotations_list in captured.items():
            count = 0
            for ann in annotations_list:
                file_path = Path(ann.file_path)
                if restore_annotations(file_path, ann):
                    count += 1
            if count:
                restored[target] = count

        return restored


# ---------------------------------------------------------------------------
# Rule Provenance Tracking (Item 13)
# ---------------------------------------------------------------------------
#
# Embeds a provenance comment into each synced rule block so that developers
# who open AGENTS.md / GEMINI.md / etc. can see exactly which source section
# produced each rule and when it was last synced.
#
# Format (HTML comment, invisible in rendered Markdown):
#   <!-- hs:provenance source="CLAUDE.md §Rules" synced="2026-03-11" -->
#
# The comment is injected immediately after the HarnessSync managed-block
# opening marker so it appears at the top of every synced section.

_PROVENANCE_RE = re.compile(
    r"<!--\s*hs:provenance[^>]*-->",
    re.IGNORECASE,
)


def build_provenance_comment(
    source_file: str,
    section: str | None = None,
    sync_date: str | None = None,
) -> str:
    """Build a provenance HTML comment for embedding in synced content.

    Args:
        source_file: Basename of the source file (e.g. "CLAUDE.md").
        section: Optional section heading or identifier (e.g. "§Rules").
        sync_date: ISO date string (defaults to today: YYYY-MM-DD).

    Returns:
        Single-line HTML comment string ending with newline.
    """
    from datetime import date as _date

    date_str = sync_date or _date.today().isoformat()
    src = source_file
    if section:
        src = f"{source_file} {section}"
    return f'<!-- hs:provenance source="{src}" synced="{date_str}" -->\n'


def inject_provenance(
    content: str,
    source_file: str,
    section: str | None = None,
    sync_date: str | None = None,
) -> str:
    """Inject or update a provenance comment into synced managed content.

    Inserts the provenance comment immediately after the HarnessSync managed-
    block opening marker (``<!-- Managed by HarnessSync -->``). If a
    provenance comment already exists it is updated in-place, so repeated
    syncs don't accumulate duplicate comments.

    Args:
        content: Full text of the target harness file.
        source_file: Basename of the source file (e.g. "CLAUDE.md").
        section: Optional section label (e.g. "§Rules").
        sync_date: Override date (defaults to today).

    Returns:
        Modified content string with provenance comment injected/updated.
        Returns original content unchanged if the managed-block marker is
        absent (non-managed files are not modified).
    """
    if MANAGED_START not in content:
        return content

    provenance = build_provenance_comment(source_file, section, sync_date)

    # Remove any existing provenance comments first (update-in-place)
    content = _PROVENANCE_RE.sub("", content)

    # Inject immediately after the opening managed marker line
    insert_after = MANAGED_START + "\n"
    if insert_after in content:
        content = content.replace(insert_after, insert_after + provenance, 1)
    else:
        # Fallback: marker without trailing newline
        content = content.replace(MANAGED_START, MANAGED_START + "\n" + provenance, 1)

    return content


def extract_provenance(content: str) -> dict | None:
    """Extract provenance metadata from a target harness file.

    Args:
        content: Full text of the target harness file.

    Returns:
        Dict with keys ``source`` and ``synced`` if a provenance comment is
        found, otherwise None.
    """
    m = re.search(
        r'<!--\s*hs:provenance\s+source="([^"]+)"\s+synced="([^"]+)"\s*-->',
        content,
        re.IGNORECASE,
    )
    if not m:
        return None
    return {"source": m.group(1), "synced": m.group(2)}


# ---------------------------------------------------------------------------
# Item 21 — Per-rule attribution and origin tracking
# ---------------------------------------------------------------------------

# Pattern for extracting individual rules from CLAUDE.md bullet lists
_RULE_LINE_RE = re.compile(r"^(\s*[-*+]\s+|\s*\d+\.\s+)(.+)$")

# Pattern for the per-rule attribution comment we inject
_RULE_ATTRIBUTION_RE = re.compile(
    r'\s*<!--\s*hs:rule\s+src="([^"]+)"\s+line="(\d+)"\s+modified="([^"]+)"\s*-->',
)


def build_rule_attribution(
    source_file: str,
    line_number: int,
    modified_date: str,
) -> str:
    """Build a per-rule attribution comment.

    Args:
        source_file: Basename of the source file (e.g. "CLAUDE.md").
        line_number: 1-based line number of the rule in the source file.
        modified_date: ISO date string (YYYY-MM-DD).

    Returns:
        An HTML comment suitable for embedding after an individual rule line.
    """
    return (
        f'<!-- hs:rule src="{source_file}" line="{line_number}" '
        f'modified="{modified_date}" -->'
    )


def annotate_rules_with_attribution(
    content: str,
    source_file: str,
    modified_date: str | None = None,
) -> str:
    """Annotate each rule line in content with its origin attribution.

    Adds a compact attribution comment after each bullet-point rule so that
    users reading translated harness files can trace any rule back to its
    source in CLAUDE.md.

    Attribution is appended as an inline HTML comment on the same line as
    the rule.  Existing attribution comments are updated in-place so that
    re-syncing does not accumulate duplicate comments.

    Example output::

        - Always use TypeScript <!-- hs:rule src="CLAUDE.md" line="42" modified="2026-03-13" -->
        - Prefer named exports  <!-- hs:rule src="CLAUDE.md" line="43" modified="2026-03-13" -->

    Args:
        content: CLAUDE.md or rules section text.
        source_file: Basename of the source file (e.g. "CLAUDE.md").
        modified_date: ISO date to stamp (default: today).

    Returns:
        Content with attribution comments added/updated on each rule line.
    """
    if modified_date is None:
        from datetime import date
        modified_date = date.today().isoformat()

    output_lines: list[str] = []
    for lineno, raw_line in enumerate(content.splitlines(), start=1):
        # Strip any existing attribution comment before re-adding
        clean_line = _RULE_ATTRIBUTION_RE.sub("", raw_line).rstrip()

        if _RULE_LINE_RE.match(clean_line):
            attribution = build_rule_attribution(source_file, lineno, modified_date)
            output_lines.append(f"{clean_line}  {attribution}")
        else:
            output_lines.append(raw_line)

    return "\n".join(output_lines)


def extract_rule_attributions(content: str) -> list[dict]:
    """Extract all per-rule attribution records from a harness file.

    Parses attribution comments embedded by annotate_rules_with_attribution()
    and returns a structured list.

    Args:
        content: Content of a synced harness file.

    Returns:
        List of dicts with keys: ``rule_text``, ``source_file``, ``line``, ``modified``.
    """
    records: list[dict] = []
    for raw_line in content.splitlines():
        attr_match = _RULE_ATTRIBUTION_RE.search(raw_line)
        if attr_match:
            rule_text = _RULE_ATTRIBUTION_RE.sub("", raw_line).strip()
            # Strip leading list marker
            rule_match = _RULE_LINE_RE.match(rule_text)
            if rule_match:
                rule_text = rule_match.group(2).strip()
            records.append({
                "rule_text": rule_text,
                "source_file": attr_match.group(1),
                "line": int(attr_match.group(2)),
                "modified": attr_match.group(3),
            })
    return records


def strip_rule_attributions(content: str) -> str:
    """Remove all per-rule attribution comments from content.

    Useful when preparing content for display or for harnesses where
    HTML comments are not supported.

    Args:
        content: Content with attribution comments.

    Returns:
        Content with attribution comments stripped.
    """
    return _RULE_ATTRIBUTION_RE.sub("", content)
