from __future__ import annotations

"""Harness compatibility rules — feature matrices, deprecated fields, and checks.

Defines the versioned feature matrix and deprecated field registry for each
target harness.  Provides functions to check which features are supported at a
given harness version, generate compatibility warnings, and produce upgrade
requirement reports.
"""

from dataclasses import dataclass, field
from pathlib import Path

from src.version_detection import (
    _DEFAULT_VERSIONS,
    _parse_version,
    _version_gte,
    _version_lt,
    load_pinned_versions,
    detect_all_installed_versions,
)


# ---------------------------------------------------------------------------
# Versioned feature matrix
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Deprecated config fields registry
# ---------------------------------------------------------------------------

# Fields that HarnessSync adapters may write, but which have been deprecated
# by the target harness.  Format:
#   {harness: {field_name: (deprecated_since, migration_hint)}}
DEPRECATED_FIELDS: dict[str, dict[str, tuple[str, str]]] = {
    "cursor": {
        "description": (
            "0.41",
            "Use 'title' frontmatter instead of 'description' in .mdc files",
        ),
        ".cursorrules": (
            "0.42",
            "Migrate rules from .cursorrules to .cursor/rules/*.mdc files",
        ),
    },
    "codex": {
        "model": (
            "1.1",
            "Move 'model' into the [provider] table in codex config.toml",
        ),
    },
    "gemini": {
        "contextWindowSize": (
            "2.0",
            "'contextWindowSize' removed — use 'context.maxTokens' instead",
        ),
        "theme": (
            "1.8",
            "Move 'theme' to 'ui.theme' in Gemini settings.json",
        ),
    },
    "opencode": {
        "instructions": (
            "0.2",
            "Replace 'instructions' with 'system' in opencode config",
        ),
    },
    "aider": {
        "encoding": (
            "0.55",
            "Replace 'encoding' with 'input-encoding' in .aider.conf.yml",
        ),
    },
    "windsurf": {
        "globalRules": (
            "1.1",
            "Remove 'globalRules' key; place rules in .windsurfrules instead",
        ),
    },
}


# ---------------------------------------------------------------------------
# Deprecated field checking
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Version compatibility checking
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Upgrade requirements and instructions
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Installed version warnings and status table
# ---------------------------------------------------------------------------

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
# Capability upgrade suggestions
# ---------------------------------------------------------------------------

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
    from src.version_detection import _detect_installed_version

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
