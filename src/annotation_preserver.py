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
