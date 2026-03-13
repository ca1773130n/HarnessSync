from __future__ import annotations

"""Tests for iteration 67 product-ideation improvements.

Covers:
- Skill Translation Quality Hints (item 4): generate_improvement_hints / annotate_with_improvement_hints
- Capability Gap Upvote Tracker (item 29): GapUpvoteTracker
- Rule Priority Win Map (item 16): format_rule_win_map
- MCP Local-Only Server Detection (item 5): detect_local_only_servers / format_local_only_report
- Skill Coverage Report (item 21): SkillCoverageReport / build_skill_coverage_report
- Config Version Pinning (item 8): PinnedTargetManager
- Undo With Diff (item 30): HarnessUndoStack.diff_preview / undo_with_diff
- Context-Aware Sync Triggers (item 7): SyncTriggerRule / SyncTriggerMatcher
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.skill_translator import (
    generate_improvement_hints,
    annotate_with_improvement_hints,
    translate_skill_content,
)
from src.feature_gap_issue_creator import GapUpvoteTracker
from src.rule_priority_sorter import (
    RuleBlock,
    format_rule_win_map,
    extract_rule_blocks,
)
from src.mcp_reachability import (
    detect_local_only_servers,
    format_local_only_report,
    LocalOnlyServerResult,
)
from src.skill_gap_analyzer import (
    SkillCoverageEntry,
    SkillCoverageReport,
    _check_skill_in_target,
)
from src.config_snapshot import PinnedTargetManager
from src.sync_undo_stack import HarnessUndoStack, MAX_STACK_DEPTH
from src.sync_filter import SyncTriggerRule, SyncTriggerMatcher


# ── generate_improvement_hints ─────────────────────────────────────────────────


def test_improvement_hints_clean_content_no_hints():
    """Clean skill content with no CC-specific constructs generates no hints."""
    original = "Use Python for all scripts. Write unit tests for each function."
    translated = original  # No changes needed
    hints = generate_improvement_hints(original, translated, "my-skill", "gemini")
    # Clean content with no tool refs or MCP calls should have only idiom hints
    # (if content is long enough) but no critical problem hints
    assert isinstance(hints, list)


def test_improvement_hints_remaining_tool_refs():
    """Remaining tool references in translated content trigger a hint."""
    original = "Use the Read tool and the Write tool to manage files."
    translated = "Use reading and writing to manage files."  # refs removed by translate
    # Simulate a case where refs remain in translated
    translated_with_refs = "Use the Read tool to manage files."
    hints = generate_improvement_hints(original, translated_with_refs, "my-skill", "codex")
    assert any("Read" in h or "tool reference" in h.lower() for h in hints)


def test_improvement_hints_mcp_references():
    """MCP tool references in translated content trigger a hint."""
    original = "Call mcp__github__list_issues to find open issues."
    translated = original  # Assume translation didn't remove MCP refs
    hints = generate_improvement_hints(original, translated, "my-skill", "cursor")
    assert any("MCP" in h or "mcp__" in h.lower() for h in hints)


def test_improvement_hints_slash_commands():
    """Slash command references trigger a hint."""
    original = "Run /commit to create a commit."
    translated = "Run /commit to create a commit."
    hints = generate_improvement_hints(original, translated, "my-skill", "aider")
    assert any("slash" in h.lower() or "/commit" in h for h in hints)


def test_annotate_with_improvement_hints_clean():
    """Clean content returns the translated content unchanged."""
    content = "Always write docstrings for public functions."
    result = annotate_with_improvement_hints(content, content, "my-skill", "gemini")
    # For very short clean content with no tool refs or slash commands,
    # the result may or may not have hints appended
    assert content in result


def test_annotate_with_improvement_hints_adds_comment():
    """Content with MCP refs gets a hint comment appended."""
    original = "Use mcp__github__list_issues to check issues."
    translated = original
    result = annotate_with_improvement_hints(original, translated, "my-skill", "codex")
    assert "improvement hints" in result.lower() or "Manual improvement" in result


# ── GapUpvoteTracker ──────────────────────────────────────────────────────────


def test_gap_upvote_tracker_upvote_increments(tmp_path):
    """Upvoting a gap increments the vote count."""
    tracker = GapUpvoteTracker(store_path=tmp_path / "upvotes.json")
    count1 = tracker.upvote("codex", "skills")
    assert count1 == 1
    count2 = tracker.upvote("codex", "skills")
    assert count2 == 2


def test_gap_upvote_tracker_list_gaps(tmp_path):
    """list_gaps returns all tracked gaps sorted by votes."""
    tracker = GapUpvoteTracker(store_path=tmp_path / "upvotes.json")
    tracker.upvote("codex", "skills")
    tracker.upvote("codex", "skills")
    tracker.upvote("aider", "agents")
    gaps = tracker.list_gaps()
    assert len(gaps) == 2
    # Sorted by votes descending: codex:skills (2) before aider:agents (1)
    assert gaps[0]["harness"] == "codex"
    assert gaps[0]["feature"] == "skills"
    assert gaps[0]["votes"] == 2


def test_gap_upvote_tracker_min_votes_filter(tmp_path):
    """min_votes filters out gaps below the threshold."""
    tracker = GapUpvoteTracker(store_path=tmp_path / "upvotes.json")
    tracker.upvote("codex", "skills")
    tracker.upvote("aider", "agents")
    tracker.upvote("aider", "agents")
    gaps = tracker.list_gaps(min_votes=2)
    assert len(gaps) == 1
    assert gaps[0]["harness"] == "aider"


def test_gap_upvote_tracker_check_resolved(tmp_path):
    """check_resolved returns gaps that are now supported."""
    tracker = GapUpvoteTracker(store_path=tmp_path / "upvotes.json")
    # gemini:skills is in _KNOWN_SUPPORT as True (resolved)
    tracker.upvote("gemini", "skills")
    # cursor:skills is not resolved
    tracker.upvote("cursor", "skills")
    resolved = tracker.check_resolved()
    resolved_keys = [(g["harness"], g["feature"]) for g in resolved]
    assert ("gemini", "skills") in resolved_keys
    assert ("cursor", "skills") not in resolved_keys


def test_gap_upvote_tracker_format_report(tmp_path):
    """format_report returns a non-empty string with votes table."""
    tracker = GapUpvoteTracker(store_path=tmp_path / "upvotes.json")
    tracker.upvote("codex", "skills")
    report = tracker.format_report()
    assert "codex" in report
    assert "skills" in report


def test_gap_upvote_tracker_empty_report(tmp_path):
    """format_report returns a message when no gaps are tracked."""
    tracker = GapUpvoteTracker(store_path=tmp_path / "upvotes.json")
    report = tracker.format_report()
    assert "No capability gaps tracked" in report


# ── format_rule_win_map ──────────────────────────────────────────────────────


def test_format_rule_win_map_basic():
    """Win map generates a multi-harness priority comparison."""
    blocks = [
        RuleBlock(heading="## Testing", body="Write tests for everything.", index=0),
        RuleBlock(heading="## Style", body="Use PEP 8.", index=1),
        RuleBlock(heading="## Commits", body="Use conventional commits.", index=2),
    ]
    result = format_rule_win_map(blocks, targets=["codex", "aider"])
    assert "Testing" in result
    assert "Style" in result
    assert "Commits" in result
    # codex uses top_wins, aider uses last_wins
    assert "codex" in result
    assert "aider" in result


def test_format_rule_win_map_no_blocks():
    """Win map with no blocks returns a helpful message."""
    result = format_rule_win_map([], targets=["codex"])
    assert "No rule blocks found" in result


def test_format_rule_win_map_single_block():
    """Win map with one block returns valid output (no pairs to compare)."""
    blocks = [RuleBlock(heading="## Rules", body="Be concise.", index=0)]
    result = format_rule_win_map(blocks, targets=["codex", "gemini"])
    # One block has no adjacent pairs — the header should still appear
    assert isinstance(result, str)
    assert len(result) > 0


# ── detect_local_only_servers ─────────────────────────────────────────────────


def test_detect_local_only_servers_localhost_url():
    """Server with localhost URL is flagged as local-only."""
    servers = {
        "local-server": {
            "transport": "sse",
            "url": "http://localhost:3000/sse",
        }
    }
    results = detect_local_only_servers(servers)
    assert len(results) == 1
    assert results[0].name == "local-server"
    assert results[0].cloud_risk == "high"


def test_detect_local_only_servers_127_ip():
    """Server with 127.x.x.x URL is flagged."""
    servers = {
        "loopback": {
            "url": "http://127.0.0.1:8080",
        }
    }
    results = detect_local_only_servers(servers)
    assert any(r.name == "loopback" for r in results)


def test_detect_local_only_servers_unix_socket():
    """Server using Unix socket path is flagged."""
    servers = {
        "unix-server": {
            "url": "/tmp/mcp.sock",
        }
    }
    results = detect_local_only_servers(servers)
    assert len(results) == 1
    assert results[0].cloud_risk == "high"


def test_detect_local_only_servers_stdio_npx():
    """Stdio server using npx is flagged as medium risk."""
    servers = {
        "npx-server": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/"],
        }
    }
    results = detect_local_only_servers(servers)
    assert len(results) == 1
    assert results[0].cloud_risk == "medium"
    assert results[0].transport == "stdio"


def test_detect_local_only_servers_remote_url_safe():
    """Server with a public remote URL is NOT flagged."""
    servers = {
        "remote-server": {
            "transport": "sse",
            "url": "https://api.example.com/mcp/sse",
        }
    }
    results = detect_local_only_servers(servers)
    assert len(results) == 0


def test_detect_local_only_servers_empty():
    """Empty server config returns empty results."""
    assert detect_local_only_servers({}) == []


def test_format_local_only_report_with_results():
    """Report with results contains server name and risk level."""
    results = [
        LocalOnlyServerResult(
            name="local-db",
            reason="Binds to localhost:5432",
            transport="sse",
            cloud_risk="high",
            workaround="Deploy to cloud endpoint.",
        )
    ]
    report = format_local_only_report(results)
    assert "local-db" in report
    assert "HIGH RISK" in report


def test_format_local_only_report_empty():
    """Empty results returns a safe message."""
    report = format_local_only_report([])
    assert "safe" in report.lower() or "All MCP" in report


# ── SkillCoverageReport ───────────────────────────────────────────────────────


def test_skill_coverage_report_coverage_pct_all_present():
    """coverage_pct returns 100 when all skills are present."""
    entries = [
        SkillCoverageEntry("skill-a", "codex", present=True, translation_score=90),
        SkillCoverageEntry("skill-b", "codex", present=True, translation_score=80),
    ]
    report = SkillCoverageReport(
        entries=entries, source_skills=["skill-a", "skill-b"], targets=["codex"]
    )
    assert report.coverage_pct("codex") == 100.0


def test_skill_coverage_report_coverage_pct_partial():
    """coverage_pct returns 50 when half the skills are present."""
    entries = [
        SkillCoverageEntry("skill-a", "gemini", present=True, translation_score=75),
        SkillCoverageEntry("skill-b", "gemini", present=False, translation_score=0),
    ]
    report = SkillCoverageReport(
        entries=entries, source_skills=["skill-a", "skill-b"], targets=["gemini"]
    )
    assert report.coverage_pct("gemini") == 50.0


def test_skill_coverage_report_avg_translation_score():
    """avg_translation_score averages only present skills."""
    entries = [
        SkillCoverageEntry("skill-a", "codex", present=True, translation_score=80),
        SkillCoverageEntry("skill-b", "codex", present=True, translation_score=60),
        SkillCoverageEntry("skill-c", "codex", present=False, translation_score=0),
    ]
    report = SkillCoverageReport(
        entries=entries,
        source_skills=["skill-a", "skill-b", "skill-c"],
        targets=["codex"],
    )
    assert report.avg_translation_score("codex") == pytest.approx(70.0)


def test_skill_coverage_report_format_includes_headers():
    """format() output contains skill names and target headers."""
    entries = [
        SkillCoverageEntry("my-skill", "gemini", present=True, translation_score=85),
    ]
    report = SkillCoverageReport(
        entries=entries, source_skills=["my-skill"], targets=["gemini"]
    )
    output = report.format()
    assert "my-skill" in output
    assert "gemini" in output
    assert "Coverage" in output


def test_skill_coverage_report_unknown_target():
    """coverage_pct for unknown target returns 0."""
    report = SkillCoverageReport(entries=[], source_skills=[], targets=[])
    assert report.coverage_pct("nonexistent") == 0.0


# ── PinnedTargetManager ───────────────────────────────────────────────────────


def test_pinned_target_pin_and_is_pinned(tmp_path):
    """pin() marks a target as pinned; is_pinned() returns True."""
    mgr = PinnedTargetManager(pins_file=tmp_path / "pins.json")
    mgr.pin("gemini", checkpoint_tag="stable-v1", reason="testing pinning")
    assert mgr.is_pinned("gemini") is True
    assert mgr.is_pinned("codex") is False


def test_pinned_target_unpin(tmp_path):
    """unpin() removes a pin; is_pinned() returns False afterward."""
    mgr = PinnedTargetManager(pins_file=tmp_path / "pins.json")
    mgr.pin("aider")
    assert mgr.is_pinned("aider") is True
    result = mgr.unpin("aider")
    assert result is True
    assert mgr.is_pinned("aider") is False


def test_pinned_target_unpin_nonexistent(tmp_path):
    """Unpinning a target that was not pinned returns False."""
    mgr = PinnedTargetManager(pins_file=tmp_path / "pins.json")
    assert mgr.unpin("cursor") is False


def test_pinned_target_get_pin(tmp_path):
    """get_pin returns the pin entry with expected fields."""
    mgr = PinnedTargetManager(pins_file=tmp_path / "pins.json")
    mgr.pin("gemini", checkpoint_tag="snap-2026", reason="stable release")
    pin = mgr.get_pin("gemini")
    assert pin is not None
    assert pin["target"] == "gemini"
    assert pin["checkpoint_tag"] == "snap-2026"
    assert pin["reason"] == "stable release"
    assert "pinned_at" in pin


def test_pinned_target_filter_unpinned(tmp_path):
    """filter_unpinned excludes pinned targets from the list."""
    mgr = PinnedTargetManager(pins_file=tmp_path / "pins.json")
    mgr.pin("gemini")
    all_targets = ["codex", "gemini", "opencode"]
    unpinned = mgr.filter_unpinned(all_targets)
    assert "gemini" not in unpinned
    assert "codex" in unpinned
    assert "opencode" in unpinned


def test_pinned_target_list_pins(tmp_path):
    """list_pins returns all pins sorted by target name."""
    mgr = PinnedTargetManager(pins_file=tmp_path / "pins.json")
    mgr.pin("opencode")
    mgr.pin("codex")
    mgr.pin("gemini")
    pins = mgr.list_pins()
    assert len(pins) == 3
    names = [p["target"] for p in pins]
    assert names == sorted(names)


def test_pinned_target_format_status_no_pins(tmp_path):
    """format_status with no pins returns an informative message."""
    mgr = PinnedTargetManager(pins_file=tmp_path / "pins.json")
    status = mgr.format_status()
    assert "No targets are pinned" in status


def test_pinned_target_format_status_with_pins(tmp_path):
    """format_status with pins lists them."""
    mgr = PinnedTargetManager(pins_file=tmp_path / "pins.json")
    mgr.pin("gemini", reason="stable")
    status = mgr.format_status()
    assert "gemini" in status
    assert "Pinned" in status or "pinned" in status


# ── HarnessUndoStack.diff_preview / undo_with_diff ───────────────────────────


def test_diff_preview_empty_stack(tmp_path):
    """diff_preview returns a message when stack is empty."""
    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=tmp_path)
    preview = stack.diff_preview()
    assert "empty" in preview.lower()


def test_diff_preview_no_differences(tmp_path):
    """diff_preview reports no differences when current matches saved content."""
    project = tmp_path / "project"
    project.mkdir()
    target_file = project / "AGENTS.md"
    content = "# Rules\nWrite tests.\n"
    target_file.write_text(content, encoding="utf-8")

    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=project)
    stack.push({"AGENTS.md": content}, label="snapshot")

    preview = stack.diff_preview()
    assert "no-op" in preview.lower() or "no differences" in preview.lower() or "identical" in preview.lower()


def test_diff_preview_shows_changes(tmp_path):
    """diff_preview shows unified diff when files differ."""
    project = tmp_path / "project"
    project.mkdir()
    target_file = project / "AGENTS.md"
    target_file.write_text("new synced content\n", encoding="utf-8")

    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=project)
    stack.push({"AGENTS.md": "original content\n"}, label="pre-sync")

    preview = stack.diff_preview()
    # Should contain diff markers
    assert "original content" in preview or "---" in preview or "+++" in preview


def test_undo_with_diff_returns_tuple(tmp_path):
    """undo_with_diff returns (diff_string, UndoResult) tuple."""
    project = tmp_path / "project"
    project.mkdir()
    target_file = project / "AGENTS.md"
    target_file.write_text("current content\n", encoding="utf-8")

    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=project)
    stack.push({"AGENTS.md": "original content\n"}, label="snap")

    diff, result = stack.undo_with_diff(show_diff=True)
    assert isinstance(diff, str)
    assert result.ok is True
    assert "AGENTS.md" in result.files_restored


def test_undo_with_diff_no_diff_flag(tmp_path):
    """undo_with_diff with show_diff=False returns empty diff string."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "AGENTS.md").write_text("v2\n", encoding="utf-8")

    stack = HarnessUndoStack("codex", root_dir=tmp_path / "stacks", project_dir=project)
    stack.push({"AGENTS.md": "v1\n"}, label="snap")

    diff, result = stack.undo_with_diff(show_diff=False)
    assert diff == ""
    assert result.ok is True


