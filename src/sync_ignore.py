from __future__ import annotations

"""
.syncignore support — gitignore-style exclusion patterns for sync operations.
Also provides inline <!-- sync:skip --> annotation parsing (item 27).

Reads a ``.syncignore`` file at project root and filters rules, skills,
commands, and agents from being synced.  Patterns follow gitignore semantics:

    # Comment
    experimental-*          # skip rules/skills whose name matches
    @skip-all               # literal name match
    *.draft                 # glob matching on rule path basename
    /absolute-prefix        # anchored to repo root (leading slash stripped)

Entries in ``.syncignore`` are matched against:
- Rule content paths (relative, e.g. "CLAUDE.md", ".claude/rules/foo.md")
- Rule section headings (extracted from the content)
- Skill names (directory names under .claude/skills/)
- Agent names
- Command names

Integration:
    from src.sync_ignore import SyncIgnore

    ignore = SyncIgnore.load(project_dir)

    # Filter a list of rule dicts
    rules = ignore.filter_rules(rules)

    # Filter a skills dict
    skills = ignore.filter_skills(skills)

    # Check a single name
    if ignore.should_skip("experimental-feature"):
        ...
"""

import fnmatch
import re
from pathlib import Path


SYNCIGNORE_FILE = ".syncignore"

# ---------------------------------------------------------------------------
# Item 27 — Inline sync:skip annotation support
# ---------------------------------------------------------------------------

# Matches <!-- sync:skip --> (skip for all targets)
_SKIP_ALL_RE = re.compile(
    r"<!--\s*sync:skip\s*-->",
    re.IGNORECASE,
)

# Matches <!-- sync:skip target=codex,gemini --> (skip for specific targets)
_SKIP_TARGET_RE = re.compile(
    r"<!--\s*sync:skip\s+target=([a-zA-Z0-9_,\s-]+?)\s*-->",
    re.IGNORECASE,
)

# Matches <!-- sync:only target=codex,gemini --> (sync to specific targets only)
_ONLY_TARGET_RE = re.compile(
    r"<!--\s*sync:only\s+target=([a-zA-Z0-9_,\s-]+?)\s*-->",
    re.IGNORECASE,
)


def strip_skip_annotations(content: str) -> str:
    """Remove all sync:skip and sync:only annotation comments from content.

    Useful when writing content to a target — the annotations themselves
    should not appear in the synced output.

    Args:
        content: Raw markdown content (e.g. CLAUDE.md).

    Returns:
        Content with all ``<!-- sync:... -->`` annotations removed.
    """
    content = _SKIP_ALL_RE.sub("", content)
    content = _SKIP_TARGET_RE.sub("", content)
    content = _ONLY_TARGET_RE.sub("", content)
    return content


