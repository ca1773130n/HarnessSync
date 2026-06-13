from __future__ import annotations

"""Tests for the 2026-06 Codex adapter modernization (Group B).

Covers config.toml model_reasoning_effort / project_doc_fallback_filenames /
guarded model, the [sandbox_workspace_write] table, and MCP HTTP transport
(http_headers / env_http_headers).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.adapters.codex import CodexAdapter
from src.utils.toml_writer import format_mcp_server_toml, read_toml_safe


def _cfg(project_dir: Path) -> str:
    return (project_dir / ".codex" / "config.toml").read_text(encoding="utf-8")


class TestCodexSettingsModernization:
    def test_reasoning_effort_and_fallback(self, tmp_path):
        CodexAdapter(tmp_path).sync_settings({"effort": "xhigh"})
        c = _cfg(tmp_path)
        assert 'model_reasoning_effort = "xhigh"' in c
        assert 'project_doc_fallback_filenames = ["CLAUDE.md"]' in c

    def test_invalid_effort_skipped(self, tmp_path):
        CodexAdapter(tmp_path).sync_settings({"effort": "ludicrous"})
        assert "model_reasoning_effort" not in _cfg(tmp_path)

    def test_model_guard_emits_codex_model_only(self, tmp_path):
        CodexAdapter(tmp_path).sync_settings({"model": "gpt-5.5"})
        assert 'model = "gpt-5.5"' in _cfg(tmp_path)

    def test_model_guard_drops_anthropic_alias(self, tmp_path):
        CodexAdapter(tmp_path).sync_settings({"model": "opusplan"})
        c = _cfg(tmp_path)
        # No bare top-level `model = ` line for an Anthropic alias
        assert not any(line.strip().startswith("model = ") for line in c.splitlines())

    def test_sandbox_workspace_write(self, tmp_path):
        CodexAdapter(tmp_path).sync_settings({
            "permissions": {"allow": ["Write", "Edit"], "additionalDirectories": ["/srv/extra"]},
            "sandbox": {"filesystem": {"allowWrite": ["/work"]}, "allowNetwork": True},
        })
        c = _cfg(tmp_path)
        assert "[sandbox_workspace_write]" in c
        assert "/work" in c and "/srv/extra" in c
        assert "network_access = true" in c

    def test_sandbox_section_absent_when_readonly(self, tmp_path):
        # Many denies -> read-only sandbox_mode -> no [sandbox_workspace_write]
        CodexAdapter(tmp_path).sync_settings({
            "permissions": {"deny": ["Bash", "Write", "Edit"], "additionalDirectories": ["/x"]},
        })
        assert "[sandbox_workspace_write]" not in _cfg(tmp_path)


class TestCodexConfigTomlOrdering:
    """Managed top-level keys must stay at root regardless of sync order.

    Regression: bare keys (model/effort/fallback) emitted by sync_settings must
    not be re-appended after [mcp_servers.*] tables by a later sync_mcp (which
    would rebind them to the table in TOML).
    """

    def test_managed_keys_at_root_when_mcp_synced_last(self, tmp_path):
        a = CodexAdapter(tmp_path)
        a.sync_settings({"model": "gpt-5.5", "effort": "high"})
        a.sync_mcp({"srv": {"url": "https://h/mcp", "headers": {"X": "y"}}})
        parsed = read_toml_safe(tmp_path / ".codex" / "config.toml")
        assert parsed.get("model") == "gpt-5.5"
        assert parsed.get("model_reasoning_effort") == "high"
        assert parsed.get("project_doc_fallback_filenames") == ["CLAUDE.md"]
        # Must NOT have leaked into the mcp table
        assert "model" not in parsed.get("mcp_servers", {}).get("srv", {})

    def test_sandbox_table_preserved_through_mcp_sync(self, tmp_path):
        a = CodexAdapter(tmp_path)
        a.sync_settings({
            "permissions": {"allow": ["Write"], "additionalDirectories": ["/d"]},
            "sandbox": {"filesystem": {"allowWrite": ["/w"]}},
        })
        a.sync_mcp({"srv": {"command": "x"}})
        parsed = read_toml_safe(tmp_path / ".codex" / "config.toml")
        sbw = parsed.get("sandbox_workspace_write", {})
        assert set(sbw.get("writable_roots", [])) == {"/w", "/d"}


class TestCodexMcpHttpTransport:
    def test_headers_mapped_to_http_headers(self):
        out = CodexAdapter._translate_mcp_fields({"url": "https://h/mcp", "headers": {"X-Region": "us"}})
        assert out["http_headers"] == {"X-Region": "us"}
        assert "headers" not in out

    def test_env_http_headers_passthrough(self):
        out = CodexAdapter._translate_mcp_fields(
            {"url": "https://h/mcp", "env_http_headers": {"Authorization": "FIGMA_TOKEN"}}
        )
        assert out["env_http_headers"] == {"Authorization": "FIGMA_TOKEN"}

    def test_toml_writer_emits_both_header_tables(self):
        toml = format_mcp_server_toml("figma", {
            "url": "https://h/mcp",
            "http_headers": {"X-Region": "us"},
            "env_http_headers": {"Authorization": "FIGMA_TOKEN"},
        })
        assert '[mcp_servers."figma".http_headers]' in toml
        assert '[mcp_servers."figma".env_http_headers]' in toml
        assert "Authorization = " in toml
