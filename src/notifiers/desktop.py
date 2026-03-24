from __future__ import annotations

"""Desktop notification sender with platform detection.

Supports:
  - macOS: osascript display notification
  - Linux: notify-send (libnotify)
  - Windows: no-op (silently skipped)

Usage:
    from src.notifiers.desktop import notify
    notify("Cursor rules manually edited — run /sync to re-sync")
"""

import subprocess
import sys


def _notify_macos(title: str, message: str) -> None:
    """Send a notification via osascript on macOS."""
    script = (
        f'display notification "{message}" with title "{title}"'
    )
    subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        timeout=5,
    )


def _notify_linux(title: str, message: str) -> None:
    """Send a notification via notify-send on Linux."""
    subprocess.run(
        ["notify-send", title, message, "--expire-time=8000"],
        capture_output=True,
        timeout=5,
    )


def notify(message: str, title: str = "HarnessSync") -> None:
    """Send a desktop notification.

    Args:
        message: The notification body text.
        title: The notification title (default: "HarnessSync").

    Silently ignores errors on unsupported platforms or when the
    notification tool is unavailable.
    """
    try:
        if sys.platform == "darwin":
            _notify_macos(title, message)
        elif sys.platform.startswith("linux"):
            _notify_linux(title, message)
        # Windows: no-op (no stdlib desktop notification support)
    except Exception:
        pass  # Notification failure must never affect core sync
