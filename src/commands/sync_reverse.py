from __future__ import annotations

"""
/sync-reverse slash command — import config from a target harness back into Claude Code.

Pulls rules, MCP servers, and env vars from Codex, Gemini, OpenCode, Cursor, Aider,
or Windsurf and merges them into Claude Code's canonical format (CLAUDE.md, .mcp.json,
settings.json).  Useful for users who started on another harness and want to migrate
their existing configs into Claude Code as the source of truth.

Usage:
    /sync-reverse --from HARNESS [--merge STRATEGY] [--apply] [--dry-run]

Options:
    --from HARNESS     Source harness to import from (codex|gemini|opencode|cursor|aider|windsurf)
    --merge STRATEGY   How to merge rules into CLAUDE.md:
                         append    — append after existing content (default)
                         prepend   — prepend before existing content
                         replace   — replace an existing reverse-sync import block
                         new_file  — write to CLAUDE.from-<harness>.md (no overwrite risk)
    --apply            Write changes to disk (default: dry-run / preview only)
    --dry-run          Show plan without writing (default behaviour)
    --project-dir PATH Project directory (default: cwd)
    --cc-home PATH     Claude Code home directory (default: ~/.claude)
    --json             Output result as JSON
"""

import json
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.reverse_sync import ReverseSync
from src.utils.constants import CORE_TARGETS

SUPPORTED_SOURCES = list(CORE_TARGETS)
MERGE_STRATEGIES = ["append", "prepend", "replace", "new_file"]


def main() -> None:
    """Entry point for /sync-reverse command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-reverse",
        description="Import config from a target harness back into Claude Code.",
    )
    parser.add_argument(
        "--from", dest="source",
        choices=SUPPORTED_SOURCES,
        required=True,
        help="Source harness to import from",
    )
    parser.add_argument(
        "--merge",
        dest="merge_strategy",
        choices=MERGE_STRATEGIES,
        default="append",
        help="Merge strategy for rules (default: append)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to disk (default: preview only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show plan without writing (default behaviour)",
    )
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--cc-home", default=None)
    parser.add_argument("--json", dest="output_json", action="store_true")

    args = parser.parse_args(raw_args)

    project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()
    cc_home = Path(args.cc_home).expanduser() if args.cc_home else None
    dry_run = not args.apply

    rs = ReverseSync(cc_home=cc_home, project_dir=project_dir)
    plan = rs.plan(source=args.source, merge_strategy=args.merge_strategy)

    if args.output_json:
        out = {
            "source": plan.source,
            "rules_count": len(plan.rules),
            "mcp_servers": [s.name for s in plan.mcp_servers],
            "env_vars": [ev.key for ev in plan.env_vars],
            "already_managed": plan.already_managed,
            "warnings": plan.warnings,
        }
        if not dry_run and plan.has_content and not plan.already_managed:
            result = rs.execute(plan, dry_run=False)
            out["result"] = result
        print(json.dumps(out, indent=2))
        return

    # Human-readable output
    print(rs.format_plan(plan))

    if plan.warnings:
        sys.exit(0)  # Warnings printed, exit cleanly

    if not plan.has_content:
        sys.exit(0)

    if dry_run:
        print(
            f"\nDry-run mode. Pass --apply to write changes.\n"
            f"Example: /sync-reverse --from {args.source} --apply"
        )
        sys.exit(0)

    # Apply
    result = rs.execute(plan, dry_run=False)
    print("\nImport complete:")
    if result["rules_written"]:
        print(f"  Rules written to: {result['claude_md_path']}")
    if result["mcp_added"]:
        print(f"  MCP servers added: {', '.join(result['mcp_added'])}")
    if result["env_added"]:
        print(f"  Env vars added: {', '.join(result['env_added'])}")
    if not result["rules_written"] and not result["mcp_added"] and not result["env_added"]:
        print("  No changes made (all content already present or nothing to import).")

    print("\nNext step: run /sync to propagate imported config to all harnesses.")


if __name__ == "__main__":
    main()
