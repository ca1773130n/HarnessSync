from __future__ import annotations

"""
.syncignore support — gitignore-style exclusion patterns for sync operations.

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
from pathlib import Path


SYNCIGNORE_FILE = ".syncignore"


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
