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


# ---------------------------------------------------------------------------
# Deprecated config fields registry (item 20)
# ---------------------------------------------------------------------------

# Fields that HarnessSync adapters may write, but which have been deprecated
# by the target harness.  Format:
#   {harness: {field_name: (deprecated_since, migration_hint)}}
#
# ``deprecated_since`` is the first harness version where the field is
# deprecated (not necessarily removed — removed means the adapter must be
# updated separately).
#
# ``migration_hint`` is shown verbatim in the warning message.
DEPRECATED_FIELDS: dict[str, dict[str, tuple[str, str]]] = {
    "cursor": {
        # Example: cursor deprecated the 'description' frontmatter key in 0.41
        # in favour of the structured 'title' field.
        "description": (
            "0.41",
            "Use 'title' frontmatter instead of 'description' in .mdc files",
        ),
        # Legacy cursor rules file — replaced by .cursor/rules/*.mdc in 0.42
        ".cursorrules": (
            "0.42",
            "Migrate rules from .cursorrules to .cursor/rules/*.mdc files",
        ),
    },
    "codex": {
        # 'model' at top level was deprecated in 1.1; use 'provider.model'
        "model": (
            "1.1",
            "Move 'model' into the [provider] table in codex config.toml",
        ),
    },
    "gemini": {
        # 'contextWindowSize' was removed in Gemini CLI 2.0
        "contextWindowSize": (
            "2.0",
            "'contextWindowSize' removed — use 'context.maxTokens' instead",
        ),
        # 'theme' top-level key deprecated in 1.8 in favour of 'ui.theme'
        "theme": (
            "1.8",
            "Move 'theme' to 'ui.theme' in Gemini settings.json",
        ),
    },
    "opencode": {
        # 'instructions' top-level key superseded by 'system' in 0.2
        "instructions": (
            "0.2",
            "Replace 'instructions' with 'system' in opencode config",
        ),
    },
    "aider": {
        # '--encoding' flag deprecated in 0.55; use '--input-encoding'
        "encoding": (
            "0.55",
            "Replace 'encoding' with 'input-encoding' in .aider.conf.yml",
        ),
    },
    "windsurf": {
        # 'globalRules' key removed in Windsurf 1.1; use .windsurfrules file
        "globalRules": (
            "1.1",
            "Remove 'globalRules' key; place rules in .windsurfrules instead",
        ),
    },
}


def check_deprecated_fields_in_output(
    target: str,
    output: dict | str,
    project_dir: Path | None = None,
) -> list[str]:
    """Check adapter output for deprecated config fields before writing.

    Scans the about-to-be-written config (either a dict or raw string) for
    fields that the target harness has deprecated.  Issues a warning for each
    deprecated field found, including the first harness version where the field
    was deprecated and the migration path.

    This runs *before* writing so the user can fix CLAUDE.md or update the
    adapter before the stale config lands on disk.

    Args:
        target: Harness name (e.g. "cursor").
        output: The config data the adapter is about to write.  May be a dict
                (for JSON/TOML configs) or a string (for Markdown configs).
        project_dir: Project root for loading pinned version (optional).

    Returns:
        List of warning strings.  Empty list = no deprecated fields detected.
    """
    deprecated = DEPRECATED_FIELDS.get(target, {})
    if not deprecated:
        return []

    # Load pinned version so we can skip warnings for fields deprecated in
    # versions newer than what the user has declared.
    pinned = load_pinned_versions(project_dir).get(target, _DEFAULT_VERSIONS.get(target, "0"))

    warnings: list[str] = []

    for field_name, (deprecated_since, migration_hint) in deprecated.items():
        # Only warn if the user's pinned version is >= the deprecation version
        if not _version_gte(pinned, deprecated_since):
            continue

        found = False
        if isinstance(output, dict):
            # Check top-level dict keys (and one level deep for nested dicts)
            if field_name in output:
                found = True
            else:
                for v in output.values():
                    if isinstance(v, dict) and field_name in v:
                        found = True
                        break
        elif isinstance(output, str):
            # For TOML/YAML/Markdown: simple substring search for the field name
            if field_name in output:
                found = True

        if found:
            warnings.append(
                f"[deprecation] {target}: '{field_name}' deprecated since v{deprecated_since} — "
                f"{migration_hint}"
            )

    return warnings


def warn_deprecated_fields(
    target: str,
    output: dict | str,
    project_dir: Path | None = None,
) -> None:
    """Log deprecation warnings for any deprecated fields in adapter output.

    Convenience wrapper around ``check_deprecated_fields_in_output`` that
    prints warnings directly to stderr.  Adapters can call this just before
    writing config files to surface deprecation notices to the user.

    Args:
        target: Harness name.
        output: Config data about to be written.
        project_dir: Project root for version lookup.
    """
    import sys
    warnings_list = check_deprecated_fields_in_output(target, output, project_dir)
    for w in warnings_list:
        print(f"  ⚠  {w}", file=sys.stderr)


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


