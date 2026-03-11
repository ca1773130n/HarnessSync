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
