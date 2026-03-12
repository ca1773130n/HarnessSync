from __future__ import annotations

"""Config complexity scorer for HarnessSync.

Scores each harness's synced configuration on multiple complexity dimensions:
- rule_count: number of distinct rule files / sections
- mcp_count: number of MCP servers
- skill_count: number of skills
- agent_count: number of agents
- permission_scope: breadth of permission grants
- rules_size_kb: size of synced rules in KB

Surfaces configs that have grown unwieldy and suggests cleanup.
Turns an invisible problem into a visible, actionable metric (0-100).
"""

from dataclasses import dataclass, field
from pathlib import Path


# Complexity penalty weights (higher = more impact on score)
_WEIGHTS = {
    "rules_size_kb": 2.0,    # KB of rules content
    "rule_sections": 1.5,    # Number of distinct rule files/sections
    "mcp_count": 1.0,        # Number of MCP servers
    "skill_count": 0.5,      # Number of skills
    "agent_count": 0.5,      # Number of agents
    "command_count": 0.3,    # Number of commands
}

# Thresholds per dimension for scoring
_THRESHOLDS = {
    "rules_size_kb":   {"low": 10.0, "medium": 30.0, "high": 60.0},
    "rule_sections":   {"low": 3,    "medium": 8,    "high": 15},
    "mcp_count":       {"low": 3,    "medium": 8,    "high": 15},
    "skill_count":     {"low": 5,    "medium": 15,   "high": 30},
    "agent_count":     {"low": 3,    "medium": 10,   "high": 20},
    "command_count":   {"low": 5,    "medium": 15,   "high": 30},
}


@dataclass
class ComplexityDimension:
    """Score for a single complexity dimension."""
    name: str
    value: float
    level: str    # "low" | "medium" | "high"
    score: int    # 0-100 (higher = more complex)


@dataclass
class HarnessComplexityReport:
    """Complexity report for a single target harness."""
    target: str
    dimensions: list[ComplexityDimension] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)

    @property
    def overall_score(self) -> int:
        """Weighted complexity score 0-100 (higher = more complex/unwieldy)."""
        if not self.dimensions:
            return 0
        total_weight = sum(_WEIGHTS.get(d.name, 1.0) for d in self.dimensions)
        if total_weight == 0:
            return 0
        weighted_sum = sum(
            d.score * _WEIGHTS.get(d.name, 1.0) for d in self.dimensions
        )
        return min(100, int(weighted_sum / total_weight))

    @property
    def label(self) -> str:
        score = self.overall_score
        if score < 25:
            return "simple"
        if score < 50:
            return "moderate"
        if score < 75:
            return "complex"
        return "unwieldy"

    def format_summary(self) -> str:
        bar_len = self.overall_score // 5
        bar = "#" * bar_len + "." * (20 - bar_len)
        return (
            f"{self.target:<12} [{bar}] {self.overall_score:>3}/100 ({self.label})"
        )


@dataclass
class ConfigComplexityReport:
    """Aggregated complexity report across all harnesses."""
    harnesses: list[HarnessComplexityReport] = field(default_factory=list)

    def format(self, verbose: bool = False) -> str:
        """Format human-readable complexity report.

        Args:
            verbose: Include per-dimension breakdown (default: totals only).
        """
        if not self.harnesses:
            return "Config Complexity: No synced harness configs found."

        lines = ["## Config Complexity Report", ""]
        lines.append("Score: 0=simple, 100=unwieldy. Consider cleanup above 75.\n")

        # Sort by score descending
        sorted_harnesses = sorted(self.harnesses, key=lambda h: h.overall_score, reverse=True)

        for h in sorted_harnesses:
            lines.append(f"  {h.format_summary()}")
            if verbose:
                for d in h.dimensions:
                    if d.level != "low":
                        lines.append(
                            f"    - {d.name}: {d.value:.1f} [{d.level.upper()}]"
                        )
                if h.suggestions:
                    for s in h.suggestions:
                        lines.append(f"    ! {s}")
            lines.append("")

        # Summary suggestion
        high_complexity = [h for h in sorted_harnesses if h.overall_score >= 75]
        if high_complexity:
            lines.append("Targets with score >= 75 are unwieldy — consider:")
            lines.append("  - Using <!-- sync:exclude --> to filter verbose sections")
            lines.append("  - Splitting CLAUDE.md into scoped rule files")
            lines.append("  - Reducing MCP server count per target")

        return "\n".join(lines)


