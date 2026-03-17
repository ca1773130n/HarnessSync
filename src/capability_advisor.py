from __future__ import annotations

"""Harness Capability Advisor — warns which harnesses can't honor new rules or skills.

When a user writes a new Claude Code rule or skill, this module analyzes it
and surfaces per-harness warnings so silent degradation never catches them
off-guard.

Example warnings:
  - "This MCP server config will be ignored by Aider — it has no MCP support."
  - "Skills are approximated in Codex — folded into the rules file."
  - "Env-var references in this rule will not be substituted in Windsurf."

The advisor is intentionally lightweight: it relies on the static data in
``capability_matrix.py`` and the ``feature_gap_issue_creator.py`` workaround
database rather than running any external processes.

Usage::

    advisor = CapabilityAdvisor()

    # Analyze a rule snippet:
    warnings = advisor.analyze_rule("Always use the 'context7' MCP server for docs.")
    for w in warnings:
        print(f"  [{w.harness}] {w.message}")

    # Analyze a skill directory's SKILL.md content:
    warnings = advisor.analyze_skill(skill_content, skill_name="commit")

    # Analyze full source_data from SourceReader:
    report = advisor.analyze_source_data(source_data)
    print(report.format())
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.constants import EXTENDED_TARGETS

# ---------------------------------------------------------------------------
# Harness capability maps (mirrors capability_matrix constants)
# ---------------------------------------------------------------------------

_MCP_CAPABLE: set[str] = {
    "codex", "gemini", "opencode", "cursor", "windsurf", "cline", "continue", "zed"
}
_MCP_NONE: set[str] = {"aider", "neovim"}

_SKILLS_CAPABLE: set[str] = {
    "codex", "gemini", "opencode", "cursor", "windsurf", "cline", "continue", "zed", "neovim"
}
_SKILLS_APPROX: set[str] = {"codex", "cursor"}  # folded into rules

_AGENTS_CAPABLE: set[str] = {"codex", "gemini", "opencode", "cursor", "cline"}

_COMMANDS_CAPABLE: set[str] = {
    "codex", "gemini", "opencode", "cursor", "windsurf", "cline", "continue"
}

_ENV_VAR_CAPABLE: set[str] = {
    "codex", "gemini", "opencode", "cursor", "aider", "windsurf", "cline"
}

# Patterns that signal MCP usage in a rule or skill body
_MCP_REF_RE = re.compile(
    r"\b(mcp|model context protocol|mcp server|mcp tool|use mcp|call mcp)\b",
    re.IGNORECASE,
)

# Patterns that signal skill invocation references
_SKILL_INVOKE_RE = re.compile(
    r"\b(invoke skill|use skill|skill:)\s*[\"']?(\w[\w-]*)[\"']?",
    re.IGNORECASE,
)

# Patterns that signal env-var usage
_ENV_VAR_RE = re.compile(r"\$\{?[A-Z][A-Z0-9_]{2,}\}?")

# Patterns that signal permission requirements
_PERMISSION_RE = re.compile(
    r"\b(bash|shell|exec|run command|file write|file delete)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CapabilityWarning:
    """A single harness-specific capability warning."""

    harness: str
    feature: str       # "mcp" | "skills" | "agents" | "commands" | "env_vars" | "permissions"
    severity: str      # "error" | "warning" | "info"
    message: str
    suggestion: str = ""


@dataclass
class AdvisorReport:
    """Full advisor report for a rule, skill, or complete source config."""

    source_label: str
    warnings: list[CapabilityWarning] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return bool(self.warnings)

    @property
    def error_count(self) -> int:
        return sum(1 for w in self.warnings if w.severity == "error")

    def format(self) -> str:
        """Render the report as a human-readable string."""
        if not self.warnings:
            return (
                f"Capability Advisor ({self.source_label}): "
                "No compatibility issues detected — all harnesses should honor this config."
            )

        lines = [
            f"Capability Advisor — {self.source_label}",
            "=" * 55,
            f"Found {len(self.warnings)} compatibility issue(s):",
            "",
        ]
        by_harness: dict[str, list[CapabilityWarning]] = {}
        for w in self.warnings:
            by_harness.setdefault(w.harness, []).append(w)

        for harness in sorted(by_harness):
            ws = by_harness[harness]
            lines.append(f"  [{harness.upper()}]")
            for w in ws:
                icon = {"error": "✗", "warning": "⚠", "info": "·"}.get(w.severity, "·")
                lines.append(f"    {icon} {w.message}")
                if w.suggestion:
                    lines.append(f"      → {w.suggestion}")
            lines.append("")

        lines.append(
            "Run /sync-compare for the full capability matrix across all harnesses."
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Advisor
# ---------------------------------------------------------------------------

class CapabilityAdvisor:
    """Analyze Claude Code config for harness-specific compatibility issues.

    Args:
        targets: Harnesses to check (default: all EXTENDED_TARGETS).
    """

    def __init__(self, targets: list[str] | None = None) -> None:
        self.targets = list(targets or EXTENDED_TARGETS)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def analyze_rule(self, rule_text: str, rule_name: str = "rule") -> list[CapabilityWarning]:
        """Analyze a single rule snippet for harness incompatibilities.

        Args:
            rule_text: The raw rule text (Markdown or plain text).
            rule_name: Label for the rule (used in messages).

        Returns:
            List of CapabilityWarning for every incompatibility found.
        """
        warnings: list[CapabilityWarning] = []
        warnings.extend(self._check_mcp_references(rule_text, rule_name))
        warnings.extend(self._check_env_var_references(rule_text, rule_name))
        warnings.extend(self._check_permission_references(rule_text, rule_name))
        return warnings

    def analyze_skill(
        self,
        skill_content: str,
        skill_name: str = "skill",
    ) -> list[CapabilityWarning]:
        """Analyze a SKILL.md body for harness incompatibilities.

        Args:
            skill_content: Full content of the SKILL.md file.
            skill_name:    Name of the skill (directory name).

        Returns:
            List of CapabilityWarning.
        """
        warnings: list[CapabilityWarning] = []

        # Harnesses with no skill support
        for target in self.targets:
            if target not in _SKILLS_CAPABLE:
                warnings.append(CapabilityWarning(
                    harness=target,
                    feature="skills",
                    severity="error",
                    message=f"Skill '{skill_name}' will NOT be synced — {target} has no skill support.",
                    suggestion="The skill content can be folded into CLAUDE.md rules manually.",
                ))
            elif target in _SKILLS_APPROX:
                warnings.append(CapabilityWarning(
                    harness=target,
                    feature="skills",
                    severity="warning",
                    message=(
                        f"Skill '{skill_name}' is approximated in {target} — "
                        "it will be appended to the rules file, not loaded as a named skill."
                    ),
                    suggestion="Test that the appended skill works as expected in " + target + ".",
                ))

        # Check for MCP references inside the skill body
        warnings.extend(self._check_mcp_references(skill_content, f"skill '{skill_name}'"))
        warnings.extend(self._check_env_var_references(skill_content, f"skill '{skill_name}'"))
        return warnings

    def analyze_mcp_server(
        self,
        server_name: str,
        server_config: dict,
    ) -> list[CapabilityWarning]:
        """Analyze a single MCP server config for harness incompatibilities.

        Args:
            server_name:   Name of the MCP server (e.g. "context7").
            server_config: The server config dict (command/url/env/etc.).

        Returns:
            List of CapabilityWarning.
        """
        warnings: list[CapabilityWarning] = []
        transport = server_config.get("transport", "stdio")
        url = server_config.get("url", "")

        for target in self.targets:
            if target in _MCP_NONE:
                warnings.append(CapabilityWarning(
                    harness=target,
                    feature="mcp",
                    severity="error",
                    message=(
                        f"MCP server '{server_name}' will be IGNORED by {target} — "
                        "it has no MCP support."
                    ),
                    suggestion=(
                        f"Add a workaround rule in CLAUDE.md scoped to {target}: "
                        f"<!-- harness:{target} --> that mentions the tool's purpose."
                    ),
                ))
            elif target not in _MCP_CAPABLE:
                warnings.append(CapabilityWarning(
                    harness=target,
                    feature="mcp",
                    severity="warning",
                    message=f"MCP support for '{server_name}' in {target} is partial.",
                    suggestion="Run /sync-compare --category mcp for the full matrix.",
                ))

        # SSE transport only works in harnesses that support it
        if transport == "sse" or (url and url.startswith("http")):
            sse_limited = {"aider", "neovim", "continue"}
            for target in self.targets:
                if target in sse_limited:
                    warnings.append(CapabilityWarning(
                        harness=target,
                        feature="mcp",
                        severity="warning",
                        message=(
                            f"MCP server '{server_name}' uses SSE/HTTP transport — "
                            f"{target} may not support it."
                        ),
                        suggestion="Check that " + target + " can connect to HTTP-based MCP servers.",
                    ))
        return warnings

    def analyze_source_data(self, source_data: dict) -> AdvisorReport:
        """Analyze full SourceReader output for all harness incompatibilities.

        Args:
            source_data: Dict returned by SourceReader.discover_all().

        Returns:
            AdvisorReport aggregating all warnings.
        """
        all_warnings: list[CapabilityWarning] = []

        # MCP servers
        mcp_servers: dict = source_data.get("mcp_servers", {})
        for name, config in mcp_servers.items():
            cfg = config if isinstance(config, dict) else {}
            all_warnings.extend(self.analyze_mcp_server(name, cfg))

        # Skills
        skills: dict = source_data.get("skills", {})
        for skill_name, skill_data in skills.items():
            content = ""
            if isinstance(skill_data, dict):
                content = skill_data.get("content", "") or skill_data.get("description", "")
            elif isinstance(skill_data, str):
                content = skill_data
            all_warnings.extend(self.analyze_skill(content, skill_name))

        # Rules — check for MCP/env-var references
        rules: dict = source_data.get("rules", {})
        for rule_path, rule_text in rules.items():
            if isinstance(rule_text, str) and rule_text.strip():
                label = Path(rule_path).name if rule_path else "rules"
                all_warnings.extend(self.analyze_rule(rule_text, label))

        # Agents
        agents: dict = source_data.get("agents", {})
        if agents:
            for target in self.targets:
                if target not in _AGENTS_CAPABLE:
                    all_warnings.append(CapabilityWarning(
                        harness=target,
                        feature="agents",
                        severity="warning",
                        message=(
                            f"{len(agents)} agent(s) will not be synced to {target} — "
                            "it has no agent support."
                        ),
                        suggestion="Summarize agent roles in CLAUDE.md rules for " + target + ".",
                    ))

        # Commands
        commands: dict = source_data.get("commands", {})
        if commands:
            for target in self.targets:
                if target not in _COMMANDS_CAPABLE:
                    all_warnings.append(CapabilityWarning(
                        harness=target,
                        feature="commands",
                        severity="warning",
                        message=(
                            f"{len(commands)} command(s) will not be synced to {target} — "
                            "no slash-command support."
                        ),
                        suggestion="Commands are silently skipped; consider noting key commands in rules.",
                    ))

        return AdvisorReport(source_label="full config", warnings=all_warnings)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _check_mcp_references(
        self, text: str, label: str
    ) -> list[CapabilityWarning]:
        warnings: list[CapabilityWarning] = []
        if _MCP_REF_RE.search(text):
            for target in self.targets:
                if target in _MCP_NONE:
                    warnings.append(CapabilityWarning(
                        harness=target,
                        feature="mcp",
                        severity="warning",
                        message=(
                            f"{label} references MCP but {target} has no MCP support — "
                            "the rule may produce unexpected behavior."
                        ),
                        suggestion=(
                            f"Annotate the rule to exclude {target}: "
                            f"<!-- harness:!{target} -->"
                        ),
                    ))
        return warnings

    def _check_env_var_references(
        self, text: str, label: str
    ) -> list[CapabilityWarning]:
        warnings: list[CapabilityWarning] = []
        matches = _ENV_VAR_RE.findall(text)
        if matches:
            unique_vars = sorted(set(matches))
            for target in self.targets:
                if target not in _ENV_VAR_CAPABLE:
                    warnings.append(CapabilityWarning(
                        harness=target,
                        feature="env_vars",
                        severity="warning",
                        message=(
                            f"{label} uses env vars ({', '.join(unique_vars[:3])}) "
                            f"but {target} does not substitute them at runtime."
                        ),
                        suggestion=(
                            "Hardcode values for " + target
                            + " or annotate the section with "
                            f"<!-- harness:!{target} -->."
                        ),
                    ))
        return warnings

    def _check_permission_references(
        self, text: str, label: str
    ) -> list[CapabilityWarning]:
        warnings: list[CapabilityWarning] = []
        if _PERMISSION_RE.search(text):
            # Harnesses that run everything without a deny mechanism
            no_deny: set[str] = {"aider", "neovim", "continue"}
            for target in self.targets:
                if target in no_deny:
                    warnings.append(CapabilityWarning(
                        harness=target,
                        feature="permissions",
                        severity="info",
                        message=(
                            f"{label} mentions shell/file operations; {target} has no "
                            "deny-list mechanism so permissions cannot be restricted."
                        ),
                        suggestion=(
                            "Review whether unrestricted tool access is acceptable in " + target + "."
                        ),
                    ))
        return warnings


def analyze_new_content(
    content: str,
    content_type: str = "rule",
    name: str = "",
    targets: list[str] | None = None,
) -> str:
    """Convenience function: analyze new rule/skill content and return formatted report.

    Args:
        content:      The raw text of the rule or skill.
        content_type: "rule" | "skill" | "mcp".
        name:         Human-readable name for the item.
        targets:      Harnesses to check (default: all).

    Returns:
        Formatted advisory string.
    """
    advisor = CapabilityAdvisor(targets=targets)
    label = name or content_type

    if content_type == "skill":
        warnings = advisor.analyze_skill(content, label)
    else:
        warnings = advisor.analyze_rule(content, label)

    report = AdvisorReport(source_label=label, warnings=warnings)
    return report.format()
