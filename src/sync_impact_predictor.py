from __future__ import annotations

"""Sync Impact Predictor — analyze pending config changes before sync.

Before syncing, this module examines the diff between the current source
config and the last-synced state to predict the behavioral impact of the
pending sync:

- New rules that may conflict with target-harness built-in style preferences
- MCP servers being added and what new tools they expose per harness
- Rules being removed and which harnesses will lose that guidance
- Settings changes and their downstream permission effects

All predictions use pattern matching against known harness behaviors and the
pending diff — no LLM inference required.

Usage:
    predictor = SyncImpactPredictor(project_dir=Path("."))
    report = predictor.predict(current_source_data, previous_source_data)
    print(report.format())
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Known harness style preferences that can conflict with user rules
# ──────────────────────────────────────────────────────────────────────────────

# Map: target -> list of (pattern, built-in-preference-description)
_HARNESS_PREFERENCES: dict[str, list[tuple[re.Pattern, str]]] = {
    "codex": [
        (re.compile(r"always use tabs|use tab indentation", re.I),
         "Codex defaults to 2-space indentation — may conflict"),
        (re.compile(r"use double quotes", re.I),
         "Codex may prefer single quotes in some language defaults"),
        (re.compile(r"no comments|avoid comments", re.I),
         "Codex often generates inline comments by default — may conflict"),
    ],
    "cursor": [
        (re.compile(r"avoid ai suggestion|disable autocomplete", re.I),
         "Cursor is autocomplete-first — rules suppressing suggestions may be ignored"),
        (re.compile(r"always ask before|never auto", re.I),
         "Cursor tab-complete mode bypasses ask-before semantics"),
    ],
    "aider": [
        (re.compile(r"use conventional commit|commit message", re.I),
         "Aider generates its own commit messages — commit format rules have limited effect"),
        (re.compile(r"no auto.commit|never commit", re.I),
         "Aider auto-commits by default — add --no-auto-commits flag if needed"),
    ],
    "gemini": [
        (re.compile(r"use typescript|prefer ts over js", re.I),
         "Gemini CLI is language-agnostic — TS preference may not be enforced"),
        (re.compile(r"use\b.{0,30}\bskill\b|invoke\b.{0,30}\bskill", re.I),
         "Gemini CLI has no slash command / skill system — skill invocations won't work"),
        (re.compile(r"/[a-z][-a-z]+\b", re.I),
         "Slash commands don't exist in Gemini CLI — prefix rules using them may be ignored"),
    ],
    "windsurf": [
        (re.compile(r"cascade|flow\s+mode", re.I),
         "Windsurf-specific terminology may confuse other harnesses if rules reference it"),
    ],
    "cline": [
        (re.compile(r"autoApprove|auto.approve|approve all", re.I),
         "Cline auto-approval is configured in VSCode settings, not in rules files"),
    ],
    "continue": [
        (re.compile(r"tab\s*complete|inline\s*suggest", re.I),
         "Continue.dev inline suggestions are controlled via config.json, not system rules"),
    ],
    "zed": [
        (re.compile(r"context\s*window|token\s*limit", re.I),
         "Zed assistant uses a fixed context window — token limit rules have no effect"),
    ],
    "neovim": [
        (re.compile(r"buffer|window|split|nvim|neovim", re.I),
         "Neovim-specific terms in rules may confuse other harnesses"),
    ],
}

# MCP server tool name patterns for impact estimation
_MCP_TOOL_PATTERNS: dict[str, list[str]] = {
    "filesystem": ["read_file", "write_file", "list_directory", "search_files", "create_directory"],
    "github": ["get_repo", "list_prs", "create_issue", "merge_pr", "get_file_contents", "push_files"],
    "postgres": ["query", "list_tables", "describe_table", "execute", "list_schemas"],
    "sqlite": ["query", "insert", "list_tables", "create_table"],
    "memory": ["store", "recall", "list_memories", "delete_memory"],
    "fetch": ["fetch_url", "get_page", "post_request"],
    "puppeteer": ["navigate", "screenshot", "click", "type", "evaluate"],
    "playwright": ["navigate", "screenshot", "click", "fill_form", "take_screenshot"],
    "git": ["log", "diff", "status", "commit", "create_branch"],
    "brave-search": ["web_search", "local_search"],
    "slack": ["send_message", "list_channels", "get_thread"],
    "jira": ["get_issue", "create_issue", "update_issue", "search_issues"],
    "linear": ["get_issues", "create_issue", "update_issue"],
    "aws": ["list_buckets", "get_object", "put_object", "list_functions"],
    "docker": ["list_containers", "run_container", "exec_command"],
    "kubernetes": ["get_pods", "apply_manifest", "exec_command"],
}


def _guess_mcp_tools(server_name: str, server_config: dict) -> list[str]:
    """Guess tool names exposed by an MCP server from its name/config."""
    for key, tools in _MCP_TOOL_PATTERNS.items():
        if key in server_name.lower():
            return tools
    # Fallback: generic tool placeholder
    return [f"{server_name.lower()}_tool"]


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ImpactItem:
    """A single predicted behavioral impact."""
    severity: str    # "info" | "warning" | "note"
    target: str      # harness target name, or "all"
    category: str    # "rule_conflict" | "mcp_added" | "mcp_removed" | "rule_removed" | "settings"
    message: str


@dataclass
class SyncImpactReport:
    """Predicted impact of a pending sync operation."""
    items: list[ImpactItem] = field(default_factory=list)
    new_mcp_servers: list[str] = field(default_factory=list)
    removed_mcp_servers: list[str] = field(default_factory=list)
    new_rules_lines: int = 0
    removed_rules_lines: int = 0
    # File-count estimates per target (item 21 — Sync Impact Estimator)
    estimated_files_per_target: dict[str, int] = field(default_factory=dict)
    # Targets where a high-importance file (e.g. system prompt) would change
    high_impact_targets: list[str] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "warning" for i in self.items)

    @property
    def is_empty(self) -> bool:
        return (
            not self.items
            and not self.new_mcp_servers
            and not self.removed_mcp_servers
            and self.new_rules_lines == 0
            and self.removed_rules_lines == 0
        )

    @property
    def impact_score(self) -> int:
        """Numeric impact score from 1 (trivial) to 10 (high impact).

        Scoring formula:
        - Each warning item contributes 2 points (capped)
        - Each removed MCP server contributes 3 points
        - Each added MCP server contributes 1 point
        - Large rule additions (>20 lines) add 2 points
        - Large rule removals (>10 lines) add 2 points
        Minimum 1 if any changes exist, 0 if empty.
        """
        if self.is_empty:
            return 0

        score = 1  # Baseline: any change = at least 1

        warnings = sum(1 for i in self.items if i.severity == "warning")
        score += min(warnings * 2, 4)

        score += min(len(self.removed_mcp_servers) * 3, 3)
        score += min(len(self.new_mcp_servers), 1)

        if self.new_rules_lines > 20:
            score += 2
        elif self.new_rules_lines > 5:
            score += 1

        if self.removed_rules_lines > 10:
            score += 2
        elif self.removed_rules_lines > 2:
            score += 1

        return min(score, 10)

    @property
    def should_auto_approve(self) -> bool:
        """True when impact_score <= 3 — safe to apply without user review."""
        return self.impact_score <= 3

    def format(self) -> str:
        """Format the impact report for terminal display."""
        if self.is_empty:
            return "Sync Impact: No significant changes predicted."

        lines = ["Sync Impact Prediction", "=" * 50, ""]

        # Impact score header
        score = self.impact_score
        score_bar = "█" * score + "░" * (10 - score)
        auto_note = " (auto-approve eligible)" if self.should_auto_approve else " (review recommended)"
        lines.append(f"Impact Score: {score}/10  [{score_bar}]{auto_note}")
        lines.append("")

        # Summary
        summary_parts: list[str] = []
        if self.new_rules_lines:
            summary_parts.append(f"+{self.new_rules_lines} rule lines")
        if self.removed_rules_lines:
            summary_parts.append(f"-{self.removed_rules_lines} rule lines")
        if self.new_mcp_servers:
            summary_parts.append(f"+{len(self.new_mcp_servers)} MCP server(s)")
        if self.removed_mcp_servers:
            summary_parts.append(f"-{len(self.removed_mcp_servers)} MCP server(s)")
        if summary_parts:
            lines.append("Changes: " + "  ".join(summary_parts))
            lines.append("")

        # New MCP servers
        if self.new_mcp_servers:
            lines.append("New MCP servers (tool exposure per harness):")
            for srv in self.new_mcp_servers:
                lines.append(f"  + {srv}")
            lines.append("")

        # Removed MCP servers
        if self.removed_mcp_servers:
            lines.append("Removed MCP servers:")
            for srv in self.removed_mcp_servers:
                lines.append(f"  - {srv}")
            lines.append("")

        # Impact items grouped by severity
        warnings = [i for i in self.items if i.severity == "warning"]
        notes = [i for i in self.items if i.severity in ("info", "note")]

        if warnings:
            lines.append("⚠ Potential conflicts:")
            for item in warnings:
                target_tag = f"[{item.target}] " if item.target != "all" else ""
                lines.append(f"  {target_tag}{item.message}")
            lines.append("")

        if notes:
            lines.append("ℹ Notes:")
            for item in notes:
                target_tag = f"[{item.target}] " if item.target != "all" else ""
                lines.append(f"  {target_tag}{item.message}")
            lines.append("")

        # File-count estimates per target (item 21 — Sync Impact Estimator)
        if self.estimated_files_per_target:
            total_files = sum(self.estimated_files_per_target.values())
            lines.append(f"Files to change: ~{total_files} across {len(self.estimated_files_per_target)} target(s)")
            for target, count in sorted(self.estimated_files_per_target.items()):
                flag = "  ⚠ high-impact" if target in self.high_impact_targets else ""
                lines.append(f"  {target:<12} ~{count} file(s){flag}")

        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Predictor
# ──────────────────────────────────────────────────────────────────────────────

class SyncImpactPredictor:
    """Predicts behavioral impact of a pending sync before it executes.

    Args:
        project_dir: Project root (used for context; not written to).
    """

    def __init__(self, project_dir: Path | None = None) -> None:
        self.project_dir = project_dir or Path.cwd()

    def predict(
        self,
        current_source: dict,
        previous_source: dict | None = None,
        targets: list[str] | None = None,
    ) -> SyncImpactReport:
        """Predict the behavioral impact of syncing current_source.

        Args:
            current_source: Source data from SourceReader.discover_all() now.
            previous_source: Source data from the last sync (or None for first sync).
            targets: Harness targets to predict for (default: all known).

        Returns:
            SyncImpactReport with predicted impacts.
        """
        if targets is None:
            targets = list(_HARNESS_PREFERENCES.keys()) + ["opencode", "windsurf"]
        if previous_source is None:
            previous_source = {}

        report = SyncImpactReport()

        self._analyze_mcp_changes(current_source, previous_source, report)
        self._analyze_rules_changes(current_source, previous_source, report, targets)
        self._analyze_settings_changes(current_source, previous_source, report)
        self._estimate_file_counts(current_source, previous_source, targets, report)

        return report

    # Number of adapter-written files per section per harness (conservative estimates)
    _FILES_PER_SECTION: dict[str, dict[str, int]] = {
        "rules":    {"codex": 1, "gemini": 1, "opencode": 1, "cursor": 1, "aider": 1, "windsurf": 1},
        "skills":   {"codex": 3, "gemini": 3, "opencode": 3, "cursor": 3, "aider": 1, "windsurf": 2},
        "agents":   {"codex": 2, "gemini": 2, "opencode": 2, "cursor": 2, "aider": 0, "windsurf": 2},
        "commands": {"codex": 2, "gemini": 2, "opencode": 2, "cursor": 2, "aider": 0, "windsurf": 0},
        "mcp":      {"codex": 1, "gemini": 1, "opencode": 1, "cursor": 1, "aider": 0, "windsurf": 1},
        "settings": {"codex": 1, "gemini": 1, "opencode": 1, "cursor": 0, "aider": 1, "windsurf": 0},
    }

    # Sections considered "high importance" — changing them alters the AI's core behaviour
    _HIGH_IMPORTANCE_SECTIONS = frozenset({"rules", "settings"})

    def _estimate_file_counts(
        self,
        current: dict,
        previous: dict,
        targets: list[str],
        report: SyncImpactReport,
    ) -> None:
        """Populate estimated_files_per_target and high_impact_targets on *report*.

        Counts how many output files each target adapter would write based on
        which sections are present in *current* and whether they differ from
        *previous*. High-impact targets are those where a high-importance section
        (rules or settings) has changed content.
        """
        changed_sections: set[str] = set()

        for section in ("rules", "skills", "agents", "commands", "mcp", "settings"):
            cur_val = current.get(section) or current.get(f"{section}_content")
            prev_val = previous.get(section) or previous.get(f"{section}_content")
            if cur_val and cur_val != prev_val:
                changed_sections.add(section)

        # Also treat non-empty additions as "changed"
        if report.new_mcp_servers or report.removed_mcp_servers:
            changed_sections.add("mcp")
        if report.new_rules_lines or report.removed_rules_lines:
            changed_sections.add("rules")

        for target in targets:
            file_count = 0
            is_high_impact = False
            for section in changed_sections:
                per_harness = self._FILES_PER_SECTION.get(section, {})
                file_count += per_harness.get(target, 0)
                if section in self._HIGH_IMPORTANCE_SECTIONS and per_harness.get(target, 0) > 0:
                    is_high_impact = True
            if file_count > 0:
                report.estimated_files_per_target[target] = file_count
            if is_high_impact and file_count > 0:
                report.high_impact_targets.append(target)

    def _analyze_mcp_changes(
        self, current: dict, previous: dict, report: SyncImpactReport
    ) -> None:
        """Detect added/removed MCP servers and estimate tool exposure."""
        cur_mcp: dict = current.get("mcp_servers", {})
        prev_mcp: dict = previous.get("mcp_servers", {})

        cur_names = set(cur_mcp.keys())
        prev_names = set(prev_mcp.keys())

        added = cur_names - prev_names
        removed = prev_names - cur_names

        report.new_mcp_servers = sorted(added)
        report.removed_mcp_servers = sorted(removed)

        for server_name in added:
            cfg = cur_mcp.get(server_name, {})
            tools = _guess_mcp_tools(server_name, cfg)
            report.items.append(ImpactItem(
                severity="info",
                target="all",
                category="mcp_added",
                message=(
                    f"Adding '{server_name}' exposes {len(tools)} tool(s): "
                    f"{', '.join(tools[:4])}"
                    + (" ..." if len(tools) > 4 else "")
                ),
            ))

        for server_name in removed:
            report.items.append(ImpactItem(
                severity="warning",
                target="all",
                category="mcp_removed",
                message=f"Removing '{server_name}' — tools will disappear from all harnesses",
            ))

    def _analyze_rules_changes(
        self,
        current: dict,
        previous: dict,
        report: SyncImpactReport,
        targets: list[str],
    ) -> None:
        """Detect rules additions/removals and check for harness conflicts."""
        cur_rules = self._rules_text(current)
        prev_rules = self._rules_text(previous)

        cur_lines = set(cur_rules.splitlines())
        prev_lines = set(prev_rules.splitlines())

        added_lines = cur_lines - prev_lines
        removed_lines = prev_lines - cur_lines

        report.new_rules_lines = len(added_lines)
        report.removed_rules_lines = len(removed_lines)

        added_text = "\n".join(added_lines)

        # Check new rules for conflicts with harness preferences
        for target in targets:
            prefs = _HARNESS_PREFERENCES.get(target, [])
            for pattern, conflict_note in prefs:
                if pattern.search(added_text):
                    report.items.append(ImpactItem(
                        severity="warning",
                        target=target,
                        category="rule_conflict",
                        message=conflict_note,
                    ))

        if removed_lines:
            # Note about rule removals
            sample = next(iter(removed_lines), "")
            report.items.append(ImpactItem(
                severity="note",
                target="all",
                category="rule_removed",
                message=(
                    f"Removing {len(removed_lines)} rule line(s) — "
                    f"AI assistants will no longer see that guidance "
                    f"(e.g. '{sample[:60].strip()}{'...' if len(sample) > 60 else ''}')"
                ),
            ))

    def _analyze_settings_changes(
        self, current: dict, previous: dict, report: SyncImpactReport
    ) -> None:
        """Detect settings changes with downstream permission effects."""
        cur_settings = current.get("settings", {}) or {}
        prev_settings = previous.get("settings", {}) or {}

        cur_mode = cur_settings.get("approval_mode", "")
        prev_mode = prev_settings.get("approval_mode", "")

        if cur_mode and cur_mode != prev_mode:
            if cur_mode == "auto":
                report.items.append(ImpactItem(
                    severity="warning",
                    target="all",
                    category="settings",
                    message=(
                        f"approval_mode changed to 'auto' — all harnesses will have "
                        f"less restrictive permissions (was '{prev_mode or 'unset'}')"
                    ),
                ))
            elif prev_mode == "auto" and cur_mode in ("ask", "default"):
                report.items.append(ImpactItem(
                    severity="info",
                    target="all",
                    category="settings",
                    message=(
                        f"approval_mode changed from 'auto' to '{cur_mode}' — "
                        f"harnesses will prompt before running tools"
                    ),
                ))

    @staticmethod
    def _rules_text(source: dict) -> str:
        """Extract combined rules text from source data."""
        rules = source.get("rules", "")
        if isinstance(rules, list):
            return "\n".join(r.get("content", "") for r in rules if isinstance(r, dict))
        return rules or ""

    # ── Pre-Sync Capability Preview (item 2) ────────────────────────────────

    def build_capability_preview(
        self,
        current_source: dict,
        previous_source: dict | None = None,
        targets: list[str] | None = None,
    ) -> dict[str, dict]:
        """Build a per-target preview of exactly what will gain and lose in sync.

        Before running a sync, shows each harness a concise summary:
        - Rules lines added / removed
        - MCP servers to be added / removed
        - Skills to be added / removed (count)
        - Sections with unsupported features (will be skipped)

        Args:
            current_source: Source data dict from ``SourceReader.discover_all()``.
            previous_source: Source data from the last sync (or None for first sync).
            targets: List of harness targets to preview (default: standard set).

        Returns:
            Dict mapping target name → preview dict with keys:
            ``"rules_added"``, ``"rules_removed"``, ``"mcp_added"``,
            ``"mcp_removed"``, ``"skills_added"``, ``"skills_removed"``,
            ``"unsupported_sections"``, ``"summary"``.
        """
        from src.harness_feature_matrix import HarnessFeatureMatrix, ALL_FEATURES

        if previous_source is None:
            previous_source = {}
        if targets is None:
            targets = list(_HARNESS_PREFERENCES.keys()) + ["opencode", "windsurf", "cline", "continue"]

        matrix = HarnessFeatureMatrix()
        previews: dict[str, dict] = {}

        # --- Compute source-level deltas ---
        cur_rules_text = self._rules_text(current_source)
        prev_rules_text = self._rules_text(previous_source)
        cur_rules_lines = set(cur_rules_text.splitlines())
        prev_rules_lines = set(prev_rules_text.splitlines())
        new_rule_lines = len(cur_rules_lines - prev_rules_lines - {""})
        removed_rule_lines = len(prev_rules_lines - cur_rules_lines - {""})

        cur_mcp = set((current_source.get("mcp") or {}).keys())
        prev_mcp = set((previous_source.get("mcp") or {}).keys())
        mcp_added = sorted(cur_mcp - prev_mcp)
        mcp_removed = sorted(prev_mcp - cur_mcp)

        cur_skills = current_source.get("skills") or []
        prev_skills = previous_source.get("skills") or []
        cur_skill_names = {s.get("name", "") for s in cur_skills if isinstance(s, dict)}
        prev_skill_names = {s.get("name", "") for s in prev_skills if isinstance(s, dict)}
        skills_added_count = len(cur_skill_names - prev_skill_names)
        skills_removed_count = len(prev_skill_names - cur_skill_names)

        for target in targets:
            # Determine which sections this target cannot support
            unsupported: list[str] = []
            for feat in ALL_FEATURES:
                level = matrix.query_harness(target).get(feat, "unsupported")
                if level == "unsupported":
                    unsupported.append(feat)

            # MCP is blocked on some harnesses (aider)
            target_mcp_added = mcp_added if "mcp" not in unsupported else []
            target_mcp_removed = mcp_removed if "mcp" not in unsupported else []

            # Build human summary line
            parts: list[str] = []
            if new_rule_lines:
                parts.append(f"+{new_rule_lines} rule line(s)")
            if removed_rule_lines:
                parts.append(f"-{removed_rule_lines} rule line(s)")
            if target_mcp_added:
                parts.append(f"+{len(target_mcp_added)} MCP server(s) ({', '.join(target_mcp_added[:2])}{'…' if len(target_mcp_added) > 2 else ''})")
            if target_mcp_removed:
                parts.append(f"-{len(target_mcp_removed)} MCP server(s)")
            if skills_added_count:
                parts.append(f"+{skills_added_count} skill(s)")
            if skills_removed_count:
                parts.append(f"-{skills_removed_count} skill(s)")
            if unsupported:
                parts.append(f"{len(unsupported)} section(s) skipped (unsupported)")

            summary = ", ".join(parts) if parts else "no changes"

            previews[target] = {
                "rules_added":          new_rule_lines,
                "rules_removed":        removed_rule_lines,
                "mcp_added":            target_mcp_added,
                "mcp_removed":          target_mcp_removed,
                "skills_added":         skills_added_count,
                "skills_removed":       skills_removed_count,
                "unsupported_sections": unsupported,
                "summary":              summary,
            }

        return previews

    def format_capability_preview(
        self,
        previews: dict[str, dict],
    ) -> str:
        """Format the output of :meth:`build_capability_preview` for terminal display.

        Args:
            previews: Dict returned by :meth:`build_capability_preview`.

        Returns:
            Multi-line human-readable preview string.
        """
        if not previews:
            return "No targets to preview."

        lines = ["Pre-Sync Capability Preview", "=" * 55, ""]
        for target, info in sorted(previews.items()):
            lines.append(f"  {target:<14} {info['summary']}")

        lines.append("")
        lines.append("Run /sync to apply these changes.")
        return "\n".join(lines)
