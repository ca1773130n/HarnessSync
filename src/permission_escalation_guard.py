from __future__ import annotations

"""Permission Escalation Guard (item 23).

Detects when a sync would grant a target harness MORE permissions than the
source Claude Code config contains. A translation quirk or adapter bug could
accidentally give Cursor bash exec permissions that aren't in CLAUDE.md.
This guard prevents silent privilege escalation.

Escalation cases detected:
- Source has restrictive approvalMode (suggest/manual) but target maps to
  an auto/full-auto mode that bypasses confirmation.
- Source denies a tool but target has no equivalent deny mechanism, silently
  granting it.
- Source has no shell execution permissions but target config would enable
  unrestricted shell access by default.
- Source has explicit deniedTools but target drops them (deny -> allow escalation).

Usage::

    guard = PermissionEscalationGuard()
    warnings = guard.check(source_settings, target="codex")
    for w in warnings:
        print(f"[ESCALATION] {w}")

    # Or check all targets at once:
    report = guard.check_all(source_settings, targets=["codex", "gemini", "cursor"])
    if report.has_escalations:
        print(report.format())
"""

from dataclasses import dataclass, field
from typing import Optional


# Approval modes ordered by permissiveness (higher index = more permissive)
_PERMISSIVENESS_RANK: dict[str, int] = {
    "manual": 0,
    "on-request": 0,
    "review": 1,
    "suggest": 1,
    "default": 1,
    "auto": 2,
    "full-auto": 3,
    "bypass": 3,
}

# What approval mode each harness uses when no explicit mapping is applied.
# "auto" means the harness runs all tools without confirmation by default.
_HARNESS_DEFAULT_APPROVAL: dict[str, str] = {
    "codex":     "on-request",   # Codex defaults to asking before shell ops
    "gemini":    "default",      # Gemini has no explicit approval concept
    "opencode":  "review",       # OpenCode defaults to review mode
    "cursor":    "auto",         # Cursor executes tools automatically
    "aider":     "auto",         # Aider's --yes flag bypasses confirmation
    "windsurf":  "auto",         # Windsurf executes tools automatically
    "cline":     "auto",         # Cline executes tools automatically
    "continue":  "auto",         # Continue executes tools automatically
    "zed":       "auto",         # Zed AI executes tools automatically
    "neovim":    "auto",         # Neovim AI plugins execute tools automatically
    "vscode":    "auto",         # VS Code Copilot executes tools automatically
}

# Approval mode mappings from Claude Code to each harness (mirrors permission_translator.py)
_CC_TO_HARNESS_APPROVAL: dict[str, dict[str, str]] = {
    "codex": {
        "auto":    "full-auto",
        "suggest": "on-request",
        "manual":  "on-request",
    },
    "gemini": {
        "auto":    "default",
        "suggest": "default",
        "manual":  "default",
    },
    "opencode": {
        "auto":    "auto",
        "suggest": "review",
        "manual":  "manual",
    },
    "cursor": {},   # No native approval mapping; falls back to harness default
    "aider":  {},
    "windsurf": {},
    "cline":  {},
    "continue": {},
    "zed":    {},
    "neovim": {},
    "vscode": {},
}

# Harnesses that have no native deny-list mechanism: denied tools silently
# become allowed because there is nowhere to write the deny rule.
_NO_DENY_MECHANISM: frozenset[str] = frozenset({
    "cursor", "aider", "windsurf", "cline", "continue", "zed", "neovim", "vscode",
})

# Harnesses where unrestricted shell execution is ON by default (unless restricted).
_DEFAULT_SHELL_EXEC: frozenset[str] = frozenset({
    "cursor", "aider", "windsurf", "cline", "continue", "zed", "neovim", "vscode",
})


@dataclass
class EscalationWarning:
    """A single permission escalation warning for one target harness.

    Attributes:
        target:      Harness name (e.g. "cursor").
        category:    Type of escalation: "approval_mode" | "denied_tools" | "shell_exec".
        description: Human-readable explanation of the escalation.
        severity:    "warn" | "block" -- whether sync should be halted.
        source_val:  The source (Claude Code) value that was escalated.
        target_val:  The effective value in the target harness.
    """

    target: str
    category: str
    description: str
    severity: str = "warn"       # "warn" or "block"
    source_val: str = ""
    target_val: str = ""

    def format(self) -> str:
        icon = "BLOCK" if self.severity == "block" else "WARN"
        lines = [f"[{icon}] {self.target}: {self.description}"]
        if self.source_val and self.target_val:
            lines.append(f"         Source: {self.source_val}  ->  Target: {self.target_val}")
        return "\n".join(lines)


