from __future__ import annotations

"""
/sync-env-matrix slash command — show environment variable compatibility across harnesses.

Displays which Claude Code environment variables have equivalents in each
harness and flags silent gaps where a variable you have set will have no
effect in a target harness.

Usage:
    /sync-env-matrix [--show-all] [--gaps-only] [--targets TARGETS] [--json]

Options:
    --show-all        Show all env vars including those not currently set
    --gaps-only       Show only variables with translation gaps
    --targets LIST    Comma-separated targets to include (default: all)
    --json            Output report as JSON
"""

import json
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.env_var_matrix import EnvVarMatrix


def main():
    """Entry point for /sync-env-matrix command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-env-matrix",
        description="Show environment variable compatibility matrix across harnesses.",
    )
    parser.add_argument("--show-all", action="store_true",
                        help="Show all vars including those not currently set")
    parser.add_argument("--gaps-only", action="store_true",
                        help="Show only vars with translation gaps for set variables")
    parser.add_argument("--targets", default=None,
                        help="Comma-separated targets to include")
    parser.add_argument("--json", dest="output_json", action="store_true")

    args = parser.parse_args(raw_args)

    targets = None
    if args.targets:
        targets = [t.strip() for t in args.targets.split(",") if t.strip()]

    matrix = EnvVarMatrix(targets=targets)
    report = matrix.analyze()

    if args.output_json:
        output = {
            "targets": report.targets,
            "total_set": report.total_set,
            "total_missing_translations": report.total_missing_translations,
            "variables": [
                {
                    "name": a.spec.name,
                    "category": a.spec.category,
                    "is_set": a.is_set,
                    "missing_in": a.missing_in,
                    "partial_in": a.partial_in,
                    "mapped_in": a.mapped_in,
                    "targets": {
                        t: {"support": level.value, "note": note}
                        for t, (level, note) in a.spec.targets.items()
                        if t in report.targets
                    },
                }
                for a in report.analyses
            ],
        }
        print(json.dumps(output, indent=2))
    elif args.gaps_only:
        print(matrix.format_gaps(report))
    else:
        print(matrix.format_table(report, show_all=args.show_all))


if __name__ == "__main__":
    main()
