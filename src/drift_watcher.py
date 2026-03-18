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
from dataclasses import dataclass
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
        discord_webhook_url: str | None = None,
        generic_webhook_url: str | None = None,
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
                    notification callback that sends desktop banners.
            notify_cooldown_minutes: Minimum minutes between OS notifications
                                     for the same file (default: 60).
            slack_webhook_url: Optional Slack incoming webhook URL. Also reads
                               HARNESSSYNC_SLACK_WEBHOOK env var.
            discord_webhook_url: Optional Discord webhook URL. Also reads
                                 HARNESSSYNC_DISCORD_WEBHOOK env var.
            generic_webhook_url: Optional generic HTTPS webhook URL. Also reads
                                 HARNESSSYNC_WEBHOOK_URL env var.
        """
        self.project_dir = project_dir
        self.poll_interval = poll_interval
        has_webhook = slack_webhook_url or discord_webhook_url or generic_webhook_url
        if alert_callback is not None:
            self.alert_callback = alert_callback
        elif notify or has_webhook:
            self.alert_callback = make_notifying_alert_callback(
                notify=notify,
                threshold_minutes=notify_cooldown_minutes,
                slack_webhook_url=slack_webhook_url,
                discord_webhook_url=discord_webhook_url,
                generic_webhook_url=generic_webhook_url,
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


def send_discord_notification(webhook_url: str, title: str, body: str) -> bool:
    """Send a drift alert to a Discord channel via incoming webhook (item 11).

    Posts a Discord embed message via Discord's incoming webhook API.
    Uses Discord's embed format for rich, readable notifications.

    CRITICAL: Never includes file content or hash values — only filenames
    and harness names to avoid leaking sensitive config data.

    Args:
        webhook_url: Discord webhook URL
                     (e.g. https://discord.com/api/webhooks/<id>/<token>).
        title: Embed title.
        body: Embed description text.

    Returns:
        True if the notification was posted successfully, False otherwise.
    """
    import json as _json
    import urllib.request as _urllib_request

    if not webhook_url or not webhook_url.startswith("https://"):
        return False

    payload = {
        "embeds": [
            {
                "title": title,
                "description": body,
                "color": 0xF85149,  # red — indicates drift/warning
                "footer": {"text": "HarnessSync"},
            }
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


def send_generic_webhook_notification(
    webhook_url: str,
    event: str,
    target: str,
    filename: str,
    detected_at: str,
    extra: dict | None = None,
) -> bool:
    """Send a structured JSON payload to a generic webhook endpoint (item 11).

    Posts a JSON body that any webhook consumer (Zapier, n8n, custom server)
    can parse. The payload is intentionally minimal: no file contents, no
    hashes — only event metadata.

    Payload schema::

        {
          "source": "harnesssync",
          "event": "drift_detected" | "sync_complete" | "sync_failed",
          "target": "<harness name>",
          "filename": "<config filename>",
          "detected_at": "<ISO 8601>",
          "extra": {}
        }

    Args:
        webhook_url: Any HTTPS endpoint that accepts POST with JSON body.
        event: Event type string (e.g. "drift_detected").
        target: Harness name (e.g. "cursor").
        filename: Config filename that changed (no path, no content).
        detected_at: ISO 8601 timestamp string.
        extra: Optional additional key-value metadata (values must be JSON-safe).

    Returns:
        True if the POST succeeded (2xx response), False otherwise.
    """
    import json as _json
    import urllib.request as _urllib_request

    if not webhook_url or not webhook_url.startswith("https://"):
        return False

    payload = {
        "source": "harnesssync",
        "event": event,
        "target": target,
        "filename": filename,
        "detected_at": detected_at,
        "extra": extra or {},
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
    discord_webhook_url: str | None = None,
    generic_webhook_url: str | None = None,
) -> "Callable[[DriftAlert], None]":
    """Create an alert callback that sends OS notifications for drift (item 11).

    The callback prints to stdout AND sends a native OS notification. A
    cooldown threshold prevents notification spam when the same file is
    detected as drifted across multiple poll cycles.

    Supports Slack, Discord, and generic webhooks — all resolved from
    explicit args first, then environment variables.

    Args:
        notify: If False, OS notifications are disabled (stdout only).
        threshold_minutes: Minimum minutes between notifications for the
                           same (target, file) pair. Default: 60 minutes.
        slack_webhook_url: Optional Slack incoming webhook URL. Falls back to
                           the HARNESSSYNC_SLACK_WEBHOOK environment variable.
        discord_webhook_url: Optional Discord webhook URL. Falls back to
                             HARNESSSYNC_DISCORD_WEBHOOK env var.
        generic_webhook_url: Optional generic HTTPS webhook URL. Falls back to
                             HARNESSSYNC_WEBHOOK_URL env var.

    Returns:
        Alert callback function compatible with DriftWatcher.alert_callback.
    """
    import os as _os

    # Resolve all webhook URLs: explicit arg > env var
    _slack_url = slack_webhook_url or _os.environ.get("HARNESSSYNC_SLACK_WEBHOOK", "").strip()
    _discord_url = discord_webhook_url or _os.environ.get("HARNESSSYNC_DISCORD_WEBHOOK", "").strip()
    _generic_url = generic_webhook_url or _os.environ.get("HARNESSSYNC_WEBHOOK_URL", "").strip()

    last_notified: dict[tuple[str, str], float] = {}

    def _callback(alert: DriftAlert) -> None:
        print(alert.format())

        has_any_channel = notify or _slack_url or _discord_url or _generic_url
        if not has_any_channel:
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
        status_verb = "deleted" if alert.deleted else "modified outside HarnessSync"
        body = f"{alert.target}: {filename} was {status_verb}."

        sent = False
        if notify:
            try:
                from src.desktop_notifier import DesktopNotifier
                notifier = DesktopNotifier(enabled=True)
                sent = notifier.notify_drift_detected(
                    target=alert.target,
                    drifted_files=[alert.file_path],
                )
            except Exception:
                sent = send_os_notification(title, body)

        # Slack
        if _slack_url:
            slack_body = (
                f"*Target:* `{alert.target}`\n"
                f"*File:* `{filename}`\n"
                f"*Status:* {status_verb}\n"
                f"*Time:* {alert.detected_at}\n"
                f"Run `/sync` to re-sync or `/sync-restore` to revert."
            )
            if send_slack_notification(_slack_url, title, slack_body):
                sent = True

        # Discord
        if _discord_url:
            discord_body = (
                f"**Target:** `{alert.target}`\n"
                f"**File:** `{filename}`\n"
                f"**Status:** {status_verb}\n"
                f"**Time:** {alert.detected_at}\n"
                f"Run `/sync` to re-sync or `/sync-restore` to revert."
            )
            if send_discord_notification(_discord_url, title, discord_body):
                sent = True

        # Generic webhook
        if _generic_url:
            if send_generic_webhook_notification(
                _generic_url,
                event="drift_detected",
                target=alert.target,
                filename=filename,
                detected_at=alert.detected_at,
            ):
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


# ---------------------------------------------------------------------------
# Semantic Drift Analysis (Item 2)
# ---------------------------------------------------------------------------

# Rule-level permission keywords whose presence/absence signals semantic drift.
_ALLOW_KEYWORDS = frozenset(["allow", "always", "enable", "permitted", "can use", "allowed"])
_BLOCK_KEYWORDS = frozenset(["block", "deny", "disable", "never", "not allowed", "forbidden", "reject"])

# Tool/capability names to check across harness configs
_CAPABILITY_TOKENS = frozenset([
    "bash", "edit", "read", "write", "glob", "grep", "agent", "webfetch", "websearch",
    "mcp", "tool_use", "computer_use", "code_execution",
])


@dataclass
class SemanticDriftAlert:
    """Alert for a rule whose meaning has shifted between Claude Code and a target harness."""

    target: str
    capability: str          # e.g. "bash", "mcp"
    source_intent: str       # "allow" | "block" | "neutral"
    target_intent: str       # "allow" | "block" | "neutral" | "absent"
    source_snippet: str      # relevant line from CLAUDE.md
    target_snippet: str      # relevant line from target config (empty if absent)
    suggested_fix: str

    def format(self) -> str:
        lines = [
            f"[SEMANTIC DRIFT] {self.target} — capability '{self.capability}'",
            f"  Claude Code intent : {self.source_intent}",
            f"  {self.target:16s} intent: {self.target_intent}",
        ]
        if self.source_snippet:
            lines.append(f"  Source rule  : {self.source_snippet.strip()}")
        if self.target_snippet:
            lines.append(f"  Target rule  : {self.target_snippet.strip()}")
        lines.append(f"  Suggested fix: {self.suggested_fix}")
        return "\n".join(lines)


def _classify_intent(text: str) -> str:
    """Return 'allow', 'block', or 'neutral' based on keyword presence."""
    lower = text.lower()
    has_allow = any(kw in lower for kw in _ALLOW_KEYWORDS)
    has_block = any(kw in lower for kw in _BLOCK_KEYWORDS)
    if has_block and not has_allow:
        return "block"
    if has_allow and not has_block:
        return "allow"
    return "neutral"


def _find_capability_line(text: str, capability: str) -> str:
    """Return the first line in text that mentions the capability, or ''."""
    for line in text.splitlines():
        if capability.lower() in line.lower():
            return line
    return ""


def analyze_semantic_drift(
    source_content: str,
    target_content: str,
    target: str,
) -> list[SemanticDriftAlert]:
    """Compare rule semantics between Claude Code config and a target harness config.

    Rather than comparing bytes, this looks for capability mentions whose
    allow/block intent differs between the source (CLAUDE.md) and the synced
    target config. For example, if CLAUDE.md permits 'bash' but the Codex
    target config now has a line that blocks it, a SemanticDriftAlert is
    returned.

    Args:
        source_content: Text of the Claude Code rules (CLAUDE.md content).
        target_content: Text of the target harness config as currently on disk.
        target: Harness name (e.g. "codex").

    Returns:
        List of SemanticDriftAlerts — empty if no semantic conflicts found.
    """
    alerts: list[SemanticDriftAlert] = []

    for cap in _CAPABILITY_TOKENS:
        source_line = _find_capability_line(source_content, cap)
        target_line = _find_capability_line(target_content, cap)

        if not source_line and not target_line:
            continue  # capability not mentioned in either — no drift

        source_intent = _classify_intent(source_line) if source_line else "neutral"
        target_intent = _classify_intent(target_line) if target_line else "absent"

        # Only surface when intents conflict meaningfully
        conflict = (
            (source_intent == "allow" and target_intent == "block")
            or (source_intent == "block" and target_intent == "allow")
            or (source_intent == "allow" and target_intent == "absent" and not target_line)
        )
        if not conflict:
            continue

        if source_intent == "allow" and target_intent == "block":
            suggested_fix = (
                f"Remove or relax the '{cap}' restriction in the {target} config, "
                f"or add '# @{target}: skip' to the source rule."
            )
        elif source_intent == "block" and target_intent == "allow":
            suggested_fix = (
                f"Add a '{cap}' restriction to the {target} config to match "
                f"the Claude Code rule, or run /sync to re-apply it."
            )
        else:
            suggested_fix = (
                f"The '{cap}' capability is allowed in Claude Code but missing "
                f"from the {target} config. Run /sync to propagate the rule."
            )

        alerts.append(SemanticDriftAlert(
            target=target,
            capability=cap,
            source_intent=source_intent,
            target_intent=target_intent,
            source_snippet=source_line,
            target_snippet=target_line,
            suggested_fix=suggested_fix,
        ))

    return alerts


def semantic_drift_summary(
    project_dir: Path,
    state_manager: StateManager | None = None,
) -> dict[str, list[SemanticDriftAlert]]:
    """Run semantic drift analysis across all synced targets.

    Reads the Claude Code rules source and compares them against each target's
    current on-disk config to detect meaning-level conflicts.

    Args:
        project_dir: Root directory of the project.
        state_manager: Optional StateManager (created from project_dir if None).

    Returns:
        Dict mapping target name → list of SemanticDriftAlerts.
        Targets with no semantic conflicts map to an empty list.
    """
    sm = state_manager or StateManager()

    # Read Claude Code source rules
    source_path = project_dir / "CLAUDE.md"
    if not source_path.exists():
        return {}
    source_content = source_path.read_text(encoding="utf-8", errors="replace")

    # Target config file paths (primary rules file per harness)
    _TARGET_RULES_FILES: dict[str, str] = {
        "codex": "AGENTS.md",
        "gemini": "GEMINI.md",
        "opencode": "AGENTS.md",
        "cursor": ".cursor/rules/harnesssync.mdc",
        "aider": "CONVENTIONS.md",
        "windsurf": ".windsurfrules",
        "cline": ".clinerules",
        "continue": ".continue/rules/harnesssync.md",
        "zed": ".zed/system-prompt.md",
        "neovim": ".avante/system-prompt.md",
    }

    state = sm.load_state()
    configured_targets = list(state.get("targets", {}).keys())
    if not configured_targets:
        configured_targets = list(_TARGET_RULES_FILES.keys())

    result: dict[str, list[SemanticDriftAlert]] = {}
    for target in configured_targets:
        rules_file = _TARGET_RULES_FILES.get(target)
        if not rules_file:
            result[target] = []
            continue
        target_path = project_dir / rules_file
        if not target_path.exists():
            result[target] = []
            continue
        target_content = target_path.read_text(encoding="utf-8", errors="replace")
        result[target] = analyze_semantic_drift(source_content, target_content, target)

    return result


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


# ---------------------------------------------------------------------------
# Zero-Drift Guarantee Mode (item 21)
# ---------------------------------------------------------------------------

class ZeroDriftGuarantee:
    """Strict mode that detects and reverts external edits to synced config files.

    When enabled, HarnessSync watches synced output files and immediately
    reverts any change made by a tool other than HarnessSync itself.  The
    revert is performed by re-writing the last-synced content stored in the
    state snapshot.

    This gives power users an iron guarantee: secondary harness configs are
    always byte-for-byte identical to the last sync output.

    Usage::

        guarantee = ZeroDriftGuarantee(project_dir=Path("."))
        guarantee.enable()   # begins watching in a background thread
        guarantee.disable()  # stops the watcher

        # Check status without starting a thread:
        violations = guarantee.scan_once()
    """

    _POLL_INTERVAL: float = 2.0
    _REVERT_LOG_MAX: int = 100

    def __init__(
        self,
        project_dir: Path | None = None,
        state_manager: StateManager | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._project_dir = project_dir or Path.cwd()
        self._sm = state_manager or StateManager()
        self._logger = logger or Logger()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._revert_log: list[dict] = []

    def enable(self) -> None:
        """Start the background file watcher that reverts external edits."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="ZeroDriftGuarantee",
            daemon=True,
        )
        self._thread.start()
        self._logger.info("ZeroDriftGuarantee enabled — external edits will be reverted.")

    def disable(self) -> None:
        """Stop the background file watcher."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._logger.info("ZeroDriftGuarantee disabled.")

    @property
    def active(self) -> bool:
        """True if the background watcher is currently running."""
        return bool(self._thread and self._thread.is_alive())

    def scan_once(self) -> list[dict]:
        """Perform a single drift scan without reverting.

        Returns:
            List of violation dicts with keys:
              ``file_path``, ``expected_hash``, ``actual_hash``, ``reverted``.
        """
        return self._check_files(revert=False)

    def revert_violations(self) -> list[dict]:
        """Detect and revert all external edits to synced files.

        Returns:
            List of reverted violation dicts.
        """
        return self._check_files(revert=True)

    @property
    def revert_log(self) -> list[dict]:
        """Return the in-memory revert log (most recent first)."""
        return list(reversed(self._revert_log))

    def format_status(self) -> str:
        """Return a human-readable status string."""
        status = "active" if self.active else "inactive"
        reverts = len(self._revert_log)
        lines = [
            f"Zero-Drift Guarantee Mode: {status.upper()}",
            f"  Reverts applied this session: {reverts}",
        ]
        if self._revert_log:
            last = self._revert_log[-1]
            lines.append(f"  Last revert: {last.get('file_path', '?')} at {last.get('timestamp', '?')}")
        lines.append("")
        lines.append(
            "All synced config files are protected. External edits are reverted automatically."
            if self.active
            else "Run /sync with --zero-drift to enable protection."
        )
        return "\n".join(lines)

    def _watch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_files(revert=True)
            except Exception as exc:
                self._logger.warning(f"ZeroDriftGuarantee scan error: {exc}")
            self._stop_event.wait(self._POLL_INTERVAL)

    def _check_files(self, revert: bool) -> list[dict]:
        """Check all tracked files for drift and optionally revert them."""
        state = self._sm.load_state()
        violations: list[dict] = []

        for target_name, target_data in state.get("targets", {}).items():
            snapshots: dict[str, str] = target_data.get("file_content_snapshots", {})
            file_hashes: dict[str, str] = target_data.get("file_hashes", {})

            for file_path_str, stored_hash in file_hashes.items():
                file_path = Path(file_path_str)
                if not file_path.exists():
                    continue

                current_hash = hash_file_sha256(file_path) or ""
                if current_hash == stored_hash:
                    continue

                violation: dict = {
                    "target": target_name,
                    "file_path": file_path_str,
                    "expected_hash": stored_hash,
                    "actual_hash": current_hash,
                    "reverted": False,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }

                if revert and file_path_str in snapshots:
                    try:
                        file_path.write_text(snapshots[file_path_str], encoding="utf-8")
                        violation["reverted"] = True
                        self._logger.warning(
                            f"ZeroDriftGuarantee: reverted external edit to {file_path_str}"
                        )
                    except OSError as exc:
                        self._logger.error(
                            f"ZeroDriftGuarantee: failed to revert {file_path_str}: {exc}"
                        )

                violations.append(violation)
                self._revert_log.append(violation)
                if len(self._revert_log) > self._REVERT_LOG_MAX:
                    self._revert_log = self._revert_log[-self._REVERT_LOG_MAX :]

        return violations


# ---------------------------------------------------------------------------
# Item 27 — Source Change Watcher (Auto-Sync on File Save)
# ---------------------------------------------------------------------------
#
# Unlike DriftWatcher which monitors target harness outputs for external edits,
# SourceChangeWatcher monitors the Claude Code *source* files (CLAUDE.md,
# .claude/) for changes and triggers an auto-sync callback when they change.
# This provides the "sync within seconds of any CLAUDE.md or .claude/ file
# change" UX described in the feature spec.


class SourceChangeWatcher:
    """Watch Claude Code source files and auto-trigger sync on change.

    Monitors ``CLAUDE.md`` and the ``.claude/`` directory (rules, skills,
    agents, commands, settings) for file content changes. When a change is
    detected the ``sync_callback`` is called so the caller can run a sync.

    Internally hashes each watched file; when a hash changes, the file is
    included in the change notification passed to the callback.

    Usage::

        def my_sync(changed_files):
            print(f"Changed: {changed_files}")
            # ... run orchestrator.sync_all() ...

        watcher = SourceChangeWatcher(project_dir, sync_callback=my_sync)
        watcher.start()          # non-blocking background thread
        watcher.watch_blocking() # or blocking until Ctrl-C
        watcher.stop()
    """

    # Source paths watched by default (relative to project_dir)
    DEFAULT_SOURCE_PATHS: list[str] = [
        "CLAUDE.md",
        ".claude/CLAUDE.md",
        ".claude/rules",
        ".claude/skills",
        ".claude/agents",
        ".claude/commands",
        ".claude/settings.json",
        ".mcp.json",
    ]

    def __init__(
        self,
        project_dir: Path,
        sync_callback: Callable[[list[str]], None],
        poll_interval: float = 2.0,
        extra_paths: list[str] | None = None,
        debounce_seconds: float = 1.0,
    ):
        """Initialise the source change watcher.

        Args:
            project_dir: Project root directory (base for relative source paths).
            sync_callback: Called with a list of changed file paths (relative to
                           project_dir) when one or more source files change.
            poll_interval: Seconds between each file check (default: 2.0).
            extra_paths: Additional paths/directories to watch.
            debounce_seconds: Minimum seconds between successive auto-sync calls.
                              Prevents rapid-fire syncs when an editor saves many
                              files at once (default: 1.0).
        """
        self.project_dir = project_dir
        self.sync_callback = sync_callback
        self.poll_interval = poll_interval
        self.debounce_seconds = debounce_seconds

        watched = list(self.DEFAULT_SOURCE_PATHS)
        if extra_paths:
            watched.extend(extra_paths)
        self._watch_paths: list[str] = watched

        # File hash snapshot: relative_path -> hash string
        self._hashes: dict[str, str] = {}
        self._last_sync_time: float = 0.0

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Take initial snapshot
        self._snapshot()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start background source-change polling (non-blocking)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="harnesssync-source-watcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the watcher to stop and wait for its thread to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_interval + 2)
            self._thread = None

    def is_running(self) -> bool:
        """Return True if the watcher thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def watch_blocking(self) -> None:
        """Run source-change detection in the current thread until interrupted.

        Blocks until KeyboardInterrupt (Ctrl-C) or ``stop()`` is called from
        another thread.
        """
        print("HarnessSync Source Watcher — monitoring CLAUDE.md and .claude/ for changes...")
        print(f"Poll interval: {self.poll_interval}s  |  Press Ctrl-C to stop\n")
        try:
            while not self._stop_event.is_set():
                self._check_once()
                self._stop_event.wait(timeout=self.poll_interval)
        except KeyboardInterrupt:
            print("\nSource watcher stopped.")

    def check_and_sync(self) -> list[str]:
        """Run a single check and trigger sync if anything changed.

        Can be called manually (e.g. from a git hook) without starting
        the background thread.

        Returns:
            List of changed file paths that triggered the sync, or empty
            list if nothing changed.
        """
        return self._check_once()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _collect_paths(self) -> list[Path]:
        """Expand watch_paths to concrete file paths that exist."""
        paths: list[Path] = []
        for rel in self._watch_paths:
            p = self.project_dir / rel
            if p.is_file():
                paths.append(p)
            elif p.is_dir():
                # Recursively include all files in the directory
                for child in sorted(p.rglob("*")):
                    if child.is_file():
                        paths.append(child)
        return paths

    def _snapshot(self) -> None:
        """Take a fresh hash snapshot of all watched files."""
        with self._lock:
            new_hashes: dict[str, str] = {}
            for path in self._collect_paths():
                try:
                    rel = str(path.relative_to(self.project_dir))
                except ValueError:
                    rel = str(path)
                h = hash_file_sha256(path) or ""
                new_hashes[rel] = h
            self._hashes = new_hashes

    def _check_once(self) -> list[str]:
        """Check for changes and trigger sync_callback if needed.

        Returns:
            List of changed relative file paths.
        """
        changed: list[str] = []

        with self._lock:
            for path in self._collect_paths():
                try:
                    rel = str(path.relative_to(self.project_dir))
                except ValueError:
                    rel = str(path)
                current_hash = hash_file_sha256(path) or ""
                stored_hash = self._hashes.get(rel, "")
                if current_hash != stored_hash:
                    changed.append(rel)
                    self._hashes[rel] = current_hash

            # Also detect newly-created files not in previous snapshot
            for path in self._collect_paths():
                try:
                    rel = str(path.relative_to(self.project_dir))
                except ValueError:
                    rel = str(path)
                if rel not in self._hashes:
                    current_hash = hash_file_sha256(path) or ""
                    self._hashes[rel] = current_hash
                    changed.append(rel)

        if not changed:
            return []

        # Debounce: avoid rapid-fire syncs
        now = time.time()
        if now - self._last_sync_time < self.debounce_seconds:
            return changed  # Changed detected but not triggering sync yet

        self._last_sync_time = now
        try:
            self.sync_callback(changed)
        except Exception:
            pass  # Don't let sync errors crash the watcher thread

        return changed

    def _poll_loop(self) -> None:
        """Background thread loop."""
        while not self._stop_event.is_set():
            try:
                self._check_once()
            except Exception:
                pass
            self._stop_event.wait(timeout=self.poll_interval)


