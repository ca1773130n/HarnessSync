from __future__ import annotations

"""Permission model semantic translator (item 19).

Intelligently maps Claude Code's tool allowlists and permission settings to
the closest equivalent in each target harness. For settings that have no
native equivalent, generates explanatory comment blocks to preserve the
permission intent as documentation rather than silently dropping it.

Claude Code permission model:
    settings.json {
        "allowedTools": ["Bash", "Read", "Write", ...],
        "deniedTools":  ["WebSearch", ...],
        "permissions":  {"allow": [...], "deny": [...]},
        "approvalMode": "auto" | "suggest" | "manual"
    }

Target mappings:
  Codex:    allowedCommands / deniedCommands (shell-only; no MCP tool refs)
  Gemini:   tools.allowed / tools.exclude (glob patterns)
  OpenCode: per-tool enable/disable in opencode.json
  Cursor:   .cursor/rules/*.mdc comment block (no native permission system)
  Aider:    CONVENTIONS.md comment block (no native permission system)
  Windsurf: .windsurfrules comment block (no native permission system)
"""

from dataclasses import dataclass, field
from pathlib import Path


# Tools that are shell-executable and can be passed to Codex allowedCommands
_SHELL_EXECUTABLE_TOOLS = frozenset({
    "Bash", "bash", "sh",
    "Read", "Write", "Edit", "Glob", "Grep", "LS",
})

# Claude Code MCP tool prefixes — these can't be mapped to shell commands
_MCP_TOOL_PREFIX = "mcp__"

# Approval mode mappings per harness
_APPROVAL_MODE_MAP: dict[str, dict[str, str]] = {
    "codex": {
        "auto":     "full-auto",
        "suggest":  "on-request",
        "manual":   "on-request",
    },
    "gemini": {
        # Gemini has no approvalMode; yolo is never auto-enabled
        "auto":     "default",
        "suggest":  "default",
        "manual":   "default",
    },
    "opencode": {
        "auto":     "auto",
        "suggest":  "review",
        "manual":   "manual",
    },
}


@dataclass
class PermissionTranslation:
    """Result of translating a Claude Code permission setting for one target."""

    target: str
    setting: str                    # Claude Code setting name
    translated_key: str             # Target-specific key (or "" if comment-only)
    translated_value: object        # Target-specific value (or None)
    comment: str                    # Explanatory comment for gaps
    fidelity: str                   # "native" | "approximated" | "comment_only" | "dropped"
    dropped_items: list[str] = field(default_factory=list)  # Items that couldn't be mapped


@dataclass
class PermissionTranslationReport:
    """Aggregated translation results for all settings and targets."""

    translations: list[PermissionTranslation] = field(default_factory=list)

    def for_target(self, target: str) -> list[PermissionTranslation]:
        return [t for t in self.translations if t.target == target]

    def has_gaps(self, target: str) -> bool:
        return any(
            t.fidelity in ("comment_only", "dropped")
            for t in self.for_target(target)
        )

    def format_summary(self) -> str:
        """Return a human-readable summary of the translation results."""
        if not self.translations:
            return "No permission settings to translate."

        # Group by target
        targets: dict[str, list[PermissionTranslation]] = {}
        for t in self.translations:
            targets.setdefault(t.target, []).append(t)

        lines = ["Permission Model Translation Summary", "=" * 50, ""]
        for target, trans in sorted(targets.items()):
            lines.append(f"[{target.upper()}]")
            for t in trans:
                fidelity_icon = {
                    "native": "✓",
                    "approximated": "~",
                    "comment_only": "ℹ",
                    "dropped": "✗",
                }.get(t.fidelity, "?")
                lines.append(f"  {fidelity_icon} {t.setting}: {t.fidelity}")
                if t.comment:
                    lines.append(f"    {t.comment}")
                if t.dropped_items:
                    dropped_str = ", ".join(t.dropped_items[:3])
                    if len(t.dropped_items) > 3:
                        dropped_str += f" (+{len(t.dropped_items) - 3} more)"
                    lines.append(f"    Dropped: {dropped_str}")
            lines.append("")

        return "\n".join(lines)


