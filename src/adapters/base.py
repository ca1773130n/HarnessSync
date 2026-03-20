from __future__ import annotations

"""Abstract base class for target adapters.

AdapterBase defines the interface all target adapters (Codex, Gemini, OpenCode)
must implement. It enforces 8 sync methods for different configuration types:
- sync_rules: CLAUDE.md rules
- sync_skills: Skills directory
- sync_agents: Agent .md files
- sync_commands: Command .md files
- sync_mcp: MCP server configurations
- sync_settings: General settings
- sync_hooks: Hook configurations
- sync_plugins: Plugin configurations

The abstract base class pattern ensures type safety and prevents incomplete
adapter implementations.

Example usage:
    @AdapterRegistry.register("codex")
    class CodexAdapter(AdapterBase):
        @property
        def target_name(self) -> str:
            return "codex"

        def sync_rules(self, rules: list[dict]) -> SyncResult:
            # Implementation
            pass

        # ... implement other sync methods ...
"""

import json
import re
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from .result import SyncResult
from src.exceptions import AdapterError

# Shared HarnessSync markers used by all adapters
HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"


class AdapterBase(ABC):
    """Abstract base class for target adapters."""

    def __init__(self, project_dir: Path):
        """Initialize adapter with project directory.

        Args:
            project_dir: Root directory of the project being synced
        """
        self.project_dir = project_dir

    @property
    @abstractmethod
    def target_name(self) -> str:
        """Return target CLI name (e.g., "codex", "gemini").

        Returns:
            Target CLI identifier
        """
        pass

    @abstractmethod
    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync CLAUDE.md rules to target format.

        Args:
            rules: List of rule dicts with 'path' (Path) and 'content' (str) keys

        Returns:
            SyncResult tracking synced/skipped/failed rules
        """
        pass

    @abstractmethod
    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to target skills directory.

        Args:
            skills: Dict mapping skill name to skill directory path

        Returns:
            SyncResult tracking synced/skipped/failed skills
        """
        pass

    @abstractmethod
    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Convert and sync agents to target format.

        Args:
            agents: Dict mapping agent name to agent .md file path

        Returns:
            SyncResult tracking synced/skipped/failed agents
        """
        pass

    @abstractmethod
    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Convert and sync commands to target format.

        Args:
            commands: Dict mapping command name to command .md file path

        Returns:
            SyncResult tracking synced/skipped/failed commands
        """
        pass

    @abstractmethod
    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Translate MCP server configs to target format.

        Args:
            mcp_servers: Dict mapping server name to server config dict

        Returns:
            SyncResult tracking synced/skipped/failed MCP servers
        """
        pass

    def sync_mcp_scoped(self, mcp_servers_scoped: dict[str, dict]) -> SyncResult:
        """Translate MCP server configs with scope metadata to target format.

        Receives scoped format:
            {server_name: {"config": {...}, "metadata": {"scope": "user|project|local", "source": "file|plugin", ...}}}

        Default implementation falls back to sync_mcp() with flat config for
        backward compatibility. Adapters override this for scope-aware routing.

        Args:
            mcp_servers_scoped: Dict mapping server name to scoped server data

        Returns:
            SyncResult tracking synced/skipped/failed MCP servers
        """
        flat = {name: entry.get("config", entry) for name, entry in mcp_servers_scoped.items()}
        return self.sync_mcp(flat)

    @abstractmethod
    def sync_settings(self, settings: dict) -> SyncResult:
        """Map settings to target configuration.

        Args:
            settings: Settings dict from Claude Code configuration

        Returns:
            SyncResult tracking synced/skipped/failed settings
        """
        pass

    def sync_plugins(self, plugins: dict[str, dict]) -> SyncResult:
        """Sync plugins to target format.

        Default no-op implementation -- returns all plugins as skipped.
        Adapters with native plugin support override this to implement
        the two-tier strategy: native equivalent first, decompose as fallback.

        Args:
            plugins: Dict mapping plugin_name -> plugin metadata dict.
                     Each dict has: enabled, version, install_path,
                     has_skills, has_agents, has_commands, has_mcp, has_hooks,
                     manifest.

        Returns:
            SyncResult with all plugins skipped
        """
        return SyncResult(skipped=len(plugins))

    def _find_native_plugin(self, plugin_name: str, manifest: dict) -> str | None:
        """Check if a native equivalent exists for a Claude Code plugin.

        Looks up PLUGIN_EQUIVALENTS + user overrides from `.harnesssync` config.

        Args:
            plugin_name: Claude Code plugin identifier
            manifest: Plugin manifest dict (currently unused, reserved for future matching)

        Returns:
            Native plugin identifier string if equivalent found, or None
        """
        try:
            from src.plugin_registry import lookup_native_equivalent, load_user_plugin_map
            user_overrides = load_user_plugin_map(self.project_dir)
            return lookup_native_equivalent(plugin_name, self.target_name, user_overrides)
        except ImportError:
            return None
        except Exception as e:
            print(f"  [AdapterBase] plugin lookup failed for {plugin_name}: {e}", file=sys.stderr)
            return None

    def sync_hooks(self, hooks: dict) -> SyncResult:
        """Sync hooks to target format.

        Default no-op implementation — returns all hooks as skipped.
        Only adapters with native hook support (Codex, Gemini) override this.

        Args:
            hooks: Dict with 'hooks' key containing list of normalized hook dicts.
                   Each dict has: event, type, command/url, matcher, timeout, scope.

        Returns:
            SyncResult with all hooks skipped
        """
        hook_list = hooks.get("hooks", []) if isinstance(hooks, dict) else []
        return SyncResult(skipped=len(hook_list))

    def get_override_content(self) -> str:
        """Read per-harness override content from .harness-sync/overrides/<target>.md.

        Override files let users append harness-specific instructions to the
        synced config without polluting CLAUDE.md. Content is appended after
        the HarnessSync-managed section in the target file.

        Returns:
            Override content string, or empty string if no override file exists.
        """
        override_path = self.project_dir / ".harness-sync" / "overrides" / f"{self.target_name}.md"
        if override_path.is_file():
            try:
                return override_path.read_text(encoding="utf-8").strip()
            except OSError:
                pass
        return ""

    @staticmethod
    def adapt_command_content(content: str) -> str:
        """Adapt Claude Code command content for use in other targets.

        Replaces Claude Code-specific syntax with portable equivalents:
        - $ARGUMENTS -> [user-provided arguments]
        """
        return content.replace('$ARGUMENTS', '[user-provided arguments]')

    def check_deprecations(self, output: "dict | str") -> list[str]:
        """Check adapter output for deprecated config fields before writing.

        Delegates to ``check_deprecated_fields_in_output`` in
        ``harness_version_compat`` using this adapter's ``target_name``.
        Adapters should call this just before writing config files so any
        deprecation warnings surface to the user rather than silently landing
        stale fields on disk.

        Args:
            output: Config data about to be written (dict or raw string).

        Returns:
            List of human-readable warning strings. Empty = no issues.
        """
        try:
            from src.harness_version_compat import check_deprecated_fields_in_output
            return check_deprecated_fields_in_output(
                self.target_name, output, self.project_dir
            )
        except ImportError:
            return []
        except Exception as e:
            print(f"  [AdapterBase] deprecation check failed for {self.target_name}: {e}", file=sys.stderr)
            return []

    # ── Shared Markdown Utilities ────────────────────────────────────────────

    def _read_managed_md(self, path: Path) -> str:
        """Read a managed markdown file or return empty string.

        Works for AGENTS.md, GEMINI.md, or any adapter's primary .md file.

        Args:
            path: Path to the markdown file

        Returns:
            File content or empty string if file doesn't exist or read fails
        """
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            return ""

    def _write_managed_md(self, path: Path, content: str) -> None:
        """Write a managed markdown file with parent directory creation.

        Args:
            path: Path to the markdown file
            content: Full file content to write
        """
        from src.utils.paths import ensure_dir
        ensure_dir(path.parent)
        path.write_text(content, encoding='utf-8')

    def _replace_managed_section(self, existing: str, managed: str) -> str:
        """Replace content between HarnessSync markers or append.

        If markers exist in existing content, replaces the section between them.
        If no markers found, appends managed section to end of file.
        If existing is empty, returns just the managed section.

        Args:
            existing: Existing file content
            managed: New managed section (including markers)

        Returns:
            Final file content
        """
        if not existing:
            return managed

        if HARNESSSYNC_MARKER in existing:
            start_idx = existing.find(HARNESSSYNC_MARKER)
            end_idx = existing.find(HARNESSSYNC_MARKER_END)

            if end_idx != -1:
                end_pos = end_idx + len(HARNESSSYNC_MARKER_END)
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
                return f"{existing.rstrip()}\n\n{managed}"
        else:
            return f"{existing.rstrip()}\n\n{managed}"

    def _build_managed_section(self, content: str, header: str = "Rules synced from Claude Code") -> str:
        """Build a HarnessSync managed section with markers and timestamp.

        Args:
            content: The content to wrap in markers
            header: Section header text (default: "Rules synced from Claude Code")

        Returns:
            Complete managed section string with markers and timestamp
        """
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        return f"""{HARNESSSYNC_MARKER}
# {header}

