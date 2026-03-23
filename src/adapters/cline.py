from __future__ import annotations

"""Cline / Roo-Code adapter for HarnessSync.

Syncs Claude Code configuration to Cline and Roo-Code (VS Code AI agent plugins):
- Rules (CLAUDE.md) → .clinerules/ directory as individual .md files (primary)
                     → .clinerules flat file (backward compat fallback)
                     → .roo/rules/harnesssync.md (Roo-Code rules directory)
- Skills → .cline/skills/<name>/SKILL.md with YAML frontmatter (Cline native skills)
- Agents → .roo/rules/agents/<name>.md (Roo-Code agent rules)
- Commands → .clinerules/workflows/<name>.md (Cline workflow files)
- MCP servers → .roo/mcp.json (Roo-Code MCP config)
- Settings → no-op (managed by VS Code extension)

Cline reads .clinerules/ directory for project rules (individual .md files).
The flat .clinerules file is still written as a backward-compatibility fallback.
Roo-Code stores rules in .roo/rules/ and MCP config in .roo/mcp.json.
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
CLINE_SKILLS_DIR = ".cline/skills"
CLINERULES_WORKFLOWS_DIR = ".clinerules/workflows"
ROO_DIR = ".roo"
ROO_RULES_DIR = ".roo/rules"
ROO_MCP_JSON = ".roo/mcp.json"


@AdapterRegistry.register("cline")
class ClineAdapter(AdapterBase):
    """Adapter for Cline and Roo-Code VS Code AI plugin configuration sync."""

    def __init__(self, project_dir: Path):
        super().__init__(project_dir)
        self.clinerules_path = project_dir / CLINERULES  # file or directory
        self.cline_skills_dir = project_dir / CLINE_SKILLS_DIR
        self.workflows_dir = project_dir / CLINERULES_WORKFLOWS_DIR
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
        """Sync rules to .clinerules/ directory, flat .clinerules, and .roo/rules/.

        Primary: individual .md files in .clinerules/ directory (Cline's current format).
        Fallback: flat .clinerules file for backward compatibility.
        Roo-Code: .roo/rules/harnesssync.md for Roo-Code compatibility.
        """
        if not rules:
            return SyncResult(skipped=1, skipped_files=[f"{CLINERULES}: no rules to sync"])

        rules_with_content = [r for r in rules if r.get("content", "").strip()]
        if not rules_with_content:
            return SyncResult(skipped=1, skipped_files=[f"{CLINERULES}: empty rules"])

        rule_contents = [r.get("content", "") for r in rules_with_content]
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

        # Determine whether .clinerules is already a flat file (legacy) or
        # can be used as a directory (new format). We never delete a user's
        # existing flat file — instead we update it in-place as a fallback.
        clinerules_is_flat_file = self.clinerules_path.is_file()

        if clinerules_is_flat_file:
            # Legacy mode: update the existing flat .clinerules file
            existing = self.clinerules_path.read_text(encoding="utf-8")
            new_content = self._replace_managed_section(existing, managed_section)
            try:
                self.clinerules_path.write_text(new_content, encoding="utf-8")
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{CLINERULES}: {e}")
        else:
            # New format: write individual .md files to .clinerules/ directory
            try:
                ensure_dir(self.clinerules_path)
                for i, rule in enumerate(rules_with_content):
                    rule_path = rule.get("path")
                    if rule_path:
                        # Derive filename from source path stem
                        name = Path(rule_path).stem.lower().replace(" ", "-")
                    else:
                        name = f"rule-{i}"
                    out_path = self.clinerules_path / f"{name}.md"
                    out_path.write_text(
                        f"{HARNESSSYNC_MARKER}\n"
                        f"{rule.get('content', '')}\n\n"
                        f"---\n"
                        f"*Last synced by HarnessSync: {timestamp}*\n"
                        f"{HARNESSSYNC_MARKER_END}\n",
                        encoding="utf-8",
                    )
                    synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{CLINERULES_DIR}/: {e}")

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
        """Sync skills to .cline/skills/<name>/SKILL.md with YAML frontmatter.

        Uses Cline's native skills format: each skill gets its own directory
        under .cline/skills/ with a SKILL.md file containing YAML frontmatter
        (name, description) followed by the skill content.
        """
        if not skills:
            return SyncResult(skipped=1, skipped_files=[f"{CLINE_SKILLS_DIR}/: no skills"])

        ensure_dir(self.cline_skills_dir)  # create parent once before loop
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

                # Extract description from first non-empty, non-heading line
                description = f"Skill: {name}"
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        description = stripped[:120]
                        break

                skill_out_dir = self.cline_skills_dir / name
                skill_out_dir.mkdir(exist_ok=True)
                out_path = skill_out_dir / "SKILL.md"

                quoted_name = self._quote_yaml_value(name)
                quoted_desc = self._quote_yaml_value(description)

                out_path.write_text(
                    f"---\n"
                    f"name: {quoted_name}\n"
                    f"description: {quoted_desc}\n"
                    f"---\n"
                    f"{content}\n",
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
        """Sync commands to .clinerules/workflows/ as markdown workflow files.

        Each command becomes a .md file in the workflows directory,
        with content adapted for Cline's workflow format.
        """
        if not commands:
            return SyncResult(skipped=0)

        ensure_dir(self.workflows_dir)
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

                out_path = self.workflows_dir / f"{name}.md"
                out_path.write_text(
                    f"{HARNESSSYNC_MARKER}\n"
                    f"# Workflow: {name}\n\n"
                    f"{adapted}\n"
                    f"{HARNESSSYNC_MARKER_END}\n",
                    encoding="utf-8",
                )
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

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