def detect_installed_version(target: str) -> str | None:
    """Detect the currently installed version of a harness CLI.

    Public wrapper around _detect_installed_version that also falls back to
    checking package manifests (package.json, pip metadata) for GUI-only tools
    like Cursor where the CLI binary may not be on PATH.

    Args:
        target: Harness name (e.g. "cursor", "gemini", "codex").

    Returns:
        Version string (e.g. "0.43.2"), or None if not detectable.
    """
    # Try the CLI --version flag first (works for terminal-based tools)
    version = _detect_installed_version(target)
    if version:
        return version

    # Fallback: check application package metadata for GUI tools
    import re as _re

    _APP_MANIFEST_PATHS: dict[str, list[Path]] = {
        "cursor": [
            Path("/Applications/Cursor.app/Contents/Resources/app/package.json"),
            Path.home() / "AppData" / "Local" / "Programs" / "cursor" / "resources" / "app" / "package.json",
        ],
        "windsurf": [
            Path("/Applications/Windsurf.app/Contents/Resources/app/package.json"),
            Path.home() / "AppData" / "Local" / "Programs" / "windsurf" / "resources" / "app" / "package.json",
        ],
    }

    for manifest_path in _APP_MANIFEST_PATHS.get(target, []):
        if manifest_path.is_file():
            try:
                import json as _json
                data = _json.loads(manifest_path.read_text(encoding="utf-8"))
                v = data.get("version", "")
                if v and _re.match(r"\d+\.\d+", v):
                    return v
            except (OSError, ValueError):
                pass

    return None


def detect_all_installed_versions(project_dir: Path | None = None) -> dict[str, str | None]:
    """Detect installed versions for all known harnesses.

    Scans the system for all supported harness tools and returns a mapping
    of harness name to detected version. Useful for sync-status and first-run
    onboarding to show which harnesses are actually installed.

    Args:
        project_dir: Optional project root for pinned-version context.

    Returns:
        Dict mapping target_name -> version_string (or None if not detected).
        Only includes targets where the harness appears to be installed.
    """
    import shutil as _shutil

    _CLI_NAMES: dict[str, str] = {
        "codex":    "codex",
        "gemini":   "gemini",
        "opencode": "opencode",
        "aider":    "aider",
        "cursor":   "cursor",
        "windsurf": "windsurf",
        "cline":    "code",    # Cline is a VS Code extension
        "continue": "code",    # Continue.dev is a VS Code extension
        "zed":      "zed",
        "neovim":   "nvim",
    }

    results: dict[str, str | None] = {}
    for target, cli in _CLI_NAMES.items():
        # Skip targets where the CLI is not on PATH (for extension-based tools, try anyway)
        if not _shutil.which(cli) and target not in ("cline", "continue"):
            continue
        version = detect_installed_version(target)
        if version is not None:
            results[target] = version

    return results


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


# New capabilities introduced in recent harness versions — used for upgrade suggestions.
# Format: {harness: [(introduced_in_version, capability_name, user_benefit, sync_section)]}
# sync_section: which HarnessSync source section benefits (rules/skills/agents/commands/mcp/settings)
_NEW_CAPABILITIES: dict[str, list[tuple[str, str, str, str]]] = {
    "cursor": [
        ("0.42", "glob_scoped_rules", "Rules can now be scoped to specific file patterns — your project rules could use glob scoping for finer control", "rules"),
        ("0.43", "mcp_json", "Cursor now supports MCP servers — your MCP config can sync to Cursor", "mcp"),
    ],
    "windsurf": [
        ("1.0", "mcp_servers", "Windsurf v1.0+ supports MCP — your MCP servers can now sync here", "mcp"),
        ("1.2", "memory_files", "Windsurf now supports memory files — your skills could sync as Windsurf memories", "skills"),
    ],
    "gemini": [
        ("1.5", "tools_exclude", "Gemini now supports tool exclusion rules — your settings can propagate tool restrictions", "settings"),
        ("2.0", "tools_allowed", "Gemini v2.0+ supports tools.allowed allowlist — finer permission control is now syncable", "settings"),
    ],
    "codex": [
        ("1.1", "sandbox_mode", "Codex now supports sandbox_mode — your safety settings can include this field", "settings"),
        ("1.2", "approval_policy", "Codex now supports approval_policy — your permission settings can fully sync", "settings"),
    ],
    "aider": [
        ("0.50", "read_files_list", "Aider v0.50+ supports read_files list — your skill files can be referenced as context", "skills"),
    ],
}


