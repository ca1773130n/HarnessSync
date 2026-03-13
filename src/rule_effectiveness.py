from __future__ import annotations

"""Rule Effectiveness Scoring (item 12).

Tracks which CLAUDE.md rules are actually applied during sessions by
listening for PostToolUse events that cite rule text or headings.
Scores each rule by frequency of application over a configurable window.

Surfaces:
- Rules that haven't fired in N days → candidates for removal
- Rules that fire constantly → candidates for promotion to all harnesses

Storage: ~/.harnesssync/rule_effectiveness.json

Schema:
    {
        "version": 1,
        "rules": {
            "<rule_title_slug>": {
                "title": "Original heading text",
                "first_seen": "2024-01-01T00:00:00",
                "last_seen": "2024-01-15T12:00:00",
                "fire_count": 42,
                "sessions": ["2024-01-15", ...]   // unique dates seen
            }
        }
    }

Usage::

    from src.rule_effectiveness import RuleEffectivenessTracker

    tracker = RuleEffectivenessTracker()

    # Called from a PostToolUse hook with the assistant response text
    tracker.record_citation(response_text)

    # Get scored report
    report = tracker.score_rules(stale_days=30)
    print(report.format())

    # Mark rules found in CLAUDE.md (so we know the full universe of rules)
    tracker.register_rules(["Conventional Commits", "No console.log", ...])
"""

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path


_STATE_FILE = Path.home() / ".harnesssync" / "rule_effectiveness.json"
_DEFAULT_STALE_DAYS = 30
_DEFAULT_HOT_THRESHOLD = 10  # fire_count above this → "hot" rule


# ── Slug helpers ────────────────────────────────────────────────────────────

_NON_ALPHA = re.compile(r"[^a-z0-9]+")


def _slugify(title: str) -> str:
    return _NON_ALPHA.sub("-", title.lower()).strip("-")[:80]


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class RuleScore:
    """Effectiveness score for a single rule."""

    title: str
    slug: str
    fire_count: int
    last_seen: datetime | None
    first_seen: datetime | None
    unique_days: int
    status: str    # "hot" | "active" | "stale" | "unused"
    days_since_last: int | None = None


@dataclass
class EffectivenessReport:
    """Aggregated effectiveness report across all tracked rules."""

    rules: list[RuleScore] = field(default_factory=list)
    stale_days: int = _DEFAULT_STALE_DAYS
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def hot(self) -> list[RuleScore]:
        return [r for r in self.rules if r.status == "hot"]

    @property
    def stale(self) -> list[RuleScore]:
        return [r for r in self.rules if r.status == "stale"]

    @property
    def unused(self) -> list[RuleScore]:
        return [r for r in self.rules if r.status == "unused"]

    @property
    def active(self) -> list[RuleScore]:
        return [r for r in self.rules if r.status == "active"]

    def format(self, verbose: bool = False) -> str:
        """Return a human-readable effectiveness report."""
        if not self.rules:
            return "Rule Effectiveness: No tracking data yet."

        lines = [
            f"Rule Effectiveness Report ({len(self.rules)} rules tracked)",
            "=" * 55,
        ]

        if self.hot:
            lines.append(f"\nHot rules (fire often — promote to all harnesses?):")
            for r in sorted(self.hot, key=lambda x: -x.fire_count):
                lines.append(f"  {r.fire_count:>4}x  {r.title}")

        if self.stale:
            lines.append(f"\nStale rules (not seen in {self.stale_days}+ days — remove?):")
            for r in sorted(self.stale, key=lambda x: x.days_since_last or 9999, reverse=True):
                days = f"{r.days_since_last}d ago" if r.days_since_last is not None else "never"
                lines.append(f"  {days:>10}  {r.title}")

        if self.unused:
            lines.append(f"\nUnused rules (never observed firing):")
            for r in self.unused:
                lines.append(f"            {r.title}")

        if verbose and self.active:
            lines.append(f"\nActive rules:")
            for r in sorted(self.active, key=lambda x: -x.fire_count):
                lines.append(f"  {r.fire_count:>4}x  {r.title}")

        return "\n".join(lines)


