from __future__ import annotations

"""Tests for Slice 6: New Settings Mapping.

Covers:
- Codex: modelOverrides -> [profiles.*] TOML sections (various shapes)
- Codex: attribution -> command_attribution (string, bool, dict forms)
- Gemini: respectGitignore -> fileFiltering.respectGitignore
- Skip behavior: verify skipped settings do NOT appear in any target output
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Codex modelOverrides -> profiles mapping tests
# ---------------------------------------------------------------------------

class TestCodexModelOverridesMapping:
    """Test Codex adapter modelOverrides -> [profiles.*] TOML sections."""

    def test_basic_model_overrides(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {
            "modelOverrides": {
                "planning": "opus",
                "coding": "sonnet",
                "review": "opus",
            }
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1
        assert result.failed == 0

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert '[profiles.planning]' in content
        assert 'model = "opus"' in content
        assert '[profiles.coding]' in content
        assert 'model = "sonnet"' in content
        assert '[profiles.review]' in content

    def test_single_model_override(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {
            "modelOverrides": {"default": "claude-sonnet-4-20250514"}
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert '[profiles.default]' in content
        assert 'model = "claude-sonnet-4-20250514"' in content

    def test_empty_model_overrides_dict(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"modelOverrides": {}}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        # No profiles section should appear
        assert '[profiles.' not in content

    def test_model_overrides_non_dict_ignored(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"modelOverrides": "not-a-dict"}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        # No profiles section should appear
        assert '[profiles.' not in content

    def test_model_overrides_skips_invalid_entries(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {
            "modelOverrides": {
                "planning": "opus",
                "": "empty-key",           # Invalid: empty key
                "coding": "",              # Invalid: empty value
                "review": 42,              # Invalid: non-string value
                "testing": "haiku",        # Valid
            }
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert '[profiles.planning]' in content
        assert '[profiles.testing]' in content
        # Invalid entries should not appear
        assert 'empty-key' not in content
        assert '[profiles.coding]' not in content

    def test_model_overrides_preserved_on_re_sync(self, tmp_path):
        """Profiles from modelOverrides should replace old profiles on re-sync."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        # First sync
        settings1 = {"modelOverrides": {"planning": "opus"}}
        adapter.sync_settings(settings1)

        # Second sync with different overrides
        settings2 = {"modelOverrides": {"coding": "sonnet"}}
        adapter.sync_settings(settings2)

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        # Old profile should be replaced
        assert '[profiles.planning]' not in content
        assert '[profiles.coding]' in content
        assert 'model = "sonnet"' in content

    def test_model_overrides_with_permissions(self, tmp_path):
        """modelOverrides and permissions should coexist in config.toml."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Read"],
                "deny": [],
                "ask": [],
            },
            "modelOverrides": {
                "planning": "opus",
            },
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'approval_policy = "on-request"' in content
        assert '[profiles.planning]' in content
        assert 'model = "opus"' in content


# ---------------------------------------------------------------------------
# Codex attribution -> command_attribution tests
# ---------------------------------------------------------------------------

class TestCodexAttributionMapping:
    """Test Codex adapter attribution -> command_attribution mapping."""

    def test_attribution_bool_true(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"attribution": True}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution = true' in content

    def test_attribution_bool_false(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"attribution": False}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution = false' in content

    def test_attribution_string_true(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"attribution": "true"}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution = true' in content

    def test_attribution_string_false(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"attribution": "false"}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution = false' in content

    def test_attribution_string_truthy(self, tmp_path):
        """Non-false truthy strings should map to true."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"attribution": "enabled"}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution = true' in content

    def test_attribution_dict_with_enabled_true(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"attribution": {"enabled": True, "format": "co-author"}}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution = true' in content

    def test_attribution_dict_with_enabled_false(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"attribution": {"enabled": False}}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution = false' in content

    def test_attribution_dict_with_enabled_string(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"attribution": {"enabled": "true"}}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution = true' in content

    def test_attribution_not_present(self, tmp_path):
        """When attribution is not in settings, command_attribution should not appear."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"some_other_key": "value"}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution' not in content

    def test_attribution_none(self, tmp_path):
        """Explicit None should not emit command_attribution."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {"attribution": None}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution' not in content

    def test_attribution_preserved_on_re_sync(self, tmp_path):
        """command_attribution should be updated on re-sync, not duplicated."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        # First sync with attribution true
        adapter.sync_settings({"attribution": True})
        config_path = tmp_path / ".codex" / "config.toml"
        content1 = config_path.read_text()
        assert 'command_attribution = true' in content1

        # Re-sync with attribution false
        adapter.sync_settings({"attribution": False})
        content2 = config_path.read_text()
        assert 'command_attribution = false' in content2
        # Should NOT have the old value
        assert content2.count('command_attribution') == 1

    def test_attribution_with_model_overrides(self, tmp_path):
        """Attribution and modelOverrides should coexist."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {
            "attribution": True,
            "modelOverrides": {"planning": "opus"},
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'command_attribution = true' in content
        assert '[profiles.planning]' in content
        assert 'model = "opus"' in content


