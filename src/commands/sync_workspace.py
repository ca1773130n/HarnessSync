from __future__ import annotations

"""
/sync-workspace slash command implementation.

Multi-project workspace manager: register projects, view sync status across
all workspaces, push global rules, and run bulk sync from one command.

Usage:
    /sync-workspace add NAME /path/to/project [--tag TAG] [--desc TEXT]
    /sync-workspace remove NAME
    /sync-workspace list [--tag TAG]
    /sync-workspace status [--tag TAG]
    /sync-workspace sync-all [--tag TAG] [--dry-run]
    /sync-workspace discover [--root DIR]
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.workspace_manager import WorkspaceManager


def main() -> None:
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-workspace",
        description="Multi-project workspace manager for HarnessSync.",
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # add
    add_parser = subparsers.add_parser("add", help="Register a project directory")
    add_parser.add_argument("name", help="Short workspace name")
    add_parser.add_argument("path", nargs="?", default=None, help="Project directory (default: cwd)")
    add_parser.add_argument("--tag", action="append", dest="tags", default=[], help="Tag for grouping")
    add_parser.add_argument("--desc", default="", help="Human-readable description")

    # remove
    rm_parser = subparsers.add_parser("remove", help="Unregister a workspace")
    rm_parser.add_argument("name", help="Workspace name to remove")

    # list
    list_parser = subparsers.add_parser("list", help="List registered workspaces")
    list_parser.add_argument("--tag", default=None, help="Filter by tag")

    # status
    status_parser = subparsers.add_parser("status", help="Show sync status for all workspaces")
    status_parser.add_argument("--tag", default=None, help="Filter by tag")

    # sync-all
    sync_parser = subparsers.add_parser("sync-all", help="Sync all workspaces")
    sync_parser.add_argument("--tag", default=None, help="Filter by tag")
    sync_parser.add_argument("--dry-run", action="store_true", help="Print without executing")
    sync_parser.add_argument("--targets", default=None, help="Comma-separated target list")

    # discover
    disc_parser = subparsers.add_parser("discover", help="Scan filesystem for unregistered projects")
    disc_parser.add_argument("--root", default=None, help="Root directory to scan")

    try:
        args = parser.parse_args(raw_args)
    except SystemExit:
        return

    if not args.subcommand:
        # Default: show status
        wm = WorkspaceManager()
        print(wm.format_status_table())
        return

    wm = WorkspaceManager()

    if args.subcommand == "add":
        project_path = Path(args.path) if args.path else Path.cwd()
        try:
            entry = wm.add(
                name=args.name,
                path=project_path,
                tags=args.tags,
                description=args.desc,
            )
            print(f"Registered workspace '{entry.name}' → {entry.path}")
            if entry.tags:
                print(f"  Tags: {', '.join(entry.tags)}")
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    elif args.subcommand == "remove":
        removed = wm.remove(args.name)
        if removed:
            print(f"Workspace '{args.name}' removed.")
        else:
            print(f"Workspace '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)

    elif args.subcommand == "list":
        entries = wm.list_workspaces()
        if args.tag:
            entries = [e for e in entries if args.tag in e.tags]
        if not entries:
            print("No workspaces registered.")
            return
        print(f"Registered workspaces ({len(entries)}):")
        for e in entries:
            tags_str = f"  [{', '.join(e.tags)}]" if e.tags else ""
            desc_str = f"  — {e.description}" if e.description else ""
            print(f"  {e.name:<20} {e.path}{tags_str}{desc_str}")

    elif args.subcommand == "status":
        print(wm.format_status_table(tag_filter=args.tag))

    elif args.subcommand == "sync-all":
        targets = args.targets.split(",") if args.targets else None
        print(f"Syncing all workspaces{' (dry-run)' if args.dry_run else ''}...")
        results = wm.sync_all(
            targets=targets,
            dry_run=args.dry_run,
            tag_filter=args.tag,
        )
        if not args.dry_run:
            successes = sum(1 for v in results.values() if v)
            failures = len(results) - successes
            print(f"\nResults: {successes} succeeded, {failures} failed")
            for name, ok in sorted(results.items()):
                icon = "✓" if ok else "✗"
                print(f"  {icon} {name}")

    elif args.subcommand == "discover":
        root = Path(args.root) if args.root else None
        print("Scanning for unregistered projects with CLAUDE.md...")
        found = wm.auto_discover(search_root=root)
        if not found:
            print("No new projects found.")
            return
        print(f"Found {len(found)} unregistered project(s):")
        for p in found:
            print(f"  {p}")
        print("\nTo register: /sync-workspace add NAME /path/to/project")


if __name__ == "__main__":
    main()
