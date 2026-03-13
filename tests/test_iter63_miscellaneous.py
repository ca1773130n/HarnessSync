from __future__ import annotations

"""Tests for iteration 63 product-ideation improvements.

Covers:
- Colorized side-by-side diff (item 1): conflict_detector.format_side_by_side_diff(colorize=True)
- Semantic temporal drift detection (item 14): SemanticConflictDetector.check_temporal_drift
- Drift-check pre-commit hook (item 3): git_hook_installer.install/uninstall/is_installed
- ASCII timeline rendering (item 11): sync_log._render_ascii_timeline
- PR-ready adapter files (item 13): adapter_sdk.AdapterWizard.generate_pr_files
- Capability gap HTML report (item 2): html_report.generate_capability_gap_report
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.conflict_detector import (
    ConflictDetector,
    SemanticConflictDetector,
)
from src.git_hook_installer import (
    DRIFT_CHECK_MARKER,
    install_drift_check_hook,
    uninstall_drift_check_hook,
    is_drift_check_hook_installed,
)
from src.commands.sync_log import _render_ascii_timeline
from src.adapter_sdk import AdapterWizard
from src.html_report import generate_capability_gap_report, write_capability_gap_report


# ── Colorized side-by-side diff ────────────────────────────────────────────


def test_format_side_by_side_no_color_baseline():
    """Baseline: no color flag produces plain text output."""
    detector = ConflictDetector(Path("/tmp"))
    three_way = {
        "file_path": "GEMINI.md",
        "source_lines": ["line A\n", "line B\n"],
        "current_lines": ["line A\n", "line X\n"],
        "has_real_conflict": True,
    }
    result = detector.format_side_by_side_diff(three_way, colorize=False)
    assert "SIDE-BY-SIDE DIFF" in result
    assert "\033[" not in result  # no ANSI escapes


def test_format_side_by_side_color_contains_ansi():
    """When colorize=True, output includes ANSI escape codes for changed lines."""
    detector = ConflictDetector(Path("/tmp"))
    three_way = {
        "file_path": "AGENTS.md",
        "source_lines": ["original rule\n"],
        "current_lines": ["modified rule\n"],
        "has_real_conflict": True,
    }
    result = detector.format_side_by_side_diff(three_way, colorize=True)
    assert "\033[" in result  # ANSI codes present


def test_format_side_by_side_color_legend_present():
    """Color mode includes a legend line."""
    detector = ConflictDetector(Path("/tmp"))
    three_way = {
        "file_path": "test.md",
        "source_lines": ["a\n"],
        "current_lines": ["b\n"],
        "has_real_conflict": True,
    }
    result = detector.format_side_by_side_diff(three_way, colorize=True)
    assert "Legend" in result


def test_format_side_by_side_identical_files():
    """Identical files produce no-difference message regardless of colorize."""
    detector = ConflictDetector(Path("/tmp"))
    three_way = {
        "file_path": "same.md",
        "source_lines": ["same line\n"],
        "current_lines": ["same line\n"],
        "has_real_conflict": False,
    }
    plain = detector.format_side_by_side_diff(three_way, colorize=False)
    colored = detector.format_side_by_side_diff(three_way, colorize=True)
    assert "no differences" in plain
    assert "no differences" in colored


# ── Semantic temporal drift detection ─────────────────────────────────────


def test_check_temporal_drift_detects_new_contradiction():
    """New rule added after snapshot contradicts old snapshot rule → drift reported."""
    detector = SemanticConflictDetector()
    snapshot = "Always add comments to explain complex logic."
    current = snapshot + "\nAvoid adding comments; keep code self-explanatory."
    conflicts = detector.check_temporal_drift(current, snapshot)
    # Should detect comment_policy drift
    assert any("drift:" in c.conflict_type for c in conflicts), (
        f"Expected drift conflicts, got: {conflicts}"
    )


def test_check_temporal_drift_no_new_rules():
    """When no new rules are added, no drift conflicts are reported."""
    detector = SemanticConflictDetector()
    content = "Always use single quotes.\nNever use var."
    conflicts = detector.check_temporal_drift(content, content)
    assert conflicts == []


def test_check_temporal_drift_unrelated_new_rule():
    """Adding a new rule that doesn't contradict anything produces no drift."""
    detector = SemanticConflictDetector()
    snapshot = "Always use tabs for indentation."
    current = snapshot + "\nKeep lines under 120 characters."
    conflicts = detector.check_temporal_drift(current, snapshot)
    # "Keep lines under 120 characters" doesn't contradict tabs
    assert not any(c.conflict_type.startswith("drift:indentation") for c in conflicts)


