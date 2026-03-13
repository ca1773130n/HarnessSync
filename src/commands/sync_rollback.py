from __future__ import annotations

"""
/sync-rollback slash command implementation.

Lists available sync backups and restores a target to a previous state.

Time-travel rollback extensions:
  --timestamp YYYY-MM-DD or YYYY-MM-DDTHH:MM  restore the most recent backup
      taken on or before the given timestamp
  --before-commit <sha>  restore the backup taken before a specific git commit
      (requires git history in the project)
"""

import datetime
import difflib
import os
import sys
import shlex
import argparse
import shutil
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)




BACKUP_ROOT = Path.home() / ".harnesssync" / "backups"


def _find_backup_by_timestamp(backups: list[Path], timestamp_str: str) -> Path | None:
    """Find the most recent backup on or before the given timestamp string.

    Args:
        backups: Sorted list of backup dirs (newest first).
        timestamp_str: Timestamp like "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM".

    Returns:
        Matching backup Path, or None if none found.
    """
    # Parse the requested cutoff timestamp
    cutoff: datetime.datetime | None = None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            cutoff = datetime.datetime.strptime(timestamp_str, fmt)
            break
        except ValueError:
            continue

    if cutoff is None:
        print(
            f"Unrecognized timestamp format: '{timestamp_str}'. "
            "Use YYYY-MM-DD or YYYY-MM-DDTHH:MM.",
            file=sys.stderr,
        )
        return None

    cutoff_ts = cutoff.timestamp()

    # backups are sorted newest-first; find the first one whose mtime <= cutoff
    for backup_dir in backups:
        try:
            mtime = backup_dir.stat().st_mtime
        except OSError:
            continue
        if mtime <= cutoff_ts:
            dt = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            print(f"Selected backup: {backup_dir.name} ({dt})")
            return backup_dir

    return None


def _find_backup_before_commit(
    backups: list[Path], commit_sha: str, project_dir: Path
) -> Path | None:
    """Find the most recent backup taken before the given git commit timestamp.

    Args:
        backups: Sorted backup dirs (newest first).
        commit_sha: Git commit SHA (full or short).
        project_dir: Project root (used to run git commands).

    Returns:
        Matching backup Path, or None if not found.
    """
    import subprocess

    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", commit_sha],
            capture_output=True,
            text=True,
            cwd=str(project_dir),
            timeout=5,
        )
        if result.returncode != 0 or not result.stdout.strip():
            print(
                f"Could not resolve commit '{commit_sha}': {result.stderr.strip()}",
                file=sys.stderr,
            )
            return None
        commit_ts = float(result.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, ValueError) as e:
        print(f"Git error: {e}", file=sys.stderr)
        return None

    dt_commit = datetime.datetime.fromtimestamp(commit_ts).strftime("%Y-%m-%d %H:%M:%S")
    print(f"Commit {commit_sha[:8]} was at {dt_commit} — looking for backup just before that...")

    # Find the most recent backup that predates the commit
    for backup_dir in backups:
        try:
            mtime = backup_dir.stat().st_mtime
        except OSError:
            continue
        if mtime < commit_ts:
            dt = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            print(f"Selected backup: {backup_dir.name} ({dt})")
            return backup_dir

    return None


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


