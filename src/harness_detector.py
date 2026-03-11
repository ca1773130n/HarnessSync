from __future__ import annotations

"""New AI harness auto-detector.

Periodically scans PATH and common install locations for AI coding CLIs
that have not yet been added as HarnessSync targets. Surfaces newly
discovered harnesses so users don't forget to configure them.

Detection strategy (item 7):
1. PATH scan: check if the CLI executable is in PATH
2. Config-dir scan: check if the harness config directory exists on disk
   (catches harnesses installed as GUI apps that don't add to PATH)
"""

import shutil
from pathlib import Path

# Known AI coding CLI executables mapped to their canonical names
_KNOWN_AI_CLIS: dict[str, str] = {
    "codex": "codex",
    "gemini": "gemini",
    "opencode": "opencode",
    "opencode-cli": "opencode",
    "cursor": "cursor",
    "cursor-cli": "cursor",
    "windsurf": "windsurf",
    "windsurf-cli": "windsurf",
    "aider": "aider",
    "continue": "continue",
    "cody": "cody",
    "copilot": "copilot",
    "gh-copilot": "copilot",
    "tabby": "tabby",
    "supermaven": "supermaven",
    "codeium": "codeium",
}

# Config directory patterns per canonical harness name.
# Paths are relative to $HOME. Multiple candidates per harness (tried in order).
_CONFIG_DIR_PATTERNS: dict[str, list[str]] = {
    "codex": [".codex", ".config/codex"],
    "gemini": [".gemini", ".config/gemini-cli"],
    "opencode": [".config/opencode", ".opencode"],
    "cursor": [".cursor", ".config/Cursor", "Library/Application Support/Cursor"],
    "windsurf": [".windsurf", ".config/windsurf", "Library/Application Support/windsurf"],
    "aider": [".aider", ".config/aider"],
    "continue": [".continue", ".config/continue"],
    "cody": [".config/cody", ".cody"],
    "copilot": [".config/gh/copilot", ".copilot"],
}


def _check_config_dir(canonical: str) -> bool:
    """Return True if any known config directory for the harness exists."""
    home = Path.home()
    for pattern in _CONFIG_DIR_PATTERNS.get(canonical, []):
        if (home / pattern).exists():
            return True
    return False


def detect_new_harnesses(already_configured: list[str]) -> list[str]:
    """Scan PATH and config directories for AI coding CLIs not yet configured.

    Detection uses two signals (either is sufficient):
    - Executable found in PATH (CLI-installed tools)
    - Config directory exists in $HOME (GUI-installed tools)

    Args:
        already_configured: List of target names already configured in
                            HarnessSync (e.g. ["codex", "gemini", "opencode"]).

    Returns:
        Sorted list of canonical harness names found but not yet configured.
        Empty list if nothing new is found.
    """
    configured_set = set(already_configured)
    found: set[str] = set()

    # PATH scan
    for exe, canonical in _KNOWN_AI_CLIS.items():
        if canonical in configured_set or canonical in found:
            continue
        if shutil.which(exe):
            found.add(canonical)

    # Config-dir scan (catches GUI apps not in PATH)
    all_canonicals = set(_KNOWN_AI_CLIS.values())
    for canonical in all_canonicals:
        if canonical in configured_set or canonical in found:
            continue
        if _check_config_dir(canonical):
            found.add(canonical)

    return sorted(found)


def scan_all() -> dict[str, dict]:
    """Scan PATH and config directories for all known AI coding CLIs.

    Returns:
        Dict mapping canonical harness name -> detection info dict:
        {
            "in_path": bool,       # found via PATH scan
            "config_dir": bool,    # found via config directory scan
            "executable": str|None # executable path if found in PATH
        }
    """
    result: dict[str, dict] = {}

    all_canonicals = set(_KNOWN_AI_CLIS.values())

    # PATH scan
    path_found: dict[str, str] = {}
    for exe, canonical in _KNOWN_AI_CLIS.items():
        if canonical in path_found:
            continue
        p = shutil.which(exe)
        if p:
            path_found[canonical] = p

    for canonical in all_canonicals:
        in_path = canonical in path_found
        config_dir = _check_config_dir(canonical)
        if in_path or config_dir:
            result[canonical] = {
                "in_path": in_path,
                "config_dir": config_dir,
                "executable": path_found.get(canonical),
            }

    return result
