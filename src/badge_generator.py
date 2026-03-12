from __future__ import annotations

"""README Sync Health Badge Generator (item 28).

Generates dynamic SVG badges showing last sync time and fidelity score per
target harness. Teams embed these in README.md so contributors instantly know
harness config health.

Badge format mirrors the Shields.io flat style:
  [HarnessSync | codex: 94/100 · 2h ago]

Usage:
    from src.badge_generator import BadgeGenerator, SyncBadgeData

    gen = BadgeGenerator(project_dir)
    badges = gen.generate_all()
    for target, svg in badges.items():
        Path(f".harnesssync/badges/{target}.svg").write_text(svg)

    # Get README snippet
    print(gen.readme_snippet(badges))

CLI integration: /sync --badges writes badges to .harnesssync/badges/
"""

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from src.state_manager import StateManager


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class SyncBadgeData:
    """Input data for generating a badge.

    Attributes:
        target: Harness target name (e.g. 'codex').
        fidelity_score: 0-100 translation fidelity (None if unknown).
        last_sync_ts: Unix timestamp of last sync (None if never synced).
        status: 'synced' | 'drifted' | 'never' | 'error'.
    """

    target: str
    fidelity_score: float | None = None
    last_sync_ts: float | None = None
    status: str = "synced"  # 'synced' | 'drifted' | 'never' | 'error'

    @property
    def age_str(self) -> str:
        """Return human-readable age string (e.g. '2h ago', 'just now')."""
        if self.last_sync_ts is None:
            return "never"
        elapsed = time.time() - self.last_sync_ts
        if elapsed < 60:
            return "just now"
        elif elapsed < 3600:
            return f"{int(elapsed / 60)}m ago"
        elif elapsed < 86400:
            return f"{int(elapsed / 3600)}h ago"
        else:
            return f"{int(elapsed / 86400)}d ago"

    @property
    def score_str(self) -> str:
        """Return fidelity score as string (e.g. '94/100' or '?')."""
        if self.fidelity_score is None:
            return "?"
        return f"{self.fidelity_score:.0f}/100"

    @property
    def label_text(self) -> str:
        """Right-side badge text."""
        if self.status == "never":
            return "not synced"
        if self.status == "error":
            return "error"
        if self.status == "drifted":
            return f"drifted · {self.age_str}"
        score = f"{self.score_str}" if self.fidelity_score is not None else ""
        age = self.age_str
        parts = [p for p in [score, age] if p]
        return " · ".join(parts) if parts else "synced"

    @property
    def color(self) -> str:
        """Badge right-side background color (hex)."""
        if self.status in ("never", "error"):
            return "#e05d44"  # red
        if self.status == "drifted":
            return "#dfb317"  # yellow
        if self.fidelity_score is None:
            return "#4c1"    # green (no score info)
        if self.fidelity_score >= 90:
            return "#4c1"    # bright green
        if self.fidelity_score >= 75:
            return "#97ca00"  # green
        if self.fidelity_score >= 50:
            return "#dfb317"  # yellow
        return "#e05d44"      # red


# ---------------------------------------------------------------------------
# SVG generation
# ---------------------------------------------------------------------------

def _svg_text_width(text: str) -> int:
    """Estimate pixel width of text rendered at ~11px Verdana.

    Uses a simple character-width table; not perfect but good enough for
    badge sizing without a font rendering engine.
    """
    # Widths for common chars at 11px Verdana (approx)
    wide = frozenset("mwMW")
    narrow = frozenset("fijlrt!|() ·")
    width = 0
    for ch in text:
        if ch in wide:
            width += 9
        elif ch in narrow:
            width += 5
        else:
            width += 7
    return width


def _xml_escape(text: str) -> str:
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_badge_svg(
    left_label: str,
    right_label: str,
    color: str = "#4c1",
    left_color: str = "#555",
) -> str:
    """Render a Shields.io-style flat SVG badge.

    Args:
        left_label: Left (dark) side text (e.g. 'harnesssync · codex').
        right_label: Right (colored) side text (e.g. '94/100 · 2h ago').
        color: Right side background hex color.
        left_color: Left side background hex color.

    Returns:
        SVG string.
    """
    left_w = _svg_text_width(left_label) + 20
    right_w = _svg_text_width(right_label) + 20
    total_w = left_w + right_w
    height = 20

    left_text_x = left_w // 2 + 1
    right_text_x = left_w + right_w // 2 + 1

    left_label_esc = _xml_escape(left_label)
    right_label_esc = _xml_escape(right_label)

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{height}">
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r">
    <rect width="{total_w}" height="{height}" rx="3" fill="#fff"/>
  </clipPath>
  <g clip-path="url(#r)">
    <rect width="{left_w}" height="{height}" fill="{left_color}"/>
    <rect x="{left_w}" width="{right_w}" height="{height}" fill="{color}"/>
    <rect width="{total_w}" height="{height}" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="11">
    <text x="{left_text_x}" y="15" fill="#010101" fill-opacity=".3">{left_label_esc}</text>
    <text x="{left_text_x}" y="14">{left_label_esc}</text>
    <text x="{right_text_x}" y="15" fill="#010101" fill-opacity=".3">{right_label_esc}</text>
    <text x="{right_text_x}" y="14">{right_label_esc}</text>
  </g>
