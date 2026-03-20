from __future__ import annotations

"""Helper functions for /sync-status: MCP grouping, plugin drift, and CI output.

Extracted from sync_status.py to keep the main command file focused on
the status display logic.
"""

import json
import sys
from pathlib import Path

from src.adapters import AdapterRegistry
from src.source_reader import SourceReader
from src.state_manager import StateManager
from src.utils.hashing import hash_file_sha256


def group_mcps_by_source(mcp_servers_scoped: dict) -> dict:
    """
    Group MCP servers by source (user/project/local/plugins).

    Args:
        mcp_servers_scoped: Output from SourceReader.get_mcp_servers_with_scope()
                            {server_name: {"config": {...}, "metadata": {...}}}

    Returns:
        {
            "user": [(server_name, scope), ...],
            "project": [(server_name, scope), ...],
            "local": [(server_name, scope), ...],
            "plugins": {
                "plugin_name@version": [(server_name, scope), ...],
                ...
            }
        }
    """
    groups = {
        "user": [],
        "project": [],
        "local": [],
        "plugins": {}
    }

    for server_name, data in mcp_servers_scoped.items():
        metadata = data.get("metadata", {})
        scope = metadata.get("scope", "user")
        source = metadata.get("source", "file")

        if source == "plugin":
            plugin_name = metadata.get("plugin_name", "unknown")
            plugin_version = metadata.get("plugin_version", "unknown")
            plugin_key = f"{plugin_name}@{plugin_version}"

            if plugin_key not in groups["plugins"]:
                groups["plugins"][plugin_key] = []
            groups["plugins"][plugin_key].append((server_name, scope))
        else:
            if scope == "user":
                groups["user"].append((server_name, scope))
            elif scope == "project":
                groups["project"].append((server_name, scope))
            elif scope == "local":
                groups["local"].append((server_name, scope))

    return groups


def format_mcp_groups(groups: dict) -> list[str]:
    """
    Format MCP groups as indented text lines for display.

    Args:
        groups: Output from group_mcps_by_source()

    Returns:
        List of formatted lines ready for printing
    """
    lines = []
    lines.append("  MCP Servers:")

    # User-configured
    user_count = len(groups["user"])
    if user_count > 0:
        lines.append(f"    User-configured ({user_count}):")
        for server_name, scope in groups["user"][:10]:
            lines.append(f"      - {server_name} ({scope})")
        if user_count > 10:
            lines.append(f"      ... and {user_count - 10} more")

    # Project-configured
    project_count = len(groups["project"])
    if project_count > 0:
        lines.append(f"    Project-configured ({project_count}):")
        for server_name, scope in groups["project"][:10]:
            lines.append(f"      - {server_name} ({scope})")
        if project_count > 10:
            lines.append(f"      ... and {project_count - 10} more")

    # Local-configured
    local_count = len(groups["local"])
    if local_count > 0:
        lines.append(f"    Local-configured ({local_count}):")
        for server_name, scope in groups["local"][:10]:
            lines.append(f"      - {server_name} ({scope})")
        if local_count > 10:
            lines.append(f"      ... and {local_count - 10} more")

    # Plugin-provided
    if groups["plugins"]:
        lines.append("    Plugin-provided:")
        for plugin_key, servers in groups["plugins"].items():
            server_count = len(servers)
            lines.append(f"      {plugin_key} ({server_count}):")
            for server_name, scope in servers[:5]:
                lines.append(f"        - {server_name} ({scope})")
            if server_count > 5:
                lines.append(f"        ... and {server_count - 5} more")

    return lines


def format_plugin_drift(drift: dict) -> list[str]:
    """
    Format plugin drift warnings as indented text lines.

    Args:
        drift: Output from StateManager.detect_plugin_drift()
               {plugin_name: drift_reason, ...}

    Returns:
        List of formatted lines, or empty list if no drift
    """
    if not drift:
        return []

    lines = []
    lines.append("  Plugin Drift:")
    for plugin_name, reason in drift.items():
        lines.append(f"    - {plugin_name}: {reason}")

    return lines


def extract_current_plugins(mcp_scoped: dict) -> dict:
    """
    Extract current plugin metadata from scoped MCP data.

    Args:
        mcp_scoped: Output from SourceReader.get_mcp_servers_with_scope()

    Returns:
        {
            plugin_name: {
                "version": str,
                "mcp_count": int,
                "mcp_servers": [str, ...],
                "last_sync": str (ISO timestamp)
            },
            ...
        }
    """
    from datetime import datetime

    plugins = {}

    for server_name, data in mcp_scoped.items():
        metadata = data.get("metadata", {})
        source = metadata.get("source")

        if source == "plugin":
            plugin_name = metadata.get("plugin_name", "unknown")
            plugin_version = metadata.get("plugin_version", "unknown")

            if plugin_name not in plugins:
                plugins[plugin_name] = {
                    "version": plugin_version,
                    "mcp_count": 0,
                    "mcp_servers": [],
                    "last_sync": datetime.utcnow().isoformat() + "Z"
                }

            plugins[plugin_name]["mcp_count"] += 1
            plugins[plugin_name]["mcp_servers"].append(server_name)

    return plugins


def compute_source_hashes(project_dir: Path, reader: SourceReader) -> dict[str, str]:
    """Compute current source file hashes for drift detection.

    Args:
        project_dir: Project root directory.
        reader: SourceReader instance.

    Returns:
        Dict mapping file path strings to SHA256 hashes.
    """
    source_paths = reader.get_source_paths()
    current_hashes: dict[str, str] = {}
    for config_type, paths in source_paths.items():
        for p in paths:
            if p.is_file():
                h = hash_file_sha256(p)
                if h:
                    current_hashes[str(p)] = h
    return current_hashes


def show_ci_status(args) -> None:
    """CI-friendly status output with machine-readable JSON and exit codes.

    Exit codes:
        0 -- all targets synced, no drift detected
        1 -- drift detected or one or more targets have never been synced
        2 -- could not read status (config error)
    """
    import os

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    state_manager = StateManager()
    registered = AdapterRegistry.list_targets()

    reader = SourceReader(scope="all", project_dir=project_dir)
    current_hashes = compute_source_hashes(project_dir, reader)

    state = state_manager.get_all_status()
    targets_state = state.get("targets", {})

    drift_targets: list[str] = []
    never_synced: list[str] = []
    per_target: dict[str, dict] = {}

    for target in registered:
        target_state = targets_state.get(target)
        if not target_state:
            never_synced.append(target)
            per_target[target] = {
                "status": "never_synced",
                "last_sync": None,
                "items_synced": 0,
                "items_failed": 0,
                "drift": [],
                "drift_count": 0,
            }
            continue

        drifted = state_manager.detect_drift(target, current_hashes) or []
        if drifted:
            drift_targets.append(target)

        per_target[target] = {
            "status": target_state.get("status", "unknown"),
            "last_sync": target_state.get("last_sync"),
            "items_synced": target_state.get("items_synced", 0),
            "items_failed": target_state.get("items_failed", 0),
            "drift": drifted,
            "drift_count": len(drifted),
        }

    has_issues = bool(drift_targets or never_synced)

    output = {
        "ok": not has_issues,
        "drift_detected": bool(drift_targets),
        "drift_targets": drift_targets,
        "never_synced": never_synced,
        "last_sync": state.get("last_sync"),
        "targets": per_target,
    }

    print(json.dumps(output, indent=2))

    if has_issues and getattr(args, "ci", False):
        sys.exit(1)
