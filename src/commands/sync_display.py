from __future__ import annotations

"""Sync output formatting: results table, dry-run preview, and post-sync display.

Extracted from sync.py to keep the main command file focused on CLI parsing
and orchestration dispatch.
"""

import os
import sys
from pathlib import Path

from src.adapters.result import SyncResult
from src.desktop_notifier import notify_from_results


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


def display_results(results: dict, args, elapsed: float = None, account: str = None,
                    source_data: dict = None, project_dir: Path = None):
    """Display sync results.

    Args:
        results: Sync results dict
        args: Parsed arguments
        elapsed: Elapsed time in seconds
        account: Account name for display
        source_data: Pre-computed source data from SourceReader.discover_all()
        project_dir: Project root directory
    """
    # Check for blocked sync (secret detection)
    if results.get('_blocked'):
        print(results.get('_warnings', 'Sync blocked'))
        return

    if args.dry_run:
        _display_dry_run(results, args, account, source_data, project_dir)
    else:
        _display_live_results(results, args, elapsed, account, source_data, project_dir)


def _display_dry_run(results: dict, args, account: str = None,
                     source_data: dict = None, project_dir: Path = None):
    """Display dry-run preview output."""
    header = f"HarnessSync Dry-Run Preview — {account}" if account else "HarnessSync Dry-Run Preview"
    print(header)
    print("=" * 60)
    for target, target_results in sorted(results.items()):
        if target.startswith('_'):
            continue
        if isinstance(target_results, dict) and "preview" in target_results:
            print(f"\n[{target}]")
            print(target_results["preview"])
    # --- TERRAFORM-STYLE PLAN SUMMARY (item 1) ---
    # Show consolidated "+ created / ~ modified / = unchanged" counts.
    if source_data is not None and project_dir is not None:
        try:
            from src.native_preview import (
                get_all_native_previews, build_sync_preview, format_sync_preview
            )
            _rules = source_data.get("rules", "")
            if isinstance(_rules, list):
                _rules = "\n\n".join(
                    r.get("content", "") for r in _rules if isinstance(r, dict)
                )
            _pall = get_all_native_previews(
                rules_content=_rules,
                mcp_servers=source_data.get("mcp_servers", {}),
                settings=source_data.get("settings", {}),
            )
            _pchanges = build_sync_preview(preview_all=_pall, project_dir=project_dir)
            if _pchanges:
                print()
                print(format_sync_preview(_pchanges))
        except Exception:
            pass  # Preview summary is best-effort

    print("\n(dry-run complete, no files modified)")

    # Write HTML report if --html-report specified
    html_report_path = getattr(args, 'html_report', None)
    if html_report_path:
        try:
            from src.html_report import write_html_report
            report_path = Path(html_report_path)
            write_html_report(
                dry_run_results=results,
                output_path=report_path,
                project_dir=project_dir or Path(os.getcwd()),
                scope=getattr(args, 'scope', 'all'),
                account=account,
            )
            print(f"HTML report written to: {report_path}")
        except Exception as e:
            print(f"Warning: HTML report failed: {e}", file=sys.stderr)


def _display_live_results(results: dict, args, elapsed: float = None,
                          account: str = None, source_data: dict = None,
                          project_dir: Path = None):
    """Display results from a live (non-dry-run) sync."""
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

    # Display fidelity scores (0-100 per target)
    if '_fidelity_report' in results:
        print(results['_fidelity_report'])

    # Display harness upgrade notices (item 20)
    if '_upgrade_notices' in results:
        print()
        print(results['_upgrade_notices'])

    # Display model preference sync summary (item 27)
    if '_model_routing_summary' in results:
        print()
        print(results['_model_routing_summary'])

    # Note: Changelog recording is handled by the orchestrator (see orchestrator.py).
    # Do NOT call ChangelogManager.record() here to avoid duplicate writes.

    # --- SYNC ANOMALY CHECK (post-sync, for next-run awareness) ---
    # Record source length for future shrinkage detection
    try:
        from src.sync_anomaly import SyncAnomalyDetector
        _anomaly_det = SyncAnomalyDetector()
        # Check for anomaly hints surfaced by orchestrator
        if "_anomalies" in results:
            _anomaly_report = _anomaly_det.format_report(results["_anomalies"])
            if _anomaly_report:
                print(_anomaly_report)
    except Exception:
        pass

    # --- DESKTOP NOTIFICATION (regular sync, not just watch mode) ---
    try:
        notify_from_results(results)
    except Exception:
        pass  # Desktop notifications are always best-effort

    # --- DOTFILES AUTO-COMMIT (item 3) ---
    # After a successful sync, stage and commit changed harness configs
    # into the user's dotfiles git repository (if --dotfiles-path is set).
    dotfiles_path = getattr(args, "dotfiles_path", None)
    if dotfiles_path and not getattr(args, "dry_run", False) and not results.get("_blocked"):
        try:
            from src.dotfile_integration import DotfilesAutoCommitter
            committer = DotfilesAutoCommitter(
                dotfiles_repo=Path(dotfiles_path),
                project_dir=project_dir or Path(os.getcwd()),
                push_after_commit=getattr(args, "dotfiles_push", False),
            )
            if committer.is_available():
                changed_targets = [
                    t for t in results
                    if not t.startswith("_") and isinstance(results[t], dict)
                ]
                commit_result = committer.commit(changed_targets=changed_targets)
                print(commit_result.format())
            else:
                print(
                    f"[dotfiles] {dotfiles_path!r} is not a git repository "
                    "or git is not on PATH — skipping auto-commit"
                )
        except Exception as _df_err:
            print(f"[dotfiles] auto-commit failed: {_df_err}", file=sys.stderr)
