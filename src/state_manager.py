"""
State management with atomic writes and drift detection.

Tracks per-target sync status with SHA256 file hashes, sync timestamps, and
drift detection. Uses atomic JSON writes (tempfile + os.replace) to prevent
corruption on interrupted writes.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from src.utils.paths import ensure_dir, read_json_safe


class StateManager:
    """
    Manages sync state with hash-based drift detection.

    State stored at ~/.harnesssync/state.json with per-target tracking
    (codex, gemini, opencode). Each target maintains file hashes, sync
    methods, status, and timestamps.

    State schema:
    {
        "version": 1,
        "last_sync": "2024-01-01T12:00:00",
        "targets": {
            "codex": {
                "last_sync": "2024-01-01T12:00:00",
                "status": "success",  # "success" | "partial" | "failed"
                "scope": "all",
                "file_hashes": {
                    "/path/to/AGENTS.md": "abc123...",
                    "/path/to/config.toml": "def456..."
                },
                "sync_method": {
                    "/path/to/skills/foo": "symlink",
                    "/path/to/skills/bar": "copy"
                },
                "items_synced": 5,
                "items_skipped": 2,
                "items_failed": 0
            }
        }
    }
    """

    def __init__(self, state_dir: Path = None):
        """
        Initialize StateManager.

        Args:
            state_dir: Directory for state file (default: ~/.harnesssync)
        """
        self.state_dir = state_dir or (Path.home() / ".harnesssync")
        self._state_file_path = self.state_dir / "state.json"
        self._state = self._load()

    def _load(self) -> dict:
        """
        Load state from JSON file.

        Returns:
            State dict with version and targets, or default empty state

        Handles:
        - Missing state file -> return default state
        - Corrupted JSON -> backup and return fresh state
        - Legacy cc2all state -> migrate to versioned schema
        """
        if not self._state_file_path.exists():
            return {"version": 1, "targets": {}}

        # Read with error handling
        state = read_json_safe(self._state_file_path, default={})

        # Check for corrupted state (read_json_safe returns {} on error)
        if not state:
            # Backup corrupted file
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = self.state_dir / f"state.json.bak.{timestamp}"
            try:
                self._state_file_path.rename(backup_path)
            except OSError:
                pass  # Backup failed, continue with fresh state

            return {"version": 1, "targets": {}}

        # Check for version key (missing = legacy cc2all state)
        if "version" not in state or not isinstance(state.get("version"), int):
            # Legacy state - migrate by wrapping old data
            migrated = {
                "version": 1,
                "targets": {},
                "migrated_from": state  # Preserve old data for reference
            }
            return migrated

        # Valid versioned state
        return state

    def _save(self) -> None:
        """
        Save state to JSON with atomic write.

        Uses tempfile + os.replace pattern to prevent corruption:
        1. Write to temp file in same directory
        2. Flush and fsync to disk
        3. Atomic rename to final path
        """
        ensure_dir(self.state_dir)

        # Create temp file in same directory (required for atomic os.replace)
        temp_fd = None
        temp_path = None

        try:
            # NamedTemporaryFile in same dir
            temp_fd = tempfile.NamedTemporaryFile(
                mode='w',
                dir=self.state_dir,
                suffix='.tmp',
                delete=False,
                encoding='utf-8'
            )
            temp_path = Path(temp_fd.name)

            # Write JSON with pretty formatting
            json.dump(self._state, temp_fd, indent=2, ensure_ascii=False)
            temp_fd.write('\n')  # Trailing newline

            # Ensure data written to disk
            temp_fd.flush()
            os.fsync(temp_fd.fileno())
            temp_fd.close()

            # Atomic rename (replaces existing file)
            os.replace(str(temp_path), str(self._state_file_path))

        except Exception:
            # Cleanup temp file on failure
            if temp_fd and not temp_fd.closed:
                temp_fd.close()
            if temp_path and temp_path.exists():
                temp_path.unlink()
            raise

    def record_sync(
        self,
        target: str,
        scope: str,
        file_hashes: dict[str, str],
        sync_methods: dict[str, str],
        synced: int,
        skipped: int,
        failed: int
    ) -> None:
        """
        Record sync operation for target.

        Args:
            target: Target name ("codex", "gemini", "opencode")
            scope: Sync scope ("all", "user", "project", etc.)
            file_hashes: Dict mapping absolute file paths to SHA256 hashes
            sync_methods: Dict mapping file paths to sync method used
            synced: Count of successfully synced items
            skipped: Count of skipped items
            failed: Count of failed items
        """
        # Determine status based on counts
        if failed == 0:
            status = "success"
        elif synced > 0 and failed > 0:
            status = "partial"
        else:  # synced == 0 and failed > 0
            status = "failed"

        # Update target state
        if "targets" not in self._state:
            self._state["targets"] = {}

        self._state["targets"][target] = {
            "last_sync": datetime.now().isoformat(),
            "status": status,
            "scope": scope,
            "file_hashes": file_hashes,
            "sync_method": sync_methods,
            "items_synced": synced,
            "items_skipped": skipped,
            "items_failed": failed
        }

        # Update global last_sync
        self._state["last_sync"] = datetime.now().isoformat()

        # Persist to disk
        self._save()

    def detect_drift(self, target: str, current_hashes: dict[str, str]) -> list[str]:
        """
        Detect drifted files by comparing current vs stored hashes.

        Args:
            target: Target name to check
            current_hashes: Dict of current file path -> hash

        Returns:
            List of file paths that changed, were added, or removed
        """
        # Get stored hashes for target
        target_state = self._state.get("targets", {}).get(target)
        if not target_state:
            # No previous sync - all files are "new"
            return list(current_hashes.keys())

        stored_hashes = target_state.get("file_hashes", {})
        drifted = []

        # Check for changed or new files
        for path, current_hash in current_hashes.items():
            stored_hash = stored_hashes.get(path)
            if stored_hash != current_hash:
                drifted.append(path)

        # Check for removed files
        for path in stored_hashes:
            if path not in current_hashes:
                drifted.append(path)

        return drifted

    def get_target_status(self, target: str) -> dict | None:
        """
        Get sync status for specific target.

        Args:
            target: Target name

        Returns:
            Target state dict, or None if not tracked
        """
        return self._state.get("targets", {}).get(target)

    def get_all_status(self) -> dict:
        """
        Get full state dict.

        Returns:
            Complete state including version and all targets
        """
        return self._state

    def clear_target(self, target: str) -> None:
        """
        Remove target from state and persist.

        Args:
            target: Target name to remove
        """
        if "targets" in self._state and target in self._state["targets"]:
            del self._state["targets"][target]
            self._save()

    @classmethod
    def migrate_from_cc2all(
        cls,
        old_state_dir: Path = None,
        new_state_dir: Path = None
    ) -> 'StateManager':
        """
        Migrate from old cc2all state to new HarnessSync state.

        Args:
            old_state_dir: Old ~/.cc2all directory (default: ~/.cc2all)
            new_state_dir: New ~/.harnesssync directory (default: ~/.harnesssync)

        Returns:
            StateManager instance with migrated data
        """
        old_state_dir = old_state_dir or (Path.home() / ".cc2all")
        new_state_dir = new_state_dir or (Path.home() / ".harnesssync")

        # Create new state manager
        sm = cls(state_dir=new_state_dir)

        # Check for old state file
        old_state_file = old_state_dir / "sync-state.json"
        if old_state_file.exists():
            old_state = read_json_safe(old_state_file, default={})

            # Copy last_sync if available
            if "last_sync" in old_state:
                sm._state["last_sync"] = old_state["last_sync"]

            # Store migration marker
            sm._state["migrated_from_cc2all"] = datetime.now().isoformat()

            # Save migrated state
            sm._save()

        return sm

    @property
    def last_sync(self) -> str | None:
        """Get last sync timestamp."""
        return self._state.get("last_sync")

    @property
    def state_file(self) -> Path:
        """Get state file path."""
        return self._state_file_path