def extract_skipped_sections(
    content: str,
    target: str | None = None,
) -> list[dict]:
    """Parse CLAUDE.md content and return sections marked as sync:skip.

    Sections are identified by their Markdown heading. A section is
    considered "skipped" when a ``<!-- sync:skip -->`` or target-specific
    ``<!-- sync:skip target=... -->`` annotation appears:

    - Immediately before the heading (on the preceding line), OR
    - Anywhere within the section's content block.

    The annotation is removed from the returned content so it doesn't
    bleed into target config files.

    Args:
        content: Raw CLAUDE.md (or any Markdown) content.
        target: Target harness name (e.g. "codex"). When provided,
                target-specific annotations are evaluated. Pass None to
                collect all annotated sections regardless of target.

    Returns:
        List of dicts with keys:
          - ``heading``: Section heading text (without ``#`` prefix).
          - ``level``: Heading level (1-6).
          - ``skipped_for``: ``"all"`` or list of target names.
          - ``content``: Section content (annotations stripped).
    """
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#+)?$", re.MULTILINE)

    sections: list[dict] = []
    lines = content.splitlines(keepends=True)
    n = len(lines)

    # Find all heading positions
    heading_positions: list[tuple[int, int, str]] = []  # (line_idx, level, text)
    for i, line in enumerate(lines):
        m = heading_re.match(line.rstrip("\n"))
        if m:
            heading_positions.append((i, len(m.group(1)), m.group(2).strip()))

    for pos_idx, (line_idx, level, heading_text) in enumerate(heading_positions):
        # Determine section content range
        next_line_idx = (
            heading_positions[pos_idx + 1][0]
            if pos_idx + 1 < len(heading_positions)
            else n
        )
        section_lines = lines[line_idx:next_line_idx]
        section_text = "".join(section_lines)

        # Determine annotation: check line before heading and within section
        preceding_line = lines[line_idx - 1].strip() if line_idx > 0 else ""

        skip_for: str | list[str] | None = None

        # Check for <!-- sync:skip --> (all targets)
        if _SKIP_ALL_RE.search(preceding_line) or _SKIP_ALL_RE.search(section_text):
            skip_for = "all"

        if skip_for is None:
            # Check for <!-- sync:skip target=... -->
            m_skip = _SKIP_TARGET_RE.search(preceding_line) or _SKIP_TARGET_RE.search(section_text)
            if m_skip:
                targets = [t.strip() for t in m_skip.group(1).split(",") if t.strip()]
                skip_for = targets

        if skip_for is None:
            # Check for <!-- sync:only target=... --> — skip if current target NOT in list
            m_only = _ONLY_TARGET_RE.search(preceding_line) or _ONLY_TARGET_RE.search(section_text)
            if m_only:
                only_targets = [t.strip() for t in m_only.group(1).split(",") if t.strip()]
                if target and target not in only_targets:
                    skip_for = "all_except_listed"

        if skip_for is None:
            continue

        # Strip annotations from content before returning
        clean_content = strip_skip_annotations(section_text)

        sections.append({
            "heading": heading_text,
            "level": level,
            "skipped_for": skip_for,
            "content": clean_content,
        })

    return sections


def filter_content_by_annotations(content: str, target: str) -> str:
    """Return content with sync:skip-annotated sections removed for ``target``.

    Parses the full content and removes any section that is annotated with
    ``<!-- sync:skip -->`` (all targets) or
    ``<!-- sync:skip target=<target> -->`` matching the given target.
    Sections annotated with ``<!-- sync:only target=... -->`` are removed
    when ``target`` is NOT in the only-list.

    The resulting content is suitable for writing to the target harness config.
    All annotation comments are stripped from the output.

    Args:
        content: Raw CLAUDE.md content.
        target: Target harness name (e.g. "codex").

    Returns:
        Filtered content string with skipped sections and annotations removed.
    """
    skipped = extract_skipped_sections(content, target=target)
    if not skipped:
        return strip_skip_annotations(content)

    # Build a set of heading texts that should be excluded
    excluded_headings: set[str] = set()
    for section in skipped:
        sf = section["skipped_for"]
        if sf == "all" or sf == "all_except_listed":
            excluded_headings.add(section["heading"])
        elif isinstance(sf, list) and target in sf:
            excluded_headings.add(section["heading"])

    if not excluded_headings:
        return strip_skip_annotations(content)

    heading_re = re.compile(r"^(#{1,6})\s+(.+?)(?:\s+#+)?$", re.MULTILINE)
    output_lines: list[str] = []
    lines = content.splitlines(keepends=True)
    in_excluded = False
    current_excluded_level: int | None = None

    for line in lines:
        m = heading_re.match(line.rstrip("\n"))
        if m:
            level = len(m.group(1))
            heading_text = m.group(2).strip()
            if heading_text in excluded_headings:
                in_excluded = True
                current_excluded_level = level
                continue  # skip the heading line itself
            elif in_excluded and current_excluded_level is not None:
                if level <= current_excluded_level:
                    # New section at same or higher level — exit excluded mode
                    in_excluded = False
                    current_excluded_level = None
        if not in_excluded:
            output_lines.append(line)

    result = "".join(output_lines)
    return strip_skip_annotations(result)


