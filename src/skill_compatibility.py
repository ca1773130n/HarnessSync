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


# ---------------------------------------------------------------------------
# Feature support maps: which features are natively supported per harness
# ---------------------------------------------------------------------------

# Fraction of the feature that reaches the target (0.0 = none, 1.0 = full)
_FEATURE_COVERAGE: dict[str, dict[str, float]] = {
    "codex": {
        "rules": 1.0,
        "skills": 0.5,   # folded into rules as plain text — intent preserved but no execution
        "mcp": 0.0,       # MCP not supported by Codex CLI
        "commands": 0.4,  # converted to AGENTS.md instruction blocks
        "agents": 0.5,
        "settings": 0.2,  # only allow/deny lists carry over
    },
    "gemini": {
        "rules": 1.0,
        "skills": 0.6,   # converted to system instructions
        "mcp": 0.8,       # stdio MCP supported; SSE may need workarounds
        "commands": 0.3,
        "agents": 0.4,
        "settings": 0.3,
    },
    "opencode": {
        "rules": 1.0,
        "skills": 0.7,
        "mcp": 0.9,
        "commands": 0.3,
        "agents": 0.5,
        "settings": 0.3,
    },
    "cursor": {
        "rules": 1.0,
        "skills": 0.8,   # converted to .mdc rule files
        "mcp": 0.9,
        "commands": 0.6,  # .mdc blocks with slash-command triggers
        "agents": 0.6,
        "settings": 0.4,
    },
    "aider": {
        "rules": 1.0,
        "skills": 0.0,   # no skill concept in Aider
        "mcp": 0.0,       # no MCP support
        "commands": 0.0,  # no custom commands
        "agents": 0.0,
        "settings": 0.2,
    },
    "windsurf": {
        "rules": 1.0,
        "skills": 0.5,   # mapped to memory files
        "mcp": 0.8,
        "commands": 0.2,
        "agents": 0.4,
        "settings": 0.3,
    },
    "cline": {
        "rules": 0.9,
        "skills": 0.5,
        "mcp": 0.9,
        "commands": 0.3,
        "agents": 0.4,
        "settings": 0.3,
    },
    "vscode": {
        "rules": 0.8,
        "skills": 0.4,
        "mcp": 0.7,
        "commands": 0.3,
        "agents": 0.4,
        "settings": 0.3,
    },
    "continue": {
        "rules": 0.9,
        "skills": 0.5,
        "mcp": 0.8,
        "commands": 0.3,
        "agents": 0.4,
        "settings": 0.3,
    },
    "neovim": {
        "rules": 0.7,
        "skills": 0.3,
        "mcp": 0.6,
        "commands": 0.2,
        "agents": 0.2,
        "settings": 0.2,
    },
    "zed": {
        "rules": 0.8,
        "skills": 0.4,
        "mcp": 0.7,
        "commands": 0.3,
        "agents": 0.3,
        "settings": 0.3,
    },
}

# Human-readable explanation for each unsupported feature
_COVERAGE_EXPLANATIONS: dict[str, dict[str, str]] = {
    "codex": {
        "mcp": "MCP servers not supported — configure separately",
        "commands": "commands become plain AGENTS.md instruction notes",
        "settings": "only allow/deny permissions carry over",
    },
    "gemini": {
        "commands": "commands converted to GEMINI.md instruction blocks",
        "agents": "agents approximated as GEMINI.md role definitions",
        "settings": "only allow/deny permissions carry over",
    },
    "aider": {
        "skills": "skills have no Aider equivalent — add to CONVENTIONS.md manually",
        "mcp": "MCP not supported by Aider",
        "commands": "Aider has no custom command concept",
        "agents": "Aider has no agent concept",
    },
}


