from __future__ import annotations

"""Tests for iteration 65 product-ideation improvements.

Covers:
- Sync Undo/Redo Stack (item 30): HarnessUndoStack / SyncUndoManager
- Cross-Harness Rule Simulation (item 10): RuleSimulator
- Context Window Budget Sync (item 26): ContextBudgetSync / parse_budget_from_claude_md
- Sync Rollback Timeline visual format (item 11): ConfigTimeMachine.format_visual_timeline()
- Git Commit-Triggered Sync annotation hook (item 7): install/uninstall_commit_annotate_hook
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sync_undo_stack import (
    HarnessUndoStack,
    SyncUndoManager,
    MAX_STACK_DEPTH,
)
from src.rule_simulator import RuleSimulator, RuleSimulationResult
from src.context_budget_sync import (
    ContextBudget,
    ContextBudgetSync,
    parse_budget_from_claude_md,
)
from src.config_time_machine import ConfigTimeMachine, ConfigCommit
from src.git_hook_installer import (
    COMMIT_ANNOTATE_MARKER,
    install_commit_annotate_hook,
    uninstall_commit_annotate_hook,
    is_commit_annotate_hook_installed,
    find_git_dir,
)


# ── HarnessUndoStack ──────────────────────────────────────────────────────────


def test_undo_stack_push_increases_depth(tmp_path):
    """Pushing onto the stack increments depth."""
    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=tmp_path)
    assert stack.depth() == 0
    stack.push({"AGENTS.md": "content A"}, label="before sync 1")
    assert stack.depth() == 1
    stack.push({"AGENTS.md": "content B"}, label="before sync 2")
    assert stack.depth() == 2


def test_undo_stack_max_depth_respected(tmp_path):
    """Stack depth never exceeds MAX_STACK_DEPTH."""
    stack = HarnessUndoStack("gemini", root_dir=tmp_path / "stacks", project_dir=tmp_path)
    for i in range(MAX_STACK_DEPTH + 5):
        stack.push({"GEMINI.md": f"v{i}"}, label=f"sync {i}")
    assert stack.depth() == MAX_STACK_DEPTH


def test_undo_empty_stack_returns_error(tmp_path):
    """Undoing an empty stack returns ok=False with an error message."""
    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=tmp_path)
    result = stack.undo()
    assert not result.ok
    assert "empty" in result.error.lower()


def test_undo_restores_file_content(tmp_path):
    """Undo writes the saved content back to disk."""
    project = tmp_path / "project"
    project.mkdir()
    target_file = project / "AGENTS.md"
    target_file.write_text("original content", encoding="utf-8")

    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=project)
    # Push snapshot of original content
    stack.push({"AGENTS.md": "original content"}, label="before overwrite")

    # Simulate sync overwriting the file
    target_file.write_text("new synced content", encoding="utf-8")

    # Undo should restore "original content"
    result = stack.undo()
    assert result.ok
    assert "AGENTS.md" in result.files_restored
    assert target_file.read_text(encoding="utf-8") == "original content"


def test_undo_push_clears_redo(tmp_path):
    """Pushing a new entry clears the redo stack."""
    project = tmp_path / "project"
    project.mkdir()
    target_file = project / "AGENTS.md"
    target_file.write_text("v1", encoding="utf-8")

    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=project)
    stack.push({"AGENTS.md": "v1"}, label="snap1")
    target_file.write_text("v2", encoding="utf-8")
    stack.undo()

    # Now there should be a redo entry
    assert stack.redo_depth() == 1

    # Push a new snapshot — should clear redo
    stack.push({"AGENTS.md": "v2"}, label="snap2")
    assert stack.redo_depth() == 0


def test_redo_empty_stack_returns_error(tmp_path):
    """Redoing an empty redo stack returns ok=False."""
    stack = HarnessUndoStack("gemini", root_dir=tmp_path / "stacks", project_dir=tmp_path)
    result = stack.redo()
    assert not result.ok
    assert "empty" in result.error.lower()


def test_undo_dry_run_does_not_write(tmp_path):
    """Dry-run undo reports files without writing them."""
    project = tmp_path / "project"
    project.mkdir()
    target_file = project / "AGENTS.md"
    target_file.write_text("overwritten", encoding="utf-8")

    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=project)
    stack.push({"AGENTS.md": "original"}, label="snap")
    target_file.write_text("overwritten", encoding="utf-8")

    result = stack.undo(dry_run=True)
    assert result.ok
    assert "AGENTS.md" in result.files_restored
    # File should NOT have been written
    assert target_file.read_text(encoding="utf-8") == "overwritten"


def test_clear_removes_stacks(tmp_path):
    """clear() empties both undo and redo stacks."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("x", encoding="utf-8")

    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=project)
    stack.push({"AGENTS.md": "x"})
    stack.clear()
    assert stack.depth() == 0
    assert stack.redo_depth() == 0


