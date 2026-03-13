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
from pathlib import Path


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


# ---------------------------------------------------------------------------
# Scheduled Sync Manager (item 8)
# ---------------------------------------------------------------------------

_LAUNCHD_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.harnesssync.scheduled</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{script}</string>
        <string>--notify-on-change</string>
    </array>
    <key>StartInterval</key>
    <integer>{interval_seconds}</integer>
    <key>RunAtLoad</key>
    <{run_at_load}/>
    <key>StandardOutPath</key>
    <string>{log_dir}/harnesssync-scheduled.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/harnesssync-scheduled.err</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
        <key>HARNESSSYNC_NOTIFY</key>
        <string>1</string>
    </dict>
</dict>
</plist>
"""

_SYSTEMD_UNIT_TEMPLATE = """\
[Unit]
Description=HarnessSync scheduled config sync
After=network.target

[Service]
Type=oneshot
ExecStart={python} {script} --notify-on-change
Environment=HARNESSSYNC_NOTIFY=1
StandardOutput=append:{log_dir}/harnesssync-scheduled.log
StandardError=append:{log_dir}/harnesssync-scheduled.err

[Install]
WantedBy=default.target
"""

_SYSTEMD_TIMER_TEMPLATE = """\
[Unit]
Description=HarnessSync scheduled sync timer
After=network.target

[Timer]
OnBootSec={interval_seconds}s
OnUnitActiveSec={interval_seconds}s
Persistent=true

