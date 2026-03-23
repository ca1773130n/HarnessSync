from __future__ import annotations

"""
/sync-watch slash command — File-watch auto-sync daemon.

Polls CLAUDE.md, .claude/skills/, .claude/commands/, .mcp.json, and
settings.json for mtime changes and triggers Orchestrator.sync_all() on
any modification. Fills the gap left by the PostToolUse hook, which only
fires when Claude Code itself edits files.

Usage:
    /sync-watch                    # poll every 2 seconds (default)
    /sync-watch --interval 5       # poll every 5 seconds
    /sync-watch --targets cursor,gemini  # only sync specific targets
    /sync-watch --dry-run          # show what would sync, don't write
"""

import os
import sys
import shlex
import argparse
import signal
import time

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.orchestrator import SyncOrchestrator


# Files and directories to watch (relative to project root)
_WATCH_PATHS = [
    "CLAUDE.md",
    ".mcp.json",
    "settings.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
]

_WATCH_DIRS = [
    ".claude/skills",
    ".claude/commands",
    ".claude/agents",
]


def _collect_watch_targets(project_dir: Path) -> list[Path]:
    """Return list of existing paths to watch."""
    paths: list[Path] = []
    for rel in _WATCH_PATHS:
        p = project_dir / rel
        if p.exists():
            paths.append(p)
    for rel_dir in _WATCH_DIRS:
        d = project_dir / rel_dir
        if d.is_dir():
            for child in d.rglob("*"):
                if child.is_file():
                    paths.append(child)
    return paths


def _snapshot_mtimes(paths: list[Path]) -> dict[str, float]:
    """Return {str(path): mtime} for all existing paths."""
    result: dict[str, float] = {}
    for p in paths:
        try:
            result[str(p)] = p.stat().st_mtime
        except OSError:
            pass
    return result


def _detect_changes(
    old_snapshot: dict[str, float],
    new_snapshot: dict[str, float],
) -> list[str]:
    """Return list of paths that changed between snapshots."""
    changed: list[str] = []
    for path, mtime in new_snapshot.items():
        if path not in old_snapshot or old_snapshot[path] != mtime:
            changed.append(path)
    # Also catch deleted files
    for path in old_snapshot:
        if path not in new_snapshot:
            changed.append(path)
    return changed


class _SyncSummary:
    """Accumulates sync stats for the final exit summary."""

    def __init__(self):
        self.syncs = 0
        self.total_synced = 0
        self.total_failed = 0
        self.changed_paths: list[str] = []

    def record(self, changed: list[str], results: dict) -> None:
        self.syncs += 1
        self.changed_paths.extend(changed)
        for target_results in results.values():
            if isinstance(target_results, dict):
                for r in target_results.values():
                    if hasattr(r, "synced"):
                        self.total_synced += r.synced
                    if hasattr(r, "failed"):
                        self.total_failed += r.failed

    def print_summary(self) -> None:
        print()
        print("─" * 50)
        print("sync-watch summary")
        print(f"  Sync runs triggered : {self.syncs}")
        print(f"  Files synced        : {self.total_synced}")
        print(f"  Failures            : {self.total_failed}")
        if self.changed_paths:
            unique = sorted(set(self.changed_paths))
            print(f"  Trigger files       : {', '.join(unique[:5])}", end="")
            if len(unique) > 5:
                print(f" (+{len(unique) - 5} more)", end="")
            print()


def main() -> None:
    """Entry point for /sync-watch command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-watch",
        description="Watch config files and auto-sync on change (Ctrl+C to stop).",
    )
    parser.add_argument(
        "--interval", type=float, default=2.0, metavar="SECS",
        help="Polling interval in seconds (default: 2)",
    )
    parser.add_argument(
        "--targets", type=str, default=None,
        help="Comma-separated list of targets to sync (default: all)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would sync without writing files",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path.cwd()
    interval = max(0.5, args.interval)
    only_targets = (
        [t.strip() for t in args.targets.split(",") if t.strip()]
        if args.targets
        else None
    )

    summary = _SyncSummary()
    stop_requested = False

    def _handle_sigint(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, _handle_sigint)

    print(f"sync-watch: monitoring config files (interval={interval}s)")
    if only_targets:
        print(f"  targets: {', '.join(only_targets)}")
    if args.dry_run:
        print("  dry-run mode: changes will be previewed, not written")
    print("  Press Ctrl+C to stop.\n")

    watch_paths = _collect_watch_targets(project_dir)
    if not watch_paths:
        print("No config files found to watch. Is this a Claude Code project directory?")
        return

    snapshot = _snapshot_mtimes(watch_paths)

    while not stop_requested:
        time.sleep(interval)
        if stop_requested:
            break

        # Refresh watch list (handles newly created files)
        watch_paths = _collect_watch_targets(project_dir)
        new_snapshot = _snapshot_mtimes(watch_paths)
        changed = _detect_changes(snapshot, new_snapshot)

        if changed:
            snapshot = new_snapshot
            changed_display = ", ".join(
                os.path.relpath(p, project_dir) for p in changed[:3]
            )
            if len(changed) > 3:
                changed_display += f" (+{len(changed) - 3} more)"
            print(f"[{_timestamp()}] Change detected: {changed_display}")

            try:
                orchestrator = SyncOrchestrator(
                    project_dir=project_dir,
                    dry_run=args.dry_run,
                )
                if only_targets:
                    results = orchestrator.sync_all(targets=only_targets)
                else:
                    results = orchestrator.sync_all()

                success_count = sum(
                    1 for tr in results.values()
                    if isinstance(tr, dict) and not any(
                        k == "error" for k in tr
                    )
                )
                print(f"  Synced {success_count}/{len(results)} targets.")
                summary.record(changed, results)
            except Exception as e:
                print(f"  Sync error: {e}")

    summary.print_summary()


def _timestamp() -> str:
    """Return HH:MM:SS timestamp string."""
    import datetime
    return datetime.datetime.now().strftime("%H:%M:%S")


if __name__ == "__main__":
    main()
