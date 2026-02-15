"""Phase 10 Integration Test: Scope-Aware Target Sync & Environment Translation.

Verifies all 7 Phase 10 requirements:
- SYNC-01: Gemini scope routing (user/project separation)
- SYNC-02: Codex scope routing (user/project separation)
- SYNC-03: Plugin MCPs route to user-scope only
- SYNC-04: Transport detection (SSE skipped on Codex, included on Gemini)
- ENV-01: ${VAR} translated to literal values for Codex
- ENV-02: ${VAR:-default} uses default when var unset
- ENV-03: Gemini preserves ${VAR} syntax unchanged
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

# Set test env vars BEFORE imports
os.environ["TEST_API_KEY"] = "sk-test-integration-key"
os.environ.pop("UNDEFINED_PORT", None)

from src.adapters.codex import CodexAdapter
from src.adapters.gemini import GeminiAdapter
from src.adapters.opencode import OpenCodeAdapter


# Test data matching Success Criteria #8
SCOPED_MCPS = {
    # User-scope MCP with ${API_KEY} (ENV-01)
    "api-server": {
        "config": {
            "command": "npx",
            "args": ["-y", "@api/mcp-server", "--key", "${TEST_API_KEY}"],
            "env": {"NODE_ENV": "production"},
        },
        "metadata": {"scope": "user", "source": "file"},
    },
    # User-scope MCP with ${PORT:-3000} (ENV-02)
    "port-server": {
        "config": {
            "command": "node",
            "args": ["server.js", "--port", "${UNDEFINED_PORT:-3000}"],
        },
        "metadata": {"scope": "user", "source": "file"},
    },
    # Project-scope MCP (SYNC-01, SYNC-02)
    "project-db": {
        "config": {
            "command": "python",
            "args": ["-m", "db_server", "--local"],
        },
        "metadata": {"scope": "project", "source": "file"},
    },
    # Plugin MCP - must go to user scope (SYNC-03)
    "plugin-tools": {
        "config": {
            "command": "node",
            "args": ["/path/to/plugin/tools-server.js"],
        },
        "metadata": {
            "scope": "user",
            "source": "plugin",
            "plugin_name": "test-tools",
            "plugin_version": "2.1.0",
        },
    },
    # SSE server - should be skipped on Codex (SYNC-04)
    "sse-analytics": {
        "config": {"url": "https://analytics.example.com/mcp/sse"},
        "metadata": {"scope": "user", "source": "file"},
    },
}


def run_tests():
    """Run all Phase 10 integration checks."""
    print("Testing Phase 10: Scope-Aware Target Sync & Environment Translation")
    print("=" * 68)
    print()

    passed = 0
    failed = 0
    total = 0

    def check(label, condition, detail=""):
        nonlocal passed, failed, total
        total += 1
        if condition:
            passed += 1
            print(f"  [PASS] {label}")
        else:
            failed += 1
            print(f"  [FAIL] {label}")
            if detail:
                print(f"         {detail}")

    # ================================================================
    # CODEX TESTS
    # ================================================================
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        home_dir = tmpdir / "home"
        proj_dir = tmpdir / "project"
        home_dir.mkdir()
        proj_dir.mkdir()

        # Monkey-patch Path.home() for test isolation
        with patch.object(Path, "home", return_value=home_dir):
            adapter = CodexAdapter(proj_dir)
            result = adapter.sync_mcp_scoped(SCOPED_MCPS)

            user_config_path = home_dir / ".codex" / "codex.toml"
            proj_config_path = proj_dir / ".codex" / "codex.toml"

            # --- SYNC-02: Codex scope routing ---
            print("SYNC-02: Codex scope routing")
            check(
                "User-scope config file exists",
                user_config_path.exists(),
                f"Expected {user_config_path}",
            )
            check(
                "Project-scope config file exists",
                proj_config_path.exists(),
                f"Expected {proj_config_path}",
            )

            user_content = user_config_path.read_text() if user_config_path.exists() else ""
            proj_content = proj_config_path.read_text() if proj_config_path.exists() else ""

            check(
                "api-server in user config",
                "api-server" in user_content,
                f"Content: {user_content[:200]}...",
            )
            check(
                "port-server in user config",
                "port-server" in user_content,
            )
            check(
                "project-db in project config",
                "project-db" in proj_content,
                f"Content: {proj_content[:200]}...",
            )
            check(
                "project-db NOT in user config",
                "project-db" not in user_content,
            )
            check(
                "api-server NOT in project config",
                "api-server" not in proj_content,
            )
            print()

            # --- SYNC-03: Plugin MCPs user-scope only ---
            print("SYNC-03: Plugin MCPs route to user-scope")
            check(
                "plugin-tools in user config",
                "plugin-tools" in user_content,
            )
            check(
                "plugin-tools NOT in project config",
                "plugin-tools" not in proj_content,
            )
            print()

            # --- SYNC-04: Transport detection (Codex) ---
            print("SYNC-04: Transport detection (Codex)")
            check(
                "SSE server skipped (not in user config)",
                "sse-analytics" not in user_content,
            )
            check(
                "SSE server skipped (not in project config)",
                "sse-analytics" not in proj_content,
            )
            check(
                "SSE warning in result",
                any("SSE" in s for s in result.skipped_files),
                f"skipped_files: {result.skipped_files}",
            )
            check(
                "At least 1 skipped count",
                result.skipped >= 1,
                f"skipped={result.skipped}",
            )
            print()

            # --- ENV-01: ${VAR} translation for Codex ---
            print("ENV-01: Codex env var translation (${VAR})")
            check(
                "TEST_API_KEY resolved to literal value",
                "sk-test-integration-key" in user_content,
                f"Looking for 'sk-test-integration-key' in TOML",
            )
            check(
                "${TEST_API_KEY} NOT in Codex output (should be expanded)",
                "${TEST_API_KEY}" not in user_content,
            )
            check(
                "TEST_API_KEY in env section",
                "TEST_API_KEY" in user_content,
                "Env map should have extracted var",
            )
            print()

            # --- ENV-02: ${VAR:-default} for Codex ---
            print("ENV-02: Codex default value (${VAR:-default})")
            check(
                "Default port 3000 in Codex output",
                "3000" in user_content,
                "UNDEFINED_PORT should use default 3000",
            )
            check(
                "${UNDEFINED_PORT:-3000} NOT in Codex output",
                "${UNDEFINED_PORT:-3000}" not in user_content,
            )
            print()

    # ================================================================
    # GEMINI TESTS
    # ================================================================
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        home_dir = tmpdir / "home"
        proj_dir = tmpdir / "project"
        home_dir.mkdir()
        proj_dir.mkdir()

        with patch.object(Path, "home", return_value=home_dir):
            adapter = GeminiAdapter(proj_dir)
            result = adapter.sync_mcp_scoped(SCOPED_MCPS)

            user_config_path = home_dir / ".gemini" / "settings.json"
            proj_config_path = proj_dir / ".gemini" / "settings.json"

            # --- SYNC-01: Gemini scope routing ---
            print("SYNC-01: Gemini scope routing")
            check(
                "User-scope settings.json exists",
                user_config_path.exists(),
                f"Expected {user_config_path}",
            )
            check(
                "Project-scope settings.json exists",
                proj_config_path.exists(),
                f"Expected {proj_config_path}",
            )

            user_json = json.loads(user_config_path.read_text()) if user_config_path.exists() else {}
            proj_json = json.loads(proj_config_path.read_text()) if proj_config_path.exists() else {}

            user_mcps = user_json.get("mcpServers", {})
            proj_mcps = proj_json.get("mcpServers", {})

            check(
                f"User config has 4 servers (api, port, plugin, sse)",
                len(user_mcps) == 4,
                f"Got {len(user_mcps)}: {list(user_mcps.keys())}",
            )
            check(
                "Project config has 1 server (project-db)",
                len(proj_mcps) == 1 and "project-db" in proj_mcps,
                f"Got {len(proj_mcps)}: {list(proj_mcps.keys())}",
            )
            print()

            # --- SYNC-03: Plugin MCPs user-scope on Gemini ---
            print("SYNC-03: Plugin MCPs user-scope (Gemini)")
            check(
                "plugin-tools in Gemini user config",
                "plugin-tools" in user_mcps,
            )
            check(
                "plugin-tools NOT in Gemini project config",
                "plugin-tools" not in proj_mcps,
            )
            print()

            # --- SYNC-04: SSE included on Gemini (supported) ---
            print("SYNC-04: Transport detection (Gemini)")
            check(
                "SSE server included on Gemini (SSE supported)",
                "sse-analytics" in user_mcps,
                f"Gemini user MCPs: {list(user_mcps.keys())}",
            )
            print()

            # --- ENV-03: Gemini preserves ${VAR} syntax ---
            print("ENV-03: Gemini env var preservation")
            api_config = user_mcps.get("api-server", {})
            api_args = api_config.get("args", [])
            check(
                "${TEST_API_KEY} preserved in Gemini args",
                "${TEST_API_KEY}" in str(api_args),
                f"args: {api_args}",
            )

            port_config = user_mcps.get("port-server", {})
            port_args = port_config.get("args", [])
            check(
                "${UNDEFINED_PORT:-3000} preserved in Gemini args",
                "${UNDEFINED_PORT:-3000}" in str(port_args),
                f"args: {port_args}",
            )
            print()

    # ================================================================
    # OPENCODE TESTS
    # ================================================================
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        proj_dir = tmpdir / "project"
        proj_dir.mkdir()

        adapter = OpenCodeAdapter(proj_dir)
        result = adapter.sync_mcp_scoped(SCOPED_MCPS)

        print("OpenCode: Transport validation")
        check(
            "SSE server skipped on OpenCode",
            result.skipped >= 1 and any("SSE" in s for s in result.skipped_files),
            f"skipped={result.skipped}, files={result.skipped_files}",
        )

        oc_config_path = proj_dir / "opencode.json"
        if oc_config_path.exists():
            oc_data = json.loads(oc_config_path.read_text())
            oc_mcps = oc_data.get("mcp", {})
            check(
                "SSE server NOT in opencode.json",
                "sse-analytics" not in oc_mcps,
            )
            check(
                "Stdio servers present in opencode.json",
                "api-server" in oc_mcps and "project-db" in oc_mcps,
                f"MCPs: {list(oc_mcps.keys())}",
            )
        print()

    # ================================================================
    # SUMMARY
    # ================================================================
    print("=" * 68)
    print(f"Results: {passed}/{total} passed")

    if failed > 0:
        print(f"FAILED: {failed} check(s) did not pass")
        sys.exit(1)
    else:
        print("ALL PHASE 10 INTEGRATION TESTS PASSED")
        sys.exit(0)


if __name__ == "__main__":
    run_tests()
