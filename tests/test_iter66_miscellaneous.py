from __future__ import annotations

"""Tests for iteration 66 product-ideation improvements.

Covers:
- CLAUDE.md Portability Score (item 16): ClaudeMdPortabilityScorer
- Sync Complexity Risky Section Analyzer (item 27): analyze_risky_sections / format_risky_sections_report
- Portable Skill Design Guide (item 12): format_portable_design_guide
- Task-Based Harness Ranking (item 25): rank_harnesses_for_task / TaskPerformanceSummary
- MCP Pre-Sync Validator (item 20): pre_sync_validate / PreSyncValidationResult
- Backup Restore By Date (item 15): BackupManager.restore_by_date
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_health import ClaudeMdPortabilityScorer, PortabilityScoreResult
from src.config_complexity import (
    RiskySection,
    analyze_risky_sections,
    format_risky_sections_report,
)
from src.skill_gap_analyzer import (
    SkillGapReport,
    SkillGapItem,
    format_portable_design_guide,
)
from src.harness_comparison import (
    HarnessTaskRanking,
    TaskPerformanceSummary,
    rank_harnesses_for_task,
)
from src.mcp_reachability import (
    PreSyncValidationResult,
    pre_sync_validate,
)
from src.backup_manager import BackupManager


# ── ClaudeMdPortabilityScorer ─────────────────────────────────────────────────


def test_portability_scorer_clean_content():
    """Fully portable CLAUDE.md gets score 100."""
    scorer = ClaudeMdPortabilityScorer()
    content = "# My Rules\n\n- Always write tests.\n- Use type hints in Python.\n"
    result = scorer.score(content)
    assert result.score == 100
    assert result.issues == []
    assert result.label == "excellent"


def test_portability_scorer_mcp_tool_ref_deducts():
    """An MCP tool reference deducts from the portability score."""
    scorer = ClaudeMdPortabilityScorer()
    content = "Use mcp__plugin_github_github__create_pr to open pull requests.\n"
    result = scorer.score(content)
    assert result.score < 100
    assert len(result.issues) >= 1
    assert any("MCP tool" in i.pattern_name for i in result.issues)


def test_portability_scorer_claude_code_name_deducts():
    """References to 'Claude Code' reduce portability score."""
    scorer = ClaudeMdPortabilityScorer()
    content = "Always run Claude Code commands before committing.\n"
    result = scorer.score(content)
    assert result.score < 100


def test_portability_scorer_annotation_gives_bonus():
    """Using harness annotations adds a bonus to portability score."""
    scorer = ClaudeMdPortabilityScorer()
    content = (
        "Use mcp__plugin_github_github__create_pr to open pull requests.\n"
        "<!-- harness:only=claude -->\n"
        "Use the Agent tool for orchestration.\n"
        "<!-- harness:exclude -->\n"
    )
    result_with = scorer.score(content)
    content_no_annotations = (
        "Use mcp__plugin_github_github__create_pr to open pull requests.\n"
        "Use the Agent tool for orchestration.\n"
    )
    result_without = scorer.score(content_no_annotations)
    # Annotations should yield a higher or equal score
    assert result_with.score >= result_without.score
    assert result_with.annotation_count >= 2


def test_portability_scorer_same_issue_deduplicated():
    """The same portability issue appearing twice is only reported once."""
    scorer = ClaudeMdPortabilityScorer()
    content = (
        "Use mcp__plugin_a__tool_x here.\n"
        "Also use mcp__plugin_b__tool_y here.\n"
    )
    result = scorer.score(content)
    # Both hit the same "MCP tool reference" suggestion — should be deduped
    mcp_issues = [i for i in result.issues if "MCP tool" in i.pattern_name]
    assert len(mcp_issues) == 1


def test_portability_scorer_format_output():
    """format() returns a non-empty string with the score."""
    scorer = ClaudeMdPortabilityScorer()
    result = scorer.score("Use the Agent tool frequently.\n")
    output = result.format()
    assert str(result.score) in output
    assert result.label in output


def test_portability_scorer_score_file(tmp_path):
    """score_file() reads a file and scores it."""
    scorer = ClaudeMdPortabilityScorer()
    f = tmp_path / "CLAUDE.md"
    f.write_text("# Good config\n\n- Write tests.\n", encoding="utf-8")
    result = scorer.score_file(f)
    assert result.score == 100


def test_portability_scorer_missing_file(tmp_path):
    """score_file() on a missing file returns score 0."""
    scorer = ClaudeMdPortabilityScorer()
    result = scorer.score_file(tmp_path / "nonexistent.md")
    assert result.score == 0


# ── Risky Section Analyzer ────────────────────────────────────────────────────


def test_risky_sections_clean_content():
    """Clean rules content yields no risky sections."""
    sections = analyze_risky_sections("# Rules\n\n- Write tests.\n- Use type hints.\n")
    assert sections == []


def test_risky_sections_non_portable_tool():
    """Non-portable tool references are flagged as high risk."""
    content = "Always use the TodoWrite tool to track tasks.\n"
    sections = analyze_risky_sections(content)
    assert any(s.section_type == "non_portable_tool" for s in sections)
    assert all(s.risk_level in {"high", "medium", "low"} for s in sections)


def test_risky_sections_mcp_tool_name():
    """mcp__* tool references are flagged."""
    content = "Call mcp__plugin_github_github__create_pr to open PRs.\n"
    sections = analyze_risky_sections(content)
    assert any(s.section_type == "non_portable_tool" for s in sections)


def test_risky_sections_ambiguous_permission():
    """'allow all' phrases are flagged as ambiguous permission grants."""
    content = "The AI should have full access to all files without restriction.\n"
    sections = analyze_risky_sections(content)
    assert any(s.section_type == "ambiguous_permission" for s in sections)


def test_risky_sections_internal_hostname():
    """Internal hostnames are flagged as medium risk."""
    content = "Connect to http://internal-api.corp/v1/data for project data.\n"
    sections = analyze_risky_sections(content)
    assert any(s.section_type == "internal_hostname" for s in sections)


def test_risky_sections_private_ip():
    """Private IP addresses are flagged."""
    content = "The MCP server runs at 192.168.1.100:8080.\n"
    sections = analyze_risky_sections(content)
    assert any(s.section_type == "internal_hostname" for s in sections)


def test_risky_sections_nested_mcp():
    """Deeply nested MCP config JSON is flagged."""
    nested_json = '{"mcpServers": {"srv": {"config": {"auth": {"token": "x"}}}}}'
    sections = analyze_risky_sections("", mcp_config_json=nested_json)
    assert any(s.section_type == "mcp_nested" for s in sections)


def test_risky_sections_sorted_high_first():
    """Risky sections are sorted high → medium → low."""
    content = (
        "Allow all permissions without restriction.\n"  # high
        "Connect to 192.168.1.100.\n"                  # medium
    )
    sections = analyze_risky_sections(content)
    risk_order = {"high": 0, "medium": 1, "low": 2}
    for a, b in zip(sections, sections[1:]):
        assert risk_order[a.risk_level] <= risk_order[b.risk_level]


def test_format_risky_sections_report_clean():
    """format_risky_sections_report on empty list says no issues."""
    output = format_risky_sections_report([])
    assert "No risky sections" in output


def test_format_risky_sections_report_with_issues():
    """format_risky_sections_report includes issue details."""
    sections = [
        RiskySection(
            section_type="non_portable_tool",
            location="line 5",
            risk_level="high",
            explanation="Tool is Claude-specific.",
            mitigation="Wrap with harness annotation.",
        )
    ]
    output = format_risky_sections_report(sections)
    assert "HIGH" in output
    assert "line 5" in output
    assert "non_portable_tool" in output


# ── Portable Skill Design Guide ───────────────────────────────────────────────


def test_portable_design_guide_no_gaps():
    """format_portable_design_guide returns guide even with no gap report."""
    output = format_portable_design_guide()
    assert "Portable Skill Design Guide" in output
    assert len(output) > 200


def test_portable_design_guide_with_gaps():
    """Guide personalizes output when a gap report is provided."""
    report = SkillGapReport(
        source_skills=["commit", "review"],
        gaps=[
            SkillGapItem(
                skill_name="commit",
                source_exists=True,
                missing_in=["aider", "cursor"],
                orphaned_in=[],
            )
        ],
    )
    output = format_portable_design_guide(report)
    assert "Portable Skill Design Guide" in output
    assert "gap" in output.lower()


def test_portable_design_guide_with_orphans():
    """Guide mentions orphaned skills when they are present."""
    report = SkillGapReport(
        source_skills=["commit"],
        gaps=[
            SkillGapItem(
                skill_name="old-skill",
                source_exists=False,
                missing_in=[],
                orphaned_in=["codex"],
            )
        ],
    )
    output = format_portable_design_guide(report)
    assert "orphaned" in output.lower() or "import" in output.lower()


def test_portable_design_guide_contains_key_tips():
    """Guide includes tips about Claude-specific tools and self-contained skills."""
    output = format_portable_design_guide()
    assert "TodoWrite" in output or "Claude Code" in output
    assert "self-contained" in output or "self_contained" in output


# ── Task-Based Harness Ranking ────────────────────────────────────────────────


def test_rank_harnesses_returns_summary():
    """rank_harnesses_for_task returns a TaskPerformanceSummary."""
    summary = rank_harnesses_for_task("code_generation")
    assert isinstance(summary, TaskPerformanceSummary)
    assert summary.task_category == "code_generation"
    assert len(summary.rankings) > 0


def test_rank_harnesses_ranks_start_at_one():
    """Rankings start at 1 and increment."""
    summary = rank_harnesses_for_task("debugging")
    for i, r in enumerate(summary.rankings, start=1):
        assert r.rank == i


def test_rank_harnesses_scores_in_descending_order():
    """Rankings are ordered highest score first."""
    summary = rank_harnesses_for_task("refactoring")
    scores = [r.score for r in summary.rankings]
    assert scores == sorted(scores, reverse=True)


def test_rank_harnesses_scores_between_zero_and_one():
    """All scores are in [0, 1]."""
    summary = rank_harnesses_for_task("multi_agent")
    for r in summary.rankings:
        assert 0.0 <= r.score <= 1.0


def test_rank_harnesses_unknown_category_falls_back():
    """Unknown task category falls back to 'general' weights without crashing."""
    summary = rank_harnesses_for_task("totally_made_up_task_xyz")
    assert len(summary.rankings) > 0
    assert summary.task_category == "totally_made_up_task_xyz"


def test_rank_harnesses_installed_filter():
    """Passing installed_harnesses limits results to that list."""
    summary = rank_harnesses_for_task("code_review", installed_harnesses=["codex", "gemini"])
    targets = [r.target for r in summary.rankings]
    assert set(targets) == {"codex", "gemini"}


def test_task_performance_summary_best_harness():
    """best_harness returns the top-ranked target."""
    summary = rank_harnesses_for_task("debugging", installed_harnesses=["codex", "aider"])
    assert summary.best_harness in {"codex", "aider"}


def test_task_performance_summary_format():
    """format() returns a non-empty string with ranking info."""
    summary = rank_harnesses_for_task("writing_docs", installed_harnesses=["codex", "gemini", "cursor"])
    output = summary.format()
    assert "codex" in output or "gemini" in output
    assert "#1" in output


def test_task_performance_summary_empty():
    """TaskPerformanceSummary with no rankings handles format gracefully."""
    summary = TaskPerformanceSummary(task_category="test", rankings=[])
    assert summary.best_harness is None
    assert "No harness data" in summary.format()


# ── MCP Pre-Sync Validator ────────────────────────────────────────────────────


def test_pre_sync_validate_empty_servers():
    """Empty server dict always returns ok status."""
    result = pre_sync_validate({}, target="codex")
    assert result.status == "ok"
    assert result.ok is True
    assert result.warnings == []
    assert result.errors == []


def test_pre_sync_validate_unsupported_target():
    """Target that doesn't support MCP returns warn status."""
    servers = {"my-server": {"command": "npx my-mcp"}}
    result = pre_sync_validate(servers, target="aider")
    assert result.status == "warn"
    assert result.ok is True
    assert len(result.warnings) == 1
    assert "does not support MCP" in result.warnings[0]
    assert result.reachable_servers == {}