# ---------------------------------------------------------------------------
# Gemini respectGitignore mapping tests
# ---------------------------------------------------------------------------

class TestGeminiRespectGitignoreMapping:
    """Test Gemini adapter respectGitignore -> fileFiltering.respectGitignore."""

    def test_respect_gitignore_true(self, tmp_path):
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {"respectGitignore": True}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        settings_path = tmp_path / ".gemini" / "settings.json"
        data = json.loads(settings_path.read_text())

        assert data.get('fileFiltering', {}).get('respectGitignore') is True

    def test_respect_gitignore_false(self, tmp_path):
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {"respectGitignore": False}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        settings_path = tmp_path / ".gemini" / "settings.json"
        data = json.loads(settings_path.read_text())

        assert data.get('fileFiltering', {}).get('respectGitignore') is False

    def test_respect_gitignore_not_present(self, tmp_path):
        """When respectGitignore is not in settings, fileFiltering should not appear."""
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {"some_other_key": "value"}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        settings_path = tmp_path / ".gemini" / "settings.json"
        data = json.loads(settings_path.read_text())

        assert 'fileFiltering' not in data

    def test_respect_gitignore_non_bool_ignored(self, tmp_path):
        """Non-boolean respectGitignore should not be mapped."""
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {"respectGitignore": "yes"}
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        settings_path = tmp_path / ".gemini" / "settings.json"
        data = json.loads(settings_path.read_text())

        assert 'fileFiltering' not in data

    def test_respect_gitignore_preserves_existing_settings(self, tmp_path):
        """respectGitignore should merge with existing settings.json content."""
        from src.adapters.gemini import GeminiAdapter

        # Pre-populate settings.json with existing content
        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir(parents=True)
        settings_path = gemini_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "mcpServers": {"test": {"command": "echo"}},
            "theme": "dark",
        }))

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {"respectGitignore": True}
        adapter.sync_settings(settings)

        data = json.loads(settings_path.read_text())
        assert data.get('fileFiltering', {}).get('respectGitignore') is True
        # Existing settings should be preserved
        assert data.get('theme') == 'dark'
        assert 'mcpServers' in data

    def test_respect_gitignore_preserves_existing_file_filtering(self, tmp_path):
        """respectGitignore should merge into existing fileFiltering, not replace it."""
        from src.adapters.gemini import GeminiAdapter

        gemini_dir = tmp_path / ".gemini"
        gemini_dir.mkdir(parents=True)
        settings_path = gemini_dir / "settings.json"
        settings_path.write_text(json.dumps({
            "fileFiltering": {"maxFileSize": 1048576},
        }))

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {"respectGitignore": True}
        adapter.sync_settings(settings)

        data = json.loads(settings_path.read_text())
        file_filtering = data.get('fileFiltering', {})
        assert file_filtering.get('respectGitignore') is True
        assert file_filtering.get('maxFileSize') == 1048576

    def test_respect_gitignore_with_permissions(self, tmp_path):
        """respectGitignore and permissions should coexist."""
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {
            "permissions": {
                "allow": ["Read"],
                "deny": [],
                "ask": [],
            },
            "respectGitignore": True,
        }
        result = adapter.sync_settings(settings)
        assert result.synced == 1

        settings_path = tmp_path / ".gemini" / "settings.json"
        data = json.loads(settings_path.read_text())

        assert data.get('fileFiltering', {}).get('respectGitignore') is True
        assert data.get('tools', {}).get('allowed') == ['Read']


