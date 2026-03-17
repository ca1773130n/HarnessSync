from __future__ import annotations

"""Rule Provenance Tracker — tag rules with origin, level, and last-modified.

Each rule in a synced config has a story: which CLAUDE.md it came from,
whether it's user-level or project-level, and when the source file was last
touched. Without provenance, conflicts in multi-account setups leave users
guessing which instance of a rule is authoritative.

This module extracts provenance metadata for every rule discovered by
SourceReader and attaches it so that /sync-diff and conflict resolution
can display "this rule came from ~/.claude/CLAUDE.md (user) on 2026-03-10"
rather than just showing a raw diff.

Usage::

    from src.rule_provenance_tracker import RuleProvenanceTracker

    tracker = RuleProvenanceTracker(project_dir=Path("."))
    records = tracker.extract(source_data)
    print(tracker.format_report(records))

    # Tag rules inline (adds HTML comments to CLAUDE.md content):
    tagged = tracker.tag_content(claude_md_content, source_file=Path("CLAUDE.md"))
"""

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RuleProvenance:
    """Provenance metadata for a single rule line or block."""

    rule_text: str          # The rule text (first 120 chars if long)
    source_file: str        # Relative path to the source CLAUDE.md
    scope: str              # "user" | "project" | "local" | "unknown"
    last_modified: str      # ISO date string from file mtime, or "" if unavailable
    line_number: int        # 1-based line number in source file, or 0 if unknown
    rule_hash: str          # Short SHA-1 of the rule text (for deduplication)
    is_section_header: bool = False  # True if this is a Markdown heading

    @property
    def short_text(self) -> str:
        """First line of the rule, truncated to 80 chars."""
        first = self.rule_text.split("\n")[0].strip()
        return first[:80] + ("…" if len(first) > 80 else "")


@dataclass
class ProvenanceReport:
    """Aggregated provenance for all rules in a source config."""

    records: list[RuleProvenance] = field(default_factory=list)

    # Counts
    @property
    def user_count(self) -> int:
        return sum(1 for r in self.records if r.scope == "user")

    @property
    def project_count(self) -> int:
        return sum(1 for r in self.records if r.scope == "project")

    @property
    def local_count(self) -> int:
        return sum(1 for r in self.records if r.scope == "local")

    def by_source(self) -> dict[str, list[RuleProvenance]]:
        """Group records by source file path."""
        out: dict[str, list[RuleProvenance]] = {}
        for r in self.records:
            out.setdefault(r.source_file, []).append(r)
        return out

    def find_duplicates(self) -> list[tuple[RuleProvenance, RuleProvenance]]:
        """Return pairs of rules with identical hashes (likely duplicates)."""
        seen: dict[str, RuleProvenance] = {}
        pairs: list[tuple[RuleProvenance, RuleProvenance]] = []
        for r in self.records:
            if r.rule_hash in seen:
                pairs.append((seen[r.rule_hash], r))
            else:
                seen[r.rule_hash] = r
        return pairs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SCOPE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[/\\]\.claude[/\\]CLAUDE\.md$", re.IGNORECASE), "user"),
    (re.compile(r"[/\\]\.claude[/\\]CLAUDE\.local\.md$", re.IGNORECASE), "local"),
    (re.compile(r"CLAUDE\.local\.md$", re.IGNORECASE), "local"),
    (re.compile(r"CLAUDE\.md$", re.IGNORECASE), "project"),
]


def _infer_scope(path_str: str) -> str:
    for pattern, scope in _SCOPE_PATTERNS:
        if pattern.search(path_str):
            # If the path contains home directory (~/.claude/), it's user scope
            home = str(Path.home())
            if scope == "project" and (home in path_str):
                return "user"
            return scope
    return "unknown"


def _rule_hash(text: str) -> str:
    """Short 8-char SHA-1 of normalized rule text."""
    normalized = " ".join(text.lower().split())
    return hashlib.sha1(normalized.encode("utf-8", errors="replace")).hexdigest()[:8]


def _file_mtime(path: Path) -> str:
    """Return ISO date string for file mtime, or '' on error."""
    try:
        ts = path.stat().st_mtime
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except OSError:
        return ""


