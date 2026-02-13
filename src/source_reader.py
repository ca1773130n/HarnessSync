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

from pathlib import Path
from src.utils.paths import read_json_safe


class SourceReader:
    """
    Discovers Claude Code configuration from user and project scopes.

    Scope options:
    - "user": Only read from ~/.claude/
    - "project": Only read from project directory
    - "all": Read from both user and project (merged)
    """

    def __init__(self, scope: str = "all", project_dir: Path = None):
        """
        Initialize SourceReader.

        Args:
            scope: "user" | "project" | "all"
            project_dir: Path to project root (required for "project" or "all")
        """
        self.scope = scope
        self.project_dir = project_dir

        # Claude Code base paths (user scope)
        self.cc_home = Path.home() / ".claude"
        self.cc_settings = self.cc_home / "settings.json"
        self.cc_plugins_registry = self.cc_home / "plugins" / "installed_plugins.json"
        self.cc_skills = self.cc_home / "skills"
        self.cc_agents = self.cc_home / "agents"
        self.cc_commands = self.cc_home / "commands"
        self.cc_mcp_global = Path.home() / ".mcp.json"
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

    def get_mcp_servers(self) -> dict[str, dict]:
        """
        Read MCP server configurations (SRC-05).

        Returns:
            Dictionary mapping server_name -> server_config_dict
            Merges configs from ~/.mcp.json, ~/.claude/.mcp.json, and project .mcp.json
            Later configs override earlier ones.

        Note:
            - Malformed entries (missing command/url) are filtered out
            - Supports both stdio (command/args) and url-based servers
            - Invalid JSON files are handled gracefully (returns empty dict)
        """
        servers = {}

        if self.scope in ("user", "all"):
            # Global MCP (~/.mcp.json)
            if self.cc_mcp_global.exists():
                data = read_json_safe(self.cc_mcp_global)
                mcp_servers = data.get("mcpServers", {})
                if isinstance(mcp_servers, dict):
                    # Filter out malformed entries (no command or url)
                    for name, config in mcp_servers.items():
                        if isinstance(config, dict) and (config.get("command") or config.get("url")):
                            servers[name] = config

            # Claude MCP (~/.claude/.mcp.json) - overrides global
            if self.cc_mcp_claude.exists():
                data = read_json_safe(self.cc_mcp_claude)
                mcp_servers = data.get("mcpServers", {})
                if isinstance(mcp_servers, dict):
                    for name, config in mcp_servers.items():
                        if isinstance(config, dict) and (config.get("command") or config.get("url")):
                            servers[name] = config

        if self.scope in ("project", "all") and self.project_dir:
            proj_mcp = self.project_dir / ".mcp.json"
            if proj_mcp.exists():
                data = read_json_safe(proj_mcp)
                mcp_servers = data.get("mcpServers", {})
                if isinstance(mcp_servers, dict):
                    for name, config in mcp_servers.items():
                        if isinstance(config, dict) and (config.get("command") or config.get("url")):
                            servers[name] = config

        return servers

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
        Convenience method to get all 6 config types at once.

        Returns:
            Dictionary with keys: rules, skills, agents, commands, mcp_servers, settings
        """
        return {
            "rules": self.get_rules(),
            "skills": self.get_skills(),
            "agents": self.get_agents(),
            "commands": self.get_commands(),
            "mcp_servers": self.get_mcp_servers(),
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
            if self.cc_mcp_global.exists():
                paths["mcp_servers"].append(self.cc_mcp_global)
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
