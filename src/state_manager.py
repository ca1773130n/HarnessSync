"""
State management with atomic writes and drift detection.

Tracks per-target sync status with SHA256 file hashes, sync timestamps, and
drift detection. Uses atomic JSON writes (tempfile + os.replace) to prevent
corruption on interrupted writes.

v2 schema adds per-account state nesting for multi-account support.
Auto-migrates v1 state (flat targets) to v2 (accounts.default.targets).
"""

import json
import os
import sys
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

    v2 schema (multi-account):
    {
        "version": 2,
        "last_sync": "2024-01-01T12:00:00",
        "accounts": {
            "default": {
                "last_sync": "...",
                "targets": { "codex": { ... } }
            }
        },
        "targets": { ... }  # Kept for backward compatibility
    }

    v1 schema (single account, backward compatible):
    {
        "version": 1,
        "last_sync": "2024-01-01T12:00:00",
        "targets": {
            "codex": {
                "last_sync": "2024-01-01T12:00:00",
                "status": "success",
                "scope": "all",
                "file_hashes": { ... },
                "sync_method": { ... },
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
        Load state from JSON file with v1-to-v2 migration.

        Returns:
            State dict with version and targets, or default empty state

        Handles:
        - Missing state file -> return default state
        - Corrupted JSON -> backup and return fresh state
        - Legacy cc2all state -> migrate to versioned schema
        - v1 state -> auto-migrate to v2 with 'default' account
        """
        if not self._state_file_path.exists():
            return {"version": 2, "targets": {}, "accounts": {}}

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

            return {"version": 2, "targets": {}, "accounts": {}}

        # Check for version key (missing = legacy cc2all state)
        if "version" not in state or not isinstance(state.get("version"), int):
            # Legacy state - migrate by wrapping old data
            migrated = {
                "version": 2,
                "targets": {},
                "accounts": {},
                "migrated_from": state  # Preserve old data for reference
            }
            return migrated

        # v1 -> v2 migration: wrap flat targets in 'default' account
        if state.get("version") == 1 and "accounts" not in state:
            v1_targets = state.get("targets", {})
            if v1_targets:
                state["accounts"] = {
                    "default": {
                        "last_sync": state.get("last_sync"),
                        "targets": dict(v1_targets)  # Copy targets into default account
                    }
                }
                print("[HarnessSync] Migrated v1 state to v2 (multi-account) schema. "
                      "Existing targets wrapped in 'default' account.", file=sys.stderr)
            else:
                state["accounts"] = {}

            state["version"] = 2
            # Keep "targets" key for backward compatibility
            # Auto-save migrated state
            self._state = state
            ensure_dir(self.state_dir)
            self._save()

        # Ensure accounts key exists for v2
        state.setdefault("accounts", {})

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
        failed: int,
        account: str = None
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
            account: Account name for per-account tracking (None = v1 flat targets)
        """
        # Determine status based on counts
        if failed == 0:
            status = "success"
        elif synced > 0 and failed > 0:
            status = "partial"
        else:  # synced == 0 and failed > 0
            status = "failed"

        target_data = {
            "last_sync": datetime.now().isoformat(),
            "status": status,
            "scope": scope,
            "file_hashes": file_hashes,
            "sync_method": sync_methods,
            "items_synced": synced,
            "items_skipped": skipped,
            "items_failed": failed
        }

        if account is not None:
            # Account-scoped: write to accounts.{account}.targets.{target}
            if "accounts" not in self._state:
                self._state["accounts"] = {}
            if account not in self._state["accounts"]:
                self._state["accounts"][account] = {"targets": {}}
            if "targets" not in self._state["accounts"][account]:
                self._state["accounts"][account]["targets"] = {}

            self._state["accounts"][account]["targets"][target] = target_data
            self._state["accounts"][account]["last_sync"] = datetime.now().isoformat()
        else:
            # v1 backward compatible: write to flat targets
            if "targets" not in self._state:
                self._state["targets"] = {}
            self._state["targets"][target] = target_data

        # Update global last_sync
        self._state["last_sync"] = datetime.now().isoformat()

        # Persist to disk
        self._save()

    def detect_drift(self, target: str, current_hashes: dict[str, str],
                     account: str = None) -> list[str]:
        """
        Detect drifted files by comparing current vs stored hashes.

        Args:
            target: Target name to check
            current_hashes: Dict of current file path -> hash
            account: Account name for per-account drift (None = v1 flat targets)

        Returns:
            List of file paths that changed, were added, or removed
        """
        if account is not None:
            # Account-scoped drift detection
            account_state = self._state.get("accounts", {}).get(account)
            if not account_state:
                return list(current_hashes.keys())
            target_state = account_state.get("targets", {}).get(target)
        else:
            # v1 backward compatible
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
        Get sync status for specific target (v1 flat targets).

        Args:
            target: Target name

        Returns:
            Target state dict, or None if not tracked
        """
        return self._state.get("targets", {}).get(target)

    def get_account_target_status(self, account: str, target: str) -> dict | None:
        """
        Get sync status for specific account and target.

        Args:
            account: Account name
            target: Target name

        Returns:
            Target state dict, or None if not tracked
        """
        account_state = self._state.get("accounts", {}).get(account)
        if not account_state:
            return None
        return account_state.get("targets", {}).get(target)

    def get_account_status(self, account: str) -> dict | None:
        """
        Get full status for an account (last_sync + all targets).

        Args:
            account: Account name

        Returns:
            Account state dict, or None if not found
        """
        return self._state.get("accounts", {}).get(account)

    def list_state_accounts(self) -> list[str]:
        """List all account names in state."""
        return sorted(self._state.get("accounts", {}).keys())

    def get_all_status(self) -> dict:
        """
        Get full state dict.

        Returns:
            Complete state including version, targets, and accounts
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

    def record_plugin_sync(self, plugins_metadata: dict, account: str = None) -> None:
        """
        Record plugin metadata after successful sync.

        Args:
            plugins_metadata: Dict mapping plugin_name -> {version, mcp_count, mcp_servers, last_sync}
            account: Account name for per-account tracking (None = flat plugins section)

        Implementation:
            - REPLACES entire plugins section on each call (no merge) to avoid stale accumulation
            - Stores in accounts.{account}.plugins if account is not None
            - Stores in flat "plugins" section if account is None (v1 compat)
        """
        if account is not None:
            # Account-scoped: write to accounts.{account}.plugins
            if "accounts" not in self._state:
                self._state["accounts"] = {}
            if account not in self._state["accounts"]:
                self._state["accounts"][account] = {}

            # REPLACE entire plugins section (no merge)
            self._state["accounts"][account]["plugins"] = dict(plugins_metadata)
        else:
            # v1 backward compatible: write to flat plugins
            # REPLACE entire plugins section (no merge)
            self._state["plugins"] = dict(plugins_metadata)

        # Persist to disk
        self._save()

    def detect_plugin_drift(self, current_plugins: dict, account: str = None) -> dict:
        """
        Detect plugin drift by comparing current vs stored plugin metadata.

        Args:
            current_plugins: Dict mapping plugin_name -> {version, mcp_count, mcp_servers, last_sync}
            account: Account name for per-account drift (None = flat plugins section)

        Returns:
            Dict mapping plugin_name -> drift reason string (empty dict = no drift)
            Drift reasons: "removed", "added", "version_changed: {old} -> {new}",
                          "mcp_count_changed: {old} -> {new}"
            Priority: version_changed > mcp_count_changed (if both changed, report version)
        """
        # Load stored plugins from appropriate location
        if account is not None:
            account_state = self._state.get("accounts", {}).get(account)
            if not account_state:
                stored_plugins = {}
            else:
                stored_plugins = account_state.get("plugins", {})
        else:
            stored_plugins = self._state.get("plugins", {})

        drift = {}

        # Check for removed plugins
        for plugin_name in stored_plugins:
            if plugin_name not in current_plugins:
                drift[plugin_name] = "removed"

        # Check for added or changed plugins
        for plugin_name, current_meta in current_plugins.items():
            if plugin_name not in stored_plugins:
                drift[plugin_name] = "added"
                continue

            stored_meta = stored_plugins[plugin_name]
            current_version = current_meta.get("version")
            stored_version = stored_meta.get("version")
            current_count = current_meta.get("mcp_count")
            stored_count = stored_meta.get("mcp_count")

            # Check version change (higher priority)
            if current_version != stored_version:
                drift[plugin_name] = f"version_changed: {stored_version} -> {current_version}"
            # Check MCP count change (only if version didn't change)
            elif current_count != stored_count:
                drift[plugin_name] = f"mcp_count_changed: {stored_count} -> {current_count}"

        return drift

    def get_plugin_status(self, account: str = None) -> dict:
        """
        Get stored plugin metadata.

        Args:
            account: Account name for per-account status (None = flat plugins section)

        Returns:
            Dict mapping plugin_name -> {version, mcp_count, mcp_servers, last_sync}
            Empty dict if no plugins tracked yet
        """
        if account is not None:
            account_state = self._state.get("accounts", {}).get(account)
            if not account_state:
                return {}
            return account_state.get("plugins", {})
        else:
            return self._state.get("plugins", {})

    @property
    def state_file(self) -> Path:
        """Get state file path."""
        return self._state_file_path
