from __future__ import annotations

"""Neovim AI adapter for HarnessSync (avante.nvim / codecompanion.nvim).

Syncs Claude Code configuration to Neovim AI plugin formats:
- Rules (CLAUDE.md) → .avante/system-prompt.md (avante.nvim system prompt)
- Rules (CLAUDE.md) → .codecompanion/system-prompt.md (codecompanion.nvim)
- Skills → .avante/rules/<name>.md (avante custom rules)
- Agents → .avante/rules/agents/<name>.md
- Commands → .codecompanion/slash-commands/<name>.md
- MCP servers → .avante/mcp.json (avante MCP config)
- Settings → no-op (managed by Neovim config)

Supported plugins:
  - avante.nvim: Uses .avante/ directory for per-project rules and system prompt
  - codecompanion.nvim: Uses .codecompanion/ for system prompts and slash commands

Both directories are written for maximum compatibility.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import ensure_dir


AVANTE_DIR = ".avante"
AVANTE_RULES_DIR = ".avante/rules"
AVANTE_SYSTEM_PROMPT = ".avante/system-prompt.md"
AVANTE_MCP_JSON = ".avante/mcp.json"

CODECOMPANION_DIR = ".codecompanion"
CODECOMPANION_SYSTEM_PROMPT = ".codecompanion/system-prompt.md"
CODECOMPANION_SLASH_COMMANDS_DIR = ".codecompanion/slash-commands"

HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"


@AdapterRegistry.register("neovim")
class NeovimAdapter(AdapterBase):
    """Adapter for Neovim AI plugins (avante.nvim, codecompanion.nvim)."""

    def __init__(self, project_dir: Path):
        super().__init__(project_dir)
        self.avante_dir = project_dir / AVANTE_DIR
        self.avante_rules_dir = project_dir / AVANTE_RULES_DIR
        self.avante_system_prompt_path = project_dir / AVANTE_SYSTEM_PROMPT
        self.avante_mcp_path = project_dir / AVANTE_MCP_JSON
        self.codecompanion_dir = project_dir / CODECOMPANION_DIR
        self.codecompanion_system_prompt_path = project_dir / CODECOMPANION_SYSTEM_PROMPT
        self.codecompanion_slash_commands_dir = project_dir / CODECOMPANION_SLASH_COMMANDS_DIR

    @property
    def target_name(self) -> str:
        return "neovim"

    def _replace_managed_section(self, existing: str, new_section: str) -> str:
        """Replace or append the HarnessSync-managed section."""
        if HARNESSSYNC_MARKER in existing and HARNESSSYNC_MARKER_END in existing:
            start = existing.index(HARNESSSYNC_MARKER)
            end = existing.index(HARNESSSYNC_MARKER_END) + len(HARNESSSYNC_MARKER_END)
            return existing[:start] + new_section + existing[end:]
        if existing.strip():
            return existing.rstrip() + "\n\n" + new_section + "\n"
        return new_section + "\n"

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync rules to avante.nvim and codecompanion.nvim system prompt files.

        Both .avante/system-prompt.md and .codecompanion/system-prompt.md are
        written so users get coverage regardless of which plugin they use.
        """
        if not rules:
            return SyncResult(skipped=1, skipped_files=["neovim: no rules to sync"])

        rule_contents = [r.get("content", "") for r in rules if r.get("content", "").strip()]
        if not rule_contents:
            return SyncResult(skipped=1, skipped_files=["neovim: empty rules"])

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        concatenated = "\n\n---\n\n".join(rule_contents)

        managed_section = (
            f"{HARNESSSYNC_MARKER}\n"
            f"# Rules (synced from Claude Code by HarnessSync)\n\n"
            f"{concatenated}\n\n"
            f"---\n"
            f"*Last synced: {timestamp}*\n"
            f"{HARNESSSYNC_MARKER_END}"
        )

        synced = 0
        failed = 0
        failed_files: list[str] = []

        # Write .avante/system-prompt.md
        try:
            ensure_dir(self.avante_dir)
            existing = ""
            if self.avante_system_prompt_path.is_file():
                existing = self.avante_system_prompt_path.read_text(encoding="utf-8")
            new_content = self._replace_managed_section(existing, managed_section)
            self.avante_system_prompt_path.write_text(new_content, encoding="utf-8")
            synced += 1
        except OSError as e:
            failed += 1
            failed_files.append(f"{AVANTE_SYSTEM_PROMPT}: {e}")

        # Write .codecompanion/system-prompt.md
        try:
            ensure_dir(self.codecompanion_dir)
            existing = ""
            if self.codecompanion_system_prompt_path.is_file():
                existing = self.codecompanion_system_prompt_path.read_text(encoding="utf-8")
            new_content = self._replace_managed_section(existing, managed_section)
            self.codecompanion_system_prompt_path.write_text(new_content, encoding="utf-8")
            synced += 1
        except OSError as e:
            failed += 1
            failed_files.append(f"{CODECOMPANION_SYSTEM_PROMPT}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to .avante/rules/ as markdown files."""
        if not skills:
            return SyncResult(skipped=1, skipped_files=[f"{AVANTE_RULES_DIR}/: no skills"])

        skills_dir = self.avante_rules_dir / "skills"
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
        """Sync agents to .avante/rules/agents/ as markdown rule files."""
        if not agents:
            return SyncResult(skipped=1, skipped_files=[f"{AVANTE_RULES_DIR}/agents/: no agents"])

        agents_dir = self.avante_rules_dir / "agents"
        ensure_dir(agents_dir)
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
                out_path = agents_dir / f"{name}.md"
                out_path.write_text(content, encoding="utf-8")
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Sync commands to .codecompanion/slash-commands/ as markdown files."""
        if not commands:
            return SyncResult(skipped=1, skipped_files=[f"{CODECOMPANION_SLASH_COMMANDS_DIR}/: no commands"])

        ensure_dir(self.codecompanion_slash_commands_dir)
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
                out_path = self.codecompanion_slash_commands_dir / f"{name}.md"
                out_path.write_text(adapted, encoding="utf-8")
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Sync MCP servers to .avante/mcp.json.

        avante.nvim supports MCP servers via its mcp.json configuration file.
        """
        if not mcp_servers:
            return SyncResult(skipped=1, skipped_files=[f"{AVANTE_MCP_JSON}: no MCP servers"])

        ensure_dir(self.avante_dir)

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
            mcp_data[name] = server_entry

        try:
            import tempfile
            import os
            temp_fd = tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.avante_dir,
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            )
            temp_path = Path(temp_fd.name)
            json.dump({"mcpServers": mcp_data}, temp_fd, indent=2, ensure_ascii=False)
            temp_fd.write("\n")
            temp_fd.flush()
            os.fsync(temp_fd.fileno())
            temp_fd.close()
            os.replace(str(temp_path), str(self.avante_mcp_path))
            return SyncResult(synced=len(mcp_data), synced_files=[str(self.avante_mcp_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"{AVANTE_MCP_JSON}: {e}"])

    def sync_settings(self, settings: dict) -> SyncResult:
        """Settings sync is a no-op for Neovim (managed by init.lua/init.vim)."""
        return SyncResult(skipped=1, skipped_files=["neovim: settings managed by Neovim config"])
