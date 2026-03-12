from __future__ import annotations

"""
/sync-agent-mesh slash command — sync Claude Code multi-agent config to other harnesses.

Reads agent definitions from .claude/agents/ and command .md files, then
writes translated agent configurations to Gemini, OpenCode, Codex, Cursor,
Aider, and Windsurf target formats.

Usage:
    /sync-agent-mesh [--targets TARGETS] [--dry-run] [--json] [--project-dir PATH]

Options:
    --targets TARGETS    Comma-separated list of targets (default: all installed)
    --dry-run            Compute output without writing files
    --json               Output report as JSON
    --cc-home PATH       Claude Code home directory (default: ~/.claude)
    --project-dir PATH   Project directory (default: cwd)
"""

import json
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.agent_mesh_sync import AgentMeshSync


def main():
    """Entry point for /sync-agent-mesh command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-agent-mesh",
        description="Sync Claude Code multi-agent configuration to other harnesses.",
    )
    parser.add_argument("--targets", default=None,
                        help="Comma-separated targets (codex,gemini,opencode,...)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute output without writing files")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Output report as JSON")
    parser.add_argument("--cc-home", default=None, help="Claude Code home directory")
    parser.add_argument("--project-dir", default=None)

    args = parser.parse_args(raw_args)

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    cc_home = Path(args.cc_home).resolve() if args.cc_home else (Path.home() / ".claude")

    targets = None
    if args.targets:
        targets = [t.strip() for t in args.targets.split(",") if t.strip()]

    sync = AgentMeshSync(cc_home=cc_home, project_dir=project_dir, dry_run=args.dry_run)

    if args.dry_run:
        print("Dry-run mode: computing agent mesh sync (no files written)…")
    else:
        print("Syncing agent mesh…")

    results = sync.sync_to_targets(targets)

    if args.output_json:
        output = [
            {
                "target": r.target,
                "agents_synced": r.agents_synced,
                "fidelity_score": r.fidelity_score,
                "features_lost": r.features_lost,
                "output_files": r.output_files,
                "errors": r.errors,
            }
            for r in results
        ]
        print(json.dumps(output, indent=2))
    else:
        print(sync.format_report(results))

    errors = [r for r in results if r.errors]
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
