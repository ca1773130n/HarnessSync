from __future__ import annotations

"""Zed Editor AI adapter for HarnessSync.

Syncs Claude Code configuration to Zed's AI assistant format:
- Rules (CLAUDE.md) → .zed/system-prompt.md (Zed AI assistant system prompt)
- Skills → appended to .zed/system-prompt.md as context sections
- Agents → .zed/prompts/<name>.md (Zed prompt library)
- Commands → .zed/prompts/<name>.md (best-effort mapping)
- MCP servers → .zed/settings.json (context_servers section)
- Settings → .zed/settings.json

Zed Editor uses:
  - ~/.config/zed/settings.json or .zed/settings.json for project settings
  - .zed/system-prompt.md for AI assistant system prompt (per-project)
  - context_servers in settings.json for MCP-compatible context servers
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import ensure_dir


ZED_DIR = ".zed"
SYSTEM_PROMPT_MD = ".zed/system-prompt.md"
ZED_SETTINGS_JSON = ".zed/settings.json"
ZED_PROMPTS_DIR = ".zed/prompts"

HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"


@AdapterRegistry.register("zed")
class ZedAdapter(AdapterBase):
    """Adapter for Zed Editor AI assistant configuration sync."""

    def __init__(self, project_dir: Path):
        super().__init__(project_dir)
        self.zed_dir = project_dir / ZED_DIR
        self.system_prompt_path = project_dir / SYSTEM_PROMPT_MD
        self.settings_path = project_dir / ZED_SETTINGS_JSON
        self.prompts_dir = project_dir / ZED_PROMPTS_DIR

    @property
    def target_name(self) -> str:
        return "zed"

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
        """Sync rules to .zed/system-prompt.md.

        Zed reads .zed/system-prompt.md as the AI assistant's system prompt
        for the project, prepended to every conversation.
        """
        if not rules:
            return SyncResult(skipped=1, skipped_files=[f"{SYSTEM_PROMPT_MD}: no rules to sync"])

        rule_contents = [r.get("content", "") for r in rules if r.get("content", "").strip()]
        if not rule_contents:
            return SyncResult(skipped=1, skipped_files=[f"{SYSTEM_PROMPT_MD}: empty rules"])

        ensure_dir(self.zed_dir)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        concatenated = "\n\n---\n\n".join(rule_contents)

        managed_section = (
            f"{HARNESSSYNC_MARKER}\n"
            f"# System Instructions (synced from Claude Code)\n\n"
            f"{concatenated}\n\n"
            f"---\n"
            f"*Last synced by HarnessSync: {timestamp}*\n"
            f"{HARNESSSYNC_MARKER_END}"
        )

        existing = ""
        if self.system_prompt_path.is_file():
            existing = self.system_prompt_path.read_text(encoding="utf-8")

        new_content = self._replace_managed_section(existing, managed_section)

        try:
            self.system_prompt_path.write_text(new_content, encoding="utf-8")
            return SyncResult(synced=1, synced_files=[str(self.system_prompt_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"{SYSTEM_PROMPT_MD}: {e}"])

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to .zed/prompts/skills/ as prompt markdown files."""
        if not skills:
            return SyncResult(skipped=1, skipped_files=[f"{ZED_PROMPTS_DIR}/skills/: no skills"])

        skills_dir = self.prompts_dir / "skills"
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
                out_path.write_text(f"# {name}\n\n{content}\n", encoding="utf-8")
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Sync agents to .zed/prompts/ as markdown prompt files."""
        if not agents:
            return SyncResult(skipped=1, skipped_files=[f"{ZED_PROMPTS_DIR}/: no agents"])

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
                out_path = self.prompts_dir / f"agent-{name}.md"
                out_path.write_text(content, encoding="utf-8")
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Sync commands to .zed/prompts/ as slash command prompt files."""
        if not commands:
            return SyncResult(skipped=1, skipped_files=[f"{ZED_PROMPTS_DIR}/: no commands"])

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
                out_path = self.prompts_dir / f"cmd-{name}.md"
                out_path.write_text(adapted, encoding="utf-8")
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Sync MCP servers to .zed/settings.json as context_servers.

        Zed uses a context_servers key in settings.json for MCP-compatible
        context providers. The format maps server name to command config.
        """
        if not mcp_servers:
            return SyncResult(skipped=1, skipped_files=[f"{ZED_SETTINGS_JSON}: no MCP servers"])

        ensure_dir(self.zed_dir)

        # Load existing settings to preserve non-MCP config
        existing: dict = {}
        if self.settings_path.is_file():
            try:
                existing = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        # Zed context_servers format:
        # {"context_servers": {"server-name": {"command": {"path": "...", "args": [...]}}}}
        context_servers: dict[str, dict] = {}
        for name, cfg in mcp_servers.items():
            cmd = cfg.get("command") or cfg.get("cmd")
            url = cfg.get("url")
            if cmd:
                server_entry: dict = {
                    "command": {
                        "path": cmd,
                        "args": cfg.get("args", []),
                    }
                }
                env = cfg.get("env", {})
                if env:
                    server_entry["command"]["env"] = env
            elif url:
                server_entry = {"url": url}
            else:
                continue
            context_servers[name] = server_entry

        existing["context_servers"] = context_servers

        try:
            import tempfile
            import os
            temp_fd = tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.zed_dir,
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
            os.replace(str(temp_path), str(self.settings_path))
            return SyncResult(synced=len(context_servers), synced_files=[str(self.settings_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"{ZED_SETTINGS_JSON}: {e}"])

    def sync_settings(self, settings: dict) -> SyncResult:
        """Settings sync is a no-op for Zed (managed by the editor)."""
        return SyncResult(skipped=1, skipped_files=["zed: settings managed by editor"])
