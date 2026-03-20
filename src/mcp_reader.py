from __future__ import annotations

"""MCP server and plugin discovery for SourceReader.

Provides MCPReaderMixin with all MCP-related methods:
- Plugin install path discovery
- Plugin MCP server discovery
- User/project/local scope MCP server reading
- Layered MCP server resolution with precedence
- Plugin metadata and capability inspection
"""

import json
from pathlib import Path
from src.utils.paths import read_json_safe


class MCPReaderMixin:
    """Mixin providing MCP server and plugin discovery methods for SourceReader.

    Expects the following attributes on self (set by SourceReader.__init__):
    - cc_home: Path
    - cc_settings: Path
    - cc_plugins_registry: Path
    - cc_mcp_global: Path
    - cc_mcp_claude: Path
    - project_dir: Path | None
    - scope: str
    """

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

    def get_plugins(self) -> dict[str, dict]:
        """Discover Claude Code plugins with full metadata.

        Combines _get_enabled_plugins() and _get_plugin_install_paths() to
        return rich metadata for each installed plugin. Inspects each plugin's
        install directory for skills, agents, commands, MCP servers, and hooks.

        Returns:
            Dict mapping plugin_name -> {
                "enabled": bool,
                "version": str,
                "install_path": Path,
                "has_skills": bool,
                "has_agents": bool,
                "has_commands": bool,
                "has_mcp": bool,
                "has_hooks": bool,
                "manifest": dict,
            }
        """
        plugins: dict[str, dict] = {}

        if not self.cc_plugins_registry.exists():
            return plugins

        registry = read_json_safe(self.cc_plugins_registry)
        plugins_data = registry.get("plugins", {})
        if not isinstance(plugins_data, dict):
            return plugins

        # Get set of enabled plugin identifiers
        enabled_set = self._get_enabled_plugins()

        # Cache settings for enabledPlugins lookup (avoid re-reading inside loop)
        settings_data = read_json_safe(self.cc_settings) if self.cc_settings.exists() else {}
        ep = settings_data.get("enabledPlugins", {}) if isinstance(settings_data, dict) else {}

        for plugin_key, installs in plugins_data.items():
            if not isinstance(installs, list):
                installs = [installs]

            for install in installs:
                if not isinstance(install, dict):
                    continue

                install_path_str = install.get("installPath", "")
                if not install_path_str:
                    continue

                try:
                    install_path = Path(install_path_str)
                    if not install_path.exists():
                        continue
                except (OSError, ValueError):
                    continue

                # Extract plugin name (strip version suffix like "@1.0.0")
                plugin_name = plugin_key.split("@")[0]
                version = install.get("version", "unknown")

                # Determine enabled status: check if explicitly listed in enabledPlugins
                # _get_enabled_plugins returns only explicitly enabled ones.
                # A plugin is disabled only if explicitly set to False in settings.
                # If enabledPlugins doesn't mention this plugin at all, treat as enabled.
                is_enabled = True
                if isinstance(ep, dict):
                    # Check both plugin_name and plugin_key forms
                    if plugin_name in ep:
                        is_enabled = bool(ep[plugin_name])
                    elif plugin_key in ep:
                        is_enabled = bool(ep[plugin_key])

                # Inspect install directory for capabilities
                has_skills = (install_path / "skills").is_dir() and any(
                    (d / "SKILL.md").exists()
                    for d in (install_path / "skills").iterdir()
                    if d.is_dir()
                ) if (install_path / "skills").is_dir() else False

                has_agents = (install_path / "agents").is_dir() and any(
                    f.suffix == ".md" and f.is_file()
                    for f in (install_path / "agents").iterdir()
                ) if (install_path / "agents").is_dir() else False

                has_commands = (install_path / "commands").is_dir() and any(
                    f.suffix == ".md" and f.is_file()
                    for f in (install_path / "commands").iterdir()
                ) if (install_path / "commands").is_dir() else False

                has_mcp = (install_path / ".mcp.json").exists()
                if not has_mcp:
                    # Check for inline mcpServers in plugin.json
                    for pj in [
                        install_path / ".claude-plugin" / "plugin.json",
                        install_path / "plugin.json",
                    ]:
                        if pj.exists():
                            pj_data = read_json_safe(pj)
                            if pj_data.get("mcpServers"):
                                has_mcp = True
                            break

                has_hooks = False
                hooks_json = install_path / "hooks" / "hooks.json"
                if hooks_json.exists():
                    has_hooks = True
                else:
                    # Check plugin.json for hooks
                    for pj in [
                        install_path / ".claude-plugin" / "plugin.json",
                        install_path / "plugin.json",
                    ]:
                        if pj.exists():
                            pj_data = read_json_safe(pj)
                            if pj_data.get("hooks"):
                                has_hooks = True
                            break

                # Read manifest (plugin.json)
                manifest: dict = {}
                for pj in [
                    install_path / ".claude-plugin" / "plugin.json",
                    install_path / "plugin.json",
                ]:
                    if pj.exists():
                        manifest = read_json_safe(pj)
                        break

                plugins[plugin_name] = {
                    "enabled": is_enabled,
                    "version": version,
                    "install_path": install_path,
                    "has_skills": has_skills,
                    "has_agents": has_agents,
                    "has_commands": has_commands,
                    "has_mcp": has_mcp,
                    "has_hooks": has_hooks,
                    "manifest": manifest,
                }

        return plugins
