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
    ],
}

# MCP server tool name patterns for impact estimation
_MCP_TOOL_PATTERNS: dict[str, list[str]] = {
    "filesystem": ["read_file", "write_file", "list_directory", "search_files"],
    "github": ["get_repo", "list_prs", "create_issue", "merge_pr"],
    "postgres": ["query", "list_tables", "describe_table", "execute"],
    "sqlite": ["query", "insert", "list_tables"],
    "memory": ["store", "recall", "list_memories"],
    "fetch": ["fetch_url", "get_page"],
    "puppeteer": ["navigate", "screenshot", "click", "type"],
    "git": ["log", "diff", "status", "commit"],
    "brave-search": ["web_search", "local_search"],
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

    def format(self) -> str:
        """Format the impact report for terminal display."""
        if self.is_empty:
            return "Sync Impact: No significant changes predicted."

        lines = ["Sync Impact Prediction", "=" * 50, ""]

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

        return report

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
