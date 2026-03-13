from __future__ import annotations

"""
/sync-status slash command implementation.

Displays per-target sync status, timestamps, item counts,
and drift detection. Supports --account and --list-accounts flags.
Read-only operation.
"""

import os
import sys
import shlex
import argparse

# Resolve project root for imports
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.adapters import AdapterRegistry
from src.source_reader import SourceReader
from src.state_manager import StateManager
from src.utils.hashing import hash_file_sha256


def _group_mcps_by_source(mcp_servers_scoped: dict) -> dict:
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
            # Plugin-sourced MCP
            plugin_name = metadata.get("plugin_name", "unknown")
            plugin_version = metadata.get("plugin_version", "unknown")
            plugin_key = f"{plugin_name}@{plugin_version}"

            if plugin_key not in groups["plugins"]:
                groups["plugins"][plugin_key] = []
            groups["plugins"][plugin_key].append((server_name, scope))
        else:
            # File-based MCP
            if scope == "user":
                groups["user"].append((server_name, scope))
            elif scope == "project":
                groups["project"].append((server_name, scope))
            elif scope == "local":
                groups["local"].append((server_name, scope))

    return groups


def _format_mcp_groups(groups: dict) -> list[str]:
    """
    Format MCP groups as indented text lines for display.

    Args:
        groups: Output from _group_mcps_by_source()

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


def _format_plugin_drift(drift: dict) -> list[str]:
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


def _extract_current_plugins(mcp_scoped: dict) -> dict:
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


def main():
    """Entry point for /sync-status command."""
    # Parse arguments
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-status",
        description="Show HarnessSync status and drift detection"
    )
    parser.add_argument(
        "--account",
        type=str,
        default=None,
        help="Show status for specific account"
    )
    parser.add_argument(
        "--list-accounts",
        action="store_true",
        help="List all configured accounts with sync status"
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    try:
        if args.list_accounts:
            _show_account_list()
        elif args.account:
            _show_account_status(args.account)
        else:
            _show_default_status()

    except Exception as e:
        print(f"Error reading status: {e}", file=sys.stderr)
        sys.exit(1)


def _show_account_list():
    """Show all configured accounts with sync status."""
    try:
        from src.account_manager import AccountManager
        am = AccountManager()
    except Exception:
        print("No multi-account configuration found.")
        return

    accounts = am.list_accounts()
    if not accounts:
        print("No accounts configured. Run /sync-setup to add one.")
        return

    default = am.get_default_account()
    state_manager = StateManager()

    print("HarnessSync Accounts")
    print("=" * 60)
    print(f"{'Account':<15}| {'Source':<25}| {'Last Sync':<20}| {'Default'}")
    print("-" * 15 + "+" + "-" * 25 + "+" + "-" * 20 + "+" + "-" * 8)

    for name in accounts:
        acc = am.get_account(name)
        source = acc.get("source", {}).get("path", "?")
        if len(source) > 23:
            source = "..." + source[-20:]

        # Get last sync from state
        acct_state = state_manager.get_account_status(name)
        last_sync = acct_state.get("last_sync", "never") if acct_state else "never"
        if last_sync != "never" and len(last_sync) > 18:
            last_sync = last_sync[:16]

        is_default = "*" if name == default else ""
        print(f"{name:<15}| {source:<25}| {last_sync:<20}| {is_default}")


def _show_account_status(account_name: str):
    """Show per-target status for a specific account."""
    try:
        from src.account_manager import AccountManager
        am = AccountManager()
    except Exception:
        print("No multi-account configuration found.")
        return

    acc = am.get_account(account_name)
    if not acc:
        print(f"Account '{account_name}' not found.")
        return

    state_manager = StateManager()
    cc_home = Path(acc["source"]["path"])
    registered = AdapterRegistry.list_targets()

    # Compute current source file hashes for drift detection
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    reader = SourceReader(scope="all", project_dir=project_dir, cc_home=cc_home)
    source_paths = reader.get_source_paths()

    current_hashes = {}
    for config_type, paths in source_paths.items():
        for p in paths:
            if p.is_file():
                h = hash_file_sha256(p)
                if h:
                    current_hashes[str(p)] = h

    # Header
    print(f"HarnessSync Status — {account_name}")
    print("=" * 60)
    print(f"Source: {acc['source']['path']}")

    acct_state = state_manager.get_account_status(account_name)
    if acct_state:
        print(f"Last sync: {acct_state.get('last_sync', 'never')}")
    else:
        print("Last sync: never")

    # Per-target status
    targets_config = acc.get("targets", {})
    for target in registered:
        if target not in targets_config:
            continue

        print(f"\nTarget: {target} -> {targets_config[target]}")
        target_state = state_manager.get_account_target_status(account_name, target)

        if not target_state:
            print("  Status: never synced")
            continue

        status = target_state.get("status", "unknown")
        t_last_sync = target_state.get("last_sync", "unknown")
        scope = target_state.get("scope", "unknown")
        synced = target_state.get("items_synced", 0)
        skipped = target_state.get("items_skipped", 0)
        failed = target_state.get("items_failed", 0)

        print(f"  Status: {status}")
        print(f"  Last sync: {t_last_sync}")
        print(f"  Scope: {scope}")
        print(f"  Items: {synced} synced, {skipped} skipped, {failed} failed")

        # Drift detection (account-scoped)
        drifted = state_manager.detect_drift(target, current_hashes, account=account_name)
        if drifted:
            print(f"  Drift: {len(drifted)} files changed")
            for f in drifted[:10]:
                stored = target_state.get("file_hashes", {})
                if f not in stored:
                    indicator = "(new)"
                elif f not in current_hashes:
                    indicator = "(deleted)"
                else:
                    indicator = "(modified)"
                print(f"    - {f} {indicator}")
            if len(drifted) > 10:
                print(f"    ... and {len(drifted) - 10} more")
        else:
            print("  Drift: None detected")

    # MCP source grouping and plugin drift (after per-target status)
    mcp_scoped = reader.get_mcp_servers_with_scope()
    if mcp_scoped:
        print()  # Blank line before MCP section

        # Display MCP grouping
        groups = _group_mcps_by_source(mcp_scoped)
        for line in _format_mcp_groups(groups):
            print(line)

        # Display plugin drift warnings (account-scoped)
        current_plugins = _extract_current_plugins(mcp_scoped)
        drift = state_manager.detect_plugin_drift(current_plugins, account=account_name)
        for line in _format_plugin_drift(drift):
            print(line)


def _show_default_status():
    """Show default status view (all accounts if configured, else v1)."""
    # Check for multi-account setup
    has_accounts = False
    try:
        from src.account_manager import AccountManager
        am = AccountManager()
        has_accounts = am.has_accounts()
    except Exception:
        pass

    if has_accounts:
        # Show status for all accounts
        print("HarnessSync Status (Multi-Account)")
        print("=" * 60)

        for account_name in am.list_accounts():
            _show_account_status(account_name)
            print()
        return

    # v1 behavior
    state_manager = StateManager()
    state = state_manager.get_all_status()
    targets_state = state.get("targets", {})
    registered = AdapterRegistry.list_targets()

    # Compute current source file hashes for drift detection
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    reader = SourceReader(scope="all", project_dir=project_dir)
    source_paths = reader.get_source_paths()

    current_hashes = {}
    for config_type, paths in source_paths.items():
        for p in paths:
            if p.is_file():
                h = hash_file_sha256(p)
                if h:
                    current_hashes[str(p)] = h

    # Header
    print("HarnessSync Status")
    print("=" * 60)

    last_sync = state.get("last_sync")
    if last_sync:
        print(f"\nLast sync: {last_sync}")
    else:
        print("\nLast sync: never")

    # Per-target status
    for target in registered:
        print(f"\nTarget: {target}")
        target_state = targets_state.get(target)

        if not target_state:
            print("  Status: never synced")
            continue

        status = target_state.get("status", "unknown")
        t_last_sync = target_state.get("last_sync", "unknown")
        scope = target_state.get("scope", "unknown")
        synced = target_state.get("items_synced", 0)
        skipped = target_state.get("items_skipped", 0)
        failed = target_state.get("items_failed", 0)

        print(f"  Status: {status}")
        print(f"  Last sync: {t_last_sync}")
        print(f"  Scope: {scope}")
        print(f"  Items: {synced} synced, {skipped} skipped, {failed} failed")

        # Drift detection
        drifted = state_manager.detect_drift(target, current_hashes)
        if drifted:
            print(f"  Drift: {len(drifted)} files changed")
            for f in drifted[:10]:
                stored = target_state.get("file_hashes", {})
                if f not in stored:
                    indicator = "(new)"
                elif f not in current_hashes:
                    indicator = "(deleted)"
                else:
                    indicator = "(modified)"
                print(f"    - {f} {indicator}")
            if len(drifted) > 10:
                print(f"    ... and {len(drifted) - 10} more")
        else:
            print("  Drift: None detected")

    # MCP source grouping and plugin drift (after per-target status)
    mcp_scoped = reader.get_mcp_servers_with_scope()
    if mcp_scoped:
        print()  # Blank line before MCP section

        # Display MCP grouping
        groups = _group_mcps_by_source(mcp_scoped)
        for line in _format_mcp_groups(groups):
            print(line)

        # Display plugin drift warnings
        current_plugins = _extract_current_plugins(mcp_scoped)
        drift = state_manager.detect_plugin_drift(current_plugins)
        for line in _format_plugin_drift(drift):
            print(line)

    # Config coverage scores — show how much of the Claude Code config maps to each harness
    try:
        from src.compatibility_reporter import CompatibilityReporter
        _source_data = reader.discover_all()
        _reporter = CompatibilityReporter()
        _coverage = _reporter.static_coverage_score(_source_data, registered)
        _coverage_text = _reporter.format_static_coverage(_coverage)
        if _coverage_text.strip():
            print(_coverage_text)
    except Exception:
        pass  # Non-critical; don't break status output

    # Capability upgrade suggestions (proactive notification of new harness features)
    try:
        from src.harness_version_compat import format_upgrade_suggestions
        source_data = reader.discover_all()
        upgrade_msg = format_upgrade_suggestions(
            project_dir=project_dir,
            source_data=source_data,
        )
        if upgrade_msg:
            print()
            print(upgrade_msg)
    except Exception:
        pass  # Non-critical; don't break status output on version check failure

    # Version upgrade requirements (harnesses running old versions blocking features)
    try:
        from src.harness_version_compat import format_upgrade_requirements
        upgrade_req_text = format_upgrade_requirements(project_dir=project_dir)
        if upgrade_req_text.strip():
            print()
            print("Version Upgrade Requirements")
            print(upgrade_req_text)
    except Exception:
        pass  # Non-critical; don't break status output

    # Item 11 — Config health scores (0-100 per harness with trend)
    try:
        from src.config_health import SyncHealthTracker
        _tracker = SyncHealthTracker()
        _health_scores = []
        for _target_name in registered:
            try:
                _score = _tracker.compute_score(_target_name)
                _health_scores.append(_score)
            except Exception:
                pass
        if _health_scores:
            print()
            print(_tracker.format_dashboard(_health_scores))
    except Exception:
        pass  # Non-critical; health scores are informational only

    # Item 8 — Harness parity scores (0-100 per target, inline with status)
    try:
        from src.commands.sync_parity import _SUPPORT_MATRIX, _score as _parity_score
        _parity_lines = ["", "Harness Parity Scores:", "-" * 40]
        for _target_name in registered:
            _support = _SUPPORT_MATRIX.get(_target_name, {})
            if _support:
                _ps = _parity_score(_support)
                _bar_filled = int(_ps / 5)
                _bar = "█" * _bar_filled + "░" * (20 - _bar_filled)
                _parity_lines.append(f"  {_target_name:<12} {_bar} {_ps:>5.1f}%")
        if len(_parity_lines) > 3:
            print("\n".join(_parity_lines))
            print("  Run /sync-parity for full feature breakdown.")
    except Exception:
        pass  # Non-critical; parity scores are informational only

    # Item 15 — Harness usage insights (last used, stale detection)
    try:
        from src.harness_adoption import HarnessAdoptionAnalyzer
        _adoption_analyzer = HarnessAdoptionAnalyzer(state_manager=StateManager())
        _adoption_reports = _adoption_analyzer.analyze(targets=registered)
        _stale_reports = [r for r in _adoption_reports if r.stale]
        if _stale_reports:
            print()
            print("Usage Insights — Stale Harnesses:")
            print("-" * 40)
            for _r in _stale_reports:
                _days = f"{_r.days_since_sync:.0f}d ago" if _r.days_since_sync is not None else "never"
                print(f"  ⚠ {_r.target:<12} last synced {_days}")
                print(f"    → {_r.recommendation}")
            print("  Run /sync-parity or remove stale targets with /sync-setup.")
    except Exception:
        pass  # Non-critical; adoption insights are informational only


if __name__ == "__main__":
    main()
