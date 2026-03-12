from __future__ import annotations

"""Cross-harness config comparison (item 17).

Compares how a CLAUDE.md configuration translates across multiple harnesses,
surfacing behavioral differences caused by feature gaps, format translations,
and sync tag filtering.

Unlike an actual prompt comparison (which would require calling each harness
CLI), this tool performs a *static* config comparison: it analyses the same
CLAUDE.md and shows which rules, sections, and features each harness would
receive, and what fidelity the translation achieves.

This helps users understand the real-world differences in AI behaviour caused
by config translation gaps before syncing.

Usage:
    from src.harness_comparison import HarnessConfigComparison

    cmp = HarnessConfigComparison()
    report = cmp.compare(source_data, targets=["codex", "gemini", "cursor"])
    print(cmp.format_report(report))

Or from the CLI (sync-compare command):
    /sync-compare [--targets codex,gemini,cursor] [--project-dir PATH]
"""

from dataclasses import dataclass, field
from pathlib import Path

# Harness-specific feature support matrix:
# Maps feature_category -> set of targets that support it.
# "partial" means some approximation exists but with lower fidelity.
_FEATURE_SUPPORT: dict[str, dict[str, str]] = {
    "rules": {
        "codex":    "full",
        "gemini":   "full",
        "opencode": "full",
        "cursor":   "full",
        "aider":    "full",
        "windsurf": "full",
        "cline":    "full",     # Via .clinerules
        "continue": "full",     # Via .continue/rules/
        "zed":      "full",     # Via .zed/system-prompt.md
        "neovim":   "partial",  # Via .avante/system-prompt.md or .codecompanion/
    },
    "skills": {
        "codex":    "none",     # No native skill concept; translates to AGENTS.md prompt
        "gemini":   "partial",  # Translated to GEMINI.md sections
        "opencode": "none",
        "cursor":   "partial",  # Embedded in .mdc rules
        "aider":    "none",
        "windsurf": "none",
        "cline":    "none",     # No skill concept in Cline
        "continue": "none",     # No skill concept in Continue
        "zed":      "none",     # No skill concept in Zed AI
        "neovim":   "none",     # No skill concept in neovim AI plugins
    },
    "agents": {
        "codex":    "partial",  # Translated to AGENTS.md subagent descriptions
        "gemini":   "none",
        "opencode": "none",
        "cursor":   "none",
        "aider":    "none",
        "windsurf": "none",
        "cline":    "none",     # No subagent concept in Cline
        "continue": "none",     # No subagent concept in Continue
        "zed":      "none",     # No subagent concept in Zed AI
        "neovim":   "none",     # No subagent concept in neovim AI plugins
    },
    "commands": {
        "codex":    "none",
        "gemini":   "partial",  # Translated to GEMINI.md slash-command hints
        "opencode": "none",
        "cursor":   "none",
        "aider":    "none",
        "windsurf": "none",
        "cline":    "none",     # No slash commands in Cline
        "continue": "none",     # No slash commands in Continue
        "zed":      "none",     # No slash commands in Zed AI
        "neovim":   "none",     # No slash commands in neovim AI plugins
    },
    "mcp": {
        "codex":    "full",
        "gemini":   "full",
        "opencode": "full",
        "cursor":   "full",
        "aider":    "none",
        "windsurf": "partial",  # Some MCP fields omitted
        "cline":    "full",     # Via .roo/mcp.json (MCP native support)
        "continue": "full",     # Via .continue/config.json mcpServers
        "zed":      "partial",  # Via .zed/settings.json context_servers (different schema)
        "neovim":   "partial",  # Via .avante/mcp.json (limited field support)
    },
    "settings": {
        "codex":    "full",
        "gemini":   "partial",  # Fewer settings supported
        "opencode": "full",
        "cursor":   "none",
        "aider":    "partial",  # Via .aider.conf.yml
        "windsurf": "partial",
        "cline":    "none",     # Settings managed in VSCode UI
        "continue": "none",     # Settings managed in IDE extension settings
        "zed":      "partial",  # Via .zed/settings.json assistant section
        "neovim":   "none",     # Settings via plugin config in init.lua/init.vim
    },
}

