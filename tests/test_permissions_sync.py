from __future__ import annotations

"""Tests for Slice 1: Permissions Sync.

Covers:
- Permission string parsing (various formats, edge cases)
- extract_permissions() with full, partial, empty settings
- SourceReader.get_permissions() integration
- Per-adapter format mapping:
    - Codex: intent-based approval_policy mapping
    - Gemini: policy file creation + settings flags
    - OpenCode: grouped per-tool permission format
- Round-trip: source -> extract -> adapter format
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.permissions import extract_permissions, parse_permission_string


# ---------------------------------------------------------------------------
# parse_permission_string tests
# ---------------------------------------------------------------------------

class TestParsePermissionString:
    """Test parse_permission_string with various formats and edge cases."""

    def test_bare_tool_name(self):
        assert parse_permission_string("Read") == ("Read", "")

    def test_bare_tool_with_whitespace(self):
        assert parse_permission_string("  Read  ") == ("Read", "")

    def test_tool_with_simple_args(self):
        assert parse_permission_string("Bash(npm *)") == ("Bash", "npm *")

    def test_tool_with_multi_word_args(self):
        assert parse_permission_string("Bash(git push *)") == ("Bash", "git push *")

    def test_tool_with_path_args(self):
        assert parse_permission_string("Bash(rm -rf /tmp/*)") == ("Bash", "rm -rf /tmp/*")

    def test_tool_with_url_args(self):
        result = parse_permission_string("WebFetch(https://api.example.com/*)")
        assert result == ("WebFetch", "https://api.example.com/*")

    def test_nested_parens(self):
        # Nested parens: first ( and last ) are used
        result = parse_permission_string("Bash(echo (hello))")
        assert result == ("Bash", "echo (hello)")

    def test_empty_string(self):
        assert parse_permission_string("") == ("", "")

    def test_none_value(self):
        assert parse_permission_string(None) == ("", "")

    def test_non_string(self):
        assert parse_permission_string(123) == ("", "")

    def test_empty_parens(self):
        assert parse_permission_string("Bash()") == ("Bash", "")

    def test_unclosed_paren(self):
        # Malformed: opening but no closing
        result = parse_permission_string("Bash(npm install")
        assert result[0] == "Bash"
        assert "npm install" in result[1]

    def test_tool_name_with_spaces_before_paren(self):
        result = parse_permission_string("Bash (npm *)")
        assert result == ("Bash", "npm *")

    def test_complex_glob_pattern(self):
        result = parse_permission_string("Bash(git commit --amend -m *)")
        assert result == ("Bash", "git commit --amend -m *")

    def test_edit_tool(self):
        assert parse_permission_string("Edit") == ("Edit", "")

    def test_write_tool(self):
        assert parse_permission_string("Write") == ("Write", "")

    def test_glob_tool(self):
        assert parse_permission_string("Glob") == ("Glob", "")

    def test_grep_tool(self):
        assert parse_permission_string("Grep") == ("Grep", "")


# ---------------------------------------------------------------------------
# extract_permissions tests
# ---------------------------------------------------------------------------

class TestExtractPermissions:
    """Test extract_permissions with full, partial, and empty settings."""

    def test_full_permissions(self):
        settings = {
            "permissions": {
                "allow": ["Read", "Bash(npm *)"],
                "deny": ["Bash(rm -rf *)"],
                "ask": ["Write"],
            }
        }
        result = extract_permissions(settings)
        assert result["allow"] == ["Read", "Bash(npm *)"]
        assert result["deny"] == ["Bash(rm -rf *)"]
        assert result["ask"] == ["Write"]

    def test_missing_permissions_key(self):
        settings = {"some_other_key": True}
        result = extract_permissions(settings)
        assert result == {"allow": [], "deny": [], "ask": []}

    def test_empty_settings(self):
        result = extract_permissions({})
        assert result == {"allow": [], "deny": [], "ask": []}

    def test_none_settings(self):
        result = extract_permissions(None)
        assert result == {"allow": [], "deny": [], "ask": []}

    def test_non_dict_settings(self):
        result = extract_permissions("not a dict")
        assert result == {"allow": [], "deny": [], "ask": []}

    def test_partial_permissions_only_allow(self):
        settings = {"permissions": {"allow": ["Read"]}}
        result = extract_permissions(settings)
        assert result["allow"] == ["Read"]
        assert result["deny"] == []
        assert result["ask"] == []

    def test_partial_permissions_only_deny(self):
        settings = {"permissions": {"deny": ["Bash(rm *)"]}}
        result = extract_permissions(settings)
        assert result["allow"] == []
        assert result["deny"] == ["Bash(rm *)"]
        assert result["ask"] == []

    def test_non_list_permission_values(self):
        settings = {"permissions": {"allow": "not a list", "deny": 42, "ask": True}}
        result = extract_permissions(settings)
        assert result["allow"] == []
        assert result["deny"] == []
        assert result["ask"] == []

    def test_non_dict_permissions(self):
        settings = {"permissions": "not a dict"}
        result = extract_permissions(settings)
        assert result == {"allow": [], "deny": [], "ask": []}

    def test_returns_defensive_copy(self):
        """Verify the returned lists are copies, not references."""
        settings = {"permissions": {"allow": ["Read"], "deny": [], "ask": []}}
        result = extract_permissions(settings)
        result["allow"].append("Write")
        # Original should be unmodified
        assert settings["permissions"]["allow"] == ["Read"]


# ---------------------------------------------------------------------------
# SourceReader.get_permissions() integration tests
# ---------------------------------------------------------------------------

class TestSourceReaderGetPermissions:
    """Test SourceReader.get_permissions() method."""

    def test_get_permissions_from_settings(self, tmp_path):
        from src.source_reader import SourceReader

        # Create a settings.json with permissions
        cc_home = tmp_path / ".claude"
        cc_home.mkdir()
        settings_json = cc_home / "settings.json"
        settings_json.write_text(json.dumps({
            "permissions": {
                "allow": ["Read", "Bash(npm *)"],
                "deny": ["Bash(rm -rf *)"],
                "ask": ["Write"],
            }
        }))

        reader = SourceReader(scope="user", cc_home=cc_home)
        perms = reader.get_permissions()
        assert perms["allow"] == ["Read", "Bash(npm *)"]
        assert perms["deny"] == ["Bash(rm -rf *)"]
        assert perms["ask"] == ["Write"]

    def test_get_permissions_no_settings(self, tmp_path):
        from src.source_reader import SourceReader

        cc_home = tmp_path / ".claude"
        cc_home.mkdir()

        reader = SourceReader(scope="user", cc_home=cc_home)
        perms = reader.get_permissions()
        assert perms == {"allow": [], "deny": [], "ask": []}

    def test_discover_all_includes_permissions(self, tmp_path):
        from src.source_reader import SourceReader

        cc_home = tmp_path / ".claude"
        cc_home.mkdir()
        settings_json = cc_home / "settings.json"
        settings_json.write_text(json.dumps({
            "permissions": {
                "allow": ["Read"],
                "deny": ["Bash(rm *)"],
                "ask": [],
            }
        }))

        reader = SourceReader(scope="user", cc_home=cc_home)
        data = reader.discover_all()
        assert "permissions" in data
        assert data["permissions"]["allow"] == ["Read"]
        assert data["permissions"]["deny"] == ["Bash(rm *)"]


# ---------------------------------------------------------------------------
# Codex adapter permission mapping tests
# ---------------------------------------------------------------------------

class TestCodexPermissionMapping:
    """Test Codex adapter intent-based permission mapping."""

    def test_restrictive_stance_many_denies(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": [],
                "deny": ["Bash(rm *)", "Bash(sudo *)", "Bash(chmod *)"],
                "ask": [],
            }
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        # Read the config.toml and check approval_policy
        config_path = tmp_path / ".codex" / "config.toml"
        assert config_path.exists()
        content = config_path.read_text()
        assert 'approval_policy = "untrusted"' in content
        assert 'sandbox_mode = "read-only"' in content

    def test_balanced_stance_default(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Read"],
                "deny": [],
                "ask": ["Bash(git push *)"],
            }
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()
        assert 'approval_policy = "on-request"' in content

    def test_permissive_stance_many_allows(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
                "deny": [],
                "ask": [],
            }
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()
        assert 'approval_policy = "never"' in content

    def test_deny_rules_documented_in_agents_md(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        # First sync rules to create AGENTS.md with markers
        rules = [{"path": "CLAUDE.md", "content": "# Test rules"}]
        adapter.sync_rules(rules)

        # Now sync settings with deny rules
        settings = {
            "permissions": {
                "allow": [],
                "deny": ["Bash(rm -rf *)", "Bash(sudo *)"],
                "ask": ["Bash(git push *)"],
            }
        }
        adapter.sync_settings(settings)

        agents_md = tmp_path / "AGENTS.md"
        assert agents_md.exists()
        content = agents_md.read_text()
        assert "Permission Restrictions" in content
        assert "Denied Operations" in content
        assert "Bash" in content
        assert "rm -rf *" in content
        assert "Requires Confirmation" in content
        assert "git push *" in content

    def test_empty_settings(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)
        result = adapter.sync_settings({})
        assert result.synced == 0

    def test_no_permissions_in_settings(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)
        settings = {"some_other": "value"}
        result = adapter.sync_settings(settings)
        assert result.synced == 1
        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()
        # Should use balanced defaults
        assert 'approval_policy = "on-request"' in content


# ---------------------------------------------------------------------------
# Gemini adapter permission mapping tests
# ---------------------------------------------------------------------------

class TestGeminiPermissionMapping:
    """Test Gemini adapter policy file creation and settings flags."""

    def test_deny_rules_create_policy_file(self, tmp_path):
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": [],
                "deny": ["Bash(rm -rf *)", "Bash(sudo *)"],
                "ask": [],
            }
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        # Verify policy file created
        policy_path = tmp_path / ".gemini" / "policies" / "harnesssync-policy.json"
        assert policy_path.exists()

        policy = json.loads(policy_path.read_text())
        assert "rules" in policy
        assert len(policy["rules"]) == 2
        assert policy["rules"][0]["action"] == "deny"
        assert policy["rules"][0]["tool"] == "bash"
        assert policy["rules"][0]["pattern"] == "rm -rf *"

    def test_deny_rules_set_settings_flags(self, tmp_path):
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": [],
                "deny": ["Bash(rm *)"],
                "ask": [],
            }
        }
        adapter.sync_settings(settings)

        settings_path = tmp_path / ".gemini" / "settings.json"
        settings_data = json.loads(settings_path.read_text())
        assert settings_data.get("disableAlwaysAllow") is True
        assert settings_data.get("disableYoloMode") is True
        assert ".gemini/policies/harnesssync-policy.json" in settings_data.get("policyPaths", [])

    def test_allow_only_no_policy_file(self, tmp_path):
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Read", "Write"],
                "deny": [],
                "ask": [],
            }
        }
        adapter.sync_settings(settings)

        # Policy file should NOT be created when there are no deny rules
        policy_path = tmp_path / ".gemini" / "policies" / "harnesssync-policy.json"
        assert not policy_path.exists()

        # Settings should have tools.allowed
        settings_path = tmp_path / ".gemini" / "settings.json"
        settings_data = json.loads(settings_path.read_text())
        assert settings_data.get("tools", {}).get("allowed") == ["Read", "Write"]
        # Should NOT have disableAlwaysAllow/disableYoloMode
        assert "disableAlwaysAllow" not in settings_data
        assert "disableYoloMode" not in settings_data

    def test_empty_settings(self, tmp_path):
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)
        result = adapter.sync_settings({})
        assert result.synced == 0

    def test_policy_with_bare_tool_deny(self, tmp_path):
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": [],
                "deny": ["WebFetch"],
                "ask": [],
            }
        }
        adapter.sync_settings(settings)

        policy_path = tmp_path / ".gemini" / "policies" / "harnesssync-policy.json"
        policy = json.loads(policy_path.read_text())
        assert len(policy["rules"]) == 1
        assert policy["rules"][0]["tool"] == "webfetch"
        assert "pattern" not in policy["rules"][0]


# ---------------------------------------------------------------------------
# OpenCode adapter permission mapping tests
# ---------------------------------------------------------------------------

class TestOpenCodePermissionMapping:
    """Test OpenCode adapter grouped per-tool permission format."""

    def test_grouped_bash_permissions(self, tmp_path):
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Bash(npm *)"],
                "deny": ["Bash(rm -rf *)"],
                "ask": ["Bash(git push *)"],
            }
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        perm = config.get("permission", {})
        assert isinstance(perm.get("bash"), dict)
        assert perm["bash"]["npm *"] == "allow"
        assert perm["bash"]["rm -rf *"] == "deny"
        assert perm["bash"]["git push *"] == "ask"

    def test_bare_tool_permissions(self, tmp_path):
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Read"],
                "deny": ["Write"],
                "ask": [],
            }
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        perm = config.get("permission", {})
        # Read -> 'read' in OpenCode
        assert perm.get("read") == "allow"
        # Write -> 'edit' in OpenCode
        assert perm.get("edit") == "deny"

    def test_mixed_bare_and_pattern_same_tool(self, tmp_path):
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Bash(npm *)"],
                "deny": ["Bash"],
                "ask": [],
            }
        }
        result = adapter.sync_settings(settings)

        config = json.loads((tmp_path / "opencode.json").read_text())
        perm = config.get("permission", {})
        # Bash has both pattern and bare: should be a dict
        assert isinstance(perm.get("bash"), dict)
        assert perm["bash"]["npm *"] == "allow"
        assert perm["bash"]["*"] == "deny"

    def test_default_ask_wildcard_added(self, tmp_path):
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Bash(npm install *)"],
                "deny": [],
                "ask": [],
            }
        }
        adapter.sync_settings(settings)

        config = json.loads((tmp_path / "opencode.json").read_text())
        perm = config.get("permission", {})
        # Should have wildcard default
        assert isinstance(perm.get("bash"), dict)
        assert perm["bash"]["*"] == "ask"
        assert perm["bash"]["npm install *"] == "allow"

    def test_colon_to_space_translation(self, tmp_path):
        """Colons in Claude Code permission globs are translated to spaces for OpenCode.

        Claude Code uses colon-separated patterns (e.g. "git commit:*") while
        OpenCode expects space-separated keys in its permission dict.
        """
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Bash(git commit:*)"],
                "deny": [],
                "ask": [],
            }
        }
        adapter.sync_settings(settings)

        config = json.loads((tmp_path / "opencode.json").read_text())
        perm = config.get("permission", {})
        assert isinstance(perm.get("bash"), dict)
        # Colon should be translated to space
        assert "git commit *" in perm["bash"]
        assert perm["bash"]["git commit *"] == "allow"

    def test_empty_settings(self, tmp_path):
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)
        result = adapter.sync_settings({})
        assert result.synced == 0

    def test_removes_old_permissions_plural_key(self, tmp_path):
        from src.adapters.opencode import OpenCodeAdapter

        # Pre-populate with old format
        (tmp_path / "opencode.json").write_text(json.dumps({
            "permissions": {"old": "format"},
            "$schema": "https://opencode.ai/config.json",
        }))

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Read"],
                "deny": [],
                "ask": [],
            }
        }
        adapter.sync_settings(settings)

        config = json.loads((tmp_path / "opencode.json").read_text())
        assert "permissions" not in config  # Plural removed
        assert "permission" in config  # Singular present

    def test_ask_list_creates_ask_permissions(self, tmp_path):
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": [],
                "deny": [],
                "ask": ["Read", "Write", "Bash(git *)"],
            }
        }
        adapter.sync_settings(settings)

        config = json.loads((tmp_path / "opencode.json").read_text())
        perm = config.get("permission", {})
        assert perm.get("read") == "ask"
        assert perm.get("edit") == "ask"
        assert isinstance(perm.get("bash"), dict)
        assert perm["bash"]["git *"] == "ask"


# ---------------------------------------------------------------------------
# Round-trip tests: source -> extract -> adapter format
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """Test end-to-end flow: source settings -> extraction -> adapter output."""

    def _make_settings(self):
        """Return a realistic Claude Code settings dict."""
        return {
            "permissions": {
                "allow": ["Read", "Bash(npm install *)", "Bash(npm test *)"],
                "deny": ["Bash(rm -rf /)", "Bash(sudo *)"],
                "ask": ["Write", "Bash(git push *)"],
            },
            "approval_mode": "ask",
        }

    def test_roundtrip_codex(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        settings = self._make_settings()
        perms = extract_permissions(settings)

        # Verify extraction
        assert len(perms["allow"]) == 3
        assert len(perms["deny"]) == 2
        assert len(perms["ask"]) == 2

        # Sync to codex
        adapter = CodexAdapter(project_dir=tmp_path)
        # Create AGENTS.md first so deny warnings can be appended
        adapter.sync_rules([{"path": "CLAUDE.md", "content": "# Test"}])
        result = adapter.sync_settings(settings)
        assert result.synced == 1
        assert result.failed == 0

    def test_roundtrip_gemini(self, tmp_path):
        from src.adapters.gemini import GeminiAdapter

        settings = self._make_settings()
        perms = extract_permissions(settings)

        adapter = GeminiAdapter(project_dir=tmp_path)
        result = adapter.sync_settings(settings)
        assert result.synced == 1
        assert result.failed == 0

        # Verify policy file has correct deny rules
        policy_path = tmp_path / ".gemini" / "policies" / "harnesssync-policy.json"
        policy = json.loads(policy_path.read_text())
        assert len(policy["rules"]) == 2

    def test_roundtrip_opencode(self, tmp_path):
        from src.adapters.opencode import OpenCodeAdapter

        settings = self._make_settings()
        perms = extract_permissions(settings)

        adapter = OpenCodeAdapter(project_dir=tmp_path)
        result = adapter.sync_settings(settings)
        assert result.synced == 1
        assert result.failed == 0

        config = json.loads((tmp_path / "opencode.json").read_text())
        perm = config.get("permission", {})

        # Verify grouped format
        assert perm.get("read") == "allow"
        assert perm.get("edit") == "ask"  # Write -> edit
        assert isinstance(perm.get("bash"), dict)
        assert perm["bash"]["npm install *"] == "allow"
        assert perm["bash"]["npm test *"] == "allow"
        assert perm["bash"]["rm -rf /"] == "deny"
        assert perm["bash"]["sudo *"] == "deny"
        assert perm["bash"]["git push *"] == "ask"

    def test_all_adapters_handle_no_permissions(self, tmp_path):
        """All adapters should handle settings without permissions gracefully."""
        from src.adapters.codex import CodexAdapter
        from src.adapters.gemini import GeminiAdapter
        from src.adapters.opencode import OpenCodeAdapter

        settings = {"model": "claude-sonnet-4-20250514"}

        for AdapterClass in [CodexAdapter, GeminiAdapter, OpenCodeAdapter]:
            adapter_dir = tmp_path / AdapterClass.__name__
            adapter_dir.mkdir()
            adapter = AdapterClass(project_dir=adapter_dir)
            result = adapter.sync_settings(settings)
            assert result.failed == 0, f"{AdapterClass.__name__} failed with no permissions"
