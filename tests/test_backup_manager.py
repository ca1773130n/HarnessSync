from __future__ import annotations

"""Unit tests for src/backup_manager.py — file backups and rollback.

Covers:
- BackupManager: backup_target (files, directories, labels), rollback (LIFO),
  list_snapshots, restore_by_date, cleanup_old_backups
- BackupContext: context manager with auto-rollback on exception
- CloudBackupExporter: export_to_archive, restore_from_archive, _collect_files
- Helper functions: annotate_backup_context, get_backup_context,
  auto_snapshot_targets, format_snapshot_manifest
"""

import json
import os
import sys
import time
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backup_manager import (
    BackupContext,
    BackupManager,
    CloudBackupExporter,
    annotate_backup_context,
    auto_snapshot_targets,
    format_snapshot_manifest,
    get_backup_context,
)


# ---------------------------------------------------------------------------
# BackupManager.backup_target
# ---------------------------------------------------------------------------

class TestBackupTarget:
    def test_backup_file(self, tmp_path):
        """Backing up a file creates a timestamped directory containing the file."""
        target = tmp_path / "my_config.md"
        target.write_text("hello config")

        bm = BackupManager(backup_root=tmp_path / "backups")
        backup_dir = bm.backup_target(target, "codex")

        assert backup_dir.is_dir()
        restored = backup_dir / "my_config.md"
        assert restored.read_text() == "hello config"

    def test_backup_directory(self, tmp_path):
        target_dir = tmp_path / "my_dir"
        target_dir.mkdir()
        (target_dir / "a.txt").write_text("aaa")
        (target_dir / "b.txt").write_text("bbb")

        bm = BackupManager(backup_root=tmp_path / "backups")
        backup_dir = bm.backup_target(target_dir, "codex")

        inner = backup_dir / "my_dir"
        assert inner.is_dir()
        assert (inner / "a.txt").read_text() == "aaa"
        assert (inner / "b.txt").read_text() == "bbb"

    def test_backup_with_label(self, tmp_path):
        target = tmp_path / "config.md"
        target.write_text("data")

        bm = BackupManager(backup_root=tmp_path / "backups")
        backup_dir = bm.backup_target(target, "codex", label="before-refactor")

        assert "before-refactor" in backup_dir.name

    def test_backup_label_sanitized(self, tmp_path):
        target = tmp_path / "config.md"
        target.write_text("data")

        bm = BackupManager(backup_root=tmp_path / "backups")
        backup_dir = bm.backup_target(target, "codex", label="a/b c!d@e")

        # Special chars should be replaced with hyphens
        assert "/" not in backup_dir.name
        assert "!" not in backup_dir.name

    def test_backup_creates_metadata(self, tmp_path):
        target = tmp_path / "config.md"
        target.write_text("data")

        bm = BackupManager(backup_root=tmp_path / "backups")
        backup_dir = bm.backup_target(target, "codex", label="test-label")

        meta_file = backup_dir / ".harnesssync-snapshot.json"
        assert meta_file.exists()
        meta = json.loads(meta_file.read_text())
        assert meta["label"] == "test-label"
        assert meta["target_name"] == "codex"
        assert meta["source"] == str(target)

    def test_backup_nonexistent_raises(self, tmp_path):
        bm = BackupManager(backup_root=tmp_path / "backups")
        with pytest.raises(OSError):
            bm.backup_target(tmp_path / "nonexistent.md", "codex")

    def test_backup_stored_under_target_name(self, tmp_path):
        target = tmp_path / "config.md"
        target.write_text("data")

        bm = BackupManager(backup_root=tmp_path / "backups")
        backup_dir = bm.backup_target(target, "gemini")

        assert backup_dir.parent.name == "gemini"


# ---------------------------------------------------------------------------
# BackupManager.rollback
# ---------------------------------------------------------------------------

