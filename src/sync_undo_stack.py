from __future__ import annotations

"""Per-harness sync undo/redo stack (item 30: Sync Undo/Redo Stack).

Maintains a rolling stack of the last 20 sync operations per harness.
Before each sync writes a target config file, the previous content is
pushed onto the stack so it can be restored with a single ``undo()`` call.

Redo is supported: undoing an operation pushes the replaced content onto
a redo stack, allowing ``redo()`` to re-apply the sync if the user
changed their mind.

Storage layout:
    ~/.harnesssync/undo_stacks/
        <harness>/
            stack.json       — ordered list of stack entries (newest first)

Each entry in stack.json:
    {
        "timestamp": "2026-03-13T10:00:00Z",
        "label":     "pre-sync: rules + mcp",
        "files": {
            "AGENTS.md": "<previous file content>",
            "...": "..."
        }
    }

Stack depth is capped at MAX_STACK_DEPTH entries per harness.
The redo stack is discarded whenever a new sync entry is pushed
(matching standard undo/redo semantics).
"""

import difflib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict


# Maximum number of undo entries stored per harness
MAX_STACK_DEPTH = 20

# Root directory for all undo stacks
_UNDO_ROOT = Path.home() / ".harnesssync" / "undo_stacks"


class StackEntry(TypedDict):
    """One entry in the per-harness undo/redo stack."""
    timestamp: str
    label: str
    files: dict[str, str]   # relative file path -> content snapshot


class UndoResult:
    """Result returned by ``undo()`` and ``redo()``."""

    def __init__(
        self,
        ok: bool,
        harness: str,
        label: str,
        files_restored: list[str],
        error: str = "",
    ) -> None:
        self.ok = ok
        self.harness = harness
        self.label = label
        self.files_restored = files_restored
        self.error = error

    def format(self) -> str:
        if not self.ok:
            return f"Undo failed for '{self.harness}': {self.error}"
        lines = [
            f"Undo successful — '{self.harness}'",
            f"  Restored from: {self.label}",
            f"  Files restored: {len(self.files_restored)}",
        ]
        for f in self.files_restored:
            lines.append(f"    ✓ {f}")
        return "\n".join(lines)


