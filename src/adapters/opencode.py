"""OpenCode CLI adapter for HarnessSync.

Implements adapter for OpenCode CLI, syncing Claude Code configuration to OpenCode format:
- Rules (CLAUDE.md) → AGENTS.md with managed markers (project root)
- Skills → Symlinks in .opencode/skills/
- Agents → Symlinks in .opencode/agents/
- Commands → Symlinks in .opencode/commands/
- MCP servers → opencode.json with type-discriminated format (local/remote)
- Settings → opencode.json permissions with conservative mapping

The adapter uses native symlink support (not inline content) and type-discriminated
MCP server configs (type: "local" for stdio, type: "remote" for URL).
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import (
    create_symlink_with_fallback,
    cleanup_stale_symlinks,
    ensure_dir,
    read_json_safe,
    write_json_atomic,
)
from src.utils.env_translator import check_transport_support


# OpenCode CLI constants
HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"
AGENTS_MD = "AGENTS.md"
OPENCODE_DIR = ".opencode"
OPENCODE_JSON = "opencode.json"


@AdapterRegistry.register("opencode")
class OpenCodeAdapter(AdapterBase):
    """Adapter for OpenCode CLI configuration sync."""

    def __init__(self, project_dir: Path):
        """Initialize OpenCode adapter.

        Args:
            project_dir: Root directory of the project being synced
        """
        super().__init__(project_dir)
        self.agents_md_path = project_dir / AGENTS_MD
        self.opencode_dir = project_dir / OPENCODE_DIR
        self.opencode_json_path = project_dir / OPENCODE_JSON

    @property
    def target_name(self) -> str:
        """Return target CLI name.

        Returns:
            Target identifier 'opencode'
        """
        return "opencode"

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync CLAUDE.md rules to AGENTS.md with managed markers.

        Concatenates all rule file contents into a single managed section in AGENTS.md.
        Preserves any user content outside HarnessSync markers. Writes to project root.

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
        """Sync skills to .opencode/skills/ via symlinks.

        Creates symlinks from source skill directories to .opencode/skills/{name}.
        Cleans up stale symlinks after creating all new symlinks.

        Args:
            skills: Dict mapping skill name to skill directory path

        Returns:
            SyncResult tracking synced/skipped/failed skills
        """
        if not skills:
            return SyncResult()

        result = SyncResult()
        target_dir = self.opencode_dir / "skills"

        # Ensure skills directory exists
        ensure_dir(target_dir)

        # Create symlinks for each skill
        for name, source_path in skills.items():
            target_path = target_dir / name

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

        # Clean up stale symlinks
        cleaned = cleanup_stale_symlinks(target_dir)
        if cleaned > 0:
            result.skipped_files.append(f"cleaned: {cleaned} stale symlinks")

        return result

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Sync agents to .opencode/agents/ via symlinks.

        Creates symlinks from source agent .md files to .opencode/agents/{name}.md.
        Cleans up stale symlinks after creating all new symlinks.

        Args:
            agents: Dict mapping agent name to agent .md file path

        Returns:
            SyncResult tracking synced/skipped/failed agents
        """
        if not agents:
            return SyncResult()

        result = SyncResult()
        target_dir = self.opencode_dir / "agents"

        # Ensure agents directory exists
        ensure_dir(target_dir)

        # Create symlinks for each agent
        for name, agent_path in agents.items():
            target_path = target_dir / f"{name}.md"

            # Create symlink with fallback
            success, method = create_symlink_with_fallback(agent_path, target_path)

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

        # Clean up stale symlinks
        cleaned = cleanup_stale_symlinks(target_dir)
        if cleaned > 0:
            result.skipped_files.append(f"cleaned: {cleaned} stale symlinks")

        return result

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Sync commands to .opencode/commands/ via symlinks.

        Creates symlinks from source command .md files to .opencode/commands/{name}.md.
        Cleans up stale symlinks after creating all new symlinks.

        Args:
            commands: Dict mapping command name to command .md file path

        Returns:
            SyncResult tracking synced/skipped/failed commands
        """
        if not commands:
            return SyncResult()

        result = SyncResult()
        target_dir = self.opencode_dir / "commands"

        # Ensure commands directory exists
        ensure_dir(target_dir)

        # Create symlinks for each command
        for name, cmd_path in commands.items():
            target_path = target_dir / f"{name}.md"

            # Create symlink with fallback
            success, method = create_symlink_with_fallback(cmd_path, target_path)

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

        # Clean up stale symlinks
        cleaned = cleanup_stale_symlinks(target_dir)
        if cleaned > 0:
            result.skipped_files.append(f"cleaned: {cleaned} stale symlinks")

        return result

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Translate MCP server configs to opencode.json with type discrimination.

        Converts Claude Code MCP server configs to OpenCode format:
        - Stdio transport (has "command") -> type: "local" with command array and environment
        - URL transport (has "url") -> type: "remote" with url and headers

        Preserves environment variable references (${VAR}) as literal strings.
        Merges with existing opencode.json preserving other config.

        Args:
            mcp_servers: Dict mapping server name to server config dict

        Returns:
            SyncResult with synced count and opencode.json path
        """
        if not mcp_servers:
            return SyncResult()

        result = SyncResult()

        try:
            # Read existing opencode.json
            existing_config = read_json_safe(self.opencode_json_path)

            # Initialize mcp section
            existing_config.setdefault('mcp', {})

            # Translate each MCP server
            for server_name, config in mcp_servers.items():
                server_config = {}

                # Stdio transport (has "command" key) -> type: "local"
                if 'command' in config:
                    server_config['type'] = 'local'
                    # Build command array: [command, arg1, arg2, ...]
                    command_array = [config['command']]
                    if 'args' in config:
                        command_array.extend(config['args'])
                    server_config['command'] = command_array

                    # Map env to environment (OpenCode uses 'environment' not 'env')
                    if 'env' in config:
                        server_config['environment'] = config['env']

                    server_config['enabled'] = True

                # URL transport (has "url" key) -> type: "remote"
                elif 'url' in config:
                    server_config['type'] = 'remote'
                    server_config['url'] = config['url']

                    # Include headers if present
                    if 'headers' in config:
                        server_config['headers'] = config['headers']

                    server_config['enabled'] = True

                else:
                    # Skip servers without command or url
                    result.skipped += 1
                    result.skipped_files.append(f"{server_name}: no command or url")
                    continue

                # Add to mcp section (override if exists)
                existing_config['mcp'][server_name] = server_config
                result.synced += 1

            # Add schema if not present
            if '$schema' not in existing_config:
                existing_config['$schema'] = 'https://opencode.ai/config.json'

            # Write atomically
            write_json_atomic(self.opencode_json_path, existing_config)

            result.synced_files.append(str(self.opencode_json_path))

        except Exception as e:
            result.failed = len(mcp_servers)
            result.failed_files.append(f"MCP servers: {str(e)}")

        return result

    def sync_mcp_scoped(self, mcp_servers_scoped: dict[str, dict]) -> SyncResult:
        """Translate MCP server configs with transport validation for OpenCode.

        OpenCode only has project-level config (opencode.json), so all servers
        go to the same file regardless of scope. Transport validation filters
        unsupported types (SSE).

        Args:
            mcp_servers_scoped: Dict mapping server name to scoped server data

        Returns:
            SyncResult with synced/skipped counts
        """
        if not mcp_servers_scoped:
            return SyncResult()

        result = SyncResult()
        valid_servers = {}

        for server_name, server_data in mcp_servers_scoped.items():
            config = server_data.get("config", server_data)

            # Transport validation
            ok, msg = check_transport_support(server_name, config, "opencode")
            if not ok:
                result.skipped += 1
                result.skipped_files.append(msg)
                continue

            valid_servers[server_name] = config

        # Write all valid servers to project-level opencode.json
        if valid_servers:
            mcp_result = self.sync_mcp(valid_servers)
            result = result.merge(mcp_result)

        return result

    def sync_settings(self, settings: dict) -> SyncResult:
        """Map Claude Code settings to opencode.json permissions.

        Maps Claude Code permission settings to OpenCode configuration.
        Uses conservative defaults:
        - Deny list → restricted mode with denied tools
        - Allow list (no deny) → default mode with allowed tools
        - Both empty → default mode
        - NEVER sets yolo or unrestricted mode

        Args:
            settings: Settings dict from Claude Code configuration

        Returns:
            SyncResult with synced count
        """
        if not settings:
            return SyncResult()

        result = SyncResult()

        try:
            # Read existing opencode.json to preserve mcp section
            existing_config = read_json_safe(self.opencode_json_path)

            # Extract permissions
            permissions = settings.get('permissions', {})
            allow_list = permissions.get('allow', [])
            deny_list = permissions.get('deny', [])

            # Conservative mapping
            permissions_config = {}

            if deny_list:
                # Deny list takes precedence → restricted mode
                permissions_config['mode'] = 'restricted'
                permissions_config['denied'] = deny_list
            elif allow_list:
                # Allow list only (no deny) → default mode with allowed
                permissions_config['mode'] = 'default'
                permissions_config['allowed'] = allow_list
            else:
                # Both empty → default mode
                permissions_config['mode'] = 'default'

            # Add permissions config to settings
            existing_config['permissions'] = permissions_config

            # Check for auto-approval mode and warn (NEVER enable yolo)
            approval_mode = settings.get('approval_mode', 'ask')
            if approval_mode == 'auto':
                result.skipped_files.append(
                    "yolo mode: not enabled (conservative default, Claude Code had auto-approval)"
                )

            # Add schema if not present
            if '$schema' not in existing_config:
                existing_config['$schema'] = 'https://opencode.ai/config.json'

            # Write atomically
            write_json_atomic(self.opencode_json_path, existing_config)

            result.synced = 1
            result.adapted = 1
            result.synced_files.append(str(self.opencode_json_path))

        except Exception as e:
            result.failed = 1
            result.failed_files.append(f"Settings: {str(e)}")

        return result

    # Helper methods for AGENTS.md management

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
