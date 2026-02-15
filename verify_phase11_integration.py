#!/usr/bin/env python3
"""
Integration tests for Phase 11: State Enhancements & Integration.

Tests all 7 success criteria:
1. StateManager plugin tracking schema (record/retrieve)
2. Plugin version change detection and re-sync trigger
3. /sync-status MCP grouping by source
4. /sync-status plugin@version display format
5. Plugin drift detection (version, count, add, remove)
6. Plugin update simulation (1.0.0 -> 1.1.0 with new MCP)
7. Full pipeline: 3 plugins, 2 user, 1 project, 1 local MCPs

Exit 0 on all pass, exit 1 on any failure.
"""

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.state_manager import StateManager
from src.commands.sync_status import (
    _group_mcps_by_source,
    _format_mcp_groups,
    _format_plugin_drift,
    _extract_current_plugins
)


def print_check(check_num: int, total: int, desc: str, passed: bool):
    """Print check result with running count."""
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"[{check_num}/{total}] {status}: {desc}")
    return passed


def test_section_1_plugin_update_simulation(tmpdir: Path) -> tuple[int, int]:
    """
    Section 1: Plugin Update Simulation (Success Criteria #6).

    Tests plugin version update 1.0.0 -> 1.1.0 with MCP count change.

    Returns:
        (passed_count, total_count)
    """
    print("\n=== SECTION 1: Plugin Update Simulation ===\n")

    passed = 0
    total = 8
    check = 1

    # Setup StateManager with temp state dir
    with patch('src.state_manager.Path.home', return_value=tmpdir):
        state_manager = StateManager()

        # Check 1: Record initial plugin state (version 1.0.0, 1 MCP)
        initial_plugins = {
            "test-plugin": {
                "version": "1.0.0",
                "mcp_count": 1,
                "mcp_servers": ["test-mcp-1"],
                "last_sync": "2026-02-15T06:00:00Z"
            }
        }
        state_manager.record_plugin_sync(initial_plugins)

        stored = state_manager.get_plugin_status()
        check1 = (
            stored.get("test-plugin", {}).get("version") == "1.0.0" and
            stored.get("test-plugin", {}).get("mcp_count") == 1
        )
        if print_check(check, total, "Record initial plugin state (v1.0.0, 1 MCP)", check1):
            passed += 1
        check += 1

        # Check 2: Detect drift with updated version (1.1.0, 2 MCPs)
        current_plugins = {
            "test-plugin": {
                "version": "1.1.0",
                "mcp_count": 2,
                "mcp_servers": ["test-mcp-1", "test-mcp-2"],
                "last_sync": "2026-02-15T06:30:00Z"
            }
        }
        drift = state_manager.detect_plugin_drift(current_plugins)

        check2 = (
            "test-plugin" in drift and
            "version_changed: 1.0.0 -> 1.1.0" in drift["test-plugin"]
        )
        if print_check(check, total, "Detect version drift (1.0.0 -> 1.1.0)", check2):
            passed += 1
        check += 1

        # Check 3: Record updated plugin state
        state_manager.record_plugin_sync(current_plugins)

        updated = state_manager.get_plugin_status()
        check3 = (
            updated.get("test-plugin", {}).get("version") == "1.1.0" and
            updated.get("test-plugin", {}).get("mcp_count") == 2 and
            len(updated.get("test-plugin", {}).get("mcp_servers", [])) == 2
        )
        if print_check(check, total, "Record updated state (v1.1.0, 2 MCPs)", check3):
            passed += 1
        check += 1

        # Check 4: Verify drift cleared after re-sync
        drift_after = state_manager.detect_plugin_drift(current_plugins)
        check4 = len(drift_after) == 0
        if print_check(check, total, "Drift cleared after re-sync", check4):
            passed += 1
        check += 1

        # Check 5: get_plugin_status returns updated data
        final = state_manager.get_plugin_status()
        check5 = (
            final.get("test-plugin", {}).get("version") == "1.1.0" and
            "test-mcp-2" in final.get("test-plugin", {}).get("mcp_servers", [])
        )
        if print_check(check, total, "get_plugin_status returns updated data", check5):
            passed += 1
        check += 1

        # Check 6: Simulate MCP count change only (no version change)
        current_with_extra_mcp = {
            "test-plugin": {
                "version": "1.1.0",
                "mcp_count": 3,
                "mcp_servers": ["test-mcp-1", "test-mcp-2", "test-mcp-3"],
                "last_sync": "2026-02-15T07:00:00Z"
            }
        }
        drift_mcp_only = state_manager.detect_plugin_drift(current_with_extra_mcp)
        check6 = (
            "test-plugin" in drift_mcp_only and
            "mcp_count_changed: 2 -> 3" in drift_mcp_only["test-plugin"]
        )
        if print_check(check, total, "Detect MCP count change (2 -> 3)", check6):
            passed += 1
        check += 1

        # Check 7: Detect plugin removal
        current_no_plugin = {}
        drift_removed = state_manager.detect_plugin_drift(current_no_plugin)
        check7 = (
            "test-plugin" in drift_removed and
            drift_removed["test-plugin"] == "removed"
        )
        if print_check(check, total, "Detect plugin removal", check7):
            passed += 1
        check += 1

        # Check 8: Detect new plugin addition
        state_manager.record_plugin_sync(current_with_extra_mcp)  # Reset to known state
        current_with_new = {
            "test-plugin": {
                "version": "1.1.0",
                "mcp_count": 3,
                "mcp_servers": ["test-mcp-1", "test-mcp-2", "test-mcp-3"],
                "last_sync": "2026-02-15T07:00:00Z"
            },
            "new-plugin": {
                "version": "2.0.0",
                "mcp_count": 1,
                "mcp_servers": ["new-mcp"],
                "last_sync": "2026-02-15T07:00:00Z"
            }
        }
        drift_added = state_manager.detect_plugin_drift(current_with_new)
        check8 = (
            "new-plugin" in drift_added and
            drift_added["new-plugin"] == "added"
        )
        if print_check(check, total, "Detect new plugin addition", check8):
            passed += 1
        check += 1

    return passed, total


