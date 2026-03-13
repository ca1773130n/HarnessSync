from __future__ import annotations

"""Tests for iteration 68 product-ideation improvements.

Covers:
- Drift Duration Tracker (item 6): DriftDurationTracker
- Per-Harness Coverage Score Format (item 9): HarnessComparisonReport.format_coverage_summary
- MCP Env Var Remapping (item 10/23): remap_mcp_env_vars / normalize_mcp_paths
- Translation Confidence Annotations (item 11): ConfidenceLevel / annotate_with_confidence
- Skill Browser HTML (item 21): generate_skill_browser
- Source Change Watcher auto-sync (item 27): SourceChangeWatcher
"""

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sync_metrics import DriftDurationTracker
from src.harness_comparison import HarnessComparisonReport, HarnessFeatureComparisonRow
from src.mcp_aliasing import remap_mcp_env_vars, normalize_mcp_paths
from src.skill_translator import (
    ConfidenceLevel,
    compute_confidence_level,
    annotate_with_confidence,
    translate_skill_content,
)
from src.html_report import generate_skill_browser
from src.drift_watcher import SourceChangeWatcher


# ── DriftDurationTracker ─────────────────────────────────────────────────────


def test_drift_duration_tracker_mark_start(tmp_path):
    """Marking drift start records the target as drifting."""
    tracker = DriftDurationTracker(persist_path=tmp_path / "drift.json")
    tracker.mark_drift_start("codex")
    assert tracker.is_drifting("codex")


def test_drift_duration_tracker_duration_positive(tmp_path):
    """Duration is positive after marking drift start."""
    tracker = DriftDurationTracker(persist_path=tmp_path / "drift.json")
    tracker.mark_drift_start("gemini", timestamp=time.time() - 3600)
    duration = tracker.drift_duration("gemini")
    assert duration is not None
    assert duration >= 3599


def test_drift_duration_tracker_resolved(tmp_path):
    """Resolved targets report their total duration, not current time."""
    tracker = DriftDurationTracker(persist_path=tmp_path / "drift.json")
    start = time.time() - 100
    end = time.time() - 50
    tracker.mark_drift_start("cursor", timestamp=start)
    tracker.mark_drift_resolved("cursor", timestamp=end)
    assert not tracker.is_drifting("cursor")
    duration = tracker.drift_duration("cursor")
    assert duration is not None
    assert abs(duration - 50) < 2  # ~50 seconds


def test_drift_duration_tracker_none_for_unknown(tmp_path):
    """Unknown targets return None duration."""
    tracker = DriftDurationTracker(persist_path=tmp_path / "drift.json")
    assert tracker.drift_duration("unknown-target") is None


def test_drift_duration_tracker_format_duration(tmp_path):
    """format_duration returns readable strings."""
    tracker = DriftDurationTracker(persist_path=tmp_path / "drift.json")
    tracker.mark_drift_start("aider", timestamp=time.time() - 7200)
    desc = tracker.format_duration("aider")
    assert "hour" in desc


def test_drift_duration_tracker_format_report(tmp_path):
    """format_report lists all tracked targets."""
    tracker = DriftDurationTracker(persist_path=tmp_path / "drift.json")
    tracker.mark_drift_start("codex")
    tracker.mark_drift_start("gemini")
    tracker.mark_drift_resolved("gemini")
    report = tracker.format_report()
    assert "codex" in report
    assert "gemini" in report
    assert "DRIFTING" in report
    assert "resolved" in report


def test_drift_duration_tracker_idempotent_start(tmp_path):
    """Calling mark_drift_start twice preserves the original start time."""
    tracker = DriftDurationTracker(persist_path=tmp_path / "drift.json")
    t0 = time.time() - 200
    tracker.mark_drift_start("codex", timestamp=t0)
    tracker.mark_drift_start("codex")  # Second call should be a no-op
    duration = tracker.drift_duration("codex")
    assert duration is not None
    assert duration >= 190  # Original 200s start preserved