def test_list_entries_returns_summary(tmp_path):
    """list_entries returns dicts with timestamp / label / file_count."""
    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=tmp_path)
    stack.push({"AGENTS.md": "content"}, label="my snapshot")
    entries = stack.list_entries()
    assert len(entries) == 1
    assert entries[0]["label"] == "my snapshot"
    assert entries[0]["file_count"] == "1"


def test_format_status_includes_harness_name(tmp_path):
    """format_status output includes harness name."""
    stack = HarnessUndoStack("gemini", root_dir=tmp_path / "stacks", project_dir=tmp_path)
    status = stack.format_status()
    assert "gemini" in status


def test_sync_undo_manager_push_and_undo(tmp_path):
    """SyncUndoManager.push and undo work via the facade."""
    project = tmp_path / "project"
    project.mkdir()
    target_file = project / "GEMINI.md"
    target_file.write_text("v1", encoding="utf-8")

    manager = SyncUndoManager(root_dir=tmp_path / "stacks", project_dir=project)
    manager.push("gemini", {"GEMINI.md": "v1"}, label="pre-sync")
    target_file.write_text("v2", encoding="utf-8")

    result = manager.undo("gemini")
    assert result.ok
    assert target_file.read_text(encoding="utf-8") == "v1"


def test_sync_undo_manager_format_all_status(tmp_path):
    """format_all_status lists configured harnesses."""
    manager = SyncUndoManager(root_dir=tmp_path / "stacks", project_dir=tmp_path)
    manager.push("codex", {"AGENTS.md": "x"})
    manager.push("gemini", {"GEMINI.md": "y"})
    status = manager.format_all_status(harnesses=["codex", "gemini"])
    assert "codex" in status
    assert "gemini" in status


# ── RuleSimulator ─────────────────────────────────────────────────────────────


def test_simulate_returns_all_default_targets():
    """simulate() returns a result with entries for all default harnesses."""
    sim = RuleSimulator()
    result = sim.simulate("Always use TypeScript over JavaScript.")
    assert "codex" in result.simulations
    assert "gemini" in result.simulations
    assert "aider" in result.simulations


def test_simulate_no_diffs_for_plain_rule():
    """A plain rule with no CC-specific constructs produces no behavioral diffs."""
    sim = RuleSimulator()
    result = sim.simulate("Always add docstrings to public functions.")
    assert not result.has_diffs


def test_simulate_detects_mcp_diff_in_codex():
    """MCP references are flagged as behavioral differences for codex/aider."""
    sim = RuleSimulator()
    result = sim.simulate("Use the mcp server context7 for library lookups.")
    assert result.simulations["codex"].behavioral_diffs
    assert result.simulations["aider"].behavioral_diffs


def test_simulate_detects_skill_diff_for_aider():
    """'Use skill' references are flagged as behavioral differences for aider."""
    sim = RuleSimulator()
    result = sim.simulate("Invoke a skill to handle all code review workflows.")
    # aider has no skill concept
    assert result.simulations["aider"].behavioral_diffs


def test_simulate_translates_claude_md_filename():
    """CLAUDE.md filename is translated to target-specific filename."""
    sim = RuleSimulator(targets=["codex", "gemini"])
    result = sim.simulate("See CLAUDE.md for the project coding standards.")
    # codex should use AGENTS.md in translated text
    assert "AGENTS.md" in result.simulations["codex"].translated_text
    # gemini should use GEMINI.md
    assert "GEMINI.md" in result.simulations["gemini"].translated_text


def test_simulate_detects_hook_diff():
    """Hook event names are flagged as behavioral differences for all non-CC harnesses."""
    sim = RuleSimulator()
    result = sim.simulate("Use PostToolUse hooks to validate tool output.")
    for harness in ("codex", "gemini", "aider", "cursor", "windsurf"):
        assert result.simulations[harness].behavioral_diffs


