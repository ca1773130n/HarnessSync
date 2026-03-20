from __future__ import annotations

"""State update logic after sync operations.

Records per-target sync results, file hashes for drift detection,
and plugin metadata persistence. Extracted from SyncOrchestrator.
"""

from datetime import datetime
from pathlib import Path

from src.adapters.result import SyncResult
from src.source_reader import SourceReader
from src.state_manager import StateManager
from src.utils.hashing import hash_file_sha256


def extract_plugin_metadata(mcp_scoped: dict) -> dict:
    """Extract plugin metadata from mcp_scoped data.

    Args:
        mcp_scoped: MCP servers with scope metadata (from SourceReader.discover_all())

    Returns:
        Dict mapping plugin_name -> {version, mcp_count, mcp_servers, last_sync}
    """
    plugins = {}

    for server_name, server_data in mcp_scoped.items():
        metadata = server_data.get('metadata', {})

        # Filter to plugin-sourced MCPs only
        if metadata.get('source') != 'plugin':
            continue

        plugin_name = metadata.get('plugin_name', 'unknown')
        plugin_version = metadata.get('plugin_version', 'unknown')

        # Group by plugin_name
        if plugin_name not in plugins:
            plugins[plugin_name] = {
                'version': plugin_version,
                'mcp_count': 0,
                'mcp_servers': [],
                'last_sync': datetime.now().isoformat()
            }

        # Increment MCP count and add server name
        plugins[plugin_name]['mcp_count'] += 1
        plugins[plugin_name]['mcp_servers'].append(server_name)

    return plugins


def update_state(
    results: dict,
    reader: SourceReader,
    state_manager: StateManager,
    scope: str,
    account: str | None = None,
    source_data: dict | None = None,
) -> None:
    """Update state manager with sync results and plugin metadata.

    Args:
        results: Per-target sync results
        reader: SourceReader used for this sync (for source paths)
        state_manager: StateManager instance
        scope: Sync scope ("user" | "project" | "all")
        account: Account name for per-account sync (None = v1 behavior)
        source_data: Source configuration data (optional, avoids re-calling discover_all)
    """
    source_paths = reader.get_source_paths()

    # Hash all source files
    file_hashes = {}
    for config_type, paths in source_paths.items():
        for p in paths:
            if p.is_file():
                h = hash_file_sha256(p)
                if h:
                    file_hashes[str(p)] = h

    for target, target_results in results.items():
        # Skip special keys
        if target.startswith('_'):
            continue

        # Aggregate counts across config types
        synced = 0
        skipped = 0
        failed = 0
        sync_methods = {}

        if isinstance(target_results, dict):
            for config_type, result in target_results.items():
                if isinstance(result, SyncResult):
                    synced += result.synced
                    skipped += result.skipped
                    failed += result.failed

        state_manager.record_sync(
            target=target,
            scope=scope,
            file_hashes=file_hashes,
            sync_methods=sync_methods,
            synced=synced,
            skipped=skipped,
            failed=failed,
            account=account
        )

    # --- PLUGIN METADATA PERSISTENCE ---
    # Extract and record plugin metadata after successful target syncs
    if source_data is None:
        source_data = reader.discover_all()

    mcp_scoped = source_data.get('mcp_servers_scoped', {})
    plugins_metadata = extract_plugin_metadata(mcp_scoped)

    if plugins_metadata:
        state_manager.record_plugin_sync(plugins_metadata, account=account)