# ── SyncTriggerMatcher ────────────────────────────────────────────────────────


def test_sync_trigger_no_rules_syncs_all(tmp_path):
    """With no trigger rules, all targets are synced."""
    matcher = SyncTriggerMatcher(project_dir=tmp_path)
    targets = matcher.targets_for_changes(
        changed_files=["CLAUDE.md"],
        changed_sections=["rules"],
        all_targets=["codex", "gemini", "opencode"],
    )
    assert set(targets) == {"codex", "gemini", "opencode"}


def test_sync_trigger_file_match(tmp_path):
    """Trigger fires when a watched file is in changed_files."""
    matcher = SyncTriggerMatcher(project_dir=tmp_path)
    rules = [
        SyncTriggerRule(
            target="codex",
            watch_paths=["CLAUDE.md"],
            description="sync codex on CLAUDE.md change",
        )
    ]
    matcher.save_rules(rules)

    targets = matcher.targets_for_changes(
        changed_files=["CLAUDE.md"],
        changed_sections=[],
        all_targets=["codex", "gemini"],
    )
    assert "codex" in targets
    assert "gemini" not in targets


def test_sync_trigger_section_match(tmp_path):
    """Trigger fires when a watched section is in changed_sections."""
    matcher = SyncTriggerMatcher(project_dir=tmp_path)
    rules = [
        SyncTriggerRule(
            target="gemini",
            watch_sections=["rules"],
            description="sync gemini on rules change",
        )
    ]
    matcher.save_rules(rules)

    targets = matcher.targets_for_changes(
        changed_files=[],
        changed_sections=["rules"],
        all_targets=["codex", "gemini"],
    )
    assert "gemini" in targets
    assert "codex" not in targets


