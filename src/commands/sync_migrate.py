from __future__ import annotations

"""
/sync-migrate slash command — migrate an existing harness configuration into Claude Code.

Scans a source harness (Cursor, Aider, Gemini, Codex, OpenCode, or Windsurf)
and imports its rules, MCP servers, and settings into Claude Code equivalents.

Usage:
    /sync-migrate [--from HARNESS] [--apply] [--dry-run] [--project-dir PATH]

Options:
    --from HARNESS     Source harness to migrate from (cursor|aider|gemini|codex|opencode|windsurf).
                       If omitted, auto-detects the first harness with config.
    --apply            Write the migration to disk (default: dry-run / show plan only)
    --dry-run          Explicitly show plan without writing (default behaviour)
    --project-dir PATH Project directory (default: cwd)
    --cc-home PATH     Claude Code home directory (default: ~/.claude)
    --json             Output plan as JSON
"""

import json
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.migration_assistant import MigrationAssistant

SUPPORTED_HARNESSES = ["cursor", "aider", "gemini", "codex", "opencode", "windsurf"]


def main():
    """Entry point for /sync-migrate command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-migrate",
        description="Migrate an existing harness configuration into Claude Code.",
    )
    parser.add_argument("--from", dest="source_harness", default=None,
                        choices=SUPPORTED_HARNESSES,
                        help="Source harness to migrate from")
    parser.add_argument("--apply", action="store_true",
                        help="Write migration to disk (default: show plan only)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show plan without writing (default)")
    parser.add_argument("--scaffold-skills", action="store_true",
                        help="Generate Claude Code skill scaffold from migrated rules")
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--cc-home", default=None)
    parser.add_argument("--json", dest="output_json", action="store_true")

    args = parser.parse_args(raw_args)

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    cc_home = Path(args.cc_home).resolve() if args.cc_home else (Path.home() / ".claude")

    assistant = MigrationAssistant(project_dir=project_dir, cc_home=cc_home)

    print(f"Scanning for {'source harness' if args.source_harness is None else args.source_harness} config…\n")
    plan = assistant.scan(source_harness=args.source_harness)

    if not plan.items:
        harness_label = args.source_harness or "any supported harness"
        print(f"No config found for {harness_label} in {project_dir}")
        print(f"Checked: {', '.join(SUPPORTED_HARNESSES)}")
        return

    if args.output_json:
        output = {
            "source_harness": plan.source_harness,
            "items": [
                {
                    "source_file": item.source_file,
                    "item_type": item.item_type,
                    "proposed_target": item.proposed_target,
                    "confidence": item.confidence,
                    "notes": item.notes,
                }
                for item in plan.items
            ],
            "skipped": [
                {"file": f, "reason": r} for f, r in plan.skipped
            ],
        }
        print(json.dumps(output, indent=2))
        return

    print(assistant.format_plan(plan))

    if args.apply and not args.dry_run:
        print("\nApplying migration…")
        written = assistant.apply(plan, dry_run=False)
        print(f"\n✓ Migration applied. Files written:")
        for f in written:
            print(f"  {f}")

        if args.scaffold_skills:
            scaffolds = assistant.generate_skills_scaffold(plan)
            if scaffolds:
                skill_files = assistant.apply_skills_scaffold(scaffolds, dry_run=False)
                print(f"\n✓ Skills scaffold generated ({len(scaffolds)} skill(s)):")
                for sf in skill_files:
                    print(f"  {sf}")
                print("  Edit each SKILL.md to refine the trigger description and content.")
            else:
                print("\nNo rule items found for skills scaffold generation.")

        print("\nReview CLAUDE.md for migrated content and adjust as needed.")
    else:
        if args.scaffold_skills:
            scaffolds = assistant.generate_skills_scaffold(plan)
            if scaffolds:
                print(f"\n[DRY RUN] Would generate {len(scaffolds)} skill scaffold(s):")
                for s in scaffolds:
                    print(f"  .claude/skills/{s['name']}/SKILL.md  (from {s['source']})")
            else:
                print("\nNo rule items found for skills scaffold generation.")
        print("\nRun with --apply to write these changes to disk.")


if __name__ == "__main__":
    main()
