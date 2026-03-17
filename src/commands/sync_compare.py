from __future__ import annotations

"""
/sync-compare slash command — Live Capability Matrix Dashboard.

Renders a table of every Claude Code feature (MCP servers, skills, rules,
env vars, permissions) against every target harness, showing:
  ✓ Full sync   ~ Approximated   ✗ Not synced

Answers instantly: "Does Gemini support the MCP server I just added?"

Usage:
    /sync-compare
    /sync-compare --targets codex,gemini,cursor
    /sync-compare --detail
    /sync-compare --category mcp
    /sync-compare --json
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.capability_matrix import CapabilityMatrixBuilder, render_matrix
from src.utils.constants import EXTENDED_TARGETS


def main() -> None:
    """Entry point for /sync-compare command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-compare",
        description="Show live capability matrix: which CC features sync to which harness",
    )
    parser.add_argument(
        "--targets", "-t",
        default=None,
        help="Comma-separated list of targets (default: all extended targets)",
    )
    parser.add_argument(
        "--category", "-c",
        default=None,
        choices=["mcp", "skill", "agent", "command", "permission", "env", "rules"],
        help="Filter to a specific config category",
    )
    parser.add_argument(
        "--detail", "-d",
        action="store_true",
        help="Show per-cell notes for approximated/missing features",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_out",
        help="Output raw JSON instead of formatted table",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project root directory (default: current directory)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()

    targets: list[str] | None = None
    if args.targets:
        targets = [t.strip() for t in args.targets.split(",") if t.strip()]

    builder = CapabilityMatrixBuilder(project_dir=project_dir, targets=targets)
    matrix = builder.build()

    # Filter by category if requested
    if args.category:
        matrix.rows = [r for r in matrix.rows if r.category == args.category]

    if args.json_out:
        out = {
            "targets": matrix.targets,
            "rows": [
                {
                    "category": r.category,
                    "item": r.item_name,
                    "cells": {
                        t: {"status": c.status, "note": c.note}
                        for t, c in r.cells.items()
                    },
                }
                for r in matrix.rows
            ],
            "summary": matrix.summary(),
        }
        print(json.dumps(out, indent=2))
        return

    print(render_matrix(matrix, detail=args.detail))


if __name__ == "__main__":
    main()
