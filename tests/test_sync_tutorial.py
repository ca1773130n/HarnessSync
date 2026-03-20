from __future__ import annotations

"""Tests for /sync-tutorial command — tutorial engine for HarnessSync.

Covers:
- State management (save/load/reconstruct)
- CLI argument parsing
- TaskFlow project scaffolding (must actually work)
- Step file templates (steps 2-8)
- Step guide text (steps 1-9)
- Action handlers (start/next/status/goto/reset/cleanup)
- End-to-end walkthrough
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.commands.sync_tutorial import (
    add_step_files,
    get_step_guide,
    handle_cleanup,
    handle_goto,
    handle_next,
    handle_reset,
    handle_start,
    handle_status,
    load_state,
    parse_args,
    reconstruct_state,
    save_state,
    scaffold_project,
)


# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------

class TestStateManagement:
    def test_save_and_load(self, tmp_path):
        save_state(tmp_path, current_step=3, completed_steps=[1, 2, 3])
        state = load_state(tmp_path)
        assert state is not None
        assert state["current_step"] == 3
        assert state["completed_steps"] == [1, 2, 3]

    def test_load_missing_returns_none(self, tmp_path):
        assert load_state(tmp_path) is None

    def test_reconstruct_from_existing_files(self, tmp_path):
        """If config files exist, reconstruct_state should detect progress."""
        scaffold_project(tmp_path)
        # Add step 2 files (CLAUDE.md)
        add_step_files(tmp_path, 2)
        state = reconstruct_state(tmp_path)
        assert state is not None
        assert state["current_step"] >= 2

    def test_reconstruct_empty_dir(self, tmp_path):
        """An empty directory has no reconstructable state."""
        state = reconstruct_state(tmp_path)
        assert state is None


# ---------------------------------------------------------------------------
# CLI Parsing
# ---------------------------------------------------------------------------

class TestCLIParsing:
    def test_parse_start(self):
        args = parse_args(["start"])
        assert args.action == "start"

    def test_parse_start_with_dir(self):
        args = parse_args(["start", "--dir", "/tmp/my-tutorial"])
        assert args.action == "start"
        assert args.dir == "/tmp/my-tutorial"

    def test_parse_next_default(self):
        args = parse_args(["next"])
        assert args.action == "next"

    def test_parse_goto_with_step(self):
        args = parse_args(["goto", "5"])
        assert args.action == "goto"
        assert args.step_num == 5

    def test_parse_status(self):
        args = parse_args(["status"])
        assert args.action == "status"

    def test_parse_reset(self):
        args = parse_args(["reset"])
        assert args.action == "reset"

    def test_parse_cleanup(self):
        args = parse_args(["cleanup"])
        assert args.action == "cleanup"

    def test_default_dir(self):
        args = parse_args(["start"])
        assert args.dir == "/tmp/taskflow-playground"


# ---------------------------------------------------------------------------
# Scaffolding
# ---------------------------------------------------------------------------

class TestScaffolding:
    def test_creates_app_structure(self, tmp_path):
        scaffold_project(tmp_path)
        assert (tmp_path / "taskflow" / "__init__.py").exists()
        assert (tmp_path / "taskflow" / "__main__.py").exists()
        assert (tmp_path / "taskflow" / "models.py").exists()
        assert (tmp_path / "taskflow" / "storage.py").exists()
        assert (tmp_path / "taskflow" / "cli.py").exists()
        assert (tmp_path / "taskflow" / "api.py").exists()
        assert (tmp_path / "taskflow" / "formatters.py").exists()
        assert (tmp_path / "tests" / "test_models.py").exists()
        assert (tmp_path / "tests" / "test_storage.py").exists()
        assert (tmp_path / "tests" / "test_cli.py").exists()
        assert (tmp_path / "README.md").exists()

    def test_app_runs(self, tmp_path):
        scaffold_project(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "taskflow", "list"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=15,
        )
        assert result.returncode == 0

    def test_taskflow_tests_pass(self, tmp_path):
        scaffold_project(tmp_path)
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "-p", "no:deepeval"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=30,
        )
        assert result.returncode == 0, f"TaskFlow tests failed:\n{result.stdout}\n{result.stderr}"


# ---------------------------------------------------------------------------
# Step Files
# ---------------------------------------------------------------------------

class TestStepFiles:
    def test_step2_adds_claude_md(self, tmp_path):
        scaffold_project(tmp_path)
        add_step_files(tmp_path, 2)
        assert (tmp_path / "CLAUDE.md").exists()
        content = (tmp_path / "CLAUDE.md").read_text()
        assert len(content) > 100

    def test_step3_adds_rules(self, tmp_path):
        scaffold_project(tmp_path)
        add_step_files(tmp_path, 3)
        assert (tmp_path / ".claude" / "rules" / "python.md").exists()
        assert (tmp_path / ".claude" / "rules" / "testing.md").exists()

    def test_step4_adds_settings(self, tmp_path):
        scaffold_project(tmp_path)
        add_step_files(tmp_path, 4)
        settings_path = tmp_path / ".claude" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "permissions" in data

    def test_step5_adds_commands(self, tmp_path):
        scaffold_project(tmp_path)
        add_step_files(tmp_path, 5)
        assert (tmp_path / ".claude" / "commands" / "check.md").exists()

    def test_step6_adds_skills_and_agents(self, tmp_path):
        scaffold_project(tmp_path)
        add_step_files(tmp_path, 6)
        assert (tmp_path / ".claude" / "skills" / "add-feature.md").exists()
        assert (tmp_path / ".claude" / "agents" / "reviewer.md").exists()

    def test_step7_adds_mcp_json(self, tmp_path):
        scaffold_project(tmp_path)
        add_step_files(tmp_path, 7)
        mcp_path = tmp_path / ".mcp.json"
        assert mcp_path.exists()
        data = json.loads(mcp_path.read_text())
        assert "mcpServers" in data

    def test_step8_adds_hooks_and_annotations(self, tmp_path):
        scaffold_project(tmp_path)
        # Step 8 expects CLAUDE.md to exist (from step 2)
        add_step_files(tmp_path, 2)
        add_step_files(tmp_path, 8)
        assert (tmp_path / "hooks.json").exists()
        claude_md = (tmp_path / "CLAUDE.md").read_text()
        assert "@harness:" in claude_md

    def test_step9_is_noop(self, tmp_path):
        scaffold_project(tmp_path)
        before = set()
        for root, dirs, files in os.walk(tmp_path):
            for f in files:
                before.add(os.path.join(root, f))
        add_step_files(tmp_path, 9)
        after = set()
        for root, dirs, files in os.walk(tmp_path):
            for f in files:
                after.add(os.path.join(root, f))
        assert before == after

    def test_steps_are_additive(self, tmp_path):
        scaffold_project(tmp_path)
        for step in range(2, 9):
            add_step_files(tmp_path, step)
        # All config files should exist
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / ".claude" / "rules" / "python.md").exists()
        assert (tmp_path / ".claude" / "settings.json").exists()
        assert (tmp_path / ".claude" / "commands" / "check.md").exists()
        assert (tmp_path / ".claude" / "skills" / "add-feature.md").exists()
        assert (tmp_path / ".mcp.json").exists()
        assert (tmp_path / "hooks.json").exists()


# ---------------------------------------------------------------------------
# Step Guides
# ---------------------------------------------------------------------------

class TestStepGuides:
    def test_all_steps_have_guides(self):
        for step in range(1, 10):
            guide = get_step_guide(step)
            assert len(guide) > 100, f"Step {step} guide is too short"

    def test_step1_mentions_scaffolding(self):
        guide = get_step_guide(1)
        assert "taskflow" in guide.lower() or "TaskFlow" in guide

    def test_step2_mentions_claude_md(self):
        guide = get_step_guide(2)
        assert "CLAUDE.md" in guide

    def test_step9_is_completion(self):
        guide = get_step_guide(9)
        assert "congrat" in guide.lower() or "complete" in guide.lower() or "done" in guide.lower()

    def test_invalid_step_raises(self):
        with pytest.raises(ValueError):
            get_step_guide(0)
        with pytest.raises(ValueError):
            get_step_guide(10)


# ---------------------------------------------------------------------------
# Action Handlers
# ---------------------------------------------------------------------------

class TestActions:
    def test_start_creates_project_and_state(self, tmp_path):
        output = handle_start(tmp_path)
        assert isinstance(output, str)
        assert len(output) > 50
        state = load_state(tmp_path)
        assert state is not None
        assert state["current_step"] == 1
        assert (tmp_path / "taskflow" / "__init__.py").exists()

    def test_next_advances(self, tmp_path):
        handle_start(tmp_path)
        output = handle_next(tmp_path)
        state = load_state(tmp_path)
        assert state["current_step"] == 2
        assert (tmp_path / "CLAUDE.md").exists()

    def test_next_without_start_shows_error(self, tmp_path):
        output = handle_next(tmp_path)
        assert "start" in output.lower()

    def test_status_shows_progress(self, tmp_path):
        handle_start(tmp_path)
        output = handle_status(tmp_path)
        assert "1" in output
        assert "9" in output

    def test_goto_jumps_to_step(self, tmp_path):
        handle_start(tmp_path)
        output = handle_goto(tmp_path, 5)
        state = load_state(tmp_path)
        assert state["current_step"] == 5
        # All intermediate files should exist
        assert (tmp_path / "CLAUDE.md").exists()  # step 2
        assert (tmp_path / ".claude" / "settings.json").exists()  # step 4

    def test_goto_out_of_range(self, tmp_path):
        handle_start(tmp_path)
        output = handle_goto(tmp_path, 0)
        assert "invalid" in output.lower() or "error" in output.lower() or "between" in output.lower()
        output = handle_goto(tmp_path, 10)
        assert "invalid" in output.lower() or "error" in output.lower() or "between" in output.lower()

    def test_reset_clears_state(self, tmp_path):
        handle_start(tmp_path)
        handle_next(tmp_path)  # step 2
        handle_reset(tmp_path)
        state = load_state(tmp_path)
        assert state is None
        # App files should remain
        assert (tmp_path / "taskflow" / "__init__.py").exists()

    def test_cleanup_removes_dir(self, tmp_path):
        target = tmp_path / "playground"
        handle_start(target)
        assert target.exists()
        handle_cleanup(target)
        assert not target.exists()

    def test_next_at_end_shows_complete(self, tmp_path):
        handle_start(tmp_path)
        for _ in range(8):
            handle_next(tmp_path)
        state = load_state(tmp_path)
        assert state["current_step"] == 9
        output = handle_next(tmp_path)
        assert "complete" in output.lower() or "congrat" in output.lower() or "finished" in output.lower()


# ---------------------------------------------------------------------------
# End-to-End
# ---------------------------------------------------------------------------

class TestEndToEnd:
    def test_full_walkthrough(self, tmp_path):
        """Walk through all 9 steps and verify all config files at the end."""
        handle_start(tmp_path)
        for i in range(8):
            output = handle_next(tmp_path)
            assert isinstance(output, str)
            assert len(output) > 50

        state = load_state(tmp_path)
        assert state["current_step"] == 9
        assert sorted(state["completed_steps"]) == list(range(1, 10))

        # All config files exist
        assert (tmp_path / "taskflow" / "__init__.py").exists()
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / ".claude" / "rules" / "python.md").exists()
        assert (tmp_path / ".claude" / "rules" / "testing.md").exists()
        assert (tmp_path / ".claude" / "settings.json").exists()
        assert (tmp_path / ".claude" / "commands" / "check.md").exists()
        assert (tmp_path / ".claude" / "skills" / "add-feature.md").exists()
        assert (tmp_path / ".claude" / "agents" / "reviewer.md").exists()
        assert (tmp_path / ".mcp.json").exists()
        assert (tmp_path / "hooks.json").exists()
        assert "@harness:" in (tmp_path / "CLAUDE.md").read_text()

        # App should still work
        result = subprocess.run(
            [sys.executable, "-m", "taskflow", "list"],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
            timeout=15,
        )
        assert result.returncode == 0