# ---------------------------------------------------------------------------
# Guided merge — item 10 (Drift Detection with Guided Merge)
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dc_guided
from enum import Enum as _Enum


class MergeChoice(_Enum):
    """User's resolution choice from guided_merge_prompt()."""
    SYNC_WINS = "sync"       # Overwrite with HarnessSync content
    KEEP_MANUAL = "keep"     # Keep the manual edits as a harness-specific override
    SKIP = "skip"            # Do nothing for now


@_dc_guided
class GuidedMergeResult:
    """Result of a guided merge interaction."""
    target: str
    file_path: str
    choice: MergeChoice
    override_saved: bool = False  # True if manual edit was saved as an override
    override_path: str = ""       # Path to saved override file (if kept)


def _show_drift_diff(
    source_content: str,
    current_content: str,
    file_label: str,
    max_lines: int = 30,
) -> None:
    """Print a compact unified diff showing what the user manually changed."""
    import difflib as _difflib

    source_lines = source_content.splitlines(keepends=True)
    current_lines = current_content.splitlines(keepends=True)
    diff = list(_difflib.unified_diff(
        source_lines,
        current_lines,
        fromfile=f"harnesssync/{file_label}",
        tofile=f"manual/{file_label}",
        lineterm="",
        n=2,
    ))
    if not diff:
        print(f"  (no text differences detected in {file_label})")
        return

    printed = 0
    for line in diff:
        if printed >= max_lines:
            remaining = len(diff) - max_lines
            print(f"  ... ({remaining} more diff lines)")
            break
        if line.startswith("+") and not line.startswith("+++"):
            print(f"  \033[32m{line}\033[0m")  # green
        elif line.startswith("-") and not line.startswith("---"):
            print(f"  \033[31m{line}\033[0m")  # red
        else:
            print(f"  {line}")
        printed += 1


