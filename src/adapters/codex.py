"""Codex CLI adapter for HarnessSync.

Implements adapter for Codex CLI, syncing Claude Code configuration to Codex format:
- Rules (CLAUDE.md) → AGENTS.md with managed markers
- Skills → Symlinks in .agents/skills/
- Agents → SKILL.md format in .agents/skills/agent-{name}/
- Commands → SKILL.md format in .agents/skills/cmd-{name}/
- MCP servers → config.toml (deferred to Plan 02-03)
- Settings → config.toml sandbox/approval settings (deferred to Plan 02-03)

The adapter preserves user-created content in AGENTS.md outside HarnessSync markers
and uses symlinks for zero-copy skill sharing.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import create_symlink_with_fallback, ensure_dir


# Codex CLI constants
HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"
AGENTS_MD = "AGENTS.md"
SKILLS_DIR = ".agents/skills"


@AdapterRegistry.register("codex")
class CodexAdapter(AdapterBase):
    """Adapter for Codex CLI configuration sync."""

    def __init__(self, project_dir: Path):
        """Initialize Codex adapter.

        Args:
            project_dir: Root directory of the project being synced
        """
        super().__init__(project_dir)
        self.agents_md_path = project_dir / AGENTS_MD
        self.skills_dir = project_dir / SKILLS_DIR

    @property
    def target_name(self) -> str:
        """Return target CLI name.

        Returns:
            Target identifier 'codex'
        """
        return "codex"

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync CLAUDE.md rules to AGENTS.md with managed markers.

        Concatenates all rule file contents into a single managed section in AGENTS.md.
        Preserves any user content above the HarnessSync marker. If AGENTS.md doesn't
        exist, creates it with just the managed section.

        Args:
            rules: List of rule dicts with 'path' (Path) and 'content' (str) keys

        Returns:
            SyncResult with synced=1 if rules written, skipped=1 if no rules
        """
        if not rules:
            return SyncResult(
                skipped=1,
                skipped_files=["AGENTS.md: no rules to sync"]
            )

        # Concatenate all rule contents
        rule_contents = [rule['content'] for rule in rules]
        concatenated = '\n\n---\n\n'.join(rule_contents)

        # Build managed section
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        managed_section = f"""{HARNESSSYNC_MARKER}
# Rules synced from Claude Code

{concatenated}

---
*Last synced by HarnessSync: {timestamp}*
{HARNESSSYNC_MARKER_END}"""

        # Read existing AGENTS.md or start fresh
        existing_content = self._read_agents_md()

        # Replace or append managed section
        final_content = self._replace_managed_section(existing_content, managed_section)

        # Write AGENTS.md
        self._write_agents_md(final_content)

        return SyncResult(
            synced=1,
            adapted=len(rules),
            synced_files=[str(self.agents_md_path)]
        )

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to .agents/skills/ via symlinks.

        Creates symlinks from source skill directories to target .agents/skills/{name}.
        Uses create_symlink_with_fallback for cross-platform compatibility (symlink →
        junction → copy with marker).

        Args:
            skills: Dict mapping skill name to skill directory path

        Returns:
            SyncResult tracking synced/skipped/failed skills
        """
        if not skills:
            return SyncResult()

        result = SyncResult()

        # Ensure skills directory exists
        ensure_dir(self.skills_dir)

        for name, source_path in skills.items():
            target_path = self.skills_dir / name

            # Create symlink with fallback
            success, method = create_symlink_with_fallback(source_path, target_path)

            if success:
                if method == 'skipped':
                    result.skipped += 1
                    result.skipped_files.append(f"{name}: already linked")
                else:
                    result.synced += 1
                    result.synced_files.append(f"{name} ({method})")
            else:
                result.failed += 1
                result.failed_files.append(f"{name}: {method}")

        return result

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Convert Claude Code agents to Codex SKILL.md format.

        Placeholder implementation - will be completed in Task 2.

        Args:
            agents: Dict mapping agent name to agent .md file path

        Returns:
            Empty SyncResult (stub)
        """
        return SyncResult()

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Convert Claude Code commands to Codex SKILL.md format.

        Placeholder implementation - will be completed in Task 2.

        Args:
            commands: Dict mapping command name to command .md file path

        Returns:
            Empty SyncResult (stub)
        """
        return SyncResult()

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Translate MCP server configs to Codex config.toml.

        Placeholder implementation - will be completed in Plan 02-03.

        Args:
            mcp_servers: Dict mapping server name to server config dict

        Returns:
            Empty SyncResult (stub)
        """
        return SyncResult()

    def sync_settings(self, settings: dict) -> SyncResult:
        """Map Claude Code settings to Codex configuration.

        Placeholder implementation - will be completed in Plan 02-03.

        Args:
            settings: Settings dict from Claude Code configuration

        Returns:
            Empty SyncResult (stub)
        """
        return SyncResult()

    # Helper methods

    def _read_agents_md(self) -> str:
        """Read existing AGENTS.md or return empty string.

        Returns:
            AGENTS.md content or empty string if file doesn't exist
        """
        if not self.agents_md_path.exists():
            return ""

        try:
            return self.agents_md_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            # If read fails, treat as empty (will overwrite on write)
            return ""

    def _write_agents_md(self, content: str) -> None:
        """Write AGENTS.md with parent directory creation.

        Args:
            content: Full AGENTS.md content to write
        """
        ensure_dir(self.agents_md_path.parent)
        self.agents_md_path.write_text(content, encoding='utf-8')

    def _replace_managed_section(self, existing: str, managed: str) -> str:
        """Replace content between HarnessSync markers or append.

        If markers exist in existing content, replaces the section between them.
        If no markers found, appends managed section to end of file.
        If existing is empty, returns just the managed section.

        Args:
            existing: Existing AGENTS.md content
            managed: New managed section (including markers)

        Returns:
            Final AGENTS.md content
        """
        if not existing:
            return managed

        # Check if markers exist
        if HARNESSSYNC_MARKER in existing:
            # Find start and end markers
            start_idx = existing.find(HARNESSSYNC_MARKER)
            end_idx = existing.find(HARNESSSYNC_MARKER_END)

            if end_idx != -1:
                # Calculate end position (after the end marker)
                end_pos = end_idx + len(HARNESSSYNC_MARKER_END)

                # Replace: content before marker + new managed + content after marker
                before = existing[:start_idx].rstrip()
                after = existing[end_pos:].lstrip()

                if before and after:
                    return f"{before}\n\n{managed}\n\n{after}"
                elif before:
                    return f"{before}\n\n{managed}"
                elif after:
                    return f"{managed}\n\n{after}"
                else:
                    return managed
            else:
                # Start marker exists but no end marker - treat as corrupted
                # Append to end instead of trying to fix
                return f"{existing.rstrip()}\n\n{managed}"
        else:
            # No markers - append managed section
            return f"{existing.rstrip()}\n\n{managed}"
