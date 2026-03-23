"""Tests for the Cline adapter (rules dir, native skills, workflow commands)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.adapters.cline import ClineAdapter


class TestClineRulesSync:
    """Test sync_rules writes to .clinerules/ directory and flat file fallback."""

    def test_rules_to_directory_new_project(self, tmp_path):
        """On a fresh project, rules go to .clinerules/ as individual .md files."""
        adapter = ClineAdapter(tmp_path)
        rules = [
            {"path": "CLAUDE.md", "content": "Rule one content"},
            {"path": "docs/RULES.md", "content": "Rule two content"},
        ]
        result = adapter.sync_rules(rules)

        assert result.synced >= 2
        assert result.failed == 0

        # Individual rule files in .clinerules/ directory
        clinerules_dir = tmp_path / ".clinerules"
        assert clinerules_dir.is_dir()
        assert (clinerules_dir / "claude.md").is_file()
        assert (clinerules_dir / "rules.md").is_file()

        content = (clinerules_dir / "claude.md").read_text()
        assert "Rule one content" in content
        assert "<!-- Managed by HarnessSync -->" in content

    def test_rules_flat_file_fallback(self, tmp_path):
        """When .clinerules exists as a flat file, update it instead of creating dir."""
        flat_file = tmp_path / ".clinerules"
        flat_file.write_text("Existing flat rules\n")

        adapter = ClineAdapter(tmp_path)
        rules = [{"path": "CLAUDE.md", "content": "New rule content"}]
        result = adapter.sync_rules(rules)

        assert result.synced >= 1
        assert result.failed == 0

        # Flat file should still exist and be updated
        assert flat_file.is_file()
        content = flat_file.read_text()
        assert "New rule content" in content
        assert "Existing flat rules" in content

    def test_rules_roo_compat(self, tmp_path):
        """Rules should also be written to .roo/rules/harnesssync.md."""
        adapter = ClineAdapter(tmp_path)
        rules = [{"path": "CLAUDE.md", "content": "Some rule"}]
        adapter.sync_rules(rules)

        roo_path = tmp_path / ".roo" / "rules" / "harnesssync.md"
        assert roo_path.is_file()
        assert "Some rule" in roo_path.read_text()

    def test_rules_empty_skipped(self, tmp_path):
        """Empty rules list returns skipped result."""
        adapter = ClineAdapter(tmp_path)
        result = adapter.sync_rules([])
        assert result.skipped == 1

    def test_rules_whitespace_only_skipped(self, tmp_path):
        """Rules with only whitespace content are skipped."""
        adapter = ClineAdapter(tmp_path)
        result = adapter.sync_rules([{"content": "   "}])
        assert result.skipped == 1

    def test_rules_dir_derives_name_from_path(self, tmp_path):
        """Rule file names are derived from source path stem."""
        adapter = ClineAdapter(tmp_path)
        rules = [{"path": "/some/Project Rules.md", "content": "content"}]
        adapter.sync_rules(rules)

        clinerules_dir = tmp_path / ".clinerules"
        assert (clinerules_dir / "project-rules.md").is_file()

    def test_rules_dir_fallback_name_without_path(self, tmp_path):
        """Rules without a path get numbered fallback names."""
        adapter = ClineAdapter(tmp_path)
        rules = [{"content": "first"}, {"content": "second"}]
        adapter.sync_rules(rules)

        clinerules_dir = tmp_path / ".clinerules"
        assert (clinerules_dir / "rule-0.md").is_file()
        assert (clinerules_dir / "rule-1.md").is_file()


class TestClineSkillsSync:
    """Test sync_skills writes to .cline/skills/<name>/SKILL.md with YAML frontmatter."""

    def test_skills_native_format(self, tmp_path):
        """Skills are written to .cline/skills/<name>/SKILL.md with frontmatter."""
        # Create a source skill
        skill_dir = tmp_path / "source_skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# My Skill\n\nDo something useful.\n")

        adapter = ClineAdapter(tmp_path)
        result = adapter.sync_skills({"my-skill": skill_dir})

        assert result.synced == 1
        assert result.failed == 0

        out_path = tmp_path / ".cline" / "skills" / "my-skill" / "SKILL.md"
        assert out_path.is_file()

        content = out_path.read_text()
        assert content.startswith("---\n")
        assert "name: my-skill" in content
        assert "description:" in content
        assert "Do something useful." in content

    def test_skills_description_extraction(self, tmp_path):
        """Description is extracted from first non-heading line."""
        skill_dir = tmp_path / "source_skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# Heading\n\nThis is the description line.\n\nMore content.\n")

        adapter = ClineAdapter(tmp_path)
        adapter.sync_skills({"test-skill": skill_dir})

        out_path = tmp_path / ".cline" / "skills" / "test-skill" / "SKILL.md"
        content = out_path.read_text()
        assert "This is the description line." in content

    def test_skills_empty_skipped(self, tmp_path):
        """Empty skills dict returns skipped result."""
        adapter = ClineAdapter(tmp_path)
        result = adapter.sync_skills({})
        assert result.skipped == 1

    def test_skills_missing_skill_md(self, tmp_path):
        """Missing SKILL.md reports a failure."""
        empty_dir = tmp_path / "source_skills" / "broken"
        empty_dir.mkdir(parents=True)

        adapter = ClineAdapter(tmp_path)
        result = adapter.sync_skills({"broken": empty_dir})
        assert result.failed == 1

    def test_skills_file_path_input(self, tmp_path):
        """When skill_path is a file (not dir), use it directly."""
        skill_file = tmp_path / "source_skills" / "inline.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text("Inline skill content\n")

        adapter = ClineAdapter(tmp_path)
        result = adapter.sync_skills({"inline": skill_file})

        assert result.synced == 1
        out_path = tmp_path / ".cline" / "skills" / "inline" / "SKILL.md"
        assert out_path.is_file()
        assert "Inline skill content" in out_path.read_text()


class TestClineCommandsSync:
    """Test sync_commands writes to .clinerules/workflows/."""

    def test_commands_to_workflows(self, tmp_path):
        """Commands become .md files in .clinerules/workflows/."""
        cmd_file = tmp_path / "source_commands" / "deploy.md"
        cmd_file.parent.mkdir(parents=True)
        cmd_file.write_text("Deploy the application with $ARGUMENTS\n")

        adapter = ClineAdapter(tmp_path)
        result = adapter.sync_commands({"deploy": cmd_file})

        assert result.synced == 1
        assert result.failed == 0

        out_path = tmp_path / ".clinerules" / "workflows" / "deploy.md"
        assert out_path.is_file()

        content = out_path.read_text()
        assert "# Workflow: deploy" in content
        assert "<!-- Managed by HarnessSync -->" in content
        # $ARGUMENTS should be adapted
        assert "[user-provided arguments]" in content
        assert "$ARGUMENTS" not in content

    def test_commands_empty_returns_zero(self, tmp_path):
        """Empty commands dict returns zero skipped."""
        adapter = ClineAdapter(tmp_path)
        result = adapter.sync_commands({})
        assert result.skipped == 0
        assert result.synced == 0

    def test_commands_missing_file(self, tmp_path):
        """Missing command file reports failure."""
        adapter = ClineAdapter(tmp_path)
        result = adapter.sync_commands({"missing": tmp_path / "nope.md"})
        assert result.failed == 1

    def test_commands_multiple(self, tmp_path):
        """Multiple commands each get their own workflow file."""
        cmd_dir = tmp_path / "source_commands"
        cmd_dir.mkdir(parents=True)
        (cmd_dir / "build.md").write_text("Build steps\n")
        (cmd_dir / "test.md").write_text("Test steps\n")

        adapter = ClineAdapter(tmp_path)
        result = adapter.sync_commands({
            "build": cmd_dir / "build.md",
            "test": cmd_dir / "test.md",
        })

        assert result.synced == 2
        workflows = tmp_path / ".clinerules" / "workflows"
        assert (workflows / "build.md").is_file()
        assert (workflows / "test.md").is_file()
