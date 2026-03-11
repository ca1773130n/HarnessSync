from __future__ import annotations

"""
/sync-log slash command implementation.

Displays the persistent sync audit log (changelog.md) with optional filtering.
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.changelog_manager import ChangelogManager


def main() -> None:
    """Entry point for /sync-log command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(prog="sync-log", description="Show sync audit log")
    parser.add_argument(
        "--tail",
        type=int,
        default=None,
        metavar="N",
        help="Show only the last N entries (default: all)",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear the sync log (irreversible)",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        help="Project directory (default: cwd)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    changelog = ChangelogManager(project_dir)

    if args.clear:
        log_path = project_dir / ".harness-sync" / "changelog.md"
        if log_path.exists():
            log_path.unlink()
            print("Sync log cleared.")
        else:
            print("No sync log found.")
        return

    content = changelog.read()
    if not content.strip():
        print("No sync history found. Run /sync to create the first log entry.")
        return

    # Split into entries (each starts with "## ")
    entries = _split_entries(content)

    if args.tail is not None:
        entries = entries[-args.tail:]

    if not entries:
        print("No entries match the filter.")
        return

    print("HarnessSync Audit Log")
    print("=" * 60)
    print()
    print("".join(entries))


def _split_entries(content: str) -> list[str]:
    """Split changelog content into individual entries."""
    lines = content.splitlines(keepends=True)
    entries: list[str] = []
    current: list[str] = []

    for line in lines:
        if line.startswith("## ") and current:
            entries.append("".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        entries.append("".join(current))

    return entries


if __name__ == "__main__":
    main()
