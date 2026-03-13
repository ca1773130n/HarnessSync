from __future__ import annotations

"""Rule source attribution tracking for HarnessSync (item 26).

Tracks where each synced rule originated: which CLAUDE.md file, which line
number, and which section heading. Stores provenance in the sync state so
users can trace a synced rule back to its source quickly.

Attribution is embedded as comment metadata in target harness configs:
  <!-- hs-source: CLAUDE.md:42 -->
and stored in the state index for fast lookup.

Usage::

    from src.rule_source_attribution import RuleAttributor

    attributor = RuleAttributor(project_dir=Path("."))

    # Record attribution while processing source rules
    attributor.record("- Always use TypeScript", source_file="CLAUDE.md", line=42, section="Code Style")

    # Look up source for a synced rule fragment
    source = attributor.lookup("Always use TypeScript")
    if source:
        print(f"Rule from {source.source_file}:{source.line_number} ({source.section})")

    # Embed provenance comments in target file content
    annotated = attributor.annotate_content(rules_content, target="codex")
"""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path


# Comment marker prefix embedded in target configs
_ATTR_COMMENT_PREFIX = "<!-- hs-source:"
_ATTR_COMMENT_SUFFIX = "-->"

# Attribution index file (relative to project dir)
_ATTRIBUTION_INDEX_FILE = ".harness-sync/rule-attribution.json"


def _rule_fingerprint(content: str) -> str:
    """Short stable fingerprint for a rule fragment (first 80 chars normalised)."""
    normalized = re.sub(r"\s+", " ", content.strip())[:80].lower()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]


@dataclass
class RuleSource:
    """Source provenance for a single rule or rule block."""

    content_preview: str    # First 80 chars of the rule text
    source_file: str        # Relative path to source file (e.g. "CLAUDE.md")
    line_number: int        # 1-based line number in the source file
    section: str            # Nearest heading above the rule (e.g. "## Code Style")
    fingerprint: str        # Stable short hash for lookups

    def format(self) -> str:
        """Return a human-readable source reference."""
        return f"{self.source_file}:{self.line_number} [{self.section}]"

    def as_comment(self) -> str:
        """Return an HTML comment embedding the provenance."""
        return f"{_ATTR_COMMENT_PREFIX} {self.source_file}:{self.line_number} {_ATTR_COMMENT_SUFFIX}"


