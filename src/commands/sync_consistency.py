from __future__ import annotations

"""
/sync-consistency slash command — cross-harness prompt consistency checker.

Statically analyses how your CLAUDE.md config will behave across target
harnesses and reports where the AI tool behaviour will diverge.  Runs
without modifying any files (read-only analysis).

Usage:
    /sync-consistency
    /sync-consistency --targets codex,gemini,cursor
    /sync-consistency --format json

Flags:
    --targets T1,T2,...   Comma-separated list of harnesses to compare
                          (default: all configured targets)
    --format text|json    Output format (default: text)
"""

import argparse
import json
import os
import shlex
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.source_reader import SourceReader
from src.prompt_consistency_checker import PromptConsistencyChecker


def main() -> None:
    """Entry point for /sync-consistency command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-consistency",
        description="Check cross-harness prompt consistency (read-only)",
    )
    parser.add_argument(
        "--targets",
        default="",
        help="Comma-separated harness names (default: all known targets)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="fmt",
        help="Output format",
    )
    parser.add_argument(
        "--project-dir",
        default="",
        help="Project directory to analyse (default: cwd)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir) if args.project_dir else Path(os.getcwd())
    targets = [t.strip() for t in args.targets.split(",") if t.strip()] or None

    # Discover source config
    reader = SourceReader(scope="all", project_dir=project_dir)
    source_data = reader.discover_all()

    # Run consistency check
    checker = PromptConsistencyChecker()
    report = checker.check(source_data, targets=targets)

    if args.fmt == "json":
        output = {
            "targets": report.targets,
            "consistency_scores": report.consistency_scores,
            "section_divergences": [
                {
                    "section_type": d.section_type,
                    "target": d.target,
                    "fidelity": d.fidelity,
                    "reason": d.reason,
                    "affected_count": d.affected_count,
                }
                for d in report.section_divergences
            ],
            "portability_issues": [
                {
                    "rule_excerpt": i.rule_excerpt,
                    "pattern_desc": i.pattern_desc,
                    "affected_targets": i.affected_targets,
                    "line_number": i.line_number,
                }
                for i in report.portability_issues
            ],
        }
        print(json.dumps(output, indent=2))
    else:
        print(checker.format_report(report))


if __name__ == "__main__":
    main()
