from __future__ import annotations

"""Unit tests for src/state_manager.py — atomic sync state tracking.

Covers:
- Initialization with default and custom state dirs
- State persistence (atomic writes via tempfile + os.replace)
- v1 → v2 migration (flat targets → accounts.default.targets)
- Legacy (no version) migration
- Corrupted state file handling (backup + fresh state)
- record_sync: success/partial/failed status, flat and account-scoped
- detect_drift: changed, added, removed files, account-scoped
- get_target_status / get_account_target_status / get_account_status
- list_state_accounts / get_all_status / clear_target
- migrate_from_cc2all
- Global dry-run mode (get/set)
- Plugin sync tracking (record/detect drift/get status)
- Health score history (record/get/sparkline)
- Concurrent-safe atomic writes (no temp file leakage)
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.state_manager import StateManager


# ---------------------------------------------------------------------------
# Initialization & Persistence
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_default_state_dir(self, tmp_path, monkeypatch):
        """StateManager uses ~/.harnesssync by default."""
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        sm = StateManager()
        assert sm.state_dir == tmp_path / ".harnesssync"

    def test_custom_state_dir(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.state_dir == tmp_path

    def test_fresh_state_has_v2_schema(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        state = sm.get_all_status()
        assert state["version"] == 2
        assert state["targets"] == {}
        assert state["accounts"] == {}

    def test_state_file_property(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.state_file == tmp_path / "state.json"

    def test_last_sync_initially_none(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.last_sync is None


class TestPersistence:
    def test_state_survives_reload(self, tmp_path):
        """State written by one instance is readable by another."""
        sm1 = StateManager(state_dir=tmp_path)
        sm1.record_sync("codex", "all", {"f": "h1"}, {"f": "copy"}, 1, 0, 0)

        sm2 = StateManager(state_dir=tmp_path)
        status = sm2.get_target_status("codex")
        assert status is not None
        assert status["status"] == "success"

    def test_atomic_write_creates_valid_json(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("gemini", "project", {}, {}, 0, 0, 0)

        raw = json.loads((tmp_path / "state.json").read_text())
        assert raw["version"] == 2

    def test_no_temp_files_left_after_save(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {}, {}, 1, 0, 0)

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Temp files leaked: {tmp_files}"

    def test_state_file_has_trailing_newline(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {}, {}, 1, 0, 0)

        content = (tmp_path / "state.json").read_text()
        assert content.endswith("\n")


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

class TestMigration:
    def test_v1_to_v2_migration(self, tmp_path):
        """v1 state (flat targets) is auto-migrated to v2 (accounts.default)."""
        v1_state = {
            "version": 1,
            "last_sync": "2024-01-01T12:00:00",
            "targets": {
                "codex": {
                    "last_sync": "2024-01-01T12:00:00",
                    "status": "success",
                    "file_hashes": {"a.md": "hash1"},
                }
            },
        }
        (tmp_path / "state.json").write_text(json.dumps(v1_state))

        sm = StateManager(state_dir=tmp_path)
        state = sm.get_all_status()

        assert state["version"] == 2
        assert "default" in state["accounts"]
        default_account = state["accounts"]["default"]
        assert "codex" in default_account["targets"]
        assert default_account["targets"]["codex"]["status"] == "success"

    def test_v1_empty_targets_migration(self, tmp_path):
        v1_state = {"version": 1, "targets": {}}
        (tmp_path / "state.json").write_text(json.dumps(v1_state))

        sm = StateManager(state_dir=tmp_path)
        assert sm.get_all_status()["version"] == 2
        assert sm.get_all_status()["accounts"] == {}

    def test_legacy_no_version_migration(self, tmp_path):
        """State without 'version' key (legacy cc2all) is wrapped in v2."""
        legacy = {"some_old_key": "value", "targets": {"old": True}}
        (tmp_path / "state.json").write_text(json.dumps(legacy))

        sm = StateManager(state_dir=tmp_path)
        state = sm.get_all_status()
        assert state["version"] == 2
        assert "migrated_from" in state

    def test_legacy_non_int_version_migration(self, tmp_path):
        """Non-integer version (e.g. string) treated as legacy."""
        bad = {"version": "beta", "data": 123}
        (tmp_path / "state.json").write_text(json.dumps(bad))

        sm = StateManager(state_dir=tmp_path)
        assert sm.get_all_status()["version"] == 2

    def test_corrupted_json_backed_up(self, tmp_path):
        """Corrupted JSON is backed up and fresh state returned."""
        (tmp_path / "state.json").write_text("{invalid json!!!")

        sm = StateManager(state_dir=tmp_path)
        state = sm.get_all_status()
        assert state["version"] == 2
        # Original corrupted file should be backed up
        backups = list(tmp_path.glob("state.json.bak.*"))
        assert len(backups) == 1

    def test_migrate_from_cc2all_no_old_state(self, tmp_path):
        old_dir = tmp_path / "old"
        new_dir = tmp_path / "new"
        old_dir.mkdir()

        sm = StateManager.migrate_from_cc2all(
            old_state_dir=old_dir, new_state_dir=new_dir
        )
        assert sm.get_all_status()["version"] == 2

    def test_migrate_from_cc2all_with_old_state(self, tmp_path):
        old_dir = tmp_path / "old"
        old_dir.mkdir()
        new_dir = tmp_path / "new"
        (old_dir / "sync-state.json").write_text(
            json.dumps({"last_sync": "2023-06-15T10:00:00"})
        )

        sm = StateManager.migrate_from_cc2all(
            old_state_dir=old_dir, new_state_dir=new_dir
        )
        assert sm.last_sync == "2023-06-15T10:00:00"
        assert "migrated_from_cc2all" in sm.get_all_status()


# ---------------------------------------------------------------------------
# record_sync
# ---------------------------------------------------------------------------

class TestRecordSync:
    def test_success_status(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {"f": "h"}, {"f": "copy"}, 5, 0, 0)
        assert sm.get_target_status("codex")["status"] == "success"

    def test_partial_status(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {}, {}, 3, 0, 2)
        assert sm.get_target_status("codex")["status"] == "partial"

    def test_failed_status(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {}, {}, 0, 0, 5)
        assert sm.get_target_status("codex")["status"] == "failed"

    def test_records_counts(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "project", {}, {}, 3, 2, 1)
        t = sm.get_target_status("codex")
        assert t["items_synced"] == 3
        assert t["items_skipped"] == 2
        assert t["items_failed"] == 1
        assert t["scope"] == "project"

    def test_records_file_hashes(self, tmp_path):
        hashes = {"/a.md": "abc123", "/b.md": "def456"}
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("gemini", "all", hashes, {}, 2, 0, 0)
        assert sm.get_target_status("gemini")["file_hashes"] == hashes

    def test_updates_last_sync(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {}, {}, 1, 0, 0)
        assert sm.last_sync is not None

    def test_account_scoped_record(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {"f": "h"}, {}, 1, 0, 0, account="work")

        status = sm.get_account_target_status("work", "codex")
        assert status is not None
        assert status["status"] == "success"

        # Flat targets should NOT have this entry
        assert sm.get_target_status("codex") is None

    def test_account_last_sync_updated(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("gemini", "all", {}, {}, 1, 0, 0, account="personal")
        acct = sm.get_account_status("personal")
        assert "last_sync" in acct

    def test_multiple_targets_independent(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {}, {}, 1, 0, 0)
        sm.record_sync("gemini", "all", {}, {}, 0, 0, 1)
        assert sm.get_target_status("codex")["status"] == "success"
        assert sm.get_target_status("gemini")["status"] == "failed"


# ---------------------------------------------------------------------------
# detect_drift
# ---------------------------------------------------------------------------

class TestDetectDrift:
    def test_no_previous_sync_all_new(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        drifted = sm.detect_drift("codex", {"a": "h1", "b": "h2"})
        assert set(drifted) == {"a", "b"}

    def test_no_drift(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        hashes = {"a": "h1", "b": "h2"}
        sm.record_sync("codex", "all", hashes, {}, 2, 0, 0)
        assert sm.detect_drift("codex", hashes) == []

    def test_changed_file_detected(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {"a": "h1"}, {}, 1, 0, 0)
        drifted = sm.detect_drift("codex", {"a": "h2_changed"})
        assert drifted == ["a"]

    def test_added_file_detected(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {"a": "h1"}, {}, 1, 0, 0)
        drifted = sm.detect_drift("codex", {"a": "h1", "b": "h2"})
        assert "b" in drifted

    def test_removed_file_detected(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {"a": "h1", "b": "h2"}, {}, 2, 0, 0)
        drifted = sm.detect_drift("codex", {"a": "h1"})
        assert "b" in drifted

    def test_empty_current_hashes(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {"a": "h1"}, {}, 1, 0, 0)
        drifted = sm.detect_drift("codex", {})
        assert drifted == ["a"]

    def test_drift_account_scoped(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {"a": "h1"}, {}, 1, 0, 0, account="work")
        drifted = sm.detect_drift("codex", {"a": "h2"}, account="work")
        assert drifted == ["a"]

    def test_drift_unknown_account_all_new(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        drifted = sm.detect_drift("codex", {"a": "h1"}, account="nonexistent")
        assert drifted == ["a"]


# ---------------------------------------------------------------------------
# Status queries
# ---------------------------------------------------------------------------

class TestStatusQueries:
    def test_get_target_status_missing(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.get_target_status("nonexistent") is None

    def test_get_account_target_status_missing_account(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.get_account_target_status("nope", "codex") is None

    def test_get_account_target_status_missing_target(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {}, {}, 1, 0, 0, account="work")
        assert sm.get_account_target_status("work", "gemini") is None

    def test_get_account_status_missing(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.get_account_status("nope") is None

    def test_list_state_accounts_empty(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.list_state_accounts() == []

    def test_list_state_accounts_sorted(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {}, {}, 1, 0, 0, account="zeta")
        sm.record_sync("codex", "all", {}, {}, 1, 0, 0, account="alpha")
        assert sm.list_state_accounts() == ["alpha", "zeta"]


# ---------------------------------------------------------------------------
# clear_target
# ---------------------------------------------------------------------------

class TestClearTarget:
    def test_clear_existing_target(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_sync("codex", "all", {}, {}, 1, 0, 0)
        sm.clear_target("codex")
        assert sm.get_target_status("codex") is None

    def test_clear_nonexistent_target_no_error(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.clear_target("nonexistent")  # Should not raise


# ---------------------------------------------------------------------------
# Global dry-run mode
# ---------------------------------------------------------------------------

class TestGlobalDryRun:
    def test_default_is_false(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.get_global_dry_run() is False

    def test_set_and_get(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.set_global_dry_run(True)
        assert sm.get_global_dry_run() is True

    def test_persists_across_instances(self, tmp_path):
        sm1 = StateManager(state_dir=tmp_path)
        sm1.set_global_dry_run(True)

        sm2 = StateManager(state_dir=tmp_path)
        assert sm2.get_global_dry_run() is True

    def test_disable_after_enable(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.set_global_dry_run(True)
        sm.set_global_dry_run(False)
        assert sm.get_global_dry_run() is False


# ---------------------------------------------------------------------------
# Plugin sync tracking
# ---------------------------------------------------------------------------

class TestPluginSync:
    def test_record_and_get_plugin_status(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        meta = {"my-plugin": {"version": "1.0", "mcp_count": 2}}
        sm.record_plugin_sync(meta)
        assert sm.get_plugin_status() == meta

    def test_record_plugin_replaces_entirely(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_plugin_sync({"old-plugin": {"version": "1.0"}})
        sm.record_plugin_sync({"new-plugin": {"version": "2.0"}})
        status = sm.get_plugin_status()
        assert "old-plugin" not in status
        assert "new-plugin" in status

    def test_plugin_status_empty_initially(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.get_plugin_status() == {}

    def test_account_scoped_plugin_sync(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        meta = {"p1": {"version": "1.0"}}
        sm.record_plugin_sync(meta, account="work")
        assert sm.get_plugin_status(account="work") == meta
        assert sm.get_plugin_status() == {}  # flat plugins untouched

    def test_detect_plugin_drift_added(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_plugin_sync({})
        drift = sm.detect_plugin_drift({"new": {"version": "1.0"}})
        assert drift == {"new": "added"}

    def test_detect_plugin_drift_removed(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_plugin_sync({"old": {"version": "1.0"}})
        drift = sm.detect_plugin_drift({})
        assert drift == {"old": "removed"}

    def test_detect_plugin_drift_version_changed(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_plugin_sync({"p": {"version": "1.0", "mcp_count": 2}})
        drift = sm.detect_plugin_drift({"p": {"version": "2.0", "mcp_count": 2}})
        assert "version_changed" in drift["p"]

    def test_detect_plugin_drift_mcp_count_changed(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_plugin_sync({"p": {"version": "1.0", "mcp_count": 2}})
        drift = sm.detect_plugin_drift({"p": {"version": "1.0", "mcp_count": 5}})
        assert "mcp_count_changed" in drift["p"]

    def test_detect_plugin_drift_no_drift(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        meta = {"p": {"version": "1.0", "mcp_count": 2}}
        sm.record_plugin_sync(meta)
        assert sm.detect_plugin_drift(meta) == {}

    def test_detect_plugin_drift_version_takes_priority(self, tmp_path):
        """When both version and mcp_count change, version_changed is reported."""
        sm = StateManager(state_dir=tmp_path)
        sm.record_plugin_sync({"p": {"version": "1.0", "mcp_count": 2}})
        drift = sm.detect_plugin_drift({"p": {"version": "2.0", "mcp_count": 5}})
        assert "version_changed" in drift["p"]
        assert "mcp_count_changed" not in drift["p"]


# ---------------------------------------------------------------------------
# Health score history
# ---------------------------------------------------------------------------

class TestHealthScoreHistory:
    def test_record_and_get(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_health_score("codex", 85, "good")
        history = sm.get_score_history("codex")
        assert len(history) == 1
        assert history[0]["score"] == 85
        assert history[0]["label"] == "good"

    def test_score_clamped_to_0_100(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        sm.record_health_score("codex", -10)
        sm.record_health_score("codex", 200)
        history = sm.get_score_history("codex")
        assert history[0]["score"] == 0
        assert history[1]["score"] == 100

    def test_history_trimmed_at_90(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        for i in range(100):
            sm.record_health_score("codex", i)
        history = sm.get_score_history("codex", n=200)
        assert len(history) == 90

    def test_get_score_history_empty(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.get_score_history("nonexistent") == []

    def test_get_score_history_n_limit(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        for i in range(10):
            sm.record_health_score("codex", i * 10)
        history = sm.get_score_history("codex", n=3)
        assert len(history) == 3
        # Should be the 3 most recent
        assert history[-1]["score"] == 90

    def test_sparkline_no_history(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        assert sm.format_score_sparkline("codex") == "(no history)"

    def test_sparkline_with_history(self, tmp_path):
        sm = StateManager(state_dir=tmp_path)
        for i in range(5):
            sm.record_health_score("codex", 80)
        sparkline = sm.format_score_sparkline("codex", width=10)
        assert "80/100" in sparkline
        assert len(sparkline) > 5