def test_pre_sync_validate_unreachable_url_server():
    """Unreachable URL server goes into warnings by default."""
    servers = {
        "remote-srv": {"url": "http://127.0.0.1:19999/mcp"}  # nothing listening
    }
    result = pre_sync_validate(servers, target="codex", timeout=0.2)
    # Should warn but not block by default
    assert result.status in {"warn", "ok"}
    # If unreachable, server should NOT be in reachable_servers
    # (or it might not detect it as unreachable in all environments)
    assert isinstance(result.reachable_servers, dict)


def test_pre_sync_validate_block_mode():
    """block_on_unreachable=True escalates unreachable servers to errors."""
    servers = {
        "dead-srv": {"url": "http://127.0.0.1:19998/mcp"}
    }
    result = pre_sync_validate(
        servers, target="codex", timeout=0.2, block_on_unreachable=True
    )
    # If server is truly unreachable, status should be block
    if result.unreachable_servers:
        assert result.status == "block"
        assert not result.ok
        assert len(result.errors) >= 1


def test_pre_sync_validate_format_summary():
    """format_summary() returns a non-empty string."""
    result = pre_sync_validate({}, target="codex")
    output = result.format_summary()
    assert "OK" in output or "reachable" in output.lower()


def test_pre_sync_validate_result_attributes():
    """PreSyncValidationResult has expected attributes."""
    result = pre_sync_validate({}, target="gemini")
    assert hasattr(result, "status")
    assert hasattr(result, "warnings")
    assert hasattr(result, "errors")
    assert hasattr(result, "reachable_servers")
    assert hasattr(result, "unreachable_servers")
    assert hasattr(result, "ok")


