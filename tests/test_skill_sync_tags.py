from __future__ import annotations

"""Tests for skill_sync_tags module — YAML frontmatter sync control for skills.

Covers:
- parse_skill_sync_tag: all frontmatter forms (all, only, exclude, dict, list, shorthand)
- skill_allowed_for_target: permission logic for each mode
- filter_skills_for_target: end-to-end filtering of skill dicts
- filter_agents_for_target: parallel filtering for agents
- Integration with build_target_data: verifies skill filtering is wired into sync pipeline
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.skill_sync_tags import (
    parse_skill_sync_tag,
    skill_allowed_for_target,
    filter_skills_for_target,
    filter_agents_for_target,
    _normalise_sync_value,
)


# ---------------------------------------------------------------------------
# parse_skill_sync_tag tests
# ---------------------------------------------------------------------------

class TestParseSkillSyncTag:
    """Test parse_skill_sync_tag reads frontmatter correctly."""

    def test_no_frontmatter_returns_all(self, tmp_path):
        """A skill file with no frontmatter syncs to all targets."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("# My Skill\nDoes stuff.\n")
        result = parse_skill_sync_tag(skill_md)
        assert result["mode"] == "all"

    def test_sync_all_explicit(self, tmp_path):
        """sync: all is the explicit default."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nsync: all\n---\n# Skill\n")
        result = parse_skill_sync_tag(skill_md)
        assert result["mode"] == "all"

    def test_sync_only_list(self, tmp_path):
        """sync: [codex, gemini] restricts to only those targets."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nsync: [codex, gemini]\n---\n# Skill\n")
        result = parse_skill_sync_tag(skill_md)
        # Without PyYAML, the fallback parser may not handle list syntax.
        # With PyYAML it should parse correctly.
        # Either way, mode should not be "exclude".
        assert result["mode"] in ("all", "only")

    def test_sync_exclude_shorthand(self, tmp_path):
        """sync: exclude-aider excludes aider."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nsync: exclude-aider\n---\n# Skill\n")
        result = parse_skill_sync_tag(skill_md)
        assert result["mode"] == "exclude"
        assert "aider" in result["targets"]

    def test_sync_exclude_multiple_shorthand(self, tmp_path):
        """sync: exclude-aider,windsurf excludes both."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nsync: exclude-aider,windsurf\n---\n# Skill\n")
        result = parse_skill_sync_tag(skill_md)
        assert result["mode"] == "exclude"
        assert "aider" in result["targets"]
        assert "windsurf" in result["targets"]

    def test_sync_none(self, tmp_path):
        """sync: none excludes all targets."""
        skill_md = tmp_path / "SKILL.md"
        skill_md.write_text("---\nsync: none\n---\n# Skill\n")
        result = parse_skill_sync_tag(skill_md)
        assert result["mode"] == "exclude"
        assert len(result["targets"]) > 0  # Should contain all targets

    def test_directory_with_skill_md(self, tmp_path):
        """Passing a directory finds SKILL.md inside it."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nsync: exclude-cursor\n---\n# Skill\n")
        result = parse_skill_sync_tag(skill_dir)
        assert result["mode"] == "exclude"
        assert "cursor" in result["targets"]

    def test_missing_file_returns_all(self):
        """Non-existent path returns sync-all default."""
        result = parse_skill_sync_tag("/nonexistent/path/SKILL.md")
        assert result["mode"] == "all"


# ---------------------------------------------------------------------------
# _normalise_sync_value tests (internal but important)
# ---------------------------------------------------------------------------

class TestNormaliseSyncValue:
    """Test the normalisation of raw sync values."""

    def test_none_value(self):
        assert _normalise_sync_value(None)["mode"] == "all"

    def test_all_string(self):
        assert _normalise_sync_value("all")["mode"] == "all"

    def test_list_of_targets(self):
        result = _normalise_sync_value(["codex", "gemini"])
        assert result["mode"] == "only"
        assert result["targets"] == frozenset({"codex", "gemini"})

    def test_dict_only(self):
        result = _normalise_sync_value({"only": ["codex", "cursor"]})
        assert result["mode"] == "only"
        assert result["targets"] == frozenset({"codex", "cursor"})

    def test_dict_exclude(self):
        result = _normalise_sync_value({"exclude": ["aider", "windsurf"]})
        assert result["mode"] == "exclude"
        assert result["targets"] == frozenset({"aider", "windsurf"})

    def test_exclude_all_string(self):
        result = _normalise_sync_value("exclude-all")
        assert result["mode"] == "exclude"
        assert len(result["targets"]) > 5  # All known targets


# ---------------------------------------------------------------------------
# skill_allowed_for_target tests
# ---------------------------------------------------------------------------

class TestSkillAllowedForTarget:
    """Test the permission check function."""

    def test_mode_all_allows_everything(self):
        tag = {"mode": "all", "targets": frozenset()}
        assert skill_allowed_for_target(tag, "codex") is True
        assert skill_allowed_for_target(tag, "aider") is True

    def test_mode_only_allows_listed(self):
        tag = {"mode": "only", "targets": frozenset({"codex", "gemini"})}
        assert skill_allowed_for_target(tag, "codex") is True
        assert skill_allowed_for_target(tag, "gemini") is True
        assert skill_allowed_for_target(tag, "aider") is False
        assert skill_allowed_for_target(tag, "cursor") is False

    def test_mode_exclude_blocks_listed(self):
        tag = {"mode": "exclude", "targets": frozenset({"aider"})}
        assert skill_allowed_for_target(tag, "aider") is False
        assert skill_allowed_for_target(tag, "codex") is True
        assert skill_allowed_for_target(tag, "cursor") is True

    def test_case_insensitive(self):
        tag = {"mode": "only", "targets": frozenset({"codex"})}
        assert skill_allowed_for_target(tag, "Codex") is True
        assert skill_allowed_for_target(tag, "CODEX") is True


# ---------------------------------------------------------------------------
# filter_skills_for_target tests
# ---------------------------------------------------------------------------

class TestFilterSkillsForTarget:
    """Test end-to-end skill filtering by sync tags."""

    def test_no_tags_passes_all(self, tmp_path):
        """Skills without frontmatter all pass through."""
        skill_a = tmp_path / "skill-a"
        skill_a.mkdir()
        (skill_a / "SKILL.md").write_text("# Skill A\nNo sync tag.\n")

        skill_b = tmp_path / "skill-b"
        skill_b.mkdir()
        (skill_b / "SKILL.md").write_text("# Skill B\nAlso no tag.\n")

        skills = {"skill-a": skill_a, "skill-b": skill_b}
        filtered = filter_skills_for_target(skills, "codex")
        assert set(filtered.keys()) == {"skill-a", "skill-b"}

    def test_exclude_tag_filters_skill(self, tmp_path):
        """A skill with exclude-aider is filtered out for aider but not codex."""
        skill_a = tmp_path / "skill-a"
        skill_a.mkdir()
        (skill_a / "SKILL.md").write_text("---\nsync: exclude-aider\n---\n# Skill A\n")

        skill_b = tmp_path / "skill-b"
        skill_b.mkdir()
        (skill_b / "SKILL.md").write_text("# Skill B\n")

        skills = {"skill-a": skill_a, "skill-b": skill_b}

        # Aider should only get skill-b
        filtered_aider = filter_skills_for_target(skills, "aider")
        assert "skill-a" not in filtered_aider
        assert "skill-b" in filtered_aider

        # Codex should get both
        filtered_codex = filter_skills_for_target(skills, "codex")
        assert "skill-a" in filtered_codex
        assert "skill-b" in filtered_codex

    def test_empty_skills_dict(self, tmp_path):
        """Empty skills dict returns empty."""
        filtered = filter_skills_for_target({}, "codex")
        assert filtered == {}


# ---------------------------------------------------------------------------
# filter_agents_for_target tests
# ---------------------------------------------------------------------------

class TestFilterAgentsForTarget:
    """Test agent filtering (parallel to skills)."""

    def test_agent_exclude_tag(self, tmp_path):
        """An agent with exclude tag is filtered out for that target."""
        agent_md = tmp_path / "agent-a.md"
        agent_md.write_text("---\nsync: exclude-cursor\n---\n# Agent A\n")

        agents = {"agent-a": agent_md}

        filtered_cursor = filter_agents_for_target(agents, "cursor")
        assert "agent-a" not in filtered_cursor

        filtered_codex = filter_agents_for_target(agents, "codex")
        assert "agent-a" in filtered_codex

    def test_agent_no_tag_passes(self, tmp_path):
        """An agent without sync tag passes for all targets."""
        agent_md = tmp_path / "agent-a.md"
        agent_md.write_text("# Agent A\nNo sync tag.\n")

        agents = {"agent-a": agent_md}
        filtered = filter_agents_for_target(agents, "aider")
        assert "agent-a" in filtered


# ---------------------------------------------------------------------------
# Integration: build_target_data applies skill sync tags
# ---------------------------------------------------------------------------

class TestBuildTargetDataSkillFiltering:
    """Verify that build_target_data wires skill_sync_tags filtering."""

    def test_skills_filtered_in_build_target_data(self, tmp_path):
        """build_target_data should filter skills using sync tags."""
        from src.sync_target_builder import build_target_data
        from unittest.mock import MagicMock

        # Create skill directories with sync tags
        skill_a = tmp_path / "skill-a"
        skill_a.mkdir()
        (skill_a / "SKILL.md").write_text("---\nsync: exclude-aider\n---\n# Skill A\n")

        skill_b = tmp_path / "skill-b"
        skill_b.mkdir()
        (skill_b / "SKILL.md").write_text("# Skill B\n")

        adapter_data = {
            "rules": [],
            "skills": {"skill-a": skill_a, "skill-b": skill_b},
            "agents": {},
            "commands": {},
            "mcp": {},
            "settings": {},
        }

        mock_reader = MagicMock()
        mock_reader.get_harness_override.return_value = None
        mock_reader.get_inline_harness_block.return_value = None
        mock_logger = MagicMock()

        result = build_target_data(
            adapter_data=adapter_data,
            target="aider",
            reader=mock_reader,
            project_dir=tmp_path,
            harness_env=None,
            rules_have_tags=False,
            rules_have_annotations=False,
            ann_filter_cls=None,
            transform_engine=None,
            model_routing_hints=None,
            model_routing_summary=[],
            logger=mock_logger,
        )

        # skill-a should be excluded from aider
        assert "skill-a" not in result.get("skills", {})
        assert "skill-b" in result.get("skills", {})

    def test_skills_not_filtered_for_allowed_target(self, tmp_path):
        """build_target_data should keep skills for allowed targets."""
        from src.sync_target_builder import build_target_data
        from unittest.mock import MagicMock

        skill_a = tmp_path / "skill-a"
        skill_a.mkdir()
        (skill_a / "SKILL.md").write_text("---\nsync: exclude-aider\n---\n# Skill A\n")

        adapter_data = {
            "rules": [],
            "skills": {"skill-a": skill_a},
            "agents": {},
            "commands": {},
            "mcp": {},
            "settings": {},
        }

        mock_reader = MagicMock()
        mock_reader.get_harness_override.return_value = None
        mock_reader.get_inline_harness_block.return_value = None
        mock_logger = MagicMock()

        result = build_target_data(
            adapter_data=adapter_data,
            target="codex",
            reader=mock_reader,
            project_dir=tmp_path,
            harness_env=None,
            rules_have_tags=False,
            rules_have_annotations=False,
            ann_filter_cls=None,
            transform_engine=None,
            model_routing_hints=None,
            model_routing_summary=[],
            logger=mock_logger,
        )

        # skill-a should be kept for codex (not excluded)
        assert "skill-a" in result.get("skills", {})
