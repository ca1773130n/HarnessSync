from __future__ import annotations

"""Config health score and recommendations.

Analyzes the current Claude Code config and scores it across dimensions:
- completeness: MCP servers configured? Rules present?
- portability: How much syncs cleanly vs gets dropped?
- security: Any secrets in rules or settings?
- size: CLAUDE.md too large for some targets?

Outputs actionable recommendations.
"""

import re
from pathlib import Path


# Target portability weights (fraction of sections supported natively)
# Based on sync_matrix.py CAPABILITY_MATRIX
_TARGET_NATIVE_FRACTIONS: dict[str, float] = {
    "codex": 0.70,
    "gemini": 0.90,
    "opencode": 0.90,
    "cursor": 0.75,
    "aider": 0.35,
    "windsurf": 0.70,
}

# Size thresholds (bytes)
RULES_SIZE_WARN = 50_000     # 50KB warning
RULES_SIZE_CRITICAL = 100_000  # 100KB critical

# Secret patterns (same as SecretDetector uses)
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE),           # OpenAI key
    re.compile(r"AKIA[A-Z0-9]{16}", re.IGNORECASE),              # AWS access key
    re.compile(r"ghp_[A-Za-z0-9]{36}", re.IGNORECASE),           # GitHub PAT
    re.compile(r"xoxb-[A-Za-z0-9-]{24,}", re.IGNORECASE),        # Slack bot token
    re.compile(r"(?i)(password|passwd|secret|api[_-]?key)\s*[:=]\s*\S{8,}"),
]


class HealthDimension:
    """Score and details for one health dimension."""

    def __init__(self, name: str, score: int, label: str, recommendations: list[str]):
        self.name = name
        self.score = score          # 0-100
        self.label = label          # e.g. "good" / "fair" / "poor"
        self.recommendations = recommendations


class ConfigHealthReport:
    """Overall config health report."""

    def __init__(self):
        self.dimensions: list[HealthDimension] = []

    def add(self, dimension: HealthDimension) -> None:
        self.dimensions.append(dimension)

    @property
    def overall_score(self) -> int:
        if not self.dimensions:
            return 0
        return int(sum(d.score for d in self.dimensions) / len(self.dimensions))

    @property
    def overall_label(self) -> str:
        score = self.overall_score
        if score >= 80:
            return "good"
        elif score >= 60:
            return "fair"
        elif score >= 40:
            return "poor"
        return "critical"


class ConfigHealthChecker:
    """Analyzes Claude Code config and produces a health report."""

    def check(self, source_data: dict, project_dir: Path | None = None) -> ConfigHealthReport:
        """Run all health checks.

        Args:
            source_data: Output of SourceReader.discover_all()
            project_dir: Project root (optional, for file size checks)

        Returns:
            ConfigHealthReport
        """
        report = ConfigHealthReport()
        report.add(self._check_completeness(source_data))
        report.add(self._check_portability(source_data))
        report.add(self._check_security(source_data))
        report.add(self._check_size(source_data, project_dir))
        return report

    def format_report(self, report: ConfigHealthReport) -> str:
        """Format health report as human-readable text."""
        lines: list[str] = []
        lines.append("Config Health Score")
        lines.append("=" * 50)
        lines.append(f"\nOverall: {report.overall_score}/100  [{report.overall_label.upper()}]")
        lines.append("")

        for dim in report.dimensions:
            bar = _score_bar(dim.score)
            lines.append(f"{dim.name:<15}  {bar}  {dim.score:>3}/100  [{dim.label}]")

        recommendations = [
            rec for dim in report.dimensions for rec in dim.recommendations
        ]
        if recommendations:
            lines.append("")
            lines.append("Recommendations:")
            for rec in recommendations:
                lines.append(f"  • {rec}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private checks
    # ------------------------------------------------------------------

    def _check_completeness(self, data: dict) -> HealthDimension:
        """Check if key config sections are populated."""
        score = 100
        recs: list[str] = []

        has_rules = bool(data.get("rules") or data.get("rules_files"))
        has_mcp = bool(data.get("mcp_servers"))
        has_skills = bool(data.get("skills"))

        if not has_rules:
            score -= 30
            recs.append("No CLAUDE.md rules found — add rules to guide AI behavior across harnesses")
        if not has_mcp:
            score -= 20
            recs.append("No MCP servers configured — MCP servers extend harness capabilities significantly")
        if not has_skills:
            score -= 10
            recs.append("No skills found — skills allow reusable workflows across harnesses")

        label = _label(score)
        return HealthDimension("completeness", score, label, recs)

    def _check_portability(self, data: dict) -> HealthDimension:
        """Check how much of the config syncs cleanly to all targets."""
        from src.adapters import AdapterRegistry
        targets = AdapterRegistry.list_targets()
        if not targets:
            return HealthDimension("portability", 100, "good", [])

        avg_fraction = sum(_TARGET_NATIVE_FRACTIONS.get(t, 0.5) for t in targets) / len(targets)
        score = int(avg_fraction * 100)
        recs: list[str] = []

        low_targets = [t for t in targets if _TARGET_NATIVE_FRACTIONS.get(t, 0.5) < 0.5]
        if low_targets:
            recs.append(
                f"Targets {', '.join(low_targets)} have limited compatibility — "
                f"run /sync-matrix for details on what gets dropped"
            )

        label = _label(score)
        return HealthDimension("portability", score, label, recs)

    def _check_security(self, data: dict) -> HealthDimension:
        """Scan rules and settings for potential secrets."""
        score = 100
        recs: list[str] = []

        # Scan rules content
        rules_texts: list[str] = []
        raw_rules = data.get("rules", "")
        if isinstance(raw_rules, str):
            rules_texts.append(raw_rules)
        elif isinstance(raw_rules, list):
            rules_texts.extend(r.get("content", "") for r in raw_rules if isinstance(r, dict))

        found_secrets = False
        for text in rules_texts:
            for pattern in _SECRET_PATTERNS:
                if pattern.search(text):
                    found_secrets = True
                    break

        if found_secrets:
            score -= 50
            recs.append(
                "Potential secrets detected in CLAUDE.md — run /sync-lint for details. "
                "Remove secrets before syncing to prevent credential leakage"
            )

        label = _label(score)
        return HealthDimension("security", score, label, recs)

    def _check_size(self, data: dict, project_dir: Path | None) -> HealthDimension:
        """Check for oversized config files that may cause issues."""
        score = 100
        recs: list[str] = []

        if project_dir:
            claude_md = project_dir / "CLAUDE.md"
            if claude_md.is_file():
                size = claude_md.stat().st_size
                if size > RULES_SIZE_CRITICAL:
                    score -= 40
                    recs.append(
                        f"CLAUDE.md is very large ({size // 1024}KB) — "
                        "consider splitting into focused rule files in .claude/rules/ "
                        "for better Codex/Aider compatibility"
                    )
                elif size > RULES_SIZE_WARN:
                    score -= 20
                    recs.append(
                        f"CLAUDE.md is large ({size // 1024}KB) — "
                        "consider splitting into smaller rule files"
                    )

        label = _label(score)
        return HealthDimension("size", score, label, recs)


def _label(score: int) -> str:
    if score >= 80:
        return "good"
    elif score >= 60:
        return "fair"
    elif score >= 40:
        return "poor"
    return "critical"


def _score_bar(score: int, width: int = 20) -> str:
    """Generate an ASCII progress bar for a score 0-100."""
    filled = int(score / 100 * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"
