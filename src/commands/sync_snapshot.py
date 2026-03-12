from __future__ import annotations

"""
/sync-snapshot slash command — export and import shareable config snapshots.

Share your entire Claude Code config as a file, GitHub Gist, or base64 URL.
Recipients import with one command and HarnessSync handles translation.

Usage:
    /sync-snapshot export [--file PATH] [--gist] [--creator LABEL]
    /sync-snapshot import <file-or-gist-url> [--dry-run] [--no-sync]
    /sync-snapshot show <file>
"""

import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.config_snapshot import ConfigSnapshot
from src.source_reader import SourceReader
from src.utils.logger import Logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync-snapshot",
        description="Export and import shareable Claude Code config snapshots.",
    )
    sub = parser.add_subparsers(dest="subcommand")

    # export
    exp = sub.add_parser("export", help="Export current config as a snapshot")
    exp.add_argument("--file", type=Path, default=None,
                     help="Write snapshot to this file (default: harnesssync-snapshot.json)")
    exp.add_argument("--gist", action="store_true",
                     help="Publish snapshot as a GitHub Gist (requires GITHUB_TOKEN)")
    exp.add_argument("--public", action="store_true",
                     help="Make Gist public (default: secret)")
    exp.add_argument("--creator", default="",
                     help="Optional label to embed in snapshot (e.g. 'neo@acme')")
    exp.add_argument("--project-dir", type=Path, default=None)
    exp.add_argument("--scope", default="all",
                     choices=["user", "project", "all"])

    # import
    imp = sub.add_parser("import", help="Import a config snapshot")
    imp.add_argument("source",
                     help="File path, Gist ID, or Gist URL to import from")
    imp.add_argument("--dry-run", action="store_true",
                     help="Preview import without applying changes")
    imp.add_argument("--no-sync", action="store_true",
                     help="Apply to CLAUDE.md but skip sync to target harnesses")
    imp.add_argument("--project-dir", type=Path, default=None)

    # show
    shw = sub.add_parser("show", help="Show summary of a snapshot file")
    shw.add_argument("file", type=Path, help="Snapshot file to inspect")

    return parser


def cmd_export(args, logger: Logger) -> int:
    project_dir = args.project_dir or Path.cwd()

    reader = SourceReader(scope=args.scope, project_dir=project_dir)
    snapper = ConfigSnapshot(source_reader=reader)

    snapshot = snapper.create(creator=args.creator)

    if args.gist:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            print("Error: GITHUB_TOKEN environment variable not set.", file=sys.stderr)
            print("Set GITHUB_TOKEN to a GitHub token with 'gist' scope.")
            return 1
        try:
            url = snapper.export_to_gist(token, creator=args.creator, public=args.public)
            print(f"Snapshot published to Gist: {url}")
            print(f"\nShare this URL or Gist ID with others.")
            print(f"They import with: /sync-snapshot import {url}")
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    # Write to file
    output_path = args.file or Path.cwd() / "harnesssync-snapshot.json"
    snapper.export_to_file(output_path, creator=args.creator)

    print(f"Snapshot exported to: {output_path}")
    print()
    print(snapper.format_summary(snapshot))
    return 0


def cmd_import(args, logger: Logger) -> int:
    project_dir = args.project_dir or Path.cwd()
    cc_home = Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))
    source = args.source

    snapper = ConfigSnapshot()

    # Load snapshot
    if source.startswith("http") or (len(source) == 32 and source.isalnum()):
        # Gist URL or ID
        print(f"Fetching snapshot from Gist: {source}")
        try:
            snapshot = snapper.load_from_gist(source)
        except (RuntimeError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
    else:
        path = Path(source)
        if not path.exists():
            print(f"Error: File not found: {path}", file=sys.stderr)
            return 1
        try:
            snapshot = snapper.load_from_file(path)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    print(snapper.format_summary(snapshot))

    if args.dry_run:
        print("\n[Dry run — previewing changes]")
        claude_md_path = project_dir / "CLAUDE.md"
        preview = snapper.apply_to_claude_md(snapshot, claude_md_path, dry_run=True)
        print(f"\nCLAUDE.md would become ({len(preview)} chars).")
        if snapshot.get("mcp"):
            print(f"MCP servers would be added: {', '.join(sorted(snapshot['mcp'].keys()))}")
        return 0

    # Apply to CLAUDE.md
    claude_md_path = project_dir / "CLAUDE.md"
    if not claude_md_path.exists():
        claude_md_path = cc_home / "CLAUDE.md"

    if snapshot.get("rules"):
        snapper.apply_to_claude_md(snapshot, claude_md_path)
        print(f"\nRules applied to: {claude_md_path}")

    # Note MCP servers (full import would require settings.json merge)
    mcp = snapshot.get("mcp", {})
    if mcp:
        print(f"\nNote: {len(mcp)} MCP server(s) in snapshot. "
              f"Run /sync to sync them, or manually add to .mcp.json:")
        for name in sorted(mcp.keys()):
            print(f"  - {name}")

    # Sync
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
            print(f"Sync complete: {total_synced} items synced.")
        except Exception as e:
            print(f"Warning: Auto-sync failed: {e}", file=sys.stderr)
            print("Run /sync manually to propagate changes.")

    return 0


def cmd_show(args, logger: Logger) -> int:
    snapper = ConfigSnapshot()
    try:
        snapshot = snapper.load_from_file(args.file)
    except (ValueError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(snapper.format_summary(snapshot))
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        raw = os.environ.get("CLAUDE_ARGS", "")
        argv = shlex.split(raw) if raw else []

    parser = _build_parser()
    args = parser.parse_args(argv)
    logger = Logger()

    if not args.subcommand:
        parser.print_help()
        return 0

    if args.subcommand == "export":
        return cmd_export(args, logger)
    elif args.subcommand == "import":
        return cmd_import(args, logger)
    elif args.subcommand == "show":
        return cmd_show(args, logger)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
