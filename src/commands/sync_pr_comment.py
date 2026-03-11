from __future__ import annotations

"""
/sync-pr-comment slash command implementation.

Post a formatted comment on a GitHub PR showing what each harness config
would change after sync — giving code reviewers visibility into the
downstream impact of CLAUDE.md changes without running HarnessSync locally.

The comment is idempotent: re-running updates the existing comment in-place.

Usage:
    /sync-pr-comment --pr NUMBER [--repo OWNER/REPO] [--scope SCOPE] [--dry-run]

Options:
    --pr NUMBER       Pull request number (required unless $PR_NUMBER is set)
    --repo OWNER/REPO Repository slug (default: $GITHUB_REPOSITORY env var)
    --token TOKEN     GitHub token (default: $GITHUB_TOKEN env var)
    --scope SCOPE     Sync scope: user | project | all (default: all)
    --dry-run         Print the comment body without posting to GitHub
    --project-dir DIR Project directory (default: cwd)
"""

import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.pr_comment_poster import PrCommentPoster
from src.utils.logger import Logger


def main() -> None:
    """Entry point for /sync-pr-comment command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-pr-comment",
        description="Post a HarnessSync config diff comment on a GitHub PR",
    )
    parser.add_argument(
        "--pr",
        type=int,
        default=None,
        metavar="NUMBER",
        help="Pull request number (or set $PR_NUMBER)",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        metavar="OWNER/REPO",
        help="Repository slug (default: $GITHUB_REPOSITORY)",
    )
    parser.add_argument(
        "--token",
        type=str,
        default=None,
        metavar="TOKEN",
        help="GitHub token (default: $GITHUB_TOKEN)",
    )
    parser.add_argument(
        "--scope",
        choices=["user", "project", "all"],
        default="all",
        help="Sync scope (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the comment body without posting to GitHub",
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

    logger = Logger()
    project_dir = Path(args.project_dir) if args.project_dir else Path(os.getcwd())

    # Resolve PR number
    pr_number = args.pr or int(os.environ.get("PR_NUMBER", 0) or 0)
    if not pr_number and not args.dry_run:
        logger.error("--pr NUMBER is required (or set $PR_NUMBER)")
        sys.exit(1)

    # Resolve repo
    repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
    if not repo and not args.dry_run:
        logger.error("--repo OWNER/REPO is required (or set $GITHUB_REPOSITORY)")
        sys.exit(1)

    # Resolve token
    token = args.token or os.environ.get("GITHUB_TOKEN", "")
    if not token and not args.dry_run:
        logger.error("--token TOKEN is required (or set $GITHUB_TOKEN)")
        sys.exit(1)

    poster = PrCommentPoster(token=token or "dry-run", repo=repo or "dry-run/repo", logger=logger)

    print(f"Computing harness config diff for project: {project_dir}")
    diffs = poster.build_diff_summary(project_dir=project_dir, scope=args.scope)

    if not diffs:
        print("No registered harness targets found or dry-run sync produced no results.")
        print("Tip: Run /sync-setup to configure harness targets.")
        return

    # Summarise locally
    changed = [d for d in diffs if d.has_changes]
    unchanged = [d for d in diffs if not d.has_changes]
    print(f"\nDiff summary: {len(changed)} target(s) would change, {len(unchanged)} in sync")
    for diff in changed:
        print(f"  {diff.target}: {diff.total_changes} file(s) — {', '.join(diff.sections_changed)}")

    comment_body = poster.format_comment(diffs)

    if args.dry_run:
        print("\n--- PR Comment Body (dry-run) ---")
        print(comment_body)
        print("--- End ---")
        return

    print(f"\nPosting comment to PR #{pr_number} in {repo} ...")
    success = poster.post(pr_number=pr_number, diffs=diffs)
    if success:
        print("Comment posted successfully.")
    else:
        print("Failed to post comment — check token permissions and repo name.")
        sys.exit(1)


if __name__ == "__main__":
    main()
