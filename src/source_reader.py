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
from pathlib import Path
from src.utils.paths import read_json_safe


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

    def get_rules(self) -> str:
        """
        Get combined CLAUDE.md rules content (SRC-01).

        Returns:
            Combined rules string with section headers, or empty string if none found.
            Multiple sections joined with "\\n\\n---\\n\\n".
        """
        rules = []

        if self.scope in ("user", "all"):
            # User-level CLAUDE.md
            user_claude_md = self.cc_home / "CLAUDE.md"
            if user_claude_md.exists():
                try:
                    content = user_claude_md.read_text(encoding='utf-8', errors='replace')
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
                        rules.append(f"# [Project rules from {claude_md_name}]\n\n{content}")
                    except (OSError, UnicodeDecodeError):
                        pass

            # Also check .claude/ subdirectory
            p = self.project_dir / ".claude" / "CLAUDE.md"
            if p.exists():
                try:
                    content = p.read_text(encoding='utf-8', errors='replace')
                    rules.append(f"# [Project rules from .claude/CLAUDE.md]\n\n{content}")
                except (OSError, UnicodeDecodeError):
                    pass

        return "\n\n---\n\n".join(rules)

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
            if self.cc_plugins_registry.exists():
                registry = read_json_safe(self.cc_plugins_registry)
                plugins_data = registry.get("plugins", {})

                # Handle both dict and list formats
                plugin_entries = []
                if isinstance(plugins_data, dict):
                    plugin_entries = plugins_data.values()
                elif isinstance(plugins_data, list):
                    plugin_entries = plugins_data

                for plugin_info in plugin_entries:
                    if not isinstance(plugin_info, dict):
                        continue
                    if plugin_info.get("scope") != "user":
                        continue
                    install_path = plugin_info.get("installPath", "")
                    if not install_path:
                        continue

                    try:
                        p = Path(install_path)
                        # Scan for skills inside the plugin
                        skills_dir = p / "skills"
                        if skills_dir.is_dir():
                            for d in skills_dir.iterdir():
                                if d.is_dir() and (d / "SKILL.md").exists():
                                    skills[d.name] = d
                    except (OSError, ValueError):
                        pass  # Invalid path or permission error

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
        """Read user-scope MCPs from ~/.claude.json top-level mcpServers."""
        claude_json = Path.home() / ".claude.json"
        if not claude_json.exists():
            return {}

        data = read_json_safe(claude_json)
        mcp_servers = data.get("mcpServers", {})
        if not isinstance(mcp_servers, dict):
            return {}

        valid = {}
        for name, config in mcp_servers.items():
            if isinstance(config, dict) and (config.get("command") or config.get("url")):
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
        """Read local-scope MCPs from ~/.claude.json projects[absolutePath].mcpServers."""
        if not self.project_dir:
            return {}

        claude_json = Path.home() / ".claude.json"
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

    def discover_all(self) -> dict:
        """
        Convenience method to get all config types at once.

        Returns:
            Dictionary with keys: rules, skills, agents, commands,
            mcp_servers (flat), mcp_servers_scoped (with metadata), settings
        """
        scoped = self.get_mcp_servers_with_scope()
        flat = {name: entry["config"] for name, entry in scoped.items()}
        return {
            "rules": self.get_rules(),
            "skills": self.get_skills(),
            "agents": self.get_agents(),
            "commands": self.get_commands(),
            "mcp_servers": flat,
            "mcp_servers_scoped": scoped,
            "settings": self.get_settings(),
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
            claude_json = Path.home() / ".claude.json"
            if claude_json.exists():
                paths["mcp_servers"].append(claude_json)

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
