from __future__ import annotations

"""Continue.dev adapter for HarnessSync.

Syncs Claude Code configuration to Continue.dev format:
- Rules (CLAUDE.md) → .continue/rules/harnesssync.md
- Skills → .continue/rules/skills/<name>.md
- Agents → .continue/prompts/<name>.prompt (Continue prompt files)
- Commands → .continue/prompts/<name>.prompt
- MCP servers → .continue/config.json (mcpServers section)
- Settings → no-op (managed by Continue extension)

Continue.dev (continue.dev) is widely used in VS Code and JetBrains.
Rules live in .continue/rules/ and are injected as context into every session.
MCP servers are declared in .continue/config.json under mcpServers.
Agent/command prompts go in .continue/prompts/ as .prompt files.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import ensure_dir


CONTINUE_DIR = ".continue"
RULES_DIR = ".continue/rules"
PROMPTS_DIR = ".continue/prompts"
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
        self.config_path = project_dir / CONFIG_JSON

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
                out_path.write_text(f"# Skill: {name}\n\n{content}\n", encoding="utf-8")
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
        """Sync MCP servers to .continue/config.json mcpServers section.

        Continue uses the standard MCP mcpServers JSON format embedded in
        its main config.json file alongside model configuration.
        """
        if not mcp_servers:
            return SyncResult(skipped=1, skipped_files=[f"{CONFIG_JSON}: no MCP servers"])

        ensure_dir(self.continue_dir)

        # Load existing config.json to preserve non-MCP settings
        existing: dict = {}
        if self.config_path.is_file():
            try:
                existing = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        mcp_data: dict[str, dict] = {}
        for name, cfg in mcp_servers.items():
            server_entry: dict = {}
            cmd = cfg.get("command") or cfg.get("cmd")
            if cmd:
                server_entry["command"] = cmd
            args = cfg.get("args", [])
            if args:
                server_entry["args"] = args
            env = cfg.get("env", {})
            if env:
                server_entry["env"] = env
            url = cfg.get("url")
            if url:
                server_entry["url"] = url
                server_entry["transport"] = "sse"
            mcp_data[name] = server_entry

        existing["mcpServers"] = mcp_data

        try:
            import tempfile
            import os
            ensure_dir(self.continue_dir)
            temp_fd = tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.continue_dir,
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            )
            temp_path = Path(temp_fd.name)
            json.dump(existing, temp_fd, indent=2, ensure_ascii=False)
            temp_fd.write("\n")
            temp_fd.flush()
            os.fsync(temp_fd.fileno())
            temp_fd.close()
            os.replace(str(temp_path), str(self.config_path))
            return SyncResult(synced=len(mcp_data), synced_files=[str(self.config_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"{CONFIG_JSON}: {e}"])

    def sync_settings(self, settings: dict) -> SyncResult:
        """Settings sync is a no-op for Continue.dev (managed by extension)."""
        return SyncResult(skipped=1, skipped_files=["continue: settings managed by extension"])