def test_format_results_includes_harness_names():
    """format_results output includes all simulated harness names."""
    sim = RuleSimulator()
    result = sim.simulate("Prefer async functions in Python.")
    output = sim.format_results(result)
    assert "codex" in output
    assert "gemini" in output
    assert "aider" in output


def test_format_results_clean_message_when_no_diffs():
    """format_results shows a clean message when no diffs detected."""
    sim = RuleSimulator()
    result = sim.simulate("Use meaningful variable names.")
    output = sim.format_results(result)
    assert "No behavioral differences" in output


def test_compare_two_returns_both_harnesses():
    """compare_two output includes both harness names."""
    sim = RuleSimulator()
    output = sim.compare_two(
        "Always use TypeScript.",
        "codex",
        "aider",
    )
    assert "codex" in output
    assert "aider" in output


def test_simulate_with_subset_targets():
    """Passing a subset of targets only simulates those harnesses."""
    sim = RuleSimulator(targets=["codex", "gemini"])
    result = sim.simulate("Use strict mode in JavaScript.")
    assert set(result.simulations.keys()) == {"codex", "gemini"}


def test_simulate_section_with_title():
    """simulate_section prepends the heading to the rule text."""
    sim = RuleSimulator(targets=["gemini"])
    result = sim.simulate_section("Always prefer async I/O.", "Async Patterns")
    assert "Async Patterns" in result.simulations["gemini"].translated_text


# ── ContextBudgetSync ─────────────────────────────────────────────────────────


def test_parse_budget_no_section_returns_none():
    """Returns None when no ## Context Budget section exists."""
    result = parse_budget_from_claude_md("# My Project\n\n## Rules\nAlways test.\n")
    assert result is None


def test_parse_budget_basic_section():
    """Parses max_tokens from a ## Context Budget section."""
    content = "## Context Budget\nmax_tokens: 4096\ncontext_limit: 100000\n"
    budget = parse_budget_from_claude_md(content)
    assert budget is not None
    assert budget.max_tokens == 4096
    assert budget.context_limit == 100_000


def test_parse_budget_thinking_budget():
    """Parses thinking_budget from the section."""
    content = "## Context Budget\nmax_tokens: 8192\nthinking_budget: 2000\n"
    budget = parse_budget_from_claude_md(content)
    assert budget is not None
    assert budget.thinking_budget == 2000


def test_parse_budget_equals_separator():
    """Supports key = value format as well as key: value."""
    content = "## Context Budget\nmax_tokens = 16384\n"
    budget = parse_budget_from_claude_md(content)
    assert budget is not None
    assert budget.max_tokens == 16384


def test_parse_budget_stops_at_next_heading():
    """Parser does not bleed into the next ## section."""
    content = (
        "## Context Budget\nmax_tokens: 4096\n\n"
        "## Other Section\nmax_tokens: 99999\n"
    )
    budget = parse_budget_from_claude_md(content)
    assert budget is not None
    assert budget.max_tokens == 4096


def test_context_budget_sync_translate_all_targets():
    """translate_budget returns a config for each default target."""
    syncer = ContextBudgetSync()
    budget = ContextBudget(max_tokens=8192, context_limit=200_000)
    configs = syncer.translate_budget(budget)
    assert "codex" in configs
    assert "gemini" in configs
    assert "aider" in configs
    assert "cursor" in configs
    assert "windsurf" in configs


def test_codex_translation_is_toml():
    """Codex translation uses TOML format."""
    syncer = ContextBudgetSync(targets=["codex"])
    budget = ContextBudget(max_tokens=4096)
    configs = syncer.translate_budget(budget)
    assert configs["codex"].config_format == "toml"
    assert "max_tokens" in configs["codex"].config_snippet


def test_gemini_translation_is_json():
    """Gemini translation uses JSON format with maxOutputTokens."""
    syncer = ContextBudgetSync(targets=["gemini"])
    budget = ContextBudget(max_tokens=4096)
    configs = syncer.translate_budget(budget)
    assert configs["gemini"].config_format == "json"
    assert "maxOutputTokens" in configs["gemini"].config_snippet


