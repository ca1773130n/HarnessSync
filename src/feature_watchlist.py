from __future__ import annotations

"""Harness Feature Watchlist (item 19).

Lets users flag unsupported features they care about and get notified when a
new harness version adds support. Removes the need to manually check feature
matrices — users subscribe once and are told when things change.

Storage: ``~/.harnesssync/watchlist.json``

Format::

    {
        "watches": [
            {
                "feature": "mcp",
                "harness": "aider",
                "added_at": "2026-03-18T10:00:00Z",
                "last_support_level": "unsupported"
            }
        ]
    }

Usage::

    wl = FeatureWatchlist()
    wl.add("mcp", "aider")
    wl.add("skills", "zed")

    hits = wl.check()          # returns newly-supported (feature, harness) pairs
    print(wl.format_status())  # show current watchlist with support levels
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


_STATE_DIR = Path.home() / ".harnesssync"
_WATCHLIST_FILE = "watchlist.json"


@dataclass
class WatchEntry:
    """A single item on the feature watchlist."""

    feature: str
    harness: str
    added_at: str = ""
    last_support_level: str = "unsupported"

    def to_dict(self) -> dict:
        return {
            "feature": self.feature,
            "harness": self.harness,
            "added_at": self.added_at,
            "last_support_level": self.last_support_level,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WatchEntry":
        return cls(
            feature=d.get("feature", ""),
            harness=d.get("harness", ""),
            added_at=d.get("added_at", ""),
            last_support_level=d.get("last_support_level", "unsupported"),
        )


@dataclass
class WatchlistHit:
    """Represents a feature that gained (or lost) support since last check."""

    feature: str
    harness: str
    old_level: str
    new_level: str
    improved: bool  # True if support improved, False if regressed

    def format(self) -> str:
        direction = "gained support" if self.improved else "lost support"
        return (
            f"  {self.feature} on {self.harness}: "
            f"{self.old_level} → {self.new_level}  [{direction}]"
        )


class FeatureWatchlist:
    """Persistent watchlist for tracking harness feature support changes.

    Users add (feature, harness) pairs they care about. ``check()`` compares
    the current feature matrix against the stored support levels and returns
    any entries where support improved or regressed.

    Args:
        state_dir: Override storage directory (default: ``~/.harnesssync``).
    """

    def __init__(self, state_dir: Optional[Path] = None) -> None:
        self._state_dir = state_dir or _STATE_DIR
        self._path = self._state_dir / _WATCHLIST_FILE

    # ── Public API ───────────────────────────────────────────────────────────

    def add(self, feature: str, harness: str) -> tuple[bool, str]:
        """Add a (feature, harness) pair to the watchlist.

        Args:
            feature: Feature name (e.g. "mcp", "skills", "agents").
            harness: Harness name (e.g. "aider", "gemini", "codex").

        Returns:
            ``(success, message)`` tuple.
        """
        from src.harness_feature_matrix import ALL_FEATURES, ALL_HARNESSES, HarnessFeatureMatrix

        feature = feature.lower().strip()
        harness = harness.lower().strip()

        if feature not in ALL_FEATURES:
            return False, (
                f"Unknown feature '{feature}'. "
                f"Valid features: {', '.join(sorted(ALL_FEATURES))}"
            )
        if harness not in ALL_HARNESSES:
            return False, (
                f"Unknown harness '{harness}'. "
                f"Valid harnesses: {', '.join(sorted(ALL_HARNESSES))}"
            )

        watches = self._load()
        for w in watches:
            if w.feature == feature and w.harness == harness:
                return False, f"Already watching {feature} on {harness}."

        # Record current support level so we can detect changes later
        matrix = HarnessFeatureMatrix()
        current_level = matrix.query_feature(feature, harness)

        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        entry = WatchEntry(
            feature=feature,
            harness=harness,
            added_at=now,
            last_support_level=current_level,
        )
        watches.append(entry)
        self._save(watches)
        return True, (
            f"Watching {feature} on {harness} "
            f"(currently: {current_level}). "
            f"Run /sync-gaps --watchlist-check to detect changes."
        )

    def remove(self, feature: str, harness: str) -> tuple[bool, str]:
        """Remove a (feature, harness) pair from the watchlist.

        Args:
            feature: Feature name.
            harness: Harness name.

        Returns:
            ``(success, message)`` tuple.
        """
        feature = feature.lower().strip()
        harness = harness.lower().strip()

        watches = self._load()
        original_count = len(watches)
        watches = [w for w in watches if not (w.feature == feature and w.harness == harness)]

        if len(watches) == original_count:
            return False, f"Not watching {feature} on {harness}."

        self._save(watches)
        return True, f"Removed {feature}/{harness} from watchlist."

    def list_watches(self) -> list[WatchEntry]:
        """Return all current watch entries."""
        return self._load()

    def check(self, update: bool = True) -> list[WatchlistHit]:
        """Compare current matrix support levels against stored levels.

        Returns entries where support changed since the last check. Updates
        the stored level for each entry if ``update=True``.

        Args:
            update: If True, persist new support levels after checking.

        Returns:
            List of :class:`WatchlistHit` objects for changed entries.
        """
        from src.harness_feature_matrix import HarnessFeatureMatrix

        watches = self._load()
        if not watches:
            return []

        matrix = HarnessFeatureMatrix()
        hits: list[WatchlistHit] = []
        _level_rank = {"native": 3, "partial": 2, "adapter": 1, "unsupported": 0}

        changed = False
        for entry in watches:
            current_level = matrix.query_feature(entry.feature, entry.harness)
            if current_level == entry.last_support_level:
                continue

            old_rank = _level_rank.get(entry.last_support_level, 0)
            new_rank = _level_rank.get(current_level, 0)
            improved = new_rank > old_rank

            hits.append(WatchlistHit(
                feature=entry.feature,
                harness=entry.harness,
                old_level=entry.last_support_level,
                new_level=current_level,
                improved=improved,
            ))

            if update:
                entry.last_support_level = current_level
                changed = True

        if update and changed:
            self._save(watches)

        return hits

    def format_status(self) -> str:
        """Return a formatted status table of all watch entries.

        Returns:
            Multi-line string showing each (feature, harness) pair with
            current support level. Empty watchlist returns a helpful hint.
        """
        from src.harness_feature_matrix import HarnessFeatureMatrix

        watches = self._load()
        if not watches:
            return (
                "Feature watchlist is empty.\n"
                "Add features with: /sync-gaps --watchlist-add <feature> <harness>\n"
                "Example: /sync-gaps --watchlist-add mcp aider"
            )

        matrix = HarnessFeatureMatrix()
        lines = [
            "Harness Feature Watchlist",
            "=" * 50,
            f"  {'Feature':<16}  {'Harness':<12}  {'Stored':<12}  {'Current':<12}  {'Changed?'}",
            "-" * 50,
        ]

        _level_rank = {"native": 3, "partial": 2, "adapter": 1, "unsupported": 0}

        for entry in sorted(watches, key=lambda w: (w.feature, w.harness)):
            current = matrix.query_feature(entry.feature, entry.harness)
            changed = current != entry.last_support_level
            old_rank = _level_rank.get(entry.last_support_level, 0)
            new_rank = _level_rank.get(current, 0)
            if changed:
                direction = "▲ improved" if new_rank > old_rank else "▼ regressed"
                changed_str = direction
            else:
                changed_str = "—"
            lines.append(
                f"  {entry.feature:<16}  {entry.harness:<12}  "
                f"{entry.last_support_level:<12}  {current:<12}  {changed_str}"
            )

        lines += [
            "",
            f"Watching {len(watches)} feature/harness pair(s).",
            "Run /sync-gaps --watchlist-check to detect and record changes.",
        ]
        return "\n".join(lines)

    def format_hits(self, hits: list[WatchlistHit]) -> str:
        """Format a list of watchlist hits for terminal display.

        Args:
            hits: Hits from ``check()``.

        Returns:
            Multi-line string, or empty string if no hits.
        """
        if not hits:
            return ""

        improved = [h for h in hits if h.improved]
        regressed = [h for h in hits if not h.improved]
        lines = ["Harness Feature Watchlist: Changes Detected", "=" * 50]

        if improved:
            lines.append("")
            lines.append("New support added:")
            lines.extend(h.format() for h in improved)

        if regressed:
            lines.append("")
            lines.append("Support regressed:")
            lines.extend(h.format() for h in regressed)

        lines += [
            "",
            f"Total changes: {len(hits)} "
            f"({len(improved)} improved, {len(regressed)} regressed).",
        ]
        return "\n".join(lines)

    # ── Storage ──────────────────────────────────────────────────────────────

    def _load(self) -> list[WatchEntry]:
        """Load watch entries from disk."""
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return [WatchEntry.from_dict(d) for d in data.get("watches", [])]
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, watches: list[WatchEntry]) -> None:
        """Persist watch entries to disk atomically."""
        self._state_dir.mkdir(parents=True, exist_ok=True)
        payload = {"watches": [w.to_dict() for w in watches]}
        content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

        import tempfile
        tmp_fd = None
        tmp_path = None
        try:
            tmp_fd = tempfile.NamedTemporaryFile(
                mode="w",
                dir=self._state_dir,
                suffix=".tmp",
                delete=False,
                encoding="utf-8",
            )
            tmp_path = Path(tmp_fd.name)
            tmp_fd.write(content)
            tmp_fd.flush()
            os.fsync(tmp_fd.fileno())
            tmp_fd.close()
            os.replace(str(tmp_path), str(self._path))
        except Exception:
            if tmp_fd and not tmp_fd.closed:
                tmp_fd.close()
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()
            raise