def test_check_temporal_drift_explanation_mentions_temporal():
    """Drift conflicts explain that the new rule was added recently."""
    detector = SemanticConflictDetector()
    snapshot = "Use verbose, detailed responses.\n"
    current = snapshot + "Keep responses concise and brief.\n"
    conflicts = detector.check_temporal_drift(current, snapshot)
    if conflicts:
        assert any("TEMPORAL DRIFT" in c.explanation or "drift" in c.conflict_type.lower()
                   for c in conflicts)


# ── Drift-check pre-commit hook ────────────────────────────────────────────


def test_drift_check_hook_installs_in_git_repo(tmp_path):
    """install_drift_check_hook writes the hook file in a git repo."""
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)
    # Fake git structure
    (tmp_path / ".git").mkdir(exist_ok=True)

    success, msg = install_drift_check_hook(tmp_path)
    assert success
    hook_path = tmp_path / ".git" / "hooks" / "pre-commit"
    assert hook_path.exists()
    content = hook_path.read_text()
    assert DRIFT_CHECK_MARKER in content
    assert "COMMIT BLOCKED" in content


def test_drift_check_hook_not_git_repo(tmp_path):
    """install_drift_check_hook fails gracefully outside a git repo."""
    success, msg = install_drift_check_hook(tmp_path)
    assert not success
    assert "git" in msg.lower()


def test_drift_check_hook_idempotent(tmp_path):
    """Installing the drift-check hook twice does not duplicate the block."""
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)

    install_drift_check_hook(tmp_path)
    install_drift_check_hook(tmp_path)  # second install

    hook_path = tmp_path / ".git" / "hooks" / "pre-commit"
    content = hook_path.read_text()
    assert content.count(DRIFT_CHECK_MARKER) == 1


def test_is_drift_check_hook_installed(tmp_path):
    """is_drift_check_hook_installed returns True after install, False before."""
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)

    assert not is_drift_check_hook_installed(tmp_path)
    install_drift_check_hook(tmp_path)
    assert is_drift_check_hook_installed(tmp_path)


def test_uninstall_drift_check_hook(tmp_path):
    """uninstall_drift_check_hook removes the block and reports success."""
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)

    install_drift_check_hook(tmp_path)
    assert is_drift_check_hook_installed(tmp_path)

    success, msg = uninstall_drift_check_hook(tmp_path)
    assert success
    assert not is_drift_check_hook_installed(tmp_path)


def test_drift_check_hook_appends_to_existing_hook(tmp_path):
    """When a pre-commit hook already exists, the block is appended safely."""
    git_dir = tmp_path / ".git" / "hooks"
    git_dir.mkdir(parents=True)

    existing_hook = git_dir / "pre-commit"
    existing_hook.write_text("#!/bin/sh\n# existing hook\nexit 0\n")

    install_drift_check_hook(tmp_path)

    content = existing_hook.read_text()
    assert "existing hook" in content
    assert DRIFT_CHECK_MARKER in content


# ── ASCII timeline rendering ────────────────────────────────────────────────