def test_aider_translation_is_yaml():
    """Aider translation uses YAML format with max-tokens key."""
    syncer = ContextBudgetSync(targets=["aider"])
    budget = ContextBudget(max_tokens=4096)
    configs = syncer.translate_budget(budget)
    assert configs["aider"].config_format == "yaml"
    assert "max-tokens" in configs["aider"].config_snippet


def test_cursor_translation_is_comment_only():
    """Cursor has no native budget config — produces comment_only format."""
    syncer = ContextBudgetSync(targets=["cursor"])
    budget = ContextBudget(max_tokens=4096)
    configs = syncer.translate_budget(budget)
    assert configs["cursor"].config_format == "comment_only"


def test_sync_from_claude_md_returns_budget_and_configs():
    """sync_from_claude_md parses and translates in one step."""
    syncer = ContextBudgetSync()
    content = "## Context Budget\nmax_tokens: 8192\ncontext_limit: 150000\n"
    budget, configs = syncer.sync_from_claude_md(content)
    assert budget is not None
    assert budget.max_tokens == 8192
    assert "codex" in configs


def test_sync_from_claude_md_no_section():
    """Returns (None, {}) when no budget section exists."""
    syncer = ContextBudgetSync()
    budget, configs = syncer.sync_from_claude_md("# No budget here\n")
    assert budget is None
    assert configs == {}


def test_format_report_contains_harness_names():
    """format_report output includes all harness names."""
    syncer = ContextBudgetSync()
    budget = ContextBudget(max_tokens=4096, thinking_budget=1000)
    configs = syncer.translate_budget(budget)
    report = syncer.format_report(budget, configs)
    assert "codex" in report
    assert "gemini" in report
    assert "aider" in report


def test_generate_claude_md_section():
    """generate_claude_md_section produces a valid section string."""
    syncer = ContextBudgetSync()
    budget = ContextBudget(max_tokens=4096, context_limit=100_000)
    section = syncer.generate_claude_md_section(budget)
    assert "## Context Budget" in section
    assert "max_tokens: 4096" in section
    assert "context_limit: 100000" in section


def test_effective_output_tokens_uses_max():
    """effective_output_tokens returns the maximum of max_tokens and output_limit."""
    budget = ContextBudget(max_tokens=4096, output_limit=8192)
    assert budget.effective_output_tokens() == 8192

    budget2 = ContextBudget(max_tokens=8192, output_limit=4096)
    assert budget2.effective_output_tokens() == 8192


# ── ConfigTimeMachine.format_visual_timeline ─────────────────────────────────


def _make_commit(sha: str, date: str, subject: str, author: str = "Alice") -> ConfigCommit:
    return ConfigCommit(
        sha=sha,
        full_sha=sha * 6,
        author=author,
        date=date,
        subject=subject,
        files_changed=["CLAUDE.md"],
    )


def test_format_visual_timeline_empty():
    """Returns a 'no commits found' message for an empty list."""
    tm = ConfigTimeMachine(Path("/tmp/fake"))
    output = tm.format_visual_timeline([])
    assert "No config-related commits found" in output


def test_format_visual_timeline_single_commit():
    """Single commit timeline renders correctly."""
    tm = ConfigTimeMachine(Path("/tmp/fake"))
    commits = [_make_commit("abc1234", "2026-03-13", "Add TypeScript rules")]
    output = tm.format_visual_timeline(commits)
    assert "abc1234" in output
    assert "2026-03-13" in output
    assert "Add TypeScript rules" in output
    # Should have the bottom cap for last commit
    assert "╵" in output


def test_format_visual_timeline_multiple_commits():
    """Multiple commits render with connectors between them."""
    tm = ConfigTimeMachine(Path("/tmp/fake"))
    commits = [
        _make_commit("abc1234", "2026-03-13", "Add rules"),
        _make_commit("def5678", "2026-03-10", "Update MCP"),
        _make_commit("ghi9012", "2026-03-07", "Initial CLAUDE.md"),
    ]
    output = tm.format_visual_timeline(commits)
    # All three SHAs should appear
    assert "abc1234" in output
    assert "def5678" in output
    assert "ghi9012" in output
    # Connector nodes between commits
    assert "│" in output
    # Count line shows commit count
    assert "3 commit" in output


def test_format_visual_timeline_shows_author():
    """Author name appears below each commit node."""
    tm = ConfigTimeMachine(Path("/tmp/fake"))
    commits = [_make_commit("aaa1111", "2026-03-13", "Fix config", author="Bob")]
    output = tm.format_visual_timeline(commits)
    assert "Bob" in output


