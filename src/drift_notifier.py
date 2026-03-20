from __future__ import annotations

"""Drift notification delivery: OS notifications, webhooks, and status formatting.

This module handles all notification channels for drift alerts:
- OS desktop notifications (macOS/Linux)
- Slack incoming webhooks
- Discord incoming webhooks
- Generic HTTPS webhooks
- Terminal status line formatting
- Alert callback factory with cooldown logic
"""

from datetime import datetime
from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from src.drift_detector import DriftAlert, DriftWatcher


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
) -> Callable:
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
        from src.drift_detector import DriftAlert as _DriftAlert  # noqa: F811 — runtime resolve

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


def format_status_line(watcher: DriftWatcher | None = None, status: dict | None = None) -> str:
    """Render a compact one-line watcher status indicator for terminal display.

    Can be used in shell prompts, VS Code status bars, or watch-mode headers.

    Args:
        watcher: Live DriftWatcher instance (preferred).
        status:  Pre-built status dict from get_status_summary() (alternative
                 when a watcher instance is unavailable).

    Returns:
        A single-line string such as::

            [HS WATCH active | poll: 30s | alerts: 0]
            [HS WATCH stopped | last alert: codex 2m ago]

    Examples::

        watcher = DriftWatcher(project_dir)
        watcher.start()
        print(format_status_line(watcher))
        # -> [HS WATCH active | poll: 30s | alerts: 0]
    """
    if watcher is not None:
        s = watcher.get_status_summary()
    elif status is not None:
        s = status
    else:
        return "[HS WATCH \u25cb not started]"

    running = s.get("running", False)
    poll = s.get("poll_interval", 30.0)
    alert_count = s.get("alert_count", 0)
    last_alert_at = s.get("last_alert_at")
    targets_drifted = s.get("targets_drifted", [])

    state_icon = "\u25c9" if running else "\u25cb"
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
