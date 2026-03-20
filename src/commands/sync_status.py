from __future__ import annotations

"""
/sync-status slash command implementation.

Displays per-target sync status, timestamps, item counts,
and drift detection. Supports --account and --list-accounts flags.
Read-only operation.

Implementation split: status_helpers.py contains MCP grouping,
plugin drift formatting, and CI output logic.
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

# Re-export for backward compatibility (tests/verify_phase11_integration.py imports these)
from src.commands.status_helpers import (  # noqa: E402, F401
    group_mcps_by_source as _group_mcps_by_source,
    format_mcp_groups as _format_mcp_groups,
    format_plugin_drift as _format_plugin_drift,
    extract_current_plugins as _extract_current_plugins,
    compute_source_hashes,
    show_ci_status as _show_ci_status,
)


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
    parser.add_argument("--account", type=str, default=None,
                        help="Show status for specific account")
    parser.add_argument("--list-accounts", action="store_true",
                        help="List all configured accounts with sync status")
    parser.add_argument("--ci", action="store_true",
                        help=("CI mode: exit 1 if drift is detected or any target has never been synced. "
                              "Output is machine-readable JSON."))
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output status as machine-readable JSON (implies CI-style output format).")

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    try:
        if args.list_accounts:
            _show_account_list()
        elif getattr(args, "ci", False) or getattr(args, "json_output", False):
            _show_ci_status(args)
            return
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

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    reader = SourceReader(scope="all", project_dir=project_dir, cc_home=cc_home)
    current_hashes = compute_source_hashes(project_dir, reader)

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

    # MCP source grouping and plugin drift
    mcp_scoped = reader.get_mcp_servers_with_scope()
    if mcp_scoped:
        print()
        groups = _group_mcps_by_source(mcp_scoped)
        for line in _format_mcp_groups(groups):
            print(line)

        current_plugins = _extract_current_plugins(mcp_scoped)
        drift = state_manager.detect_plugin_drift(current_plugins, account=account_name)
        for line in _format_plugin_drift(drift):
            print(line)


def _show_default_status():
    """Show default status view (all accounts if configured, else v1)."""
    has_accounts = False
    try:
        from src.account_manager import AccountManager
        am = AccountManager()
        has_accounts = am.has_accounts()
    except Exception:
        pass

    if has_accounts:
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

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    reader = SourceReader(scope="all", project_dir=project_dir)
    current_hashes = compute_source_hashes(project_dir, reader)

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

    # MCP source grouping and plugin drift
    mcp_scoped = reader.get_mcp_servers_with_scope()
    if mcp_scoped:
        print()
        groups = _group_mcps_by_source(mcp_scoped)
        for line in _format_mcp_groups(groups):
            print(line)

        current_plugins = _extract_current_plugins(mcp_scoped)
        drift = state_manager.detect_plugin_drift(current_plugins)
        for line in _format_plugin_drift(drift):
            print(line)

    # Config coverage scores
    try:
        from src.compatibility_reporter import CompatibilityReporter
        _source_data = reader.discover_all()
        _reporter = CompatibilityReporter()
        _coverage = _reporter.static_coverage_score(_source_data, registered)
        _coverage_text = _reporter.format_static_coverage(_coverage)
        if _coverage_text.strip():
            print(_coverage_text)
    except Exception:
        pass

    # Capability upgrade suggestions
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
        pass

    # Version upgrade requirements
    try:
        from src.harness_version_compat import format_upgrade_requirements
        upgrade_req_text = format_upgrade_requirements(project_dir=project_dir)
        if upgrade_req_text.strip():
            print()
            print("Version Upgrade Requirements")
            print(upgrade_req_text)
    except Exception:
        pass

    # Inline harness blocks
    try:
        _inline_blocks = reader.get_all_inline_harness_blocks()
        if _inline_blocks:
            print()
            print("Inline Harness Blocks:")
            print("-" * 40)
            for _harness, _block in sorted(_inline_blocks.items()):
                _first_line = _block.split("\n")[0]
                _truncated = len(_first_line) > 60 or "\n" in _block
                _preview = _first_line[:60]
                print(f"  {_harness:<12} {_preview}{'...' if _truncated else ''}")
    except Exception:
        pass

    # Config health scores
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
        pass

    # Harness health score dashboard
    try:
        from src.harness_health_score import HarnessHealthScorer
        _hs = HarnessHealthScorer(project_dir=project_dir)
        _health_scores_new = _hs.score_all(targets=list(registered))
        if _health_scores_new:
            print()
            print(_hs.format_dashboard(_health_scores_new))
    except Exception:
        pass

    # Harness parity scores
    try:
        from src.commands.sync_parity import _SUPPORT_MATRIX, _score as _parity_score
        _parity_lines = ["", "Harness Parity Scores:", "-" * 40]
        for _target_name in registered:
            _support = _SUPPORT_MATRIX.get(_target_name, {})
            if _support:
                _ps = _parity_score(_support)
                _bar_filled = int(_ps / 5)
                _bar = "\u2588" * _bar_filled + "\u2591" * (20 - _bar_filled)
                _parity_lines.append(f"  {_target_name:<12} {_bar} {_ps:>5.1f}%")
        if len(_parity_lines) > 3:
            print("\n".join(_parity_lines))
            print("  Run /sync-parity for full feature breakdown.")
    except Exception:
        pass

    # Harness usage insights
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
                print(f"  \u26a0 {_r.target:<12} last synced {_days}")
                print(f"    \u2192 {_r.recommendation}")
            print("  Run /sync-parity or remove stale targets with /sync-setup.")
    except Exception:
        pass


if __name__ == "__main__":
    main()
