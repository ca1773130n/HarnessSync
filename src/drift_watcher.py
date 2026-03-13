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

import difflib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from difflib import unified_diff

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


@dataclass
class DriftRootCause:
    """Detailed root cause analysis for a drift event."""

    alert: DriftAlert
    lines_added: list[tuple[int, str]]    # (line_num, text) new lines
    lines_removed: list[tuple[int, str]]  # (line_num, text) removed lines
    lines_modified: int                    # count of changed lines
    likely_cause: str                      # human-readable explanation
    diff_text: str                         # unified diff string
    suggested_action: str                  # what to do about it


# Heuristic patterns for root-cause inference
_VERSION_PATTERNS = (
    "version:",
    "\"version\"",
    "# version",
    "v0.", "v1.", "v2.", "v3.", "v4.", "v5.", "v6.", "v7.", "v8.", "v9.",
)
_ENV_VAR_PATTERNS = (
    "=",          # KEY=VALUE lines
    "export ",
    "api_key",
    "api-key",
    "token",
    "secret",
    "password",
    "passwd",
)


def analyze_drift_root_cause(
    alert: DriftAlert,
    stored_content: str,
    current_content: str,
) -> DriftRootCause:
    """Generate a detailed root-cause analysis for a drift event.

    Compares stored_content (what HarnessSync last wrote) with current_content
    (what the file contains now) to explain what changed and why it likely
    drifted, plus what the user should do about it.

    Args:
        alert: The DriftAlert that triggered this analysis.
        stored_content: File content at last HarnessSync write (source of truth).
        current_content: Current on-disk content of the drifted file.

    Returns:
        DriftRootCause with diff, line counts, likely cause, and action.
    """
    stored_lines = stored_content.splitlines(keepends=True)
    current_lines = current_content.splitlines(keepends=True)

    file_label = alert.file_path
    diff_lines = list(
        unified_diff(
            stored_lines,
            current_lines,
            fromfile=f"harnesssync/{file_label}",
            tofile=f"current/{file_label}",
            lineterm="",
        )
    )
    diff_text = "\n".join(diff_lines)

    # Collect added/removed lines with line numbers
    added: list[tuple[int, str]] = []
    removed: list[tuple[int, str]] = []
    current_line_num = 0
    stored_line_num = 0

    for raw_line in diff_lines:
        if raw_line.startswith("@@"):
            # Parse hunk header to reset counters: @@ -a,b +c,d @@
            try:
                parts = raw_line.split(" ")
                plus_part = next(p for p in parts if p.startswith("+"))
                current_line_num = int(plus_part[1:].split(",")[0]) - 1
                minus_part = next(p for p in parts if p.startswith("-"))
                stored_line_num = int(minus_part[1:].split(",")[0]) - 1
            except (ValueError, StopIteration):
                pass
            continue
        if raw_line.startswith("---") or raw_line.startswith("+++"):
            continue
        if raw_line.startswith("+"):
            current_line_num += 1
            added.append((current_line_num, raw_line[1:].rstrip("\n")))
        elif raw_line.startswith("-"):
            stored_line_num += 1
            removed.append((stored_line_num, raw_line[1:].rstrip("\n")))
        else:
            current_line_num += 1
            stored_line_num += 1

    # Estimate modified lines as min(added, removed) — paired changes
    lines_modified = min(len(added), len(removed))

    # ------------------------------------------------------------------ #
    # Heuristic root-cause inference                                       #
    # ------------------------------------------------------------------ #
    all_changed_text = " ".join(t for _, t in added + removed).lower()

    # 1. Only whitespace changed
    if stored_content.strip() == current_content.strip() and stored_content != current_content:
        likely_cause = "Whitespace normalization (trailing spaces, newlines)"
        suggested_action = "Run /sync to restore canonical formatting"

    # 2. Version strings changed (self-update)
    elif any(pat.lower() in all_changed_text for pat in _VERSION_PATTERNS) and (
        added and removed
    ):
        likely_cause = "Harness self-update modified config file"
        suggested_action = "Run /sync-check to verify harness update compatibility"

    # 3. Environment variable / secret values changed
    elif any(pat.lower() in all_changed_text for pat in _ENV_VAR_PATTERNS) and (
        added and removed
    ):
        likely_cause = "Environment variable update (possible secret rotation)"
        suggested_action = "Run /sync-diff to review changes, then /sync to restore"

    # 4. Pure addition (no lines removed)
    elif added and not removed:
        likely_cause = "Manual addition of new config section"
        suggested_action = "Run /sync-merge to incorporate manual additions, or /sync to overwrite"

    # 5. Pure deletion (no lines added)
    elif removed and not added:
        likely_cause = "Manual deletion of synced content"
        suggested_action = "Run /sync to restore deleted content"

    # 6. Default — mixed manual edit
    else:
        likely_cause = "Manual edit to synced config file"
        suggested_action = "Run /sync-diff to review changes, then /sync to restore"

    return DriftRootCause(
        alert=alert,
        lines_added=added,
        lines_removed=removed,
        lines_modified=lines_modified,
        likely_cause=likely_cause,
        diff_text=diff_text,
        suggested_action=suggested_action,
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

    def get_status_summary(self) -> dict:
        """Return a compact status dict for the watcher (suitable for status bars).

        Returns:
            Dict with keys:
                - running: bool — whether the watcher thread is alive
                - poll_interval: float — configured poll interval in seconds
                - alert_count: int — total alerts fired this session
                - last_alert_at: str | None — ISO timestamp of last alert (or None)
                - targets_drifted: list[str] — target names with active drift alerts
        """
        with self._history_lock:
            history = list(self._alert_history)

        last_alert_at: str | None = history[-1].detected_at if history else None
        targets_drifted = sorted({a.target for a in history})

        return {
            "running": self.is_running(),
            "poll_interval": self.poll_interval,
            "alert_count": len(history),
            "last_alert_at": last_alert_at,
            "targets_drifted": targets_drifted,
        }

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

    def get_root_cause(self, alert: DriftAlert) -> DriftRootCause | None:
        """Return a detailed root-cause analysis for a drift alert.

        Reads the stored (source-of-truth) content from the HarnessSync state
        and the current on-disk content of the drifted file, then delegates to
        :func:`analyze_drift_root_cause` for diff generation and heuristic
        cause inference.

        The "stored" content is the project-level source file that HarnessSync
        last synced FROM (e.g. CLAUDE.md in project_dir). The state manager's
        file_hashes track paths of TARGET files; to retrieve what was written we
        look up the source file in project_dir by matching the filename.

        Args:
            alert: A DriftAlert previously emitted by this watcher.

        Returns:
            DriftRootCause with diff and explanation, or None if either content
            is unavailable (file deleted, source not found, I/O error).
        """
        if alert.deleted:
            # No current content to diff against
            return None

        # Read current on-disk content of the drifted file
        try:
            current_content = Path(alert.file_path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        # Retrieve stored content from state: the state stores the *target* file
        # path and its hash, but not the content.  We recover the source content
        # from the project-dir file that was originally synced to this target.
        # Strategy: look for a file with the same basename in project_dir.
        stored_content: str | None = None
        target_filename = Path(alert.file_path).name

        # Try the project_dir source file first (most common case)
        candidate = self.project_dir / target_filename
        if candidate.is_file():
            try:
                stored_content = candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                stored_content = None

        # Fallback: search one level deep in project_dir for the filename
        if stored_content is None:
            for child in self.project_dir.rglob(target_filename):
                if child.is_file() and child != Path(alert.file_path):
                    try:
                        stored_content = child.read_text(encoding="utf-8", errors="replace")
                        break
                    except OSError:
                        continue

        if stored_content is None:
            return None

        return analyze_drift_root_cause(alert, stored_content, current_content)

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
    """Default alert handler: print to stdout with terminal bell."""
    print(alert.format())
    _ring_terminal_bell()


def _ring_terminal_bell() -> None:
    """Emit a terminal bell character (\x07) to the controlling TTY.

    This triggers the terminal emulator's audio or visual bell, giving
    immediate tactile feedback when drift is detected — even if the user
    is not watching this terminal window.

    Writes directly to /dev/tty so the bell fires even when stdout is
    redirected.  Silently suppressed if /dev/tty is unavailable (e.g.
    inside a CI runner or non-interactive shell).
    """
    import sys as _sys

    try:
        # Prefer direct TTY write so the bell fires even with piped stdout
        with open("/dev/tty", "w") as tty:
            tty.write("\x07")
            tty.flush()
    except OSError:
        # Fallback: write to stderr if stdout/stderr is a real TTY
        if hasattr(_sys.stderr, "isatty") and _sys.stderr.isatty():
            try:
                _sys.stderr.write("\x07")
                _sys.stderr.flush()
            except OSError:
                pass


def send_os_notification(title: str, body: str) -> bool:
    """Send a native OS desktop notification (item 29).

    Delegates to :class:`src.desktop_notifier.DesktopNotifier` which handles
    macOS (osascript), Linux (notify-send), and graceful fallback.

    CRITICAL: Never includes file content or hashes in the notification body —
    only filenames and harness names to avoid leaking sensitive config data.

    Args:
        title: Notification title (short, e.g. "HarnessSync Drift Detected").
        body: Notification body (e.g. "AGENTS.md was modified outside HarnessSync").

    Returns:
        True if notification was sent successfully, False otherwise.
    """
    try:
        from src.desktop_notifier import DesktopNotifier
        notifier = DesktopNotifier(enabled=True)
        return notifier._send(title, body)
    except Exception:
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


def format_status_line(watcher: "DriftWatcher | None" = None, status: dict | None = None) -> str:
    """Render a compact one-line watcher status indicator for terminal display.

    Can be used in shell prompts, VS Code status bars, or watch-mode headers.

    Args:
        watcher: Live DriftWatcher instance (preferred).
        status:  Pre-built status dict from get_status_summary() (alternative
                 when a watcher instance is unavailable).

    Returns:
        A single-line string such as::

            [HS WATCH ◉ active | poll: 30s | alerts: 0]
            [HS WATCH ○ stopped | last alert: codex 2m ago]

    Examples::

        watcher = DriftWatcher(project_dir)
        watcher.start()
        print(format_status_line(watcher))
        # → [HS WATCH ◉ active | poll: 30s | alerts: 0]
    """
    if watcher is not None:
        s = watcher.get_status_summary()
    elif status is not None:
        s = status
    else:
        return "[HS WATCH ○ not started]"

    running = s.get("running", False)
    poll = s.get("poll_interval", 30.0)
    alert_count = s.get("alert_count", 0)
    last_alert_at = s.get("last_alert_at")
    targets_drifted = s.get("targets_drifted", [])

    state_icon = "◉" if running else "○"
    state_label = "active" if running else "stopped"
    poll_str = f"{int(poll)}s" if poll < 60 else f"{int(poll // 60)}m"

    parts = [f"HS WATCH {state_icon} {state_label}", f"poll: {poll_str}"]

    if alert_count == 0:
        parts.append("alerts: 0")
    else:
        drift_str = f"drift: {', '.join(targets_drifted)}" if targets_drifted else ""
        parts.append(f"alerts: {alert_count}")
        if drift_str:
            parts.append(drift_str)

    if last_alert_at and not running:
        # Show relative time of last alert when watcher is stopped
        try:
            last_dt = datetime.fromisoformat(last_alert_at)
            delta_s = (datetime.now(tz=last_dt.tzinfo) - last_dt).total_seconds()
            if delta_s < 60:
                rel = f"{int(delta_s)}s ago"
            elif delta_s < 3600:
                rel = f"{int(delta_s // 60)}m ago"
            else:
                rel = f"{int(delta_s // 3600)}h ago"
            parts.append(f"last alert: {rel}")
        except (ValueError, TypeError):
            pass

    return "[" + " | ".join(parts) + "]"


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