def guided_merge_prompt(
    target: str,
    file_path: str,
    source_content: str,
    current_content: str,
    project_dir: "Path | None" = None,
    non_interactive: bool = False,
) -> GuidedMergeResult:
    """Interactively resolve a drift conflict between HarnessSync and manual edits.

    Shows the user exactly what they changed in the target config (diff),
    then offers three choices:
      1. Let sync win  — overwrite manual edits on next sync
      2. Keep changes  — save manual edits as a harness-specific override
                         in .harnesssync-overrides/<target>/ so they survive
                         future syncs
      3. Skip for now  — do nothing (drift remains)

    Args:
        target: Canonical harness name (e.g. "codex").
        file_path: Absolute path to the drifted config file.
        source_content: Last-synced content (the HarnessSync version).
        current_content: Current on-disk content (with manual edits).
        project_dir: Project root (for saving overrides). Defaults to cwd.
        non_interactive: If True, skip the prompt and default to SKIP.

    Returns:
        GuidedMergeResult describing what was chosen and what was done.
    """
    import sys as _sys

    result = GuidedMergeResult(
        target=target,
        file_path=file_path,
        choice=MergeChoice.SKIP,
    )

    print(f"\n{'─' * 60}")
    print(f"Drift detected in {target}: {file_path}")
    print(f"{'─' * 60}")
    print("Your manual changes vs. the last HarnessSync version:\n")
    _show_drift_diff(source_content, current_content, file_path)
    print()

    if non_interactive or not _sys.stdin.isatty():
        print(f"[non-interactive] Defaulting to SKIP for {target}.")
        return result

    print("How would you like to resolve this?")
    print("  [1] Let sync win     — overwrite on next /sync (manual edits lost)")
    print("  [2] Keep my changes  — save as a harness-specific override")
    print("  [3] Skip for now     — leave as-is (drift remains)")
    print()

    try:
        answer = input("Choice [1/2/3, default=3]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted — defaulting to skip.")
        return result

    if answer == "1":
        result.choice = MergeChoice.SYNC_WINS
        print(f"✓ Marked: sync will overwrite {target} config on next /sync.")

    elif answer == "2":
        result.choice = MergeChoice.KEEP_MANUAL
        # Save the manual edits as a harness-specific override
        proj = Path(project_dir) if project_dir else Path.cwd()
        override_dir = proj / ".harnesssync-overrides" / target
        override_dir.mkdir(parents=True, exist_ok=True)
        override_file = override_dir / Path(file_path).name
        try:
            override_file.write_text(current_content, encoding="utf-8")
            result.override_saved = True
            result.override_path = str(override_file)
            print(f"✓ Manual edits saved to: {override_file}")
            print(
                f"  HarnessSync will merge this override on future syncs.\n"
                f"  Commit .harnesssync-overrides/ to share with your team."
            )
        except OSError as e:
            print(f"  Warning: could not save override: {e}")

    else:
        print(f"  Skipping — drift in {target} remains. Run /sync to overwrite.")

    return result