class PermissionTranslator:
    """Translates Claude Code permission settings to target harness equivalents.

    For each target harness, maps tool allowlists/denylists and approval mode
    to the closest native equivalent. Where no native equivalent exists,
    generates a comment block preserving the intent for manual review.
    """

    def translate(
        self,
        settings: dict,
        targets: list[str],
    ) -> PermissionTranslationReport:
        """Translate all permission-related settings for the given targets.

        Args:
            settings: Claude Code settings dict (from settings.json).
            targets: List of target harness names.

        Returns:
            PermissionTranslationReport with per-target translations.
        """
        report = PermissionTranslationReport()

        allowed_tools: list[str] = settings.get("allowedTools") or []
        denied_tools: list[str] = settings.get("deniedTools") or []
        approval_mode: str = settings.get("approvalMode", "suggest")

        # Also read nested permissions dict format
        perms = settings.get("permissions", {})
        if isinstance(perms, dict):
            allowed_tools = allowed_tools or perms.get("allow", [])
            denied_tools = denied_tools or perms.get("deny", [])

        for target in targets:
            if allowed_tools:
                report.translations.append(
                    self._translate_allowed_tools(allowed_tools, target)
                )
            if denied_tools:
                report.translations.append(
                    self._translate_denied_tools(denied_tools, target)
                )
            if approval_mode:
                t = self._translate_approval_mode(approval_mode, target)
                if t:
                    report.translations.append(t)

        return report

    # ------------------------------------------------------------------
    # allowedTools
    # ------------------------------------------------------------------

    def _translate_allowed_tools(
        self, tools: list[str], target: str
    ) -> PermissionTranslation:
        if target == "codex":
            shell_tools = [t for t in tools if _is_shell_tool(t)]
            dropped = [t for t in tools if not _is_shell_tool(t)]
            return PermissionTranslation(
                target=target,
                setting="allowedTools",
                translated_key="allowedCommands",
                translated_value=shell_tools,
                comment=(
                    "MCP tool references and non-shell tools dropped (Codex only supports shell commands)"
                    if dropped else ""
                ),
                fidelity="approximated" if dropped else "native",
                dropped_items=dropped,
            )

        if target == "gemini":
            # Gemini uses glob patterns for tools.allowed
            gemini_patterns = [_tool_to_gemini_pattern(t) for t in tools]
            return PermissionTranslation(
                target=target,
                setting="allowedTools",
                translated_key="tools.allowed",
                translated_value=gemini_patterns,
                comment="Converted to Gemini glob patterns",
                fidelity="approximated",
            )

        if target == "opencode":
            return PermissionTranslation(
                target=target,
                setting="allowedTools",
                translated_key="permissions.allow",
                translated_value=tools,
                comment="",
                fidelity="native",
            )

        # Targets without native permission systems — generate comment block
        comment = (
            f"Claude Code allowedTools: {', '.join(tools[:5])}"
            + (f" (+{len(tools) - 5} more)" if len(tools) > 5 else "")
            + ". These tools are permitted in Claude Code but this harness has no native equivalent."
        )
        return PermissionTranslation(
            target=target,
            setting="allowedTools",
            translated_key="",
            translated_value=None,
            comment=comment,
            fidelity="comment_only",
            dropped_items=tools,
        )

    # ------------------------------------------------------------------
    # deniedTools
    # ------------------------------------------------------------------

    def _translate_denied_tools(
        self, tools: list[str], target: str
    ) -> PermissionTranslation:
        if target == "codex":
            shell_tools = [t for t in tools if _is_shell_tool(t)]
            dropped = [t for t in tools if not _is_shell_tool(t)]
            return PermissionTranslation(
                target=target,
                setting="deniedTools",
                translated_key="deniedCommands",
                translated_value=shell_tools,
                comment=(
                    "MCP tool refs dropped — Codex only supports shell command deny lists"
                    if dropped else ""
                ),
                fidelity="approximated" if dropped else "native",
                dropped_items=dropped,
            )

        if target == "gemini":
            gemini_patterns = [_tool_to_gemini_pattern(t) for t in tools]
            return PermissionTranslation(
                target=target,
                setting="deniedTools",
                translated_key="tools.exclude",
                translated_value=gemini_patterns,
                comment="Converted to Gemini glob patterns; enforcement depends on Gemini version",
                fidelity="approximated",
            )

        if target == "opencode":
            return PermissionTranslation(
                target=target,
                setting="deniedTools",
                translated_key="permissions.deny",
                translated_value=tools,
                comment="",
                fidelity="native",
            )

        # No native system — generate a comment block for manual reference
        tool_list = ", ".join(tools[:5])
        if len(tools) > 5:
            tool_list += f" (+{len(tools) - 5} more)"
        comment = (
            f"Claude Code deniedTools: {tool_list}. "
            "Add explicit 'Do not use <tool>' instructions to enforce this restriction."
        )
        return PermissionTranslation(
            target=target,
            setting="deniedTools",
            translated_key="",
            translated_value=None,
            comment=comment,
            fidelity="comment_only",
            dropped_items=tools,
        )

    # ------------------------------------------------------------------
    # approvalMode
    # ------------------------------------------------------------------

    def _translate_approval_mode(
        self, mode: str, target: str
    ) -> PermissionTranslation | None:
        target_map = _APPROVAL_MODE_MAP.get(target)
        if not target_map:
            return None  # No mapping known for this target

        mapped = target_map.get(mode)
        if not mapped or mapped == "default":
            return PermissionTranslation(
                target=target,
                setting="approvalMode",
                translated_key="",
                translated_value=None,
                comment=f"Claude Code approvalMode='{mode}' has no equivalent in {target}",
                fidelity="dropped",
            )

        key_map = {
            "codex":    "approval_policy",
            "opencode": "approvalMode",
        }
        key = key_map.get(target, "approvalMode")
        return PermissionTranslation(
            target=target,
            setting="approvalMode",
            translated_key=key,
            translated_value=mapped,
            comment="" if mapped else f"No equivalent for '{mode}' in {target}",
            fidelity="native" if mapped else "dropped",
        )

    def generate_comment_block(
        self,
        report: PermissionTranslationReport,
        target: str,
    ) -> str:
        """Generate a comment block summarizing permission gaps for a target.

        This block can be appended to the target's rules file to preserve
        the permission intent even when native enforcement isn't available.

        Args:
            report: Output of translate().
            target: Target harness to generate the comment for.

        Returns:
            Markdown comment block string, or empty string if no gaps.
        """
        gaps = [
            t for t in report.for_target(target)
            if t.fidelity in ("comment_only", "dropped") and t.comment
        ]
        if not gaps:
            return ""

        lines = [
            f"<!-- HarnessSync permission notes for {target} -->",
            "<!-- The following Claude Code permissions have no native equivalent here: -->",
        ]
        for g in gaps:
            lines.append(f"<!-- {g.comment} -->")
        lines.append(f"<!-- End HarnessSync permission notes -->")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_shell_tool(tool_name: str) -> bool:
    """Return True if a tool name is a shell-executable command (not an MCP ref)."""
    if tool_name.startswith(_MCP_TOOL_PREFIX):
        return False
    # Allow known Claude Code built-in tool names through
    return tool_name in _SHELL_EXECUTABLE_TOOLS or "/" in tool_name or tool_name.endswith(".sh")


def _tool_to_gemini_pattern(tool_name: str) -> str:
    """Convert a Claude Code tool name to a Gemini glob pattern.

    Gemini uses strings like "bash", "read_file", "*" for tool matching.
    MCP tool refs (mcp__server__tool) are converted to their server prefix.
    """
    if tool_name.startswith(_MCP_TOOL_PREFIX):
        # e.g. mcp__github__search → github_*
        parts = tool_name.split("__", 2)
        if len(parts) >= 2:
            return f"{parts[1]}_*"
        return tool_name
    # Built-in tools — lower-case, snake_case form
    return tool_name.lower().replace(" ", "_")
