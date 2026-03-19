from __future__ import annotations

"""
Claude Code configuration discovery across user and project scopes.

SourceReader discovers all 6 types of Claude Code configuration:
- Rules (CLAUDE.md files)
- Skills (skill directories with SKILL.md)
- Agents (agent .md files)
- Commands (command .md files)
- MCP servers (.mcp.json configs)
- Settings (settings.json files)

Supports user scope (~/.claude/) and project scope (.claude/, CLAUDE.md).
"""

import json
import re
from pathlib import Path
from src.utils.paths import read_json_safe
from src.utils.permissions import extract_permissions
from src.utils.includes import resolve_includes, extract_include_refs

# ─────────────────────────────────────────────────────────────────────────────
# Inline harness annotation parsing (item 2 — Per-Harness Rule Overrides)
# ─────────────────────────────────────────────────────────────────────────────
#
# Supported annotation forms in CLAUDE.md:
#
#   <!-- harness:codex -->
#   This rule is only for Codex.
#   <!-- /harness:codex -->
#
#   <!-- harness:codex,cursor -->
#   This rule is for Codex and Cursor only.
#   <!-- /harness:codex,cursor -->
#
#   <!-- harness:!gemini -->
#   This rule is synced everywhere EXCEPT Gemini.
#   <!-- /harness:!gemini -->
#
#   <!-- sync:only:cursor,gemini -->
#   Power-user form: only land in cursor and gemini.
#   <!-- /sync:only -->
#
#   <!-- sync:skip:codex -->
#   Power-user form: sync everywhere EXCEPT codex.
#   <!-- /sync:skip -->
#
# Blocks without any annotation are included for all harnesses (default).
# Opening and closing tags are consumed; only the block body is kept.

_HARNESS_ANNO_RE = re.compile(
    r"<!--\s*harness:(!?)([a-zA-Z0-9_,\s-]+?)\s*-->(.*?)<!--\s*/harness:[^>]+-->",
    re.DOTALL | re.IGNORECASE,
)

# sync:only:target1,target2 ... /sync:only  (include-list form)
_SYNC_ONLY_RE = re.compile(
    r"<!--\s*sync:only:([a-zA-Z0-9_,\s-]+?)\s*-->(.*?)<!--\s*/sync:only\s*-->",
    re.DOTALL | re.IGNORECASE,
)

