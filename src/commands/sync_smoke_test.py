from __future__ import annotations

"""
/sync-smoke-test slash command implementation.

After syncing skills, runs minimal validation checks against each target
harness's synced skill files, reporting pass/fail per skill per harness.

Catches silent failures where a skill synced at the file level but is
broken due to harness-specific syntax (bad MDC frontmatter, broken symlinks,
malformed YAML, etc.).

Usage:
    /sync-smoke-test [--targets codex,cursor] [--verbose] [--project-dir PATH]
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.skill_smoke_tester import SkillSmokeTester


def main() -> None:
    """Entry point for /sync-smoke-test command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-smoke-test",
        description="Run smoke tests on synced skill files",
    )
    parser.add_argument(
        "--targets",
        type=str,
        default=None,
        help="Comma-separated list of targets to test (default: all detected)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include passing skills in output",
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

    tester = SkillSmokeTester(project_dir)
    report = tester.test_all(targets=targets)

    print(report.format(verbose=args.verbose))

    # Exit with non-zero if any failures (allows CI integration)
    if report.failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