def test_format_visual_timeline_show_files():
    """show_files=True includes changed file names."""
    tm = ConfigTimeMachine(Path("/tmp/fake"))
    commit = ConfigCommit(
        sha="abc1234",
        full_sha="abc1234" * 6,
        author="Alice",
        date="2026-03-13",
        subject="Update config",
        files_changed=["CLAUDE.md", ".mcp.json"],
    )
    output = tm.format_visual_timeline([commit], show_files=True)
    assert "CLAUDE.md" in output
    assert ".mcp.json" in output


def test_format_visual_timeline_subject_truncated():
    """Very long subjects are truncated to fit max_width."""
    tm = ConfigTimeMachine(Path("/tmp/fake"))
    long_subject = "A" * 200
    commits = [_make_commit("abc1234", "2026-03-13", long_subject)]
    output = tm.format_visual_timeline(commits, max_width=80)
    # Truncated subjects end with ellipsis
    assert "…" in output


def test_format_visual_timeline_tip_message():
    """Timeline output includes the restore tip."""
    tm = ConfigTimeMachine(Path("/tmp/fake"))
    commits = [_make_commit("abc1234", "2026-03-13", "Update rules")]
    output = tm.format_visual_timeline(commits)
    assert "sync-restore" in output or "Tip:" in output


# ── Commit Annotate Hook ──────────────────────────────────────────────────────


def _init_git_repo(path: Path) -> Path:
    """Create a minimal git repo at path and return the .git/hooks dir."""
    import subprocess
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    hooks_dir = path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    return hooks_dir


def test_install_commit_annotate_hook(tmp_path):
    """install_commit_annotate_hook creates a post-commit hook with the marker."""
    _init_git_repo(tmp_path)
    success, msg = install_commit_annotate_hook(tmp_path)
    assert success
    assert is_commit_annotate_hook_installed(tmp_path)


def test_install_commit_annotate_hook_idempotent(tmp_path):
    """Installing the hook twice returns success without duplicating."""
    _init_git_repo(tmp_path)
    install_commit_annotate_hook(tmp_path)
    success, msg = install_commit_annotate_hook(tmp_path)
    assert success
    # Check the marker appears exactly once
    hook_path = tmp_path / ".git" / "hooks" / "post-commit"
    content = hook_path.read_text(encoding="utf-8")
    assert content.count(COMMIT_ANNOTATE_MARKER) == 1


def test_uninstall_commit_annotate_hook(tmp_path):
    """Uninstalling removes the marker and leaves the hook clean."""
    _init_git_repo(tmp_path)
    install_commit_annotate_hook(tmp_path)
    success, msg = uninstall_commit_annotate_hook(tmp_path)
    assert success
    assert not is_commit_annotate_hook_installed(tmp_path)


def test_uninstall_commit_annotate_hook_nonexistent(tmp_path):
    """Uninstalling when not installed returns success."""
    _init_git_repo(tmp_path)
    success, msg = uninstall_commit_annotate_hook(tmp_path)
    assert success


def test_install_commit_annotate_hook_appends_to_existing(tmp_path):
    """Installing appends to an existing post-commit hook."""
    _init_git_repo(tmp_path)
    hook_path = tmp_path / ".git" / "hooks" / "post-commit"
    hook_path.write_text("#!/bin/sh\necho 'existing hook'\n", encoding="utf-8")

    success, msg = install_commit_annotate_hook(tmp_path)
    assert success
    content = hook_path.read_text(encoding="utf-8")
    assert "existing hook" in content
    assert COMMIT_ANNOTATE_MARKER in content


def test_commit_annotate_hook_template_contains_amend():
    """The hook template includes git commit --amend for message annotation."""
    from src.git_hook_installer import COMMIT_ANNOTATE_HOOK_TEMPLATE
    assert "git commit --amend" in COMMIT_ANNOTATE_HOOK_TEMPLATE
    assert "HarnessSync:" in COMMIT_ANNOTATE_HOOK_TEMPLATE


def test_is_commit_annotate_not_installed_in_non_git(tmp_path):
    """Returns False when not in a git repo."""
    assert not is_commit_annotate_hook_installed(tmp_path)