_FIDELITY_SCORE = {"full": 1.0, "partial": 0.5, "none": 0.0}


@dataclass
class HarnessFeatureComparisonRow:
    """Comparison data for a single feature/section across harnesses."""

    feature: str
    per_harness: dict[str, str] = field(default_factory=dict)  # target -> "full"|"partial"|"none"
    notes: dict[str, str] = field(default_factory=dict)         # target -> explanation


@dataclass
class HarnessComparisonReport:
    """Full cross-harness comparison report."""

    targets: list[str]
    source_sections: list[str]           # Which sections exist in source
    rows: list[HarnessFeatureComparisonRow]
    rule_coverage: dict[str, int]        # target -> rule count after filtering
    compliance_rule_count: int           # Number of compliance-pinned rules
    tag_filtered_targets: dict[str, int] # target -> rules excluded by sync tags
    overall_scores: dict[str, float]     # target -> 0-100 compatibility score
    parity_gaps: dict[str, list[str]]    # target -> list of gap descriptions


class HarnessConfigComparison:
    """Compare how CLAUDE.md config translates across multiple harnesses.

    Performs static analysis of the source config to show per-target feature
    coverage, rule filtering, and compatibility scores without executing any
    harness binary.
    """

    ALL_TARGETS = (
        "codex", "gemini", "opencode", "cursor", "aider", "windsurf",
        "cline", "continue", "zed", "neovim",
    )

    def compare(
        self,
        source_data: dict,
        targets: list[str] | None = None,
        rules_content: str = "",
    ) -> HarnessComparisonReport:
        """Compare how source_data translates to each target.

        Args:
            source_data: Dict from SourceReader (keys: rules, skills, agents,
                         commands, mcp, settings, etc.)
            targets: Harness names to compare. Defaults to all known targets.
            rules_content: Raw CLAUDE.md rules text, used for sync-tag analysis.

        Returns:
            HarnessComparisonReport with per-target coverage and scores.
        """
        if targets is None:
            targets = list(self.ALL_TARGETS)

        # Determine which sections are present in source
        source_sections = [
            s for s in ("rules", "skills", "agents", "commands", "mcp", "settings")
            if source_data.get(s)
        ]

        # Build per-feature comparison rows
        rows: list[HarnessFeatureComparisonRow] = []
        for feature in ("rules", "skills", "agents", "commands", "mcp", "settings"):
            if feature not in source_sections:
                continue
            row = HarnessFeatureComparisonRow(feature=feature)
            for target in targets:
                support = _FEATURE_SUPPORT.get(feature, {}).get(target, "none")
                row.per_harness[target] = support
                if support == "partial":
                    row.notes[target] = self._partial_note(feature, target)
                elif support == "none":
                    row.notes[target] = self._none_note(feature, target)
            rows.append(row)

        # Count rules after sync-tag filtering per target
        rule_coverage: dict[str, int] = {}
        tag_filtered: dict[str, int] = {}
        compliance_count = 0

        if rules_content:
            from src.sync_filter import filter_rules_for_target, has_compliance_pinned, extract_compliance_pinned
            from src.harness_rule_dsl import RuleDSLParser, get_compliance_rules

            parser = RuleDSLParser()
            dsl_rules = parser.parse(rules_content)
            compliance_count = len(get_compliance_rules(dsl_rules))

            raw_lines = [ln for ln in rules_content.splitlines() if ln.strip()]
            raw_count = len(raw_lines)

            for target in targets:
                filtered = filter_rules_for_target(rules_content, target)
                filtered_lines = [ln for ln in filtered.splitlines() if ln.strip()]
                filtered_count = len(filtered_lines)
                rule_coverage[target] = filtered_count
                tag_filtered[target] = max(0, raw_count - filtered_count)
        else:
            for target in targets:
                rule_coverage[target] = 0
                tag_filtered[target] = 0

        # Compute per-target compatibility scores (0-100)
        overall_scores: dict[str, float] = {}
        parity_gaps: dict[str, list[str]] = {}

        for target in targets:
            if not source_sections:
                overall_scores[target] = 100.0
                parity_gaps[target] = []
                continue

            total_score = 0.0
            gaps: list[str] = []

            for feature in source_sections:
                support = _FEATURE_SUPPORT.get(feature, {}).get(target, "none")
                fidelity = _FIDELITY_SCORE[support]
                total_score += fidelity
                if support == "partial":
                    gaps.append(f"{feature}: partially supported — {self._partial_note(feature, target)}")
                elif support == "none":
                    gaps.append(f"{feature}: not supported — {self._none_note(feature, target)}")

            score = (total_score / len(source_sections)) * 100
            # Penalise for sync-tag filtering
            if rules_content and rule_coverage.get(target, 0) > 0:
                raw = sum(1 for ln in rules_content.splitlines() if ln.strip())
                if raw > 0:
                    coverage_ratio = rule_coverage[target] / raw
                    score = score * (0.5 + 0.5 * coverage_ratio)

            overall_scores[target] = round(score, 1)
            parity_gaps[target] = gaps

        return HarnessComparisonReport(
            targets=targets,
            source_sections=source_sections,
            rows=rows,
            rule_coverage=rule_coverage,
            compliance_rule_count=compliance_count,
            tag_filtered_targets=tag_filtered,
            overall_scores=overall_scores,
            parity_gaps=parity_gaps,
        )

    @staticmethod
    def _partial_note(feature: str, target: str) -> str:
        """Return a brief explanation for partial feature support."""
        notes = {
            ("skills", "gemini"):   "skills translated to GEMINI.md sections without invocation syntax",
            ("skills", "cursor"):   "skills embedded in .mdc rules; no separate skill invocation",
            ("agents", "codex"):    "agents described in AGENTS.md as subagent descriptions only",
            ("commands", "gemini"): "commands translated to GEMINI.md slash-command hints only",
            ("mcp", "windsurf"):    "some MCP fields (auth, headers) omitted in Windsurf format",
            ("mcp", "zed"):         "MCP mapped to context_servers; different schema and no env var support",
            ("mcp", "neovim"):      "MCP via .avante/mcp.json; limited to command/args fields only",
            ("settings", "gemini"): "subset of settings supported; approval_mode and shell only",
            ("settings", "aider"):  "settings translated to .aider.conf.yml key-value pairs",
            ("settings", "windsurf"): "limited settings via .windsurfrules",
            ("settings", "zed"):    "assistant model/context settings only; permissions not supported",
            ("rules", "neovim"):    "rules synced to .avante/system-prompt.md; plugin must be avante.nvim",
        }
        return notes.get((feature, target), f"{feature} approximated for {target}")

    @staticmethod
    def _none_note(feature: str, target: str) -> str:
        """Return a brief explanation for unsupported features."""
        notes = {
            ("skills", "codex"):    "no skill concept; skill descriptions dropped",
            ("skills", "opencode"): "no skill concept in OpenCode",
            ("skills", "aider"):    "no skill concept in Aider",
            ("skills", "windsurf"): "no skill concept in Windsurf",
            ("skills", "cline"):    "no skill concept in Cline",
            ("skills", "continue"): "no skill concept in Continue",
            ("skills", "zed"):      "no skill concept in Zed AI",
            ("skills", "neovim"):   "no skill concept in neovim AI plugins",
            ("agents", "gemini"):   "no subagent concept in Gemini CLI",
            ("agents", "opencode"): "no subagent concept in OpenCode",
            ("agents", "cursor"):   "no subagent concept in Cursor",
            ("agents", "aider"):    "no subagent concept in Aider",
            ("agents", "windsurf"): "no subagent concept in Windsurf",
            ("agents", "cline"):    "no subagent concept in Cline",
            ("agents", "continue"): "no subagent concept in Continue",
            ("agents", "zed"):      "no subagent concept in Zed AI",
            ("agents", "neovim"):   "no subagent concept in neovim AI plugins",
            ("commands", "codex"):  "no slash commands in Codex",
            ("commands", "opencode"): "no slash commands in OpenCode",
            ("commands", "cursor"): "no slash commands in Cursor",
            ("commands", "aider"):  "no slash commands in Aider",
            ("commands", "windsurf"): "no slash commands in Windsurf",
            ("commands", "cline"):  "no slash commands in Cline",
            ("commands", "continue"): "no slash commands in Continue",
            ("commands", "zed"):    "no slash commands in Zed AI",
            ("commands", "neovim"): "no slash commands in neovim AI plugins",
            ("mcp", "aider"):       "Aider does not support MCP server configuration",
            ("settings", "cursor"): "Cursor settings managed in UI, not config files",
            ("settings", "cline"):  "Cline settings managed in VSCode UI extension settings",
            ("settings", "continue"): "Continue settings managed in IDE extension settings",
            ("settings", "neovim"): "neovim AI plugin settings managed in init.lua/init.vim",
        }
        return notes.get((feature, target), f"{feature} not supported by {target}")

    def format_report(self, report: HarnessComparisonReport) -> str:
        """Format a HarnessComparisonReport as a human-readable string.

        Args:
            report: Output of compare().

        Returns:
            Formatted multi-line comparison report.
        """
        targets = report.targets
        col_w = max(10, max(len(t) for t in targets) + 2)

        lines = [
            "Cross-Harness Config Comparison",
            "=" * (20 + col_w * len(targets)),
            "",
        ]

        if report.compliance_rule_count:
            lines.append(f"  ✓ {report.compliance_rule_count} compliance-pinned rule(s) — always synced to all targets")
            lines.append("")

        # Feature coverage table
        header = f"  {'Feature':<14}" + "".join(f"{t:^{col_w}}" for t in targets)
        lines.append(header)
        lines.append("  " + "-" * (14 + col_w * len(targets)))

        support_icons = {"full": "✓", "partial": "~", "none": "✗"}
        for row in report.rows:
            row_str = f"  {row.feature:<14}"
            for target in targets:
                icon = support_icons.get(row.per_harness.get(target, "none"), "?")
                row_str += f"{icon:^{col_w}}"
            lines.append(row_str)

        lines.append("")
        lines.append("  ✓=full  ~=partial  ✗=not supported")
        lines.append("")

        # Compatibility scores
        lines.append("Compatibility Scores:")
        lines.append("")
        for target in sorted(targets, key=lambda t: report.overall_scores.get(t, 0), reverse=True):
            score = report.overall_scores.get(target, 0)
            bar = "█" * int(score / 5) + "░" * (20 - int(score / 5))
            tag_info = ""
            filtered = report.tag_filtered_targets.get(target, 0)
            if filtered:
                tag_info = f"  ({filtered} rules excluded by sync tags)"
            lines.append(f"  {target:<12} {score:>5.1f}%  [{bar}]{tag_info}")

        lines.append("")

        # Parity gaps
        targets_with_gaps = [(t, g) for t in targets if (g := report.parity_gaps.get(t, []))]
        if targets_with_gaps:
            lines.append("Parity Gaps:")
            lines.append("")
            for target, gaps in targets_with_gaps:
                lines.append(f"  {target.upper()}:")
                for gap in gaps:
                    lines.append(f"    - {gap}")
                lines.append("")

        return "\n".join(lines)

    @classmethod
    def from_project(
        cls,
        project_dir: Path,
        targets: list[str] | None = None,
        cc_home: Path | None = None,
    ) -> "tuple[HarnessConfigComparison, HarnessComparisonReport]":
        """Convenience factory: load source data and run comparison.

        Args:
            project_dir: Project root directory.
            targets: Target harnesses to compare. Defaults to all.
            cc_home: Custom Claude Code home directory.

        Returns:
            Tuple of (HarnessConfigComparison instance, HarnessComparisonReport).
        """
        from src.source_reader import SourceReader

        reader = SourceReader(scope="all", project_dir=project_dir, cc_home=cc_home)
        source_data = reader.read_all()

        # Extract raw rules content for sync-tag analysis
        rules_content = ""
        rules_src = source_data.get("rules", {})
        if isinstance(rules_src, dict):
            # user-level rules
            rules_content = "\n".join(
                str(v) for v in rules_src.values() if v
            )
        elif isinstance(rules_src, str):
            rules_content = rules_src

        cmp = cls()
        report = cmp.compare(source_data, targets=targets, rules_content=rules_content)
        return cmp, report
