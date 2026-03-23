from __future__ import annotations

"""
/sync-recipe slash command — Config Recipe Marketplace.

Browse and install role-based config starters (Python, frontend, ML,
DevOps) into your CLAUDE.md with one command.  Each recipe adds a curated
set of rules tailored to the selected workflow.

Usage:
    /sync-recipe list [--tag TAG]
    /sync-recipe show <RECIPE_ID>
    /sync-recipe install <RECIPE_ID> [--claude-md PATH] [--dry-run]
    /sync-recipe remove <RECIPE_ID> [--claude-md PATH] [--dry-run]

Examples:
    /sync-recipe list
    /sync-recipe list --tag python
    /sync-recipe show python-backend
    /sync-recipe install python-backend
    /sync-recipe install ml-researcher --dry-run

Exit codes:
    0 — success
    1 — recipe not found or operation failed
"""

import argparse
import os
import re
import sys
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.config_recipe import RecipeRegistry


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sync-recipe",
        description="Browse and install config recipes into CLAUDE.md",
    )
    sub = parser.add_subparsers(dest="subcommand")

    # list
    list_p = sub.add_parser("list", help="List available recipes")
    list_p.add_argument("--tag", default=None, help="Filter by tag (e.g. python, frontend, ml)")

    # show
    show_p = sub.add_parser("show", help="Show recipe details and preview")
    show_p.add_argument("recipe_id", help="Recipe ID")

    # install
    install_p = sub.add_parser("install", help="Install a recipe into CLAUDE.md")
    install_p.add_argument("recipe_id", help="Recipe ID to install")
    install_p.add_argument(
        "--claude-md",
        default=None,
        help="Path to CLAUDE.md (default: CLAUDE.md in cwd or project root)",
    )
    install_p.add_argument("--dry-run", action="store_true", help="Preview without writing")

    # remove
    remove_p = sub.add_parser("remove", help="Remove a previously installed recipe")
    remove_p.add_argument("recipe_id", help="Recipe ID to remove")
    remove_p.add_argument(
        "--claude-md",
        default=None,
        help="Path to CLAUDE.md",
    )
    remove_p.add_argument("--dry-run", action="store_true", help="Preview without writing")

    return parser.parse_args(argv)


def _resolve_claude_md(path_arg: str | None) -> Path:
    """Resolve the target CLAUDE.md path."""
    if path_arg:
        return Path(path_arg)
    # Walk up from cwd looking for CLAUDE.md
    cwd = Path.cwd()
    for candidate in [cwd / "CLAUDE.md", cwd.parent / "CLAUDE.md"]:
        if candidate.is_file():
            return candidate
    return cwd / "CLAUDE.md"


def _cmd_list(args: argparse.Namespace, registry: RecipeRegistry) -> int:
    print(registry.list_recipes(tag=args.tag))
    return 0


def _cmd_show(args: argparse.Namespace, registry: RecipeRegistry) -> int:
    recipe = registry.get(args.recipe_id)
    if recipe is None:
        print(f"Recipe '{args.recipe_id}' not found. Run `/sync-recipe list` to see options.")
        return 1
    print(recipe.format_preview())
    return 0


def _cmd_install(args: argparse.Namespace, registry: RecipeRegistry) -> int:
    recipe = registry.get(args.recipe_id)
    if recipe is None:
        print(f"Recipe '{args.recipe_id}' not found. Run `/sync-recipe list` to see options.")
        return 1

    target = _resolve_claude_md(getattr(args, "claude_md", None))
    result = registry.apply(recipe, target_path=target, dry_run=args.dry_run)
    print(result.format())
    return 0 if not result.error else 1


def _cmd_remove(args: argparse.Namespace, registry: RecipeRegistry) -> int:
    target = _resolve_claude_md(getattr(args, "claude_md", None))
    dry_run: bool = getattr(args, "dry_run", False)
    recipe_id = args.recipe_id

    if not target.is_file():
        print(f"CLAUDE.md not found at {target}.")
        return 1

    try:
        content = target.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Could not read {target}: {exc}")
        return 1

    marker_start = f"<!-- recipe:{recipe_id} -->"
    marker_end = f"<!-- /recipe:{recipe_id} -->"

    if marker_start not in content:
        print(f"Recipe '{recipe_id}' marker not found in {target}. Nothing to remove.")
        return 0

    # Strip the block between markers (inclusive)
    pattern = re.compile(
        rf"\n?{re.escape(marker_start)}.*?{re.escape(marker_end)}\n?",
        re.DOTALL,
    )
    new_content, count = pattern.subn("", content)
    removed_lines = content.count("\n") - new_content.count("\n")

    if dry_run:
        print(f"[dry-run] Would remove {removed_lines} lines for recipe '{recipe_id}' from {target}.")
        return 0

    try:
        target.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        print(f"Could not write {target}: {exc}")
        return 1

    print(f"Removed recipe '{recipe_id}' ({removed_lines} lines) from {target}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = argv if argv is not None else sys.argv[1:]
    args = _parse_args(raw)
    registry = RecipeRegistry()

    if args.subcommand == "list":
        return _cmd_list(args, registry)
    elif args.subcommand == "show":
        return _cmd_show(args, registry)
    elif args.subcommand == "install":
        return _cmd_install(args, registry)
    elif args.subcommand == "remove":
        return _cmd_remove(args, registry)
    else:
        print("Usage: /sync-recipe [list|show|install|remove] ...")
        print("Run `/sync-recipe list` to browse available recipes.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
