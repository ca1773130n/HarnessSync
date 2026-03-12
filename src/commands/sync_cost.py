from __future__ import annotations

"""
/sync-cost slash command — cross-harness cost optimization advisor.

Analyzes harness configurations across Claude Code, Gemini, OpenCode, Codex,
Cursor, and Aider and surfaces config changes that could reduce API costs.

Usage:
    /sync-cost [--severity LEVEL] [--json] [--project-dir PATH]

Options:
    --severity LEVEL    Filter by minimum severity: high|medium|low (default: medium)
    --json              Output advisories as JSON
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

from src.harness_cost_advisor import HarnessCostAdvisor


def main():
    """Entry point for /sync-cost command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-cost",
        description="Cross-harness API cost optimization advisor.",
    )
    parser.add_argument("--severity", default="medium",
                        choices=["high", "medium", "low"],
                        help="Minimum severity level to show (default: medium)")
    parser.add_argument("--json", dest="output_json", action="store_true")
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--cc-home", default=None)

    args = parser.parse_args(raw_args)

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    cc_home = Path(args.cc_home).resolve() if args.cc_home else (Path.home() / ".claude")

    advisor = HarnessCostAdvisor(project_dir=project_dir, cc_home=cc_home)
    report = advisor.analyze()

    # Filter by severity
    severity_order = {"high": 0, "medium": 1, "low": 2}
    min_severity = severity_order.get(args.severity, 1)
    report.advisories = [
        a for a in report.advisories
        if severity_order.get(a.severity, 2) <= min_severity
    ]
    # Recount
    report.total_high = sum(1 for a in report.advisories if a.severity == "high")
    report.total_medium = sum(1 for a in report.advisories if a.severity == "medium")
    report.total_low = sum(1 for a in report.advisories if a.severity == "low")

    if args.output_json:
        print(advisor.format_json(report))
    else:
        print(advisor.format_report(report))

    if report.total_high > 0:
        sys.exit(0)  # Advisory only — don't fail on findings


if __name__ == "__main__":
    main()
