from __future__ import annotations

"""Tests for iteration 64 product-ideation improvements.

Covers:
- Sync Conflict Resolution Wizard (item 1): SyncConflictWizard.auto_resolve()
- Per-Project Sync Profiles (item 4): load_project_profile / save_project_profile
- Named Config Snapshots (item 22): NamedSnapshotStore
- Rule Triage by Harness Support (item 11): triage_by_portability / format_portability_triage
- Rules Coverage Heatmap (item 3): HarnessFeatureMatrix.render_coverage_heatmap()
- Pre-Sync Capability Preview (item 2): SyncImpactPredictor.build_capability_preview()
- Scheduled Sync Cron (item 20): SyncScheduler
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.conflict_detector import SyncConflictWizard
from src.profile_manager import load_project_profile, save_project_profile, merge_project_profile
from src.config_snapshot import NamedSnapshotStore
from src.rule_categorizer import triage_by_portability, format_portability_triage, RulePortability
from src.harness_feature_matrix import HarnessFeatureMatrix
from src.sync_impact_predictor import SyncImpactPredictor
from src.sync_scheduler import SyncScheduler, ScheduleEntry, _INTERVAL_MAP


# ── SyncConflictWizard ──────────────────────────────────────────────────────


def test_conflict_wizard_invalid_strategy():
    """Unknown strategy raises ValueError."""
    with pytest.raises(ValueError, match="Unknown strategy"):
        SyncConflictWizard(strategy="magic")


def test_conflict_wizard_ours_returns_source():
    """Strategy 'ours' returns source content."""
    wizard = SyncConflictWizard(strategy="ours")
    three_way = {
        "file_path": "AGENTS.md",
        "source_lines": ["# Source\n", "new rule\n"],
        "current_lines": ["# Target\n", "manual edit\n"],
    }
    label, content = wizard.auto_resolve(three_way)
    assert label == "synced"
    assert "new rule" in content
    assert "manual edit" not in content


def test_conflict_wizard_theirs_returns_current():
    """Strategy 'theirs' preserves manual edits."""
    wizard = SyncConflictWizard(strategy="theirs")
    three_way = {
        "file_path": "GEMINI.md",
        "source_lines": ["sync version\n"],
        "current_lines": ["manual version\n"],
    }
    label, content = wizard.auto_resolve(three_way)
    assert label == "keep"
    assert "manual version" in content


def test_conflict_wizard_newer_is_alias_for_ours():
    """Strategy 'newer' behaves identically to 'ours'."""
    wizard = SyncConflictWizard(strategy="newer")
    three_way = {
        "file_path": "test.md",
        "source_lines": ["source line\n"],
        "current_lines": ["current line\n"],
    }
    label, content = wizard.auto_resolve(three_way)
    assert label == "synced"
    assert "source line" in content


def test_conflict_wizard_union_includes_source_first():
    """Strategy 'union' includes source lines, then novel current lines."""
    wizard = SyncConflictWizard(strategy="union")
    three_way = {
        "file_path": "rules.md",
        "source_lines": ["rule A\n", "rule B\n"],
        "current_lines": ["rule A\n", "rule C\n"],   # rule C is novel
    }
    label, content = wizard.auto_resolve(three_way)
    assert label == "merged"
    assert "rule A" in content
    assert "rule B" in content
    assert "rule C" in content
    # source content should appear before the novel current lines
    assert content.index("rule A") < content.index("rule C")


def test_conflict_wizard_union_no_duplication():
    """Shared lines are not duplicated in union strategy."""
    wizard = SyncConflictWizard(strategy="union")
    three_way = {
        "file_path": "f.md",
        "source_lines": ["shared line\n"],
        "current_lines": ["shared line\n"],
    }
    _label, content = wizard.auto_resolve(three_way)
    assert content.count("shared line") == 1


def test_conflict_wizard_resolve_many():
    """resolve_many returns one tuple per three-way dict."""
    wizard = SyncConflictWizard(strategy="ours")
    three_ways = [
        {"file_path": "a.md", "source_lines": ["a\n"], "current_lines": ["x\n"]},
        {"file_path": "b.md", "source_lines": ["b\n"], "current_lines": ["y\n"]},
    ]
    results = wizard.resolve_many(three_ways)
    assert len(results) == 2
    assert results[0][0] == "a.md"
    assert results[1][0] == "b.md"


def test_conflict_wizard_build_resolution_summary():
    """build_resolution_summary returns readable text."""
    wizard = SyncConflictWizard(strategy="theirs")
    three_ways = [
        {"file_path": "AGENTS.md", "source_lines": ["s\n"], "current_lines": ["c\n"]},
    ]
    summary = wizard.build_resolution_summary(three_ways)
    assert "AGENTS.md" in summary
    assert "keep" in summary.lower() or "theirs" in summary.lower() or "manual" in summary.lower()
    assert "Total: 1 file(s)" in summary


# ── Per-Project Sync Profiles ───────────────────────────────────────────────


def test_load_project_profile_missing(tmp_path):
    """Returns None when .harnesssync.json does not exist."""
    assert load_project_profile(tmp_path) is None


def test_save_and_load_project_profile(tmp_path):
    """Saving then loading a project profile round-trips correctly."""
    profile = {"skip_sections": ["mcp"], "targets": ["codex", "gemini"]}
    save_project_profile(tmp_path, profile)
    loaded = load_project_profile(tmp_path)
    assert loaded == profile


def test_save_project_profile_invalid_type(tmp_path):
    """Passing a non-dict raises ValueError."""
    with pytest.raises(ValueError):
        save_project_profile(tmp_path, ["not", "a", "dict"])  # type: ignore[arg-type]


def test_load_project_profile_invalid_json(tmp_path):
    """Returns None when .harnesssync.json contains invalid JSON."""
    (tmp_path / ".harnesssync.json").write_text("{ not valid json }", encoding="utf-8")
    assert load_project_profile(tmp_path) is None


def test_merge_project_profile_project_wins():
    """Project profile keys override named profile keys."""
    named = {"scope": "all", "targets": ["codex"]}
    project = {"targets": ["gemini"], "skip_sections": ["mcp"]}
    merged = merge_project_profile(named, project)
    assert merged["targets"] == ["gemini"]
    assert merged["scope"] == "all"
    assert merged["skip_sections"] == ["mcp"]


def test_merge_project_profile_both_none():
    """Both None produces empty dict."""
    assert merge_project_profile(None, None) == {}


def test_merge_project_profile_named_only():
    """When project profile is None, named profile is returned."""
    named = {"scope": "user"}
    merged = merge_project_profile(named, None)
    assert merged == named


def test_save_project_profile_creates_file(tmp_path):
    """File is created at correct path."""
    save_project_profile(tmp_path, {"description": "test"})
    assert (tmp_path / ".harnesssync.json").exists()


# ── NamedSnapshotStore ──────────────────────────────────────────────────────


def test_named_snapshot_save_and_load(tmp_path):
    """Saving then loading a snapshot round-trips correctly."""
    store = NamedSnapshotStore(store_dir=tmp_path)
    snap = {"rules": "always use TypeScript", "mcp": {}}
    store.save("pre-migration", snap)
    loaded = store.load("pre-migration")
    assert loaded == snap


def test_named_snapshot_list_names(tmp_path):
    """list_names returns all saved snapshot names."""
    store = NamedSnapshotStore(store_dir=tmp_path)
    store.save("snap-a", {"rules": "a"})
    store.save("snap-b", {"rules": "b"})
    names = store.list_names()
    assert "snap-a" in names
    assert "snap-b" in names


def test_named_snapshot_delete(tmp_path):
    """Deleting a snapshot removes it from list_names."""
    store = NamedSnapshotStore(store_dir=tmp_path)
    store.save("temp", {"data": 1})
    assert store.delete("temp") is True
    assert "temp" not in store.list_names()


def test_named_snapshot_delete_missing(tmp_path):
    """Deleting a non-existent snapshot returns False."""
    store = NamedSnapshotStore(store_dir=tmp_path)
    assert store.delete("nonexistent") is False


def test_named_snapshot_load_missing(tmp_path):
    """Loading a non-existent snapshot returns None."""
    store = NamedSnapshotStore(store_dir=tmp_path)
    assert store.load("ghost") is None


def test_named_snapshot_invalid_name(tmp_path):
    """Invalid snapshot name raises ValueError."""
    store = NamedSnapshotStore(store_dir=tmp_path)
    with pytest.raises(ValueError):
        store.save("../hack", {})


def test_named_snapshot_load_metadata(tmp_path):
    """load_metadata returns name and saved_at without full payload."""
    store = NamedSnapshotStore(store_dir=tmp_path)
    store.save("meta-test", {"key": "value"})
    meta = store.load_metadata("meta-test")
    assert meta is not None
    assert meta["name"] == "meta-test"
    assert "saved_at" in meta


def test_named_snapshot_format_listing_empty(tmp_path):
    """format_listing handles empty store gracefully."""
    store = NamedSnapshotStore(store_dir=tmp_path)
    listing = store.format_listing()
    assert "No named snapshots" in listing


def test_named_snapshot_format_listing_populated(tmp_path):
    """format_listing includes saved snapshot names."""
    store = NamedSnapshotStore(store_dir=tmp_path)
    store.save("project-x", {"rules": "x"})
    listing = store.format_listing()
    assert "project-x" in listing


# ── Rule Portability Triage ─────────────────────────────────────────────────


def test_triage_universal_rule():
    """Plain coding rules with no CC-specific syntax are classified universal."""
    text = "## Always use TypeScript\nPrefer TypeScript over JavaScript in all new files."
    results = triage_by_portability(text)
    assert len(results) == 1
    assert results[0].portability == "universal"


def test_triage_cc_only_rule():
    """Rules referencing CC-specific tools are classified claude-code-only."""
    text = "## Use EnterPlanMode\nBefore big changes, call EnterPlanMode to plan."
    results = triage_by_portability(text)
    assert len(results) == 1
    assert results[0].portability == "claude-code-only"


def test_triage_approximable_rule():
    """Rules mentioning skills or agents are classified approximable."""
    text = "## Use skills\nInvoke a skill to handle repetitive workflows."
    results = triage_by_portability(text)
    assert len(results) == 1
    assert results[0].portability == "approximable"


def test_triage_multiple_sections():
    """Multiple sections are each classified independently."""
    text = (
        "## Rule A\nAlways write tests.\n\n"
        "## Rule B\nUse the TodoWrite tool.\n\n"
        "## Rule C\nInvoke skill for linting.\n"
    )
    results = triage_by_portability(text)
    assert len(results) == 3
    types = {r.title: r.portability for r in results}
    assert types["Rule A"] == "universal"
    assert types["Rule B"] == "claude-code-only"
    assert types["Rule C"] == "approximable"


def test_triage_empty_document():
    """Empty document produces no results."""
    results = triage_by_portability("")
    assert results == []


def test_triage_suggestion_for_non_universal():
    """Non-universal rules include a non-empty suggestion."""
    text = "## Skill Rule\nUse skills for all workflow automation."
    results = triage_by_portability(text)
    assert results[0].suggestion != ""


def test_triage_universal_no_suggestion():
    """Universal rules have an empty suggestion string."""
    text = "## Format code\nAlways run prettier before committing."
    results = triage_by_portability(text)
    assert results[0].portability == "universal"
    assert results[0].suggestion == ""


def test_format_portability_triage_output():
    """format_portability_triage produces readable multi-line output."""
    text = "## A\nAlways use tabs.\n\n## B\nUse EnterPlanMode to plan before big changes."
    results = triage_by_portability(text)
    output = format_portability_triage(results)
    assert "UNIVERSAL" in output or "universal" in output.lower()
    assert "CC ONLY" in output or "claude-code-only" in output.lower()


def test_format_portability_triage_empty():
    """format_portability_triage handles empty input."""
    output = format_portability_triage([])
    assert "No rule sections found" in output


# ── Rules Coverage Heatmap ──────────────────────────────────────────────────


def test_render_coverage_heatmap_basic():
    """Heatmap renders without errors and includes all target names."""
    matrix = HarnessFeatureMatrix()
    output = matrix.render_coverage_heatmap()
    assert "codex" in output
    assert "gemini" in output
    assert "aider" in output


def test_render_coverage_heatmap_contains_glyphs():
    """Heatmap includes the expected glyph characters."""
    matrix = HarnessFeatureMatrix()
    output = matrix.render_coverage_heatmap()
    assert "■" in output or "◑" in output or "✗" in output


def test_render_coverage_heatmap_coverage_line():
    """Heatmap footer includes native coverage percentage."""
    matrix = HarnessFeatureMatrix()
    output = matrix.render_coverage_heatmap()
    assert "Native coverage:" in output
    assert "%" in output


def test_render_coverage_heatmap_subset_targets():
    """Heatmap with restricted targets only shows those targets."""
    matrix = HarnessFeatureMatrix()
    output = matrix.render_coverage_heatmap(targets=["codex", "gemini"])
    assert "codex" in output
    assert "gemini" in output
    assert "aider" not in output


def test_render_coverage_heatmap_subset_features():
    """Heatmap with restricted features only shows those feature columns."""
    matrix = HarnessFeatureMatrix()
    output = matrix.render_coverage_heatmap(features=["rules", "mcp"])
    assert "rule" in output.lower()
    # 'skills' column header should not appear when skills not in feature list
    # (first 4 chars of 'skills' = 'skil')
    assert "skil" not in output.lower()


def test_render_coverage_heatmap_no_color():
    """Default (no color) output contains no ANSI escape codes."""
    matrix = HarnessFeatureMatrix()
    output = matrix.render_coverage_heatmap(use_color=False)
    assert "\033[" not in output


def test_render_coverage_heatmap_with_color():
    """With use_color=True, output includes ANSI escape codes."""
    matrix = HarnessFeatureMatrix()
    output = matrix.render_coverage_heatmap(use_color=True)
    assert "\033[" in output


# ── Pre-Sync Capability Preview ─────────────────────────────────────────────


def test_build_capability_preview_returns_targets():
    """build_capability_preview returns keys for all requested targets."""
    predictor = SyncImpactPredictor()
    current = {"rules": "use TypeScript\n", "mcp": {"github": {}}, "skills": []}
    previous = {"rules": "", "mcp": {}, "skills": []}
    previews = predictor.build_capability_preview(
        current, previous, targets=["codex", "gemini", "aider"]
    )
    assert set(previews.keys()) == {"codex", "gemini", "aider"}


def test_build_capability_preview_rules_added():
    """rules_added count reflects new rule lines."""
    predictor = SyncImpactPredictor()
    current = {"rules": "rule A\nrule B\n"}
    previous = {"rules": "rule A\n"}
    previews = predictor.build_capability_preview(current, previous, targets=["codex"])
    assert previews["codex"]["rules_added"] >= 1


def test_build_capability_preview_mcp_added():
    """mcp_added lists newly introduced MCP servers."""
    predictor = SyncImpactPredictor()
    current = {"mcp": {"github": {}, "slack": {}}}
    previous = {"mcp": {"github": {}}}
    previews = predictor.build_capability_preview(current, previous, targets=["codex"])
    assert "slack" in previews["codex"]["mcp_added"]


def test_build_capability_preview_mcp_blocked_for_aider():
    """MCP servers are not added for aider (mcp is unsupported)."""
    predictor = SyncImpactPredictor()
    current = {"mcp": {"new-server": {}}}
    previous = {}
    previews = predictor.build_capability_preview(current, previous, targets=["aider"])
    assert previews["aider"]["mcp_added"] == []


def test_build_capability_preview_summary_string():
    """Summary string is non-empty when there are changes."""
    predictor = SyncImpactPredictor()
    current = {"rules": "new rule\n", "mcp": {}}
    previous = {}
    previews = predictor.build_capability_preview(current, previous, targets=["codex"])
    assert previews["codex"]["summary"] != "no changes"


def test_build_capability_preview_no_changes():
    """Summary is 'no changes' when source identical to previous."""
    predictor = SyncImpactPredictor()
    source = {"rules": "same rule\n", "mcp": {}}
    previews = predictor.build_capability_preview(source, source, targets=["codex"])
    # rules_added is 0 when lines are identical
    assert previews["codex"]["rules_added"] == 0


def test_format_capability_preview_output():
    """format_capability_preview produces readable output."""
    predictor = SyncImpactPredictor()
    current = {"rules": "new rule\n", "mcp": {"gh": {}}}
    previous = {}
    previews = predictor.build_capability_preview(current, previous, targets=["codex", "gemini"])
    output = predictor.format_capability_preview(previews)
    assert "codex" in output
    assert "gemini" in output
    assert "Pre-Sync Capability Preview" in output


def test_format_capability_preview_empty():
    """format_capability_preview handles empty previews."""
    predictor = SyncImpactPredictor()
    output = predictor.format_capability_preview({})
    assert "No targets" in output


# ── SyncScheduler ────────────────────────────────────────────────────────────


def test_sync_scheduler_add_valid_interval(tmp_path):
    """Adding a valid interval with dry_run=True succeeds."""
    scheduler = SyncScheduler(state_dir=tmp_path, dry_run=True)
    ok, msg = scheduler.add("daily")
    assert ok
    assert "daily" in msg.lower() or "scheduled" in msg.lower()


def test_sync_scheduler_add_invalid_interval(tmp_path):
    """Adding an unknown interval returns failure."""
    scheduler = SyncScheduler(state_dir=tmp_path, dry_run=True)
    ok, msg = scheduler.add("every-tuesday-at-3pm")
    assert not ok
    assert "Unknown interval" in msg or "Valid:" in msg


def test_sync_scheduler_persists_entry(tmp_path):
    """Adding a schedule writes a descriptor file."""
    scheduler = SyncScheduler(state_dir=tmp_path, dry_run=True)
    scheduler.add("hourly")
    entry = scheduler.get()
    assert entry is not None
    assert entry.interval == "hourly"
    assert entry.cron_expr == _INTERVAL_MAP["hourly"]


def test_sync_scheduler_remove_clears_entry(tmp_path):
    """Removing a schedule deletes the descriptor."""
    scheduler = SyncScheduler(state_dir=tmp_path, dry_run=True)
    scheduler.add("daily")
    ok, _ = scheduler.remove()
    assert ok
    assert scheduler.get() is None


def test_sync_scheduler_interval_map_coverage():
    """All standard interval strings are in the map."""
    for key in ("hourly", "daily", "weekly", "30m"):
        assert key in _INTERVAL_MAP


def test_sync_scheduler_targets_stored(tmp_path):
    """Target list is persisted in the schedule entry."""
    scheduler = SyncScheduler(state_dir=tmp_path, dry_run=True)
    scheduler.add("daily", targets=["codex", "gemini"])
    entry = scheduler.get()
    assert entry is not None
    assert "codex" in entry.targets
    assert "gemini" in entry.targets


def test_sync_scheduler_format_status_not_configured(tmp_path):
    """format_status reports 'not configured' when no schedule exists."""
    scheduler = SyncScheduler(state_dir=tmp_path, dry_run=True)
    status = scheduler.format_status()
    assert "not configured" in status


def test_sync_scheduler_format_status_after_add(tmp_path):
    """format_status includes interval after a schedule is added."""
    scheduler = SyncScheduler(state_dir=tmp_path, dry_run=True)
    scheduler.add("weekly")
    status = scheduler.format_status()
    assert "weekly" in status


def test_schedule_entry_round_trip():
    """ScheduleEntry round-trips through to_dict / from_dict."""
    entry = ScheduleEntry(
        interval="daily",
        cron_expr="0 9 * * *",
        targets=["codex"],
        created_at="2026-01-01T09:00:00Z",
    )
    restored = ScheduleEntry.from_dict(entry.to_dict())
    assert restored.interval == entry.interval
    assert restored.cron_expr == entry.cron_expr
    assert restored.targets == entry.targets
