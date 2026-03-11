from __future__ import annotations

"""Unified diff output for dry-run preview mode.

DiffFormatter accumulates diffs across configuration types and produces
a formatted output showing what would change without writing files.
Supports text diffs (unified_diff), file diffs, and structural diffs
for JSON/TOML configs.

Change Cost Estimate (item 23):
DiffFormatter tracks write operations so it can produce a cost summary
before sync is executed:
- File count rewritten
- Symlinks recreated
- Lines added / removed
- Irreversible operations flagged
- Estimated time (rough: ~10ms/file for text, ~50ms for symlinks)

Native format preview (item 30):
add_native_preview() stores the fully-rendered target file content so
users can see exactly what AGENTS.md / opencode.json will look like.
"""

import difflib
from pathlib import Path


class SyncCostEstimate:
    """Quantitative cost summary for a planned sync operation.

    Produced by DiffFormatter.estimate_cost() from accumulated diff data.
    """

    def __init__(self):
        self.files_to_write: int = 0
        self.files_unchanged: int = 0
        self.symlinks_to_create: int = 0
        self.lines_added: int = 0
        self.lines_removed: int = 0
        self.irreversible_ops: list[str] = []
        self.target_breakdown: dict[str, dict] = {}

    @property
    def estimated_seconds(self) -> float:
        """Rough time estimate in seconds."""
        return (
            self.files_to_write * 0.010
            + self.symlinks_to_create * 0.050
            + (self.lines_added + self.lines_removed) * 0.0001
        )

    def format(self) -> str:
        """Return a human-readable cost summary."""
        lines = ["Sync Cost Estimate", "-" * 35]
        lines.append(f"  Files to write:    {self.files_to_write}")
        lines.append(f"  Files unchanged:   {self.files_unchanged}")
        if self.symlinks_to_create:
            lines.append(f"  Symlinks:          {self.symlinks_to_create}")
        lines.append(f"  Lines added:       +{self.lines_added}")
        lines.append(f"  Lines removed:     -{self.lines_removed}")
        lines.append(f"  Est. time:         ~{self.estimated_seconds:.1f}s")
        if self.irreversible_ops:
            lines.append("\n  ⚠ Irreversible operations:")
            for op in self.irreversible_ops:
                lines.append(f"    - {op}")
        if self.target_breakdown:
            lines.append("\n  Per-target breakdown:")
            for target, info in sorted(self.target_breakdown.items()):
                lines.append(
                    f"    {target:<12}: "
                    f"{info.get('files', 0)} file(s), "
                    f"+{info.get('added', 0)}/-{info.get('removed', 0)} lines"
                )
        return "\n".join(lines)


