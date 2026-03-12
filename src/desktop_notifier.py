from __future__ import annotations

"""Desktop Notifications for HarnessSync sync events.

Sends native desktop notifications on macOS and Linux when auto-sync
triggers, summarising what changed, which harnesses were updated, and
whether any errors occurred.

Platform support:
  macOS:  ``osascript`` (AppleScript) — zero-dependency, always available
  Linux:  ``notify-send`` — requires libnotify-bin (commonly pre-installed)
  Other:  Silently skipped (notifications are best-effort, never block sync)

Notifications are opt-in: users enable them by setting
``HARNESSSYNC_NOTIFY=1`` in their environment, or by adding
``"desktop_notifications": true`` to their ``.harnesssync`` config file.

Usage::

    from src.desktop_notifier import DesktopNotifier

    notifier = DesktopNotifier()
    notifier.notify_sync_complete(
        targets_updated=["codex", "gemini"],
        targets_skipped=["aider"],
        errors=[],
    )
"""

import os
import platform
import shutil
import subprocess


# Notification title prefix
_APP_NAME = "HarnessSync"

# Urgency levels for notify-send
_URGENCY_NORMAL = "normal"
_URGENCY_CRITICAL = "critical"

# Maximum body text length before truncation
_MAX_BODY = 200


class DesktopNotifier:
    """Sends desktop notifications for sync events.

    Respects the user's opt-in preference via environment variable or
    .harnesssync config.  Notification delivery is best-effort: failures
    are swallowed silently so they never interrupt sync operations.
    """

    def __init__(self, enabled: bool | None = None):
        """Initialise DesktopNotifier.

        Args:
            enabled: Override for notification enable state.
                     If None, reads from ``HARNESSSYNC_NOTIFY`` env var
                     (truthy values: "1", "true", "yes").
        """
        if enabled is not None:
            self._enabled = enabled
        else:
            env_val = os.environ.get("HARNESSSYNC_NOTIFY", "").lower().strip()
            self._enabled = env_val in ("1", "true", "yes")

        self._platform = platform.system()  # "Darwin", "Linux", "Windows"

    # ------------------------------------------------------------------
    # High-level event notifications
    # ------------------------------------------------------------------

    def notify_sync_complete(
        self,
        targets_updated: list[str],
        targets_skipped: list[str],
        errors: list[str],
    ) -> bool:
        """Send a sync-complete notification.

        Args:
            targets_updated: List of harness names that were successfully synced.
            targets_skipped: List of harness names that were skipped (no changes).
            errors:          List of error messages from failed targets.

        Returns:
            True if a notification was sent, False otherwise.
        """
        if not self._enabled:
            return False

        has_errors = bool(errors)

        if has_errors:
            title = f"{_APP_NAME}: Sync completed with errors"
        elif targets_updated:
            count = len(targets_updated)
            title = f"{_APP_NAME}: Synced {count} harness{'es' if count != 1 else ''}"
        else:
            title = f"{_APP_NAME}: No changes"

        # Build body
        parts: list[str] = []
        if targets_updated:
            parts.append(f"Updated: {', '.join(targets_updated)}")
        if targets_skipped:
            parts.append(f"Skipped: {', '.join(targets_skipped)}")
        if errors:
            parts.append(f"Errors: {'; '.join(errors[:2])}")

        body = " | ".join(parts) if parts else "Sync complete."
        if len(body) > _MAX_BODY:
            body = body[:_MAX_BODY - 3] + "..."

        urgency = _URGENCY_CRITICAL if has_errors else _URGENCY_NORMAL
        return self._send(title, body, urgency=urgency)

    def notify_sync_paused(self, reason: str = "", resume_at: str = "") -> bool:
        """Send a notification that sync has been paused.

        Args:
            reason:    Human-readable pause reason.
            resume_at: ISO timestamp for auto-resume (empty = indefinite).

        Returns:
            True if a notification was sent.
        """
        if not self._enabled:
            return False
        title = f"{_APP_NAME}: Auto-sync paused"
        parts = []
        if reason:
            parts.append(reason)
        if resume_at:
            parts.append(f"Auto-resume: {resume_at}")
        body = " | ".join(parts) if parts else "Run /sync-pause --resume to re-enable."
        return self._send(title, body)

    def notify_sync_error(self, target: str, error: str) -> bool:
        """Send a notification for a critical sync error.

        Args:
            target: Harness name that failed.
            error:  Error message.

        Returns:
            True if a notification was sent.
        """
        if not self._enabled:
            return False
        title = f"{_APP_NAME}: Sync error — {target}"
        body = error[:_MAX_BODY] if error else "Unknown error."
        return self._send(title, body, urgency=_URGENCY_CRITICAL)

    def notify_conflict_detected(self, target: str, file_count: int) -> bool:
        """Send a notification when manual edits are detected in a target.

        Args:
            target:     Harness name with conflicting changes.
            file_count: Number of conflicting files.

        Returns:
            True if a notification was sent.
        """
        if not self._enabled:
            return False
        title = f"{_APP_NAME}: Conflict detected — {target}"
        s = "s" if file_count != 1 else ""
        body = (
            f"{file_count} file{s} in {target} were manually edited since last sync. "
            "Run /sync-diff to review."
        )
        return self._send(title, body, urgency=_URGENCY_CRITICAL)

    # ------------------------------------------------------------------
    # Platform dispatch
    # ------------------------------------------------------------------

    def _send(self, title: str, body: str, urgency: str = _URGENCY_NORMAL) -> bool:
        """Dispatch a notification to the appropriate platform backend.

        Returns True if delivery was attempted (not necessarily successful).
        """
        try:
            if self._platform == "Darwin":
                return self._send_macos(title, body)
            elif self._platform == "Linux":
                return self._send_linux(title, body, urgency)
            # Windows / other: not supported
            return False
        except Exception:
            return False

    def _send_macos(self, title: str, body: str) -> bool:
        """Send via osascript on macOS."""
        # Escape double-quotes for AppleScript string literal
        title_esc = title.replace('"', '\\"')
        body_esc = body.replace('"', '\\"')
        script = (
            f'display notification "{body_esc}" '
            f'with title "{title_esc}"'
        )
        try:
            subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _send_linux(self, title: str, body: str, urgency: str) -> bool:
        """Send via notify-send on Linux."""
        if not shutil.which("notify-send"):
            return False
        try:
            subprocess.run(
                [
                    "notify-send",
                    "--app-name", _APP_NAME,
                    f"--urgency={urgency}",
                    "--expire-time=6000",
                    title,
                    body,
                ],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return True
        except (OSError, subprocess.TimeoutExpired):
            return False


class SyncDigestCollector:
    """Accumulate sync events during a session and emit a single digest summary.

    Rather than bombarding users with per-event notifications, SyncDigestCollector
    gathers each sync event and provides a single human-readable digest (either
    as a formatted string or as a desktop notification) at the end of the session
    or on demand.

    Usage::

        digest = SyncDigestCollector()
        digest.record_sync(targets_updated=["codex"], targets_skipped=[], errors=[])
        digest.record_sync(targets_updated=["gemini"], targets_skipped=["aider"], errors=[])
        print(digest.format_digest())
        digest.send_digest()   # optional OS notification at session end
    """

    def __init__(self) -> None:
        self._events: list[dict] = []

    def record_sync(
        self,
        targets_updated: list[str],
        targets_skipped: list[str],
        errors: list[str],
        details: str = "",
    ) -> None:
        """Record a single sync event.

        Args:
            targets_updated: Harness names that were synced.
            targets_skipped: Harness names with no changes.
            errors:          Error messages from failed targets.
            details:         Optional extra detail (e.g. "added 1 skill").
        """
        self._events.append({
            "updated": list(targets_updated),
            "skipped": list(targets_skipped),
            "errors": list(errors),
            "details": details,
        })

    def record_from_results(self, results: dict) -> None:
        """Record a sync event from an orchestrator results dict.

        Args:
            results: Dict from SyncOrchestrator.sync_all().
        """
        targets_updated: list[str] = []
        targets_skipped: list[str] = []
        errors: list[str] = []

        for key, val in results.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            has_error = any(
                getattr(v, "failed", 0) for v in val.values() if hasattr(v, "failed")
            )
            all_skipped = all(
                getattr(v, "skipped", 0) > 0 and getattr(v, "synced", 0) == 0
                for v in val.values()
                if hasattr(v, "skipped")
            )
            if has_error:
                errors.append(f"{key}: error")
            elif all_skipped:
                targets_skipped.append(key)
            else:
                targets_updated.append(key)

        self.record_sync(targets_updated, targets_skipped, errors)

    @property
    def event_count(self) -> int:
        """Number of recorded sync events."""
        return len(self._events)

    def format_digest(self) -> str:
        """Return a human-readable session digest string.

        Returns:
            Multi-line summary of all sync activity this session.
        """
        if not self._events:
            return "No sync events this session."

        total_syncs = len(self._events)
        all_updated: list[str] = []
        all_errors: list[str] = []
        all_details: list[str] = []
        skipped_count = 0

        for ev in self._events:
            all_updated.extend(ev["updated"])
            all_errors.extend(ev["errors"])
            if ev["details"]:
                all_details.append(ev["details"])
            skipped_count += len(ev["skipped"])

        # Deduplicate updated target names with counts
        from collections import Counter
        updated_counts = Counter(all_updated)

        lines = [
            f"Session Sync Digest — {total_syncs} sync{'s' if total_syncs != 1 else ''}",
        ]
        if updated_counts:
            parts = [f"{t} ×{c}" if c > 1 else t for t, c in sorted(updated_counts.items())]
            lines.append(f"  Updated: {', '.join(parts)}")
        if skipped_count:
            lines.append(f"  Skipped (no changes): {skipped_count} target(s)")
        if all_errors:
            lines.append(f"  Errors: {'; '.join(all_errors[:3])}")
        if all_details:
            lines.append("  Details: " + "; ".join(all_details[:5]))

        return "\n".join(lines)

    def send_digest(self, enabled: bool | None = None) -> bool:
        """Send the digest as a desktop notification.

        Args:
            enabled: Override notification enable state.

        Returns:
            True if the notification was sent.
        """
        if not self._events:
            return False
        notifier = DesktopNotifier(enabled=enabled)
        if not notifier._enabled:
            return False
        digest_text = self.format_digest()
        body = digest_text[:_MAX_BODY] + ("..." if len(digest_text) > _MAX_BODY else "")
        return notifier._send("HarnessSync: Session Digest", body)

    def clear(self) -> None:
        """Clear all recorded events (e.g. at session start)."""
        self._events.clear()


def notify_from_results(
    results: dict,
    enabled: bool | None = None,
) -> bool:
    """Convenience function: parse orchestrator results and send a notification.

    Extracts updated/skipped/errored targets from the orchestrator results
    dict and fires the appropriate desktop notification.

    Args:
        results:  Results dict from ``SyncOrchestrator.sync_all()``.
        enabled:  Override for notification enable state.

    Returns:
        True if a notification was sent.
    """
    notifier = DesktopNotifier(enabled=enabled)
    if not notifier._enabled:
        return False

    if results.get("_blocked"):
        return notifier.notify_sync_error("all", results.get("_reason", "sync blocked"))

    targets_updated: list[str] = []
    targets_skipped: list[str] = []
    errors: list[str] = []

    for key, val in results.items():
        if key.startswith("_"):
            continue
        if isinstance(val, dict):
            has_error = any(
                getattr(v, "failed", 0) or getattr(v, "error", None)
                for v in val.values()
                if hasattr(v, "failed")
            )
            all_skipped = all(
                getattr(v, "skipped", 0) > 0 and getattr(v, "synced", 0) == 0
                for v in val.values()
                if hasattr(v, "skipped")
            )
            if has_error:
                errors.append(f"{key}: sync error")
            elif all_skipped:
                targets_skipped.append(key)
            else:
                targets_updated.append(key)

    return notifier.notify_sync_complete(
        targets_updated=targets_updated,
        targets_skipped=targets_skipped,
        errors=errors,
    )