class HarnessUndoStack:
    """Per-harness undo/redo stack backed by JSON files on disk.

    Args:
        harness:    Target harness name (e.g. "codex", "gemini").
        root_dir:   Base directory for stack storage (default: ~/.harnesssync/undo_stacks/).
        project_dir: Project root for resolving relative file paths on restore.
    """

    def __init__(
        self,
        harness: str,
        root_dir: Path | None = None,
        project_dir: Path | None = None,
    ) -> None:
        self.harness = harness
        self.root_dir = root_dir or _UNDO_ROOT
        self.project_dir = project_dir or Path.cwd()
        self._harness_dir = self.root_dir / harness
        self._stack_file = self._harness_dir / "stack.json"
        self._redo_file = self._harness_dir / "redo_stack.json"

    # ── persistence helpers ──────────────────────────────────────────────────

    def _ensure_dir(self) -> None:
        self._harness_dir.mkdir(parents=True, exist_ok=True)

    def _load(self, path: Path) -> list[StackEntry]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError):
            pass
        return []

    def _save(self, path: Path, entries: list[StackEntry]) -> None:
        self._ensure_dir()
        path.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── public API ───────────────────────────────────────────────────────────

    def push(self, files: dict[str, str], label: str = "") -> None:
        """Push a snapshot of ``files`` onto the undo stack.

        Call this BEFORE writing new config files so the previous state
        is saved and can be restored by ``undo()``.

        Pushing clears the redo stack (matching standard UX conventions).

        Args:
            files:  Dict mapping relative file path → current file content.
            label:  Human-readable description of the operation being saved.
        """
        if not files:
            return

        entry: StackEntry = {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "label": label or f"pre-sync snapshot ({len(files)} file(s))",
            "files": dict(files),
        }

        stack = self._load(self._stack_file)
        # Insert newest entry at position 0
        stack.insert(0, entry)
        # Trim to max depth
        if len(stack) > MAX_STACK_DEPTH:
            stack = stack[:MAX_STACK_DEPTH]
        self._save(self._stack_file, stack)

        # Clear redo stack — new operation breaks the redo chain
        if self._redo_file.exists():
            self._redo_file.unlink()

    def undo(self, dry_run: bool = False) -> UndoResult:
        """Restore the most recent undo entry for this harness.

        Pops the top entry from the undo stack, writes the saved file
        contents back to disk, and pushes the replaced content onto the
        redo stack.

        Args:
            dry_run: If True, report what would be restored without writing.

        Returns:
            UndoResult with restore outcome.
        """
        stack = self._load(self._stack_file)
        if not stack:
            return UndoResult(
                ok=False,
                harness=self.harness,
                label="",
                files_restored=[],
                error="undo stack is empty — nothing to undo",
            )

        entry = stack.pop(0)
        files_restored: list[str] = []

        if not dry_run:
            # Capture current state for redo before overwriting
            current_files: dict[str, str] = {}
            for rel_path in entry["files"]:
                abs_path = self.project_dir / rel_path
                if abs_path.exists():
                    try:
                        current_files[rel_path] = abs_path.read_text(encoding="utf-8")
                    except OSError:
                        current_files[rel_path] = ""

            # Write saved content back to disk
            errors: list[str] = []
            for rel_path, content in entry["files"].items():
                abs_path = self.project_dir / rel_path
                try:
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_text(content, encoding="utf-8")
                    files_restored.append(rel_path)
                except OSError as exc:
                    errors.append(f"{rel_path}: {exc}")

            if errors:
                return UndoResult(
                    ok=False,
                    harness=self.harness,
                    label=entry["label"],
                    files_restored=files_restored,
                    error="; ".join(errors),
                )

            # Push current state onto redo stack
            redo_entry: StackEntry = {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "label": f"redo: {entry['label']}",
                "files": current_files,
            }
            redo_stack = self._load(self._redo_file)
            redo_stack.insert(0, redo_entry)
            if len(redo_stack) > MAX_STACK_DEPTH:
                redo_stack = redo_stack[:MAX_STACK_DEPTH]
            self._save(self._redo_file, redo_stack)

            # Save the popped undo stack
            self._save(self._stack_file, stack)
        else:
            files_restored = list(entry["files"].keys())

        return UndoResult(
            ok=True,
            harness=self.harness,
            label=entry["label"],
            files_restored=files_restored,
        )

    def redo(self, dry_run: bool = False) -> UndoResult:
        """Re-apply the most recently undone operation.

        Args:
            dry_run: If True, report what would be restored without writing.

        Returns:
            UndoResult with restore outcome.
        """
        redo_stack = self._load(self._redo_file)
        if not redo_stack:
            return UndoResult(
                ok=False,
                harness=self.harness,
                label="",
                files_restored=[],
                error="redo stack is empty — nothing to redo",
            )

        entry = redo_stack.pop(0)
        files_restored: list[str] = []

        if not dry_run:
            # Capture current state for undo before overwriting
            current_files: dict[str, str] = {}
            for rel_path in entry["files"]:
                abs_path = self.project_dir / rel_path
                if abs_path.exists():
                    try:
                        current_files[rel_path] = abs_path.read_text(encoding="utf-8")
                    except OSError:
                        current_files[rel_path] = ""

            errors: list[str] = []
            for rel_path, content in entry["files"].items():
                abs_path = self.project_dir / rel_path
                try:
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    abs_path.write_text(content, encoding="utf-8")
                    files_restored.append(rel_path)
                except OSError as exc:
                    errors.append(f"{rel_path}: {exc}")

            if errors:
                return UndoResult(
                    ok=False,
                    harness=self.harness,
                    label=entry["label"],
                    files_restored=files_restored,
                    error="; ".join(errors),
                )

            # Push current state back onto undo stack
            undo_entry: StackEntry = {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "label": f"pre-redo: {entry['label']}",
                "files": current_files,
            }
            undo_stack = self._load(self._stack_file)
            undo_stack.insert(0, undo_entry)
            if len(undo_stack) > MAX_STACK_DEPTH:
                undo_stack = undo_stack[:MAX_STACK_DEPTH]
            self._save(self._stack_file, undo_stack)
            self._save(self._redo_file, redo_stack)
        else:
            files_restored = list(entry["files"].keys())

        return UndoResult(
            ok=True,
            harness=self.harness,
            label=entry["label"],
            files_restored=files_restored,
        )

    def depth(self) -> int:
        """Return the number of entries currently on the undo stack."""
        return len(self._load(self._stack_file))

    def redo_depth(self) -> int:
        """Return the number of entries currently on the redo stack."""
        return len(self._load(self._redo_file))

    def clear(self) -> None:
        """Clear both undo and redo stacks for this harness."""
        for path in (self._stack_file, self._redo_file):
            if path.exists():
                path.unlink()

    def list_entries(self) -> list[dict[str, str]]:
        """Return a summary list of undo stack entries (without file content).

        Returns:
            List of dicts with 'timestamp', 'label', 'file_count' keys.
        """
        return [
            {
                "timestamp": e["timestamp"],
                "label": e["label"],
                "file_count": str(len(e.get("files", {}))),
            }
            for e in self._load(self._stack_file)
        ]

    def diff_preview(self) -> str:
        """Return a unified diff showing what undo() would restore.

        Compares the saved snapshot (what would be restored) against the
        current on-disk file content. Lets users see what will change
        BEFORE committing to an undo.

        Returns:
            Unified diff string, or a message if nothing to undo / no changes.
        """
        stack = self._load(self._stack_file)
        if not stack:
            return f"[{self.harness}] Undo stack is empty — nothing to preview."

        entry = stack[0]  # Top of stack (would be popped by undo())
        diff_chunks: list[str] = []

        for rel_path, saved_content in entry.get("files", {}).items():
            abs_path = self.project_dir / rel_path
            if abs_path.exists():
                try:
                    current = abs_path.read_text(encoding="utf-8")
                except OSError:
                    current = ""
            else:
                current = ""

            saved_lines = saved_content.splitlines(keepends=True)
            current_lines = current.splitlines(keepends=True)

            if saved_lines == current_lines:
                continue  # No difference for this file

            chunk = list(difflib.unified_diff(
                current_lines,
                saved_lines,
                fromfile=f"current/{rel_path}",
                tofile=f"restored/{rel_path}",
                lineterm="",
            ))
            if chunk:
                diff_chunks.append("\n".join(chunk))

        if not diff_chunks:
            label = entry.get("label", "?")
            return (
                f"[{self.harness}] No differences — current files match the "
                f"snapshot '{label}'. Undo would be a no-op."
            )

        label = entry.get("label", "?")
        header = (
            f"[{self.harness}] Undo preview — would restore snapshot: '{label}'\n"
            + "=" * 60
        )
        return header + "\n\n" + "\n\n".join(diff_chunks)

    def undo_with_diff(self, show_diff: bool = True) -> tuple[str, UndoResult]:
        """Show a diff preview then perform the undo operation.

        Convenience method that combines diff_preview() and undo() so callers
        can present the diff to the user before the restore happens.

        Args:
            show_diff: If True, generate the diff preview. Set to False to
                       skip the diff and just undo (equivalent to undo()).

        Returns:
            Tuple of (diff_string, UndoResult). diff_string is empty if
            show_diff is False or the undo stack is empty.
        """
        diff = self.diff_preview() if show_diff else ""
        result = self.undo()
        return diff, result

    def format_status(self) -> str:
        """Format a human-readable status of the undo/redo stacks."""
        undo_entries = self._load(self._stack_file)
        redo_entries = self._load(self._redo_file)
        lines = [
            f"Undo/Redo Stack — {self.harness}",
            "=" * 40,
            f"  Undo depth:  {len(undo_entries)} / {MAX_STACK_DEPTH}",
            f"  Redo depth:  {len(redo_entries)} / {MAX_STACK_DEPTH}",
        ]
        if undo_entries:
            lines.append("")
            lines.append("  Last undo entries:")
            for i, entry in enumerate(undo_entries[:5], 1):
                ts = entry.get("timestamp", "?")[:19].replace("T", " ")
                label = entry.get("label", "?")
                fc = len(entry.get("files", {}))
                lines.append(f"    {i}. [{ts}]  {label}  ({fc} file(s))")
            if len(undo_entries) > 5:
                lines.append(f"    ... and {len(undo_entries) - 5} more")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Multi-harness facade