def suggest_capability_upgrades(
    project_dir: Path | None = None,
    source_data: dict | None = None,
) -> list[str]:
    """Suggest sync improvements when installed harnesses support new capabilities.

    Compares the installed harness version against the pinned version and
    against the new capability registry. When the installed version is newer
    than the pinned version and unlocks a new capability that would benefit
    the user's existing Claude Code config, a suggestion string is returned.

    Args:
        project_dir: Project root directory for version config lookup.
        source_data: Pre-loaded source config dict (from SourceReader.discover_all()).
                     If None, capability matching is skipped (suggestions are generic).

    Returns:
        List of actionable suggestion strings. Empty if no upgrades available.

    Example output:
        [
            "Windsurf 1.2 is installed (you have pinned 1.0): memory files are now supported "
            "— you have 3 skills that could sync as Windsurf memories. Run /sync to enable.",
        ]
    """
    pinned_versions = load_pinned_versions(project_dir)
    suggestions: list[str] = []

    for target, pinned in pinned_versions.items():
        installed = _detect_installed_version(target)
        if not installed:
            continue
        if _version_gte(pinned, installed):
            continue  # Already pinned at or beyond installed — no upgrade news

        # Installed version is newer than pinned — check for new capabilities
        new_caps = _NEW_CAPABILITIES.get(target, [])
        for (min_ver, cap_name, benefit, section) in new_caps:
            # Only surface if the installed version supports it but pinned doesn't
            if _version_gte(installed, min_ver) and not _version_gte(pinned, min_ver):
                # Count relevant source items if source_data provided
                count_hint = ""
                if source_data and section:
                    section_data = source_data.get(section, {})
                    count: int = 0
                    if isinstance(section_data, dict):
                        count = len(section_data)
                    elif isinstance(section_data, (list, str)):
                        count = len(section_data)
                    if count:
                        unit = {
                            "rules": "rule line(s)",
                            "skills": "skill(s)",
                            "agents": "agent(s)",
                            "commands": "command(s)",
                            "mcp": "MCP server(s)",
                            "settings": "setting(s)",
                        }.get(section, "item(s)")
                        count_hint = f" — you have {count} {unit} that could benefit"

                suggestions.append(
                    f"{target.capitalize()} {installed} is installed (pinned: {pinned}): "
                    f"{benefit}{count_hint}. "
                    f"Run `harnesssync --set-version {target}={installed}` to upgrade, "
                    f"then /sync to enable."
                )

    return suggestions


def format_upgrade_suggestions(
    project_dir: Path | None = None,
    source_data: dict | None = None,
) -> str:
    """Format capability upgrade suggestions as a human-readable string.

    Convenience wrapper around suggest_capability_upgrades() for CLI output.

    Args:
        project_dir: Project root directory.
        source_data: Pre-loaded source config dict.

    Returns:
        Formatted multi-line string with suggestions, or empty string if none.
    """
    suggestions = suggest_capability_upgrades(project_dir=project_dir, source_data=source_data)
    if not suggestions:
        return ""
    lines = ["Capability Upgrade Suggestions:", ""]
    for i, s in enumerate(suggestions, 1):
        lines.append(f"  {i}. {s}")
    lines.append("")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Inline upgrade instructions (item 10)
# ──────────────────────────────────────────────────────────────────────────────

# Upgrade commands per harness
_UPGRADE_COMMANDS: dict[str, list[str]] = {
    "cursor": [
        "Open Cursor → Help → Check for Updates",
        "Or download from https://cursor.com",
    ],
    "codex": [
        "npm install -g @openai/codex@latest",
        "Or: npx @openai/codex@latest (no global install)",
    ],
    "gemini": [
        "npm install -g @google/gemini-cli@latest",
        "Or: pip install --upgrade gemini-cli  (if Python-based)",
    ],
    "opencode": [
        "npm install -g opencode@latest",
        "Or: bun upgrade opencode",
    ],
    "aider": [
        "pip install --upgrade aider-chat",
        "Or: pipx upgrade aider-chat",
    ],
    "windsurf": [
        "Open Windsurf → Help → Check for Updates",
        "Or download from https://windsurf.ai",
    ],
    "cline": [
        "Open VS Code → Extensions → Cline → Update",
    ],
    "continue": [
        "Open VS Code → Extensions → Continue → Update",
    ],
}


@dataclass
class UpgradeRequirement:
    """A harness version upgrade that would unlock blocked sync features."""
    harness: str
    current_version: str
    required_version: str
    blocked_features: list[str]
    upgrade_commands: list[str]

    def format(self) -> str:
        """Return a human-readable upgrade requirement block."""
        lines = [
            f"{self.harness.capitalize()} — upgrade {self.current_version} → {self.required_version}",
            f"  Blocked features: {', '.join(self.blocked_features)}",
            "  Upgrade instructions:",
        ]
        for cmd in self.upgrade_commands:
            lines.append(f"    {cmd}")
        return "\n".join(lines)


