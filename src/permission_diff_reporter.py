from __future__ import annotations

"""Permission model diff reporter for HarnessSync.

Clearly explains where Claude Code's permission model (allowedTools, env vars,
approvalMode) cannot map cleanly to a target harness and what the security
implications are.

Users discover permission mismatches by accident today. A clear report lets
them make informed decisions about which tools to trust in each harness.
"""

from dataclasses import dataclass, field
from pathlib import Path


# Permission model mapping per target:
# "full": Claude Code permission concept maps natively
# "partial": Approximate mapping, some semantics lost
# "none": No equivalent — permission is silently dropped
_PERMISSION_SUPPORT: dict[str, dict[str, str]] = {
    "codex": {
        "allowedTools": "partial",       # Maps to approval_policy on-request/auto
        "deniedTools": "none",           # Codex has no tool deny list
        "approvalMode": "partial",       # Maps to approval_policy field
        "envVars": "partial",            # Mapped to [env] section, but CC env namespacing differs
        "networkAccess": "none",         # No Codex equivalent
        "fileAccess": "none",            # No Codex equivalent
    },
    "gemini": {
        "allowedTools": "partial",       # Maps to tools.allowed list
        "deniedTools": "partial",        # Maps to tools.exclude list
        "approvalMode": "none",          # Gemini auto-approves all tool calls
        "envVars": "partial",            # Env vars inherited from shell, not declared
        "networkAccess": "none",         # No Gemini equivalent
        "fileAccess": "none",            # No Gemini equivalent
    },
    "opencode": {
        "allowedTools": "partial",       # Per-tool permission entries
        "deniedTools": "partial",        # Per-tool permission entries
        "approvalMode": "partial",       # permission field per tool
        "envVars": "partial",            # Env inherited from shell
        "networkAccess": "none",
        "fileAccess": "none",
    },
    "cursor": {
        "allowedTools": "none",          # Cursor manages tool access via IDE settings
        "deniedTools": "none",
        "approvalMode": "none",
        "envVars": "partial",            # Env in mcp.json server configs
        "networkAccess": "none",
        "fileAccess": "none",
    },
    "aider": {
        "allowedTools": "none",
        "deniedTools": "none",
        "approvalMode": "partial",       # --auto-commits, --yes flags
        "envVars": "partial",            # Env inherited from shell
        "networkAccess": "none",
        "fileAccess": "none",
    },
    "windsurf": {
        "allowedTools": "none",
        "deniedTools": "none",
        "approvalMode": "none",
        "envVars": "partial",
        "networkAccess": "none",
        "fileAccess": "none",
    },
    "cline": {
        "allowedTools": "none",
        "deniedTools": "none",
        "approvalMode": "partial",       # Cline has auto-approve mode in extension
        "envVars": "partial",
        "networkAccess": "none",
        "fileAccess": "none",
    },
    "continue": {
        "allowedTools": "none",
        "deniedTools": "none",
        "approvalMode": "none",
        "envVars": "partial",
        "networkAccess": "none",
        "fileAccess": "none",
    },
    "zed": {
        "allowedTools": "none",
        "deniedTools": "none",
        "approvalMode": "none",
        "envVars": "partial",
        "networkAccess": "none",
        "fileAccess": "none",
    },
    "neovim": {
        "allowedTools": "none",
        "deniedTools": "none",
        "approvalMode": "none",
        "envVars": "partial",
        "networkAccess": "none",
        "fileAccess": "none",
    },
}

_SECURITY_IMPLICATIONS: dict[str, dict[str, str]] = {
    "allowedTools": {
        "none": (
            "All tools are implicitly allowed. Users accustomed to Claude Code's "
            "tool allowlist may be surprised by unrestricted access in this harness."
        ),
        "partial": (
            "Tool allow/deny semantics differ. Some tool restrictions may not be "
            "honored. Review the target harness's tool access model."
        ),
    },
    "deniedTools": {
        "none": (
            "Tool deny lists are not enforced. Tools explicitly blocked in Claude Code "
            "will be available in this harness — potential security exposure."
        ),
        "partial": (
            "Tool exclusions are approximated. Verify denied tools are actually "
            "blocked in the target harness."
        ),
    },
    "approvalMode": {
        "none": (
            "Approval mode has no equivalent. The harness may auto-approve all "
            "actions without user confirmation, including destructive operations."
        ),
        "partial": (
            "Approval semantics differ. Review the target's confirmation model "
            "to understand what user approval is required."
        ),
    },
    "envVars": {
        "partial": (
            "Environment variable handling differs. Secrets in env vars may be "
            "exposed differently across harnesses. Use the secret detector."
        ),
    },
}


@dataclass
class PermissionMismatch:
    """A single permission concept that doesn't map cleanly to a target."""
    permission: str     # "allowedTools" | "deniedTools" etc.
    support_level: str  # "none" | "partial"
    implication: str    # Security implication text


