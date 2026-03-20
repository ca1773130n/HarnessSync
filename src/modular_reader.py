from __future__ import annotations

"""Modular config discovery methods for SourceReader.

Provides ModularReaderMixin with methods to discover skills, agents,
commands, settings, hooks, and permissions from Claude Code configuration.
"""

from pathlib import Path
from src.utils.paths import read_json_safe
from src.utils.permissions import extract_permissions


class ModularReaderMixin:
    """Mixin providing skills/agents/commands/settings/hooks/permissions discovery.

    Expects the following attributes on self (set by SourceReader.__init__):
    - cc_home: Path
    - cc_settings: Path
    - cc_skills: Path
    - cc_agents: Path
    - cc_commands: Path
    - project_dir: Path | None
    - scope: str

    Also expects _get_plugin_install_paths() from MCPReaderMixin.
    """

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
        are merged after (duplicates by command+event are not deduplicated --
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
