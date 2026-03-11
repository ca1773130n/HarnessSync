from __future__ import annotations

"""
/sync-template slash command — browse and apply config templates.

Browse community templates by language, framework, or domain, apply
them to CLAUDE.md, and immediately sync to all target harnesses.

Usage:
    /sync-template list                      # Show all templates
    /sync-template list --tag python         # Filter by tag
    /sync-template search 'fastapi'          # Search by query
    /sync-template apply python-fastapi      # Apply a template
    /sync-template apply python-fastapi --mode replace
    /sync-template show python-fastapi       # Preview a template
"""

import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.template_registry import TemplateRegistry
from src.utils.logger import Logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync-template",
        description="Browse and apply Claude Code configuration templates.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    # list
    lst = sub.add_parser("list", help="List available templates")
    lst.add_argument("--tag", default="", help="Filter by tag")

    # search
    srch = sub.add_parser("search", help="Search templates")
    srch.add_argument("query", help="Search query")

    # show
    shw = sub.add_parser("show", help="Preview a template's rules")
    shw.add_argument("name", help="Template name")

    # apply
    app = sub.add_parser("apply", help="Apply a template to CLAUDE.md")
    app.add_argument("name", help="Template name")
    app.add_argument(
        "--mode",
        choices=["append", "prepend", "replace"],
        default="append",
        help="How to apply: append (default), prepend, or replace",
    )
    app.add_argument("--dry-run", action="store_true",
                     help="Preview without applying")
    app.add_argument("--no-sync", action="store_true",
                     help="Apply to CLAUDE.md but skip sync to target harnesses")
    app.add_argument("--project-dir", type=Path, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        raw = os.environ.get("CLAUDE_ARGS", "")
        argv = shlex.split(raw) if raw else []

    parser = _build_parser()
    args = parser.parse_args(argv)
    logger = Logger()
    registry = TemplateRegistry()

    if not args.subcommand or args.subcommand == "list":
        tag = getattr(args, "tag", "")
        if tag:
            templates = registry.list_by_tag(tag)
        else:
            templates = registry.list_all()
        print(registry.format_catalog(templates))
        return 0

    if args.subcommand == "search":
        results = registry.search(args.query)
        if not results:
            print(f"No templates found matching: {args.query!r}")
            return 0
        print(registry.format_catalog(results))
        return 0

    if args.subcommand == "show":
        template = registry.get(args.name)
        if not template:
            print(f"Template not found: {args.name!r}", file=sys.stderr)
            print("Run '/sync-template list' to see available templates.")
            return 1
        print(f"Template: {template.title}")
        print(f"Tags: {', '.join(template.tags)}")
        print(f"Description: {template.description}")
        if template.mcp_suggestions:
            print(f"Suggested MCP: {', '.join(template.mcp_suggestions)}")
        print("\n" + "=" * 50 + "\n")
        print(template.rules)
        return 0

    if args.subcommand == "apply":
        template = registry.get(args.name)
        if not template:
            print(f"Template not found: {args.name!r}", file=sys.stderr)
            print("Run '/sync-template list' to see available templates.")
            return 1

        project_dir = args.project_dir or Path.cwd()
        claude_md_path = project_dir / "CLAUDE.md"
        if not claude_md_path.exists():
            claude_md_path = Path.home() / ".claude" / "CLAUDE.md"

        if args.dry_run:
            print(f"[Dry run] Would apply template '{template.name}' ({args.mode} mode)")
            print(f"Target: {claude_md_path}")
            print(f"\nTemplate rules preview:")
            print(template.rules[:400] + ("..." if len(template.rules) > 400 else ""))
            return 0

        new_content = registry.apply_to_claude_md(template, claude_md_path, mode=args.mode)
        print(f"Applied template '{template.title}' to {claude_md_path}")
        print(f"Mode: {args.mode} | Lines: {len(new_content.splitlines())}")

        if template.mcp_suggestions:
            print(f"\nThis template suggests these MCP servers: {', '.join(template.mcp_suggestions)}")
            print("Add them to .mcp.json or run '/sync-mcp-health' to check.")

        if not args.no_sync:
            print("\nSyncing to all harnesses...")
            try:
                from src.orchestrator import SyncOrchestrator
                orchestrator = SyncOrchestrator(project_dir=project_dir)
                results = orchestrator.sync_all()
                total_synced = sum(
                    sum(r.synced for r in tr.values() if hasattr(r, "synced"))
                    for tr in results.values()
                    if isinstance(tr, dict)
                )
                print(f"Sync complete: {total_synced} items propagated.")
            except Exception as e:
                print(f"Warning: Sync failed: {e}", file=sys.stderr)
                print("Run /sync manually to propagate changes.")

        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