# ── Citation detection ──────────────────────────────────────────────────────

def _extract_cited_headings(response_text: str, known_slugs: dict[str, str]) -> set[str]:
    """Scan *response_text* for mentions of known rule headings.

    Returns set of matched slugs.

    Detection uses:
    1. Exact title match (case-insensitive)
    2. Slug keyword match (rule title words present in response)
    """
    response_lower = response_text.lower()
    cited: set[str] = set()

    for slug, title in known_slugs.items():
        # Exact title check
        if title.lower() in response_lower:
            cited.add(slug)
            continue
        # Word-boundary check: all significant words from title present
        words = [w for w in re.split(r"\W+", title.lower()) if len(w) > 3]
        if words and all(w in response_lower for w in words):
            cited.add(slug)

    return cited


# ── Tracker ─────────────────────────────────────────────────────────────────

class RuleEffectivenessTracker:
    """Persistent tracker for rule citation frequency.

    Args:
        state_file: Path to effectiveness JSON store.
                    Defaults to ~/.harnesssync/rule_effectiveness.json.
    """

    def __init__(self, state_file: Path | None = None):
        self._path = state_file or _STATE_FILE
        self._data: dict = self._load()

    # ── Persistence ────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self._path.exists():
            return {"version": 1, "rules": {}}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "rules" in raw:
                return raw
        except (json.JSONDecodeError, OSError):
            pass
        return {"version": 1, "rules": {}}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self._path.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(self._data, tmp, indent=2, ensure_ascii=False)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, str(self._path))
        except Exception:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise

    # ── Registration ───────────────────────────────────────────────────────

    def register_rules(self, titles: list[str]) -> None:
        """Register rule titles so they appear in reports even if never fired.

        Args:
            titles: List of rule heading strings from CLAUDE.md.
        """
        rules = self._data.setdefault("rules", {})
        for title in titles:
            slug = _slugify(title)
            if slug not in rules:
                rules[slug] = {
                    "title": title,
                    "first_seen": None,
                    "last_seen": None,
                    "fire_count": 0,
                    "sessions": [],
                }
        self._save()

    # ── Citation recording ─────────────────────────────────────────────────

    def record_citation(self, response_text: str) -> list[str]:
        """Scan *response_text* for rule citations and record them.

        Intended to be called from a PostToolUse hook with the tool result
        or assistant response text.

        Args:
            response_text: Text to scan for rule mentions.

        Returns:
            List of rule slugs that were detected in this call.
        """
        rules = self._data.setdefault("rules", {})
        known = {slug: entry["title"] for slug, entry in rules.items()}
        cited = _extract_cited_headings(response_text, known)
        if not cited:
            return []

        now = datetime.now(timezone.utc)
        today = now.date().isoformat()

        for slug in cited:
            if slug not in rules:
                continue
            entry = rules[slug]
            entry["fire_count"] = entry.get("fire_count", 0) + 1
            entry["last_seen"] = now.isoformat()
            if entry.get("first_seen") is None:
                entry["first_seen"] = now.isoformat()
            sessions = entry.setdefault("sessions", [])
            if today not in sessions:
                sessions.append(today)
                # Keep only last 90 days
                if len(sessions) > 90:
                    sessions[:] = sessions[-90:]

        self._save()
        return list(cited)

    # ── Scoring ────────────────────────────────────────────────────────────

    def score_rules(
        self,
        stale_days: int = _DEFAULT_STALE_DAYS,
        hot_threshold: int = _DEFAULT_HOT_THRESHOLD,
    ) -> EffectivenessReport:
        """Compute effectiveness scores for all tracked rules.

        Args:
            stale_days: Rules last seen more than this many days ago are "stale".
            hot_threshold: Rules with fire_count >= this are "hot".

        Returns:
            EffectivenessReport with scored rules.
        """
        rules = self._data.get("rules", {})
        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(days=stale_days)

        scored: list[RuleScore] = []
        for slug, entry in rules.items():
            fire_count = entry.get("fire_count", 0)

            last_seen: datetime | None = None
            if entry.get("last_seen"):
                try:
                    last_seen = datetime.fromisoformat(entry["last_seen"])
                except ValueError:
                    pass

            first_seen: datetime | None = None
            if entry.get("first_seen"):
                try:
                    first_seen = datetime.fromisoformat(entry["first_seen"])
                except ValueError:
                    pass

            unique_days = len(entry.get("sessions", []))

            days_since: int | None = None
            if last_seen:
                delta = now - last_seen
                days_since = delta.days

            # Determine status
            if fire_count == 0:
                status = "unused"
            elif fire_count >= hot_threshold:
                status = "hot"
            elif last_seen and last_seen < stale_cutoff:
                status = "stale"
            else:
                status = "active"

            scored.append(RuleScore(
                title=entry.get("title", slug),
                slug=slug,
                fire_count=fire_count,
                last_seen=last_seen,
                first_seen=first_seen,
                unique_days=unique_days,
                status=status,
                days_since_last=days_since,
            ))

        return EffectivenessReport(
            rules=scored,
            stale_days=stale_days,
        )

    def reset(self) -> None:
        """Clear all effectiveness data (irreversible)."""
        self._data = {"version": 1, "rules": {}}
        self._save()

    def get_stale_titles(self, stale_days: int = _DEFAULT_STALE_DAYS) -> list[str]:
        """Return rule titles that haven't fired in *stale_days* days."""
        report = self.score_rules(stale_days=stale_days)
        return [r.title for r in report.stale + report.unused]

    def get_hot_titles(self, hot_threshold: int = _DEFAULT_HOT_THRESHOLD) -> list[str]:
        """Return rule titles that fire frequently (candidates for promotion)."""
        report = self.score_rules(hot_threshold=hot_threshold)
        return [r.title for r in report.hot]


