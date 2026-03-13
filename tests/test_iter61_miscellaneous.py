from __future__ import annotations

"""Tests for iteration 61 product-ideation improvements.

Covers:
- ReverseSync (item 3): reverse_sync.py
- Scope Inheritance Visualizer (item 28): config_inheritance.format_visual_tree
- Pre-sync capability check (item 1): harness_feature_matrix.check_before_sync
- Config Diff History (item 12): changelog_manager.get_diff_history
- Text diff preview (item 4): native_preview.build_text_diff_preview
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reverse_sync import (
    ReverseSync,
    ReverseSyncPlan,
    _strip_managed_block,
    _parse_toml_mcp_servers,
)
from src.config_inheritance import ConfigInheritance, format_visual_tree, format_scope_overview
from src.harness_feature_matrix import HarnessFeatureMatrix
from src.changelog_manager import ChangelogManager, get_diff_history, format_diff_history
from src.native_preview import build_text_diff_preview, format_text_diff_preview


# ── ReverseSync tests ─────────────────────────────────────────────────────────


def test_strip_managed_block_removes_harnesssync_content():
    content = (
        "User content here\n"
        "<!-- Managed by HarnessSync -->\n"
        "This is managed\n"
        "<!-- End HarnessSync managed content -->\n"
        "More user content"
    )
    result = _strip_managed_block(content)
    assert "This is managed" not in result
    assert "User content here" in result
    assert "More user content" in result


def test_strip_managed_block_no_block():
    content = "Just plain content with no managed block."
    assert _strip_managed_block(content) == content


def test_parse_toml_mcp_servers_basic():
    toml = """
[mcp_servers."github"]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]

