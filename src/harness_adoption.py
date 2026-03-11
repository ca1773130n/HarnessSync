from __future__ import annotations

"""Harness adoption insights analyzer.

Analyzes sync state, file access timestamps, and changelog data to report
which target harnesses are actively used versus stale. Surfaces harnesses
that haven't been touched in N days so users can prune dead targets.

Signals used:
1. Last sync timestamp per target (from StateManager)
2. File modification time of key harness config files (mtime)
3. Sync frequency over the trailing 30-day window (from changelog)
4. Sync success rate per target

A harness is flagged as "stale" when:
- Its last sync was > stale_days ago, OR
- Its config files haven't been read/modified since last sync

Output is a dict per target with adoption metrics and a human-readable
recommendation (keep / review / prune).
"""

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from src.state_manager import StateManager


# Default staleness threshold in days
DEFAULT_STALE_DAYS = 30

# Key config files per harness used to detect active reads (mtime proxy)
_TARGET_CONFIG_FILES: dict[str, list[str]] = {
    "codex": ["AGENTS.md", ".agents/skills"],
    "gemini": ["GEMINI.md", ".gemini/skills"],
    "opencode": ["opencode.json", ".opencode/"],
    "cursor": [".cursor/rules/"],
    "aider": ["CONVENTIONS.md", ".aider.conf.yml"],
    "windsurf": [".windsurfrules", ".windsurf/"],
    "vscode": [".github/copilot-instructions.md", ".codeium/instructions.md"],
}

# Changelog entry pattern: sync events per target
_CHANGELOG_TARGET_RE = re.compile(r"\*\*Target:\*\*\s*(\w+)", re.IGNORECASE)
_CHANGELOG_DATE_RE = re.compile(r"^#{1,3}\s+(\d{4}-\d{2}-\d{2})", re.MULTILINE)


class HarnessAdoptionReport:
    """Per-harness adoption metrics."""

    def __init__(
        self,
        target: str,
        last_sync: str | None,
        days_since_sync: float | None,
        last_file_touch: str | None,
        days_since_touch: float | None,
        sync_count_30d: int,
        success_rate: float,
        config_files_exist: bool,
        stale: bool,
        recommendation: str,
    ):
        self.target = target
        self.last_sync = last_sync
        self.days_since_sync = days_since_sync
        self.last_file_touch = last_file_touch
        self.days_since_touch = days_since_touch
        self.sync_count_30d = sync_count_30d
        self.success_rate = success_rate
        self.config_files_exist = config_files_exist
        self.stale = stale
        self.recommendation = recommendation

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "last_sync": self.last_sync,
            "days_since_sync": round(self.days_since_sync, 1) if self.days_since_sync is not None else None,
            "last_file_touch": self.last_file_touch,
            "days_since_touch": round(self.days_since_touch, 1) if self.days_since_touch is not None else None,
            "sync_count_30d": self.sync_count_30d,
            "success_rate": round(self.success_rate * 100, 1),
            "config_files_exist": self.config_files_exist,
            "stale": self.stale,
            "recommendation": self.recommendation,
        }