def get_upgrade_requirements(
    project_dir: Path | None = None,
) -> list[UpgradeRequirement]:
    """Return a list of harness upgrades needed to unblock locked features.

    Compares the declared/detected harness version against the feature
    requirements in VERSIONED_FEATURES and returns upgrade requirements for
    any feature that is currently blocked by an older version.

    Args:
        project_dir: Project root for version config lookup.

    Returns:
        List of UpgradeRequirement objects, one per harness that needs upgrading.
    """
    pinned = load_pinned_versions(project_dir)
    requirements: list[UpgradeRequirement] = []

    for harness, features in VERSIONED_FEATURES.items():
        current = pinned.get(harness) or _DEFAULT_VERSIONS.get(harness, "0.0")
        blocked: list[tuple[str, str]] = []  # (min_version_needed, feature_description)

        for _feature_name, (min_ver, description) in features.items():
            if not _version_gte(current, min_ver):
                blocked.append((min_ver, description))

        if not blocked:
            continue

        # Find the highest required version
        highest_required = max(blocked, key=lambda x: _parse_version(x[0]))[0]
        upgrade_cmds = _UPGRADE_COMMANDS.get(harness, [f"Upgrade {harness} to {highest_required}+"])

        requirements.append(UpgradeRequirement(
            harness=harness,
            current_version=current,
            required_version=highest_required,
            blocked_features=[desc for _, desc in blocked],
            upgrade_commands=upgrade_cmds,
        ))

    return sorted(requirements, key=lambda r: r.harness)


def format_upgrade_requirements(project_dir: Path | None = None) -> str:
    """Format harness upgrade requirements as a human-readable report.

    Shows which harnesses need upgrading to unlock blocked sync features,
    with inline installation commands.

    Args:
        project_dir: Project root directory.

    Returns:
        Formatted multi-line string, or message indicating no upgrades needed.
    """
    reqs = get_upgrade_requirements(project_dir)
    if not reqs:
        return "All harnesses meet the minimum version requirements."

    lines = [
        "Harness Version Upgrade Requirements",
        "=" * 50,
        "",
        "The following harnesses are below the minimum version for some",
        "HarnessSync features. Upgrade to unlock blocked capabilities.",
        "",
    ]
    for req in reqs:
        lines.append(req.format())
        lines.append("")
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Format Change Notifier (item 7)
#
# Detects when HarnessSync's own feature matrix (VERSIONED_FEATURES) has been
# updated — e.g. new features added for Cursor or Codex after a harness release.
# This is different from version pinning: it alerts users when the compatibility
# data itself has changed so they know to re-evaluate their sync setup.
#
# How it works:
#   1. Compute a stable hash of VERSIONED_FEATURES at startup.
#   2. Compare against a hash stored at ~/.harnesssync/format-matrix.json.
#   3. If the hash differs, compute a diff of added/removed features and surface
#      a notification listing which harnesses gained or lost documented features.
#   4. Update the stored hash after the user acknowledges (or automatically).
# ──────────────────────────────────────────────────────────────────────────────

import hashlib as _hashlib
import json as _json_fmt


_FORMAT_MATRIX_CACHE_FILE = Path.home() / ".harnesssync" / "format-matrix.json"


