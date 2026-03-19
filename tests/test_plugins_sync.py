from __future__ import annotations

"""Tests for Slice 5: Plugin Sync.

Covers:
- Plugin discovery and metadata extraction (SourceReader.get_plugins)
- Equivalence lookup (PLUGIN_EQUIVALENTS + user override)
- Decomposition fallback (skills/agents/commands/mcp/hooks routed)
- Native plugin reference for Codex/Gemini/OpenCode
- Base adapter no-op behavior
- sync_plugins wired into all three sync_all methods
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def tmp_project(tmp_path):
    """Create a minimal project directory with plugin fixtures."""
    project = tmp_path / "project"
    project.mkdir()
    return project


@pytest.fixture
def plugin_install_dir(tmp_path):
    """Create a fake plugin install directory with skills/agents/commands/mcp/hooks."""
    install = tmp_path / "plugins" / "test-plugin"
    install.mkdir(parents=True)

    # Skills
    skill_dir = install / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: my-skill\ndescription: A skill\n---\nDo stuff.")

    # Agents
    agents_dir = install / "agents"
    agents_dir.mkdir()
    (agents_dir / "my-agent.md").write_text("---\nname: my-agent\ndescription: An agent\n---\n<role>Be helpful.</role>")

    # Commands
    commands_dir = install / "commands"
    commands_dir.mkdir()
    (commands_dir / "my-cmd.md").write_text("---\nname: my-cmd\ndescription: A command\n---\nDo a thing.")

    # MCP servers
    mcp_data = {
        "mcpServers": {
            "test-server": {
                "command": "node",
                "args": ["server.js"],
            }
        }
    }
    (install / ".mcp.json").write_text(json.dumps(mcp_data))

    # Hooks
    hooks_dir = install / "hooks"
    hooks_dir.mkdir()
    hooks_data = {
        "hooks": {
            "PostToolUse": [{
                "matcher": "Edit|Write",
                "hooks": [{"type": "command", "command": "echo synced"}]
            }]
        }
    }
    (hooks_dir / "hooks.json").write_text(json.dumps(hooks_data))

    # Plugin manifest
    manifest = {
        "name": "test-plugin",
        "version": "1.2.3",
        "description": "A test plugin",
        "mcpServers": {},
    }
    (install / "plugin.json").write_text(json.dumps(manifest))

    return install


@pytest.fixture
def cc_home_with_plugins(tmp_path, plugin_install_dir):
    """Create a cc_home with plugins registry and settings."""
    cc_home = tmp_path / ".claude"
    cc_home.mkdir()

    # Settings with enabledPlugins
    settings = {"enabledPlugins": {"test-plugin": True, "disabled-plugin": False}}
    (cc_home / "settings.json").write_text(json.dumps(settings))

    # Plugins registry
    plugins_dir = cc_home / "plugins"
    plugins_dir.mkdir()
    registry = {
        "plugins": {
            "test-plugin@1.2.3": [{
                "scope": "user",
                "installPath": str(plugin_install_dir),
                "version": "1.2.3",
            }],
        }
    }
    (plugins_dir / "installed_plugins.json").write_text(json.dumps(registry))

    return cc_home


# ─── Plugin Discovery Tests ─────────────────────────────────────────────


class TestPluginDiscovery:
    """Test SourceReader.get_plugins() metadata extraction."""

    def test_get_plugins_returns_full_metadata(self, cc_home_with_plugins, tmp_project, plugin_install_dir):
        from src.source_reader import SourceReader

        reader = SourceReader(scope="user", project_dir=tmp_project, cc_home=cc_home_with_plugins)
        plugins = reader.get_plugins()

        assert "test-plugin" in plugins
        meta = plugins["test-plugin"]
        assert meta["enabled"] is True
        assert meta["version"] == "1.2.3"
        assert meta["install_path"] == plugin_install_dir
        assert meta["has_skills"] is True
        assert meta["has_agents"] is True
        assert meta["has_commands"] is True
        assert meta["has_mcp"] is True
        assert meta["has_hooks"] is True
        assert isinstance(meta["manifest"], dict)
        assert meta["manifest"]["name"] == "test-plugin"

    def test_get_plugins_empty_when_no_registry(self, tmp_project, tmp_path):
        from src.source_reader import SourceReader

        cc_home = tmp_path / ".claude_empty"
        cc_home.mkdir()
        reader = SourceReader(scope="user", project_dir=tmp_project, cc_home=cc_home)
        plugins = reader.get_plugins()
        assert plugins == {}

    def test_get_plugins_detects_disabled(self, tmp_path, plugin_install_dir):
        """Disabled plugins should have enabled=False when explicitly disabled."""
        from src.source_reader import SourceReader

        cc_home = tmp_path / ".claude"
        cc_home.mkdir()
        settings = {"enabledPlugins": {"disabled-only": False}}
        (cc_home / "settings.json").write_text(json.dumps(settings))

        plugins_dir = cc_home / "plugins"
        plugins_dir.mkdir()
        registry = {
            "plugins": {
                "disabled-only@1.0.0": [{
                    "scope": "user",
                    "installPath": str(plugin_install_dir),
                    "version": "1.0.0",
                }],
            }
        }
        (plugins_dir / "installed_plugins.json").write_text(json.dumps(registry))

        reader = SourceReader(scope="user", project_dir=tmp_path / "proj", cc_home=cc_home)
        plugins = reader.get_plugins()
        # The plugin name extracted is "disabled-only" but enabledPlugins has it disabled
        assert "disabled-only" in plugins
        # enabled should be False because enabledPlugins explicitly lists it as disabled
        # and it's not in the enabled_set
        assert plugins["disabled-only"]["enabled"] is False

    def test_discover_all_includes_plugins(self, cc_home_with_plugins, tmp_project):
        from src.source_reader import SourceReader

        reader = SourceReader(scope="user", project_dir=tmp_project, cc_home=cc_home_with_plugins)
        data = reader.discover_all()
        assert "plugins" in data
        assert isinstance(data["plugins"], dict)


# ─── Plugin Registry / Equivalence Lookup Tests ─────────────────────────


class TestPluginRegistry:
    """Test PLUGIN_EQUIVALENTS and lookup functions."""

    def test_static_equivalents_structure(self):
        from src.plugin_registry import PLUGIN_EQUIVALENTS

        assert "sentry" in PLUGIN_EQUIVALENTS
        assert "codex" in PLUGIN_EQUIVALENTS["sentry"]
        assert PLUGIN_EQUIVALENTS["sentry"]["codex"] == "@sentry/codex-plugin"

    def test_lookup_native_equivalent_found(self):
        from src.plugin_registry import lookup_native_equivalent

        result = lookup_native_equivalent("sentry", "codex")
        assert result == "@sentry/codex-plugin"

    def test_lookup_native_equivalent_none(self):
        from src.plugin_registry import lookup_native_equivalent

        result = lookup_native_equivalent("context-mode", "codex")
        assert result is None

    def test_lookup_native_equivalent_unknown_plugin(self):
        from src.plugin_registry import lookup_native_equivalent

        result = lookup_native_equivalent("unknown-plugin", "codex")
        assert result is None

    def test_user_override_takes_precedence(self):
        from src.plugin_registry import lookup_native_equivalent

        user_overrides = {
            "sentry": {"codex": "my-custom-sentry-codex"},
        }
        result = lookup_native_equivalent("sentry", "codex", user_overrides)
        assert result == "my-custom-sentry-codex"

    def test_user_override_new_plugin(self):
        from src.plugin_registry import lookup_native_equivalent

        user_overrides = {
            "my-custom-plugin": {"codex": "codex-custom-equiv"},
        }
        result = lookup_native_equivalent("my-custom-plugin", "codex", user_overrides)
        assert result == "codex-custom-equiv"

    def test_load_user_plugin_map_from_config(self, tmp_project):
        from src.plugin_registry import load_user_plugin_map

        config = {
            "plugin_map": {
                "my-plugin": {"codex": "codex-equiv", "gemini": None},
            }
        }
        (tmp_project / ".harnesssync").write_text(json.dumps(config))
        result = load_user_plugin_map(tmp_project)
        assert result == config["plugin_map"]

    def test_load_user_plugin_map_no_file(self, tmp_project):
        from src.plugin_registry import load_user_plugin_map

        result = load_user_plugin_map(tmp_project)
        assert result == {}


# ─── Base Adapter No-Op Tests ────────────────────────────────────────────


class TestBaseAdapterPluginSync:
    """Test AdapterBase.sync_plugins default no-op and _find_native_plugin."""

    def test_base_sync_plugins_noop(self, tmp_project):
        """Base sync_plugins returns all plugins as skipped."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_project)
        # Use the grandparent's default by calling it directly
        from src.adapters.base import AdapterBase
        result = AdapterBase.sync_plugins(adapter, {"p1": {}, "p2": {}})
        assert result.skipped == 2
        assert result.synced == 0

    def test_find_native_plugin_with_registry(self, tmp_project):
        """_find_native_plugin should look up from PLUGIN_EQUIVALENTS."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_project)
        result = adapter._find_native_plugin("sentry", {})
        assert result == "@sentry/codex-plugin"

    def test_find_native_plugin_unknown(self, tmp_project):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_project)
        result = adapter._find_native_plugin("unknown-plugin", {})
        assert result is None

    def test_find_native_plugin_with_user_override(self, tmp_project):
        """_find_native_plugin should respect .harnesssync plugin_map."""
        from src.adapters.codex import CodexAdapter

        config = {"plugin_map": {"custom": {"codex": "codex-custom"}}}
        (tmp_project / ".harnesssync").write_text(json.dumps(config))

        adapter = CodexAdapter(tmp_project)
        result = adapter._find_native_plugin("custom", {})
        assert result == "codex-custom"


# ─── Codex Plugin Sync Tests ────────────────────────────────────────────


class TestCodexPluginSync:
    """Test Codex adapter sync_plugins with native + decompose."""

    def test_native_plugin_written_to_config_toml(self, tmp_project):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_project)
        plugins = {
            "sentry": {
                "enabled": True,
                "version": "1.0.0",
                "install_path": None,
                "has_skills": False,
                "has_agents": False,
                "has_commands": False,
                "has_mcp": False,
                "has_hooks": False,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.synced == 1
        assert any("native" in f for f in result.synced_files)

        # Check config.toml was written
        config_path = tmp_project / ".codex" / "config.toml"
        assert config_path.exists()
        content = config_path.read_text()
        assert "@sentry/codex-plugin" in content

    def test_decompose_plugin_routes_skills(self, tmp_project, plugin_install_dir):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_project)
        plugins = {
            "test-plugin": {
                "enabled": True,
                "version": "1.2.3",
                "install_path": plugin_install_dir,
                "has_skills": True,
                "has_agents": False,
                "has_commands": False,
                "has_mcp": False,
                "has_hooks": False,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.synced == 1
        assert any("decomposed" in f for f in result.synced_files)

        # Skills should have been synced
        skill_path = tmp_project / ".agents" / "skills" / "my-skill"
        assert skill_path.exists()

    def test_disabled_plugin_skipped(self, tmp_project):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_project)
        plugins = {
            "disabled-one": {
                "enabled": False,
                "version": "1.0.0",
                "install_path": None,
                "has_skills": False,
                "has_agents": False,
                "has_commands": False,
                "has_mcp": False,
                "has_hooks": False,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.skipped == 1
        assert result.synced == 0

    def test_sync_all_dispatches_plugins(self, tmp_project):
        """Codex sync_all should include 'plugins' in results."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_project)
        source_data = {
            "rules": [],
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp": {},
            "settings": {},
            "hooks": {},
            "plugins": {},
        }

        results = adapter.sync_all(source_data)
        assert "plugins" in results