# ---------------------------------------------------------------------------

class SyncUndoManager:
    """Manages undo/redo stacks across multiple harnesses.

    Provides a single entry point for the sync orchestrator to push
    pre-sync snapshots and for users to undo/redo per harness.

    Args:
        root_dir:    Stack storage root (default: ~/.harnesssync/undo_stacks/).
        project_dir: Project root for resolving relative paths.
    """

    def __init__(
        self,
        root_dir: Path | None = None,
        project_dir: Path | None = None,
    ) -> None:
        self.root_dir = root_dir or _UNDO_ROOT
        self.project_dir = project_dir or Path.cwd()

    def _stack(self, harness: str) -> HarnessUndoStack:
        return HarnessUndoStack(harness, root_dir=self.root_dir, project_dir=self.project_dir)

    def push(self, harness: str, files: dict[str, str], label: str = "") -> None:
        """Save a pre-sync snapshot for ``harness``."""
        self._stack(harness).push(files, label=label)

    def undo(self, harness: str, dry_run: bool = False) -> UndoResult:
        """Undo the last sync for ``harness``."""
        return self._stack(harness).undo(dry_run=dry_run)

    def redo(self, harness: str, dry_run: bool = False) -> UndoResult:
        """Redo the last undone operation for ``harness``."""
        return self._stack(harness).redo(dry_run=dry_run)

    def status(self, harness: str) -> str:
        """Return formatted undo/redo status for ``harness``."""
        return self._stack(harness).format_status()

    def clear(self, harness: str) -> None:
        """Clear all undo/redo history for ``harness``."""
        self._stack(harness).clear()

    def format_all_status(self, harnesses: list[str] | None = None) -> str:
        """Format undo/redo status for all harnesses with stored stacks.

        Args:
            harnesses: Explicit list of harnesses to show. If None, auto-discovers
                       harnesses with existing stack directories.
        """
        if harnesses is None:
            if not self.root_dir.exists():
                return "No undo stacks found."
            harnesses = sorted(
                d.name for d in self.root_dir.iterdir() if d.is_dir()
            )

        if not harnesses:
            return "No undo stacks found."

        lines: list[str] = ["HarnessSync Undo/Redo Status", "=" * 50, ""]
        for h in harnesses:
            stack = self._stack(h)
            ud = stack.depth()
            rd = stack.redo_depth()
            lines.append(f"  {h:<12}  undo: {ud:>2}  redo: {rd:>2}")
        lines.append("")
        lines.append("Use /sync-rollback --undo <harness> to restore the previous state.")
        return "\n".join(lines)
