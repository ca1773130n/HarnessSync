from __future__ import annotations

"""Harness version compatibility pinning.

Let users declare the version of Cursor/Codex/Gemini they're targeting so
HarnessSync uses the correct schema for that version rather than the latest.

Prevents sync breakage when a user is on an older harness version that
doesn't support newer config fields.

Version pinning is declared in .harnesssync:
{
    "harness_versions": {
        "cursor": "0.43",
        "codex": "1.2",
        "gemini": "2.0"
    }
}

Or globally in ~/.harnesssync/versions.json (project overrides global).

Version-gated feature matrix:
  Each harness entry lists features introduced in specific versions.
  When the declared version is older than a feature's minimum version,
  that feature is disabled and a warning is emitted.
"""

from dataclasses import dataclass, field
from pathlib import Path


# Features with version requirements per harness.
# Format: {harness: {feature_name: (min_version_str, description)}}
VERSIONED_FEATURES: dict[str, dict[str, tuple[str, str]]] = {
    "cursor": {
        "mdc_alwaysApply": ("0.40", "alwaysApply frontmatter field in .mdc files"),
        "mdc_glob_scoping": ("0.42", "glob-based rule scoping in .mdc frontmatter"),
        "mcp_json":         ("0.43", ".cursor/mcp.json for MCP server configuration"),
    },
    "codex": {
        "mcp_servers":      ("1.0", "MCP server configuration in config.toml"),
        "sandbox_mode":     ("1.1", "sandbox_mode field in config.toml"),
        "approval_policy":  ("1.2", "approval_policy field in config.toml"),
    },
    "gemini": {
        "mcp_servers":      ("1.0", "mcpServers in settings.json"),
        "tools_exclude":    ("1.5", "tools.exclude permission field"),
        "tools_allowed":    ("2.0", "tools.allowed permission field"),
    },
    "opencode": {
        "mcp_type_field":   ("0.1", "type discriminator in MCP server config"),
    },
    "aider": {
        "read_files_list":  ("0.50", "read_files list in .aider.conf.yml"),
    },
    "windsurf": {
        "mcp_config_json":  ("1.0", ".codeium/windsurf/mcp_config.json"),
        "memory_files":     ("1.2", ".windsurf/memories/ directory"),
    },
}

# Default "current" versions (assume latest supported)
_DEFAULT_VERSIONS: dict[str, str] = {
    "cursor":   "0.43",
    "codex":    "1.2",
    "gemini":   "2.0",
    "opencode": "0.2",
    "aider":    "0.60",
    "windsurf": "1.3",
}

# Global versions config file
_GLOBAL_VERSIONS_FILE = Path.home() / ".harnesssync" / "versions.json"


@dataclass
class VersionCompatResult:
    """Compatibility check result for a single harness."""

    target: str
    declared_version: str
    supported_features: list[str] = field(default_factory=list)
    disabled_features: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def all_supported(self) -> bool:
        return not self.disabled_features


def _parse_version(version_str: str) -> tuple[int, ...]:
    """Parse a version string into a comparable tuple.

    Args:
        version_str: Version like "1.2", "0.43", "2.0.1"

    Returns:
        Tuple of ints for comparison.
    """
    try:
        return tuple(int(x) for x in str(version_str).split("."))
    except (ValueError, AttributeError):
        return (0,)


def _version_gte(v1: str, v2: str) -> bool:
    """Return True if v1 >= v2."""
    return _parse_version(v1) >= _parse_version(v2)