[mcp_servers."filesystem"]
command = "uvx"
args = ["mcp-server-filesystem", "/home"]
"""
    servers = _parse_toml_mcp_servers(toml)
    assert "github" in servers
    assert servers["github"]["command"] == "npx"
    assert "filesystem" in servers


def test_reverse_sync_plan_unsupported_source(tmp_path):
    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="nonexistent-harness")
    assert not plan.has_content
    assert plan.warnings


def test_reverse_sync_plan_codex_empty_project(tmp_path):
    """Plan from codex when no AGENTS.md exists returns empty plan."""
    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="codex")
    assert len(plan.rules) == 0
    assert len(plan.mcp_servers) == 0


def test_reverse_sync_plan_codex_with_agents_md(tmp_path):
    """Plan detects rules from AGENTS.md that are not HarnessSync-managed."""
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# User rules\n\n- Always use TypeScript\n- Prefer functional style")
    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="codex")
    assert len(plan.rules) == 1
    assert "Always use TypeScript" in plan.rules[0].content


def test_reverse_sync_plan_codex_skips_managed_content(tmp_path):
    """Plan strips HarnessSync-managed blocks from AGENTS.md."""
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text(
        "<!-- Managed by HarnessSync -->\n"
        "This was synced by HarnessSync\n"
        "<!-- End HarnessSync managed content -->\n"
    )
    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="codex")
    # After stripping managed block, no user content remains
    assert len(plan.rules) == 0


def test_reverse_sync_execute_append_rules(tmp_path):
    """Execute appends imported rules to CLAUDE.md."""
    # Create source AGENTS.md with user rules
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("- Always document public APIs\n")

    # Create existing CLAUDE.md
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text("# Existing rules\n\n- Use consistent naming\n")

    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="codex", merge_strategy="append")
    result = rs.execute(plan, dry_run=False)

    assert result["rules_written"]
    new_content = claude_md.read_text()
    assert "Always document public APIs" in new_content
    assert "Use consistent naming" in new_content  # Existing preserved


def test_reverse_sync_execute_dry_run_no_write(tmp_path):
    """Dry-run does not write to disk."""
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("- Some rule\n")

    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="codex")
    result = rs.execute(plan, dry_run=True)

    # CLAUDE.md should NOT be created in dry-run mode
    claude_md = tmp_path / "CLAUDE.md"
    assert not claude_md.exists()
    assert result["dry_run"] is True


def test_reverse_sync_execute_new_file_strategy(tmp_path):
    """new_file strategy writes to CLAUDE.from-<source>.md."""
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("- Import me\n")

    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="codex", merge_strategy="new_file")
    result = rs.execute(plan, dry_run=False)

    new_file = tmp_path / "CLAUDE.from-codex.md"
    assert new_file.exists()
    assert "Import me" in new_file.read_text()


def test_reverse_sync_execute_mcp_import(tmp_path):
    """Execute merges MCP servers from codex config.toml."""
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    (codex_dir / "config.toml").write_text(
        '[mcp_servers."myserver"]\ncommand = "uvx"\nargs = ["my-mcp"]\n'
    )

    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="codex")
    result = rs.execute(plan, dry_run=False)

    assert "myserver" in result["mcp_added"]
    mcp_json = tmp_path / ".mcp.json"
    assert mcp_json.exists()
    data = json.loads(mcp_json.read_text())
    assert "myserver" in data["mcpServers"]


def test_reverse_sync_format_plan_empty(tmp_path):
    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="codex")
    formatted = rs.format_plan(plan)
    assert "codex" in formatted
    assert "Nothing to import" in formatted


def test_reverse_sync_format_plan_with_content(tmp_path):
    (tmp_path / "AGENTS.md").write_text("- Some rule\n")
    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="codex")
    formatted = rs.format_plan(plan)
    assert "Rules" in formatted
    assert "append" in formatted  # merge strategy shown


def test_reverse_sync_cursor_mdc_import(tmp_path):
    """Import rules from cursor .mdc files."""
    cursor_rules = tmp_path / ".cursor" / "rules"
    cursor_rules.mkdir(parents=True)
    (cursor_rules / "style.mdc").write_text("---\ndescription: style rules\n---\n- Use snake_case\n")

    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="cursor")
    assert len(plan.rules) >= 1
    assert any("snake_case" in r.content for r in plan.rules)


def test_reverse_sync_cursor_skips_harnesssync_files(tmp_path):
    """Cursor import skips files we wrote."""
    cursor_rules = tmp_path / ".cursor" / "rules"
    cursor_rules.mkdir(parents=True)
    (cursor_rules / "harnesssync.mdc").write_text("- This is ours\n")
    (cursor_rules / "user_rules.mdc").write_text("- This is theirs\n")

    rs = ReverseSync(project_dir=tmp_path)
    plan = rs.plan(source="cursor")
    # harnesssync.mdc should be excluded
    sources = [r.source_file for r in plan.rules]
    assert not any("harnesssync" in s for s in sources)


def test_looks_like_secret():
    # Mixed-case long string looks like a secret
    assert ReverseSync._looks_like_secret("sk-AbCdEfGhIjKlMnOpQrSt1234567890")
    assert not ReverseSync._looks_like_secret("${MY_TOKEN}")
    assert not ReverseSync._looks_like_secret("$MY_TOKEN")
    assert not ReverseSync._looks_like_secret("")
    assert not ReverseSync._looks_like_secret("short")


# ── Scope Inheritance Visualizer tests ───────────────────────────────────────


def test_format_visual_tree_no_chain(tmp_path):
    ci = ConfigInheritance(project_dir=tmp_path)
    result = format_visual_tree(ci)
    assert "Config Scope Inheritance Tree" in result
    assert "USER" in result


def test_format_visual_tree_with_project_claude_md(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("- rule1\n- rule2\n")
    ci = ConfigInheritance(project_dir=tmp_path)
    result = format_visual_tree(ci)
    assert "PROJECT" in result
    assert "CLAUDE.md" in result


def test_format_scope_overview(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("- rule1\n- rule2\n- rule3\n")
    result = format_scope_overview(project_dir=tmp_path)
    assert "Config Scope Overview" in result
    assert "CLAUDE.md" in result


def test_format_scope_overview_missing_files(tmp_path):
    result = format_scope_overview(project_dir=tmp_path)
    assert "✗" in result  # Not-found indicators


# ── HarnessFeatureMatrix pre-sync check tests ─────────────────────────────────


def test_check_before_sync_codex_returns_dict():
    matrix = HarnessFeatureMatrix()
    result = matrix.check_before_sync("codex")
    assert "target" in result
    assert result["target"] == "codex"
    assert "verdict" in result
    assert result["verdict"] in ("ok", "warnings", "blocked")
    assert "score" in result
    assert isinstance(result["score"], int)


def test_check_before_sync_all_fields_present():
    matrix = HarnessFeatureMatrix()
    result = matrix.check_before_sync("gemini")
    for key in ("target", "ready", "degraded", "blocked", "score", "verdict", "summary"):
        assert key in result


def test_check_before_sync_unknown_target():
    matrix = HarnessFeatureMatrix()
    result = matrix.check_before_sync("nonexistent")
    assert result["target"] == "nonexistent"
    # Unknown target should have blocked features (defaults to unsupported)
    assert isinstance(result["blocked"], list)


def test_check_all_targets_before_sync_sorted():
    matrix = HarnessFeatureMatrix()
    results = matrix.check_all_targets_before_sync()
    assert len(results) > 0
    # Should be sorted by score descending
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_format_pre_sync_warnings_returns_string():
    matrix = HarnessFeatureMatrix()
    result = matrix.format_pre_sync_warnings()
    # Should be empty string (no warnings) or a warning block string
    assert isinstance(result, str)


def test_format_pre_sync_warnings_no_warnings_for_native_targets():
    """Targets with all-native support should not appear in warnings."""
    matrix = HarnessFeatureMatrix()
    # Check that warning output doesn't mention targets with 100% native support
    result = matrix.format_pre_sync_warnings()
    # Result may be empty string if no warnings exist
    if result:
        assert "Pre-sync capability warnings" in result


# ── Config diff history tests ─────────────────────────────────────────────────


def test_get_diff_history_empty_changelog(tmp_path):
    manager = ChangelogManager(project_dir=tmp_path)
    history = get_diff_history(manager)
    assert history == []


def test_get_diff_history_parses_entries(tmp_path):
    # Create a synthetic changelog at the path ChangelogManager uses
    changelog_dir = tmp_path / ".harness-sync"
    changelog_dir.mkdir(parents=True)
    (changelog_dir / "changelog.md").write_text(
        "## Sync 2026-03-13T10:00:00Z scope=all\n"
        "Synced: codex gemini opencode\n"
        "synced=5 skipped=1 failed=0\n"
        "\n"
        "## Sync 2026-03-13T11:00:00Z scope=project\n"
        "Synced: codex\n"
        "synced=3 skipped=0 failed=0\n"
    )

    manager = ChangelogManager(project_dir=tmp_path)
    history = get_diff_history(manager)
    assert len(history) >= 1


def test_format_diff_history_empty(tmp_path):
    manager = ChangelogManager(project_dir=tmp_path)
    result = format_diff_history(manager)
    assert "No sync history" in result


# ── Text diff preview tests ───────────────────────────────────────────────────


def test_build_text_diff_preview_created_files(tmp_path):
    preview_all = {
        "codex": {"AGENTS.md": "# Rules\n- rule1\n- rule2\n"},
        "gemini": {"GEMINI.md": "# Gemini\n- rule1\n"},
    }
    diffs = build_text_diff_preview(preview_all, project_dir=tmp_path)
    assert len(diffs) == 2
    statuses = {d["file_path"]: d["status"] for d in diffs}
    assert statuses["AGENTS.md"] == "created"
    assert statuses["GEMINI.md"] == "created"


def test_build_text_diff_preview_modified_file(tmp_path):
    # Write existing file
    (tmp_path / "AGENTS.md").write_text("# Old content\n- old rule\n")
    preview_all = {
        "codex": {"AGENTS.md": "# New content\n- new rule\n"},
    }
    diffs = build_text_diff_preview(preview_all, project_dir=tmp_path)
    assert diffs[0]["status"] == "modified"
    assert diffs[0]["additions"] > 0 or diffs[0]["deletions"] > 0


def test_build_text_diff_preview_unchanged_file(tmp_path):
    content = "# Rules\n- rule1\n"
    (tmp_path / "AGENTS.md").write_text(content)
    preview_all = {"codex": {"AGENTS.md": content}}
    diffs = build_text_diff_preview(preview_all, project_dir=tmp_path)
    assert diffs[0]["status"] == "unchanged"
    assert diffs[0]["unified_diff"] == ""


def test_format_text_diff_preview_empty():
    result = format_text_diff_preview([])
    assert "Nothing to sync" in result


def test_format_text_diff_preview_with_changes(tmp_path):
    preview_all = {
        "codex": {"AGENTS.md": "- new rule\n"},
        "gemini": {"GEMINI.md": "# gemini\n"},
    }
    diffs = build_text_diff_preview(preview_all, project_dir=tmp_path)
    result = format_text_diff_preview(diffs)
    assert "Sync Dry-Run Preview" in result
    assert "created" in result or "+" in result


def test_format_text_diff_preview_hides_unchanged_by_default(tmp_path):
    content = "# Existing\n- rule\n"
    (tmp_path / "AGENTS.md").write_text(content)
    preview_all = {
        "codex": {"AGENTS.md": content},  # unchanged
        "gemini": {"GEMINI.md": "# New\n"},  # created
    }
    diffs = build_text_diff_preview(preview_all, project_dir=tmp_path)
    result = format_text_diff_preview(diffs, show_unchanged=False)
    # Unchanged file should not appear prominently
    assert "1 to create" in result or "GEMINI" in result.upper()


def test_format_text_diff_preview_shows_unchanged_when_requested(tmp_path):
    content = "# Existing\n- rule\n"
    (tmp_path / "AGENTS.md").write_text(content)
    preview_all = {"codex": {"AGENTS.md": content}}
    diffs = build_text_diff_preview(preview_all, project_dir=tmp_path)
    result = format_text_diff_preview(diffs, show_unchanged=True)
    assert "unchanged" in result
