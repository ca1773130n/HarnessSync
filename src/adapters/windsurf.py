from __future__ import annotations

"""Windsurf (Codeium) IDE adapter for HarnessSync.

Syncs Claude Code configuration to Windsurf format:
- Rules (CLAUDE.md) → .windsurf/rules/<name>.md (individual rule files with
  YAML frontmatter) + .windsurfrules (combined fallback for older versions)
- Skills → .windsurf/skills/<name>.md (Windsurf skills)
- Agents → .windsurf/workflows/<name>.md (Windsurf workflows)
- Commands → .windsurf/workflows/<name>.md (best-effort mapping)
- MCP servers → .codeium/windsurf/mcp_config.json
- Settings → no-op (managed by IDE)

Windsurf now uses .windsurf/rules/ directory for individual rule files with
YAML frontmatter (trigger: always_on). The legacy .windsurfrules at project
root is still written as a combined fallback for backward compatibility.
"""

from datetime import datetime, timezone
from pathlib import Path
import re

from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import ensure_dir, write_json_atomic


HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"
WINDSURFRULES = ".windsurfrules"
WINDSURF_DIR = ".windsurf"
WINDSURF_RULES_DIR = ".windsurf/rules"
WINDSURF_SKILLS_DIR = ".windsurf/skills"
# NOTE: The global MCP config path is ~/.codeium/windsurf/mcp_config.json.
# We write project-level config at .codeium/windsurf/mcp_config.json within
# the project directory. For global installs, users should symlink or copy
# to the home-directory path.
MCP_CONFIG_JSON = ".codeium/windsurf/mcp_config.json"


