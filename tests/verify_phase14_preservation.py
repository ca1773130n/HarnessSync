"""Verification tests for Phase 14 Plan 02 -- PRES-01 config preservation.

Tests that Codex config.toml writes preserve non-managed [agents], [profiles],
[features] sections, and that Gemini settings.json preserves non-synced keys
like hooks and security.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from src.adapters.codex import CodexAdapter
from src.adapters.gemini import GeminiAdapter


def test_codex_preservation():
    """Codex _write_mcp_to_path() preserves [agents] and [profiles] sections."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        adapter = CodexAdapter(project)

        # Pre-create config.toml with user-defined sections
        config_path = project / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            '# Codex configuration managed by HarnessSync\n'
            '# Do not edit MCP servers section manually\n'
            '\n'
            'sandbox_mode = "workspace-write"\n'
            '\n'
            '[agents]\n'
            'model = "gpt-4"\n'
            'temperature = 0.7\n'
            '\n'
            '[profiles.default]\n'
            'theme = "dark"\n'
            'verbose = true\n',
            encoding='utf-8',
        )

        # Write MCP servers (should preserve [agents] and [profiles])
        adapter._write_mcp_to_path(
            {"test-server": {"command": "node", "args": ["server.js"]}},
            config_path,
        )

        # Re-read and verify preservation
        content = config_path.read_text(encoding='utf-8')

        assert '[agents]' in content, f"[agents] section lost!\n{content}"
        assert 'model = "gpt-4"' in content, f"agents.model lost!\n{content}"
        assert '[profiles.default]' in content, f"[profiles.default] section lost!\n{content}"
        assert 'theme = "dark"' in content, f"profiles theme lost!\n{content}"
        assert '[mcp_servers."test-server"]' in content, f"MCP server missing!\n{content}"
        assert 'sandbox_mode' in content, f"sandbox_mode missing!\n{content}"

        print("  Codex _write_mcp_to_path() preservation: OK")


def test_codex_sync_settings_preservation():
    """Codex sync_settings() also preserves non-managed sections."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        adapter = CodexAdapter(project)

        # Pre-create config.toml with user-defined sections + MCP
        config_path = project / ".codex" / "config.toml"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            '# Codex configuration managed by HarnessSync\n'
            '# Do not edit MCP servers section manually\n'
            '\n'
            'sandbox_mode = "read-only"\n'
            '\n'
            '# MCP servers managed by HarnessSync\n'
            '# Do not edit manually - changes will be overwritten on next sync\n'
            '\n'
            '[mcp_servers."existing"]\n'
            'command = "python3"\n'
            '\n'
            '[features]\n'
            'auto_complete = true\n',
            encoding='utf-8',
        )

        # Run sync_settings (should preserve [features])
        adapter.sync_settings({
            'permissions': {'allow': ['Write', 'Edit']},
        })

        content = config_path.read_text(encoding='utf-8')

        assert '[features]' in content, f"[features] section lost!\n{content}"
        assert 'auto_complete = true' in content, f"features.auto_complete lost!\n{content}"
        assert 'sandbox_mode' in content, f"sandbox_mode missing!\n{content}"

        print("  Codex sync_settings() preservation: OK")


def test_gemini_preservation():
    """Gemini settings.json preserves non-synced keys (hooks, security)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        adapter = GeminiAdapter(project)

        # Pre-create settings.json with user-defined keys
        settings_path = project / ".gemini" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        settings_path.write_text(
            json.dumps({
                "hooks": {"pre_commit": "lint"},
                "security": {"sandbox": True},
                "mcpServers": {},
            }, indent=2),
            encoding='utf-8',
        )

        # Run sync_settings (should preserve hooks and security)
        adapter.sync_settings({
            'permissions': {'deny': ['Bash']},
        })

        content = json.loads(settings_path.read_text(encoding='utf-8'))

        assert 'hooks' in content, f"hooks key lost!\n{content}"
        assert content['hooks']['pre_commit'] == 'lint', f"hooks.pre_commit changed!\n{content}"
        assert 'security' in content, f"security key lost!\n{content}"
        assert content['security']['sandbox'] is True, f"security.sandbox changed!\n{content}"
        assert 'tools' in content, f"tools key missing (should have been added)!\n{content}"

        print("  Gemini settings.json preservation: OK")


if __name__ == '__main__':
    test_codex_preservation()
    test_codex_sync_settings_preservation()
    test_gemini_preservation()
    print("PRES-01 OK")
