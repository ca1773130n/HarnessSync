from __future__ import annotations

"""
/sync-token-estimate slash command implementation.

Shows an estimate of how many tokens each synced rules file will consume
in each harness's context window. Flags configurations that may degrade
LLM performance due to bloated system prompts.

Usage:
    /sync-token-estimate [--targets codex,cursor] [--verbose] [--project-dir PATH]
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.token_estimator import TokenEstimator


def main() -> None:
    """Entry point for /sync-token-estimate command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-token-estimate",
        description="Estimate token cost of synced rule files per harness",
    )
    parser.add_argument(
        "--targets",
        type=str,
        default=None,
        help="Comma-separated targets to check (default: all detected)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-file breakdown",
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

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    targets = [t.strip() for t in args.targets.split(",")] if args.targets else None

    estimator = TokenEstimator(project_dir)
    report = estimator.estimate_all(targets=targets)

    print(report.format(verbose=args.verbose))


if __name__ == "__main__":
    main()