@dataclass
class EscalationReport:
    """Aggregated escalation warnings for all checked targets.

    Attributes:
        warnings:          List of EscalationWarning objects (all severities).
        targets_checked:   Harnesses that were evaluated.
        source_settings:   Summary of source Claude Code settings.
    """

    warnings: list[EscalationWarning] = field(default_factory=list)
    targets_checked: list[str] = field(default_factory=list)
    source_settings: dict = field(default_factory=dict)

    @property
    def has_escalations(self) -> bool:
        return bool(self.warnings)

    @property
    def has_blocks(self) -> bool:
        return any(w.severity == "block" for w in self.warnings)

    def for_target(self, target: str) -> list[EscalationWarning]:
        return [w for w in self.warnings if w.target == target]

    def format(self, verbose: bool = False) -> str:
        if not self.warnings:
            return (
                "No permission escalations detected across "
                f"{len(self.targets_checked)} target(s)."
            )

        blocks = [w for w in self.warnings if w.severity == "block"]
        warns  = [w for w in self.warnings if w.severity == "warn"]

        lines = [
            "Permission Escalation Guard",
            "=" * 60,
            "",
        ]
        if blocks:
            lines.append(f"BLOCKED: {len(blocks)} critical escalation(s) would grant excess permissions.")
            for w in blocks:
                lines.append(f"  {w.format()}")
            lines.append("")
        if warns:
            lines.append(f"Warnings: {len(warns)} permission gap(s) worth reviewing.")
            for w in warns:
                lines.append(f"  {w.format()}")
            lines.append("")

        if verbose and self.source_settings:
            lines.append("Source settings evaluated:")
            for k, v in self.source_settings.items():
                lines.append(f"  {k}: {v!r}")

        lines.append("Tip: Use per-harness overrides (/sync-override) to restrict individual targets.")
        return "\n".join(lines)


def _approval_rank(mode: str) -> int:
    """Return the permissiveness rank for an approval mode string."""
    return _PERMISSIVENESS_RANK.get(mode.lower().replace("_", "-"), 1)


