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
        lines.append("<!-- End HarnessSync permission notes -->")
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


# ---------------------------------------------------------------------------
# Cross-harness Permissions Audit Report (Item 27)
# ---------------------------------------------------------------------------

def generate_audit_report(
    settings: dict,
    targets: list[str] | None = None,
) -> str:
    """Generate a cross-harness permissions audit report.

    Produces a Markdown table showing what each configured harness is allowed
    to do, flags dangerous permission inconsistencies (e.g. shell execution
    allowed in one harness but blocked in another), and lists items that
    could not be translated natively.

    Args:
        settings: Claude Code settings dict (keys: allowedTools, deniedTools,
                  approvalMode, permissions).
        targets:  Harnesses to include (default: all known).

    Returns:
        Multi-line Markdown string with the audit report.
    """
    if targets is None:
        targets = list(_APPROVAL_MODE_MAP.keys()) + ["cursor", "aider", "windsurf"]

    translator = PermissionTranslator()
    report = translator.translate(settings, targets)

    # Gather per-target capability summary
    target_caps: dict[str, dict] = {}
    for target in targets:
        translations = report.for_target(target)
        shell_allowed = _infer_shell_allowed(settings, target, translations)
        network_allowed = _infer_network_allowed(settings, target, translations)
        file_read = _infer_file_access(settings, target, translations, "read")
        file_write = _infer_file_access(settings, target, translations, "write")
        approval = _infer_approval_label(settings, target, translations)
        gaps = [t for t in translations if t.fidelity in ("comment_only", "dropped")]
        target_caps[target] = {
            "shell": shell_allowed,
            "network": network_allowed,
            "file_read": file_read,
            "file_write": file_write,
            "approval": approval,
            "gap_count": len(gaps),
            "gap_items": [t.setting for t in gaps],
        }

    lines: list[str] = []
    lines.append("# HarnessSync Permissions Audit Report\n")
    lines.append(
        "Cross-harness permissions matrix — shows what each AI harness is allowed "
        "to do based on your Claude Code settings.\n"
    )

    # Matrix table
    col_targets = targets[:8]  # cap width
    header = "| Capability       | " + " | ".join(f"{t:<10}" for t in col_targets) + " |"
    sep    = "|:-----------------|-" + "-|-".join("-" * 12 for _ in col_targets) + "-|"
    lines.append(header)
    lines.append(sep)

    def _row(label: str, key: str) -> str:
        cells = [_bool_cell(target_caps[t][key]) for t in col_targets]
        return f"| {label:<17}| " + " | ".join(f"{c:<10}" for c in cells) + " |"

    lines.append(_row("Shell execution",  "shell"))
    lines.append(_row("Network access",   "network"))
    lines.append(_row("File read",        "file_read"))
    lines.append(_row("File write",       "file_write"))

    # Approval mode row
    approval_cells = [target_caps[t]["approval"] for t in col_targets]
    lines.append(
        f"| {'Approval mode':<17}| "
        + " | ".join(f"{c:<10}" for c in approval_cells)
        + " |"
    )

    lines.append("")

    # Dangerous inconsistencies
    inconsistencies: list[str] = []
    for cap_key, cap_label in (
        ("shell",      "Shell execution"),
        ("network",    "Network access"),
        ("file_write", "File write"),
    ):
        values = {t: target_caps[t][cap_key] for t in col_targets}
        unique_vals = set(values.values())
        if len(unique_vals) > 1:
            allowed_in  = [t for t, v in values.items() if v is True]
            blocked_in  = [t for t, v in values.items() if v is False]
            if allowed_in and blocked_in:
                inconsistencies.append(
                    f"- **{cap_label}**: allowed in `{'`, `'.join(allowed_in)}` "
                    f"but blocked in `{'`, `'.join(blocked_in)}`"
                )

    if inconsistencies:
        lines.append("## ⚠ Dangerous Inconsistencies\n")
        lines.extend(inconsistencies)
        lines.append(
            "\nInconsistencies can cause the same AI task to succeed in one harness "
            "and silently fail (or behave dangerously) in another.\n"
        )
    else:
        lines.append("## ✓ No Dangerous Inconsistencies\n")
        lines.append(
            "All harnesses have consistent permissions for high-risk capabilities.\n"
        )

    # Translation gaps
    all_gaps: dict[str, list[str]] = {
        t: target_caps[t]["gap_items"]
        for t in col_targets
        if target_caps[t]["gap_items"]
    }
    if all_gaps:
        lines.append("## Translation Gaps\n")
        lines.append(
            "The following settings could not be mapped natively and were "
            "embedded as comments or dropped:\n"
        )
        for target, items in sorted(all_gaps.items()):
            lines.append(f"- **{target}**: {', '.join(items)}")
        lines.append("")

    return "\n".join(lines)


def _bool_cell(value: bool | None) -> str:
    if value is True:
        return "✓ yes"
    if value is False:
        return "✗ no"
    return "~ partial"


def _infer_shell_allowed(
    settings: dict,
    target: str,
    translations: list[PermissionTranslation],
) -> bool | None:
    """Infer whether shell execution is permitted for a harness."""
    denied = settings.get("deniedTools", [])
    if "Bash" in denied or "bash" in denied:
        return False
    allowed = settings.get("allowedTools", [])
    if allowed and "Bash" not in allowed and "bash" not in allowed:
        return False
    if target in ("aider", "continue", "zed", "neovim"):
        return None  # No native shell permission model
    return True


def _infer_network_allowed(
    settings: dict,
    target: str,
    translations: list[PermissionTranslation],
) -> bool | None:
    denied = settings.get("deniedTools", [])
    if "WebFetch" in denied or "WebSearch" in denied:
        return False
    return True


def _infer_file_access(
    settings: dict,
    target: str,
    translations: list[PermissionTranslation],
    direction: str,
) -> bool | None:
    """Infer file read or write permission."""
    denied = settings.get("deniedTools", [])
    if direction == "read" and ("Read" in denied or "Glob" in denied):
        return False
    if direction == "write" and ("Write" in denied or "Edit" in denied):
        return False
    return True


def _infer_approval_label(
    settings: dict,
    target: str,
    translations: list[PermissionTranslation],
) -> str:
    """Return a short approval mode label for a target."""
    approval_mode = settings.get("approvalMode", settings.get("approval_mode", "suggest"))
    mapping = _APPROVAL_MODE_MAP.get(target, {})
    return mapping.get(str(approval_mode), approval_mode[:8])