class DiffFormatter:
    """Accumulates and formats diff output for dry-run preview."""

    def __init__(self):
        self.diffs = []
        # Cost tracking
        self._files_to_write: int = 0
        self._files_unchanged: int = 0
        self._symlinks: int = 0
        self._lines_added: int = 0
        self._lines_removed: int = 0
        self._irreversible: list[str] = []
        self._target_breakdown: dict[str, dict] = {}
        # Native format previews
        self._native_previews: dict[str, str] = {}  # label -> rendered content

    def add_text_diff(
        self,
        label: str,
        old_content: str,
        new_content: str,
        target: str = "",
    ) -> None:
        """Generate unified diff between two text strings.

        Args:
            label: Section label (e.g., "rules", "AGENTS.md")
            old_content: Current content
            new_content: Proposed new content
            target: Optional target harness name for cost breakdown
        """
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff_lines = list(difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"current/{label}",
            tofile=f"synced/{label}",
            lineterm=""
        ))

        if diff_lines:
            self.diffs.append(f"--- {label} ---\n" + "\n".join(diff_lines))
            self._files_to_write += 1
            # Count added/removed lines from diff
            added = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
            self._lines_added += added
            self._lines_removed += removed
            if target:
                tb = self._target_breakdown.setdefault(target, {"files": 0, "added": 0, "removed": 0})
                tb["files"] += 1
                tb["added"] += added
                tb["removed"] += removed
        else:
            self.diffs.append(f"--- {label} ---\n[no changes]")
            self._files_unchanged += 1

    def add_file_diff(
        self,
        label: str,
        old_path: Path | None,
        new_content: str,
        target: str = "",
        irreversible: bool = False,
    ) -> None:
        """Generate diff between existing file and proposed content.

        Args:
            label: Section label
            old_path: Path to existing file (None if new file)
            new_content: Proposed new content
            target: Optional target harness name for cost breakdown
            irreversible: Mark as irreversible operation (e.g. file deletion)
        """
        old_content = ""
        if old_path and old_path.is_file():
            try:
                old_content = old_path.read_text(encoding='utf-8', errors='replace')
            except OSError:
                old_content = ""
        elif old_path is None:
            # New file creation
            if irreversible:
                self._irreversible.append(f"Create {label}")

        self.add_text_diff(label, old_content, new_content, target=target)

        if irreversible:
            self._irreversible.append(f"Overwrite {label} (irreversible)")

    def add_symlink_op(self, label: str, target: str = "") -> None:
        """Record a symlink creation operation for cost tracking.

        Args:
            label: Symlink label/description.
            target: Optional harness target name.
        """
        self._symlinks += 1
        self.diffs.append(f"--- {label} ---\n[symlink created/updated]")
        if target:
            tb = self._target_breakdown.setdefault(target, {"files": 0, "added": 0, "removed": 0})
            tb["files"] += 1

    def add_structural_diff(self, label: str, old_items: dict, new_items: dict) -> None:
        """Show added/removed/changed keys for structured data.

        Args:
            label: Section label (e.g., "mcp", "settings")
            old_items: Current config dict
            new_items: Proposed config dict
        """
        old_keys = set(old_items.keys())
        new_keys = set(new_items.keys())

        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)
        common = sorted(old_keys & new_keys)
        changed = [k for k in common if old_items[k] != new_items[k]]

        lines = [f"--- {label} ---"]
        if not added and not removed and not changed:
            lines.append("[no changes]")
        else:
            for k in added:
                lines.append(f"  + added: {k}")
            for k in removed:
                lines.append(f"  - removed: {k}")
            for k in changed:
                lines.append(f"  ~ changed: {k}")

        self.diffs.append("\n".join(lines))

    def add_native_preview(self, label: str, harness: str, content: str) -> None:
        """Store a native-format preview of what the target file will look like.

        This lets users see the actual AGENTS.md / opencode.json / .mdc content
        that will be written, in its final native format.

        Args:
            label: Human-readable label (e.g. "AGENTS.md for codex").
            harness: Target harness name.
            content: Fully-rendered content in the target's native format.
        """
        key = f"{harness}:{label}"
        self._native_previews[key] = content
        # Also add as a diff section
        preview_lines = content.splitlines()
        preview_text = "\n".join(f"  {line}" for line in preview_lines[:30])
        if len(preview_lines) > 30:
            preview_text += f"\n  ... ({len(preview_lines) - 30} more lines)"
        self.diffs.append(f"--- native preview: {label} ({harness}) ---\n{preview_text}")

    def get_native_preview(self, harness: str, label: str) -> str | None:
        """Retrieve a stored native format preview.

        Args:
            harness: Target harness name.
            label: Label used in add_native_preview().

        Returns:
            Preview content or None if not stored.
        """
        return self._native_previews.get(f"{harness}:{label}")

    def estimate_cost(self) -> "SyncCostEstimate":
        """Return a cost estimate object based on accumulated diff data.

        Returns:
            SyncCostEstimate with write counts, line changes, time estimate.
        """
        estimate = SyncCostEstimate()
        estimate.files_to_write = self._files_to_write
        estimate.files_unchanged = self._files_unchanged
        estimate.symlinks_to_create = self._symlinks
        estimate.lines_added = self._lines_added
        estimate.lines_removed = self._lines_removed
        estimate.irreversible_ops = list(self._irreversible)
        estimate.target_breakdown = {
            t: dict(info) for t, info in self._target_breakdown.items()
        }
        return estimate

    def format_output(self) -> str:
        """Join all accumulated diffs with section separators.

        Returns:
            Complete diff string for display
        """
        if not self.diffs:
            return "[no changes detected]"
        return "\n\n".join(self.diffs)

    def format_with_cost(self) -> str:
        """Format diffs followed by a cost estimate summary.

        Returns:
            Diff output + cost estimate block.
        """
        diff_output = self.format_output()
        cost = self.estimate_cost()
        return diff_output + "\n\n" + cost.format()
