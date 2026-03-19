from __future__ import annotations

"""Codex CLI adapter for HarnessSync.

Implements adapter for Codex CLI, syncing Claude Code configuration to Codex format:
- Rules (CLAUDE.md) → AGENTS.md with managed markers
- Skills → Symlinks in .agents/skills/
- Agents → SKILL.md format in .agents/skills/{name}/
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
from src.utils.toml_writer import (
    format_mcp_servers_toml,
    format_mcp_server_toml,
    write_toml_atomic,
    escape_toml_string,
    read_toml_safe,
)
from src.utils.env_translator import translate_env_vars_for_codex, check_transport_support
from src.utils.permissions import extract_permissions, parse_permission_string


# Codex CLI constants
HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"

# Thresholds for intent-based approval policy mapping (see _map_approval_policy)
CODEX_DENY_THRESHOLD = 3    # deny_list >= this -> "untrusted"
CODEX_ALLOW_THRESHOLD = 5   # allow_list >= this (with no denies) -> "never"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"
AGENTS_MD = "AGENTS.md"
SKILLS_DIR = ".agents/skills"
CONFIG_TOML = "config.toml"


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

        # Append per-harness override content (from .harness-sync/overrides/codex.md)
        override = self.get_override_content()
        if override:
            final_content = final_content.rstrip() + f"\n\n{override}\n"

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
        tags, and writes to .agents/skills/{name}/SKILL.md. Discards Claude-specific
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

                # Translate CC-specific tool references for Codex
                try:
                    from src.skill_translator import translate_skill_content
                    instructions = translate_skill_content(instructions, self.target_name)
                except Exception:
                    pass

                # Format as SKILL.md
                skill_content = self._format_skill_md(name, description, instructions)

                # Write to .agents/skills/{name}/SKILL.md
                skill_dir = self.skills_dir / f"{agent_name}"
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

                # Adapt Claude Code-specific syntax for portability
                content = self.adapt_command_content(content)

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
                # Sanitize colons from namespaced commands (e.g. harness:setup -> harness-setup)
                safe_name = cmd_name.replace(':', '-')
                skill_dir = self.skills_dir / f"cmd-{safe_name}"
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

        Converts Claude Code MCP server JSON configs to Codex TOML format.
        Preserves environment variable references (${VAR}) as literal strings.
        Merges with existing config.toml preserving non-MCP settings.

        Args:
            mcp_servers: Dict mapping server name to server config dict

        Returns:
            SyncResult with synced count and config.toml path
        """
        if not mcp_servers:
            return SyncResult()

        config_path = self.project_dir / ".codex" / CONFIG_TOML
        return self._write_mcp_to_path(mcp_servers, config_path)

    def sync_mcp_scoped(self, mcp_servers_scoped: dict[str, dict]) -> SyncResult:
        """Translate MCP server configs with scope routing and env var translation.

        Routes servers by scope:
        - user/local/plugin -> user-scope config (~/.codex/config.toml)
        - project -> project-scope config (.codex/config.toml)

        Translates ${VAR} to resolved values for Codex (no native interpolation).
        Skips unsupported transports (SSE) with warning.

        Args:
            mcp_servers_scoped: Dict mapping server name to scoped server data

        Returns:
            SyncResult with combined counts from both scope writes
        """
        if not mcp_servers_scoped:
            return SyncResult()

        result = SyncResult()
        user_servers = {}
        project_servers = {}

        for server_name, server_data in mcp_servers_scoped.items():
            config = server_data.get("config", server_data)
            metadata = server_data.get("metadata", {})
            scope = metadata.get("scope", "user")

            # Plugin MCPs always route to user scope (Decision #34)
            if metadata.get("source") == "plugin" or scope == "local":
                scope = "user"

            # Transport validation
            ok, msg = check_transport_support(server_name, config, "codex")
            if not ok:
                result.skipped += 1
                result.skipped_files.append(msg)
                continue

            # Env var translation for Codex
            translated_config, warnings = translate_env_vars_for_codex(config)
            result.skipped_files.extend(warnings)

            # Route to correct scope bucket
            if scope == "project":
                project_servers[server_name] = translated_config
            else:
                user_servers[server_name] = translated_config

        # Write user-scope servers
        if user_servers:
            user_path = self.project_dir / CONFIG_TOML
            user_result = self._write_mcp_to_path(user_servers, user_path)
            result = result.merge(user_result)

        # Write project-scope servers
        if project_servers:
            project_path = self.project_dir / ".codex" / CONFIG_TOML
            project_result = self._write_mcp_to_path(project_servers, project_path)
            result = result.merge(project_result)

        return result

    def _write_mcp_to_path(self, mcp_servers: dict[str, dict], config_path: Path) -> SyncResult:
        """Write MCP servers to a specific config.toml path.

        Reads existing config, merges servers, writes atomically.

        Args:
            mcp_servers: Dict mapping server name to server config dict
            config_path: Target config.toml path

        Returns:
            SyncResult with synced count and path
        """
        result = SyncResult()

        try:
            # Read existing config to preserve settings and merge MCP servers
            existing_config = read_toml_safe(config_path)

            # Merge MCP servers (new servers override existing with same name)
            merged_mcp_servers = existing_config.get('mcp_servers', {}).copy()
            merged_mcp_servers.update(mcp_servers)

            # Generate MCP servers TOML section from merged servers
            mcp_toml = format_mcp_servers_toml(merged_mcp_servers)

            # Build settings section from existing config
            settings_lines = []
            for key in ['sandbox_mode', 'approval_policy']:
                if key in existing_config:
                    val = existing_config[key]
                    if isinstance(val, str):
                        settings_lines.append(f'{key} = "{val}"')
                    elif isinstance(val, bool):
                        settings_lines.append(f'{key} = {"true" if val else "false"}')
                    else:
                        settings_lines.append(f'{key} = {val}')

            settings_section = '\n'.join(settings_lines) if settings_lines else ''

            # Extract non-managed sections for preservation
            preserved = self._extract_unmanaged_toml(config_path)

            # Build complete config.toml
            final_toml = self._build_config_toml(settings_section, mcp_toml, preserved)

            # Write atomically
            write_toml_atomic(config_path, final_toml)

            # Track results
            result.synced = len(mcp_servers)
            result.synced_files.append(str(config_path))

        except Exception as e:
            result.failed = len(mcp_servers)
            result.failed_files.append(f"MCP servers: {str(e)}")

        return result

    def sync_settings(self, settings: dict) -> SyncResult:
        """Map Claude Code settings to Codex configuration.

        Maps Claude Code permission settings to Codex sandbox_mode and approval_policy
        using intent-based mapping:

        | Claude Code stance         | Codex approval_policy |
        |----------------------------|-----------------------|
        | Restrictive (many denies)  | "untrusted"           |
        | Balanced (default ask)     | "on-request"          |
        | Permissive (many allows)   | "never"               |

        Specific deny rules are documented as warnings in AGENTS.md since Codex
        cannot express per-tool restrictions. The mapping is intentionally lossy.

        Args:
            settings: Settings dict from Claude Code configuration

        Returns:
            SyncResult with synced count
        """
        if not settings:
            return SyncResult()

        result = SyncResult()

        try:
            # Config target path
            config_path = self.project_dir / ".codex" / CONFIG_TOML

            # Extract permissions (use pre-extracted if available, fall back to settings)
            permissions = extract_permissions(settings)
            allow_list = permissions.get('allow', [])
            deny_list = permissions.get('deny', [])
            ask_list = permissions.get('ask', [])

            # Determine sandbox_mode (conservative mapping)
            sandbox_mode = 'workspace-write'  # Default
            if deny_list:
                # ANY denied tool -> most restrictive
                sandbox_mode = 'read-only'
            elif allow_list and any(
                parse_permission_string(tool)[0] in ('Write', 'Edit', 'Bash')
                for tool in allow_list
            ):
                sandbox_mode = 'workspace-write'

            # Determine approval_policy using intent-based mapping
            approval_policy = self._map_approval_policy(
                allow_list, deny_list, ask_list, settings
            )

            # Read existing config to preserve MCP servers
            existing_config = self._read_existing_config()

            # Build settings section
            settings_lines = [
                f'sandbox_mode = "{sandbox_mode}"',
                f'approval_policy = "{approval_policy}"',
            ]
            settings_section = '\n'.join(settings_lines)

            # Preserve MCP servers section if present
            mcp_section = ''
            if 'mcp_servers' in existing_config:
                # Re-generate MCP section from existing config
                mcp_section = format_mcp_servers_toml(existing_config['mcp_servers'])

            # Extract non-managed sections for preservation
            preserved = self._extract_unmanaged_toml(config_path)

            # Build complete config.toml
            final_toml = self._build_config_toml(settings_section, mcp_section, preserved)

            # Write atomically
            write_toml_atomic(config_path, final_toml)

            # Document specific deny/ask rules in AGENTS.md (lossy mapping notice)
            if deny_list or ask_list:
                self._append_permission_warnings_to_agents_md(deny_list, ask_list)

            # Track results
            result.synced = 1
            result.adapted = 1
            result.synced_files.append(str(config_path))

        except Exception as e:
            result.failed = 1
            result.failed_files.append(f"Settings: {str(e)}")

        return result

    def _map_approval_policy(
        self,
        allow_list: list,
        deny_list: list,
        ask_list: list,
        settings: dict,
    ) -> str:
        """Map Claude Code permission stance to Codex approval_policy.

        Intent mapping:
        - Restrictive (3+ deny rules)     -> "untrusted"
        - Balanced (default, or ask-heavy) -> "on-request"
        - Permissive (5+ allow, no deny)   -> "never" (auto-approve)

        Falls back to "on-request" as the conservative default.

        Args:
            allow_list: Permission allow entries
            deny_list: Permission deny entries
            ask_list: Permission ask entries
            settings: Full settings dict for additional signals

        Returns:
            Codex approval_policy string
        """
        # Restrictive: many deny rules indicate a locked-down stance
        if len(deny_list) >= CODEX_DENY_THRESHOLD:
            return "untrusted"

        # Permissive: many allow rules with no deny rules
        if len(allow_list) >= CODEX_ALLOW_THRESHOLD and not deny_list:
            return "never"

        # Balanced: everything else
        return "on-request"

    def _append_permission_warnings_to_agents_md(
        self, deny_list: list, ask_list: list
    ) -> None:
        """Append permission restriction warnings to AGENTS.md.

        Codex cannot express per-tool permission restrictions, so we document
        the source deny/ask rules in the AGENTS.md rules section as warnings
        so users are aware of the intent that was lost in translation.

        Args:
            deny_list: List of denied permission strings
            ask_list: List of ask-required permission strings
        """
        if not deny_list and not ask_list:
            return

        lines = [
            "",
            "## Permission Restrictions (from Claude Code)",
            "",
            "> **Note:** Codex uses coarse approval policies and cannot enforce",
            "> per-tool restrictions. The following Claude Code rules are documented",
            "> here for reference but are NOT enforced by Codex.",
            "",
        ]

        if deny_list:
            lines.append("### Denied Operations")
            lines.append("")
            for perm in deny_list:
                tool, args = parse_permission_string(perm)
                if args:
                    lines.append(f"- **{tool}**: `{args}` (DENIED)")
                else:
                    lines.append(f"- **{tool}** (DENIED)")
            lines.append("")

        if ask_list:
            lines.append("### Requires Confirmation")
            lines.append("")
            for perm in ask_list:
                tool, args = parse_permission_string(perm)
                if args:
                    lines.append(f"- **{tool}**: `{args}` (requires approval)")
                else:
                    lines.append(f"- **{tool}** (requires approval)")
            lines.append("")

        warning_section = "\n".join(lines)

        # Read existing AGENTS.md and append within managed section
        existing = self._read_agents_md()
        if existing and HARNESSSYNC_MARKER_END in existing:
            # Insert before the end marker
            end_idx = existing.find(HARNESSSYNC_MARKER_END)
            before = existing[:end_idx].rstrip()
            after = existing[end_idx:]
            final = f"{before}\n{warning_section}\n{after}"
            self._write_agents_md(final)
        elif existing:
            # No managed section — append at end
            self._write_agents_md(f"{existing.rstrip()}\n{warning_section}\n")
        # If no AGENTS.md exists, skip — sync_rules will create it

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

        # Parse key: value lines with support for multiline block scalars (| and >)
        frontmatter = {}
        lines = frontmatter_text.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            if ':' in line and not line.startswith(' ') and not line.startswith('\t'):
                key, val = line.split(':', 1)
                key = key.strip()
                val = val.strip()

                # Handle YAML block scalar indicators (| or >)
                if val in ('|', '>', '|+', '>+', '|-', '>-'):
                    # Collect indented continuation lines
                    block_lines = []
                    i += 1
                    while i < len(lines) and (lines[i].startswith(' ') or lines[i].startswith('\t') or lines[i] == ''):
                        block_lines.append(lines[i].strip())
                        i += 1
                    val = '\n'.join(block_lines).strip()
                    frontmatter[key] = val
                    continue

                # Remove quotes if present
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                elif val.startswith("'") and val.endswith("'"):
                    val = val[1:-1]
                frontmatter[key] = val
            i += 1

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

        # Truncate long descriptions for frontmatter (keep first sentence)
        short_desc = description.split('\n')[0].strip()
        if len(short_desc) > 200:
            short_desc = short_desc[:200].rsplit(' ', 1)[0] + '...'

        # Quote description if it contains YAML-unsafe characters
        if any(c in short_desc for c in ':"\'{}[]|>&*!%#`@,'):
            quoted_desc = '"' + short_desc.replace('\\', '\\\\').replace('"', '\\"') + '"'
        else:
            quoted_desc = short_desc

        # Build frontmatter
        frontmatter = f"""---
name: {name}
description: {quoted_desc}
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

    # Helper methods for config.toml management

    def _read_existing_config(self) -> dict:
        """Read existing config.toml if it exists.

        Returns:
            Parsed TOML dict or empty dict if file missing or parse error
        """
        config_path = self.project_dir / ".codex" / CONFIG_TOML
        return read_toml_safe(config_path)

    def _extract_unmanaged_toml(self, config_path: Path) -> str:
        """Extract TOML sections not managed by HarnessSync for re-emission.

        Managed content (will be regenerated):
        - Header comments (# ... HarnessSync ..., # Do not edit ...)
        - sandbox_mode and approval_policy top-level keys
        - All [mcp_servers.*] sections

        Everything else is preserved verbatim.

        Args:
            config_path: Path to existing config.toml

        Returns:
            Raw TOML string of non-managed sections, or empty string
        """
        if not config_path.exists():
            return ''

        try:
            raw = config_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            return ''

        kept_lines: list[str] = []
        in_mcp_section = False

        for line in raw.split('\n'):
            stripped = line.strip()

            # Skip HarnessSync header comments
            if stripped.startswith('#') and ('HarnessSync' in stripped or 'Do not edit' in stripped or 'MCP servers' in stripped):
                continue

            # Skip managed top-level keys
            if stripped.startswith('sandbox_mode') and '=' in stripped:
                continue
            if stripped.startswith('approval_policy') and '=' in stripped:
                continue

            # Track table headers
            if stripped.startswith('['):
                if stripped.startswith('[mcp_servers'):
                    in_mcp_section = True
                    continue
                else:
                    in_mcp_section = False

            # Skip lines inside mcp_servers sections
            if in_mcp_section:
                continue

            kept_lines.append(line)

        # Strip leading/trailing blank lines
        result = '\n'.join(kept_lines).strip()
        return result

    def _build_config_toml(self, settings_section: str, mcp_section: str, preserved_sections: str = '') -> str:
        """Combine settings and MCP sections into complete config.toml.

        Args:
            settings_section: Settings TOML content (sandbox_mode, approval_policy)
            mcp_section: MCP servers TOML content

        Returns:
            Complete config.toml string with header comment
        """
        lines = [
            '# Codex configuration managed by HarnessSync',
            '# Do not edit MCP servers section manually',
            '',
        ]

        if settings_section:
            lines.append(settings_section)
            lines.append('')

        if mcp_section:
            lines.append(mcp_section)

        if preserved_sections:
            lines.append('')
            lines.append(preserved_sections)

        return '\n'.join(lines)
