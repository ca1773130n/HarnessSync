from __future__ import annotations

"""Skill compatibility checker for cross-harness compatibility analysis.

Analyzes each Claude Code skill and flags constructs that won't work in
target harnesses: Claude-specific tool references, MCP calls that require
unavailable servers, hooks that reference Claude Code internals.

Shows a compatibility score per skill per harness.
"""

import dataclasses
import re
from pathlib import Path


# Patterns that are Claude Code-specific and may not work in other harnesses
CLAUDE_SPECIFIC_PATTERNS = [
    # Claude Code tool names
    (r"\bBash\b", "Claude Code 'Bash' tool reference"),
    (r"\bRead\b(?=\s+tool|\s+the\s+file)", "Claude Code 'Read' tool reference"),
    (r"\bWrite\b(?=\s+tool|\s+the\s+file)", "Claude Code 'Write' tool reference"),
    (r"\bEdit\b(?=\s+tool)", "Claude Code 'Edit' tool reference"),
    (r"\bGlob\b(?=\s+tool|\s+pattern)", "Claude Code 'Glob' tool reference"),
    (r"\bGrep\b(?=\s+tool)", "Claude Code 'Grep' tool reference"),
    (r"\bAgent\b(?=\s+tool)", "Claude Code 'Agent' tool reference"),
    (r"\bTodoWrite\b", "Claude Code 'TodoWrite' tool reference"),
    (r"\bWebFetch\b", "Claude Code 'WebFetch' tool reference"),
    (r"\bWebSearch\b", "Claude Code 'WebSearch' tool reference"),
    # Hook/event references
    (r"PostToolUse|PreToolUse|UserPromptSubmit|SessionStart|SessionEnd",
     "Claude Code hook event reference"),
    # Plugin-specific patterns
    (r"\$CLAUDE_PLUGIN_ROOT", "Claude Code plugin path variable"),
    (r"CLAUDE\.md", "Claude Code config file reference"),
    # MCP-specific tool calls
    (r"mcp__\w+__\w+", "MCP tool call reference"),
]

# Hook patterns specific to Claude Code
HOOK_PATTERNS = [
    (r"hooks\.json", "hooks.json configuration reference"),
    (r"\.claude/hooks", "Claude Code hooks directory reference"),
]

# Patterns that indicate MCP dependency
MCP_PATTERNS = [
    (r"mcp__(\w+)__", "MCP server dependency"),
]

# Targets and their known limitations
TARGET_LIMITATIONS: dict[str, list[str]] = {
    "codex": [
        "MCP tool calls not supported",
        "Hook events not available",
        "Claude Code-specific tools not available",
    ],
    "gemini": [
        "Hook events not available",
        "Claude Code-specific tools not available",
        "Some MCP servers may not be configured",
    ],
    "opencode": [
        "Hook events not available",
        "Claude Code-specific tools not available",
    ],
    "cursor": [
        "Skill format converted to .mdc",
        "Hook events not available",
        "MCP tool calls require separate Cursor MCP setup",
        "Claude Code-specific tools not available",
    ],
    "aider": [
        "Skills mapped to context files (no execution)",
        "Hook events not available",
        "MCP servers not supported",
        "Commands not available",
    ],
    "windsurf": [
        "Skills mapped to memory files",
        "Hook events not available",
        "MCP tool calls require separate Windsurf MCP setup",
        "Claude Code-specific tools not available",
    ],
}


class SkillCompatibilityIssue:
    """A single compatibility issue found in a skill."""

    def __init__(self, pattern_desc: str, line: int, line_text: str):
        self.pattern_desc = pattern_desc
        self.line = line
        self.line_text = line_text.strip()