@AdapterRegistry.register("windsurf")
class WindsurfAdapter(AdapterBase):
    """Adapter for Windsurf (Codeium) IDE configuration sync."""

    def __init__(self, project_dir: Path):
        super().__init__(project_dir)
        self.rules_path = project_dir / WINDSURFRULES
        self.windsurf_dir = project_dir / WINDSURF_DIR
        self.rules_dir = project_dir / WINDSURF_RULES_DIR
        self.skills_dir = project_dir / WINDSURF_SKILLS_DIR
        self.mcp_config_path = project_dir / MCP_CONFIG_JSON

    @property
    def target_name(self) -> str:
        return "windsurf"

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync rules to .windsurf/rules/ as individual .md files with YAML frontmatter.

        Each rule is written as a separate .md file in .windsurf/rules/ with
        YAML frontmatter containing trigger and description fields. A combined
        .windsurfrules file is also written as a fallback for older Windsurf
        versions.
        """
        if not rules:
            return SyncResult(skipped=1, skipped_files=[f"{WINDSURF_RULES_DIR}: no rules to sync"])

        rule_contents = [(r, r.get("content", "")) for r in rules if r.get("content", "").strip()]
        if not rule_contents:
            return SyncResult(skipped=1, skipped_files=[f"{WINDSURF_RULES_DIR}: empty rules"])

        ensure_dir(self.rules_dir)

        synced = 0
        failed = 0
        failed_files: list[str] = []
        synced_files: list[str] = []

        # Write individual rule files to .windsurf/rules/
        for rule, content in rule_contents:
            rule_name = self._rule_name(rule)
            description = self._rule_description(rule, content)
            frontmatter = (
                "---\n"
                "trigger: always_on\n"
                f"description: {self._quote_yaml_value(description)}\n"
                "---\n"
            )
            rule_file = self.rules_dir / f"{rule_name}.md"
            try:
                rule_file.write_text(frontmatter + content, encoding="utf-8")
                synced += 1
                synced_files.append(str(rule_file))
            except OSError as e:
                failed += 1
                failed_files.append(f"{rule_name}: {e}")

        # Write combined .windsurfrules as backward-compatible fallback
        all_contents = [c for _, c in rule_contents]
        concatenated = "\n\n---\n\n".join(all_contents)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        managed_section = (
            f"{HARNESSSYNC_MARKER}\n"
            f"# Rules synced from Claude Code\n\n"
            f"{concatenated}\n\n"
            f"---\n"
            f"*Last synced by HarnessSync: {timestamp}*\n"
            f"{HARNESSSYNC_MARKER_END}"
        )

        existing = ""
        if self.rules_path.is_file():
            existing = self.rules_path.read_text(encoding="utf-8")

        new_content = self._replace_managed_section(existing, managed_section)

        try:
            self.rules_path.write_text(new_content, encoding="utf-8")
            synced_files.append(str(self.rules_path))
        except OSError as e:
            failed += 1
            failed_files.append(f"{WINDSURFRULES}: {e}")

        return SyncResult(synced=synced, failed=failed,
                          synced_files=synced_files, failed_files=failed_files)

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to .windsurf/skills/ as Markdown files.

        Windsurf supports skills that provide specialized capabilities.
        Skills are mapped to .windsurf/skills/<name>.md files.
        """
        if not skills:
            return SyncResult(skipped=1, skipped_files=[f"{WINDSURF_SKILLS_DIR}: no skills"])

        ensure_dir(self.skills_dir)
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
                out_path = self.skills_dir / f"{name}.md"
                out_path.write_text(content, encoding="utf-8")
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Sync agents to .windsurf/workflows/ as Markdown workflow files."""
        if not agents:
            return SyncResult(skipped=1, skipped_files=[".windsurf/workflows/: no agents"])

        workflows_dir = self.windsurf_dir / "workflows"
        ensure_dir(workflows_dir)
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
                out_path = workflows_dir / f"{name}.md"
                out_path.write_text(content, encoding="utf-8")
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Sync commands to .windsurf/workflows/ (adapted, no $ARGUMENTS)."""
        if not commands:
            return SyncResult(skipped=1, skipped_files=[".windsurf/workflows/: no commands"])

        workflows_dir = self.windsurf_dir / "workflows"
        ensure_dir(workflows_dir)
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
                out_path = workflows_dir / f"cmd-{name}.md"
                out_path.write_text(adapted, encoding="utf-8")
                synced += 1
            except OSError as e:
                failed += 1
                failed_files.append(f"{name}: {e}")

        return SyncResult(synced=synced, failed=failed, failed_files=failed_files)

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Sync MCP servers to .codeium/windsurf/mcp_config.json.

        Windsurf uses Codeium's MCP config format under ~/.codeium/windsurf/.
        At project level we write .codeium/windsurf/mcp_config.json.
        """
        if not mcp_servers:
            return SyncResult(skipped=1, skipped_files=["mcp_config.json: no MCP servers"])

        ensure_dir(self.mcp_config_path.parent)

        mcp_data: dict[str, dict] = {}
        for name, cfg in mcp_servers.items():
            entry: dict = {}
            cmd = cfg.get("command") or cfg.get("cmd")
            if cmd:
                entry["command"] = cmd
            args = cfg.get("args", [])
            if args:
                entry["args"] = args
            env = cfg.get("env", {})
            if env:
                entry["env"] = env
            url = cfg.get("url")
            if url:
                entry["serverUrl"] = url
            # Pass through timeout (direct, ms)
            if "timeout" in cfg:
                entry["timeout"] = cfg["timeout"]
            mcp_data[name] = entry

        config = {"mcpServers": mcp_data}

        try:
            write_json_atomic(self.mcp_config_path, config)
            return SyncResult(synced=len(mcp_data), synced_files=[str(self.mcp_config_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"mcp_config.json: {e}"])

    def sync_settings(self, settings: dict) -> SyncResult:
        """Settings sync is a no-op for Windsurf (managed by IDE)."""
        return SyncResult(skipped=1, skipped_files=["windsurf settings: managed by IDE"])

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _replace_managed_section(self, existing: str, new_section: str) -> str:
        """Replace or append HarnessSync managed section in a file."""
        if HARNESSSYNC_MARKER in existing and HARNESSSYNC_MARKER_END in existing:
            start = existing.index(HARNESSSYNC_MARKER)
            end = existing.index(HARNESSSYNC_MARKER_END) + len(HARNESSSYNC_MARKER_END)
            return existing[:start] + new_section + existing[end:]
        separator = "\n\n" if existing.strip() else ""
        return existing + separator + new_section + "\n"

    @staticmethod
    def _rule_name(rule: dict) -> str:
        """Derive a filesystem-safe rule name from a rule dict.

        Uses the rule's 'path' stem if available, otherwise falls back
        to a sanitized version of the first line of content.
        """
        path = rule.get("path")
        if path:
            stem = Path(str(path)).stem
            # Sanitize: lowercase, replace non-alphanum with hyphens
            return re.sub(r'[^a-z0-9]+', '-', stem.lower()).strip('-') or "rule"
        content = rule.get("content", "")
        first_line = content.split("\n", 1)[0].strip()[:60]
        sanitized = re.sub(r'[^a-z0-9]+', '-', first_line.lower()).strip('-')
        return sanitized or "rule"

    @staticmethod
    def _rule_description(rule: dict, content: str) -> str:
        """Extract a short description for a rule's YAML frontmatter.

        Uses the rule's 'path' name or the first non-empty line of content.
        """
        path = rule.get("path")
        if path:
            return f"Rules from {Path(str(path)).name}"
        first_line = content.strip().split("\n", 1)[0].strip()
        # Strip leading markdown heading markers
        first_line = re.sub(r'^#+\s*', '', first_line)
        return first_line[:80] if first_line else "Synced rules"