# sync:skip:target1,target2 ... /sync:skip  (exclude-list form)
_SYNC_SKIP_RE = re.compile(
    r"<!--\s*sync:skip:([a-zA-Z0-9_,\s-]+?)\s*-->(.*?)<!--\s*/sync:skip\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def filter_rules_for_harness(content: str, target: str) -> str:
    """Filter CLAUDE.md content, keeping only rules relevant to *target*.

    Inline harness annotations scope rule blocks to specific targets.
    Three equivalent syntaxes are supported:

    * ``<!-- harness:codex --> ... <!-- /harness:codex -->``
      Keep only when syncing to codex.
    * ``<!-- harness:codex,cursor --> ... <!-- /harness:codex,cursor -->``
      Keep only when syncing to codex or cursor.
    * ``<!-- harness:!gemini --> ... <!-- /harness:!gemini -->``
      Exclude when syncing to gemini.
    * ``<!-- sync:only:cursor,gemini --> ... <!-- /sync:only -->``
      Power-user alias: include only in cursor and gemini.
    * ``<!-- sync:skip:codex --> ... <!-- /sync:skip -->``
      Power-user alias: include everywhere except codex.

    Content outside annotation blocks is passed through unchanged.

    Args:
        content: Raw CLAUDE.md text.
        target: Target harness name (e.g. ``"codex"``).

    Returns:
        Filtered content with annotation markers removed.
    """
    target_lower = target.lower().strip()

    # ── Pass 1: resolve sync:only blocks ─────────────────────────────────────
    def _apply_sync_only(m: re.Match) -> str:
        targets = [t.strip().lower() for t in m.group(1).replace(" ", "").split(",") if t.strip()]
        return m.group(2) if target_lower in targets else ""

    content = _SYNC_ONLY_RE.sub(_apply_sync_only, content)

    # ── Pass 2: resolve sync:skip blocks ─────────────────────────────────────
    def _apply_sync_skip(m: re.Match) -> str:
        targets = [t.strip().lower() for t in m.group(1).replace(" ", "").split(",") if t.strip()]
        return m.group(2) if target_lower not in targets else ""

    content = _SYNC_SKIP_RE.sub(_apply_sync_skip, content)

    # ── Pass 3: resolve harness: blocks ──────────────────────────────────────
    result_parts: list[str] = []
    last_end = 0

    for m in _HARNESS_ANNO_RE.finditer(content):
        result_parts.append(content[last_end:m.start()])
        last_end = m.end()

        negate = m.group(1) == "!"
        raw_targets = [t.strip().lower() for t in m.group(2).replace(" ", "").split(",") if t.strip()]
        body = m.group(3)

        in_list = target_lower in raw_targets
        include = (not negate and in_list) or (negate and not in_list)
        if include:
            result_parts.append(body)

    result_parts.append(content[last_end:])
    return "".join(result_parts)


class SourceReader:
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

    def _get_plugin_install_paths(self) -> list[Path]:
        """Get install paths for all user-scope plugins from the registry.

        Handles both v1 (flat dict) and v2 (dict of lists) formats of
        installed_plugins.json.

        Returns:
            List of Path objects for each plugin install directory
        """
        if not self.cc_plugins_registry.exists():
            return []

        registry = read_json_safe(self.cc_plugins_registry)
        plugins_data = registry.get("plugins", {})

        paths = []

        if isinstance(plugins_data, dict):
            for plugin_key, installs in plugins_data.items():
                # v2 format: each value is a list of install entries
                if not isinstance(installs, list):
                    installs = [installs]

                for install in installs:
                    if not isinstance(install, dict):
                        continue
                    if install.get("scope") != "user":
                        continue
                    install_path = install.get("installPath", "")
                    if not install_path:
                        continue
                    try:
                        p = Path(install_path)
                        if p.exists():
                            paths.append(p)
                    except (OSError, ValueError):
                        pass

        elif isinstance(plugins_data, list):
            for plugin_info in plugins_data:
                if not isinstance(plugin_info, dict):
                    continue
                if plugin_info.get("scope") != "user":
                    continue
                install_path = plugin_info.get("installPath", "")
                if not install_path:
                    continue
                try:
                    p = Path(install_path)
                    if p.exists():
                        paths.append(p)
                except (OSError, ValueError):
                    pass

        return paths

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

    def get_skills(self) -> dict[str, Path]:
        """
        Discover Claude Code skills (SRC-02).

        Returns:
            Dictionary mapping skill_name -> path_to_skill_dir
            Includes skills from ~/.claude/skills/, plugin cache, and project .claude/skills/

        Note:
            - Symlinked skill directories are recorded as-is (not followed)
            - Plugin cache supports both dict and list formats in installed_plugins.json
            - Only user-scope plugins are included in user-scope discovery
            - Handles permission errors and invalid paths gracefully
        """
        skills = {}

        if self.scope in ("user", "all"):
            # User-level skills
            if self.cc_skills.is_dir():
                for d in self.cc_skills.iterdir():
                    try:
                        skill_md = d / "SKILL.md"
                        if d.is_dir() and skill_md.exists():
                            skills[d.name] = d
                    except OSError:
                        pass  # Permission error or other issue

            # Plugin-installed skills
            for p in self._get_plugin_install_paths():
                try:
                    skills_dir = p / "skills"
                    if skills_dir.is_dir():
                        for d in skills_dir.iterdir():
                            if d.is_dir() and (d / "SKILL.md").exists():
                                skills[d.name] = d
                except (OSError, ValueError):
                    pass

        if self.scope in ("project", "all") and self.project_dir:
            proj_skills = self.project_dir / ".claude" / "skills"
            if proj_skills.is_dir():
                for d in proj_skills.iterdir():
                    try:
                        if d.is_dir() and (d / "SKILL.md").exists():
                            skills[d.name] = d
                    except OSError:
                        pass

        return skills

    def get_agents(self) -> dict[str, Path]:
        """
        Discover Claude Code agent definitions (SRC-03).

        Returns:
            Dictionary mapping agent_name -> path_to_md_file
            Includes agents from ~/.claude/agents/ and project .claude/agents/

        Note:
            - Hidden files (starting with .) are filtered out
            - Only .md files are included
            - Non-file entries (directories) are skipped
        """
        agents = {}

        if self.scope in ("user", "all"):
            if self.cc_agents.is_dir():
                for f in self.cc_agents.iterdir():
                    try:
                        # Skip hidden files and non-.md files
                        if f.suffix == ".md" and not f.name.startswith('.') and f.is_file():
                            agents[f.stem] = f
                    except OSError:
                        pass

            # Plugin-installed agents
            for p in self._get_plugin_install_paths():
                try:
                    agents_dir = p / "agents"
                    if agents_dir.is_dir():
                        for f in agents_dir.iterdir():
                            if f.suffix == ".md" and not f.name.startswith('.') and f.is_file():
                                agents[f.stem] = f
                except (OSError, ValueError):
                    pass

        if self.scope in ("project", "all") and self.project_dir:
            proj_agents = self.project_dir / ".claude" / "agents"
            if proj_agents.is_dir():
                for f in proj_agents.iterdir():
                    try:
                        if f.suffix == ".md" and not f.name.startswith('.') and f.is_file():
                            agents[f.stem] = f
                    except OSError:
                        pass

        return agents

    def get_commands(self) -> dict[str, Path]:
        """
        Discover Claude Code slash commands (SRC-04).

        Returns:
            Dictionary mapping command_name -> path_to_md_file
            Includes commands from ~/.claude/commands/ and project .claude/commands/

        Note:
            - Hidden files (starting with .) are filtered out
            - Only .md files are included
            - Non-file entries (directories) are skipped
        """
        commands = {}

        if self.scope in ("user", "all"):
            if self.cc_commands.is_dir():
                for f in self.cc_commands.iterdir():
                    try:
                        # Skip hidden files and non-.md files
                        if f.suffix == ".md" and not f.name.startswith('.') and f.is_file():
                            commands[f.stem] = f
                    except OSError:
                        pass

            # Plugin-installed commands
            for p in self._get_plugin_install_paths():
                try:
                    commands_dir = p / "commands"
                    if commands_dir.is_dir():
                        for f in commands_dir.iterdir():
                            if f.suffix == ".md" and not f.name.startswith('.') and f.is_file():
                                commands[f.stem] = f
                except (OSError, ValueError):
                    pass

        if self.scope in ("project", "all") and self.project_dir:
            proj_cmds = self.project_dir / ".claude" / "commands"
            if proj_cmds.is_dir():
                for f in proj_cmds.iterdir():
                    try:
                        if f.suffix == ".md" and not f.name.startswith('.') and f.is_file():
                            commands[f.stem] = f
                    except OSError:
                        pass

        return commands

    def _get_enabled_plugins(self) -> set[str]:
        """Return set of enabled plugin identifiers from settings.json."""
        enabled = set()

        # User-scope settings
        if self.cc_settings.exists():
            settings = read_json_safe(self.cc_settings)
            enabled_plugins = settings.get("enabledPlugins", {})
            if isinstance(enabled_plugins, dict):
                for plugin_key, is_enabled in enabled_plugins.items():
                    if is_enabled:
                        enabled.add(plugin_key)

        # Project-scope settings (if applicable)
        if self.project_dir and self.scope in ("project", "all"):
            proj_settings = self.project_dir / ".claude" / "settings.json"
            if proj_settings.exists():
                settings = read_json_safe(proj_settings)
                enabled_plugins = settings.get("enabledPlugins", {})
                if isinstance(enabled_plugins, dict):
                    for plugin_key, is_enabled in enabled_plugins.items():
                        if is_enabled:
                            enabled.add(plugin_key)
                        elif plugin_key in enabled:
                            enabled.discard(plugin_key)

        return enabled

    def _expand_plugin_root(self, config: dict, plugin_path: Path) -> dict:
        """Expand ${CLAUDE_PLUGIN_ROOT} in MCP server config."""
        config_str = json.dumps(config)
        config_str = config_str.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_path))
        return json.loads(config_str)

    def _get_plugin_mcp_servers(self) -> dict[str, dict]:
        """Discover MCP servers from installed Claude Code plugins."""
        servers = {}

        if not self.cc_plugins_registry.exists():
            return servers

        registry = read_json_safe(self.cc_plugins_registry)
        plugins = registry.get("plugins", {})
        if not isinstance(plugins, dict):
            return servers

        # Build set of explicitly disabled plugins from settings
        disabled_plugins = set()
        if self.cc_settings.exists():
            settings = read_json_safe(self.cc_settings)
            ep = settings.get("enabledPlugins", {})
            if isinstance(ep, dict):
                disabled_plugins = {k for k, v in ep.items() if v is False}

        for plugin_key, installs in plugins.items():
            # Version 2 format: plugin_key -> list of install entries
            if not isinstance(installs, list):
                installs = [installs]

            for install in installs:
                if not isinstance(install, dict):
                    continue

                # Skip only explicitly disabled plugins
                if plugin_key in disabled_plugins:
                    continue

                install_path_str = install.get("installPath", "")
                if not install_path_str:
                    continue

                try:
                    install_path = Path(install_path_str)
                    if not install_path.exists():
                        continue
                except (ValueError, OSError):
                    continue

                plugin_mcps = {}

                # Method 1: Standalone .mcp.json at plugin root
                mcp_json_path = install_path / ".mcp.json"
                if mcp_json_path.exists():
                    data = read_json_safe(mcp_json_path)
                    if isinstance(data, dict):
                        # Handle both flat and nested formats
                        if "mcpServers" in data and isinstance(data["mcpServers"], dict):
                            plugin_mcps.update(data["mcpServers"])
                        else:
                            plugin_mcps.update(data)

                # Method 2: Inline mcpServers in plugin.json
                for plugin_json_path in [
                    install_path / ".claude-plugin" / "plugin.json",
                    install_path / "plugin.json",
                ]:
                    if plugin_json_path.exists():
                        plugin_data = read_json_safe(plugin_json_path)
                        inline_mcps = plugin_data.get("mcpServers", {})
                        if isinstance(inline_mcps, dict):
                            plugin_mcps.update(inline_mcps)
                        break  # Only check first found

                # Expand variables and tag with metadata
                plugin_name = plugin_key.split("@")[0]
                plugin_version = install.get("version", "unknown")

                for server_name, config in plugin_mcps.items():
                    if not isinstance(config, dict):
                        continue
                    expanded = self._expand_plugin_root(config, install_path)
                    expanded["_plugin_name"] = plugin_name
                    expanded["_plugin_version"] = plugin_version
                    expanded["_source"] = "plugin"
                    servers[server_name] = expanded

        return servers

    def _get_user_scope_mcps(self) -> dict[str, dict]:
        """Read user-scope MCPs from cc_home/.claude.json and cc_home/.mcp.json."""
        valid = {}

        # Source 1: cc_home/.claude.json top-level mcpServers
        claude_json = self.cc_home / ".claude.json"
        if claude_json.exists():
            data = read_json_safe(claude_json)
            mcp_servers = data.get("mcpServers", {})
            if isinstance(mcp_servers, dict):
                for name, config in mcp_servers.items():
                    if isinstance(config, dict) and (config.get("command") or config.get("url") or config.get("type")):
                        valid[name] = config

        # Source 2: cc_home/.mcp.json (if it exists)
        if self.cc_mcp_claude.exists():
            data = read_json_safe(self.cc_mcp_claude)
            if isinstance(data, dict):
                mcp_servers = data.get("mcpServers", data) if "mcpServers" in data else data
                if isinstance(mcp_servers, dict):
                    for name, config in mcp_servers.items():
                        if name not in valid and isinstance(config, dict) and (config.get("command") or config.get("url") or config.get("type")):
                            valid[name] = config

        return valid

    def _get_project_scope_mcps(self) -> dict[str, dict]:
        """Read project-scope MCPs from .mcp.json in project root."""
        if not self.project_dir:
            return {}

        proj_mcp = self.project_dir / ".mcp.json"
        if not proj_mcp.exists():
            return {}

        data = read_json_safe(proj_mcp)
        mcp_servers = data.get("mcpServers", {})
        if not isinstance(mcp_servers, dict):
            return {}

        valid = {}
        for name, config in mcp_servers.items():
            if isinstance(config, dict) and (config.get("command") or config.get("url")):
                valid[name] = config
        return valid

    def _get_local_scope_mcps(self) -> dict[str, dict]:
        """Read local-scope MCPs from cc_home/.claude.json projects[absolutePath].mcpServers."""
        if not self.project_dir:
            return {}

        claude_json = self.cc_home / ".claude.json"
        if not claude_json.exists():
            return {}

        data = read_json_safe(claude_json)
        projects = data.get("projects", {})
        if not isinstance(projects, dict):
            return {}

        project_key = str(self.project_dir.resolve())
        project_config = projects.get(project_key, {})
        if not isinstance(project_config, dict):
            return {}

        mcp_servers = project_config.get("mcpServers", {})
        if not isinstance(mcp_servers, dict):
            return {}

        valid = {}
        for name, config in mcp_servers.items():
            if isinstance(config, dict) and (config.get("command") or config.get("url")):
                valid[name] = config
        return valid

    def get_mcp_servers_with_scope(self) -> dict[str, dict]:
        """
        Discover all MCP servers with scope metadata and precedence resolution.

        Returns:
            Dictionary mapping server_name -> {"config": {...}, "metadata": {...}}
            Metadata includes: scope (user/project/local), source (file/plugin),
            and optionally plugin_name/plugin_version for plugin sources.

        Precedence: local > project > user (higher scope overrides lower).
        Plugin MCPs are treated as user-scope.
        """
        servers = {}

        # Layer 1 (lowest precedence): User-scope file-based MCPs
        if self.scope in ("user", "all"):
            for name, config in self._get_user_scope_mcps().items():
                servers[name] = {
                    "config": config,
                    "metadata": {"scope": "user", "source": "file"},
                }

        # Layer 2 (same precedence as user): Plugin MCPs
        if self.scope in ("user", "all"):
            for name, config in self._get_plugin_mcp_servers().items():
                if name not in servers:  # File-based user MCPs have priority
                    # Extract and remove underscore-prefixed metadata from config
                    clean_config = {k: v for k, v in config.items() if not k.startswith("_")}
                    plugin_name = config.get("_plugin_name", "unknown")
                    plugin_version = config.get("_plugin_version", "unknown")
                    servers[name] = {
                        "config": clean_config,
                        "metadata": {
                            "scope": "user",
                            "source": "plugin",
                            "plugin_name": plugin_name,
                            "plugin_version": plugin_version,
                        },
                    }

        # Layer 3 (overrides user): Project-scope MCPs
        if self.scope in ("project", "all") and self.project_dir:
            for name, config in self._get_project_scope_mcps().items():
                servers[name] = {
                    "config": config,
                    "metadata": {"scope": "project", "source": "file"},
                }

        # Layer 4 (highest precedence): Local-scope MCPs
        if self.scope in ("project", "all") and self.project_dir:
            for name, config in self._get_local_scope_mcps().items():
                servers[name] = {
                    "config": config,
                    "metadata": {"scope": "local", "source": "file"},
                }

        return servers

    def get_mcp_servers(self) -> dict[str, dict]:
        """
        Read MCP server configurations (SRC-05).

        Returns:
            Dictionary mapping server_name -> server_config_dict
            Backward-compatible flat dict without metadata.

        Note:
            - Internally uses get_mcp_servers_with_scope() for layered discovery
            - Malformed entries (missing command/url) are filtered out
            - Supports both stdio (command/args) and url-based servers
        """
        scoped = self.get_mcp_servers_with_scope()
        return {name: entry["config"] for name, entry in scoped.items()}

    def get_settings(self) -> dict:
        """
        Read Claude Code settings with merge (SRC-06).

        Returns:
            Merged settings dict
            User settings + project settings + project local settings
            Later files override earlier ones.

        Note:
            - Non-dict settings files are skipped (returns empty dict for that file)
            - settings.local.json has highest priority (overrides base settings)
            - Invalid JSON handled gracefully via read_json_safe
        """
        settings = {}

        if self.scope in ("user", "all"):
            # User settings (~/.claude/settings.json)
            if self.cc_settings.exists():
                user_settings = read_json_safe(self.cc_settings)
                if isinstance(user_settings, dict):
                    settings.update(user_settings)

        if self.scope in ("project", "all") and self.project_dir:
            # Project settings (.claude/settings.json)
            proj_settings = self.project_dir / ".claude" / "settings.json"
            if proj_settings.exists():
                proj_data = read_json_safe(proj_settings)
                if isinstance(proj_data, dict):
                    settings.update(proj_data)

            # Local settings (.claude/settings.local.json) - highest priority
            local_settings = self.project_dir / ".claude" / "settings.local.json"
            if local_settings.exists():
                local_data = read_json_safe(local_settings)
                if isinstance(local_data, dict):
                    settings.update(local_data)

        return settings

    def get_hooks(self) -> dict:
        """Discover hooks from settings.json and project-level hooks/hooks.json.

        Reads from two locations and normalizes to a common shape:
        1. settings.json -> 'hooks' key (new format: event-keyed arrays)
        2. Project-level hooks/hooks.json (legacy plugin format)

        User-scope hooks from settings.json come first; project-level hooks
        are merged after (duplicates by command+event are not deduplicated —
        both are kept).

        Returns:
            Dict with 'hooks' key containing a list of normalized hook dicts.
            Each hook dict has: event, type, command/url, matcher, timeout, scope.
        """
        hooks: list[dict] = []

        # Source 1: settings.json 'hooks' key (new format)
        # Format: {"hooks": {"PreToolUse": [{"type": "command", "command": "...", "matcher": "..."}], ...}}
        if self.scope in ("user", "all"):
            if self.cc_settings.exists():
                settings = read_json_safe(self.cc_settings)
                hooks_section = settings.get("hooks", {})
                if isinstance(hooks_section, dict):
                    for event, entries in hooks_section.items():
                        if not isinstance(entries, list):
                            continue
                        for entry in entries:
                            if not isinstance(entry, dict):
                                continue
                            hooks.append(self._normalize_settings_hook(entry, event, "user"))

        if self.scope in ("project", "all") and self.project_dir:
            proj_settings = self.project_dir / ".claude" / "settings.json"
            if proj_settings.exists():
                settings = read_json_safe(proj_settings)
                hooks_section = settings.get("hooks", {})
                if isinstance(hooks_section, dict):
                    for event, entries in hooks_section.items():
                        if not isinstance(entries, list):
                            continue
                        for entry in entries:
                            if not isinstance(entry, dict):
                                continue
                            hooks.append(self._normalize_settings_hook(entry, event, "project"))

        # Source 2: project-level hooks/hooks.json (legacy plugin format)
        # Format: {"hooks": {"PostToolUse": [{"matcher": "...", "hooks": [{"type": "command", "command": "..."}]}]}}
        if self.scope in ("project", "all") and self.project_dir:
            hooks_json = self.project_dir / "hooks" / "hooks.json"
            if hooks_json.exists():
                data = read_json_safe(hooks_json)
                hooks_section = data.get("hooks", {})
                if isinstance(hooks_section, dict):
                    for event, event_entries in hooks_section.items():
                        if not isinstance(event_entries, list):
                            continue
                        for group in event_entries:
                            if not isinstance(group, dict):
                                continue
                            matcher = group.get("matcher", "")
                            inner_hooks = group.get("hooks", [])
                            if not isinstance(inner_hooks, list):
                                continue
                            for hook_entry in inner_hooks:
                                if not isinstance(hook_entry, dict):
                                    continue
                                hooks.append(self._normalize_legacy_hook(hook_entry, event, matcher, "project"))

        return {"hooks": hooks}

    @staticmethod
    def _normalize_settings_hook(entry: dict, event: str, scope: str) -> dict:
        """Normalize a hook entry from settings.json format.

        Args:
            entry: Raw hook dict from settings.json (has type, command/url, matcher, timeout)
            event: Event name (e.g. 'PreToolUse')
            scope: 'user' or 'project'

        Returns:
            Normalized hook dict
        """
        hook_type = entry.get("type", "command")
        # Normalize type: "command" -> "shell"
        if hook_type == "command":
            hook_type = "shell"

        normalized: dict = {
            "event": event,
            "type": hook_type,
            "scope": scope,
        }

        if hook_type == "shell":
            normalized["command"] = entry.get("command", "")
        elif hook_type == "http":
            normalized["url"] = entry.get("url", "")

        if entry.get("matcher"):
            normalized["matcher"] = entry["matcher"]
        if entry.get("timeout"):
            normalized["timeout"] = entry["timeout"]

        return normalized

    @staticmethod
    def _normalize_legacy_hook(entry: dict, event: str, matcher: str, scope: str) -> dict:
        """Normalize a hook entry from legacy hooks/hooks.json format.

        Args:
            entry: Raw hook dict from hooks.json (has type, command)
            event: Event name (e.g. 'PostToolUse')
            matcher: Matcher string from parent group (e.g. 'Edit|Write')
            scope: 'user' or 'project'

        Returns:
            Normalized hook dict
        """
        hook_type = entry.get("type", "command")
        # Normalize type: "command" -> "shell"
        if hook_type == "command":
            hook_type = "shell"

        normalized: dict = {
            "event": event,
            "type": hook_type,
            "scope": scope,
        }

        if hook_type == "shell":
            normalized["command"] = entry.get("command", "")
        elif hook_type == "http":
            normalized["url"] = entry.get("url", "")

        if matcher:
            normalized["matcher"] = matcher
        if entry.get("timeout"):
            normalized["timeout"] = entry["timeout"]

        return normalized

    def get_permissions(self) -> dict:
        """Extract structured permissions from Claude Code settings.

        Convenience method that calls :meth:`get_settings` and then
        :func:`extract_permissions` to return a pre-extracted permissions
        dict. This is provided as a dedicated key in :meth:`discover_all`
        so adapters can consume permissions directly without digging into
        the nested ``settings["permissions"]`` structure.

        Returns:
            Dict with keys ``"allow"``, ``"deny"``, ``"ask"``, each
            mapping to a list of permission strings. Always returns
            all three keys (empty lists if no permissions configured).
        """
        try:
            settings = self.get_settings()
            return extract_permissions(settings)
        except Exception:
            return {"allow": [], "deny": [], "ask": []}

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
        unconditionally — callers should treat the empty string as "no override".

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
        returns a mapping of harness name → block content.  Empty if CLAUDE.md
        has no inline blocks.

        Returns:
            Dict mapping harness name → extracted block content.
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
            mcp_servers (flat), mcp_servers_scoped (with metadata), settings
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
            - NEW method added in Task 2 for state manager integration
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


