from __future__ import annotations

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

import subprocess
from pathlib import Path
from src.orchestrator import SyncOrchestrator
from src.lock import sync_lock, should_debounce, LOCK_FILE_DEFAULT
from src.state_manager import StateManager
from src.adapters.result import SyncResult


def _detect_git_root(cwd: Path) -> Path | None:
    """Return git repository root for cwd, or None if not inside a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=3,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None


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


def _save_profile_from_args(pm, args) -> None:
    """Save current sync args as a named profile."""
    name = args.profile_save
    config: dict = {"scope": args.scope}
    if args.only:
        config["only_sections"] = [s.strip() for s in args.only.split(",") if s.strip()]
    if args.skip:
        config["skip_sections"] = [s.strip() for s in args.skip.split(",") if s.strip()]
    try:
        pm.save_profile(name, config)
        print(f"Profile {name!r} saved. Activate with: /sync --profile {name}")
    except ValueError as e:
        print(f"Error saving profile: {e}", file=sys.stderr)


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
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Skip interactive conflict resolution (always overwrite)"
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Sync only these sections (comma-separated): rules,skills,agents,commands,mcp,settings"
    )
    parser.add_argument(
        "--skip",
        type=str,
        default=None,
        help="Skip these sections (comma-separated): rules,skills,agents,commands,mcp,settings"
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only sync targets where source files changed since last sync (delta sync)"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch for config file changes and sync automatically (Ctrl+C to stop)"
    )
    parser.add_argument(
        "--profile",
        type=str,
        default=None,
        help="Activate a named sync profile (e.g., 'work', 'minimal')"
    )
    parser.add_argument(
        "--profile-list",
        action="store_true",
        help="List all configured sync profiles and exit"
    )
    parser.add_argument(
        "--profile-save",
        type=str,
        default=None,
        metavar="NAME",
        help="Save current --scope/--only/--skip options as a named profile"
    )
    parser.add_argument(
        "--only-targets",
        type=str,
        default=None,
        help="Sync only these harness targets (comma-separated): codex,gemini,cursor,cline,..."
    )
    parser.add_argument(
        "--skip-targets",
        type=str,
        default=None,
        help="Skip these harness targets (comma-separated): codex,gemini,cursor,cline,..."
    )
    parser.add_argument(
        "--html-report",
        type=str,
        default=None,
        metavar="PATH",
        help="Write a self-contained HTML dry-run report to PATH (implies --dry-run)"
    )
    parser.add_argument(
        "--pick-sections",
        action="store_true",
        help="Launch interactive section picker to choose which sections to sync"
    )
    parser.add_argument(
        "--monorepo",
        action="store_true",
        help="Discover and sync each monorepo sub-package with its own config"
    )
    parser.add_argument(
        "--env",
        type=str,
        default=None,
        metavar="ENV",
        help=(
            "Filter env-tagged sections for this environment "
            "(e.g. 'production', 'dev'). Also reads HARNESS_ENV env var."
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Show a preview of all files that would be written and prompt y/n before syncing",
    )
    parser.add_argument(
        "--three-way",
        action="store_true",
        dest="three_way",
        help="Use three-way diff conflict resolution (shows per-section diffs; requires TTY)",
    )
    parser.add_argument(
        "--allow-anomalies",
        action="store_true",
        dest="allow_anomalies",
        help="Proceed even when sync anomaly detection flags unexpectedly large changes",
    )
    parser.add_argument(
        "--no-changelog",
        action="store_true",
        dest="no_changelog",
        help="Skip writing the auto-generated sync changelog entry",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    # --- PROFILE MANAGEMENT ---
    from src.profile_manager import ProfileManager
    pm = ProfileManager()

    if getattr(args, 'profile_list', False):
        print(pm.format_list())
        return

    if getattr(args, 'profile_save', None):
        _save_profile_from_args(pm, args)
        return

    # Parse --only / --skip into section sets
    only_sections = None
    skip_sections: set[str] = set()
    valid_sections = {"rules", "skills", "agents", "commands", "mcp", "settings"}
    if args.only:
        only_sections = {s.strip() for s in args.only.split(",") if s.strip()} & valid_sections
    if args.skip:
        skip_sections = {s.strip() for s in args.skip.split(",") if s.strip()} & valid_sections

    # --pick-sections: interactive multi-select (overrides --only/--skip when set)
    if getattr(args, "pick_sections", False) and not args.only and not args.skip:
        try:
            from src.section_picker import pick_sections_interactive, format_section_selection
            only_sections, skip_sections = pick_sections_interactive(
                preselected=only_sections or set(valid_sections),
            )
            print(format_section_selection(only_sections, skip_sections))
        except Exception:
            pass  # Non-blocking: fall back to syncing all sections

    # Parse --only-targets / --skip-targets into target sets
    cli_only_targets: set[str] | None = None
    cli_skip_targets: set[str] = set()
    if getattr(args, 'only_targets', None):
        cli_only_targets = {t.strip() for t in args.only_targets.split(",") if t.strip()}
    if getattr(args, 'skip_targets', None):
        cli_skip_targets = {t.strip() for t in args.skip_targets.split(",") if t.strip()}

    # Apply named profile (overrides --scope/--only/--skip if profile specifies them)
    _profile_targets = None
    if getattr(args, 'profile', None):
        try:
            base_kwargs = {
                "scope": args.scope,
                "only_sections": only_sections,
                "skip_sections": skip_sections,
            }
            merged = pm.apply_to_kwargs(args.profile, base_kwargs)
            args.scope = merged.get("scope", args.scope)
            only_sections = merged.get("only_sections", only_sections)
            skip_sections = merged.get("skip_sections", skip_sections)
            _profile_targets = merged.get("profile_targets")
            print(f"[profile: {args.profile}]")
        except KeyError as e:
            print(f"Error: {e}", file=sys.stderr)
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
            cwd = Path(os.getcwd())
            project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", cwd))

            # --- PROJECT-AWARE SCOPE AUTO-DETECTION ---
            # When inside a git repo and no explicit scope was given (default="all"),
            # inform the user that project-level configs are included.
            git_root = _detect_git_root(project_dir)
            if git_root and git_root != project_dir:
                # CLAUDE_PROJECT_DIR is set but differs from git root — use git root
                # only if CLAUDE_PROJECT_DIR was not explicitly provided
                if "CLAUDE_PROJECT_DIR" not in os.environ:
                    project_dir = git_root

            # --- PRE-SYNC: INTERACTIVE CONFLICT RESOLUTION ---
            if not args.dry_run and not args.no_interactive:
                import sys
                if sys.stdin.isatty():
                    try:
                        from src.conflict_detector import ConflictDetector
                        cd = ConflictDetector()
                        conflicts = cd.check_all()
                        if any(conflicts.values()):
                            use_three_way = getattr(args, "three_way", False)
                            if use_three_way:
                                # Three-way per-section resolution wizard
                                keep_files: list[str] = []
                                for target_name, target_conflicts in conflicts.items():
                                    for conflict in target_conflicts:
                                        from src.source_reader import SourceReader
                                        try:
                                            sr = SourceReader(scope=getattr(args, "scope", "all"),
                                                              project_dir=project_dir)
                                            source_data = sr.discover_all()
                                            source_content = source_data.get("rules", "")
                                        except Exception:
                                            source_content = ""
                                        three_way = cd.three_way_diff(source_content, conflict)
                                        if three_way["has_real_conflict"]:
                                            resolution, _ = cd.resolve_three_way_interactive(
                                                conflict, three_way
                                            )
                                            if resolution == "keep":
                                                keep_files.append(conflict["file_path"])
                                if keep_files:
                                    os.environ["HARNESSSYNC_KEEP_FILES"] = ",".join(keep_files)
                            else:
                                resolutions = cd.resolve_interactive(conflicts)
                                if resolutions:
                                    os.environ["HARNESSSYNC_KEEP_FILES"] = ",".join(
                                        fp for fp, action in resolutions.items() if action == "keep"
                                    )
                    except Exception:
                        pass  # Conflict resolution failure should not block sync

            # --- PRE-SYNC: APPROVAL GATE (--confirm) ---
            if getattr(args, "confirm", False) and not args.dry_run:
                try:
                    from src.native_preview import build_sync_preview, confirm_sync
                    from src.source_reader import SourceReader
                    _sr = SourceReader(scope=getattr(args, "scope", "all"),
                                       project_dir=project_dir)
                    _source_data = _sr.discover_all()
                    _preview_changes = build_sync_preview(
                        source_data=_source_data,
                        project_dir=project_dir,
                    )
                    if not confirm_sync(_preview_changes, force=False):
                        print("Sync cancelled by user.")
                        return
                except Exception:
                    pass  # Non-blocking: approval gate failure should not hard-break

            if getattr(args, 'watch', False):
                _run_watch_mode(project_dir, args, only_sections, skip_sections)
                return

            if getattr(args, 'monorepo', False):
                _run_monorepo_sync(project_dir, args)
                return

            harness_env = getattr(args, 'env', None)
            if harness_env:
                print(f"[env: {harness_env}]")

            if args.account:
                # Sync specific account
                orchestrator = SyncOrchestrator(
                    project_dir=project_dir,
                    scope=args.scope,
                    dry_run=args.dry_run,
                    allow_secrets=args.allow_secrets,
                    account=args.account,
                    only_sections=only_sections,
                    skip_sections=skip_sections,
                    incremental=getattr(args, 'incremental', False),
                    cli_only_targets=cli_only_targets,
                    cli_skip_targets=cli_skip_targets,
                    harness_env=harness_env,
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
                    allow_secrets=args.allow_secrets,
                    only_sections=only_sections,
                    skip_sections=skip_sections,
                    incremental=getattr(args, 'incremental', False),
                    cli_only_targets=cli_only_targets,
                    cli_skip_targets=cli_skip_targets,
                    harness_env=harness_env,
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
                    project_dir=Path(os.getcwd()),
                    scope=getattr(args, 'scope', 'all'),
                    account=account,
                )
                print(f"HTML report written to: {report_path}")
            except Exception as e:
                print(f"Warning: HTML report failed: {e}", file=sys.stderr)
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

        # Display fidelity scores (0-100 per target)
        if '_fidelity_report' in results:
            print(results['_fidelity_report'])

        # --- AUTO-GENERATED SYNC CHANGELOG ---
        if not getattr(args, "no_changelog", False):
            try:
                from src.changelog_manager import ChangelogManager
                cm = ChangelogManager(project_dir=Path(os.getcwd()))
                cm.record(
                    results,
                    scope=getattr(args, "scope", "all"),
                    account=account,
                )
            except Exception:
                pass  # Changelog write is best-effort

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
            _total_synced = sum(
                sum(getattr(r, "synced", 0) for r in tr.values() if hasattr(r, "synced"))
                for tr in results.values()
                if isinstance(tr, dict) and not str(list(tr.keys())[:1]).startswith("['_")
            )
            _total_failed = sum(
                sum(getattr(r, "failed", 0) for r in tr.values() if hasattr(r, "failed"))
                for tr in results.values()
                if isinstance(tr, dict) and not str(list(tr.keys())[:1]).startswith("['_")
            )
            _targets_synced = [k for k in results if not k.startswith("_")]
            _notif_msg = (
                f"{_total_synced} file(s) synced to {len(_targets_synced)} target(s)"
                if _total_failed == 0
                else f"{_total_synced} synced, {_total_failed} failed"
            )
            _send_desktop_notification(
                "HarnessSync",
                _notif_msg,
                is_error=_total_failed > 0,
            )
        except Exception:
            pass  # Desktop notifications are always best-effort


def _run_monorepo_sync(project_dir: Path, args) -> None:
    """Run per-package sync for a monorepo project.

    Discovers sub-packages with .harnesssync-package.json or CLAUDE.md files
    inside well-known package directories (packages/, apps/, libs/, etc.) and
    syncs each one with its own target/section overrides.
    """
    from src.monorepo_sync import MonorepoPackageDiscoverer, run_monorepo_sync, format_monorepo_results

    print("HarnessSync — Monorepo Mode")
    print("=" * 50)

    discoverer = MonorepoPackageDiscoverer(project_dir)
    packages = discoverer.discover()

    if not packages:
        print("No monorepo sub-packages found.")
        print(
            "Add a .harnesssync-package.json to any subdirectory, or place a CLAUDE.md "
            "inside packages/, apps/, libs/, or services/."
        )
        return

    print(discoverer.format_report(packages))
    print()

    results = run_monorepo_sync(
        project_dir=project_dir,
        packages=packages,
        dry_run=args.dry_run,
        scope=args.scope,
        allow_secrets=getattr(args, "allow_secrets", False),
    )

    print(format_monorepo_results(results))


def _run_watch_mode(project_dir: Path, args, only_sections, skip_sections) -> None:
    """Watch Claude Code config files and sync on change.

    Uses polling (stat mtime) since fswatch/inotify may not be available.
    Triggers incremental sync whenever a watched file changes.

    Args:
        project_dir: Project root directory
        args: Parsed sync arguments
        only_sections: Section filter from --only
        skip_sections: Section filter from --skip
    """
    import time as _time

    # Files and dirs to watch
    watch_targets = [
        project_dir / "CLAUDE.md",
        project_dir / ".claude",
        project_dir / ".mcp.json",
        project_dir / ".harness-sync",
        Path.home() / ".claude" / "settings.json",
        Path.home() / ".mcp.json",
    ]

    def _collect_mtimes() -> dict:
        mtimes: dict[str, float] = {}
        for target in watch_targets:
            if target.is_file():
                mtimes[str(target)] = target.stat().st_mtime
            elif target.is_dir():
                for f in target.rglob("*"):
                    if f.is_file():
                        mtimes[str(f)] = f.stat().st_mtime
        return mtimes

    print("HarnessSync Watch Mode")
    print("=" * 50)
    print("Watching Claude Code config files for changes...")
    print("Press Ctrl+C to stop.\n")

    last_mtimes = _collect_mtimes()

    try:
        while True:
            _time.sleep(1)
            current_mtimes = _collect_mtimes()

            changed = set()
            for path, mtime in current_mtimes.items():
                if last_mtimes.get(path) != mtime:
                    changed.add(path)
            for path in last_mtimes:
                if path not in current_mtimes:
                    changed.add(path)

            if changed:
                import datetime
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] Changes detected ({len(changed)} file(s)), syncing...")
                for p in sorted(changed)[:5]:
                    print(f"  {p}")

                try:
                    orchestrator = SyncOrchestrator(
                        project_dir=project_dir,
                        scope=args.scope,
                        dry_run=args.dry_run,
                        allow_secrets=args.allow_secrets,
                        only_sections=only_sections,
                        skip_sections=skip_sections,
                        incremental=True,  # Always incremental in watch mode
                    )
                    results = orchestrator.sync_all()
                    # Brief summary
                    synced_total = sum(
                        sum(getattr(r, 'synced', 0) for r in tr.values() if hasattr(r, 'synced'))
                        for tr in results.values()
                        if isinstance(tr, dict) and not str(tr).startswith('_')
                    )
                    print(f"[{ts}] Sync complete.\n")
                    _send_desktop_notification(
                        "HarnessSync", "Sync complete", is_error=False
                    )
                except Exception as e:
                    print(f"[{ts}] Sync error: {e}\n")
                    _send_desktop_notification(
                        "HarnessSync", f"Sync error: {e}", is_error=True
                    )

                last_mtimes = current_mtimes
    except KeyboardInterrupt:
        print("\nWatch mode stopped.")


def _send_desktop_notification(title: str, message: str, is_error: bool = False) -> None:
    """Send a desktop notification on macOS or Linux.

    Uses osascript (macOS) or notify-send (Linux) if available.
    Silently no-ops if no notification system is found.

    Args:
        title: Notification title.
        message: Notification body text.
        is_error: If True, uses error sound/icon on macOS.
    """
    import platform
    import subprocess as _subprocess

    system = platform.system()
    try:
        if system == "Darwin":
            # macOS: use osascript to show a notification
            subtitle = "Error" if is_error else "Success"
            sound = "Basso" if is_error else "Glass"
            script = (
                f'display notification "{message}" '
                f'with title "{title}" subtitle "{subtitle}" sound name "{sound}"'
            )
            _subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=3,
            )
        elif system == "Linux":
            # Linux: use notify-send if available
            import shutil as _shutil
            if _shutil.which("notify-send"):
                urgency = "critical" if is_error else "normal"
                _subprocess.run(
                    ["notify-send", "-u", urgency, title, message],
                    capture_output=True,
                    timeout=3,
                )
    except Exception:
        pass  # Desktop notifications are best-effort


if __name__ == "__main__":
    main()