class HarnessAdoptionAnalyzer:
    """Analyzes harness adoption using sync state and file timestamps.

    Args:
        project_dir: Project root directory.
        state_manager: StateManager instance (created if None).
        stale_days: Days without activity before flagging as stale.
    """

    def __init__(
        self,
        project_dir: Path | None = None,
        state_manager: StateManager | None = None,
        stale_days: int = DEFAULT_STALE_DAYS,
    ):
        self.project_dir = project_dir or Path.cwd()
        self.state_manager = state_manager or StateManager()
        self.stale_days = stale_days
        self._now = time.time()

    def analyze(self, targets: list[str] | None = None) -> list[HarnessAdoptionReport]:
        """Run adoption analysis for all (or specified) targets.

        Args:
            targets: Target names to analyze. None = all tracked targets.

        Returns:
            List of HarnessAdoptionReport, sorted by staleness descending.
        """
        state = self.state_manager._state
        all_targets_in_state = set()

        # Collect targets from v2 accounts structure
        accounts = state.get("accounts", {})
        for account_data in accounts.values():
            all_targets_in_state.update(account_data.get("targets", {}).keys())

        # Also from flat targets (v1 compat)
        all_targets_in_state.update(state.get("targets", {}).keys())

        if targets is None:
            targets = sorted(all_targets_in_state) or list(_TARGET_CONFIG_FILES.keys())

        reports: list[HarnessAdoptionReport] = []
        changelog_counts = self._count_changelog_syncs()

        for target in targets:
            report = self._analyze_target(target, changelog_counts)
            reports.append(report)

        # Sort: stale first, then by days_since_sync descending
        reports.sort(key=lambda r: (not r.stale, r.days_since_sync or 0), reverse=True)
        return reports

    def format_report(self, reports: list[HarnessAdoptionReport]) -> str:
        """Format adoption reports as human-readable text.

        Args:
            reports: List of HarnessAdoptionReport from analyze().

        Returns:
            Multi-line formatted string.
        """
        if not reports:
            return "No harness sync data found. Run /sync first to generate adoption metrics."

        lines = ["HarnessSync Adoption Insights", "=" * 50, ""]

        for r in reports:
            icon = "⚠" if r.stale else "✓"
            lines.append(f"{icon} {r.target.upper()}")

            if r.days_since_sync is not None:
                lines.append(f"  Last sync:        {r.last_sync} ({r.days_since_sync:.0f}d ago)")
            else:
                lines.append("  Last sync:        never")

            if r.days_since_touch is not None:
                lines.append(f"  Last file touch:  {r.last_file_touch} ({r.days_since_touch:.0f}d ago)")
            else:
                lines.append("  Last file touch:  unknown")

            lines.append(f"  Syncs (30d):      {r.sync_count_30d}")
            lines.append(f"  Success rate:     {r.success_rate * 100:.0f}%")
            lines.append(f"  Config files:     {'present' if r.config_files_exist else 'missing'}")
            lines.append(f"  → {r.recommendation}")
            lines.append("")

        stale_count = sum(1 for r in reports if r.stale)
        if stale_count:
            lines.append(f"Action needed: {stale_count} harness(es) appear stale (>{self.stale_days}d without activity).")
            lines.append("Review them with /sync-status or remove with /sync-setup.")
        else:
            lines.append("All harnesses appear active. No pruning needed.")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _analyze_target(self, target: str, changelog_counts: dict[str, int]) -> HarnessAdoptionReport:
        """Analyze a single target and return its report."""
        target_status = self.state_manager.get_target_status(target)

        last_sync_str: str | None = None
        days_since_sync: float | None = None
        success_rate = 1.0

        if target_status:
            last_sync_str = target_status.get("last_sync")
            if last_sync_str:
                days_since_sync = self._days_since_iso(last_sync_str)

            # Estimate success rate from status field
            status = target_status.get("status", "success")
            if status == "failed":
                success_rate = 0.0
            elif status == "partial":
                success_rate = 0.5

        # File modification times
        last_file_touch_str, days_since_touch = self._latest_file_touch(target)
        config_files_exist = last_file_touch_str is not None

        sync_count_30d = changelog_counts.get(target, 0)

        # Staleness determination
        stale = self._is_stale(days_since_sync, days_since_touch, sync_count_30d)

        recommendation = self._recommendation(
            stale, days_since_sync, days_since_touch, sync_count_30d, config_files_exist
        )

        return HarnessAdoptionReport(
            target=target,
            last_sync=last_sync_str,
            days_since_sync=days_since_sync,
            last_file_touch=last_file_touch_str,
            days_since_touch=days_since_touch,
            sync_count_30d=sync_count_30d,
            success_rate=success_rate,
            config_files_exist=config_files_exist,
            stale=stale,
            recommendation=recommendation,
        )

    def _days_since_iso(self, iso_str: str) -> float | None:
        """Parse ISO 8601 datetime string and return days elapsed."""
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            elapsed = self._now - dt.timestamp()
            return max(0.0, elapsed / 86400)
        except (ValueError, AttributeError):
            return None

    def _latest_file_touch(self, target: str) -> tuple[str | None, float | None]:
        """Return (ISO timestamp, days_ago) of the most recently modified config file."""
        patterns = _TARGET_CONFIG_FILES.get(target, [])
        latest_mtime: float | None = None

        for pattern in patterns:
            path = self.project_dir / pattern
            if path.is_file():
                mtime = path.stat().st_mtime
                if latest_mtime is None or mtime > latest_mtime:
                    latest_mtime = mtime
            elif path.is_dir():
                for child in path.rglob("*"):
                    if child.is_file():
                        mtime = child.stat().st_mtime
                        if latest_mtime is None or mtime > latest_mtime:
                            latest_mtime = mtime

        if latest_mtime is None:
            return None, None

        iso_str = datetime.fromtimestamp(latest_mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        days_ago = (self._now - latest_mtime) / 86400
        return iso_str, max(0.0, days_ago)

    def _count_changelog_syncs(self) -> dict[str, int]:
        """Count sync events per target in the last 30 days from changelog."""
        counts: dict[str, int] = {}
        changelog_path = self.project_dir / ".harness-sync" / "changelog.md"
        if not changelog_path.exists():
            return counts

        try:
            text = changelog_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return counts

        # Find entries from the last 30 days
        cutoff_ts = self._now - (30 * 86400)
        current_date_ts: float | None = None

        for line in text.splitlines():
            # Look for date headers
            date_m = _CHANGELOG_DATE_RE.match(line)
            if date_m:
                try:
                    dt = datetime.strptime(date_m.group(1), "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    current_date_ts = dt.timestamp()
                except ValueError:
                    current_date_ts = None
                continue

            # Count target lines within 30-day window
            if current_date_ts is not None and current_date_ts >= cutoff_ts:
                target_m = _CHANGELOG_TARGET_RE.search(line)
                if target_m:
                    t = target_m.group(1).lower()
                    counts[t] = counts.get(t, 0) + 1

        return counts

    def _is_stale(
        self,
        days_since_sync: float | None,
        days_since_touch: float | None,
        sync_count_30d: int,
    ) -> bool:
        """Return True if the target appears stale."""
        # If never synced, not considered stale (just unconfigured)
        if days_since_sync is None and sync_count_30d == 0:
            return False

        # Stale if last sync was long ago AND no file activity
        if days_since_sync is not None and days_since_sync > self.stale_days:
            if sync_count_30d == 0:
                return True
            if days_since_touch is not None and days_since_touch > self.stale_days:
                return True

        return False

    def _recommendation(
        self,
        stale: bool,
        days_since_sync: float | None,
        days_since_touch: float | None,
        sync_count_30d: int,
        config_files_exist: bool,
    ) -> str:
        """Generate human-readable recommendation."""
        if days_since_sync is None and not config_files_exist:
            return "Never synced and no config files found — target may not be in use."

        if stale:
            if not config_files_exist:
                return f"Config files missing after {days_since_sync:.0f}d — harness may have been uninstalled. Consider removing with /sync-setup."
            return f"No activity for {days_since_sync:.0f}d. Verify harness is still in use or run /sync-setup to remove."

        if sync_count_30d == 0 and days_since_sync and days_since_sync > 14:
            return "Low recent activity. Consider scheduling with /sync or checking if harness is still active."

        return "Active — no action needed."