class TestRollback:
    def test_rollback_restores_file(self, tmp_path):
        original = tmp_path / "config.md"
        original.write_text("original content")

        bm = BackupManager(backup_root=tmp_path / "backups")
        backup_dir = bm.backup_target(original, "codex")

        # Simulate failed sync by overwriting
        original.write_text("corrupted by sync")

        bm.rollback([(backup_dir, original)])
        assert original.read_text() == "original content"

    def test_rollback_lifo_order(self, tmp_path):
        """Rollback processes in reversed (LIFO) order."""
        f1 = tmp_path / "first.md"
        f2 = tmp_path / "second.md"
        f1.write_text("first original")
        f2.write_text("second original")

        bm = BackupManager(backup_root=tmp_path / "backups")
        b1 = bm.backup_target(f1, "codex")
        b2 = bm.backup_target(f2, "codex")

        f1.write_text("first corrupted")
        f2.write_text("second corrupted")

        bm.rollback([(b1, f1), (b2, f2)])
        assert f1.read_text() == "first original"
        assert f2.read_text() == "second original"

    def test_rollback_missing_backup_content_continues(self, tmp_path):
        """Rollback skips entries where backup content is missing."""
        original = tmp_path / "config.md"
        original.write_text("data")

        bm = BackupManager(backup_root=tmp_path / "backups")
        fake_backup = tmp_path / "backups" / "fake"
        fake_backup.mkdir(parents=True)

        # Should not raise
        bm.rollback([(fake_backup, original)])

    def test_rollback_restores_directory(self, tmp_path):
        target_dir = tmp_path / "my_dir"
        target_dir.mkdir()
        (target_dir / "a.txt").write_text("original")

        bm = BackupManager(backup_root=tmp_path / "backups")
        backup_dir = bm.backup_target(target_dir, "codex")

        # Corrupt the directory
        (target_dir / "a.txt").write_text("corrupted")

        bm.rollback([(backup_dir, target_dir)])
        assert (target_dir / "a.txt").read_text() == "original"


# ---------------------------------------------------------------------------
# BackupManager.list_snapshots
# ---------------------------------------------------------------------------