{content}

---
*Last synced by HarnessSync: {timestamp}*
{HARNESSSYNC_MARKER_END}"""

    def _insert_before_end_marker(self, existing: str, section: str) -> str:
        """Insert content before the HarnessSync end marker in a managed file.

        Useful for appending plugin docs, hook docs, or permission warnings
        within the managed section.

        Args:
            existing: Current file content with markers
            section: Content to insert before end marker

        Returns:
            Updated content, or original if no end marker found
        """
        if existing and HARNESSSYNC_MARKER_END in existing:
            end_idx = existing.find(HARNESSSYNC_MARKER_END)
            before = existing[:end_idx].rstrip()
            after = existing[end_idx:]
            return f"{before}\n{section}\n{after}"
        elif existing:
            return f"{existing.rstrip()}\n{section}\n"
        return existing

    # ── Shared Frontmatter / YAML Utilities ───────────────────────────────

    @staticmethod
    def _parse_frontmatter(content: str) -> tuple[dict, str]:
        """Extract YAML frontmatter from markdown content.

        Parses simple key: value frontmatter between --- delimiters.
        Supports multiline block scalars (| and >) and quoted values.
        Does not use PyYAML.

        Args:
            content: Markdown content with optional frontmatter

        Returns:
            Tuple of (frontmatter_dict, body_after_frontmatter)
        """
        if not content.startswith('---'):
            return {}, content

        match = re.match(r'^---\n(.*?)\n---\n(.*)$', content, re.DOTALL)
        if not match:
            return {}, content

        frontmatter_text = match.group(1)
        body = match.group(2)

        frontmatter: dict[str, str] = {}
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
                    block_lines: list[str] = []
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

    @staticmethod
    def _extract_role_section(body: str) -> str:
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

    @staticmethod
    def _quote_yaml_value(value: str) -> str:
        """Quote a YAML value if it contains unsafe characters.

        Args:
            value: Raw string value for YAML frontmatter

        Returns:
            Quoted string if needed, original otherwise
        """
        if not value:
            return '""'
        if any(c in value for c in ':"\'{}[]|>&*!%#`@,'):
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            return f'"{escaped}"'
        return value

    # ── Shared Plugin Decompose ───────────────────────────────────────────

    def _decompose_plugin(self, plugin_name: str, meta: dict) -> tuple[bool, list[str]]:
        """Decompose a plugin by routing its contents through existing sync pipelines.

        Routes skills, agents, commands, MCP servers, and hooks from a plugin's
        install directory through the adapter's own sync methods.

        Args:
            plugin_name: Name of the plugin
            meta: Plugin metadata dict with install_path, has_skills, etc.

        Returns:
            Tuple of (decomposed: bool, failures: list[str])
        """
        from src.utils.paths import read_json_safe

        install_path = meta.get("install_path")
        if not install_path:
            return False, []

        install_path = Path(install_path)
        decomposed = False
        failures: list[str] = []

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
            except (OSError, UnicodeDecodeError, AdapterError) as e:
                print(f"  [AdapterBase] plugin decompose skills failed for {plugin_name}: {e}", file=sys.stderr)
                failures.append("skills")

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
            except (OSError, UnicodeDecodeError, AdapterError) as e:
                print(f"  [AdapterBase] plugin decompose agents failed for {plugin_name}: {e}", file=sys.stderr)
                failures.append("agents")

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
            except (OSError, UnicodeDecodeError, AdapterError) as e:
                print(f"  [AdapterBase] plugin decompose commands failed for {plugin_name}: {e}", file=sys.stderr)
                failures.append("commands")

        # Route MCP servers
        if meta.get("has_mcp"):
            try:
                mcp_json = install_path / ".mcp.json"
                if mcp_json.exists():
                    mcp_data = read_json_safe(mcp_json)
                    servers = mcp_data.get("mcpServers", mcp_data)
                    if isinstance(servers, dict) and servers:
                        self.sync_mcp(servers)
                        decomposed = True
            except (OSError, json.JSONDecodeError, AdapterError) as e:
                print(f"  [AdapterBase] plugin decompose mcp failed for {plugin_name}: {e}", file=sys.stderr)
                failures.append("mcp")

        # Route hooks
        if meta.get("has_hooks"):
            try:
                hooks_json = install_path / "hooks" / "hooks.json"
                if hooks_json.exists():
                    hooks_data = read_json_safe(hooks_json)
                    if hooks_data:
                        self.sync_hooks(hooks_data)
                        decomposed = True
            except (OSError, json.JSONDecodeError, AdapterError) as e:
                print(f"  [AdapterBase] plugin decompose hooks failed for {plugin_name}: {e}", file=sys.stderr)
                failures.append("hooks")

        return decomposed, failures

    def sync_all(self, source_data: dict) -> dict[str, SyncResult]:
        """Sync all configuration types.

        Calls all sync methods and returns results by config type.
        Wraps each call in try/except to report failures without aborting.

        Args:
            source_data: Dict with keys 'rules', 'skills', 'agents',
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
                print(f"  ⚠  {w}", file=sys.stderr)

        # Sync rules
        try:
            results['rules'] = self.sync_rules(source_data.get('rules', []))
        except (AdapterError, OSError, UnicodeDecodeError) as e:
            results['rules'] = SyncResult(
                failed=1,
                failed_files=[f'rules: {str(e)}']
            )
        except Exception as e:
            print(f"  [AdapterBase] unexpected error syncing rules for {self.target_name}: {e}", file=sys.stderr)
            results['rules'] = SyncResult(
                failed=1,
                failed_files=[f'rules: {str(e)}']
            )

        # Sync skills
        try:
            results['skills'] = self.sync_skills(source_data.get('skills', {}))
        except (AdapterError, OSError, UnicodeDecodeError) as e:
            results['skills'] = SyncResult(
                failed=1,
                failed_files=[f'skills: {str(e)}']
            )
        except Exception as e:
            print(f"  [AdapterBase] unexpected error syncing skills for {self.target_name}: {e}", file=sys.stderr)
            results['skills'] = SyncResult(
                failed=1,
                failed_files=[f'skills: {str(e)}']
            )

        # Sync agents
        try:
            results['agents'] = self.sync_agents(source_data.get('agents', {}))
        except (AdapterError, OSError, UnicodeDecodeError) as e:
            results['agents'] = SyncResult(
                failed=1,
                failed_files=[f'agents: {str(e)}']
            )
        except Exception as e:
            print(f"  [AdapterBase] unexpected error syncing agents for {self.target_name}: {e}", file=sys.stderr)
            results['agents'] = SyncResult(
                failed=1,
                failed_files=[f'agents: {str(e)}']
            )

        # Sync commands
        try:
            results['commands'] = self.sync_commands(source_data.get('commands', {}))
        except (AdapterError, OSError, UnicodeDecodeError) as e:
            results['commands'] = SyncResult(
                failed=1,
                failed_files=[f'commands: {str(e)}']
            )
        except Exception as e:
            print(f"  [AdapterBase] unexpected error syncing commands for {self.target_name}: {e}", file=sys.stderr)
            results['commands'] = SyncResult(
                failed=1,
                failed_files=[f'commands: {str(e)}']
            )

        # Sync MCP servers (use scoped data if available, fall back to flat)
        try:
            mcp_scoped = source_data.get('mcp_scoped', {})
            if mcp_scoped:
                results['mcp'] = self.sync_mcp_scoped(mcp_scoped)
            else:
                results['mcp'] = self.sync_mcp(source_data.get('mcp', {}))
        except (AdapterError, OSError, UnicodeDecodeError) as e:
            results['mcp'] = SyncResult(
                failed=1,
                failed_files=[f'mcp: {str(e)}']
            )
        except Exception as e:
            print(f"  [AdapterBase] unexpected error syncing mcp for {self.target_name}: {e}", file=sys.stderr)
            results['mcp'] = SyncResult(
                failed=1,
                failed_files=[f'mcp: {str(e)}']
            )

        # Sync settings
        try:
            results['settings'] = self.sync_settings(source_data.get('settings', {}))
        except (AdapterError, OSError, UnicodeDecodeError) as e:
            results['settings'] = SyncResult(
                failed=1,
                failed_files=[f'settings: {str(e)}']
            )
        except Exception as e:
            print(f"  [AdapterBase] unexpected error syncing settings for {self.target_name}: {e}", file=sys.stderr)
            results['settings'] = SyncResult(
                failed=1,
                failed_files=[f'settings: {str(e)}']
            )

        # Sync hooks
        try:
            results['hooks'] = self.sync_hooks(source_data.get('hooks', {}))
        except (AdapterError, OSError, UnicodeDecodeError) as e:
            results['hooks'] = SyncResult(
                failed=1,
                failed_files=[f'hooks: {str(e)}']
            )
        except Exception as e:
            print(f"  [AdapterBase] unexpected error syncing hooks for {self.target_name}: {e}", file=sys.stderr)
            results['hooks'] = SyncResult(
                failed=1,
                failed_files=[f'hooks: {str(e)}']
            )

        # Sync plugins
        try:
            results['plugins'] = self.sync_plugins(source_data.get('plugins', {}))
        except (AdapterError, OSError, UnicodeDecodeError) as e:
            results['plugins'] = SyncResult(
                failed=1,
                failed_files=[f'plugins: {str(e)}']
            )
        except Exception as e:
            print(f"  [AdapterBase] unexpected error syncing plugins for {self.target_name}: {e}", file=sys.stderr)
            results['plugins'] = SyncResult(
                failed=1,
                failed_files=[f'plugins: {str(e)}']
            )

        return results

    def prepare_rules_content(self, content: str) -> str:
        """Transform rule content for this target, including effectiveness annotations.

        Called by adapters before writing rules to disk. Applies:
        1. Effectiveness annotation propagation — converts ``<!-- @effectiveness: ... -->``
           markers to target-appropriate format (kept as HTML comments for most targets,
           converted to blockquotes for plain-text targets like Aider).

        Args:
            content: Rule text (combined from one or more source files).

        Returns:
            Transformed content ready for the target file.
        """
        try:
            from src.sync_filter import propagate_effectiveness_annotations
            return propagate_effectiveness_annotations(content, self.target_name)
        except ImportError:
            return content
        except Exception as e:
            print(f"  [AdapterBase] effectiveness annotation propagation failed: {e}", file=sys.stderr)
            return content
