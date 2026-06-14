from __future__ import annotations

"""Tests for the 2026-06 modernization: new Claude Code source surfaces.

Covers SourceReader surfacing of settings.env, model/effort, sandbox,
permissions.defaultMode + additionalDirectories, outputStyle + output-styles,
MCP enable/disable gates, recursive (namespaced) agent/command discovery, and
the env_translator transport normalization helpers.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.source_reader import SourceReader
from src.sync_pipeline import PreSyncPipeline
from src.utils.logger import Logger
from src.utils.permissions import extract_permission_mode
from src.utils.env_translator import detect_transport_type, transport_deprecation


def _pipeline(tmp_path):
    return PreSyncPipeline(
        project_dir=tmp_path, cc_home=tmp_path / "cc", scope="project",
        dry_run=True, allow_secrets=False, scrub_secrets=False, minimal=False,
        logger=Logger(),
    )


def _reader(tmp_path, settings=None, project_files=None):
    """Build a SourceReader over isolated cc_home + project dirs.

    settings: dict written to <project>/.claude/settings.json
    project_files: {relative_path: text} written under <project>
    """
    cc = tmp_path / "cc"
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True, exist_ok=True)
    cc.mkdir(parents=True, exist_ok=True)
    if settings is not None:
        (proj / ".claude" / "settings.json").write_text(json.dumps(settings), encoding="utf-8")
    for rel, text in (project_files or {}).items():
        p = proj / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return SourceReader(scope="all", project_dir=proj, cc_home=cc)


# --------------------------------------------------------------------------- #
# C2 — settings.env
# --------------------------------------------------------------------------- #

def test_get_env_surfaces_string_map(tmp_path):
    r = _reader(tmp_path, settings={"env": {"ANTHROPIC_MODEL": "claude-opus-4-8", "MCP_TIMEOUT": 30000}})
    env = r.get_env()
    assert env == {"ANTHROPIC_MODEL": "claude-opus-4-8", "MCP_TIMEOUT": "30000"}


def test_get_env_absent_or_invalid(tmp_path):
    assert _reader(tmp_path, settings={}).get_env() == {}
    assert _reader(tmp_path, settings={"env": "nope"}).get_env() == {}


# --------------------------------------------------------------------------- #
# C3 — model + effort
# --------------------------------------------------------------------------- #

def test_get_model_config(tmp_path):
    r = _reader(tmp_path, settings={"model": "opusplan", "effort": "xhigh"})
    assert r.get_model_config() == {"model": "opusplan", "effort": "xhigh"}


def test_get_model_config_absent(tmp_path):
    assert _reader(tmp_path, settings={}).get_model_config() == {"model": None, "effort": None}


# --------------------------------------------------------------------------- #
# C4 — sandbox + permission mode
# --------------------------------------------------------------------------- #

def test_get_sandbox(tmp_path):
    sb = {"enabled": True, "filesystem": {"allowWrite": ["/tmp/work"]}}
    assert _reader(tmp_path, settings={"sandbox": sb}).get_sandbox() == sb


def test_get_permission_mode(tmp_path):
    settings = {"permissions": {"defaultMode": "acceptEdits", "additionalDirectories": ["/srv/data", 5]}}
    pm = _reader(tmp_path, settings=settings).get_permission_mode()
    assert pm["defaultMode"] == "acceptEdits"
    assert pm["additionalDirectories"] == ["/srv/data"]  # non-str dropped


def test_extract_permission_mode_defaults():
    assert extract_permission_mode({}) == {"defaultMode": None, "additionalDirectories": []}
    assert extract_permission_mode({"permissions": "x"}) == {"defaultMode": None, "additionalDirectories": []}


# --------------------------------------------------------------------------- #
# C5 — outputStyle + output-styles dir
# --------------------------------------------------------------------------- #

def test_output_styles(tmp_path):
    r = _reader(
        tmp_path,
        settings={"outputStyle": "Explanatory"},
        project_files={".claude/output-styles/my-style.md": "# Custom persona\nBe terse."},
    )
    out = r.get_output_styles()
    assert out["active"] == "Explanatory"
    assert "my-style" in out["styles"]
    assert out["styles"]["my-style"].read_text(encoding="utf-8").startswith("# Custom persona")


# --------------------------------------------------------------------------- #
# C1 — MCP enable/disable gates
# --------------------------------------------------------------------------- #

def test_mcp_disable_gate(tmp_path):
    r = _reader(
        tmp_path,
        settings={"disabledMcpjsonServers": ["secret-server"]},
        project_files={
            ".mcp.json": json.dumps({"mcpServers": {
                "keep-me": {"command": "npx", "args": ["good"]},
                "secret-server": {"command": "npx", "args": ["bad"]},
            }})
        },
    )
    servers = r.get_mcp_servers()
    assert "keep-me" in servers
    assert "secret-server" not in servers  # explicitly disabled -> never synced
    skipped = r.get_skipped_mcp_servers()
    assert [s["name"] for s in skipped] == ["secret-server"]
    assert skipped[0]["reason"] == "disabledMcpjsonServers"


def test_mcp_no_gate_includes_all(tmp_path):
    r = _reader(
        tmp_path,
        settings={},
        project_files={".mcp.json": json.dumps({"mcpServers": {
            "a": {"command": "x"}, "b": {"url": "https://h/mcp"},
        }})},
    )
    assert set(r.get_mcp_servers()) == {"a", "b"}
    assert r.get_skipped_mcp_servers() == []


# --------------------------------------------------------------------------- #
# C6 — namespaced (recursive) agent/command discovery
# --------------------------------------------------------------------------- #

def test_namespaced_commands_and_agents_rglob(tmp_path):
    r = _reader(
        tmp_path,
        settings={},
        project_files={
            ".claude/commands/top.md": "top",
            ".claude/commands/ns/nested.md": "nested",
            ".claude/agents/group/deep.md": "agent",
        },
    )
    cmds = r.get_commands()
    assert "top" in cmds and "nested" in cmds  # nested previously missed by iterdir
    agents = r.get_agents()
    assert "deep" in agents


# --------------------------------------------------------------------------- #
# C6 — dead attribute cleanup
# --------------------------------------------------------------------------- #

def test_cc_mcp_global_attribute_removed(tmp_path):
    r = _reader(tmp_path, settings={})
    assert not hasattr(r, "cc_mcp_global")


# --------------------------------------------------------------------------- #
# C7 — transport normalization
# --------------------------------------------------------------------------- #

def test_detect_transport_explicit_type():
    assert detect_transport_type({"type": "streamable-http", "url": "https://h/mcp"}) == "http"
    assert detect_transport_type({"type": "streamable_http", "url": "https://h/mcp"}) == "http"
    assert detect_transport_type({"type": "http", "url": "https://h/mcp"}) == "http"
    assert detect_transport_type({"type": "sse", "url": "https://h/mcp"}) == "sse"
    assert detect_transport_type({"type": "stdio", "command": "x"}) == "stdio"
    # no explicit type -> inferred
    assert detect_transport_type({"command": "npx"}) == "stdio"
    assert detect_transport_type({"url": "https://h/sse"}) == "sse"
    assert detect_transport_type({"url": "https://h/mcp"}) == "http"


def test_transport_deprecation():
    assert transport_deprecation("s1", {"url": "https://h/sse"}) != ""
    assert transport_deprecation("s2", {"url": "https://h/mcp"}) == ""
    assert transport_deprecation("s3", {"command": "npx"}) == ""


# --------------------------------------------------------------------------- #
# discover_all exposes the new keys
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Follow-up #1 — outputStyle injected into the rules pipeline
# --------------------------------------------------------------------------- #

def test_inject_active_custom_output_style(tmp_path):
    osfile = tmp_path / "terse.md"
    osfile.write_text("---\nname: Terse\ndescription: x\n---\n# Persona\nBe terse.\n", encoding="utf-8")
    sd = {
        "rules": [{"path": "CLAUDE.md", "content": "base"}],
        "output_styles": {"active": "terse", "styles": {"terse": osfile}},
    }
    _pipeline(tmp_path).inject_output_styles(sd)
    injected = [r for r in sd["rules"] if r["path"] == "output-style-terse"]
    assert injected, "active custom output style should be injected as a rule"
    assert "Be terse." in injected[0]["content"]
    assert "name: Terse" not in injected[0]["content"]  # frontmatter stripped


def test_builtin_output_style_not_injected(tmp_path):
    sd = {"rules": [], "output_styles": {"active": "Explanatory", "styles": {}}}
    _pipeline(tmp_path).inject_output_styles(sd)
    assert sd["rules"] == []  # built-in styles carry no body to sync


def test_no_output_style_is_noop(tmp_path):
    sd = {"rules": [{"path": "CLAUDE.md", "content": "x"}]}
    _pipeline(tmp_path).inject_output_styles(sd)
    assert len(sd["rules"]) == 1


# --------------------------------------------------------------------------- #
# Follow-up #2 — settings.env -> aider `set-env` (the one env-capable non-Codex adapter)
# --------------------------------------------------------------------------- #

def test_aider_env_to_set_env(tmp_path):
    from src.adapters.aider import AiderAdapter
    AiderAdapter(tmp_path).sync_settings({"env": {"HTTP_PROXY": "http://proxy:8080", "TZ": "UTC"}})
    conf = (tmp_path / ".aider.conf.yml").read_text(encoding="utf-8")
    assert "set-env:" in conf
    assert "HTTP_PROXY=http://proxy:8080" in conf
    assert "TZ=UTC" in conf


def test_aider_env_filters_secrets(tmp_path):
    from src.adapters.aider import AiderAdapter
    AiderAdapter(tmp_path).sync_settings({"env": {
        "HTTP_PROXY": "http://proxy:8080",
        "OPENAI_API_KEY": "placeholder-not-a-real-key",
    }})
    conf = (tmp_path / ".aider.conf.yml").read_text(encoding="utf-8")
    assert "HTTP_PROXY=" in conf
    assert "OPENAI_API_KEY" not in conf  # secret-looking var is not written


def test_aider_env_preserves_existing_set_env(tmp_path):
    from src.adapters.aider import AiderAdapter
    (tmp_path / ".aider.conf.yml").write_text("set-env:\n  - USER_VAR=keepme\n", encoding="utf-8")
    AiderAdapter(tmp_path).sync_settings({"env": {"TZ": "UTC"}})
    conf = (tmp_path / ".aider.conf.yml").read_text(encoding="utf-8")
    assert "USER_VAR=keepme" in conf  # user entry preserved
    assert "TZ=UTC" in conf


# --------------------------------------------------------------------------- #
# C8 — deferred surfaces (statusLine, user hooks, ancestor CLAUDE.md, managed-settings)
# --------------------------------------------------------------------------- #

def test_status_line_surfaced(tmp_path):
    sl = {"type": "command", "command": "~/bin/statusline.sh"}
    r = _reader(tmp_path, settings={"statusLine": sl, "subagentStatusLine": {"type": "command", "command": "x"}})
    out = r.get_status_line()
    assert out["statusLine"] == sl
    assert out["subagentStatusLine"]["command"] == "x"
    assert r.discover_all()["status_line"]["statusLine"] == sl


def test_user_scope_hooks_json(tmp_path):
    r = _reader(tmp_path, settings={})
    user_hooks = r.cc_home / "hooks" / "hooks.json"
    user_hooks.parent.mkdir(parents=True, exist_ok=True)
    user_hooks.write_text(json.dumps({"hooks": {"SessionStart": [
        {"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}
    ]}}))
    hooks = r.get_hooks()["hooks"]
    user = [h for h in hooks if h.get("scope") == "user" and h.get("command") == "echo hi"]
    assert user, "user-scope hooks/hooks.json should be read"


def test_managed_settings_highest_precedence(tmp_path, monkeypatch):
    managed = tmp_path / "managed-settings.json"
    managed.write_text(json.dumps({"model": "enterprise-locked"}))
    r = _reader(tmp_path, settings={"model": "user-choice"})
    monkeypatch.setattr(r, "_managed_settings_path", lambda: managed)
    # managed-settings overrides the project/user value
    assert r.get_settings()["model"] == "enterprise-locked"


def test_managed_settings_absent_is_noop(tmp_path, monkeypatch):
    r = _reader(tmp_path, settings={"model": "user-choice"})
    monkeypatch.setattr(r, "_managed_settings_path", lambda: tmp_path / "does-not-exist.json")
    assert r.get_settings()["model"] == "user-choice"


def test_ancestor_monorepo_claude_md(tmp_path):
    # monorepo root (with .git) + a nested project package
    root = tmp_path / "monorepo"
    (root / ".git").mkdir(parents=True)
    (root / "CLAUDE.md").write_text("# Monorepo root rules\nShared conventions.")
    pkg = root / "packages" / "app"
    (pkg / ".claude").mkdir(parents=True)
    (pkg / "CLAUDE.md").write_text("# App rules\nApp-specific.")
    r = SourceReader(scope="project", project_dir=pkg, cc_home=tmp_path / "cc")
    rules = r.get_rules()
    assert "Shared conventions." in rules  # ancestor root CLAUDE.md included
    assert "App-specific." in rules
    # broad -> specific ordering: ancestor appears before the project rules
    assert rules.index("Shared conventions.") < rules.index("App-specific.")
    # tracked for incremental sync
    assert (root / "CLAUDE.md") in r.get_source_paths()["rules"]


def test_ancestor_traversal_stops_at_nearest_repo_root(tmp_path):
    # Traversal is bounded to the nearest enclosing git repo and never goes above it.
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    proj = root / "a" / "b"
    proj.mkdir(parents=True)
    ancestors = list(SourceReader(scope="project", project_dir=proj, cc_home=tmp_path / "cc")._ancestor_dirs(proj))
    assert root in ancestors                     # includes the repo root
    assert root.parent not in ancestors          # never above it
    assert all(str(a).startswith(str(root)) for a in ancestors)  # all within the repo


def test_ancestor_traversal_none_when_project_is_repo_root(tmp_path):
    # When the project dir IS the repo root, there are no in-repo ancestors.
    root = tmp_path / "repo2"
    (root / ".git").mkdir(parents=True)
    assert list(SourceReader(scope="project", project_dir=root, cc_home=tmp_path / "cc")._ancestor_dirs(root)) == []


def test_discover_all_has_new_keys(tmp_path):
    data = _reader(tmp_path, settings={"env": {"A": "1"}, "model": "fable"}).discover_all()
    for key in ("env", "model_config", "sandbox", "permission_mode", "output_styles", "mcp_disabled"):
        assert key in data, f"discover_all missing new key: {key}"
    assert data["env"] == {"A": "1"}
    assert data["model_config"]["model"] == "fable"
