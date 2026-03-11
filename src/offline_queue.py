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

# Target config directories (to check availability)
_TARGET_CONFIG_DIRS: dict[str, Path] = {
    "codex":    Path.home() / ".codex",
    "gemini":   Path.home() / ".gemini",
    "opencode": Path.home() / ".config" / "opencode",
    "windsurf": Path.home() / ".codeium" / "windsurf",
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
    # Project-scoped targets: check if project_dir is writable
    project_scoped = {"cursor", "aider"}
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

        Args:
            available_check: If False, replay all entries regardless of availability
                             (useful for forced replay via /sync --replay-queue).

        Returns:
            Dict mapping queue_key -> "replayed" | "still_unavailable" | "error: <msg>".
        """
        queue = self._load()
        results: dict[str, str] = {}
        remaining: list[dict] = []

        for entry in queue:
            key = entry.get("key", "?")
            target = entry.get("target", "")
            project_dir_str = entry.get("project_dir") or os.getcwd()
            project_dir = Path(project_dir_str)

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
                remaining.append(entry)  # Keep for next retry

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
            lines.append(
                f"  - [{e.get('target', '?')}] {e.get('reason', '')} "
                f"(queued {e.get('queued_at', '?')})"
                + (f" project={e.get('project_dir', '')}" if e.get('project_dir') else "")
            )
        lines.append("\nRun /sync to replay when targets are available.")
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
