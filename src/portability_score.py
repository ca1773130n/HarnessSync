from __future__ import annotations

"""Config Portability Score (Item 5).

Computes a 0-100 portability score for a CLAUDE.md / source config showing:
- Overall score per target harness
- Per-section breakdown: which sections translate cleanly, approximately,
  or are dropped entirely
- A plain-English summary

This is a lightweight *pre-sync* analysis — it does NOT require running sync.
It uses a static capability matrix and augments it with annotation-aware
rule counting from AnnotationFilter when annotations are present.

Usage::

    from src.portability_score import PortabilityScorer

    scorer = PortabilityScorer()
    report = scorer.analyze(source_data)
    print(scorer.format_report(report))

    # Verbose per-section breakdown
    print(scorer.format_report(report, verbose=True))
"""

from dataclasses import dataclass, field

from src.utils.constants import CORE_TARGETS

# ---------------------------------------------------------------------------
# Capability levels
# ---------------------------------------------------------------------------
FULL    = "full"     # 100 pts — translates directly with no data loss
PARTIAL = "partial"  # 70 pts  — approximated or adapted (some loss)
NONE    = "none"     # 0 pts   — dropped entirely

# Static capability matrix: target → {section → level}
# Based on CompatibilityReporter.CAPABILITY and harness feature matrices.
_CAPABILITY: dict[str, dict[str, str]] = {
    "codex":    {"rules": FULL,    "skills": PARTIAL, "agents": PARTIAL,
                 "commands": PARTIAL, "mcp": PARTIAL,   "settings": PARTIAL},
    "gemini":   {"rules": FULL,    "skills": PARTIAL, "agents": PARTIAL,
                 "commands": PARTIAL, "mcp": FULL,     "settings": PARTIAL},
    "opencode": {"rules": FULL,    "skills": PARTIAL, "agents": PARTIAL,
                 "commands": PARTIAL, "mcp": FULL,     "settings": PARTIAL},
    "cursor":   {"rules": FULL,    "skills": PARTIAL, "agents": PARTIAL,
                 "commands": PARTIAL, "mcp": FULL,     "settings": PARTIAL},
    "aider":    {"rules": PARTIAL, "skills": NONE,    "agents": NONE,
                 "commands": NONE,    "mcp": NONE,     "settings": PARTIAL},
    "windsurf": {"rules": FULL,    "skills": NONE,    "agents": NONE,
                 "commands": NONE,    "mcp": PARTIAL,  "settings": PARTIAL},
    "vscode":   {"rules": PARTIAL, "skills": NONE,    "agents": NONE,
                 "commands": NONE,    "mcp": FULL,     "settings": NONE},
    "cline":    {"rules": FULL,    "skills": NONE,    "agents": NONE,
                 "commands": NONE,    "mcp": FULL,     "settings": NONE},
    "continue": {"rules": PARTIAL, "skills": NONE,    "agents": NONE,
                 "commands": NONE,    "mcp": FULL,     "settings": NONE},
    "zed":      {"rules": FULL,    "skills": NONE,    "agents": NONE,
                 "commands": NONE,    "mcp": FULL,     "settings": NONE},
    "neovim":   {"rules": FULL,    "skills": NONE,    "agents": NONE,
                 "commands": NONE,    "mcp": FULL,     "settings": PARTIAL},
}

_SECTION_WEIGHTS: dict[str, float] = {
    "rules": 2.0, "mcp": 1.5, "skills": 1.5,
    "agents": 1.0, "commands": 1.0, "settings": 1.0,
}

_SUPPORT_PTS: dict[str, float] = {FULL: 100.0, PARTIAL: 70.0, NONE: 0.0}

_GRADE_THRESHOLDS: list[tuple[float, str, str]] = [
    (90, "A", "Excellent"),
    (75, "B", "Good"),
    (50, "C", "Fair"),
    (25, "D", "Poor"),
    (0,  "F", "Critical"),
]