def _diff_preview(backup_dir: Path, project_dir: Path) -> str:
    """Return a unified-diff string showing what rollback would change.

    Compares every file in *backup_dir* against its current counterpart in
    *project_dir*.  Files that exist in the backup but are absent in the
    working tree are shown as pure additions (i.e. they would be restored).
    Files that exist only in the working tree are not shown — rollback never
    deletes files that weren't in the backup.

    Args:
        backup_dir: Backup snapshot directory.
        project_dir: Project root to compare against.

    Returns:
        Unified diff string, or an empty string if no differences found.
    """
    diff_lines: list[str] = []

    children = list(backup_dir.iterdir())
    if not children:
        return ""

    # Walk all files in the backup recursively
    def _walk(base: Path) -> list[Path]:
        result: list[Path] = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                result.append(p)
        return result

    restore_root = children[0]  # first child is the item to restore
    backup_files = _walk(restore_root) if restore_root.is_dir() else [restore_root]

    for backup_file in backup_files:
        if restore_root.is_dir():
            rel = backup_file.relative_to(restore_root)
            current_file = project_dir / restore_root.name / rel
        else:
            current_file = project_dir / restore_root.name

        try:
            backup_lines = backup_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
        except OSError:
            continue

        if current_file.exists():
            try:
                current_lines = current_file.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
            except OSError:
                current_lines = []
        else:
            current_lines = []

        if backup_lines == current_lines:
            continue  # no difference

        label_current = str(current_file) if current_file.exists() else f"{current_file} (new)"
        chunk = list(difflib.unified_diff(
            current_lines,
            backup_lines,
            fromfile=f"current/{current_file.name}",
            tofile=f"backup/{backup_file.name}",
            lineterm="",
        ))
        if chunk:
            diff_lines.extend(chunk)
            diff_lines.append("")

    return "\n".join(diff_lines)


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
    parser.add_argument(
        "--timestamp",
        type=str,
        default=None,
        help=(
            "Restore the most recent backup on or before this timestamp. "
            "Formats: YYYY-MM-DD or YYYY-MM-DDTHH:MM. "
            "Example: --timestamp 2025-03-10 or --timestamp '2025-03-10T14:30'"
        ),
    )
    parser.add_argument(
        "--before-commit",
        type=str,
        default=None,
        help=(
            "Restore the backup taken before a specific git commit SHA. "
            "Uses git log to find the commit timestamp then selects the nearest backup. "
            "Example: --before-commit abc1234"
        ),
    )
    parser.add_argument(
        "--diff-preview",
        action="store_true",
        default=False,
        help=(
            "Show a unified diff of what would change in each harness file before "
            "executing the rollback.  Use with --target to preview a specific target. "
            "When combined with --dry-run (implied), no files are modified."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Show what would be restored without making any changes.",
    )
    parser.add_argument(
        "--context",
        action="store_true",
        default=False,
        help=(
            "Show change context for each listed backup: what triggered the sync, "
            "which sections changed, and which rule was modified. "
            "Turns rollback into a root-cause debugging tool."
        ),
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Undo the last N sync operations using the undo stack (not file backups). "
            "Requires --target.  Example: --target codex --steps 3"
        ),
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    # --steps N: undo the last N operations via HarnessUndoStack
    if args.steps is not None:
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
                print(f"  Step {i}: {mode} '{result.label}' — {files}")
            else:
                print(f"  Step {i}: {result.error}")
                break

        ok_count = sum(1 for r in results if r.ok)
        print(f"\n{ok_count}/{len(results)} undo step(s) {'previewed' if args.dry_run else 'applied'}.")
        return

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

            # --context: show change context from backup metadata (item 23)
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
    elif args.timestamp:
        # Time-travel: find backup on or before given timestamp
        backup_dir = _find_backup_by_timestamp(backups, args.timestamp)
        if backup_dir is None:
            print(f"No backup found for target '{target}' at or before '{args.timestamp}'.")
            print("Run /sync-rollback --list to see available backups with their timestamps.")
            return
    elif args.before_commit:
        # Time-travel: find backup taken before a specific git commit
        backup_dir = _find_backup_before_commit(backups, args.before_commit, project_dir)
        if backup_dir is None:
            print(
                f"Could not find a backup for target '{target}' before commit '{args.before_commit}'. "
                "Ensure git history is available and the commit SHA is valid."
            )
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

    # Diff preview (item 29): show what would change before executing rollback.
    if args.diff_preview or args.dry_run:
        dt = datetime.datetime.fromtimestamp(backup_dir.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"\nDiff preview: {target} → backup {backup_dir.name} ({dt})")
        print("=" * 70)
        diff = _diff_preview(backup_dir, project_dir)
        if diff:
            print(diff)
        else:
            print("(no differences — files are already identical to this backup)")
        print("=" * 70)

        if args.dry_run and not args.diff_preview:
            # Pure dry-run without explicit --diff-preview: still skip restore
            print("\nDry run — no files modified.")
            return
        if args.diff_preview and not args.dry_run:
            # Diff-preview alone: ask confirmation or proceed
            print("\nProceeding with rollback...")
        else:
            # Both flags set: just preview, no restore
            print("\nDry run — no files modified.")
            return

    print(f"Restoring {target} from backup: {backup_dir.name}")
    success = _restore_backup(backup_dir, project_dir, target)

    if success:
        print(f"Rollback complete. {target} restored to state from {backup_dir.name}")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
