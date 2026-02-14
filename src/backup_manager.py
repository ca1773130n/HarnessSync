"""
Pre-sync backup with timestamped storage and rollback context manager.

Provides BackupManager for creating timestamped backups under ~/.harnesssync/backups/,
with automatic rollback on sync failures. Implements SAF-01 from Phase 5 safety validation.

Based on rollback context pattern (Python rollback library) and ISO 8601 timestamped
backup best practices.
"""

import shutil
from datetime import datetime
from pathlib import Path

from src.utils.logger import Logger
from src.utils.paths import ensure_dir


class BackupManager:
    """
    Timestamped backup manager with rollback capabilities.

    Features:
    - Creates timestamped backups under ~/.harnesssync/backups/{target_name}/
    - Preserves symlink structure (does NOT follow symlinks during backup)
    - LIFO rollback order on sync failure
    - Configurable retention policy (default: keep 10 most recent backups)
    """

    def __init__(self, backup_root: Path = None, logger: Logger = None):
        """
        Initialize backup manager.

        Args:
            backup_root: Root directory for backups (default: ~/.harnesssync/backups/)
            logger: Optional logger for backup operations
        """
        if backup_root is None:
            backup_root = Path.home() / '.harnesssync' / 'backups'

        self.backup_root = backup_root
        self.logger = logger or Logger()

    def backup_target(self, target_path: Path, target_name: str) -> Path:
        """
        Create timestamped backup of a target config file or directory.

        Args:
            target_path: Path to file or directory to backup
            target_name: Target name (e.g., 'codex', 'opencode', 'gemini')

        Returns:
            Path to created backup directory

        Raises:
            OSError: If backup creation fails
        """
        # Generate timestamp in YYYYMMDD_HHMMSS format
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Create backup directory structure: backup_root/{target_name}/{filename}_{timestamp}/
        backup_name = f"{target_path.name}_{timestamp}"
        backup_dir = self.backup_root / target_name / backup_name

        # Ensure parent directory exists
        ensure_dir(backup_dir.parent)

        try:
            if target_path.is_dir():
                # For directories: use copytree with symlinks=True to preserve symlink structure
                # CRITICAL: Do NOT follow symlinks (per RESEARCH.md Pitfall 2)
                shutil.copytree(target_path, backup_dir / target_path.name, symlinks=True)
            else:
                # For files: use copy2 to preserve metadata
                ensure_dir(backup_dir)
                shutil.copy2(target_path, backup_dir / target_path.name)

            self.logger.debug(f"Backed up {target_path} to {backup_dir}")
            return backup_dir

        except (OSError, shutil.Error) as e:
            self.logger.error(f"Backup failed for {target_path}: {e}")
            raise

    def rollback(self, backups: list[tuple[Path, Path]]):
        """
        Restore files from backup in LIFO order.

        Args:
            backups: List of (backup_path, original_path) tuples to restore

        Note:
            Best-effort rollback: logs errors but continues processing remaining backups.
            Does not raise on individual restore failures (per RESEARCH.md).
        """
        # Process in LIFO order (reversed)
        for backup_path, original_path in reversed(backups):
            try:
                # Remove failed sync result first
                if original_path.exists():
                    if original_path.is_dir():
                        shutil.rmtree(original_path)
                    else:
                        original_path.unlink()

                # Restore from backup
                # Find the actual backed-up content (backup_dir contains the original name)
                backup_content = backup_path / original_path.name

                if not backup_content.exists():
                    self.logger.warn(f"Backup content not found: {backup_content}")
                    continue

                if backup_content.is_dir():
                    # Restore directory with symlinks preserved
                    shutil.copytree(backup_content, original_path, symlinks=True)
                else:
                    # Restore file with metadata
                    shutil.copy2(backup_content, original_path)

                self.logger.info(f"Restored {original_path} from backup")

            except (OSError, shutil.Error) as e:
                # Log error but continue (best-effort rollback)
                self.logger.error(f"Rollback failed for {original_path}: {e}")

    def cleanup_old_backups(self, target_name: str, keep_count: int = 10):
        """
        Remove old backups beyond retention policy.

        Args:
            target_name: Target name (e.g., 'codex', 'opencode')
            keep_count: Number of most recent backups to keep (default: 10)

        Note:
            Failure to delete old backups does not raise (per RESEARCH.md).
            Logs errors but continues operation.
        """
        target_backup_dir = self.backup_root / target_name

        if not target_backup_dir.exists():
            return

        try:
            # Get all backup directories for this target
            backups = [d for d in target_backup_dir.iterdir() if d.is_dir()]

            # Sort by modification time, newest first
            backups.sort(key=lambda d: d.stat().st_mtime, reverse=True)

            # Delete backups beyond keep_count
            for old_backup in backups[keep_count:]:
                try:
                    shutil.rmtree(old_backup)
                    self.logger.debug(f"Deleted old backup: {old_backup.name}")
                except OSError as e:
                    # Log but continue (backup cleanup failures should not break sync)
                    self.logger.warn(f"Failed to delete old backup {old_backup.name}: {e}")

        except OSError as e:
            self.logger.warn(f"Backup cleanup failed for {target_name}: {e}")


class BackupContext:
    """
    Context manager for automatic rollback on exception.

    Usage:
        bm = BackupManager()
        with BackupContext(bm) as ctx:
            backup_path = bm.backup_target(target, 'codex')
            ctx.register(backup_path, target)
            # ... perform sync operation ...
            # If exception occurs, automatic rollback happens
    """

    def __init__(self, backup_manager: BackupManager):
        """
        Initialize backup context.

        Args:
            backup_manager: BackupManager instance to use for rollback
        """
        self.backup_manager = backup_manager
        self._backups = []

    def register(self, backup_path: Path, original_path: Path):
        """
        Register a backup for potential rollback.

        Args:
            backup_path: Path to backup directory
            original_path: Original file/directory path
        """
        self._backups.append((backup_path, original_path))

    def __enter__(self):
        """Enter context - return self for use in 'with' statement."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit context - rollback if exception occurred.

        Returns:
            False to propagate exception (do not suppress)
        """
        if exc_type is not None:
            # Exception occurred - perform rollback
            self.backup_manager.logger.warn("Exception during sync - rolling back changes")
            self.backup_manager.rollback(self._backups)

        # Do not suppress exception
        return False
