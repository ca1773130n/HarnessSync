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
    format_toml_value,
    write_toml_atomic,
    escape_toml_string,
    read_toml_safe,
)
from src.utils.env_translator import translate_env_vars_for_codex, check_transport_support
from src.utils.permissions import extract_permissions, parse_permission_string


# Codex CLI constants
HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"

# Thresholds for intent-based approval policy mapping (see _map_approval_policy)
CODEX_DENY_THRESHOLD = 3    # deny_list >= this -> "untrusted"
CODEX_ALLOW_THRESHOLD = 5   # allow_list >= this (with no denies) -> "never"
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

    def sync_rules(self, rules: list[dict], rules_files: list[dict] | None = None) -> SyncResult:
        """Sync CLAUDE.md rules to AGENTS.md with managed markers.

        Concatenates all rule file contents into a single managed section in AGENTS.md.
        Preserves any user content above the HarnessSync marker. If AGENTS.md doesn't
        exist, creates it with just the managed section.

        When *rules_files* contains entries with subdirectory paths (relative to the
        project root), additional AGENTS.md files are created in those subdirectories
        to leverage Codex's ``child_agents_md`` discovery mechanism.

        Args:
            rules: List of rule dicts with 'path' (Path) and 'content' (str) keys
            rules_files: Optional list of rules_files dicts with 'path', 'content',
                        'scope', 'scope_patterns' keys. Used for hierarchical AGENTS.md.

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

        result = SyncResult(
            synced=1,
            adapted=len(rules),
            synced_files=[str(self.agents_md_path)]
        )

        # Write hierarchical AGENTS.md for subdirectory rules_files
        if rules_files:
            sub_result = self._write_subdirectory_agents_md(rules_files, timestamp)
            result = result.merge(sub_result)

        return result

    def _write_subdirectory_agents_md(self, rules_files: list[dict], timestamp: str) -> SyncResult:
        """Write AGENTS.md files in subdirectories for Codex child_agents_md discovery.

        Codex discovers AGENTS.md files in subdirectories automatically. When Claude Code
        has project-scoped rules in .claude/rules/ with path-based scoping, we create
        AGENTS.md files in the corresponding subdirectories.

        Args:
            rules_files: List of rules_files dicts with 'path', 'content', 'scope_patterns'
            timestamp: ISO timestamp string for managed section

        Returns:
            SyncResult tracking subdirectory AGENTS.md files written
        """
        result = SyncResult()

        for rule_file in rules_files:
            scope_patterns = rule_file.get('scope_patterns', [])
            content = rule_file.get('content', '')
            if not scope_patterns or not content.strip():
                continue

            # Use the first scope pattern to determine subdirectory
            for pattern in scope_patterns:
                # Extract directory prefix from glob pattern (e.g., "src/api/**" -> "src/api")
                subdir = self._extract_subdir_from_pattern(pattern)
                if not subdir:
                    continue

                subdir_path = self.project_dir / subdir
                if not subdir_path.is_dir():
                    # Only create if the directory already exists in the project
                    continue

                sub_agents_md = subdir_path / AGENTS_MD
                managed = f"""{HARNESSSYNC_MARKER}
# Subdirectory rules synced from Claude Code

{content}

