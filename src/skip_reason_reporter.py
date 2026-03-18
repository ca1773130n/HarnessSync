from __future__ import annotations

"""Explains why config items were skipped during sync (item 20).

For every setting, MCP server, skill, or rule that a target harness cannot
accept, SkipReasonReporter produces a clear human-readable explanation so
users know what they are giving up — and why — rather than having items
silently disappear.

Usage::

    reporter = SkipReasonReporter()
    reasons = reporter.explain_all(target="aider", source_data=source)
    print(reporter.format_report("aider", reasons))

Or to annotate an existing SyncResult::

    reasons = reporter.explain_skipped_files(target, section, skipped_files)
"""

from dataclasses import dataclass, field
from pathlib import Path

from src.utils.constants import CORE_TARGETS


@dataclass
class SkipReason:
    """A single skip explanation for one config item."""

    target: str
    section: str       # "rules" | "skills" | "mcp" | "agents" | "commands" | "settings"
    item_name: str     # human-readable name of the skipped item
    reason: str        # human-readable explanation
    severity: str = "info"   # "info" | "warning"
    suggestion: str = ""     # optional actionable hint


@dataclass
class SkipReport:
    """Aggregated skip explanations for one target."""

    target: str
    reasons: list[SkipReason] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.reasons

    @property
    def warning_count(self) -> int:
        return sum(1 for r in self.reasons if r.severity == "warning")

    def format(self) -> str:
        """Return a human-readable report of all skip reasons for this target.

        Returns:
            Multi-line string describing every skipped item and why.
        """
        if self.is_empty:
            return f"{self.target.title()}: All supported items synced — nothing skipped."

        lines = [f"Skipped settings for {self.target.title()}:", ""]
        by_section: dict[str, list[SkipReason]] = {}
        for r in self.reasons:
            by_section.setdefault(r.section, []).append(r)

        for section in ("rules", "skills", "agents", "commands", "mcp", "settings"):
            items = by_section.get(section, [])
            if not items:
                continue
            label = _SECTION_LABEL[section]
            lines.append(f"  [{label.upper()}]")
            for r in items:
                icon = "!" if r.severity == "warning" else "-"
                lines.append(f"    {icon} {r.item_name}")
                lines.append(f"      Why: {r.reason}")
                if r.suggestion:
                    lines.append(f"      Fix: {r.suggestion}")
            lines.append("")

        total = len(self.reasons)
        warnings = self.warning_count
        lines.append(
            f"  Total: {total} item(s) skipped"
            + (f", {warnings} warning(s)" if warnings else "")
        )
        return "\n".join(lines)


_SECTION_LABEL: dict[str, str] = {
    "rules":    "rules",
    "skills":   "skills",
    "agents":   "agents",
    "commands": "commands",
    "mcp":      "MCP servers",
    "settings": "settings",
}

# --- Per-target capability definitions -----------------------------------
# Maps (target, section) -> human-readable reason for the skip.
# None means the section is fully supported.

