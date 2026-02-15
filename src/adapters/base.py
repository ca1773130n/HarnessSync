"""Abstract base class for target adapters.

AdapterBase defines the interface all target adapters (Codex, Gemini, OpenCode)
must implement. It enforces 6 sync methods for different configuration types:
- sync_rules: CLAUDE.md rules
- sync_skills: Skills directory
- sync_agents: Agent .md files
- sync_commands: Command .md files
- sync_mcp: MCP server configurations
- sync_settings: General settings

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

from abc import ABC, abstractmethod
from pathlib import Path
from .result import SyncResult


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

        Receives Phase 9 scoped format:
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

    def sync_all(self, source_data: dict) -> dict[str, SyncResult]:
        """Sync all configuration types.

        Calls all 6 sync methods and returns results by config type.
        Wraps each call in try/except to report failures without aborting.

        Args:
            source_data: Dict with keys 'rules', 'skills', 'agents',
                        'commands', 'mcp', 'settings'

        Returns:
            Dict mapping config type to SyncResult
        """
        results = {}

        # Sync rules
        try:
            results['rules'] = self.sync_rules(source_data.get('rules', []))
        except Exception as e:
            results['rules'] = SyncResult(
                failed=1,
                failed_files=[f'rules: {str(e)}']
            )

        # Sync skills
        try:
            results['skills'] = self.sync_skills(source_data.get('skills', {}))
        except Exception as e:
            results['skills'] = SyncResult(
                failed=1,
                failed_files=[f'skills: {str(e)}']
            )

        # Sync agents
        try:
            results['agents'] = self.sync_agents(source_data.get('agents', {}))
        except Exception as e:
            results['agents'] = SyncResult(
                failed=1,
                failed_files=[f'agents: {str(e)}']
            )

        # Sync commands
        try:
            results['commands'] = self.sync_commands(source_data.get('commands', {}))
        except Exception as e:
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
        except Exception as e:
            results['mcp'] = SyncResult(
                failed=1,
                failed_files=[f'mcp: {str(e)}']
            )

        # Sync settings
        try:
            results['settings'] = self.sync_settings(source_data.get('settings', {}))
        except Exception as e:
            results['settings'] = SyncResult(
                failed=1,
                failed_files=[f'settings: {str(e)}']
            )

        return results
