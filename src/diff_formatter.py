"""Unified diff output for dry-run preview mode.

DiffFormatter accumulates diffs across configuration types and produces
a formatted output showing what would change without writing files.
Supports text diffs (unified_diff), file diffs, and structural diffs
for JSON/TOML configs.
"""

import difflib
from pathlib import Path


class DiffFormatter:
    """Accumulates and formats diff output for dry-run preview."""

    def __init__(self):
        self.diffs = []

    def add_text_diff(self, label: str, old_content: str, new_content: str) -> None:
        """Generate unified diff between two text strings.

        Args:
            label: Section label (e.g., "rules", "AGENTS.md")
            old_content: Current content
            new_content: Proposed new content
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
        else:
            self.diffs.append(f"--- {label} ---\n[no changes]")

    def add_file_diff(self, label: str, old_path: Path | None, new_content: str) -> None:
        """Generate diff between existing file and proposed content.

        Args:
            label: Section label
            old_path: Path to existing file (None if new file)
            new_content: Proposed new content
        """
        old_content = ""
        if old_path and old_path.is_file():
            try:
                old_content = old_path.read_text(encoding='utf-8', errors='replace')
            except OSError:
                old_content = ""

        self.add_text_diff(label, old_content, new_content)

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

    def format_output(self) -> str:
        """Join all accumulated diffs with section separators.

        Returns:
            Complete diff string for display
        """
        if not self.diffs:
            return "[no changes detected]"
        return "\n\n".join(self.diffs)
