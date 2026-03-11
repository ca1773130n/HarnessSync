from __future__ import annotations

"""
/sync-git-hook slash command implementation.

Install or uninstall the git post-commit hook that auto-syncs config
when CLAUDE.md, .claude/, or .mcp.json changes.
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.git_hook_installer import install_hook, uninstall_hook, is_hook_installed


def main() -> None:
    """Entry point for /sync-git-hook command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-git-hook",
        description="Install/uninstall git post-commit auto-sync hook",
    )
    parser.add_argument(
        "action",
        choices=["install", "uninstall", "status"],
        nargs="?",
        default="status",
        help="Action to perform (default: status)",
    )
    parser.add_argument("--project-dir", type=str, default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    if args.action == "status":
        installed = is_hook_installed(project_dir)
        if installed:
            print("Git post-commit hook: installed")
            print("HarnessSync will auto-sync when CLAUDE.md, .claude/, or .mcp.json changes.")
        else:
            print("Git post-commit hook: not installed")
            print("Run /sync-git-hook install to enable auto-sync on git commit.")

    elif args.action == "install":
        success, message = install_hook(project_dir)
        if success:
            print(f"OK: {message}")
            print("\nHarnessSync will now auto-sync in the background whenever you commit")
            print("changes to CLAUDE.md, .claude/, or .mcp.json.")
        else:
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)

    elif args.action == "uninstall":
        success, message = uninstall_hook(project_dir)
        if success:
            print(f"OK: {message}")
        else:
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
