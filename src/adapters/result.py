"""Structured sync operation result.

SyncResult is a dataclass that tracks the outcome of sync operations
for each configuration type (rules, skills, agents, commands, MCP, settings).

Fields:
- synced: Count of successfully synced items
- skipped: Count of items skipped (already up-to-date or incompatible)
- failed: Count of items that failed to sync
- adapted: Count of items that required format adaptation
- synced_files: Paths of successfully synced files
- skipped_files: Paths of skipped files
- failed_files: Paths and reasons for failed files

The merge() method combines two results additively, useful for
aggregating results across multiple sync operations.
"""

from dataclasses import dataclass, field


@dataclass
class SyncResult:
    """Structured result for sync operations."""

    synced: int = 0
    skipped: int = 0
    failed: int = 0
    adapted: int = 0
    synced_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    failed_files: list[str] = field(default_factory=list)

    def merge(self, other: 'SyncResult') -> 'SyncResult':
        """Combine two sync results additively.

        Args:
            other: Another SyncResult to merge

        Returns:
            New SyncResult with counts added and file lists concatenated
        """
        return SyncResult(
            synced=self.synced + other.synced,
            skipped=self.skipped + other.skipped,
            failed=self.failed + other.failed,
            adapted=self.adapted + other.adapted,
            synced_files=self.synced_files + other.synced_files,
            skipped_files=self.skipped_files + other.skipped_files,
            failed_files=self.failed_files + other.failed_files,
        )

    @property
    def total(self) -> int:
        """Total number of items processed."""
        return self.synced + self.skipped + self.failed

    @property
    def status(self) -> str:
        """Overall sync status.

        Returns:
            - "success": All items synced successfully (failed == 0)
            - "partial": Some synced, some failed (synced > 0 and failed > 0)
            - "failed": All items failed (synced == 0 and failed > 0)
            - "nothing": No items processed (total == 0)
        """
        if self.total == 0:
            return "nothing"
        if self.failed == 0:
            return "success"
        if self.synced > 0 and self.failed > 0:
            return "partial"
        return "failed"
