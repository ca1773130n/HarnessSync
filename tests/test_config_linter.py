from __future__ import annotations

"""Unit tests for src/config_linter.py — configuration linting and validation.

Covers:
- ConfigLinter.lint: built-in checks for rules, settings, skills, agents
- _lint_rules: unclosed fences, unclosed sync tags, orphan sync:end
- _lint_settings: valid settings pass, suspicious keys detected
- _lint_skills / _lint_agents: missing dirs/files
- Custom lint rules: load from file, add programmatically, all rule types
- suggest_fixes / apply_fixes / format_fix_report: auto-fix pipeline
- _suggest_portability_fixes: CC-specific constructs detected
- quality_score: scoring tiers, deductions
- lint_skill_portability / lint_all_skills_portability: cross-harness skill checks
- LintFix dataclass
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_linter import ConfigLinter, LintFix


# ---------------------------------------------------------------------------
# Basic lint — rules content
# ---------------------------------------------------------------------------

class TestLintRules:
    def test_empty_rules_no_issues(self):
        linter = ConfigLinter()
        issues = linter.lint({"rules": ""})
        assert issues == []

    def test_valid_rules_no_issues(self):
        linter = ConfigLinter()
        issues = linter.lint({"rules": "## Commands\n\n```bash\npython3 test\n```\n"})
        assert issues == []

    def test_unclosed_fence_detected(self):
        linter = ConfigLinter()
        issues = linter.lint({"rules": "## Code\n\n```python\nprint('hi')\n"})
        assert any("unclosed" in i.lower() and "fence" in i.lower() for i in issues)

    def test_even_fences_no_issue(self):
        linter = ConfigLinter()
        issues = linter.lint({"rules": "```\ncode\n```\n```\nmore\n```\n"})
        fence_issues = [i for i in issues if "fence" in i.lower()]
        assert fence_issues == []

    def test_unclosed_sync_tag_detected(self):
        linter = ConfigLinter()
        content = "<!-- sync:exclude -->\nSecret stuff\n"
        issues = linter.lint({"rules": content})
        assert any("unclosed" in i.lower() and "sync:exclude" in i.lower() for i in issues)

    def test_matched_sync_tags_no_issue(self):
        linter = ConfigLinter()
        content = "<!-- sync:exclude -->\nSecret\n<!-- sync:end -->\n"
        issues = linter.lint({"rules": content})
        sync_issues = [i for i in issues if "sync:" in i]
        assert sync_issues == []

    def test_orphan_sync_end_detected(self):
        linter = ConfigLinter()
        content = "<!-- sync:end -->\nSome content\n"
        issues = linter.lint({"rules": content})
        assert any("without matching" in i.lower() for i in issues)

    def test_rules_as_list_of_dicts(self):
        """Rules can be a list of dicts with 'content' key."""
        linter = ConfigLinter()
        rules = [
            {"content": "```python\ncode\n"},  # Unclosed fence
            {"content": "normal text"},
        ]
        issues = linter.lint({"rules": rules})
        assert any("fence" in i.lower() for i in issues)


# ---------------------------------------------------------------------------
# Lint — settings
# ---------------------------------------------------------------------------

class TestLintSettings:
    def test_valid_settings_pass(self):
        linter = ConfigLinter()
        settings = {"permissions": {}, "model": "claude-3", "verbose": True}
        issues = linter.lint({"rules": "", "settings": settings})
        assert issues == []

    def test_suspicious_key_detected(self):
        linter = ConfigLinter()
        # Key with special chars (looks like corruption)
        settings = {"permissions": {}, "some.corrupt!key@here": "val"}
        issues = linter.lint({"rules": "", "settings": settings})
        assert any("suspicious" in i.lower() for i in issues)

    def test_non_dict_settings_flagged(self):
        linter = ConfigLinter()
        issues = linter.lint({"rules": "", "settings": "not a dict"})
        assert any("not a JSON object" in i for i in issues)

    def test_known_keys_not_flagged(self):
        linter = ConfigLinter()
        settings = {
            "permissions": {},
            "approval_mode": "auto",
            "env": {},
            "hooks": {},
            "model": "claude-3",
        }
        issues = linter.lint({"rules": "## Test", "settings": settings})
        settings_issues = [i for i in issues if "settings" in i.lower()]
        assert settings_issues == []


# ---------------------------------------------------------------------------
# Lint — skills & agents
# ---------------------------------------------------------------------------

class TestLintSkillsAgents:
    def test_missing_skill_dir_flagged(self, tmp_path):
        linter = ConfigLinter()
        issues = linter.lint({
            "rules": "",
            "skills": {"my-skill": tmp_path / "nonexistent"},
        })
        assert any("missing directory" in i.lower() for i in issues)

    def test_empty_skill_dir_flagged(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        linter = ConfigLinter()
        issues = linter.lint({"rules": "", "skills": {"my-skill": skill_dir}})
        assert any("empty" in i.lower() for i in issues)

    def test_valid_skill_dir_passes(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# My Skill")
        linter = ConfigLinter()
        issues = linter.lint({"rules": "", "skills": {"my-skill": skill_dir}})
        skill_issues = [i for i in issues if "skill" in i.lower()]
        assert skill_issues == []

    def test_missing_agent_file_flagged(self, tmp_path):
        linter = ConfigLinter()
        issues = linter.lint({
            "rules": "",
            "agents": {"my-agent": tmp_path / "nonexistent.md"},
        })
        assert any("missing file" in i.lower() for i in issues)

    def test_valid_agent_passes(self, tmp_path):
        agent_file = tmp_path / "my-agent.md"
        agent_file.write_text("# Agent")
        linter = ConfigLinter()
        issues = linter.lint({"rules": "", "agents": {"my-agent": agent_file}})
        agent_issues = [i for i in issues if "agent" in i.lower()]
        assert agent_issues == []

    def test_none_skills_no_error(self):
        linter = ConfigLinter()
        issues = linter.lint({"rules": "", "skills": None})
        assert isinstance(issues, list)

    def test_none_agents_no_error(self):
        linter = ConfigLinter()
        issues = linter.lint({"rules": "", "agents": None})
        assert isinstance(issues, list)


# ---------------------------------------------------------------------------
# Custom lint rules
# ---------------------------------------------------------------------------

class TestCustomRules:
    def test_load_from_file(self, tmp_path):
        rules_dir = tmp_path / ".harness-sync"
        rules_dir.mkdir()
        rules = [{"id": "r1", "description": "Test rule", "type": "require_heading", "value": "Testing"}]
        (rules_dir / "lint-rules.json").write_text(json.dumps(rules))

        linter = ConfigLinter()
        loaded = linter.load_custom_rules(tmp_path)
        assert len(loaded) == 1
        assert loaded[0]["id"] == "r1"

    def test_load_missing_file_returns_empty(self, tmp_path):
        linter = ConfigLinter()
        loaded = linter.load_custom_rules(tmp_path)
        assert loaded == []

    def test_load_invalid_json_returns_empty(self, tmp_path):
        rules_dir = tmp_path / ".harness-sync"
        rules_dir.mkdir()
        (rules_dir / "lint-rules.json").write_text("{invalid json!")

        linter = ConfigLinter()
        loaded = linter.load_custom_rules(tmp_path)
        assert loaded == []

    def test_add_custom_rule_programmatically(self):
        linter = ConfigLinter()
        linter.add_custom_rule({
            "id": "test",
            "description": "Test",
            "type": "require_heading",
            "value": "Testing",
        })
        assert len(linter._custom_rules) == 1

    def test_require_heading_violation(self):
        linter = ConfigLinter()
        linter.add_custom_rule({
            "id": "need-testing",
            "description": "Must have Testing heading",
            "type": "require_heading",
            "value": "Testing",
            "severity": "error",
        })
        issues = linter.lint({"rules": "## Commands\n\nDo stuff\n"})
        assert any("need-testing" in i for i in issues)

    def test_require_heading_passes(self):
        linter = ConfigLinter()
        linter.add_custom_rule({
            "id": "need-testing",
            "description": "Must have Testing heading",
            "type": "require_heading",
            "value": "Testing",
        })
        issues = linter.lint({"rules": "## Testing\n\nRun tests\n"})
        custom_issues = [i for i in issues if "need-testing" in i]
        assert custom_issues == []

    def test_pattern_must_match_violation(self):
        linter = ConfigLinter()
        linter.add_custom_rule({
            "id": "needs-python",
            "description": "Must mention python",
            "type": "pattern_must_match",
            "pattern": r"python",
            "severity": "warning",
        })
        issues = linter.lint({"rules": "## Commands\nUse node\n"})
        assert any("needs-python" in i for i in issues)

    def test_pattern_must_not_match_violation(self):
        linter = ConfigLinter()
        linter.add_custom_rule({
            "id": "no-sudo",
            "description": "Must not use sudo",
            "type": "pattern_must_not_match",
            "pattern": r"\bsudo\b",
            "severity": "error",
        })
        issues = linter.lint({"rules": "Run: sudo apt install\n"})
        assert any("no-sudo" in i for i in issues)

    def test_max_lines_violation(self):
        linter = ConfigLinter()
        linter.add_custom_rule({
            "id": "max-10",
            "description": "Max 10 lines",
            "type": "max_lines",
            "value": 10,
            "severity": "warning",
        })
        issues = linter.lint({"rules": "\n".join(f"line {i}" for i in range(20))})
        assert any("max-10" in i for i in issues)

    def test_min_section_count_violation(self):
        linter = ConfigLinter()
        linter.add_custom_rule({
            "id": "min-3-sections",
            "description": "Need at least 3 sections",
            "type": "min_section_count",
            "value": 3,
            "severity": "warning",
        })
        issues = linter.lint({"rules": "## One Section\nContent\n"})
        assert any("min-3-sections" in i for i in issues)

    def test_mcp_field_required_violation(self):
        linter = ConfigLinter()
        linter.add_custom_rule({
            "id": "need-tools",
            "description": "MCP must have tools field",
            "type": "mcp_field_required",
            "field": "tools",
            "severity": "warning",
        })
        issues = linter.lint({
            "rules": "",
            "mcp_servers": {"s1": {"command": "npx"}},
        })
        assert any("need-tools" in i for i in issues)

    def test_mcp_field_required_passes(self):
        linter = ConfigLinter()
        linter.add_custom_rule({
            "id": "need-tools",
            "description": "MCP must have tools field",
            "type": "mcp_field_required",
            "field": "tools",
        })
        issues = linter.lint({
            "rules": "",
            "mcp_servers": {"s1": {"command": "npx", "tools": ["t1"]}},
        })
        custom_issues = [i for i in issues if "need-tools" in i]
        assert custom_issues == []

    def test_unknown_rule_type_skipped(self):
        linter = ConfigLinter()
        linter.add_custom_rule({
            "id": "unknown",
            "description": "Unknown type",
            "type": "does_not_exist",
        })
        issues = linter.lint({"rules": "text"})
        unknown_issues = [i for i in issues if "unknown" in i.lower()]
        assert unknown_issues == []

    def test_custom_rules_loaded_via_lint(self, tmp_path):
        """lint() auto-loads custom rules when project_dir is passed."""
        rules_dir = tmp_path / ".harness-sync"
        rules_dir.mkdir()
        rules = [{"id": "r1", "description": "Need Testing", "type": "require_heading", "value": "Testing"}]
        (rules_dir / "lint-rules.json").write_text(json.dumps(rules))

        linter = ConfigLinter()
        issues = linter.lint({"rules": "## Commands\nstuff\n"}, project_dir=tmp_path)
        assert any("r1" in i for i in issues)


# ---------------------------------------------------------------------------
# suggest_fixes / apply_fixes / format_fix_report
# ---------------------------------------------------------------------------

class TestAutoFix:
    def test_suggest_fixes_unclosed_tag(self):
        linter = ConfigLinter()
        source_data = {"rules": "<!-- sync:exclude -->\nSecret content\n"}
        fixes = linter.suggest_fixes(source_data)
        assert any("sync:exclude" in f.issue for f in fixes)

    def test_suggest_fixes_portability(self):
        linter = ConfigLinter()
        source_data = {"rules": "Use $ARGUMENTS to pass args\n"}
        fixes = linter.suggest_fixes(source_data)
        assert any("$ARGUMENTS" in f.issue for f in fixes)

    def test_apply_fixes_replaces(self):
        linter = ConfigLinter()
        content = "Use $ARGUMENTS here\n"
        fix = LintFix(
            issue="test",
            suggestion="replace",
            auto_fixable=True,
            fix_pattern=re.compile(r"\$ARGUMENTS\b"),
            fix_replacement="[user-provided arguments]",
        )
        result = linter.apply_fixes(content, [fix])
        assert "[user-provided arguments]" in result
        assert "$ARGUMENTS" not in result

    def test_apply_fixes_skips_non_auto(self):
        linter = ConfigLinter()
        content = "original content"
        fix = LintFix(issue="test", suggestion="manual fix", auto_fixable=False)
        result = linter.apply_fixes(content, [fix])
        assert result == content

    def test_format_fix_report_no_issues(self):
        linter = ConfigLinter()
        report = linter.format_fix_report([])
        assert "No lint issues" in report

    def test_format_fix_report_with_issues(self):
        linter = ConfigLinter()
        fixes = [
            LintFix(issue="Issue one", suggestion="Fix it", auto_fixable=True),
            LintFix(issue="Issue two", suggestion="Do that", auto_fixable=False),
        ]
        report = linter.format_fix_report(fixes)
        assert "2 issue(s)" in report
        assert "[AUTO-FIX]" in report
        assert "[MANUAL]" in report


# ---------------------------------------------------------------------------
# Portability checks
# ---------------------------------------------------------------------------

class TestPortabilityChecks:
    def test_tool_references_detected(self):
        linter = ConfigLinter()
        source_data = {"rules": "Use the Read tool to view the file\n"}
        fixes = linter.suggest_fixes(source_data)
        assert any("tool reference" in f.issue.lower() for f in fixes)

    def test_slash_command_detected(self):
        """The /sync portability pattern fires when preceded by a word boundary."""
        linter = ConfigLinter()
        # Use text where /sync appears after a word char so \b matches
        source_data = {"rules": "use/sync-status to check\n"}
        fixes = linter.suggest_fixes(source_data)
        assert any("/sync" in f.issue.lower() or "slash" in f.issue.lower()
                    or "claude code" in f.issue.lower() for f in fixes)

    def test_trailing_whitespace_detected(self):
        linter = ConfigLinter()
        source_data = {"rules": "Some line with trailing spaces   \n"}
        fixes = linter.suggest_fixes(source_data)
        assert any("whitespace" in f.issue.lower() for f in fixes)

    def test_secret_in_rules_detected(self):
        linter = ConfigLinter()
        source_data = {"rules": "Use this key: sk-abcdefghijklmnop1234567890abcdef\n"}
        fixes = linter.suggest_fixes(source_data)
        assert any("secret" in f.issue.lower() or "key" in f.issue.lower() for f in fixes)


# ---------------------------------------------------------------------------
# quality_score
# ---------------------------------------------------------------------------

class TestQualityScore:
    def test_perfect_score(self):
        linter = ConfigLinter()
        source_data = {"rules": "## Commands\n\n```bash\npython3 test\n```\n"}
        result = linter.quality_score(source_data)
        assert result["score"] >= 90
        assert result["tier"] in ("Excellent", "Good")

    def test_poor_score_with_issues(self):
        linter = ConfigLinter()
        # Unclosed fence + unclosed sync tag + $ARGUMENTS
        source_data = {
            "rules": (
                "```python\ncode\n"  # Unclosed fence
                "<!-- sync:exclude -->\n"  # Unclosed tag
                "Use $ARGUMENTS to pass\n"
            ),
        }
        result = linter.quality_score(source_data)
        assert result["score"] < 90
        assert len(result["issues"]) >= 1

    def test_score_clamped_to_0(self):
        linter = ConfigLinter()
        # Many issues to drive score below 0
        rules = "\n".join([
            "```python\ncode\n",  # Unclosed fence
            "<!-- sync:exclude -->\n",
            "<!-- sync:codex-only -->\n",
            "<!-- sync:gemini-only -->\n",
        ])
        result = linter.quality_score({"rules": rules})
        assert result["score"] >= 0

    def test_score_returns_breakdown(self):
        linter = ConfigLinter()
        result = linter.quality_score({"rules": "clean content\n"})
        assert "breakdown" in result
        assert "structural_deduction" in result["breakdown"]
        assert "portability_deduction" in result["breakdown"]

    def test_tier_labels(self):
        linter = ConfigLinter()
        # Test the tier mapping
        result_clean = linter.quality_score({"rules": "## Section\nClean config\n"})
        assert result_clean["tier"] in ("Excellent", "Good", "Fair", "Poor")


# ---------------------------------------------------------------------------
# Skill portability linting
# ---------------------------------------------------------------------------

class TestSkillPortability:
    def test_clean_skill_no_issues(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# My Skill\n\nDoes useful things.\n")

        linter = ConfigLinter()
        issues = linter.lint_skill_portability("my-skill", skill_dir)
        assert issues == []

    def test_tool_reference_flagged(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Use the Read tool to view files.\n")

        linter = ConfigLinter()
        issues = linter.lint_skill_portability("my-skill", skill_dir)
        assert any(i["code"] == "CC_TOOL_REF" for i in issues)

    def test_arguments_placeholder_flagged(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Process $ARGUMENTS from user.\n")

        linter = ConfigLinter()
        issues = linter.lint_skill_portability("my-skill", skill_dir)
        assert any(i["code"] == "CC_ARGUMENTS" for i in issues)

    def test_missing_skill_md(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()

        linter = ConfigLinter()
        issues = linter.lint_skill_portability("my-skill", skill_dir)
        assert any(i["code"] == "MISSING_SKILL_MD" for i in issues)

    def test_lint_all_skills(self, tmp_path):
        s1 = tmp_path / "skill-a"
        s1.mkdir()
        (s1 / "SKILL.md").write_text("Use the Bash tool\n")

        s2 = tmp_path / "skill-b"
        s2.mkdir()
        (s2 / "SKILL.md").write_text("Clean skill content\n")

        linter = ConfigLinter()
        results = linter.lint_all_skills_portability({"skill-a": s1, "skill-b": s2})
        assert "skill-a" in results
        assert "skill-b" not in results

    def test_format_skill_report_clean(self):
        linter = ConfigLinter()
        report = linter.format_skill_portability_report({})
        assert "portable" in report.lower()

    def test_format_skill_report_with_issues(self, tmp_path):
        linter = ConfigLinter()
        issues = {"my-skill": [{
            "code": "CC_TOOL_REF",
            "message": "test message",
            "fix": "rewrite it",
            "line": 5,
        }]}
        report = linter.format_skill_portability_report(issues)
        assert "1 issue(s)" in report
        assert "my-skill" in report

    def test_slash_command_flagged(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Run /sync to synchronize.\n")

        linter = ConfigLinter()
        issues = linter.lint_skill_portability("my-skill", skill_dir)
        assert any(i["code"] == "CC_SLASH_CMD" for i in issues)

    def test_mcp_tool_ref_flagged(self, tmp_path):
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("Call mcp__server__tool_name to do work.\n")

        linter = ConfigLinter()
        issues = linter.lint_skill_portability("my-skill", skill_dir)
        assert any(i["code"] == "CC_MCP_TOOL_REF" for i in issues)


# ---------------------------------------------------------------------------
# LintFix dataclass
# ---------------------------------------------------------------------------

class TestLintFix:
    def test_default_values(self):
        fix = LintFix(issue="test", suggestion="do this")
        assert fix.auto_fixable is False
        assert fix.fix_pattern is None
        assert fix.fix_replacement == ""

    def test_auto_fixable(self):
        fix = LintFix(
            issue="test",
            suggestion="auto",
            auto_fixable=True,
            fix_pattern=re.compile(r"old"),
            fix_replacement="new",
        )
        assert fix.auto_fixable is True
        assert fix.fix_pattern is not None
