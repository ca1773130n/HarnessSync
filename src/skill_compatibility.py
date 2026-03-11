from __future__ import annotations

"""Skill compatibility checker for cross-harness compatibility analysis.

Analyzes each Claude Code skill and flags constructs that won't work in
target harnesses: Claude-specific tool references, MCP calls that require
unavailable servers, hooks that reference Claude Code internals.

Shows a compatibility score per skill per harness.
"""

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


class SkillCompatibilityChecker:
    """Analyzes Claude Code skills for cross-harness compatibility."""

    ALL_PATTERNS = CLAUDE_SPECIFIC_PATTERNS + HOOK_PATTERNS + MCP_PATTERNS

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
