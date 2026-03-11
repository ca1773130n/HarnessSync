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
