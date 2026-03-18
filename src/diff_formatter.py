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
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Side-by-side diff (item 1 — Rich Sync Preview)
# ──────────────────────────────────────────────────────────────────────────────

_ANSI_GREEN = "\033[32m"
_ANSI_RED = "\033[31m"
_ANSI_CYAN = "\033[36m"
_ANSI_DIM = "\033[2m"
_ANSI_RESET = "\033[0m"


def _supports_color() -> bool:
    """Return True if the terminal supports ANSI color codes."""
    # Respect NO_COLOR env var (https://no-color.org/)
    if os.environ.get("NO_COLOR"):
        return False
    # Check if stdout is a TTY
    try:
        return os.isatty(1)
    except Exception:
        return False


def _color(text: str, code: str) -> str:
    """Wrap text in ANSI color if supported."""
    if _supports_color():
        return f"{code}{text}{_ANSI_RESET}"
    return text


def format_side_by_side(
    old_content: str,
    new_content: str,
    label: str = "",
    width: int = 0,
    context_lines: int = 3,
) -> str:
    """Render a side-by-side diff of two text strings.

    New lines appear in green, removed lines in red, unchanged lines
    are collapsed to context_lines surrounding changed sections.

    Args:
        old_content: Current/left-side content.
        new_content: Proposed/right-side content.
        label: Optional section header.
        width: Terminal column width (0 = auto-detect).
        context_lines: Lines of unchanged context around each change hunk.

    Returns:
        Formatted string suitable for terminal output.
    """
    if not width:
        try:
            width = shutil.get_terminal_size(fallback=(160, 40)).columns
        except Exception:
            width = 160

    # Each column gets roughly half, minus 3 chars for the separator
    col_w = max(20, (width - 3) // 2)

    old_lines = old_content.splitlines()
    new_lines = new_content.splitlines()

    # Build a sequence matcher to get change opcodes
    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    opcodes = matcher.get_opcodes()

    # Expand opcodes to include context lines, collapsing equal runs
    visible: list[tuple[str, int | None, int | None]] = []
    # visible entries: (tag, old_idx, new_idx) where None means blank

    def _add_equal(start_a: int, end_a: int, start_b: int, end_b: int) -> None:
        """Add up to context_lines lines from equal block, adding skip marker."""
        count = end_a - start_a
        if count <= context_lines * 2 + 1:
            for i in range(count):
                visible.append(("equal", start_a + i, start_b + i))
        else:
            for i in range(context_lines):
                visible.append(("equal", start_a + i, start_b + i))
            visible.append(("skip", None, None))
            for i in range(count - context_lines, count):
                visible.append(("equal", start_a + i, start_b + i))

    for tag, a0, a1, b0, b1 in opcodes:
        if tag == "equal":
            _add_equal(a0, a1, b0, b1)
        elif tag == "replace":
            for i in range(max(a1 - a0, b1 - b0)):
                oi = a0 + i if a0 + i < a1 else None
                ni = b0 + i if b0 + i < b1 else None
                visible.append(("replace", oi, ni))
        elif tag == "delete":
            for i in range(a1 - a0):
                visible.append(("delete", a0 + i, None))
        elif tag == "insert":
            for i in range(b1 - b0):
                visible.append(("insert", None, b0 + i))

    def _pad(text: str, w: int) -> str:
        """Truncate or pad text to exactly w characters."""
        if len(text) > w:
            return text[: w - 1] + "…"
        return text.ljust(w)

    lines_out: list[str] = []

    # Header
    if label:
        header = f"── {label} "
        lines_out.append(_color(header + "─" * max(0, width - len(header)), _ANSI_CYAN))
    else:
        lines_out.append(_color("─" * width, _ANSI_CYAN))

    col_header = _pad("  CURRENT", col_w) + " │ " + _pad("  AFTER SYNC", col_w)
    lines_out.append(_color(col_header, _ANSI_DIM))
    lines_out.append(_color("─" * col_w + "─┼─" + "─" * col_w, _ANSI_DIM))

    has_changes = False

    for tag, oi, ni in visible:
        if tag == "skip":
            skip_line = _pad("  ⋮", col_w) + " │ " + _pad("  ⋮", col_w)
            lines_out.append(_color(skip_line, _ANSI_DIM))
            continue

        old_text = old_lines[oi] if oi is not None else ""
        new_text = new_lines[ni] if ni is not None else ""

        if tag == "equal":
            left = _pad("  " + old_text, col_w)
            right = _pad("  " + new_text, col_w)
            lines_out.append(left + " │ " + right)
        elif tag in ("delete", "replace") and oi is not None and ni is None:
            # Deletion: show old on left, empty on right
            left = _color(_pad("- " + old_text, col_w), _ANSI_RED)
            right = _pad("", col_w)
            lines_out.append(left + " │ " + right)
            has_changes = True
        elif tag in ("insert", "replace") and oi is None and ni is not None:
            # Insertion: empty on left, show new on right
            left = _pad("", col_w)
            right = _color(_pad("+ " + new_text, col_w), _ANSI_GREEN)
            lines_out.append(left + " │ " + right)
            has_changes = True
        elif tag == "replace":
            # Both sides changed
            left = _color(_pad("- " + old_text, col_w), _ANSI_RED)
            right = _color(_pad("+ " + new_text, col_w), _ANSI_GREEN)
            lines_out.append(left + " │ " + right)
            has_changes = True

    if not has_changes:
        lines_out.append(_color("  (no changes)", _ANSI_DIM))

    return "\n".join(lines_out)


# ──────────────────────────────────────────────────────────────────────────────
# Semantic diff (item 8)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class SemanticChange:
    """A single semantic change expressed in human terms.

    Instead of 'line 47 changed', this represents changes like
    'bash tool permission: allow → deny' or 'new MCP server: filesystem'.
    """
    category: str    # e.g. "mcp_server", "tool_permission", "rule", "setting"
    action: str      # "added", "removed", "changed"
    subject: str     # e.g. "filesystem" (MCP name) or "bash" (tool name)
    old_value: str   # Previous value, empty string if added
    new_value: str   # New value, empty string if removed

    def format(self) -> str:
        """Return a one-line human-readable description."""
        if self.action == "added":
            return f"{self.category} added: {self.subject}"
        if self.action == "removed":
            return f"{self.category} removed: {self.subject}"
        # changed
        if self.old_value and self.new_value:
            return f"{self.category} '{self.subject}': {self.old_value} → {self.new_value}"
        return f"{self.category} '{self.subject}' changed"


def _extract_mcp_servers(content: str) -> dict[str, str]:
    """Extract MCP server names from JSON or TOML config content.

    Returns dict of server_name → command/url summary.
    """
    servers: dict[str, str] = {}
    # JSON: {"mcpServers": {"name": {"command": ..., "args": ...}}}
    try:
        data = json.loads(content)
        mcp_block = (
            data.get("mcpServers")
            or data.get("mcp_servers")
            or data.get("mcp", {}).get("servers", {})
        )
        if isinstance(mcp_block, dict):
            for name, cfg in mcp_block.items():
                if isinstance(cfg, dict):
                    cmd = cfg.get("command") or cfg.get("url", "")
                    servers[name] = str(cmd)
            return servers
    except (json.JSONDecodeError, TypeError):
        pass

    # TOML-style: [mcp_servers."name"]
    for m in re.finditer(r'\[mcp_servers\."([^"]+)"\]', content):
        name = m.group(1)
        servers[name] = ""
    return servers


def _extract_tool_permissions(content: str) -> dict[str, str]:
    """Extract tool permission settings from config content.

    Returns dict of tool_name → permission_value.
    """
    perms: dict[str, str] = {}
    # JSON: {"permissions": {"allow": [...], "deny": [...]}}
    try:
        data = json.loads(content)
        perm_block = data.get("permissions", {})
        if isinstance(perm_block, dict):
            for action in ("allow", "deny"):
                for tool in perm_block.get(action, []):
                    perms[str(tool)] = action
        return perms
    except (json.JSONDecodeError, TypeError):
        pass

    # Markdown/TOML-style: "allow: bash" or "deny: web_search"
    for m in re.finditer(r"\b(allow|deny)\s*:\s*(\w+)", content, re.IGNORECASE):
        perms[m.group(2)] = m.group(1).lower()
    return perms


def _extract_rules(content: str) -> list[str]:
    """Extract rule headings from CLAUDE.md-style markdown content."""
    return re.findall(r"^#{1,3}\s+(.+?)$", content, re.MULTILINE)


def compute_semantic_diff(old_content: str, new_content: str, label: str = "") -> list[SemanticChange]:
    """Compute a list of semantic changes between two config strings.

    Compares MCP servers, tool permissions, and rule headings to produce
    human-readable change descriptions rather than raw line diffs.

    Args:
        old_content: Previous config content.
        new_content: New config content.
        label: Optional label hint to select parser (e.g. "mcpServers", "rules").

    Returns:
        List of SemanticChange objects sorted by category then subject.
    """
    changes: list[SemanticChange] = []

    # --- MCP servers ---
    old_mcp = _extract_mcp_servers(old_content)
    new_mcp = _extract_mcp_servers(new_content)
    for name in set(old_mcp) | set(new_mcp):
        if name not in old_mcp:
            changes.append(SemanticChange("MCP server", "added", name, "", new_mcp[name]))
        elif name not in new_mcp:
            changes.append(SemanticChange("MCP server", "removed", name, old_mcp[name], ""))
        elif old_mcp[name] != new_mcp[name]:
            changes.append(SemanticChange("MCP server", "changed", name, old_mcp[name], new_mcp[name]))

    # --- Tool permissions ---
    old_perms = _extract_tool_permissions(old_content)
    new_perms = _extract_tool_permissions(new_content)
    for tool in set(old_perms) | set(new_perms):
        if tool not in old_perms:
            changes.append(SemanticChange("tool permission", "added", tool, "", new_perms[tool]))
        elif tool not in new_perms:
            changes.append(SemanticChange("tool permission", "removed", tool, old_perms[tool], ""))
        elif old_perms[tool] != new_perms[tool]:
            changes.append(SemanticChange(
                "tool permission", "changed", tool, old_perms[tool], new_perms[tool]
            ))

    # --- Rule headings ---
    old_rules = set(_extract_rules(old_content))
    new_rules = set(_extract_rules(new_content))
    for rule in sorted(new_rules - old_rules):
        changes.append(SemanticChange("rule section", "added", rule, "", ""))
    for rule in sorted(old_rules - new_rules):
        changes.append(SemanticChange("rule section", "removed", rule, "", ""))

    return sorted(changes, key=lambda c: (c.category, c.subject))


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

    def format_per_harness_summary(self) -> str:
        """Format a compact per-harness dry-run summary table.

        Shows one row per harness with file and line change counts.
        Designed for quick scanning before a real sync run.

        Returns:
            Formatted multi-line string, or empty string if no data.

        Example output::

            Dry-Run Summary — Per Harness
            ─────────────────────────────────────
              harness        files   added  removed  status
              codex              3    +142      -18  changes
              gemini             1      +8       -2  changes
              opencode           0       —        —  no change
              cursor             5     +67      -11  changes
            ─────────────────────────────────────
              Total              9    +217      -31
        """
        breakdown = self._target_breakdown
        if not breakdown:
            return ""

        lines = ["Dry-Run Summary — Per Harness", "─" * 52]
        lines.append(f"  {'harness':<14} {'files':>5}  {'added':>7}  {'removed':>8}  status")
        lines.append("  " + "─" * 50)

        total_files = 0
        total_added = 0
        total_removed = 0

        # Sort: harnesses with changes first, then alphabetically
        sorted_targets = sorted(
            breakdown.items(),
            key=lambda kv: (-(kv[1].get("files", 0)), kv[0]),
        )

        for target, info in sorted_targets:
            files = info.get("files", 0)
            added = info.get("added", 0)
            removed = info.get("removed", 0)
            status = "changes" if files > 0 else "no change"
            added_str = f"+{added}" if added else "—"
            removed_str = f"-{removed}" if removed else "—"
            lines.append(
                f"  {target:<14} {files:>5}  {added_str:>7}  {removed_str:>8}  {status}"
            )
            total_files += files
            total_added += added
            total_removed += removed

        unchanged = self._files_unchanged
        if unchanged:
            lines.append(
                f"  {'(unchanged)':<14} {'—':>5}  {'—':>7}  {'—':>8}  "
                f"{unchanged} file(s) unchanged"
            )

        lines.append("  " + "─" * 50)
        lines.append(
            f"  {'Total':<14} {total_files:>5}  +{total_added:>6}  -{total_removed:>7}"
        )
        return "\n".join(lines)

    def add_semantic_diff(
        self,
        label: str,
        old_content: str,
        new_content: str,
        target: str = "",
    ) -> list[SemanticChange]:
        """Compute and record a semantic diff between two config strings.

        Stores a human-readable semantic summary alongside the raw unified diff.
        Returns the list of SemanticChange objects for further inspection.

        Args:
            label: Section label for display.
            old_content: Previous config content.
            new_content: Proposed new content.
            target: Optional target harness name.

        Returns:
            List of SemanticChange objects.
        """
        changes = compute_semantic_diff(old_content, new_content, label)
        if changes:
            lines = [f"--- semantic diff: {label} ---"]
            for change in changes:
                lines.append(f"  {change.format()}")
            self.diffs.append("\n".join(lines))
            if target:
                tb = self._target_breakdown.setdefault(target, {"files": 0, "added": 0, "removed": 0})
                tb["files"] += 1
        else:
            self.diffs.append(f"--- semantic diff: {label} ---\n[no semantic changes]")
        return changes

    def format_semantic_summary(self) -> str:
        """Format all semantic changes from the accumulated diffs as a summary.

        Returns a compact, human-readable list of what actually changed in
        meaningful terms rather than raw line numbers.

        Returns:
            Formatted semantic summary string.
        """
        semantic_lines = []
        for entry in self.diffs:
            if entry.startswith("--- semantic diff:"):
                lines = entry.split("\n")
                for line in lines[1:]:
                    stripped = line.strip()
                    if stripped and stripped != "[no semantic changes]":
                        semantic_lines.append(stripped)
        if not semantic_lines:
            return "No semantic changes detected."
        result = ["Semantic Changes Summary", "─" * 40]
        result.extend(f"  {line}" for line in semantic_lines)
        return "\n".join(result)

    def format_side_by_side_report(self, width: int = 0, context_lines: int = 3) -> str:
        """Render all accumulated text diffs as side-by-side views.

        For each target file that has changes, produces a two-column view:
        left = current content, right = post-sync content, with removed
        lines in red and added lines in green.

        Args:
            width: Terminal column width (0 = auto-detect).
            context_lines: Unchanged context lines to show around each hunk.

        Returns:
            Complete formatted string, or empty string if no text diffs.
        """
        parts: list[str] = []
        for entry in self.diffs:
            if not entry.startswith("--- ") or "[no changes]" in entry:
                continue
            # Extract label from "--- label ---\n<diff>"
            first_line, _, rest = entry.partition("\n")
            label = first_line.strip("- ").strip()
            if not rest.strip() or rest.strip().startswith("---"):
                continue
            # Reconstruct old/new from unified diff lines
            old_lines: list[str] = []
            new_lines: list[str] = []
            for dl in rest.splitlines():
                if dl.startswith("+++") or dl.startswith("---") or dl.startswith("@@"):
                    continue
                if dl.startswith("+"):
                    new_lines.append(dl[1:])
                elif dl.startswith("-"):
                    old_lines.append(dl[1:])
                else:
                    # Context line: appears in both
                    old_lines.append(dl[1:] if dl.startswith(" ") else dl)
                    new_lines.append(dl[1:] if dl.startswith(" ") else dl)
            if not old_lines and not new_lines:
                continue
            parts.append(format_side_by_side(
                "\n".join(old_lines),
                "\n".join(new_lines),
                label=label,
                width=width,
                context_lines=context_lines,
            ))

        if not parts:
            return _color("[no file changes to preview]", _ANSI_DIM)
        return "\n\n".join(parts)

    def format_file_change_list(self, color: bool | None = None) -> str:
        """Render a concise color-coded per-file change list (item 28).

        Shows one line per file with:
        - Green '+ NEW' for new files (no prior content)
        - Red   '- DEL' for deletions
        - Cyan  '~ MOD' for modifications, with +N/-N line counts
        - Dim   '  ---' for unchanged files

        This is the quick-scan view users see before deciding whether to
        proceed with a sync. Designed to fit in a narrow terminal window.

        Args:
            color: Force color on/off. None = auto-detect from TTY.

        Returns:
            Formatted multi-line string.
        """
        use_color = _supports_color() if color is None else color

        def _c(text: str, code: str) -> str:
            return f"{code}{text}{_ANSI_RESET}" if use_color else text

        lines: list[str] = [
            _c("File Changes (dry-run)", _ANSI_CYAN),
            _c("─" * 52, _ANSI_DIM),
        ]

        new_count = mod_count = del_count = unc_count = 0

        for entry in self.diffs:
            if not entry.startswith("--- "):
                continue
            first_line, _, rest = entry.partition("\n")
            label = first_line.strip("- ").strip()

            # Skip semantic/native preview sections in this view
            if label.startswith("semantic diff:") or label.startswith("native preview:"):
                continue

            no_change = "[no changes]" in rest or not rest.strip()
            is_new = "new file" in rest.lower() or (not rest.strip() and "[no changes]" not in entry)

            # Count added/removed lines from embedded unified diff
            added = sum(
                1 for l in rest.splitlines()
                if l.startswith("+") and not l.startswith("+++")
            )
            removed = sum(
                1 for l in rest.splitlines()
                if l.startswith("-") and not l.startswith("---")
            )

            if no_change:
                unc_count += 1
                lines.append(_c(f"  ---  {label}", _ANSI_DIM))
            elif removed > 0 and added == 0:
                del_count += 1
                lines.append(_c(f"  DEL  {label}", _ANSI_RED))
            elif added > 0 and removed == 0:
                new_count += 1
                lines.append(_c(f"  NEW  {label}  (+{added})", _ANSI_GREEN))
            else:
                mod_count += 1
                delta = f"+{added}/-{removed}"
                lines.append(_c(f"  MOD  {label}  ({delta})", _ANSI_CYAN))

        lines.append(_c("─" * 52, _ANSI_DIM))
        summary_parts = []
        if new_count:
            summary_parts.append(_c(f"{new_count} new", _ANSI_GREEN))
        if mod_count:
            summary_parts.append(_c(f"{mod_count} modified", _ANSI_CYAN))
        if del_count:
            summary_parts.append(_c(f"{del_count} deleted", _ANSI_RED))
        if unc_count:
            summary_parts.append(_c(f"{unc_count} unchanged", _ANSI_DIM))
        if summary_parts:
            lines.append("  " + "  ·  ".join(summary_parts))
        else:
            lines.append(_c("  (no file changes)", _ANSI_DIM))

        return "\n".join(lines)

    def format_full_dry_run(self) -> str:
        """Format a complete dry-run report: file list + summary table + diffs + cost.

        Intended as the canonical output for ``--dry-run`` mode. Provides:
          1. Color-coded per-file change list (quick at-a-glance)
          2. Per-harness summary table (target breakdown)
          3. Full unified diffs (detailed review)
          4. Cost estimate (time / write count)

        Returns:
            Complete formatted string.
        """
        parts: list[str] = []

        file_list = self.format_file_change_list()
        if file_list:
            parts.append(file_list)

        summary = self.format_per_harness_summary()
        if summary:
            parts.append(summary)

        diff_output = self.format_output()
        if diff_output and diff_output != "[no changes detected]":
            parts.append(diff_output)
        elif not summary and not file_list:
            parts.append("[no changes detected]")

        cost = self.estimate_cost()
        if cost.files_to_write > 0 or cost.files_unchanged > 0:
            parts.append(cost.format())

        return "\n\n".join(parts) if parts else "[no changes detected]"
