from __future__ import annotations

"""
/sync-watch slash command — File-watch auto-sync daemon.

Polls CLAUDE.md, .claude/skills/, .claude/commands/, .mcp.json, and
settings.json for mtime changes and triggers Orchestrator.sync_all() on
any modification. Fills the gap left by the PostToolUse hook, which only
fires when Claude Code itself edits files.

The daemon PID is stored at .claude/harness-sync/watch.pid so that
/sync can detect a running watcher and skip redundant syncs.

Usage:
    /sync-watch                    # poll every 2 seconds (default)
    /sync-watch --interval 5       # poll every 5 seconds
    /sync-watch --targets cursor,gemini  # only sync specific targets
    /sync-watch --dry-run          # show what would sync, don't write
    /sync-watch --stop             # stop a running watcher daemon
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

# PID file location: .claude/harness-sync/watch.pid (relative to project dir)
_PID_FILE_REL = ".claude/harness-sync/watch.pid"


def _pid_file_path(project_dir: Path) -> Path:
    return project_dir / _PID_FILE_REL


def _write_pid(project_dir: Path) -> None:
    """Write current process PID to the watch.pid file."""
    pid_file = _pid_file_path(project_dir)
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")


def _clear_pid(project_dir: Path) -> None:
    """Remove the watch.pid file."""
    pid_file = _pid_file_path(project_dir)
    try:
        pid_file.unlink(missing_ok=True)
    except OSError:
        pass


def is_watcher_running(project_dir: Path) -> int | None:
    """Return the watcher PID if a live watcher is running, else None."""
    pid_file = _pid_file_path(project_dir)
    if not pid_file.is_file():
        return None
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        # Check if the process is alive (signal 0 = existence check)
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError):
        # Stale PID file — clean it up
        _clear_pid(project_dir)
        return None


def _stop_watcher(project_dir: Path) -> None:
    """Send SIGINT to a running watcher and remove its PID file."""
    pid = is_watcher_running(project_dir)
    if pid is None:
        print("No sync-watch daemon is running.")
        return
    try:
        os.kill(pid, signal.SIGINT)
        print(f"Sent stop signal to watcher (PID {pid}).")
        _clear_pid(project_dir)
    except OSError as e:
        print(f"Could not stop watcher (PID {pid}): {e}")


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

# Known target (harness) output files that drift detection watches.
# Maps harness name -> list of paths relative to project root.
_TARGET_FILES: dict[str, list[str]] = {
    "codex": ["AGENTS.md"],
    "gemini": ["GEMINI.md"],
    "cursor": [".cursor/rules/CLAUDE.mdc", ".cursorrules"],
    "aider": [".aider.conf.yml", "aider.conf.yml"],
    "cline": [".clinerules"],
    "windsurf": [".windsurfrules"],
    "opencode": ["opencode.json"],
    "zed": [".zed/settings.json"],
    "continue": [".continue/config.json"],
    "vscode": [".vscode/settings.json"],
    "neovim": [".config/nvim/codecompanion.json"],
}


def _collect_target_paths(project_dir: Path) -> list[Path]:
    """Return list of existing harness target output files."""
    paths: list[Path] = []
    for file_list in _TARGET_FILES.values():
        for rel in file_list:
            p = project_dir / rel
            if p.exists():
                paths.append(p)
    return paths


def _load_last_synced_hashes(project_dir: Path) -> dict[str, str]:
    """Load per-file hashes from the last sync state."""
    import hashlib
    import json as _json
    state_path = project_dir / ".claude/harness-sync/state.json"
    try:
        if state_path.exists():
            data = _json.loads(state_path.read_text(encoding="utf-8"))
            return data.get("file_hashes", {})
    except Exception:
        pass
    return {}


def _hash_file(path: Path) -> str:
    """Return MD5 hex digest of file content."""
    import hashlib
    try:
        return hashlib.md5(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _check_target_drift(
    project_dir: Path,
    last_synced_hashes: dict[str, str],
    known_hashes: dict[str, str],
) -> list[tuple[str, str]]:
    """Return list of (path, harness_name) for target files that drifted externally.

    A file has drifted if its current hash differs from the last-synced hash
    AND differs from what we recorded at watch start (to avoid double-reporting).
    """
    drifted: list[tuple[str, str]] = []
    for harness, file_list in _TARGET_FILES.items():
        for rel in file_list:
            p = project_dir / rel
            key = str(p)
            if not p.exists():
                continue
            current_hash = _hash_file(p)
            synced_hash = last_synced_hashes.get(key) or last_synced_hashes.get(rel)
            # Only report if: we have a known synced hash AND current differs from it
            # AND this is a new change (not already in known_hashes)
            if synced_hash and current_hash != synced_hash:
                if known_hashes.get(key) != current_hash:
                    drifted.append((key, harness))
    return drifted


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
    parser.add_argument(
        "--stop", action="store_true",
        help="Stop a running sync-watch daemon and exit",
    )
    parser.add_argument(
        "--project-dir", default=None,
        help="Project directory (default: current directory)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(
        args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    )
    interval = max(0.5, args.interval)
    only_targets: set[str] | None = (
        {t.strip() for t in args.targets.split(",") if t.strip()}
        if args.targets
        else None
    )

    if args.stop:
        _stop_watcher(project_dir)
        return

    # Check if a watcher is already running
    existing_pid = is_watcher_running(project_dir)
    if existing_pid is not None:
        print(f"sync-watch: a watcher is already running (PID {existing_pid}).")
        print("Use --stop to stop it, or kill it manually.")
        return

    summary = _SyncSummary()
    stop_requested = False

    def _handle_sigint(signum, frame):
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGINT, _handle_sigint)

    _write_pid(project_dir)

    print(f"sync-watch: monitoring config files (interval={interval}s, PID={os.getpid()})")
    if only_targets:
        print(f"  targets: {', '.join(sorted(only_targets))}")
    if args.dry_run:
        print("  dry-run mode: changes will be previewed, not written")
    print("  Press Ctrl+C to stop.\n")

    watch_paths = _collect_watch_targets(project_dir)
    if not watch_paths:
        print("No config files found to watch. Is this a Claude Code project directory?")
        _clear_pid(project_dir)
        return

    snapshot = _snapshot_mtimes(watch_paths)

    # Snapshot of target file hashes at watch start (for drift detection)
    _target_known_hashes: dict[str, str] = {
        str(p): _hash_file(p) for p in _collect_target_paths(project_dir)
    }

    try:
        while not stop_requested:
            time.sleep(interval)
            if stop_requested:
                break

            # Refresh watch list (handles newly created files)
            watch_paths = _collect_watch_targets(project_dir)
            new_snapshot = _snapshot_mtimes(watch_paths)
            changed = _detect_changes(snapshot, new_snapshot)

            # --- TARGET DRIFT DETECTION ---
            try:
                last_hashes = _load_last_synced_hashes(project_dir)
                if last_hashes:
                    drifted = _check_target_drift(project_dir, last_hashes, _target_known_hashes)
                    for drift_path, harness_name in drifted:
                        # Update our known snapshot so we don't re-notify
                        _target_known_hashes[drift_path] = _hash_file(Path(drift_path))
                        rel = os.path.relpath(drift_path, project_dir)
                        msg = (
                            f"{rel} manually edited — "
                            f"run /sync to re-sync or /sync-resolve to merge"
                        )
                        print(f"[{_timestamp()}] Drift detected: {msg}")
                        try:
                            from src.notifiers.desktop import notify
                            notify(msg, title=f"HarnessSync — {harness_name} drift")
                        except Exception:
                            pass
            except Exception:
                pass  # Drift check must never interrupt the watch loop

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
                        cli_only_targets=only_targets,
                    )
                    results = orchestrator.sync_all()

                    success_count = sum(
                        1 for tr in results.values()
                        if isinstance(tr, dict) and "error" not in tr
                    )
                    print(f"  Synced {success_count}/{len(results)} targets.")
                    summary.record(changed, results)
                    # Update target known hashes after a successful sync
                    for p in _collect_target_paths(project_dir):
                        _target_known_hashes[str(p)] = _hash_file(p)
                except Exception as e:
                    print(f"  Sync error: {e}")
    finally:
        _clear_pid(project_dir)

    summary.print_summary()


def _timestamp() -> str:
    """Return HH:MM:SS timestamp string."""
    import datetime
    return datetime.datetime.now().strftime("%H:%M:%S")


if __name__ == "__main__":
    main()
