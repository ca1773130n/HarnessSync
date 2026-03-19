from __future__ import annotations

"""Tests for Slice 2: MCP Enhancements.

Covers:
- Codex: timeout ms->sec conversion, oauth_scopes->scopes, elicitation passthrough,
  enabled_tools/disabled_tools passthrough, essential dropped, url+bearer_token
- Gemini: essential->trust:true, cwd passthrough, url passthrough,
  timeout/oauth_scopes dropped
- OpenCode: timeout passthrough, env passthrough, type discrimination (local/remote),
  essential/oauth_scopes dropped
- Cursor: timeout and url passthrough in .cursor/mcp.json
- Cline: timeout and url passthrough in .roo/mcp.json
- Windsurf: timeout and url passthrough in .codeium/windsurf/mcp_config.json
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.adapters.codex import CodexAdapter
from src.adapters.gemini import GeminiAdapter
from src.adapters.opencode import OpenCodeAdapter
from src.adapters.cursor import CursorAdapter
from src.adapters.cline import ClineAdapter
from src.adapters.windsurf import WindsurfAdapter


# ---------------------------------------------------------------------------
# Codex adapter MCP enhancement tests
# ---------------------------------------------------------------------------

class TestCodexMcpEnhancements:
    """Test Codex adapter MCP field translation."""

    def test_timeout_ms_to_sec_conversion(self, tmp_path):
        """timeout in ms should be converted to tool_timeout_sec in seconds."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "command": "node",
            "args": ["server.js"],
            "timeout": 30000,
        })
        assert result["command"] == "node"
        assert result["tool_timeout_sec"] == 30
        assert "timeout" not in result

    def test_timeout_ms_to_sec_rounding(self, tmp_path):
        """Non-round ms values should truncate to integer seconds."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({"command": "x", "timeout": 1500})
        assert result["tool_timeout_sec"] == 1

    def test_timeout_zero_dropped(self, tmp_path):
        """Zero timeout should not produce a tool_timeout_sec field."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({"command": "x", "timeout": 0})
        assert "tool_timeout_sec" not in result
        assert "timeout" not in result

    def test_timeout_negative_dropped(self, tmp_path):
        """Negative timeout should not produce a tool_timeout_sec field."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({"command": "x", "timeout": -1000})
        assert "tool_timeout_sec" not in result
        assert "timeout" not in result

    def test_oauth_scopes_mapped(self, tmp_path):
        """oauth_scopes should become scopes list."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "url": "https://example.com/mcp",
            "oauth_scopes": ["read", "write", "admin"],
        })
        assert result["scopes"] == ["read", "write", "admin"]
        assert "oauth_scopes" not in result

    def test_oauth_scopes_non_list_dropped(self, tmp_path):
        """Non-list oauth_scopes should be dropped."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "url": "https://example.com/mcp",
            "oauth_scopes": "read,write",
        })
        assert "scopes" not in result
        assert "oauth_scopes" not in result

    def test_elicitation_passthrough(self, tmp_path):
        """elicitation should pass through unchanged (Codex supports natively)."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "command": "node",
            "elicitation": True,
        })
        assert result["elicitation"] is True

    def test_elicitation_dict_passthrough(self, tmp_path):
        """elicitation dict config should pass through unchanged."""
        adapter = CodexAdapter(tmp_path)
        elicitation_config = {"enabled": True, "max_turns": 5}
        result = adapter._translate_mcp_fields({
            "command": "node",
            "elicitation": elicitation_config,
        })
        assert result["elicitation"] == elicitation_config

    def test_enabled_tools_passthrough(self, tmp_path):
        """enabled_tools should pass through directly."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "command": "node",
            "enabled_tools": ["tool_a", "tool_b"],
        })
        assert result["enabled_tools"] == ["tool_a", "tool_b"]

    def test_disabled_tools_passthrough(self, tmp_path):
        """disabled_tools should pass through directly."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "command": "node",
            "disabled_tools": ["tool_c"],
        })
        assert result["disabled_tools"] == ["tool_c"]

    def test_essential_dropped(self, tmp_path):
        """essential should be silently dropped."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "command": "node",
            "essential": True,
        })
        assert "essential" not in result

    def test_multiple_fields_combined(self, tmp_path):
        """All new fields should be translated together correctly."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "command": "node",
            "args": ["server.js"],
            "timeout": 60000,
            "oauth_scopes": ["admin"],
            "elicitation": True,
            "enabled_tools": ["read"],
            "disabled_tools": ["delete"],
            "essential": True,
        })
        assert result["tool_timeout_sec"] == 60
        assert result["scopes"] == ["admin"]
        assert result["elicitation"] is True
        assert result["enabled_tools"] == ["read"]
        assert result["disabled_tools"] == ["delete"]
        assert "essential" not in result
        assert "timeout" not in result
        assert "oauth_scopes" not in result
        # Original fields preserved
        assert result["command"] == "node"
        assert result["args"] == ["server.js"]

    def test_bearer_token_env_var_populated_for_remote_with_auth(self, tmp_path):
        """Remote URL with auth env var should set bearer_token_env_var."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "url": "https://mcp.example.com/api",
            "env": {
                "SENTRY_TOKEN": "secret123",
                "DEBUG": "true",
            },
        })
        assert result["bearer_token_env_var"] == "SENTRY_TOKEN"
        assert result["url"] == "https://mcp.example.com/api"

    def test_bearer_token_env_var_key_pattern(self, tmp_path):
        """Auth env var detection should be case-insensitive on key substrings."""
        adapter = CodexAdapter(tmp_path)
        for env_key in ["API_KEY", "auth_header", "Bearer_Value", "my_secret", "GH_TOKEN"]:
            result = adapter._translate_mcp_fields({
                "url": "https://example.com/mcp",
                "env": {env_key: "val"},
            })
            assert "bearer_token_env_var" in result, f"Expected bearer_token_env_var for env key '{env_key}'"
            assert result["bearer_token_env_var"] == env_key

    def test_bearer_token_env_var_not_set_for_remote_without_auth_env(self, tmp_path):
        """Remote URL without auth env var should NOT set bearer_token_env_var."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "url": "https://mcp.example.com/api",
            "env": {
                "DEBUG": "true",
                "LOG_LEVEL": "info",
            },
        })
        assert "bearer_token_env_var" not in result

    def test_bearer_token_env_var_not_set_for_remote_no_env(self, tmp_path):
        """Remote URL with no env dict should NOT set bearer_token_env_var."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "url": "https://mcp.example.com/api",
        })
        assert "bearer_token_env_var" not in result

    def test_bearer_token_env_var_not_set_for_stdio(self, tmp_path):
        """Stdio server (no url) with auth env var should NOT set bearer_token_env_var."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "command": "node",
            "args": ["server.js"],
            "env": {"API_KEY": "secret"},
        })
        assert "bearer_token_env_var" not in result

    def test_bearer_token_env_var_not_overridden_if_explicit(self, tmp_path):
        """Explicit bearer_token_env_var in source should not be overridden."""
        adapter = CodexAdapter(tmp_path)
        result = adapter._translate_mcp_fields({
            "url": "https://mcp.example.com/api",
            "bearer_token_env_var": "CUSTOM_VAR",
            "env": {"API_TOKEN": "secret"},
        })
        assert result["bearer_token_env_var"] == "CUSTOM_VAR"

    def test_sync_mcp_applies_translation(self, tmp_path):
        """sync_mcp should apply field translation before writing TOML."""
        adapter = CodexAdapter(tmp_path)
        servers = {
            "test-server": {
                "command": "node",
                "args": ["server.js"],
                "timeout": 45000,
                "essential": True,
                "enabled_tools": ["read_file"],
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1
        assert result.failed == 0

        # Read back the written config.toml and verify
        config_path = tmp_path / ".codex" / "config.toml"
        assert config_path.exists()
        content = config_path.read_text()
        assert "tool_timeout_sec = 45" in content
        assert "enabled_tools" in content
        assert "essential" not in content
        # timeout (ms) should not appear as raw field
        assert "timeout = 45000" not in content

    def test_sync_mcp_scoped_applies_translation(self, tmp_path):
        """sync_mcp_scoped should also apply field translation."""
        adapter = CodexAdapter(tmp_path)
        scoped_servers = {
            "scoped-server": {
                "config": {
                    "command": "python3",
                    "args": ["-m", "server"],
                    "timeout": 20000,
                    "essential": True,
                },
                "metadata": {"scope": "project"},
            }
        }
        result = adapter.sync_mcp_scoped(scoped_servers)
        assert result.failed == 0

        # Check the project-scope config
        config_path = tmp_path / ".codex" / "config.toml"
        assert config_path.exists()
        content = config_path.read_text()
        assert "tool_timeout_sec = 20" in content
        assert "essential" not in content


# ---------------------------------------------------------------------------
# Gemini adapter MCP enhancement tests
# ---------------------------------------------------------------------------

class TestGeminiMcpEnhancements:
    """Test Gemini adapter MCP field translation."""

    def test_essential_mapped_to_trust(self, tmp_path):
        """essential: true should map to trust: true."""
        adapter = GeminiAdapter(tmp_path)
        servers = {
            "core-server": {
                "command": "node",
                "args": ["server.js"],
                "essential": True,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        server_cfg = settings["mcpServers"]["core-server"]
        assert server_cfg["trust"] is True

    def test_essential_false_no_trust(self, tmp_path):
        """essential: false should not set trust."""
        adapter = GeminiAdapter(tmp_path)
        servers = {
            "optional-server": {
                "command": "node",
                "essential": False,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        server_cfg = settings["mcpServers"]["optional-server"]
        assert "trust" not in server_cfg

    def test_explicit_trust_not_overridden_by_essential(self, tmp_path):
        """If config already has trust field, essential should not override it."""
        adapter = GeminiAdapter(tmp_path)
        servers = {
            "server": {
                "command": "node",
                "essential": True,
                "trust": False,  # Explicit trust=false should win
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        server_cfg = settings["mcpServers"]["server"]
        # The explicit trust=False from the passthrough block should be present
        assert server_cfg["trust"] is False

    def test_cwd_passthrough(self, tmp_path):
        """cwd should pass through directly."""
        adapter = GeminiAdapter(tmp_path)
        servers = {
            "cwd-server": {
                "command": "node",
                "cwd": "/home/user/project",
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        server_cfg = settings["mcpServers"]["cwd-server"]
        assert server_cfg["cwd"] == "/home/user/project"

    def test_url_passthrough_for_remote(self, tmp_path):
        """url should be available in the output for remote servers."""
        adapter = GeminiAdapter(tmp_path)
        servers = {
            "remote-server": {
                "url": "https://mcp.example.com/api",
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        server_cfg = settings["mcpServers"]["remote-server"]
        # URL should be in the config (either as url or httpUrl)
        has_url = "url" in server_cfg or "httpUrl" in server_cfg
        assert has_url

    def test_timeout_dropped(self, tmp_path):
        """timeout should not appear in Gemini output (not supported)."""
        adapter = GeminiAdapter(tmp_path)
        servers = {
            "timeout-server": {
                "command": "node",
                "timeout": 30000,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        server_cfg = settings["mcpServers"]["timeout-server"]
        assert "timeout" not in server_cfg

    def test_oauth_scopes_dropped(self, tmp_path):
        """oauth_scopes should not appear in Gemini output (not supported)."""
        adapter = GeminiAdapter(tmp_path)
        servers = {
            "oauth-server": {
                "url": "https://mcp.example.com/api",
                "oauth_scopes": ["read", "write"],
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        server_cfg = settings["mcpServers"]["oauth-server"]
        assert "oauth_scopes" not in server_cfg

    def test_combined_fields(self, tmp_path):
        """Test all new Gemini fields together."""
        adapter = GeminiAdapter(tmp_path)
        servers = {
            "full-server": {
                "command": "node",
                "args": ["server.js"],
                "essential": True,
                "cwd": "/opt/mcp",
                "timeout": 30000,
                "oauth_scopes": ["admin"],
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        server_cfg = settings["mcpServers"]["full-server"]
        assert server_cfg["trust"] is True
        assert server_cfg["cwd"] == "/opt/mcp"
        assert "timeout" not in server_cfg
        assert "oauth_scopes" not in server_cfg
        assert "essential" not in server_cfg


# ---------------------------------------------------------------------------
# OpenCode adapter MCP enhancement tests
# ---------------------------------------------------------------------------

class TestOpenCodeMcpEnhancements:
    """Test OpenCode adapter MCP field translation."""

    def test_stdio_type_local(self, tmp_path):
        """Stdio transport (command) should produce type: local."""
        adapter = OpenCodeAdapter(tmp_path)
        servers = {
            "local-server": {
                "command": "node",
                "args": ["server.js"],
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        server_cfg = config["mcp"]["local-server"]
        assert server_cfg["type"] == "local"

    def test_url_type_remote(self, tmp_path):
        """URL transport should produce type: remote."""
        adapter = OpenCodeAdapter(tmp_path)
        servers = {
            "remote-server": {
                "url": "https://mcp.example.com/api",
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        server_cfg = config["mcp"]["remote-server"]
        assert server_cfg["type"] == "remote"
        assert server_cfg["url"] == "https://mcp.example.com/api"

    def test_timeout_passthrough_stdio(self, tmp_path):
        """timeout should pass through directly for stdio servers."""
        adapter = OpenCodeAdapter(tmp_path)
        servers = {
            "timed-server": {
                "command": "node",
                "args": ["server.js"],
                "timeout": 30000,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        server_cfg = config["mcp"]["timed-server"]
        assert server_cfg["timeout"] == 30000

    def test_timeout_passthrough_remote(self, tmp_path):
        """timeout should pass through directly for remote servers."""
        adapter = OpenCodeAdapter(tmp_path)
        servers = {
            "remote-timed": {
                "url": "https://mcp.example.com/api",
                "timeout": 60000,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        server_cfg = config["mcp"]["remote-timed"]
        assert server_cfg["timeout"] == 60000

    def test_env_passthrough_stdio(self, tmp_path):
        """env should map to environment for stdio servers."""
        adapter = OpenCodeAdapter(tmp_path)
        servers = {
            "env-server": {
                "command": "node",
                "env": {"API_KEY": "test123", "DEBUG": "true"},
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        server_cfg = config["mcp"]["env-server"]
        assert server_cfg["environment"] == {"API_KEY": "test123", "DEBUG": "true"}

    def test_env_passthrough_remote(self, tmp_path):
        """env should pass through for remote servers as env."""
        adapter = OpenCodeAdapter(tmp_path)
        servers = {
            "remote-env": {
                "url": "https://mcp.example.com/api",
                "env": {"TOKEN": "abc"},
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        server_cfg = config["mcp"]["remote-env"]
        assert server_cfg["env"] == {"TOKEN": "abc"}

    def test_essential_dropped(self, tmp_path):
        """essential should not appear in OpenCode output."""
        adapter = OpenCodeAdapter(tmp_path)
        servers = {
            "essential-server": {
                "command": "node",
                "essential": True,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        server_cfg = config["mcp"]["essential-server"]
        assert "essential" not in server_cfg

    def test_oauth_scopes_dropped(self, tmp_path):
        """oauth_scopes should not appear in OpenCode output."""
        adapter = OpenCodeAdapter(tmp_path)
        servers = {
            "oauth-server": {
                "command": "node",
                "oauth_scopes": ["read"],
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        server_cfg = config["mcp"]["oauth-server"]
        assert "oauth_scopes" not in server_cfg

    def test_combined_fields(self, tmp_path):
        """Test all OpenCode fields together."""
        adapter = OpenCodeAdapter(tmp_path)
        servers = {
            "full-server": {
                "command": "python3",
                "args": ["-m", "mcp_server"],
                "env": {"DEBUG": "1"},
                "timeout": 45000,
                "essential": True,
                "oauth_scopes": ["admin"],
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        config = json.loads((tmp_path / "opencode.json").read_text())
        server_cfg = config["mcp"]["full-server"]
        assert server_cfg["type"] == "local"
        assert server_cfg["timeout"] == 45000
        assert server_cfg["environment"] == {"DEBUG": "1"}
        assert "essential" not in server_cfg
        assert "oauth_scopes" not in server_cfg


# ---------------------------------------------------------------------------
# Cursor adapter MCP enhancement tests
# ---------------------------------------------------------------------------

class TestCursorMcpEnhancements:
    """Test Cursor adapter MCP field passthrough."""

    def test_timeout_passthrough(self, tmp_path):
        """timeout should pass through in .cursor/mcp.json."""
        adapter = CursorAdapter(tmp_path)
        servers = {
            "timed-server": {
                "command": "node",
                "args": ["server.js"],
                "timeout": 30000,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
        server_cfg = mcp_data["mcpServers"]["timed-server"]
        assert server_cfg["timeout"] == 30000

    def test_url_passthrough(self, tmp_path):
        """url should pass through in .cursor/mcp.json."""
        adapter = CursorAdapter(tmp_path)
        servers = {
            "remote-server": {
                "url": "https://mcp.example.com/api",
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
        server_cfg = mcp_data["mcpServers"]["remote-server"]
        assert server_cfg["url"] == "https://mcp.example.com/api"

    def test_timeout_and_url_combined(self, tmp_path):
        """Both timeout and url should pass through together."""
        adapter = CursorAdapter(tmp_path)
        servers = {
            "remote-timed": {
                "url": "https://mcp.example.com/api",
                "timeout": 15000,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
        server_cfg = mcp_data["mcpServers"]["remote-timed"]
        assert server_cfg["url"] == "https://mcp.example.com/api"
        assert server_cfg["timeout"] == 15000

    def test_no_timeout_no_field(self, tmp_path):
        """When no timeout is set, the field should not appear."""
        adapter = CursorAdapter(tmp_path)
        servers = {
            "basic-server": {
                "command": "node",
                "args": ["server.js"],
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads((tmp_path / ".cursor" / "mcp.json").read_text())
        server_cfg = mcp_data["mcpServers"]["basic-server"]
        assert "timeout" not in server_cfg


# ---------------------------------------------------------------------------
# Cline adapter MCP enhancement tests
# ---------------------------------------------------------------------------

class TestClineMcpEnhancements:
    """Test Cline adapter MCP field passthrough."""

    def test_timeout_passthrough(self, tmp_path):
        """timeout should pass through in .roo/mcp.json."""
        adapter = ClineAdapter(tmp_path)
        servers = {
            "timed-server": {
                "command": "node",
                "args": ["server.js"],
                "timeout": 30000,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads((tmp_path / ".roo" / "mcp.json").read_text())
        server_cfg = mcp_data["mcpServers"]["timed-server"]
        assert server_cfg["timeout"] == 30000

    def test_url_passthrough(self, tmp_path):
        """url should pass through in .roo/mcp.json."""
        adapter = ClineAdapter(tmp_path)
        servers = {
            "remote-server": {
                "url": "https://mcp.example.com/api",
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads((tmp_path / ".roo" / "mcp.json").read_text())
        server_cfg = mcp_data["mcpServers"]["remote-server"]
        assert server_cfg["url"] == "https://mcp.example.com/api"

    def test_timeout_and_url_combined(self, tmp_path):
        """Both timeout and url should pass through together."""
        adapter = ClineAdapter(tmp_path)
        servers = {
            "remote-timed": {
                "url": "https://mcp.example.com/api",
                "timeout": 25000,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads((tmp_path / ".roo" / "mcp.json").read_text())
        server_cfg = mcp_data["mcpServers"]["remote-timed"]
        assert server_cfg["url"] == "https://mcp.example.com/api"
        assert server_cfg["timeout"] == 25000

    def test_no_timeout_no_field(self, tmp_path):
        """When no timeout is set, the field should not appear."""
        adapter = ClineAdapter(tmp_path)
        servers = {
            "basic-server": {
                "command": "node",
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads((tmp_path / ".roo" / "mcp.json").read_text())
        server_cfg = mcp_data["mcpServers"]["basic-server"]
        assert "timeout" not in server_cfg


# ---------------------------------------------------------------------------
# Windsurf adapter MCP enhancement tests
# ---------------------------------------------------------------------------

class TestWindsurfMcpEnhancements:
    """Test Windsurf adapter MCP field passthrough."""

    def test_timeout_passthrough(self, tmp_path):
        """timeout should pass through in mcp_config.json."""
        adapter = WindsurfAdapter(tmp_path)
        servers = {
            "timed-server": {
                "command": "node",
                "args": ["server.js"],
                "timeout": 30000,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads(
            (tmp_path / ".codeium" / "windsurf" / "mcp_config.json").read_text()
        )
        server_cfg = mcp_data["mcpServers"]["timed-server"]
        assert server_cfg["timeout"] == 30000

    def test_url_passthrough_as_serverUrl(self, tmp_path):
        """url should map to serverUrl in Windsurf mcp_config.json."""
        adapter = WindsurfAdapter(tmp_path)
        servers = {
            "remote-server": {
                "url": "https://mcp.example.com/api",
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads(
            (tmp_path / ".codeium" / "windsurf" / "mcp_config.json").read_text()
        )
        server_cfg = mcp_data["mcpServers"]["remote-server"]
        assert server_cfg["serverUrl"] == "https://mcp.example.com/api"

    def test_timeout_and_url_combined(self, tmp_path):
        """Both timeout and url should pass through together."""
        adapter = WindsurfAdapter(tmp_path)
        servers = {
            "remote-timed": {
                "url": "https://mcp.example.com/api",
                "timeout": 50000,
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads(
            (tmp_path / ".codeium" / "windsurf" / "mcp_config.json").read_text()
        )
        server_cfg = mcp_data["mcpServers"]["remote-timed"]
        assert server_cfg["serverUrl"] == "https://mcp.example.com/api"
        assert server_cfg["timeout"] == 50000

    def test_no_timeout_no_field(self, tmp_path):
        """When no timeout is set, the field should not appear."""
        adapter = WindsurfAdapter(tmp_path)
        servers = {
            "basic-server": {
                "command": "node",
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced == 1

        mcp_data = json.loads(
            (tmp_path / ".codeium" / "windsurf" / "mcp_config.json").read_text()
        )
        server_cfg = mcp_data["mcpServers"]["basic-server"]
        assert "timeout" not in server_cfg


# ---------------------------------------------------------------------------
# Cross-adapter: dropped fields verification
# ---------------------------------------------------------------------------

class TestDroppedFields:
    """Verify that fields explicitly marked as 'dropped' do not leak through."""

    @pytest.fixture
    def full_source_config(self):
        """A source MCP config with all new fields set."""
        return {
            "command": "node",
            "args": ["server.js"],
            "env": {"KEY": "val"},
            "timeout": 30000,
            "essential": True,
            "oauth_scopes": ["read", "write"],
            "elicitation": True,
            "cwd": "/opt/project",
            "enabled_tools": ["tool_a"],
            "disabled_tools": ["tool_b"],
        }

    def test_codex_drops_essential(self, tmp_path, full_source_config):
        """Codex should drop essential."""
        adapter = CodexAdapter(tmp_path)
        result = adapter.sync_mcp({"s": full_source_config})
        assert result.synced == 1
        content = (tmp_path / ".codex" / "config.toml").read_text()
        assert "essential" not in content

    def test_gemini_drops_timeout(self, tmp_path, full_source_config):
        """Gemini should drop timeout."""
        adapter = GeminiAdapter(tmp_path)
        result = adapter.sync_mcp({"s": full_source_config})
        assert result.synced == 1
        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        assert "timeout" not in settings["mcpServers"]["s"]

    def test_gemini_drops_oauth_scopes(self, tmp_path, full_source_config):
        """Gemini should drop oauth_scopes."""
        adapter = GeminiAdapter(tmp_path)
        result = adapter.sync_mcp({"s": full_source_config})
        assert result.synced == 1
        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        assert "oauth_scopes" not in settings["mcpServers"]["s"]

    def test_gemini_drops_essential_key(self, tmp_path, full_source_config):
        """Gemini should not have 'essential' key (only 'trust')."""
        adapter = GeminiAdapter(tmp_path)
        result = adapter.sync_mcp({"s": full_source_config})
        assert result.synced == 1
        settings = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
        assert "essential" not in settings["mcpServers"]["s"]

    def test_opencode_drops_essential(self, tmp_path, full_source_config):
        """OpenCode should drop essential."""
        adapter = OpenCodeAdapter(tmp_path)
        result = adapter.sync_mcp({"s": full_source_config})
        assert result.synced == 1
        config = json.loads((tmp_path / "opencode.json").read_text())
        assert "essential" not in config["mcp"]["s"]

    def test_opencode_drops_oauth_scopes(self, tmp_path, full_source_config):
        """OpenCode should drop oauth_scopes."""
        adapter = OpenCodeAdapter(tmp_path)
        result = adapter.sync_mcp({"s": full_source_config})
        assert result.synced == 1
        config = json.loads((tmp_path / "opencode.json").read_text())
        assert "oauth_scopes" not in config["mcp"]["s"]