class RuleAttributor:
    """Records and queries rule source attribution.

    Args:
        project_dir: Project root directory. Attribution index is stored
                     relative to this directory.
    """

    def __init__(self, project_dir: Path | None = None):
        self._project_dir = project_dir or Path.cwd()
        self._index: dict[str, dict] = {}   # fingerprint -> attribution dict
        self._load_index()

    # ── Index I/O ─────────────────────────────────────────────────────────

    def _index_path(self) -> Path:
        return self._project_dir / _ATTRIBUTION_INDEX_FILE

    def _load_index(self) -> None:
        """Load attribution index from disk (silently ignores missing files)."""
        idx_path = self._index_path()
        if idx_path.is_file():
            try:
                self._index = json.loads(idx_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self._index = {}

    def save_index(self) -> None:
        """Persist attribution index to disk."""
        idx_path = self._index_path()
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        idx_path.write_text(json.dumps(self._index, indent=2) + "\n", encoding="utf-8")

    # ── Recording ─────────────────────────────────────────────────────────

    def record(
        self,
        content: str,
        source_file: str,
        line_number: int,
        section: str = "",
    ) -> RuleSource:
        """Record attribution for a rule fragment.

        Args:
            content: The rule text (used for fingerprinting).
            source_file: Relative path to source file.
            line_number: 1-based line number.
            section: Nearest section heading (e.g. "## Code Style").

        Returns:
            RuleSource with provenance data.
        """
        fp = _rule_fingerprint(content)
        preview = re.sub(r"\s+", " ", content.strip())[:80]

        source = RuleSource(
            content_preview=preview,
            source_file=source_file,
            line_number=line_number,
            section=section,
            fingerprint=fp,
        )
        self._index[fp] = asdict(source)
        return source

    def record_from_file(self, source_file: Path, relative_to: Path | None = None) -> int:
        """Parse a CLAUDE.md file and record attribution for all rule lines.

        Scans for Markdown list items (lines starting with ``-``) and heading
        context. Records each rule with its line number and nearest heading.

        Args:
            source_file: Path to the source CLAUDE.md file.
            relative_to: Base directory for computing relative source paths.
                         Defaults to self._project_dir.

        Returns:
            Number of rules recorded.
        """
        base = relative_to or self._project_dir
        try:
            rel_path = str(source_file.relative_to(base))
        except ValueError:
            rel_path = source_file.name

        try:
            text = source_file.read_text(encoding="utf-8")
        except OSError:
            return 0

        lines = text.splitlines()
        current_section = ""
        count = 0

        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            # Track heading context
            if stripped.startswith("#"):
                current_section = stripped.lstrip("#").strip()
                continue
            # Record list items and non-empty content lines
            if stripped.startswith("-") or (stripped and not stripped.startswith("#")):
                if len(stripped) >= 10:  # Skip very short lines
                    self.record(stripped, rel_path, i, current_section)
                    count += 1

        return count

    # ── Lookup ────────────────────────────────────────────────────────────

    def lookup(self, content: str) -> RuleSource | None:
        """Look up the source attribution for a rule by its content.

        Args:
            content: Rule text to look up.

        Returns:
            RuleSource if found, None otherwise.
        """
        fp = _rule_fingerprint(content)
        entry = self._index.get(fp)
        if not entry:
            return None
        try:
            return RuleSource(**entry)
        except (TypeError, KeyError):
            return None

    def lookup_by_fingerprint(self, fingerprint: str) -> RuleSource | None:
        """Look up attribution by exact fingerprint string."""
        entry = self._index.get(fingerprint)
        if not entry:
            return None
        try:
            return RuleSource(**entry)
        except (TypeError, KeyError):
            return None

    # ── Annotation ────────────────────────────────────────────────────────

    def annotate_content(self, content: str, target: str = "") -> str:
        """Embed source attribution comments into rules content.

        Inserts ``<!-- hs-source: FILE:LINE -->`` comments after each list
        item line whose attribution is known. Supported in HTML-comment-capable
        targets (markdown-based configs). Skipped for TOML/YAML targets.

        Args:
            content: Raw rules content string.
            target: Target harness name (used to skip non-markdown targets).

        Returns:
            Content with attribution comments injected after known rule lines.
        """
        _NO_COMMENT_TARGETS = {"codex", "aider"}  # Non-markdown config formats
        if target in _NO_COMMENT_TARGETS:
            return content

        lines = content.splitlines(keepends=True)
        result: list[str] = []

        for line in lines:
            result.append(line)
            stripped = line.strip()
            if stripped.startswith("-") and len(stripped) >= 10:
                source = self.lookup(stripped)
                if source:
                    indent = len(line) - len(line.lstrip())
                    comment = " " * indent + source.as_comment() + "\n"
                    result.append(comment)

        return "".join(result)

    def strip_attribution_comments(self, content: str) -> str:
        """Remove embedded attribution comments from content.

        Useful when reading back target files to avoid double-annotating.

        Args:
            content: Content that may contain attribution comments.

        Returns:
            Content with attribution comments removed.
        """
        comment_re = re.compile(
            r"^\s*<!--\s*hs-source:\s*[^\s>]+:\d+\s*-->\s*\n?",
            re.MULTILINE,
        )
        return comment_re.sub("", content)

    # ── Report ────────────────────────────────────────────────────────────

    def format_attribution_report(self, max_entries: int = 20) -> str:
        """Format a human-readable report of tracked rule sources.

        Args:
            max_entries: Maximum number of entries to include.

        Returns:
            Formatted report string.
        """
        if not self._index:
            return "No rule attribution data recorded. Run /sync to populate."

        lines = ["## Rule Source Attribution", ""]
        entries = list(self._index.values())[:max_entries]

        # Group by source file
        by_file: dict[str, list[dict]] = {}
        for entry in entries:
            sf = entry.get("source_file", "unknown")
            by_file.setdefault(sf, []).append(entry)

        for source_file, file_entries in sorted(by_file.items()):
            lines.append(f"### {source_file} ({len(file_entries)} rules)")
            for entry in sorted(file_entries, key=lambda e: e.get("line_number", 0)):
                line_no = entry.get("line_number", "?")
                section = entry.get("section", "")
                preview = entry.get("content_preview", "")[:60]
                section_str = f" [{section}]" if section else ""
                lines.append(f"  L{line_no}{section_str}: {preview}")
            lines.append("")

        if len(self._index) > max_entries:
            remaining = len(self._index) - max_entries
            lines.append(f"  ... and {remaining} more. Run with larger max_entries to see all.")

        return "\n".join(lines)

    def get_all_sources(self) -> list[RuleSource]:
        """Return all recorded rule sources.

        Returns:
            List of RuleSource objects sorted by source_file and line_number.
        """
        sources = []
        for entry in self._index.values():
            try:
                sources.append(RuleSource(**entry))
            except (TypeError, KeyError):
                continue
        return sorted(sources, key=lambda s: (s.source_file, s.line_number))

    @property
    def rule_count(self) -> int:
        """Number of rules currently tracked."""
        return len(self._index)


def extract_rule_sources(
    source_files: list[Path],
    project_dir: Path | None = None,
) -> RuleAttributor:
    """Convenience: scan multiple source files and return a populated RuleAttributor.

    Args:
        source_files: List of CLAUDE.md-like files to scan.
        project_dir: Base directory for relative path computation.

    Returns:
        RuleAttributor with all rules from the given files recorded.
    """
    attributor = RuleAttributor(project_dir=project_dir or Path.cwd())
    for path in source_files:
        if path.is_file():
            attributor.record_from_file(path)
    return attributor
