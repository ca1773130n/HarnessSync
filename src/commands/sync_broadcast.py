from __future__ import annotations

"""Team Config Broadcast slash command.

Push Claude Code config to a shared git repo (push), or pull and apply
a teammate's shared config (pull). Solves 'everyone on the team has
wildly different AI setups' by letting a team lead set the standard.

Usage:
    /sync-broadcast push --to <repo-url> [--branch team-config] [--dry-run]
    /sync-broadcast pull --from <repo-url> [--branch team-config] [--dry-run]
"""

import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.team_broadcast import TeamBroadcast


def main() -> None:
    """Entry point for /sync-broadcast command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-broadcast",
        description="Push or pull team config via a shared git repository",
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # Push subcommand
    push_p = subparsers.add_parser("push", help="Push config to shared repo")
    push_p.add_argument("--to", dest="repo", required=True, help="Shared repo URL or path")
    push_p.add_argument("--branch", default="team-config", help="Branch name (default: team-config)")
    push_p.add_argument("--message", default="", help="Custom commit message")
    push_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    push_p.add_argument("--project-dir", default=None)

    # Pull subcommand
    pull_p = subparsers.add_parser("pull", help="Pull and apply config from shared repo")
    pull_p.add_argument("--from", dest="repo", required=True, help="Shared repo URL or path")
    pull_p.add_argument("--branch", default="team-config", help="Branch name (default: team-config)")
    pull_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    pull_p.add_argument("--project-dir", default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    if not args.subcommand:
        parser.print_help()
        return

    project_dir = Path(
        getattr(args, "project_dir", None) or
        os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    )

    broadcaster = TeamBroadcast(project_dir)

    if args.subcommand == "push":
        result = broadcaster.push(
            shared_repo=args.repo,
            branch=args.branch,
            message=args.message,
            dry_run=args.dry_run,
        )
    else:
        result = broadcaster.pull(
            shared_repo=args.repo,
            branch=args.branch,
            dry_run=args.dry_run,
        )

    print(result.summary)
    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