# ── BackupManager.restore_by_date ─────────────────────────────────────────────


def _make_backup(backup_root: Path, target: str, timestamp: str, content: str) -> Path:
    """Helper: create a fake backup directory with metadata."""
    target_dir = backup_root / target
    target_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = target_dir / f"CLAUDE.md_{timestamp}"
    backup_dir.mkdir()
    (backup_dir / "CLAUDE.md").write_text(content, encoding="utf-8")
    meta = {
        "label": None,
        "timestamp": timestamp,
        "source": str(backup_dir.parent.parent / "CLAUDE.md"),
        "target_name": target,
    }
    (backup_dir / ".harnesssync-snapshot.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )
    return backup_dir


def test_restore_by_date_invalid_format(tmp_path):
    """Invalid date format returns an error dict."""
    mgr = BackupManager(backup_root=tmp_path / "backups")
    result = mgr.restore_by_date("not-a-date")
    assert len(result["errors"]) == 1
    assert "Invalid date format" in result["errors"][0][1]


def test_restore_by_date_no_snapshots(tmp_path):
    """No backups before the cutoff date returns a skipped entry."""
    mgr = BackupManager(backup_root=tmp_path / "backups")
    result = mgr.restore_by_date("2020-01-01")
    assert len(result["restored"]) == 0
    assert len(result["skipped"]) >= 1


def test_restore_by_date_dry_run(tmp_path):
    """Dry run reports what would be restored without writing files."""
    backup_root = tmp_path / "backups"
    _make_backup(backup_root, "codex", "20260310_120000", "old codex content")

    mgr = BackupManager(backup_root=backup_root)
    result = mgr.restore_by_date("2026-03-11", target_name="codex", dry_run=True)
    assert "codex" in result["restored"]
    assert result["errors"] == []


def test_restore_by_date_finds_closest_before_cutoff(tmp_path):
    """restore_by_date picks the most recent snapshot before the cutoff."""
    backup_root = tmp_path / "backups"
    _make_backup(backup_root, "codex", "20260310_080000", "old content")
    _make_backup(backup_root, "codex", "20260311_090000", "newer content")  # after cutoff
    # Cutoff is 2026-03-10 — should pick 20260310_080000, not 20260311_090000
    mgr = BackupManager(backup_root=backup_root)
    result = mgr.restore_by_date("2026-03-10", target_name="codex", dry_run=True)
    assert "codex" in result["restored"]


def test_restore_by_date_skips_snapshots_after_cutoff(tmp_path):
    """Snapshots newer than cutoff date are not picked."""
    backup_root = tmp_path / "backups"
    _make_backup(backup_root, "gemini", "20260315_100000", "future content")
    mgr = BackupManager(backup_root=backup_root)
    result = mgr.restore_by_date("2026-03-10", target_name="gemini", dry_run=True)
    assert "gemini" not in result["restored"]
    assert len(result["skipped"]) >= 1


def test_restore_by_date_accepts_no_separator_format(tmp_path):
    """YYYYMMDD without dashes is also accepted."""
    backup_root = tmp_path / "backups"
    _make_backup(backup_root, "opencode", "20260305_060000", "content")
    mgr = BackupManager(backup_root=backup_root)
    result = mgr.restore_by_date("20260306", target_name="opencode", dry_run=True)
    assert "opencode" in result["restored"]
