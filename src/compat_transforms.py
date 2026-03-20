from __future__ import annotations

"""Harness compatibility transforms — migration rules, migration guides, and update alerts.

Provides schema migration functions for when harness config formats change
between versions, plus tools for generating migration guides and post-update
validation alerts.
"""

from dataclasses import dataclass, field
from pathlib import Path

from src.version_detection import (
    _DEFAULT_VERSIONS,
    _detect_installed_version,
    _update_pinned_version,
    _version_gte,
    load_pinned_versions,
)
from src.compat_rules import (
    DEPRECATED_FIELDS,
    VERSIONED_FEATURES,
)


# ──────────────────────────────────────────────────────────────────────────────
# Migration functions: schema transforms between harness versions
# ──────────────────────────────────────────────────────────────────────────────

def _gemini_migrate_tools_permissions(config: dict) -> dict:
    """Gemini 1.5 → 2.0: rename blockedTools/allowedTools → tools.exclude/tools.allowed."""
    settings = config.get("settings", {})
    if not settings:
        return config
    changed = False
    if "blockedTools" in settings and "tools" not in settings:
        settings.setdefault("tools", {})["exclude"] = settings.pop("blockedTools")
        changed = True
    if "allowedTools" in settings and "tools" not in settings.get("tools", {}):
        settings.setdefault("tools", {})["allowed"] = settings.pop("allowedTools")
        changed = True
    if changed:
        config["settings"] = settings
    return config


def _codex_migrate_approval_policy(config: dict) -> dict:
    """Codex 1.0 → 1.2: rename fullAuto → on-request in approval_policy."""
    settings = config.get("settings", {})
    if settings.get("approval_policy") == "fullAuto":
        settings["approval_policy"] = "on-request"
        config["settings"] = settings
    return config


def _windsurf_migrate_mcp_config(config: dict) -> dict:
    """Windsurf 0.x → 1.0: move mcp_servers to .codeium/windsurf/mcp_config.json format."""
    # The top-level "mcp" key moves under "mcpServers" wrapper
    if "mcp" in config and "mcpServers" not in config:
        config["mcpServers"] = config.pop("mcp")
    return config


# Migration table: (min_from_ver, target_version, label, fn)
_MIGRATION_RULES: dict[str, list[tuple[str, str, str, object]]] = {
    "gemini": [
        ("1.5", "2.0", "Rename blockedTools/allowedTools to tools.exclude/tools.allowed",
         _gemini_migrate_tools_permissions),
    ],
    "codex": [
        ("1.0", "1.2", "Rename approval_policy 'fullAuto' to 'on-request'",
         _codex_migrate_approval_policy),
    ],
    "windsurf": [
        ("0.9", "1.0", "Wrap mcp servers under mcpServers key",
         _windsurf_migrate_mcp_config),
    ],
}


# ──────────────────────────────────────────────────────────────────────────────
# Migration result and execution
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MigrationResult:
    """Result of a config migration attempt."""
    target: str
    migrations_applied: list[str] = field(default_factory=list)
    migrations_skipped: list[str] = field(default_factory=list)
    config_before: dict = field(default_factory=dict)
    config_after: dict = field(default_factory=dict)

    @property
    def changed(self) -> bool:
        return bool(self.migrations_applied)

    def format(self) -> str:
        if not self.changed:
            return f"{self.target}: No migrations needed."
        lines = [f"{self.target}: Applied {len(self.migrations_applied)} migration(s):"]
        for m in self.migrations_applied:
            lines.append(f"  ✓ {m}")
        for m in self.migrations_skipped:
            lines.append(f"  ~ {m} (skipped — already up to date)")
        return "\n".join(lines)


