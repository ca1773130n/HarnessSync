# TaskFlow Tutorial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an interactive `/sync-tutorial` command that scaffolds a TaskFlow todo app and guides users through all 9 HarnessSync config surfaces step by step.

**Architecture:** A single slash command (`commands/sync-tutorial.md`) delegates to a Python engine (`src/commands/sync_tutorial.py`) that embeds all templates as string constants. The engine scaffolds the project, tracks state via `.tutorial-state.json`, and prints step guides. A static reference doc (`docs/tutorial-reference.md`) serves GitHub browsers.

**Tech Stack:** Python 3.10+, stdlib only (argparse, json, pathlib, shutil, datetime, textwrap)

**Spec:** `docs/superpowers/specs/2026-03-19-taskflow-tutorial-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/commands/sync_tutorial.py` | Tutorial engine: CLI parsing, scaffolding, state management, step guides, all embedded templates |
| `commands/sync-tutorial.md` | Slash command definition (frontmatter + usage + `!PY=...` execution line) |
| `docs/tutorial-reference.md` | Static reference for GitHub browsers describing what the tutorial covers |
| `tests/test_sync_tutorial.py` | Tests for scaffolding, state management, step progression, error handling |

---

### Task 1: Slash Command Definition

**Files:**
- Create: `commands/sync-tutorial.md`

- [ ] **Step 1: Create the slash command markdown file**

```markdown
---
description: Interactive tutorial — scaffold a TaskFlow example project and learn HarnessSync step by step
---

Learn HarnessSync by building a real project. Scaffolds a TaskFlow todo app and walks you through
syncing every config surface (CLAUDE.md, rules, permissions, skills, agents, commands, MCP, hooks,
annotations) to all 11 target harnesses.

Usage: /sync-tutorial [action] [--dir PATH]

Actions:
- start: Scaffold the example project and begin the tutorial
- next: Advance to the next step (default)
- reset: Remove tutorial state and start over
- status: Show current step and progress
- goto N: Jump to step N (for returning users)
- cleanup: Remove the scaffolded project directory entirely

Options:
- --dir PATH: Target directory (default: /tmp/taskflow-playground)

Examples:
- /sync-tutorial start                    # Begin the tutorial
- /sync-tutorial start --dir ~/playground # Use custom directory
- /sync-tutorial next                     # Proceed to next step
- /sync-tutorial goto 8                   # Jump to annotations step
- /sync-tutorial status                   # Check progress

!PY=$(command -v python3 || command -v python) && [ -n "$PY" ] || { echo "Error: Python not found. Install Python 3 to use HarnessSync." >&2; exit 1; }; "$PY" ${CLAUDE_PLUGIN_ROOT}/src/commands/sync_tutorial.py $ARGUMENTS
```

- [ ] **Step 2: Commit**

```bash
git add commands/sync-tutorial.md
git commit -m "feat: add /sync-tutorial slash command definition"
```

---

### Task 2: Tutorial Engine — CLI Parsing & State Management

**Files:**
- Create: `src/commands/sync_tutorial.py`
- Create: `tests/test_sync_tutorial.py`

- [ ] **Step 1: Write failing tests for state management and CLI parsing**

```python
from __future__ import annotations

"""Tests for /sync-tutorial command."""

import json
import os
import sys
import shutil
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestStateManagement:
    """Test tutorial state load/save/reconstruct."""

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_and_load_state(self):
        from src.commands.sync_tutorial import save_state, load_state
        save_state(self.tmp, current_step=2, completed_steps=[1, 2])
        state = load_state(self.tmp)
        assert state["current_step"] == 2
        assert state["completed_steps"] == [1, 2]
        assert "started_at" in state

    def test_load_state_missing_file(self):
        from src.commands.sync_tutorial import load_state
        state = load_state(self.tmp)
        assert state is None

    def test_reconstruct_state_from_files(self):
        from src.commands.sync_tutorial import reconstruct_state
        # Create CLAUDE.md (step 2) and .claude/rules/ (step 3)
        (self.tmp / "CLAUDE.md").write_text("# TaskFlow")
        (self.tmp / ".claude" / "rules").mkdir(parents=True)
        (self.tmp / ".claude" / "rules" / "python.md").write_text("rules")
        state = reconstruct_state(self.tmp)
        assert 2 in state["completed_steps"]
        assert 3 in state["completed_steps"]


class TestCLIParsing:
    """Test argument parsing."""

    def test_parse_start(self):
        from src.commands.sync_tutorial import parse_args
        args = parse_args(["start"])
        assert args.action == "start"
        assert args.dir == "/tmp/taskflow-playground"

    def test_parse_start_with_dir(self):
        from src.commands.sync_tutorial import parse_args
        args = parse_args(["start", "--dir", "/tmp/custom"])
        assert args.action == "start"
        assert args.dir == "/tmp/custom"

    def test_parse_next_default(self):
        from src.commands.sync_tutorial import parse_args
        args = parse_args([])
        assert args.action == "next"

    def test_parse_goto(self):
        from src.commands.sync_tutorial import parse_args
        args = parse_args(["goto", "5"])
        assert args.action == "goto"
        assert args.step_num == 5

    def test_parse_status(self):
        from src.commands.sync_tutorial import parse_args
        args = parse_args(["status"])
        assert args.action == "status"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_sync_tutorial.py -v
```