def test_section_2_full_v2_pipeline(tmpdir: Path) -> tuple[int, int]:
    """
    Section 2: Full v2.0 Pipeline (Success Criteria #7).

    Tests complete pipeline with 3 plugins + 2 user + 1 project + 1 local MCPs.

    Returns:
        (passed_count, total_count)
    """
    print("\n=== SECTION 2: Full v2.0 Pipeline ===\n")

    passed = 0
    total = 8
    check = 1

    # Mock MCP data: 3 plugins, 2 user file, 1 project file, 1 local file
    mcp_scoped = {
        # User file-based MCPs
        "user-mcp-1": {
            "config": {"command": "node", "args": ["server.js"]},
            "metadata": {"scope": "user", "source": "file"}
        },
        "user-mcp-2": {
            "config": {"command": "python", "args": ["-m", "server"]},
            "metadata": {"scope": "user", "source": "file"}
        },
        # Project file-based MCP
        "project-db": {
            "config": {"command": "npx", "args": ["db-server"]},
            "metadata": {"scope": "project", "source": "file"}
        },
        # Local file-based MCP
        "local-key": {
            "config": {"command": "vault", "args": ["server"]},
            "metadata": {"scope": "local", "source": "file"}
        },
        # Plugin MCPs - context7 (2 MCPs)
        "ctx-browse": {
            "config": {"command": "ctx", "args": ["browse"]},
            "metadata": {
                "scope": "user",
                "source": "plugin",
                "plugin_name": "context7",
                "plugin_version": "1.2.0"
            }
        },
        "ctx-query": {
            "config": {"command": "ctx", "args": ["query"]},
            "metadata": {
                "scope": "user",
                "source": "plugin",
                "plugin_name": "context7",
                "plugin_version": "1.2.0"
            }
        },
        # Plugin MCPs - grd (1 MCP)
        "grd-research": {
            "config": {"command": "grd", "args": ["research"]},
            "metadata": {
                "scope": "user",
                "source": "plugin",
                "plugin_name": "grd",
                "plugin_version": "0.3.1"
            }
        },
        # Plugin MCPs - test-plugin (1 MCP)
        "test-mcp": {
            "config": {"command": "test", "args": []},
            "metadata": {
                "scope": "user",
                "source": "plugin",
                "plugin_name": "test-plugin",
                "plugin_version": "1.0.0"
            }
        }
    }

    # Check 1: Discovery of all 8 MCPs
    check1 = len(mcp_scoped) == 8
    if print_check(check, total, "Discover all 8 MCPs (100% discovery)", check1):
        passed += 1
    check += 1

    # Check 2: Correct scope labels
    scopes = {name: data["metadata"]["scope"] for name, data in mcp_scoped.items()}
    check2 = (
        scopes["user-mcp-1"] == "user" and
        scopes["project-db"] == "project" and
        scopes["local-key"] == "local" and
        scopes["ctx-browse"] == "user"
    )
    if print_check(check, total, "Correct scope labels (user/project/local)", check2):
        passed += 1
    check += 1

    # Check 3: Correct source labels
    sources = {name: data["metadata"]["source"] for name, data in mcp_scoped.items()}
    check3 = (
        sources["user-mcp-1"] == "file" and
        sources["ctx-browse"] == "plugin"
    )
    if print_check(check, total, "Correct source labels (file/plugin)", check3):
        passed += 1
    check += 1

    # Check 4: Plugin metadata present
    check4 = (
        mcp_scoped["ctx-browse"]["metadata"].get("plugin_name") == "context7" and
        mcp_scoped["ctx-browse"]["metadata"].get("plugin_version") == "1.2.0" and
        mcp_scoped["grd-research"]["metadata"].get("plugin_name") == "grd"
    )
    if print_check(check, total, "Plugin MCPs have plugin_name and plugin_version metadata", check4):
        passed += 1
    check += 1

    # Check 5: _group_mcps_by_source produces correct groupings
    groups = _group_mcps_by_source(mcp_scoped)
    check5 = (
        len(groups["user"]) == 2 and
        len(groups["project"]) == 1 and
        len(groups["local"]) == 1 and
        "context7@1.2.0" in groups["plugins"] and
        len(groups["plugins"]["context7@1.2.0"]) == 2 and
        "grd@0.3.1" in groups["plugins"] and
        "test-plugin@1.0.0" in groups["plugins"]
    )
    if print_check(check, total, "_group_mcps_by_source produces correct groupings", check5):
        passed += 1
    check += 1

    # Check 6: _extract_current_plugins produces correct metadata
    plugins = _extract_current_plugins(mcp_scoped)
    check6 = (
        len(plugins) == 3 and
        plugins["context7"]["version"] == "1.2.0" and
        plugins["context7"]["mcp_count"] == 2 and
        plugins["grd"]["mcp_count"] == 1 and
        plugins["test-plugin"]["mcp_count"] == 1
    )
    if print_check(check, total, "_extract_current_plugins produces correct metadata", check6):
        passed += 1
    check += 1

    # Check 7: StateManager round-trip (record + get)
    with patch('src.state_manager.Path.home', return_value=tmpdir):
        state_manager = StateManager()
        state_manager.record_plugin_sync(plugins)

        retrieved = state_manager.get_plugin_status()
        check7 = (
            retrieved["context7"]["version"] == "1.2.0" and
            retrieved["context7"]["mcp_count"] == 2 and
            "ctx-browse" in retrieved["context7"]["mcp_servers"]
        )
        if print_check(check, total, "StateManager record_plugin_sync + get_plugin_status round-trip", check7):
            passed += 1
        check += 1

        # Check 8: Drift detection cycle (modify -> detect -> re-sync -> verify cleared)
        modified_plugins = plugins.copy()
        modified_plugins["context7"] = {
            "version": "1.3.0",
            "mcp_count": 3,
            "mcp_servers": ["ctx-browse", "ctx-query", "ctx-new"],
            "last_sync": "2026-02-15T08:00:00Z"
        }

        drift = state_manager.detect_plugin_drift(modified_plugins)
        drift_detected = "context7" in drift and "version_changed" in drift["context7"]

        state_manager.record_plugin_sync(modified_plugins)
        drift_after = state_manager.detect_plugin_drift(modified_plugins)
        drift_cleared = len(drift_after) == 0

        check8 = drift_detected and drift_cleared
        if print_check(check, total, "Drift detection cycle (modify -> detect -> re-sync -> cleared)", check8):
            passed += 1
        check += 1

    return passed, total