# ---------------------------------------------------------------------------
# Skip behavior: verify skipped settings do NOT appear in any target output
# ---------------------------------------------------------------------------

class TestSkippedSettingsNotInOutput:
    """Verify that Claude Code-internal settings do not leak into target configs."""

    SKIPPED_KEYS = [
        'autoMemoryDirectory',
        'language',
        'cleanupPeriodDays',
    ]

    def test_codex_skips_internal_settings(self, tmp_path):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {
            "autoMemoryDirectory": "/home/user/.claude/memory",
            "language": "en",
            "cleanupPeriodDays": 30,
            "permissions": {"allow": ["Read"], "deny": [], "ask": []},
        }
        adapter.sync_settings(settings)

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        for key in self.SKIPPED_KEYS:
            assert key not in content, f"Skipped setting '{key}' leaked into Codex config"

    def test_gemini_skips_internal_settings(self, tmp_path):
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {
            "autoMemoryDirectory": "/home/user/.claude/memory",
            "language": "en",
            "cleanupPeriodDays": 30,
            "permissions": {"allow": ["Read"], "deny": [], "ask": []},
        }
        adapter.sync_settings(settings)

        settings_path = tmp_path / ".gemini" / "settings.json"
        data = json.loads(settings_path.read_text())

        for key in self.SKIPPED_KEYS:
            assert key not in data, f"Skipped setting '{key}' leaked into Gemini settings"

    def test_opencode_skips_internal_settings(self, tmp_path):
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "autoMemoryDirectory": "/home/user/.claude/memory",
            "language": "en",
            "cleanupPeriodDays": 30,
            "permissions": {"allow": ["Read"], "deny": [], "ask": []},
        }
        adapter.sync_settings(settings)

        config_path = tmp_path / "opencode.json"
        data = json.loads(config_path.read_text())

        for key in self.SKIPPED_KEYS:
            assert key not in data, f"Skipped setting '{key}' leaked into OpenCode config"

    def test_codex_model_overrides_not_in_gemini(self, tmp_path):
        """modelOverrides should not appear in Gemini output (skip rationale: no equivalent)."""
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {
            "modelOverrides": {"planning": "opus"},
            "permissions": {"allow": [], "deny": [], "ask": []},
        }
        adapter.sync_settings(settings)

        settings_path = tmp_path / ".gemini" / "settings.json"
        data = json.loads(settings_path.read_text())

        assert 'modelOverrides' not in data
        assert 'profiles' not in data

    def test_codex_model_overrides_not_in_opencode(self, tmp_path):
        """modelOverrides should not appear in OpenCode output."""
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "modelOverrides": {"planning": "opus"},
            "permissions": {"allow": [], "deny": [], "ask": []},
        }
        adapter.sync_settings(settings)

        config_path = tmp_path / "opencode.json"
        data = json.loads(config_path.read_text())

        assert 'modelOverrides' not in data
        assert 'profiles' not in data

    def test_attribution_not_in_gemini(self, tmp_path):
        """attribution should not appear in Gemini output."""
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(project_dir=tmp_path)

        settings = {
            "attribution": True,
            "permissions": {"allow": [], "deny": [], "ask": []},
        }
        adapter.sync_settings(settings)

        settings_path = tmp_path / ".gemini" / "settings.json"
        data = json.loads(settings_path.read_text())

        assert 'attribution' not in data
        assert 'command_attribution' not in data

    def test_attribution_not_in_opencode(self, tmp_path):
        """attribution should not appear in OpenCode output."""
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "attribution": True,
            "permissions": {"allow": [], "deny": [], "ask": []},
        }
        adapter.sync_settings(settings)

        config_path = tmp_path / "opencode.json"
        data = json.loads(config_path.read_text())

        assert 'attribution' not in data
        assert 'command_attribution' not in data

    def test_respect_gitignore_not_in_codex(self, tmp_path):
        """respectGitignore should not appear in Codex output."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(project_dir=tmp_path)

        settings = {
            "respectGitignore": True,
            "permissions": {"allow": [], "deny": [], "ask": []},
        }
        adapter.sync_settings(settings)

        config_path = tmp_path / ".codex" / "config.toml"
        content = config_path.read_text()

        assert 'respectGitignore' not in content
        assert 'fileFiltering' not in content

    def test_respect_gitignore_not_in_opencode(self, tmp_path):
        """respectGitignore should not appear in OpenCode output."""
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(project_dir=tmp_path)

        settings = {
            "respectGitignore": True,
            "permissions": {"allow": [], "deny": [], "ask": []},
        }
        adapter.sync_settings(settings)

        config_path = tmp_path / "opencode.json"
        data = json.loads(config_path.read_text())

        assert 'respectGitignore' not in data
        assert 'fileFiltering' not in data


# ---------------------------------------------------------------------------
# Codex _map_attribution unit tests
# ---------------------------------------------------------------------------

class TestCodexMapAttribution:
    """Unit test the static _map_attribution method directly."""

    def test_bool_true(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution(True) is True

    def test_bool_false(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution(False) is False

    def test_string_true(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution("true") is True

    def test_string_True_case_insensitive(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution("True") is True
        assert CodexAdapter._map_attribution("TRUE") is True

    def test_string_false(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution("false") is False

    def test_string_False_case_insensitive(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution("False") is False
        assert CodexAdapter._map_attribution("FALSE") is False

    def test_string_truthy(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution("enabled") is True
        assert CodexAdapter._map_attribution("yes") is True

    def test_dict_enabled_true(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution({"enabled": True}) is True

    def test_dict_enabled_false(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution({"enabled": False}) is False

    def test_dict_enabled_string(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution({"enabled": "true"}) is True
        assert CodexAdapter._map_attribution({"enabled": "false"}) is False

    def test_dict_no_enabled_key(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution({"format": "co-author"}) is None

    def test_none(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution(None) is None

    def test_int(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution(42) is None

    def test_empty_string(self):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._map_attribution("") is None


# ---------------------------------------------------------------------------
# Codex _map_model_overrides unit tests
# ---------------------------------------------------------------------------

class TestCodexMapModelOverrides:
    """Unit test the static _map_model_overrides method directly."""

    def test_basic_mapping(self):
        from src.adapters.codex import CodexAdapter
        result = CodexAdapter._map_model_overrides({
            "planning": "opus",
            "coding": "sonnet",
        })
        assert '[profiles.planning]' in result
        assert 'model = "opus"' in result
        assert '[profiles.coding]' in result
        assert 'model = "sonnet"' in result

    def test_empty_dict(self):
        from src.adapters.codex import CodexAdapter
        result = CodexAdapter._map_model_overrides({})
        assert result == ''

    def test_skips_empty_keys(self):
        from src.adapters.codex import CodexAdapter
        result = CodexAdapter._map_model_overrides({"": "opus"})
        assert result == ''

    def test_skips_empty_values(self):
        from src.adapters.codex import CodexAdapter
        result = CodexAdapter._map_model_overrides({"planning": ""})
        assert result == ''

    def test_skips_non_string_values(self):
        from src.adapters.codex import CodexAdapter
        result = CodexAdapter._map_model_overrides({"planning": 42})
        assert result == ''

    def test_mixed_valid_and_invalid(self):
        from src.adapters.codex import CodexAdapter
        result = CodexAdapter._map_model_overrides({
            "planning": "opus",
            "": "bad",
            "coding": "",
        })
        assert '[profiles.planning]' in result
        assert 'model = "opus"' in result
        assert 'bad' not in result
        assert '[profiles.coding]' not in result
