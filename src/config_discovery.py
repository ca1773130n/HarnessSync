from __future__ import annotations

"""Claude Code configuration discovery across user and project scopes.

SourceReader discovers all 6 types of Claude Code configuration:
- Rules (CLAUDE.md files)
- Skills (skill directories with SKILL.md)
- Agents (agent .md files)
- Commands (command .md files)
- MCP servers (.mcp.json configs)
- Settings (settings.json files)

Supports user scope (~/.claude/) and project scope (.claude/, CLAUDE.md).
"""

import re
from pathlib import Path
from src.utils.paths import read_json_safe
from src.utils.includes import resolve_includes, extract_include_refs
from src.harness_annotation import filter_rules_for_harness
from src.mcp_reader import MCPReaderMixin
from src.modular_reader import ModularReaderMixin


class SourceReader(MCPReaderMixin, ModularReaderMixin):
    """
    Discovers Claude Code configuration from user and project scopes.

    Scope options:
    - "user": Only read from ~/.claude/
    - "project": Only read from project directory
    - "all": Read from both user and project (merged)

    Multi-account support: Pass cc_home to read from a custom Claude Code
    config directory instead of the default ~/.claude/.
    """

    def __init__(self, scope: str = "all", project_dir: Path = None, cc_home: Path = None):
        """
        Initialize SourceReader.

        Args:
            scope: "user" | "project" | "all"
            project_dir: Path to project root (required for "project" or "all")
            cc_home: Custom Claude Code config directory (default: ~/.claude/)
                     Used for multi-account support to read from account-specific paths.
        """
        self.scope = scope
        self.project_dir = project_dir

        # Claude Code base paths (user scope)
        self.cc_home = cc_home if cc_home is not None else Path.home() / ".claude"
        self.cc_settings = self.cc_home / "settings.json"
        self.cc_plugins_registry = self.cc_home / "plugins" / "installed_plugins.json"
        self.cc_skills = self.cc_home / "skills"
        self.cc_agents = self.cc_home / "agents"
        self.cc_commands = self.cc_home / "commands"
        self.cc_mcp_global = Path.home() / ".mcp.json"  # Global MCP is always at ~
        self.cc_mcp_claude = self.cc_home / ".mcp.json"

    def _parse_rules_frontmatter(self, content: str) -> tuple[dict, str]:
        """Parse YAML frontmatter from rules file content.

        Extracts `paths:` and `globs:` keys from frontmatter delimited by
        `---` at the start of the file. Supports three value formats:
        - Single string: ``paths: src/api/**/*.ts``
        - YAML list: ``paths:\\n  - src/components/**/*.tsx``
        - Inline list: ``paths: [a, b]``

        Args:
            content: Full file content (may or may not have frontmatter)

        Returns:
            Tuple of (frontmatter_dict, body_without_frontmatter).
            frontmatter_dict has 'scope_patterns' key (list of strings).
            If no frontmatter, returns ({}, full_content).
        """
        # Check for frontmatter delimiters
        if not content.startswith('---'):
            return {}, content

        # Find closing ---
        end_match = re.search(r'\n---\s*\n', content[3:])
        if not end_match:
            # No closing delimiter — treat as no frontmatter
            return {}, content

        fm_text = content[3:end_match.start() + 3]
        body = content[end_match.end() + 3:]

        # Extract paths or globs patterns
        scope_patterns = []
        # Try paths: first, then globs: as fallback
        for key in ('paths', 'globs'):
            # Match the key line (use [^\n]* to stay on same line)
            key_match = re.search(rf'^{key}:[ \t]*([^\n]*)$', fm_text, re.MULTILINE)
            if not key_match:
                continue

            value = key_match.group(1).strip()
            if value:
                if value.startswith('[') and value.endswith(']'):
                    # Inline list: paths: [a, b]
                    items = [item.strip().strip('"').strip("'")
                             for item in value[1:-1].split(',')]
                    scope_patterns = [i for i in items if i]
                else:
                    # Single string: paths: src/**/*.ts
                    scope_patterns = [value]
            else:
                # Multi-line YAML list: paths:\n  - item1\n  - item2
                list_pattern = re.compile(r'^\s+-\s+(.+)$', re.MULTILINE)
                # Grab lines after the key until next key or end
                key_pos = key_match.end()
                remaining = fm_text[key_pos:]
                # Find next top-level key (non-indented line with colon)
                next_key = re.search(r'^\S+:', remaining, re.MULTILINE)
                if next_key:
                    remaining = remaining[:next_key.start()]
                items = list_pattern.findall(remaining)
                scope_patterns = [item.strip().strip('"').strip("'") for item in items]

            # paths: takes precedence over globs: — stop after first match
            break

        result = {}
        if scope_patterns:
            result['scope_patterns'] = scope_patterns

        return result, body

    def get_rules_files(self) -> list[dict]:
        """Return list of rules from .claude/rules/ directories.

        Discovers .md files recursively from both user-level (cc_home/rules/)
        and project-level (.claude/rules/) directories. Parses YAML frontmatter
        for optional path-scoping via ``paths:`` or ``globs:`` keys.

        Returns:
            List of dicts with keys:
            - path: Path to the .md file
            - content: Markdown body (after frontmatter stripped)
            - scope_patterns: List of path patterns from frontmatter (empty if none)
            - scope: 'user' or 'project'
        """
        rules = []

        if self.scope in ("user", "all"):
            user_rules_dir = self.cc_home / "rules"
            if user_rules_dir.is_dir():
                for md_file in sorted(user_rules_dir.rglob("*.md")):
                    if not md_file.is_file():
                        continue
                    try:
                        content = md_file.read_text(encoding='utf-8', errors='replace')
                        frontmatter, body = self._parse_rules_frontmatter(content)
                        rules.append({
                            'path': md_file,
                            'content': body,
                            'scope_patterns': frontmatter.get('scope_patterns', []),
                            'scope': 'user',
                        })
                    except (OSError, UnicodeDecodeError):
                        pass

        if self.scope in ("project", "all") and self.project_dir:
            proj_rules_dir = self.project_dir / ".claude" / "rules"
            if proj_rules_dir.is_dir():
                for md_file in sorted(proj_rules_dir.rglob("*.md")):
                    if not md_file.is_file():
                        continue
                    try:
                        content = md_file.read_text(encoding='utf-8', errors='replace')
                        frontmatter, body = self._parse_rules_frontmatter(content)
                        rules.append({
                            'path': md_file,
                            'content': body,
                            'scope_patterns': frontmatter.get('scope_patterns', []),
                            'scope': 'project',
                        })
                    except (OSError, UnicodeDecodeError):
                        pass

        return rules

    def get_rules(self) -> str:
        """
        Get combined CLAUDE.md rules content (SRC-01).

        Returns:
            Combined rules string with section headers, or empty string if none found.
            Multiple sections joined with "\\n\\n---\\n\\n".

        Side-effect:
            Populates ``self._include_refs`` with raw ``@include`` paths found
            during resolution, available via :meth:`get_include_refs`.
        """
        rules = []
        all_include_refs: list[str] = []

        if self.scope in ("user", "all"):
            # User-level CLAUDE.md
            user_claude_md = self.cc_home / "CLAUDE.md"
            if user_claude_md.exists():
                try:
                    content = user_claude_md.read_text(encoding='utf-8', errors='replace')
                    # Collect raw include refs before resolution
                    all_include_refs.extend(extract_include_refs(content))
                    # Resolve @include directives
                    content, _included = resolve_includes(content, user_claude_md.parent)
                    rules.append(f"# [User-level rules from ~/.claude/CLAUDE.md]\n\n{content}")
                except (OSError, UnicodeDecodeError):
                    pass  # Skip on error

        if self.scope in ("project", "all") and self.project_dir:
            # Project-level CLAUDE.md files
            for claude_md_name in ["CLAUDE.md", "CLAUDE.local.md"]:
                p = self.project_dir / claude_md_name
                if p.exists():
                    try:
                        content = p.read_text(encoding='utf-8', errors='replace')
                        all_include_refs.extend(extract_include_refs(content))
                        content, _included = resolve_includes(content, p.parent)
                        rules.append(f"# [Project rules from {claude_md_name}]\n\n{content}")
                    except (OSError, UnicodeDecodeError):
                        pass

            # Also check .claude/ subdirectory
            p = self.project_dir / ".claude" / "CLAUDE.md"
            if p.exists():
                try:
                    content = p.read_text(encoding='utf-8', errors='replace')
                    all_include_refs.extend(extract_include_refs(content))
                    content, _included = resolve_includes(content, p.parent)
                    rules.append(f"# [Project rules from .claude/CLAUDE.md]\n\n{content}")
                except (OSError, UnicodeDecodeError):
                    pass

        # Store include refs for discover_all() to expose
        self._include_refs = all_include_refs

        return "\n\n---\n\n".join(rules)

    def get_include_refs(self) -> list[str]:
        """Return raw ``@include`` path strings found during the last ``get_rules()`` call.

        Returns:
            List of raw include path strings. Empty if ``get_rules()`` has not been called
            or no ``@include`` directives were found.
        """
        return getattr(self, '_include_refs', [])

    def get_rules_for_harness(self, target: str) -> str:
        """Return rules filtered by inline ``<!-- harness:X -->`` annotations.

        Calls :func:`get_rules` then applies :func:`filter_rules_for_harness`
        so that only rules relevant to *target* are included.  Annotation
        markers are stripped from the output.

        Args:
            target: Target harness name (e.g. ``"codex"``).

        Returns:
            Filtered rules string ready for use by the adapter.
        """
        raw = self.get_rules()
        return filter_rules_for_harness(raw, target)

    def get_harness_override(self, target_name: str) -> str:
        """Read per-harness override file (e.g. CLAUDE.codex.md) if present.

        Per-harness override files let users maintain harness-specific additions
        that layer on top of the main CLAUDE.md during sync. For example,
        CLAUDE.codex.md contains codex-only instructions appended when syncing
        to codex.

        Supported files (looked up in project_dir, then .claude/):
            CLAUDE.codex.md   -> codex
            CLAUDE.gemini.md  -> gemini
            CLAUDE.opencode.md -> opencode
            CLAUDE.cursor.md  -> cursor
            CLAUDE.aider.md   -> aider
            CLAUDE.windsurf.md -> windsurf

        Args:
            target_name: Target harness name (e.g. "codex").

        Returns:
            Content of the override file, or empty string if none found.
        """
        if not self.project_dir or not target_name:
            return ""

        target_lower = target_name.lower()
        candidates = [
            self.project_dir / f"CLAUDE.{target_lower}.md",
            self.project_dir / ".claude" / f"CLAUDE.{target_lower}.md",
        ]
        for path in candidates:
            if path.is_file():
                try:
                    return path.read_text(encoding="utf-8")
                except OSError:
                    pass
        return ""

    def get_harness_override_paths(self) -> dict[str, Path]:
        """Return mapping of target -> override file path for all present overrides.

        Returns:
            Dict mapping target_name -> Path for each existing override file.
        """
        known_targets = ("codex", "gemini", "opencode", "cursor", "aider", "windsurf")
        result: dict[str, Path] = {}
        if not self.project_dir:
            return result
        for target in known_targets:
            candidates = [
                self.project_dir / f"CLAUDE.{target}.md",
                self.project_dir / ".claude" / f"CLAUDE.{target}.md",
            ]
            for path in candidates:
                if path.is_file():
                    result[target] = path
                    break
        return result

    def get_inline_harness_block(self, target_name: str) -> str:
        """Extract the inline ``<!-- harness:X -->`` block for *target_name* from CLAUDE.md.

        Supports the fenced inline override syntax described in product-ideation
        item 3: users can embed harness-specific sections directly inside CLAUDE.md
        without maintaining separate files::

            <!-- harness:codex -->
            Always use TypeScript.  No implicit any.
            <!-- /harness:codex -->

        This method reads the primary CLAUDE.md (project or global) and returns the
        content of the matching block for *target_name*.  It returns an empty string
        when no inline block exists for the target, making it safe to call
        unconditionally -- callers should treat the empty string as "no override".

        Args:
            target_name: Target harness name (e.g. "codex", "gemini").

        Returns:
            Extracted block content (stripped), or empty string if none found.
        """
        from src.harness_override import extract_inline_block

        # Try project CLAUDE.md first, then global ~/.claude/CLAUDE.md
        candidates: list[Path] = []
        if self.project_dir:
            candidates.append(self.project_dir / "CLAUDE.md")
            candidates.append(self.project_dir / ".claude" / "CLAUDE.md")
        if self.cc_home:
            candidates.append(self.cc_home / "CLAUDE.md")

        for path in candidates:
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                    block = extract_inline_block(content, target_name)
                    if block:
                        return block
                except OSError:
                    continue
        return ""

    def get_all_inline_harness_blocks(self) -> dict[str, str]:
        """Return all inline harness blocks found in CLAUDE.md as {harness: content}.

        Scans the primary CLAUDE.md file for all ``<!-- harness:X -->`` blocks and
        returns a mapping of harness name -> block content.  Empty if CLAUDE.md
        has no inline blocks.

        Returns:
            Dict mapping harness name -> extracted block content.
        """
        from src.harness_override import parse_inline_harness_blocks

        candidates: list[Path] = []
        if self.project_dir:
            candidates.append(self.project_dir / "CLAUDE.md")
            candidates.append(self.project_dir / ".claude" / "CLAUDE.md")
        if self.cc_home:
            candidates.append(self.cc_home / "CLAUDE.md")

        for path in candidates:
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                    blocks = parse_inline_harness_blocks(content)
                    if blocks:
                        return blocks
                except OSError:
                    continue
        return {}

    def discover_all(self) -> dict:
        """
        Convenience method to get all config types at once.

        Returns:
            Dictionary with keys: rules (fully resolved with includes inlined),
            include_refs (raw @include paths for adapters that prefer native imports),
            rules_files, skills, agents, commands,
            mcp_servers (flat), mcp_servers_scoped (with metadata), settings,
            permissions, hooks, plugins
        """
        scoped = self.get_mcp_servers_with_scope()
        flat = {name: entry["config"] for name, entry in scoped.items()}
        # get_rules() populates self._include_refs as a side-effect
        rules = self.get_rules()
        return {
            "rules": rules,
            "include_refs": self.get_include_refs(),
            "rules_files": self.get_rules_files(),
            "skills": self.get_skills(),
            "agents": self.get_agents(),
            "commands": self.get_commands(),
            "mcp_servers": flat,
            "mcp_servers_scoped": scoped,
            "settings": self.get_settings(),
            "permissions": self.get_permissions(),
            "harness_overrides": self.get_harness_override_paths(),
            "hooks": self.get_hooks(),
            "plugins": self.get_plugins(),
        }

    def get_source_paths(self) -> dict[str, list[Path]]:
        """
        Get list of source file paths that were found for each config type.
        Useful for state tracking (hash each source file for drift detection).

        Returns:
            Dictionary mapping config_type -> list of Path objects
            Keys: rules, skills, agents, commands, mcp_servers, settings
            Values: List of Path objects that were successfully found

        Note:
            - For skills: returns skill directory paths (not SKILL.md files)
            - For agents/commands: returns .md file paths
            - For rules/mcp/settings: returns source file paths
            - Used for state tracking (hash each source file for drift detection)
        """
        paths = {
            "rules": [],
            "skills": [],
            "agents": [],
            "commands": [],
            "mcp_servers": [],
            "settings": [],
        }

        # Rules sources
        if self.scope in ("user", "all"):
            user_claude_md = self.cc_home / "CLAUDE.md"
            if user_claude_md.exists():
                paths["rules"].append(user_claude_md)

        if self.scope in ("project", "all") and self.project_dir:
            for claude_md_name in ["CLAUDE.md", "CLAUDE.local.md"]:
                p = self.project_dir / claude_md_name
                if p.exists():
                    paths["rules"].append(p)
            p = self.project_dir / ".claude" / "CLAUDE.md"
            if p.exists():
                paths["rules"].append(p)

        # Skills sources (directories)
        skills = self.get_skills()
        paths["skills"] = list(skills.values())

        # Agents sources (files)
        agents = self.get_agents()
        paths["agents"] = list(agents.values())

        # Commands sources (files)
        commands = self.get_commands()
        paths["commands"] = list(commands.values())

        # MCP servers sources
        if self.scope in ("user", "all"):
            claude_json = self.cc_home / ".claude.json"
            if claude_json.exists():
                paths["mcp_servers"].append(claude_json)
            if self.cc_mcp_claude.exists():
                paths["mcp_servers"].append(self.cc_mcp_claude)

        if self.scope in ("project", "all") and self.project_dir:
            proj_mcp = self.project_dir / ".mcp.json"
            if proj_mcp.exists():
                paths["mcp_servers"].append(proj_mcp)

        # Settings sources
        if self.scope in ("user", "all"):
            if self.cc_settings.exists():
                paths["settings"].append(self.cc_settings)

        if self.scope in ("project", "all") and self.project_dir:
            proj_settings = self.project_dir / ".claude" / "settings.json"
            if proj_settings.exists():
                paths["settings"].append(proj_settings)
            local_settings = self.project_dir / ".claude" / "settings.local.json"
            if local_settings.exists():
                paths["settings"].append(local_settings)

        return paths
