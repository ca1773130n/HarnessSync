from __future__ import annotations

"""Harness Usage Tracker — weekly heatmap of AI harness invocations (item 24).

Reads shell history files (bash, zsh, fish) and harness-specific log files
to count how often each AI coding harness is invoked.  Produces a weekly
heatmap summary so users can see which harnesses are actually worth
maintaining configs for.

Detection sources (in priority order):
1. ``~/.zsh_history`` / ``~/.bash_history`` / ``~/.local/share/fish/fish_history``
2. Harness-specific log directories (best-effort)
3. ``HARNESS_USAGE_LOG`` environment variable pointing to a custom CSV log

Usage::

    from src.harness_usage_tracker import UsageTracker

    tracker = UsageTracker()
    tracker.scan()

    print(tracker.render_heatmap())            # weekly heatmap table
    print(tracker.render_summary())            # top harnesses this week
    tracker.export_csv(Path("usage.csv"))      # optional export
"""

import csv
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Canonical harness names → CLI executable names that indicate invocation
_HARNESS_EXECUTABLES: Dict[str, List[str]] = {
    "claude":    ["claude"],
    "codex":     ["codex"],
    "gemini":    ["gemini"],
    "opencode":  ["opencode"],
    "cursor":    ["cursor"],
    "aider":     ["aider"],
    "windsurf":  ["windsurf"],
    "cline":     ["cline"],
    "continue":  ["continue"],
    "zed":       ["zed"],
    "copilot":   ["gh copilot", "copilot"],
}

# Build a single compiled pattern for fast history scanning
_HARNESS_PATTERNS: Dict[str, re.Pattern] = {
    harness: re.compile(
        r"(?:^|[\s;|&])(" + "|".join(re.escape(e) for e in exes) + r")\b",
        re.MULTILINE,
    )
    for harness, exes in _HARNESS_EXECUTABLES.items()
}

_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

# Maps (harness, date_str "YYYY-MM-DD") -> count
UsageMatrix = Dict[Tuple[str, str], int]


# ---------------------------------------------------------------------------
# History parsers
# ---------------------------------------------------------------------------

def _parse_zsh_history(path: Path) -> List[Tuple[Optional[datetime], str]]:
    """Parse zsh extended history format ```: <epoch>:0;<command>```.

    Falls back to treating each line as a bare command with no timestamp.
    """
    entries: List[Tuple[Optional[datetime], str]] = []
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except OSError:
        return entries

    # Extended format: `: 1700000000:0;command text`
    ext_re = re.compile(r"^:\s*(\d+):\d+;(.+)$", re.MULTILINE)
    found_extended = False
    for m in ext_re.finditer(text):
        ts = datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
        entries.append((ts, m.group(2)))
        found_extended = True

    if not found_extended:
        # Plain format: one command per line, no timestamps
        for line in text.splitlines():
            line = line.strip()
            if line:
                entries.append((None, line))

    return entries


