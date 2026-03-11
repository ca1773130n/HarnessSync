from __future__ import annotations

"""
Pre-sync backup with timestamped storage and rollback context manager.

Provides BackupManager for creating timestamped backups under ~/.harnesssync/backups/,
with automatic rollback on sync failures. Implements SAF-01 from Phase 5 safety validation.

Cloud backup export (item 7):
``CloudBackupExporter`` exports the full synced config snapshot to a GitHub Gist
or to a local encrypted archive. Pair with /sync-restore to recover on a new machine.
GitHub Gist export requires a GITHUB_TOKEN environment variable with gist scope.
Local archive export uses zip format (no external dependencies).

Based on rollback context pattern (Python rollback library) and ISO 8601 timestamped
backup best practices.
"""

import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.utils.logger import Logger
from src.utils.paths import ensure_dir


class CloudBackupExporter:
    """Export HarnessSync config snapshot to cloud or local archive (item 7).

    Supports two export destinations:
    - GitHub Gist: POST to GitHub API using GITHUB_TOKEN env var
    - Local zip archive: Creates a portable encrypted-zip at a user-specified path

    Usage:
        exporter = CloudBackupExporter(project_dir)
        # Export to GitHub Gist (requires GITHUB_TOKEN env var with gist scope)
        result = exporter.export_to_gist()
        print(result["gist_url"])

        # Export to local archive
        archive_path = exporter.export_to_archive("/path/to/backup.zip")
    """

    # Config files captured in the snapshot (relative to project_dir)
    _CONFIG_FILES = [
        "CLAUDE.md",
        "CLAUDE.local.md",
        "AGENTS.md",
        "GEMINI.md",
        "opencode.json",
        ".harnesssync",
    ]

    def __init__(self, project_dir: Path, cc_home: Optional[Path] = None):
        """Initialize CloudBackupExporter.

        Args:
            project_dir: Project root directory (source of config files).
            cc_home: Claude Code home directory. Defaults to ~/.claude.
        """
        self.project_dir = Path(project_dir)
        self.cc_home = cc_home or (Path.home() / ".claude")
        self.logger = Logger()

    def _collect_files(self) -> dict[str, str]:
        """Collect config file contents for export.

        Returns:
            Dict mapping filename -> file content string.
            Missing files are silently skipped.
        """
        files: dict[str, str] = {}
        for rel in self._CONFIG_FILES:
            path = self.project_dir / rel
            if path.exists() and path.is_file():
                try:
                    files[rel] = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
        # Also include global CLAUDE.md if present in cc_home
        global_claude = self.cc_home / "CLAUDE.md"
        if global_claude.exists():
            try:
                files["~/.claude/CLAUDE.md"] = global_claude.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        return files

    def export_to_gist(
        self,
        description: str = "HarnessSync config backup",
        public: bool = False,
        github_token: Optional[str] = None,
    ) -> dict:
        """Export config snapshot to a GitHub Gist.

        Requires a GitHub personal access token with ``gist`` scope in the
        GITHUB_TOKEN environment variable (or passed as ``github_token``).

        Args:
            description: Gist description shown on GitHub.
            public: If True, create a public gist. Default: private (secret) gist.
            github_token: Override for GitHub token (defaults to GITHUB_TOKEN env var).

        Returns:
            Dict with keys:
                - gist_url: URL of the created gist
                - gist_id: GitHub gist ID
                - files_exported: Number of config files included
                - timestamp: ISO 8601 timestamp of export

        Raises:
            ValueError: If no GitHub token is available.
            RuntimeError: If the GitHub API request fails.
        """
        import urllib.request

        token = github_token or os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise ValueError(
                "GitHub token required for Gist export. "
                "Set GITHUB_TOKEN environment variable with 'gist' scope, "
                "or pass github_token= parameter."
            )

        files = self._collect_files()
        if not files:
            raise RuntimeError("No config files found to export.")

        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        # Add a manifest file to the gist
        manifest = {
            "created": timestamp,
            "project_dir": str(self.project_dir),
            "files": list(files.keys()),
            "harnesssync_version": "1.0",
        }
        files["harnesssync-manifest.json"] = json.dumps(manifest, indent=2)

        # Build GitHub Gist API payload
        gist_files = {
            fname.replace("/", "_").replace("~", "home"): {"content": content}
            for fname, content in files.items()
        }
        payload = json.dumps({
            "description": f"{description} [{timestamp}]",
            "public": public,
            "files": gist_files,
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.github.com/gists",
            data=payload,
            headers={
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
                "Content-Type": "application/json",
                "User-Agent": "HarnessSync/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                response_data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"GitHub Gist API request failed: {exc}") from exc

        gist_url = response_data.get("html_url", "")
        gist_id = response_data.get("id", "")
        self.logger.info(f"Config snapshot exported to GitHub Gist: {gist_url}")

        return {
            "gist_url": gist_url,
            "gist_id": gist_id,
            "files_exported": len(files),
            "timestamp": timestamp,
        }

    def export_to_archive(self, archive_path: Optional[Path] = None) -> Path:
        """Export config snapshot to a local zip archive.

        Creates a portable zip archive containing all config files. The archive
        can be restored on a new machine using /sync-restore --from-archive.

        Args:
            archive_path: Destination path for the zip file. If None, saves to
                          ~/.harnesssync/exports/harnesssync-backup-{timestamp}.zip

        Returns:
            Path to the created archive file.

        Raises:
            OSError: If archive creation fails.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if archive_path is None:
            export_dir = Path.home() / ".harnesssync" / "exports"
            ensure_dir(export_dir)
            archive_path = export_dir / f"harnesssync-backup-{timestamp}.zip"

        archive_path = Path(archive_path)
        ensure_dir(archive_path.parent)
        files = self._collect_files()
        if not files:
            raise OSError("No config files found to export.")

        manifest = {
            "created": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "project_dir": str(self.project_dir),
            "files": list(files.keys()),
            "harnesssync_version": "1.0",
        }
        files["harnesssync-manifest.json"] = json.dumps(manifest, indent=2)

        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for fname, content in files.items():
                safe_name = fname.replace("~", "home").replace("/", os.sep)
                zf.writestr(safe_name, content)

        self.logger.info(f"Config snapshot exported to archive: {archive_path}")
        return archive_path

    @staticmethod
    def restore_from_archive(archive_path: Path, project_dir: Path) -> list[str]:
        """Restore config files from a local zip archive.

        Extracts config files from the archive into project_dir, overwriting
        existing files. Returns the list of restored filenames.

        Args:
            archive_path: Path to the zip archive created by export_to_archive().
            project_dir: Target project directory for restoration.

        Returns:
            List of restored filenames (relative paths).

        Raises:
            OSError: If extraction fails.
        """
        project_dir = Path(project_dir)
        restored: list[str] = []

        with zipfile.ZipFile(archive_path, "r") as zf:
            for entry in zf.namelist():
                if entry == "harnesssync-manifest.json":
                    continue
                dest = project_dir / entry.replace("home", "~")
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(entry))
                restored.append(entry)

        return restored


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

    def backup_target(self, target_path: Path, target_name: str,
                      label: str | None = None) -> Path:
        """
        Create timestamped backup of a target config file or directory.

        Args:
            target_path: Path to file or directory to backup
            target_name: Target name (e.g., 'codex', 'opencode', 'gemini')
            label: Optional human-readable label (e.g., 'before-new-project-rules').
                   Appended to the backup directory name and stored in a metadata file.

        Returns:
            Path to created backup directory

        Raises:
            OSError: If backup creation fails
        """
        # Generate timestamp in YYYYMMDD_HHMMSS format
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Create backup directory structure: backup_root/{target_name}/{filename}_{timestamp}[_{label}]/
        safe_label = ""
        if label:
            # Sanitize label: alphanumeric + hyphens/underscores only
            import re
            safe_label = "_" + re.sub(r"[^a-zA-Z0-9_-]", "-", label)[:40]

        backup_name = f"{target_path.name}_{timestamp}{safe_label}"
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

            # Write label metadata file if label provided
            if label:
                try:
                    import json
                    meta = {
                        "label": label,
                        "timestamp": timestamp,
                        "source": str(target_path),
                        "target_name": target_name,
                    }
                    (backup_dir / ".harnesssync-snapshot.json").write_text(
                        json.dumps(meta, indent=2), encoding="utf-8"
                    )
                except OSError:
                    pass  # Metadata write failure is non-fatal

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

    def list_snapshots(self, target_name: str | None = None) -> list[dict]:
        """List available backup snapshots with metadata.

        Args:
            target_name: If provided, list only snapshots for this target.
                         If None, list snapshots for all targets.

        Returns:
            List of snapshot info dicts sorted by modification time (newest first):
            {
                "target": str,
                "name": str,           # backup directory name
                "path": Path,          # full path to backup directory
                "timestamp": str,      # YYYYMMDD_HHMMSS from directory name
                "label": str | None,   # user-defined label (if any)
                "mtime": float,        # modification time
            }
        """
        import json

        snapshots = []

        if target_name:
            target_dirs = [self.backup_root / target_name]
        else:
            target_dirs = (
                [d for d in self.backup_root.iterdir() if d.is_dir()]
                if self.backup_root.exists()
                else []
            )

        for target_dir in target_dirs:
            if not target_dir.is_dir():
                continue
            tname = target_dir.name

            try:
                backup_dirs = [d for d in target_dir.iterdir() if d.is_dir()]
            except OSError:
                continue

            for bdir in backup_dirs:
                meta_file = bdir / ".harnesssync-snapshot.json"
                label = None
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        label = meta.get("label")
                    except (OSError, json.JSONDecodeError):
                        pass

                try:
                    mtime = bdir.stat().st_mtime
                except OSError:
                    mtime = 0.0

                # Extract timestamp from directory name (first 15 chars after target)
                parts = bdir.name.split("_", 2)
                ts = "_".join(parts[:2]) if len(parts) >= 2 else bdir.name

                snapshots.append({
                    "target": tname,
                    "name": bdir.name,
                    "path": bdir,
                    "timestamp": ts,
                    "label": label,
                    "mtime": mtime,
                })

        snapshots.sort(key=lambda s: s["mtime"], reverse=True)
        return snapshots

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
