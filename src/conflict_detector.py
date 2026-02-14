"""
Conflict detection via SHA256 hash comparison.

Detects manual config edits that would be overwritten by sync operations.
Uses hmac.compare_digest() for secure hash comparison to prevent timing attacks.
"""

import hmac
from pathlib import Path

from src.state_manager import StateManager
from src.utils.hashing import hash_file_sha256
from src.utils.logger import Logger


class ConflictDetector:
    """
    Hash-based conflict detection for manual config edits.

    Compares current file hashes against stored hashes from last sync.
    Uses hmac.compare_digest() for secure comparison (prevents timing attacks).
    """

    def __init__(self, state_manager: StateManager = None):
        """
        Initialize ConflictDetector.

        Args:
            state_manager: Optional StateManager for dependency injection.
                          Default: create new StateManager().
        """
        self.state_manager = state_manager or StateManager()

    def check(self, target_name: str) -> list[dict]:
        """
        Check if target config files have been modified outside HarnessSync.

        Args:
            target_name: Target to check ("codex", "gemini", "opencode")

        Returns:
            List of conflict dicts with keys:
                - file_path: Absolute path to modified file
                - stored_hash: Hash from last sync
                - current_hash: Current computed hash (or "" if deleted)
                - target_name: Target name
                - note: "deleted" if file was removed (optional)

            Empty list if no conflicts detected.
        """
        # Get stored state for target
        target_status = self.state_manager.get_target_status(target_name)
        if not target_status:
            # No previous sync - no conflicts possible
            return []

        # Extract file_hashes dict (maps file_path -> stored_hash)
        file_hashes = target_status.get("file_hashes", {})
        conflicts = []

        # Check each tracked file
        for file_path_str, stored_hash in file_hashes.items():
            file_path = Path(file_path_str)

            # Compute current hash
            current_hash = hash_file_sha256(file_path)

            # Check for deletion
            if not current_hash:
                conflicts.append({
                    "file_path": file_path_str,
                    "stored_hash": stored_hash,
                    "current_hash": "",
                    "target_name": target_name,
                    "note": "deleted"
                })
                continue

            # Secure hash comparison (prevents timing attacks)
            # Use hmac.compare_digest instead of == operator
            if not hmac.compare_digest(stored_hash, current_hash):
                conflicts.append({
                    "file_path": file_path_str,
                    "stored_hash": stored_hash,
                    "current_hash": current_hash,
                    "target_name": target_name
                })

        return conflicts

    def check_all(self) -> dict[str, list[dict]]:
        """
        Run conflict check for all targets.

        Returns:
            Dict mapping target_name -> list of conflicts
            Example: {"codex": [...], "gemini": [], "opencode": [...]}
        """
        targets = ["codex", "gemini", "opencode"]
        result = {}

        for target in targets:
            result[target] = self.check(target)

        return result

    def format_warnings(self, conflicts: dict[str, list[dict]]) -> str:
        """
        Format conflict warnings for user output.

        Args:
            conflicts: Dict from check_all() mapping target -> conflict list

        Returns:
            Formatted warning string showing modified/deleted files per target
        """
        if not conflicts or all(not v for v in conflicts.values()):
            return ""

        lines = []
        for target_name, target_conflicts in conflicts.items():
            if not target_conflicts:
                continue

            lines.append(f"\n⚠ {target_name.upper()}: {len(target_conflicts)} file(s) modified outside HarnessSync:")

            for conflict in target_conflicts:
                file_path = conflict["file_path"]
                note = conflict.get("note", "")

                if note == "deleted":
                    lines.append(f"  · {file_path} (deleted)")
                else:
                    lines.append(f"  · {file_path} (modified)")

        if not lines:
            return ""

        warning = "\n".join(lines)
        warning += "\n\nThese changes will be overwritten. Run with --dry-run to preview changes."

        return warning
