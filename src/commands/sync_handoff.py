from __future__ import annotations

"""
/sync-handoff slash command — cross-harness session handoff (item 23).

Generates a context-rich prompt that lets the user continue their Claude Code
session in another AI harness (Gemini CLI, Codex, OpenCode, Cursor, Aider,
Windsurf) without losing context.

Usage examples:

    /sync-handoff --target gemini --task "Refactoring auth middleware"

    /sync-handoff --target codex \\
        --task "Add JWT refresh-token endpoint" \\
        --files src/auth/middleware.py,src/auth/tokens.py \\
        --todo "Write tests for /token/refresh" \\
        --decision "HS256 chosen over RS256 — no PKI infrastructure available"

    /sync-handoff --target cursor --status blocked \\
        --notes "Blocked on: Prisma migration generates wrong SQL for Postgres 15"

    /sync-handoff --load .harness-handoff.json --target opencode
"""

import json
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.session_handoff import SessionHandoff


def main() -> None:
    """Entry point for /sync-handoff command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-handoff",
        description="Generate a cross-harness session handoff prompt",
    )
    parser.add_argument(
        "--target",
        type=str,
        default="default",
        help="Target harness to hand off to (gemini, codex, opencode, cursor, aider, windsurf).",
    )
    parser.add_argument(
        "--task",
        type=str,
        default="",
        help="Brief description of the current task.",
    )
    parser.add_argument(
        "--status",
        type=str,
        default="in-progress",
        choices=["in-progress", "blocked", "done"],
        help="Current task status.",
    )
    parser.add_argument(
        "--files",
        type=str,
        default="",
        help=(
            "Comma-separated list of files involved in the session. "
            "Prefix with 'modified:' or 'created:' or 'deleted:' to set role. "
            "Example: modified:src/auth.py,created:src/tokens.py"
        ),
    )
    parser.add_argument(
        "--todo",
        action="append",
        default=[],
        metavar="ITEM",
        help="Pending work item (repeatable). Example: --todo 'Write tests'",
    )
    parser.add_argument(
        "--decision",
        action="append",
        default=[],
        metavar="TEXT",
        help="Key decision made in this session (repeatable).",
    )
    parser.add_argument(
        "--constraint",
        action="append",
        default=[],
        metavar="TEXT",
        help="Constraint or gotcha the next session should know about (repeatable).",
    )
    parser.add_argument(
        "--notes",
        type=str,
        default="",
        help="Free-form session notes.",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        help="Project root directory (used to shorten paths in output).",
    )
    parser.add_argument(
        "--save",
        type=str,
        default=None,
        metavar="FILE",
        help="Save the handoff context to a JSON file for later use with --load.",
    )
    parser.add_argument(
        "--load",
        type=str,
        default=None,
        metavar="FILE",
        help="Load handoff context from a previously saved JSON file.",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(
        args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    )

    # Load from file if requested
    if args.load:
        load_path = Path(args.load)
        if not load_path.is_absolute():
            load_path = project_dir / load_path
        if not load_path.exists():
            print(f"Error: handoff file not found: {load_path}", file=sys.stderr)
            sys.exit(1)
        try:
            data = json.loads(load_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"Error reading handoff file: {e}", file=sys.stderr)
            sys.exit(1)
        handoff = SessionHandoff.from_dict(data, project_dir=project_dir)
        # Allow CLI flags to override loaded values
        if args.task:
            handoff.set_task(args.task)
        if args.status != "in-progress":
            handoff.set_status(args.status)
        if args.notes:
            handoff.set_notes(args.notes)
    else:
        handoff = SessionHandoff(project_dir=project_dir)
        if args.task:
            handoff.set_task(args.task)
        handoff.set_status(args.status)
        if args.notes:
            handoff.set_notes(args.notes)

    # Add files
    if args.files:
        for entry in args.files.split(","):
            entry = entry.strip()
            if not entry:
                continue
            if ":" in entry:
                role, path = entry.split(":", 1)
                role = role.strip()
                path = path.strip()
            else:
                role = "read"
                path = entry
            handoff.add_file_context(path, role=role)

    # Add todos, decisions, constraints
    for todo in args.todo:
        handoff.add_todo(todo)
    for decision in args.decision:
        handoff.add_decision(decision)
    for constraint in args.constraint:
        handoff.add_constraint(constraint)

    # Save to file if requested
    if args.save:
        save_path = Path(args.save)
        if not save_path.is_absolute():
            save_path = project_dir / save_path
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(
            json.dumps(handoff.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Handoff context saved to: {save_path}")

    # Render and print the handoff prompt
    prompt = handoff.render(target_harness=args.target)
    print("\n" + prompt + "\n")
    print(
        f"── Copy the prompt above and paste it into {args.target} to continue your session. ──"
    )


if __name__ == "__main__":
    main()
