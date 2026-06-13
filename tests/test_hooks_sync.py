from __future__ import annotations

"""Tests for Slice 4: Hooks Sync.

Covers:
- Hook normalization from settings.json format and hooks/hooks.json legacy format
- Event mapping for Codex (SessionStart, Stop, PostToolUse->AfterToolUse, PreToolUse skipped)
- Codex feature gate behavior (hooks written when flag set, AGENTS.md warning when not)
- Default no-op behavior in base adapter
- Orchestrator section filter includes hooks
- discover_all() includes hooks key
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.source_reader import SourceReader
from src.adapters.base import AdapterBase
from src.adapters.result import SyncResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# SourceReader.get_hooks() — settings.json format
# ---------------------------------------------------------------------------

class TestGetHooksFromSettings:
    """Test hook discovery from settings.json (new format)."""

    def test_user_scope_hooks(self, tmp_path):
        cc_home = tmp_path / ".claude"
        cc_home.mkdir()
        _write_json(cc_home / "settings.json", {
            "hooks": {
                "PreToolUse": [
                    {"type": "command", "command": "echo pre", "matcher": "Edit|Write"}
                ],
                "SessionStart": [
                    {"type": "command", "command": "echo start"}
                ],
            }
        })
        reader = SourceReader(scope="user", cc_home=cc_home)
        result = reader.get_hooks()
        hooks = result["hooks"]
        assert len(hooks) == 2

        pre = [h for h in hooks if h["event"] == "PreToolUse"][0]
        assert pre["type"] == "shell"  # "command" normalized to "shell"
        assert pre["command"] == "echo pre"
        assert pre["matcher"] == "Edit|Write"
        assert pre["scope"] == "user"

        start = [h for h in hooks if h["event"] == "SessionStart"][0]
        assert start["type"] == "shell"
        assert start["command"] == "echo start"
        assert "matcher" not in start  # No matcher set

    def test_project_scope_hooks(self, tmp_path):
        project_dir = tmp_path / "project"
        settings_dir = project_dir / ".claude"
        settings_dir.mkdir(parents=True)
        _write_json(settings_dir / "settings.json", {
            "hooks": {
                "PostToolUse": [
                    {"type": "command", "command": "echo post", "matcher": "Bash"}
                ],
            }
        })
        reader = SourceReader(scope="project", project_dir=project_dir, cc_home=tmp_path / ".claude_empty")
        result = reader.get_hooks()
        hooks = result["hooks"]
        assert len(hooks) == 1
        assert hooks[0]["event"] == "PostToolUse"
        assert hooks[0]["scope"] == "project"

    def test_http_hook_from_settings(self, tmp_path):
        cc_home = tmp_path / ".claude"
        cc_home.mkdir()
        _write_json(cc_home / "settings.json", {
            "hooks": {
                "Stop": [
                    {"type": "http", "url": "https://example.com/hook", "timeout": 5000}
                ],
            }
        })
        reader = SourceReader(scope="user", cc_home=cc_home)
        result = reader.get_hooks()
        hooks = result["hooks"]
        assert len(hooks) == 1
        assert hooks[0]["type"] == "http"
        assert hooks[0]["url"] == "https://example.com/hook"
        assert hooks[0]["timeout"] == 5000

    def test_empty_hooks(self, tmp_path):
        cc_home = tmp_path / ".claude"
        cc_home.mkdir()
        _write_json(cc_home / "settings.json", {"hooks": {}})
        reader = SourceReader(scope="user", cc_home=cc_home)
        result = reader.get_hooks()
        assert result == {"hooks": []}

    def test_no_settings_file(self, tmp_path):
        cc_home = tmp_path / ".claude"
        cc_home.mkdir()
        reader = SourceReader(scope="user", cc_home=cc_home)
        result = reader.get_hooks()
        assert result == {"hooks": []}


# ---------------------------------------------------------------------------
# SourceReader.get_hooks() — legacy hooks/hooks.json format
# ---------------------------------------------------------------------------

class TestGetHooksFromLegacy:
    """Test hook discovery from hooks/hooks.json (legacy plugin format)."""

    def test_legacy_hooks_json(self, tmp_path):
        project_dir = tmp_path / "project"
        hooks_dir = project_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        _write_json(hooks_dir / "hooks.json", {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Edit|Write|MultiEdit",
                        "hooks": [
                            {"type": "command", "command": "python3 sync.py"}
                        ]
                    }
                ],
                "SessionStart": [
                    {
                        "hooks": [
                            {"type": "command", "command": "python3 startup.py"}
                        ]
                    }
                ],
            }
        })
        reader = SourceReader(scope="project", project_dir=project_dir, cc_home=tmp_path / ".claude_empty")
        result = reader.get_hooks()
        hooks = result["hooks"]
        assert len(hooks) == 2

        post = [h for h in hooks if h["event"] == "PostToolUse"][0]
        assert post["type"] == "shell"
        assert post["command"] == "python3 sync.py"
        assert post["matcher"] == "Edit|Write|MultiEdit"
        assert post["scope"] == "project"

        start = [h for h in hooks if h["event"] == "SessionStart"][0]
        assert start["type"] == "shell"
        assert start["command"] == "python3 startup.py"
        assert "matcher" not in start  # No matcher from legacy group without matcher key

    def test_merged_from_both_sources(self, tmp_path):
        """settings.json hooks + legacy hooks/hooks.json are both included."""
        cc_home = tmp_path / ".claude"
        cc_home.mkdir()
        _write_json(cc_home / "settings.json", {
            "hooks": {
                "PreToolUse": [{"type": "command", "command": "echo user-pre"}]
            }
        })

        project_dir = tmp_path / "project"
        hooks_dir = project_dir / "hooks"
        hooks_dir.mkdir(parents=True)
        _write_json(hooks_dir / "hooks.json", {
            "hooks": {
                "PostToolUse": [
                    {
                        "matcher": "Edit",
                        "hooks": [{"type": "command", "command": "echo legacy-post"}]
                    }
                ]
            }
        })

        reader = SourceReader(scope="all", project_dir=project_dir, cc_home=cc_home)
        result = reader.get_hooks()
        hooks = result["hooks"]
        assert len(hooks) == 2
        events = {h["event"] for h in hooks}
        assert events == {"PreToolUse", "PostToolUse"}


# ---------------------------------------------------------------------------
# discover_all() includes hooks
# ---------------------------------------------------------------------------

class TestDiscoverAllHooks:
    """Test that discover_all() includes the hooks key."""

    def test_hooks_key_present(self, tmp_path):
        cc_home = tmp_path / ".claude"
        cc_home.mkdir()
        reader = SourceReader(scope="user", cc_home=cc_home)
        data = reader.discover_all()
        assert "hooks" in data
        assert isinstance(data["hooks"], dict)
        assert "hooks" in data["hooks"]


# ---------------------------------------------------------------------------
# Base adapter default no-op
# ---------------------------------------------------------------------------

class TestBaseAdapterSyncHooks:
    """Test the default no-op sync_hooks in AdapterBase."""

    def test_no_op_returns_all_skipped(self, tmp_path):
        """Default implementation skips all hooks."""
        # Create a concrete subclass for testing
        class DummyAdapter(AdapterBase):
            @property
            def target_name(self) -> str:
                return "dummy"
            def sync_rules(self, rules): return SyncResult()
            def sync_skills(self, skills): return SyncResult()
            def sync_agents(self, agents): return SyncResult()
            def sync_commands(self, commands): return SyncResult()
            def sync_mcp(self, mcp): return SyncResult()
            def sync_settings(self, settings): return SyncResult()

        adapter = DummyAdapter(tmp_path)
        hooks_data = {
            "hooks": [
                {"event": "PreToolUse", "type": "shell", "command": "echo 1"},
                {"event": "Stop", "type": "shell", "command": "echo 2"},
            ]
        }
        result = adapter.sync_hooks(hooks_data)
        assert result.skipped == 2
        assert result.synced == 0
        assert result.failed == 0

    def test_no_op_empty_hooks(self, tmp_path):
        class DummyAdapter(AdapterBase):
            @property
            def target_name(self) -> str:
                return "dummy"
            def sync_rules(self, rules): return SyncResult()
            def sync_skills(self, skills): return SyncResult()
            def sync_agents(self, agents): return SyncResult()
            def sync_commands(self, commands): return SyncResult()
            def sync_mcp(self, mcp): return SyncResult()
            def sync_settings(self, settings): return SyncResult()

        adapter = DummyAdapter(tmp_path)
        result = adapter.sync_hooks({})
        assert result.skipped == 0

    def test_hooks_wired_into_sync_all(self, tmp_path):
        """sync_all() dispatches sync_hooks()."""
        class DummyAdapter(AdapterBase):
            @property
            def target_name(self) -> str:
                return "dummy"
            def sync_rules(self, rules): return SyncResult()
            def sync_skills(self, skills): return SyncResult()
            def sync_agents(self, agents): return SyncResult()
            def sync_commands(self, commands): return SyncResult()
            def sync_mcp(self, mcp): return SyncResult()
            def sync_settings(self, settings): return SyncResult()

        adapter = DummyAdapter(tmp_path)
        source_data = {
            "hooks": {
                "hooks": [
                    {"event": "PreToolUse", "type": "shell", "command": "echo x"},
                ]
            }
        }
        results = adapter.sync_all(source_data)
        assert "hooks" in results
        assert results["hooks"].skipped == 1  # Default no-op skips all


# ---------------------------------------------------------------------------
# Codex adapter — hooks sync
# ---------------------------------------------------------------------------

class TestCodexHooksSync:
    """Test CodexAdapter.sync_hooks() event mapping and feature gate."""

    def _make_adapter(self, tmp_path):
        from src.adapters.codex import CodexAdapter
        return CodexAdapter(tmp_path)

    def test_event_mapping_session_start(self, tmp_path):
        """SessionStart maps directly to SessionStart in Codex."""
        adapter = self._make_adapter(tmp_path)
        # Enable feature gate
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[features]\nhooks = true\n')

        hooks = {"hooks": [
            {"event": "SessionStart", "type": "shell", "command": "echo start", "scope": "user"},
        ]}
        result = adapter.sync_hooks(hooks)
        assert result.synced == 1
        content = (config_dir / "config.toml").read_text()
        assert "[[hooks.SessionStart]]" in content
        assert 'command = "echo start"' in content

    def test_event_mapping_stop(self, tmp_path):
        """Stop maps directly to Stop in Codex."""
        adapter = self._make_adapter(tmp_path)
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[features]\nhooks = true\n')

        hooks = {"hooks": [
            {"event": "Stop", "type": "shell", "command": "echo stop", "scope": "user"},
        ]}
        result = adapter.sync_hooks(hooks)
        assert result.synced == 1
        content = (config_dir / "config.toml").read_text()
        assert "[[hooks.Stop]]" in content

    def test_event_mapping_post_tool_use_renamed(self, tmp_path):
        """PostToolUse is renamed to AfterToolUse in Codex."""
        adapter = self._make_adapter(tmp_path)
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[features]\nhooks = true\n')

        hooks = {"hooks": [
            {"event": "PostToolUse", "type": "shell", "command": "echo post", "matcher": "Edit", "scope": "user"},
        ]}
        result = adapter.sync_hooks(hooks)
        assert result.synced == 1
        content = (config_dir / "config.toml").read_text()
        assert "[[hooks.AfterToolUse]]" in content
        assert "PostToolUse" not in content.split("# Hooks")[1] if "# Hooks" in content else True

    def test_pre_tool_use_skipped(self, tmp_path):
        """PreToolUse is skipped (unsupported by Codex)."""
        adapter = self._make_adapter(tmp_path)
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[features]\nhooks = true\n')

        hooks = {"hooks": [
            {"event": "PreToolUse", "type": "shell", "command": "echo pre", "scope": "user"},
        ]}
        result = adapter.sync_hooks(hooks)
        assert result.skipped >= 1
        assert result.synced == 0

    def test_http_hooks_skipped(self, tmp_path):
        """HTTP hooks are skipped (Codex is shell-only)."""
        adapter = self._make_adapter(tmp_path)
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[features]\nhooks = true\n')

        hooks = {"hooks": [
            {"event": "Stop", "type": "http", "url": "https://example.com/hook", "scope": "user"},
        ]}
        result = adapter.sync_hooks(hooks)
        assert result.skipped == 1
        assert result.synced == 0

    def test_feature_gate_disabled_documents_in_agents_md(self, tmp_path):
        """When feature gate is off, hooks are documented in AGENTS.md, not written to config."""
        adapter = self._make_adapter(tmp_path)
        # Create AGENTS.md with managed section
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "<!-- Managed by HarnessSync -->\nRules\n<!-- End HarnessSync managed content -->"
        )

        hooks = {"hooks": [
            {"event": "SessionStart", "type": "shell", "command": "echo start", "scope": "user"},
        ]}
        result = adapter.sync_hooks(hooks)
        # Hooks should be skipped (not written to config.toml)
        assert result.skipped >= 1
        assert result.synced == 0

        # Check AGENTS.md has the documentation
        content = agents_md.read_text()
        assert "Available Hooks" in content
        assert "features" in content.lower() or "hooks = true" in content

    def test_feature_gate_enabled_writes_config(self, tmp_path):
        """When feature gate is on, hooks are written to config.toml."""
        adapter = self._make_adapter(tmp_path)
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text(
            '[features]\nhooks = true\n\nsandbox_mode = "workspace-write"\n'
        )

        hooks = {"hooks": [
            {"event": "SessionStart", "type": "shell", "command": "echo start", "scope": "user"},
            {"event": "PostToolUse", "type": "shell", "command": "echo post", "matcher": "Edit", "scope": "project"},
        ]}
        result = adapter.sync_hooks(hooks)
        assert result.synced == 2
        content = (config_dir / "config.toml").read_text()
        assert "[[hooks.SessionStart]]" in content
        assert "[[hooks.AfterToolUse]]" in content
        assert 'matcher = "Edit"' in content

    def test_mixed_hooks_with_skips(self, tmp_path):
        """Mix of supported and unsupported hooks."""
        adapter = self._make_adapter(tmp_path)
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[features]\nhooks = true\n')

        hooks = {"hooks": [
            {"event": "SessionStart", "type": "shell", "command": "echo start", "scope": "user"},
            {"event": "PreToolUse", "type": "shell", "command": "echo pre", "scope": "user"},
            {"event": "Stop", "type": "http", "url": "https://example.com", "scope": "user"},
        ]}
        result = adapter.sync_hooks(hooks)
        assert result.synced == 1   # Only SessionStart
        assert result.skipped == 2  # PreToolUse + HTTP Stop


# ---------------------------------------------------------------------------
# Orchestrator section filter
# ---------------------------------------------------------------------------

class TestOrchestratorHooksFilter:
    """Test that _apply_section_filter handles hooks key."""

    def test_hooks_filtered_by_only_sections(self, tmp_path):
        from src.orchestrator import SyncOrchestrator
        orch = SyncOrchestrator(
            project_dir=tmp_path,
            only_sections={"rules"},
        )
        data = {
            "rules": [{"content": "test"}],
            "hooks": {"hooks": [{"event": "Stop"}]},
            "settings": {"key": "val"},
        }
        filtered = orch._apply_section_filter(data)
        # hooks should be zeroed out (not in only_sections)
        assert filtered["hooks"] == {}
        # rules should remain
        assert filtered["rules"] == [{"content": "test"}]

    def test_hooks_included_when_in_only_sections(self, tmp_path):
        from src.orchestrator import SyncOrchestrator
        orch = SyncOrchestrator(
            project_dir=tmp_path,
            only_sections={"rules", "hooks"},
        )
        data = {
            "rules": [{"content": "test"}],
            "hooks": {"hooks": [{"event": "Stop"}]},
            "settings": {"key": "val"},
        }
        filtered = orch._apply_section_filter(data)
        assert filtered["hooks"] == {"hooks": [{"event": "Stop"}]}
        assert filtered["settings"] == {}

    def test_hooks_filtered_by_skip_sections(self, tmp_path):
        from src.orchestrator import SyncOrchestrator
        orch = SyncOrchestrator(
            project_dir=tmp_path,
            skip_sections={"hooks"},
        )
        data = {
            "rules": [{"content": "test"}],
            "hooks": {"hooks": [{"event": "Stop"}]},
        }
        filtered = orch._apply_section_filter(data)
        assert filtered["hooks"] == {}
        assert filtered["rules"] == [{"content": "test"}]


# ---------------------------------------------------------------------------
# Codex feature gate unit test
# ---------------------------------------------------------------------------

class TestCodexFeatureGate:
    """Test _codex_hooks_feature_enabled detection."""

    def test_feature_enabled(self, tmp_path):
        from src.adapters.codex import CodexAdapter
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[features]\nhooks = true\n')
        assert CodexAdapter._codex_hooks_feature_enabled(config_dir / "config.toml") is True

    def test_feature_disabled(self, tmp_path):
        from src.adapters.codex import CodexAdapter
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[features]\nhooks = false\n')
        assert CodexAdapter._codex_hooks_feature_enabled(config_dir / "config.toml") is False

    def test_feature_not_set(self, tmp_path):
        from src.adapters.codex import CodexAdapter
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('sandbox_mode = "workspace-write"\n')
        assert CodexAdapter._codex_hooks_feature_enabled(config_dir / "config.toml") is False

    def test_no_config_file(self, tmp_path):
        from src.adapters.codex import CodexAdapter
        assert CodexAdapter._codex_hooks_feature_enabled(tmp_path / "nonexistent.toml") is False


# ---------------------------------------------------------------------------
# Integration: sync_all() dispatches sync_hooks() in adapter overrides
# ---------------------------------------------------------------------------

class TestCodexSyncAllDispatchesHooks:
    """Verify CodexAdapter.sync_all() dispatches sync_hooks() and includes 'hooks' in results."""

    def test_sync_all_includes_hooks_in_results(self, tmp_path):
        """CodexAdapter.sync_all() must include 'hooks' key in returned results dict."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_path)
        # Enable feature gate so hooks are actually written
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[features]\nhooks = true\n')

        source_data = {
            "rules": [{"path": Path("CLAUDE.md"), "content": "# Test rule"}],
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp": {},
            "settings": {},
            "hooks": {
                "hooks": [
                    {"event": "SessionStart", "type": "shell", "command": "echo start", "scope": "user"},
                    {"event": "PostToolUse", "type": "shell", "command": "echo post", "matcher": "Edit", "scope": "project"},
                ]
            },
        }
        results = adapter.sync_all(source_data)
        assert "hooks" in results, "sync_all() must dispatch sync_hooks() and include 'hooks' in results"
        assert results["hooks"].synced == 2
        assert results["hooks"].failed == 0

    def test_sync_all_hooks_empty_source(self, tmp_path):
        """sync_all() with no hooks data still includes 'hooks' key with zero counts."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_path)
        source_data = {
            "rules": [],
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp": {},
            "settings": {},
            "hooks": {},
        }
        results = adapter.sync_all(source_data)
        assert "hooks" in results
        assert results["hooks"].synced == 0
        assert results["hooks"].failed == 0

    def test_sync_all_hooks_with_skipped_events(self, tmp_path):
        """sync_all() correctly propagates skipped hooks (e.g., PreToolUse unsupported by Codex)."""
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_path)
        config_dir = tmp_path / ".codex"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text('[features]\nhooks = true\n')

        source_data = {
            "rules": [],
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp": {},
            "settings": {},
            "hooks": {
                "hooks": [
                    {"event": "PreToolUse", "type": "shell", "command": "echo pre", "scope": "user"},
                ]
            },
        }
        results = adapter.sync_all(source_data)
        assert "hooks" in results
        assert results["hooks"].skipped >= 1
        assert results["hooks"].synced == 0
