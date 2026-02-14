"""
/sync slash command implementation.

Syncs Claude Code configuration to all registered target CLIs.
Supports --scope (user/project/all), --dry-run, and --account flags.
"""

import os
import sys
import shlex
import argparse
import time

# Resolve project root for imports
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.orchestrator import SyncOrchestrator
from src.lock import sync_lock, should_debounce, LOCK_FILE_DEFAULT
from src.state_manager import StateManager
from src.adapters.result import SyncResult


def format_results_table(results: dict, account: str = None) -> str:
    """Format sync results as a summary table.

    Args:
        results: Dict mapping target_name -> {config_type: SyncResult}
        account: Optional account name for header

    Returns:
        Formatted table string
    """
    lines = []
    header = f"HarnessSync Results — {account}" if account else "HarnessSync Results"
    lines.append(header)
    lines.append("=" * 60)
    lines.append(f"{'Target':<12}| {'Synced':>6} | {'Skipped':>7} | {'Failed':>6} | {'Status':<8}")
    lines.append("-" * 12 + "+" + "-" * 8 + "+" + "-" * 9 + "+" + "-" * 8 + "+" + "-" * 8)

    total_synced = 0
    total_skipped = 0
    total_failed = 0

    for target, target_results in sorted(results.items()):
        # Skip special result keys
        if target.startswith('_'):
            continue

        synced = 0
        skipped = 0
        failed = 0

        if isinstance(target_results, dict):
            for config_type, result in target_results.items():
                if isinstance(result, SyncResult):
                    synced += result.synced
                    skipped += result.skipped
                    failed += result.failed

        total_synced += synced
        total_skipped += skipped
        total_failed += failed

        if failed == 0:
            status = "success"
        elif synced > 0 and failed > 0:
            status = "partial"
        elif synced == 0 and failed == 0:
            status = "nothing"
        else:
            status = "failed"

        lines.append(f"{target:<12}| {synced:>6} | {skipped:>7} | {failed:>6} | {status:<8}")

    lines.append("-" * 12 + "+" + "-" * 8 + "+" + "-" * 9 + "+" + "-" * 8 + "+" + "-" * 8)
    lines.append(f"{'Total':<12}| {total_synced:>6} | {total_skipped:>7} | {total_failed:>6} |")

    return "\n".join(lines)


def main():
    """Entry point for /sync command."""
    # Parse arguments from $ARGUMENTS
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync",
        description="Sync Claude Code config to all targets"
    )
    parser.add_argument(
        "--scope",
        choices=["user", "project", "all"],
        default="all",
        help="Sync scope (default: all)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files"
    )
    parser.add_argument(
        "--allow-secrets",
        action="store_true",
        help="Allow sync even when secrets detected in env vars"
    )
    parser.add_argument(
        "--account",
        type=str,
        default=None,
        help="Sync specific account (default: all accounts or v1 behavior)"
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    # Debounce check
    state_manager = StateManager()
    if should_debounce(state_manager):
        print("Sync skipped (debounce: last sync <3s ago)")
        return

    # Lock acquisition and sync
    try:
        with sync_lock(LOCK_FILE_DEFAULT):
            start_time = time.time()
            project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

            if args.account:
                # Sync specific account
                orchestrator = SyncOrchestrator(
                    project_dir=project_dir,
                    scope=args.scope,
                    dry_run=args.dry_run,
                    allow_secrets=args.allow_secrets,
                    account=args.account
                )
                results = orchestrator.sync_all()
                elapsed = time.time() - start_time

                _display_results(results, args, elapsed, account=args.account)
            else:
                # Auto-detect: sync all accounts if configured, else v1 behavior
                orchestrator = SyncOrchestrator(
                    project_dir=project_dir,
                    scope=args.scope,
                    dry_run=args.dry_run,
                    allow_secrets=args.allow_secrets
                )

                # Check for multi-account setup
                try:
                    from src.account_manager import AccountManager
                    am = AccountManager()
                    if am.has_accounts():
                        # Multi-account: sync each account
                        all_results = orchestrator.sync_all_accounts()
                        elapsed = time.time() - start_time

                        if isinstance(all_results, dict):
                            # Check if this is account-keyed results
                            first_key = next(iter(all_results), None)
                            if first_key and not first_key.startswith('_') and isinstance(all_results.get(first_key), dict):
                                # Check if first value looks like per-target results
                                first_val = all_results[first_key]
                                if any(k.startswith('_') or isinstance(v, (dict,)) for k, v in first_val.items()):
                                    # Account-keyed results
                                    for acct_name, acct_results in all_results.items():
                                        _display_results(acct_results, args, None, account=acct_name)
                                        print()
                                    print(f"All accounts synced in {elapsed:.1f}s")
                                    return

                        # Fallback: single results dict (v1 behavior from fallback)
                        _display_results(all_results, args, elapsed)
                        return
                except Exception:
                    pass

                # v1 behavior: no accounts configured
                results = orchestrator.sync_all()
                elapsed = time.time() - start_time
                _display_results(results, args, elapsed)

    except BlockingIOError:
        print("Sync already in progress, skipping")

    except KeyboardInterrupt:
        print("\nSync cancelled")
        sys.exit(130)

    except Exception as e:
        print(f"Sync error: {e}", file=sys.stderr)
        sys.exit(1)


def _display_results(results: dict, args, elapsed: float = None, account: str = None):
    """Display sync results.

    Args:
        results: Sync results dict
        args: Parsed arguments
        elapsed: Elapsed time in seconds
        account: Account name for display
    """
    # Check for blocked sync (secret detection)
    if results.get('_blocked'):
        print(results.get('_warnings', 'Sync blocked'))
        return

    if args.dry_run:
        header = f"HarnessSync Dry-Run Preview — {account}" if account else "HarnessSync Dry-Run Preview"
        print(header)
        print("=" * 60)
        for target, target_results in sorted(results.items()):
            if target.startswith('_'):
                continue
            if isinstance(target_results, dict) and "preview" in target_results:
                print(f"\n[{target}]")
                print(target_results["preview"])
        print(f"\n(dry-run complete, no files modified)")
    else:
        # Display conflict warnings if any
        if '_conflicts' in results:
            from src.conflict_detector import ConflictDetector
            cd = ConflictDetector()
            print(cd.format_warnings(results['_conflicts']))
            print()

        # Display results table
        print(format_results_table(results, account=account))
        if elapsed is not None:
            print(f"\nCompleted in {elapsed:.1f}s")

        # Display compatibility report if issues detected
        if '_compatibility_report' in results:
            print(results['_compatibility_report'])


if __name__ == "__main__":
    main()
