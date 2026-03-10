from __future__ import annotations

"""
/sync-restore slash command implementation.

Lists available config snapshots and restores a chosen one. Snapshots are
created by BackupManager before every sync. Users can roll back to any
recent snapshot if a bad CLAUDE.md change propagated to target harnesses.

Usage:
  /sync-restore                         List available snapshots
  /sync-restore --date 2026-03-10       Restore closest snapshot to date
  /sync-restore --latest                Restore the most recent snapshot
  /sync-restore --target codex          Restore snapshots for one target only
"""

import os
import shlex
import shutil
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

import argparse
from datetime import datetime
from pathlib import Path


def _backup_root() -> Path:
    return Path.home() / ".harnesssync" / "backups"


def _list_snapshots(target_filter: str | None = None) -> dict[str, list[tuple[str, datetime, Path]]]:
    """Return per-target snapshot lists sorted newest-first.

    Returns:
        Dict mapping target_name -> list of (name, timestamp, path).
    """
    root = _backup_root()
    result: dict[str, list[tuple[str, datetime, Path]]] = {}

    if not root.exists():
        return result

    for target_dir in sorted(root.iterdir()):
        if not target_dir.is_dir():
            continue
        target = target_dir.name
        if target_filter and target != target_filter:
            continue

        snapshots: list[tuple[str, datetime, Path]] = []
        for snap in sorted(target_dir.iterdir(), reverse=True):
            if not snap.is_dir():
                continue
            # Parse timestamp from name suffix: {filename}_{YYYYMMDD_HHMMSS}
            parts = snap.name.rsplit("_", 2)
            if len(parts) >= 3:
                try:
                    ts_str = f"{parts[-2]}_{parts[-1]}"
                    ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
                    snapshots.append((snap.name, ts, snap))
                except ValueError:
                    snapshots.append((snap.name, datetime.fromtimestamp(snap.stat().st_mtime), snap))
            else:
                snapshots.append((snap.name, datetime.fromtimestamp(snap.stat().st_mtime), snap))

        if snapshots:
            result[target] = snapshots

    return result


def _find_closest_snapshot(
    snapshots: list[tuple[str, datetime, Path]],
    date_str: str,
) -> tuple[str, datetime, Path] | None:
    """Find the snapshot whose timestamp is closest to (and before) the given date."""
    try:
        target_dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        try:
            target_dt = datetime.fromisoformat(date_str)
        except ValueError:
            print(f"Error: cannot parse date '{date_str}'. Use YYYY-MM-DD.", file=sys.stderr)
            return None

    candidates = [(name, ts, path) for name, ts, path in snapshots if ts <= target_dt]
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[1])


def _restore_snapshot(snap_path: Path, target: str, project_dir: Path) -> bool:
    """Restore files from a snapshot directory to the project.

    Looks for files inside the snapshot dir and copies them back.
    Returns True on success.
    """
    restored = 0
    for item in snap_path.iterdir():
        # Each item is the backed-up file/directory with its original name
        dest_map: dict[str, Path] = {
            "AGENTS.md": project_dir / "AGENTS.md",
            "GEMINI.md": project_dir / "GEMINI.md",
            "opencode.json": project_dir / "opencode.json",
            "config.toml": project_dir / ".codex" / "config.toml",
            "settings.json": project_dir / ".gemini" / "settings.json",
        }
        dest = dest_map.get(item.name)
        if dest is None:
            # Attempt direct restore by name
            dest = project_dir / item.name

        try:
            if item.is_dir():
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(item, dest, symlinks=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
            print(f"  Restored: {dest}")
            restored += 1
        except OSError as e:
            print(f"  Error restoring {item.name}: {e}", file=sys.stderr)

    return restored > 0


def main() -> None:
    """Entry point for /sync-restore command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-restore",
        description="List and restore HarnessSync config snapshots"
    )
    parser.add_argument("--date", type=str, default=None,
                        help="Restore snapshot closest to this date (YYYY-MM-DD)")
    parser.add_argument("--latest", action="store_true",
                        help="Restore the most recent snapshot for each target")
    parser.add_argument("--target", type=str, default=None,
                        help="Limit restore to a specific target (codex/gemini/opencode)")
    parser.add_argument("--list", action="store_true",
                        help="List available snapshots (default when no other flags)")

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    snapshots = _list_snapshots(target_filter=args.target)

    if not snapshots:
        print("No snapshots found. Snapshots are created automatically before each sync.")
        return

    # --- LIST MODE ---
    if args.list or (not args.date and not args.latest):
        print("HarnessSync Snapshots")
        print("=" * 60)
        for target, snaps in sorted(snapshots.items()):
            print(f"\n[{target}] ({len(snaps)} snapshot(s))")
            for i, (name, ts, path) in enumerate(snaps[:10]):
                marker = " ← most recent" if i == 0 else ""
                print(f"  {ts.strftime('%Y-%m-%d %H:%M:%S')}  {name}{marker}")
            if len(snaps) > 10:
                print(f"  ... and {len(snaps) - 10} older")
        print("\nTo restore: /sync-restore --latest   OR   /sync-restore --date YYYY-MM-DD")
        return

    # --- RESTORE MODE ---
    print("HarnessSync Restore")
    print("=" * 60)

    for target, snaps in sorted(snapshots.items()):
        chosen: tuple[str, datetime, Path] | None = None

        if args.latest:
            chosen = snaps[0]
        elif args.date:
            chosen = _find_closest_snapshot(snaps, args.date)

        if not chosen:
            print(f"\n[{target}] No matching snapshot found")
            continue

        name, ts, snap_path = chosen
        print(f"\n[{target}] Restoring from {ts.strftime('%Y-%m-%d %H:%M:%S')} ({name})")
        ok = _restore_snapshot(snap_path, target, project_dir)
        if ok:
            print(f"  [{target}] Restore complete")
        else:
            print(f"  [{target}] Restore had errors — check messages above")


if __name__ == "__main__":
    main()