_SECTION_LABELS: dict[str, str] = {
    "rules":    "Rules",
    "skills":   "Skills",
    "agents":   "Agents",
    "commands": "Commands",
    "mcp":      "MCP servers",
    "settings": "Settings",
}

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class SectionPortability:
    """Portability result for one config section in one target."""

    section: str
    capability: str   # FULL | PARTIAL | NONE
    score: float      # 0–100
    item_count: int   # Items in source for this section
    note: str = ""    # Human-readable explanation


@dataclass
class TargetPortabilityResult:
    """Portability score for one target harness."""

    target: str
    overall_score: float
    grade: str
    label: str
    sections: list[SectionPortability] = field(default_factory=list)
    active_sections: int = 0
    clean_sections: list[str] = field(default_factory=list)
    adapted_sections: list[str] = field(default_factory=list)
    dropped_sections: list[str] = field(default_factory=list)


@dataclass
class PortabilityReport:
    """Full portability analysis across all targets."""

    results: list[TargetPortabilityResult] = field(default_factory=list)
    source_section_counts: dict[str, int] = field(default_factory=dict)
    annotation_harnesses: list[str] = field(default_factory=list)

    @property
    def best_target(self) -> str | None:
        if not self.results:
            return None
        return max(self.results, key=lambda r: r.overall_score).target

    @property
    def worst_target(self) -> str | None:
        if not self.results:
            return None
        return min(self.results, key=lambda r: r.overall_score).target


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_section(source_data: dict, section: str) -> int:
    """Count items in a source section."""
    # SourceReader uses "mcp_servers" for MCP, but section key is "mcp"
    key = "mcp_servers" if section == "mcp" else section
    val = source_data.get(key) or source_data.get(section)
    if val is None:
        return 0
    if isinstance(val, dict):
        return len(val)
    if isinstance(val, list):
        return len(val)
    if isinstance(val, str):
        # Count non-empty, non-heading lines as a rough rule count
        return len([ln for ln in val.splitlines() if ln.strip() and not ln.startswith("#")])
    return 1


