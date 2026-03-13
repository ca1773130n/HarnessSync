from __future__ import annotations

"""Offline sync queue for HarnessSync.

When a target harness config directory is unavailable (mounted drive offline,
remote filesystem disconnected), sync operations are queued and replayed
automatically when the target becomes available again.

Queue entries are persisted to ~/.harnesssync/offline_queue.json.
Each entry records: target name, serialized adapter data snapshot, reason
the original sync was deferred, and the timestamp.

Workflow:
1. Orchestrator calls ``is_target_available(target, project_dir)`` before sync.
2. If unavailable, orchestrator calls ``enqueue(target, source_data, reason)``
   instead of running the adapter.
3. At session start (or on next sync), ``replay_pending()`` re-runs deferred syncs
   for targets that are now reachable.

Availability check:
- For targets with a known config directory (codex ~/.codex, gemini ~/.gemini, etc.)
  we check if the directory is accessible (os.access).
- For project-scoped targets, we check if the project_dir is accessible.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from src.utils.paths import ensure_dir


# Queue storage location
_QUEUE_DIR = Path.home() / ".harnesssync"
_QUEUE_FILE = _QUEUE_DIR / "offline_queue.json"

# Retry limits and backoff constants
MAX_RETRY_ATTEMPTS = 5          # Drop entry after this many consecutive failures
_BACKOFF_BASE_SECONDS = 60      # First retry: 1 minute
_BACKOFF_MAX_SECONDS = 3600     # Cap backoff at 1 hour

# Target config directories (to check availability).
# Each entry maps a canonical target name to its user-level config home.
# Targets that live inside the project directory are handled separately
# via the project_scoped set in is_target_available().
_TARGET_CONFIG_DIRS: dict[str, Path] = {
    "codex":    Path.home() / ".codex",
    "gemini":   Path.home() / ".gemini",
    "opencode": Path.home() / ".config" / "opencode",
    "windsurf": Path.home() / ".codeium" / "windsurf",
    # Cursor stores user-level MCP config in ~/.cursor; project rules live in .cursor/
    "cursor":   Path.home() / ".cursor",
    # Aider keeps its config in ~/.aider
    "aider":    Path.home() / ".aider",
    # Cline (VSCode extension) uses ~/.vscode or .roo at project level
    "cline":    Path.home() / ".vscode",
    # Continue.dev stores user config in ~/.continue
    "continue": Path.home() / ".continue",
    # Zed stores user settings in ~/Library/Application Support/Zed on macOS,
    # or ~/.config/zed on Linux
    "zed":      (
        Path.home() / "Library" / "Application Support" / "Zed"
        if (Path.home() / "Library").exists()
        else Path.home() / ".config" / "zed"
    ),
    # Neovim: check for avante.nvim or codecompanion.nvim config in ~/.config/nvim
    "neovim":   Path.home() / ".config" / "nvim",
}


def is_target_available(target: str, project_dir: Path) -> bool:
    """Check if a sync target's config location is accessible.

    Checks that the target's expected config directory (or the project directory
    for project-scoped targets) is readable/writable on the filesystem.

    Args:
        target: Target name ("codex", "gemini", "cursor", etc.)
        project_dir: Project root directory.

    Returns:
        True if the target is accessible, False if the path is unavailable
        (e.g., unmounted drive, disconnected network share).
    """
    # Project-scoped targets: these store their config inside the project directory
    # rather than a user-level config home, so availability is tied to project_dir.
    project_scoped = {"cursor", "aider", "cline", "continue", "zed"}
    if target in project_scoped:
        try:
            return os.access(project_dir, os.W_OK)
        except OSError:
            return False

    # User-level targets: check if the config home directory is accessible
    config_dir = _TARGET_CONFIG_DIRS.get(target)
    if config_dir:
        parent = config_dir.parent
        try:
            # Directory doesn't need to exist yet — but its parent must be accessible
            return os.access(parent, os.R_OK)
        except OSError:
            return False

    # Unknown target — assume available
    return True


class OfflineQueue:
    """Persistent queue for deferred sync operations.

    Stores queued syncs as JSON so they survive session restarts.
    Each entry contains enough information to replay the sync when
    the target becomes available.
    """

    def __init__(self, queue_file: Path | None = None):
        """Initialize offline queue.

        Args:
            queue_file: Path to queue JSON file (default: ~/.harnesssync/offline_queue.json).
        """
        self._path = queue_file or _QUEUE_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(
        self,
        target: str,
        source_snapshot: dict,
        reason: str = "target unavailable",
        project_dir: str | None = None,
    ) -> None:
        """Add a deferred sync operation to the queue.

        If an entry for the same target+project already exists, it is replaced
        with the newer source snapshot (last-write-wins per target slot).

        Args:
            target: Target harness name.
            source_snapshot: Serialisable subset of adapter_data for this sync.
                             Only JSON-safe values are stored (paths removed).
            reason: Human-readable reason for deferral.
            project_dir: Project directory path (stored for replay).
        """
        queue = self._load()

        # Deduplicate: one pending entry per (target, project_dir) pair
        key = f"{target}::{project_dir or ''}"
        entry = {
            "key": key,
            "target": target,
            "project_dir": project_dir,
            "reason": reason,
            "queued_at": datetime.now().isoformat(timespec="seconds"),
            "source_snapshot": _serialise_snapshot(source_snapshot),
            "retry_count": 0,
            "next_retry_at": None,
        }

        # Remove older entry for same key (replace with fresh snapshot)
        queue = [e for e in queue if e.get("key") != key]
        queue.append(entry)

        self._save(queue)

    def dequeue(self, target: str, project_dir: str | None = None) -> list[dict]:
        """Remove and return all queued entries for target+project.

        Args:
            target: Target name to dequeue.
            project_dir: Project directory filter (None = all projects).

        Returns:
            List of queue entries that were removed.
        """
        queue = self._load()
        key = f"{target}::{project_dir or ''}"

        matching = [e for e in queue if e.get("key") == key]
        remaining = [e for e in queue if e.get("key") != key]
        self._save(remaining)
        return matching

    def list_pending(self) -> list[dict]:
        """Return all pending queue entries (read-only).

        Returns:
            List of dicts with keys: target, project_dir, reason, queued_at.
        """
        return list(self._load())

    def replay_pending(
        self,
        available_check: bool = True,
    ) -> dict[str, str]:
        """Replay deferred syncs for targets that are now available.

        Iterates the queue, checks availability for each entry, and runs
        SyncOrchestrator for entries whose target is now reachable.

        Entries that fail are kept with an incremented retry_count and a
        computed next_retry_at timestamp (exponential backoff). Entries that
        exceed MAX_RETRY_ATTEMPTS are dropped from the queue with an
        "exhausted" result status.

        Args:
            available_check: If False, replay all entries regardless of availability
                             (useful for forced replay via /sync --replay-queue).

        Returns:
            Dict mapping queue_key -> "replayed" | "still_unavailable" |
            "backoff" | "exhausted" | "error: <msg>".
        """
        queue = self._load()
        results: dict[str, str] = {}
        remaining: list[dict] = []
        now_iso = datetime.now().isoformat(timespec="seconds")
        now_ts = datetime.now().timestamp()

        for entry in queue:
            key = entry.get("key", "?")
            target = entry.get("target", "")
            project_dir_str = entry.get("project_dir") or os.getcwd()
            project_dir = Path(project_dir_str)
            retry_count = entry.get("retry_count", 0)

            # Enforce max retry limit — silently drop exhausted entries
            if retry_count >= MAX_RETRY_ATTEMPTS:
                results[key] = "exhausted"
                continue  # Drop from queue

            # Skip entries still in backoff window (unless forced)
            if available_check:
                next_retry = entry.get("next_retry_at")
                if next_retry:
                    try:
                        next_ts = datetime.fromisoformat(next_retry).timestamp()
                        if now_ts < next_ts:
                            results[key] = "backoff"
                            remaining.append(entry)
                            continue
                    except ValueError:
                        pass  # Malformed timestamp — proceed anyway

            if available_check and not is_target_available(target, project_dir):
                results[key] = "still_unavailable"
                remaining.append(entry)
                continue

            # Attempt replay
            try:
                _replay_entry(entry)
                results[key] = "replayed"
                # Entry consumed — do NOT add back to remaining
            except Exception as exc:
                results[key] = f"error: {exc}"
                # Increment retry_count and compute next backoff window
                new_retry_count = retry_count + 1
                backoff_secs = min(
                    _BACKOFF_BASE_SECONDS * (2 ** (new_retry_count - 1)),
                    _BACKOFF_MAX_SECONDS,
                )
                from datetime import timedelta
                next_retry_dt = datetime.now() + timedelta(seconds=backoff_secs)
                updated_entry = dict(entry)
                updated_entry["retry_count"] = new_retry_count
                updated_entry["next_retry_at"] = next_retry_dt.isoformat(timespec="seconds")
                updated_entry["last_error"] = str(exc)
                updated_entry["last_attempt_at"] = now_iso
                remaining.append(updated_entry)

        self._save(remaining)
        return results

    def clear(self) -> int:
        """Clear all pending entries.

        Returns:
            Number of entries cleared.
        """
        queue = self._load()
        count = len(queue)
        self._save([])
        return count

    def format_summary(self) -> str:
        """Format human-readable summary of pending queue entries.

        Returns:
            Formatted string listing all pending entries, or a 'queue empty' message.
        """
        entries = self.list_pending()
        if not entries:
            return "Offline sync queue: empty"

        lines = [f"Offline sync queue: {len(entries)} pending entry/entries"]
        for e in entries:
            retry_count = e.get("retry_count", 0)
            retries_left = MAX_RETRY_ATTEMPTS - retry_count
            retry_info = f" [attempt {retry_count + 1}/{MAX_RETRY_ATTEMPTS}]" if retry_count > 0 else ""
            next_retry = e.get("next_retry_at")
            backoff_info = f" retry after {next_retry}" if next_retry else ""
            last_err = e.get("last_error")
            err_info = f" last_err={last_err!r}" if last_err else ""
            lines.append(
                f"  - [{e.get('target', '?')}] {e.get('reason', '')} "
                f"(queued {e.get('queued_at', '?')})"
                + (f" project={e.get('project_dir', '')}" if e.get('project_dir') else "")
                + retry_info + backoff_info + err_info
            )
        lines.append("\nRun /sync to replay when targets are available.")
        return "\n".join(lines)

    def clear_exhausted(self) -> int:
        """Remove queue entries that have exceeded the retry limit.

        These entries would never be retried anyway (replay_pending drops them
        silently), but clearing them explicitly keeps the queue file tidy and
        surfaces to users that some syncs were permanently abandoned.

        Returns:
            Number of exhausted entries removed.
        """
        queue = self._load()
        live = [e for e in queue if e.get("retry_count", 0) < MAX_RETRY_ATTEMPTS]
        removed = len(queue) - len(live)
        if removed:
            self._save(live)
        return removed

    def get_next_retry_time(self, target: str, project_dir: str | None = None) -> str | None:
        """Return the ISO timestamp when a queued target will next be retried.

        Useful for status displays that want to tell the user 'Codex sync will
        retry at 14:32' rather than just 'pending'.

        Args:
            target: Target harness name.
            project_dir: Project directory path (None = any project).

        Returns:
            ISO timestamp string, or None if no backoff window is set (i.e., the
            entry will be retried on the next /sync invocation).
        """
        key = f"{target}::{project_dir or ''}"
        for entry in self._load():
            if entry.get("key") == key:
                return entry.get("next_retry_at")
        return None

    def format_pending(self) -> str:
        """Format human-readable table of pending queue entries.

        More structured than format_summary() — suitable for display in
        /sync-status and /sync --show-queue. Shows target, reason, age,
        retry count, and estimated next-retry time for each entry.

        Returns:
            Formatted table string, or a one-liner if the queue is empty.
        """
        entries = self.list_pending()
        if not entries:
            return "Offline sync queue: empty"

        from datetime import datetime as _dt

        now = _dt.now()
        lines = [f"Offline Sync Queue  ({len(entries)} pending)", "─" * 60]
        lines.append(f"  {'Target':<12} {'Age':>6}  {'Retries':>8}  {'Next Retry':<20}  Reason")
        lines.append(f"  {'─'*12} {'─'*6}  {'─'*8}  {'─'*20}  {'─'*20}")

        for entry in entries:
            target = entry.get("target", "?")
            reason = entry.get("reason", "")[:30]
            retry_count = entry.get("retry_count", 0)
            retries_str = f"{retry_count}/{MAX_RETRY_ATTEMPTS}"
            next_retry = entry.get("next_retry_at", "")
            if next_retry:
                try:
                    nr_dt = _dt.fromisoformat(next_retry)
                    delta_mins = int((nr_dt - now).total_seconds() / 60)
                    if delta_mins > 0:
                        next_retry_str = f"in {delta_mins}m ({nr_dt.strftime('%H:%M')})"
                    else:
                        next_retry_str = "ready"
                except ValueError:
                    next_retry_str = next_retry[:20]
            else:
                next_retry_str = "ready"

            queued_at = entry.get("queued_at", "")
            age_str = ""
            if queued_at:
                try:
                    q_dt = _dt.fromisoformat(queued_at)
                    age_secs = int((now - q_dt).total_seconds())
                    if age_secs < 3600:
                        age_str = f"{age_secs // 60}m"
                    elif age_secs < 86400:
                        age_str = f"{age_secs // 3600}h"
                    else:
                        age_str = f"{age_secs // 86400}d"
                except ValueError:
                    age_str = "?"

            lines.append(
                f"  {target:<12} {age_str:>6}  {retries_str:>8}  {next_retry_str:<20}  {reason}"
            )

            if entry.get("last_error"):
                lines.append(f"    └─ last error: {entry['last_error'][:60]}")

        lines.append("─" * 60)
        lines.append("Run /sync to replay queued syncs when targets become available.")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load(self) -> list[dict]:
        """Load queue from JSON file."""
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save(self, queue: list[dict]) -> None:
        """Atomically save queue to JSON file."""
        ensure_dir(self._path.parent)
        fd, tmp_path = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(queue, f, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _serialise_snapshot(source_snapshot: dict) -> dict:
    """Convert source_data snapshot to a JSON-safe dict.

    Strips non-serialisable values (Paths, objects) and keeps only
    the fields that can be stored as plain JSON and replayed later.

    Args:
        source_snapshot: Raw adapter_data dict.

    Returns:
        JSON-safe dict.
    """
    safe: dict = {}
    for k, v in source_snapshot.items():
        try:
            json.dumps(v)  # Test serialisability
            safe[k] = v
        except (TypeError, ValueError):
            # Convert non-serialisable values to strings
            safe[k] = str(v)
    return safe


def _replay_entry(entry: dict) -> None:
    """Replay a single queue entry via SyncOrchestrator.

    Args:
        entry: Queue entry dict.

    Raises:
        Exception: If replay fails (caller keeps entry in queue).
    """
    from src.orchestrator import SyncOrchestrator

    project_dir = Path(entry.get("project_dir") or os.getcwd())
    orchestrator = SyncOrchestrator(project_dir=project_dir)
    orchestrator.sync_all()