@dataclasses.dataclass
class HarnessFeatureCoverage:
    """Per-feature coverage for a single target harness."""

    target: str
    rules_pct: float       # 0.0–1.0
    skills_pct: float
    mcp_pct: float
    commands_pct: float
    agents_pct: float
    settings_pct: float
    source_has_skills: bool
    source_has_mcp: bool
    source_has_commands: bool
    source_has_agents: bool

    @property
    def overall_pct(self) -> float:
        """Weighted overall coverage percentage.

        Rules and MCP carry the most weight since they have the highest day-to-day impact.
        """
        weights = {
            "rules": 0.30,
            "skills": 0.20 if self.source_has_skills else 0.0,
            "mcp": 0.25 if self.source_has_mcp else 0.0,
            "commands": 0.15 if self.source_has_commands else 0.0,
            "agents": 0.10 if self.source_has_agents else 0.0,
        }
        total_weight = sum(weights.values()) or 1.0
        weighted = (
            self.rules_pct * weights["rules"]
            + self.skills_pct * weights["skills"]
            + self.mcp_pct * weights["mcp"]
            + self.commands_pct * weights["commands"]
            + self.agents_pct * weights["agents"]
        )
        return round(weighted / total_weight, 2)

    def format(self) -> str:
        """Single-line summary: 'Aider: 42% — skills not supported, MCP not supported'."""
        pct = round(self.overall_pct * 100)
        limitations = _COVERAGE_EXPLANATIONS.get(self.target, {})

        unsupported: list[str] = []
        if self.source_has_skills and self.skills_pct < 0.3:
            unsupported.append(limitations.get("skills", "skills not supported"))
        elif self.source_has_skills and self.skills_pct < 0.7:
            unsupported.append("skills partially supported")
        if self.source_has_mcp and self.mcp_pct < 0.3:
            unsupported.append(limitations.get("mcp", "MCP not supported"))
        if self.source_has_commands and self.commands_pct < 0.3:
            unsupported.append(limitations.get("commands", "commands not supported"))
        if self.source_has_agents and self.agents_pct < 0.3:
            unsupported.append(limitations.get("agents", "agents not supported"))

        if unsupported:
            return f"{self.target}: {pct}% — {', '.join(unsupported)}"
        return f"{self.target}: {pct}%"


@dataclasses.dataclass
class HarnessCoverageReport:
    """Coverage breakdown across all configured target harnesses."""

    coverages: list[HarnessFeatureCoverage]

    def format(self) -> str:
        """Render a multi-line table showing per-harness coverage."""
        if not self.coverages:
            return "No targets configured."
        lines = [
            "Harness Coverage Score",
            "=" * 55,
            "  How much of your Claude Code config reaches each target.",
            "",
        ]
        for cov in sorted(self.coverages, key=lambda c: -c.overall_pct):
            lines.append(f"  {cov.format()}")
            # Show per-feature breakdown
            features = [
                ("rules", cov.rules_pct),
                ("skills", cov.skills_pct, cov.source_has_skills),
                ("MCP", cov.mcp_pct, cov.source_has_mcp),
                ("commands", cov.commands_pct, cov.source_has_commands),
                ("agents", cov.agents_pct, cov.source_has_agents),
            ]
            for feat in features:
                name = feat[0]
                pct_val = feat[1]
                has_it = feat[2] if len(feat) > 2 else True
                if not has_it:
                    continue  # source has none — skip
                bar = round(pct_val * 10)
                bar_str = "█" * bar + "░" * (10 - bar)
                lines.append(f"    {name:<10} {bar_str}  {round(pct_val * 100):>3}%")
            lines.append("")
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

    def compute_harness_coverage(
        self,
        source_data: dict | None = None,
        targets: list[str] | None = None,
    ) -> HarnessCoverageReport:
        """Compute per-harness coverage scores from SourceReader output.

        Shows what fraction of each config section (rules, skills, MCP servers,
        commands, agents) is actually expressible in each target harness.
        Unlike the portability score (which penalises CC-specific constructs),
        coverage score reflects the harness's *structural* capability.

        Args:
            source_data: Dict from SourceReader.read() with keys: rules, skills,
                         mcp_servers, commands, agents. Pass None to use defaults.
            targets: Target harness names. Defaults to all registered targets.

        Returns:
            HarnessCoverageReport with a HarnessFeatureCoverage per target.
        """
        from src.adapters import AdapterRegistry
        resolved_targets = targets or AdapterRegistry.list_targets()

        sd = source_data or {}
        has_skills = bool(sd.get("skills"))
        has_mcp = bool(sd.get("mcp_servers"))
        has_commands = bool(sd.get("commands"))
        has_agents = bool(sd.get("agents"))

        coverages: list[HarnessFeatureCoverage] = []
        for target in resolved_targets:
            fc = _FEATURE_COVERAGE.get(target, {})
            coverages.append(HarnessFeatureCoverage(
                target=target,
                rules_pct=fc.get("rules", 0.8),
                skills_pct=fc.get("skills", 0.5),
                mcp_pct=fc.get("mcp", 0.5),
                commands_pct=fc.get("commands", 0.3),
                agents_pct=fc.get("agents", 0.4),
                settings_pct=fc.get("settings", 0.3),
                source_has_skills=has_skills,
                source_has_mcp=has_mcp,
                source_has_commands=has_commands,
                source_has_agents=has_agents,
            ))
        return HarnessCoverageReport(coverages=coverages)

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