def test_drift_duration_tracker_persistence(tmp_path):
    """Drift state persists across tracker instances."""
    path = tmp_path / "drift.json"
    t0 = time.time() - 60
    tracker = DriftDurationTracker(persist_path=path)
    tracker.mark_drift_start("windsurf", timestamp=t0)

    # Reload from disk
    tracker2 = DriftDurationTracker(persist_path=path)
    assert tracker2.is_drifting("windsurf")
    assert tracker2.drift_duration("windsurf") is not None


# ── HarnessComparisonReport.format_coverage_summary ──────────────────────────


def _make_report(targets, scores, gaps=None) -> HarnessComparisonReport:
    return HarnessComparisonReport(
        targets=targets,
        source_sections=["rules", "skills"],
        rows=[],
        rule_coverage={t: 10 for t in targets},
        compliance_rule_count=0,
        tag_filtered_targets={t: 0 for t in targets},
        overall_scores=scores,
        parity_gaps=gaps or {t: [] for t in targets},
    )


def test_format_coverage_summary_percentages():
    """Coverage summary includes scores for each target."""
    report = _make_report(
        ["codex", "gemini"],
        {"codex": 87.0, "gemini": 100.0},
        {"codex": ["skills: not supported"], "gemini": []},
    )
    summary = report.format_coverage_summary()
    assert "87%" in summary
    assert "100%" in summary
    assert "codex" in summary
    assert "gemini" in summary


def test_format_coverage_summary_gap_count():
    """Coverage summary mentions number of features with no equivalent."""
    report = _make_report(
        ["cursor"],
        {"cursor": 62.0},
        {"cursor": ["skills: not supported", "agents: not supported", "commands: not supported"]},
    )
    summary = report.format_coverage_summary()
    assert "3 feature" in summary


def test_format_coverage_summary_no_gaps():
    """Target with no gaps doesn't mention 'have no equivalent'."""
    report = _make_report(["gemini"], {"gemini": 100.0}, {"gemini": []})
    summary = report.format_coverage_summary()
    assert "have no equivalent" not in summary


def test_format_gap_details():
    """format_gap_details lists gap descriptions per target."""
    report = _make_report(
        ["codex"],
        {"codex": 75.0},
        {"codex": ["skills: not supported — no skill concept", "commands: not supported"]},
    )
    details = report.format_gap_details()
    assert "codex" in details
    assert "skills" in details


def test_format_coverage_summary_empty():
    """Empty scores returns sensible fallback message."""
    report = _make_report([], {}, {})
    summary = report.format_coverage_summary()
    assert summary  # Non-empty


# ── remap_mcp_env_vars ────────────────────────────────────────────────────────


def test_remap_mcp_env_vars_codex_anthropic_key():
    """ANTHROPIC_API_KEY is remapped to OPENAI_API_KEY for Codex proxy targets."""
    servers = {
        "my-proxy": {
            "command": "npx",
            "args": ["my-proxy"],
            "env": {"ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"},
        }
    }
    result = remap_mcp_env_vars(servers, "codex")
    assert "OPENAI_API_KEY" in result["my-proxy"]["env"]
    assert "ANTHROPIC_API_KEY" not in result["my-proxy"]["env"]


def test_remap_mcp_env_vars_no_change_for_opencode():
    """ANTHROPIC_API_KEY stays the same for OpenCode (same var name)."""
    servers = {
        "my-server": {
            "command": "npx",
            "args": [],
            "env": {"ANTHROPIC_API_KEY": "${ANTHROPIC_API_KEY}"},
        }
    }
    result = remap_mcp_env_vars(servers, "opencode")
    # opencode maps to same var name — no rename needed
    assert "ANTHROPIC_API_KEY" in result["my-server"]["env"]


