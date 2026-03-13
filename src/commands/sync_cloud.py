from __future__ import annotations

"""
/sync-cloud slash command implementation.

Push/pull HarnessSync config to GitHub Gist for multi-machine or team sharing.

Upload your current config to a Gist, pull a teammate's config from a Gist,
or build a shareable bundle URL from your current setup.

Usage:
  /sync-cloud push                        Push config to a new Gist
  /sync-cloud push --gist-id ID           Update an existing Gist
  /sync-cloud pull --gist-id ID           Pull config from a Gist
  /sync-cloud pull --gist-url URL         Pull config from a Gist URL
  /sync-cloud share                       Build a shareable bundle
  /sync-cloud share --profile myprofile   Include a named profile
"""

import os
import shlex
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

import argparse
from pathlib import Path

from src.cloud_sync import (
    GistCloudSync,
    build_shareable_bundle,
    parse_gist_id_from_url,
)


def _resolve_token(args_token: str | None) -> str | None:
    """Return the GitHub token from CLI arg or environment variable."""
    if args_token:
        return args_token
    return os.environ.get("GITHUB_TOKEN")


def _resolve_gist_id(
    gist_id: str | None, gist_url: str | None
) -> str | None:
    """Return a gist ID from either --gist-id or --gist-url."""
    if gist_id:
        return gist_id
    if gist_url:
        return parse_gist_id_from_url(gist_url)
    return None


def _cmd_push(args: argparse.Namespace, project_dir: Path, token: str) -> None:
    """Handle the 'push' action."""
    gist_id = _resolve_gist_id(args.gist_id, args.gist_url)

    extra_files = None
    if args.profile:
        extra_files = build_shareable_bundle(project_dir, profile_name=args.profile)

    syncer = GistCloudSync(token=token)
    result = syncer.push(project_dir, gist_id=gist_id, extra_files=extra_files)
    print(result.format())

    if result.success and result.gist_url:
        print()
        print("Share this URL with teammates:")
        print(f"  {result.gist_url}")
        print()
        print("To update this Gist later:")
        print(f"  /sync-cloud push --gist-id {result.gist_id}")


def _cmd_pull(args: argparse.Namespace, project_dir: Path, token: str) -> None:
    """Handle the 'pull' action."""
    gist_id = _resolve_gist_id(args.gist_id, args.gist_url)
    if not gist_id:
        print("ERROR: Gist ID or URL required for pull.")
        print("  Use --gist-id ID or --gist-url URL.")
        return

    overwrite = not args.no_overwrite

    syncer = GistCloudSync(token=token)
    result = syncer.pull(project_dir, gist_id=gist_id, overwrite=overwrite)
    print(result.format())


def _cmd_share(args: argparse.Namespace, project_dir: Path, token: str) -> None:
    """Handle the 'share' action — build and push a shareable bundle."""
    bundle = build_shareable_bundle(project_dir, profile_name=args.profile)

    if not bundle:
        print("ERROR: No config files found to share.")
        print(f"  Looked in: {project_dir}")
        return

    print(f"Building shareable bundle ({len(bundle)} file(s))...")
    for fname in sorted(bundle):
        print(f"  - {fname}")

    gist_id = _resolve_gist_id(args.gist_id, args.gist_url)

    syncer = GistCloudSync(token=token)
    result = syncer.push(project_dir, gist_id=gist_id, extra_files=bundle)
    print()
    print(result.format())

    if result.success and result.gist_url:
        print()
        print("Teammates can pull this config with:")
        print(f"  /sync-cloud pull --gist-url {result.gist_url}")


def main() -> None:
    """Entry point for /sync-cloud command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-cloud",
        description="Push/pull HarnessSync config to GitHub Gist",
    )
    parser.add_argument(
        "action",
        nargs="?",
        choices=["push", "pull", "share"],
        default=None,
        help="Action to perform: push, pull, or share",
    )
    parser.add_argument(
        "--token",
        default=None,
        metavar="TOKEN",
        help="GitHub personal access token (or set GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--gist-id",
        default=None,
        metavar="ID",
        help="Gist ID to update (push) or fetch (pull)",
    )
    parser.add_argument(
        "--gist-url",
        default=None,
        metavar="URL",
        help="Full Gist URL (alternative to --gist-id)",
    )
    parser.add_argument(
        "--profile",
        default=None,
        metavar="NAME",
        help="Include named profile in the bundle",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Don't overwrite existing local files on pull",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        metavar="DIR",
        help="Project directory (default: current working directory)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    if not args.action:
        parser.print_help()
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    token = _resolve_token(args.token)
    if not token:
        print("ERROR: GitHub token required.")
        print("  Pass --token TOKEN or set the GITHUB_TOKEN environment variable.")
        return

    if args.action == "push":
        _cmd_push(args, project_dir, token)
    elif args.action == "pull":
        _cmd_pull(args, project_dir, token)
    elif args.action == "share":
        _cmd_share(args, project_dir, token)


if __name__ == "__main__":
    main()