# ---------------------------------------------------------------------------
# Skill Coverage Advisor
# ---------------------------------------------------------------------------

#: Fallback suggestions keyed by pattern description fragment.
_FALLBACK_SUGGESTIONS: list[tuple[str, str]] = [
    (
        "MCP server dependency",
        "Replace the MCP tool call with a plain description of the behavior. "
        "Example: instead of calling `mcp__context7__query-docs`, describe the "
        "lookup step in prose so non-CC harnesses can follow the intent manually.",
    ),
    (
        "Bash' tool",
        "Replace references to the Bash tool with generic shell-command instructions "
        "('Run the following shell command:') so Codex/Gemini users know what to execute.",
    ),
    (
        "Read' tool",
        "Replace 'Read tool' references with 'open the file' or 'view the file contents' "
        "to work across all harnesses.",
    ),
    (
        "Write' tool",
        "Replace 'Write tool' references with 'create the file' or 'write the file contents' "
        "so the instruction is harness-agnostic.",
    ),
    (
        "Edit' tool",
        "Replace 'Edit tool' references with 'modify the file at line N' or an equivalent "
        "instruction that any harness can interpret.",
    ),
    (
        "Glob' tool",
        "Replace 'Glob tool' references with 'find files matching the pattern' to remain "
        "portable across harnesses.",
    ),
    (
        "Grep' tool",
        "Replace 'Grep tool' references with 'search for the pattern in files' for "
        "cross-harness compatibility.",
    ),
    (
        "Agent' tool",
        "Agent tool is CC-specific. Add a fallback description: 'If Agent tool is unavailable, "
        "complete this step manually in sequence.'",
    ),
    (
        "TodoWrite",
        "TodoWrite is CC-specific. Add a note: 'Track progress in your task manager of choice "
        "if this harness lacks a todo tool.'",
    ),
    (
        "hooks.json",
        "hooks.json references are CC-specific. Describe the trigger behavior in prose so "
        "users of other harnesses understand the intent without the hook mechanism.",
    ),
    (
        "hooks directory",
        "The .claude/hooks path is CC-specific. Add a note explaining what the hook does "
        "so users of other harnesses can replicate the behavior manually.",
    ),
    (
        "Hook event name",
        "Hook lifecycle events (PreToolUse, PostToolUse, etc.) are CC-specific. "
        "Describe the equivalent trigger in plain language as a fallback.",
    ),
    (
        "plugin path",
        "$CLAUDE_PLUGIN_ROOT is a CC-only environment variable. Replace with a relative "
        "path or add a note to set the equivalent variable in other harnesses.",
    ),
    (
        "web tool",
        "WebFetch/WebSearch tools are CC-specific. Add an alternative: 'If this tool is "
        "unavailable, fetch the URL using curl or a browser and paste the content.'",
    ),
]


def _find_fallback(pattern_desc: str) -> str | None:
    """Return the best matching fallback suggestion for a pattern description."""
    desc_lower = pattern_desc.lower()
    for fragment, suggestion in _FALLBACK_SUGGESTIONS:
        if fragment.lower() in desc_lower:
            return suggestion
    return None


@dataclasses.dataclass
class SkillAdvisory:
    """Advisory for a single skill with actionable fallback suggestions."""

    skill_name: str
    issues: list[SkillCompatibilityIssue]
    suggestions: list[str] = dataclasses.field(default_factory=list)

    @property
    def has_suggestions(self) -> bool:
        return bool(self.suggestions)

    def format(self) -> str:
        """Render this advisory as human-readable text."""
        if not self.issues:
            return f"  {self.skill_name}: no portability issues found."
        lines = [f"  {self.skill_name} ({len(self.issues)} issue(s)):"]
        seen_descs: set[str] = set()
        for issue in self.issues:
            desc = issue.pattern_desc
            if desc in seen_descs:
                continue
            seen_descs.add(desc)
            lines.append(f"    · {desc}")
            suggestion = _find_fallback(desc)
            if suggestion:
                lines.append(f"      → Fallback: {suggestion}")
        return "\n".join(lines)


