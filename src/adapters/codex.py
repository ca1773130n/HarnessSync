from __future__ import annotations

"""Codex CLI adapter for HarnessSync.

Implements adapter for Codex CLI, syncing Claude Code configuration to Codex format:
- Rules (CLAUDE.md) → AGENTS.md with managed markers
- Skills → Symlinks in .agents/skills/
- Agents → SKILL.md format in .agents/skills/{name}/
- Commands → SKILL.md format in .agents/skills/cmd-{name}/
- MCP servers → config.toml
- Settings → config.toml sandbox/approval settings

The adapter preserves user-created content in AGENTS.md outside HarnessSync markers
and uses symlinks for zero-copy skill sharing.
"""

import re
import sys
from pathlib import Path
from .base import AdapterBase, HARNESSSYNC_MARKER, HARNESSSYNC_MARKER_END
from .registry import AdapterRegistry
from .result import SyncResult
from src.exceptions import AdapterError
from src.utils.paths import create_symlink_with_fallback, ensure_dir, read_json_safe
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
        managed_section = self._build_managed_section(concatenated)

        # Read existing AGENTS.md or start fresh
        existing_content = self._read_managed_md(self.agents_md_path)

        # Replace or append managed section
        final_content = self._replace_managed_section(existing_content, managed_section)

        # Append per-harness override content (from .harness-sync/overrides/codex.md)
        override = self.get_override_content()
        if override:
            final_content = final_content.rstrip() + f"\n\n{override}\n"

        # Write AGENTS.md
        self._write_managed_md(self.agents_md_path, final_content)

        result = SyncResult(
            synced=1,
            adapted=len(rules),
            synced_files=[str(self.agents_md_path)]
        )

        # Write hierarchical AGENTS.md for subdirectory rules_files
        # Also check _pending_rules_files from sync_all override
        effective_rules_files = rules_files or getattr(self, '_pending_rules_files', None)
        if effective_rules_files:
            sub_result = self._write_subdirectory_agents_md(effective_rules_files)
            result = result.merge(sub_result)

        return result

    def _write_subdirectory_agents_md(self, rules_files: list[dict]) -> SyncResult:
        """Write AGENTS.md files in subdirectories for Codex child_agents_md discovery.

        Codex discovers AGENTS.md files in subdirectories automatically. When Claude Code
        has project-scoped rules in .claude/rules/ with path-based scoping, we create
        AGENTS.md files in the corresponding subdirectories.

        Args:
            rules_files: List of rules_files dicts with 'path', 'content', 'scope_patterns'

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
                managed = self._build_managed_section(
                    content, header="Subdirectory rules synced from Claude Code"
                )

                try:
                    # Read existing or create
                    existing = self._read_managed_md(sub_agents_md)
                    final = self._replace_managed_section(existing, managed)
                    self._write_managed_md(sub_agents_md, final)
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
                except ImportError:
                    pass
                except Exception as e:
                    print(f"  [CodexAdapter] skill translation failed for {agent_name}: {e}", file=sys.stderr)

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

            except (OSError, UnicodeDecodeError) as e:
                result.failed += 1
                result.failed_files.append(f"{agent_name}: {str(e)}")
            except Exception as e:
                print(f"  [CodexAdapter] unexpected error syncing agent {agent_name}: {e}", file=sys.stderr)
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

            except (OSError, UnicodeDecodeError) as e:
                result.failed += 1
                result.failed_files.append(f"{cmd_name}: {str(e)}")
            except Exception as e:
                print(f"  [CodexAdapter] unexpected error syncing command {cmd_name}: {e}", file=sys.stderr)
                result.failed += 1
                result.failed_files.append(f"{cmd_name}: {str(e)}")

        return result

    def sync_all(self, source_data: dict) -> dict[str, SyncResult]:
        """Override sync_all to pass rules_files to sync_rules for hierarchical AGENTS.md.

        Delegates to base sync_all for all config types except rules, which
        receives the additional rules_files kwarg for subdirectory AGENTS.md.

        Args:
            source_data: Dict with keys 'rules', 'rules_files', 'skills', 'agents',
                        'commands', 'mcp', 'settings'

        Returns:
            Dict mapping config type to SyncResult
        """
        # Stash rules_files so sync_rules gets it via the override
        self._pending_rules_files = source_data.get('rules_files', None)
        try:
            return super().sync_all(source_data)
        finally:
            self._pending_rules_files = None

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
            except OSError as e:
                result.failed = len(mapped_hooks)
                result.failed_files.append(f"hooks: {str(e)}")
            except Exception as e:
                print(f"  [CodexAdapter] unexpected error writing hooks: {e}", file=sys.stderr)
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
        cleaned = re.sub(
            r'# Hooks managed by HarnessSync.*?(?=\n(?:\[(?!hooks\.)|# [A-Z]|$))',
            '', existing_raw, flags=re.DOTALL
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

        existing = self._read_managed_md(self.agents_md_path)
        if existing:
            final = self._insert_before_end_marker(existing, hook_section)
            self._write_managed_md(self.agents_md_path, final)

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
                if not meta.get("install_path"):
                    result.skipped += 1
                    result.skipped_files.append(f"{plugin_name}: no install path")
                    continue

                decomposed, decompose_failures = self._decompose_plugin(plugin_name, meta)

                if decomposed:
                    result.synced += 1
                    result.synced_files.append(f"{plugin_name} (decomposed)")
                    decomposed_names.append(plugin_name)
                    if decompose_failures:
                        result.failed_files.extend(
                            f"{plugin_name}: decompose failed for {comp}"
                            for comp in decompose_failures
                        )
                else:
                    result.skipped += 1
                    result.skipped_files.append(f"{plugin_name}: nothing to decompose")

        # Write native plugins to config.toml plugins section
        if native_plugins:
            try:
                self._write_native_plugins_toml(native_plugins)
            except OSError as e:
                print(f"  [CodexAdapter] failed to write native plugins TOML: {e}", file=sys.stderr)
            except Exception as e:
                print(f"  [CodexAdapter] unexpected error writing native plugins TOML: {e}", file=sys.stderr)

        # Document plugin info in AGENTS.md
        if native_plugins or decomposed_names:
            try:
                self._document_plugins_in_agents_md(native_plugins, decomposed_names)
            except OSError as e:
                print(f"  [CodexAdapter] failed to document plugins in AGENTS.md: {e}", file=sys.stderr)
            except Exception as e:
                print(f"  [CodexAdapter] unexpected error documenting plugins: {e}", file=sys.stderr)

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
        cleaned = re.sub(
            r'# Plugins managed by HarnessSync.*?(?=\n(?:\[(?!plugins)|# [A-Z]|$))',
            '', existing_raw, flags=re.DOTALL
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

        existing = self._read_managed_md(self.agents_md_path)
        if existing:
            final = self._insert_before_end_marker(existing, plugin_section)
            self._write_managed_md(self.agents_md_path, final)

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

        except (OSError, ValueError) as e:
            result.failed = len(mcp_servers)
            result.failed_files.append(f"MCP servers: {str(e)}")
        except Exception as e:
            print(f"  [CodexAdapter] unexpected error writing MCP to {config_path}: {e}", file=sys.stderr)
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

        except (OSError, ValueError) as e:
            result.failed = 1
            result.failed_files.append(f"Settings: {str(e)}")
        except Exception as e:
            print(f"  [CodexAdapter] unexpected error syncing settings: {e}", file=sys.stderr)
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

        # ANY deny rules -> never auto-approve, even with many allows
        if deny_list:
            return "on-request"

        # Permissive: many allow rules with no deny rules
        if len(allow_list) >= CODEX_ALLOW_THRESHOLD:
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
        existing = self._read_managed_md(self.agents_md_path)
        if existing:
            final = self._insert_before_end_marker(existing, warning_section)
            self._write_managed_md(self.agents_md_path, final)
        # If no AGENTS.md exists, skip — sync_rules will create it

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

        quoted_desc = self._quote_yaml_value(short_desc)

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
        - sandbox_mode, approval_policy, and command_attribution top-level keys
        - All [mcp_servers.*] sections
        - All [profiles.*] sections

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
