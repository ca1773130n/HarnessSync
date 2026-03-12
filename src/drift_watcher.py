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
        notify: bool = False,
        notify_cooldown_minutes: float = 60.0,
        slack_webhook_url: str | None = None,
    ):
        """Initialize the drift watcher.

        Args:
            project_dir: Project root directory (used to resolve relative paths).
            poll_interval: Seconds between each poll cycle.
            alert_callback: Optional function called with each DriftAlert when
                            drift is detected. Defaults to printing to stdout.
                            Takes precedence over the ``notify`` flag.
            state_manager: Optional StateManager for dependency injection.
            notify: If True and no alert_callback is provided, use the OS
                    notification callback that sends desktop banners (item 29).
            notify_cooldown_minutes: Minimum minutes between OS notifications
                                     for the same file (default: 60).
            slack_webhook_url: Optional Slack incoming webhook URL for posting
                               drift alerts. Also reads HARNESSSYNC_SLACK_WEBHOOK
                               env var if not provided explicitly.
        """
        self.project_dir = project_dir
        self.poll_interval = poll_interval
        if alert_callback is not None:
            self.alert_callback = alert_callback
        elif notify or slack_webhook_url:
            self.alert_callback = make_notifying_alert_callback(
                notify=notify,
                threshold_minutes=notify_cooldown_minutes,
                slack_webhook_url=slack_webhook_url,
            )
        else:
            self.alert_callback = _default_alert_callback
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


def send_os_notification(title: str, body: str) -> bool:
    """Send a native OS desktop notification (item 29).

    Attempts to deliver a desktop notification using the best available
    mechanism for the current platform:
      - macOS: ``osascript`` (AppleScript) via display notification
      - Linux: ``notify-send`` (libnotify, available in most distros)
      - Windows: ``PowerShell`` with BurntToast or basic balloon tip
      - Fallback: prints to stderr (no-op, never raises)

    CRITICAL: Never includes file content or hashes in the notification body —
    only filenames and harness names to avoid leaking sensitive config data.

    Args:
        title: Notification title (short, e.g. "HarnessSync Drift Detected").
        body: Notification body (e.g. "AGENTS.md was modified outside HarnessSync").

    Returns:
        True if notification was sent successfully, False otherwise.
    """
    import platform
    import subprocess
    import shutil

    system = platform.system()
    try:
        if system == "Darwin":
            # macOS: use AppleScript display notification
            script = f'display notification "{body}" with title "{title}"'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0

        elif system == "Linux":
            # Linux: use notify-send (libnotify)
            if shutil.which("notify-send"):
                result = subprocess.run(
                    ["notify-send", "--urgency=normal", title, body],
                    capture_output=True,
                    timeout=5,
                )
                return result.returncode == 0

        elif system == "Windows":
            # Windows: use PowerShell with basic balloon notification
            ps_script = (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "$n = New-Object System.Windows.Forms.NotifyIcon; "
                "$n.Icon = [System.Drawing.SystemIcons]::Information; "
                "$n.Visible = $true; "
                f"$n.ShowBalloonTip(5000, '{title}', '{body}', [System.Windows.Forms.ToolTipIcon]::Info); "
                "Start-Sleep -Seconds 6; "
                "$n.Dispose()"
            )
            result = subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0

    except Exception:
        pass  # Notifications are best-effort; never raise

    return False


def send_slack_notification(webhook_url: str, title: str, body: str) -> bool:
    """Send a drift alert to a Slack channel via incoming webhook (item 14).

    Posts a formatted Slack message using the Incoming Webhooks API.
    The message uses Slack's Block Kit for readable formatting.

    CRITICAL: Never includes file content or hash values in the payload —
    only filenames and harness names to avoid leaking sensitive config data.

    Args:
        webhook_url: Slack incoming webhook URL
                     (e.g. https://hooks.slack.com/services/T.../B.../...).
        title: Notification title (e.g. "HarnessSync Drift Detected").
        body: Notification body text.

    Returns:
        True if the notification was posted successfully, False otherwise.
    """
    import json as _json
    import urllib.request as _urllib_request

    if not webhook_url or not webhook_url.startswith("https://"):
        return False

    payload = {
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": title, "emoji": True},
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": body},
            },
        ]
    }

    try:
        data = _json.dumps(payload).encode("utf-8")
        req = _urllib_request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urllib_request.urlopen(req, timeout=5):
            pass
        return True
    except Exception:
        return False


def make_notifying_alert_callback(
    notify: bool = True,
    threshold_minutes: float = 60.0,
    slack_webhook_url: str | None = None,
) -> "Callable[[DriftAlert], None]":
    """Create an alert callback that sends OS notifications for drift (item 29).

    The callback prints to stdout AND sends a native OS notification. A
    cooldown threshold prevents notification spam when the same file is
    detected as drifted across multiple poll cycles.

    When ``slack_webhook_url`` is provided, also posts to Slack. The Slack
    webhook URL can also be set via the HARNESSSYNC_SLACK_WEBHOOK env var.

    Args:
        notify: If False, OS notifications are disabled (stdout only).
        threshold_minutes: Minimum minutes between notifications for the
                           same (target, file) pair. Default: 60 minutes.
        slack_webhook_url: Optional Slack incoming webhook URL. Falls back to
                           the HARNESSSYNC_SLACK_WEBHOOK environment variable.

    Returns:
        Alert callback function compatible with DriftWatcher.alert_callback.
    """
    import os as _os
    from typing import Callable

    # Resolve Slack webhook: explicit arg takes precedence over env var
    _slack_url = slack_webhook_url or _os.environ.get("HARNESSSYNC_SLACK_WEBHOOK", "").strip()

    last_notified: dict[tuple[str, str], float] = {}

    def _callback(alert: DriftAlert) -> None:
        print(alert.format())

        if not notify and not _slack_url:
            return

        key = (alert.target, alert.file_path)
        import time as _time
        now = _time.time()
        last = last_notified.get(key, 0.0)
        if now - last < threshold_minutes * 60:
            return  # Cooldown period active

        title = "HarnessSync — Config Drift Detected"
        import os
        filename = os.path.basename(alert.file_path)
        if alert.deleted:
            body = f"{alert.target}: {filename} was deleted outside HarnessSync."
        else:
            body = f"{alert.target}: {filename} was modified outside HarnessSync."

        sent = False
        if notify:
            sent = send_os_notification(title, body)

        # Also post to Slack if webhook configured
        if _slack_url:
            slack_body = (
                f"*Target:* `{alert.target}`\n"
                f"*File:* `{filename}`\n"
                f"*Status:* {'deleted' if alert.deleted else 'modified outside HarnessSync'}\n"
                f"*Time:* {alert.detected_at}\n"
                f"Run `/sync` to re-sync or `/sync-restore` to revert."
            )
            send_slack_notification(_slack_url, title, slack_body)
            sent = True

        if sent:
            last_notified[key] = now

    return _callback


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