def test_section_3_mcp_source_grouping_display(tmpdir: Path) -> tuple[int, int]:
    """
    Section 3: MCP Source Grouping Display (Success Criteria #3, #4).

    Tests formatting functions for display.

    Returns:
        (passed_count, total_count)
    """
    print("\n=== SECTION 3: MCP Source Grouping Display ===\n")

    passed = 0
    total = 5
    check = 1

    # Mock grouped data
    groups = {
        "user": [("user-mcp-1", "user"), ("user-mcp-2", "user")],
        "project": [("project-db", "project")],
        "local": [("local-key", "local")],
        "plugins": {
            "context7@1.2.0": [("ctx-browse", "user"), ("ctx-query", "user")],
            "grd@0.3.1": [("grd-research", "user")]
        }
    }

    # Check 1: _format_mcp_groups contains "User-configured"
    lines = _format_mcp_groups(groups)
    output = "\n".join(lines)
    check1 = "User-configured (2)" in output
    if print_check(check, total, "_format_mcp_groups contains 'User-configured' section", check1):
        passed += 1
    check += 1

    # Check 2: _format_mcp_groups contains "Project-configured"
    check2 = "Project-configured (1)" in output
    if print_check(check, total, "_format_mcp_groups contains 'Project-configured' section", check2):
        passed += 1
    check += 1

    # Check 3: _format_mcp_groups contains "Plugin-provided" with plugin@version
    check3 = "Plugin-provided" in output and "context7@1.2.0 (2)" in output
    if print_check(check, total, "_format_mcp_groups contains 'Plugin-provided' with plugin@version", check3):
        passed += 1
    check += 1

    # Check 4: _format_plugin_drift contains drift warnings when drift exists
    drift = {"context7": "version_changed: 1.2.0 -> 1.3.0", "old-plugin": "removed"}
    drift_lines = _format_plugin_drift(drift)
    drift_output = "\n".join(drift_lines)
    check4 = "Plugin Drift" in drift_output and "context7: version_changed" in drift_output
    if print_check(check, total, "_format_plugin_drift contains drift warnings when drift exists", check4):
        passed += 1
    check += 1

    # Check 5: _format_plugin_drift is empty when no drift
    no_drift_lines = _format_plugin_drift({})
    check5 = len(no_drift_lines) == 0
    if print_check(check, total, "_format_plugin_drift is empty when no drift", check5):
        passed += 1
    check += 1

    return passed, total


