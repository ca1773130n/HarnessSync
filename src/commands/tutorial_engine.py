from __future__ import annotations

"""Tutorial engine: state management and action handlers for /sync-tutorial.

This module contains the stateful logic for the tutorial:
- State persistence (save/load/reconstruct)
- Action handlers (start, next, status, goto, reset, cleanup)
"""

import json
import shutil
from pathlib import Path

from src.commands.tutorial_content import (
    TOTAL_STEPS,
    add_step_files,
    get_step_guide,
    scaffold_project,
)

STATE_FILE = ".tutorial-state.json"

# Step number -> sentinel file that proves the step was completed
STEP_MARKERS = {
    1: "taskflow/__init__.py",
    2: "CLAUDE.md",
    3: ".claude/rules/python.md",
    4: ".claude/settings.json",
    5: ".claude/commands/check.md",
    6: ".claude/skills/add-feature.md",
    7: ".mcp.json",
    8: "hooks.json",
}

STEP_NAMES = {
    1: "Project Scaffolding",
    2: "CLAUDE.md",
    3: "Scoped Rules",
    4: "Settings / Permissions",
    5: "Custom Commands",
    6: "Skills & Agents",
    7: "MCP Servers",
    8: "Hooks & Annotations",
    9: "Tutorial Complete",
}


# ============================================================================
# State Management
# ============================================================================

def save_state(target_dir: Path | str, current_step: int, completed_steps: list[int]) -> None:
    """Persist tutorial state to .tutorial-state.json."""
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "current_step": current_step,
        "completed_steps": sorted(set(completed_steps)),
    }
    (target_dir / STATE_FILE).write_text(json.dumps(state, indent=2) + "\n")


def load_state(target_dir: Path | str) -> dict | None:
    """Load tutorial state. Returns None if no state file exists."""
    state_path = Path(target_dir) / STATE_FILE
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def reconstruct_state(target_dir: Path | str) -> dict | None:
    """Detect tutorial progress from existing files when state file is missing."""
    target_dir = Path(target_dir)
    if not target_dir.exists():
        return None

    completed = []
    for step, marker in STEP_MARKERS.items():
        if (target_dir / marker).exists():
            completed.append(step)

    if not completed:
        return None

    current = max(completed)
    return {"current_step": current, "completed_steps": completed}


# ============================================================================
# Action Handlers
# ============================================================================

def handle_start(target_dir: Path | str) -> str:
    """Start the tutorial: scaffold project, save state at step 1."""
    target_dir = Path(target_dir)

    if target_dir.exists() and load_state(target_dir) is not None:
        # Already started — clean up config files before re-scaffolding
        handle_reset(target_dir)

    scaffold_project(target_dir)
    save_state(target_dir, current_step=1, completed_steps=[1])
    return get_step_guide(1, str(target_dir))


def handle_next(target_dir: Path | str) -> str:
    """Advance to the next step."""
    target_dir = Path(target_dir)
    state = load_state(target_dir) or reconstruct_state(target_dir)

    if state is None:
        return (
            "No tutorial in progress. Run `/sync-tutorial start` to begin.\n\n"
            "If you have an existing tutorial directory, try `/sync-tutorial start` "
            "to set it up."
        )

    current = state["current_step"]
    completed = state["completed_steps"]

    if current >= TOTAL_STEPS:
        return (
            "You've already completed all 9 steps! The tutorial is finished.\n\n"
            "Run `/sync-tutorial status` to review your progress, or "
            "`/sync-tutorial cleanup` to remove the tutorial directory."
        )

    next_step = current + 1
    add_step_files(target_dir, next_step)
    completed.append(next_step)
    save_state(target_dir, current_step=next_step, completed_steps=completed)
    return get_step_guide(next_step, str(target_dir))


def handle_status(target_dir: Path | str) -> str:
    """Show current tutorial progress."""
    target_dir = Path(target_dir)
    state = load_state(target_dir)

    if state is None:
        return "No tutorial in progress. Run `/sync-tutorial start` to begin."

    current = state["current_step"]
    completed = sorted(state["completed_steps"])

    lines = [
        f"## Tutorial Progress: Step {current} of {TOTAL_STEPS}\n",
        f"**Directory:** `{target_dir}`\n",
    ]

    for step in range(1, TOTAL_STEPS + 1):
        if step in completed:
            marker = "[x]"
        elif step == current + 1:
            marker = "[ ] <-- next"
        else:
            marker = "[ ]"
        lines.append(f"  {marker} Step {step}: {STEP_NAMES[step]}")

    if current < TOTAL_STEPS:
        lines.append(f"\nRun `/sync-tutorial next` to proceed to Step {current + 1}.")
    else:
        lines.append("\nAll steps completed!")

    return "\n".join(lines)


def handle_goto(target_dir: Path | str, step_num: int) -> str:
    """Jump to a specific step, ensuring all prerequisite steps have files."""
    target_dir = Path(target_dir)

    if step_num < 1 or step_num > TOTAL_STEPS:
        return f"Invalid step number: {step_num}. Must be between 1 and {TOTAL_STEPS}."

    state = load_state(target_dir)
    if state is None:
        # Auto-start if needed
        scaffold_project(target_dir)
        completed = [1]
    else:
        completed = list(state["completed_steps"])
        if 1 not in completed:
            completed.append(1)

    # Ensure all steps up to step_num have their files
    for s in range(2, step_num + 1):
        add_step_files(target_dir, s)
        if s not in completed:
            completed.append(s)

    save_state(target_dir, current_step=step_num, completed_steps=completed)
    return get_step_guide(step_num, str(target_dir))


def handle_reset(target_dir: Path | str) -> str:
    """Remove tutorial state and config files, but keep the app code."""
    target_dir = Path(target_dir)

    if not target_dir.exists():
        return f"Directory does not exist: {target_dir}"

    # Remove state file
    state_path = target_dir / STATE_FILE
    if state_path.exists():
        state_path.unlink()

    # Remove config files added by tutorial steps
    config_paths = [
        target_dir / "CLAUDE.md",
        target_dir / ".claude",
        target_dir / ".mcp.json",
        target_dir / "hooks.json",
    ]
    for p in config_paths:
        if p.is_dir():
            shutil.rmtree(p)
        elif p.is_file():
            p.unlink()

    return (
        "Tutorial state and config files removed.\n"
        "The TaskFlow app code is still intact.\n\n"
        "Run `/sync-tutorial start` to begin again."
    )


def handle_cleanup(target_dir: Path | str) -> str:
    """Remove the entire tutorial directory."""
    target_dir = Path(target_dir)

    if not target_dir.exists():
        return f"Directory does not exist: {target_dir}"

    shutil.rmtree(target_dir)
    return f"Removed tutorial directory: {target_dir}"
