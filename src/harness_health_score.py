from __future__ import annotations

"""Per-harness sync health score (0-100) with badge rendering (item 23).

Assigns each harness a numeric health score based on observable state:
- Sync recency      (30 pts): How recently was this harness last synced?
- Config coverage   (25 pts): How many supported sections are synced?
- Drift amount      (20 pts): Are the synced files still at last-sync state?
- Skip ratio        (15 pts): What fraction of items got synced (not skipped)?
- Error rate        (10 pts): Any failed items in the last sync?

The score is rendered as a terminal badge:

    codex    [████████░░]  84/100  (synced 2h ago)
    gemini   [██████░░░░]  62/100  (drift detected)
    aider    [████░░░░░░]  41/100  (never synced)

Usage::

    scorer = HarnessHealthScorer(project_dir=Path("."))
    scores = scorer.score_all()
    print(scorer.format_dashboard(scores))
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.constants import CORE_TARGETS


# --- Per-target expected section support (max coverage score denominator) ---
_SUPPORTED_SECTIONS: dict[str, frozenset[str]] = {
    "codex":    frozenset({"rules", "skills", "agents", "commands", "mcp", "settings"}),
    "gemini":   frozenset({"rules", "skills", "agents", "commands", "mcp", "settings"}),
    "opencode": frozenset({"rules", "skills", "agents", "commands", "mcp", "settings"}),
    "cursor":   frozenset({"rules", "skills", "agents", "commands", "mcp", "settings"}),
    "aider":    frozenset({"rules", "settings"}),
    "windsurf": frozenset({"rules", "mcp", "settings"}),
    "cline":    frozenset({"rules", "mcp", "settings"}),
    "continue": frozenset({"rules", "mcp", "settings"}),
    "zed":      frozenset({"rules", "settings"}),
    "neovim":   frozenset({"rules", "settings"}),
}


@dataclass
class HarnessHealthScore:
    """Health score and metadata for a single harness target.

    Attributes:
        target:          Harness name.
        score:           Overall 0-100 score.
        recency_score:   Sub-score: sync recency (0-30).
        coverage_score:  Sub-score: config coverage (0-25).
        drift_score:     Sub-score: drift status (0-20).
        skip_score:      Sub-score: skip ratio (0-15).
        error_score:     Sub-score: error rate (0-10).
        last_sync_age:   Seconds since last sync (None = never).
        drift_detected:  True if target files differ from last-sync snapshot.
        status_label:    Human-readable status ("healthy" | "warning" | "stale" | "unknown").
        notes:           List of actionable observations.
    """

    target: str
    score: int
    recency_score: int = 0
    coverage_score: int = 0
    drift_score: int = 0
    skip_score: int = 0
    error_score: int = 0
    last_sync_age: float | None = None
    drift_detected: bool = False
    status_label: str = "unknown"
    notes: list[str] = field(default_factory=list)

    @property
    def badge(self) -> str:
        """Render a compact ASCII progress bar badge.

        Returns:
            E.g. "[████████░░]  84/100"
        """
        filled = round(self.score / 10)
        bar = "█" * filled + "░" * (10 - filled)
        return f"[{bar}] {self.score:>3}/100"

    @property
    def status_icon(self) -> str:
        icons = {"healthy": "✓", "warning": "~", "stale": "○", "unknown": "?", "critical": "✗"}
        return icons.get(self.status_label, "?")


class HarnessHealthScorer:
    """Computes health scores for all configured harness targets.

    Args:
        project_dir: Project root (used to locate state files).
        state_dir: Override for the harnesssync state directory.
    """

    def __init__(
        self,
        project_dir: Path | None = None,
        state_dir: Path | None = None,
    ) -> None:
        self._project_dir = project_dir or Path.cwd()
        self._state_dir = state_dir or (Path.home() / ".harnesssync")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, target: str) -> HarnessHealthScore:
        """Compute a health score for a single harness target.

        Args:
            target: Harness name (e.g. "codex", "gemini").

        Returns:
            HarnessHealthScore with all sub-scores populated.
        """
        state = self._load_target_state(target)
        notes: list[str] = []

        # --- Recency (0-30 pts) ---
        recency_score, recency_note = self._score_recency(state)
        if recency_note:
            notes.append(recency_note)

        # --- Coverage (0-25 pts) ---
        coverage_score, coverage_note = self._score_coverage(target, state)
        if coverage_note:
            notes.append(coverage_note)

        # --- Drift (0-20 pts) ---
        drift_detected = self._detect_drift(target, state)
        drift_score = 0 if drift_detected else 20
        if drift_detected:
            notes.append("Config drift detected — run /sync to restore.")

        # --- Skip ratio (0-15 pts) ---
        skip_score, skip_note = self._score_skip_ratio(state)
        if skip_note:
            notes.append(skip_note)

        # --- Error rate (0-10 pts) ---
        error_score, error_note = self._score_errors(state)
        if error_note:
            notes.append(error_note)

        total = recency_score + coverage_score + drift_score + skip_score + error_score

        last_sync_age: float | None = None
        last_sync_ts = state.get("last_sync_time") or state.get("last_sync")
        if last_sync_ts:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(str(last_sync_ts).replace("Z", "+00:00"))
                last_sync_age = time.time() - dt.timestamp()
            except (ValueError, OSError):
                pass

        status_label = _classify_status(total, drift_detected, last_sync_age)

        return HarnessHealthScore(
            target=target,
            score=total,
            recency_score=recency_score,
            coverage_score=coverage_score,
            drift_score=drift_score,
            skip_score=skip_score,
            error_score=error_score,
            last_sync_age=last_sync_age,
            drift_detected=drift_detected,
            status_label=status_label,
            notes=notes,
        )

    def score_all(self, targets: list[str] | None = None) -> list[HarnessHealthScore]:
        """Score all (or a subset of) harness targets.

        Args:
            targets: Targets to score (default: registered adapter targets).

        Returns:
            List of HarnessHealthScore sorted by score descending.
        """
        if targets is None:
            targets = self._get_registered_targets()
        scores = [self.score(t) for t in targets]
        return sorted(scores, key=lambda s: s.score, reverse=True)

    def format_dashboard(self, scores: list[HarnessHealthScore]) -> str:
        """Render all health scores as a terminal dashboard table.

        Args:
            scores: List of HarnessHealthScore from score_all().

        Returns:
            Multi-line formatted table string.
        """
        if not scores:
            return "No harness targets configured. Run /sync-setup to add targets."

        lines = [
            "Harness Health Scores",
            "=" * 60,
            "",
            f"  {'Target':<12} {'Score':<18} {'Status':<10} {'Last Sync':<14} {'Notes'}",
            "  " + "-" * 56,
        ]

        for hs in scores:
            age_str = _format_age(hs.last_sync_age)
            note_str = hs.notes[0] if hs.notes else ""
            if len(note_str) > 30:
                note_str = note_str[:27] + "..."
            icon = hs.status_icon
            lines.append(
                f"  {icon} {hs.target:<10} {hs.badge}  "
                f"{hs.status_label:<10} {age_str:<14} {note_str}"
            )

        lines.append("")
        overall = round(sum(s.score for s in scores) / len(scores)) if scores else 0
        lines.append(f"  Overall average: {overall}/100")
        lines.append("  Run /sync-health --score for full breakdown.")
        return "\n".join(lines)

    def format_single(self, hs: HarnessHealthScore) -> str:
        """Render a detailed breakdown for a single harness.

        Args:
            hs: HarnessHealthScore from score().

        Returns:
            Multi-line breakdown string.
        """
        lines = [
            f"Health Score: {hs.target.title()}",
            "=" * 40,
            f"  Overall:   {hs.badge}  [{hs.status_icon} {hs.status_label}]",
            "",
            "  Breakdown:",
            f"    Sync recency   {hs.recency_score:>3}/30 pts",
            f"    Config cover.  {hs.coverage_score:>3}/25 pts",
            f"    Drift status   {hs.drift_score:>3}/20 pts",
            f"    Skip ratio     {hs.skip_score:>3}/15 pts",
            f"    Error rate     {hs.error_score:>3}/10 pts",
        ]
        if hs.notes:
            lines.append("")
            lines.append("  Observations:")
            for note in hs.notes:
                lines.append(f"    • {note}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_target_state(self, target: str) -> dict:
        """Load state for *target* from the state file."""
        state_file = self._state_dir / "state.json"
        if not state_file.exists():
            return {}
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

        # v2 schema: accounts -> default -> targets
        accounts = data.get("accounts", {})
        for acct in accounts.values():
            targets = acct.get("targets", {})
            if target in targets:
                return targets[target]

        # v1 fallback
        return data.get("targets", {}).get(target, {})

    def _score_recency(self, state: dict) -> tuple[int, str]:
        """Score based on how recently the last sync occurred.

        Returns:
            (score 0-30, note or "")
        """
        ts = state.get("last_sync_time") or state.get("last_sync")
        if not ts:
            return 0, "Never synced — run /sync to get started."

        try:
            from datetime import datetime
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            age_secs = time.time() - dt.timestamp()
        except (ValueError, OSError):
            return 5, "Last sync timestamp could not be parsed."

        # Full points if synced within 1 day; decay to 0 at 30 days
        if age_secs < 3600:          # < 1 h
            return 30, ""
        elif age_secs < 86400:       # < 1 day
            return 25, ""
        elif age_secs < 3 * 86400:   # < 3 days
            return 18, ""
        elif age_secs < 7 * 86400:   # < 1 week
            return 12, "Last sync > 3 days ago — consider re-syncing."
        elif age_secs < 30 * 86400:  # < 1 month
            return 6, "Last sync > 1 week ago — config may be stale."
        else:
            return 0, "Last sync > 30 days ago — config is likely very stale."

    def _score_coverage(self, target: str, state: dict) -> tuple[int, str]:
        """Score based on how many supported sections were synced.

        Returns:
            (score 0-25, note or "")
        """
        supported = _SUPPORTED_SECTIONS.get(target, frozenset())
        if not supported:
            return 25, ""  # Unknown target, assume full coverage

        sync_method = state.get("sync_method", {})
        if not sync_method:
            # No state yet — assume 0 coverage
            return 0, f"No sync data found for {target}."

        synced_sections = {k for k, v in sync_method.items() if v != "not_synced"}
        coverage = len(synced_sections & supported) / len(supported)
        score = round(coverage * 25)

        missing = supported - synced_sections
        if missing:
            note = f"Missing sections: {', '.join(sorted(missing))}."
            return score, note
        return score, ""

    def _detect_drift(self, target: str, state: dict) -> bool:
        """Return True if any tracked config files differ from stored hashes."""
        file_hashes = state.get("file_hashes", {})
        if not file_hashes:
            return False

        for rel_path, stored_hash in file_hashes.items():
            full = self._project_dir / rel_path
            if not full.exists():
                return True  # File was deleted
            try:
                from src.utils.hashing import hash_file_sha256
                current = hash_file_sha256(full)
                if current != stored_hash:
                    return True
            except Exception:
                pass
        return False

    def _score_skip_ratio(self, state: dict) -> tuple[int, str]:
        """Score based on ratio of synced vs skipped items.

        Returns:
            (score 0-15, note or "")
        """
        synced = state.get("items_synced", 0) or 0
        skipped = state.get("items_skipped", 0) or 0
        total = synced + skipped
        if total == 0:
            return 10, ""  # Nothing to sync yet — neutral

        ratio = synced / total
        score = round(ratio * 15)
        if ratio < 0.5:
            pct = round((1 - ratio) * 100)
            return score, f"{pct}% of items skipped — run /sync-lint --compat for details."
        return score, ""

    def _score_errors(self, state: dict) -> tuple[int, str]:
        """Score based on failed items in the last sync.

        Returns:
            (score 0-10, note or "")
        """
        failed = state.get("items_failed", 0) or 0
        if failed == 0:
            return 10, ""
        if failed == 1:
            return 5, "1 item failed in last sync — check /sync-log for details."
        return 0, f"{failed} items failed in last sync — run /sync-health for details."

    def _get_registered_targets(self) -> list[str]:
        """Return the list of registered adapter targets."""
        try:
            from src.adapters.registry import AdapterRegistry
            return AdapterRegistry.list_targets()
        except Exception:
            return list(CORE_TARGETS)


def _classify_status(score: int, drift: bool, age_secs: float | None) -> str:
    """Classify a score into a human-readable status label."""
    if age_secs is None:
        return "unknown"
    if drift:
        return "warning"
    if score >= 80:
        return "healthy"
    if score >= 55:
        return "warning"
    if age_secs and age_secs > 30 * 86400:
        return "stale"
    if score < 30:
        return "critical"
    return "warning"


def _format_age(age_secs: float | None) -> str:
    """Format seconds-since-last-sync as a human-readable age."""
    if age_secs is None:
        return "never"
    if age_secs < 60:
        return "just now"
    if age_secs < 3600:
        return f"{int(age_secs / 60)}m ago"
    if age_secs < 86400:
        return f"{int(age_secs / 3600)}h ago"
    return f"{int(age_secs / 86400)}d ago"