class SkillCoverageAdvisor:
    """Analyzes skills and flags Claude Code-specific APIs that won't translate.

    For each issue detected, surfaces a concrete fallback suggestion so authors
    can either add harness-agnostic alternatives or accept the portability gap
    with full awareness.

    Usage::

        advisor = SkillCoverageAdvisor()
        advisories = advisor.advise_all(skills)
        print(advisor.format_advisory(advisories))
    """

    def __init__(self) -> None:
        self._checker = SkillCompatibilityChecker()

    def advise(self, skill_name: str, skill_path: Path) -> SkillAdvisory:
        """Analyze one skill and return an advisory with fallback suggestions.

        Args:
            skill_name: Human-readable skill name.
            skill_path: Path to the skill directory or file.

        Returns:
            SkillAdvisory with issues and suggestions.
        """
        report = self._checker.check_skill(skill_name, skill_path)
        suggestions: list[str] = []
        seen_descs: set[str] = set()
        for issue in report.issues:
            desc = issue.pattern_desc
            if desc in seen_descs:
                continue
            seen_descs.add(desc)
            fallback = _find_fallback(desc)
            if fallback and fallback not in suggestions:
                suggestions.append(f"[{desc}] {fallback}")
        return SkillAdvisory(
            skill_name=skill_name,
            issues=report.issues,
            suggestions=suggestions,
        )

    def advise_all(self, skills: dict[str, Path]) -> list[SkillAdvisory]:
        """Analyze all skills and return advisories sorted by issue count.

        Args:
            skills: Dict mapping skill name to skill directory path.

        Returns:
            List of SkillAdvisory, most-problematic first.
        """
        advisories = [self.advise(name, path) for name, path in skills.items()]
        return sorted(advisories, key=lambda a: -len(a.issues))

    def format_advisory(self, advisories: list[SkillAdvisory]) -> str:
        """Format all advisories as a human-readable report.

        Args:
            advisories: List from advise_all().

        Returns:
            Multi-line advisory string.
        """
        if not advisories:
            return "No skills found to analyze."

        with_issues = [a for a in advisories if a.issues]
        clean = [a for a in advisories if not a.issues]

        lines = [
            "Skill Coverage Advisor",
            "=" * 60,
            f"  Analyzed {len(advisories)} skill(s): "
            f"{len(with_issues)} need attention, {len(clean)} fully portable.",
            "",
        ]

        if with_issues:
            lines.append("Skills with portability gaps:")
            lines.append("-" * 60)
            for advisory in with_issues:
                lines.append(advisory.format())
                lines.append("")

        if clean:
            lines.append(f"Fully portable ({len(clean)}):")
            for a in clean:
                lines.append(f"  \u2713 {a.skill_name}")
            lines.append("")

        lines.append(
            "Tip: Add a <!-- harness:skip=codex --> comment around CC-specific "
            "sections to keep portability explicit in your skill files."
        )
        return "\n".join(lines)