# ─────────────────────────────────────────────────────────────────────────────
# Config Variable Substitution (Item 9)
# ─────────────────────────────────────────────────────────────────────────────
#
# Supports ${VAR} placeholders in CLAUDE.md and skills that are substituted
# with project-specific or user-specific values before syncing to each harness.
#
# Built-in variables resolved automatically:
#   ${PROJECT_NAME}   — git repo name (basename of git root) or project_dir name
#   ${GIT_USER}       — git config user.name
#   ${GIT_EMAIL}      — git config user.email
#   ${REPO_URL}       — git remote origin URL
#   ${BRANCH}         — current git branch name
#   ${HOME}           — user home directory
#
# Custom variables can be declared in .harnesssync under "vars":
#   {"vars": {"CLIENT": "Acme Corp", "TICKET_PREFIX": "ACME"}}


import os as _os
import subprocess as _subprocess


def _run_git_field(args: list[str], cwd: str | None = None) -> str:
    """Run a git command and return stripped stdout, or empty string on failure."""
    try:
        result = _subprocess.run(
            args, capture_output=True, text=True, timeout=3, cwd=cwd
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, _subprocess.TimeoutExpired, OSError):
        return ""


def _resolve_builtin_vars(project_dir: Path | None = None) -> dict[str, str]:
    """Resolve built-in config variables from git and environment.

    Args:
        project_dir: Project root for git commands. Falls back to cwd.

    Returns:
        Dict of variable name -> resolved value (all strings).
        Variables that cannot be resolved are set to empty string.
    """
    cwd = str(project_dir) if project_dir else None

    git_root = _run_git_field(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    project_name = Path(git_root).name if git_root else (
        project_dir.name if project_dir else _os.path.basename(_os.getcwd())
    )

    return {
        "PROJECT_NAME": project_name,
        "GIT_USER": _run_git_field(["git", "config", "user.name"], cwd=cwd),
        "GIT_EMAIL": _run_git_field(["git", "config", "user.email"], cwd=cwd),
        "REPO_URL": _run_git_field(
            ["git", "remote", "get-url", "origin"], cwd=cwd
        ),
        "BRANCH": _run_git_field(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd
        ),
        "HOME": str(Path.home()),
    }


def _load_custom_vars(project_dir: Path | None = None) -> dict[str, str]:
    """Load custom variables from .harnesssync 'vars' key.

    Args:
        project_dir: Directory containing .harnesssync config.

    Returns:
        Dict of var_name -> value from config, or empty dict.
    """
    if not project_dir:
        return {}
    harnesssync = project_dir / ".harnesssync"
    if not harnesssync.is_file():
        return {}
    try:
        data = json.loads(harnesssync.read_text(encoding="utf-8"))
        raw = data.get("vars", {})
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {}


_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def substitute_config_vars(
    content: str,
    project_dir: Path | None = None,
    extra_vars: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Substitute ${VAR} placeholders in config content.

    Resolution order (highest priority wins):
    1. ``extra_vars`` passed directly
    2. Custom vars from .harnesssync ``vars`` key
    3. Built-in vars (PROJECT_NAME, GIT_USER, REPO_URL, BRANCH, HOME, GIT_EMAIL)

    Unresolved placeholders are left as-is (not substituted) so that
    harness-specific ${ENV_VAR} references are preserved for the target tool.

    Args:
        content:     String content with optional ${VAR} placeholders.
        project_dir: Project root for git resolution and .harnesssync loading.
        extra_vars:  Additional variables to inject (highest priority).

    Returns:
        Tuple of (substituted_content, list_of_substituted_var_names).
        The second element lists which variables were actually replaced.
    """
    builtin = _resolve_builtin_vars(project_dir)
    custom = _load_custom_vars(project_dir)
    # Merge: extra_vars > custom > builtin
    merged: dict[str, str] = {**builtin, **custom, **(extra_vars or {})}

    substituted: list[str] = []

    def _replace(m: re.Match) -> str:
        name = m.group(1)
        if name in merged and merged[name]:
            substituted.append(name)
            return merged[name]
        return m.group(0)  # Leave unresolved placeholders intact

    result = _VAR_PATTERN.sub(_replace, content)
    return result, substituted
