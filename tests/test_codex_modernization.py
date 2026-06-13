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


class TestCodexEnvAndApprovalGranular:
    """Follow-ups: settings.env -> [shell_environment_policy.set]; granular approval_policy."""

    def test_env_emitted_as_shell_environment_policy(self, tmp_path):
        CodexAdapter(tmp_path).sync_settings({"env": {"ANTHROPIC_MODEL": "x", "MCP_TIMEOUT": 30000}})
        parsed = read_toml_safe(tmp_path / ".codex" / "config.toml")
        setmap = parsed.get("shell_environment_policy", {}).get("set", {})
        assert setmap.get("ANTHROPIC_MODEL") == "x"
        assert setmap.get("MCP_TIMEOUT") == "30000"  # coerced to string

    def test_env_preserved_when_mcp_synced_after(self, tmp_path):
        a = CodexAdapter(tmp_path)
        a.sync_settings({"env": {"K": "v"}})
        a.sync_mcp({"srv": {"command": "x"}})
        parsed = read_toml_safe(tmp_path / ".codex" / "config.toml")
        assert parsed.get("shell_environment_policy", {}).get("set", {}).get("K") == "v"
        assert "srv" in parsed.get("mcp_servers", {})

    def test_no_env_no_shell_policy(self, tmp_path):
        CodexAdapter(tmp_path).sync_settings({"effort": "high"})
        assert "[shell_environment_policy" not in (tmp_path / ".codex" / "config.toml").read_text()

    def test_granular_approval_policy_opt_in(self, tmp_path):
        CodexAdapter(tmp_path).sync_settings(
            {"codexApprovalGranular": {"sandbox_approval": True, "rules": False}}
        )
        parsed = read_toml_safe(tmp_path / ".codex" / "config.toml")
        ap = parsed.get("approval_policy")
        assert isinstance(ap, dict)
        assert ap["granular"]["sandbox_approval"] is True
        assert ap["granular"]["rules"] is False

    def test_granular_approval_true_enables_all(self, tmp_path):
        CodexAdapter(tmp_path).sync_settings({"codexApprovalGranular": True})
        ap = read_toml_safe(tmp_path / ".codex" / "config.toml").get("approval_policy")
        assert isinstance(ap, dict) and all(ap["granular"].values())
        assert len(ap["granular"]) == 5

    def test_granular_survives_mcp_resync(self, tmp_path):
        a = CodexAdapter(tmp_path)
        a.sync_settings({"codexApprovalGranular": {"skill_approval": True}})
        a.sync_mcp({"srv": {"command": "x"}})
        ap = read_toml_safe(tmp_path / ".codex" / "config.toml").get("approval_policy")
        assert isinstance(ap, dict) and ap["granular"]["skill_approval"] is True

    def test_default_approval_policy_stays_string(self, tmp_path):
        CodexAdapter(tmp_path).sync_settings({"permissions": {"allow": ["Read"]}})
        ap = read_toml_safe(tmp_path / ".codex" / "config.toml").get("approval_policy")
        assert isinstance(ap, str)  # intent-based string form unchanged by default


class TestCodexPreservesUserConfig:
    """Regression (Codex review P2): user-owned config must not be silently dropped."""

    def _seed(self, tmp_path):
        cdir = tmp_path / ".codex"
        cdir.mkdir()
        (cdir / "config.toml").write_text(
            'model_verbosity = "high"\n'
            'sandbox_mode = "workspace-write"\n'
            '\n[sandbox_workspace_write]\nexclude_slash_tmp = true\n'
            '\n[shell_environment_policy]\ninherit = "all"\n',
            encoding="utf-8",
        )
        return cdir / "config.toml"

    def test_sync_settings_preserves_user_owned_fields(self, tmp_path):
        cfg = self._seed(tmp_path)
        CodexAdapter(tmp_path).sync_settings({
            "effort": "high", "env": {"K": "v"},
            "permissions": {"allow": ["Write"], "additionalDirectories": ["/extra"]},
            "sandbox": {"filesystem": {"allowWrite": ["/w"]}},
        })
        p = read_toml_safe(cfg)
        # managed key we don't generate -> preserved
        assert p.get("model_verbosity") == "high"
        # table siblings -> preserved alongside the keys we do generate
        assert p["sandbox_workspace_write"]["exclude_slash_tmp"] is True
        assert set(p["sandbox_workspace_write"]["writable_roots"]) == {"/w", "/extra"}
        assert p["shell_environment_policy"]["inherit"] == "all"
        assert p["shell_environment_policy"]["set"]["K"] == "v"
        assert p["model_reasoning_effort"] == "high"

    def test_preservation_survives_later_sync_mcp(self, tmp_path):
        cfg = self._seed(tmp_path)
        a = CodexAdapter(tmp_path)
        a.sync_settings({"env": {"K": "v"}, "sandbox": {"filesystem": {"allowWrite": ["/w"]}},
                         "permissions": {"allow": ["Write"]}})
        a.sync_mcp({"srv": {"command": "x"}})
        p = read_toml_safe(cfg)
        assert p.get("model_verbosity") == "high"
        assert p["sandbox_workspace_write"]["exclude_slash_tmp"] is True
        assert p["shell_environment_policy"]["inherit"] == "all"
        assert "srv" in p.get("mcp_servers", {})

    def test_existing_model_not_clobbered_by_anthropic_alias(self, tmp_path):
        cdir = tmp_path / ".codex"; cdir.mkdir()
        (cdir / "config.toml").write_text('model = "gpt-5.5"\nsandbox_mode = "workspace-write"\n')
        CodexAdapter(tmp_path).sync_settings({"model": "opusplan"})  # alias not propagated
        # existing codex model preserved (not erased)
        assert read_toml_safe(cdir / "config.toml").get("model") == "gpt-5.5"


def test_output_style_file_tracked_in_source_paths(tmp_path):
    """Regression (Codex review P2): active output-style file must be hashed for incremental sync."""
    import json
    from src.source_reader import SourceReader
    proj = tmp_path / "proj"; (proj / ".claude" / "output-styles").mkdir(parents=True)
    (proj / ".claude" / "settings.json").write_text(json.dumps({"outputStyle": "terse"}))
    sf = proj / ".claude" / "output-styles" / "terse.md"
    sf.write_text("---\nname: T\n---\nBe terse.")
    paths = SourceReader(scope="all", project_dir=proj, cc_home=tmp_path / "cc").get_source_paths()
    assert sf in paths["rules"]


class TestInlineTableRoundTrip:
    def test_parse_and_format(self):
        from src.utils.toml_writer import parse_toml_simple, format_inline_table
        d = parse_toml_simple('approval_policy = { granular = { rules = true, sandbox_approval = false } }')
        assert d["approval_policy"]["granular"]["rules"] is True
        assert d["approval_policy"]["granular"]["sandbox_approval"] is False
        assert format_inline_table({"granular": {"rules": True}}) == "{ granular = { rules = true } }"


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