def generate_what_youre_missing_report(
    target_harness: str,
    skills: "dict[str, Path]",
    rules_content: str = "",
    mcp_servers: "dict | None" = None,
) -> str:
    """Produce a prioritized 'what you're missing in <harness>' report (item 3).

    Scans CLAUDE.md rules, skills, and MCP server config for capabilities
    that the target harness cannot replicate — then produces a concise,
    prioritized list with workarounds where they exist.

    Users don't know what they're losing until they need it. This report
    makes the gap visible upfront so users can plan or accept the trade-off.

    Args:
        target_harness: Target harness name (e.g. "cursor", "codex", "aider").
        skills: Dict mapping skill_name → skill directory Path.
        rules_content: Content of CLAUDE.md rules section (optional).
        mcp_servers: Dict of MCP server configs from .mcp.json (optional).

    Returns:
        Multi-line string with prioritized gap list and suggested workarounds.
    """
    # ── Known capabilities that only Claude Code supports ────────────────────
    _CC_ONLY_CAPABILITIES: list[dict] = [
        {
            "feature": "MCP tool calls (mcp__* tools)",
            "description": "Claude Code can call MCP servers directly as tools.",
            "affected_harnesses": {"cursor", "aider", "windsurf", "cline", "continue", "vscode", "neovim"},
            "workaround": "Describe MCP tool behavior in rules as manual steps instead.",
            "severity": "high",
        },
        {
            "feature": "Slash command skills (/commit, /review-pr, etc.)",
            "description": "Claude Code skills are invocable slash commands with full tool access.",
            "affected_harnesses": {"aider", "windsurf", "continue", "neovim"},
            "workaround": "Convert skills to prompt templates; run manually from CLI.",
            "severity": "high",
        },
        {
            "feature": "PostToolUse / PreToolUse hooks",
            "description": "Claude Code hooks trigger shell commands around tool calls.",
            "affected_harnesses": {"cursor", "aider", "codex", "gemini", "opencode", "windsurf", "cline", "continue", "vscode", "neovim"},
            "workaround": "Add equivalent actions to CI or a pre-commit hook instead.",
            "severity": "medium",
        },
        {
            "feature": "Tool permission allow/deny lists",
            "description": "Claude Code's settings.json controls which tools the model can call.",
            "affected_harnesses": {"aider", "continue", "neovim", "cline"},
            "workaround": "Enforce restrictions via rules text ('never call bash').",
            "severity": "medium",
        },
        {
            "feature": "Persistent memory (memory/ directory)",
            "description": "Claude Code agents can read/write persistent markdown memory files.",
            "affected_harnesses": {"cursor", "codex", "gemini", "aider", "windsurf", "cline", "continue", "vscode", "neovim", "opencode"},
            "workaround": "Attach relevant context manually or via project README.",
            "severity": "low",
        },
        {
            "feature": "Multi-agent orchestration (Agent tool)",
            "description": "Claude Code can spawn and coordinate subagents for parallel tasks.",
            "affected_harnesses": {"cursor", "aider", "windsurf", "cline", "continue", "vscode", "neovim", "opencode", "codex", "gemini"},
            "workaround": "Structure prompts sequentially; use CI pipelines for parallelism.",
            "severity": "low",
        },
    ]

    target_lc = target_harness.lower()
    gaps: list[dict] = []

    for cap in _CC_ONLY_CAPABILITIES:
        if target_lc in cap["affected_harnesses"]:
            gaps.append(cap)

    # Check skills for harness-specific issues
    checker = SkillCompatibilityChecker()
    skill_issues_by_harness: dict[str, list[str]] = {}
    for skill_name, skill_path in (skills or {}).items():
        report = checker.check_skill(skill_name, skill_path)
        harness_score = report.harness_scores.get(target_lc, 100)
        if harness_score < 80:
            skill_issues_by_harness.setdefault(target_lc, []).append(
                f"Skill '{skill_name}' compatibility: {harness_score}%"
            )

    # Check MCP servers — most harnesses can't use them at runtime
    mcp_gaps: list[str] = []
    if mcp_servers:
        _mcp_unsupported = {"aider", "neovim", "cline", "continue"}
        if target_lc in _mcp_unsupported:
            mcp_gaps = [
                f"MCP server '{name}' will not be callable at runtime in {target_harness}."
                for name in list(mcp_servers.keys())[:5]
            ]

    # Build the report
    lines = [
        f"Feature Gap Report — What You're Missing in {target_harness.capitalize()}",
        "=" * 65,
        "",
    ]

    if not gaps and not mcp_gaps and not skill_issues_by_harness:
        lines.append(f"  No significant capability gaps detected for {target_harness}.")
        lines.append("  This harness supports most Claude Code features via synced config.")
        return "\n".join(lines)

    # Sort by severity: high → medium → low
    severity_rank = {"high": 0, "medium": 1, "low": 2}
    gaps_sorted = sorted(gaps, key=lambda g: severity_rank.get(g["severity"], 3))

    for i, gap in enumerate(gaps_sorted, 1):
        sev = gap["severity"].upper()
        sev_tag = f"[{sev}]"
        lines.append(f"{i}. {sev_tag} {gap['feature']}")
        lines.append(f"   {gap['description']}")
        lines.append(f"   Workaround: {gap['workaround']}")
        lines.append("")

    if mcp_gaps:
        lines.append("MCP Server Gaps")
        lines.append("-" * 40)
        for msg in mcp_gaps:
            lines.append(f"  • {msg}")
        lines.append(f"  Tip: Describe MCP tool capabilities in rules so {target_harness} "
                     "users know what to do manually.")
        lines.append("")

    skill_msgs = skill_issues_by_harness.get(target_lc, [])
    if skill_msgs:
        lines.append("Skill Compatibility Issues")
        lines.append("-" * 40)
        for msg in skill_msgs:
            lines.append(f"  • {msg}")
        lines.append("")

    lines.append(
        f"Run 'skill_transpiler.transpile_all(skills_dir, target={target_harness!r})' "
        "to convert skills to the closest native equivalent."
    )

    return "\n".join(lines)