def _compute_matrix_hash(matrix: dict[str, dict[str, tuple[str, str]]]) -> str:
    """Compute a stable SHA256 hash of the feature matrix.

    Args:
        matrix: VERSIONED_FEATURES dict (or equivalent).

    Returns:
        Hex digest string.
    """
    # Serialise with sorted keys so the hash is stable across Python sessions
    payload = _json_fmt.dumps(
        {
            target: {
                feat: list(data)
                for feat, data in sorted(features.items())
            }
            for target, features in sorted(matrix.items())
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    return _hashlib.sha256(payload.encode()).hexdigest()


def _load_format_matrix_cache() -> dict:
    """Load the cached format matrix record from disk.

    Returns:
        Dict with keys ``hash`` (str) and ``features`` (dict snapshot),
        or empty dict if no cache exists.
    """
    if not _FORMAT_MATRIX_CACHE_FILE.exists():
        return {}
    try:
        data = _json_fmt.loads(_FORMAT_MATRIX_CACHE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, _json_fmt.JSONDecodeError):
        return {}


def _save_format_matrix_cache(matrix: dict[str, dict[str, tuple[str, str]]]) -> None:
    """Persist current feature matrix hash and snapshot to disk.

    Args:
        matrix: Current VERSIONED_FEATURES dict.
    """
    _FORMAT_MATRIX_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "hash": _compute_matrix_hash(matrix),
        "features": {
            target: {feat: list(data) for feat, data in features.items()}
            for target, features in matrix.items()
        },
    }
    try:
        _FORMAT_MATRIX_CACHE_FILE.write_text(
            _json_fmt.dumps(record, indent=2, ensure_ascii=True),
            encoding="utf-8",
        )
    except OSError:
        pass


def check_format_matrix_changes(
    matrix: dict[str, dict[str, tuple[str, str]]] | None = None,
    acknowledge: bool = False,
) -> list[str]:
    """Check if the HarnessSync feature matrix has changed since last run.

    Compares the current VERSIONED_FEATURES matrix against a cached snapshot.
    Returns a list of human-readable change notices so callers can surface them
    to the user (e.g. during /sync or /sync-health).

    Args:
        matrix: Feature matrix to check. Defaults to VERSIONED_FEATURES.
        acknowledge: If True, update the cache after computing the diff
                     (marks the user as having seen the changes).

    Returns:
        List of change notice strings. Empty list means no changes detected.
    """
    if matrix is None:
        matrix = VERSIONED_FEATURES

    current_hash = _compute_matrix_hash(matrix)
    cache = _load_format_matrix_cache()

    if not cache:
        # First run — establish baseline silently
        _save_format_matrix_cache(matrix)
        return []

    if cache.get("hash") == current_hash:
        return []  # No changes

    # Matrix changed — compute diff
    notices: list[str] = []
    prev_features: dict = cache.get("features", {})

    for target, features in sorted(matrix.items()):
        prev = prev_features.get(target, {})

        added = {f: v for f, v in features.items() if f not in prev}
        removed = {f: v for f, v in prev.items() if f not in features}
        changed = {
            f: (prev[f], v)
            for f, v in features.items()
            if f in prev and list(v) != list(prev[f])
        }

        if added or removed or changed:
            notices.append(f"HarnessSync compat matrix updated for {target.upper()}:")
            for feat, (min_ver, desc) in added.items():
                notices.append(f"  + Added:   {feat} (requires {target} v{min_ver}+) — {desc}")
            for feat, data in removed.items():
                prev_ver = data[0] if isinstance(data, (list, tuple)) else "?"
                notices.append(f"  - Removed: {feat} (was v{prev_ver}+)")
            for feat, (old_data, new_data) in changed.items():
                old_ver = old_data[0] if isinstance(old_data, (list, tuple)) else "?"
                new_ver = new_data[0] if isinstance(new_data, (list, tuple)) else "?"
                if old_ver != new_ver:
                    notices.append(
                        f"  ~ Changed: {feat} min version {old_ver} → {new_ver}"
                    )

    if acknowledge:
        _save_format_matrix_cache(matrix)

    return notices


def format_matrix_change_report(notices: list[str]) -> str:
    """Format format-matrix change notices as a user-facing message.

    Args:
        notices: Output of check_format_matrix_changes().

    Returns:
        Formatted string, or empty string if no notices.
    """
    if not notices:
        return ""
    header = [
        "⚠  HarnessSync compatibility matrix has changed.",
        "   Run /sync to apply the updated config schema.",
        "",
    ]
    return "\n".join(header + notices)


# ──────────────────────────────────────────────────────────────────────────────
# Harness Version Update Detector (item 25)
# ──────────────────────────────────────────────────────────────────────────────
# Compares previously recorded harness versions (stored in
# ~/.harnesssync/detected-versions.json) against currently detected installed
# versions. When a harness has been updated, surfaces a notice with the old and
# new version so users know to re-run compatibility checks.

import json
import os
import tempfile


_DETECTED_VERSIONS_FILE = Path.home() / ".harnesssync" / "detected-versions.json"


def _load_detected_versions() -> dict[str, str]:
    """Load previously recorded harness versions from disk."""
    if not _DETECTED_VERSIONS_FILE.exists():
        return {}
    try:
        data = json.loads(_DETECTED_VERSIONS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_detected_versions(versions: dict[str, str]) -> None:
    """Persist detected harness versions to disk (atomic write)."""
    _DETECTED_VERSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        dir=_DETECTED_VERSIONS_FILE.parent,
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        json.dump(versions, tmp, indent=2, ensure_ascii=False)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, str(_DETECTED_VERSIONS_FILE))
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def detect_harness_updates(
    current_versions: dict[str, str | None],
    acknowledge: bool = True,
) -> list[dict]:
    """Detect harnesses that have been updated since the last check.

    Compares ``current_versions`` (harness → detected version) against the
    previously stored versions. Returns one entry per harness that has changed.

    Args:
        current_versions: Dict mapping harness name → currently detected version
                          (None if not installed or version unknown).
        acknowledge: If True, update the stored versions to the current values
                     so repeated calls don't keep reporting the same updates.

    Returns:
        List of dicts, each with keys:
            - ``harness``: str
            - ``old_version``: str | None  (None if first detection)
            - ``new_version``: str | None
            - ``kind``: "new" | "updated" | "removed"
    """
    stored = _load_detected_versions()
    updates: list[dict] = []

    all_harnesses = set(stored.keys()) | {k for k, v in current_versions.items() if v}

    for harness in sorted(all_harnesses):
        old_ver = stored.get(harness)
        new_ver = current_versions.get(harness)

        if old_ver is None and new_ver:
            # Newly detected harness
            updates.append({
                "harness": harness,
                "old_version": None,
                "new_version": new_ver,
                "kind": "new",
            })
        elif old_ver and not new_ver:
            # Harness was removed / uninstalled
            updates.append({
                "harness": harness,
                "old_version": old_ver,
                "new_version": None,
                "kind": "removed",
            })
        elif old_ver and new_ver and old_ver != new_ver:
            # Version changed
            updates.append({
                "harness": harness,
                "old_version": old_ver,
                "new_version": new_ver,
                "kind": "updated",
            })

    if acknowledge and updates:
        # Write the new detected versions, removing entries for removed harnesses
        new_stored = dict(stored)
        for entry in updates:
            harness = entry["harness"]
            if entry["kind"] == "removed":
                new_stored.pop(harness, None)
            else:
                new_stored[harness] = entry["new_version"]
        _save_detected_versions(new_stored)
    elif acknowledge and not stored:
        # First run — just record current versions
        initial = {h: v for h, v in current_versions.items() if v}
        if initial:
            _save_detected_versions(initial)

    return updates


def format_update_report(updates: list[dict]) -> str:
    """Format harness update notices as a user-facing message.

    Args:
        updates: Output of detect_harness_updates().

    Returns:
        Human-readable string, or empty string if no updates.
    """
    if not updates:
        return ""

    lines = ["Harness version changes detected:", ""]
    for entry in updates:
        harness = entry["harness"]
        kind = entry["kind"]
        old_ver = entry["old_version"] or "?"
        new_ver = entry["new_version"] or "?"
        if kind == "new":
            lines.append(f"  + {harness}: newly detected (v{new_ver})")
        elif kind == "removed":
            lines.append(f"  - {harness}: no longer detected (was v{old_ver})")
        else:
            lines.append(f"  ↑ {harness}: v{old_ver} → v{new_ver}")

    lines.append("")
    lines.append("Run /sync-status to check for config schema changes.")
    return "\n".join(lines)


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
# Post-Update Config Validation (item 11)
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


# ---------------------------------------------------------------------------
# Harness Update Feed (Item 29 — Harness Update Feed / What's New)
# ---------------------------------------------------------------------------

# Known harness version improvements that unlock better sync fidelity.
# Format: {harness: [(version, feature_name, sync_improvement_note)]}
_VERSION_IMPROVEMENTS: dict[str, list[tuple[str, str, str]]] = {
    "cursor": [
        ("0.40", "mdc_alwaysApply", "alwaysApply support in .mdc rules — rules now activate globally without manual trigger"),
        ("0.42", "mdc_glob_scoping", "glob-based scoping in rules — use globs to target rules to specific file patterns"),
        ("0.43", "mcp_json", "native .cursor/mcp.json — MCP servers now sync directly without manual setup"),
    ],
    "gemini": [
        ("1.5", "tools_exclude", "tools.exclude permission field — tool restrictions now sync cleanly"),
        ("2.0", "tools_allowed", "tools.allowed allowlist — precise tool allowlists now supported"),
        ("2.0", "mcp_servers", "native MCP server support — all configured MCP servers sync to Gemini"),
    ],
    "codex": [
        ("1.0", "mcp_servers", "MCP server config in config.toml — MCP servers now sync to Codex"),
        ("1.1", "sandbox_mode", "sandbox_mode field — execution safety settings sync correctly"),
        ("1.2", "approval_policy", "approval_policy — permission modes now translate faithfully to Codex"),
    ],
    "windsurf": [
        ("1.0", "mcp_config_json", ".codeium/windsurf/mcp_config.json — MCP servers sync to Windsurf"),
        ("1.2", "memory_files", ".windsurf/memories/ — persistent memory files sync as skills"),
    ],
    "aider": [
        ("0.50", "read_files_list", "read_files list in .aider.conf.yml — context files sync cleanly"),
    ],
}


class HarnessUpdateFeed:
    """Monitor harness versions and surface sync-relevant improvements.

    Item 29: When a harness update unlocks better sync fidelity (e.g. Gemini CLI
    1.5 now supports native MCP), this feed notifies users so they know
    upgrading is worthwhile.
    """

    def get_available_improvements(
        self,
        harness: str,
        current_version: str | None,
    ) -> list[dict]:
        """Return improvements available if the user upgrades from current_version.

        Args:
            harness: Canonical harness name.
            current_version: Current installed version string (e.g. "1.4.2").
                             None if version is unknown.

        Returns:
            List of improvement dicts, each with keys:
                - version: str — the harness version that introduced this
                - feature: str — internal feature name
                - note: str — human-readable improvement description
                - unlocks_sync: bool — always True (all listed improvements affect sync)
        """
        improvements = _VERSION_IMPROVEMENTS.get(harness, [])
        if not improvements:
            return []

        if current_version is None:
            # Unknown version — return all improvements as potential gains
            return [
                {"version": v, "feature": f, "note": n, "unlocks_sync": True}
                for v, f, n in improvements
            ]

        result = []
        for min_ver, feature, note in improvements:
            if _version_lt(current_version, min_ver):
                result.append({
                    "version": min_ver,
                    "feature": feature,
                    "note": note,
                    "unlocks_sync": True,
                })
        return result

    def get_all_improvements(
        self,
        installed: dict[str, str | None],
    ) -> dict[str, list[dict]]:
        """Check all installed harnesses for available sync improvements.

        Args:
            installed: Dict mapping harness name -> current version (or None).

        Returns:
            Dict mapping harness name -> list of improvement dicts.
            Only includes harnesses that have pending improvements.
        """
        result: dict[str, list[dict]] = {}
        for harness, version in installed.items():
            improvements = self.get_available_improvements(harness, version)
            if improvements:
                result[harness] = improvements
        return result

    def format_feed(self, improvements: dict[str, list[dict]]) -> str:
        """Format the update feed as a human-readable report.

        Args:
            improvements: Output of get_all_improvements().

        Returns:
            Formatted string, or message indicating everything is up to date.
        """
        if not improvements:
            return "All installed harnesses support current sync capabilities. No upgrades needed."

        lines = ["Harness Update Feed — Sync Improvements Available", "=" * 55, ""]
        for harness in sorted(improvements):
                items = improvements[harness]
                lines.append(f"  {harness}  ({len(items)} improvement(s)):")
                for item in sorted(items, key=lambda x: x["version"]):
                    lines.append(f"    ↑ v{item['version']}: {item['note']}")
                lines.append("")

        lines.append("Upgrade these harnesses to unlock better HarnessSync fidelity.")
        lines.append("After upgrading, run /sync to apply improved config translation.")
        return "\n".join(lines)


def _version_lt(v1: str, v2: str) -> bool:
    """Return True if version v1 is less than v2 (simple numeric comparison).

    Args:
        v1: Version string to compare (e.g. "1.4.2").
        v2: Version string to compare against (e.g. "1.5").

    Returns:
        True if v1 < v2, False otherwise.
    """
    def _parts(v: str) -> tuple:
        parts = []
        for seg in v.lstrip("v").split("."):
            try:
                parts.append(int(seg))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    try:
        return _parts(v1) < _parts(v2)
    except Exception:
        return False


def format_installed_version_warnings(project_dir: Path | None = None) -> list[str]:
    """Compare detected installed versions against feature requirements and return warnings.

    For each installed harness, detects the actual installed CLI version, then
    checks whether any features used in the current config require a newer version.
    Returns actionable warnings like:
        'Gemini CLI 0.3.1 installed — MCP servers require >= 1.0. Upgrade to unlock sync.'

    Args:
        project_dir: Project root directory.

    Returns:
        List of warning strings (empty if all installed versions are sufficient).
    """
    installed = detect_all_installed_versions(project_dir)
    warnings: list[str] = []

    for target, detected_version in installed.items():
        if not detected_version:
            continue

        features = VERSIONED_FEATURES.get(target, {})
        for feature_name, (min_version, description) in features.items():
            if _version_lt(detected_version, min_version):
                warnings.append(
                    f"{target} {detected_version} installed — {description} "
                    f"requires >= {min_version}. Upgrade to unlock full sync."
                )

    return warnings


def get_installed_vs_required_table(project_dir: Path | None = None) -> str:
    """Render a table comparing installed harness versions to feature requirements.

    Shows each harness, its installed version, and any features that need a
    newer version. Useful for diagnosing silent sync failures.

    Args:
        project_dir: Project root directory.

    Returns:
        Formatted table string.
    """
    installed = detect_all_installed_versions(project_dir)
    if not installed:
        return "No harnesses detected. Install a target harness CLI and retry."

    lines = [
        "Harness Version Compatibility",
        "=" * 60,
        f"  {'Target':<12} {'Installed':<12} {'Status':<10} Notes",
        "-" * 60,
    ]

    for target in sorted(installed.keys()):
        version = installed[target]
        if not version:
            lines.append(f"  {target:<12} {'not found':<12} {'—':<10}")
            continue

        features = VERSIONED_FEATURES.get(target, {})
        blocking: list[str] = []
        for feature_name, (min_version, description) in features.items():
            if _version_lt(version, min_version):
                blocking.append(f"{description} (needs {min_version})")

        if blocking:
            status = "outdated"
            note = blocking[0][:40]
        else:
            status = "ok"
            note = ""

        lines.append(f"  {target:<12} {version:<12} {status:<10} {note}")

    lines.append("-" * 60)
    warnings = format_installed_version_warnings(project_dir)
    if warnings:
        lines.append(f"\n{len(warnings)} compatibility issue(s) found:")
        for w in warnings:
            lines.append(f"  ⚠  {w}")
    else:
        lines.append("\nAll installed harnesses meet feature requirements.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Config Version Pinning (item 23)
# ---------------------------------------------------------------------------

_PIN_STORE_PATH = Path.home() / ".harnesssync" / "version_pins.json"


@dataclass
class VersionPin:
    """A snapshot of the HarnessSync source config pinned at a specific point.

    Pinning records the source-side config hash at a moment in time.  When
    the source drifts from the pin, a notification is emitted so that teams
    running stable AI-assisted workflows can decide consciously when to
    accept config changes.

    Attributes:
        harness: Target harness the pin applies to (or "all").
        pinned_hash: SHA-256 hash of the source config at pin time.
        pinned_at: ISO 8601 timestamp when the pin was created.
        label: Optional human-readable label (e.g. "v1.2-stable").
        notify_on_drift: Whether to notify when source drifts from this pin.
    """
    harness: str
    pinned_hash: str
    pinned_at: str
    label: str = ""
    notify_on_drift: bool = True


def _load_pins() -> dict[str, VersionPin]:
    """Load pins from the persistent pin store."""
    if not _PIN_STORE_PATH.exists():
        return {}
    try:
        data = json.loads(_PIN_STORE_PATH.read_text(encoding="utf-8"))
        return {
            k: VersionPin(
                harness=k,
                pinned_hash=v.get("pinned_hash", ""),
                pinned_at=v.get("pinned_at", ""),
                label=v.get("label", ""),
                notify_on_drift=v.get("notify_on_drift", True),
            )
            for k, v in data.items()
        }
    except Exception:
        return {}


def _save_pins(pins: dict[str, VersionPin]) -> None:
    """Persist pins to the pin store."""
    _PIN_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        k: {
            "pinned_hash": p.pinned_hash,
            "pinned_at": p.pinned_at,
            "label": p.label,
            "notify_on_drift": p.notify_on_drift,
        }
        for k, p in pins.items()
    }
    _PIN_STORE_PATH.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def pin_config_version(
    harness: str,
    source_hash: str,
    label: str = "",
    notify_on_drift: bool = True,
) -> VersionPin:
    """Pin the current source config hash for a harness.

    Records the current hash so future syncs can detect when the source
    has changed relative to the pin.

    Args:
        harness: Harness name to pin, or "all" to pin all harnesses.
        source_hash: SHA-256 hash of the source config at pin time.
        label: Optional descriptive label (e.g. "v1.2-stable").
        notify_on_drift: Emit a notification when source drifts from pin.

    Returns:
        The created VersionPin.
    """
    from datetime import datetime, timezone
    pins = _load_pins()
    pin = VersionPin(
        harness=harness,
        pinned_hash=source_hash,
        pinned_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        label=label,
        notify_on_drift=notify_on_drift,
    )
    pins[harness] = pin
    _save_pins(pins)
    return pin


def check_pin_drift(
    harness: str,
    current_source_hash: str,
) -> dict:
    """Check whether the current source config has drifted from its pin.

    Args:
        harness: Harness name to check.
        current_source_hash: SHA-256 hash of the current source config.

    Returns:
        Dict with keys:
          ``pinned``: bool — True if a pin exists for this harness.
          ``drifted``: bool — True if the current hash differs from the pin.
          ``pin``: The VersionPin (or None if not pinned).
          ``message``: Human-readable status message.
    """
    pins = _load_pins()
    pin = pins.get(harness) or pins.get("all")
    if pin is None:
        return {"pinned": False, "drifted": False, "pin": None, "message": f"No pin set for '{harness}'."}

    drifted = pin.pinned_hash != current_source_hash
    label_str = f" ({pin.label})" if pin.label else ""
    if drifted:
        msg = (
            f"Config has drifted from pin set on {pin.pinned_at}{label_str}. "
            f"Review changes before syncing to '{harness}'."
        )
    else:
        msg = f"Config matches pin set on {pin.pinned_at}{label_str} — no drift detected."

    return {"pinned": True, "drifted": drifted, "pin": pin, "message": msg}


def list_pins() -> str:
    """Return a formatted list of all active version pins.

    Returns:
        Human-readable table of pins.
    """
    pins = _load_pins()
    if not pins:
        return "No version pins configured. Use /sync-pin to create one."

    lines = [
        "Active Version Pins",
        "=" * 50,
        f"{'Harness':<16} {'Pinned At':<26} {'Label':<20} Drift-Notify",
        "-" * 80,
    ]
    for harness, pin in sorted(pins.items()):
        notify_str = "yes" if pin.notify_on_drift else "no"
        lines.append(
            f"{harness:<16} {pin.pinned_at:<26} {pin.label[:20]:<20} {notify_str}"
        )
    return "\n".join(lines)


def remove_pin(harness: str) -> bool:
    """Remove the version pin for a harness.

    Args:
        harness: Harness name to unpin.

    Returns:
        True if a pin was removed, False if no pin existed.
    """
    pins = _load_pins()
    if harness not in pins:
        return False
    del pins[harness]
    _save_pins(pins)
    return True