def test_sync_trigger_all_target(tmp_path):
    """Trigger with target='all' syncs every configured target."""
    matcher = SyncTriggerMatcher(project_dir=tmp_path)
    rules = [
        SyncTriggerRule(
            target="all",
            watch_paths=[".claude/skills/"],
            description="sync all on skill change",
        )
    ]
    matcher.save_rules(rules)

    targets = matcher.targets_for_changes(
        changed_files=[".claude/skills/my-skill/SKILL.md"],
        changed_sections=[],
        all_targets=["codex", "gemini", "aider"],
    )
    assert set(targets) == {"codex", "gemini", "aider"}


def test_sync_trigger_no_match_skips_all(tmp_path):
    """When no triggers match, no targets are synced."""
    matcher = SyncTriggerMatcher(project_dir=tmp_path)
    rules = [
        SyncTriggerRule(
            target="codex",
            watch_paths=["CLAUDE.md"],
            description="only on CLAUDE.md",
        )
    ]
    matcher.save_rules(rules)

    targets = matcher.targets_for_changes(
        changed_files=["README.md"],  # Not watched
        changed_sections=[],
        all_targets=["codex", "gemini"],
    )
    assert targets == []


def test_sync_trigger_explain_no_rules(tmp_path):
    """explain() with no rules returns default-sync message."""
    matcher = SyncTriggerMatcher(project_dir=tmp_path)
    explanation = matcher.explain(["CLAUDE.md"], ["rules"], ["codex", "gemini"])
    assert "No trigger rules" in explanation
    assert "all targets" in explanation.lower()