---
*Last synced by HarnessSync: {timestamp}*
{HARNESSSYNC_MARKER_END}"""

                try:
                    # Read existing or create
                    existing = ""
                    if sub_agents_md.exists():
                        existing = sub_agents_md.read_text(encoding='utf-8', errors='replace')
                    final = self._replace_managed_section(existing, managed)
                    sub_agents_md.write_text(final, encoding='utf-8')
                    result.synced += 1
                    result.synced_files.append(str(sub_agents_md))
                except OSError as e:
                    result.failed += 1
                    result.failed_files.append(f"{sub_agents_md}: {e}")
                break  # Only use first matching pattern per rule file

        return result

    @staticmethod
    def _extract_subdir_from_pattern(pattern: str) -> str:
        """Extract the directory prefix from a glob/path pattern.

        Examples:
            "src/api/**/*.ts"  -> "src/api"
            "src/components/*" -> "src/components"
            "**/*.py"          -> ""  (no fixed prefix)
            "docs/"            -> "docs"

        Args:
            pattern: Glob pattern string

        Returns:
            Directory prefix, or empty string if no fixed prefix
        """
        # Remove trailing slash
        pattern = pattern.rstrip('/')
        parts = pattern.split('/')
        # Collect parts before any glob wildcard
        prefix_parts = []
        for part in parts:
            if '*' in part or '?' in part or '[' in part:
                break
            prefix_parts.append(part)
        return '/'.join(prefix_parts)

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

    def sync_all(self, source_data: dict) -> dict[str, SyncResult]:
        """Override sync_all to pass rules_files to sync_rules for hierarchical AGENTS.md.

        Args:
            source_data: Dict with keys 'rules', 'rules_files', 'skills', 'agents',
                        'commands', 'mcp', 'settings'

        Returns:
            Dict mapping config type to SyncResult
        """
        results = {}

        # Pre-sync: warn about deprecated config fields
        settings_output = source_data.get('settings', {})
        if settings_output:
            dep_warnings = self.check_deprecations(settings_output)
            for w in dep_warnings:
                import sys
                print(f"  \u26a0  {w}", file=sys.stderr)

        # Sync rules with rules_files for hierarchical AGENTS.md
        try:
            results['rules'] = self.sync_rules(
                source_data.get('rules', []),
                rules_files=source_data.get('rules_files', None),
            )
        except Exception as e:
            results['rules'] = SyncResult(
                failed=1,
                failed_files=[f'rules: {str(e)}']
            )

        # Sync remaining types via parent class pattern
        for config_type, method_name, data_key, default in [
            ('skills', 'sync_skills', 'skills', {}),
            ('agents', 'sync_agents', 'agents', {}),
            ('commands', 'sync_commands', 'commands', {}),
            ('settings', 'sync_settings', 'settings', {}),
        ]:
            try:
                method = getattr(self, method_name)
                results[config_type] = method(source_data.get(data_key, default))
            except Exception as e:
                results[config_type] = SyncResult(
                    failed=1,
                    failed_files=[f'{config_type}: {str(e)}']
                )

        # Sync MCP servers (use scoped data if available, fall back to flat)
        try:
            mcp_scoped = source_data.get('mcp_scoped', {})
            if mcp_scoped:
                results['mcp'] = self.sync_mcp_scoped(mcp_scoped)
            else:
                results['mcp'] = self.sync_mcp(source_data.get('mcp', {}))
        except Exception as e:
            results['mcp'] = SyncResult(
                failed=1,
                failed_files=[f'mcp: {str(e)}']
            )

        # Sync hooks
        try:
            results['hooks'] = self.sync_hooks(source_data.get('hooks', {}))
        except Exception as e:
            results['hooks'] = SyncResult(
                failed=1,
                failed_files=[f'hooks: {str(e)}']
            )

        # Sync plugins
        try:
            results['plugins'] = self.sync_plugins(source_data.get('plugins', {}))
        except Exception as e:
            results['plugins'] = SyncResult(
                failed=1,
                failed_files=[f'plugins: {str(e)}']
            )

        return results

    # ── Hooks Sync ─────────────────────────────────────────────────────────────

    # Codex event mapping (Claude Code event -> Codex event)
    _CODEX_EVENT_MAP: dict[str, str] = {
        "SessionStart": "SessionStart",
        "Stop": "Stop",
        "PostToolUse": "AfterToolUse",  # Rename
    }
    # Events to skip (unsupported by Codex)
    _CODEX_SKIP_EVENTS: set[str] = {"PreToolUse"}

    def sync_hooks(self, hooks: dict) -> SyncResult:
        """Sync hooks to Codex config.toml (experimental, gated behind features.hooks).

        Codex hooks are experimental and require ``[features] hooks = true`` in config.
        If the feature flag is not set, available hooks are documented in AGENTS.md
        instead of being written to config.toml. NEVER enables the flag automatically.

        Event mapping:
        - SessionStart -> SessionStart (direct)
        - Stop -> Stop (direct)
        - PostToolUse -> AfterToolUse (rename)
        - PreToolUse -> Skip (unsupported)
        - HTTP hooks -> Skip (shell-only)

        Args:
            hooks: Dict with 'hooks' key containing list of normalized hook dicts

        Returns:
            SyncResult tracking synced/skipped hooks
        """
        hook_list = hooks.get("hooks", []) if isinstance(hooks, dict) else []
        if not hook_list:
            return SyncResult()

        result = SyncResult()

        # Check if the feature gate is enabled
        config_path = self.project_dir / ".codex" / CONFIG_TOML
        feature_enabled = self._codex_hooks_feature_enabled(config_path)

        # Map hooks to Codex events
        mapped_hooks: list[dict] = []
        for hook in hook_list:
            event = hook.get("event", "")
            hook_type = hook.get("type", "shell")

            # Skip HTTP hooks (Codex is shell-only)
            if hook_type == "http":
                result.skipped += 1
                result.skipped_files.append(f"{event}: HTTP hooks not supported by Codex")
                continue

            # Skip unsupported events
            if event in self._CODEX_SKIP_EVENTS:
                result.skipped += 1
                result.skipped_files.append(f"{event}: not supported by Codex")
                continue

            # Map event name
            codex_event = self._CODEX_EVENT_MAP.get(event)
            if codex_event is None:
                result.skipped += 1
                result.skipped_files.append(f"{event}: no Codex equivalent")
                continue

            mapped_hooks.append({
                "event": codex_event,
                "command": hook.get("command", ""),
                "matcher": hook.get("matcher", ""),
            })

        if not mapped_hooks:
            return result

        if feature_enabled:
            # Write hooks to config.toml under [[hooks.EVENT]] sections
            try:
                self._write_codex_hooks(config_path, mapped_hooks)
                result.synced = len(mapped_hooks)
                result.synced_files.append(str(config_path))
            except Exception as e:
                result.failed = len(mapped_hooks)
                result.failed_files.append(f"hooks: {str(e)}")
        else:
            # Document available hooks in AGENTS.md (feature gate not set)
            self._document_hooks_in_agents_md(mapped_hooks)
            result.skipped = len(mapped_hooks)
            result.skipped_files.append(
                "hooks: documented in AGENTS.md (enable [features] hooks = true in Codex config to activate)"
            )

        return result

    @staticmethod
    def _codex_hooks_feature_enabled(config_path: Path) -> bool:
        """Check if Codex has the experimental hooks feature flag enabled.

        Looks for ``[features]`` section with ``hooks = true`` in config.toml.

        Args:
            config_path: Path to Codex config.toml

        Returns:
            True if hooks feature is explicitly enabled
        """
        existing = read_toml_safe(config_path)
        features = existing.get("features", {})
        if isinstance(features, dict):
            return features.get("hooks") is True
        return False

    def _write_codex_hooks(self, config_path: Path, mapped_hooks: list[dict]) -> None:
        """Write mapped hooks to Codex config.toml under [[hooks.EVENT]] sections.

        Merges with existing config.toml, preserving non-hook settings.
        Replaces existing HarnessSync-managed hook sections.

        Args:
            config_path: Path to Codex config.toml
            mapped_hooks: List of mapped hook dicts with event, command, matcher
        """
        # Read existing config
        existing_raw = ""
        if config_path.exists():
            try:
                existing_raw = config_path.read_text(encoding="utf-8")
            except OSError:
                pass

        # Remove existing HarnessSync hooks sections
        import re as _re
        cleaned = _re.sub(
            r'# Hooks managed by HarnessSync.*?(?=\n(?:\[(?!hooks\.)|# [A-Z]|$))',
            '', existing_raw, flags=_re.DOTALL
        ).rstrip()

        # Build hooks TOML sections
        hook_lines = [
            "",
            "# Hooks managed by HarnessSync",
            "# Do not edit manually - changes will be overwritten on next sync",
        ]

        for hook in mapped_hooks:
            event = hook["event"]
            command = hook.get("command", "")
            matcher = hook.get("matcher", "")
            hook_lines.append("")
            hook_lines.append(f'[[hooks.{event}]]')
            hook_lines.append(f'command = {format_toml_value(command)}')
            if matcher:
                hook_lines.append(f'matcher = {format_toml_value(matcher)}')

        final = cleaned + "\n" + "\n".join(hook_lines) + "\n"
        write_toml_atomic(config_path, final)

    def _document_hooks_in_agents_md(self, mapped_hooks: list[dict]) -> None:
        """Document available hooks in AGENTS.md when feature gate is not set.

        Informs the user about hooks that could be activated by enabling the
        experimental feature flag, without actually enabling it.

        Args:
            mapped_hooks: List of mapped hook dicts with event, command, matcher
        """
        lines = [
            "",
            "## Available Hooks (requires Codex feature flag)",
            "",
            "> **Note:** The following hooks from Claude Code are available but require",
            "> `[features] hooks = true` in your Codex config.toml to activate.",
            "> HarnessSync will NOT enable experimental features without your consent.",
            "",
        ]

        for hook in mapped_hooks:
            event = hook.get("event", "")
            command = hook.get("command", "")[:80]
            matcher = hook.get("matcher", "")
            desc = f"- **{event}**"
            if matcher:
                desc += f" (matcher: `{matcher}`)"
            if command:
                desc += f": `{command}`"
            lines.append(desc)

        lines.append("")
        hook_section = "\n".join(lines)

        existing = self._read_agents_md()
        if existing and HARNESSSYNC_MARKER_END in existing:
            end_idx = existing.find(HARNESSSYNC_MARKER_END)
            before = existing[:end_idx].rstrip()
            after = existing[end_idx:]
            final = f"{before}\n{hook_section}\n{after}"
            self._write_agents_md(final)
        elif existing:
            self._write_agents_md(f"{existing.rstrip()}\n{hook_section}\n")

    # ── Plugin Sync ─────────────────────────────────────────────────────────

    def sync_plugins(self, plugins: dict[str, dict]) -> SyncResult:
        """Sync plugins to Codex: native equivalent first, decompose as fallback.

        For each Claude Code plugin:
        1. Check for native Codex equivalent via _find_native_plugin()
           - If found -> add to .codex/config.toml plugins section
        2. No equivalent -> decompose through existing pipelines
           - Skills -> sync_skills()
           - Agents -> sync_agents()
           - Commands -> sync_commands()
           - MCP servers -> sync_mcp()
           - Hooks -> sync_hooks()
        3. Plugin metadata -> surface in AGENTS.md as informational context

        Args:
            plugins: Dict mapping plugin_name -> plugin metadata dict

        Returns:
            SyncResult tracking synced/skipped/decomposed plugins
        """
        if not plugins:
            return SyncResult()

        result = SyncResult()
        native_plugins: list[dict] = []
        decomposed_names: list[str] = []

        for plugin_name, meta in plugins.items():
            if not meta.get("enabled", True):
                result.skipped += 1
                result.skipped_files.append(f"{plugin_name}: disabled")
                continue

            # Check for native equivalent
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
                # Decompose: route plugin contents through existing pipelines
                install_path = meta.get("install_path")
                if not install_path:
                    result.skipped += 1
                    result.skipped_files.append(f"{plugin_name}: no install path")
                    continue

                from pathlib import Path
                install_path = Path(install_path)
                decomposed = False

                # Route skills
                if meta.get("has_skills"):
                    try:
                        skills_dir = install_path / "skills"
                        plugin_skills = {}
                        for d in skills_dir.iterdir():
                            if d.is_dir() and (d / "SKILL.md").exists():
                                plugin_skills[d.name] = d
                        if plugin_skills:
                            self.sync_skills(plugin_skills)
                            decomposed = True
                    except Exception:
                        pass

                # Route agents
                if meta.get("has_agents"):
                    try:
                        agents_dir = install_path / "agents"
                        plugin_agents = {}
                        for f in agents_dir.iterdir():
                            if f.suffix == ".md" and f.is_file():
                                plugin_agents[f.stem] = f
                        if plugin_agents:
                            self.sync_agents(plugin_agents)
                            decomposed = True
                    except Exception:
                        pass

                # Route commands
                if meta.get("has_commands"):
                    try:
                        commands_dir = install_path / "commands"
                        plugin_commands = {}
                        for f in commands_dir.iterdir():
                            if f.suffix == ".md" and f.is_file():
                                plugin_commands[f.stem] = f
                        if plugin_commands:
                            self.sync_commands(plugin_commands)
                            decomposed = True
                    except Exception:
                        pass

                # Route MCP servers
                if meta.get("has_mcp"):
                    try:
                        from src.utils.paths import read_json_safe
                        mcp_json = install_path / ".mcp.json"
                        if mcp_json.exists():
                            mcp_data = read_json_safe(mcp_json)
                            servers = mcp_data.get("mcpServers", mcp_data)
                            if isinstance(servers, dict) and servers:
                                self.sync_mcp(servers)
                                decomposed = True
                    except Exception:
                        pass

                # Route hooks
                if meta.get("has_hooks"):
                    try:
                        hooks_json = install_path / "hooks" / "hooks.json"
                        if hooks_json.exists():
                            from src.utils.paths import read_json_safe
                            hooks_data = read_json_safe(hooks_json)
                            if hooks_data:
                                self.sync_hooks(hooks_data)
                                decomposed = True
                    except Exception:
                        pass

                if decomposed:
                    result.synced += 1
                    result.synced_files.append(f"{plugin_name} (decomposed)")
                    decomposed_names.append(plugin_name)
                else:
                    result.skipped += 1
                    result.skipped_files.append(f"{plugin_name}: nothing to decompose")

        # Write native plugins to config.toml plugins section
        if native_plugins:
            try:
                self._write_native_plugins_toml(native_plugins)
            except Exception:
                pass  # Best-effort

        # Document plugin info in AGENTS.md
        if native_plugins or decomposed_names:
            try:
                self._document_plugins_in_agents_md(native_plugins, decomposed_names)
            except Exception:
                pass  # Best-effort

        return result

    def _write_native_plugins_toml(self, native_plugins: list[dict]) -> None:
        """Write native plugin references to Codex config.toml.

        Args:
            native_plugins: List of dicts with name, native_id, version
        """
        config_path = self.project_dir / ".codex" / CONFIG_TOML

        existing_raw = ""
        if config_path.exists():
            try:
                existing_raw = config_path.read_text(encoding="utf-8")
            except OSError:
                pass

        # Remove existing HarnessSync plugins section
        import re as _re
        cleaned = _re.sub(
            r'# Plugins managed by HarnessSync.*?(?=\n(?:\[(?!plugins)|# [A-Z]|$))',
            '', existing_raw, flags=_re.DOTALL
        ).rstrip()

        # Build plugins TOML section
        plugin_lines = [
            "",
            "# Plugins managed by HarnessSync",
            "# Do not edit manually - changes will be overwritten on next sync",
        ]

        for plugin in native_plugins:
            plugin_lines.append("")
            plugin_lines.append(f'[[plugins]]')
            plugin_lines.append(f'name = {format_toml_value(plugin["native_id"])}')
            plugin_lines.append(f'# source: {plugin["name"]} v{plugin["version"]}')

        final = cleaned + "\n" + "\n".join(plugin_lines) + "\n"
        write_toml_atomic(config_path, final)

    def _document_plugins_in_agents_md(
        self, native_plugins: list[dict], decomposed_names: list[str]
    ) -> None:
        """Document synced plugin information in AGENTS.md.

        Args:
            native_plugins: List of native plugin reference dicts
            decomposed_names: List of plugin names that were decomposed
        """
        lines = [
            "",
            "## Synced Plugins (from Claude Code)",
            "",
        ]

        if native_plugins:
            lines.append("### Native Equivalents")
            lines.append("")
            for p in native_plugins:
                lines.append(f"- **{p['name']}** -> `{p['native_id']}` (native Codex plugin)")
            lines.append("")

        if decomposed_names:
            lines.append("### Decomposed Plugins")
            lines.append("")
            lines.append("> These plugins had no native Codex equivalent.")
            lines.append("> Their skills, agents, commands, MCP servers, and hooks were synced individually.")
            lines.append("")
            for name in decomposed_names:
                lines.append(f"- **{name}**")
            lines.append("")

        plugin_section = "\n".join(lines)

        existing = self._read_agents_md()
        if existing and HARNESSSYNC_MARKER_END in existing:
            end_idx = existing.find(HARNESSSYNC_MARKER_END)
            before = existing[:end_idx].rstrip()
            after = existing[end_idx:]
            final = f"{before}\n{plugin_section}\n{after}"
            self._write_agents_md(final)
        elif existing:
            self._write_agents_md(f"{existing.rstrip()}\n{plugin_section}\n")

    # Environment variable key substrings that indicate bearer token / auth credentials
    _AUTH_ENV_KEYWORDS = ('TOKEN', 'KEY', 'AUTH', 'BEARER', 'SECRET')

    @staticmethod
    def _translate_mcp_fields(config: dict) -> dict:
        """Translate Claude Code MCP fields to Codex equivalents.

        Field mapping:
        - timeout (ms) -> tool_timeout_sec (seconds, divide by 1000)
        - oauth_scopes -> scopes
        - elicitation -> elicitation (pass through, Codex supports natively)
        - enabled_tools -> enabled_tools (direct)
        - disabled_tools -> disabled_tools (direct)
        - essential -> dropped (no Codex equivalent)
        - url (remote) + env with auth var -> url + bearer_token_env_var

        Args:
            config: Source MCP server config dict

        Returns:
            New dict with Codex-compatible field names
        """
        translated = dict(config)

        # timeout (ms) -> tool_timeout_sec (seconds)
        if 'timeout' in translated:
            timeout_ms = translated.pop('timeout')
            if isinstance(timeout_ms, (int, float)) and timeout_ms > 0:
                translated['tool_timeout_sec'] = int(timeout_ms / 1000)

        # oauth_scopes -> scopes
        if 'oauth_scopes' in translated:
            scopes = translated.pop('oauth_scopes')
            if isinstance(scopes, list):
                translated['scopes'] = scopes

        # elicitation: pass through (Codex supports natively)
        # No transformation needed, already in translated dict

        # enabled_tools / disabled_tools: direct passthrough
        # No transformation needed, already in translated dict

        # essential: drop silently (no Codex equivalent)
        translated.pop('essential', None)

        # Remote URL servers: detect auth env var and set bearer_token_env_var
        if 'url' in translated and 'bearer_token_env_var' not in translated:
            env = translated.get('env')
            if isinstance(env, dict):
                for env_key in env:
                    env_key_upper = env_key.upper()
                    if any(kw in env_key_upper for kw in CodexAdapter._AUTH_ENV_KEYWORDS):
                        translated['bearer_token_env_var'] = env_key
                        break

        return translated

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

        # Translate Claude Code fields to Codex equivalents
        translated_servers = {
            name: self._translate_mcp_fields(cfg)
            for name, cfg in mcp_servers.items()
        }

        config_path = self.project_dir / ".codex" / CONFIG_TOML
        return self._write_mcp_to_path(translated_servers, config_path)

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

            # Translate Claude Code MCP fields to Codex equivalents
            translated_config = self._translate_mcp_fields(translated_config)

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

        Additional settings mapped:
        - modelOverrides -> [profiles.*] TOML sections
        - attribution -> command_attribution boolean

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

            # Map attribution -> command_attribution
            attribution = settings.get('attribution')
            if attribution is not None:
                attr_value = self._map_attribution(attribution)
                if attr_value is not None:
                    settings_lines.append(
                        f'command_attribution = {format_toml_value(attr_value)}'
                    )

            settings_section = '\n'.join(settings_lines)

            # Build profiles section from modelOverrides
            profiles_section = ''
            model_overrides = settings.get('modelOverrides')
            if isinstance(model_overrides, dict) and model_overrides:
                profiles_section = self._map_model_overrides(model_overrides)

            # Preserve MCP servers section if present
            mcp_section = ''
            if 'mcp_servers' in existing_config:
                # Re-generate MCP section from existing config
                mcp_section = format_mcp_servers_toml(existing_config['mcp_servers'])

            # Extract non-managed sections for preservation
            preserved = self._extract_unmanaged_toml(config_path)

            # Build complete config.toml
            final_toml = self._build_config_toml(
                settings_section, mcp_section, preserved,
                profiles_section=profiles_section,
            )

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

    @staticmethod
    def _map_attribution(attribution) -> bool | None:
        """Convert Claude Code attribution setting to Codex command_attribution boolean.

        Handles multiple input shapes:
        - bool: direct passthrough
        - str: "true"/"false" (case-insensitive), any other truthy string -> True
        - dict with 'enabled' key: use that value
        - None / unrecognized: return None (skip)

        Args:
            attribution: Raw attribution value from Claude Code settings

        Returns:
            Boolean for Codex command_attribution, or None to skip
        """
        if isinstance(attribution, bool):
            return attribution
        if isinstance(attribution, str):
            lower = attribution.lower().strip()
            if lower == 'false':
                return False
            if lower == 'true' or lower:
                return True
            return None
        if isinstance(attribution, dict):
            enabled = attribution.get('enabled')
            if isinstance(enabled, bool):
                return enabled
            if isinstance(enabled, str):
                return enabled.lower().strip() != 'false'
            return None
        return None

    @staticmethod
    def _map_model_overrides(model_overrides: dict) -> str:
        """Convert Claude Code modelOverrides to Codex [profiles.*] TOML sections.

        Claude Code format:
            {"planning": "opus", "coding": "sonnet", "review": "opus"}

        Codex format:
            [profiles.planning]
            model = "opus"

            [profiles.coding]
            model = "sonnet"

            [profiles.review]
            model = "opus"

        Args:
            model_overrides: Dict mapping task type to model name

        Returns:
            TOML string with [profiles.*] sections
        """
        lines = []
        for task_type, model_name in model_overrides.items():
            if not isinstance(task_type, str) or not task_type.strip():
                continue
            if not isinstance(model_name, str) or not model_name.strip():
                continue
            if lines:
                lines.append('')
            lines.append(f'[profiles.{task_type}]')
            lines.append(f'model = {format_toml_value(model_name)}')
        return '\n'.join(lines)

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
            if stripped.startswith('command_attribution') and '=' in stripped:
                continue

            # Track table headers
            if stripped.startswith('['):
                if stripped.startswith('[mcp_servers') or stripped.startswith('[profiles.'):
                    in_mcp_section = True
                    continue
                else:
                    in_mcp_section = False

            # Skip lines inside managed sections (mcp_servers, profiles)
            if in_mcp_section:
                continue

            kept_lines.append(line)

        # Strip leading/trailing blank lines
        result = '\n'.join(kept_lines).strip()
        return result

    def _build_config_toml(
        self,
        settings_section: str,
        mcp_section: str,
        preserved_sections: str = '',
        profiles_section: str = '',
    ) -> str:
        """Combine settings, profiles, and MCP sections into complete config.toml.

        Args:
            settings_section: Settings TOML content (sandbox_mode, approval_policy, etc.)
            mcp_section: MCP servers TOML content
            preserved_sections: Non-managed TOML sections to preserve
            profiles_section: [profiles.*] TOML sections from modelOverrides

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

        if profiles_section:
            lines.append(profiles_section)
            lines.append('')

        if mcp_section:
            lines.append(mcp_section)

        if preserved_sections:
            lines.append('')
            lines.append(preserved_sections)

        return '\n'.join(lines)