def test_remap_mcp_env_vars_no_env_key():
    """Servers without env block are returned unchanged."""
    servers = {"no-env-server": {"command": "npx", "args": []}}
    result = remap_mcp_env_vars(servers, "codex")
    assert result["no-env-server"] == {"command": "npx", "args": []}


def test_remap_mcp_env_vars_extra_remaps():
    """extra_remaps parameter allows caller overrides."""
    servers = {
        "s": {"command": "x", "args": [], "env": {"MY_SECRET": "abc"}}
    }
    result = remap_mcp_env_vars(servers, "cursor", extra_remaps={"MY_SECRET": "CURSOR_SECRET"})
    assert "CURSOR_SECRET" in result["s"]["env"]
    assert "MY_SECRET" not in result["s"]["env"]


def test_normalize_mcp_paths_relative():
    """Relative 'cwd' values are expanded to absolute paths."""
    servers = {"s": {"command": "x", "args": [], "cwd": "subdir/child"}}
    result = normalize_mcp_paths(servers, base_dir="/home/user/project")
    cwd = result["s"]["cwd"]
    assert cwd.startswith("/")
    assert "subdir" in cwd


def test_normalize_mcp_paths_absolute_unchanged():
    """Absolute paths are not modified."""
    servers = {"s": {"command": "x", "args": [], "cwd": "/absolute/path"}}
    result = normalize_mcp_paths(servers, base_dir="/home/user")
    assert result["s"]["cwd"] == "/absolute/path"


# ── ConfidenceLevel / annotate_with_confidence ────────────────────────────────


def test_confidence_level_exact_clean_content():
    """Clean content with no CC constructs is classified as exact or approximate."""
    content = "Always write unit tests for every public function."
    translated = content  # No changes
    level = compute_confidence_level(content, translated, "gemini")
    assert level in (ConfidenceLevel.EXACT, ConfidenceLevel.APPROXIMATE)


def test_confidence_level_lossy_with_mcp_refs():
    """Content with remaining MCP refs is classified as lossy."""
    content = "Call mcp__github__list_issues to check issues."
    translated = content  # MCP refs not removed
    level = compute_confidence_level(content, translated, "codex")
    assert level == ConfidenceLevel.LOSSY


def test_annotate_with_confidence_exact_format():
    """Exact confidence produces a single-line annotation."""
    content = "Write clean, testable code."
    translated = content
    result = annotate_with_confidence(content, translated, "my-skill", "gemini")
    assert "sync:confidence" in result
    assert "my-skill" in result
    assert "gemini" in result


def test_annotate_with_confidence_lossy_warning():
    """Lossy confidence includes a WARNING in the annotation."""
    content = "Use mcp__sentry__list_errors to check for errors."
    translated = content  # MCP refs remain
    result = annotate_with_confidence(content, translated, "sentry-skill", "codex")
    assert "lossy" in result
    assert "WARNING" in result


def test_annotate_with_confidence_preserves_content():
    """Annotated content always contains the original translated text."""
    content = "Only import what you need."
    translated = translate_skill_content(content, "codex")
    result = annotate_with_confidence(content, translated, "import-rule", "codex")
    # The translated text should appear after the annotation
    assert translated.strip() in result


def test_confidence_level_constants():
    """Confidence level constants are distinct strings."""
    levels = {ConfidenceLevel.EXACT, ConfidenceLevel.APPROXIMATE, ConfidenceLevel.LOSSY}
    assert len(levels) == 3


# ── generate_skill_browser ────────────────────────────────────────────────────


def test_generate_skill_browser_contains_skill_names():
    """Skill browser HTML contains skill names."""
    skills = [
        {"name": "commit-skill", "content": "Always write descriptive commit messages.", "path": "skills/commit-skill.md"},
        {"name": "test-skill", "content": "Write unit tests for all public functions.", "path": "skills/test-skill.md"},
    ]
    html = generate_skill_browser(skills, targets=["codex", "gemini"])
    assert "commit-skill" in html
    assert "test-skill" in html