_SKIP_REASONS: dict[str, dict[str, str | None]] = {
    "codex": {
        "rules":    None,
        "skills":   None,
        "agents":   None,
        "commands": None,
        "mcp":      None,
        "settings": None,
    },
    "gemini": {
        "rules":    None,
        "skills":   None,
        "agents":   None,
        "commands": None,
        "mcp":      None,
        "settings": None,
    },
    "opencode": {
        "rules":    None,
        "skills":   None,
        "agents":   None,
        "commands": None,
        "mcp":      None,
        "settings": None,
    },
    "cursor": {
        "rules":    None,
        "skills":   None,
        "agents":   None,
        "commands": None,
        "mcp":      None,
        "settings": None,
    },
    "aider": {
        "rules":    None,
        "skills":   "Aider does not have a native skill/tool system; skills are omitted.",
        "agents":   "Aider does not support agent definitions; agent configs are omitted.",
        "commands": "Aider does not support slash-command definitions; commands are omitted.",
        "mcp":      "Aider does not support MCP server configurations; MCP entries are omitted.",
        "settings": None,
    },
    "windsurf": {
        "rules":    None,
        "skills":   "Windsurf does not support native skills; skills are omitted.",
        "agents":   "Windsurf does not support agent definitions; agents are omitted.",
        "commands": "Windsurf does not support slash-command definitions; commands are omitted.",
        "mcp":      None,
        "settings": None,
    },
    "cline": {
        "rules":    None,
        "skills":   "Cline does not have a native skill system; skills are omitted.",
        "agents":   "Cline does not support agent config files; agents are omitted.",
        "commands": "Cline does not support slash commands in the HarnessSync format.",
        "mcp":      None,
        "settings": None,
    },
    "continue": {
        "rules":    None,
        "skills":   "Continue does not support skills in the Claude Code format.",
        "agents":   "Continue does not support agent definitions.",
        "commands": "Continue does not support slash-command definitions.",
        "mcp":      None,
        "settings": None,
    },
    "zed": {
        "rules":    None,
        "skills":   "Zed does not support skills.",
        "agents":   "Zed does not support agent definitions.",
        "commands": "Zed does not support slash-command definitions.",
        "mcp":      "Zed uses a different extension model; MCP servers are not synced.",
        "settings": None,
    },
    "neovim": {
        "rules":    None,
        "skills":   "Neovim does not support skills.",
        "agents":   "Neovim does not support agent definitions.",
        "commands": "Neovim does not support slash-command definitions.",
        "mcp":      "Neovim uses a plugin model; MCP servers are not synced.",
        "settings": None,
    },
}

# Suggestions to show alongside unsupported sections
_SKIP_SUGGESTIONS: dict[str, dict[str, str]] = {
    "aider": {
        "skills":   "Consider adding key skill instructions inline in your rules for Aider.",
        "agents":   "Add agent-like instructions to CONVENTIONS.md via an Aider rule.",
        "commands": "Use Aider's --cmd flag or aliases for frequently-used commands.",
        "mcp":      "Run MCP tools manually; Aider cannot auto-discover them.",
    },
    "windsurf": {
        "skills":   "Add skill logic as markdown instructions in .windsurfrules.",
        "agents":   "Windsurf does not support agent configs; use rule-based instructions.",
        "commands": "Windsurf does not have a slash-command system.",
    },
    "zed": {
        "mcp":   "Configure Zed extensions separately via the Zed Extension Registry.",
    },
}

# MCP-specific capability notes per target
_MCP_TRANSPORT_RESTRICTIONS: dict[str, str] = {
    "aider":   "Aider does not support MCP; all MCP servers are skipped.",
    "windsurf": "Windsurf supports MCP via its own configuration file (.windsurf/mcp.json).",
    "cline":   "Cline supports MCP but only via stdio transport; SSE servers are skipped.",
    "zed":     "Zed does not support MCP server configs in the HarnessSync format.",
    "neovim":  "Neovim does not support MCP server configs in the HarnessSync format.",
}


