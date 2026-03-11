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
    parser.add_argument("--list", action="store_true", help="List available backups")
    parser.add_argument("--target", type=str, help="Target to rollback (codex, gemini, etc.)")
    parser.add_argument(
        "--backup",
        type=str,
        default=None,
        help="Backup name to restore (from --list output). Omit to restore most recent.",
    )
    parser.add_argument("--project-dir", type=str, default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    if args.list or (not args.target):
        # List all available backups
        targets = _get_all_targets()
        if not targets:
            print("No backups found. Run /sync to create backups automatically.")
            return

        print("Available Sync Backups")
        print("=" * 60)
        for t in targets:
            backups = _list_backups_for_target(t)
            print(f"\n{t} ({len(backups)} backup(s)):")
            for b in backups[:5]:
                mtime = b.stat().st_mtime
                import datetime
                dt = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                print(f"  {b.name}  ({dt})")
            if len(backups) > 5:
                print(f"  ... and {len(backups) - 5} older backups")

        print("\nUse: /sync-rollback --target <target> [--backup <name>]")
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
