from __future__ import annotations

"""Gemini CLI adapter for HarnessSync.

Implements adapter for Gemini CLI, syncing Claude Code configuration to Gemini format:
- Rules (CLAUDE.md) → GEMINI.md with managed markers
- Skills → Native .gemini/skills/<name>/SKILL.md files
- Agents → Native .gemini/agents/<name>.md files
- Commands → Native .gemini/commands/<name>.toml files
- MCP servers → settings.json mcpServers format (with trust/includeTools/excludeTools/cwd)
- Settings → settings.json tools.exclude/tools.allowed (never auto-enable yolo)

The adapter writes native Gemini CLI discovery files for skills, agents, and commands
instead of inlining content into GEMINI.md. Only rules remain in GEMINI.md.
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import ensure_dir, read_json_safe, write_json_atomic
from src.utils.env_translator import check_transport_support
from src.utils.permissions import extract_permissions, parse_permission_string


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

        # Append per-harness override content (from .harness-sync/overrides/gemini.md)
        override = self.get_override_content()
        if override:
            final_content = final_content.rstrip() + f"\n\n{override}\n"

        # Write GEMINI.md
        self._write_gemini_md(final_content)

        return SyncResult(
            synced=1,
            adapted=len(rules),
            synced_files=[str(self.gemini_md_path)]
        )

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to native .gemini/skills/<name>/SKILL.md files.

        Copies SKILL.md content (frontmatter + body preserved) to Gemini's native
        skill discovery path. Validates that name and description frontmatter
        fields exist before writing.

        Args:
            skills: Dict mapping skill name to skill directory path

        Returns:
            SyncResult tracking synced/skipped/failed skills
        """
        if not skills:
            return SyncResult()

        result = SyncResult()

        for name, skill_dir in skills.items():
            try:
                # Read SKILL.md from skill directory
                skill_md = skill_dir / "SKILL.md"
                if not skill_md.exists():
                    result.skipped += 1
                    result.skipped_files.append(f"{name}: SKILL.md not found")
                    continue

                content = skill_md.read_text(encoding='utf-8')

                # Validate frontmatter has required fields
                frontmatter, _ = self._parse_frontmatter(content)
                if 'name' not in frontmatter or 'description' not in frontmatter:
                    result.skipped += 1
                    result.skipped_files.append(f"{name}: missing name or description in frontmatter")
                    continue

                # Translate CC-specific tool references for Gemini
                try:
                    from src.skill_translator import translate_skill_content
                    content = translate_skill_content(content, self.target_name)
                except Exception:
                    pass  # Translation failure should not abort the sync

                # Write to native discovery path
                target_dir = self.project_dir / ".gemini" / "skills" / name
                ensure_dir(target_dir)
                (target_dir / "SKILL.md").write_text(content, encoding='utf-8')

                result.synced += 1
                result.synced_files.append(str(target_dir / "SKILL.md"))

            except Exception:
                result.failed += 1
                result.failed_files.append(f"{name}: write failed")
                continue

        return result

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Sync agents to native .gemini/agents/<name>.md files.

        Writes each agent as a Gemini-compatible .md file with frontmatter
        (name, description, optional tools/model/max_turns) and body from
        <role> tags (stripped). Drops Gemini-incompatible fields like color.

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
                    result.skipped += 1
                    result.skipped_files.append(f"{agent_name}: file not found")
                    continue

                content = agent_path.read_text(encoding='utf-8')

                # Parse frontmatter and extract body
                frontmatter, body = self._parse_frontmatter(content)
                name = frontmatter.get('name', agent_name)
                description = frontmatter.get('description', '')

                # Extract role body (strip <role> tags, fall back to full body)
                role_body = self._extract_role_section(body)
                if not role_body.strip():
                    result.skipped += 1
                    result.skipped_files.append(f"{agent_name}: no body content")
                    continue

                # Build Gemini-compatible frontmatter
                fm_lines = []
                fm_lines.append(f"name: {self._quote_yaml_value(name)}")
                fm_lines.append(f"description: {self._quote_yaml_value(description)}")

                # Pass through optional Gemini-compatible fields
                for field in ('model', 'max_turns'):
                    if field in frontmatter:
                        fm_lines.append(f"{field}: {frontmatter[field]}")

                # Handle tools as a YAML list
                if 'tools' in frontmatter:
                    tools_val = frontmatter['tools']
                    # Parse tools: could be comma-separated string or already parsed
                    if isinstance(tools_val, str) and tools_val.strip():
                        # Could be "tool1, tool2" or "- tool1\n- tool2" from block scalar
                        if '\n' in tools_val:
                            # Block scalar parsed lines (already "- " prefixed from source)
                            tool_items = [t.lstrip('- ').strip() for t in tools_val.split('\n') if t.strip()]
                        else:
                            tool_items = [t.strip() for t in tools_val.split(',') if t.strip()]
                        fm_lines.append("tools:")
                        for tool in tool_items:
                            fm_lines.append(f"- {tool}")

                # Drop color field (Gemini-incompatible) -- simply not included

                # Build final file content
                frontmatter_str = '\n'.join(fm_lines)
                agent_content = f"---\n{frontmatter_str}\n---\n\n{role_body.strip()}\n"

                # Write to native discovery path
                agents_dir = self.project_dir / ".gemini" / "agents"
                ensure_dir(agents_dir)
                target_path = agents_dir / f"{agent_name}.md"
                target_path.write_text(agent_content, encoding='utf-8')

                result.synced += 1
                result.adapted += 1
                result.synced_files.append(str(target_path))

            except Exception:
                result.failed += 1
                result.failed_files.append(f"{agent_name}: write failed")
                continue

        return result

    def _quote_yaml_value(self, value: str) -> str:
        """Quote a YAML value if it contains unsafe characters.

        Args:
            value: Raw string value for YAML frontmatter

        Returns:
            Quoted string if needed, original otherwise
        """
        if not value:
            return '""'
        # Quote if contains YAML-unsafe characters
        if any(c in value for c in ':"\'{}[]|>&*!%#`@,'):
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            return f'"{escaped}"'
        return value

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Sync commands to native .gemini/commands/<name>.toml files.

        Writes each command as a TOML file with description and prompt fields.
        Maps $ARGUMENTS to {{args}}. Handles namespaced commands (colons create
        subdirectory paths).

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
                    result.skipped += 1
                    result.skipped_files.append(f"{cmd_name}: file not found")
                    continue

                content = cmd_path.read_text(encoding='utf-8')

                # Parse frontmatter and extract body (prompt template)
                frontmatter, body = self._parse_frontmatter(content)
                name = frontmatter.get('name', cmd_name)
                description = frontmatter.get('description', '')
                prompt = body.strip()

                # Map $ARGUMENTS -> {{args}} in prompt body
                prompt = prompt.replace('$ARGUMENTS', '{{args}}')

                # Build TOML content
                toml_content = self._format_command_toml(description, prompt)

                # Handle namespaced commands: colon -> subdirectory
                # e.g., "harness:setup" -> "harness/setup.toml"
                if ':' in name:
                    parts = name.split(':')
                    toml_path = self.project_dir / ".gemini" / "commands"
                    for part in parts[:-1]:
                        toml_path = toml_path / part
                    toml_path = toml_path / f"{parts[-1]}.toml"
                else:
                    toml_path = self.project_dir / ".gemini" / "commands" / f"{name}.toml"

                ensure_dir(toml_path.parent)
                toml_path.write_text(toml_content, encoding='utf-8')

                result.synced += 1
                result.adapted += 1
                result.synced_files.append(str(toml_path))

            except Exception:
                result.failed += 1
                result.failed_files.append(f"{cmd_name}: write failed")
                continue

        return result

    def _format_command_toml(self, description: str, prompt: str) -> str:
        """Format a Gemini command TOML file with description and prompt fields.

        Args:
            description: Command description (for TOML basic string)
            prompt: Command prompt body (for TOML multi-line string)

        Returns:
            TOML file content string
        """
        lines = []

        if description:
            # Escape for TOML basic string (backslash and double-quote)
            desc_escaped = description.replace('\\', '\\\\').replace('"', '\\"')
            lines.append(f'description = "{desc_escaped}"')

        # Handle triple-quote in prompt body to avoid premature termination
        if '"""' in prompt:
            prompt = prompt.replace('"""', '""\\"')

        lines.append(f'prompt = """\n{prompt}\n"""')

        return '\n'.join(lines) + '\n'

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
            user_path = self.project_dir / ".gemini" / SETTINGS_JSON
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
                    # Note: timeout is intentionally NOT passed through (not supported by Gemini)

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

                # Map essential -> trust: true (closest semantic match)
                if config.get('essential') and 'trust' not in config:
                    server_config['trust'] = True

                # Map cwd (direct)
                if 'cwd' in config:
                    server_config['cwd'] = config['cwd']

                # Map url for remote servers (direct)
                if 'url' in config and 'url' not in server_config and 'httpUrl' not in server_config:
                    server_config['url'] = config['url']

                # Pass through additional Gemini CLI fields (GMN-11)
                for field in ('trust', 'includeTools', 'excludeTools'):
                    if field in config:
                        server_config[field] = config[field]

                # Drop fields not supported by Gemini:
                # - timeout: not supported
                # - oauth_scopes: not supported
                # - elicitation: not supported
                # - enabled_tools / disabled_tools: use includeTools / excludeTools instead

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

        Maps Claude Code permission settings to Gemini tools configuration
        and policy engine:
        - Deny rules -> ``.gemini/policies/harnesssync-policy.json`` + disableAlwaysAllow/disableYoloMode
        - Allow list -> ``tools.allowed`` in settings.json
        - NEVER auto-enables yolo mode (security constraint)

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
            permissions = extract_permissions(settings)
            allow_list = permissions.get('allow', [])
            deny_list = permissions.get('deny', [])

            # Conservative mapping rules
            tools_config = {}

            if deny_list:
                # Deny list takes precedence
                tools_config['exclude'] = deny_list
                # Add warnings for blocked tools
                for tool in deny_list:
                    result.skipped_files.append(f"{tool}: blocked (Claude Code deny list)")

                # Create policy file for deny rules
                self._write_deny_policy(deny_list)

                # Register policy path in settings
                policy_paths = existing_settings.get('policyPaths', [])
                policy_rel = ".gemini/policies/harnesssync-policy.json"
                if policy_rel not in policy_paths:
                    policy_paths.append(policy_rel)
                existing_settings['policyPaths'] = policy_paths

                # Disable always-allow and yolo when deny rules are present
                existing_settings['disableAlwaysAllow'] = True
                existing_settings['disableYoloMode'] = True

            elif allow_list:
                # Allow list only if no deny list
                tools_config['allowed'] = allow_list

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

    def _write_deny_policy(self, deny_list: list) -> None:
        """Create a Gemini policy JSON file from Claude Code deny rules.

        Writes ``.gemini/policies/harnesssync-policy.json`` with deny
        rules translated to Gemini's policy format. Each denied
        permission becomes a policy rule entry.

        Args:
            deny_list: List of permission strings from Claude Code deny list
        """
        policy_dir = self.project_dir / ".gemini" / "policies"
        ensure_dir(policy_dir)

        rules = []
        for perm in deny_list:
            tool, args = parse_permission_string(perm)
            rule = {
                "action": "deny",
                "tool": tool.lower() if tool else "unknown",
                "description": f"Denied by Claude Code: {perm}",
            }
            if args:
                rule["pattern"] = args
            rules.append(rule)

        policy = {
            "_comment": "Generated by HarnessSync from Claude Code deny permissions",
            "rules": rules,
        }

        policy_path = policy_dir / "harnesssync-policy.json"
        write_json_atomic(policy_path, policy)

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

    def sync_all(self, source_data: dict) -> dict[str, SyncResult]:
        """Sync all configuration types, then clean stale GEMINI.md subsections.

        Overrides base sync_all to add post-sync cleanup of legacy inlined
        Skills/Agents/Commands subsections from GEMINI.md. Cleanup only runs
        if all three native-format syncs (skills, agents, commands) completed
        without failures, to avoid data loss.

        Args:
            source_data: Dict with keys 'rules', 'skills', 'agents',
                        'commands', 'mcp', 'settings'

        Returns:
            Dict mapping config type to SyncResult
        """
        results = super().sync_all(source_data)

        # Only cleanup if all three native-format syncs succeeded (no failures)
        skills_ok = results.get('skills', SyncResult()).failed == 0
        agents_ok = results.get('agents', SyncResult()).failed == 0
        commands_ok = results.get('commands', SyncResult()).failed == 0

        if skills_ok and agents_ok and commands_ok:
            self.cleanup_legacy_inline_sections()

        return results

    def cleanup_legacy_inline_sections(self) -> int:
        """Remove stale Skills/Agents/Commands subsections from GEMINI.md.

        Public API for cleaning up legacy inlined subsections that are no longer
        needed after migration to native format files. Safe to call multiple times
        (idempotent -- returns 0 if no subsections found).

        Returns:
            Number of subsections removed (0-3)
        """
        return self._cleanup_stale_subsections()

    def _cleanup_stale_subsections(self) -> int:
        """Remove HarnessSync:Skills/Agents/Commands markers and content from GEMINI.md.

        Scans for subsection marker pairs (<!-- HarnessSync:X --> / <!-- End HarnessSync:X -->)
        and removes everything between and including the markers. Preserves the main
        managed section (<!-- Managed by HarnessSync -->) containing rules.

        Returns:
            Number of subsections removed (0-3)
        """
        content = self._read_gemini_md()
        if not content:
            return 0

        removed = 0
        for section in ["Skills", "Agents", "Commands"]:
            start_marker = f"<!-- HarnessSync:{section} -->"
            end_marker = f"<!-- End HarnessSync:{section} -->"

            if start_marker in content:
                start_idx = content.find(start_marker)
                end_idx = content.find(end_marker)
                if end_idx != -1:
                    end_pos = end_idx + len(end_marker)
                    before = content[:start_idx].rstrip()
                    after = content[end_pos:].lstrip()
                    if before and after:
                        content = f"{before}\n\n{after}"
                    else:
                        content = before or after
                    removed += 1

        if removed > 0:
            self._write_gemini_md(content.strip())

        return removed

    def _write_subsection(self, subsection_name: str, subsection_content: str) -> None:
        """Write or update a subsection within GEMINI.md.

        Legacy method -- retained for backward compatibility. Since Phase 13,
        sync_skills, sync_agents, and sync_commands write native format files
        instead of calling this method. Do NOT remove as other code may reference it.

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
