from __future__ import annotations

"""
/sync-rollback slash command implementation.

Lists available sync backups and restores a target to a previous state.

Implementation split: rollback_helpers.py contains backup discovery,
diff preview, and restore logic.
"""

import datetime
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.commands.rollback_helpers import (  # noqa: E402
    BACKUP_ROOT,
    diff_preview as _diff_preview,
    find_backup_before_commit as _find_backup_before_commit,
    find_backup_by_timestamp as _find_backup_by_timestamp,
    find_last_known_good_backup as _find_last_known_good_backup,
    list_backups_for_target as _list_backups_for_target,
    restore_backup as _restore_backup,
)


def main() -> None:
    """Entry point for /sync-rollback command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-rollback",
        description="Restore a target to a previous backed-up state",
    )
    parser.add_argument("--list", action="store_true", help="List available backups (with labels)")
    parser.add_argument("--target", type=str, help="Target to rollback (codex, gemini, etc.)")
    parser.add_argument("--backup", type=str, default=None,
                        help="Backup name to restore (from --list output). Omit to restore most recent.")
    parser.add_argument("--project-dir", type=str, default=None)
    parser.add_argument("--label", type=str, default=None,
                        help="Filter --list to backups with this label, or find backup by label for restore.")
    parser.add_argument("--timestamp", type=str, default=None,
                        help=("Restore the most recent backup on or before this timestamp. "
                              "Formats: YYYY-MM-DD or YYYY-MM-DDTHH:MM."))
    parser.add_argument("--before-commit", type=str, default=None,
                        help=("Restore the backup taken before a specific git commit SHA. "
                              "Example: --before-commit abc1234"))
    parser.add_argument("--diff-preview", action="store_true", default=False,
                        help="Show a unified diff of what would change before executing the rollback.")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="Show what would be restored without making any changes.")
    parser.add_argument("--context", action="store_true", default=False,
                        help="Show change context for each listed backup.")
    parser.add_argument("--steps", type=int, default=None, metavar="N",
                        help="Undo the last N sync operations using the undo stack. Requires --target.")
    parser.add_argument("--last-known-good", action="store_true", default=False, dest="last_known_good",
                        help=("Find and restore the most recent sync checkpoint where ALL active "
                              "targets had status='success'."))

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    # --last-known-good: find and restore the last clean-state backup
    if getattr(args, "last_known_good", False):
        _handle_last_known_good(args, project_dir)
        return

    # --steps N: undo the last N operations via HarnessUndoStack
    if args.steps is not None:
        _handle_undo_steps(args, project_dir)
        return

    if args.list or (not args.target):
        _handle_list(args)
        return

    # Rollback specific target
    _handle_rollback(args, project_dir)


def _handle_last_known_good(args, project_dir: Path) -> None:
    """Handle --last-known-good flag."""
    if not args.target:
        print("Error: --last-known-good requires --target.", file=sys.stderr)
        sys.exit(1)
    backup_dir = _find_last_known_good_backup(args.target, project_dir)
    if backup_dir is None:
        print(f"No backups found for target '{args.target}'.")
        return
    if args.dry_run or args.diff_preview:
        dt = datetime.datetime.fromtimestamp(backup_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"\nDiff preview: {args.target} -> last-known-good backup {backup_dir.name} ({dt})")
        print("=" * 70)
        diff = _diff_preview(backup_dir, project_dir)
        if diff:
            print(diff)
        else:
            print("  (no differences -- target files already match backup)")
        print("\nDry run -- no files modified.")
        return
    success = _restore_backup(backup_dir, project_dir, args.target)
    if success:
        dt = datetime.datetime.fromtimestamp(backup_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"Rollback complete. {args.target} restored to last-known-good state ({dt})")
    else:
        sys.exit(1)


def _handle_undo_steps(args, project_dir: Path) -> None:
    """Handle --steps N flag."""
    if not args.target:
        print("Error: --steps requires --target.", file=sys.stderr)
        sys.exit(1)
    try:
        from src.sync_undo_stack import SyncUndoManager
        mgr = SyncUndoManager(project_dir=project_dir)
        results = mgr.undo_n(args.target, args.steps, dry_run=args.dry_run)
    except Exception as exc:
        print(f"Error accessing undo stack: {exc}", file=sys.stderr)
        sys.exit(1)

    if not results:
        print(f"Undo stack for '{args.target}' is empty.")
        return

    for i, result in enumerate(results, 1):
        if result.ok:
            mode = "Would restore" if args.dry_run else "Restored"
            files = ", ".join(result.files_restored) or "(none)"
            print(f"  Step {i}: {mode} '{result.label}' -- {files}")
        else:
            print(f"  Step {i}: {result.error}")
            break

    ok_count = sum(1 for r in results if r.ok)
    print(f"\n{ok_count}/{len(results)} undo step(s) {'previewed' if args.dry_run else 'applied'}.")


def _handle_list(args) -> None:
    """Handle --list flag or no-target display."""
    try:
        from src.backup_manager import BackupManager
        bm = BackupManager()
        snapshots = bm.list_snapshots(target_name=args.target or None)
    except Exception:
        snapshots = []

    if not snapshots:
        print("No backups found. Run /sync to create backups automatically.")
        return

    if args.label:
        snapshots = [s for s in snapshots if s.get("label") == args.label]
        if not snapshots:
            print(f"No backups found with label '{args.label}'.")
            return

    print("Available Sync Backups (newest first)")
    print("=" * 60)
    current_target = None
    for snap in snapshots:
        if snap["target"] != current_target:
            current_target = snap["target"]
            print(f"\n{current_target}:")
        dt = datetime.datetime.fromtimestamp(snap["mtime"]).strftime("%Y-%m-%d %H:%M:%S")
        label_str = f"  [label: {snap['label']}]" if snap.get("label") else ""
        print(f"  {snap['name']}  ({dt}){label_str}")

        if args.context:
            try:
                from src.backup_manager import get_backup_context
                ctx = get_backup_context(snap["path"])
                trigger = ctx.get("trigger")
                sections = ctx.get("changed_sections") or []
                rule = ctx.get("changed_rule")
                if trigger:
                    print(f"      trigger        : {trigger}")
                if sections:
                    print(f"      changed sections: {', '.join(sections)}")
                if rule:
                    print(f"      changed rule    : {rule}")
                if not trigger and not sections and not rule:
                    print("      (no change context recorded for this backup)")
            except Exception:
                print("      (change context unavailable)")

    print("\nUse: /sync-rollback --target <target> [--backup <name>] [--label <label>]")
    if not args.context:
        print("     Add --context to see what triggered each backup.")


def _handle_rollback(args, project_dir: Path) -> None:
    """Handle rollback of a specific target."""
    target = args.target
    backups = _list_backups_for_target(target)

    if not backups:
        print(f"No backups found for target '{target}'.")
        return

    backup_dir = _resolve_backup(args, backups, target, project_dir)
    if backup_dir is None:
        return

    # Diff preview
    if args.diff_preview or args.dry_run:
        dt = datetime.datetime.fromtimestamp(backup_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"\nDiff preview: {target} -> backup {backup_dir.name} ({dt})")
        print("=" * 70)
        diff = _diff_preview(backup_dir, project_dir)
        if diff:
            print(diff)
        else:
            print("(no differences -- files are already identical to this backup)")
        print("=" * 70)

        if args.dry_run and not args.diff_preview:
            print("\nDry run -- no files modified.")
            return
        if args.diff_preview and not args.dry_run:
            print("\nProceeding with rollback...")
        else:
            print("\nDry run -- no files modified.")
            return

    print(f"Restoring {target} from backup: {backup_dir.name}")
    success = _restore_backup(backup_dir, project_dir, target)

    if success:
        print(f"Rollback complete. {target} restored to state from {backup_dir.name}")
    else:
        sys.exit(1)


def _resolve_backup(args, backups: list[Path], target: str, project_dir: Path) -> Path | None:
    """Resolve which backup to use based on CLI arguments."""
    if args.backup:
        for b in backups:
            if b.name == args.backup:
                return b
        print(f"Backup '{args.backup}' not found for target '{target}'.")
        print("Run /sync-rollback --list to see available backups.")
        return None
    elif args.timestamp:
        backup_dir = _find_backup_by_timestamp(backups, args.timestamp)
        if backup_dir is None:
            print(f"No backup found for target '{target}' at or before '{args.timestamp}'.")
            print("Run /sync-rollback --list to see available backups with their timestamps.")
        return backup_dir
    elif args.before_commit:
        backup_dir = _find_backup_before_commit(backups, args.before_commit, project_dir)
        if backup_dir is None:
            print(
                f"Could not find a backup for target '{target}' before commit '{args.before_commit}'. "
                "Ensure git history is available and the commit SHA is valid."
            )
        return backup_dir
    elif args.label:
        try:
            from src.backup_manager import BackupManager
            bm = BackupManager()
            snapshots = bm.list_snapshots(target_name=target)
            labeled = [s for s in snapshots if s.get("label") == args.label]
            if not labeled:
                print(f"No backups found for target '{target}' with label '{args.label}'.")
                return None
            return Path(labeled[0]["path"])
        except Exception as e:
            print(f"Error finding labeled backup: {e}", file=sys.stderr)
            return None
    else:
        return backups[0]


if __name__ == "__main__":
    main()
