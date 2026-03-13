from __future__ import annotations

"""Scheduled Sync Cron (item 20).

Allows HarnessSync to re-sync on a recurring schedule (hourly, daily, weekly)
without requiring an open Claude Code session.  The schedule is stored as a
lightweight JSON descriptor at ``~/.harnesssync/schedule.json`` and realized
as a crontab entry written via ``crontab -l / crontab -`` on Unix systems.

On macOS, the user's crontab is used.  On other Unix systems the same
mechanism applies.  Windows cron is not supported (returns ``False``).

Usage::

    from src.sync_scheduler import SyncScheduler

    scheduler = SyncScheduler()

    # Add a daily sync at 09:00
    ok, msg = scheduler.add("daily", targets=["codex", "gemini"])

    # List configured schedule
    entry = scheduler.get()
    print(entry)

    # Remove schedule
    scheduler.remove()

Supported interval strings (case-insensitive):
    ``"hourly"``   — every hour at minute 0
    ``"daily"``    — every day at 09:00 (local time)
    ``"weekly"``   — every Monday at 09:00 (local time)
    ``"30m"``      — every 30 minutes
    ``"1h"``       — every 1 hour (same as hourly)
    ``"2h"``       — every 2 hours
    ``"6h"``       — every 6 hours
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


# Marker embedded in crontab so we can find and remove our entry later
_CRON_MARKER = "# harnesssync-cron-v1"

# Default state dir
_STATE_DIR = Path.home() / ".harnesssync"
_SCHEDULE_FILE = _STATE_DIR / "schedule.json"

# Map interval name → cron expression
_INTERVAL_MAP: dict[str, str] = {
    "hourly": "0 * * * *",
    "1h":     "0 * * * *",
    "2h":     "0 */2 * * *",
    "6h":     "0 */6 * * *",
    "daily":  "0 9 * * *",
    "weekly": "0 9 * * 1",
    "30m":    "*/30 * * * *",
    "15m":    "*/15 * * * *",
}


def _resolve_harnesssync_cmd() -> str:
    """Find the best available command to run HarnessSync sync."""
    python = sys.executable or "python3"
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if plugin_root:
        return f"{python} {plugin_root}/src/commands/sync.py --scope all"
    default = Path.home() / ".claude" / "plugins" / "harness-sync" / "src" / "commands" / "sync.py"
    if default.exists():
        return f"{python} {default} --scope all"
    return f"{python} -m harnesssync sync --scope all"


@dataclass
class ScheduleEntry:
    """Describes an active HarnessSync cron schedule.

    Attributes:
        interval:    Human-readable interval string (e.g. ``"daily"``).
        cron_expr:   Cron expression (e.g. ``"0 9 * * *"``).
        targets:     Harness targets to sync (empty = all).
        created_at:  ISO-8601 timestamp when the schedule was added.
        enabled:     Whether the cron entry is active.
    """

    interval: str
    cron_expr: str
    targets: list[str] = field(default_factory=list)
    created_at: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "interval": self.interval,
            "cron_expr": self.cron_expr,
            "targets": self.targets,
            "created_at": self.created_at,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScheduleEntry":
        return cls(
            interval=data.get("interval", ""),
            cron_expr=data.get("cron_expr", ""),
            targets=data.get("targets", []),
            created_at=data.get("created_at", ""),
            enabled=data.get("enabled", True),
        )


class SyncScheduler:
    """Manage a cron-based HarnessSync auto-sync schedule.

    The schedule is stored in two places:
    1. ``~/.harnesssync/schedule.json`` — the human-readable descriptor.
    2. The user's crontab — the actual scheduler entry.

    Args:
        state_dir: Override the state directory (default: ``~/.harnesssync``).
        dry_run:   If ``True``, crontab commands are simulated (not executed).
    """

    def __init__(
        self,
        state_dir: Path | None = None,
        dry_run: bool = False,
    ) -> None:
        self._state_dir = state_dir or _STATE_DIR
        self._schedule_path = self._state_dir / "schedule.json"
        self.dry_run = dry_run

    # ── Public API ───────────────────────────────────────────────────────────

    def add(
        self,
        interval: str,
        targets: list[str] | None = None,
    ) -> tuple[bool, str]:
        """Add (or replace) a HarnessSync cron schedule.

        Args:
            interval: Interval string (``"hourly"``, ``"daily"``, ``"weekly"``,
                      ``"30m"``, ``"2h"``, ``"6h"``).
            targets:  Harness targets to sync (empty list = all).

        Returns:
            ``(success, message)`` tuple.
        """
        interval = interval.strip().lower()
        cron_expr = _INTERVAL_MAP.get(interval)
        if not cron_expr:
            return False, (
                f"Unknown interval '{interval}'. "
                f"Valid: {', '.join(sorted(_INTERVAL_MAP))}"
            )

        if sys.platform == "win32":
            return False, "Cron scheduling is not supported on Windows."

        # Build the cron line
        cmd = _resolve_harnesssync_cmd()
        if targets:
            # Filter-flag accepted by sync.py --targets codex,gemini
            cmd += f" --targets {','.join(targets)}"
        cron_line = f"{cron_expr} {cmd}  {_CRON_MARKER}"

        # Read existing crontab, remove old HarnessSync entry, append new one
        existing = self._read_crontab()
        cleaned = [l for l in existing if _CRON_MARKER not in l]
        cleaned.append(cron_line)
        new_crontab = "\n".join(cleaned) + "\n"

        ok, err = self._write_crontab(new_crontab)
        if not ok:
            return False, f"Failed to write crontab: {err}"

        # Persist descriptor
        from datetime import datetime, timezone
        entry = ScheduleEntry(
            interval=interval,
            cron_expr=cron_expr,
            targets=list(targets or []),
            created_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )
        self._save_entry(entry)

        target_label = f" for {', '.join(targets)}" if targets else ""
        return True, f"HarnessSync scheduled: {interval} ({cron_expr}){target_label}"

    def remove(self) -> tuple[bool, str]:
        """Remove the HarnessSync cron entry.

        Returns:
            ``(success, message)`` tuple.
        """
        if sys.platform == "win32":
            return False, "Cron scheduling is not supported on Windows."

        existing = self._read_crontab()
        cleaned = [l for l in existing if _CRON_MARKER not in l]

        if len(cleaned) == len(existing):
            # Nothing to remove — clean up descriptor anyway
            self._delete_entry()
            return True, "No HarnessSync cron entry found (nothing to remove)."

        new_crontab = "\n".join(cleaned) + "\n" if cleaned else ""
        ok, err = self._write_crontab(new_crontab)
        if not ok:
            return False, f"Failed to update crontab: {err}"

        self._delete_entry()
        return True, "HarnessSync cron schedule removed."

    def get(self) -> ScheduleEntry | None:
        """Return the current schedule descriptor, or ``None`` if not set.

        Returns:
            :class:`ScheduleEntry` or ``None``.
        """
        if not self._schedule_path.exists():
            return None
        try:
            data = json.loads(self._schedule_path.read_text(encoding="utf-8"))
            return ScheduleEntry.from_dict(data)
        except (json.JSONDecodeError, OSError):
            return None

    def is_active(self) -> bool:
        """Return ``True`` if a HarnessSync cron entry exists in the user's crontab.

        Checks the live crontab, not just the local descriptor, so this method
        returns ``False`` if the entry was removed externally.
        """
        if sys.platform == "win32":
            return False
        existing = self._read_crontab()
        return any(_CRON_MARKER in l for l in existing)

    def format_status(self) -> str:
        """Return a human-readable status string.

        Returns:
            Status string suitable for terminal display.
        """
        entry = self.get()
        active = self.is_active()

        if not entry and not active:
            return "HarnessSync scheduled sync: not configured."

        if entry:
            target_label = f" → targets: {', '.join(entry.targets)}" if entry.targets else " → all targets"
            status = "active" if active else "inactive (crontab entry missing)"
            return (
                f"HarnessSync scheduled sync: {entry.interval} ({entry.cron_expr}){target_label}"
                f"\n  Status: {status}"
                f"\n  Added: {entry.created_at[:19].replace('T', ' ') if entry.created_at else 'unknown'}"
            )

        return f"HarnessSync scheduled sync: crontab active but descriptor missing."

    # ── Internal helpers ────────────────────────────────────────────────────

    def _read_crontab(self) -> list[str]:
        """Read the current user crontab as a list of lines."""
        if self.dry_run:
            return []
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.splitlines()
            # Exit code 1 = no crontab yet — that's fine
            return []
        except (subprocess.SubprocessError, FileNotFoundError, OSError):
            return []

    def _write_crontab(self, content: str) -> tuple[bool, str]:
        """Write content to the user's crontab.

        Returns:
            ``(success, error_message)`` tuple.
        """
        if self.dry_run:
            return True, ""
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".cron", delete=False, encoding="utf-8"
            ) as tf:
                tf.write(content)
                tmp = tf.name
            result = subprocess.run(
                ["crontab", tmp],
                capture_output=True,
                text=True,
                timeout=5,
            )
            os.unlink(tmp)
            if result.returncode != 0:
                return False, result.stderr.strip() or "crontab returned non-zero"
            return True, ""
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
            return False, str(exc)

    def _save_entry(self, entry: ScheduleEntry) -> None:
        """Persist the schedule descriptor to disk."""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._schedule_path.write_text(
            json.dumps(entry.to_dict(), indent=2) + "\n",
            encoding="utf-8",
        )

    def _delete_entry(self) -> None:
        """Remove the schedule descriptor file."""
        try:
            self._schedule_path.unlink(missing_ok=True)
        except OSError:
            pass
