from __future__ import annotations

"""
/sync-catalog slash command — MCP Server Catalog Browser.

Fetches a curated registry of community MCP servers, shows which ones you
already have, and lets you add them to Claude Code config (and auto-sync
everywhere) in one step.

Usage:
    /sync-catalog                        List all catalog entries
    /sync-catalog --search query         Search by name, description, or tag
    /sync-catalog --add context7         Add a server to your config
    /sync-catalog --add context7 --user  Add to user scope (~/.claude/.mcp.json)
    /sync-catalog --installed            Show only installed servers
    /sync-catalog --available            Show only uninstalled servers
    /sync-catalog --refresh              Fetch latest catalog from network
    /sync-catalog --verbose              Show command, tags, and homepage
    /sync-catalog --json                 Output raw JSON
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.mcp_catalog import McpCatalog, format_catalog


def main() -> None:
    """Entry point for /sync-catalog command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-catalog",
        description="Browse and add community MCP servers to Claude Code config",
    )
    parser.add_argument("--search", "-s", default=None, metavar="QUERY",
                        help="Search catalog by name, description, or tag")
    parser.add_argument("--add", "-a", default=None, metavar="NAME",
                        help="Add a catalog server to your .mcp.json")
    parser.add_argument("--user", action="store_true",
                        help="Add to user scope (~/.claude/.mcp.json) instead of project")
    parser.add_argument("--installed", action="store_true",
                        help="Show only installed servers")
    parser.add_argument("--available", action="store_true",
                        help="Show only uninstalled servers")
    parser.add_argument("--refresh", action="store_true",
                        help="Fetch latest catalog from network (requires internet)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show command, tags, and homepage for each entry")
    parser.add_argument("--json", action="store_true", dest="json_out",
                        help="Output raw JSON")
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--cc-home", default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()
    cc_home = Path(args.cc_home).expanduser() if args.cc_home else None

    catalog = McpCatalog(project_dir=project_dir, cc_home=cc_home)
    entries = catalog.load_catalog(refresh=args.refresh)

    if args.add:
        scope = "user" if args.user else "project"
        success, msg = catalog.add_server(args.add, entries=entries, scope=scope)
        print(msg)
        if not success:
            sys.exit(1)
        return

    if args.search:
        entries = catalog.search(args.search, entries=entries)
        if not entries:
            print(f"No results for '{args.search}'.")
            return

    if args.json_out:
        out = [
            {
                "name": e.name,
                "description": e.description,
                "installed": e.installed,
                "tags": e.tags,
                "homepage": e.homepage,
                "command": e.command,
                "args": e.args,
            }
            for e in entries
        ]
        print(json.dumps(out, indent=2))
        return

    show_installed = not args.available
    if args.installed:
        entries = [e for e in entries if e.installed]
        show_installed = True

    print(format_catalog(entries, show_installed=show_installed, verbose=args.verbose))


if __name__ == "__main__":
    main()
