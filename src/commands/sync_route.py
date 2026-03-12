from __future__ import annotations

"""
/sync-route slash command — recommend the best harness for a given task.

Given a task description, classifies the task and scores each installed
harness against it, returning an ordered recommendation.

Usage:
    /sync-route "task description" [--all] [--top N] [--json] [--project-dir PATH]

Options:
    "task description"  Natural language description of what you want to do
    --all               Include harnesses not currently installed/configured
    --top N             Show top N recommendations (default: 3)
    --json              Output as JSON
    --project-dir PATH  Project directory (default: cwd)
    --cc-home PATH      Claude Code home directory (default: ~/.claude)
"""

import json
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.task_router import TaskRouter


def main():
    """Entry point for /sync-route command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-route",
        description="Recommend the best harness for a given task description.",
    )
    parser.add_argument("task", nargs="?", default=None,
                        help="Task description (required)")
    parser.add_argument("--all", dest="include_all", action="store_true",
                        help="Include harnesses not currently installed")
    parser.add_argument("--top", type=int, default=3,
                        help="Number of recommendations to show (default: 3)")
    parser.add_argument("--json", dest="output_json", action="store_true")
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--cc-home", default=None)

    args = parser.parse_args(raw_args)

    if not args.task:
        # Try reading from stdin if not interactive
        if not sys.stdin.isatty():
            args.task = sys.stdin.read().strip()
        if not args.task:
            print("Error: task description required.", file=sys.stderr)
            print("Usage: /sync-route \"your task description\"", file=sys.stderr)
            sys.exit(1)

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    cc_home = Path(args.cc_home).resolve() if args.cc_home else (Path.home() / ".claude")

    router = TaskRouter(project_dir=project_dir, cc_home=cc_home)
    result = router.route(args.task, include_all=args.include_all)

    if args.output_json:
        print(router.format_json(result))
    else:
        print(router.format_recommendation(result, top_n=args.top))


if __name__ == "__main__":
    main()
