"""
Broken symlink detection and removal for target directories.

Provides SymlinkCleaner for finding and removing broken symlinks from
.codex/skills/, .opencode/skills/, .opencode/agents/, and .opencode/commands/
directories. Implements SAF-05 from Phase 5 safety validation.

Based on pathlib documentation's broken symlink detection pattern:
is_symlink() and not exists().
"""

from pathlib import Path

from src.utils.logger import Logger


class SymlinkCleaner:
    """
    Broken symlink detector and cleaner for target directories.

    Features:
    - Detects broken symlinks using is_symlink() + not exists() pattern
    - Removes broken symlinks from target-specific directories
    - Preserves valid symlinks and regular files
    - Handles non-existent directories gracefully
    - Per-target cleanup (codex, opencode) or cleanup_all()
    """

    # Map target names to their symlink directories
    TARGET_DIRS = {
        'codex': ['.codex/skills/'],
        'opencode': [
            '.opencode/skills/',
            '.opencode/agents/',
            '.opencode/commands/'
        ],
        'gemini': []  # Gemini uses inline content, no symlinks
    }

    def __init__(self, project_dir: Path, logger: Logger = None):
        """
        Initialize symlink cleaner.

        Args:
            project_dir: Project directory (contains .codex/, .opencode/, etc.)
            logger: Optional logger for cleanup operations
        """
        self.project_dir = project_dir
        self.logger = logger or Logger()

    def find_broken_symlinks(self, directory: Path) -> list[Path]:
        """
        Find all broken symlinks in a directory (recursive).

        Args:
            directory: Directory to scan

        Returns:
            List of broken symlink paths

        Note:
            Uses is_symlink() and not exists() pattern per pathlib documentation.
            Does NOT use lexists() which returns True for broken links.
        """
        if not directory.exists() or not directory.is_dir():
            return []

        broken = []

        try:
            # Scan directory recursively
            for item in directory.rglob('*'):
                # Check if it's a symlink AND the target doesn't exist
                # CRITICAL: Use is_symlink() first, then exists()
                # exists() follows symlinks, so broken symlinks return False
                if item.is_symlink() and not item.exists():
                    broken.append(item)

        except (OSError, PermissionError) as e:
            # Handle permission errors gracefully
            self.logger.warn(f"Error scanning {directory}: {e}")

        return broken

    def cleanup(self, target_name: str) -> list[Path]:
        """
        Clean broken symlinks for a specific target.

        Args:
            target_name: Target name ('codex', 'opencode', or 'gemini')

        Returns:
            List of removed symlink paths

        Note:
            - Gemini returns empty list (no symlinks used)
            - Logs errors but continues processing remaining symlinks
        """
        if target_name not in self.TARGET_DIRS:
            self.logger.warn(f"Unknown target: {target_name}")
            return []

        removed = []

        # Get directories for this target
        target_dirs = self.TARGET_DIRS[target_name]

        for rel_dir in target_dirs:
            directory = self.project_dir / rel_dir

            # Find broken symlinks in this directory
            broken_links = self.find_broken_symlinks(directory)

            # Remove each broken symlink
            for broken_link in broken_links:
                try:
                    broken_link.unlink()
                    removed.append(broken_link)
                    self.logger.info(f"Removed broken symlink: {broken_link.relative_to(self.project_dir)}")
                except OSError as e:
                    # Log error but continue
                    self.logger.error(f"Failed to remove {broken_link}: {e}")

        return removed

    def cleanup_all(self) -> dict[str, list[Path]]:
        """
        Run cleanup for all targets.

        Returns:
            Dict mapping target_name -> list of removed paths

        Note:
            Runs cleanup for codex, opencode, and gemini (in that order).
        """
        results = {}

        for target_name in ['codex', 'opencode', 'gemini']:
            removed = self.cleanup(target_name)
            results[target_name] = removed

        return results
