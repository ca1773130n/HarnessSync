#!/usr/bin/env python3
"""Verification script for Task 2: GeminiAdapter sync_mcp and sync_settings."""

import json
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.adapters.gemini import GeminiAdapter


def test_sync_mcp_stdio():
    """Test sync_mcp with stdio server (command+args+env)."""
    print("TEST 1: sync_mcp with stdio server...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Create MCP server config (stdio)
        mcp_servers = {
            "test-server": {
                "command": "npx",
                "args": ["-y", "test-package"],
                "env": {
                    "API_KEY": "${MY_API_KEY}",
                    "DEBUG": "true"
                },
                "timeout": 30000
            }
        }

        # Sync MCP servers
        result = adapter.sync_mcp(mcp_servers)

        # Verify result
        assert result.synced == 1, f"Expected synced=1, got {result.synced}"

        # Verify settings.json exists and has correct structure
        settings_path = project_dir / ".gemini" / "settings.json"
        assert settings_path.exists(), "settings.json not created"

        with open(settings_path, 'r') as f:
            settings = json.load(f)

        assert "mcpServers" in settings, "mcpServers not in settings.json"
        assert "test-server" in settings["mcpServers"], "test-server not found"

        server = settings["mcpServers"]["test-server"]
        assert server["command"] == "npx", "Command mismatch"
        assert server["args"] == ["-y", "test-package"], "Args mismatch"
        assert server["env"]["API_KEY"] == "${MY_API_KEY}", "Env var not preserved"
        assert server["timeout"] == 30000, "Timeout mismatch"

    print("  ✓ sync_mcp with stdio server works correctly")


def test_sync_mcp_url():
    """Test sync_mcp with URL server."""
    print("TEST 2: sync_mcp with URL server...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Create MCP server config (URL - SSE)
        mcp_servers = {
            "sse-server": {
                "url": "https://api.example.com/sse"
            },
            "http-server": {
                "url": "https://api.example.com/mcp"
            }
        }

        # Sync MCP servers
        result = adapter.sync_mcp(mcp_servers)

        # Verify result
        assert result.synced == 2, f"Expected synced=2, got {result.synced}"

        # Verify settings.json
        settings_path = project_dir / ".gemini" / "settings.json"
        with open(settings_path, 'r') as f:
            settings = json.load(f)

        # SSE server should use "url" field
        sse = settings["mcpServers"]["sse-server"]
        assert "url" in sse, "SSE server should have 'url' field"
        assert sse["url"] == "https://api.example.com/sse", "SSE URL mismatch"

        # HTTP server should use "httpUrl" field
        http = settings["mcpServers"]["http-server"]
        assert "httpUrl" in http, "HTTP server should have 'httpUrl' field"
        assert http["httpUrl"] == "https://api.example.com/mcp", "HTTP URL mismatch"

    print("  ✓ sync_mcp with URL server works correctly")


def test_sync_mcp_mixed():
    """Test sync_mcp with mixed server types."""
    print("TEST 3: sync_mcp with mixed server types...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Create mixed MCP server configs
        mcp_servers = {
            "stdio-server": {
                "command": "node",
                "args": ["server.js"]
            },
            "url-server": {
                "url": "https://api.example.com/sse"
            }
        }

        # Sync MCP servers
        result = adapter.sync_mcp(mcp_servers)

        # Verify both types present
        assert result.synced == 2, f"Expected synced=2, got {result.synced}"

        settings_path = project_dir / ".gemini" / "settings.json"
        with open(settings_path, 'r') as f:
            settings = json.load(f)

        assert "stdio-server" in settings["mcpServers"], "stdio-server not found"
        assert "url-server" in settings["mcpServers"], "url-server not found"

        # Verify structure
        assert "command" in settings["mcpServers"]["stdio-server"], "stdio-server missing command"
        assert "url" in settings["mcpServers"]["url-server"], "url-server missing url"

    print("  ✓ sync_mcp with mixed servers works correctly")


def test_sync_mcp_preserves_existing():
    """Test sync_mcp preserves existing settings.json content."""
    print("TEST 4: sync_mcp preserves existing settings.json...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Create existing settings.json with tools config
        settings_path = project_dir / ".gemini" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        existing = {
            "tools": {
                "allowedTools": ["Read", "Write"]
            },
            "otherSetting": "value"
        }

        with open(settings_path, 'w') as f:
            json.dump(existing, f)

        # Sync MCP servers
        mcp_servers = {
            "new-server": {
                "command": "node",
                "args": ["server.js"]
            }
        }

        result = adapter.sync_mcp(mcp_servers)

        # Verify merge (not overwrite)
        assert result.synced == 1, f"Expected synced=1, got {result.synced}"

        with open(settings_path, 'r') as f:
            settings = json.load(f)

        # Original settings preserved
        assert "tools" in settings, "tools config lost"
        assert settings["tools"]["allowedTools"] == ["Read", "Write"], "allowedTools lost"
        assert settings["otherSetting"] == "value", "otherSetting lost"

        # New MCP server added
        assert "mcpServers" in settings, "mcpServers not added"
        assert "new-server" in settings["mcpServers"], "new-server not found"

    print("  ✓ sync_mcp preserves existing settings correctly")


def test_sync_mcp_env_var_preservation():
    """Test sync_mcp preserves env var references."""
    print("TEST 5: sync_mcp preserves env var references...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # MCP server with env vars
        mcp_servers = {
            "server-with-env": {
                "command": "node",
                "args": ["server.js"],
                "env": {
                    "API_KEY": "${MY_API_KEY}",
                    "SECRET": "${SECRET_VAR}",
                    "LITERAL": "actual_value"
                }
            }
        }

        # Sync
        result = adapter.sync_mcp(mcp_servers)
        assert result.synced == 1, f"Expected synced=1, got {result.synced}"

        # Verify env vars preserved as literal strings
        settings_path = project_dir / ".gemini" / "settings.json"
        with open(settings_path, 'r') as f:
            settings = json.load(f)

        env = settings["mcpServers"]["server-with-env"]["env"]
        assert env["API_KEY"] == "${MY_API_KEY}", "Env var reference not preserved"
        assert env["SECRET"] == "${SECRET_VAR}", "Env var reference not preserved"
        assert env["LITERAL"] == "actual_value", "Literal value mismatch"

    print("  ✓ sync_mcp env var preservation works correctly")


def test_sync_settings_deny_list():
    """Test sync_settings with deny list creates blockedTools."""
    print("TEST 6: sync_settings with deny list...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Settings with deny list
        settings = {
            "permissions": {
                "deny": ["Bash", "Edit"]
            }
        }

        # Sync settings
        result = adapter.sync_settings(settings)

        # Verify result
        assert result.synced == 1, f"Expected synced=1, got {result.synced}"
        assert result.adapted == 1, f"Expected adapted=1, got {result.adapted}"

        # Verify blockedTools in settings.json
        settings_path = project_dir / ".gemini" / "settings.json"
        with open(settings_path, 'r') as f:
            settings_json = json.load(f)

        assert "tools" in settings_json, "tools config not found"
        assert "blockedTools" in settings_json["tools"], "blockedTools not found"
        assert settings_json["tools"]["blockedTools"] == ["Bash", "Edit"], "blockedTools mismatch"

        # Verify warnings for blocked tools
        assert any("Bash: blocked" in f for f in result.skipped_files), "Bash warning not found"
        assert any("Edit: blocked" in f for f in result.skipped_files), "Edit warning not found"

    print("  ✓ sync_settings with deny list works correctly")


def test_sync_settings_allow_list():
    """Test sync_settings with allow list creates allowedTools."""
    print("TEST 7: sync_settings with allow list...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Settings with allow list (no deny list)
        settings = {
            "permissions": {
                "allow": ["Read", "Write"]
            }
        }

        # Sync settings
        result = adapter.sync_settings(settings)

        # Verify allowedTools in settings.json
        settings_path = project_dir / ".gemini" / "settings.json"
        with open(settings_path, 'r') as f:
            settings_json = json.load(f)

        assert "tools" in settings_json, "tools config not found"
        assert "allowedTools" in settings_json["tools"], "allowedTools not found"
        assert settings_json["tools"]["allowedTools"] == ["Read", "Write"], "allowedTools mismatch"

    print("  ✓ sync_settings with allow list works correctly")


def test_sync_settings_auto_approval_warning():
    """Test sync_settings warns about yolo mode NOT being enabled."""
    print("TEST 8: sync_settings auto-approval warning...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Settings with auto-approval
        settings = {
            "approval_mode": "auto",
            "permissions": {}
        }

        # Sync settings
        result = adapter.sync_settings(settings)

        # Verify warning present
        assert result.synced == 1, f"Expected synced=1, got {result.synced}"

        has_yolo_warning = any("yolo mode: not enabled" in f for f in result.skipped_files)
        assert has_yolo_warning, "Yolo mode warning not found"

        # Verify yolo mode NOT in settings.json
        settings_path = project_dir / ".gemini" / "settings.json"
        with open(settings_path, 'r') as f:
            settings_json = json.load(f)

        # Should NOT have yolo: true
        assert settings_json.get('yolo') != True, "Yolo mode should NOT be enabled"

    print("  ✓ sync_settings auto-approval warning works correctly")


def test_sync_settings_mcp_coexistence():
    """Test sync_settings + sync_mcp coexistence in same settings.json."""
    print("TEST 9: sync_settings + sync_mcp coexistence...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # First sync MCP servers
        mcp_servers = {
            "test-server": {
                "command": "node",
                "args": ["server.js"]
            }
        }
        adapter.sync_mcp(mcp_servers)

        # Then sync settings
        settings = {
            "permissions": {
                "deny": ["Bash"]
            }
        }
        adapter.sync_settings(settings)

        # Verify both present in settings.json
        settings_path = project_dir / ".gemini" / "settings.json"
        with open(settings_path, 'r') as f:
            settings_json = json.load(f)

        # Both sections should exist
        assert "mcpServers" in settings_json, "mcpServers lost after sync_settings"
        assert "tools" in settings_json, "tools not added"

        assert "test-server" in settings_json["mcpServers"], "test-server lost"
        assert "blockedTools" in settings_json["tools"], "blockedTools not found"

    print("  ✓ sync_settings + sync_mcp coexistence works correctly")


def run_all_tests():
    """Run all verification tests."""
    print("=" * 60)
    print("TASK 2 VERIFICATION: GeminiAdapter sync_mcp and sync_settings")
    print("=" * 60)
    print()

    tests = [
        test_sync_mcp_stdio,
        test_sync_mcp_url,
        test_sync_mcp_mixed,
        test_sync_mcp_preserves_existing,
        test_sync_mcp_env_var_preservation,
        test_sync_settings_deny_list,
        test_sync_settings_allow_list,
        test_sync_settings_auto_approval_warning,
        test_sync_settings_mcp_coexistence,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"  ✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            failed += 1

    print()
    print("=" * 60)
    if failed == 0:
        print("ALL TESTS PASSED ✓")
        print("=" * 60)
        return 0
    else:
        print(f"FAILED: {failed}/{len(tests)} tests")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