def migrate_config(
    target: str,
    config: dict,
    from_version: str,
    to_version: str,
) -> MigrationResult:
    """Apply all relevant migration rules to a harness config dict.

    Detects which schema transformations are needed when a target harness
    upgrades from from_version to to_version, and applies them in order.

    This is the core of the version migration assistant: when a harness
    upgrades with a breaking config change, callers pass the current pinned
    config and get back an updated config that matches the new schema.

    Args:
        target: Harness name (e.g. "gemini", "codex").
        config: Current config dict for the target.
        from_version: The version the config was written for.
        to_version: The version being migrated to.

    Returns:
        MigrationResult with the updated config and applied migration log.
    """
    import copy

    result = MigrationResult(
        target=target,
        config_before=copy.deepcopy(config),
    )

    rules = _MIGRATION_RULES.get(target, [])
    current_config = copy.deepcopy(config)

    for min_from, needs_at, label, fn in rules:
        # Apply this rule if: we're upgrading from <= min_from, and to >= needs_at
        if _version_gte(from_version, needs_at):
            # From version is already at or past the migration target — skip
            result.migrations_skipped.append(label)
            continue
        if not _version_gte(to_version, needs_at):
            # Target version doesn't reach the migration minimum — skip
            result.migrations_skipped.append(label)
            continue
        try:
            current_config = fn(current_config)  # type: ignore[operator]
            result.migrations_applied.append(label)
        except Exception as exc:
            result.migrations_skipped.append(f"{label} (error: {exc})")

    result.config_after = current_config
    return result


def detect_and_migrate(
    target: str,
    project_dir: Path | None = None,
) -> MigrationResult | None:
    """Detect if the installed harness version is newer than the pinned version
    and auto-migrate the saved config to the new schema.

    Compares the version in ~/.harnesssync/versions.json (pinned = last sync)
    against the newly detected installed version. If the installed version is
    newer, applies all applicable migrations and updates the pinned version.

    Returns None if no migration is needed or harness is not detectable.

    Args:
        target: Harness name to check.
        project_dir: Project root for per-project version config.

    Returns:
        MigrationResult if migrations were applied, None otherwise.
    """

    # Get currently pinned (last-synced) version
    pinned_versions = load_pinned_versions(project_dir)
    pinned = pinned_versions.get(target, _DEFAULT_VERSIONS.get(target, "0.0"))

    # Detect installed version by parsing the harness CLI's version output
    installed = _detect_installed_version(target)
    if not installed:
        return None  # Can't detect version

    if _version_gte(pinned, installed):
        return None  # Already at or ahead of installed — no migration needed

    # Migration needed: installed version is newer than pinned
    # Load the current synced config for this target (if any)
    # We operate on the in-memory default config for schema updates
    config: dict = {"version": pinned, "target": target}
    result = migrate_config(target, config, from_version=pinned, to_version=installed)

    # Update the pinned version to the installed version
    if result.changed:
        _update_pinned_version(target, installed, project_dir)

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Upgrade migration guide generation
# ──────────────────────────────────────────────────────────────────────────────

