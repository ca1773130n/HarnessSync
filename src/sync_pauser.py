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
