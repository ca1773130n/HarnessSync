from __future__ import annotations

"""
/sync-history slash command — Config Time Travel browser.

Browse, search, and restore CLAUDE.md config history from git commits.
Wraps ConfigTimeMachine to give a git-log-style interface for config changes.

Usage:
    /sync-history                       List recent config-touching commits
    /sync-history --search "TDD"        Search commit messages
    /sync-history --since 2026-01-01    Show commits after a date
    /sync-history --show <SHA>          Show CLAUDE.md content at a commit
    /sync-history --diff <SHA1> <SHA2>  Diff between two commits
    /sync-history --restore <SHA> [--target codex]  Re-sync from past state

Options:
    --search QUERY          Filter commits by message keyword
    --since DATE            Start date filter (ISO format: YYYY-MM-DD)
    --until DATE            End date filter
    --author NAME           Filter by author name (substring)
    --show SHA              Print CLAUDE.md content at this commit
    --diff SHA1 SHA2        Show diff between two commits
    --restore SHA           Re-sync target harnesses from this past state
    --target TARGETS        Comma-separated target list for --restore
    --limit N               Max commits to show (default: 20)
    --snapshots             List named snapshots instead of git history
    --snapshot-save NAME    Save the current config as a named snapshot
    --snapshot-restore NAME Restore a named snapshot to a temp directory
    --project-dir PATH      Project directory (default: cwd)
    --json                  Output in JSON format
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.config_time_machine import ConfigTimeMachine


def main() -> None:
    """Entry point for /sync-history command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-history",
        description="Browse config git history and restore past states",
    )
    parser.add_argument(
        "--search", metavar="QUERY", default=None,
        help="Filter commits by message keyword",
    )
    parser.add_argument(
        "--since", metavar="DATE", default=None,
        help="Show commits on or after this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--until", metavar="DATE", default=None,
        help="Show commits on or before this date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--author", metavar="NAME", default=None,
        help="Filter by author name (substring match)",
    )
    parser.add_argument(
        "--show", metavar="SHA", default=None,
        help="Print CLAUDE.md content at this commit SHA",
    )
    parser.add_argument(
        "--diff", nargs=2, metavar=("SHA1", "SHA2"), default=None,
        help="Show diff of CLAUDE.md between two commits",
    )
    parser.add_argument(
        "--restore", metavar="SHA", default=None,
        help="Re-sync target harnesses from the CLAUDE.md at this commit",
    )
    parser.add_argument(
        "--target", metavar="TARGETS", default=None,
        help="Comma-separated targets for --restore (default: all)",
    )
    parser.add_argument(
        "--limit", type=int, default=20,
        help="Maximum commits to display (default: 20)",
    )
    parser.add_argument(
        "--snapshots", action="store_true",
        help="List named snapshots instead of git history",
    )
    parser.add_argument(
        "--snapshot-save", metavar="NAME", default=None, dest="snapshot_save",
        help="Save current config as a named snapshot",
    )
    parser.add_argument(
        "--snapshot-restore", metavar="NAME", default=None, dest="snapshot_restore",
        help="Restore a named snapshot to a temp directory for inspection",
    )
    parser.add_argument(
        "--file", metavar="PATH", default=None,
        help="Config file to show/diff (default: CLAUDE.md)",
    )
    parser.add_argument(
        "--json", action="store_true", dest="output_json",
        help="Output in JSON format",
    )
    parser.add_argument(
        "--project-dir", metavar="PATH", default=None, dest="project_dir",
        help="Project root directory (default: cwd)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(
        args.project_dir
        or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    )

    try:
        tm = ConfigTimeMachine(project_dir=project_dir)
    except Exception as exc:
        print(f"Error initializing time machine: {exc}", file=sys.stderr)
        sys.exit(1)

    # ── Snapshot save ──────────────────────────────────────────────────
    if args.snapshot_save:
        try:
            entry = tm.take_snapshot(args.snapshot_save)
            if args.output_json:
                print(json.dumps({
                    "name": entry.name,
                    "timestamp": entry.timestamp,
                    "files": list(entry.files.keys()),
                }))
            else:
                print(f"Snapshot '{entry.name}' saved at {entry.timestamp[:19]}.")
                print(f"  Files captured: {', '.join(sorted(entry.files.keys()))}")
        except Exception as exc:
            print(f"Error saving snapshot: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # ── Snapshot restore ───────────────────────────────────────────────
    if args.snapshot_restore:
        try:
            restored = tm.restore_snapshot(args.snapshot_restore)
            if not restored:
                print(f"Snapshot '{args.snapshot_restore}' not found.", file=sys.stderr)
                sys.exit(1)
            if args.output_json:
                print(json.dumps({p: str(dest) for p, dest in restored.items()}))
            else:
                print(f"Snapshot '{args.snapshot_restore}' restored to temp directory:")
                for file_rel, dest_path in sorted(restored.items()):
                    print(f"  {file_rel}  →  {dest_path}")
        except Exception as exc:
            print(f"Error restoring snapshot: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # ── List snapshots ─────────────────────────────────────────────────
    if args.snapshots:
        try:
            entries = tm.list_snapshots()
            if args.output_json:
                print(json.dumps([
                    {"name": e.name, "timestamp": e.timestamp, "files": list(e.files.keys())}
                    for e in entries
                ], indent=2))
            elif not entries:
                print("No named snapshots found.")
                print("Create one with /sync-history --snapshot-save <name>")
            else:
                print("Named Config Snapshots")
                print("=" * 45)
                for e in entries:
                    ts = e.timestamp[:19].replace("T", " ")
                    print(f"  {e.name:<20} {ts}  ({len(e.files)} file(s))")
                print()
                print("Restore: /sync-history --snapshot-restore <name>")
        except Exception as exc:
            print(f"Error listing snapshots: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # ── Show file at commit ────────────────────────────────────────────
    if args.show:
        file_path = args.file or "CLAUDE.md"
        try:
            content = tm.show_at(args.show, file_path=file_path)
            if content is None:
                print(f"File '{file_path}' not found at commit {args.show}.", file=sys.stderr)
                sys.exit(1)
            if args.output_json:
                print(json.dumps({"sha": args.show, "file": file_path, "content": content}))
            else:
                print(f"── {file_path} @ {args.show} ──")
                print(content)
        except Exception as exc:
            print(f"Error showing file: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # ── Diff between two commits ───────────────────────────────────────
    if args.diff:
        sha1, sha2 = args.diff
        file_path = args.file or "CLAUDE.md"
        try:
            diff_text = tm.diff_between(sha1, sha2, file_path=file_path)
            if args.output_json:
                print(json.dumps({"sha1": sha1, "sha2": sha2, "file": file_path, "diff": diff_text}))
            else:
                print(f"── diff {file_path}: {sha1}..{sha2} ──")
                print(diff_text or "(no differences)")
        except Exception as exc:
            print(f"Error computing diff: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # ── Restore from commit ────────────────────────────────────────────
    if args.restore:
        targets = (
            [t.strip() for t in args.target.split(",") if t.strip()]
            if args.target else None
        )
        try:
            result = tm.restore_to(args.restore, targets=targets)
            if args.output_json:
                print(json.dumps({
                    "sha": args.restore,
                    "targets": result.targets_synced,
                    "skipped": result.targets_skipped,
                    "errors": result.errors,
                }))
            else:
                print(f"Restored config from commit {args.restore}:")
                if result.targets_synced:
                    print(f"  Synced:  {', '.join(result.targets_synced)}")
                if result.targets_skipped:
                    print(f"  Skipped: {', '.join(result.targets_skipped)}")
                if result.errors:
                    print("  Errors:")
                    for err in result.errors:
                        print(f"    {err}")
        except Exception as exc:
            print(f"Error restoring: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # ── Timeline (default) ─────────────────────────────────────────────
    try:
        if args.search or args.since or args.until or args.author:
            commits = tm.search_timeline(
                query=args.search,
                since=args.since,
                until=args.until,
                author=args.author,
                max_commits=max(args.limit * 5, 200),
            )
            commits = commits[: args.limit]
        else:
            commits = tm.timeline(max_commits=args.limit)
    except Exception as exc:
        print(f"Error reading git history: {exc}", file=sys.stderr)
        sys.exit(1)

    if args.output_json:
        print(json.dumps([
            {
                "sha": c.sha,
                "author": c.author,
                "date": c.date,
                "subject": c.subject,
                "files_changed": c.files_changed,
            }
            for c in commits
        ], indent=2))
        return

    # ── Human-readable timeline ────────────────────────────────────────
    if not commits:
        print("No config-related commits found in this repository.")
        print("Tip: /sync-history --snapshot-save <name> to create a manual snapshot.")
        return

    header = "Config History"
    if args.search:
        header += f" — search: '{args.search}'"
    print(header)
    print("=" * max(len(header), 50))
    print()

    for c in commits:
        print(f"  {c.sha}  {c.date}  {c.author}")
        print(f"    {c.subject}")
        if c.files_changed:
            files_str = ", ".join(c.files_changed[:3])
            if len(c.files_changed) > 3:
                files_str += f" (+{len(c.files_changed) - 3})"
            print(f"    files: {files_str}")
        print()

    print(f"{len(commits)} commit(s) shown.")
    print()
    print("Commands:")
    print("  /sync-history --show <SHA>          view config at that point")
    print("  /sync-history --diff <SHA1> <SHA2>  compare two commits")
    print("  /sync-history --restore <SHA>       re-sync from that state")
    print("  /sync-history --snapshot-save <name> save a named snapshot")


if __name__ == "__main__":
    main()