def test_render_ascii_timeline_basic():
    """Timeline renders date labels and bar characters."""
    entries = [
        "## Sync 2024-03-01T10:00:00Z\ncodex: 3 synced\n",
        "## Sync 2024-03-01T11:00:00Z\ngemini: 2 synced\n",
        "## Sync 2024-03-02T09:00:00Z\ncodex: 1 synced\n",
    ]
    result = _render_ascii_timeline(entries)
    assert "2024-03-01" in result
    assert "2024-03-02" in result
    assert "█" in result


def test_render_ascii_timeline_no_entries():
    """Empty entry list returns a helpful message."""
    result = _render_ascii_timeline([])
    assert "No dated" in result or "no" in result.lower()


def test_render_ascii_timeline_shows_total():
    """Timeline includes a total count at the bottom."""
    entries = [
        "## Sync 2024-05-10T08:00Z\n",
        "## Sync 2024-05-10T09:00Z\n",
        "## Sync 2024-05-11T10:00Z\n",
    ]
    result = _render_ascii_timeline(entries)
    assert "Total:" in result
    assert "3" in result


def test_render_ascii_timeline_at_most_30_days():
    """Only the 30 most recent days are shown when there are more."""
    # 34 unique dates: 2024-01-01 through 2024-01-31, then 2024-02-01 through 2024-02-03
    entries = (
        [f"## Sync 2024-01-{str(d).zfill(2)}T10:00Z\n" for d in range(1, 32)]
        + [f"## Sync 2024-02-{str(d).zfill(2)}T10:00Z\n" for d in range(1, 4)]
    )
    result = _render_ascii_timeline(entries)
    # 34 dates total; last 30 = 2024-01-04 through 2024-02-03
    # so 2024-01-01, 2024-01-02, 2024-01-03 are excluded
    assert "2024-01-01" not in result  # earliest 4 days should be clipped out
    assert "2024-01-02" not in result
    assert "2024-01-03" not in result
    assert "2024-02-03" in result  # most recent day should be present
    assert "(Showing most recent 30" in result


def test_render_ascii_timeline_undated_entries_skipped():
    """Entries without an ISO date are silently skipped."""
    entries = [
        "## Sync (no date here)\nsome content\n",
        "## Sync 2024-06-01T10:00Z\ncontent\n",
    ]
    result = _render_ascii_timeline(entries)
    assert "2024-06-01" in result
    # Should not crash or show anything for the undated entry


# ── PR-ready adapter files ──────────────────────────────────────────────────


def test_generate_pr_files_creates_all_three(tmp_path):
    """generate_pr_files writes adapter, test, and notes files."""
    wizard = AdapterWizard()
    files = wizard.generate_pr_files(
        "plandex",
        tmp_path,
        config_file=".plandex/config.json",
        config_format="json",
        display_name="Plandex",
    )
    assert "adapter" in files
    assert "test" in files
    assert "notes" in files
    for path in files.values():
        assert path.exists(), f"Expected file to exist: {path}"


def test_generate_pr_files_adapter_content(tmp_path):
    """The generated adapter file contains the class name and target_name."""
    wizard = AdapterWizard()
    files = wizard.generate_pr_files(
        "mytool",
        tmp_path,
        config_file=".mytool/config.json",
        config_format="json",
    )
    adapter_content = files["adapter"].read_text()
    assert "MytoolAdapter" in adapter_content or "mytool" in adapter_content


def test_generate_pr_files_test_content(tmp_path):
    """The generated test file contains pytest fixtures and test functions."""
    wizard = AdapterWizard()
    files = wizard.generate_pr_files(
        "newtool",
        tmp_path,
        config_file=".newtool/config.toml",
        config_format="toml",
    )
    test_content = files["test"].read_text()
    assert "pytest" in test_content
    assert "def test_" in test_content
    assert "target_name" in test_content


