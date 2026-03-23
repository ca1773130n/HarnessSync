from __future__ import annotations

"""Continue.dev adapter for HarnessSync.

Syncs Claude Code configuration to Continue.dev format:
- Rules (CLAUDE.md) → .continue/rules/harnesssync.md (with YAML frontmatter)
- Skills → .continue/rules/skills/<name>.md (with YAML frontmatter)
- Agents → .continue/prompts/<name>.prompt (Continue prompt files)
- Commands → .continue/prompts/<name>.prompt
- MCP servers → .continue/config.yaml (primary, YAML list format)
                 .continue/config.json (fallback if config.yaml absent)
- Settings → no-op (managed by Continue extension)

Continue.dev (continue.dev) is widely used in VS Code and JetBrains.
Rules live in .continue/rules/ and are injected as context into every session.
MCP servers are declared in config.yaml under mcpServers as a list of objects
with name, command, args, cwd, env keys (not a dict keyed by name).
Falls back to config.json dict format when config.yaml doesn't exist.
Agent/command prompts go in .continue/prompts/ as .prompt files.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import ensure_dir, write_json_atomic


CONTINUE_DIR = ".continue"
RULES_DIR = ".continue/rules"
PROMPTS_DIR = ".continue/prompts"
CONFIG_YAML = ".continue/config.yaml"
CONFIG_JSON = ".continue/config.json"

HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"


@AdapterRegistry.register("continue")
class ContinueDevAdapter(AdapterBase):
    """Adapter for Continue.dev AI coding assistant configuration sync."""

    def __init__(self, project_dir: Path):
        super().__init__(project_dir)
        self.continue_dir = project_dir / CONTINUE_DIR
        self.rules_dir = project_dir / RULES_DIR
        self.prompts_dir = project_dir / PROMPTS_DIR
        self.config_yaml_path = project_dir / CONFIG_YAML
        self.config_json_path = project_dir / CONFIG_JSON

    @property
    def target_name(self) -> str:
        return "continue"

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync rules to .continue/rules/harnesssync.md.

        Continue reads all .md files in .continue/rules/ as persistent context
        injected into every AI session.
        """
        if not rules:
            return SyncResult(skipped=1, skipped_files=[f"{RULES_DIR}: no rules to sync"])

        rule_contents = [r.get("content", "") for r in rules if r.get("content", "").strip()]
        if not rule_contents:
            return SyncResult(skipped=1, skipped_files=[f"{RULES_DIR}: empty rules"])

        ensure_dir(self.rules_dir)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        concatenated = "\n\n---\n\n".join(rule_contents)

        rules_path = self.rules_dir / "harnesssync.md"
        content = (
            f"---\n"
            f"name: HarnessSync Rules\n"
            f"alwaysApply: true\n"
            f"description: Rules synced from Claude Code by HarnessSync\n"
            f"---\n\n"
            f"{HARNESSSYNC_MARKER}\n"
            f"# Rules (synced from Claude Code by HarnessSync)\n\n"
            f"{concatenated}\n\n"
            f"---\n"
            f"*Last synced: {timestamp}*\n"
            f"{HARNESSSYNC_MARKER_END}\n"
        )

        try:
            rules_path.write_text(content, encoding="utf-8")
            return SyncResult(synced=1, synced_files=[str(rules_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"{RULES_DIR}/harnesssync.md: {e}"])

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to .continue/rules/skills/ as markdown context files."""
        if not skills:
            return SyncResult(skipped=1, skipped_files=[f"{RULES_DIR}/skills/: no skills"])

        skills_dir = self.rules_dir / "skills"
        ensure_dir(skills_dir)
        synced = 0
        failed = 0
        failed_files: list[str] = []

        for name, skill_path in skills.items():
            skill_md = skill_path / "SKILL.md" if skill_path.is_dir() else skill_path
            if not skill_md.is_file():
                failed += 1
                failed_files.append(f"{name}: SKILL.md not found")
                continue
            try:
                content = skill_md.read_text(encoding="utf-8")
                out_path = skills_dir / f"{name}.md"
                quoted_name = self._quote_yaml_value(name)
                quoted_desc = self._quote_yaml_value(f"Skill '{name}' synced from Claude Code")
                out_path.write_text(
                    f"---\n"
                    f"name: {quoted_name}\n"
                    f"alwaysApply: true\n"
                    f"description: {quoted_desc}\n"
                    f"---\n\n"
                    f"# Skill: {name}\n\n{content}\n",
                    encoding="utf-8",
                )
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Sync agents to .continue/prompts/ as .prompt files.

        Continue supports .prompt files in .continue/prompts/ for slash commands
        and named prompts. Agent definitions are converted to this format.
        """
        if not agents:
            return SyncResult(skipped=1, skipped_files=[f"{PROMPTS_DIR}/: no agents"])

        ensure_dir(self.prompts_dir)
        synced = 0
        failed = 0
        failed_files: list[str] = []

        for name, agent_path in agents.items():
            agent_md = agent_path if agent_path.is_file() else agent_path / f"{name}.md"
            if not agent_md.is_file():
                failed += 1
                failed_files.append(f"{name}: agent file not found")
                continue
            try:
                content = agent_md.read_text(encoding="utf-8")
                adapted = self.adapt_command_content(content)
                out_path = self.prompts_dir / f"{name}.prompt"
                out_path.write_text(
                    f"name: {name}\ndescription: Agent from Claude Code\n---\n\n{adapted}\n",
                    encoding="utf-8",
                )
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Sync commands to .continue/prompts/ as .prompt files."""
        if not commands:
            return SyncResult(skipped=1, skipped_files=[f"{PROMPTS_DIR}/: no commands"])

        ensure_dir(self.prompts_dir)
        synced = 0
        failed = 0
        failed_files: list[str] = []

        for name, cmd_path in commands.items():
            cmd_md = cmd_path if cmd_path.is_file() else cmd_path / f"{name}.md"
            if not cmd_md.is_file():
                failed += 1
                failed_files.append(f"{name}: command file not found")
                continue
            try:
                content = cmd_md.read_text(encoding="utf-8")
                adapted = self.adapt_command_content(content)
                out_path = self.prompts_dir / f"cmd-{name}.prompt"
                out_path.write_text(
                    f"name: {name}\ndescription: Command from Claude Code\n---\n\n{adapted}\n",
                    encoding="utf-8",
                )
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Sync MCP servers to .continue/config.yaml (primary) or config.json (fallback).

        Continue now prefers config.yaml with mcpServers as a list of objects
        (each with name, command, args, cwd, env). Falls back to config.json
        dict format if config.yaml doesn't exist and config.json does.
        """
        if not mcp_servers:
            return SyncResult(skipped=1, skipped_files=[f"{CONFIG_YAML}: no MCP servers"])

        ensure_dir(self.continue_dir)

        # Decide format before building entries to avoid constructing both
        use_yaml = self.config_yaml_path.is_file() or not self.config_json_path.is_file()

        # Build server entries in the needed format only
        entries: list[dict] = []
        for name, cfg in mcp_servers.items():
            entry: dict = {}
            if use_yaml:
                entry["name"] = name
            cmd = cfg.get("command") or cfg.get("cmd")
            if cmd:
                entry["command"] = cmd
            args = cfg.get("args", [])
            if args:
                entry["args"] = args
            cwd = cfg.get("cwd")
            if cwd:
                entry["cwd"] = cwd
            env = cfg.get("env", {})
            if env:
                entry["env"] = env
            url = cfg.get("url")
            if url:
                entry["url"] = url
                entry["transport"] = "sse"
            entries.append(entry)

        if use_yaml:
            return self._write_mcp_yaml(entries)
        else:
            mcp_dict = {e.pop("name", name): e for name, e in zip(mcp_servers, entries)}
            return self._write_mcp_json(mcp_dict)

    def _write_mcp_yaml(self, mcp_entries: list[dict]) -> SyncResult:
        """Write MCP servers to config.yaml in Continue's list format."""
        existing_lines: list[str] = []
        if self.config_yaml_path.is_file():
            try:
                raw = self.config_yaml_path.read_text(encoding="utf-8")
                existing_lines = self._remove_yaml_section(raw, "mcpServers")
            except OSError:
                existing_lines = []

        yaml_lines = list(existing_lines)  # avoid mutating the source list
        yaml_lines.append("mcpServers:")
        for entry in mcp_entries:
            yaml_lines.append(f"  - name: {self._quote_yaml_value(entry['name'])}")
            if "command" in entry:
                yaml_lines.append(f"    command: {self._quote_yaml_value(entry['command'])}")
            if "args" in entry:
                yaml_lines.append("    args:")
                for arg in entry["args"]:
                    yaml_lines.append(f"      - {self._quote_yaml_value(str(arg))}")
            if "cwd" in entry:
                yaml_lines.append(f"    cwd: {self._quote_yaml_value(entry['cwd'])}")
            if "env" in entry:
                yaml_lines.append("    env:")
                for k, v in entry["env"].items():
                    yaml_lines.append(f"      {k}: {self._quote_yaml_value(str(v))}")
            if "url" in entry:
                yaml_lines.append(f"    url: {self._quote_yaml_value(entry['url'])}")
                yaml_lines.append(f"    transport: sse")

        try:
            yaml_content = "\n".join(yaml_lines) + "\n"
            # Atomic write via temp file + rename
            tmp = self.config_yaml_path.with_suffix(".tmp")
            tmp.write_text(yaml_content, encoding="utf-8")
            os.replace(str(tmp), str(self.config_yaml_path))
            return SyncResult(synced=len(mcp_entries), synced_files=[str(self.config_yaml_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"{CONFIG_YAML}: {e}"])

    def _write_mcp_json(self, mcp_data: dict[str, dict]) -> SyncResult:
        """Write MCP servers to config.json in Continue's legacy dict format."""
        existing: dict = {}
        if self.config_json_path.is_file():
            try:
                existing = json.loads(self.config_json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        existing["mcpServers"] = mcp_data

        try:
            write_json_atomic(self.config_json_path, existing)
            return SyncResult(synced=len(mcp_data), synced_files=[str(self.config_json_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"{CONFIG_JSON}: {e}"])

    @staticmethod
    def _remove_yaml_section(raw: str, section: str) -> list[str]:
        """Remove a top-level YAML section and return remaining lines.

        Strips the section key and all indented lines beneath it.
        """
        result: list[str] = []
        lines = raw.splitlines()
        in_section = False
        for line in lines:
            if line.rstrip() == f"{section}:" or line.startswith(f"{section}:"):
                in_section = True
                continue
            if in_section:
                # Still inside the section if line is indented or blank
                if line == "" or line[0] in (" ", "\t"):
                    continue
                else:
                    in_section = False
            if not in_section:
                result.append(line)
        return result

    def sync_settings(self, settings: dict) -> SyncResult:
        """Settings sync is a no-op for Continue.dev (managed by extension)."""
        return SyncResult(skipped=1, skipped_files=["continue: settings managed by extension"])
