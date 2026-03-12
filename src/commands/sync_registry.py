from __future__ import annotations

"""
/sync-registry slash command implementation.

Browses the curated MCP server registry, shows which servers are already
installed in Claude Code, and installs new ones in one step.

Usage:
    /sync-registry                        # list all servers
    /sync-registry list                   # same as above
    /sync-registry search <query>         # search by keyword
    /sync-registry install <server-id>    # add server to Claude Code
    /sync-registry install <id> --project # add to project .mcp.json
    /sync-registry info <server-id>       # show server details
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.mcp_registry import McpRegistry


def main() -> None:
    """Entry point for /sync-registry command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-registry",
        description="Browse and install MCP servers from the community registry",
    )
    subparsers = parser.add_subparsers(dest="action", help="Action")

    # list subcommand
    list_p = subparsers.add_parser("list", help="List all registry entries")
    list_p.add_argument("--category", type=str, default=None, help="Filter by category")
    list_p.add_argument("--installed", action="store_true", help="Show only installed servers")
    list_p.add_argument("--no-remote", action="store_true", help="Skip remote registry fetch")

    # search subcommand
    search_p = subparsers.add_parser("search", help="Search registry by keyword")
    search_p.add_argument("query", type=str, help="Search query")
    search_p.add_argument("--no-remote", action="store_true", help="Skip remote registry fetch")

    # install subcommand
    install_p = subparsers.add_parser("install", help="Install an MCP server")
    install_p.add_argument("server_id", type=str, help="Server ID to install")
    install_p.add_argument(
        "--project",
        action="store_true",
        help="Install to project .mcp.json instead of user config",
    )
    install_p.add_argument("--no-remote", action="store_true", help="Skip remote registry fetch")

    # info subcommand
    info_p = subparsers.add_parser("info", help="Show details about a server")
    info_p.add_argument("server_id", type=str, help="Server ID")
    info_p.add_argument("--no-remote", action="store_true", help="Skip remote registry fetch")

    # Default to list if no subcommand
    if not tokens:
        tokens = ["list"]

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    action = args.action or "list"
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    cc_home = Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))

    fetch_remote = not getattr(args, "no_remote", False)
    registry = McpRegistry(cc_home=cc_home, project_dir=project_dir, fetch_remote=fetch_remote)

    if action == "list":
        category = getattr(args, "category", None)
        installed_only = getattr(args, "installed", False)

        entries = registry.list_entries(category=category)
        if installed_only:
            entries = [e for e in entries if e.installed]

        print(registry.format_list(entries, group_by_category=not bool(category)))

    elif action == "search":
        query = args.query
        results = registry.search(query)
        if not results:
            print(f"No servers matching '{query}' found.")
            return
        print(f"Search results for '{query}':\n")
        print(registry.format_list(results, group_by_category=False))

    elif action == "install":
        server_id = args.server_id
        scope = "project" if args.project else "user"

        print(f"Installing '{server_id}' ({scope} scope)...")
        success, message = registry.install(server_id, scope=scope)
        if success:
            print(f"OK: {message}")
            # Show config hint for servers with env vars
            entry = registry.get_by_id(server_id)
            if entry and entry.env:
                print("\nRequired environment variables:")
                for var, val in entry.env.items():
                    print(f"  export {var}=<your-value>")
            print("\nRun /sync to propagate this MCP server to all target harnesses.")
        else:
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)

    elif action == "info":
        server_id = args.server_id
        entry = registry.get_by_id(server_id)
        if entry is None:
            print(f"Server '{server_id}' not found in registry.", file=sys.stderr)
            sys.exit(1)

        status = "INSTALLED" if entry.installed else "not installed"
        print(f"MCP Server: {entry.name}")
        print(f"  ID:          {entry.id}")
        print(f"  Category:    {entry.category}")
        print(f"  Status:      {status}")
        print(f"  Description: {entry.description}")
        print(f"  Command:     {entry.command} {' '.join(entry.args)}")
        if entry.env:
            print(f"  Environment:")
            for var, val in entry.env.items():
                print(f"               {var}={val}")
        if entry.tags:
            print(f"  Tags:        {', '.join(entry.tags)}")
        if not entry.installed:
            print(f"\nInstall: /sync-registry install {entry.id}")


if __name__ == "__main__":
    main()