def _score_dimension(name: str, value: float) -> ComplexityDimension:
    """Score a single dimension value against thresholds."""
    thresholds = _THRESHOLDS.get(name, {"low": 5.0, "medium": 15.0, "high": 30.0})
    if value <= thresholds["low"]:
        level = "low"
        score = int(value / thresholds["low"] * 25)
    elif value <= thresholds["medium"]:
        level = "medium"
        frac = (value - thresholds["low"]) / (thresholds["medium"] - thresholds["low"])
        score = 25 + int(frac * 25)
    elif value <= thresholds["high"]:
        level = "high"
        frac = (value - thresholds["medium"]) / (thresholds["high"] - thresholds["medium"])
        score = 50 + int(frac * 25)
    else:
        level = "high"
        score = min(100, 75 + int((value - thresholds["high"]) / thresholds["high"] * 25))

    return ComplexityDimension(name=name, value=value, level=level, score=score)


class ConfigComplexityScorer:
    """Scores the complexity of synced harness configurations.

    Args:
        project_dir: Project root directory.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def score_all(self, targets: list[str] | None = None) -> ConfigComplexityReport:
        """Score all known synced targets.

        Args:
            targets: Specific targets to check (None = auto-detect from files present).

        Returns:
            ConfigComplexityReport.
        """
        if targets is None:
            targets = self._detect_synced_targets()

        report = ConfigComplexityReport()
        for target in targets:
            harness_report = self._score_target(target)
            if harness_report is not None:
                report.harnesses.append(harness_report)

        return report

    def _detect_synced_targets(self) -> list[str]:
        """Auto-detect targets by looking for known output files."""
        from src.adapters import AdapterRegistry
        found = []
        rules_files = {
            "codex": "AGENTS.md",
            "gemini": "GEMINI.md",
            "opencode": "OPENCODE.md",
            "cursor": ".cursor/rules/claude-code-rules.mdc",
            "aider": "CONVENTIONS.md",
            "windsurf": ".windsurfrules",
            "cline": ".clinerules",
            "continue": ".continue/rules/harnesssync.md",
            "zed": ".zed/system-prompt.md",
            "neovim": ".avante/system-prompt.md",
        }
        for target, rel in rules_files.items():
            if (self.project_dir / rel).is_file():
                found.append(target)
        return found

    def _score_target(self, target: str) -> HarnessComplexityReport | None:
        """Score a single target harness.

        Returns None if no synced files detected for this target.
        """
        metrics = self._collect_metrics(target)
        if metrics is None:
            return None

        report = HarnessComplexityReport(target=target)
        for name, value in metrics.items():
            dim = _score_dimension(name, value)
            report.dimensions.append(dim)

        # Generate suggestions for high-complexity dimensions
        for d in report.dimensions:
            if d.level == "high":
                if d.name == "rules_size_kb":
                    report.suggestions.append(
                        f"Rules file is {d.value:.0f}KB — use <!-- sync:exclude --> "
                        "to exclude verbose sections"
                    )
                elif d.name == "mcp_count":
                    report.suggestions.append(
                        f"{int(d.value)} MCP servers synced — consider using "
                        "--skip-sections mcp for lightweight targets"
                    )
                elif d.name == "skill_count":
                    report.suggestions.append(
                        f"{int(d.value)} skills synced — prune unused skills or "
                        "use per-target overrides to exclude some"
                    )

        return report

    def _collect_metrics(self, target: str) -> dict[str, float] | None:
        """Collect raw complexity metrics for a target from its output files."""
        rules_files = {
            "codex": ["AGENTS.md"],
            "gemini": ["GEMINI.md"],
            "opencode": ["OPENCODE.md"],
            "cursor": [".cursor/rules/claude-code-rules.mdc"],
            "aider": ["CONVENTIONS.md"],
            "windsurf": [".windsurfrules"],
            "cline": [".clinerules"],
            "continue": [".continue/rules/harnesssync.md"],
            "zed": [".zed/system-prompt.md"],
            "neovim": [".avante/system-prompt.md"],
        }
        skills_dirs = {
            "codex": ".agents/skills",
            "gemini": ".gemini/skills",
            "opencode": ".opencode/skills",
            "cursor": ".cursor/rules/skills",
            "cline": ".roo/rules/skills",
            "continue": ".continue/rules/skills",
            "zed": ".zed/prompts/skills",
            "neovim": ".avante/rules/skills",
        }
        mcp_files = {
            "codex": ".codex/config.toml",
            "gemini": ".gemini/settings.json",
            "opencode": ".opencode/settings.json",
            "cursor": ".cursor/mcp.json",
            "cline": ".roo/mcp.json",
            "continue": ".continue/config.json",
            "zed": ".zed/settings.json",
            "neovim": ".avante/mcp.json",
        }

        # Measure rules size
        total_rules_bytes = 0
        rule_sections = 0
        for rel in rules_files.get(target, []):
            p = self.project_dir / rel
            if p.is_file():
                try:
                    size = p.stat().st_size
                    total_rules_bytes += size
                    rule_sections += 1
                except OSError:
                    pass

        if rule_sections == 0:
            return None  # Target has no synced output

        # Count MCP servers
        mcp_count = 0
        mcp_rel = mcp_files.get(target)
        if mcp_rel:
            mcp_path = self.project_dir / mcp_rel
            if mcp_path.is_file():
                try:
                    import json as _json
                    data = _json.loads(mcp_path.read_text(encoding="utf-8"))
                    # Handle both mcpServers and context_servers
                    mcp_count = len(data.get("mcpServers", data.get("context_servers", {})))
                except (OSError, ValueError):
                    pass

        # Count skills
        skill_count = 0
        skills_rel = skills_dirs.get(target)
        if skills_rel:
            skills_path = self.project_dir / skills_rel
            if skills_path.is_dir():
                skill_count = sum(1 for _ in skills_path.iterdir())

        return {
            "rules_size_kb": total_rules_bytes / 1024.0,
            "rule_sections": float(rule_sections),
            "mcp_count": float(mcp_count),
            "skill_count": float(skill_count),
        }


# ──────────────────────────────────────────────────────────────────────────────
# CLAUDE.md Content Quality Analyzer (item 28)
# ──────────────────────────────────────────────────────────────────────────────

import re as _re


@dataclass
class ContentIssue:
    """A single content quality issue found in a rules file."""
    issue_type: str   # "duplicate" | "vague" | "contradiction" | "redundant"
    severity: str     # "warning" | "info"
    description: str
    line_numbers: list[int] = field(default_factory=list)


@dataclass
class ContentQualityReport:
    """Content quality analysis for a rules file."""
    file_path: str
    issues: list[ContentIssue] = field(default_factory=list)
    section_count: int = 0
    rule_count: int = 0

    @property
    def has_issues(self) -> bool:
        return bool(self.issues)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")

    def format(self) -> str:
        lines = [f"Content Quality: {self.file_path}"]
        lines.append(
            f"  {self.section_count} section(s), {self.rule_count} rule item(s)"
        )
        if not self.issues:
            lines.append("  ✓ No quality issues found.")
            return "\n".join(lines)

        for issue in self.issues:
            icon = "⚠" if issue.severity == "warning" else "·"
            loc = ""
            if issue.line_numbers:
                loc = f" (lines {', '.join(str(n) for n in issue.line_numbers)})"
            lines.append(f"  {icon} [{issue.issue_type}] {issue.description}{loc}")
        return "\n".join(lines)


_SECTION_HEADING_RE = _re.compile(r"^(#{1,3})\s+(.+)$", _re.MULTILINE)
_RULE_ITEM_RE = _re.compile(r"^[ \t]*[-*+]\s+.+$", _re.MULTILINE)

# Contradiction pairs: if both patterns appear near each other, flag as possible contradiction
_CONTRADICTION_PAIRS: list[tuple[str, str]] = [
    (r"\balways\b", r"\bnever\b"),
    (r"\bmust\b", r"\bshould not\b"),
    (r"\brequired\b", r"\boptional\b"),
    (r"\bdo not\b", r"\balways do\b"),
    (r"\bprefer\b", r"\bavoid\b"),
]

# Vague rule indicators: rules matching these are too imprecise to be actionable
_VAGUE_PATTERNS: list[str] = [
    r"^[-*+]\s+(?:be\s+)?(?:good|better|best|nice|clean|clear|proper|appropriate|careful)\b",
    r"^[-*+]\s+(?:try to|attempt to|consider)\b.{0,30}$",
    r"^[-*+]\s+.{1,20}$",  # Very short rules (< 20 chars after bullet)
]
_VAGUE_RES = [_re.compile(p, _re.IGNORECASE | _re.MULTILINE) for p in _VAGUE_PATTERNS]


def analyze_claude_md_content(content: str, file_path: str = "CLAUDE.md") -> ContentQualityReport:
    """Analyze CLAUDE.md content for quality issues.

    Detects:
    - Duplicate section headings (same heading appears twice)
    - Vague rules (too short or non-actionable)
    - Possible contradictions (e.g., 'always X' and 'never X' in same section)
    - Redundant bullet points (identical or near-identical rule text)

    Args:
        content: Raw CLAUDE.md text.
        file_path: Label used in the report (default: "CLAUDE.md").

    Returns:
        ContentQualityReport with found issues.
    """
    report = ContentQualityReport(file_path=file_path)

    # Count sections and rules
    headings = _SECTION_HEADING_RE.findall(content)
    report.section_count = len(headings)
    report.rule_count = len(_RULE_ITEM_RE.findall(content))

    lines = content.splitlines()

    # --- Duplicate headings ---
    heading_lines: dict[str, list[int]] = {}
    for i, line in enumerate(lines, start=1):
        m = _re.match(r"^#{1,3}\s+(.+)$", line)
        if m:
            heading_text = m.group(1).strip().lower()
            heading_lines.setdefault(heading_text, []).append(i)

    for heading_text, linenos in heading_lines.items():
        if len(linenos) > 1:
            report.issues.append(ContentIssue(
                issue_type="duplicate",
                severity="warning",
                description=f"Section heading appears {len(linenos)} times: '{heading_text}'",
                line_numbers=linenos,
            ))

    # --- Redundant/duplicate rule items ---
    rule_texts: dict[str, list[int]] = {}
    for i, line in enumerate(lines, start=1):
        m = _re.match(r"^[ \t]*[-*+]\s+(.+)$", line)
        if m:
            rule_text = m.group(1).strip().lower()
            # Normalise whitespace for fuzzy dedup
            rule_text = _re.sub(r"\s+", " ", rule_text)
            rule_texts.setdefault(rule_text, []).append(i)

    for rule_text, linenos in rule_texts.items():
        if len(linenos) > 1:
            preview = rule_text[:60] + ("..." if len(rule_text) > 60 else "")
            report.issues.append(ContentIssue(
                issue_type="redundant",
                severity="warning",
                description=f"Duplicate rule item: '{preview}'",
                line_numbers=linenos,
            ))

    # --- Vague rules ---
    for pattern_re in _VAGUE_RES:
        for m in pattern_re.finditer(content):
            lineno = content[: m.start()].count("\n") + 1
            rule_preview = m.group(0).strip()[:60]
            report.issues.append(ContentIssue(
                issue_type="vague",
                severity="info",
                description=f"Possibly vague/non-actionable rule: '{rule_preview}'",
                line_numbers=[lineno],
            ))

    # --- Contradiction detection ---
    for pattern_a, pattern_b in _CONTRADICTION_PAIRS:
        matches_a = [
            (content[: m.start()].count("\n") + 1, m.group(0))
            for m in _re.finditer(pattern_a, content, _re.IGNORECASE)
        ]
        matches_b = [
            (content[: m.start()].count("\n") + 1, m.group(0))
            for m in _re.finditer(pattern_b, content, _re.IGNORECASE)
        ]
        if matches_a and matches_b:
            # Only flag if they appear within 30 lines of each other (same section likely)
            for line_a, word_a in matches_a:
                for line_b, word_b in matches_b:
                    if abs(line_a - line_b) <= 30:
                        report.issues.append(ContentIssue(
                            issue_type="contradiction",
                            severity="warning",
                            description=(
                                f"Possible contradiction: '{word_a}' (line {line_a}) "
                                f"and '{word_b}' (line {line_b}) near each other"
                            ),
                            line_numbers=[line_a, line_b],
                        ))
                        break  # One report per contradiction pair is enough
                else:
                    continue
                break

    return report


class ClaudeMdQualityChecker:
    """Batch content quality checker for CLAUDE.md and related rule files.

    Args:
        project_dir: Project root to scan for CLAUDE.md and override files.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def check_all(self) -> list[ContentQualityReport]:
        """Check all CLAUDE.md style files in the project directory.

        Returns:
            List of ContentQualityReport, one per file found.
        """
        candidates = [
            self.project_dir / "CLAUDE.md",
            self.project_dir / "CLAUDE.local.md",
        ]
        # Include per-harness override files
        for target in ("codex", "gemini", "opencode", "cursor", "aider", "windsurf"):
            candidates.append(self.project_dir / f"CLAUDE.{target}.md")
            candidates.append(self.project_dir / ".claude" / f"CLAUDE.{target}.md")

        reports = []
        for path in candidates:
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            rel = path.relative_to(self.project_dir) if path.is_relative_to(self.project_dir) else path
            report = analyze_claude_md_content(content, file_path=str(rel))
            reports.append(report)

        return reports

    def format_summary(self, reports: list[ContentQualityReport] | None = None) -> str:
        """Format a combined quality summary for all checked files.

        Args:
            reports: Pre-computed reports (runs check_all() if None).

        Returns:
            Multi-line summary string.
        """
        if reports is None:
            reports = self.check_all()

        if not reports:
            return "No CLAUDE.md files found in project directory."

        lines = ["CLAUDE.md Content Quality Report", "=" * 40, ""]
        total_issues = 0
        total_warnings = 0

        for report in reports:
            lines.append(report.format())
            lines.append("")
            total_issues += len(report.issues)
            total_warnings += report.warning_count

        lines.append("-" * 40)
        lines.append(
            f"Total: {total_issues} issue(s) across {len(reports)} file(s) "
            f"({total_warnings} warning(s))"
        )
        if total_warnings > 0:
            lines.append(
                "\nTip: Warnings are rule quality issues that may reduce AI effectiveness.\n"
                "     Run /sync-lint --content for detailed suggestions."
            )
        return "\n".join(lines)