class SkillCompatibilityReport:
    """Compatibility report for a single skill across all targets."""

    def __init__(self, skill_name: str):
        self.skill_name = skill_name
        self.issues: list[SkillCompatibilityIssue] = []
        self.target_scores: dict[str, int] = {}  # target -> score 0-100

    def add_issue(self, issue: SkillCompatibilityIssue) -> None:
        self.issues.append(issue)

    def compute_scores(self, targets: list[str]) -> None:
        """Compute compatibility score per target (0=broken, 100=perfect)."""
        # Deduct points per issue (max deduction per issue: 10)
        base = 100
        deduction_per_issue = min(10, 100 // max(len(self.issues), 1)) if self.issues else 0

        for target in targets:
            score = base - len(self.issues) * deduction_per_issue
            # Additional deductions for target-specific limitations
            limitations = TARGET_LIMITATIONS.get(target, [])
            if self.issues and limitations:
                # Heavy penalty for aider (no execution) if skill has code-execution patterns
                if target == "aider" and self.issues:
                    score -= 20
            self.target_scores[target] = max(0, min(100, score))


@dataclasses.dataclass
class RulePortabilityIssue:
    """A single portability issue found in a CLAUDE.md rule."""

    rule_index: int        # 1-based index into the rules list
    rule_preview: str      # first 80 chars of the rule text
    pattern_desc: str      # human-readable description of the issue


@dataclasses.dataclass
class ProjectPortabilityScore:
    """Aggregate portability score for the whole project (rules + skills).

    Scores are in the range 0-100 per target:
    - 90-100: Excellent — most content will transfer faithfully
    - 70-89:  Good — minor degradation expected
    - 50-69:  Fair — noticeable capability loss on some targets
    - 0-49:   Poor — significant config investment won't carry over

    The project score is a weighted average: rules carry 40% of the weight
    (they affect all harnesses), skills carry 60%.
    """

    target_scores: dict[str, int]        # target -> 0-100
    rule_issues: list[RulePortabilityIssue]
    skill_reports: list[SkillCompatibilityReport]
    total_rules: int
    total_skills: int

    @property
    def overall_score(self) -> int:
        """Return the mean score across all configured targets."""
        if not self.target_scores:
            return 100
        return round(sum(self.target_scores.values()) / len(self.target_scores))

    def format_summary(self) -> str:
        """Return a concise summary of the project portability score."""
        lines: list[str] = []
        lines.append("Harness Portability Score")
        lines.append("=" * 40)
        lines.append(f"  Overall: {self.overall_score}/100")
        lines.append("")
        for target, score in sorted(self.target_scores.items(), key=lambda x: -x[1]):
            bar = "#" * (score // 5) + "." * (20 - score // 5)
            lines.append(f"  {target:<12} {score:>3}/100  [{bar}]")
        lines.append("")
        lines.append(f"  Rules checked:  {self.total_rules}")
        lines.append(f"  Rule issues:    {len(self.rule_issues)}")
        lines.append(f"  Skills checked: {self.total_skills}")
        skill_issues = sum(len(r.issues) for r in self.skill_reports)
        lines.append(f"  Skill issues:   {skill_issues}")
        if self.rule_issues:
            lines.append("")
            lines.append("  Top rule portability issues:")
            for issue in self.rule_issues[:5]:
                lines.append(f"    Rule {issue.rule_index}: {issue.pattern_desc}")
                lines.append(f"      > {issue.rule_preview}")
        return "\n".join(lines)


class SkillCompatibilityChecker:
    """Analyzes Claude Code skills for cross-harness compatibility."""

    ALL_PATTERNS = CLAUDE_SPECIFIC_PATTERNS + HOOK_PATTERNS + MCP_PATTERNS

    # Patterns that reduce portability when found in raw rule text
    RULE_PORTABILITY_PATTERNS = [
        (r"mcp__\w+__\w+", "MCP tool call — not available outside Claude Code"),
        (r"\$CLAUDE_PLUGIN_ROOT", "Claude plugin path — CC-specific"),
        (r"PostToolUse|PreToolUse|UserPromptSubmit|SessionStart|SessionEnd",
         "Hook event name — CC-specific lifecycle"),
        (r"\.claude/hooks", "Claude hooks directory — CC-specific path"),
        (r"hooks\.json", "hooks.json reference — CC-specific"),
        (r"\bTodoWrite\b", "TodoWrite tool — CC-specific"),
        (r"\bWebFetch\b|\bWebSearch\b", "CC-specific web tool reference"),
        (r"CLAUDE\.md", "CLAUDE.md filename reference — target-specific"),
    ]

    def check_rules_portability(
        self,
        rules: list[str | dict],
        targets: list[str] | None = None,
    ) -> list[RulePortabilityIssue]:
        """Scan a list of rules from CLAUDE.md for portability issues.

        Args:
            rules: List of rule strings, or dicts with a "content" key.
            targets: Target harness names (defaults to all registered targets).

        Returns:
            List of RulePortabilityIssue for rules that reference CC-specific features.
        """
        import re as _re

        issues: list[RulePortabilityIssue] = []
        for idx, rule in enumerate(rules, 1):
            text = rule.get("content", "") if isinstance(rule, dict) else str(rule)
            for pattern, desc in self.RULE_PORTABILITY_PATTERNS:
                if _re.search(pattern, text, _re.IGNORECASE):
                    preview = text.strip()[:80].replace("\n", " ")
                    issues.append(RulePortabilityIssue(idx, preview, desc))
                    break  # one issue per rule
        return issues

    def compute_project_score(
        self,
        rules: list[str | dict],
        skills: dict[str, Path] | None = None,
    ) -> ProjectPortabilityScore:
        """Compute a holistic portability score for the entire project.

        Combines rule portability (40% weight) with skill portability (60%)
        into a per-target score and an overall project score.

        Args:
            rules: List of rule strings or dicts from SourceReader.
            skills: Optional dict mapping skill name → skill path.

        Returns:
            ProjectPortabilityScore with per-target scores and issue details.
        """
        from src.adapters import AdapterRegistry
        targets = AdapterRegistry.list_targets()

        skill_reports: list[SkillCompatibilityReport] = []
        if skills:
            skill_reports = self.check_all_skills(skills)

        rule_issues = self.check_rules_portability(rules, targets)

        # --- Per-target score ---
        # Rules: deduct 5 points per CC-specific issue (capped at 40 deduction)
        # Skills: use average skill score per target
        target_scores: dict[str, int] = {}
        for target in targets:
            rule_deduction = min(40, len(rule_issues) * 5)
            rule_score = 100 - rule_deduction

            if skill_reports:
                skill_target_scores = [
                    r.target_scores.get(target, 100) for r in skill_reports
                ]
                skill_score = round(sum(skill_target_scores) / len(skill_target_scores))
            else:
                skill_score = 100

            # Weighted average: rules 40%, skills 60%
            combined = round(0.4 * rule_score + 0.6 * skill_score)
            target_scores[target] = max(0, min(100, combined))

        return ProjectPortabilityScore(
            target_scores=target_scores,
            rule_issues=rule_issues,
            skill_reports=skill_reports,
            total_rules=len(rules),
            total_skills=len(skills) if skills else 0,
        )

    def check_skill(self, skill_name: str, skill_path: Path) -> SkillCompatibilityReport:
        """Check a single skill for compatibility issues.

        Args:
            skill_name: Name of the skill
            skill_path: Path to skill directory or SKILL.md file

        Returns:
            SkillCompatibilityReport
        """
        report = SkillCompatibilityReport(skill_name)

        # Find SKILL.md
        if skill_path.is_dir():
            skill_md = skill_path / "SKILL.md"
        else:
            skill_md = skill_path

        if not skill_md.is_file():
            return report

        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError:
            return report

        lines = content.splitlines()
        for line_no, line in enumerate(lines, 1):
            for pattern, desc in self.ALL_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    report.add_issue(SkillCompatibilityIssue(desc, line_no, line))
                    break  # One issue per line

        from src.adapters import AdapterRegistry
        targets = AdapterRegistry.list_targets()
        report.compute_scores(targets)

        return report

    def check_all_skills(self, skills: dict[str, Path]) -> list[SkillCompatibilityReport]:
        """Check all skills for compatibility.

        Args:
            skills: Dict mapping skill name to skill directory path

        Returns:
            List of SkillCompatibilityReport
        """
        reports: list[SkillCompatibilityReport] = []
        for name, path in skills.items():
            report = self.check_skill(name, path)
            reports.append(report)
        return reports

    def format_report(self, reports: list[SkillCompatibilityReport]) -> str:
        """Format compatibility reports as human-readable text.

        Args:
            reports: List of reports from check_all_skills()

        Returns:
            Formatted report string
        """
        if not reports:
            return "No skills found to check."

        from src.adapters import AdapterRegistry
        targets = AdapterRegistry.list_targets()

        lines: list[str] = []
        lines.append("Skill Compatibility Report")
        lines.append("=" * 60)
        lines.append("")

        # Summary table header
        header = f"{'Skill':<25}"
        for t in targets:
            header += f"  {t[:8]:<8}"
        header += "  Issues"
        lines.append(header)
        lines.append("-" * len(header))

        for report in sorted(reports, key=lambda r: r.skill_name):
            row = f"{report.skill_name[:24]:<25}"
            for t in targets:
                score = report.target_scores.get(t, 100)
                if score >= 80:
                    indicator = f"{score}%"
                elif score >= 50:
                    indicator = f"~{score}%"
                else:
                    indicator = f"✗{score}%"
                row += f"  {indicator:<8}"
            row += f"  {len(report.issues)}"
            lines.append(row)

        # Detail section for skills with issues
        skills_with_issues = [r for r in reports if r.issues]
        if skills_with_issues:
            lines.append("")
            lines.append("Issues Found:")
            lines.append("-" * 60)
            for report in skills_with_issues:
                lines.append(f"\n{report.skill_name}:")
                for issue in report.issues[:10]:
                    lines.append(f"  line {issue.line}: {issue.pattern_desc}")
                    lines.append(f"    > {issue.line_text[:80]}")
                if len(report.issues) > 10:
                    lines.append(f"  ... and {len(report.issues) - 10} more issues")

        return "\n".join(lines)
