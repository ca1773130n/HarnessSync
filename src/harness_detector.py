from __future__ import annotations

"""New AI harness auto-detector.

Periodically scans PATH and common install locations for AI coding CLIs
that have not yet been added as HarnessSync targets. Surfaces newly
discovered harnesses so users don't forget to configure them.
"""

import shutil

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


def detect_new_harnesses(already_configured: list[str]) -> list[str]:
    """Scan PATH for AI coding CLIs not in the configured target list.

    Args:
        already_configured: List of target names already configured in
                            HarnessSync (e.g. ["codex", "gemini", "opencode"]).

    Returns:
        Sorted list of canonical harness names found in PATH but not yet
        configured. Empty list if nothing new is found.
    """
    configured_set = set(already_configured)
    found: dict[str, str] = {}  # canonical_name -> executable

    for exe, canonical in _KNOWN_AI_CLIS.items():
        if canonical in configured_set:
            continue  # Already managed — skip
        if canonical in found:
            continue  # Already detected via another exe name

        path = shutil.which(exe)
        if path:
            found[canonical] = exe

    return sorted(found.keys())


def scan_all() -> dict[str, str]:
    """Scan PATH for all known AI coding CLIs.

    Returns:
        Dict mapping canonical harness name -> executable path for all
        CLIs found in PATH regardless of configuration status.
    """
    result: dict[str, str] = {}

    for exe, canonical in _KNOWN_AI_CLIS.items():
        if canonical in result:
            continue
        path = shutil.which(exe)
        if path:
            result[canonical] = path

    return result
