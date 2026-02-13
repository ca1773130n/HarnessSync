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

        Extracts name/description from agent frontmatter, role instructions from <role>
        tags, and writes to .agents/skills/agent-{name}/SKILL.md. Discards Claude-specific
        fields like tools and color.

        Args:
            agents: Dict mapping agent name to agent .md file path

        Returns:
            SyncResult tracking synced/skipped/failed/adapted agents
        """
        if not agents:
            return SyncResult()

        result = SyncResult()

        for agent_name, agent_path in agents.items():
            try:
                # Read agent file
                if not agent_path.exists():
                    result.failed += 1
                    result.failed_files.append(f"{agent_name}: file not found at {agent_path}")
                    continue

                content = agent_path.read_text(encoding='utf-8')

                # Parse frontmatter and extract role
                frontmatter, body = self._parse_frontmatter(content)
                name = frontmatter.get('name', agent_name)
                description = frontmatter.get('description', '')
                instructions = self._extract_role_section(body)

                # Skip if no content
                if not instructions.strip():
                    result.skipped += 1
                    result.skipped_files.append(f"{agent_name}: no role content")
                    continue

                # Format as SKILL.md
                skill_content = self._format_skill_md(name, description, instructions)

                # Write to .agents/skills/agent-{name}/SKILL.md
                skill_dir = self.skills_dir / f"agent-{agent_name}"
                ensure_dir(skill_dir)
                skill_md = skill_dir / "SKILL.md"
                skill_md.write_text(skill_content, encoding='utf-8')

                result.synced += 1
                result.adapted += 1
                result.synced_files.append(str(skill_md))

            except Exception as e:
                result.failed += 1
                result.failed_files.append(f"{agent_name}: {str(e)}")

        return result

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Convert Claude Code commands to Codex SKILL.md format.

        Similar to sync_agents but writes to .agents/skills/cmd-{name}/SKILL.md.
        Commands use full content as instructions (no <role> extraction).

        Args:
            commands: Dict mapping command name to command .md file path

        Returns:
            SyncResult tracking synced/skipped/failed/adapted commands
        """
        if not commands:
            return SyncResult()

        result = SyncResult()

        for cmd_name, cmd_path in commands.items():
            try:
                # Read command file
                if not cmd_path.exists():
                    result.failed += 1
                    result.failed_files.append(f"{cmd_name}: file not found at {cmd_path}")
                    continue

                content = cmd_path.read_text(encoding='utf-8')

                # Parse frontmatter
                frontmatter, body = self._parse_frontmatter(content)
                name = frontmatter.get('name', cmd_name)
                description = frontmatter.get('description', f"Claude Code command: {cmd_name}")

                # For commands, use full body as instructions (no <role> extraction)
                instructions = body if body.strip() else content

                # Skip if no content
                if not instructions.strip():
                    result.skipped += 1
                    result.skipped_files.append(f"{cmd_name}: no content")
                    continue

                # Format as SKILL.md
                skill_content = self._format_skill_md(name, description, instructions)

                # Write to .agents/skills/cmd-{name}/SKILL.md
                skill_dir = self.skills_dir / f"cmd-{cmd_name}"
                ensure_dir(skill_dir)
                skill_md = skill_dir / "SKILL.md"
                skill_md.write_text(skill_content, encoding='utf-8')

                result.synced += 1
                result.adapted += 1
                result.synced_files.append(str(skill_md))

            except Exception as e:
                result.failed += 1
                result.failed_files.append(f"{cmd_name}: {str(e)}")

        return result

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

    # Helper methods for parsing and formatting

    def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
        """Extract YAML frontmatter from markdown content.

        Parses simple key: value frontmatter between --- delimiters.
        Does not use PyYAML - just simple string splitting for Claude Code format.

        Args:
            content: Markdown content with optional frontmatter

        Returns:
            Tuple of (frontmatter_dict, body_after_frontmatter)
        """
        # Check for frontmatter at start of file
        if not content.startswith('---'):
            return {}, content

        # Find end of frontmatter
        match = re.match(r'^---\n(.*?)\n---\n(.*)$', content, re.DOTALL)
        if not match:
            return {}, content

        frontmatter_text = match.group(1)
        body = match.group(2)

        # Parse simple key: value lines
        frontmatter = {}
        for line in frontmatter_text.split('\n'):
            if ':' in line:
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip()
                # Remove quotes if present
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                frontmatter[key] = val

        return frontmatter, body

    def _extract_role_section(self, body: str) -> str:
        """Extract content between <role> tags.

        Args:
            body: Markdown body content

        Returns:
            Content from <role> section, or full body if no tags found
        """
        match = re.search(r'<role>(.*?)</role>', body, re.DOTALL | re.IGNORECASE)
        if match:
            return match.group(1).strip()
        return body.strip()

    def _format_skill_md(self, name: str, description: str, instructions: str) -> str:
        """Format Codex SKILL.md with frontmatter and sections.

        Args:
            name: Skill name
            description: Skill description (used in frontmatter and trigger section)
            instructions: Main skill instructions

        Returns:
            Formatted SKILL.md content
        """
        # Use name as description fallback
        if not description:
            description = name

        # Build frontmatter
        frontmatter = f"""---
name: {name}
description: {description}
---"""

        # Build skill body
        body = f"""
{instructions}

## When to Use This Skill

{description}"""

        return frontmatter + body

    # Helper methods for AGENTS.md

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