Expected: ModuleNotFoundError or ImportError

- [ ] **Step 3: Implement CLI parsing and state management**

Create `src/commands/sync_tutorial.py` with:

```python
from __future__ import annotations

"""
/sync-tutorial slash command implementation.

Interactive tutorial that scaffolds a TaskFlow todo app and walks users
through all HarnessSync config surfaces step by step.
"""

import argparse
import json
import os
import shutil
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

# Resolve project root for imports
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

DEFAULT_DIR = "/tmp/taskflow-playground"
TOTAL_STEPS = 9
STATE_FILE = ".tutorial-state.json"


# ---------------------------------------------------------------------------
# CLI Parsing
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sync-tutorial",
        description="Interactive HarnessSync tutorial",
    )
    parser.add_argument(
        "action",
        nargs="?",
        default="next",
        choices=["start", "next", "reset", "status", "goto", "cleanup"],
        help="Tutorial action (default: next)",
    )
    parser.add_argument(
        "step_num",
        nargs="?",
        type=int,
        default=None,
        help="Step number for goto action",
    )
    parser.add_argument(
        "--dir",
        default=DEFAULT_DIR,
        help=f"Target directory (default: {DEFAULT_DIR})",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------

def save_state(target_dir: Path, current_step: int, completed_steps: list[int]) -> None:
    state_path = Path(target_dir) / STATE_FILE
    state = {
        "current_step": current_step,
        "completed_steps": sorted(completed_steps),
        "target_dir": str(target_dir),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    # Preserve original started_at if exists
    if state_path.exists():
        try:
            existing = json.loads(state_path.read_text())
            state["started_at"] = existing.get("started_at", state["started_at"])
        except (json.JSONDecodeError, OSError):
            pass
    state_path.write_text(json.dumps(state, indent=2) + "\n")


def load_state(target_dir: Path) -> dict | None:
    state_path = Path(target_dir) / STATE_FILE
    if not state_path.exists():
        return None
    try:
        return json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def reconstruct_state(target_dir: Path) -> dict:
    """Re-detect progress by scanning which config files exist."""
    target = Path(target_dir)
    completed = []
    # Step 1: taskflow/ app exists
    if (target / "taskflow" / "cli.py").exists():
        completed.append(1)
    # Step 2: CLAUDE.md exists
    if (target / "CLAUDE.md").exists():
        completed.append(2)
    # Step 3: .claude/rules/ exists
    if (target / ".claude" / "rules" / "python.md").exists():
        completed.append(3)
    # Step 4: .claude/settings.json exists
    if (target / ".claude" / "settings.json").exists():
        completed.append(4)
    # Step 5: .claude/commands/ exists
    if (target / ".claude" / "commands" / "check.md").exists():
        completed.append(5)
    # Step 6: .claude/skills/ and .claude/agents/ exist
    if (target / ".claude" / "skills" / "add-feature.md").exists():
        completed.append(6)
    # Step 7: .mcp.json exists
    if (target / ".mcp.json").exists():
        completed.append(7)
    # Step 8: hooks.json exists
    if (target / "hooks.json").exists():
        completed.append(8)
    current = max(completed) if completed else 0
    return {
        "current_step": current,
        "completed_steps": sorted(completed),
        "target_dir": str(target_dir),
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_sync_tutorial.py -v
```

Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add src/commands/sync_tutorial.py tests/test_sync_tutorial.py
git commit -m "feat: add tutorial engine CLI parsing and state management"
```

---

### Task 3: TaskFlow App Templates

**Files:**
- Modify: `src/commands/sync_tutorial.py`
- Modify: `tests/test_sync_tutorial.py`

- [ ] **Step 1: Write failing test for scaffolding**

Add to `tests/test_sync_tutorial.py`:

```python
class TestScaffolding:
    """Test project scaffolding."""

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_scaffold_creates_app_structure(self):
        from src.commands.sync_tutorial import scaffold_project
        scaffold_project(self.tmp)
        assert (self.tmp / "taskflow" / "__init__.py").exists()
        assert (self.tmp / "taskflow" / "__main__.py").exists()
        assert (self.tmp / "taskflow" / "cli.py").exists()
        assert (self.tmp / "taskflow" / "models.py").exists()
        assert (self.tmp / "taskflow" / "storage.py").exists()
        assert (self.tmp / "taskflow" / "api.py").exists()
        assert (self.tmp / "taskflow" / "formatters.py").exists()
        assert (self.tmp / "tests" / "test_models.py").exists()
        assert (self.tmp / "tests" / "test_storage.py").exists()
        assert (self.tmp / "tests" / "test_cli.py").exists()
        assert (self.tmp / "README.md").exists()

    def test_scaffold_app_runs(self):
        from src.commands.sync_tutorial import scaffold_project
        import subprocess
        scaffold_project(self.tmp)
        result = subprocess.run(
            [sys.executable, "-m", "taskflow", "list"],
            cwd=self.tmp,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

    def test_scaffold_tests_pass(self):
        from src.commands.sync_tutorial import scaffold_project
        import subprocess
        scaffold_project(self.tmp)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", str(self.tmp / "tests"), "-v"],
            cwd=self.tmp,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Tests failed:\n{result.stdout}\n{result.stderr}"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_sync_tutorial.py::TestScaffolding -v
```

- [ ] **Step 3: Implement scaffold_project with all TaskFlow app templates**

Add to `src/commands/sync_tutorial.py` the embedded string constants for all TaskFlow source files and the `scaffold_project()` function. The TaskFlow app should be a working Python CLI todo app (~200-300 lines total across all files) using SQLite for storage. Key files:

- `taskflow/__init__.py` — version string
- `taskflow/__main__.py` — entry point calling `cli.main()`
- `taskflow/models.py` — `Task` dataclass with id, title, priority, tags, due_date, completed
- `taskflow/storage.py` — SQLite CRUD: `TaskStore` class with `add`, `list_all`, `complete`, `delete`, `search` methods
- `taskflow/cli.py` — argparse CLI dispatching to storage methods
- `taskflow/api.py` — minimal REST API using `http.server` (GET/POST /tasks)
- `taskflow/formatters.py` — terminal color output helpers
- `tests/test_models.py` — Task dataclass tests
- `tests/test_storage.py` — SQLite integration tests (real DB, temp file)
- `tests/test_cli.py` — CLI smoke tests via subprocess
- `README.md` — what TaskFlow is

The `scaffold_project(target_dir)` function writes all files using `pathlib.Path.write_text()` with `parents=True` on mkdir.

**Important:** All code must actually work. `python3 -m taskflow list` must run. `pytest tests/` must pass. This is real code, not stubs.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_sync_tutorial.py::TestScaffolding -v
```

Expected: All 3 tests pass (structure exists, app runs, tests pass)

- [ ] **Step 5: Commit**

```bash
git add src/commands/sync_tutorial.py tests/test_sync_tutorial.py
git commit -m "feat: add TaskFlow app templates and scaffold_project"
```

---

### Task 4: Step File Templates (Steps 2-8)

**Files:**
- Modify: `src/commands/sync_tutorial.py`
- Modify: `tests/test_sync_tutorial.py`

- [ ] **Step 1: Write failing tests for add_step_files**

Add to `tests/test_sync_tutorial.py`:

```python
class TestStepFiles:
    """Test that each step adds the correct config files."""

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())
        from src.commands.sync_tutorial import scaffold_project
        scaffold_project(self.tmp)

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_step2_adds_claude_md(self):
        from src.commands.sync_tutorial import add_step_files
        add_step_files(self.tmp, 2)
        claude_md = self.tmp / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "TaskFlow" in content
        assert "Architecture" in content or "architecture" in content

    def test_step3_adds_rules(self):
        from src.commands.sync_tutorial import add_step_files
        add_step_files(self.tmp, 3)
        assert (self.tmp / ".claude" / "rules" / "python.md").exists()
        assert (self.tmp / ".claude" / "rules" / "testing.md").exists()

    def test_step4_adds_permissions(self):
        from src.commands.sync_tutorial import add_step_files
        add_step_files(self.tmp, 4)
        settings = self.tmp / ".claude" / "settings.json"
        assert settings.exists()
        data = json.loads(settings.read_text())
        assert "permissions" in data

    def test_step5_adds_commands(self):
        from src.commands.sync_tutorial import add_step_files
        add_step_files(self.tmp, 5)
        assert (self.tmp / ".claude" / "commands" / "check.md").exists()

    def test_step6_adds_skills_and_agents(self):
        from src.commands.sync_tutorial import add_step_files
        add_step_files(self.tmp, 6)
        assert (self.tmp / ".claude" / "skills" / "add-feature.md").exists()
        assert (self.tmp / ".claude" / "agents" / "reviewer.md").exists()

    def test_step7_adds_mcp(self):
        from src.commands.sync_tutorial import add_step_files
        add_step_files(self.tmp, 7)
        mcp = self.tmp / ".mcp.json"
        assert mcp.exists()
        data = json.loads(mcp.read_text())
        assert "mcpServers" in data or "servers" in data

    def test_step8_adds_hooks_and_annotations(self):
        from src.commands.sync_tutorial import add_step_files
        # Step 2 must exist first (CLAUDE.md gets annotations appended)
        add_step_files(self.tmp, 2)
        add_step_files(self.tmp, 8)
        assert (self.tmp / "hooks.json").exists()
        claude_md = (self.tmp / "CLAUDE.md").read_text()
        assert "@harness:" in claude_md

    def test_steps_are_additive(self):
        from src.commands.sync_tutorial import add_step_files
        for step in range(2, 9):
            add_step_files(self.tmp, step)
        # All config files should coexist
        assert (self.tmp / "CLAUDE.md").exists()
        assert (self.tmp / ".claude" / "rules" / "python.md").exists()
        assert (self.tmp / ".claude" / "settings.json").exists()
        assert (self.tmp / ".claude" / "commands" / "check.md").exists()
        assert (self.tmp / ".claude" / "skills" / "add-feature.md").exists()
        assert (self.tmp / ".mcp.json").exists()
        assert (self.tmp / "hooks.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_sync_tutorial.py::TestStepFiles -v
```

- [ ] **Step 3: Implement add_step_files with all config templates**

Add to `src/commands/sync_tutorial.py`:

- String constants for each config file:
  - `CLAUDE_MD_TEMPLATE` — project rules for TaskFlow (architecture, DB conventions, API patterns)
  - `RULES_PYTHON_MD` — Python style conventions
  - `RULES_TESTING_MD` — testing philosophy (pytest, real DB, no mocks)
  - `SETTINGS_JSON` — permissions (allow: pytest, sqlite3, python3; deny: rm -rf, DROP TABLE)
  - `COMMAND_CHECK_MD` — `/check` command (runs ruff + pytest)
  - `SKILL_ADD_FEATURE_MD` — guided feature addition skill
  - `AGENT_REVIEWER_MD` — code review agent with TaskFlow context
  - `MCP_JSON` — demo SQLite explorer MCP server config
  - `HOOKS_JSON` — format-on-save hook
  - `CLAUDE_MD_ANNOTATIONS` — harness annotation block to append to CLAUDE.md

- `add_step_files(target_dir, step_num)` function that writes the appropriate files for each step:
  - Step 2: Write `CLAUDE.md`
  - Step 3: Write `.claude/rules/python.md` and `.claude/rules/testing.md`
  - Step 4: Write `.claude/settings.json`
  - Step 5: Write `.claude/commands/check.md`
  - Step 6: Write `.claude/skills/add-feature.md` and `.claude/agents/reviewer.md`
  - Step 7: Write `.mcp.json`
  - Step 8: Write `hooks.json` and append annotations to `CLAUDE.md`

Each template should be realistic and non-trivial — these are what users will see as the showcase of HarnessSync.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_sync_tutorial.py::TestStepFiles -v
```

- [ ] **Step 5: Commit**

```bash
git add src/commands/sync_tutorial.py tests/test_sync_tutorial.py
git commit -m "feat: add step file templates for all 9 tutorial steps"
```

---

### Task 5: Step Guide Text

**Files:**
- Modify: `src/commands/sync_tutorial.py`
- Modify: `tests/test_sync_tutorial.py`

- [ ] **Step 1: Write failing tests for get_step_guide**

Add to `tests/test_sync_tutorial.py`:

```python
class TestStepGuides:
    """Test that each step returns meaningful guide text."""

    def test_all_steps_have_guides(self):
        from src.commands.sync_tutorial import get_step_guide
        for step in range(1, 10):
            guide = get_step_guide(step)
            assert isinstance(guide, str)
            assert len(guide) > 100, f"Step {step} guide too short"

    def test_step1_mentions_setup(self):
        from src.commands.sync_tutorial import get_step_guide
        guide = get_step_guide(1)
        assert "taskflow" in guide.lower()

    def test_step2_mentions_sync(self):
        from src.commands.sync_tutorial import get_step_guide
        guide = get_step_guide(2)
        assert "/sync" in guide

    def test_step8_mentions_annotations(self):
        from src.commands.sync_tutorial import get_step_guide
        guide = get_step_guide(8)
        assert "annotation" in guide.lower() or "@harness" in guide

    def test_step9_mentions_dashboard(self):
        from src.commands.sync_tutorial import get_step_guide
        guide = get_step_guide(9)
        assert "dashboard" in guide.lower() or "sync-dashboard" in guide

    def test_invalid_step_raises(self):
        from src.commands.sync_tutorial import get_step_guide
        with pytest.raises((ValueError, KeyError)):
            get_step_guide(10)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_sync_tutorial.py::TestStepGuides -v
```

- [ ] **Step 3: Implement get_step_guide for all 9 steps**

Add to `src/commands/sync_tutorial.py`:

- `get_step_guide(step_num)` returns markdown-formatted guide text for each step
- Each guide follows the pattern: explain what's being added, what commands to run, what to look for, key observations
- Step 1: setup and verify the app works
- Step 2: CLAUDE.md → run `/sync` → inspect target files
- Step 3: rules → run `/sync`, `/sync-diff` → see rules merged
- Step 4: permissions → run `/sync`, `/sync-status` → see permission translation
- Step 5: commands → run `/sync` → see command representation
- Step 6: skills/agents → run `/sync`, `/sync-capabilities` → see adaptation
- Step 7: MCP → run `/sync`, `/sync-status` → see MCP portability
- Step 8: hooks + annotations → run `/sync`, `/sync-matrix` → see per-harness differentiation
- Step 9: victory lap → run `/sync-dashboard`, `/sync-health`, `/sync-report`

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_sync_tutorial.py::TestStepGuides -v
```

- [ ] **Step 5: Commit**

```bash
git add src/commands/sync_tutorial.py tests/test_sync_tutorial.py
git commit -m "feat: add step guide text for all 9 tutorial steps"
```

---

### Task 6: Main Dispatcher & Action Handlers

**Files:**
- Modify: `src/commands/sync_tutorial.py`
- Modify: `tests/test_sync_tutorial.py`

- [ ] **Step 1: Write failing tests for action handlers**

Add to `tests/test_sync_tutorial.py`:

```python
class TestActions:
    """Test the main action dispatcher."""

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_start_creates_project_and_state(self):
        from src.commands.sync_tutorial import handle_start
        output = handle_start(self.tmp)
        assert (self.tmp / "taskflow" / "cli.py").exists()
        state = json.loads((self.tmp / ".tutorial-state.json").read_text())
        assert state["current_step"] == 1
        assert 1 in state["completed_steps"]
        assert "Step 1" in output or "step 1" in output.lower()

    def test_next_advances_step(self):
        from src.commands.sync_tutorial import handle_start, handle_next
        handle_start(self.tmp)
        output = handle_next(self.tmp)
        state = json.loads((self.tmp / ".tutorial-state.json").read_text())
        assert state["current_step"] == 2
        assert (self.tmp / "CLAUDE.md").exists()

    def test_next_without_start_shows_error(self):
        from src.commands.sync_tutorial import handle_next
        output = handle_next(self.tmp)
        assert "start" in output.lower()

    def test_status_shows_progress(self):
        from src.commands.sync_tutorial import handle_start, handle_status
        handle_start(self.tmp)
        output = handle_status(self.tmp)
        assert "1" in output
        assert "9" in output  # total steps

    def test_goto_jumps_to_step(self):
        from src.commands.sync_tutorial import handle_start, handle_goto
        handle_start(self.tmp)
        output = handle_goto(self.tmp, 4)
        state = json.loads((self.tmp / ".tutorial-state.json").read_text())
        assert state["current_step"] == 4
        # All prior steps' files should exist
        assert (self.tmp / "CLAUDE.md").exists()  # step 2
        assert (self.tmp / ".claude" / "rules" / "python.md").exists()  # step 3
        assert (self.tmp / ".claude" / "settings.json").exists()  # step 4

    def test_reset_clears_state(self):
        from src.commands.sync_tutorial import handle_start, handle_reset
        handle_start(self.tmp)
        output = handle_reset(self.tmp)
        assert not (self.tmp / ".tutorial-state.json").exists()
        assert "reset" in output.lower()

    def test_cleanup_removes_directory(self):
        from src.commands.sync_tutorial import handle_start, handle_cleanup
        handle_start(self.tmp)
        output = handle_cleanup(self.tmp)
        assert not self.tmp.exists()
        assert "removed" in output.lower() or "cleaned" in output.lower()

    def test_next_at_end_shows_complete(self):
        from src.commands.sync_tutorial import handle_start, handle_goto, handle_next
        handle_start(self.tmp)
        handle_goto(self.tmp, 9)
        output = handle_next(self.tmp)
        assert "complete" in output.lower() or "finished" in output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_sync_tutorial.py::TestActions -v
```

- [ ] **Step 3: Implement action handlers and main dispatcher**

Add to `src/commands/sync_tutorial.py`:

- `handle_start(target_dir) -> str` — scaffolds project, saves state at step 1, returns step 1 guide
- `handle_next(target_dir) -> str` — loads state, advances to next step, adds files, saves state, returns guide. If no state, returns error message. If at step 9, returns completion message.
- `handle_status(target_dir) -> str` — loads state, returns progress summary (step N of 9, completed steps list, progress bar)
- `handle_goto(target_dir, step_num) -> str` — ensures all steps up to N have their files, saves state, returns guide for step N
- `handle_reset(target_dir) -> str` — removes `.tutorial-state.json` and all Claude config files (keeps the app), returns confirmation
- `handle_cleanup(target_dir) -> str` — removes entire target directory, returns confirmation
- `main()` — parses args, dispatches to appropriate handler, prints output

The `main()` function at the bottom:

```python
def main():
    args = parse_args()
    target = Path(args.dir)

    try:
        if args.action == "start":
            print(handle_start(target))
        elif args.action == "next":
            print(handle_next(target))
        elif args.action == "status":
            print(handle_status(target))
        elif args.action == "goto":
            if args.step_num is None:
                print("Error: goto requires a step number. Usage: /sync-tutorial goto 5")
                sys.exit(1)
            print(handle_goto(target, args.step_num))
        elif args.action == "reset":
            print(handle_reset(target))
        elif args.action == "cleanup":
            print(handle_cleanup(target))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python3 -m pytest tests/test_sync_tutorial.py::TestActions -v
```

- [ ] **Step 5: Run all tests to verify nothing broke**

```bash
python3 -m pytest tests/test_sync_tutorial.py -v
```

Expected: All tests across all classes pass

- [ ] **Step 6: Commit**

```bash
git add src/commands/sync_tutorial.py tests/test_sync_tutorial.py
git commit -m "feat: add action handlers and main dispatcher for tutorial"
```

---

### Task 7: Tutorial Reference Doc

**Files:**
- Create: `docs/tutorial-reference.md`

- [ ] **Step 1: Create the static reference document**

Write `docs/tutorial-reference.md` — a document for GitHub browsers that describes:
- What the tutorial is and who it's for
- Prerequisites (Claude Code + HarnessSync plugin installed)
- The 9 steps and what each covers (brief, 1-2 lines each)
- Quick start: `/sync-tutorial start`
- What config surfaces are demonstrated
- Expected outcome: understanding of how HarnessSync syncs each config type

This is NOT a replacement for the interactive tutorial — it's a preview for people browsing the repo who haven't installed the plugin yet.

- [ ] **Step 2: Commit**

```bash
git add docs/tutorial-reference.md
git commit -m "docs: add tutorial reference for GitHub browsers"
```

---

### Task 8: Integration Test & Final Verification

**Files:**
- Modify: `tests/test_sync_tutorial.py`

- [ ] **Step 1: Write an end-to-end integration test**

Add to `tests/test_sync_tutorial.py`:

```python
class TestEndToEnd:
    """Full tutorial walkthrough."""

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp())

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_full_walkthrough(self):
        """Run through all 9 steps sequentially."""
        from src.commands.sync_tutorial import (
            handle_start, handle_next, load_state,
        )
        import subprocess

        # Step 1: Start
        output = handle_start(self.tmp)
        assert "Step 1" in output or "step 1" in output.lower()

        # Verify app works
        result = subprocess.run(
            [sys.executable, "-m", "taskflow", "list"],
            cwd=self.tmp, capture_output=True, text=True,
        )
        assert result.returncode == 0

        # Steps 2-9: Next through all
        for expected_step in range(2, 10):
            output = handle_next(self.tmp)
            state = load_state(self.tmp)
            assert state["current_step"] == expected_step
            assert expected_step in state["completed_steps"]

        # After step 9, all config files should exist
        assert (self.tmp / "CLAUDE.md").exists()
        assert (self.tmp / ".claude" / "rules" / "python.md").exists()
        assert (self.tmp / ".claude" / "settings.json").exists()
        assert (self.tmp / ".claude" / "commands" / "check.md").exists()
        assert (self.tmp / ".claude" / "skills" / "add-feature.md").exists()
        assert (self.tmp / ".claude" / "agents" / "reviewer.md").exists()
        assert (self.tmp / ".mcp.json").exists()
        assert (self.tmp / "hooks.json").exists()
        assert "@harness:" in (self.tmp / "CLAUDE.md").read_text()

        # Next after step 9 should show completion
        output = handle_next(self.tmp)
        assert "complete" in output.lower() or "finished" in output.lower()
```

- [ ] **Step 2: Run full test suite**

```bash
python3 -m pytest tests/test_sync_tutorial.py -v
```

Expected: All tests pass

- [ ] **Step 3: Run the existing HarnessSync test suite to verify no regressions**

```bash
python3 -m pytest tests/ -v
```

Expected: All existing tests still pass

- [ ] **Step 4: Manual smoke test**

```bash
python3 src/commands/sync_tutorial.py start --dir /tmp/taskflow-test
python3 src/commands/sync_tutorial.py status --dir /tmp/taskflow-test
python3 src/commands/sync_tutorial.py next --dir /tmp/taskflow-test
python3 src/commands/sync_tutorial.py goto 8 --dir /tmp/taskflow-test
python3 src/commands/sync_tutorial.py cleanup --dir /tmp/taskflow-test
```

Verify each produces meaningful output.

- [ ] **Step 5: Commit**

```bash
git add tests/test_sync_tutorial.py
git commit -m "test: add end-to-end integration test for tutorial walkthrough"
```

- [ ] **Step 6: Final commit with all files**

```bash
git add -A
git status
# Verify only expected files are staged
git commit -m "feat: complete /sync-tutorial interactive tutorial for HarnessSync

Adds an interactive tutorial that scaffolds a TaskFlow todo app and
guides users through all 9 HarnessSync config surfaces step by step.

- /sync-tutorial slash command with start/next/goto/reset/status/cleanup actions
- TaskFlow: working Python CLI todo app with SQLite storage
- 9 progressive steps: CLAUDE.md, rules, permissions, commands, skills/agents, MCP, hooks, annotations
- State tracking via .tutorial-state.json with reconstruction fallback
- Static tutorial reference doc for GitHub browsers
- Full test suite: unit tests + end-to-end integration test"
```