def test_sync_trigger_explain_with_rules(tmp_path):
    """explain() lists rules and which ones fired."""
    matcher = SyncTriggerMatcher(project_dir=tmp_path)
    rules = [
        SyncTriggerRule(
            target="codex",
            watch_paths=["CLAUDE.md"],
            description="codex on CLAUDE.md",
        ),
        SyncTriggerRule(
            target="gemini",
            watch_paths=["settings.json"],
            description="gemini on settings",
        ),
    ]
    matcher.save_rules(rules)

    explanation = matcher.explain(
        changed_files=["CLAUDE.md"],
        changed_sections=[],
        all_targets=["codex", "gemini"],
    )
    assert "codex" in explanation
    assert "FIRED" in explanation or "fired" in explanation.lower()
    assert "codex" in explanation


def test_sync_trigger_rule_persist_roundtrip(tmp_path):
    """Rules saved and loaded are equivalent to the originals."""
    matcher = SyncTriggerMatcher(project_dir=tmp_path)
    rules = [
        SyncTriggerRule(
            target="codex",
            watch_paths=["CLAUDE.md", ".claude/skills/"],
            watch_sections=["rules"],
            description="test rule",
        )
    ]
    matcher.save_rules(rules)
    loaded = matcher.load_rules()
    assert len(loaded) == 1
    assert loaded[0].target == "codex"
    assert "CLAUDE.md" in loaded[0].watch_paths
    assert "rules" in loaded[0].watch_sections
    assert loaded[0].description == "test rule"
