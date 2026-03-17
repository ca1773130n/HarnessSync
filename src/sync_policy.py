from __future__ import annotations

"""Sync Policy Enforcement (item 25).

Allows teams to define an org-level policy file specifying which config
sections MUST sync to all targets and which MUST NOT sync (e.g. personal
preferences, internal URLs, sensitive prompts).

Policy file locations (checked in priority order):
  1. ``<project_dir>/.harnesssync-policy.json``   (project-level override)
  2. ``~/.harnesssync/policy.json``               (global/org-level policy)

Policy JSON schema::

    {
        "version": 1,
        "description": "Acme Corp AI config policy",
        "must_sync": ["rules", "mcp"],
        "must_not_sync": ["personal_preferences"],
        "target_overrides": {
            "aider": {
                "must_not_sync": ["mcp"]
            }
        },
        "protected_sections": ["Security Rules", "Compliance"],
        "require_review_for": ["mcp", "settings"]
    }

Fields:
- ``must_sync``: Sections that MUST be included in every sync. If a section
  is absent from the source, sync is blocked with a clear error.
- ``must_not_sync``: Sections that are NEVER synced to any target.
  Overrides ``must_sync`` at the target level.
- ``target_overrides``: Per-target overrides for must_sync / must_not_sync.
- ``protected_sections``: CLAUDE.md heading names that cannot be removed or
  modified during a sync (checked against diff if available).
- ``require_review_for``: Sections that emit a warning prompting manual review
  before sync proceeds. Does not block sync.

Usage::

    enforcer = PolicyEnforcer(project_dir=Path("."))
    report = enforcer.check(source_data, target="codex")
    if report.blocked:
        print(report.format())
        sys.exit(1)
    for warning in report.warnings:
        print(f"[POLICY WARNING] {warning}")
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_PROJECT_POLICY_NAME = ".harnesssync-policy.json"
_GLOBAL_POLICY_FILE = Path.home() / ".harnesssync" / "policy.json"

# Sections recognised by HarnessSync
_KNOWN_SECTIONS = frozenset(["rules", "skills", "agents", "commands", "mcp", "settings"])


@dataclass
class PolicyViolation:
    """A single policy rule violation."""

    severity: str   # "error" (blocks sync) | "warning" (advisory)
    section: str    # Which config section triggered this
    target: str     # Harness target name
    message: str    # Human-readable description


@dataclass
class PolicyReport:
    """Result of a policy check for a single target."""

    target: str
    violations: list[PolicyViolation] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(v.severity == "error" for v in self.violations)

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == "warning") + len(self.warnings)

    def format(self) -> str:
        if not self.violations and not self.warnings:
            return f"Policy check passed for {self.target}."
        lines = [f"Policy Check: {self.target}", "-" * 40]
        for v in self.violations:
            icon = "✗" if v.severity == "error" else "⚠"
            lines.append(f"  {icon} [{v.severity.upper()}] {v.section}: {v.message}")
        for w in self.warnings:
            lines.append(f"  ⚠ [WARNING] {w}")
        if self.blocked:
            lines.append("")
            lines.append("Sync BLOCKED by policy. Fix errors above before syncing.")
        return "\n".join(lines)


@dataclass
class PolicyCheckResult:
    """Aggregate result across all checked targets."""

    reports: list[PolicyReport] = field(default_factory=list)
    policy_file: Optional[str] = None   # Path that was loaded

    @property
    def any_blocked(self) -> bool:
        return any(r.blocked for r in self.reports)

    @property
    def total_errors(self) -> int:
        return sum(r.error_count for r in self.reports)

    @property
    def total_warnings(self) -> int:
        return sum(r.warning_count for r in self.reports)

    def format(self) -> str:
        if not self.reports:
            return "No policy checks performed."
        lines = []
        if self.policy_file:
            lines.append(f"Policy: {self.policy_file}")
        for report in self.reports:
            lines.append(report.format())
        lines.append("")
        status = "BLOCKED" if self.any_blocked else "OK"
        lines.append(
            f"Summary: {status} — {self.total_errors} error(s), "
            f"{self.total_warnings} warning(s) across {len(self.reports)} target(s)."
        )
        return "\n".join(lines)


def _load_policy(project_dir: Optional[Path]) -> tuple[dict, Optional[str]]:
    """Load the first policy file found in priority order.

    Returns:
        Tuple of (policy_dict, file_path_string).  policy_dict is {} if
        no policy file exists.
    """
    candidates: list[Path] = []
    if project_dir:
        candidates.append(project_dir / _PROJECT_POLICY_NAME)
    candidates.append(_GLOBAL_POLICY_FILE)

    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data, str(path)
            except (json.JSONDecodeError, OSError):
                continue
    return {}, None


class PolicyEnforcer:
    """Checks sync operations against a team/org policy file.

    Args:
        project_dir: Project root; policy file searched here first.
        policy: Explicit policy dict (skips file discovery; useful for tests).
    """

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        policy: Optional[dict] = None,
    ) -> None:
        self._project_dir = project_dir
        if policy is not None:
            self._policy = policy
            self._policy_file: Optional[str] = "<inline>"
        else:
            self._policy, self._policy_file = _load_policy(project_dir)

    @property
    def policy_file(self) -> Optional[str]:
        return self._policy_file

    @property
    def has_policy(self) -> bool:
        return bool(self._policy)

    def check(self, source_data: dict, target: str) -> PolicyReport:
        """Check a single target against the policy.

        Args:
            source_data: Config dict from SourceReader.discover_all().
            target: Harness name (e.g. "codex", "gemini").

        Returns:
            PolicyReport with any violations found.
        """
        report = PolicyReport(target=target)
        if not self._policy:
            return report

        must_sync = set(self._policy.get("must_sync", []))
        must_not_sync = set(self._policy.get("must_not_sync", []))
        protected = list(self._policy.get("protected_sections", []))
        review_required = set(self._policy.get("require_review_for", []))

        # Apply per-target overrides
        overrides = self._policy.get("target_overrides", {}).get(target, {})
        must_sync = must_sync | set(overrides.get("must_sync", []))
        must_not_sync = must_not_sync | set(overrides.get("must_not_sync", []))

        # must_sync check: each required section must be non-empty in source
        for section in must_sync:
            value = source_data.get(section)
            is_present = bool(value) if not isinstance(value, dict) else bool(value)
            if not is_present:
                report.violations.append(PolicyViolation(
                    severity="error",
                    section=section,
                    target=target,
                    message=(
                        f"Policy requires '{section}' to sync to '{target}', "
                        f"but it is absent or empty in source config."
                    ),
                ))

        # must_not_sync check: if source has the section, flag it
        for section in must_not_sync:
            value = source_data.get(section)
            is_present = bool(value) if not isinstance(value, dict) else bool(value)
            if is_present:
                report.violations.append(PolicyViolation(
                    severity="error",
                    section=section,
                    target=target,
                    message=(
                        f"Policy forbids syncing '{section}' to '{target}'. "
                        f"Remove it from source or add <!-- sync:exclude --> tags."
                    ),
                ))

        # require_review_for: emit warnings, don't block
        for section in review_required:
            value = source_data.get(section)
            is_present = bool(value) if not isinstance(value, dict) else bool(value)
            if is_present:
                report.warnings.append(
                    f"Section '{section}' requires manual review before syncing to '{target}'."
                )

        # protected_sections: warn if they appear to be empty/missing
        rules_text = source_data.get("rules", "") or ""
        for section_name in protected:
            if section_name not in rules_text:
                report.violations.append(PolicyViolation(
                    severity="warning",
                    section="rules",
                    target=target,
                    message=(
                        f"Protected section '{section_name}' not found in rules — "
                        f"it may have been accidentally removed."
                    ),
                ))

        return report

    def check_all(
        self,
        source_data: dict,
        targets: list[str] | None = None,
    ) -> PolicyCheckResult:
        """Check multiple targets against the policy.

        Args:
            source_data: Config dict from SourceReader.
            targets: Harness names to check. Defaults to all known sections.

        Returns:
            PolicyCheckResult aggregating all target reports.
        """
        from src.adapters import AdapterRegistry
        if targets is None:
            targets = AdapterRegistry.list_targets()

        result = PolicyCheckResult(policy_file=self._policy_file)
        for target in targets:
            result.reports.append(self.check(source_data, target))
        return result

    def get_must_not_sync_sections(self, target: str) -> set[str]:
        """Return sections forbidden for *target* per current policy.

        Args:
            target: Harness name.

        Returns:
            Set of section names that should be excluded from the sync payload.
        """
        must_not = set(self._policy.get("must_not_sync", []))
        overrides = self._policy.get("target_overrides", {}).get(target, {})
        must_not |= set(overrides.get("must_not_sync", []))
        return must_not

    def strip_forbidden_sections(self, source_data: dict, target: str) -> dict:
        """Return a copy of *source_data* with policy-forbidden sections removed.

        This enables sync to proceed for non-blocked sections even when a
        ``must_not_sync`` section is present, rather than halting entirely.

        Args:
            source_data: Original config dict.
            target: Harness name.

        Returns:
            New dict with forbidden sections removed.
        """
        forbidden = self.get_must_not_sync_sections(target)
        if not forbidden:
            return source_data
        return {k: v for k, v in source_data.items() if k not in forbidden}

    def format_policy_summary(self) -> str:
        """Return a human-readable summary of the active policy."""
        if not self._policy:
            return "No policy file found. Sync proceeds without restrictions."
        lines = [
            "Active Sync Policy",
            "=" * 40,
        ]
        if self._policy_file:
            lines.append(f"  File        : {self._policy_file}")
        if "description" in self._policy:
            lines.append(f"  Description : {self._policy['description']}")
        must_sync = self._policy.get("must_sync", [])
        must_not = self._policy.get("must_not_sync", [])
        protected = self._policy.get("protected_sections", [])
        review = self._policy.get("require_review_for", [])
        lines.append(f"  Must sync   : {', '.join(must_sync) if must_sync else '(none)'}")
        lines.append(f"  Must NOT    : {', '.join(must_not) if must_not else '(none)'}")
        if protected:
            lines.append(f"  Protected   : {', '.join(protected)}")
        if review:
            lines.append(f"  Review req. : {', '.join(review)}")
        overrides = self._policy.get("target_overrides", {})
        if overrides:
            lines.append("  Overrides   :")
            for tgt, rules in overrides.items():
                lines.append(f"    {tgt}: {json.dumps(rules)}")
        return "\n".join(lines)
