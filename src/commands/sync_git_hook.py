from __future__ import annotations

"""
/sync-git-hook slash command implementation.

Install or uninstall git hooks that auto-sync config when CLAUDE.md,
.claude/, or .mcp.json changes.

Post-commit hook:   syncs in background after commit (non-blocking)
Pre-commit hook:    syncs synchronously and stages updated target files
                    (AGENTS.md, GEMINI.md, etc.) in the same commit
Gate hook:          blocks commits when harness configs are stale
                    (Claude Code config changed but targets not synced yet)
Post-checkout hook: auto-syncs when switching branches or pulling team
                    config changes (removes need to remember /sync after
                    git checkout or git pull)
Post-merge hook:    auto-syncs after git merge / git pull when team config
                    files (CLAUDE.md, .mcp.json, etc.) changed in the merge
                    (item 3 — Team Config Broadcast via Git)
Pre-push hook:      blocks git push when harness configs are out of sync
                    with CLAUDE.md, preventing teams from pushing config
                    debt (item 4 — Pre-Push Sync Enforcement)

Usage:
    /sync-git-hook                            # show status
    /sync-git-hook install                    # install post-commit hook
    /sync-git-hook install --pre-commit       # install pre-commit sync + auto-stage
    /sync-git-hook install --gate             # install pre-commit gate (blocking)
    /sync-git-hook install --post-checkout    # install post-checkout branch-sync hook
    /sync-git-hook install --post-merge       # install post-merge team-config hook
    /sync-git-hook install --pre-push         # install pre-push sync enforcement hook
    /sync-git-hook uninstall                  # remove post-commit hook
    /sync-git-hook uninstall --pre-commit     # remove pre-commit hook
    /sync-git-hook uninstall --gate           # remove gate hook
    /sync-git-hook uninstall --post-checkout  # remove post-checkout hook
    /sync-git-hook uninstall --post-merge     # remove post-merge hook
    /sync-git-hook uninstall --pre-push       # remove pre-push hook
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
    install_gate_hook,
    uninstall_gate_hook,
    is_gate_hook_installed,
    install_post_checkout_hook,
    uninstall_post_checkout_hook,
    is_post_checkout_hook_installed,
    install_post_merge_hook,
    uninstall_post_merge_hook,
    is_post_merge_hook_installed,
    install_pre_push_hook,
    uninstall_pre_push_hook,
    is_pre_push_hook_installed,
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
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Install/remove pre-commit gate that blocks commits when sync is stale",
    )
    parser.add_argument(
        "--post-checkout",
        action="store_true",
        dest="post_checkout",
        help=(
            "Install/remove post-checkout hook that auto-syncs when switching branches "
            "or pulling team config changes (non-blocking, background sync)"
        ),
    )
    parser.add_argument(
        "--post-merge",
        action="store_true",
        dest="post_merge",
        help=(
            "Install/remove post-merge hook that auto-syncs after git merge/pull when "
            "team config files (CLAUDE.md, .mcp.json, settings.json) changed "
            "(item 3: Team Config Broadcast via Git)"
        ),
    )
    parser.add_argument(
        "--pre-push",
        action="store_true",
        dest="pre_push",
        help=(
            "Install/remove pre-push enforcement hook that blocks push when harness "
            "configs are out of sync with CLAUDE.md. Prevents teams from pushing "
            "CLAUDE.md changes without also committing the synced harness files."
        ),
    )
    parser.add_argument("--project-dir", type=str, default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    pre_commit = args.pre_commit
    gate = getattr(args, 'gate', False)
    post_checkout = getattr(args, 'post_checkout', False)

    if args.action == "status":
        post_installed = is_hook_installed(project_dir)
        pre_installed = is_pre_commit_hook_installed(project_dir)
        gate_installed = is_gate_hook_installed(project_dir)
        post_checkout_installed = is_post_checkout_hook_installed(project_dir)

        print("HarnessSync Git Hook Status")
        print("=" * 40)
        print(f"  post-commit:      {'installed' if post_installed else 'not installed'}")
        print(f"  pre-commit:       {'installed' if pre_installed else 'not installed'}")
        print(f"  pre-commit gate:  {'installed' if gate_installed else 'not installed'}")
        print(f"  post-checkout:    {'installed' if post_checkout_installed else 'not installed'}")
        print()
        if post_installed:
            print("Post-commit:    auto-syncs in background after each commit.")
        if pre_installed:
            print("Pre-commit:     syncs and stages target files before each commit.")
        if gate_installed:
            print("Gate:           blocks commits when harness configs are stale.")
        if post_checkout_installed:
            print("Post-checkout:  auto-syncs when switching branches or pulling team changes.")
        if not any([post_installed, pre_installed, gate_installed, post_checkout_installed]):
            print("Run /sync-git-hook install to enable post-commit auto-sync.")
            print("Run /sync-git-hook install --pre-commit to enable pre-commit sync + auto-stage.")
            print("Run /sync-git-hook install --gate to enable the stale-sync commit gate.")
            print("Run /sync-git-hook install --post-checkout to enable branch-switch auto-sync.")

    elif args.action == "install":
        if gate:
            success, message = install_gate_hook(project_dir)
            if success:
                print(f"OK: {message}")
                print()
                print("HarnessSync gate is active: commits that include CLAUDE.md changes")
                print("will be blocked if the harness target files are out of sync.")
                print("Run /sync to unblock, then commit again.")
            else:
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)
        elif pre_commit:
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
        elif post_checkout:
            success, message = install_post_checkout_hook(project_dir)
            if success:
                print(f"OK: {message}")
                print()
                print("HarnessSync will now auto-sync in the background whenever you")
                print("switch branches (git checkout / git switch), but only when")
                print("CLAUDE.md, .claude/, or .mcp.json differs between branches.")
                print("This eliminates 'forgot to /sync after git pull' config drift.")
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
        if gate:
            success, message = uninstall_gate_hook(project_dir)
        elif pre_commit:
            success, message = uninstall_pre_commit_hook(project_dir)
        elif post_checkout:
            success, message = uninstall_post_checkout_hook(project_dir)
        else:
            success, message = uninstall_hook(project_dir)

        if success:
            print(f"OK: {message}")
        else:
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
