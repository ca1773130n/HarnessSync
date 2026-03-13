from __future__ import annotations

"""
/sync-attribution slash command implementation.

Shows rule source attribution: where each synced rule came from in your
source CLAUDE.md files (file, line number, section heading).

Usage:
    /sync-attribution                     # show all tracked rule sources
    /sync-attribution --lookup "rule text"  # find source for a specific rule
    /sync-attribution --rebuild           # re-scan source files and rebuild index
    /sync-attribution --count             # show count only
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.rule_source_attribution import RuleAttributor, extract_rule_sources


def main() -> None:
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-attribution",
        description="Show source attribution for synced rules.",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project directory (default: cwd)",
    )
    parser.add_argument(
        "--lookup",
        metavar="RULE_TEXT",
        default=None,
        help="Find source for a specific rule fragment",
    )
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Re-scan source files and rebuild the attribution index",
    )
    parser.add_argument(
        "--count",
        action="store_true",
        help="Show rule count only",
    )

    try:
        args = parser.parse_args(raw_args)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    if args.rebuild:
        source_files = []
        for name in ["CLAUDE.md", "CLAUDE.local.md"]:
            p = project_dir / name
            if p.is_file():
                source_files.append(p)
        cc_home = Path.home() / ".claude"
        for name in ["CLAUDE.md"]:
            p = cc_home / name
            if p.is_file():
                source_files.append(p)

        attributor = extract_rule_sources(source_files, project_dir=project_dir)
        attributor.save_index()
        print(f"Attribution index rebuilt: {attributor.rule_count} rule(s) tracked")
        for sf in source_files:
            try:
                rel = sf.relative_to(project_dir)
            except ValueError:
                rel = sf
            print(f"  Scanned: {rel}")
        return

    attributor = RuleAttributor(project_dir=project_dir)

    if args.count:
        print(f"Tracked rules: {attributor.rule_count}")
        return

    if args.lookup:
        source = attributor.lookup(args.lookup)
        if source:
            print(f"Rule source: {source.format()}")
            print(f"  Preview: {source.content_preview[:80]}")
        else:
            print(f"No attribution found for: {args.lookup!r}")
            print("Run /sync-attribution --rebuild to index the current source files.")
        return

    # Default: show full report
    report = attributor.format_attribution_report(max_entries=50)
    print(report)

    if attributor.rule_count == 0:
        print("Tip: run /sync-attribution --rebuild to populate the index,")
        print("     or just run /sync (attribution is recorded automatically).")


if __name__ == "__main__":
    main()