class SkipReasonReporter:
    """Reports why config items were skipped during sync.

    Args:
        targets: Harness targets to consider (default: all known targets).
    """

    def __init__(self, targets: list[str] | None = None) -> None:
        self._targets = list(targets or _SKIP_REASONS.keys())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def explain_section(self, target: str, section: str) -> str | None:
        """Return a reason string if *section* is unsupported by *target*.

        Args:
            target: Harness name (e.g. "aider").
            section: Config section name (e.g. "mcp").

        Returns:
            Reason string if the section is skipped, None if fully supported.
        """
        reasons = _SKIP_REASONS.get(target, {})
        return reasons.get(section)

    def explain_mcp_server(self, target: str, server_name: str, transport: str = "stdio") -> str | None:
        """Return a skip reason for a specific MCP server on *target*.

        Args:
            target: Harness name.
            server_name: MCP server key from mcp_servers config.
            transport: Transport type ("stdio" | "sse").

        Returns:
            Skip reason string or None if the server is supported.
        """
        # Check if the entire MCP section is unsupported
        section_reason = self.explain_section(target, "mcp")
        if section_reason:
            return section_reason

        # SSE transport restriction
        if transport == "sse" and target in ("cline",):
            return (
                f"{target.title()} only supports stdio transport; "
                f"SSE-based MCP server '{server_name}' will be skipped."
            )
        return None

    def explain_all(self, target: str, source_data: dict) -> SkipReport:
        """Generate a SkipReport for all sections given the current source data.

        Args:
            target: Harness name.
            source_data: Output of SourceReader.discover_all().

        Returns:
            SkipReport with reasons for every skipped item.
        """
        report = SkipReport(target=target)

        for section in ("rules", "skills", "agents", "commands", "mcp", "settings"):
            reason = self.explain_section(target, section)
            if reason is None:
                continue  # Section is supported

            section_data = source_data.get(section)
            if not section_data:
                continue  # Nothing to skip

            suggestion = _SKIP_SUGGESTIONS.get(target, {}).get(section, "")
            count = _count_section(section, section_data)
            noun = _pluralise_section(section, count)

            report.reasons.append(SkipReason(
                target=target,
                section=section,
                item_name=f"{count} {noun}",
                reason=reason,
                severity="warning" if count > 0 else "info",
                suggestion=suggestion,
            ))

        # MCP server-level detail
        mcp_data = source_data.get("mcp") or source_data.get("mcp_servers") or {}
        if isinstance(mcp_data, dict):
            mcp_reason = _MCP_TRANSPORT_RESTRICTIONS.get(target)
            if not mcp_reason:
                # Per-server transport check
                for server_name, server_cfg in mcp_data.items():
                    transport = "stdio"
                    if isinstance(server_cfg, dict):
                        transport = server_cfg.get("transport", "stdio")
                    detail = self.explain_mcp_server(target, server_name, transport)
                    if detail:
                        report.reasons.append(SkipReason(
                            target=target,
                            section="mcp",
                            item_name=f"MCP server '{server_name}'",
                            reason=detail,
                            severity="warning",
                        ))

        return report

    def explain_all_targets(self, source_data: dict) -> dict[str, SkipReport]:
        """Generate SkipReports for every configured target.

        Args:
            source_data: Output of SourceReader.discover_all().

        Returns:
            Mapping target -> SkipReport.
        """
        return {t: self.explain_all(t, source_data) for t in self._targets}

    def format_summary(self, reports: dict[str, SkipReport]) -> str:
        """Format all SkipReports as a compact multi-target summary.

        Args:
            reports: Mapping from target name -> SkipReport.

        Returns:
            Multi-line string. Targets with no skips are omitted.
        """
        lines = ["Skipped Settings Explanation", "=" * 50, ""]
        any_skips = False
        for target in sorted(reports):
            report = reports[target]
            if report.is_empty:
                continue
            any_skips = True
            lines.append(report.format())
            lines.append("")

        if not any_skips:
            return "All settings synced cleanly to all targets — nothing skipped."

        total_warnings = sum(r.warning_count for r in reports.values())
        if total_warnings:
            lines.append(
                f"Note: {total_warnings} item(s) marked as warnings because they "
                "carry significant functionality that won't reach those targets."
            )
        return "\n".join(lines)


# --- helpers ---

def _count_section(section: str, data: object) -> int:
    """Return the number of items in *data* for *section*."""
    if data is None:
        return 0
    if isinstance(data, dict):
        return len(data)
    if isinstance(data, list):
        return len(data)
    if isinstance(data, str):
        return 1 if data.strip() else 0
    return 1


def _pluralise_section(section: str, count: int) -> str:
    labels = {
        "rules":    ("rule", "rules"),
        "skills":   ("skill", "skills"),
        "agents":   ("agent", "agents"),
        "commands": ("command", "commands"),
        "mcp":      ("MCP server", "MCP servers"),
        "settings": ("setting", "settings"),
    }
    singular, plural = labels.get(section, (section, section + "s"))
    return singular if count == 1 else plural
