from __future__ import annotations

"""
/sync-dashboard slash command implementation.

Shows a live terminal UI with sync status, drift level, and health metrics
for each configured target harness. Refreshes every N seconds until Ctrl+C.

A single-pane-of-glass view for multi-harness sync health.
"""

import os
import sys
import shlex
import argparse
import subprocess
import time

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from datetime import datetime
from pathlib import Path


def _clear_screen() -> None:
    """Clear terminal screen using ANSI escape code."""
    print("\033[2J\033[H", end="", flush=True)


def _format_age(ts: float | None) -> str:
    """Format seconds-since-epoch into human-readable age string."""
    if ts is None:
        return "never"
    now = time.time()
    delta = now - ts
    if delta < 60:
        return f"{int(delta)}s ago"
    elif delta < 3600:
        return f"{int(delta / 60)}m ago"
    elif delta < 86400:
        return f"{int(delta / 3600)}h ago"
    else:
        return f"{int(delta / 86400)}d ago"


def _health_icon(status: str) -> str:
    """Return a health icon for the given status string."""
    icons = {
        "ok":      "✓",
        "synced":  "✓",
        "warn":    "~",
        "partial": "~",
        "error":   "✗",
        "failed":  "✗",
        "unknown": "?",
        "never":   "○",
    }
    return icons.get(status, "?")


def _get_target_health(target_status: dict, conflicts: list) -> str:
    """Determine overall health string for a target."""
    if not target_status.get("last_sync_time"):
        return "never"
    if conflicts:
        return "warn"
    fail_count = target_status.get("last_sync_counts", {}).get("failed", 0)
    if fail_count > 0:
        return "partial"
    return "ok"


def _render_dashboard(project_dir: Path, account: str | None) -> str:
    """Build the dashboard frame string.

    Args:
        project_dir: Current project root.
        account: Optional account name.

    Returns:
        Full dashboard text to print.
    """
    from src.state_manager import StateManager
    from src.conflict_detector import ConflictDetector
    from src.changelog_manager import ChangelogManager

    state = StateManager()
    detector = ConflictDetector(state_manager=state)
    changelog = ChangelogManager(project_dir=project_dir)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = "HarnessSync Dashboard"
    if account:
        header += f" — {account}"

    lines: list[str] = [
        f"{'=' * 60}",
        f"  {header}",
        f"  Updated: {now_str}",
        f"{'=' * 60}",
        "",
    ]

    # Get all known targets
    all_status: dict[str, dict] = {}
    if hasattr(state, "get_all_targets_status"):
        all_status = state.get_all_targets_status() or {}
    if not all_status:
        # Fallback: enumerate known adapters
        try:
            from src.adapters import AdapterRegistry
            reg = AdapterRegistry(project_dir)
            all_status = {
                name: state.get_target_status(name) or {}
                for name in reg.list_adapters()
            }
        except Exception:
            all_status = {}

    if not all_status:
        lines.append("  No sync targets configured. Run /sync-setup to add targets.")
        return "\n".join(lines)

    # Get conflicts once
    try:
        all_conflicts: dict[str, list] = detector.check_all()
    except Exception:
        all_conflicts = {}

    # Render per-target rows
    col_target = 12
    col_health = 8
    col_synced = 12
    col_drift = 12
    col_items = 8

    lines.append(
        f"  {'Target':<{col_target}} {'Health':<{col_health}} "
        f"{'Last Sync':<{col_synced}} {'Drift':<{col_drift}} {'Items':>{col_items}}"
    )
    lines.append("  " + "-" * (col_target + col_health + col_synced + col_drift + col_items + 4))

    for target_name, status in sorted(all_status.items()):
        if status is None:
            status = {}
        conflicts = all_conflicts.get(target_name, [])
        health = _get_target_health(status, conflicts)
        icon = _health_icon(health)

        last_sync_ts = status.get("last_sync_time")
        age = _format_age(last_sync_ts)

        # Drift level from state or inferred
        drift_level = status.get("drift_level", "unknown")
        if not last_sync_ts:
            drift_level = "unknown"
        elif conflicts:
            drift_level = "high"

        counts = status.get("last_sync_counts", {})
        total_items = sum(
            v for k, v in counts.items()
            if k in ("rules", "skills", "agents", "commands", "mcp")
        )
        items_str = str(total_items) if total_items else "-"
        conflict_note = f"  [{len(conflicts)} conflict(s)]" if conflicts else ""

        lines.append(
            f"  {icon} {target_name:<{col_target - 2}} "
            f"{health:<{col_health}} "
            f"{age:<{col_synced}} "
            f"{drift_level:<{col_drift}} "
            f"{items_str:>{col_items}}"
            f"{conflict_note}"
        )

    lines.append("")
    lines.append("  Legend: ✓ synced  ~ warning  ✗ error  ○ never synced")
    lines.append("")

    # Recent sync activity from changelog
    try:
        changelog_text = changelog.read()
        if changelog_text:
            recent_entries = [
                ln for ln in changelog_text.splitlines()
                if ln.startswith("##")
            ][-3:]
            if recent_entries:
                lines.append("  Recent syncs:")
                for entry in reversed(recent_entries):
                    lines.append(f"    {entry.lstrip('#').strip()}")
    except Exception:
        pass

    lines.append("")

    # Capability gap summary — which features are missing per target
    try:
        from src.compatibility_reporter import GapTracker
        gap_tracker = GapTracker()
        all_gaps = gap_tracker.get_gaps()
        if all_gaps:
            open_gaps = [g for g in all_gaps if not getattr(g, "resolved", False)]
            if open_gaps:
                # Group by target for compact display
                gap_by_target: dict[str, list[str]] = {}
                for g in open_gaps:
                    t = getattr(g, "target", "?")
                    f = getattr(g, "feature", "?")
                    gap_by_target.setdefault(t, []).append(f)

                lines.append("  Capability Gaps:")
                for tgt in sorted(gap_by_target):
                    features = ", ".join(sorted(gap_by_target[tgt]))
                    lines.append(f"    {tgt:<14} missing: {features}")
                lines.append("  Run /sync-gaps for details and upstream issue links.")
                lines.append("")
    except Exception:
        pass

    lines.append("  Press Ctrl+C to exit  |  /sync to run sync  |  /sync-status for details")

    return "\n".join(lines)


def main() -> None:
    """Entry point for /sync-dashboard command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-dashboard",
        description="Live terminal dashboard showing sync status for all harness targets",
    )
    parser.add_argument(
        "--refresh",
        type=int,
        default=0,
        help="Refresh interval in seconds (0 = show once and exit, default: 0)",
    )
    parser.add_argument("--account", type=str, default=None, help="Account name")
    parser.add_argument("--project-dir", type=str, default=None)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Auto-refresh every 30 seconds until Ctrl+C (same as --refresh 30)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    refresh = args.refresh
    if args.live and refresh == 0:
        refresh = 30

    if refresh > 0:
        try:
            while True:
                _clear_screen()
                print(_render_dashboard(project_dir, args.account))
                time.sleep(refresh)
        except KeyboardInterrupt:
            print("\nDashboard stopped.")
    else:
        print(_render_dashboard(project_dir, args.account))


if __name__ == "__main__":
    main()
