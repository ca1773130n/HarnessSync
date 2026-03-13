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
    parser.add_argument(
        "--export-json",
        type=str,
        default=None,
        metavar="OUTPUT_FILE",
        help="Export full sync history as machine-queryable JSON to OUTPUT_FILE",
    )
    parser.add_argument(
        "--export-csv",
        type=str,
        default=None,
        metavar="OUTPUT_FILE",
        help="Export full sync history as CSV (for spreadsheet analysis) to OUTPUT_FILE",
    )
    parser.add_argument(
        "--ascii-timeline",
        action="store_true",
        help="Render a visual ASCII bar chart showing sync event density by day",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    changelog = ChangelogManager(project_dir)

    # Handle export modes before other actions
    if getattr(args, "export_json", None):
        output_path = Path(args.export_json)
        result = changelog.export_json(output_path=output_path)
        if args.export_json == "-":
            print(result)
        else:
            print(f"Sync history exported as JSON to: {output_path}")
        return

    if getattr(args, "export_csv", None):
        output_path = Path(args.export_csv)
        result = changelog.export_csv(output_path=output_path)
        if args.export_csv == "-":
            print(result)
        else:
            print(f"Sync history exported as CSV to: {output_path}")
        return

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

    if getattr(args, "ascii_timeline", False):
        print(_render_ascii_timeline(entries))
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


def _render_ascii_timeline(entries: list[str], width: int = 72) -> str:
    """Render a visual ASCII bar chart showing sync frequency by date.

    Parses ISO dates from changelog entries and produces a bar chart where
    each row represents a day and the bar length indicates how many syncs
    occurred on that day. The last 30 days are shown.

    Args:
        entries: List of changelog entry strings.
        width: Total character width for the chart (label + bar + count).

    Returns:
        Formatted ASCII timeline string.
    """
    import re
    from collections import Counter

    # Extract dates from each entry (first YYYY-MM-DD match)
    date_re = re.compile(r"\d{4}-\d{2}-\d{2}")
    date_counts: Counter = Counter()
    for entry in entries:
        m = date_re.search(entry)
        if m:
            date_counts[m.group()] += 1

    if not date_counts:
        return "No dated sync entries found in the log."

    # Show only the most-recent 30 days that have entries, sorted ascending
    sorted_dates = sorted(date_counts.keys())[-30:]
    max_count = max(date_counts[d] for d in sorted_dates) or 1
    label_w = 10   # "YYYY-MM-DD"
    count_w = 4    # " (N)"
    bar_w = max(10, width - label_w - count_w - 4)

    lines: list[str] = [
        "HarnessSync — Sync Events Timeline",
        "=" * width,
        f"{'Date':<{label_w}}  {'Events':>{bar_w + count_w}}",
        "─" * width,
    ]

    bar_chars = "█"
    for date in sorted_dates:
        count = date_counts[date]
        filled = max(1, round(count / max_count * bar_w))
        bar = bar_chars * filled
        lines.append(f"{date:<{label_w}}  {bar:<{bar_w}} ({count})")

    lines.append("─" * width)
    total = sum(date_counts[d] for d in sorted_dates)
    lines.append(f"Total: {total} sync event(s) across {len(sorted_dates)} day(s)")
    if len(date_counts) > 30:
        lines.append(f"(Showing most recent 30 of {len(date_counts)} days)")
    return "\n".join(lines)


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
