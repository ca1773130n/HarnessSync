from __future__ import annotations

"""Sync Pause / Lockdown Mode for HarnessSync.

Allows users to temporarily suspend all auto-sync operations so that manual
edits to target harness configs are not immediately overwritten.

State is stored in ``~/.claude/harnesssync_pause.json`` so it persists across
processes (e.g. when auto-sync is triggered from a PostToolUse hook in a
different shell session).

Pause file schema:
    {
        "paused": true,
        "reason": "debugging Gemini config",
        "paused_at": "2026-03-12T10:00:00Z",
        "resume_at": "2026-03-12T11:00:00Z"   // optional auto-resume timestamp
    }

Usage::

    from src.sync_pauser import SyncPauser

    pauser = SyncPauser()
    pauser.pause(reason="testing", duration_minutes=30)

    if pauser.is_paused():
        # skip sync
        ...

    pauser.resume()
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


_PAUSE_FILENAME = "harnesssync_pause.json"


class SyncPauser:
    """Manages sync pause/resume state for HarnessSync.

    Pause state is stored in a JSON file under the Claude Code home
    directory (default: ~/.claude/).  Any HarnessSync process — commands,
    hooks, or the orchestrator — can check this file before running sync.
    """

    def __init__(self, cc_home: Path | None = None):
        """Initialise SyncPauser.

        Args:
            cc_home: Claude Code config home directory.
                     Defaults to ~/.claude/.
        """
        self._cc_home = cc_home or (Path.home() / ".claude")
        self._pause_file = self._cc_home / _PAUSE_FILENAME

    # ------------------------------------------------------------------
    # Core state operations
    # ------------------------------------------------------------------

    def pause(
        self,
        reason: str = "",
        duration_minutes: int | None = None,
    ) -> dict:
        """Pause sync operations.

        Args:
            reason: Human-readable reason for pausing (e.g. "debugging Codex").
            duration_minutes: If set, auto-resume after this many minutes.
                              If None, pause is indefinite until manually resumed.

        Returns:
            The pause state dict that was written.
        """
        now = datetime.now(tz=timezone.utc)
        state: dict = {
            "paused": True,
            "reason": reason or "manual pause",
            "paused_at": now.isoformat(),
            "resume_at": None,
        }
        if duration_minutes is not None and duration_minutes > 0:
            resume_dt = now + timedelta(minutes=duration_minutes)
            state["resume_at"] = resume_dt.isoformat()

        self._write_state(state)
        return state

    def resume(self) -> bool:
        """Resume sync operations by removing the pause file.

        Returns:
            True if pause was active and has been lifted.
            False if sync was not paused.
        """
        if not self._pause_file.exists():
            return False
        try:
            self._pause_file.unlink()
        except OSError:
            pass
        return True

    def is_paused(self) -> bool:
        """Return True if sync is currently paused.

        Automatically expires a timed pause if ``resume_at`` has passed.
        """
        state = self._read_state()
        if not state or not state.get("paused"):
            return False

        # Check timed auto-resume
        resume_at_str = state.get("resume_at")
        if resume_at_str:
            try:
                resume_at = datetime.fromisoformat(resume_at_str)
                now = datetime.now(tz=timezone.utc)
                if now >= resume_at:
                    # Auto-resume: clean up pause file
                    self.resume()
                    return False
            except (ValueError, TypeError):
                pass

        return True

    def get_status(self) -> dict:
        """Return the current pause status as a human-readable dict.

        Returns:
            Dict with keys:
              - paused: bool
              - reason: str
              - paused_at: str | None
              - resume_at: str | None
              - time_remaining: str | None  (e.g. "28m 14s")
        """
        state = self._read_state()
        paused = self.is_paused()  # also handles auto-expiry

        if not paused or not state:
            return {
                "paused": False,
                "reason": "",
                "paused_at": None,
                "resume_at": None,
                "time_remaining": None,
            }

        time_remaining: str | None = None
        resume_at_str = state.get("resume_at")
        if resume_at_str:
            try:
                resume_at = datetime.fromisoformat(resume_at_str)
                now = datetime.now(tz=timezone.utc)
                remaining = resume_at - now
                total_secs = max(0, int(remaining.total_seconds()))
                mins, secs = divmod(total_secs, 60)
                time_remaining = f"{mins}m {secs}s"
            except (ValueError, TypeError):
                pass

        return {
            "paused": True,
            "reason": state.get("reason", ""),
            "paused_at": state.get("paused_at"),
            "resume_at": resume_at_str,
            "time_remaining": time_remaining,
        }

    def format_status(self) -> str:
        """Return a formatted human-readable status string."""
        status = self.get_status()
        if not status["paused"]:
            return "Sync is active (not paused)."

        lines = ["Sync is PAUSED."]
        if status["reason"]:
            lines.append(f"  Reason:    {status['reason']}")
        if status["paused_at"]:
            lines.append(f"  Paused at: {status['paused_at']}")
        if status["resume_at"]:
            remaining = status.get("time_remaining", "")
            lines.append(f"  Auto-resume at: {status['resume_at']}")
            if remaining:
                lines.append(f"  Time remaining: {remaining}")
        else:
            lines.append("  Auto-resume: disabled (run /sync-pause --resume to re-enable)")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write_state(self, state: dict) -> None:
        try:
            self._cc_home.mkdir(parents=True, exist_ok=True)
            self._pause_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def _read_state(self) -> dict | None:
        if not self._pause_file.exists():
            return None
        try:
            raw = self._pause_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None


# ──────────────────────────────────────────────────────────────────────────────
# Smart Sync Scheduler (Item 22)
# ──────────────────────────────────────────────────────────────────────────────

_ACTIVITY_LOG_FILE = "harnesssync_activity.jsonl"
_SCHEDULE_CONFIG_FILE = "harnesssync_schedule.json"


class SmartSyncScheduler:
    """Schedule background syncs during idle periods based on work patterns.

    Records sync events and activity signals to a JSONL log so patterns
    can be detected. Uses the activity log to decide whether the current
    moment is "idle" (safe to auto-sync) or "active" (user is coding).

    Activity is inferred from:
    - Time since last recorded tool use / commit
    - Hour-of-day histogram from the activity log
    - Whether the session is currently paused

    Usage::

        scheduler = SmartSyncScheduler()
        scheduler.record_activity()          # call on each tool use
        if scheduler.is_idle():
            # trigger background sync
            ...
        next_slot = scheduler.next_idle_window()
        print(f"Best next sync window: {next_slot}")
    """

    # Idle threshold: seconds since last activity before declaring idle
    DEFAULT_IDLE_THRESHOLD_SECONDS = 300  # 5 minutes

    def __init__(self, cc_home: Path | None = None):
        self._cc_home = cc_home or (Path.home() / ".claude")
        self._log_file = self._cc_home / _ACTIVITY_LOG_FILE
        self._config_file = self._cc_home / _SCHEDULE_CONFIG_FILE
        self._pauser = SyncPauser(cc_home=cc_home)

    # ------------------------------------------------------------------
    # Activity recording
    # ------------------------------------------------------------------

    def record_activity(self, event: str = "tool_use") -> None:
        """Log an activity event (call on each tool invocation or save).

        Args:
            event: Short label for the activity (e.g. "tool_use", "save", "commit").
        """
        entry = {
            "ts": datetime.now(tz=timezone.utc).isoformat(),
            "event": event,
            "hour": datetime.now().hour,
            "weekday": datetime.now().weekday(),  # 0=Monday
        }
        try:
            self._cc_home.mkdir(parents=True, exist_ok=True)
            with self._log_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def record_sync(self) -> None:
        """Log a sync event — used to avoid back-to-back syncs."""
        self.record_activity("sync")

    # ------------------------------------------------------------------
    # Idle detection
    # ------------------------------------------------------------------

    def is_idle(
        self,
        idle_threshold_seconds: int | None = None,
    ) -> bool:
        """Return True if the user appears to be idle (safe to auto-sync).

        Considers:
        - Seconds since the last recorded activity event
        - Whether sync is currently paused

        Args:
            idle_threshold_seconds: Override the default idle threshold.

        Returns:
            True if idle, False if the user appears to be actively coding.
        """
        if self._pauser.is_paused():
            return False

        threshold = idle_threshold_seconds or self._load_threshold()
        last_ts = self._last_activity_timestamp()
        if last_ts is None:
            return True  # No history → assume idle

        elapsed = (datetime.now(tz=timezone.utc) - last_ts).total_seconds()
        return elapsed >= threshold

    def seconds_since_last_activity(self) -> float | None:
        """Return seconds since the last recorded activity, or None if unknown."""
        last_ts = self._last_activity_timestamp()
        if last_ts is None:
            return None
        return (datetime.now(tz=timezone.utc) - last_ts).total_seconds()

    # ------------------------------------------------------------------
    # Work pattern analysis
    # ------------------------------------------------------------------

    def active_hours_histogram(self, last_n_days: int = 14) -> dict[int, int]:
        """Build an hour-of-day activity histogram from the log.

        Args:
            last_n_days: Only consider events within this many days.

        Returns:
            Dict mapping hour (0-23) → event count.
        """
        histogram: dict[int, int] = {h: 0 for h in range(24)}
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=last_n_days)

        for entry in self._read_log():
            try:
                ts = datetime.fromisoformat(entry["ts"])
                if ts < cutoff:
                    continue
                hour = entry.get("hour", ts.hour)
                histogram[int(hour)] = histogram.get(int(hour), 0) + 1
            except (KeyError, ValueError):
                pass

        return histogram

    def next_idle_window(self, look_ahead_hours: int = 24) -> str:
        """Predict the next low-activity window within the next N hours.

        Uses the hour-of-day histogram to find the quietest upcoming hour.

        Args:
            look_ahead_hours: How many hours ahead to consider (max 24).

        Returns:
            ISO-format datetime string of the predicted idle window start,
            or "now" if the current hour is already the quietest.
        """
        histogram = self.active_hours_histogram()
        now = datetime.now(tz=timezone.utc)

        best_hour_offset = 0
        best_count = histogram.get(now.hour, 0)

        for offset in range(1, min(look_ahead_hours, 24)):
            hour = (now.hour + offset) % 24
            count = histogram.get(hour, 0)
            if count < best_count:
                best_count = count
                best_hour_offset = offset

        if best_hour_offset == 0:
            return "now"

        window_start = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=best_hour_offset)
        return window_start.isoformat()

    def configure(
        self,
        idle_threshold_seconds: int | None = None,
        enabled: bool | None = None,
    ) -> None:
        """Persist smart scheduling configuration.

        Args:
            idle_threshold_seconds: Override idle detection threshold.
            enabled: Whether smart scheduling is enabled at all.
        """
        config = self._load_config()
        if idle_threshold_seconds is not None:
            config["idle_threshold_seconds"] = idle_threshold_seconds
        if enabled is not None:
            config["enabled"] = enabled
        try:
            self._cc_home.mkdir(parents=True, exist_ok=True)
            self._config_file.write_text(
                json.dumps(config, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def format_status(self) -> str:
        """Return a human-readable status summary."""
        idle = self.is_idle()
        elapsed = self.seconds_since_last_activity()
        threshold = self._load_threshold()
        next_window = self.next_idle_window()

        lines = [
            "Smart Sync Scheduler",
            "-" * 35,
            f"  Status:          {'idle — safe to sync' if idle else 'active — sync deferred'}",
        ]
        if elapsed is not None:
            lines.append(f"  Last activity:   {elapsed:.0f}s ago")
        else:
            lines.append("  Last activity:   (no history)")
        lines.append(f"  Idle threshold:  {threshold}s")
        if not idle:
            lines.append(f"  Next idle window: {next_window}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _last_activity_timestamp(self) -> datetime | None:
        """Return the timestamp of the most recent non-sync event."""
        last: datetime | None = None
        for entry in self._read_log():
            if entry.get("event") == "sync":
                continue
            try:
                ts = datetime.fromisoformat(entry["ts"])
                if last is None or ts > last:
                    last = ts
            except (KeyError, ValueError):
                pass
        return last

    def _read_log(self) -> list[dict]:
        """Read all activity log entries."""
        if not self._log_file.exists():
            return []
        entries: list[dict] = []
        try:
            for line in self._log_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        except OSError:
            pass
        return entries

    def _load_config(self) -> dict:
        if not self._config_file.exists():
            return {}
        try:
            return json.loads(self._config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _load_threshold(self) -> int:
        config = self._load_config()
        return int(config.get("idle_threshold_seconds", self.DEFAULT_IDLE_THRESHOLD_SECONDS))
