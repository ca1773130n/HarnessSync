from __future__ import annotations

"""
/sync-scope slash command — Rule Scope & Priority Visualizer (item 19).

Displays which CLAUDE.md rules apply at each scope level (global, project,
subdirectory) and highlights conflicts where the same rule name appears at
multiple scopes.

With --assets, also shows which skills/agents/commands will be synced to each
registered target harness based on YAML frontmatter ``sync:`` tags.

Usage:
    /sync-scope                          # show scope tree for current project
    /sync-scope --project-dir /path      # override project directory
    /sync-scope --assets                 # also show per-target asset visibility
    /sync-scope --assets --target codex  # show asset visibility for one target
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


def _show_asset_scope(project_dir: Path, cc_home: Path, target_filter: str | None) -> None:
    """Print per-target asset visibility matrix for skills and agents."""
    try:
        from src.source_reader import SourceReader
        from src.skill_sync_tags import (
            parse_skill_sync_tag,
            parse_agent_sync_tag,
            skill_allowed_for_target,
            describe_skill_sync_tag,
        )
        from src.adapters import AdapterRegistry
    except ImportError as e:
        print(f"  (asset scope unavailable: {e})")
        return

    reader = SourceReader(scope="all", project_dir=project_dir, cc_home=cc_home)
    skills = reader.get_skills()
    agents = reader.get_agents()
    commands = reader.get_commands()

    targets = AdapterRegistry.list_targets()
    if target_filter:
        targets = [t for t in targets if t == target_filter.lower()]
        if not targets:
            print(f"  (no registered target named {target_filter!r})")
            return

    # --- Skills ---
    if skills:
        print()
        print("Skills → target visibility:")
        print("-" * 40)
        for name, path in sorted(skills.items()):
            tag = parse_skill_sync_tag(path)
            allowed = [t for t in targets if skill_allowed_for_target(tag, t)]
            denied = [t for t in targets if not skill_allowed_for_target(tag, t)]
            tag_desc = describe_skill_sync_tag(tag)
            if denied:
                print(f"  {name}  [{tag_desc}]")
                print(f"    syncs to:    {', '.join(allowed) or '(none)'}")
                print(f"    blocked for: {', '.join(denied)}")
            else:
                print(f"  {name}  [all targets]")
    else:
        print()
        print("Skills: (none found)")

    # --- Agents ---
    if agents:
        print()
        print("Agents → target visibility:")
        print("-" * 40)
        for name, path in sorted(agents.items()):
            tag = parse_agent_sync_tag(path)
            allowed = [t for t in targets if skill_allowed_for_target(tag, t)]
            denied = [t for t in targets if not skill_allowed_for_target(tag, t)]
            tag_desc = describe_skill_sync_tag(tag)
            if denied:
                print(f"  {name}  [{tag_desc}]")
                print(f"    syncs to:    {', '.join(allowed) or '(none)'}")
                print(f"    blocked for: {', '.join(denied)}")
            else:
                print(f"  {name}  [all targets]")
    else:
        print()
        print("Agents: (none found)")

    # --- Commands: no sync tag support yet, just count ---
    if commands:
        print()
        print(f"Commands: {len(commands)} found (no per-target filtering — all sync everywhere)")


def main() -> None:
    """Entry point for /sync-scope command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-scope",
        description="Visualize rule scope hierarchy, detect conflicts, and preview asset sync targets.",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Override project directory (default: current directory)",
    )
    parser.add_argument(
        "--assets",
        action="store_true",
        help="Show per-target visibility for skills, agents, and commands based on sync: frontmatter tags",
    )
    parser.add_argument(
        "--target",
        default=None,
        metavar="TARGET",
        help="With --assets: restrict output to a single target harness (e.g. codex)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    cc_home = default_cc_home()

    rules = build_scope_map(project_dir, cc_home=cc_home)

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

    if args.assets:
        _show_asset_scope(project_dir, cc_home, target_filter=args.target)


if __name__ == "__main__":
    main()
