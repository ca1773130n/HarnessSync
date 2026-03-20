from __future__ import annotations

"""OpenCode CLI adapter for HarnessSync.

Implements adapter for OpenCode CLI, syncing Claude Code configuration to OpenCode format:
- Rules (CLAUDE.md) → AGENTS.md with managed markers (project root)
- Skills → Symlinks in .opencode/skills/
- Agents → Symlinks in .opencode/agents/
- Commands → Symlinks in .opencode/commands/
- MCP servers → opencode.json with type-discriminated format (local/remote)
- Settings → opencode.json permission (singular) with per-tool allow/ask/deny

The adapter uses native symlink support (not inline content) and type-discriminated
MCP server configs (type: "local" for stdio, type: "remote" for URL).
"""

import re
import sys
from pathlib import Path
from .base import AdapterBase, HARNESSSYNC_MARKER, HARNESSSYNC_MARKER_END
from .registry import AdapterRegistry
from .result import SyncResult
from src.exceptions import AdapterError
from src.utils.paths import (
    create_symlink_with_fallback,
    cleanup_stale_symlinks,
    ensure_dir,
    read_json_safe,
    write_json_atomic,
)
from src.utils.env_translator import check_transport_support, translate_env_vars_for_opencode_headers
from src.utils.permissions import extract_permissions, parse_permission_string
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
        """Sync CLAUDE.md rules to AGENTS.md or instructions array in opencode.json.

        When multiple rule sources exist, writes individual rule files to
        ``.opencode/rules/`` and references them as an ``instructions`` array
        in opencode.json. When only one rule source exists, falls back to the
        traditional AGENTS.md approach for backward compatibility.

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

        # Multi-source: write individual rule files + instructions array
        if len(rules) > 1:
            return self._sync_rules_multi_source(rules)

        # Single source: backward-compatible AGENTS.md approach
        return self._sync_rules_single_source(rules)

    def _sync_rules_single_source(self, rules: list[dict]) -> SyncResult:
        """Write rules to AGENTS.md (single source, backward compatible)."""
        rule_contents = [rule['content'] for rule in rules]
        concatenated = '\n\n---\n\n'.join(rule_contents)

        # Build managed section
        managed_section = self._build_managed_section(concatenated)

        # Read existing AGENTS.md or start fresh
        existing_content = self._read_managed_md(self.agents_md_path)

        # Replace or append managed section
        final_content = self._replace_managed_section(existing_content, managed_section)

        # Append per-harness override content (from .harness-sync/overrides/opencode.md)
        override = self.get_override_content()
        if override:
            final_content = final_content.rstrip() + f"\n\n{override}\n"

        # Write AGENTS.md
        self._write_managed_md(self.agents_md_path, final_content)

        return SyncResult(
            synced=1,
            adapted=len(rules),
            synced_files=[str(self.agents_md_path)]
        )

    def _sync_rules_multi_source(self, rules: list[dict]) -> SyncResult:
        """Write individual rule files to .opencode/rules/ and reference in opencode.json."""
        result = SyncResult()
        rules_dir = self.opencode_dir / "rules"
        ensure_dir(rules_dir)

        instruction_paths: list[str] = []

        for rule in rules:
            # Determine a filename from the source path
            source_path = rule.get('path')
            if source_path:
                source_path = Path(source_path)
                # Use scope-based naming: user-rules.md, project-rules.md, etc.
                scope = rule.get('scope', 'project')
                name_stem = source_path.stem.lower().replace(' ', '-')
                filename = f"{scope}-{name_stem}.md"
            else:
                filename = f"rules-{len(instruction_paths)}.md"

            rule_file = rules_dir / filename
            try:
                rule_file.write_text(rule['content'], encoding='utf-8')
                # Path relative to project root for opencode.json
                rel_path = f".opencode/rules/{filename}"
                instruction_paths.append(rel_path)
                result.synced += 1
                result.synced_files.append(str(rule_file))
            except OSError as e:
                result.failed += 1
                result.failed_files.append(f"{filename}: {e}")

        # Write instructions array to opencode.json
        if instruction_paths:
            try:
                existing_config = read_json_safe(self.opencode_json_path)
                existing_config['instructions'] = instruction_paths
                if '$schema' not in existing_config:
                    existing_config['$schema'] = 'https://opencode.ai/config.json'
                write_json_atomic(self.opencode_json_path, existing_config)
                result.synced_files.append(str(self.opencode_json_path))
            except (OSError, ValueError) as e:
                result.failed += 1
                result.failed_files.append(f"opencode.json instructions: {e}")
            except Exception as e:
                print(f"  [OpenCodeAdapter] unexpected error writing instructions: {e}", file=sys.stderr)
                result.failed += 1
                result.failed_files.append(f"opencode.json instructions: {e}")

        result.adapted = len(rules)
        return result

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

        # OpenCode natively discovers skills from .claude/skills/, so skip those
        claude_skills_dir = self.project_dir / ".claude" / "skills"

        # Create symlinks for each skill
        for name, source_path in skills.items():
            # Skip skills that OpenCode natively discovers from .claude/skills/
            try:
                if source_path.is_relative_to(claude_skills_dir):
                    result.skipped += 1
                    result.skipped_files.append(f"{name}: natively discovered by OpenCode from .claude/skills/")
                    continue
            except (ValueError, TypeError):
                pass  # Not relative to claude_skills_dir, proceed with symlink

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
        """Sync agents to .opencode/agents/ via symlinks AND write agent config to opencode.json.

        Creates symlinks from source agent .md files to .opencode/agents/{name}.md.
        Cleans up stale symlinks after creating all new symlinks.

        Additionally writes the new ``agent`` config shape to opencode.json::

            {
                "agent": {
                    "primary": "<first_agent>",
                    "agents": {
                        "<name>": {"instructions": "<content>"},
                        ...
                    }
                }
            }

        This replaces the deprecated ``mode`` key.

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

        # Build agent config for opencode.json
        agent_configs: dict[str, dict] = {}

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

                # Read agent content for opencode.json agent config
                try:
                    if agent_path.is_file():
                        content = agent_path.read_text(encoding='utf-8', errors='replace')
                        # Extract instructions from agent content (strip frontmatter)
                        instructions = self._extract_agent_instructions(content)
                        if instructions:
                            agent_configs[name] = {"instructions": instructions}
                except OSError:
                    pass  # Symlink created, just skip JSON config for this agent
            else:
                result.failed += 1
                result.failed_files.append(f"{name}: {method}")

        # Clean up stale symlinks
        cleaned = cleanup_stale_symlinks(target_dir)
        if cleaned > 0:
            result.skipped_files.append(f"cleaned: {cleaned} stale symlinks")

        # Write agent config to opencode.json (new shape, replacing deprecated "mode")
        if agent_configs:
            try:
                existing_config = read_json_safe(self.opencode_json_path)
                # Remove deprecated "mode" key
                existing_config.pop('mode', None)
                # Determine primary agent (first in sorted order for determinism)
                primary = sorted(agent_configs.keys())[0]
                existing_config['agent'] = {
                    "primary": primary,
                    "agents": agent_configs,
                }
                if '$schema' not in existing_config:
                    existing_config['$schema'] = 'https://opencode.ai/config.json'
                write_json_atomic(self.opencode_json_path, existing_config)
                result.adapted += len(agent_configs)
            except (OSError, ValueError) as e:
                result.failed_files.append(f"opencode.json agent config: {e}")
            except Exception as e:
                print(f"  [OpenCodeAdapter] unexpected error writing agent config: {e}", file=sys.stderr)
                result.failed_files.append(f"opencode.json agent config: {e}")

        return result

    @staticmethod
    def _extract_agent_instructions(content: str) -> str:
        """Extract instructions from agent .md content.

        Strips YAML frontmatter (between --- delimiters) and returns the body.
        Falls back to full content if no frontmatter found.

        Args:
            content: Raw agent .md file content

        Returns:
            Instruction text (body after frontmatter)
        """
        if content.startswith('---'):
            match = re.match(r'^---\n.*?\n---\n(.*)$', content, re.DOTALL)
            if match:
                return match.group(1).strip()
        return content.strip()

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

                    # Include headers if present (translate ${VAR} to {env:VAR})
                    if 'headers' in config:
                        translated_headers, header_warnings = translate_env_vars_for_opencode_headers(config['headers'])
                        server_config['headers'] = translated_headers
                        if header_warnings:
                            result.skipped_files.extend(header_warnings)

                    server_config['enabled'] = True

                else:
                    # Skip servers without command or url
                    result.skipped += 1
                    result.skipped_files.append(f"{server_name}: no command or url")
                    continue

                # Pass through timeout (direct map, ms)
                if 'timeout' in config:
                    server_config['timeout'] = config['timeout']

                # Pass through env for remote servers too (if not already mapped)
                if 'env' in config and 'environment' not in server_config:
                    server_config['env'] = config['env']

                # Drop unsupported fields:
                # - essential: not supported
                # - oauth_scopes: not supported
                # - elicitation: not supported
                # - enabled_tools / disabled_tools: not supported

                # Add to mcp section (override if exists)
                existing_config['mcp'][server_name] = server_config
                result.synced += 1

            # Add schema if not present
            if '$schema' not in existing_config:
                existing_config['$schema'] = 'https://opencode.ai/config.json'

            # Write atomically
            write_json_atomic(self.opencode_json_path, existing_config)

            result.synced_files.append(str(self.opencode_json_path))

        except (OSError, ValueError) as e:
            result.failed = len(mcp_servers)
            result.failed_files.append(f"MCP servers: {str(e)}")
        except Exception as e:
            print(f"  [OpenCodeAdapter] unexpected error syncing MCP: {e}", file=sys.stderr)
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

    # Claude Code tool name -> OpenCode permission identifier mapping
    TOOL_MAPPING = {
        'Bash': 'bash',
        'Read': 'read',
        'Write': 'edit',
        'Edit': 'edit',
        'Glob': 'glob',
        'Grep': 'grep',
        'WebFetch': 'webfetch',
        'WebSearch': 'websearch',
        'TodoWrite': 'todowrite',
        'TodoRead': 'todoread',
    }

    def sync_settings(self, settings: dict) -> SyncResult:
        """Map Claude Code settings to opencode.json permission (singular).

        Maps Claude Code permission settings to OpenCode per-tool permission format
        using ``parse_permission_string()`` to group by tool name:

        | Claude Code                      | opencode.json permission               |
        |----------------------------------|-----------------------------------------|
        | ``permissions.allow: ["Bash(npm *)"]`` | ``{"permission": {"bash": {"npm *": "allow"}}}`` |
        | ``permissions.deny: ["Bash(rm -rf *)"]`` | ``{"permission": {"bash": {"rm -rf *": "deny"}}}`` |
        | ``permissions.ask: ["Bash(git push *)"]`` | ``{"permission": {"bash": {"git push *": "ask"}}}`` |

        Format: group by tool name (lowercased), then glob pattern -> permission level.
        NEVER sets unrestricted mode.

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

            # Extract permissions from Claude Code settings
            permissions = extract_permissions(settings)
            allow_list = permissions.get('allow', [])
            deny_list = permissions.get('deny', [])
            ask_list = permissions.get('ask', [])

            # Build per-tool permission config using parse_permission_string
            # Group by tool name (lowercased), then pattern -> level
            permission_config: dict = {}

            # Process all three lists with their respective levels
            for perm_list, level in [
                (deny_list, 'deny'),
                (allow_list, 'allow'),
                (ask_list, 'ask'),
            ]:
                for perm in perm_list:
                    tool, args = parse_permission_string(perm)
                    if not tool:
                        continue

                    # Translate Claude Code colon-separated patterns to space-separated.
                    # Claude Code historically uses colons in some permission globs
                    # (e.g. "Bash(git commit:*)"), but OpenCode expects spaces in
                    # its permission dict keys (e.g. "git commit *").  This was the
                    # original behaviour before parse_permission_string was extracted.
                    if args:
                        args = args.replace(':', ' ')

                    # Map Claude Code tool name to OpenCode identifier
                    oc_tool = self.TOOL_MAPPING.get(tool, tool.lower())

                    if args:
                        # Tool with pattern args -> nested dict
                        if oc_tool not in permission_config:
                            permission_config[oc_tool] = {}
                        elif isinstance(permission_config[oc_tool], str):
                            # Upgrade from simple string to dict
                            old_val = permission_config[oc_tool]
                            permission_config[oc_tool] = {'*': old_val}
                        permission_config[oc_tool][args] = level
                    else:
                        # Bare tool name -> simple string value
                        if isinstance(permission_config.get(oc_tool), dict):
                            # Already has patterns; set default wildcard
                            permission_config[oc_tool]['*'] = level
                        else:
                            permission_config[oc_tool] = level

            # If any tool has specific patterns but no default, add "*": "ask"
            for tool_key, tool_val in permission_config.items():
                if isinstance(tool_val, dict) and '*' not in tool_val:
                    permission_config[tool_key]['*'] = 'ask'

            # Write permission (singular) key; remove old permissions (plural) if present
            if 'permissions' in existing_config:
                del existing_config['permissions']

            if permission_config:
                existing_config['permission'] = permission_config

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

        except (OSError, ValueError) as e:
            result.failed = 1
            result.failed_files.append(f"Settings: {str(e)}")
        except Exception as e:
            print(f"  [OpenCodeAdapter] unexpected error syncing settings: {e}", file=sys.stderr)
            result.failed = 1
            result.failed_files.append(f"Settings: {str(e)}")

        return result

    # ── Plugin Sync ─────────────────────────────────────────────────────────

    def sync_plugins(self, plugins: dict[str, dict]) -> SyncResult:
        """Sync plugins to OpenCode: native npm plugin first, decompose as fallback.

        For each Claude Code plugin:
        1. Check for native OpenCode npm plugin via _find_native_plugin()
           - If found -> add to opencode.json plugins array
        2. No equivalent -> decompose through existing pipelines
           - Skip TypeScript-specific event hooks (can't translate from shell/prompt hooks)

        Args:
            plugins: Dict mapping plugin_name -> plugin metadata dict

        Returns:
            SyncResult tracking synced/skipped/decomposed plugins
        """
        if not plugins:
            return SyncResult()

        result = SyncResult()
        native_plugins: list[dict] = []

        for plugin_name, meta in plugins.items():
            if not meta.get("enabled", True):
                result.skipped += 1
                result.skipped_files.append(f"{plugin_name}: disabled")
                continue

            native = self._find_native_plugin(plugin_name, meta.get("manifest", {}))

            if native:
                native_plugins.append({
                    "name": plugin_name,
                    "native_id": native,
                    "version": meta.get("version", "unknown"),
                })
                result.synced += 1
                result.synced_files.append(f"{plugin_name} -> {native} (native)")
            else:
                if not meta.get("install_path"):
                    result.skipped += 1
                    result.skipped_files.append(f"{plugin_name}: no install path")
                    continue

                decomposed, decompose_failures = self._decompose_plugin(plugin_name, meta)

                # Note: hooks are routed through sync_hooks (which is a no-op for OpenCode)
                # but add an informational message if the plugin has hooks
                if meta.get("has_hooks"):
                    result.skipped_files.append(
                        f"{plugin_name}: hooks skipped (OpenCode uses TS event hooks)"
                    )

                if decomposed:
                    result.synced += 1
                    result.synced_files.append(f"{plugin_name} (decomposed)")
                    if decompose_failures:
                        result.failed_files.extend(
                            f"{plugin_name}: decompose failed for {comp}"
                            for comp in decompose_failures
                        )
                else:
                    result.skipped += 1
                    result.skipped_files.append(f"{plugin_name}: nothing to decompose")

        # Write native plugins to opencode.json
        if native_plugins:
            try:
                self._write_native_plugins_json(native_plugins)
            except OSError as e:
                print(f"  [OpenCodeAdapter] failed to write native plugins JSON: {e}", file=sys.stderr)
            except Exception as e:
                print(f"  [OpenCodeAdapter] unexpected error writing native plugins: {e}", file=sys.stderr)

        return result

    def _write_native_plugins_json(self, native_plugins: list[dict]) -> None:
        """Write native plugin references to opencode.json plugins array.

        Args:
            native_plugins: List of dicts with name, native_id, version
        """
        existing_config = read_json_safe(self.opencode_json_path)

        plugins_array = existing_config.get("plugins", [])
        if not isinstance(plugins_array, list):
            plugins_array = []

        # Build set of existing plugin IDs for dedup
        existing_ids = {
            p.get("id") or p.get("name", "")
            for p in plugins_array
            if isinstance(p, dict)
        }

        for plugin in native_plugins:
            native_id = plugin["native_id"]
            if native_id not in existing_ids:
                plugins_array.append({
                    "id": native_id,
                    "_source": f"harnesssync:{plugin['name']}",
                })

        existing_config["plugins"] = plugins_array

        if '$schema' not in existing_config:
            existing_config['$schema'] = 'https://opencode.ai/config.json'

        write_json_atomic(self.opencode_json_path, existing_config)

    # Helper methods for AGENTS.md management (using base class _read_managed_md/_write_managed_md)
