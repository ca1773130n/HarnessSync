from __future__ import annotations

"""Tests for newly added modules that lack test coverage.

Covers:
- src/commands/sync_coverage.py — coverage matrix and source section parsing
- src/commands/sync_score.py — portability score computation and grading
- src/commands/sync_resolve.py — hunk extraction from diffs
- src/analysis/skill_linter.py — Claude Code-specific pattern detection
- src/override_manager.py — loading overrides from both directory paths
- src/notifiers/desktop.py — notify() doesn't crash (mocked subprocess)
- src/utils/harness_validator.py — validation logic
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ============================================================================
# sync_coverage — coverage matrix
# ============================================================================

from src.commands.sync_coverage import _CAPABILITIES, _source_sections, _SYMBOLS


class TestSyncCoverage:
    def test_capabilities_contains_known_harnesses(self):
        """All 11 harnesses should be present in the capability map."""
        expected = {"codex", "gemini", "opencode", "cursor", "aider",
                    "windsurf", "cline", "continue", "zed", "neovim", "vscode"}
        assert expected == set(_CAPABILITIES.keys())

    def test_source_sections_extracts_counts(self):
        """_source_sections should count items from dicts and lists."""
        data = {
            "rules": ["rule1", "rule2"],
            "skills": {"s1": "/path1", "s2": "/path2", "s3": "/path3"},
            "mcp": {"server1": {}},
            "settings": {"env": {"A": "1"}, "permissions": {"allow": ["read", "write"]}},
        }
        sections = _source_sections(data)
        assert sections["rules"] == 2
        assert sections["skills"] == 3
        assert sections["mcp"] == 1
        assert sections["env"] == 1
        assert sections["permissions"] == 2

    def test_source_sections_empty_data(self):
        """Empty source data should return empty sections."""
        assert _source_sections({}) == {}

    def test_symbols_mapping(self):
        """All three coverage levels should have symbols."""
        assert set(_SYMBOLS.keys()) == {"full", "partial", "none"}


# ============================================================================
# sync_score — portability scoring
# ============================================================================

from src.commands.sync_score import (
    _compute_total,
    _score_path_hygiene,
    _score_settings_coverage,
)


class TestSyncScore:
    def test_compute_total_perfect_scores(self):
        """All 100s should give a total of 100."""
        sub = {
            "skill_portability": 100,
            "mcp_breadth": 100,
            "path_hygiene": 100,
            "settings_coverage": 100,
        }
        assert _compute_total(sub) == 100

    def test_compute_total_zero_scores(self):
        """All 0s should give a total of 0."""
        sub = {
            "skill_portability": 0,
            "mcp_breadth": 0,
            "path_hygiene": 0,
            "settings_coverage": 0,
        }
        assert _compute_total(sub) == 0

    def test_compute_total_in_range(self):
        """Mixed scores should produce a result between 0 and 100."""
        sub = {
            "skill_portability": 80,
            "mcp_breadth": 60,
            "path_hygiene": 90,
            "settings_coverage": 70,
        }
        total = _compute_total(sub)
        assert 0 <= total <= 100

    def test_path_hygiene_clean(self):
        """No absolute paths should score 100."""
        score, fixes = _score_path_hygiene({"rules": "use relative paths"}, Path("/tmp"))
        assert score == 100
        assert fixes == []

    def test_path_hygiene_with_absolute_paths(self):
        """Absolute paths should reduce score and suggest fixes."""
        rules = "Look at /Users/neo/config.json and /home/user/file.txt"
        score, fixes = _score_path_hygiene({"rules": rules}, Path("/tmp"))
        assert score < 100
        assert len(fixes) > 0

    def test_settings_coverage_all_known(self):
        """Settings with only known keys should score 100."""
        score, fixes = _score_settings_coverage({"settings": {"model": "claude-3", "env": {}}})
        assert score == 100
        assert fixes == []

    def test_settings_coverage_unknown_keys(self):
        """Unknown settings keys should reduce score."""
        score, fixes = _score_settings_coverage({
            "settings": {"model": "claude-3", "unknownKey": "val", "anotherUnknown": "val2"}
        })
        assert score < 100
        assert len(fixes) > 0


# ============================================================================
# sync_resolve — hunk extraction
# ============================================================================

from src.commands.sync_resolve import _make_hunks


class TestSyncResolve:
    def test_identical_content_produces_no_hunks(self):
        """Identical lines should produce no hunks."""
        lines = ["line1\n", "line2\n", "line3\n"]
        hunks = _make_hunks(lines, lines)
        assert hunks == []

    def test_single_change_produces_one_hunk(self):
        """A single line change should produce one hunk."""
        theirs = ["line1\n", "line2\n", "line3\n"]
        mine = ["line1\n", "CHANGED\n", "line3\n"]
        hunks = _make_hunks(theirs, mine)
        assert len(hunks) == 1
        assert hunks[0]["index"] == 1
        assert any("- line2" in l for l in hunks[0]["lines"])
        assert any("+ CHANGED" in l for l in hunks[0]["lines"])

    def test_hunk_structure(self):
        """Each hunk should have the expected keys."""
        theirs = ["a\n", "b\n"]
        mine = ["a\n", "c\n"]
        hunks = _make_hunks(theirs, mine)
        assert len(hunks) >= 1
        hunk = hunks[0]
        assert "index" in hunk
        assert "header" in hunk
        assert "lines" in hunk
        assert "theirs_block" in hunk
        assert "mine_block" in hunk

    def test_insertion_detected(self):
        """Inserting a new line should appear as a hunk."""
        theirs = ["a\n", "b\n"]
        mine = ["a\n", "new\n", "b\n"]
        hunks = _make_hunks(theirs, mine)
        assert len(hunks) >= 1
        all_lines = " ".join(l for h in hunks for l in h["lines"])
        assert "new" in all_lines


# ============================================================================
# analysis/skill_linter — Claude Code pattern detection
# ============================================================================

from src.analysis.skill_linter import SkillLinter, SkillReport, SkillIssue


class TestSkillLinter:
    def test_clean_file_no_issues(self, tmp_path):
        """A skill with no CC-specific patterns should be clean."""
        md = tmp_path / "clean.md"
        md.write_text("# My Skill\n\nDoes useful portable things.\n")
        linter = SkillLinter()
        report = linter.lint_file(md)
        assert report.is_clean
        assert report.issue_count == 0

    def test_mcp_tool_call_detected(self, tmp_path):
        """mcp__server__tool patterns should be flagged."""
        md = tmp_path / "mcp_skill.md"
        md.write_text("Call mcp__github__create_pr to make a PR.\n")
        linter = SkillLinter()
        report = linter.lint_file(md)
        assert not report.is_clean
        assert any(i.code == "MCP_TOOL_CALL" for i in report.issues)

    def test_cc_tool_name_detected(self, tmp_path):
        """Claude Code internal tool names like Read, Edit should be flagged."""
        md = tmp_path / "tool_skill.md"
        md.write_text("Use the Read tool to view files.\n")
        linter = SkillLinter()
        report = linter.lint_file(md)
        assert any(i.code == "CC_TOOL_NAME" for i in report.issues)

    def test_lint_all_filters_clean(self, tmp_path):
        """lint_all should only return skills with issues."""
        clean = tmp_path / "clean.md"
        clean.write_text("Portable content\n")
        dirty = tmp_path / "dirty.md"
        dirty.write_text("Use mcp__server__tool here\n")

        linter = SkillLinter()
        results = linter.lint_all({"clean": clean, "dirty": dirty})
        assert "clean" not in results
        assert "dirty" in results

    def test_missing_file_reported(self, tmp_path):
        """A missing skill file should produce a MISSING_FILE issue."""
        linter = SkillLinter()
        report = linter.lint_file(tmp_path / "nonexistent.md")
        assert any(i.code == "MISSING_FILE" for i in report.issues)


# ============================================================================
# override_manager — per-harness overrides
# ============================================================================

from src.override_manager import OverrideManager


class TestOverrideManager:
    def test_no_overrides_returns_empty(self, tmp_path):
        """No override dirs should return empty dict."""
        om = OverrideManager(tmp_path)
        result = om.load_overrides("cursor")
        assert result == {}

    def test_load_md_override_from_primary(self, tmp_path):
        """Markdown override in .harness-sync/overrides/ should be loaded."""
        od = tmp_path / ".harness-sync" / "overrides"
        od.mkdir(parents=True)
        (od / "cursor.md").write_text("# Cursor-specific rules\n")
        om = OverrideManager(tmp_path)
        result = om.load_overrides("cursor")
        assert "md" in result
        assert "Cursor-specific" in result["md"]

    def test_load_md_override_from_claude_dir(self, tmp_path):
        """Markdown override in .claude/overrides/ should be loaded as fallback."""
        od = tmp_path / ".claude" / "overrides"
        od.mkdir(parents=True)
        (od / "gemini.md").write_text("# Gemini extras\n")
        om = OverrideManager(tmp_path)
        result = om.load_overrides("gemini")
        assert "md" in result
        assert "Gemini extras" in result["md"]

    def test_primary_takes_precedence(self, tmp_path):
        """Primary override dir should win over .claude/overrides/."""
        for d in (".harness-sync/overrides", ".claude/overrides"):
            od = tmp_path / d
            od.mkdir(parents=True)

        (tmp_path / ".harness-sync" / "overrides" / "codex.md").write_text("primary")
        (tmp_path / ".claude" / "overrides" / "codex.md").write_text("fallback")

        om = OverrideManager(tmp_path)
        result = om.load_overrides("codex")
        assert result["md"] == "primary"

    def test_merge_overrides_md(self, tmp_path):
        """merge_overrides with md type should append override text."""
        od = tmp_path / ".harness-sync" / "overrides"
        od.mkdir(parents=True)
        (od / "cursor.md").write_text("Extra rules\n")

        om = OverrideManager(tmp_path)
        merged = om.merge_overrides("cursor", "Base rules\n", "md")
        assert "Base rules" in merged
        assert "Extra rules" in merged

    def test_merge_overrides_json(self, tmp_path):
        """merge_overrides with json type should deep-merge dicts."""
        od = tmp_path / ".harness-sync" / "overrides"
        od.mkdir(parents=True)
        (od / "cursor.json").write_text(json.dumps({"extra_key": "val"}))

        om = OverrideManager(tmp_path)
        merged = om.merge_overrides("cursor", {"base_key": "original"}, "json")
        assert merged["base_key"] == "original"
        assert merged["extra_key"] == "val"

    def test_has_overrides(self, tmp_path):
        """has_overrides should detect when files exist."""
        od = tmp_path / ".harness-sync" / "overrides"
        od.mkdir(parents=True)
        (od / "zed.md").write_text("zed rules")

        om = OverrideManager(tmp_path)
        assert om.has_overrides("zed") is True
        assert om.has_overrides("nonexistent") is False


# ============================================================================
# notifiers/desktop — notify() doesn't crash
# ============================================================================

from src.notifiers.desktop import notify


class TestDesktopNotify:
    @patch("src.notifiers.desktop.subprocess.run")
    def test_notify_calls_subprocess_on_darwin(self, mock_run):
        """notify() should call osascript on macOS."""
        with patch("src.notifiers.desktop.sys") as mock_sys:
            mock_sys.platform = "darwin"
            notify("Test message", "Test Title")
            mock_run.assert_called_once()
            args = mock_run.call_args
            assert args[0][0][0] == "osascript"

    @patch("src.notifiers.desktop.subprocess.run")
    @patch("src.notifiers.desktop.sys")
    def test_notify_calls_notify_send_on_linux(self, mock_sys, mock_run):
        """notify() should call notify-send on Linux."""
        # Use a MagicMock for platform so startswith works
        platform_mock = MagicMock()
        platform_mock.__eq__ = lambda self, other: other == "linux"
        platform_mock.startswith = lambda x: x == "linux"
        mock_sys.platform = platform_mock
        notify("Test message")
        mock_run.assert_called_once()
        args = mock_run.call_args
        assert args[0][0][0] == "notify-send"

    @patch("src.notifiers.desktop.subprocess.run", side_effect=OSError("no binary"))
    @patch("src.notifiers.desktop.sys")
    def test_notify_swallows_errors(self, mock_sys, mock_run):
        """notify() should never raise, even if subprocess fails."""
        platform_mock = MagicMock()
        platform_mock.__eq__ = lambda self, other: other == "darwin"
        mock_sys.platform = platform_mock
        # Should not raise
        notify("Test message")

    @patch("src.notifiers.desktop.subprocess.run")
    @patch("src.notifiers.desktop.sys")
    def test_notify_noop_on_windows(self, mock_sys, mock_run):
        """notify() should be a no-op on Windows."""
        platform_mock = MagicMock()
        platform_mock.__eq__ = lambda self, other: other == "win32"
        platform_mock.startswith = lambda x: False
        mock_sys.platform = platform_mock
        notify("Test message")
        mock_run.assert_not_called()


# ============================================================================
# utils/harness_validator — validation logic
# ============================================================================

from src.utils.harness_validator import HarnessValidator


class TestHarnessValidator:
    def test_unknown_harness_returns_success(self):
        """Unknown harness (no probe defined) should return success=True."""
        v = HarnessValidator()
        result = v.validate("unknown_harness", Path("/tmp"))
        assert result["success"] is True
        assert "No probe defined" in result["message"]

    def test_missing_binary(self, tmp_path):
        """Missing binary should report binary_found=False."""
        v = HarnessValidator()
        with patch("src.utils.harness_validator.shutil.which", return_value=None):
            result = v.validate("codex", tmp_path)
        assert result["binary_found"] is False
        assert result["success"] is False
        assert len(result["errors"]) > 0

    def test_binary_found_config_present(self, tmp_path):
        """Binary found + config present should give success=True."""
        # Create the config indicator
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text("# Agents")

        v = HarnessValidator()
        mock_proc = MagicMock()
        mock_proc.stdout = "codex v1.0.0\n"
        mock_proc.stderr = ""
        mock_proc.returncode = 0

        with patch("src.utils.harness_validator.shutil.which", return_value="/usr/bin/codex"):
            with patch("src.utils.harness_validator.subprocess.run", return_value=mock_proc):
                result = v.validate("codex", tmp_path)
        assert result["binary_found"] is True
        assert result["config_present"] is True
        assert result["success"] is True
        assert result["version"] is not None

    def test_binary_found_config_missing(self, tmp_path):
        """Binary found but no config indicator should report config_present=False."""
        v = HarnessValidator()
        mock_proc = MagicMock()
        mock_proc.stdout = "codex v1.0.0\n"
        mock_proc.stderr = ""
        mock_proc.returncode = 0

        with patch("src.utils.harness_validator.shutil.which", return_value="/usr/bin/codex"):
            with patch("src.utils.harness_validator.subprocess.run", return_value=mock_proc):
                result = v.validate("codex", tmp_path)
        assert result["binary_found"] is True
        assert result["config_present"] is False
        assert result["success"] is False