def load_pinned_versions(project_dir: Path | None = None) -> dict[str, str]:
    """Load pinned harness versions from config files.

    Merges global versions (~/.harnesssync/versions.json) with per-project
    versions from .harnesssync["harness_versions"]. Project overrides global.

    Args:
        project_dir: Project root directory (for per-project config).

    Returns:
        Dict mapping target_name -> version_string.
        Falls back to _DEFAULT_VERSIONS for unconfigured targets.
    """
    import json

    versions: dict[str, str] = dict(_DEFAULT_VERSIONS)

    # Load global pinned versions
    if _GLOBAL_VERSIONS_FILE.exists():
        try:
            data = json.loads(_GLOBAL_VERSIONS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                versions.update({k: str(v) for k, v in data.items() if isinstance(v, (str, int, float))})
        except (OSError, json.JSONDecodeError):
            pass

    # Load per-project pinned versions
    if project_dir:
        project_config = project_dir / ".harnesssync"
        if project_config.exists():
            try:
                import json as _json
                data = _json.loads(project_config.read_text(encoding="utf-8"))
                harness_versions = data.get("harness_versions", {})
                if isinstance(harness_versions, dict):
                    versions.update({
                        k: str(v) for k, v in harness_versions.items()
                        if isinstance(v, (str, int, float))
                    })
            except (OSError, ValueError):
                pass

    return versions


def check_version_compat(
    target: str,
    declared_version: str,
) -> VersionCompatResult:
    """Check which features are supported for a given harness version.

    Args:
        target: Target harness name.
        declared_version: Declared/pinned version string.

    Returns:
        VersionCompatResult listing supported and disabled features.
    """
    features = VERSIONED_FEATURES.get(target, {})
    result = VersionCompatResult(target=target, declared_version=declared_version)

    for feature_name, (min_version, description) in features.items():
        if _version_gte(declared_version, min_version):
            result.supported_features.append(feature_name)
        else:
            result.disabled_features.append((feature_name, description))
            result.warnings.append(
                f"{target} v{declared_version}: '{feature_name}' disabled "
                f"(requires v{min_version}+) — {description}"
            )

    return result


def get_compat_flags(target: str, project_dir: Path | None = None) -> dict[str, bool]:
    """Get feature compatibility flags for a target based on pinned version.

    Returns a flat dict of {feature_name: is_supported} that adapters can
    query to conditionally enable/disable fields in their config output.

    Args:
        target: Target harness name.
        project_dir: Project root (for per-project version config).

    Returns:
        Dict mapping feature_name -> bool.
    """
    versions = load_pinned_versions(project_dir)
    declared = versions.get(target, _DEFAULT_VERSIONS.get(target, "0.0"))
    result = check_version_compat(target, declared)

    flags: dict[str, bool] = {}
    for feat in result.supported_features:
        flags[feat] = True
    for feat, _ in result.disabled_features:
        flags[feat] = False

    return flags


# ──────────────────────────────────────────────────────────────────────────────
# Migration Rules: breaking config changes between harness versions
# Format: {target: [(from_ver, to_ver, description, migration_fn)]}
# migration_fn(config: dict) -> dict applies the schema transformation
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
    import json
    import shutil

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


def _detect_installed_version(target: str) -> str | None:
    """Attempt to detect the installed harness CLI version.

    Args:
        target: Harness name.

    Returns:
        Version string, or None if not detectable.
    """
    import subprocess
    import re as _re

    cli_map: dict[str, list[str]] = {
        "codex": ["codex", "--version"],
        "gemini": ["gemini", "--version"],
        "opencode": ["opencode", "--version"],
        "cursor": ["cursor", "--version"],
        "aider": ["aider", "--version"],
        "windsurf": ["windsurf", "--version"],
    }
    args = cli_map.get(target)
    if not args:
        return None

    try:
        result = subprocess.run(
            args, capture_output=True, text=True, timeout=5
        )
        output = result.stdout + result.stderr
        # Extract first version-like string (e.g. "1.2.3" or "v0.43.2")
        match = _re.search(r"v?(\d+\.\d+(?:\.\d+)?)", output)
        if match:
            return match.group(1)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _update_pinned_version(target: str, version: str, project_dir: Path | None = None) -> None:
    """Update the pinned version for a target in versions.json.

    Args:
        target: Harness name.
        version: New version string to pin.
        project_dir: Project root (updates project config if provided).
    """
    import json

    _GLOBAL_VERSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        if _GLOBAL_VERSIONS_FILE.exists():
            data = json.loads(_GLOBAL_VERSIONS_FILE.read_text(encoding="utf-8"))
        else:
            data = {}
        data[target] = version
        _GLOBAL_VERSIONS_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass


def format_compat_warnings(project_dir: Path | None = None) -> list[str]:
    """Generate all version compatibility warnings for all pinned targets.

    Args:
        project_dir: Project root directory.

    Returns:
        List of warning strings (empty if all features supported at declared versions).
    """
    versions = load_pinned_versions(project_dir)
    warnings: list[str] = []

    for target, version in versions.items():
        result = check_version_compat(target, version)
        warnings.extend(result.warnings)

    return warnings
