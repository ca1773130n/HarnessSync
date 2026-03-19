from __future__ import annotations

"""Cline / Roo-Code adapter for HarnessSync.

Syncs Claude Code configuration to Cline and Roo-Code (VS Code AI agent plugins):
- Rules (CLAUDE.md) → .clinerules (Cline project rules file)
- Rules (CLAUDE.md) → .roo/rules/harnesssync.md (Roo-Code rules directory)
- Skills → .clinerules (appended as skill context)
- Agents → .roo/rules/agents/<name>.md (Roo-Code agent rules)
- Commands → .clinerules (best-effort mapping)
- MCP servers → .roo/mcp.json (Roo-Code MCP config)
- Settings → no-op (managed by VS Code extension)

Cline reads .clinerules at project root as persistent system instructions.
Roo-Code stores rules in .roo/rules/ and MCP config in .roo/mcp.json.
Both formats are written to maximize compatibility with both tools.
"""

from datetime import datetime, timezone
from pathlib import Path

from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import ensure_dir, write_json_atomic


HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"

CLINERULES = ".clinerules"
ROO_DIR = ".roo"
ROO_RULES_DIR = ".roo/rules"
ROO_MCP_JSON = ".roo/mcp.json"


@AdapterRegistry.register("cline")
class ClineAdapter(AdapterBase):
    """Adapter for Cline and Roo-Code VS Code AI plugin configuration sync."""

    def __init__(self, project_dir: Path):
        super().__init__(project_dir)
        self.clinerules_path = project_dir / CLINERULES
        self.roo_dir = project_dir / ROO_DIR
        self.roo_rules_dir = project_dir / ROO_RULES_DIR
        self.roo_mcp_path = project_dir / ROO_MCP_JSON

    @property
    def target_name(self) -> str:
        return "cline"

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
        """Sync rules to .clinerules and .roo/rules/harnesssync.md.

        Cline reads .clinerules from project root as system instructions.
        Roo-Code reads rules from .roo/rules/ directory.
        Both files are written to support both tools simultaneously.
        """
        if not rules:
            return SyncResult(skipped=1, skipped_files=[f"{CLINERULES}: no rules to sync"])

        rule_contents = [r.get("content", "") for r in rules if r.get("content", "").strip()]
        if not rule_contents:
            return SyncResult(skipped=1, skipped_files=[f"{CLINERULES}: empty rules"])

        concatenated = "\n\n---\n\n".join(rule_contents)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        managed_section = (
            f"{HARNESSSYNC_MARKER}\n"
            f"# Rules synced from Claude Code\n\n"
            f"{concatenated}\n\n"
            f"---\n"
            f"*Last synced by HarnessSync: {timestamp}*\n"
            f"{HARNESSSYNC_MARKER_END}"
        )

        synced = 0
        failed = 0
        failed_files: list[str] = []

        # Write .clinerules for Cline
        existing = ""
        if self.clinerules_path.is_file():
            existing = self.clinerules_path.read_text(encoding="utf-8")
        new_content = self._replace_managed_section(existing, managed_section)
        try:
            self.clinerules_path.write_text(new_content, encoding="utf-8")
            synced += 1
        except OSError as e:
            failed += 1
            failed_files.append(f"{CLINERULES}: {e}")

        # Write .roo/rules/harnesssync.md for Roo-Code
        try:
            ensure_dir(self.roo_rules_dir)
            roo_rules_path = self.roo_rules_dir / "harnesssync.md"
            roo_rules_path.write_text(
                f"# HarnessSync Rules\n\n{concatenated}\n\n"
                f"*Last synced by HarnessSync: {timestamp}*\n",
                encoding="utf-8",
            )
            synced += 1
        except OSError as e:
            failed += 1
            failed_files.append(f".roo/rules/harnesssync.md: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to .roo/rules/skills/ as markdown files."""
        if not skills:
            return SyncResult(skipped=1, skipped_files=[".roo/rules/skills/: no skills"])

        skills_dir = self.roo_rules_dir / "skills"
        ensure_dir(skills_dir)
        synced = 0
        failed = 0
        failed_files: list[str] = []

        for name, skill_path in skills.items():
            skill_md = skill_path / "SKILL.md" if skill_path.is_dir() else skill_path
            if not skill_md.is_file():
                failed += 1
                failed_files.append(f"{name}: SKILL.md not found at {skill_md}")
                continue
            try:
                content = skill_md.read_text(encoding="utf-8")
                out_path = skills_dir / f"{name}.md"
                out_path.write_text(
                    f"# Skill: {name}\n\n{content}\n",
                    encoding="utf-8",
                )
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Sync agents to .roo/rules/agents/ as markdown files."""
        if not agents:
            return SyncResult(skipped=1, skipped_files=[".roo/rules/agents/: no agents"])

        agents_dir = self.roo_rules_dir / "agents"
        ensure_dir(agents_dir)
        synced = 0
        failed = 0
        failed_files: list[str] = []

        for name, agent_path in agents.items():
            agent_md = agent_path if agent_path.is_file() else agent_path / f"{name}.md"
            if not agent_md.is_file():
                failed += 1
                failed_files.append(f"{name}: agent file not found at {agent_md}")
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
        """Commands are appended to .clinerules as reference documentation."""
        if not commands:
            return SyncResult(skipped=0)

        return SyncResult(
            skipped=len(commands),
            skipped_files=[f"{name}: commands not natively supported in Cline" for name in commands],
        )

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Sync MCP servers to .roo/mcp.json.

        Roo-Code uses the standard mcpServers JSON format.
        """
        if not mcp_servers:
            return SyncResult(skipped=1, skipped_files=[f"{ROO_MCP_JSON}: no MCP servers"])

        ensure_dir(self.roo_dir)

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
            # Pass through timeout (direct, ms)
            if "timeout" in cfg:
                server_entry["timeout"] = cfg["timeout"]
            mcp_data[name] = server_entry

        try:
            write_json_atomic(self.roo_mcp_path, {"mcpServers": mcp_data})
            return SyncResult(synced=len(mcp_data), synced_files=[str(self.roo_mcp_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"{ROO_MCP_JSON}: {e}"])

    def sync_settings(self, settings: dict) -> SyncResult:
        """Settings sync is a no-op for Cline/Roo-Code (managed by VS Code)."""
        return SyncResult(skipped=1, skipped_files=["cline: settings managed by VS Code extension"])