class TestListSnapshots:
    def test_empty_when_no_backups(self, tmp_path):
        bm = BackupManager(backup_root=tmp_path / "backups")
        assert bm.list_snapshots() == []

    def test_lists_all_targets(self, tmp_path):
        f1 = tmp_path / "a.md"
        f2 = tmp_path / "b.md"
        f1.write_text("a")
        f2.write_text("b")

        bm = BackupManager(backup_root=tmp_path / "backups")
        bm.backup_target(f1, "codex")
        bm.backup_target(f2, "gemini")

        snapshots = bm.list_snapshots()
        targets = {s["target"] for s in snapshots}
        assert "codex" in targets
        assert "gemini" in targets

    def test_filter_by_target(self, tmp_path):
        f1 = tmp_path / "a.md"
        f1.write_text("a")

        bm = BackupManager(backup_root=tmp_path / "backups")
        bm.backup_target(f1, "codex")
        bm.backup_target(f1, "gemini")

        snapshots = bm.list_snapshots(target_name="codex")
        assert all(s["target"] == "codex" for s in snapshots)

    def test_snapshots_include_label(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("a")

        bm = BackupManager(backup_root=tmp_path / "backups")
        bm.backup_target(f, "codex", label="my-label")

        snapshots = bm.list_snapshots("codex")
        assert snapshots[0]["label"] == "my-label"

    def test_snapshots_sorted_newest_first(self, tmp_path):
        """Multiple backups with distinct labels produce distinct dirs."""
        f = tmp_path / "a.md"
        f.write_text("a")

        bm = BackupManager(backup_root=tmp_path / "backups")
        bm.backup_target(f, "codex", label="first")
        time.sleep(0.05)
        bm.backup_target(f, "codex", label="second")

        snapshots = bm.list_snapshots("codex")
        assert len(snapshots) == 2
        assert snapshots[0]["mtime"] >= snapshots[1]["mtime"]


# ---------------------------------------------------------------------------
# BackupManager.cleanup_old_backups
# ---------------------------------------------------------------------------

class TestCleanupOldBackups:
    def test_keeps_recent_backups(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("a")

        bm = BackupManager(backup_root=tmp_path / "backups")
        for i in range(5):
            bm.backup_target(f, "codex", label=f"run-{i}")

        bm.cleanup_old_backups("codex", keep_count=5)
        remaining = [d for d in (tmp_path / "backups" / "codex").iterdir() if d.is_dir()]
        assert len(remaining) == 5

    def test_removes_excess_backups(self, tmp_path):
        f = tmp_path / "a.md"
        f.write_text("a")

        bm = BackupManager(backup_root=tmp_path / "backups")
        for i in range(5):
            bm.backup_target(f, "codex", label=f"run-{i}")
            time.sleep(0.02)

        bm.cleanup_old_backups("codex", keep_count=2)
        remaining = [d for d in (tmp_path / "backups" / "codex").iterdir() if d.is_dir()]
        assert len(remaining) == 2

    def test_cleanup_nonexistent_target_no_error(self, tmp_path):
        bm = BackupManager(backup_root=tmp_path / "backups")
        bm.cleanup_old_backups("nonexistent")  # Should not raise


# ---------------------------------------------------------------------------
# BackupContext
# ---------------------------------------------------------------------------

class TestBackupContext:
    def test_no_rollback_on_success(self, tmp_path):
        original = tmp_path / "config.md"
        original.write_text("original")

        bm = BackupManager(backup_root=tmp_path / "backups")
        backup_dir = bm.backup_target(original, "codex")

        original.write_text("updated by sync")

        with BackupContext(bm) as ctx:
            ctx.register(backup_dir, original)
            # No exception → no rollback

        assert original.read_text() == "updated by sync"

    def test_rollback_on_exception(self, tmp_path):
        original = tmp_path / "config.md"
        original.write_text("original")

        bm = BackupManager(backup_root=tmp_path / "backups")
        backup_dir = bm.backup_target(original, "codex")

        with pytest.raises(RuntimeError):
            with BackupContext(bm) as ctx:
                ctx.register(backup_dir, original)
                original.write_text("corrupted by sync")
                raise RuntimeError("sync failed")

        assert original.read_text() == "original"

    def test_exception_propagates(self, tmp_path):
        bm = BackupManager(backup_root=tmp_path / "backups")
        with pytest.raises(ValueError, match="test error"):
            with BackupContext(bm):
                raise ValueError("test error")


# ---------------------------------------------------------------------------
# annotate_backup_context / get_backup_context
# ---------------------------------------------------------------------------

class TestBackupContextMetadata:
    def test_annotate_and_get(self, tmp_path):
        backup_dir = tmp_path / "backup1"
        backup_dir.mkdir()

        result = annotate_backup_context(
            backup_dir,
            trigger="manual /sync",
            changed_sections=["rules", "mcp"],
            changed_rule="new-format-rule",
        )
        assert result is True

        ctx = get_backup_context(backup_dir)
        assert ctx["trigger"] == "manual /sync"
        assert ctx["changed_sections"] == ["rules", "mcp"]
        assert ctx["changed_rule"] == "new-format-rule"

    def test_get_context_missing_dir(self, tmp_path):
        ctx = get_backup_context(tmp_path / "nonexistent")
        assert ctx["trigger"] is None
        assert ctx["changed_sections"] == []

    def test_annotate_updates_existing_metadata(self, tmp_path):
        backup_dir = tmp_path / "backup1"
        backup_dir.mkdir()
        meta_file = backup_dir / ".harnesssync-snapshot.json"
        meta_file.write_text(json.dumps({"label": "pre-sync", "timestamp": "123"}))

        annotate_backup_context(backup_dir, trigger="hook")
        ctx = get_backup_context(backup_dir)
        assert ctx["trigger"] == "hook"
        assert ctx["label"] == "pre-sync"  # Preserved existing field


# ---------------------------------------------------------------------------
# auto_snapshot_targets
# ---------------------------------------------------------------------------

class TestAutoSnapshot:
    def test_snapshots_existing_tracked_files(self, tmp_path):
        f = tmp_path / "config.md"
        f.write_text("content")

        state = {"targets": {"codex": {"file_hashes": {str(f): "hash1"}}}}
        result = auto_snapshot_targets(state, backup_root=tmp_path / "backups")

        assert "codex" in result
        assert len(result["codex"]) == 1

    def test_skips_nonexistent_files(self, tmp_path):
        state = {"targets": {"codex": {"file_hashes": {"/no/such/file.md": "h1"}}}}
        result = auto_snapshot_targets(state, backup_root=tmp_path / "backups")
        assert result == {}

    def test_empty_state(self, tmp_path):
        result = auto_snapshot_targets({}, backup_root=tmp_path / "backups")
        assert result == {}


# ---------------------------------------------------------------------------
# format_snapshot_manifest
# ---------------------------------------------------------------------------

class TestFormatSnapshotManifest:
    def test_empty_map(self):
        assert "no files" in format_snapshot_manifest({})

    def test_with_entries(self, tmp_path):
        snapshot_map = {"codex": [tmp_path / "backup1"], "gemini": [tmp_path / "backup2"]}
        output = format_snapshot_manifest(snapshot_map)
        assert "2 file(s)" in output
        assert "2 target(s)" in output
        assert "codex" in output


# ---------------------------------------------------------------------------
# CloudBackupExporter
# ---------------------------------------------------------------------------

class TestCloudBackupExporter:
    def test_export_to_archive(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "CLAUDE.md").write_text("# Rules")

        exporter = CloudBackupExporter(project_dir=project, cc_home=tmp_path / ".claude")
        archive_path = exporter.export_to_archive(tmp_path / "backup.zip")

        assert archive_path.exists()
        with zipfile.ZipFile(archive_path, "r") as zf:
            names = zf.namelist()
            assert any("CLAUDE" in n for n in names)
            assert any("manifest" in n for n in names)

    def test_export_archive_no_files_raises(self, tmp_path):
        project = tmp_path / "empty_project"
        project.mkdir()

        exporter = CloudBackupExporter(project_dir=project, cc_home=tmp_path / ".claude")
        with pytest.raises(OSError, match="No config files"):
            exporter.export_to_archive(tmp_path / "backup.zip")

    def test_restore_from_archive(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "CLAUDE.md").write_text("# Original Rules")

        exporter = CloudBackupExporter(project_dir=project, cc_home=tmp_path / ".claude")
        archive = exporter.export_to_archive(tmp_path / "backup.zip")

        restore_dir = tmp_path / "restored"
        restore_dir.mkdir()
        restored = CloudBackupExporter.restore_from_archive(archive, restore_dir)
        assert len(restored) >= 1

    def test_collect_files_skips_missing(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        # Only create one file
        (project / "CLAUDE.md").write_text("rules")

        exporter = CloudBackupExporter(project_dir=project, cc_home=tmp_path / ".claude")
        files = exporter._collect_files()
        assert "CLAUDE.md" in files
        assert "AGENTS.md" not in files  # Not created → skipped

    def test_export_to_gist_no_token_raises(self, tmp_path, monkeypatch):
        project = tmp_path / "project"
        project.mkdir()
        (project / "CLAUDE.md").write_text("rules")

        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        exporter = CloudBackupExporter(project_dir=project)
        with pytest.raises(ValueError, match="GitHub token"):
            exporter.export_to_gist(github_token="")


# ---------------------------------------------------------------------------
# restore_by_date
# ---------------------------------------------------------------------------

class TestRestoreByDate:
    def test_invalid_date_format(self, tmp_path):
        bm = BackupManager(backup_root=tmp_path / "backups")
        result = bm.restore_by_date("not-a-date")
        assert len(result["errors"]) == 1
        assert "Invalid date" in result["errors"][0][1]

    def test_no_snapshots_before_date(self, tmp_path):
        bm = BackupManager(backup_root=tmp_path / "backups")
        result = bm.restore_by_date("2020-01-01")
        assert result["restored"] == []
        assert len(result["skipped"]) == 1
