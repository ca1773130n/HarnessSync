from __future__ import annotations

"""Cursor IDE adapter for HarnessSync.

Syncs Claude Code configuration to Cursor IDE format:
- Rules (CLAUDE.md) → .cursor/rules/<name>.mdc files
- Skills → .cursor/rules/skills/<name>.mdc files
- Agents → .cursor/rules/agents/<name>.mdc files
- Commands → .cursor/rules/commands/<name>.mdc files
- MCP servers → .cursor/mcp.json
- Settings → .cursor/settings.json (no-op, Cursor settings managed by IDE)

Cursor uses .mdc (Markdown with Config) files for rules.
Each file can have YAML frontmatter for matching/scope config.
"""

from datetime import datetime, timezone
from pathlib import Path

from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import ensure_dir, write_json_atomic


HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"
CURSOR_DIR = ".cursor"
RULES_DIR = ".cursor/rules"
MCP_JSON = ".cursor/mcp.json"


@AdapterRegistry.register("cursor")
class CursorAdapter(AdapterBase):
    """Adapter for Cursor IDE configuration sync."""

    def __init__(self, project_dir: Path):
        super().__init__(project_dir)
        self.cursor_dir = project_dir / CURSOR_DIR
        self.rules_dir = project_dir / RULES_DIR
        self.mcp_json_path = project_dir / MCP_JSON

    @property
    def target_name(self) -> str:
        return "cursor"

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync rules to .cursor/rules/ as .mdc files.

        Each rule file becomes a .mdc file. CLAUDE.md becomes
        .cursor/rules/claude-code-rules.mdc.
        """
        if not rules:
            return SyncResult(skipped=1, skipped_files=[".cursor/rules/: no rules to sync"])

        ensure_dir(self.rules_dir)
        synced = 0
        failed = 0
        failed_files: list[str] = []

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        for rule in rules:
            path_str = rule.get("path", "CLAUDE.md")
            content = rule.get("content", "")
            if not content.strip():
                continue

            # Derive output filename from source path
            src_name = Path(path_str).stem  # e.g. "CLAUDE" from "CLAUDE.md"
            out_name = src_name.lower().replace(" ", "-")
            if out_name == "claude":
                out_name = "claude-code-rules"

            out_path = self.rules_dir / f"{out_name}.mdc"

            # Version-gate alwaysApply field (requires Cursor >= 0.40)
            try:
                from src.harness_version_compat import get_compat_flags
                flags = get_compat_flags("cursor", self.project_dir)
                _always_apply_supported = flags.get("mdc_alwaysApply", True)
            except Exception:
                _always_apply_supported = True

            _frontmatter_extra = "alwaysApply: true\n" if _always_apply_supported else ""

            mdc_content = (
                f"---\n"
                f"description: Synced from Claude Code by HarnessSync\n"
                f"{_frontmatter_extra}"
                f"---\n\n"
                f"{HARNESSSYNC_MARKER}\n"
                f"<!-- Last synced: {timestamp} -->\n\n"
                f"{content}\n\n"
                f"{HARNESSSYNC_MARKER_END}\n"
            )

            try:
                out_path.write_text(mdc_content, encoding="utf-8")
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{out_path}: {e}")

        if failed == 0 and synced == 0:
            return SyncResult(skipped=1, skipped_files=["no rule content to sync"])

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to .cursor/rules/skills/ as .mdc files."""
        if not skills:
            return SyncResult(skipped=1, skipped_files=[".cursor/rules/skills/: no skills"])

        skills_dir = self.rules_dir / "skills"
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
                out_path = skills_dir / f"{name}.mdc"
                out_path.write_text(
                    f"---\ndescription: Skill '{name}' from Claude Code\nalwaysApply: false\n---\n\n{content}\n",
                    encoding="utf-8",
                )
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Sync agents to .cursor/rules/agents/ as .mdc files."""
        if not agents:
            return SyncResult(skipped=1, skipped_files=[".cursor/rules/agents/: no agents"])

        agents_dir = self.rules_dir / "agents"
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
                out_path = agents_dir / f"{name}.mdc"
                out_path.write_text(
                    f"---\ndescription: Agent '{name}' from Claude Code\nalwaysApply: false\n---\n\n{content}\n",
                    encoding="utf-8",
                )
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Sync commands to .cursor/rules/commands/ as .mdc files."""
        if not commands:
            return SyncResult(skipped=1, skipped_files=[".cursor/rules/commands/: no commands"])

        commands_dir = self.rules_dir / "commands"
        ensure_dir(commands_dir)
        synced = 0
        failed = 0
        failed_files: list[str] = []

        for name, cmd_path in commands.items():
            cmd_md = cmd_path if cmd_path.is_file() else cmd_path / f"{name}.md"
            if not cmd_md.is_file():
                failed += 1
                failed_files.append(f"{name}: command file not found at {cmd_md}")
                continue

            try:
                content = cmd_md.read_text(encoding="utf-8")
                adapted = self.adapt_command_content(content)
                out_path = commands_dir / f"{name}.mdc"
                out_path.write_text(
                    f"---\ndescription: Command '{name}' from Claude Code\nalwaysApply: false\n---\n\n{adapted}\n",
                    encoding="utf-8",
                )
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Sync MCP servers to .cursor/mcp.json.

        Cursor uses the same mcpServers format as VS Code / standard MCP JSON.
        """
        if not mcp_servers:
            return SyncResult(skipped=1, skipped_files=[".cursor/mcp.json: no MCP servers"])

        ensure_dir(self.cursor_dir)

        # Cursor mcp.json format: {"mcpServers": {...}}
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

        cursor_mcp = {"mcpServers": mcp_data}

        try:
            write_json_atomic(self.mcp_json_path, cursor_mcp)
            return SyncResult(synced=len(mcp_data), synced_files=[str(self.mcp_json_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f".cursor/mcp.json: {e}"])

    def sync_settings(self, settings: dict) -> SyncResult:
        """Settings sync is a no-op for Cursor (managed by IDE)."""
        return SyncResult(skipped=1, skipped_files=[".cursor/settings.json: managed by IDE"])
