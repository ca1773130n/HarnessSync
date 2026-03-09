from __future__ import annotations

"""Phase 12 Integration Tests: Adapter config fixes and rules directory discovery.

Verifies all phase 12 requirements:
- Codex: config.toml filename, on-request approval policy
- Gemini: tools.exclude / tools.allowed (not blockedTools/allowedTools)
- OpenCode: permission (singular) with per-tool entries, old permissions cleanup
- SourceReader: rules directory discovery with frontmatter path-scoping
"""

import json
import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.adapters.codex import CodexAdapter, CONFIG_TOML
from src.adapters.gemini import GeminiAdapter
from src.adapters.opencode import OpenCodeAdapter
from src.source_reader import SourceReader


# ---------- Codex Tests ----------


def test_codex_config_filename():
    """CONFIG_TOML constant must be 'config.toml', not 'codex.toml'."""
    assert CONFIG_TOML == "config.toml"


def test_codex_approval_policy_auto(tmp_path):
    """Codex approval_policy maps to 'on-request' when Claude Code has auto mode."""
    adapter = CodexAdapter(tmp_path)
    adapter.sync_settings({"approval_mode": "auto", "permissions": {}})

    config_path = tmp_path / ".codex" / "config.toml"
    assert config_path.exists(), "config.toml not written"

    content = config_path.read_text()
    assert "on-request" in content
    assert "on-failure" not in content


def test_codex_approval_policy_ask(tmp_path):
    """Codex approval_policy maps to 'on-request' when Claude Code has ask mode."""
    adapter = CodexAdapter(tmp_path)
    adapter.sync_settings({"approval_mode": "ask", "permissions": {}})

    config_path = tmp_path / ".codex" / "config.toml"
    content = config_path.read_text()
    assert "on-request" in content
    assert "on-failure" not in content


# ---------- Gemini Tests ----------


def test_gemini_deny_list_uses_exclude(tmp_path):
    """Gemini settings uses tools.exclude, not blockedTools."""
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()

    adapter = GeminiAdapter(tmp_path)
    adapter.sync_settings({"permissions": {"deny": ["Write"], "allow": []}})

    settings_path = gemini_dir / "settings.json"
    assert settings_path.exists()

    data = json.loads(settings_path.read_text())
    assert "exclude" in data.get("tools", {}), "tools.exclude key missing"
    assert "blockedTools" not in data, "deprecated blockedTools key still present"


def test_gemini_allow_list_uses_allowed(tmp_path):
    """Gemini settings uses tools.allowed, not allowedTools."""
    gemini_dir = tmp_path / ".gemini"
    gemini_dir.mkdir()

    adapter = GeminiAdapter(tmp_path)
    adapter.sync_settings({"permissions": {"deny": [], "allow": ["Read", "Bash"]}})

    settings_path = gemini_dir / "settings.json"
    data = json.loads(settings_path.read_text())
    assert "allowed" in data.get("tools", {}), "tools.allowed key missing"
    assert "allowedTools" not in data, "deprecated allowedTools key still present"


# ---------- OpenCode Tests ----------


def test_opencode_permission_singular(tmp_path):
    """OpenCode uses 'permission' (singular), not 'permissions' (plural)."""
    adapter = OpenCodeAdapter(tmp_path)
    adapter.sync_settings({"permissions": {"deny": ["Write"], "allow": ["Read"]}})

    oc_path = tmp_path / "opencode.json"
    assert oc_path.exists()

    data = json.loads(oc_path.read_text())
    assert "permission" in data, "permission (singular) key missing"
    assert "permissions" not in data, "deprecated permissions (plural) key still present"


def test_opencode_bash_patterns(tmp_path):
    """OpenCode bash patterns produce permission.bash dict with pattern entries."""
    adapter = OpenCodeAdapter(tmp_path)
    adapter.sync_settings({
        "permissions": {
            "deny": [],
            "allow": ["Bash(git commit:*)"],
        }
    })

    oc_path = tmp_path / "opencode.json"
    data = json.loads(oc_path.read_text())
    bash_perm = data.get("permission", {}).get("bash", {})
    assert isinstance(bash_perm, dict), "permission.bash should be a dict with patterns"
    assert "git commit *" in bash_perm, "bash pattern not translated"
    assert bash_perm["git commit *"] == "allow"


def test_opencode_removes_old_permissions(tmp_path):
    """OpenCode removes old 'permissions' (plural) key when writing new config."""
    # Pre-write old format
    oc_path = tmp_path / "opencode.json"
    oc_path.write_text(json.dumps({"permissions": {"mode": "default"}}))

    adapter = OpenCodeAdapter(tmp_path)
    adapter.sync_settings({"permissions": {"deny": ["Write"], "allow": []}})

    data = json.loads(oc_path.read_text())
    assert "permissions" not in data, "old permissions (plural) key not removed"
    assert "permission" in data, "new permission (singular) key missing"


# ---------- SourceReader: Rules Discovery Tests ----------


def test_rules_discovery_project(tmp_path):
    """SourceReader discovers .md files from .claude/rules/ directory."""
    rules_dir = tmp_path / ".claude" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "test.md").write_text("# Test rule")

    reader = SourceReader(scope="project", project_dir=tmp_path)
    rules = reader.get_rules_files()

    assert len(rules) == 1
    assert rules[0]["content"].strip() == "# Test rule"
    assert rules[0]["scope"] == "project"


def test_rules_discovery_nested(tmp_path):
    """SourceReader discovers .md files from nested subdirectories."""
    nested_dir = tmp_path / ".claude" / "rules" / "subdir"
    nested_dir.mkdir(parents=True)
    (nested_dir / "nested.md").write_text("Nested rule content")

    reader = SourceReader(scope="project", project_dir=tmp_path)
    rules = reader.get_rules_files()

    assert len(rules) == 1
    assert "Nested rule content" in rules[0]["content"]


def test_rules_frontmatter_paths(tmp_path):
    """SourceReader parses paths: from YAML frontmatter as scope_patterns."""
    rules_dir = tmp_path / ".claude" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "scoped.md").write_text("---\npaths: src/**/*.ts\n---\nScoped rule")

    reader = SourceReader(scope="project", project_dir=tmp_path)
    rules = reader.get_rules_files()

    assert len(rules) == 1
    assert rules[0]["scope_patterns"] == ["src/**/*.ts"]


def test_rules_frontmatter_list(tmp_path):
    """SourceReader parses multi-line paths: list from frontmatter."""
    rules_dir = tmp_path / ".claude" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "multi.md").write_text("---\npaths:\n  - a\n  - b\n---\nContent")

    reader = SourceReader(scope="project", project_dir=tmp_path)
    rules = reader.get_rules_files()

    assert len(rules) == 1
    assert rules[0]["scope_patterns"] == ["a", "b"]


def test_rules_no_frontmatter(tmp_path):
    """SourceReader returns empty scope_patterns when no frontmatter present."""
    rules_dir = tmp_path / ".claude" / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "plain.md").write_text("No frontmatter here")

    reader = SourceReader(scope="project", project_dir=tmp_path)
    rules = reader.get_rules_files()

    assert len(rules) == 1
    assert rules[0]["scope_patterns"] == []


def test_rules_user_scope(tmp_path):
    """SourceReader discovers rules from cc_home/rules/ with user scope."""
    cc_home = tmp_path / "cc_home"
    rules_dir = cc_home / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "user.md").write_text("User-level rule")

    reader = SourceReader(scope="user", cc_home=cc_home)
    rules = reader.get_rules_files()

    assert len(rules) == 1
    assert rules[0]["scope"] == "user"
    assert "User-level rule" in rules[0]["content"]