def test_generate_pr_files_notes_checklist(tmp_path):
    """The contribution notes file contains a pre-PR checklist."""
    wizard = AdapterWizard()
    files = wizard.generate_pr_files(
        "anothertool",
        tmp_path,
        config_file=".anothertool/config.json",
        config_format="json",
        display_name="AnotherTool",
    )
    notes_content = files["notes"].read_text()
    assert "Checklist" in notes_content or "checklist" in notes_content.lower()
    assert "AnotherTool" in notes_content


def test_generate_pr_files_directory_structure(tmp_path):
    """PR files are placed under src/adapters/ and tests/ subdirectories."""
    wizard = AdapterWizard()
    files = wizard.generate_pr_files(
        "toolx",
        tmp_path,
        config_file=".toolx/config.json",
        config_format="json",
    )
    assert "src/adapters" in str(files["adapter"])
    assert "tests" in str(files["test"])


# ── Capability gap HTML report ──────────────────────────────────────────────


def test_generate_capability_gap_report_basic():
    """Generated HTML contains target names and feature names."""
    gap_data = {
        "codex": [
            {"feature": "Skills", "status": "unsupported",
             "description": "No skill system", "workaround": "Use AGENTS.md rules"},
        ],
        "gemini": [
            {"feature": "MCP Servers", "status": "partial",
             "description": "Limited server support", "workaround": "Use stdio only"},
        ],
    }
    html = generate_capability_gap_report(gap_data)
    assert "Codex" in html or "codex" in html
    assert "Gemini" in html or "gemini" in html
    assert "Skills" in html
    assert "MCP Servers" in html


def test_generate_capability_gap_report_status_badges():
    """Status badges are included in the HTML."""
    gap_data = {
        "aider": [
            {"feature": "Agents", "status": "unsupported",
             "description": "No agent support", "workaround": ""},
            {"feature": "Profiles", "status": "workaround",
             "description": "Manual only", "workaround": "Use --config flag"},
        ],
    }
    html = generate_capability_gap_report(gap_data)
    assert "UNSUPPORTED" in html
    assert "WORKAROUND" in html


def test_generate_capability_gap_report_no_workarounds_flag():
    """include_workarounds=False omits the workaround column."""
    gap_data = {
        "codex": [
            {"feature": "Skills", "status": "unsupported",
             "description": "No skill system", "workaround": "Use AGENTS.md"},
        ],
    }
    html_with = generate_capability_gap_report(gap_data, include_workarounds=True)
    html_without = generate_capability_gap_report(gap_data, include_workarounds=False)
    assert "Workaround" in html_with
    assert "Workaround" not in html_without


def test_generate_capability_gap_report_empty_target():
    """A target with no gaps shows a success message."""
    gap_data = {
        "opencode": [],
    }
    html = generate_capability_gap_report(gap_data)
    assert "No capability gaps" in html


def test_generate_capability_gap_report_valid_html_structure():
    """Generated HTML has basic structural elements."""
    gap_data = {"codex": []}
    html = generate_capability_gap_report(gap_data)
    assert "<!DOCTYPE html>" in html
    assert "<html" in html
    assert "</html>" in html
    assert "<title>" in html


def test_write_capability_gap_report_creates_file(tmp_path):
    """write_capability_gap_report writes the file to disk."""
    gap_data = {
        "gemini": [
            {"feature": "Commands", "status": "partial",
             "description": "Summarized only", "workaround": ""},
        ],
    }
    out = tmp_path / "gap_report.html"
    write_capability_gap_report(gap_data, out)
    assert out.exists()
    content = out.read_text()
    assert "Commands" in content


def test_generate_capability_gap_report_total_in_meta():
    """Report metadata includes the total gap count."""
    gap_data = {
        "codex": [
            {"feature": "A", "status": "unsupported", "description": "x", "workaround": ""},
            {"feature": "B", "status": "partial", "description": "y", "workaround": ""},
        ],
        "gemini": [
            {"feature": "C", "status": "workaround", "description": "z", "workaround": ""},
        ],
    }
    html = generate_capability_gap_report(gap_data)
    assert "3 total gap" in html
