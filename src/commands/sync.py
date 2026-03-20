from __future__ import annotations

"""
/sync slash command implementation.

Syncs Claude Code configuration to all registered target CLIs.
Supports --scope (user/project/all), --dry-run, and --account flags.

Implementation split across:
- sync_display.py — results formatting and output
- sync_modes.py — watch mode and monorepo sync
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
from src.source_reader import SourceReader

# Re-export for backward compatibility
from src.commands.sync_display import format_results_table  # noqa: F401
from src.commands.sync_display import display_results as _display_results
from src.commands.sync_modes import run_watch_mode as _run_watch_mode
from src.commands.sync_modes import run_monorepo_sync as _run_monorepo_sync


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


def _parse_args(tokens: list[str]) -> argparse.Namespace | None:
    """Parse sync CLI arguments. Returns None on parse failure."""
    parser = argparse.ArgumentParser(
        prog="sync",
        description="Sync Claude Code config to all targets"
    )
    parser.add_argument("--scope", choices=["user", "project", "all"], default="all",
                        help="Sync scope (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview changes without writing files")
    parser.add_argument("--allow-secrets", action="store_true",
                        help="Allow sync even when secrets detected in env vars")
    parser.add_argument("--scrub-secrets", action="store_true",
                        help="Replace detected secret values with ${VAR_NAME} placeholders instead of blocking")
    parser.add_argument("--account", type=str, default=None,
                        help="Sync specific account (default: all accounts or v1 behavior)")
    parser.add_argument("--no-interactive", action="store_true",
                        help="Skip interactive conflict resolution (always overwrite)")
    parser.add_argument("--only", type=str, default=None,
                        help="Sync only these sections (comma-separated): rules,skills,agents,commands,mcp,settings")
    parser.add_argument("--skip", type=str, default=None,
                        help="Skip these sections (comma-separated): rules,skills,agents,commands,mcp,settings")
    parser.add_argument("--incremental", action="store_true",
                        help="Only sync targets where source files changed since last sync (delta sync)")
    parser.add_argument("--minimal", action="store_true",
                        help=("Minimal Footprint Mode: sync only rules and essential MCP servers to each target. "
                              "Skills, agents, commands, and non-essential MCP servers are skipped. "
                              "Mark a server as essential with '\"essential\": true' in .mcp.json."))
    parser.add_argument("--watch", action="store_true",
                        help="Watch for config file changes and sync automatically (Ctrl+C to stop)")
    parser.add_argument("--profile", type=str, default=None,
                        help="Activate a named sync profile (e.g., 'work', 'minimal')")
    parser.add_argument("--profile-list", action="store_true",
                        help="List all configured sync profiles and exit")
    parser.add_argument("--profile-save", type=str, default=None, metavar="NAME",
                        help="Save current --scope/--only/--skip options as a named profile")
    parser.add_argument("--only-targets", type=str, default=None,
                        help="Sync only these harness targets (comma-separated): codex,gemini,cursor,cline,...")
    parser.add_argument("--skip-targets", type=str, default=None,
                        help="Skip these harness targets (comma-separated): codex,gemini,cursor,cline,...")
    parser.add_argument("--only-for", type=str, default=None, metavar="TARGET:SECTIONS",
                        action="append", dest="only_for",
                        help=("Sync only specific sections to a specific target. "
                              "Format: TARGET:section1,section2 (e.g. 'gemini:skills,rules'). "
                              "Repeat for multiple targets."))
    parser.add_argument("--html-report", type=str, default=None, metavar="PATH",
                        help="Write a self-contained HTML dry-run report to PATH (implies --dry-run)")
    parser.add_argument("--pick-sections", action="store_true",
                        help="Launch interactive section picker to choose which sections to sync")
    parser.add_argument("--monorepo", action="store_true",
                        help="Discover and sync each monorepo sub-package with its own config")
    parser.add_argument("--env", type=str, default=None, metavar="ENV",
                        help=("Filter env-tagged sections for this environment "
                              "(e.g. 'production', 'dev'). Also reads HARNESS_ENV env var."))
    parser.add_argument("--confirm", action="store_true",
                        help="Show a preview of all files that would be written and prompt y/n before syncing")
    parser.add_argument("--three-way", action="store_true", dest="three_way",
                        help="Use three-way diff conflict resolution (shows per-section diffs; requires TTY)")
    parser.add_argument("--section-wizard", action="store_true", dest="section_wizard",
                        help=("Interactively resolve conflicts section-by-section before syncing. "
                              "For each conflicting Markdown section, choose: use synced version, "
                              "keep your edits, or skip the section entirely. Requires a TTY."))
    parser.add_argument("--allow-anomalies", action="store_true", dest="allow_anomalies",
                        help="Proceed even when sync anomaly detection flags unexpectedly large changes")
    parser.add_argument("--no-changelog", action="store_true", dest="no_changelog",
                        help="Skip writing the auto-generated sync changelog entry")
    parser.add_argument("--enable-global-dry-run", action="store_true", dest="enable_global_dry_run",
                        help=("Persistently enable global dry-run mode: all future syncs will preview "
                              "changes without writing files until disabled."))
    parser.add_argument("--disable-global-dry-run", action="store_true", dest="disable_global_dry_run",
                        help="Disable persistent global dry-run mode, restoring normal sync behavior.")
    parser.add_argument("--dotfiles-path", type=str, default=None, metavar="PATH", dest="dotfiles_path",
                        help=("After a successful sync, auto-commit changed harness configs to this "
                              "dotfiles git repository."))
    parser.add_argument("--dotfiles-push", action="store_true", dest="dotfiles_push",
                        help="With --dotfiles-path: push to remote after committing.")

    try:
        return parser.parse_args(tokens)
    except SystemExit:
        return None


def _resolve_sections(args, pm, valid_sections: set[str]):
    """Resolve --only, --skip, --pick-sections, and --profile into section sets.

    Returns:
        (only_sections, skip_sections, profile_targets) tuple
    """
    only_sections = None
    skip_sections: set[str] = set()

    if args.only:
        only_sections = {s.strip() for s in args.only.split(",") if s.strip()} & valid_sections
    if args.skip:
        skip_sections = {s.strip() for s in args.skip.split(",") if s.strip()} & valid_sections

    # --pick-sections: interactive multi-select
    if getattr(args, "pick_sections", False) and not args.only and not args.skip:
        try:
            from src.section_picker import pick_sections_interactive, format_section_selection
            only_sections, skip_sections = pick_sections_interactive(
                preselected=only_sections or set(valid_sections),
            )
            print(format_section_selection(only_sections, skip_sections))
        except Exception:
            pass

    # Apply named profile
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
            return None, None, "error"

    return only_sections, skip_sections, _profile_targets


def _resolve_target_filters(args, valid_sections: set[str]):
    """Resolve --only-targets, --skip-targets, and --only-for into filter sets.

    Returns:
        (cli_only_targets, cli_skip_targets, cli_per_target_only) tuple
    """
    cli_only_targets: set[str] | None = None
    cli_skip_targets: set[str] = set()

    if getattr(args, 'only_targets', None):
        cli_only_targets = {t.strip() for t in args.only_targets.split(",") if t.strip()}
    if getattr(args, 'skip_targets', None):
        cli_skip_targets = {t.strip() for t in args.skip_targets.split(",") if t.strip()}

    cli_per_target_only: dict[str, set[str]] = {}
    for only_for_entry in (getattr(args, "only_for", None) or []):
        if ":" not in only_for_entry:
            print(
                f"Warning: --only-for '{only_for_entry}' ignored — expected format TARGET:sections",
                file=sys.stderr,
            )
            continue
        tgt, _, secs_str = only_for_entry.partition(":")
        tgt = tgt.strip()
        secs = {s.strip() for s in secs_str.split(",") if s.strip()} & valid_sections
        if not secs:
            print(
                f"Warning: --only-for '{only_for_entry}' has no valid sections; "
                f"valid: {', '.join(sorted(valid_sections))}",
                file=sys.stderr,
            )
            continue
        if tgt in cli_per_target_only:
            cli_per_target_only[tgt] |= secs
        else:
            cli_per_target_only[tgt] = secs
    if cli_per_target_only:
        for tgt, secs in sorted(cli_per_target_only.items()):
            print(f"[only-for] {tgt}: syncing only {', '.join(sorted(secs))}")

    return cli_only_targets, cli_skip_targets, cli_per_target_only


def _run_conflict_resolution(args, source_data: dict) -> None:
    """Run pre-sync interactive conflict resolution if applicable."""
    if args.dry_run or args.no_interactive:
        return
    if not sys.stdin.isatty():
        return
    try:
        from src.conflict_detector import ConflictDetector
        cd = ConflictDetector()
        conflicts = cd.check_all()
        if not any(conflicts.values()):
            return

        use_section_wizard = getattr(args, "section_wizard", False)
        use_three_way = getattr(args, "three_way", False)
        source_content = source_data.get("rules", "")

        if use_section_wizard:
            section_merged: dict[str, str] = {}
            for _target_name, target_conflicts in conflicts.items():
                for conflict in target_conflicts:
                    file_path = conflict.get("file_path", "")
                    current_content = ""
                    try:
                        from pathlib import Path as _Path
                        _fp = _Path(file_path)
                        if _fp.exists():
                            current_content = _fp.read_text(encoding="utf-8", errors="replace")
                    except OSError:
                        pass
                    sec_conflicts = cd.section_conflicts(source_content, conflict)
                    if sec_conflicts:
                        print(f"\nSection wizard: {file_path}")
                        sec_resolutions = cd.resolve_section_interactive(sec_conflicts)
                        merged = cd.apply_section_resolutions(
                            source_content, current_content, sec_resolutions
                        )
                        section_merged[file_path] = merged
            if section_merged:
                import json as _json
                os.environ["HARNESSSYNC_SECTION_MERGED"] = _json.dumps(section_merged)
        elif use_three_way:
            keep_files: list[str] = []
            for target_name, target_conflicts in conflicts.items():
                for conflict in target_conflicts:
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
            try:
                from src.conflict_detector import ConflictResolutionWizard
                wizard = ConflictResolutionWizard(cd)
                _wizard_src: dict[str, str] = {}
                for _tgt, _clist in conflicts.items():
                    for _c in _clist:
                        _fp = _c.get("file_path", "")
                        if _fp and _fp not in _wizard_src:
                            _wizard_src[_fp] = source_content
                wizard_resolutions = wizard.run_interactive(
                    conflicts,
                    source_contents=_wizard_src,
                )
                keep_files_wizard = [
                    fp for (_, fp), action in wizard_resolutions.items()
                    if action == ConflictResolutionWizard.RESOLUTION_KEEP_TARGET
                ]
                if keep_files_wizard:
                    os.environ["HARNESSSYNC_KEEP_FILES"] = ",".join(keep_files_wizard)
            except Exception:
                resolutions = cd.resolve_interactive(conflicts)
                if resolutions:
                    os.environ["HARNESSSYNC_KEEP_FILES"] = ",".join(
                        fp for fp, action in resolutions.items() if action == "keep"
                    )
    except Exception:
        pass  # Conflict resolution failure should not block sync


def main():
    """Entry point for /sync command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    args = _parse_args(tokens)
    if args is None:
        return

    # --- GLOBAL DRY-RUN TOGGLE ---
    state_mgr_early = StateManager()
    if getattr(args, "enable_global_dry_run", False):
        state_mgr_early.set_global_dry_run(True)
        print("Global dry-run mode ENABLED. All syncs will preview without writing.")
        print("Disable with: /sync --disable-global-dry-run")
        return
    if getattr(args, "disable_global_dry_run", False):
        state_mgr_early.set_global_dry_run(False)
        print("Global dry-run mode DISABLED. Syncs will write files normally.")
        return
    if state_mgr_early.get_global_dry_run():
        print("[global dry-run mode active — pass --disable-global-dry-run to write files]")

    # --- PROFILE MANAGEMENT ---
    from src.profile_manager import ProfileManager
    pm = ProfileManager()

    if getattr(args, 'profile_list', False):
        print(pm.format_list())
        return

    if getattr(args, 'profile_save', None):
        _save_profile_from_args(pm, args)
        return

    valid_sections = {"rules", "skills", "agents", "commands", "mcp", "settings"}
    only_sections, skip_sections, _profile_targets = _resolve_sections(args, pm, valid_sections)
    if _profile_targets == "error":
        return

    cli_only_targets, cli_skip_targets, cli_per_target_only = _resolve_target_filters(args, valid_sections)

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
            git_root = _detect_git_root(project_dir)
            if git_root and git_root != project_dir:
                if "CLAUDE_PROJECT_DIR" not in os.environ:
                    project_dir = git_root

            # --- SHARED SOURCE READER ---
            source_reader = SourceReader(
                scope=getattr(args, "scope", "all"),
                project_dir=project_dir,
            )
            source_data = source_reader.discover_all()

            # --- PRE-SYNC IMPACT SUMMARY ---
            try:
                from src.pre_sync_summary import PreSyncSummary
                import json as _pss_json
                _snapshot_path = project_dir / ".harnesssync-last-source.json"
                _prev_source: dict = {}
                if _snapshot_path.exists():
                    try:
                        _prev_source = _pss_json.loads(
                            _snapshot_path.read_text(encoding="utf-8")
                        )
                    except Exception:
                        pass
                _pss = PreSyncSummary()
                _summary_line = _pss.one_liner(source_data, _prev_source)
                if _summary_line and "up to date" not in _summary_line:
                    print(f"[preview] {_summary_line}")
            except Exception:
                pass

            # --- PRE-SYNC: INTERACTIVE CONFLICT RESOLUTION ---
            _run_conflict_resolution(args, source_data)

            # --- PRE-SYNC: APPROVAL GATE (--confirm) ---
            if getattr(args, "confirm", False) and not args.dry_run:
                try:
                    from src.native_preview import (
                        build_sync_preview, confirm_sync, get_all_native_previews
                    )
                    _rules = source_data.get("rules", "")
                    if isinstance(_rules, list):
                        _rules = "\n\n".join(
                            r.get("content", "") for r in _rules if isinstance(r, dict)
                        )
                    _preview_all = get_all_native_previews(
                        rules_content=_rules,
                        mcp_servers=source_data.get("mcp_servers", {}),
                        settings=source_data.get("settings", {}),
                    )
                    _preview_changes = build_sync_preview(
                        preview_all=_preview_all,
                        project_dir=project_dir,
                    )
                    if not confirm_sync(_preview_changes, force=False):
                        print("Sync cancelled by user.")
                        return
                except Exception:
                    pass

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
                    scrub_secrets=getattr(args, 'scrub_secrets', False),
                    account=args.account,
                    only_sections=only_sections,
                    skip_sections=skip_sections,
                    incremental=getattr(args, 'incremental', False),
                    cli_only_targets=cli_only_targets,
                    cli_skip_targets=cli_skip_targets,
                    harness_env=harness_env,
                    cli_per_target_only=cli_per_target_only if cli_per_target_only else None,
                    minimal=getattr(args, 'minimal', False),
                )
                results = orchestrator.sync_all()
                elapsed = time.time() - start_time

                _display_results(results, args, elapsed, account=args.account,
                                 source_data=source_data, project_dir=project_dir)
            else:
                # Auto-detect: sync all accounts if configured, else v1 behavior
                orchestrator = SyncOrchestrator(
                    project_dir=project_dir,
                    scope=args.scope,
                    dry_run=args.dry_run,
                    allow_secrets=args.allow_secrets,
                    scrub_secrets=getattr(args, 'scrub_secrets', False),
                    only_sections=only_sections,
                    skip_sections=skip_sections,
                    incremental=getattr(args, 'incremental', False),
                    cli_only_targets=cli_only_targets,
                    cli_skip_targets=cli_skip_targets,
                    harness_env=harness_env,
                    cli_per_target_only=cli_per_target_only if cli_per_target_only else None,
                    minimal=getattr(args, 'minimal', False),
                )

                # Check for multi-account setup
                try:
                    from src.account_manager import AccountManager
                    am = AccountManager()
                    if am.has_accounts():
                        all_results = orchestrator.sync_all_accounts()
                        elapsed = time.time() - start_time

                        if isinstance(all_results, dict):
                            first_key = next(iter(all_results), None)
                            if first_key and not first_key.startswith('_') and isinstance(all_results.get(first_key), dict):
                                first_val = all_results[first_key]
                                if any(k.startswith('_') or isinstance(v, (dict,)) for k, v in first_val.items()):
                                    for acct_name, acct_results in all_results.items():
                                        _display_results(acct_results, args, None, account=acct_name,
                                                         source_data=source_data, project_dir=project_dir)
                                        print()
                                    print(f"All accounts synced in {elapsed:.1f}s")
                                    return

                        _display_results(all_results, args, elapsed,
                                         source_data=source_data, project_dir=project_dir)
                        return
                except Exception:
                    pass

                # v1 behavior: no accounts configured
                results = orchestrator.sync_all()
                elapsed = time.time() - start_time
                _display_results(results, args, elapsed,
                                 source_data=source_data, project_dir=project_dir)

    except BlockingIOError:
        print("Sync already in progress, skipping")

    except KeyboardInterrupt:
        print("\nSync cancelled")
        sys.exit(130)

    except Exception as e:
        print(f"Sync error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
