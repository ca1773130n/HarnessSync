from __future__ import annotations

"""
/sync-categorize slash command implementation.

Auto-categorizes CLAUDE.md rules and shows effectiveness scores.
Integrates RuleCategorizer (item 9) and RuleEffectivenessTracker (item 12).

Usage:
    /sync-categorize                        Show categorized rules summary
    /sync-categorize --detail               Show per-rule categories
    /sync-categorize --effectiveness        Show rule effectiveness scores
    /sync-categorize --stale-days 30        Report stale rules (default: 30)
    /sync-categorize --filter security      Show only 'security' tagged rules
    /sync-categorize --json                 Machine-readable output
"""

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.rule_categorizer import RuleCategorizer
from src.rule_effectiveness import RuleEffectivenessTracker
from src.source_reader import SourceReader


def _read_rules(project_dir: Path, cc_home: Path | None) -> str:
    """Read CLAUDE.md rules text from source."""
    try:
        reader = SourceReader(project_dir=project_dir, cc_home=cc_home)
        data = reader.discover_all()
        return data.get("rules", "") or ""
    except Exception:
        # Fallback: read CLAUDE.md directly
        for candidate in [
            project_dir / "CLAUDE.md",
            (cc_home or Path.home() / ".claude") / "CLAUDE.md",
        ]:
            if candidate.exists():
                return candidate.read_text(encoding="utf-8", errors="replace")
        return ""


def main() -> None:
    """Entry point for /sync-categorize command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-categorize",
        description="Auto-categorize CLAUDE.md rules and show effectiveness scores",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Show per-rule category assignments",
    )
    parser.add_argument(
        "--effectiveness",
        action="store_true",
        help="Show rule effectiveness scores (fire frequency)",
    )
    parser.add_argument(
        "--stale-days",
        type=int,
        default=30,
        metavar="N",
        dest="stale_days",
        help="Report rules not seen in N days as stale (default: 30)",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        metavar="TAG",
        help="Show only rules with this category tag (e.g. security, workflow, style)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output machine-readable JSON",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
        help="Project root directory (default: $CLAUDE_PROJECT_DIR or cwd)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir)
    rules_text = _read_rules(project_dir, cc_home=None)

    categorizer = RuleCategorizer()
    result = categorizer.categorize_text(rules_text)

    # Register discovered rule titles with the effectiveness tracker
    tracker = RuleEffectivenessTracker()
    tracker.register_rules([r.title for r in result.rules])

    if args.as_json:
        output = {
            "rules": [
                {
                    "title": r.title,
                    "category": r.category,
                    "tags": r.tags,
                    "confidence": r.confidence,
                    "line": r.line_start,
                }
                for r in result.rules
            ],
            "tag_counts": result.tag_counts,
        }
        if args.effectiveness:
            eff_report = tracker.score_rules(stale_days=args.stale_days)
            output["effectiveness"] = [
                {
                    "title": r.title,
                    "fire_count": r.fire_count,
                    "status": r.status,
                    "unique_days": r.unique_days,
                    "days_since_last": r.days_since_last,
                }
                for r in eff_report.rules
            ]
        print(json.dumps(output, indent=2))
        return

    # Text output
    if args.filter:
        filtered = result.filter_by_tag(args.filter)
        if not filtered:
            print(f"No rules tagged '{args.filter}'.")
            return
        print(f"Rules tagged '{args.filter}' ({len(filtered)} found):")
        for r in filtered:
            print(f"  [{r.confidence}] {r.title}")
        return

    print(result.format_summary())

    if args.detail:
        print()
        print(result.format_detail())

    if args.effectiveness:
        eff_report = tracker.score_rules(stale_days=args.stale_days)
        print()
        print(eff_report.format())


if __name__ == "__main__":
    main()
