from __future__ import annotations

"""Pre-Sync Impact Summary — plain-English description of what will change.

Before any sync runs, PreSyncSummary computes a concise human-readable
description of the upcoming changes: how many settings are added, removed,
or modified per harness, and which harnesses are affected.

Unlike SyncImpactPredictor (which provides full per-item predictions),
PreSyncSummary focuses on a brief executive summary:

    "3 rules added to Codex • 1 MCP server added to Gemini and OpenCode
     • 2 skills removed from Aider"

Usage::

    from src.pre_sync_summary import PreSyncSummary
    summary = PreSyncSummary()
    text = summary.build(current_source, previous_source, targets=["codex", "gemini"])
    print(text)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.constants import CORE_TARGETS


@dataclass
class _TargetDelta:
    """Change counts for a single section within a single target."""
    added: int = 0
    removed: int = 0
    modified: int = 0


@dataclass
class SectionDelta:
    """Cross-target delta for one config section."""
    section: str
    added_targets: list[str] = field(default_factory=list)
    removed_targets: list[str] = field(default_factory=list)
    modified_targets: list[str] = field(default_factory=list)
    added_count: int = 0
    removed_count: int = 0

    @property
    def is_empty(self) -> bool:
        return not (self.added_targets or self.removed_targets or self.modified_targets)


@dataclass
class PreSyncSummaryReport:
    """Top-level summary of pending sync changes."""

    section_deltas: list[SectionDelta] = field(default_factory=list)
    targets_affected: list[str] = field(default_factory=list)
    total_added: int = 0
    total_removed: int = 0
    total_modified: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.targets_affected)

    def format_one_liner(self) -> str:
        """Return a single-line summary suitable for displaying before sync.

        Returns:
            A concise description like:
            "3 rules added to Codex and Gemini • 1 MCP server added (all targets)"
            or "No changes detected." if nothing will change.
        """
        if not self.has_changes:
            return "No changes detected — all targets are up to date."

        parts: list[str] = []
        for delta in self.section_deltas:
            if delta.is_empty:
                continue
            label = _SECTION_LABELS.get(delta.section, delta.section)
            if delta.added_targets:
                targets_str = _format_targets(delta.added_targets)
                noun = _pluralise(label, delta.added_count)
                parts.append(f"{delta.added_count} {noun} added to {targets_str}")
            if delta.removed_targets:
                targets_str = _format_targets(delta.removed_targets)
                noun = _pluralise(label, delta.removed_count)
                parts.append(f"{delta.removed_count} {noun} removed from {targets_str}")
            if delta.modified_targets and not delta.added_targets and not delta.removed_targets:
                targets_str = _format_targets(delta.modified_targets)
                parts.append(f"{label} updated in {targets_str}")

        if not parts:
            return "Minor changes detected — run /sync to apply."
        return " • ".join(parts)

    def format_full(self) -> str:
        """Return a multi-line detailed summary.

        Returns:
            Formatted string listing all changes per section.
        """
        if not self.has_changes:
            return "Pre-Sync Summary: No changes detected."

        lines = ["Pre-Sync Summary", "=" * 50]
        for delta in self.section_deltas:
            if delta.is_empty:
                continue
            label = _SECTION_LABELS.get(delta.section, delta.section).title()
            lines.append(f"\n  {label}:")
            if delta.added_targets:
                targets_str = ", ".join(delta.added_targets)
                noun = _pluralise(_SECTION_LABELS.get(delta.section, delta.section), delta.added_count)
                lines.append(f"    + {delta.added_count} {noun} added → {targets_str}")
            if delta.removed_targets:
                targets_str = ", ".join(delta.removed_targets)
                noun = _pluralise(_SECTION_LABELS.get(delta.section, delta.section), delta.removed_count)
                lines.append(f"    - {delta.removed_count} {noun} removed from {targets_str}")
            if delta.modified_targets and not delta.added_targets and not delta.removed_targets:
                targets_str = ", ".join(delta.modified_targets)
                lines.append(f"    ~ content updated → {targets_str}")

        lines.append("")
        lines.append(f"  Targets affected: {', '.join(self.targets_affected) or 'none'}")
        return "\n".join(lines)


# Human-readable section labels
_SECTION_LABELS: dict[str, str] = {
    "rules": "rule",
    "skills": "skill",
    "agents": "agent",
    "commands": "command",
    "mcp": "MCP server",
    "settings": "setting",
}

# Per-target section support — determines which targets receive each section
_TARGET_SECTION_SUPPORT: dict[str, frozenset[str]] = {
    "codex":     frozenset({"rules", "skills", "agents", "commands", "mcp", "settings"}),
    "gemini":    frozenset({"rules", "skills", "agents", "commands", "mcp", "settings"}),
    "opencode":  frozenset({"rules", "skills", "agents", "commands", "mcp", "settings"}),
    "cursor":    frozenset({"rules", "skills", "agents", "commands", "mcp", "settings"}),
    "aider":     frozenset({"rules", "settings"}),
    "windsurf":  frozenset({"rules", "mcp", "settings"}),
    "cline":     frozenset({"rules", "mcp", "settings"}),
    "continue":  frozenset({"rules", "mcp", "settings"}),
    "zed":       frozenset({"rules", "settings"}),
    "neovim":    frozenset({"rules", "settings"}),
}


def _pluralise(noun: str, count: int) -> str:
    """Return noun with appropriate plural suffix."""
    if count == 1:
        return noun
    # Simple English pluralisation: "MCP server" → "MCP servers"
    return noun + "s"


def _format_targets(targets: list[str]) -> str:
    """Format a target list for display.

    Returns:
        "all targets" | "Codex" | "Codex and Gemini" | "Codex, Gemini, and OpenCode"
    """
    if not targets:
        return "no targets"
    known = set(CORE_TARGETS)
    if set(targets) >= known:
        return "all targets"
    titled = [t.title() for t in targets]
    if len(titled) == 1:
        return titled[0]
    if len(titled) == 2:
        return f"{titled[0]} and {titled[1]}"
    return ", ".join(titled[:-1]) + f", and {titled[-1]}"


def _count_rules(source_data: dict) -> int:
    """Count rule lines or blocks in source data."""
    rules = source_data.get("rules", "")
    if not rules:
        return 0
    if isinstance(rules, list):
        return len(rules)
    return len([l for l in str(rules).splitlines() if l.strip() and not l.startswith("#")])


def _count_mcp(source_data: dict) -> int:
    """Count MCP servers in source data."""
    mcp = source_data.get("mcp", {}) or source_data.get("mcp_servers", {})
    if isinstance(mcp, dict):
        return len(mcp)
    return 0


def _count_skills(source_data: dict) -> int:
    skills = source_data.get("skills", {})
    if isinstance(skills, dict):
        return len(skills)
    return 0


def _count_agents(source_data: dict) -> int:
    agents = source_data.get("agents", [])
    if isinstance(agents, list):
        return len(agents)
    return 0


def _count_commands(source_data: dict) -> int:
    commands = source_data.get("commands", [])
    if isinstance(commands, list):
        return len(commands)
    return 0


_SECTION_COUNTERS = {
    "rules":    _count_rules,
    "mcp":      _count_mcp,
    "skills":   _count_skills,
    "agents":   _count_agents,
    "commands": _count_commands,
}


class PreSyncSummary:
    """Generates a plain-English summary of what will change in the next sync.

    Args:
        targets: Harness targets to consider (default: CORE_TARGETS).
    """

    def __init__(self, targets: list[str] | None = None) -> None:
        self._targets = list(targets or CORE_TARGETS)

    def build(
        self,
        current_source: dict,
        previous_source: dict | None = None,
        targets: list[str] | None = None,
    ) -> PreSyncSummaryReport:
        """Compute the pending sync delta and return a summary report.

        Args:
            current_source: SourceReader.discover_all() output for current state.
            previous_source: Source data from last sync (None = first sync).
            targets: Override the instance-level target list.

        Returns:
            PreSyncSummaryReport with structured change information.
        """
        targets = targets or self._targets
        previous_source = previous_source or {}

        section_deltas: list[SectionDelta] = []
        affected: set[str] = set()

        for section, counter in _SECTION_COUNTERS.items():
            cur_count = counter(current_source)
            prev_count = counter(previous_source)

            cur_content = _section_content(current_source, section)
            prev_content = _section_content(previous_source, section)

            if cur_content == prev_content:
                continue  # No change for this section

            delta = SectionDelta(section=section)

            if cur_count > prev_count:
                delta.added_count = cur_count - prev_count
            elif cur_count < prev_count:
                delta.removed_count = prev_count - cur_count

            # Determine which targets are affected
            for target in targets:
                support = _TARGET_SECTION_SUPPORT.get(target, frozenset())
                if section not in support:
                    continue
                affected.add(target)
                if delta.added_count > 0:
                    delta.added_targets.append(target)
                elif delta.removed_count > 0:
                    delta.removed_targets.append(target)
                else:
                    delta.modified_targets.append(target)

            section_deltas.append(delta)

        report = PreSyncSummaryReport(
            section_deltas=section_deltas,
            targets_affected=sorted(affected),
            total_added=sum(d.added_count for d in section_deltas),
            total_removed=sum(d.removed_count for d in section_deltas),
        )
        return report

    def one_liner(
        self,
        current_source: dict,
        previous_source: dict | None = None,
        targets: list[str] | None = None,
    ) -> str:
        """Convenience wrapper that returns the one-line summary string.

        Args:
            current_source: Current source data.
            previous_source: Previous source data (None = first sync).
            targets: Targets to consider.

        Returns:
            Human-readable one-line summary.
        """
        return self.build(current_source, previous_source, targets).format_one_liner()


def _section_content(source: dict, section: str) -> object:
    """Extract the relevant content for *section* from source data dict."""
    if section == "rules":
        return source.get("rules") or source.get("rules_content", "")
    if section == "mcp":
        return source.get("mcp") or source.get("mcp_servers") or {}
    if section == "settings":
        return source.get("settings") or {}
    return source.get(section)