def _iter_rule_lines(content: str) -> Iterator[tuple[int, str]]:
    """Yield (1-based line number, stripped line) for non-blank, non-comment lines."""
    for i, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped and not stripped.startswith("<!--"):
            yield i, stripped


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class RuleProvenanceTracker:
    """Extract and report provenance metadata for all rules in a config.

    Args:
        project_dir: The project root directory.
        cc_home:     Claude Code home directory (defaults to ~/.claude).
    """

    # Inline provenance tag injected into CLAUDE.md content
    _TAG_RE = re.compile(r"<!--\s*provenance:[^>]+?-->", re.IGNORECASE)
    _TAG_TEMPLATE = "<!-- provenance: source={source} scope={scope} modified={modified} -->"

    def __init__(
        self,
        project_dir: Path | None = None,
        cc_home: Path | None = None,
    ) -> None:
        self.project_dir = project_dir or Path.cwd()
        self.cc_home = cc_home or Path.home() / ".claude"

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def extract(self, source_data: dict) -> ProvenanceReport:
        """Build a ProvenanceReport from SourceReader output.

        Args:
            source_data: Dict from SourceReader.discover_all().

        Returns:
            ProvenanceReport with one RuleProvenance per rule file/entry.
        """
        records: list[RuleProvenance] = []
        rules: dict = source_data.get("rules", {})

        for path_str, content in rules.items():
            if not isinstance(content, str):
                continue
            source_path = Path(path_str) if path_str else self.project_dir / "CLAUDE.md"
            scope = _infer_scope(str(source_path))
            mtime = _file_mtime(source_path)
            rel_path = _rel(source_path, self.project_dir)

            for lineno, line in _iter_rule_lines(content):
                is_header = line.startswith("#")
                records.append(RuleProvenance(
                    rule_text=line,
                    source_file=rel_path,
                    scope=scope,
                    last_modified=mtime,
                    line_number=lineno,
                    rule_hash=_rule_hash(line),
                    is_section_header=is_header,
                ))

        return ProvenanceReport(records=records)

    def format_report(self, report: ProvenanceReport, show_all: bool = False) -> str:
        """Format provenance report as a human-readable string.

        Args:
            report:   Output from extract().
            show_all: If False, show only a summary per source file.

        Returns:
            Multi-line string.
        """
        if not report.records:
            return "Rule Provenance: No rules found in source config."

        lines = [
            "Rule Provenance Report",
            "=" * 50,
            f"  Total rules: {len(report.records)} "
            f"(user: {report.user_count}, project: {report.project_count}, "
            f"local: {report.local_count})",
            "",
        ]

        for source_file, recs in sorted(report.by_source().items()):
            scope = recs[0].scope if recs else "unknown"
            mtime = recs[0].last_modified if recs else ""
            mtime_str = f"  last-modified: {mtime}" if mtime else ""
            lines.append(f"  [{scope.upper()}] {source_file}{mtime_str}")
            lines.append(f"    {len(recs)} rule(s)")
            if show_all:
                for r in recs[:10]:
                    lines.append(f"      L{r.line_number:4d}  {r.short_text}")
                if len(recs) > 10:
                    lines.append(f"      … and {len(recs) - 10} more")
            lines.append("")

        # Duplicate detection
        dupes = report.find_duplicates()
        if dupes:
            lines.append(f"  Duplicate rules detected: {len(dupes)} pair(s)")
            for a, b in dupes[:5]:
                lines.append(f"    '{a.short_text}'")
                lines.append(f"      → in {a.source_file}:L{a.line_number}")
                lines.append(f"      → in {b.source_file}:L{b.line_number}")
            if len(dupes) > 5:
                lines.append(f"    … and {len(dupes) - 5} more pairs")
            lines.append("")

        lines.append(
            "Run /sync-diff to see provenance inline in the conflict view."
        )
        return "\n".join(lines)

    def tag_content(self, content: str, source_file: Path) -> str:
        """Inject inline provenance tags after each rule block in CLAUDE.md.

        Tags are idempotent: existing tags are removed and re-inserted.
        The resulting content is safe to sync — tags are HTML comments.

        Args:
            content:     Raw CLAUDE.md content.
            source_file: Path to the source file (for scope inference).

        Returns:
            Content with provenance tags injected.
        """
        scope = _infer_scope(str(source_file))
        mtime = _file_mtime(source_file)
        rel = _rel(source_file, self.project_dir)

        # Strip existing provenance tags first
        content = self._TAG_RE.sub("", content)

        tag = self._TAG_TAG = self._TAG_TEMPLATE.format(
            source=rel, scope=scope, modified=mtime or "unknown"
        )

        # Inject tag after each H2 section header (## ...) for coarse provenance
        lines = content.splitlines(keepends=True)
        out: list[str] = []
        for line in lines:
            out.append(line)
            if line.startswith("## "):
                out.append(f"{tag}\n")

        return "".join(out)

    def extract_tag(self, line: str) -> dict | None:
        """Parse a provenance tag comment into a dict, or None if not a tag."""
        m = self._TAG_RE.search(line)
        if not m:
            return None
        inner = m.group(0)[4:-3].strip()  # strip <!-- and -->
        parts = {}
        for token in inner.split():
            if "=" in token:
                k, v = token.split("=", 1)
                parts[k] = v
        return parts if parts else None


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _rel(path: Path, base: Path) -> str:
    """Return path relative to base, or str(path) if not relative."""
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)
