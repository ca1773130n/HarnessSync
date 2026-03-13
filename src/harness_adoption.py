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


# Quick-start snippets shown after a successful first sync to a harness.
# Provides the user with an immediate "try it" command to validate the sync.
_QUICK_START_SNIPPETS: dict[str, list[str]] = {
    "codex": [
        "Your Codex is now configured with HarnessSync!",
        "  Try: codex --help",
        "  Run your first agent: codex run <agent-name>",
        "  Or start an interactive session: codex chat",
    ],
    "gemini": [
        "Your Gemini CLI is now configured with HarnessSync!",
        "  Try: gemini --help",
        "  Run an agent: gemini run <agent-name>",
        "  Or start a chat: gemini",
    ],
    "opencode": [
        "Your OpenCode is now configured with HarnessSync!",
        "  Try: opencode --help",
        "  Start coding: opencode",
        "  List available agents: opencode agents",
    ],
    "cursor": [
        "Your Cursor rules are now synced by HarnessSync!",
        "  Open Cursor and check .cursor/rules/ for your synced rules.",
        "  Try Cursor's Composer (Ctrl+Shift+I) to use your synced skills.",
        "  To verify: ls .cursor/rules/",
    ],
    "aider": [
        "Your Aider configuration is now synced by HarnessSync!",
        "  Try: aider --help",
        "  Start a session: aider",
        "  Your conventions are in CONVENTIONS.md — aider reads it automatically.",
    ],
    "windsurf": [
        "Your Windsurf is now configured with HarnessSync!",
        "  Open Windsurf and check .windsurfrules for your synced rules.",
        "  Windsurf reads .windsurfrules automatically at session start.",
    ],
}


def get_quick_start_nudge(target: str, is_first_sync: bool = False) -> str | None:
    """Return a quick-start nudge string for a newly synced harness.

    Shows the user an actionable 'try it now' snippet immediately after a
    successful first sync, reducing the gap between 'sync succeeded' and
    'user actually using the new harness.'

    Args:
        target: Target harness name.
        is_first_sync: If True, always show the nudge. If False, only show
                       for targets that appear to not have been used yet.

    Returns:
        Quick-start text string, or None if no nudge available for this target.
    """
    snippet_lines = _QUICK_START_SNIPPETS.get(target)
    if not snippet_lines:
        return None

    lines = ["", "─" * 50] + snippet_lines + ["─" * 50]
    return "\n".join(lines)


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


# ──────────────────────────────────────────────────────────────────────────────
# Per-harness usage attribution (item 28)
# ──────────────────────────────────────────────────────────────────────────────

# Shell history file patterns to check for harness invocations
_SHELL_HISTORY_FILES = [
    Path.home() / ".bash_history",
    Path.home() / ".zsh_history",
    Path.home() / ".local" / "share" / "fish" / "fish_history",
]

# CLI executable names per harness to search for in shell history
_HARNESS_CLI_NAMES: dict[str, list[str]] = {
    "codex":    ["codex"],
    "gemini":   ["gemini"],
    "opencode": ["opencode"],
    "cursor":   ["cursor"],
    "windsurf": ["windsurf"],
    "aider":    ["aider"],
    "cline":    ["cline"],
    "continue": ["continue"],
    "zed":      ["zed"],
    "neovim":   ["nvim", "neovim"],
}


class UsageAttributionReport:
    """Per-harness actual usage metrics derived from shell history."""

    def __init__(
        self,
        target: str,
        invocation_count: int,
        last_invocation: str | None,
        share_of_total: float,
        rules_in_source: int,
        rules_synced: int,
        rules_coverage_pct: float,
    ):
        self.target = target
        self.invocation_count = invocation_count
        self.last_invocation = last_invocation
        self.share_of_total = share_of_total         # 0.0 – 1.0
        self.rules_in_source = rules_in_source       # total rules in CC source
        self.rules_synced = rules_synced             # rules that made it to this target
        self.rules_coverage_pct = rules_coverage_pct  # synced / source

    def insight(self) -> str:
        """Return an actionable insight sentence."""
        if self.invocation_count == 0:
            return f"Not used in shell history — verify if {self.target} is actively used."
        if self.share_of_total > 0.5 and self.rules_coverage_pct < 0.7:
            return (
                f"Primary harness ({self.share_of_total*100:.0f}% usage) but only "
                f"{self.rules_coverage_pct*100:.0f}% rule coverage — prioritize sync fidelity."
            )
        if self.share_of_total < 0.1 and self.invocation_count > 0:
            return f"Rarely used ({self.share_of_total*100:.0f}%) — low priority for sync."
        if self.rules_coverage_pct < 0.5:
            return f"Low rule coverage ({self.rules_coverage_pct*100:.0f}%) — some rules may be dropped."
        return f"Healthy — {self.share_of_total*100:.0f}% usage, {self.rules_coverage_pct*100:.0f}% rule coverage."