</svg>"""


# ---------------------------------------------------------------------------
# High-level generator
# ---------------------------------------------------------------------------

class BadgeGenerator:
    """Generates sync health SVG badges from current state.

    Reads last-sync timestamps from StateManager and fidelity scores from
    the most recent sync run's state file. Falls back gracefully when no
    sync has ever run.

    Args:
        project_dir: Project root directory.
    """

    BADGE_DIR = ".harnesssync/badges"

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self._state = StateManager()

    def collect_badge_data(self, targets: list[str] | None = None) -> dict[str, SyncBadgeData]:
        """Collect badge data for all (or specified) targets.

        Args:
            targets: If provided, only these targets. Otherwise all known.

        Returns:
            Dict mapping target_name -> SyncBadgeData.
        """
        from src.adapters import AdapterRegistry

        if targets is None:
            targets = AdapterRegistry.list_targets()

        badge_map: dict[str, SyncBadgeData] = {}

        for target in targets:
            ts = self._last_sync_ts(target)
            fidelity = self._fidelity_score(target)
            drift = self._is_drifted(target)

            if ts is None:
                status = "never"
            elif drift:
                status = "drifted"
            else:
                status = "synced"

            badge_map[target] = SyncBadgeData(
                target=target,
                fidelity_score=fidelity,
                last_sync_ts=ts,
                status=status,
            )

        return badge_map

    def generate_all(self, targets: list[str] | None = None) -> dict[str, str]:
        """Generate SVG badge strings for all targets.

        Args:
            targets: If provided, only these targets.

        Returns:
            Dict mapping target_name -> SVG string.
        """
        badge_data = self.collect_badge_data(targets)
        return {
            target: render_badge_svg(
                left_label=f"harnesssync · {target}",
                right_label=data.label_text,
                color=data.color,
            )
            for target, data in badge_data.items()
        }

    def write_badges(self, targets: list[str] | None = None) -> dict[str, Path]:
        """Generate and write SVG badges to .harnesssync/badges/.

        Args:
            targets: If provided, only write these targets.

        Returns:
            Dict mapping target_name -> written file path.
        """
        badge_dir = self.project_dir / self.BADGE_DIR
        badge_dir.mkdir(parents=True, exist_ok=True)

        svgs = self.generate_all(targets)
        written: dict[str, Path] = {}
        for target, svg in svgs.items():
            out = badge_dir / f"{target}.svg"
            out.write_text(svg, encoding="utf-8")
            written[target] = out
        return written

    def readme_snippet(self, badges: dict[str, str] | None = None) -> str:
        """Return a Markdown snippet for embedding badges in README.md.

        Args:
            badges: Dict from generate_all(). If None, calls generate_all().

        Returns:
            Markdown string with image tags.
        """
        if badges is None:
            badges = self.generate_all()

        badge_dir = self.BADGE_DIR
        lines = ["<!-- HarnessSync badges — auto-generated, do not edit manually -->"]
        for target in sorted(badges):
            path = f"{badge_dir}/{target}.svg"
            lines.append(
                f"![{target} sync health]({path})"
            )
        return " ".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _last_sync_ts(self, target: str) -> float | None:
        """Return last sync Unix timestamp for target, or None."""
        try:
            state = self._state.get_state(target)
            if state:
                ts = state.get("last_sync_time") or state.get("last_sync")
                if ts:
                    return float(ts)
        except Exception:
            pass
        return None

    def _fidelity_score(self, target: str) -> float | None:
        """Return cached fidelity score for target from state, or None."""
        try:
            state = self._state.get_state(target)
            if state:
                return state.get("fidelity_score")
        except Exception:
            pass
        return None

    def _is_drifted(self, target: str) -> bool:
        """Return True if the target config has drifted from last sync."""
        try:
            state = self._state.get_state(target)
            if state:
                return bool(state.get("drift_detected", False))
        except Exception:
            pass
        return False
