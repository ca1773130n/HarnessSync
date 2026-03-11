from __future__ import annotations

"""
/sync-sandbox slash command implementation.

Runs a full sync simulation in a temporary directory and shows the complete
file tree that would be created for each target harness — without writing
anything to the real filesystem.

More powerful than --dry-run: the simulated output files are fully written
to a temp dir and can be browsed before committing to a real sync.

Usage:
    /sync-sandbox [--scope SCOPE] [--keep] [--json] [--project-dir PATH]
    /sync-sandbox [--only SECTIONS] [--skip SECTIONS] [--only-targets TARGETS]

Options:
    --scope SCOPE         Sync scope: user | project | all (default: all)
    --only SECTIONS       Comma-separated sections to include (rules,mcp,...)
    --skip SECTIONS       Comma-separated sections to skip
    --only-targets LIST   Comma-separated targets to simulate
    --keep                Keep the sandbox directory after showing the report
    --json                Output report as JSON
    --project-dir PATH    Project directory (default: cwd)
"""

import json
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.sync_sandbox import SyncSandbox


def main():
    """Entry point for /sync-sandbox command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-sandbox",
        description="Simulate a full sync into a temp directory without writing real files.",
    )
    parser.add_argument("--scope", default="all", choices=["user", "project", "all"])
    parser.add_argument("--only", default=None, help="Sections to sync (comma-separated)")
    parser.add_argument("--skip", default=None, help="Sections to skip (comma-separated)")
    parser.add_argument("--only-targets", default=None, help="Targets to simulate (comma-separated)")
    parser.add_argument("--skip-targets", default=None, help="Targets to skip (comma-separated)")
    parser.add_argument("--keep", action="store_true",
                        help="Keep sandbox directory after showing report")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Output report as JSON")
    parser.add_argument("--project-dir", default=None)

    args = parser.parse_args(raw_args)

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()

    only_sections: set[str] | None = None
    skip_sections: set[str] | None = None
    only_targets: set[str] | None = None
    skip_targets: set[str] | None = None

    valid_sections = {"rules", "skills", "agents", "commands", "mcp", "settings"}
    if args.only:
        only_sections = {s.strip() for s in args.only.split(",") if s.strip()} & valid_sections
    if args.skip:
        skip_sections = {s.strip() for s in args.skip.split(",") if s.strip()} & valid_sections
    if args.only_targets:
        only_targets = {t.strip() for t in args.only_targets.split(",") if t.strip()}
    if args.skip_targets:
        skip_targets = {t.strip() for t in args.skip_targets.split(",") if t.strip()}

    sandbox = SyncSandbox(project_dir=project_dir, keep_sandbox=args.keep)

    print("Running sync simulation…")
    try:
        report = sandbox.run(
            scope=args.scope,
            only_sections=only_sections,
            skip_sections=skip_sections,
            only_targets=only_targets,
            skip_targets=skip_targets,
        )
    except Exception as e:
        print(f"Sandbox error: {e}", file=sys.stderr)
        if not args.keep:
            sandbox.cleanup()
        sys.exit(1)

    if args.output_json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(report.format())

    if args.keep:
        print(f"\nSandbox kept at: {report.sandbox_dir}")
    else:
        sandbox.cleanup()


if __name__ == "__main__":
    main()
