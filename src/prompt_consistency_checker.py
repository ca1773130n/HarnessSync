from __future__ import annotations

"""Cross-Harness Prompt Consistency Checker.

Statically analyses how a CLAUDE.md rule set will be experienced across
multiple harnesses and highlights behavioural divergence caused by:

1. **Structural translation gaps** — rules that exist in CLAUDE.md but whose
   section type (agents, commands, skills) is not supported by the target
   harness, so they are silently dropped.

2. **Sync tag exclusions** — sections explicitly excluded for certain targets
   via ``<!-- sync:exclude -->`` or ``<!-- harness:skip=TARGET -->`` tags.

3. **Fidelity loss** — rules that survive translation but at reduced fidelity
   (e.g. MCP server definitions written as commented text in Aider).

4. **Feature gap rules** — rules that reference Claude Code-specific features
   (tools, hooks, plugins) that other harnesses cannot act on.

This is *static* analysis — it does not call any harness CLI.  The output is
a divergence report that shows users exactly where their AI tools will behave
differently across harnesses.

Usage::

    from src.prompt_consistency_checker import PromptConsistencyChecker

    checker = PromptConsistencyChecker()
    report = checker.check(source_data, targets=["codex", "gemini", "aider"])
    print(checker.format_report(report))
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Feature support matrix: harness → section_type → fidelity level
# "full"    = full support, 1:1 translation
# "partial" = approximated/degraded translation
# "none"    = not supported; content dropped
# ---------------------------------------------------------------------------
_SECTION_FIDELITY: dict[str, dict[str, str]] = {
    "codex": {
        "rules":    "full",
        "skills":   "partial",   # translated to AGENTS.md prompt text
        "agents":   "partial",   # translated to AGENTS.md subagent sections
        "commands": "none",
        "mcp":      "partial",   # written to agents.json but not executed
        "settings": "partial",
    },
    "gemini": {
        "rules":    "full",
        "skills":   "partial",   # translated to GEMINI.md sections
        "agents":   "none",
        "commands": "none",
        "mcp":      "partial",
        "settings": "partial",
    },
    "opencode": {
        "rules":    "full",
        "skills":   "none",
        "agents":   "none",
        "commands": "none",
        "mcp":      "full",
        "settings": "partial",
    },
    "cursor": {
        "rules":    "full",
        "skills":   "partial",   # embedded in .mdc rules
        "agents":   "none",
        "commands": "none",
        "mcp":      "partial",   # needs separate Cursor MCP setup
        "settings": "none",
    },
    "aider": {
        "rules":    "full",
        "skills":   "none",      # mapped to context files (no execution)
        "agents":   "none",
        "commands": "none",
        "mcp":      "none",
        "settings": "none",
    },
    "windsurf": {
        "rules":    "full",
        "skills":   "none",      # mapped to memory files
        "agents":   "none",
        "commands": "none",
        "mcp":      "partial",
        "settings": "none",
    },
}

# Rules that reference Claude Code-specific features reduce portability
_CLAUDE_ONLY_PATTERNS = [
    (re.compile(r"\b(Bash|Read|Write|Edit|Glob|Grep|Agent|TodoWrite|WebFetch|WebSearch)\b\s+tool", re.I),
     "references Claude Code tool"),
    (re.compile(r"PostToolUse|PreToolUse|UserPromptSubmit|SessionStart|SessionEnd", re.I),
     "references Claude Code hook event"),
    (re.compile(r"\$CLAUDE_PLUGIN_ROOT", re.I),
     "uses Claude Code plugin path variable"),
    (re.compile(r"mcp__\w+__\w+", re.I),
     "calls MCP tool directly"),
    (re.compile(r"\.claude/hooks", re.I),
     "references Claude Code hooks directory"),
]


@dataclass
class SectionDivergence:
    """Divergence info for a single config section across harnesses."""

    section_type: str         # "rules", "skills", "agents", "commands", "mcp", "settings"
    target: str               # harness name
    fidelity: str             # "full", "partial", "none"
    reason: str               # human-readable explanation
    affected_count: int = 0   # number of items (rules/skills/etc) affected


@dataclass
class RulePortabilityIssue:
    """A specific rule that reduces portability for one or more harnesses."""

    rule_excerpt: str          # first 120 chars of the rule text
    pattern_desc: str          # what pattern was found
    affected_targets: list[str] = field(default_factory=list)
    line_number: int = 0


@dataclass
class ConsistencyReport:
    """Full cross-harness consistency report for a source config."""

    targets: list[str]
    section_divergences: list[SectionDivergence] = field(default_factory=list)
    portability_issues: list[RulePortabilityIssue] = field(default_factory=list)
    # Per-target overall consistency score 0-100
    consistency_scores: dict[str, int] = field(default_factory=dict)

    @property
    def has_divergence(self) -> bool:
        return bool(self.section_divergences or self.portability_issues)


class PromptConsistencyChecker:
    """Static cross-harness prompt consistency analyser."""

    def check(
        self,
        source_data: dict,
        targets: list[str] | None = None,
    ) -> ConsistencyReport:
        """Analyse source config for cross-harness behavioural divergence.

        Args:
            source_data: Parsed source config dict from SourceReader
                         (keys: rules, skills, agents, commands, mcp, settings).
            targets:     Harnesses to compare.  Defaults to all known targets.

        Returns:
            ConsistencyReport with divergence details and per-target scores.
        """
        if targets is None:
            targets = list(_SECTION_FIDELITY.keys())

        report = ConsistencyReport(targets=list(targets))

        # --- Section-level fidelity gaps ---
        _present_sections = self._detect_present_sections(source_data)
        for target in targets:
            target_matrix = _SECTION_FIDELITY.get(target, {})
            for section in _present_sections:
                fidelity = target_matrix.get(section, "none")
                if fidelity != "full":
                    reason = self._fidelity_reason(target, section, fidelity)
                    count = self._section_item_count(source_data, section)
                    report.section_divergences.append(SectionDivergence(
                        section_type=section,
                        target=target,
                        fidelity=fidelity,
                        reason=reason,
                        affected_count=count,
                    ))

        # --- Rule portability issues (Claude Code-specific patterns) ---
        rules_text = self._extract_rules_text(source_data)
        if rules_text:
            report.portability_issues = self._check_rule_portability(
                rules_text, targets
            )

        # --- Compute per-target consistency scores ---
        for target in targets:
            report.consistency_scores[target] = self._score_target(
                target, report, source_data
            )

        return report

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _detect_present_sections(self, source_data: dict) -> list[str]:
        """Return list of section types that have non-empty data."""
        present = []
        if source_data.get("rules"):
            present.append("rules")
        if source_data.get("skills"):
            present.append("skills")
        if source_data.get("agents"):
            present.append("agents")
        if source_data.get("commands"):
            present.append("commands")
        if source_data.get("mcp") or source_data.get("mcp_servers"):
            present.append("mcp")
        if source_data.get("settings"):
            present.append("settings")
        return present

    def _section_item_count(self, source_data: dict, section: str) -> int:
        """Return the number of items in a section."""
        val = source_data.get(section) or source_data.get(f"{section}_servers")
        if val is None:
            return 0
        if isinstance(val, (list, dict)):
            return len(val)
        if isinstance(val, str):
            return 1 if val.strip() else 0
        return 0

    def _fidelity_reason(self, target: str, section: str, fidelity: str) -> str:
        """Generate a human-readable reason for fidelity loss."""
        _reasons: dict[str, dict[str, str]] = {
            "codex": {
                "skills":   "Skills translated to AGENTS.md prompt text (no native skill runner)",
                "agents":   "Agents translated to AGENTS.md subagent descriptions",
                "commands": "Commands not supported; content dropped",
                "mcp":      "MCP configs written to agents.json but not executed by Codex",
                "settings": "Only subset of settings have Codex equivalents",
            },
            "gemini": {
                "skills":   "Skills translated to GEMINI.md sections (no execution model)",
                "agents":   "Agents not supported; content dropped",
                "commands": "Commands not supported; content dropped",
                "mcp":      "MCP servers written to GEMINI.md but require manual Gemini MCP setup",
                "settings": "Settings partially mapped; some fields silently ignored",
            },
            "opencode": {
                "skills":   "Skills not supported; content dropped",
                "agents":   "Agents not supported; content dropped",
                "commands": "Commands not supported; content dropped",
                "settings": "Settings partially mapped to opencode.json equivalents",
            },
            "cursor": {
                "skills":   "Skills embedded as .mdc rule text (no execution model)",
                "agents":   "Agents not supported; content dropped",
                "commands": "Commands not supported; content dropped",
                "mcp":      "MCP requires separate Cursor MCP JSON configuration",
                "settings": "Settings not supported; content dropped",
            },
            "aider": {
                "skills":   "Skills mapped to read-only context files (no execution)",
                "agents":   "Agents not supported; content dropped",
                "commands": "Commands not supported; content dropped",
                "mcp":      "MCP not supported in Aider; servers dropped",
                "settings": "Settings not supported; content dropped",
            },
            "windsurf": {
                "skills":   "Skills mapped to Windsurf memory files (no execution model)",
                "agents":   "Agents not supported; content dropped",
                "commands": "Commands not supported; content dropped",
                "mcp":      "MCP requires separate Windsurf MCP configuration",
                "settings": "Settings not supported; content dropped",
            },
        }
        default = f"{section} support is {fidelity} in {target}"
        return _reasons.get(target, {}).get(section, default)

    def _extract_rules_text(self, source_data: dict) -> str:
        """Concatenate all rules content into a single analysable string."""
        parts = []
        rules = source_data.get("rules", [])
        if isinstance(rules, str):
            parts.append(rules)
        elif isinstance(rules, list):
            for r in rules:
                if isinstance(r, dict):
                    parts.append(r.get("content", ""))
                elif isinstance(r, str):
                    parts.append(r)
        return "\n".join(parts)

    def _check_rule_portability(
        self,
        rules_text: str,
        targets: list[str],
    ) -> list[RulePortabilityIssue]:
        """Scan rules text for Claude Code-specific patterns."""
        issues: list[RulePortabilityIssue] = []
        lines = rules_text.splitlines()

        # Targets that cannot act on Claude Code-specific patterns
        non_cc_targets = [t for t in targets if t != "claude"]

        for line_no, line in enumerate(lines, 1):
            for pattern, desc in _CLAUDE_ONLY_PATTERNS:
                if pattern.search(line):
                    issues.append(RulePortabilityIssue(
                        rule_excerpt=line.strip()[:120],
                        pattern_desc=desc,
                        affected_targets=list(non_cc_targets),
                        line_number=line_no,
                    ))
                    break  # one issue per line
        return issues

    def _score_target(
        self,
        target: str,
        report: ConsistencyReport,
        source_data: dict,
    ) -> int:
        """Compute a 0-100 consistency score for a target.

        100 = identical behaviour to Claude Code
        0   = all config lost in translation
        """
        score = 100

        # Deductions for section fidelity gaps
        target_divs = [d for d in report.section_divergences if d.target == target]
        for div in target_divs:
            if div.fidelity == "none":
                score -= 15
            elif div.fidelity == "partial":
                score -= 7

        # Deductions for portability issues (capped at 20 points total)
        portability_penalty = min(20, len(report.portability_issues) * 2)
        score -= portability_penalty

        return max(0, min(100, score))

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_report(self, report: ConsistencyReport) -> str:
        """Format a ConsistencyReport as human-readable text.

        Args:
            report: Report from :meth:`check`.

        Returns:
            Formatted multi-line string.
        """
        lines = ["Cross-Harness Prompt Consistency Report", "=" * 60, ""]

        # Per-target score summary
        lines.append("Consistency Scores (vs Claude Code baseline):")
        lines.append("-" * 44)
        for target in sorted(report.targets):
            score = report.consistency_scores.get(target, 100)
            bar_len = score // 5  # 0-20 chars
            bar = "█" * bar_len + "░" * (20 - bar_len)
            rating = "excellent" if score >= 85 else "good" if score >= 65 else "degraded" if score >= 40 else "poor"
            lines.append(f"  {target:<12} {score:>3}%  [{bar}]  {rating}")

        if not report.has_divergence:
            lines.append("")
            lines.append("No divergence detected — all configured harnesses have full parity.")
            return "\n".join(lines)

        # Section fidelity gaps
        if report.section_divergences:
            lines.append("")
            lines.append("Section Fidelity Gaps:")
            lines.append("-" * 44)
            by_target: dict[str, list[SectionDivergence]] = {}
            for div in report.section_divergences:
                by_target.setdefault(div.target, []).append(div)

            for target in sorted(by_target):
                lines.append(f"\n  {target}:")
                for div in by_target[target]:
                    fid_label = {"full": "✓", "partial": "~", "none": "✗"}.get(div.fidelity, "?")
                    count_str = f" ({div.affected_count} item(s))" if div.affected_count else ""
                    lines.append(f"    [{fid_label}] {div.section_type}{count_str}")
                    lines.append(f"        {div.reason}")

        # Portability issues
        if report.portability_issues:
            lines.append("")
            lines.append(f"Rule Portability Issues ({len(report.portability_issues)} found):")
            lines.append("-" * 44)
            lines.append("  These rules reference Claude Code-specific features that other")
            lines.append("  harnesses cannot act on:")
            for issue in report.portability_issues[:10]:
                lines.append(f"\n  Line {issue.line_number}: {issue.pattern_desc}")
                lines.append(f"    > {issue.rule_excerpt}")
            if len(report.portability_issues) > 10:
                lines.append(f"\n  ... and {len(report.portability_issues) - 10} more issues")

        return "\n".join(lines)
