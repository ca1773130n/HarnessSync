from __future__ import annotations

"""Real-time drift alert watcher (item 3).

Runs a background thread that polls target harness config files for changes
not originating from HarnessSync and surfaces notifications with a /sync-restore
prompt. Solves silent config divergence that only surfaces as confusing behavior
differences between harnesses.

Usage:
    watcher = DriftWatcher(project_dir)
    watcher.start()          # start background polling
    watcher.stop()           # stop background polling

Or as a blocking watch mode:
    watcher.watch_blocking() # block until Ctrl-C
"""

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.state_manager import StateManager
from src.utils.hashing import hash_file_sha256
from src.utils.logger import Logger


# Default poll interval in seconds
DEFAULT_POLL_INTERVAL = 30.0

# Maximum number of alerts buffered before dropping oldest
_MAX_ALERT_HISTORY = 100


@dataclass
class DriftAlert:
    """A single drift detection event for one target file."""

    target: str
    file_path: str
    detected_at: str  # ISO 8601 timestamp
    stored_hash: str
    current_hash: str  # empty string means file was deleted

    @property
    def deleted(self) -> bool:
        return self.current_hash == ""

    def format(self) -> str:
        """Return a human-readable alert string."""
        ts = self.detected_at
        if self.deleted:
            return (
                f"[{ts}] DRIFT ALERT — {self.target}: {self.file_path} was DELETED\n"
                f"  Run /sync-restore to restore the file from the last sync."
            )
        return (
            f"[{ts}] DRIFT ALERT — {self.target}: {self.file_path} was modified outside HarnessSync\n"
            f"  Run /sync-restore to restore, or /sync to accept manual edits as new baseline."
        )


class DriftWatcher:
    """Background file watcher that detects manual config edits.

    Uses a daemon thread that polls file hashes at a configurable interval.
    Newly detected drift events are passed to the alert_callback and added
    to the internal alert history.

    Thread safety: alert_callback is called from the watcher thread.
    The caller is responsible for any cross-thread synchronization needed
    to display alerts in a UI context.
    """

    def __init__(
        self,
        project_dir: Path,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        alert_callback: Callable[[DriftAlert], None] | None = None,
        state_manager: StateManager | None = None,
    ):
        """Initialize the drift watcher.

        Args:
            project_dir: Project root directory (used to resolve relative paths).
            poll_interval: Seconds between each poll cycle.
            alert_callback: Optional function called with each DriftAlert when
                            drift is detected. Defaults to printing to stdout.
            state_manager: Optional StateManager for dependency injection.
        """
        self.project_dir = project_dir
        self.poll_interval = poll_interval
        self.alert_callback = alert_callback or _default_alert_callback
        self._state_manager = state_manager or StateManager()
        self._logger = Logger()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Tracks which (target, file_path) pairs have already been alerted
        # to avoid spam on every poll cycle
        self._alerted: set[tuple[str, str]] = set()
        self._alert_history: list[DriftAlert] = []
        self._history_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background watcher thread (non-blocking)."""
        if self._thread is not None and self._thread.is_alive():
            return  # Already running
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="harnesssync-drift-watcher",
            daemon=True,
        )
        self._thread.start()
        self._logger.debug("DriftWatcher started (poll interval: {}s)".format(self.poll_interval))

    def stop(self) -> None:
        """Signal the watcher thread to stop and wait for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_interval + 2)
            self._thread = None

    def is_running(self) -> bool:
        """Return True if the watcher thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def watch_blocking(self) -> None:
        """Run drift detection in the current thread until interrupted.

        Blocks until KeyboardInterrupt (Ctrl-C) or stop() is called from
        another thread. Intended for use from CLI watch-mode commands.
        """
        print("HarnessSync Drift Watcher — monitoring target configs...")
        print(f"Poll interval: {self.poll_interval}s  |  Press Ctrl-C to stop\n")
        try:
            while not self._stop_event.is_set():
                self._poll_once()
                self._stop_event.wait(timeout=self.poll_interval)
        except KeyboardInterrupt:
            print("\nDrift watcher stopped.")

    def get_alert_history(self) -> list[DriftAlert]:
        """Return a copy of the alert history (most-recent last)."""
        with self._history_lock:
            return list(self._alert_history)

    def reset_alert_for(self, target: str, file_path: str) -> None:
        """Allow re-alerting for a previously alerted (target, file) pair.

        Call this after the user resolves a drift (e.g. after /sync-restore)
        so that further edits to the same file generate new alerts.
        """
        key = (target, file_path)
        self._alerted.discard(key)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _poll_loop(self) -> None:
        """Background thread loop."""
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:
                self._logger.warn(f"DriftWatcher poll error: {exc}")
            self._stop_event.wait(timeout=self.poll_interval)

    def _poll_once(self) -> None:
        """Run a single drift-detection pass over all tracked targets."""
        state = self._state_manager.load_state()
        targets = state.get("targets", {})
        if not targets:
            return

        for target_name, target_data in targets.items():
            file_hashes: dict[str, str] = target_data.get("file_hashes", {})
            for file_path_str, stored_hash in file_hashes.items():
                key = (target_name, file_path_str)
                if key in self._alerted:
                    continue  # Already alerted, skip until reset

                current_hash = hash_file_sha256(Path(file_path_str))
                current_hash = current_hash or ""

                if current_hash == stored_hash:
                    continue  # No change

                alert = DriftAlert(
                    target=target_name,
                    file_path=file_path_str,
                    detected_at=datetime.now().isoformat(timespec="seconds"),
                    stored_hash=stored_hash,
                    current_hash=current_hash,
                )
                self._alerted.add(key)
                self._record_alert(alert)
                self.alert_callback(alert)

    def _record_alert(self, alert: DriftAlert) -> None:
        """Append alert to history, capping at _MAX_ALERT_HISTORY."""
        with self._history_lock:
            self._alert_history.append(alert)
            if len(self._alert_history) > _MAX_ALERT_HISTORY:
                self._alert_history = self._alert_history[-_MAX_ALERT_HISTORY:]


def _default_alert_callback(alert: DriftAlert) -> None:
    """Default alert handler: print to stdout."""
    print(alert.format())


def drift_summary(project_dir: Path, state_manager: StateManager | None = None) -> dict:
    """One-shot drift check across all tracked targets (no background thread).

    Returns a dict with structure:
        {
            "has_drift": bool,
            "targets": {
                "codex": {
                    "drifted_files": ["path/to/AGENTS.md"],
                    "deleted_files": [],
                    "clean": bool,
                },
                ...
            }
        }

    Useful for the /sync-status command to surface drift without starting
    a background watcher.
    """
    sm = state_manager or StateManager()
    state = sm.load_state()
    targets_state = state.get("targets", {})

    result: dict = {"has_drift": False, "targets": {}}

    for target_name, target_data in targets_state.items():
        file_hashes: dict[str, str] = target_data.get("file_hashes", {})
        drifted: list[str] = []
        deleted: list[str] = []

        for file_path_str, stored_hash in file_hashes.items():
            current_hash = hash_file_sha256(Path(file_path_str)) or ""
            if current_hash == stored_hash:
                continue
            if current_hash == "":
                deleted.append(file_path_str)
            else:
                drifted.append(file_path_str)

        has_target_drift = bool(drifted or deleted)
        if has_target_drift:
            result["has_drift"] = True

        result["targets"][target_name] = {
            "drifted_files": drifted,
            "deleted_files": deleted,
            "clean": not has_target_drift,
        }

    return result