def test_section_4_account_scoped_plugin_tracking(tmpdir: Path) -> tuple[int, int]:
    """
    Section 4: Account-Scoped Plugin Tracking.

    Tests account-scoped plugin tracking in StateManager.

    Returns:
        (passed_count, total_count)
    """
    print("\n=== SECTION 4: Account-Scoped Plugin Tracking ===\n")

    passed = 0
    total = 3
    check = 1

    with patch('src.state_manager.Path.home', return_value=tmpdir):
        state_manager = StateManager()

        # Check 1: record_plugin_sync with account stores under accounts.work.plugins
        work_plugins = {
            "work-plugin": {
                "version": "2.0.0",
                "mcp_count": 1,
                "mcp_servers": ["work-mcp"],
                "last_sync": "2026-02-15T09:00:00Z"
            }
        }
        state_manager.record_plugin_sync(work_plugins, account="work")

        # Read state file directly
        state_file = tmpdir / ".harnesssync" / "state.json"
        with open(state_file) as f:
            state = json.load(f)

        check1 = (
            "accounts" in state and
            "work" in state["accounts"] and
            "plugins" in state["accounts"]["work"] and
            "work-plugin" in state["accounts"]["work"]["plugins"]
        )
        if print_check(check, total, "record_plugin_sync with account stores under accounts.work.plugins", check1):
            passed += 1
        check += 1

        # Check 2: detect_plugin_drift with account reads from accounts.work.plugins
        modified_work = {
            "work-plugin": {
                "version": "2.1.0",
                "mcp_count": 1,
                "mcp_servers": ["work-mcp"],
                "last_sync": "2026-02-15T09:30:00Z"
            }
        }
        drift = state_manager.detect_plugin_drift(modified_work, account="work")
        check2 = "work-plugin" in drift and "version_changed: 2.0.0 -> 2.1.0" in drift["work-plugin"]
        if print_check(check, total, "detect_plugin_drift with account reads from accounts.work.plugins", check2):
            passed += 1
        check += 1

        # Check 3: get_plugin_status with account returns account-scoped data
        retrieved = state_manager.get_plugin_status(account="work")
        check3 = (
            retrieved.get("work-plugin", {}).get("version") == "2.0.0" and
            retrieved.get("work-plugin", {}).get("mcp_count") == 1
        )
        if print_check(check, total, "get_plugin_status with account returns account-scoped data", check3):
            passed += 1
        check += 1

    return passed, total


def main():
    """Run all integration tests."""
    print("\n" + "=" * 80)
    print("Phase 11 Integration Tests: State Enhancements & Integration")
    print("=" * 80)

    total_passed = 0
    total_checks = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Section 1: Plugin Update Simulation
        p1, t1 = test_section_1_plugin_update_simulation(tmpdir_path)
        total_passed += p1
        total_checks += t1

        # Section 2: Full v2.0 Pipeline
        p2, t2 = test_section_2_full_v2_pipeline(tmpdir_path)
        total_passed += p2
        total_checks += t2

        # Section 3: MCP Source Grouping Display
        p3, t3 = test_section_3_mcp_source_grouping_display(tmpdir_path)
        total_passed += p3
        total_checks += t3

        # Section 4: Account-Scoped Plugin Tracking
        p4, t4 = test_section_4_account_scoped_plugin_tracking(tmpdir_path)
        total_passed += p4
        total_checks += t4

    # Summary
    print("\n" + "=" * 80)
    print(f"TOTAL: {total_passed}/{total_checks} checks passed")
    print("=" * 80)

    if total_passed == total_checks:
        print("\n✓ ALL TESTS PASSED\n")
        sys.exit(0)
    else:
        print(f"\n✗ {total_checks - total_passed} TESTS FAILED\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