def _parse_bash_history(path: Path) -> List[Tuple[Optional[datetime], str]]:
    """Parse bash history.  Supports ``HISTTIMEFORMAT`` timestamp comments."""
    entries: List[Tuple[Optional[datetime], str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entries

    ts: Optional[datetime] = None
    ts_re = re.compile(r"^#(\d{10,})$")
    for line in text.splitlines():
        line = line.rstrip()
        m = ts_re.match(line)
        if m:
            ts = datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
            continue
        if line and not line.startswith("#"):
            entries.append((ts, line))
            ts = None
    return entries


def _parse_fish_history(path: Path) -> List[Tuple[Optional[datetime], str]]:
    """Parse fish shell history (YAML-like ``cmd:`` / ``when:`` blocks)."""
    entries: List[Tuple[Optional[datetime], str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entries

    cmd: Optional[str] = None
    ts: Optional[datetime] = None
    cmd_re = re.compile(r"^-\s+cmd:\s+(.+)$")
    when_re = re.compile(r"^\s+when:\s+(\d+)$")

    for line in text.splitlines():
        mc = cmd_re.match(line)
        mw = when_re.match(line)
        if mc:
            if cmd:
                entries.append((ts, cmd))
            cmd = mc.group(1)
            ts = None
        elif mw and cmd:
            ts = datetime.fromtimestamp(int(mw.group(1)), tz=timezone.utc)

    if cmd:
        entries.append((ts, cmd))

    return entries


# ---------------------------------------------------------------------------
# Main tracker class
# ---------------------------------------------------------------------------

class UsageTracker:
    """Scan shell histories and produce harness usage heatmaps.

    Args:
        home:      User home directory (default: ``Path.home()``).
        weeks:     Number of weeks of history to consider (default: 4).
        log_path:  Optional path to a custom CSV usage log (``timestamp,harness``).
    """

    def __init__(
        self,
        home: Optional[Path] = None,
        weeks: int = 4,
        log_path: Optional[Path] = None,
    ) -> None:
        self.home = home or Path.home()
        self.weeks = weeks
        self.log_path = log_path or _env_log_path()
        self._matrix: UsageMatrix = defaultdict(int)
        self._scanned = False

    # ── Scan ──────────────────────────────────────────────────────────────────

    def scan(self) -> None:
        """Scan all available history sources and populate the usage matrix."""
        cutoff = datetime.now(tz=timezone.utc) - timedelta(weeks=self.weeks)

        history_parsers = [
            (self.home / ".zsh_history", _parse_zsh_history),
            (self.home / ".bash_history", _parse_bash_history),
            (self.home / ".local" / "share" / "fish" / "fish_history", _parse_fish_history),
        ]

        for hist_path, parser in history_parsers:
            if hist_path.is_file():
                self._process_entries(parser(hist_path), cutoff)

        # Custom CSV log (HARNESS_USAGE_LOG env or log_path arg)
        if self.log_path and self.log_path.is_file():
            self._process_csv_log(self.log_path, cutoff)

        self._scanned = True

    def _process_entries(
        self,
        entries: List[Tuple[Optional[datetime], str]],
        cutoff: datetime,
    ) -> None:
        """Classify and count harness invocations from history entries."""
        today = datetime.now(tz=timezone.utc).date()

        for ts, command in entries:
            if ts is not None and ts < cutoff:
                continue
            date_str = ts.date().isoformat() if ts else today.isoformat()
            for harness, pattern in _HARNESS_PATTERNS.items():
                if pattern.search(command):
                    self._matrix[(harness, date_str)] += 1

    def _process_csv_log(self, path: Path, cutoff: datetime) -> None:
        """Read a CSV log with columns ``timestamp,harness[,count]``."""
        try:
            with path.open(encoding="utf-8") as fh:
                reader = csv.reader(fh)
                for row in reader:
                    if not row or row[0].startswith("#"):
                        continue
                    if len(row) < 2:
                        continue
                    ts_str, harness = row[0].strip(), row[1].strip().lower()
                    count = int(row[2]) if len(row) >= 3 and row[2].strip().isdigit() else 1
                    try:
                        ts = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if ts < cutoff:
                        continue
                    date_str = ts.date().isoformat()
                    if harness in _HARNESS_EXECUTABLES:
                        self._matrix[(harness, date_str)] += count
        except OSError:
            pass

    # ── Rendering ─────────────────────────────────────────────────────────────

    def render_heatmap(self, top_n: int = 8) -> str:
        """Render a weekly usage heatmap as an ASCII table.

        Args:
            top_n: Number of harnesses to include (sorted by total usage).

        Returns:
            Multi-line string with a day-of-week × harness heatmap.
        """
        if not self._scanned:
            self.scan()

        today = datetime.now(tz=timezone.utc).date()
        # Build 4-week calendar of days
        all_days = [
            (today - timedelta(days=i)).isoformat()
            for i in range(self.weeks * 7 - 1, -1, -1)
        ]

        # Aggregate by harness
        totals: Dict[str, int] = defaultdict(int)
        for (harness, date_str), count in self._matrix.items():
            totals[harness] += count

        if not totals:
            return (
                "No harness usage detected in the last "
                f"{self.weeks} week(s) of shell history.\n"
                "Tip: ensure your shell writes timestamped history "
                "(HISTTIMEFORMAT / setopt EXTENDED_HISTORY)."
            )

        harnesses = sorted(totals, key=lambda h: -totals[h])[:top_n]
        col_w = max(len(h) for h in harnesses) + 1

        # Day-of-week aggregation: sum over all occurrences of each weekday
        dow_totals: Dict[str, Dict[str, int]] = {h: defaultdict(int) for h in harnesses}
        for (harness, date_str), count in self._matrix.items():
            if harness not in harnesses:
                continue
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").weekday()  # 0=Mon
            except ValueError:
                continue
            dow_totals[harness][_DAYS[d]] += count

        # Determine scale (max invocations in a cell)
        max_val = max(
            (v for dow in dow_totals.values() for v in dow.values()),
            default=1,
        )

        def _bar(v: int) -> str:
            if v == 0:
                return "  ·  "
            blocks = max(1, round(v / max_val * 5))
            return f" {'█' * blocks:<5}"

        header = f"  {'Harness':<{col_w}}" + "".join(f" {d:^5}" for d in _DAYS)
        sep = "  " + "─" * (col_w + len(_DAYS) * 6)
        lines = [
            f"Harness Usage Heatmap — last {self.weeks} week(s)",
            "=" * (col_w + len(_DAYS) * 6 + 4),
            header,
            sep,
        ]
        for h in harnesses:
            row = f"  {h:<{col_w}}"
            for day in _DAYS:
                row += _bar(dow_totals[h].get(day, 0))
            row += f"  ({totals[h]} total)"
            lines.append(row)
        lines.append(sep)
        lines.append("  Scale: · = 0  █ = max")
        return "\n".join(lines)

    def render_summary(self) -> str:
        """Return a one-paragraph summary of this week's top harnesses."""
        if not self._scanned:
            self.scan()

        today = datetime.now(tz=timezone.utc).date()
        week_start = today - timedelta(days=today.weekday())
        week_days = {
            (week_start + timedelta(days=i)).isoformat() for i in range(7)
        }

        week_totals: Dict[str, int] = defaultdict(int)
        for (harness, date_str), count in self._matrix.items():
            if date_str in week_days:
                week_totals[harness] += count

        if not week_totals:
            return "No harness usage recorded this week."

        ranked = sorted(week_totals, key=lambda h: -week_totals[h])
        total_inv = sum(week_totals.values())
        parts = []
        for h in ranked:
            pct = round(week_totals[h] / total_inv * 100)
            parts.append(f"{h} {pct}%")

        return (
            f"This week: {total_inv} total harness invocations — "
            + ", ".join(parts[:5])
            + ("." if len(ranked) <= 5 else f", and {len(ranked) - 5} more.")
        )

    def export_csv(self, path: Path) -> int:
        """Write the raw usage matrix to a CSV file.

        Args:
            path: Destination CSV path.

        Returns:
            Number of rows written.
        """
        if not self._scanned:
            self.scan()

        rows = sorted(self._matrix.items(), key=lambda kv: (kv[0][1], kv[0][0]))
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["date", "harness", "count"])
                for (harness, date_str), count in rows:
                    writer.writerow([date_str, harness, count])
            return len(rows)
        except OSError:
            return 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env_log_path() -> Optional[Path]:
    """Return path from HARNESS_USAGE_LOG env var, or None."""
    val = os.environ.get("HARNESS_USAGE_LOG", "")
    return Path(val) if val else None