@dataclass
class TargetPermissionReport:
    """Permission mapping report for a single target harness."""
    target: str
    mismatches: list[PermissionMismatch] = field(default_factory=list)

    @property
    def has_security_gaps(self) -> bool:
        return any(m.support_level == "none" for m in self.mismatches)

    @property
    def risk_level(self) -> str:
        """Overall risk level for this target's permission mapping."""
        none_count = sum(1 for m in self.mismatches if m.support_level == "none")
        partial_count = sum(1 for m in self.mismatches if m.support_level == "partial")
        if none_count >= 3:
            return "high"
        if none_count >= 1 or partial_count >= 3:
            return "medium"
        return "low"


@dataclass
class PermissionDiffReport:
    """Full permission diff report across all targets."""
    targets: list[TargetPermissionReport] = field(default_factory=list)
    source_permissions: dict = field(default_factory=dict)

    def format(self) -> str:
        """Format the permission diff report as human-readable text."""
        lines = ["## Permission Model Diff Report", ""]
        lines.append(
            "Shows where Claude Code's permission model cannot map cleanly to "
            "each target harness.\n"
        )

        if not self.source_permissions and not self.targets:
            lines.append("No permission configuration found in Claude Code settings.")
            return "\n".join(lines)

        for target_report in sorted(self.targets, key=lambda t: t.target):
            risk_symbol = {"high": "!", "medium": "~", "low": " "}.get(
                target_report.risk_level, " "
            )
            lines.append(
                f"[{risk_symbol}] {target_report.target} "
                f"(risk: {target_report.risk_level.upper()})"
            )
            if not target_report.mismatches:
                lines.append("    All permissions map cleanly.")
            else:
                for m in target_report.mismatches:
                    support_label = "NOT SUPPORTED" if m.support_level == "none" else "PARTIAL"
                    lines.append(f"  {m.permission}: {support_label}")
                    if m.implication:
                        lines.append(f"    => {m.implication}")
            lines.append("")

        high_risk = [t for t in self.targets if t.risk_level == "high"]
        if high_risk:
            lines.append(
                "HIGH RISK targets have 3+ permission concepts with no equivalent. "
                "Users may be surprised by the permissive behavior in these harnesses."
            )

        return "\n".join(lines)


class PermissionDiffReporter:
    """Generates permission model diff reports.

    Args:
        project_dir: Project root directory.
        cc_home: Claude Code home directory (defaults to ~/.claude).
    """

    def __init__(self, project_dir: Path, cc_home: Path = None):
        self.project_dir = project_dir
        self.cc_home = cc_home or Path.home() / ".claude"

    def generate(
        self,
        settings: dict = None,
        targets: list[str] = None,
    ) -> PermissionDiffReport:
        """Generate a permission diff report.

        Args:
            settings: Claude Code settings dict (from SourceReader).
                      If None, auto-loads from ~/.claude/settings.json.
            targets: Targets to include (None = all registered targets).

        Returns:
            PermissionDiffReport.
        """
        if settings is None:
            settings = self._load_settings()

        if targets is None:
            from src.adapters import AdapterRegistry
            targets = AdapterRegistry.list_targets()

        # Extract active permission concepts from settings
        active_permissions = self._extract_active_permissions(settings)

        report = PermissionDiffReport(source_permissions=active_permissions)

        for target in targets:
            target_support = _PERMISSION_SUPPORT.get(target, {})
            target_report = TargetPermissionReport(target=target)

            for perm_name, is_active in active_permissions.items():
                if not is_active:
                    continue
                support_level = target_support.get(perm_name, "none")
                if support_level == "full":
                    continue  # No mismatch

                implications = _SECURITY_IMPLICATIONS.get(perm_name, {})
                implication = implications.get(support_level, "")

                target_report.mismatches.append(PermissionMismatch(
                    permission=perm_name,
                    support_level=support_level,
                    implication=implication,
                ))

            report.targets.append(target_report)

        return report

    def _load_settings(self) -> dict:
        """Load Claude Code settings from disk."""
        import json as _json
        for candidate in (
            self.cc_home / "settings.json",
            self.project_dir / ".claude" / "settings.json",
        ):
            if candidate.is_file():
                try:
                    return _json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
        return {}

    def _extract_active_permissions(self, settings: dict) -> dict[str, bool]:
        """Extract which permission concepts are actively configured."""
        return {
            "allowedTools": bool(settings.get("allowedTools") or settings.get("permissions", {}).get("allow")),
            "deniedTools": bool(settings.get("deniedTools") or settings.get("permissions", {}).get("deny")),
            "approvalMode": bool(settings.get("approvalMode") or settings.get("approval_mode")),
            "envVars": bool(settings.get("env") or settings.get("envVars")),
            "networkAccess": bool(settings.get("networkAccess")),
            "fileAccess": bool(settings.get("fileAccess")),
        }
