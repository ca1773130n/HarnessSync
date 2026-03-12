from __future__ import annotations

"""
/sync-pause slash command — pause or resume HarnessSync auto-sync.

Usage:
    /sync-pause                     Pause sync indefinitely
    /sync-pause --reason "text"     Pause with a descriptive reason
    /sync-pause --duration 30       Pause for 30 minutes, then auto-resume
    /sync-pause --resume            Resume a paused sync
    /sync-pause --status            Show current pause status

While paused:
  - /sync commands still run (this is manual sync, which is intentional)
  - Auto-sync PostToolUse hooks are suppressed
  - A warning banner is shown when any sync is attempted

Examples:
    /sync-pause --reason "debugging Gemini config" --duration 30
    /sync-pause --resume
    /sync-pause --status
"""

import argparse
import os
import shlex
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.sync_pauser import SyncPauser


def main() -> None:
    """Entry point for /sync-pause command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-pause",
        description="Pause or resume HarnessSync auto-sync operations",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume sync (lift the pause)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current pause status",
    )
    parser.add_argument(
        "--reason",
        default="",
        help="Reason for pausing (shown in status)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        metavar="MINUTES",
        help="Auto-resume after MINUTES minutes",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    pauser = SyncPauser()

    if args.status:
        print(pauser.format_status())
        return

    if args.resume:
        was_paused = pauser.resume()
        if was_paused:
            print("Sync resumed. Auto-sync operations are now active.")
        else:
            print("Sync was not paused — nothing to resume.")
        return

    # Default: pause
    state = pauser.pause(reason=args.reason, duration_minutes=args.duration)
    reason_str = f": {state['reason']}" if state.get("reason") else ""
    print(f"Sync PAUSED{reason_str}")
    if state.get("resume_at"):
        print(f"Auto-resume scheduled at: {state['resume_at']}")
    else:
        print("Run '/sync-pause --resume' to re-enable auto-sync.")


if __name__ == "__main__":
    main()
