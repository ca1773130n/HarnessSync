from __future__ import annotations

"""Live Capability Matrix — per-config-item sync status across all harnesses.

Unlike the static sync_capabilities matrix which shows general feature support
levels, this module inspects the *actual current config* (MCP servers, skills,
rules sections, env vars, permissions) and shows whether each specific item
will be fully synced, approximated, or lost in each target harness.

This answers the question: "Does Gemini support the 'context7' MCP server I
just added?" — without trial and error.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.constants import EXTENDED_TARGETS

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------
STATUS_FULL = "full"
STATUS_APPROX = "approx"
STATUS_NONE = "none"

_SYMBOLS = {STATUS_FULL: "✓", STATUS_APPROX: "~", STATUS_NONE: "✗"}
_LABELS = {STATUS_FULL: "Full", STATUS_APPROX: "Approx", STATUS_NONE: "No"}

# ---------------------------------------------------------------------------
# MCP transport compatibility: which harnesses support which transports.
# ---------------------------------------------------------------------------
_MCP_TRANSPORT_SUPPORT: dict[str, set[str]] = {
    "codex":    {"stdio"},
    "gemini":   {"stdio", "http", "sse"},
    "opencode": {"stdio", "http"},
    "cursor":   {"stdio", "http"},
    "aider":    set(),
    "windsurf": {"stdio", "http"},
    "cline":    {"stdio", "http"},
    "continue": {"stdio", "http"},
    "zed":      {"stdio"},
    "neovim":   {"stdio"},
}

# Harnesses that fully support MCP.
_MCP_CAPABLE: set[str] = {
    "codex", "gemini", "opencode", "cursor", "windsurf", "cline", "continue", "zed", "neovim"
}

# Harnesses that support skills/agents.
_SKILLS_CAPABLE: set[str] = {
    "codex", "gemini", "opencode", "cursor", "windsurf", "cline", "continue", "zed", "neovim"
}
_SKILLS_APPROX: set[str] = {"codex", "cursor"}  # Skills folded into rules/mdc

# Harnesses that support commands.
_COMMANDS_CAPABLE: set[str] = {
    "codex", "gemini", "opencode", "cursor", "windsurf", "cline", "continue"
}
_COMMANDS_APPROX: set[str] = {"codex", "cursor", "windsurf"}  # No $ARGUMENTS substitution

# Permission support tiers.
_PERM_FULL: set[str] = {"codex", "gemini", "opencode"}
_PERM_APPROX: set[str] = {"cursor", "windsurf", "aider"}

# Env var support.
_ENV_MCP_CAPABLE: set[str] = _MCP_CAPABLE  # Env vars live inside MCP server configs


def _infer_mcp_transport(server_config: dict) -> str:
    """Return 'stdio' or 'http' based on server config."""
    if "url" in server_config or "baseUrl" in server_config:
        return "http"
    return "stdio"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MatrixCell:
    """Status of one config item in one target harness."""
    status: str        # STATUS_FULL | STATUS_APPROX | STATUS_NONE
    note: str = ""     # Short explanation of limitations, if any


@dataclass
class MatrixRow:
    """One config item across all target harnesses."""
    category: str       # "mcp" | "skill" | "rule" | "permission" | "env"
    item_name: str      # Display name for the item
    cells: dict[str, MatrixCell] = field(default_factory=dict)


@dataclass
class CapabilityMatrix:
    """The full capability matrix for the current config."""
    rows: list[MatrixRow] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, dict[str, int]]:
        """Return per-target counts of full/approx/none cells."""
        result: dict[str, dict[str, int]] = {
            t: {STATUS_FULL: 0, STATUS_APPROX: 0, STATUS_NONE: 0}
            for t in self.targets
        }
        for row in self.rows:
            for target, cell in row.cells.items():
                result[target][cell.status] = result[target].get(cell.status, 0) + 1
        return result


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class CapabilityMatrixBuilder:
    """Build a CapabilityMatrix from live SourceReader data.

    Args:
        project_dir: Project root directory.
        targets: Optional list of target harnesses to include (default: all).
    """

    def __init__(self, project_dir: Path | None = None, targets: list[str] | None = None):
        self.project_dir = project_dir or Path.cwd()
        self.targets = targets or list(EXTENDED_TARGETS)

    def build(self, source_data: dict | None = None) -> CapabilityMatrix:
        """Build the matrix, reading live config if source_data not provided."""
        if source_data is None:
            try:
                from src.source_reader import SourceReader
                reader = SourceReader(project_dir=self.project_dir)
                source_data = reader.discover_all()
            except Exception:
                source_data = {}

        rows: list[MatrixRow] = []

        # --- MCP servers ---
        for name, cfg in source_data.get("mcp_servers", {}).items():
            transport = _infer_mcp_transport(cfg)
            cells = self._mcp_cells(name, cfg, transport)
            rows.append(MatrixRow(category="mcp", item_name=f"mcp:{name}", cells=cells))

        # --- Skills ---
        for name in source_data.get("skills", {}).keys():
            cells = self._skills_cells(name)
            rows.append(MatrixRow(category="skill", item_name=f"skill:{name}", cells=cells))

        # --- Agents ---
        for name in source_data.get("agents", {}).keys():
            cells = self._agents_cells(name)
            rows.append(MatrixRow(category="agent", item_name=f"agent:{name}", cells=cells))

        # --- Commands ---
        for name in source_data.get("commands", {}).keys():
            cells = self._commands_cells(name)
            rows.append(MatrixRow(category="command", item_name=f"cmd:{name}", cells=cells))

        # --- Permissions from settings ---
        settings = source_data.get("settings", {})
        allowed = settings.get("allowedTools", settings.get("permissions", {}).get("allow", []))
        denied = settings.get("deniedTools", settings.get("permissions", {}).get("deny", []))
        if allowed or denied:
            cells = self._permission_cells(allowed, denied)
            rows.append(MatrixRow(category="permission", item_name="permissions", cells=cells))

        # --- Env vars from MCP configs ---
        env_names: list[str] = []
        for cfg in source_data.get("mcp_servers", {}).values():
            env_names.extend(cfg.get("env", {}).keys())
        if env_names:
            cells = self._env_cells(env_names)
            rows.append(MatrixRow(category="env", item_name=f"env vars ({len(env_names)})", cells=cells))

        # --- Rules sections ---
        rules_content = source_data.get("rules", "")
        if rules_content:
            cells = self._rules_cells(rules_content)
            rows.append(MatrixRow(category="rules", item_name="CLAUDE.md rules", cells=cells))

        return CapabilityMatrix(rows=rows, targets=self.targets)

    # ------------------------------------------------------------------
    # Per-category cell builders
    # ------------------------------------------------------------------

    def _mcp_cells(self, name: str, cfg: dict, transport: str) -> dict[str, MatrixCell]:
        cells: dict[str, MatrixCell] = {}
        for t in self.targets:
            if t not in _MCP_CAPABLE:
                cells[t] = MatrixCell(STATUS_NONE, "MCP not supported")
            elif transport not in _MCP_TRANSPORT_SUPPORT.get(t, set()):
                cells[t] = MatrixCell(STATUS_NONE, f"{transport} transport not supported")
            else:
                cells[t] = MatrixCell(STATUS_FULL, "")
        return cells

    def _skills_cells(self, name: str) -> dict[str, MatrixCell]:
        cells: dict[str, MatrixCell] = {}
        for t in self.targets:
            if t == "aider":
                cells[t] = MatrixCell(STATUS_NONE, "no skill concept")
            elif t in _SKILLS_APPROX:
                cells[t] = MatrixCell(STATUS_APPROX, "tool refs rewritten")
            else:
                cells[t] = MatrixCell(STATUS_FULL, "")
        return cells

    def _agents_cells(self, name: str) -> dict[str, MatrixCell]:
        cells: dict[str, MatrixCell] = {}
        for t in self.targets:
            if t in ("aider", "codex"):
                cells[t] = MatrixCell(STATUS_APPROX, "folded into rules")
            else:
                cells[t] = MatrixCell(STATUS_FULL, "")
        return cells

    def _commands_cells(self, name: str) -> dict[str, MatrixCell]:
        cells: dict[str, MatrixCell] = {}
        for t in self.targets:
            if t not in _COMMANDS_CAPABLE:
                cells[t] = MatrixCell(STATUS_NONE, "no command concept")
            elif t in _COMMANDS_APPROX:
                cells[t] = MatrixCell(STATUS_APPROX, "no $ARGUMENTS")
            else:
                cells[t] = MatrixCell(STATUS_FULL, "")
        return cells

    def _permission_cells(self, allowed: list, denied: list) -> dict[str, MatrixCell]:
        cells: dict[str, MatrixCell] = {}
        for t in self.targets:
            if t in _PERM_FULL:
                cells[t] = MatrixCell(STATUS_FULL, "")
            elif t in _PERM_APPROX:
                cells[t] = MatrixCell(STATUS_APPROX, "as comment block")
            else:
                cells[t] = MatrixCell(STATUS_NONE, "no permission model")
        return cells

    def _env_cells(self, names: list[str]) -> dict[str, MatrixCell]:
        cells: dict[str, MatrixCell] = {}
        for t in self.targets:
            if t in _ENV_MCP_CAPABLE:
                cells[t] = MatrixCell(STATUS_FULL, "in MCP env block")
            else:
                cells[t] = MatrixCell(STATUS_NONE, "MCP not supported")
        return cells

    def _rules_cells(self, content: str) -> dict[str, MatrixCell]:
        cells: dict[str, MatrixCell] = {}
        for t in self.targets:
            # All targets receive rules; just note format difference
            cells[t] = MatrixCell(STATUS_FULL, "")
        return cells


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_matrix(matrix: CapabilityMatrix, detail: bool = False) -> str:
    """Render the capability matrix as an ASCII table.

    Args:
        matrix: The matrix to render.
        detail: If True, show per-cell notes under each row.

    Returns:
        Formatted table string.
    """
    if not matrix.rows:
        return "No config items found. Run from a Claude Code project directory."

    targets = matrix.targets
    name_width = max(len(r.item_name) for r in matrix.rows) + 2
    name_width = max(name_width, 20)
    col_w = 9

    lines: list[str] = []
    lines.append("HarnessSync Live Capability Matrix")
    lines.append("=" * (name_width + len(targets) * (col_w + 1) + 2))
    lines.append(
        f"  {'Config Item':<{name_width}}"
        + "".join(f" {t:<{col_w}}" for t in targets)
    )
    lines.append(
        "  " + "-" * name_width + "".join("-" * (col_w + 1) for _ in targets)
    )

    current_cat = None
    for row in matrix.rows:
        if row.category != current_cat:
            current_cat = row.category
            lines.append(f"\n  [{row.category.upper()}]")

        cells_str = ""
        for t in targets:
            cell = row.cells.get(t, MatrixCell(STATUS_NONE, "unknown"))
            sym = _SYMBOLS[cell.status]
            label = _LABELS[cell.status]
            cells_str += f" {sym + ' ' + label:<{col_w}}"

        lines.append(f"  {row.item_name:<{name_width}}{cells_str}")

        if detail:
            for t in targets:
                cell = row.cells.get(t, MatrixCell(STATUS_NONE, ""))
                if cell.note:
                    lines.append(f"    {t}: {cell.note}")

    lines.append("")
    lines.append(
        f"  Legend: {_SYMBOLS[STATUS_FULL]} Full sync  "
        f"{_SYMBOLS[STATUS_APPROX]} Approximated  "
        f"{_SYMBOLS[STATUS_NONE]} Not synced"
    )

    # Summary row
    summary = matrix.summary()
    lines.append("")
    lines.append("  Summary (full/approx/none):")
    summary_parts = []
    for t in targets:
        counts = summary[t]
        f = counts.get(STATUS_FULL, 0)
        a = counts.get(STATUS_APPROX, 0)
        n = counts.get(STATUS_NONE, 0)
        summary_parts.append(f"  {t}: {f}/{a}/{n}")
    lines.append("".join(summary_parts))

    return "\n".join(lines)