[Install]
WantedBy=timers.target
"""


class ScheduledSyncManager:
    """Configure cron-style scheduled HarnessSync runs with desktop notifications.

    Generates platform-appropriate scheduler configs (launchd on macOS,
    systemd timers on Linux) that run HarnessSync on a configurable interval
    and send a desktop notification *only when something actually changed*.

    Users who don't rely on PostToolUse hooks get eventual consistency without
    manual runs. The scheduler stays silent when nothing changed.

    Args:
        interval_minutes: How often to run sync (default: 60).
        run_at_load: macOS only — also run immediately on login/boot.
        cc_home: Claude Code home directory (default: ~/.claude).
        script_path: Path to the harnesssync CLI entry point.
    """

    SERVICE_LABEL = "com.harnesssync.scheduled"

    def __init__(
        self,
        interval_minutes: int = 60,
        run_at_load: bool = True,
        cc_home: Path | None = None,
        script_path: Path | None = None,
    ):
        self.interval_minutes = max(1, interval_minutes)
        self.run_at_load = run_at_load
        self._cc_home = cc_home or (Path.home() / ".claude")
        self._script_path = script_path or (Path.home() / ".cc2all" / "harnesssync.py")

    @property
    def interval_seconds(self) -> int:
        return self.interval_minutes * 60

    def generate_launchd_plist(self) -> str:
        """Generate a launchd plist for macOS scheduled sync.

        Returns:
            XML plist string ready to write to
            ~/Library/LaunchAgents/com.harnesssync.scheduled.plist
        """
        import sys
        log_dir = str(self._cc_home / "logs")
        return _LAUNCHD_PLIST_TEMPLATE.format(
            python=sys.executable,
            script=str(self._script_path),
            interval_seconds=self.interval_seconds,
            run_at_load="true" if self.run_at_load else "false",
            log_dir=log_dir,
        )

    def generate_systemd_unit(self) -> tuple[str, str]:
        """Generate a systemd service unit and timer for Linux scheduled sync.

        Returns:
            Tuple of (service_unit_content, timer_unit_content).
            Write to ~/.config/systemd/user/harnesssync.service and
            ~/.config/systemd/user/harnesssync.timer
        """
        import sys
        log_dir = str(self._cc_home / "logs")
        service = _SYSTEMD_UNIT_TEMPLATE.format(
            python=sys.executable,
            script=str(self._script_path),
            log_dir=log_dir,
        )
        timer = _SYSTEMD_TIMER_TEMPLATE.format(
            interval_seconds=self.interval_seconds,
        )
        return service, timer

    def install(self, dry_run: bool = False) -> dict[str, str]:
        """Install the scheduler for the current platform.

        On macOS: writes the launchd plist and runs launchctl load.
        On Linux: writes systemd unit/timer and runs systemctl --user enable.

        Args:
            dry_run: If True, return the generated configs without writing.

        Returns:
            Dict with keys 'platform', 'status', 'files', and optionally 'error'.
        """
        plat = platform.system()
        if plat == "Darwin":
            return self._install_macos(dry_run)
        elif plat == "Linux":
            return self._install_linux(dry_run)
        else:
            return {
                "platform": plat,
                "status": "unsupported",
                "files": {},
                "error": f"Scheduled sync not supported on {plat}; use cron manually.",
            }

    def uninstall(self) -> dict[str, str]:
        """Remove the installed scheduler."""
        plat = platform.system()
        if plat == "Darwin":
            return self._uninstall_macos()
        elif plat == "Linux":
            return self._uninstall_linux()
        return {"platform": plat, "status": "unsupported"}

    def format_status(self) -> str:
        """Return a human-readable description of the schedule configuration."""
        lines = [
            "HarnessSync Scheduled Sync",
            f"  Interval:     every {self.interval_minutes} minute(s)",
            f"  Run at load:  {'yes' if self.run_at_load else 'no'}",
            f"  Platform:     {platform.system()}",
            f"  Notifications: on change only (HARNESSSYNC_NOTIFY=1)",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Platform-specific install/uninstall
    # ------------------------------------------------------------------

    def _install_macos(self, dry_run: bool) -> dict[str, str]:
        plist_content = self.generate_launchd_plist()
        plist_dir = Path.home() / "Library" / "LaunchAgents"
        plist_path = plist_dir / f"{self.SERVICE_LABEL}.plist"

        result: dict[str, str] = {
            "platform": "Darwin",
            "status": "dry-run" if dry_run else "pending",
            "files": {str(plist_path): plist_content},
        }

        if dry_run:
            return result

        try:
            plist_dir.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(plist_content, encoding="utf-8")
            # Unload existing if present (ignore errors)
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True, timeout=10,
            )
            load_result = subprocess.run(
                ["launchctl", "load", str(plist_path)],
                capture_output=True, text=True, timeout=10,
            )
            if load_result.returncode != 0:
                result["status"] = "partial"
                result["error"] = f"launchctl load: {load_result.stderr.strip()}"
            else:
                result["status"] = "installed"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _install_linux(self, dry_run: bool) -> dict[str, str]:
        service_content, timer_content = self.generate_systemd_unit()
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        service_path = unit_dir / "harnesssync.service"
        timer_path = unit_dir / "harnesssync.timer"

        result: dict[str, str] = {
            "platform": "Linux",
            "status": "dry-run" if dry_run else "pending",
            "files": {
                str(service_path): service_content,
                str(timer_path): timer_content,
            },
        }

        if dry_run:
            return result

        try:
            unit_dir.mkdir(parents=True, exist_ok=True)
            service_path.write_text(service_content, encoding="utf-8")
            timer_path.write_text(timer_content, encoding="utf-8")
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True, timeout=10,
            )
            enable_result = subprocess.run(
                ["systemctl", "--user", "enable", "--now", "harnesssync.timer"],
                capture_output=True, text=True, timeout=10,
            )
            if enable_result.returncode != 0:
                result["status"] = "partial"
                result["error"] = f"systemctl enable: {enable_result.stderr.strip()}"
            else:
                result["status"] = "installed"
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def _uninstall_macos(self) -> dict[str, str]:
        plist_path = (
            Path.home() / "Library" / "LaunchAgents" / f"{self.SERVICE_LABEL}.plist"
        )
        try:
            subprocess.run(
                ["launchctl", "unload", str(plist_path)],
                capture_output=True, timeout=10,
            )
            if plist_path.exists():
                plist_path.unlink()
            return {"platform": "Darwin", "status": "uninstalled"}
        except Exception as e:
            return {"platform": "Darwin", "status": "error", "error": str(e)}

    def _uninstall_linux(self) -> dict[str, str]:
        unit_dir = Path.home() / ".config" / "systemd" / "user"
        try:
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", "harnesssync.timer"],
                capture_output=True, timeout=10,
            )
            for name in ("harnesssync.service", "harnesssync.timer"):
                p = unit_dir / name
                if p.exists():
                    p.unlink()
            subprocess.run(
                ["systemctl", "--user", "daemon-reload"],
                capture_output=True, timeout=10,
            )
            return {"platform": "Linux", "status": "uninstalled"}
        except Exception as e:
            return {"platform": "Linux", "status": "error", "error": str(e)}