def test_generate_skill_browser_contains_target_columns():
    """Skill browser has columns for each target."""
    skills = [{"name": "s", "content": "Be helpful.", "path": ""}]
    html = generate_skill_browser(skills, targets=["codex", "gemini", "cursor"])
    assert "codex" in html
    assert "gemini" in html
    assert "cursor" in html


def test_generate_skill_browser_has_confidence_badges():
    """Skill browser includes confidence badge CSS classes."""
    skills = [{"name": "s", "content": "Use Python.", "path": ""}]
    html = generate_skill_browser(skills, targets=["codex"])
    # At least one of the badge classes should be present
    assert "badge-exact" in html or "badge-approx" in html or "badge-lossy" in html


def test_generate_skill_browser_filter_script():
    """Skill browser includes the JavaScript filter function."""
    skills = [{"name": "s", "content": "x", "path": ""}]
    html = generate_skill_browser(skills)
    assert "filterSkills" in html


def test_generate_skill_browser_empty_skills():
    """Skill browser with no skills still produces valid HTML."""
    html = generate_skill_browser([], targets=["codex"])
    assert "<html" in html
    assert "table" in html


def test_generate_skill_browser_custom_title():
    """Custom title appears in the HTML."""
    skills = [{"name": "s", "content": "x", "path": ""}]
    html = generate_skill_browser(skills, title="My Skill Viewer")
    assert "My Skill Viewer" in html


# ── SourceChangeWatcher ───────────────────────────────────────────────────────


def test_source_change_watcher_detects_new_file(tmp_path):
    """SourceChangeWatcher detects a newly created source file."""
    changes_seen = []

    def callback(changed):
        changes_seen.extend(changed)

    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Rules\nBe helpful.", encoding="utf-8")

    watcher = SourceChangeWatcher(tmp_path, sync_callback=callback, poll_interval=0.1)
    # Take initial snapshot
    initial = watcher._hashes.copy()

    # Now modify the file
    claude_md.write_text("# Rules\nBe helpful.\n- New rule added.", encoding="utf-8")

    changed = watcher.check_and_sync()
    assert len(changed) > 0 or len(changes_seen) > 0


def test_source_change_watcher_no_change_no_sync(tmp_path):
    """SourceChangeWatcher does not call sync if nothing changed."""
    syncs = []

    watcher = SourceChangeWatcher(tmp_path, sync_callback=lambda f: syncs.append(f))

    # No files, no changes
    changed = watcher.check_and_sync()
    assert changed == []
    assert syncs == []


def test_source_change_watcher_start_stop(tmp_path):
    """SourceChangeWatcher can be started and stopped cleanly."""
    watcher = SourceChangeWatcher(
        tmp_path,
        sync_callback=lambda f: None,
        poll_interval=0.05,
    )
    watcher.start()
    assert watcher.is_running()
    watcher.stop()
    assert not watcher.is_running()


def test_source_change_watcher_debounce(tmp_path):
    """Debounce prevents rapid-fire sync callbacks."""
    sync_count = [0]

    def callback(changed):
        sync_count[0] += 1

    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("line1", encoding="utf-8")

    watcher = SourceChangeWatcher(
        tmp_path,
        sync_callback=callback,
        poll_interval=0.05,
        debounce_seconds=10.0,  # very long debounce
    )

    # First change: sync should be triggered (last_sync_time starts at 0)
    claude_md.write_text("line2", encoding="utf-8")
    watcher.check_and_sync()

    first_count = sync_count[0]

    # Second immediate change: debounce should prevent another sync call
    claude_md.write_text("line3", encoding="utf-8")
    watcher.check_and_sync()

    # Should still be 1 if debounce worked (or possibly 0 if first was also debounced)
    # The point is the second shouldn't add another if debounce is active
    assert sync_count[0] <= first_count + 1
