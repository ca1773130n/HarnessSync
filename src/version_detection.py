from __future__ import annotations

"""Harness version detection and comparison utilities.

Detects installed harness CLI versions by running version commands, checking
application manifests, and comparing version strings.  Used by the compat
layer to determine which features a harness installation supports.
"""

from pathlib import Path


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
# Version parsing and comparison
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Pinned version loading
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Installed version detection
# ---------------------------------------------------------------------------

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