def generate_upgrade_migration_guide(
    target: str,
    from_version: str,
    to_version: str,
    project_dir: Path | None = None,
) -> dict:
    """Generate a step-by-step migration guide when a harness is upgraded.

    When the user upgrades a harness (e.g. Gemini CLI from 1.5 to 2.0) and the
    config format changes, this function produces a structured guide covering:
      - Features gained/lost between the two versions
      - Migration rules that will be applied automatically by HarnessSync
      - Deprecated fields requiring manual attention
      - Manual action items the user must perform

    Args:
        target: Harness name (e.g. "gemini", "cursor").
        from_version: The version being upgraded from.
        to_version: The version being upgraded to.
        project_dir: Project root directory (used for pinned version lookup).

    Returns:
        Dict with keys:
          - ``target``: str
          - ``from_version``: str
          - ``to_version``: str
          - ``features_gained``: list[str]  — features newly supported in to_version
          - ``features_lost``: list[str]    — features supported in from_version but not to_version
          - ``auto_migrations``: list[str]  — migration rule descriptions applied automatically
          - ``deprecated_warnings``: list[str]  — deprecated fields that need attention
          - ``manual_actions``: list[str]   — steps the user must take manually
          - ``summary``: str               — one-line upgrade impact summary
    """
    features_gained: list[str] = []
    features_lost: list[str] = []

    target_features = VERSIONED_FEATURES.get(target, {})
    for feat, (min_ver, description) in target_features.items():
        had_before = _version_gte(from_version, min_ver)
        has_after = _version_gte(to_version, min_ver)
        if has_after and not had_before:
            features_gained.append(f"{feat}: {description}")
        elif had_before and not has_after:
            # This can happen if min_ver > to_version (downgrade or unusual range)
            features_lost.append(f"{feat}: {description}")

    # Collect auto-migrations: rules whose version range overlaps the upgrade window
    auto_migrations: list[str] = []
    target_migrations = _MIGRATION_RULES.get(target, [])
    for rule in target_migrations:
        rule_version = rule.get("introduced_in", "")
        if rule_version and _version_gte(to_version, rule_version) and not _version_gte(from_version, rule_version):
            action = rule.get("action", "")
            field = rule.get("field", "")
            rename_to = rule.get("rename_to", "")
            if action == "rename" and rename_to:
                auto_migrations.append(
                    f"Field '{field}' renamed to '{rename_to}' (v{rule_version}+) — HarnessSync will rewrite automatically"
                )
            elif action == "remove":
                auto_migrations.append(
                    f"Field '{field}' removed in v{rule_version} — HarnessSync will drop it from the synced config"
                )
            elif action == "transform":
                transform = rule.get("transform", "")
                auto_migrations.append(
                    f"Field '{field}' transformed ({transform}) in v{rule_version} — HarnessSync will apply the transformation"
                )
            elif action:
                auto_migrations.append(
                    f"Field '{field}' ({action}) in v{rule_version} — HarnessSync will handle this migration"
                )

    # Collect deprecated field warnings
    deprecated_warnings: list[str] = []
    target_deprecated = DEPRECATED_FIELDS.get(target, {})
    for field, dep_info in target_deprecated.items():
        deprecated_since = dep_info.get("deprecated_since", "")
        removal_version = dep_info.get("removal_version", "")
        replacement = dep_info.get("replacement", "")
        # Warn if the field was not deprecated at from_version but is at to_version
        if deprecated_since and _version_gte(to_version, deprecated_since) and not _version_gte(from_version, deprecated_since):
            msg = f"'{field}' deprecated since v{deprecated_since}"
            if removal_version:
                msg += f", scheduled for removal in v{removal_version}"
            if replacement:
                msg += f" — use '{replacement}' instead"
            deprecated_warnings.append(msg)

    # Build manual action items
    manual_actions: list[str] = []
    if features_gained:
        manual_actions.append(
            f"Run /sync to push updated config that enables {len(features_gained)} newly supported feature(s)"
        )
    if deprecated_warnings:
        manual_actions.append(
            f"Review {len(deprecated_warnings)} deprecated field(s) in your {target} config and migrate to replacements"
        )
    if not auto_migrations and not features_gained and not deprecated_warnings:
        manual_actions.append(
            f"No breaking changes detected for {target} v{from_version} → v{to_version} — run /sync as a precaution"
        )

    # Build one-line summary
    parts = []
    if features_gained:
        parts.append(f"{len(features_gained)} feature(s) gained")
    if features_lost:
        parts.append(f"{len(features_lost)} feature(s) lost")
    if auto_migrations:
        parts.append(f"{len(auto_migrations)} auto-migration(s)")
    if deprecated_warnings:
        parts.append(f"{len(deprecated_warnings)} deprecation warning(s)")
    summary = (
        f"{target.capitalize()} v{from_version} → v{to_version}: "
        + (", ".join(parts) if parts else "no breaking changes")
    )

    return {
        "target": target,
        "from_version": from_version,
        "to_version": to_version,
        "features_gained": features_gained,
        "features_lost": features_lost,
        "auto_migrations": auto_migrations,
        "deprecated_warnings": deprecated_warnings,
        "manual_actions": manual_actions,
        "summary": summary,
    }


def format_upgrade_migration_guide(guide: dict) -> str:
    """Format a migration guide dict as a human-readable terminal string.

    Args:
        guide: Output of generate_upgrade_migration_guide().

    Returns:
        Multi-line formatted string ready for CLI output.
    """
    target = guide.get("target", "")
    from_v = guide.get("from_version", "?")
    to_v = guide.get("to_version", "?")

    lines = [
        f"Migration Guide: {target.capitalize()} v{from_v} → v{to_v}",
        "=" * 60,
        "",
    ]

    features_gained = guide.get("features_gained", [])
    if features_gained:
        lines.append("Features Gained:")
        for f in features_gained:
            lines.append(f"  + {f}")
        lines.append("")

    features_lost = guide.get("features_lost", [])
    if features_lost:
        lines.append("Features Lost:")
        for f in features_lost:
            lines.append(f"  - {f}")
        lines.append("")

    auto_migrations = guide.get("auto_migrations", [])
    if auto_migrations:
        lines.append("Automatic Migrations (HarnessSync will handle these):")
        for m in auto_migrations:
            lines.append(f"  * {m}")
        lines.append("")

    deprecated_warnings = guide.get("deprecated_warnings", [])
    if deprecated_warnings:
        lines.append("Deprecation Warnings:")
        for w in deprecated_warnings:
            lines.append(f"  ! {w}")
        lines.append("")

    manual_actions = guide.get("manual_actions", [])
    if manual_actions:
        lines.append("Required Actions:")
        for i, action in enumerate(manual_actions, 1):
            lines.append(f"  {i}. {action}")
        lines.append("")

    lines.append(guide.get("summary", ""))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Post-Update Config Validation
