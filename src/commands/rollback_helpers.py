from __future__ import annotations

"""Helper functions for /sync-rollback: backup discovery, diff preview, restore.

Extracted from sync_rollback.py to keep the main command file focused on
CLI argument parsing and dispatch logic.
"""

import datetime
import difflib
import shutil
import sys
from pathlib import Path

BACKUP_ROOT = Path.home() / ".harnesssync" / "backups"


def find_backup_by_timestamp(backups: list[Path], timestamp_str: str) -> Path | None:
    """Find the most recent backup on or before the given timestamp string.

    Args:
        backups: Sorted list of backup dirs (newest first).
        timestamp_str: Timestamp like "YYYY-MM-DD" or "YYYY-MM-DDTHH:MM".

    Returns:
        Matching backup Path, or None if none found.
    """
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


def find_backup_before_commit(
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


def list_backups_for_target(target: str) -> list[Path]:
    """Return sorted list of backup dirs for a target (newest first)."""
    target_dir = BACKUP_ROOT / target
    if not target_dir.exists():
        return []
    backups = [d for d in target_dir.iterdir() if d.is_dir()]
    backups.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    return backups


def get_all_targets() -> list[str]:
    """Return list of targets that have backups."""
    if not BACKUP_ROOT.exists():
        return []
    return sorted(d.name for d in BACKUP_ROOT.iterdir() if d.is_dir())


def diff_preview(backup_dir: Path, project_dir: Path) -> str:
    """Return a unified-diff string showing what rollback would change.

    Compares every file in *backup_dir* against its current counterpart in
    *project_dir*.  Files that exist in the backup but are absent in the
    working tree are shown as pure additions (i.e. they would be restored).
    Files that exist only in the working tree are not shown -- rollback never
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

    def _walk(base: Path) -> list[Path]:
        result: list[Path] = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                result.append(p)
        return result

    restore_root = children[0]
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
            continue

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


def restore_backup(backup_dir: Path, project_dir: Path, target: str) -> bool:
    """Restore a backup to the project directory.

    Args:
        backup_dir: Path to the backup directory
        project_dir: Project root to restore into
        target: Target name (used to determine restore path)

    Returns:
        True on success, False on failure
    """
    children = list(backup_dir.iterdir())
    if not children:
        print(f"Backup {backup_dir.name} is empty.", file=sys.stderr)
        return False

    restore_source = children[0]
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


def find_last_known_good_backup(target: str, project_dir: Path) -> Path | None:
    """Find the backup from the most recent sync where all targets were healthy.

    Queries the audit log for "sync" events and walks backwards from newest to
    oldest to find the last event that had no failures.

    Falls back to the second-most-recent backup if the audit log is empty.

    Args:
        target: Target harness to roll back.
        project_dir: Project root (used to locate the audit log).

    Returns:
        Best-candidate backup Path, or None if no backups exist.
    """
    backups = list_backups_for_target(target)
    if not backups:
        return None

    clean_ts: float | None = None
    try:
        from src.audit_log import AuditLog
        audit = AuditLog(project_dir=project_dir)
        for entry in reversed(audit.tail(500)):
            if entry.event != "sync":
                continue
            failed = entry.extra.get("failed", 0) if isinstance(entry.extra, dict) else 0
            if int(failed) == 0:
                try:
                    from datetime import datetime as _dt, timezone as _tz
                    ts_str = entry.timestamp.rstrip("Z")
                    ts_dt = _dt.fromisoformat(ts_str).replace(tzinfo=_tz.utc)
                    clean_ts = ts_dt.timestamp()
                    break
                except (ValueError, AttributeError):
                    continue
    except Exception:
        pass

    if clean_ts is not None:
        for backup_dir in backups:
            try:
                mtime = backup_dir.stat().st_mtime
            except OSError:
                continue
            if mtime <= clean_ts + 60:
                dt = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
                print(f"Last-known-good sync was at {dt} (audit log reference)")
                print(f"Selected backup: {backup_dir.name}")
                return backup_dir

    if len(backups) >= 2:
        fallback = backups[1]
        dt = datetime.datetime.fromtimestamp(fallback.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        print(f"No clean-state event found in audit log — using second-most-recent backup ({dt})")
        print(f"Selected backup: {fallback.name}")
        return fallback

    print(f"Only one backup available — using: {backups[0].name}")
    return backups[0]