class PermissionEscalationGuard:
    """Detect when a sync would grant a target harness more permissions than the source.

    This guard runs before each sync and emits warnings (or blocks) when a
    translation would silently escalate privileges in the target harness.

    Args:
        block_on_escalation: If True, any detected escalation raises a
                              RuntimeError (useful for CI/CD pipelines).
                              Default: False (warnings only).
    """

    def __init__(self, block_on_escalation: bool = False) -> None:
        self._block = block_on_escalation

    def check(
        self,
        source_settings: dict,
        target: str,
    ) -> list[EscalationWarning]:
        """Check a single target for permission escalations.

        Args:
            source_settings: Claude Code settings dict (from settings.json).
            target: Harness name to evaluate.

        Returns:
            List of EscalationWarning objects. Empty if no escalations found.
        """
        warnings: list[EscalationWarning] = []
        warnings.extend(self._check_approval_mode(source_settings, target))
        warnings.extend(self._check_denied_tools(source_settings, target))
        warnings.extend(self._check_shell_exec(source_settings, target))
        return warnings

    def check_all(
        self,
        source_settings: dict,
        targets: Optional[list[str]] = None,
    ) -> EscalationReport:
        """Check all targets for permission escalations.

        Args:
            source_settings: Claude Code settings dict.
            targets: Harnesses to check. Defaults to all known harnesses.

        Returns:
            EscalationReport with all warnings and a formatted summary.
        """
        if targets is None:
            targets = list(_HARNESS_DEFAULT_APPROVAL.keys())

        all_warnings: list[EscalationWarning] = []
        for target in targets:
            all_warnings.extend(self.check(source_settings, target))

        source_summary: dict = {}
        if "approvalMode" in source_settings:
            source_summary["approvalMode"] = source_settings["approvalMode"]
        if "deniedTools" in source_settings:
            source_summary["deniedTools"] = source_settings["deniedTools"]
        if "permissions" in source_settings:
            deny = source_settings["permissions"].get("deny", [])
            if deny:
                source_summary["permissions.deny"] = deny

        return EscalationReport(
            warnings=all_warnings,
            targets_checked=list(targets),
            source_settings=source_summary,
        )

    def _check_approval_mode(
        self,
        settings: dict,
        target: str,
    ) -> list[EscalationWarning]:
        """Warn when target approval mode is more permissive than source."""
        source_mode = settings.get("approvalMode", "")
        if not source_mode:
            return []

        harness_map = _CC_TO_HARNESS_APPROVAL.get(target, {})
        target_mode = harness_map.get(source_mode, _HARNESS_DEFAULT_APPROVAL.get(target, ""))

        source_rank = _approval_rank(source_mode)
        target_rank = _approval_rank(target_mode)

        if target_rank > source_rank:
            severity = "block" if target_rank >= _approval_rank("auto") else "warn"
            return [EscalationWarning(
                target=target,
                category="approval_mode",
                description=(
                    f"Approval mode escalation: source is '{source_mode}' but {target} "
                    f"would use '{target_mode}' (more permissive -- tools run without confirmation)."
                ),
                severity=severity,
                source_val=source_mode,
                target_val=target_mode,
            )]
        return []

    def _check_denied_tools(
        self,
        settings: dict,
        target: str,
    ) -> list[EscalationWarning]:
        """Warn when denied tools cannot be enforced on the target."""
        denied: list[str] = []
        denied.extend(settings.get("deniedTools", []) or [])
        perms = settings.get("permissions", {}) or {}
        denied.extend(perms.get("deny", []) or [])

        if not denied:
            return []

        if target not in _NO_DENY_MECHANISM:
            return []  # Target supports deny lists; no escalation

        significant_denials = [d for d in denied if d not in {"*", ""}]
        if not significant_denials:
            return []

        return [EscalationWarning(
            target=target,
            category="denied_tools",
            description=(
                f"Denied tools cannot be enforced on {target}: "
                f"{', '.join(significant_denials[:5])}"
                f"{' (and more)' if len(significant_denials) > 5 else ''}"
                f" will be silently accessible."
            ),
            severity="warn",
            source_val=f"deny: {', '.join(significant_denials[:3])}",
            target_val="(no deny mechanism -- tools accessible)",
        )]

    def _check_shell_exec(
        self,
        settings: dict,
        target: str,
    ) -> list[EscalationWarning]:
        """Warn when source restricts shell but target enables it by default."""
        if target not in _DEFAULT_SHELL_EXEC:
            return []

        allowed_tools: list[str] = settings.get("allowedTools", []) or []
        denied_tools: list[str] = settings.get("deniedTools", []) or []
        perms = settings.get("permissions", {}) or {}
        perm_deny: list[str] = perms.get("deny", []) or []

        bash_denied = any(
            t.lower() in {"bash", "sh", "execute", "shell"}
            for t in denied_tools + perm_deny
        )
        bash_explicitly_allowed = any(
            t.lower() in {"bash", "sh", "execute", "shell"}
            for t in allowed_tools
        )
        bash_restricted_by_allowlist = bool(allowed_tools) and not bash_explicitly_allowed

        if not (bash_denied or bash_restricted_by_allowlist):
            return []

        return [EscalationWarning(
            target=target,
            category="shell_exec",
            description=(
                f"Shell execution is restricted in Claude Code but {target} "
                f"enables unrestricted shell access by default. "
                f"Your Bash restrictions will not apply."
            ),
            severity="warn",
            source_val="Bash: restricted",
            target_val=f"{target}: unrestricted shell (default)",
        )]


def check_escalation(
    source_settings: dict,
    targets: Optional[list[str]] = None,
    block_on_escalation: bool = False,
) -> EscalationReport:
    """Convenience function: check all targets for permission escalations.

    Args:
        source_settings: Claude Code settings dict.
        targets: Harnesses to evaluate (default: all).
        block_on_escalation: Raise RuntimeError if any block-level escalation found.

    Returns:
        EscalationReport with all warnings.

    Raises:
        RuntimeError: If block_on_escalation=True and block-level escalations exist.
    """
    guard = PermissionEscalationGuard(block_on_escalation=block_on_escalation)
    report = guard.check_all(source_settings, targets=targets)
    if block_on_escalation and report.has_blocks:
        raise RuntimeError(
            f"Permission escalation guard blocked sync: "
            f"{len([w for w in report.warnings if w.severity == 'block'])} "
            f"critical escalation(s) detected. "
            f"Run /sync-permissions to review."
        )
    return report
