from __future__ import annotations

"""
/sync-git-hook slash command implementation.

Install or uninstall git hooks that auto-sync config when CLAUDE.md,
.claude/, or .mcp.json changes.

Post-commit hook: syncs in background after commit (non-blocking)
Pre-commit hook:  syncs synchronously and stages updated target files
                  (AGENTS.md, GEMINI.md, etc.) in the same commit

Usage:
    /sync-git-hook                          # show status
    /sync-git-hook install                  # install post-commit hook
    /sync-git-hook install --pre-commit     # install pre-commit hook
    /sync-git-hook uninstall                # remove post-commit hook
    /sync-git-hook uninstall --pre-commit   # remove pre-commit hook
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.git_hook_installer import (
    install_hook,
    uninstall_hook,
    is_hook_installed,
    install_pre_commit_hook,
    uninstall_pre_commit_hook,
    is_pre_commit_hook_installed,
)


def main() -> None:
    """Entry point for /sync-git-hook command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-git-hook",
        description="Install/uninstall git hooks for auto-sync",
    )
    parser.add_argument(
        "action",
        choices=["install", "uninstall", "status"],
        nargs="?",
        default="status",
        help="Action to perform (default: status)",
    )
    parser.add_argument(
        "--pre-commit",
        action="store_true",
        help="Target pre-commit hook (syncs synchronously, stages updated files)",
    )
    parser.add_argument("--project-dir", type=str, default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    pre_commit = args.pre_commit

    if args.action == "status":
        post_installed = is_hook_installed(project_dir)
        pre_installed = is_pre_commit_hook_installed(project_dir)

        print("HarnessSync Git Hook Status")
        print("=" * 40)
        print(f"  post-commit: {'installed' if post_installed else 'not installed'}")
        print(f"  pre-commit:  {'installed' if pre_installed else 'not installed'}")
        print()
        if post_installed:
            print("Post-commit: auto-syncs in background after each commit.")
        if pre_installed:
            print("Pre-commit:  syncs and stages target files before each commit.")
        if not post_installed and not pre_installed:
            print("Run /sync-git-hook install to enable post-commit auto-sync.")
            print("Run /sync-git-hook install --pre-commit to enable pre-commit sync + auto-stage.")

    elif args.action == "install":
        if pre_commit:
            success, message = install_pre_commit_hook(project_dir)
            if success:
                print(f"OK: {message}")
                print()
                print("HarnessSync will now sync harness configs and stage updated")
                print("target files (AGENTS.md, GEMINI.md, etc.) before each commit")
                print("when CLAUDE.md, .claude/, or .mcp.json is staged.")
            else:
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)
        else:
            success, message = install_hook(project_dir)
            if success:
                print(f"OK: {message}")
                print()
                print("HarnessSync will now auto-sync in the background whenever you commit")
                print("changes to CLAUDE.md, .claude/, or .mcp.json.")
            else:
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)

    elif args.action == "uninstall":
        if pre_commit:
            success, message = uninstall_pre_commit_hook(project_dir)
        else:
            success, message = uninstall_hook(project_dir)

        if success:
            print(f"OK: {message}")
        else:
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
