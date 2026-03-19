from __future__ import annotations

"""Weekly Sync Health Digest (Item 25).

Generates a scheduled weekly report summarizing:
- Sync success rate for the past 7 days
- Targets that have drifted (manually edited since last sync)
- Rules that are potentially stale (not cited in 30+ days)
- Most frequently synced files
- New harness capabilities (targets added since last digest)

Designed for users who set-it-and-forget-it: they don't watch individual
sync runs but want to catch creeping config debt before it becomes a problem.

Usage::

    from src.weekly_health_digest import WeeklyHealthDigest

    digest = WeeklyHealthDigest(project_dir)
    report = digest.generate()
    print(digest.format(report))

    # Only generate if a week has passed since last digest
    if digest.should_run_this_week():
        report = digest.generate()
        digest.save_state(report)
        print(digest.format(report))

Or from the /sync-schedule --weekly-digest flag.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DIGEST_STATE_FILE = Path.home() / ".harnesssync" / "weekly_digest_state.json"
_DEFAULT_LOOKBACK_DAYS = 7
_STALE_RULE_WINDOW_DAYS = 30  # rules not cited in 30d = stale candidate


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class DigestReport:
    """Weekly health digest report."""

    period_start: datetime
    period_end: datetime
    total_syncs: int = 0
    successful_syncs: int = 0
    failed_syncs: int = 0
    drifted_targets: list[str] = field(default_factory=list)
    translation_failures: list[str] = field(default_factory=list)
    top_changed_files: list[tuple[str, int]] = field(default_factory=list)
    new_capabilities: list[str] = field(default_factory=list)
    stale_rules: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_syncs == 0:
            return 100.0
        return self.successful_syncs / self.total_syncs * 100

    @property
    def health_score(self) -> int:
        """Return a 0-100 overall health score for the week.

        Deductions:
        - Failed syncs: up to -40 pts proportional to failure rate
        - Drifted targets: -10 pts each (max -30)
        - Translation failures: -5 pts each (max -20)
        - Stale rules: -2 pts each (max -10)
        """
        score = 100
        if self.total_syncs > 0:
            failure_rate = self.failed_syncs / self.total_syncs
            score -= int(failure_rate * 40)
        score -= min(len(self.drifted_targets) * 10, 30)
        score -= min(len(self.translation_failures) * 5, 20)
        score -= min(len(self.stale_rules) * 2, 10)
        return max(0, score)

    @property
    def health_label(self) -> str:
        s = self.health_score
        if s >= 90:
            return "Healthy"
        if s >= 70:
            return "Good"
        if s >= 50:
            return "Degraded"
        return "Critical"


# ---------------------------------------------------------------------------
# Digest generator
# ---------------------------------------------------------------------------

class WeeklyHealthDigest:
    """Generate weekly sync health digest reports.

    Args:
        project_dir: Project root directory.  Defaults to ``CLAUDE_PROJECT_DIR``
                     env var or the current working directory.
        lookback_days: Number of days to include in the report (default: 7).
    """

    def __init__(
        self,
        project_dir: Path | None = None,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    ) -> None:
        self.project_dir = project_dir or Path(
            os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
        )
        self.lookback_days = lookback_days

    # ── Public API ──────────────────────────────────────────────────────────

    def generate(self) -> DigestReport:
        """Generate a weekly health digest from available data sources.

        Reads from changelog, state manager, rule effectiveness tracker, and
        the adapter registry.  Each data source is attempted independently —
        failures are silently ignored so the digest always returns *something*.

        Returns:
            :class:`DigestReport` covering the past ``lookback_days`` days.
        """
        now = datetime.now(timezone.utc)
        period_start = now - timedelta(days=self.lookback_days)
        report = DigestReport(period_start=period_start, period_end=now)

        self._collect_sync_history(report)
        self._collect_drift(report)
        self._collect_stale_rules(report)
        self._collect_new_capabilities(report)

        return report

    def format(self, report: DigestReport) -> str:
        """Format the digest report for terminal output.

        Args:
            report: Output of :meth:`generate`.

        Returns:
            Formatted multi-line string suitable for display or file write.
        """
        period_str = (
            f"{report.period_start.strftime('%Y-%m-%d')} → "
            f"{report.period_end.strftime('%Y-%m-%d')}"
        )
        bar_filled = report.health_score // 5
        score_bar = "█" * bar_filled + "░" * (20 - bar_filled)

        lines = [
            f"Weekly Sync Health Digest  [{period_str}]",
            "=" * 60,
            "",
            f"  Health Score:  {report.health_score}/100  [{score_bar}]  {report.health_label}",
            f"  Sync activity: {report.total_syncs} sync{'s' if report.total_syncs != 1 else ''}"
            f"  ({report.success_rate:.0f}% success rate)",
            "",
        ]

        if report.drifted_targets:
            lines.append(
                f"  ⚠  Drift detected in {len(report.drifted_targets)}"
                f" target{'s' if len(report.drifted_targets) != 1 else ''}:"
            )
            for t in report.drifted_targets:
                lines.append(f"       {t} — manually edited since last sync")
            lines.append(
                "     Run /sync to re-synchronize, or /sync-reverse to promote changes."
            )
            lines.append("")

        if report.translation_failures:
            lines.append(f"  ✗  Translation failures ({len(report.translation_failures)}):")
            for f in report.translation_failures[:5]:
                lines.append(f"       {f}")
            if len(report.translation_failures) > 5:
                lines.append(f"       … and {len(report.translation_failures) - 5} more")
            lines.append("")

        if report.stale_rules:
            lines.append(
                f"  -  Potentially stale rules ({len(report.stale_rules)}"
                f", not cited in {_STALE_RULE_WINDOW_DAYS}+ days):"
            )
            for rule in report.stale_rules[:5]:
                lines.append(f"       {rule}")
            if len(report.stale_rules) > 5:
                lines.append(f"       … and {len(report.stale_rules) - 5} more")
            lines.append("     Run /sync-lint --dead to review and prune unused rules.")
            lines.append("")

        if report.top_changed_files:
            lines.append("  Most frequently synced files this period:")
            for path, count in report.top_changed_files:
                lines.append(f"    {count:>3}×  {path}")
            lines.append("")

        if report.new_capabilities:
            lines.append("  ✦  New capabilities since last digest:")
            for cap in report.new_capabilities:
                lines.append(f"       {cap}")
            lines.append("")

        if not any([
            report.drifted_targets,
            report.translation_failures,
            report.stale_rules,
            report.new_capabilities,
        ]):
            lines.append("  ✓  All clear — no issues detected this week.")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)

    def should_run_this_week(self) -> bool:
        """Return ``True`` if the weekly digest hasn't run yet this week.

        Checks the persisted state file for the last run timestamp.
        """
        state = self._load_state()
        last_str = state.get("last_digest")
        if not last_str:
            return True
        try:
            last = datetime.fromisoformat(last_str)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - last) >= timedelta(days=7)
        except (ValueError, TypeError):
            return True

    def save_state(self, report: DigestReport) -> None:
        """Persist digest state so :meth:`should_run_this_week` works correctly.

        Args:
            report: The digest report that was just generated and shown.
        """
        try:
            from src.adapters import AdapterRegistry
            known_targets = list(AdapterRegistry.list_targets())
        except Exception:
            known_targets = []

        state = {
            "last_digest": report.period_end.isoformat(),
            "known_targets": known_targets,
            "last_health_score": report.health_score,
        }
        try:
            _DIGEST_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _DIGEST_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            pass  # Best-effort; never block the caller

    # ── Data collectors ─────────────────────────────────────────────────────

    def _collect_sync_history(self, report: DigestReport) -> None:
        """Populate sync counts from the changelog manager."""
        try:
            from src.changelog_manager import ChangelogManager
            cm = ChangelogManager(self.project_dir)
            analytics = cm.analytics()
            total = analytics.get("total_syncs", 0)
            report.total_syncs = total
            targets = analytics.get("targets", {})
            if targets and total > 0:
                rates = [v.get("success_rate", 100) for v in targets.values()]
                avg_rate = sum(rates) / len(rates)
                report.successful_syncs = round(total * avg_rate / 100)
                report.failed_syncs = total - report.successful_syncs
            file_counts = analytics.get("file_change_counts", {})
            top = sorted(file_counts.items(), key=lambda x: -x[1])[:5]
            report.top_changed_files = [(p, c) for p, c in top]
        except Exception:
            pass

    def _collect_drift(self, report: DigestReport) -> None:
        """Populate drifted_targets by comparing stored hashes vs current files."""
        try:
            from src.state_manager import StateManager
            from src.source_reader import SourceReader
            from src.utils.hashing import hash_file_sha256
            from src.adapters import AdapterRegistry

            state_manager = StateManager()
            reader = SourceReader(scope="all", project_dir=self.project_dir)
            source_paths = reader.get_source_paths()

            current_hashes: dict[str, str] = {}
            for paths in source_paths.values():
                for p in paths:
                    h = hash_file_sha256(p)
                    if h:
                        current_hashes[str(p)] = h

            for target in AdapterRegistry.list_targets():
                drifted = state_manager.detect_drift(target, current_hashes)
                if drifted:
                    report.drifted_targets.append(target)
        except Exception:
            pass

    def _collect_stale_rules(self, report: DigestReport) -> None:
        """Populate stale_rules from the rule effectiveness tracker."""
        try:
            from src.rule_effectiveness import RuleEffectivenessTracker
            tracker = RuleEffectivenessTracker()
            effectiveness = tracker.score_rules(stale_days=_STALE_RULE_WINDOW_DAYS)
            report.stale_rules = [r.title for r in effectiveness.stale[:10]]
        except Exception:
            pass

    def _collect_new_capabilities(self, report: DigestReport) -> None:
        """Populate new_capabilities by diffing against the last known target list."""
        try:
            last_state = self._load_state()
            last_targets = set(last_state.get("known_targets", []))
            from src.adapters import AdapterRegistry
            current_targets = set(AdapterRegistry.list_targets())
            for t in sorted(current_targets - last_targets):
                report.new_capabilities.append(f"New harness target available: {t}")
        except Exception:
            pass

    def _load_state(self) -> dict:
        try:
            if _DIGEST_STATE_FILE.is_file():
                return json.loads(_DIGEST_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}