def _grade(score: float) -> tuple[str, str]:
    """Return (grade_letter, grade_label) for a 0-100 score."""
    for threshold, grade, label in _GRADE_THRESHOLDS:
        if score >= threshold:
            return grade, label
    return "F", "Critical"


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class PortabilityScorer:
    """Compute config portability scores without running sync.

    Args:
        targets: Harness targets to score.  Defaults to ``CORE_TARGETS``.
    """

    def __init__(self, targets: list[str] | None = None) -> None:
        self._targets = list(targets or CORE_TARGETS)

    def analyze(self, source_data: dict) -> PortabilityReport:
        """Compute portability scores for all configured targets.

        Args:
            source_data: Output of ``SourceReader.discover_all()``.

        Returns:
            :class:`PortabilityReport` with per-target and per-section scores.
        """
        # Count source items per section
        section_counts: dict[str, int] = {
            s: _count_section(source_data, s) for s in _SECTION_WEIGHTS
        }
        active_sections = {s for s, c in section_counts.items() if c > 0}

        # Check for annotation-filtered harnesses
        ann_harnesses: list[str] = []
        try:
            from src.annotation_filter import AnnotationFilter
            rules_content = source_data.get("rules", "")
            if isinstance(rules_content, list):
                rules_content = "\n".join(
                    r.get("content", "") if isinstance(r, dict) else str(r)
                    for r in rules_content
                )
            if AnnotationFilter.has_annotations(str(rules_content)):
                ann_summary = AnnotationFilter.extract_annotation_summary(str(rules_content))
                ann_harnesses = sorted(ann_summary.keys())
        except ImportError:
            pass

        results: list[TargetPortabilityResult] = []
        for target in self._targets:
            caps = _CAPABILITY.get(target, {})
            weighted_sum = 0.0
            weight_total = 0.0
            sections: list[SectionPortability] = []
            clean: list[str] = []
            adapted: list[str] = []
            dropped: list[str] = []

            for section in _SECTION_WEIGHTS:
                if section not in active_sections:
                    continue
                cap = caps.get(section, NONE)
                score = _SUPPORT_PTS[cap]
                w = _SECTION_WEIGHTS[section]
                weighted_sum += score * w
                weight_total += w

                note_map = {
                    FULL:    f"Translates directly to {target}",
                    PARTIAL: f"Approximated in {target} (some loss)",
                    NONE:    f"No equivalent in {target} — dropped",
                }
                sections.append(SectionPortability(
                    section=section,
                    capability=cap,
                    score=score,
                    item_count=section_counts[section],
                    note=note_map[cap],
                ))
                if cap == FULL:
                    clean.append(section)
                elif cap == PARTIAL:
                    adapted.append(section)
                else:
                    dropped.append(section)

            overall = round(weighted_sum / weight_total, 1) if weight_total > 0 else 100.0
            grade, grade_label = _grade(overall)
            results.append(TargetPortabilityResult(
                target=target,
                overall_score=overall,
                grade=grade,
                label=grade_label,
                sections=sections,
                active_sections=len(active_sections),
                clean_sections=clean,
                adapted_sections=adapted,
                dropped_sections=dropped,
            ))

        # Sort best-first
        results.sort(key=lambda r: -r.overall_score)
        return PortabilityReport(
            results=results,
            source_section_counts=section_counts,
            annotation_harnesses=ann_harnesses,
        )

    def format_report(self, report: PortabilityReport, verbose: bool = False) -> str:
        """Format a portability report for terminal display.

        Args:
            report: Output of :meth:`analyze`.
            verbose: If ``True``, show per-section details for every target.

        Returns:
            Multi-line formatted string.
        """
        lines = ["Config Portability Score", "=" * 55, ""]

        # Source inventory
        active = {s: c for s, c in report.source_section_counts.items() if c > 0}
        if active:
            parts = [f"{c} {_SECTION_LABELS.get(s, s)}" for s, c in active.items()]
            lines.append(f"Source config: {', '.join(parts)}")
            lines.append("")

        if report.annotation_harnesses:
            harnesses_str = ", ".join(report.annotation_harnesses)
            lines.append(f"Harness-targeted annotations found for: {harnesses_str}")
            lines.append("")

        # Per-target score table
        col_t = 12
        lines.append(f"{'Target':<{col_t}} {'Score':>6}  Grade  {'Label':<10}  Notes")
        lines.append("-" * 65)

        for result in report.results:
            bar_len = int(result.overall_score / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            notes_parts = []
            if result.adapted_sections:
                notes_parts.append("~" + ",".join(result.adapted_sections))
            if result.dropped_sections:
                notes_parts.append("✗" + ",".join(result.dropped_sections))
            notes = "  ".join(notes_parts) if notes_parts else "all clean"

            lines.append(
                f"{result.target:<{col_t}} {result.overall_score:>5.0f}%"
                f"  [{result.grade}]  {result.label:<10}  {notes}"
            )

            if verbose:
                for sec in result.sections:
                    icon = {"full": "✓", "partial": "~", "none": "✗"}.get(sec.capability, "?")
                    count_str = f"({sec.item_count} item{'s' if sec.item_count != 1 else ''})"
                    lines.append(
                        f"  {icon} {_SECTION_LABELS.get(sec.section, sec.section):<12}"
                        f" {count_str:<16} {sec.note}"
                    )
                lines.append("")

        lines.extend([
            "",
            "Score = weighted translation fidelity (rules×2, MCP×1.5, skills×1.5, others×1).",
            "✓ clean (no loss)   ~ adapted (some loss)   ✗ dropped",
            f"Best target: {report.best_target or 'N/A'}"
            f"   Worst: {report.worst_target or 'N/A'}",
        ])
        return "\n".join(lines)
