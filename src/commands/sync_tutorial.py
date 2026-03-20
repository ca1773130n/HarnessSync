from __future__ import annotations

"""
/sync-tutorial slash command implementation.

Interactive tutorial engine that walks users through configuring
a real Python project (TaskFlow) with every Claude Code config layer:
CLAUDE.md, rules, settings, commands, skills, agents, MCP, hooks,
and harness annotations.

9 steps total. Each step adds real config files and explains what they do.

Implementation split across:
- tutorial_content.py — scaffolding, step file templates, step guide text
- tutorial_engine.py — state management and action handlers
"""

import argparse
import sys
from pathlib import Path

PLUGIN_ROOT = str(Path(__file__).resolve().parent.parent.parent)
sys.path.insert(0, PLUGIN_ROOT)

# Re-export everything that tests and other modules import
from src.commands.tutorial_content import (  # noqa: E402, F401
    TOTAL_STEPS,
    add_step_files,
    get_step_guide,
    scaffold_project,
)
from src.commands.tutorial_engine import (  # noqa: E402, F401
    STATE_FILE,
    STEP_MARKERS,
    STEP_NAMES,
    handle_cleanup,
    handle_goto,
    handle_next,
    handle_reset,
    handle_start,
    handle_status,
    load_state,
    reconstruct_state,
    save_state,
)


# ============================================================================
# CLI Parsing
# ============================================================================

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse tutorial command arguments."""
    parser = argparse.ArgumentParser(
        prog="sync-tutorial",
        description="Interactive HarnessSync tutorial engine",
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    # Each subparser inherits --dir so it can appear before or after the action
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--dir",
        default=None,
        help="Tutorial project directory (default: /tmp/taskflow-playground)",
    )

    subparsers.add_parser("start", parents=[parent], help="Start the tutorial from step 1")
    subparsers.add_parser("next", parents=[parent], help="Advance to the next step")
    subparsers.add_parser("reset", parents=[parent], help="Reset tutorial state (keeps app code)")
    subparsers.add_parser("status", parents=[parent], help="Show current tutorial progress")
    subparsers.add_parser("cleanup", parents=[parent], help="Remove the tutorial directory entirely")

    goto_parser = subparsers.add_parser("goto", parents=[parent], help="Jump to a specific step")
    goto_parser.add_argument("step_num", type=int, help="Step number to jump to (1-9)")

    parsed = parser.parse_args(argv)
    # Merge: top-level --dir is the fallback, subparser --dir overrides
    top_dir = getattr(parsed, "dir", None)
    if top_dir is None:
        parsed.dir = "/tmp/taskflow-playground"
    return parsed


# ============================================================================
# Main
# ============================================================================

def main(argv: list[str] | None = None) -> None:
    """Parse args and dispatch to the appropriate handler."""
    args = parse_args(argv)
    target_dir = Path(args.dir)

    dispatch = {
        "start": lambda: handle_start(target_dir),
        "next": lambda: handle_next(target_dir),
        "status": lambda: handle_status(target_dir),
        "reset": lambda: handle_reset(target_dir),
        "cleanup": lambda: handle_cleanup(target_dir),
        "goto": lambda: handle_goto(target_dir, args.step_num),
    }

    output = dispatch[args.action]()
    print(output)


if __name__ == "__main__":
    main()
