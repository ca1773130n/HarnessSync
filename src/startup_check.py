from __future__ import annotations

"""Session-start drift check for HarnessSync (item 28).

Provides a lightweight drift summary suitable for the session startup hook.
Reads the last-known sync state and current source file hashes, then emits
a one-line summary if any targets are out of sync.

Designed to be fast (no subprocess calls, no network I/O) and silent on success
so it doesn't interrupt the normal workflow.

Example output (when drift detected):
    [HarnessSync] 2 target(s) out of sync (codex, gemini) — run /sync to update
"""

from datetime import datetime
from pathlib import Path

from src.state_manager import StateManager
from src.utils.hashing import hash_file_sha256


# Source files to watch for drift
_SOURCE_FILES = [
    "CLAUDE.md",
    "CLAUDE.local.md",
    ".claude/CLAUDE.md",
    ".mcp.json",
    ".claude/settings.json",
    ".claude/settings.local.json",
]

_USER_SOURCE_FILES = [
    "CLAUDE.md",
    ".mcp.json",
    "settings.json",
]


def check_drift_brief(
    project_dir: Path | None = None,
    cc_home: Path | None = None,
) -> str | None:
    """Check if any targets are out of sync and return a one-line summary.

    Compares current source file hashes against the last recorded sync hashes.
    This is designed to be called at session start (fast, read-only).

    Args:
        project_dir: Project root directory (uses cwd if None)
        cc_home: Claude Code home directory (uses ~/.claude if None)

    Returns:
        One-line summary string if any targets are out of sync, or None if all
        targets are up to date (or no state has been recorded yet).
    """
    project_dir = project_dir or Path.cwd()
    cc_home = cc_home or (Path.home() / ".claude")

    try:
        state = StateManager()
    except Exception:
        return None

    # Collect current source file hashes
    current_hashes: dict[str, str] = {}

    for fname in _SOURCE_FILES:
        p = project_dir / fname
        if p.is_file():
            h = hash_file_sha256(p)
            if h:
                current_hashes[str(p)] = h

    for fname in _USER_SOURCE_FILES:
        p = cc_home / fname
        if p.is_file():
            h = hash_file_sha256(p)
            if h:
                current_hashes[str(p)] = h

    if not current_hashes:
        return None  # No source files found — nothing to check

    # Check drift for all known targets
    all_state = state.get_all_status()
    targets_checked = list(all_state.get("targets", {}).keys())

    # Also check account targets
    for account_data in all_state.get("accounts", {}).values():
        for t in account_data.get("targets", {}).keys():
            if t not in targets_checked:
                targets_checked.append(t)

    if not targets_checked:
        return None  # No sync history — first run

    drifted_targets = []
    for target in targets_checked:
        drifted = state.detect_drift(target, current_hashes)
        if drifted:
            drifted_targets.append(target)

    if not drifted_targets:
        return None

    count = len(drifted_targets)
    names = ", ".join(sorted(drifted_targets)[:5])
    if len(drifted_targets) > 5:
        names += f", +{len(drifted_targets) - 5} more"

    return f"[HarnessSync] {count} target(s) out of sync ({names}) — run /sync to update"


def check_drift_detailed(
    project_dir: Path | None = None,
    cc_home: Path | None = None,
) -> dict:
    """Return detailed drift info for each target.

    Args:
        project_dir: Project root directory
        cc_home: Claude Code home directory

    Returns:
        Dict mapping target_name -> list of drifted file paths.
        Empty dict if no drift detected or no state exists.
    """
    project_dir = project_dir or Path.cwd()
    cc_home = cc_home or (Path.home() / ".claude")

    try:
        state = StateManager()
    except Exception:
        return {}

    current_hashes: dict[str, str] = {}
    for fname in _SOURCE_FILES:
        p = project_dir / fname
        if p.is_file():
            h = hash_file_sha256(p)
            if h:
                current_hashes[str(p)] = h
    for fname in _USER_SOURCE_FILES:
        p = cc_home / fname
        if p.is_file():
            h = hash_file_sha256(p)
            if h:
                current_hashes[str(p)] = h

    all_state = state.get_all_status()
    targets = list(all_state.get("targets", {}).keys())

    result: dict[str, list[str]] = {}
    for target in targets:
        drifted = state.detect_drift(target, current_hashes)
        if drifted:
            result[target] = drifted

    return result


def format_startup_message(project_dir: Path | None = None) -> str | None:
    """Return a formatted startup message if drift is detected.

    Suitable for display in hooks/startup scripts. Returns None if no drift.
    """
    return check_drift_brief(project_dir)
