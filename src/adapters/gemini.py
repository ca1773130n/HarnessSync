"""Gemini CLI adapter for HarnessSync.

Implements adapter for Gemini CLI, syncing Claude Code configuration to Gemini format:
- Rules (CLAUDE.md) → GEMINI.md with managed markers
- Skills → Inline content in GEMINI.md (no symlinks, YAML frontmatter stripped)
- Agents → Inline content in GEMINI.md
- Commands → Brief descriptions in GEMINI.md
- MCP servers → settings.json mcpServers format
- Settings → settings.json tools.blockedTools/allowedTools (never auto-enable yolo)

The adapter uses subsection markers within the main HarnessSync managed block
to allow incremental syncing without losing other sections.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import ensure_dir, read_json_safe, write_json_atomic
from src.utils.env_translator import check_transport_support


# Gemini CLI constants
HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"
GEMINI_MD = "GEMINI.md"
SETTINGS_JSON = "settings.json"


@AdapterRegistry.register("gemini")
class GeminiAdapter(AdapterBase):
    """Adapter for Gemini CLI configuration sync."""

    def __init__(self, project_dir: Path):
        """Initialize Gemini adapter.

        Args:
            project_dir: Root directory of the project being synced
        """
        super().__init__(project_dir)
        self.gemini_md_path = project_dir / GEMINI_MD
        self.settings_path = project_dir / ".gemini" / SETTINGS_JSON

    @property
    def target_name(self) -> str:
        """Return target CLI name.

        Returns:
            Target identifier 'gemini'
        """
        return "gemini"

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync CLAUDE.md rules to GEMINI.md with managed markers.

        Concatenates all rule file contents into a single managed section in GEMINI.md.
        Preserves any user content outside HarnessSync markers.

        Args:
            rules: List of rule dicts with 'path' (Path) and 'content' (str) keys

        Returns:
            SyncResult with synced=1 if rules written, skipped=1 if no rules
        """
        if not rules:
            return SyncResult(
                skipped=1,
                skipped_files=["GEMINI.md: no rules to sync"]
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

        # Read existing GEMINI.md or start fresh
        existing_content = self._read_gemini_md()

        # Replace or append managed section
        final_content = self._replace_managed_section(existing_content, managed_section)

        # Write GEMINI.md
        self._write_gemini_md(final_content)

        return SyncResult(
            synced=1,
            adapted=len(rules),
            synced_files=[str(self.gemini_md_path)]
        )

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to GEMINI.md via inline content.

        Reads SKILL.md from each skill directory, strips YAML frontmatter,
        and inlines the content into GEMINI.md with section headers.

        Args:
            skills: Dict mapping skill name to skill directory path

        Returns:
            SyncResult tracking synced/skipped/failed skills
        """
        if not skills:
            return SyncResult()

        skill_sections = []
        synced_count = 0

        for name, skill_dir in skills.items():
            try:
                # Read SKILL.md from skill directory
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    continue

                content = skill_md.read_text(encoding='utf-8')

                # Parse frontmatter and extract body
                frontmatter, body = self._parse_frontmatter(content)
                skill_name = frontmatter.get('name', name)
                description = frontmatter.get('description', '')

                # Strip leading/trailing whitespace from body
                body = body.strip()

                # Build skill section
                section = f"## Skill: {skill_name}\n\n"
                if description:
                    section += f"**Purpose:** {description}\n\n"
                section += body

                skill_sections.append(section)
                synced_count += 1

            except Exception:
                # Silently skip malformed skills
                continue

        if not skill_sections:
            return SyncResult()

        # Combine all skill sections
        combined = '\n\n---\n\n'.join(skill_sections)

        # Build subsection with markers
        skills_subsection = f"""<!-- HarnessSync:Skills -->
{combined}
<!-- End HarnessSync:Skills -->"""

        # Write into GEMINI.md (merge with existing content)
        self._write_subsection("Skills", skills_subsection)

        return SyncResult(
            synced=synced_count,
            adapted=synced_count,
            synced_files=[str(self.gemini_md_path)]
        )

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Convert Claude Code agents to Gemini inline format.

        Extracts name/description from agent frontmatter, role instructions from <role>
        tags, and inlines into GEMINI.md agents subsection.

        Args:
            agents: Dict mapping agent name to agent .md file path

        Returns:
            SyncResult tracking synced/skipped/failed/adapted agents
        """
        if not agents:
            return SyncResult()

        agent_sections = []
        synced_count = 0

        for agent_name, agent_path in agents.items():
            try:
                # Read agent file
                if not agent_path.exists():
                    continue

                content = agent_path.read_text(encoding='utf-8')

                # Parse frontmatter and extract role
                frontmatter, body = self._parse_frontmatter(content)
                name = frontmatter.get('name', agent_name)
                description = frontmatter.get('description', '')
                role_instructions = self._extract_role_section(body)

                # Skip if no content
                if not role_instructions.strip():
                    continue

                # Build agent section
                section = f"## Agent: {name}\n\n"
                if description:
                    section += f"**Description:** {description}\n\n"
                section += role_instructions.strip()

                agent_sections.append(section)
                synced_count += 1

            except Exception:
                # Silently skip malformed agents
                continue

        if not agent_sections:
            return SyncResult()

        # Combine all agent sections
        combined = '\n\n---\n\n'.join(agent_sections)

        # Build subsection with markers
        agents_subsection = f"""<!-- HarnessSync:Agents -->
{combined}
<!-- End HarnessSync:Agents -->"""

        # Write into GEMINI.md (merge with existing content)
        self._write_subsection("Agents", agents_subsection)

        return SyncResult(
            synced=synced_count,
            adapted=synced_count,
            synced_files=[str(self.gemini_md_path)]
        )

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Convert Claude Code commands to Gemini brief descriptions.

        Extracts command name and description from frontmatter and creates
        a bullet list in GEMINI.md (NOT full content, just summaries).

        Args:
            commands: Dict mapping command name to command .md file path

        Returns:
            SyncResult tracking synced/skipped/failed/adapted commands
        """
        if not commands:
            return SyncResult()

        command_lines = []
        synced_count = 0

        for cmd_name, cmd_path in commands.items():
            try:
                # Read command file
                if not cmd_path.exists():
                    continue

                content = cmd_path.read_text(encoding='utf-8')

                # Parse frontmatter
                frontmatter, _ = self._parse_frontmatter(content)
                name = frontmatter.get('name', cmd_name)
                description = frontmatter.get('description', f"Claude Code command: {cmd_name}")

                # Build brief description line
                command_lines.append(f"- **/{name}**: {description}")
                synced_count += 1

            except Exception:
                # Silently skip malformed commands
                continue

        if not command_lines:
            return SyncResult()

        # Build commands section
        commands_content = "## Available Commands\n\n" + '\n'.join(command_lines)

        # Build subsection with markers
        commands_subsection = f"""<!-- HarnessSync:Commands -->
{commands_content}
<!-- End HarnessSync:Commands -->"""

        # Write into GEMINI.md (merge with existing content)
        self._write_subsection("Commands", commands_subsection)

        return SyncResult(
            synced=synced_count,
            adapted=synced_count,
            synced_files=[str(self.gemini_md_path)]
        )

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Translate MCP server configs to Gemini settings.json.

        Converts Claude Code MCP server JSON configs to Gemini settings.json format.
        Supports stdio (command+args) and URL (direct URL config) transports.
        Preserves environment variable references (${VAR}) as literal strings.
        Merges with existing settings.json preserving other settings.

        Args:
            mcp_servers: Dict mapping server name to server config dict

        Returns:
            SyncResult with synced count and settings.json path
        """
        if not mcp_servers:
            return SyncResult()

        return self._write_mcp_to_settings(mcp_servers, self.settings_path)

    def sync_mcp_scoped(self, mcp_servers_scoped: dict[str, dict]) -> SyncResult:
        """Translate MCP server configs with scope routing for Gemini.

        Routes servers by scope:
        - user/local/plugin -> user-scope config (~/.gemini/settings.json)
        - project -> project-scope config (.gemini/settings.json)

        Preserves ${VAR} syntax as-is (Gemini supports native interpolation).
        Skips unsupported transports with warning.

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
            ok, msg = check_transport_support(server_name, config, "gemini")
            if not ok:
                result.skipped += 1
                result.skipped_files.append(msg)
                continue

            # No env var translation for Gemini (ENV-03: preserves ${VAR} natively)

            # Route to correct scope bucket
            if scope == "project":
                project_servers[server_name] = config
            else:
                user_servers[server_name] = config

        # Write user-scope servers
        if user_servers:
            user_path = Path.home() / ".gemini" / SETTINGS_JSON
            user_result = self._write_mcp_to_settings(user_servers, user_path)
            result = result.merge(user_result)

        # Write project-scope servers
        if project_servers:
            project_path = self.project_dir / ".gemini" / SETTINGS_JSON
            project_result = self._write_mcp_to_settings(project_servers, project_path)
            result = result.merge(project_result)

        return result

    def _write_mcp_to_settings(self, mcp_servers: dict[str, dict], settings_path: Path) -> SyncResult:
        """Write MCP servers to a specific settings.json path.

        Reads existing settings, merges mcpServers, writes atomically.

        Args:
            mcp_servers: Dict mapping server name to server config dict
            settings_path: Target settings.json path

        Returns:
            SyncResult with synced count and path
        """
        result = SyncResult()

        try:
            # Read existing settings.json
            existing_settings = read_json_safe(settings_path)

            # Initialize mcpServers section
            existing_settings.setdefault('mcpServers', {})

            # Translate each MCP server
            for server_name, config in mcp_servers.items():
                server_config = {}

                # Stdio transport (has "command" key)
                if 'command' in config:
                    server_config['command'] = config['command']
                    if 'args' in config:
                        server_config['args'] = config.get('args', [])
                    if 'env' in config:
                        server_config['env'] = config['env']
                    if 'timeout' in config:
                        server_config['timeout'] = config['timeout']

                # URL transport (has "url" key)
                elif 'url' in config:
                    url = config['url']
                    # Detect SSE vs HTTP based on URL
                    if url.endswith('/sse') or 'sse' in url.lower():
                        server_config['url'] = url
                    else:
                        # Use httpUrl for plain HTTP/HTTPS
                        server_config['httpUrl'] = url

                    # Include headers if present
                    if 'headers' in config:
                        server_config['headers'] = config['headers']

                else:
                    # Skip servers without command or url
                    continue

                # Add to mcpServers (override if exists)
                existing_settings['mcpServers'][server_name] = server_config
                result.synced += 1

            # Write atomically
            ensure_dir(settings_path.parent)
            write_json_atomic(settings_path, existing_settings)

            result.synced_files.append(str(settings_path))

        except Exception as e:
            result.failed = len(mcp_servers)
            result.failed_files.append(f"MCP servers: {str(e)}")

        return result

    def sync_settings(self, settings: dict) -> SyncResult:
        """Map Claude Code settings to Gemini configuration.

        Maps Claude Code permission settings to Gemini tools configuration.
        Uses conservative defaults: deny list -> blockedTools, allow list -> allowedTools.
        NEVER auto-enables yolo mode (security constraint).

        Args:
            settings: Settings dict from Claude Code configuration

        Returns:
            SyncResult with synced count and warning if auto-approval detected
        """
        if not settings:
            return SyncResult()

        result = SyncResult()

        try:
            # Read existing settings.json to preserve mcpServers
            existing_settings = read_json_safe(self.settings_path)

            # Extract permissions
            permissions = settings.get('permissions', {})
            allow_list = permissions.get('allow', [])
            deny_list = permissions.get('deny', [])

            # Conservative mapping rules
            tools_config = {}

            if deny_list:
                # Deny list takes precedence
                tools_config['blockedTools'] = deny_list
                # Add warnings for blocked tools
                for tool in deny_list:
                    result.skipped_files.append(f"{tool}: blocked (Claude Code deny list)")

            elif allow_list:
                # Allow list only if no deny list
                tools_config['allowedTools'] = allow_list

            # Add tools config to settings if any rules defined
            if tools_config:
                existing_settings['tools'] = tools_config

            # Check for auto-approval mode and warn (NEVER enable yolo)
            approval_mode = settings.get('approval_mode', 'ask')
            if approval_mode == 'auto':
                result.skipped_files.append(
                    "yolo mode: not enabled (conservative default, Claude Code had auto-approval)"
                )

            # Write atomically
            write_json_atomic(self.settings_path, existing_settings)

            result.synced = 1
            result.adapted = 1
            result.synced_files.append(str(self.settings_path))

        except Exception as e:
            result.failed = 1
            result.failed_files.append(f"Settings: {str(e)}")

        return result

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

    # Helper methods for GEMINI.md management

    def _read_gemini_md(self) -> str:
        """Read existing GEMINI.md or return empty string.

        Returns:
            GEMINI.md content or empty string if file doesn't exist
        """
        if not self.gemini_md_path.exists():
            return ""

        try:
            return self.gemini_md_path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            # If read fails, treat as empty (will overwrite on write)
            return ""

    def _write_gemini_md(self, content: str) -> None:
        """Write GEMINI.md with parent directory creation.

        Args:
            content: Full GEMINI.md content to write
        """
        ensure_dir(self.gemini_md_path.parent)
        self.gemini_md_path.write_text(content, encoding='utf-8')

    def _replace_managed_section(self, existing: str, managed: str) -> str:
        """Replace content between HarnessSync markers or append.

        If markers exist in existing content, replaces the section between them.
        If no markers found, appends managed section to end of file.
        If existing is empty, returns just the managed section.

        Args:
            existing: Existing GEMINI.md content
            managed: New managed section (including markers)

        Returns:
            Final GEMINI.md content
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

    def _write_subsection(self, subsection_name: str, subsection_content: str) -> None:
        """Write or update a subsection within GEMINI.md.

        Reads current GEMINI.md, finds the subsection markers, replaces that
        subsection, and writes back. This allows incremental syncing.

        Args:
            subsection_name: Name of subsection (for logging)
            subsection_content: Content including subsection markers
        """
        existing = self._read_gemini_md()

        # Extract subsection marker from content
        # Format: <!-- HarnessSync:SubsectionName -->
        marker_match = re.search(r'<!-- HarnessSync:(\w+) -->', subsection_content)
        if not marker_match:
            # No marker found, can't process
            return

        marker_name = marker_match.group(1)
        start_marker = f"<!-- HarnessSync:{marker_name} -->"
        end_marker = f"<!-- End HarnessSync:{marker_name} -->"

        # Check if subsection exists in GEMINI.md
        if start_marker in existing:
            # Find and replace subsection
            start_idx = existing.find(start_marker)
            end_idx = existing.find(end_marker)

            if end_idx != -1:
                # Calculate end position (after the end marker)
                end_pos = end_idx + len(end_marker)

                # Replace subsection
                before = existing[:start_idx].rstrip()
                after = existing[end_pos:].lstrip()

                if before and after:
                    final_content = f"{before}\n\n{subsection_content}\n\n{after}"
                elif before:
                    final_content = f"{before}\n\n{subsection_content}"
                elif after:
                    final_content = f"{subsection_content}\n\n{after}"
                else:
                    final_content = subsection_content
            else:
                # Start marker exists but no end marker - append
                final_content = f"{existing.rstrip()}\n\n{subsection_content}"
        else:
            # Subsection doesn't exist - check if main managed section exists
            if HARNESSSYNC_MARKER in existing:
                # Insert within main managed section (before end marker)
                main_end_idx = existing.find(HARNESSSYNC_MARKER_END)
                if main_end_idx != -1:
                    # Insert before main end marker
                    before = existing[:main_end_idx].rstrip()
                    after = existing[main_end_idx:].lstrip()
                    final_content = f"{before}\n\n{subsection_content}\n\n{after}"
                else:
                    # Corrupted main section - append
                    final_content = f"{existing.rstrip()}\n\n{subsection_content}"
            else:
                # No main section - append subsection
                if existing:
                    final_content = f"{existing.rstrip()}\n\n{subsection_content}"
                else:
                    final_content = subsection_content

        # Write back to GEMINI.md
        self._write_gemini_md(final_content)