class SyncIgnore:
    """Parses and applies .syncignore exclusion rules.

    Patterns are gitignore-style:
    - Lines starting with ``#`` are comments.
    - Blank lines are ignored.
    - A leading ``/`` anchors the pattern to the repo root (stripped before matching).
    - ``*`` matches any sequence of characters that doesn't include ``/``.
    - ``**`` matches any sequence of characters including ``/``.
    - Patterns without wildcards are matched as exact names (basename).
    - Patterns with wildcards use fnmatch against the full relative path and basename.
    """

    def __init__(self, patterns: list[str]):
        """Initialise with a list of parsed patterns (no comments, no blanks)."""
        self._patterns: list[str] = patterns

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, project_dir: Path) -> "SyncIgnore":
        """Load .syncignore from project_dir, returning an empty instance if absent.

        Args:
            project_dir: Project root directory.

        Returns:
            SyncIgnore instance (empty patterns if file not found or unreadable).
        """
        path = Path(project_dir) / SYNCIGNORE_FILE
        if not path.is_file():
            return cls([])
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return cls([])
        return cls.from_text(text)

    @classmethod
    def from_text(cls, text: str) -> "SyncIgnore":
        """Parse .syncignore content and return a SyncIgnore instance.

        Args:
            text: Raw .syncignore file content.

        Returns:
            SyncIgnore with parsed patterns.
        """
        patterns: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # Strip leading slash (anchored patterns — we match basenames anyway)
            if stripped.startswith("/"):
                stripped = stripped[1:]
            if stripped:
                patterns.append(stripped)
        return cls(patterns)

    # ------------------------------------------------------------------
    # Core matching
    # ------------------------------------------------------------------

    def should_skip(self, name: str, path: str | None = None) -> bool:
        """Return True if this name/path should be excluded from sync.

        Matches ``name`` (typically a basename without extension) and
        optionally ``path`` (relative path) against all loaded patterns.

        Args:
            name: Short identifier, e.g. skill name, rule file stem.
            path: Optional relative path for more precise pattern matching.

        Returns:
            True if any pattern matches.
        """
        candidates = [name]
        if path:
            candidates.append(path)
            # Also match against basename
            candidates.append(Path(path).name)
            candidates.append(Path(path).stem)

        for pattern in self._patterns:
            for candidate in candidates:
                if self._matches(pattern, candidate):
                    return True
        return False

    def _matches(self, pattern: str, name: str) -> bool:
        """Check if ``pattern`` matches ``name`` using fnmatch semantics."""
        # Exact match first (case-insensitive for cross-platform compatibility)
        if pattern.lower() == name.lower():
            return True
        # Wildcard match
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(name.lower(), pattern.lower()):
            return True
        return False

    # ------------------------------------------------------------------
    # Filtering helpers
    # ------------------------------------------------------------------

    def filter_rules(self, rules: list[dict]) -> list[dict]:
        """Return rules with excluded entries removed.

        Each rule dict must have at least a ``path`` key.  The stem of the
        path and the full relative path are both checked against patterns.

        Args:
            rules: List of rule dicts with ``path`` and ``content`` keys.

        Returns:
            Filtered list.  The original list is not modified.
        """
        if not self._patterns:
            return rules
        kept: list[dict] = []
        for rule in rules:
            path = rule.get("path", "")
            name = Path(path).stem if path else rule.get("name", "")
            if not self.should_skip(name, path):
                kept.append(rule)
        return kept

    def filter_skills(self, skills: dict[str, Path]) -> dict[str, Path]:
        """Return skills dict with excluded skills removed.

        Args:
            skills: Mapping of skill_name -> path.

        Returns:
            Filtered dict.
        """
        if not self._patterns:
            return skills
        return {name: path for name, path in skills.items() if not self.should_skip(name)}

    def filter_agents(self, agents: dict[str, Path]) -> dict[str, Path]:
        """Return agents dict with excluded agents removed."""
        if not self._patterns:
            return agents
        return {name: path for name, path in agents.items() if not self.should_skip(name)}

    def filter_commands(self, commands: dict[str, Path]) -> dict[str, Path]:
        """Return commands dict with excluded commands removed."""
        if not self._patterns:
            return commands
        return {name: path for name, path in commands.items() if not self.should_skip(name)}

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def pattern_count(self) -> int:
        """Number of active exclusion patterns."""
        return len(self._patterns)

    def describe(self) -> str:
        """Return a human-readable summary of loaded patterns."""
        if not self._patterns:
            return ".syncignore: no patterns loaded (all content will sync)"
        lines = [f".syncignore: {len(self._patterns)} exclusion pattern(s)"]
        for p in self._patterns:
            lines.append(f"  - {p}")
        return "\n".join(lines)
