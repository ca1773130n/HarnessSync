from __future__ import annotations

"""
/sync-memory slash command implementation.

Syncs Claude Code memory files (.claude/memory/) to equivalent persistent
context mechanisms in all configured target harnesses.  Ensures that project
knowledge accumulated in Claude Code is available when switching to another
harness mid-session.

Usage:
    /sync-memory [--dry-run] [--target TARGET] [--project-dir PATH]

Options:
    --dry-run           Preview which files would be written without writing
    --target TARGET     Sync to a specific harness only (default: all)
    --project-dir PATH  Project directory (default: cwd)
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.cross_harness_memory_sync import CrossHarnessMemorySync, discover_memories


def main() -> None:
    """Entry point for /sync-memory command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-memory",
        description="Sync Claude Code memory files to all target harnesses",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview changes without writing files",
    )
    parser.add_argument(
        "--target",
        help="Sync to this specific harness only (e.g. gemini, codex)",
    )
    parser.add_argument(
        "--project-dir", default=None,
        help="Project directory (default: cwd)",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List discovered memory files without syncing",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(
        args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    )

    syncer = CrossHarnessMemorySync(project_dir=project_dir, dry_run=args.dry_run)

    if args.list:
        memories = discover_memories(project_dir)
        if not memories:
            print("No memory files found in .claude/memory/")
            print(f"(Searched: {project_dir / '.claude' / 'memory'})")
            return
        print(f"Found {len(memories)} memory file(s):")
        for mem in memories:
            print(f"  [{mem.scope}] {mem.name}  ({mem.modified_at})")
            preview = mem.content[:80].replace("\n", " ")
            if len(mem.content) > 80:
                preview += "…"
            print(f"           {preview}")
        return

    if args.target:
        result = syncer.sync_to_target(args.target)
        if result.ok:
            mode = " [DRY RUN]" if args.dry_run else ""
            print(f"Memory sync{mode}: {result.synced_count} file(s) → {result.target_path}")
        else:
            print(f"Error syncing to {args.target}: {result.error}", file=sys.stderr)
        return

    # Sync to all targets
    memories = discover_memories(project_dir)
    if not memories:
        print("No memory files found in .claude/memory/")
        print(f"Create .md files in {project_dir / '.claude' / 'memory'} to get started.")
        return

    results = syncer.sync_to_all()
    print(syncer.format_summary(results))

    errors = [r for r in results if not r.ok]
    if errors:
        print(f"\nWarnings ({len(errors)} target(s) had issues):")
        for r in errors:
            print(f"  {r.target}: {r.error}")


if __name__ == "__main__":
    main()
