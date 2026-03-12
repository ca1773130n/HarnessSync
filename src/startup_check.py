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

from datetime import datetime, timedelta, timezone
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


def check_harness_updates(cache_dir: Path | None = None) -> str | None:
    """Check for newly installed or updated harnesses and return a notice.

    Detects harnesses that have been installed or updated since the last
    HarnessSync run. Surfaces a short notification so users know new sync
    capabilities may be available.

    Args:
        cache_dir: Directory for the version cache.
                   Default: ~/.harnesssync/

    Returns:
        Formatted notice string, or None if no updates detected.
    """
    try:
        from src.harness_detector import detect_version_updates, format_version_update_report
        updates = detect_version_updates(cache_dir=cache_dir)
        report = format_version_update_report(updates)
        return report or None
    except Exception:
        return None


def check_team_broadcast(project_dir: Path | None = None) -> str | None:
    """Auto-pull team broadcast config if the local copy is stale.

    Reads the configured ``team_broadcast_repo`` and ``team_broadcast_branch``
    from the project's ``.harnesssync`` file. If present and the last pull is
    older than ``team_broadcast_max_age_hours`` (default: 24), pulls the team
    config and returns a summary notice.

    This is intentionally silent on success to keep session start non-intrusive.
    It only surfaces a notice when a pull actually occurs or when an error happens.

    Args:
        project_dir: Project root directory (uses cwd if None).

    Returns:
        Notice string if a pull was performed or failed, None if fresh or not configured.
    """
    project_dir = project_dir or Path.cwd()
    config_path = project_dir / ".harnesssync"
    if not config_path.exists():
        return None

    try:
        import json as _json
        cfg = _json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    repo = cfg.get("team_broadcast_repo", "")
    if not repo:
        return None

    branch = cfg.get("team_broadcast_branch", "team-config")
    max_age_hours = float(cfg.get("team_broadcast_max_age_hours", 24.0))

    try:
        from src.team_broadcast import TeamBroadcast
        broadcaster = TeamBroadcast(project_dir)
        result = broadcaster.check_and_auto_pull(
            repo=repo,
            branch=branch,
            max_age_hours=max_age_hours,
        )
    except Exception as e:
        return f"[HarnessSync] Team broadcast check failed: {e}"

    if result is None:
        return None  # Still fresh

    if result.success:
        count = len(result.files_included)
        return (
            f"[HarnessSync] Team config pulled from {branch} "
            f"({count} file(s) updated) — run /sync to apply"
        )
    else:
        errs = "; ".join(result.errors[:2])
        return f"[HarnessSync] Team broadcast pull failed: {errs}"


def check_schedule_staleness(project_dir: Path | None = None) -> str | None:
    """Warn if the scheduled sync interval has elapsed without a sync.

    Reads the sync schedule config from ``.harnesssync`` and compares the
    last sync timestamp from StateManager. If the scheduled interval has
    elapsed, returns a warning encouraging the user to sync.

    Args:
        project_dir: Project root directory (uses cwd if None).

    Returns:
        Warning string if sync is overdue, None otherwise.
    """
    project_dir = project_dir or Path.cwd()

    # Read sync_interval_hours from .harnesssync if present
    sync_interval_hours: float | None = None
    config_path = project_dir / ".harnesssync"
    if config_path.exists():
        try:
            import json as _json
            cfg = _json.loads(config_path.read_text(encoding="utf-8"))
            interval = cfg.get("sync_interval_hours")
            if interval is not None:
                sync_interval_hours = float(interval)
        except (OSError, ValueError):
            pass

    if sync_interval_hours is None:
        return None  # No schedule configured

    try:
        state = StateManager()
        last_sync_str = state.last_sync
        if not last_sync_str:
            return (
                f"[HarnessSync] Sync scheduled every {sync_interval_hours:.0f}h "
                f"but no sync has been run yet — run /sync"
            )
        last_sync = datetime.fromisoformat(last_sync_str)
        if last_sync.tzinfo is None:
            last_sync = last_sync.replace(tzinfo=timezone.utc)
        age = datetime.now(timezone.utc) - last_sync
        if age > timedelta(hours=sync_interval_hours):
            hours_ago = round(age.total_seconds() / 3600, 1)
            return (
                f"[HarnessSync] Sync is {hours_ago}h overdue "
                f"(scheduled every {sync_interval_hours:.0f}h) — run /sync"
            )
    except Exception:
        pass

    return None


def full_startup_check(project_dir: Path | None = None) -> list[str]:
    """Run all startup checks and return a list of notice strings.

    Combines drift detection, harness version update detection, team broadcast
    auto-pull, and schedule staleness warnings into a single call suitable for
    use in SessionStart hooks or shell prompts.

    Args:
        project_dir: Project root directory (optional).

    Returns:
        List of notice strings (may be empty if everything is up to date).
        Each string is a self-contained message suitable for printing.
    """
    notices: list[str] = []

    drift_msg = format_startup_message(project_dir)
    if drift_msg:
        notices.append(drift_msg)

    update_msg = check_harness_updates()
    if update_msg:
        notices.append(update_msg)

    broadcast_msg = check_team_broadcast(project_dir)
    if broadcast_msg:
        notices.append(broadcast_msg)

    staleness_msg = check_schedule_staleness(project_dir)
    if staleness_msg:
        notices.append(staleness_msg)

    return notices
