from __future__ import annotations

"""Config Search & Cross-Harness Query for HarnessSync.

Full-text search across all rules, skills, MCP configs, and settings across
all supported harnesses with a single call.  Search terms are matched against
file contents using either literal string search or regular expressions.

Results show WHERE each match was found: which harness, which file path (relative
to the user home directory), which config section, and the line plus surrounding
context lines.

Supported harnesses and their config locations:
    codex     : ~/.codex/AGENTS.md, ~/.codex/config.toml
    gemini    : ~/.gemini/GEMINI.md, ~/.gemini/settings.json
    opencode  : ~/.config/opencode/AGENTS.md, ~/.config/opencode/opencode.json
    cursor    : ~/.cursor/rules/*.mdc
    aider     : ~/.aider/CONVENTIONS.md, ~/.aider/.aider.conf.yml
    windsurf  : ~/.windsurf/memories/ (all files)

Additionally, project-level files are searched when a project_dir is supplied:
    CLAUDE.md, AGENTS.md, GEMINI.md, .mcp.json  (project root)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Harness file catalog
# ---------------------------------------------------------------------------

#: Maps harness name -> list of (glob_pattern_or_path, section_tag)
#: Paths are relative to the user home directory.
_HARNESS_FILES: dict[str, list[tuple[str, str]]] = {
    "codex": [
        (".codex/AGENTS.md",      "rules"),
        (".codex/config.toml",    "settings"),
    ],
    "gemini": [
        (".gemini/GEMINI.md",     "rules"),
        (".gemini/settings.json", "settings"),
    ],
    "opencode": [
        (".config/opencode/AGENTS.md",      "rules"),
        (".config/opencode/opencode.json",  "settings"),
    ],
    "cursor": [
        (".cursor/rules",         "rules"),   # directory — expanded below
    ],
    "aider": [
        (".aider/CONVENTIONS.md",       "rules"),
        (".aider/.aider.conf.yml",      "settings"),
    ],
    "windsurf": [
        (".windsurf/memories",    "rules"),   # directory — expanded below
    ],
}

#: Project-level files searched alongside harness configs.
#: Tuples of (filename_relative_to_project_dir, section_tag, harness_label).
_PROJECT_FILES: list[tuple[str, str, str]] = [
    ("CLAUDE.md",  "rules",    "claude"),
    ("AGENTS.md",  "rules",    "claude"),
    ("GEMINI.md",  "rules",    "gemini"),
    (".mcp.json",  "mcp",      "claude"),
]

_CONTEXT_LINES = 2  # lines of context to capture before/after each match


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SearchMatch:
    """A single line that matched the search query.

    Attributes:
        harness:        Harness name (e.g. ``"codex"``), or ``"claude"`` for
                        project-level source files.
        file_path:      Path to the file, relative to the user home directory
                        (or relative to project_dir for project files).
        section:        Config section type: ``"rules"`` | ``"skills"`` |
                        ``"mcp"`` | ``"settings"`` | ``"commands"``.
        line_number:    1-based line number of the match within the file.
        line_text:      The full text of the matching line (no trailing newline).
        context_before: Up to ``_CONTEXT_LINES`` lines immediately before the match.
        context_after:  Up to ``_CONTEXT_LINES`` lines immediately after the match.
    """

    harness: str
    file_path: str
    section: str
    line_number: int
    line_text: str
    context_before: list[str] = field(default_factory=list)
    context_after: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """Aggregated results from a cross-harness search.

    Attributes:
        query:              The original search query string.
        matches:            Ordered list of :class:`SearchMatch` objects.
        harnesses_searched: Names of harnesses that were scanned.
        files_searched:     Total number of files that were read and searched.
    """

    query: str
    matches: list[SearchMatch]
    harnesses_searched: list[str]
    files_searched: int

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def format(self, show_context: bool = True) -> str:
        """Render the search results as human-readable text.

        Args:
            show_context: When True, include up to ``_CONTEXT_LINES`` lines of
                          context around each match.  When False, show only the
                          matching line.

        Returns:
            Multi-line string suitable for terminal output.
        """
        if not self.matches:
            return (
                f"No matches found for '{self.query}'\n"
                f"Searched {self.files_searched} file(s) across "
                f"{len(self.harnesses_searched)} harness(es): "
                f"{', '.join(self.harnesses_searched) or 'none'}"
            )

        lines: list[str] = []
        lines.append(
            f"Found {len(self.matches)} match(es) for '{self.query}' "
            f"across {self.files_searched} file(s) "
            f"in {len(self.harnesses_searched)} harness(es):"
        )
        lines.append("")

        # Group by (harness, file_path) for cleaner output
        current_file_key: tuple[str, str] | None = None

        for m in self.matches:
            file_key = (m.harness, m.file_path)
            if file_key != current_file_key:
                current_file_key = file_key
                lines.append(f"  [{m.harness}] {m.file_path}  (section: {m.section})")

            if show_context and m.context_before:
                for i, ctx_line in enumerate(m.context_before):
                    ctx_lineno = m.line_number - len(m.context_before) + i
                    lines.append(f"    {ctx_lineno:>5}  {ctx_line}")

            lines.append(f"  > {m.line_number:>5}  {m.line_text}")

            if show_context and m.context_after:
                for i, ctx_line in enumerate(m.context_after):
                    ctx_lineno = m.line_number + 1 + i
                    lines.append(f"    {ctx_lineno:>5}  {ctx_line}")

            if show_context and (m.context_before or m.context_after):
                lines.append("")

        if not show_context:
            lines.append("")

        lines.append(
            f"Searched harnesses: {', '.join(self.harnesses_searched) or 'none'}"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main search class
# ---------------------------------------------------------------------------

class ConfigSearch:
    """Full-text search across all harness config files.

    Scans the per-harness file locations documented in :mod:`config_search` as
    well as project-level files (CLAUDE.md, AGENTS.md, GEMINI.md, .mcp.json)
    when *project_dir* is supplied.

    Example::

        searcher = ConfigSearch(project_dir=Path("/my/project"))
        result = searcher.search("conventional commits", harnesses=["codex", "gemini"])
        print(result.format())
    """

    def __init__(self, project_dir: Path | None = None):
        """Initialize the searcher.

        Args:
            project_dir: Optional path to the project root.  When supplied,
                         project-level files (CLAUDE.md, .mcp.json, etc.) are
                         also searched.
        """
        self.project_dir = project_dir
        self._home = Path.home()

    # ------------------------------------------------------------------
    # File discovery helpers
    # ------------------------------------------------------------------

    def _resolve_harness_files(
        self, harness: str
    ) -> list[tuple[Path, str]]:
        """Return all (absolute_path, section) pairs for a harness.

        Expands directory entries (cursor rules/, windsurf memories/) into
        their constituent files.

        Args:
            harness: Harness name.

        Returns:
            List of (Path, section_string) tuples for files that exist.
        """
        entries = _HARNESS_FILES.get(harness, [])
        result: list[tuple[Path, str]] = []

        for rel_path, section in entries:
            abs_path = self._home / rel_path

            if abs_path.is_dir():
                # Expand directory: grab all readable files recursively
                try:
                    for child in sorted(abs_path.rglob("*")):
                        if child.is_file() and not child.name.startswith("."):
                            result.append((child, section))
                except OSError:
                    pass
            elif abs_path.exists():
                result.append((abs_path, section))

        return result

    def _resolve_project_files(self) -> list[tuple[Path, str, str]]:
        """Return (absolute_path, section, harness_label) for project files.

        Returns:
            List of tuples for project-level files that exist.
        """
        if not self.project_dir:
            return []

        result: list[tuple[Path, str, str]] = []
        for rel, section, harness_label in _PROJECT_FILES:
            p = self.project_dir / rel
            if p.exists() and p.is_file():
                result.append((p, section, harness_label))
        return result

    # ------------------------------------------------------------------
    # Core search logic
    # ------------------------------------------------------------------

    @staticmethod
    def _compile_pattern(query: str, regex: bool) -> re.Pattern[str]:
        """Compile the search pattern.

        Args:
            query: Search string or regex pattern.
            regex: When False the query is treated as a literal string and
                   escaped before compiling.

        Returns:
            Compiled :class:`re.Pattern`.
        """
        flags = re.IGNORECASE
        pattern_str = query if regex else re.escape(query)
        return re.compile(pattern_str, flags)

    @staticmethod
    def _make_file_path_label(abs_path: Path, home: Path) -> str:
        """Return a display path relative to home (or absolute if outside home).

        Args:
            abs_path: Absolute path to the file.
            home:     User home directory.

        Returns:
            ``~/<relative>`` style string when the path is under home, otherwise
            the resolved absolute path string.
        """
        try:
            rel = abs_path.relative_to(home)
            return f"~/{rel}"
        except ValueError:
            return str(abs_path.resolve())

    def _search_file(
        self,
        abs_path: Path,
        harness: str,
        section: str,
        pattern: re.Pattern[str],
    ) -> list[SearchMatch]:
        """Search a single file for lines matching *pattern*.

        Args:
            abs_path: Absolute path to the file.
            harness:  Harness label for the match records.
            section:  Section type label for the match records.
            pattern:  Compiled regex pattern to search for.

        Returns:
            List of :class:`SearchMatch` objects (may be empty).
        """
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        all_lines = text.splitlines()
        file_label = self._make_file_path_label(abs_path, self._home)
        matches: list[SearchMatch] = []

        for idx, line in enumerate(all_lines):
            if not pattern.search(line):
                continue

            line_number = idx + 1  # 1-based

            before_start = max(0, idx - _CONTEXT_LINES)
            after_end = min(len(all_lines), idx + _CONTEXT_LINES + 1)

            context_before = all_lines[before_start:idx]
            context_after = all_lines[idx + 1: after_end]

            matches.append(
                SearchMatch(
                    harness=harness,
                    file_path=file_label,
                    section=section,
                    line_number=line_number,
                    line_text=line,
                    context_before=context_before,
                    context_after=context_after,
                )
            )

        return matches

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        harnesses: list[str] | None = None,
        sections: list[str] | None = None,
        regex: bool = False,
    ) -> SearchResult:
        """Search all harness config files for *query*.

        Args:
            query:     Search term or regular expression.
            harnesses: Optional list of harness names to restrict the search to.
                       When None, all known harnesses are searched.
            sections:  Optional list of section types to restrict the search to
                       (``"rules"``, ``"skills"``, ``"mcp"``, ``"settings"``,
                       ``"commands"``).  When None, all sections are searched.
            regex:     When True, treat *query* as a regular expression.
                       When False (default), treat it as a literal string.

        Returns:
            :class:`SearchResult` with all matches and search metadata.

        Raises:
            re.error: If *regex* is True and *query* is not a valid pattern.
        """
        pattern = self._compile_pattern(query, regex)

        known_harnesses = list(_HARNESS_FILES.keys())
        target_harnesses: list[str] = (
            [h for h in harnesses if h in _HARNESS_FILES]
            if harnesses is not None
            else known_harnesses
        )

        all_matches: list[SearchMatch] = []
        files_searched = 0
        harnesses_searched: list[str] = []

        # --- Search harness-specific files ---
        for harness in target_harnesses:
            harness_files = self._resolve_harness_files(harness)
            harness_had_file = False

            for abs_path, section in harness_files:
                if sections is not None and section not in sections:
                    continue
                files_searched += 1
                harness_had_file = True
                matches = self._search_file(abs_path, harness, section, pattern)
                all_matches.extend(matches)

            if harness_had_file and harness not in harnesses_searched:
                harnesses_searched.append(harness)

        # --- Search project-level files ---
        project_files = self._resolve_project_files()
        project_harnesses_seen: set[str] = set()

        for abs_path, section, harness_label in project_files:
            if sections is not None and section not in sections:
                continue
            # If caller requested specific harnesses, only include project files
            # whose harness_label matches (or "claude" which maps to project scope).
            if harnesses is not None:
                if harness_label not in harnesses and harness_label != "claude":
                    continue

            files_searched += 1
            matches = self._search_file(abs_path, harness_label, section, pattern)
            all_matches.extend(matches)

            if harness_label not in project_harnesses_seen:
                project_harnesses_seen.add(harness_label)
                if harness_label not in harnesses_searched:
                    harnesses_searched.append(harness_label)

        return SearchResult(
            query=query,
            matches=all_matches,
            harnesses_searched=harnesses_searched,
            files_searched=files_searched,
        )
