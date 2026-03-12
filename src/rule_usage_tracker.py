from __future__ import annotations

"""Rule usage and effectiveness tracker (item 14).

Instruments hooks to track which rules and skills are referenced in tool
calls across sessions. Surfaces a /sync-analytics report showing which
rules are frequently triggered versus never used.

Architecture:
- Usage events are appended to ~/.harnesssync/rule-usage.jsonl (one JSON
  per line for append-friendly writes without parsing the full file)
- RuleUsageTracker.record() appends an event
- RuleUsageTracker.analytics() parses the log and aggregates counts
- RuleUsageTracker.format_report() formats for human display

Event schema:
    {
        "ts": "2024-01-01T10:00:00",   # ISO 8601 timestamp
        "rule": "section-heading",      # rule/skill name or pattern matched
        "context": "tool_call",         # event context
        "session_id": "abc123"          # opaque session identifier
    }
"""

import json
import os
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


# Default usage log location
_DEFAULT_LOG_FILE = Path.home() / ".harnesssync" / "rule-usage.jsonl"

# Maximum log file size before rotation (5 MB)
_MAX_LOG_SIZE_BYTES = 5 * 1024 * 1024

# Session ID for this process (stable within a session)
_SESSION_ID = uuid.uuid4().hex[:8]


@dataclass
class RuleUsageEvent:
    """A single rule reference event."""
    ts: str
    rule: str
    context: str
    session_id: str = _SESSION_ID
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        d = {"ts": self.ts, "rule": self.rule, "context": self.context,
             "session_id": self.session_id}
        if self.extra:
            d.update(self.extra)
        return json.dumps(d, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RuleUsageEvent":
        extra = {k: v for k, v in d.items()
                 if k not in ("ts", "rule", "context", "session_id")}
        return cls(
            ts=d.get("ts", ""),
            rule=d.get("rule", ""),
            context=d.get("context", ""),
            session_id=d.get("session_id", ""),
            extra=extra,
        )


@dataclass
class RuleUsageSummary:
    """Aggregated statistics for a single rule/skill."""
    rule: str
    total_uses: int = 0
    sessions: int = 0
    last_used: str = ""
    first_used: str = ""


class RuleUsageTracker:
    """Tracks and reports rule/skill usage across Claude Code sessions.

    Thread-safe via append-only writes to a JSONL file. Reading parses
    the entire log; writing appends a single line (no lock needed for
    standard POSIX filesystems where single writes < PIPE_BUF are atomic).
    """

    def __init__(self, log_file: Path | None = None):
        self._log_file = log_file or _DEFAULT_LOG_FILE

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(self, rule: str, context: str = "unknown", extra: dict | None = None) -> None:
        """Record a single rule reference event.

        Args:
            rule: Name/identifier of the rule or skill referenced.
            context: Context in which the rule was triggered
                     (e.g. "tool_call", "user_prompt", "hook").
            extra: Optional additional metadata to store.
        """
        self._rotate_if_needed()
        event = RuleUsageEvent(
            ts=datetime.now(tz=timezone.utc).isoformat(timespec="seconds"),
            rule=rule,
            context=context,
            extra=extra or {},
        )
        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._log_file, "a", encoding="utf-8") as fh:
            fh.write(event.to_json() + "\n")

    def record_from_text(self, text: str, known_rules: list[str], context: str = "tool_call") -> int:
        """Scan text for known rule references and record matches.

        Useful in PostToolUse hooks that receive tool input/output text
        and want to log which rules were implicitly referenced.

        Args:
            text: Text to scan (e.g. AI response, tool call content).
            known_rules: List of rule/skill names to detect.
            context: Event context label.

        Returns:
            Number of unique rule references detected.
        """
        detected = 0
        text_lower = text.lower()
        for rule in known_rules:
            if rule.lower() in text_lower:
                self.record(rule, context=context)
                detected += 1
        return detected

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def load_events(self, days: int = 30) -> list[RuleUsageEvent]:
        """Load events from the log, optionally filtering to last N days.

        Args:
            days: Only return events within this many days. 0 = all time.

        Returns:
            List of RuleUsageEvent objects.
        """
        if not self._log_file.exists():
            return []

        cutoff: datetime | None = None
        if days > 0:
            cutoff = datetime.now(tz=timezone.utc) - timedelta(days=days)

        events: list[RuleUsageEvent] = []
        with open(self._log_file, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    ev = RuleUsageEvent.from_dict(d)
                    if cutoff and ev.ts:
                        try:
                            ev_dt = datetime.fromisoformat(ev.ts)
                            if ev_dt.tzinfo is None:
                                ev_dt = ev_dt.replace(tzinfo=timezone.utc)
                            if ev_dt < cutoff:
                                continue
                        except ValueError:
                            pass
                    events.append(ev)
                except json.JSONDecodeError:
                    continue

        return events

    def analytics(self, days: int = 30) -> dict[str, RuleUsageSummary]:
        """Compute per-rule aggregated statistics.

        Args:
            days: Analyse events from the last N days (0 = all time).

        Returns:
            Dict mapping rule name → RuleUsageSummary.
        """
        events = self.load_events(days=days)

        # Group by rule
        by_rule: dict[str, list[RuleUsageEvent]] = defaultdict(list)
        for ev in events:
            if ev.rule:
                by_rule[ev.rule].append(ev)

        summaries: dict[str, RuleUsageSummary] = {}
        for rule, rule_events in by_rule.items():
            sessions = {ev.session_id for ev in rule_events if ev.session_id}
            timestamps = sorted(ev.ts for ev in rule_events if ev.ts)
            summaries[rule] = RuleUsageSummary(
                rule=rule,
                total_uses=len(rule_events),
                sessions=len(sessions),
                first_used=timestamps[0] if timestamps else "",
                last_used=timestamps[-1] if timestamps else "",
            )

        return summaries

    def find_unused_rules(self, known_rules: list[str], days: int = 30) -> list[str]:
        """Return rules from known_rules that have zero recorded uses.

        Args:
            known_rules: List of all rule names to check.
            days: Look-back window in days.

        Returns:
            Sorted list of rule names with zero recorded uses.
        """
        used = set(self.analytics(days=days).keys())
        return sorted(r for r in known_rules if r not in used)

    def format_report(
        self,
        known_rules: list[str] | None = None,
        days: int = 30,
        top_n: int = 20,
    ) -> str:
        """Format analytics as a human-readable report.

        Args:
            known_rules: If provided, also shows unused rules.
            days: Look-back window in days.
            top_n: Show top N most-used rules.

        Returns:
            Formatted report string.
        """
        summaries = self.analytics(days=days)
        window_label = f"last {days} days" if days > 0 else "all time"

        lines = [
            "Rule Usage Analytics",
            "=" * 50,
            f"Window: {window_label}",
            f"Tracked rules: {len(summaries)}",
            "",
        ]

        if not summaries:
            lines.append("No usage data found. Run some sessions with rule tracking enabled.")
            return "\n".join(lines)

        # Sort by usage count descending
        ranked = sorted(summaries.values(), key=lambda s: s.total_uses, reverse=True)

        lines.append(f"{'Rule':<40} {'Uses':>6}  {'Sessions':>8}  {'Last Used'}")
        lines.append("-" * 75)
        for s in ranked[:top_n]:
            last = s.last_used[:10] if s.last_used else "—"
            lines.append(f"  {s.rule:<38} {s.total_uses:>6}  {s.sessions:>8}  {last}")

        if len(ranked) > top_n:
            lines.append(f"  ... and {len(ranked) - top_n} more rules")

        if known_rules:
            unused = self.find_unused_rules(known_rules, days=days)
            if unused:
                lines.append(f"\nNever-used rules ({len(unused)}) — consider pruning:")
                for rule in unused[:15]:
                    lines.append(f"  - {rule}")
                if len(unused) > 15:
                    lines.append(f"  ... and {len(unused) - 15} more")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def _rotate_if_needed(self) -> None:
        """Rotate log file if it exceeds _MAX_LOG_SIZE_BYTES."""
        if not self._log_file.exists():
            return
        if self._log_file.stat().st_size < _MAX_LOG_SIZE_BYTES:
            return
        rotated = self._log_file.with_suffix(".jsonl.1")
        try:
            self._log_file.rename(rotated)
        except OSError:
            pass

    def clear(self) -> None:
        """Delete the usage log (for testing or fresh start)."""
        if self._log_file.exists():
            self._log_file.unlink()

    # ------------------------------------------------------------------
    # Stale Harness Detection (item 30)
    # ------------------------------------------------------------------

    # Known config file paths per harness, relative to $HOME.
    # First path in each list that exists is used for mtime checks.
    _HARNESS_CONFIG_PATHS: dict[str, list[str]] = {
        "codex":    [".codex/config.toml", ".config/codex/config.toml"],
        "gemini":   [".gemini/settings.json", ".config/gemini-cli/settings.json"],
        "opencode": [".config/opencode/config.json", ".opencode/config.json"],
        "cursor":   [".cursor/rules/claude-code-rules.mdc", ".cursor/settings.json"],
        "aider":    [".aider.conf.yml", ".config/aider/config.yml"],
        "windsurf": [".windsurfrules", ".windsurf/config.json"],
    }

    def detect_stale_harnesses(
        self,
        stale_days: int = 30,
        home_dir: "Path | None" = None,
    ) -> list[dict]:
        """Detect harnesses whose config files haven't been modified recently.

        Uses file modification time (mtime) as a proxy for harness activity.
        A harness is considered stale if its primary config file exists but
        hasn't been modified in ``stale_days`` days.

        Args:
            stale_days: Number of days of inactivity before a harness is
                        considered stale (default: 30).
            home_dir: Override home directory for testing. Defaults to
                      ``Path.home()``.

        Returns:
            List of dicts, one per stale harness, with keys:
                - ``harness``: str — harness name
                - ``config_file``: str — path to the config file checked
                - ``last_modified``: str — ISO date of last mtime
                - ``days_inactive``: int — days since last modification
                - ``suggestion``: str — human-readable suggestion
        """
        from pathlib import Path as _Path
        home = home_dir or _Path.home()
        cutoff = datetime.now(tz=timezone.utc) - timedelta(days=stale_days)
        stale: list[dict] = []

        for harness, candidates in self._HARNESS_CONFIG_PATHS.items():
            config_path = None
            for rel in candidates:
                p = home / rel
                if p.exists():
                    config_path = p
                    break

            if config_path is None:
                continue  # Harness not installed — not stale, just absent

            try:
                mtime = config_path.stat().st_mtime
                last_modified_dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
            except OSError:
                continue

            if last_modified_dt >= cutoff:
                continue  # Active — not stale

            days_inactive = (datetime.now(tz=timezone.utc) - last_modified_dt).days
            stale.append({
                "harness": harness,
                "config_file": str(config_path),
                "last_modified": last_modified_dt.date().isoformat(),
                "days_inactive": days_inactive,
                "suggestion": (
                    f"You haven't used {harness} in {days_inactive} days. "
                    f"Consider removing it from sync targets to reduce noise: "
                    f"add \"{harness}\" to skip_targets in .harnesssync."
                ),
            })

        # Sort by most inactive first
        stale.sort(key=lambda x: x["days_inactive"], reverse=True)
        return stale

    def format_stale_harness_report(
        self,
        stale_days: int = 30,
        home_dir: "Path | None" = None,
    ) -> str:
        """Format a stale harness detection report for display.

        Args:
            stale_days: Inactivity threshold in days.
            home_dir: Override home directory for testing.

        Returns:
            Human-readable report string, or empty string if no stale harnesses.
        """
        stale = self.detect_stale_harnesses(stale_days=stale_days, home_dir=home_dir)
        if not stale:
            return ""

        lines = [
            f"Stale Harness Detection (>{stale_days} days inactive)",
            "=" * 55,
            "",
        ]
        for entry in stale:
            lines.append(f"  {entry['harness'].upper()}")
            lines.append(f"    Config: {entry['config_file']}")
            lines.append(f"    Last modified: {entry['last_modified']} ({entry['days_inactive']} days ago)")
            lines.append(f"    Suggestion: {entry['suggestion']}")
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Rules Coverage Heatmap (item 30)
    # ------------------------------------------------------------------

    def coverage_heatmap(
        self,
        known_rules: list[str],
        days: int = 30,
        bar_width: int = 20,
    ) -> dict[str, dict]:
        """Compute per-rule usage frequency for a visual heatmap.

        Assigns each rule a heat level based on how often it was triggered
        in the trailing ``days`` window. Rules with zero uses are flagged as
        dead weight (candidates for pruning).

        Args:
            known_rules: List of rule/section names from CLAUDE.md.
            days: Lookback window in days.
            bar_width: Width of the ASCII heat bar in the formatted output.

        Returns:
            Dict mapping rule_name -> {
                "uses": int,
                "last_seen": str | None,   # ISO timestamp or None
                "heat": str,               # "hot" | "warm" | "cool" | "cold"
                "heat_score": float,       # 0.0–1.0 normalised
            }
        """
        summaries = self.analytics(days=days)
        max_uses = max((s.total_uses for s in summaries.values()), default=1)
        if max_uses == 0:
            max_uses = 1

        result: dict[str, dict] = {}
        for rule in known_rules:
            summary = summaries.get(rule)
            uses = summary.total_uses if summary else 0
            last_seen = summary.last_seen if summary else None
            heat_score = uses / max_uses

            if heat_score >= 0.66:
                heat = "hot"
            elif heat_score >= 0.33:
                heat = "warm"
            elif heat_score > 0:
                heat = "cool"
            else:
                heat = "cold"

            result[rule] = {
                "uses": uses,
                "last_seen": last_seen,
                "heat": heat,
                "heat_score": heat_score,
            }

        # Include rules seen in analytics that aren't in known_rules
        for rule, summary in summaries.items():
            if rule not in result:
                heat_score = summary.total_uses / max_uses
                result[rule] = {
                    "uses": summary.total_uses,
                    "last_seen": summary.last_seen,
                    "heat": "warm" if heat_score >= 0.33 else "cool",
                    "heat_score": heat_score,
                }

        return result

    def format_heatmap(
        self,
        known_rules: list[str],
        days: int = 30,
        bar_width: int = 20,
    ) -> str:
        """Format a rules coverage heatmap for terminal display.

        Rules are sorted hottest-first. Cold (never-fired) rules are listed
        at the bottom as pruning candidates.

        Args:
            known_rules: Rule/section names from CLAUDE.md.
            days: Lookback window in days.
            bar_width: Width of the ASCII heat bar.

        Returns:
            Formatted heatmap string.
        """
        heat_icons = {"hot": "🔥", "warm": "🌡", "cool": "❄", "cold": "⬛"}
        heat_chars = {"hot": "█", "warm": "▓", "cool": "░", "cold": " "}

        heatmap = self.coverage_heatmap(known_rules, days=days, bar_width=bar_width)
        if not heatmap:
            return "No rules to display. Add known_rules from your CLAUDE.md."

        sorted_rules = sorted(
            heatmap.items(),
            key=lambda kv: (kv[1]["heat_score"], kv[1]["uses"]),
            reverse=True,
        )

        lines = [
            f"Rules Coverage Heatmap — last {days} days",
            "=" * (bar_width + 50),
            "",
            f"  {'Rule':<35} {'Uses':>5}  Heat{'':>{bar_width - 4}}  Status",
            "  " + "-" * (bar_width + 48),
        ]

        for rule, data in sorted_rules:
            uses = data["uses"]
            heat = data["heat"]
            score = data["heat_score"]
            filled = int(score * bar_width)
            char = heat_chars[heat]
            bar = (char * filled).ljust(bar_width)
            icon = heat_icons.get(heat, " ")
            last = ""
            if data["last_seen"]:
                last = data["last_seen"][:10]

            rule_display = rule[:34]
            status = f"last: {last}" if last else "NEVER FIRED"
            lines.append(f"  {rule_display:<35} {uses:>5}  [{bar}]  {icon} {status}")

        cold_count = sum(1 for d in heatmap.values() if d["heat"] == "cold")
        if cold_count:
            lines.append("")
            lines.append(f"  ⚠ {cold_count} rule(s) never fired in {days} days — consider pruning.")

        lines.append("")
        lines.append("  🔥=high  🌡=medium  ❄=low  ⬛=never")
        return "\n".join(lines)
