from __future__ import annotations

"""
Conflict detection via SHA256 hash comparison.

Detects manual config edits that would be overwritten by sync operations.
Uses hmac.compare_digest() for secure hash comparison to prevent timing attacks.

Three-way diff (item 11):
When a conflict is detected, ``three_way_diff()`` generates a structured
three-column diff:
  - LEFT  = Claude Code source (what HarnessSync would write)
  - BASE  = Last-synced version (the common ancestor stored as hash)
  - RIGHT = Current target file (what the user manually edited)

Users can then choose per-block: keep theirs / use synced / merge.
The ``resolve_three_way_interactive()`` method presents this UI on a TTY.
"""

import difflib
import hmac
from pathlib import Path

from src.state_manager import StateManager
from src.utils.hashing import hash_file_sha256
from src.utils.logger import Logger


def _build_merge_template(source: str, current: str, label: str) -> str:
    """Build a conflict merge template with git-style conflict markers."""
    return (
        f"<<<<<<< SYNC SOURCE (HarnessSync would write this)\n"
        f"{source}"
        f"=======\n"
        f"{current}"
        f">>>>>>> CURRENT ({label})\n"
        f"\n"
        f"# Edit the content above: remove the conflict markers and keep what you want.\n"
        f"# Save and close the editor to apply your resolution.\n"
    )


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

    def resolve_interactive(self, conflicts: dict[str, list[dict]]) -> dict[str, str]:
        """Prompt the user to resolve each conflict interactively.

        For each conflicted file, asks whether to keep local modifications or
        accept the incoming sync (overwrite). Works only when stdin is a TTY;
        falls back to an empty dict (overwrite all) in non-interactive contexts.

        Args:
            conflicts: Dict from check_all() mapping target -> conflict list.

        Returns:
            Dict mapping file_path -> "keep" | "accept".
            Files absent from the returned dict default to "accept" (overwrite).
        """
        import sys

        if not sys.stdin.isatty():
            return {}

        resolutions: dict[str, str] = {}
        all_conflicts: list[dict] = [
            c for target_conflicts in conflicts.values() for c in target_conflicts
        ]

        if not all_conflicts:
            return resolutions

        print(f"\nHarnessSync detected {len(all_conflicts)} conflict(s) — local modifications "
              "exist that would be overwritten.")

        for conflict in all_conflicts:
            file_path = conflict["file_path"]
            target_name = conflict.get("target_name", "?")
            note = conflict.get("note", "")

            print(f"\n{'=' * 60}")
            print(f"File:   {file_path}")
            print(f"Target: {target_name}")
            if note == "deleted":
                print("Status: deleted after last sync")
            else:
                stored = conflict.get("stored_hash", "")[:12]
                current = conflict.get("current_hash", "")[:12]
                print(f"Status: modified  ({stored}... → {current}...)")

            print()
            print("  k) Keep local  — skip overwriting this file")
            print("  a) Accept sync — allow HarnessSync to overwrite")

            while True:
                try:
                    choice = input("  Choice [k/a]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\nResolution cancelled — defaulting to accept all remaining.")
                    return resolutions

                if choice in ("k", "keep"):
                    resolutions[file_path] = "keep"
                    print(f"  → Keeping local: {file_path}")
                    break
                elif choice in ("a", "accept"):
                    resolutions[file_path] = "accept"
                    print(f"  → Will overwrite: {file_path}")
                    break
                else:
                    print("  Enter 'k' to keep local or 'a' to accept sync.")

        return resolutions

    def three_way_diff(
        self,
        source_content: str,
        conflict: dict,
        base_content: str | None = None,
    ) -> dict:
        """Generate a three-way diff for a conflicted file.

        Produces a structured comparison of:
          - source: What HarnessSync would write (from Claude Code)
          - base:   Last-synced content (the common ancestor, if available)
          - current: What's in the target file right now (manually edited)

        Args:
            source_content: The content HarnessSync would write.
            conflict: A conflict dict from ``check()`` (contains file_path).
            base_content: The last-synced content. If None, treated as empty
                          (simulates no common ancestor).

        Returns:
            Dict with keys:
              - file_path: Conflicted file path
              - source_lines: Lines of what sync would write
              - base_lines: Lines of last-synced version (or [])
              - current_lines: Lines of current file
              - unified_source_vs_current: Unified diff source↔current
              - unified_base_vs_current: Unified diff base↔current
              - unified_base_vs_source: Unified diff base↔source
              - has_real_conflict: True if current ≠ source
        """
        file_path = conflict.get("file_path", "")
        fp = Path(file_path)

        current_content = ""
        if fp.exists():
            try:
                current_content = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

        base_content = base_content or ""

        source_lines = source_content.splitlines(keepends=True)
        base_lines = base_content.splitlines(keepends=True)
        current_lines = current_content.splitlines(keepends=True)

        def _udiff(a: list[str], b: list[str], fromfile: str, tofile: str) -> str:
            return "".join(difflib.unified_diff(a, b, fromfile=fromfile, tofile=tofile, lineterm="\n"))

        return {
            "file_path": file_path,
            "source_lines": source_lines,
            "base_lines": base_lines,
            "current_lines": current_lines,
            "unified_source_vs_current": _udiff(source_lines, current_lines, "sync-source", "current"),
            "unified_base_vs_current": _udiff(base_lines, current_lines, "last-synced", "current"),
            "unified_base_vs_source": _udiff(base_lines, source_lines, "last-synced", "sync-source"),
            "has_real_conflict": source_content != current_content,
        }

    def resolve_three_way_interactive(
        self,
        conflict: dict,
        three_way: dict,
    ) -> tuple[str, str]:
        """Present three-way diff in terminal and ask user to resolve.

        Shows the diff between (last-synced → current) and (last-synced → source)
        and offers per-file choices:
          s) Use synced  — accept HarnessSync's version
          k) Keep theirs — preserve the manual edit
          e) Edit manually — write a temp file and open $EDITOR

        Args:
            conflict: Conflict dict from ``check()``.
            three_way: Three-way diff dict from ``three_way_diff()``.

        Returns:
            Tuple of (resolution: "synced" | "keep" | "manual", final_content: str).
        """
        import os
        import subprocess
        import sys
        import tempfile

        file_path = three_way["file_path"]
        source_lines = three_way["source_lines"]
        current_lines = three_way["current_lines"]
        diff_source_vs_current = three_way["unified_source_vs_current"]
        diff_base_vs_current = three_way["unified_base_vs_current"]

        print(f"\n{'=' * 70}")
        print(f"THREE-WAY CONFLICT: {file_path}")
        print(f"{'=' * 70}")

        print("\n[ Changes: last-synced → manual edits (what YOU changed) ]")
        if diff_base_vs_current.strip():
            print(diff_base_vs_current[:3000])
        else:
            print("  (no diff from base)")

        print("\n[ Changes: last-synced → sync-source (what HARNESSSYNC would write) ]")
        if three_way["unified_base_vs_source"].strip():
            print(three_way["unified_base_vs_source"][:3000])
        else:
            print("  (no diff from base)")

        print("\nChoices:")
        print("  s) Use synced  — overwrite with HarnessSync version")
        print("  k) Keep theirs — preserve your manual edits, skip sync for this file")
        print("  e) Edit        — open a merge in $EDITOR (requires EDITOR env var)")

        while True:
            try:
                choice = input("\n  Choice [s/k/e]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled — defaulting to 'keep'.")
                return "keep", "".join(current_lines)

            if choice in ("s", "synced"):
                return "synced", "".join(source_lines)

            elif choice in ("k", "keep"):
                return "keep", "".join(current_lines)

            elif choice in ("e", "edit"):
                editor = os.environ.get("EDITOR", "vi")
                # Write merge template to temp file
                merge_content = _build_merge_template(
                    "".join(source_lines), "".join(current_lines), file_path
                )
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                ) as tf:
                    tf.write(merge_content)
                    tmp_path = tf.name

                try:
                    subprocess.run([editor, tmp_path], check=False)
                    final = Path(tmp_path).read_text(encoding="utf-8")
                except Exception as e:
                    print(f"  Editor failed: {e}. Defaulting to keep.")
                    final = "".join(current_lines)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

                return "manual", final

            else:
                print("  Enter 's', 'k', or 'e'.")

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