# ---------------------------------------------------------------------------

class ConfigUpdateAlert:
    """An alert produced when a harness update may affect synced configs."""

    def __init__(
        self,
        harness: str,
        old_version: str | None,
        new_version: str,
        broken_fields: list[str],
        new_features: list[str],
        action_required: bool,
    ):
        self.harness = harness
        self.old_version = old_version
        self.new_version = new_version
        self.broken_fields = broken_fields      # Fields no longer valid in new version
        self.new_features = new_features        # New native features now available
        self.action_required = action_required  # True if re-sync is recommended

    def format(self) -> str:
        lines = [
            f"Harness update detected: {self.harness} "
            f"{self.old_version or '?'} → {self.new_version}",
        ]
        if self.broken_fields:
            lines.append("  Breaking changes (re-sync recommended):")
            for f in self.broken_fields:
                lines.append(f"    ✗ {f}")
        if self.new_features:
            lines.append("  New features now available:")
            for f in self.new_features:
                lines.append(f"    + {f}")
        if self.action_required:
            lines.append("  Action: run /sync to apply updated config format.")
        return "\n".join(lines)


def validate_configs_after_update(
    update_entries: list[dict],
    project_dir: Path | None = None,
) -> list[ConfigUpdateAlert]:
    """Re-validate synced configs against new harness formats after an update.

    When detect_harness_updates() reports version changes, call this function
    to determine whether the updated harnesses require config changes (broken
    fields) or now offer new native features that weren't available before.

    Args:
        update_entries: Output of detect_harness_updates() — list of dicts
                        with keys 'harness', 'old_version', 'new_version', 'kind'.
        project_dir: Project root for loading pinned version config.

    Returns:
        List of ConfigUpdateAlert for harnesses that need attention.
        Empty list if all updates are backwards-compatible.
    """
    alerts: list[ConfigUpdateAlert] = []

    for entry in update_entries:
        if entry.get("kind") not in ("updated", "new"):
            continue

        harness = entry["harness"]
        old_ver = entry.get("old_version")
        new_ver = entry.get("new_version")
        if not new_ver:
            continue

        harness_features = VERSIONED_FEATURES.get(harness, {})

        broken_fields: list[str] = []
        new_features: list[str] = []

        # Detect deprecated fields that the old config may have written.
        # DEPRECATED_FIELDS[harness][field] = (since_version, description)
        deprecated = DEPRECATED_FIELDS.get(harness, {})
        for field_name, field_info in deprecated.items():
            # field_info is (since_version_str, description)
            since = field_info[0] if isinstance(field_info, (tuple, list)) else "0"
            description = field_info[1] if isinstance(field_info, (tuple, list)) and len(field_info) > 1 else ""
            # If old version was before deprecation and new version is at or after it
            if old_ver and _version_gte(new_ver, since) and not _version_gte(old_ver, since):
                msg = f"{field_name} deprecated in v{since}"
                if description:
                    msg += f": {description}"
                broken_fields.append(msg)

        # Detect new features that are now available in the new version
        for feature_name, (min_ver, description) in harness_features.items():
            was_available = old_ver and _version_gte(old_ver, min_ver)
            now_available = _version_gte(new_ver, min_ver)
            if now_available and not was_available:
                new_features.append(f"{feature_name}: {description} (v{min_ver}+)")

        action_required = bool(broken_fields)
        if broken_fields or new_features:
            alerts.append(ConfigUpdateAlert(
                harness=harness,
                old_version=old_ver,
                new_version=new_ver,
                broken_fields=broken_fields,
                new_features=new_features,
                action_required=action_required,
            ))

    return alerts


def format_update_alerts(alerts: list[ConfigUpdateAlert]) -> str:
    """Format a list of ConfigUpdateAlerts into a user-facing message.

    Args:
        alerts: Output of validate_configs_after_update().

    Returns:
        Formatted string, or empty string if no alerts.
    """
    if not alerts:
        return ""
    lines = ["Harness update compatibility check:"]
    for alert in alerts:
        lines.append("")
        lines.append(alert.format())
    return "\n".join(lines)