# ─── Gemini Plugin Sync Tests ───────────────────────────────────────────


class TestGeminiPluginSync:
    """Test Gemini adapter sync_plugins with native + decompose."""

    def test_native_extension_written_to_settings(self, tmp_project):
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(tmp_project)
        plugins = {
            "linear": {
                "enabled": True,
                "version": "2.0.0",
                "install_path": None,
                "has_skills": False,
                "has_agents": False,
                "has_commands": False,
                "has_mcp": False,
                "has_hooks": False,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.synced == 1
        assert any("native" in f for f in result.synced_files)

        # Check settings.json was written
        settings_path = tmp_project / ".gemini" / "settings.json"
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "extensions" in data
        assert "linear-gemini-extension" in data["extensions"]

    def test_decompose_plugin_routes_agents(self, tmp_project, plugin_install_dir):
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(tmp_project)
        plugins = {
            "test-plugin": {
                "enabled": True,
                "version": "1.2.3",
                "install_path": plugin_install_dir,
                "has_skills": False,
                "has_agents": True,
                "has_commands": False,
                "has_mcp": False,
                "has_hooks": False,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.synced == 1

    def test_sync_all_dispatches_plugins(self, tmp_project):
        """Gemini sync_all should include 'plugins' in results."""
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(tmp_project)
        source_data = {
            "rules": [],
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp": {},
            "settings": {},
            "hooks": {},
            "plugins": {},
        }

        results = adapter.sync_all(source_data)
        assert "plugins" in results


# ─── OpenCode Plugin Sync Tests ─────────────────────────────────────────


class TestOpenCodePluginSync:
    """Test OpenCode adapter sync_plugins with native + decompose."""

    def test_native_plugin_written_to_json(self, tmp_project):
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(tmp_project)
        plugins = {
            "sentry": {
                "enabled": True,
                "version": "1.0.0",
                "install_path": None,
                "has_skills": False,
                "has_agents": False,
                "has_commands": False,
                "has_mcp": False,
                "has_hooks": False,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.synced == 1

        # Check opencode.json was written
        json_path = tmp_project / "opencode.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "plugins" in data
        assert any(p.get("id") == "@sentry/opencode-plugin" for p in data["plugins"])

    def test_hooks_skipped_for_opencode(self, tmp_project, plugin_install_dir):
        """OpenCode should skip hooks (TypeScript event hooks can't translate)."""
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(tmp_project)
        plugins = {
            "test-plugin": {
                "enabled": True,
                "version": "1.2.3",
                "install_path": plugin_install_dir,
                "has_skills": True,
                "has_agents": False,
                "has_commands": False,
                "has_mcp": False,
                "has_hooks": True,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.synced == 1  # Decomposed via skills
        assert any("hooks skipped" in f for f in result.skipped_files)

    def test_sync_all_dispatches_plugins(self, tmp_project):
        """OpenCode sync_all (via base) should include 'plugins' in results."""
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(tmp_project)
        source_data = {
            "rules": [],
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp": {},
            "settings": {},
            "hooks": {},
            "plugins": {},
        }

        results = adapter.sync_all(source_data)
        assert "plugins" in results


# ─── Orchestrator Section Filter Tests ───────────────────────────────────


class TestOrchestratorPluginFilter:
    """Test that orchestrator _apply_section_filter handles plugins."""

    def test_section_filter_includes_plugins(self, tmp_project):
        from src.orchestrator import SyncOrchestrator

        orch = SyncOrchestrator(project_dir=tmp_project, only_sections={"rules"})
        data = {
            "rules": [{"content": "rule1"}],
            "plugins": {"p1": {"enabled": True}},
        }
        filtered = orch._apply_section_filter(data)
        # plugins should be zeroed out since only_sections={"rules"}
        assert filtered["plugins"] == {}

    def test_section_filter_preserves_plugins_when_included(self, tmp_project):
        from src.orchestrator import SyncOrchestrator

        orch = SyncOrchestrator(project_dir=tmp_project, only_sections={"plugins"})
        data = {
            "rules": [{"content": "rule1"}],
            "plugins": {"p1": {"enabled": True}},
        }
        filtered = orch._apply_section_filter(data)
        assert filtered["plugins"] == {"p1": {"enabled": True}}
        assert filtered["rules"] == []

    def test_section_filter_skip_plugins(self, tmp_project):
        from src.orchestrator import SyncOrchestrator

        orch = SyncOrchestrator(project_dir=tmp_project, skip_sections={"plugins"})
        data = {
            "rules": [{"content": "rule1"}],
            "plugins": {"p1": {"enabled": True}},
        }
        filtered = orch._apply_section_filter(data)
        assert filtered["plugins"] == {}
        assert filtered["rules"] == [{"content": "rule1"}]


# ─── Decomposition Fallback Integration Tests ───────────────────────────


class TestDecompositionFallback:
    """Test that decomposition routes through existing pipelines."""

    def test_codex_decomposes_mcp(self, tmp_project, plugin_install_dir):
        """MCP servers from a plugin should be routed through sync_mcp."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_project)
        plugins = {
            "test-plugin": {
                "enabled": True,
                "version": "1.2.3",
                "install_path": plugin_install_dir,
                "has_skills": False,
                "has_agents": False,
                "has_commands": False,
                "has_mcp": True,
                "has_hooks": False,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.synced == 1

        # config.toml should have MCP servers
        config_path = tmp_project / ".codex" / "config.toml"
        assert config_path.exists()
        content = config_path.read_text()
        assert "test-server" in content

    def test_gemini_decomposes_commands(self, tmp_project, plugin_install_dir):
        """Commands from a plugin should be routed through sync_commands."""
        from src.adapters.gemini import GeminiAdapter

        adapter = GeminiAdapter(tmp_project)
        plugins = {
            "test-plugin": {
                "enabled": True,
                "version": "1.2.3",
                "install_path": plugin_install_dir,
                "has_skills": False,
                "has_agents": False,
                "has_commands": True,
                "has_mcp": False,
                "has_hooks": False,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.synced == 1

        # Commands should have been written
        cmd_path = tmp_project / ".gemini" / "commands" / "my-cmd.toml"
        assert cmd_path.exists()

    def test_opencode_decomposes_skills(self, tmp_project, plugin_install_dir):
        """Skills from a plugin should be routed through sync_skills."""
        from src.adapters.opencode import OpenCodeAdapter

        adapter = OpenCodeAdapter(tmp_project)
        plugins = {
            "test-plugin": {
                "enabled": True,
                "version": "1.2.3",
                "install_path": plugin_install_dir,
                "has_skills": True,
                "has_agents": False,
                "has_commands": False,
                "has_mcp": False,
                "has_hooks": False,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.synced == 1

    def test_plugin_with_no_content_skipped(self, tmp_project, tmp_path):
        """A plugin with no skills/agents/commands/mcp/hooks is skipped."""
        from src.adapters.codex import CodexAdapter

        # Create empty plugin dir
        empty_dir = tmp_path / "empty-plugin"
        empty_dir.mkdir()

        adapter = CodexAdapter(tmp_project)
        plugins = {
            "empty-plugin": {
                "enabled": True,
                "version": "0.1.0",
                "install_path": empty_dir,
                "has_skills": False,
                "has_agents": False,
                "has_commands": False,
                "has_mcp": False,
                "has_hooks": False,
                "manifest": {},
            }
        }

        result = adapter.sync_plugins(plugins)
        assert result.skipped == 1
        assert result.synced == 0
