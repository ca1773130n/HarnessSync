from __future__ import annotations

"""
/sync-rollback slash command implementation.

Lists available sync backups and restores a target to a previous state.
"""

import os
import sys
import shlex
import argparse
import shutil
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)




BACKUP_ROOT = Path.home() / ".harnesssync" / "backups"


def _list_backups_for_target(target: str) -> list[Path]:
    """Return sorted list of backup dirs for a target (newest first)."""
    target_dir = BACKUP_ROOT / target
    if not target_dir.exists():
        return []
    backups = [d for d in target_dir.iterdir() if d.is_dir()]
    backups.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return backups


def _get_all_targets() -> list[str]:
    """Return list of targets that have backups."""
    if not BACKUP_ROOT.exists():
        return []
    return sorted(d.name for d in BACKUP_ROOT.iterdir() if d.is_dir())


def _restore_backup(backup_dir: Path, project_dir: Path, target: str) -> bool:
    """Restore a backup to the project directory.

    Args:
        backup_dir: Path to the backup directory
        project_dir: Project root to restore into
        target: Target name (used to determine restore path)

    Returns:
        True on success, False on failure
    """
    # Find the backed-up file/directory inside the backup dir
    children = list(backup_dir.iterdir())
    if not children:
        print(f"Backup {backup_dir.name} is empty.", file=sys.stderr)
        return False

    restore_source = children[0]

    # Determine where to restore (use backup item name as destination)
    dest = project_dir / restore_source.name

    try:
        if restore_source.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(restore_source, dest, symlinks=True)
        else:
            shutil.copy2(restore_source, dest)
        return True
    except OSError as e:
        print(f"Restore failed: {e}", file=sys.stderr)
        return False


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
    parser.add_argument(
        "--backup",
        type=str,
        default=None,
        help="Backup name to restore (from --list output). Omit to restore most recent.",
    )
    parser.add_argument("--project-dir", type=str, default=None)
    parser.add_argument(
        "--label",
        type=str,
        default=None,
        help="Filter --list to backups with this label, or find backup by label for restore.",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    if args.list or (not args.target):
        # List all available backups using BackupManager for label-aware output
        try:
            from src.backup_manager import BackupManager
            bm = BackupManager()
            snapshots = bm.list_snapshots(target_name=args.target or None)
        except Exception:
            snapshots = []

        if not snapshots:
            print("No backups found. Run /sync to create backups automatically.")
            return

        # Filter by label if requested
        if args.label:
            snapshots = [s for s in snapshots if s.get("label") == args.label]
            if not snapshots:
                print(f"No backups found with label '{args.label}'.")
                return

        import datetime
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

        print("\nUse: /sync-rollback --target <target> [--backup <name>] [--label <label>]")
        return

    # Rollback specific target
    target = args.target
    backups = _list_backups_for_target(target)

    if not backups:
        print(f"No backups found for target '{target}'.")
        return

    if args.backup:
        # Find named backup
        backup_dir = None
        for b in backups:
            if b.name == args.backup:
                backup_dir = b
                break
        if not backup_dir:
            print(f"Backup '{args.backup}' not found for target '{target}'.")
            print("Run /sync-rollback --list to see available backups.")
            return
    elif args.label:
        # Find most recent backup with matching label
        try:
            from src.backup_manager import BackupManager
            bm = BackupManager()
            snapshots = bm.list_snapshots(target_name=target)
            labeled = [s for s in snapshots if s.get("label") == args.label]
            if not labeled:
                print(f"No backups found for target '{target}' with label '{args.label}'.")
                return
            backup_dir = labeled[0]["path"]
        except Exception as e:
            print(f"Error finding labeled backup: {e}", file=sys.stderr)
            return
    else:
        # Use most recent
        backup_dir = backups[0]

    print(f"Restoring {target} from backup: {backup_dir.name}")
    success = _restore_backup(backup_dir, project_dir, target)

    if success:
        print(f"Rollback complete. {target} restored to state from {backup_dir.name}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
