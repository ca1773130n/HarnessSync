from __future__ import annotations

"""
/sync-scope slash command — Rule Scope & Priority Visualizer (item 19).

Displays which CLAUDE.md rules apply at each scope level (global, project,
subdirectory) and highlights conflicts where the same rule name appears at
multiple scopes.

Usage:
    /sync-scope                          # show scope tree for current project
    /sync-scope --project-dir /path      # override project directory
"""

import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.rule_dependency_viz import build_scope_map, format_scope_tree
from src.utils.paths import default_cc_home


def main() -> None:
    """Entry point for /sync-scope command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-scope",
        description="Visualize rule scope hierarchy and detect conflicts.",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Override project directory (default: current directory)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    rules = build_scope_map(project_dir, cc_home=default_cc_home())

    print(format_scope_tree(rules))

    # Summary line with counts per scope and number of conflicts
    scope_counts: dict[str, int] = {}
    conflict_names: set[str] = set()
    for rule in rules:
        scope_counts[rule.scope] = scope_counts.get(rule.scope, 0) + 1
        if rule.conflicts_with:
            conflict_names.add(rule.name.lower())

    total = len(rules)
    parts = [f"{count} {scope}" for scope, count in scope_counts.items() if count > 0]
    conflict_count = len(conflict_names)
    conflict_label = f"{conflict_count} conflict(s)" if conflict_count else "no conflicts"
    print(f"Summary: {total} rule(s) ({', '.join(parts)}), {conflict_label}.")


if __name__ == "__main__":
    main()