# ── Skill Usage Tracker (item 22) ───────────────────────────────────────────

_SKILL_STATE_FILE = Path.home() / ".harnesssync" / "skill_usage.json"


@dataclass
class SkillUsageEntry:
    """Usage record for a single skill across all harnesses."""

    name: str
    invocations: int = 0
    last_invoked: datetime | None = None
    harness_counts: dict = field(default_factory=dict)
    unique_days: int = 0


class SkillUsageTracker:
    """Track which synced skills are invoked and how often, per harness.

    Records invocations when a skill name is detected in tool output or
    session transcripts. Stores counts per harness so users can see which
    harness they rely on most for each skill.

    Storage: ~/.harnesssync/skill_usage.json
    """

    def __init__(self, state_file: Path | None = None):
        self._path = state_file or _SKILL_STATE_FILE
        self._data: dict = self._load()

    def _load(self) -> dict:
        if not self._path.exists():
            return {"version": 1, "skills": {}}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "skills" in raw:
                return raw
        except (json.JSONDecodeError, OSError):
            pass
        return {"version": 1, "skills": {}}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self._path.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(self._data, tmp, indent=2, ensure_ascii=False)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp.close()
            os.replace(tmp.name, str(self._path))
        except Exception:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise

    def record_invocation(self, skill_name: str, harness: str = "unknown") -> None:
        """Record a skill invocation for a given harness.

        Args:
            skill_name: Name of the invoked skill (e.g. "feature-dev").
            harness: Harness where the skill was invoked (e.g. "codex").
        """
        skills = self._data.setdefault("skills", {})
        entry = skills.setdefault(skill_name, {
            "invocations": 0,
            "last_invoked": None,
            "harness_counts": {},
            "unique_days": 0,
            "days": [],
        })

        now = datetime.now(timezone.utc)
        today = now.date().isoformat()

        entry["invocations"] = entry.get("invocations", 0) + 1
        entry["last_invoked"] = now.isoformat()

        harness_counts = entry.setdefault("harness_counts", {})
        harness_counts[harness] = harness_counts.get(harness, 0) + 1

        days = entry.setdefault("days", [])
        if today not in days:
            days.append(today)
            if len(days) > 90:
                days[:] = days[-90:]
            entry["unique_days"] = len(days)

        self._save()

    def detect_and_record(
        self,
        text: str,
        known_skills: list[str],
        harness: str = "unknown",
    ) -> list[str]:
        """Scan text for skill invocations and record matches.

        Args:
            text: Text to scan (e.g. assistant response or tool output).
            known_skills: List of known skill names to look for.
            harness: Harness where the session occurred.

        Returns:
            List of skill names that were detected and recorded.
        """
        text_lower = text.lower()
        detected: list[str] = []

        for skill in known_skills:
            needle = _NON_ALPHA.sub(".", skill.lower())
            if re.search(r"\b" + needle + r"\b", text_lower):
                self.record_invocation(skill, harness)
                detected.append(skill)

        return detected

    def get_usage_stats(self) -> list[SkillUsageEntry]:
        """Return usage stats for all tracked skills, sorted by invocations desc.

        Returns:
            List of SkillUsageEntry objects.
        """
        skills = self._data.get("skills", {})
        entries: list[SkillUsageEntry] = []

        for name, data in skills.items():
            last_inv: datetime | None = None
            if data.get("last_invoked"):
                try:
                    last_inv = datetime.fromisoformat(data["last_invoked"])
                except ValueError:
                    pass
            entries.append(SkillUsageEntry(
                name=name,
                invocations=data.get("invocations", 0),
                last_invoked=last_inv,
                harness_counts=dict(data.get("harness_counts", {})),
                unique_days=data.get("unique_days", 0),
            ))

        entries.sort(key=lambda e: -e.invocations)
        return entries

    def format_usage_report(self, top_n: int = 20) -> str:
        """Return a human-readable skill usage dashboard.

        Args:
            top_n: Maximum skills to display. Default: 20.

        Returns:
            Formatted report string.
        """
        entries = self.get_usage_stats()
        if not entries:
            return "Skill Usage: No invocations recorded yet."

        lines = [
            f"Skill Usage Dashboard ({len(entries)} skill(s) tracked)",
            "=" * 55,
            f"  {'Skill':<25}  {'Total':>6}  {'Days':>5}  Top Harness",
            "  " + "-" * 52,
        ]

        for entry in entries[:top_n]:
            top_harness = (
                max(entry.harness_counts, key=entry.harness_counts.get)
                if entry.harness_counts
                else "—"
            )
            lines.append(
                f"  {entry.name:<25}  {entry.invocations:>6}  "
                f"{entry.unique_days:>5}  {top_harness}"
            )

        if len(entries) > top_n:
            lines.append(f"  ... and {len(entries) - top_n} more")

        total = sum(e.invocations for e in entries)
        lines += ["", f"  Total invocations recorded: {total}"]
        return "\n".join(lines)

    def get_unused_skills(
        self,
        known_skills: list[str],
        stale_days: int = 30,
    ) -> list[str]:
        """Return skills that have never been invoked or not used recently.

        Args:
            known_skills: All skill names from the skills directory.
            stale_days: Skills last invoked more than this many days ago count as stale.

        Returns:
            Sorted list of unused/stale skill names.
        """
        skills = self._data.get("skills", {})
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=stale_days)
        unused: list[str] = []

        for skill in known_skills:
            if skill not in skills:
                unused.append(skill)
                continue
            last_raw = skills[skill].get("last_invoked")
            if not last_raw:
                unused.append(skill)
                continue
            try:
                last = datetime.fromisoformat(last_raw)
                if last < cutoff:
                    unused.append(skill)
            except ValueError:
                unused.append(skill)

        return sorted(unused)

    def reset(self) -> None:
        """Clear all skill usage data."""
        self._data = {"version": 1, "skills": {}}
        self._save()
