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
        "--interactive",
        action="store_true",
        help="Interactive timeline explorer — browse entries with pagination, "
             "search, and git-based config restore",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        metavar="TARGET",
        help="Filter entries by target harness name (e.g. codex, gemini)",
    )
    parser.add_argument(
        "--since",
        type=str,
        default=None,
        metavar="DATE",
        help="Show entries since a date (YYYY-MM-DD format)",
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

    # Apply filters
    if getattr(args, "target", None):
        entries = [e for e in entries if args.target.lower() in e.lower()]
    if getattr(args, "since", None):
        entries = [e for e in entries if _entry_is_since(e, args.since)]

    if args.tail is not None:
        entries = entries[-args.tail:]

    if not entries:
        print("No entries match the filter.")
        return

    if getattr(args, "interactive", False) and sys.stdin.isatty():
        _run_interactive_timeline(entries, project_dir)
        return

    print("HarnessSync Audit Log")
    print("=" * 60)
    print()
    print("".join(entries))


def _entry_is_since(entry: str, since_date: str) -> bool:
    """Return True if the entry's date is >= since_date (YYYY-MM-DD).

    Args:
        entry: Changelog entry text.
        since_date: ISO date string "YYYY-MM-DD".

    Returns:
        True if the entry date is on or after since_date.
    """
    import re
    match = re.search(r"\d{4}-\d{2}-\d{2}", entry)
    if not match:
        return True  # Include entries where date can't be parsed
    return match.group() >= since_date


def _run_interactive_timeline(entries: list[str], project_dir: Path) -> None:
    """Run a paginated interactive timeline explorer.

    Shows entries one page at a time. Commands:
      n / Enter  — next page
      p          — previous page
      q          — quit
      s <term>   — search entries for a term
      g <sha>    — git show config at that commit (uses ConfigTimeMachine)

    Args:
        entries: Parsed changelog entries (newest last).
        project_dir: Project root for git operations.
    """
    page_size = 5
    current_page = 0
    search_term: str | None = None
    filtered = list(reversed(entries))  # Show newest first

    def _apply_search(term: str) -> list[str]:
        return [e for e in reversed(entries) if term.lower() in e.lower()]

    while True:
        display = filtered
        total_pages = max(1, (len(display) + page_size - 1) // page_size)
        start = current_page * page_size
        page_entries = display[start:start + page_size]

        print("\033[2J\033[H", end="")  # Clear screen
        print("HarnessSync Sync Timeline  (interactive)")
        print("=" * 60)
        if search_term:
            print(f"Search: '{search_term}' — {len(display)} result(s)")
        print(f"Page {current_page + 1}/{total_pages}  ({len(entries)} total entries)")
        print()

        if not page_entries:
            print("No entries to display.")
        else:
            for i, entry in enumerate(page_entries, start=start + 1):
                # Show first 3 lines of each entry for brevity
                lines = entry.strip().splitlines()[:4]
                print(f"[{i}] " + "\n    ".join(lines))
                print()

        print("-" * 60)
        print("Commands: n=next  p=prev  q=quit  s <term>=search  r=reset")
        try:
            cmd = input("> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd or cmd == "n":
            if current_page < total_pages - 1:
                current_page += 1
        elif cmd == "p":
            if current_page > 0:
                current_page -= 1
        elif cmd == "q":
            break
        elif cmd == "r":
            filtered = list(reversed(entries))
            search_term = None
            current_page = 0
        elif cmd.startswith("s "):
            search_term = cmd[2:].strip()
            if search_term:
                filtered = _apply_search(search_term)
                current_page = 0
        elif cmd.startswith("g "):
            sha = cmd[2:].strip()
            if sha:
                try:
                    from src.config_time_machine import ConfigTimeMachine
                    ctm = ConfigTimeMachine(project_dir)
                    print(f"\n--- CLAUDE.md at {sha} ---")
                    print(ctm.show_at(sha))
                    input("\nPress Enter to continue...")
                except Exception as exc:
                    print(f"Error: {exc}")
                    input("Press Enter to continue...")

    print("Timeline closed.")


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
