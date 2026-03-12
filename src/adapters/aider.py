from __future__ import annotations

"""Aider adapter for HarnessSync.

Syncs Claude Code configuration to Aider format:
- Rules (CLAUDE.md) → .aider.conf.yml (as system_prompt or via extra conventions)
- Skills → Appended to CONVENTIONS.md (Aider reads this for project conventions)
- Agents → CONVENTIONS.md entries (best-effort mapping)
- Commands → CONVENTIONS.md entries (best-effort mapping)
- MCP servers → .aider.conf.yml (not natively supported — notes section)
- Settings → .aider.conf.yml key mappings

Aider's primary config file is .aider.conf.yml and uses CONVENTIONS.md
(or CLAUDE.md) as context. Rules sync to CONVENTIONS.md as project context.
"""

import yaml
from datetime import datetime, timezone
from pathlib import Path

from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult


HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"
AIDER_CONF = ".aider.conf.yml"
CONVENTIONS_MD = "CONVENTIONS.md"


@AdapterRegistry.register("aider")
class AiderAdapter(AdapterBase):
    """Adapter for Aider AI coding assistant configuration sync."""

    def __init__(self, project_dir: Path):
        super().__init__(project_dir)
        self.aider_conf_path = project_dir / AIDER_CONF
        self.conventions_path = project_dir / CONVENTIONS_MD

    @property
    def target_name(self) -> str:
        return "aider"

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync rules to CONVENTIONS.md with HarnessSync markers.

        Aider reads CONVENTIONS.md (and CLAUDE.md) as project context files.
        Rules content is injected into a managed section in CONVENTIONS.md.
        """
        if not rules:
            return SyncResult(skipped=1, skipped_files=[f"{CONVENTIONS_MD}: no rules to sync"])

        rule_contents = [r.get("content", "") for r in rules if r.get("content", "").strip()]
        if not rule_contents:
            return SyncResult(skipped=1, skipped_files=[f"{CONVENTIONS_MD}: empty rules"])

        # Apply effectiveness annotation propagation before joining
        rule_contents = [self.prepare_rules_content(c) for c in rule_contents]
        concatenated = "\n\n---\n\n".join(rule_contents)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        managed_section = (
            f"{HARNESSSYNC_MARKER}\n"
            f"# Project Conventions (synced from Claude Code)\n\n"
            f"{concatenated}\n\n"
            f"---\n"
            f"*Last synced by HarnessSync: {timestamp}*\n"
            f"{HARNESSSYNC_MARKER_END}"
        )

        existing = ""
        if self.conventions_path.is_file():
            existing = self.conventions_path.read_text(encoding="utf-8")

        new_content = self._replace_managed_section(existing, managed_section)

        try:
            self.conventions_path.write_text(new_content, encoding="utf-8")
            return SyncResult(synced=1, synced_files=[str(self.conventions_path)])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"{CONVENTIONS_MD}: {e}"])

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Skills are noted in .aider.conf.yml as read-files (best-effort)."""
        if not skills:
            return SyncResult(skipped=1, skipped_files=["aider: no skills to sync"])

        # Aider supports `read` key in .aider.conf.yml to auto-add files as context
        skill_files: list[str] = []
        for name, skill_path in skills.items():
            skill_md = skill_path / "SKILL.md" if skill_path.is_dir() else skill_path
            if skill_md.is_file():
                skill_files.append(str(skill_md))

        if not skill_files:
            return SyncResult(skipped=len(skills), skipped_files=["no SKILL.md files found"])

        self._update_aider_conf_read_files(skill_files)
        return SyncResult(adapted=len(skill_files), synced_files=[AIDER_CONF])

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Agents have no direct Aider equivalent — skip."""
        if not agents:
            return SyncResult(skipped=0)
        return SyncResult(
            skipped=len(agents),
            skipped_files=[f"{name}: agents not natively supported in Aider" for name in agents],
        )

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Commands have no direct Aider equivalent — skip."""
        if not commands:
            return SyncResult(skipped=0)
        return SyncResult(
            skipped=len(commands),
            skipped_files=[f"{name}: commands not natively supported in Aider" for name in commands],
        )

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """MCP servers are not natively supported by Aider — log in conf as comments."""
        if not mcp_servers:
            return SyncResult(skipped=1, skipped_files=["aider: no MCP servers"])

        # Note server names in .aider.conf.yml under a comment block for visibility
        self._update_aider_conf_mcp_note(list(mcp_servers.keys()))
        return SyncResult(
            adapted=len(mcp_servers),
            synced_files=[AIDER_CONF],
        )

    def sync_settings(self, settings: dict) -> SyncResult:
        """Map Claude Code settings to Aider .aider.conf.yml equivalents."""
        aider_settings: dict = {}

        # Map approval_mode
        approval = settings.get("approval_mode", "")
        if approval in ("auto", "bypassPermissions"):
            aider_settings["yes"] = True  # aider --yes: auto-accept all changes

        try:
            self._merge_aider_conf(aider_settings)
            return SyncResult(synced=1, synced_files=[AIDER_CONF])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"{AIDER_CONF}: {e}"])

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_aider_conf(self) -> dict:
        """Read existing .aider.conf.yml, returning empty dict on missing/error."""
        if not self.aider_conf_path.is_file():
            return {}
        try:
            text = self.aider_conf_path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write_aider_conf(self, data: dict) -> None:
        """Write .aider.conf.yml atomically."""
        import os
        text = yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)
        tmp = self.aider_conf_path.with_suffix(".yml.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, self.aider_conf_path)
        except OSError:
            if tmp.exists():
                tmp.unlink(missing_ok=True)
            raise

    def _merge_aider_conf(self, updates: dict) -> None:
        """Merge updates into existing .aider.conf.yml."""
        existing = self._read_aider_conf()
        existing.update(updates)
        self._write_aider_conf(existing)

    def _update_aider_conf_read_files(self, files: list[str]) -> None:
        """Add skill files to aider conf read list (HarnessSync managed)."""
        conf = self._read_aider_conf()
        existing_reads = conf.get("read", [])
        if not isinstance(existing_reads, list):
            existing_reads = []
        # Add new files, avoid duplicates
        merged = list(existing_reads)
        for f in files:
            if f not in merged:
                merged.append(f)
        conf["read"] = merged
        self._write_aider_conf(conf)

    def _update_aider_conf_mcp_note(self, server_names: list[str]) -> None:
        """Add MCP server names as a note in aider conf (informational)."""
        conf = self._read_aider_conf()
        conf["# harnesssync_mcp_servers"] = server_names
        self._write_aider_conf(conf)

    def _replace_managed_section(self, existing: str, new_section: str) -> str:
        """Replace or append HarnessSync managed section in a file."""
        if HARNESSSYNC_MARKER in existing and HARNESSSYNC_MARKER_END in existing:
            start = existing.index(HARNESSSYNC_MARKER)
            end = existing.index(HARNESSSYNC_MARKER_END) + len(HARNESSSYNC_MARKER_END)
            return existing[:start] + new_section + existing[end:]
        # Append to end
        separator = "\n\n" if existing.strip() else ""
        return existing + separator + new_section + "\n"