class UsageAttributionAnalyzer:
    """Analyzes shell history to attribute usage to specific harnesses.

    Reads shell history files (.bash_history, .zsh_history, fish_history)
    to count invocations of each harness CLI. Cross-references with sync
    state to compute how well each harness's rules coverage matches its usage.

    Args:
        project_dir: Project root directory.
        state_manager: StateManager for sync state (created if None).
        history_files: Override shell history file paths for testing.
    """

    def __init__(
        self,
        project_dir: Path | None = None,
        state_manager=None,
        history_files: list[Path] | None = None,
    ):
        self.project_dir = project_dir or Path.cwd()
        if state_manager is None:
            from src.state_manager import StateManager
            state_manager = StateManager()
        self.state_manager = state_manager
        self.history_files = history_files or _SHELL_HISTORY_FILES

    def _count_invocations(self) -> dict[str, int]:
        """Count CLI invocations per harness from shell history files."""
        counts: dict[str, int] = {h: 0 for h in _HARNESS_CLI_NAMES}

        for history_path in self.history_files:
            if not history_path.exists():
                continue
            try:
                text = history_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for harness, cli_names in _HARNESS_CLI_NAMES.items():
                for cli in cli_names:
                    # Count lines starting with the CLI command (shell history format)
                    # zsh history has ": timestamp:elapsed;command" format
                    import re as _re
                    pattern = _re.compile(
                        rf"(?m)^(?::\s*\d+:\d+;)?{_re.escape(cli)}\b"
                    )
                    counts[harness] += len(pattern.findall(text))

        return counts

    def _get_last_invocation(self, cli_names: list[str]) -> str | None:
        """Find the most recent invocation date of a CLI from zsh history."""
        latest_ts: int | None = None

        for history_path in self.history_files:
            if not history_path.exists():
                continue
            if "zsh" not in str(history_path):
                continue  # Only zsh history has timestamps
            try:
                text = history_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            import re as _re
            for cli in cli_names:
                # zsh format: ": timestamp:elapsed;command"
                for m in _re.finditer(rf"^:\s*(\d+):\d+;{_re.escape(cli)}\b", text, _re.MULTILINE):
                    ts = int(m.group(1))
                    if latest_ts is None or ts > latest_ts:
                        latest_ts = ts

        if latest_ts is None:
            return None
        from datetime import datetime, timezone
        return datetime.fromtimestamp(latest_ts, tz=timezone.utc).strftime("%Y-%m-%d")

    def _get_rules_coverage(self, target: str, total_source_rules: int) -> int:
        """Estimate number of source rules that synced to target."""
        target_status = self.state_manager.get_target_status(target)
        if not target_status:
            return 0
        # Use synced count from last sync state if available
        last_counts = target_status.get("last_sync_counts", {})
        return last_counts.get("rules", 0) or max(0, total_source_rules - 1)

    def analyze(
        self,
        targets: list[str] | None = None,
        total_source_rules: int = 10,
    ) -> list[UsageAttributionReport]:
        """Analyze usage attribution across harnesses.

        Args:
            targets: Harnesses to analyze (default: all known).
            total_source_rules: Total rules in Claude Code source (for coverage calc).

        Returns:
            List of UsageAttributionReport sorted by invocation_count descending.
        """
        if targets is None:
            targets = list(_HARNESS_CLI_NAMES.keys())

        counts = self._count_invocations()
        total_invocations = max(1, sum(counts.get(t, 0) for t in targets))

        reports: list[UsageAttributionReport] = []
        for target in targets:
            inv_count = counts.get(target, 0)
            cli_names = _HARNESS_CLI_NAMES.get(target, [target])
            last_inv = self._get_last_invocation(cli_names)
            synced_rules = self._get_rules_coverage(target, total_source_rules)
            coverage_pct = synced_rules / total_source_rules if total_source_rules > 0 else 1.0

            reports.append(UsageAttributionReport(
                target=target,
                invocation_count=inv_count,
                last_invocation=last_inv,
                share_of_total=inv_count / total_invocations,
                rules_in_source=total_source_rules,
                rules_synced=synced_rules,
                rules_coverage_pct=min(1.0, coverage_pct),
            ))

        reports.sort(key=lambda r: r.invocation_count, reverse=True)
        return reports

    def format_report(self, reports: list[UsageAttributionReport]) -> str:
        """Format usage attribution report as human-readable text."""
        if not reports:
            return "No usage data available."

        total = sum(r.invocation_count for r in reports)
        lines = [
            "Per-Harness Usage Attribution",
            "=" * 50,
            f"Total harness invocations found in shell history: {total}",
            "",
        ]

        for r in reports:
            bar_len = int(r.share_of_total * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            lines.append(
                f"{r.target:<12} {bar}  "
                f"{r.share_of_total*100:4.0f}%  ({r.invocation_count} invocations)"
            )
            coverage_bar = int(r.rules_coverage_pct * 10)
            lines.append(
                f"{'':12}  Rule coverage: "
                f"{'█' * coverage_bar}{'░' * (10 - coverage_bar)}  "
                f"{r.rules_coverage_pct*100:.0f}%"
            )
            if r.last_invocation:
                lines.append(f"{'':12}  Last used: {r.last_invocation}")
            lines.append(f"{'':12}  ↳ {r.insight()}")
            lines.append("")

        # Summary insights
        if total == 0:
            lines.append(
                "Note: No harness invocations found in shell history.\n"
                "Shell history may be in a non-standard location or disabled."
            )
        else:
            primary = max(reports, key=lambda r: r.invocation_count)
            if primary.invocation_count > 0:
                lines.append(
                    f"Primary harness: {primary.target} "
                    f"({primary.share_of_total*100:.0f}% of usage)"
                )
                low_coverage = [
                    r for r in reports
                    if r.invocation_count > 0 and r.rules_coverage_pct < 0.7
                ]
                if low_coverage:
                    names = ", ".join(r.target for r in low_coverage)
                    lines.append(
                        f"Low coverage in active harnesses: {names}\n"
                        "Consider running /sync-matrix to see what's being dropped."
                    )

        return "\n".join(lines)


def generate_weekly_digest(
    project_dir: Path | None = None,
    targets: list[str] | None = None,
    state_manager=None,
) -> str:
    """Generate a weekly analytics digest across all configured harnesses.

    Summarises per-harness invocation counts found in shell history,
    highlights the most-used harness, flags harnesses that were synced
    but never invoked, and surfaces rules coverage gaps.

    Args:
        project_dir: Project root (used for context).
        targets: Harnesses to include (default: all known).
        state_manager: StateManager instance for sync state (created if None).

    Returns:
        Formatted multi-line digest string ready to print or log.
    """
    if state_manager is None:
        from src.state_manager import StateManager
        state_manager = StateManager()

    analyzer = UsageAttributionAnalyzer(
        project_dir=project_dir or Path.cwd(),
        state_manager=state_manager,
    )
    reports = analyzer.analyze(targets=targets)

    total_invocations = sum(r.invocation_count for r in reports)
    synced_targets = [r for r in reports if r.rules_synced > 0]
    active_targets = [r for r in reports if r.invocation_count > 0]
    idle_synced = [r for r in synced_targets if r.invocation_count == 0]

    from datetime import date
    week_str = date.today().strftime("Week of %Y-%m-%d")

    lines = [
        f"HarnessSync Weekly Digest — {week_str}",
        "=" * 54,
        "",
    ]

    if total_invocations == 0:
        lines.append(
            "No harness invocations detected in shell history this week.\n"
            "Shell history may be in a non-standard location or harnesses\n"
            "haven't been used yet."
        )
        return "\n".join(lines)

    # Most-used harness
    primary = max(reports, key=lambda r: r.invocation_count)
    lines.append(
        f"Most-used harness: {primary.target} "
        f"— {primary.invocation_count} invocations "
        f"({primary.share_of_total * 100:.0f}% of total)"
    )
    lines.append("")

    # Per-harness table
    lines.append(f"{'Harness':<12}  {'Invocations':>12}  {'Coverage':>10}  Last used")
    lines.append("  " + "-" * 52)
    for r in reports:
        last = r.last_invocation or "never"
        cov = f"{r.rules_coverage_pct * 100:.0f}%"
        bar_len = int(r.share_of_total * 15)
        bar = "█" * bar_len + "░" * (15 - bar_len)
        lines.append(
            f"  {r.target:<10}  {bar}  {r.invocation_count:>4}  "
            f"{cov:>7}   {last}"
        )
    lines.append("")

    # Insights
    if idle_synced:
        names = ", ".join(r.target for r in idle_synced)
        lines.append(
            f"Synced but unused: {names}\n"
            "  → These harnesses have synced config but show zero invocations.\n"
            "    Consider pruning them with /sync-setup or /sync-gaps to free maintenance burden."
        )
        lines.append("")

    low_cov = [r for r in active_targets if r.rules_coverage_pct < 0.7]
    if low_cov:
        names = ", ".join(r.target for r in low_cov)
        lines.append(
            f"Low rule coverage in active harnesses: {names}\n"
            "  → Some rules are dropped when syncing to these harnesses.\n"
            "    Run /sync-matrix to see which rules are lost in translation."
        )
        lines.append("")

    lines.append("Run /sync-usage --full for complete attribution details.")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Multi-Project Sync Dashboard (item 26)
# ──────────────────────────────────────────────────────────────────────────────


class MultiProjectDashboard:
    """Aggregated sync status across all tracked projects.

    Scans common project roots (git repos under home, recently accessed dirs)
    for HarnessSync state and presents a unified control-tower view showing
    which projects are synced, drifted, or unsynced.

    Useful for power users working across 10+ repositories who need to know
    at a glance which projects have stale harness configs.
    """

    # Common project root directories to scan
    _DEFAULT_SEARCH_ROOTS: list[str] = [
        "~/Developer",
        "~/Projects",
        "~/Code",
        "~/src",
        "~/work",
        "~/repos",
    ]

    def __init__(self, search_roots: list[str] | None = None, max_depth: int = 3):
        self.search_roots = [Path(r).expanduser() for r in (search_roots or self._DEFAULT_SEARCH_ROOTS)]
        self.max_depth = max_depth

    def discover_projects(self) -> list[Path]:
        """Find all directories that look like HarnessSync-tracked projects.

        A directory qualifies if it contains a ``.harnesssync`` file or a
        HarnessSync state file in the default state directory.

        Returns:
            Sorted list of project root Paths.
        """
        projects: list[Path] = []

        for root in self.search_roots:
            if not root.exists():
                continue
            try:
                self._scan_dir(root, depth=0, found=projects)
            except PermissionError:
                pass

        # Also check any explicitly tracked projects in state
        try:
            state_dir = Path.home() / ".harnesssync" / "projects"
            if state_dir.exists():
                for entry in state_dir.iterdir():
                    if entry.is_dir():
                        candidate = Path(entry.name.replace("_", "/"))
                        if candidate.exists() and candidate not in projects:
                            projects.append(candidate)
        except OSError:
            pass

        return sorted(set(projects))

    def _scan_dir(self, directory: Path, depth: int, found: list[Path]) -> None:
        """Recursively scan for HarnessSync project markers."""
        if depth > self.max_depth:
            return

        # Project marker: .harnesssync config file or .git + CLAUDE.md
        has_harnesssync = (directory / ".harnesssync").exists()
        has_claude_md = (directory / "CLAUDE.md").exists()
        has_git = (directory / ".git").exists()

        if has_harnesssync or (has_git and has_claude_md):
            found.append(directory)
            return  # Don't recurse into found projects

        try:
            for child in directory.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    self._scan_dir(child, depth + 1, found)
        except PermissionError:
            pass

    def project_status(self, project_dir: Path) -> dict:
        """Get sync status for a single project.

        Args:
            project_dir: Project root directory.

        Returns:
            Dict with keys:
                - path: str — project path
                - name: str — directory name
                - has_harnesssync: bool — config file present
                - has_claude_md: bool — CLAUDE.md present
                - last_sync: str | None — ISO timestamp of last sync
                - targets_synced: list[str] — targets with sync state
                - drift_targets: list[str] — targets with detected drift
                - status: str — "synced" | "drifted" | "never_synced" | "no_config"
        """
        has_harnesssync = (project_dir / ".harnesssync").exists()
        has_claude_md = (project_dir / "CLAUDE.md").exists()

        last_sync: str | None = None
        targets_synced: list[str] = []
        drift_targets: list[str] = []

        try:
            from src.state_manager import StateManager
            sm = StateManager(project_dir=project_dir)
            state = sm.load()

            last_sync_ts = state.get("last_sync")
            if last_sync_ts:
                last_sync = last_sync_ts[:19]

            for target, info in state.get("targets", {}).items():
                if info:
                    targets_synced.append(target)

            # Check for drift using conflict detector
            try:
                from src.conflict_detector import ConflictDetector
                detector = ConflictDetector(state_manager=sm)
                for target in targets_synced:
                    conflicts = detector.check(target)
                    if conflicts:
                        drift_targets.append(target)
            except Exception:
                pass

        except Exception:
            pass

        if not has_claude_md:
            status = "no_config"
        elif not targets_synced and not last_sync:
            status = "never_synced"
        elif drift_targets:
            status = "drifted"
        else:
            status = "synced"

        return {
            "path": str(project_dir),
            "name": project_dir.name,
            "has_harnesssync": has_harnesssync,
            "has_claude_md": has_claude_md,
            "last_sync": last_sync,
            "targets_synced": targets_synced,
            "drift_targets": drift_targets,
            "status": status,
        }

    def dashboard(self, projects: list[Path] | None = None) -> list[dict]:
        """Generate status for all discovered (or provided) projects.

        Args:
            projects: Projects to check. If None, auto-discovers via discover_projects().

        Returns:
            List of project status dicts, sorted by status severity then name.
        """
        if projects is None:
            projects = self.discover_projects()

        statuses = [self.project_status(p) for p in projects]

        # Sort: drifted first, then never_synced, then synced, then no_config
        priority = {"drifted": 0, "never_synced": 1, "synced": 2, "no_config": 3}
        statuses.sort(key=lambda s: (priority.get(s["status"], 9), s["name"]))

        return statuses

    def format_dashboard(self, statuses: list[dict] | None = None) -> str:
        """Format the multi-project dashboard for terminal display.

        Args:
            statuses: Output of dashboard(). If None, auto-discovers.

        Returns:
            Formatted dashboard string.
        """
        if statuses is None:
            statuses = self.dashboard()

        if not statuses:
            return (
                "No HarnessSync projects found.\n"
                "Projects with .harnesssync or CLAUDE.md + .git will appear here."
            )

        status_icons = {
            "synced": "✓",
            "drifted": "⚠",
            "never_synced": "○",
            "no_config": "—",
        }

        lines = [
            "Multi-Project Sync Dashboard",
            "=" * 70,
            "",
            f"  {'Project':<30} {'Status':<14} {'Last Sync':<20} Targets",
            "  " + "-" * 68,
        ]

        for s in statuses:
            icon = status_icons.get(s["status"], "?")
            name = s["name"][:29]
            status_str = f"{icon} {s['status'].replace('_', ' ')}"
            last = s["last_sync"] or "never"
            targets = ", ".join(s["targets_synced"][:4])
            if len(s["targets_synced"]) > 4:
                targets += f" (+{len(s['targets_synced']) - 4})"
            if s["drift_targets"]:
                targets += f"  [drift: {', '.join(s['drift_targets'])}]"
            lines.append(f"  {name:<30} {status_str:<14} {last:<20} {targets}")

        lines.append("")
        counts = {k: sum(1 for s in statuses if s["status"] == k)
                  for k in ("synced", "drifted", "never_synced", "no_config")}
        lines.append(
            f"  Summary: {counts['synced']} synced  "
            f"{counts['drifted']} drifted  "
            f"{counts['never_synced']} never synced  "
            f"{counts['no_config']} no config"
        )
        lines.append("")
        lines.append("  ✓=synced  ⚠=drifted  ○=never synced  —=no CLAUDE.md")

        return "\n".join(lines)
