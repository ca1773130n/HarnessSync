from __future__ import annotations

"""Permissions Drift Viewer — matrix of allowed/denied/missing permissions per harness.

Security-conscious teams need to verify that a ``deny`` in Claude Code actually
propagated correctly to Cursor, Windsurf, and other harnesses — not just assume
it did.  This module reads the permissions/allowed-tools configuration from
the Claude Code source and from each synced harness's config, then renders a
side-by-side matrix so gaps are immediately visible.

Source permissions come from ``settings.json`` (Claude Code):
    { "permissions": { "allow": ["Bash"], "deny": ["WebSearch"] } }

Harness permission representations vary:
    - Gemini: ``tools.allowed`` / ``tools.exclude`` in ``.gemini/settings.json``
    - Cursor: No declarative permission model (permissions implicit via tool availability)
    - Codex: ``approval_policy`` field in ``.codex/config.toml`` (full_auto / none)
    - Aider: ``allowed_commands`` in ``.aider.conf.yml``
    - OpenCode: ``permissions`` block in ``opencode.json``
    - Windsurf / others: No formal permission API (rules-based only)

Usage::

    viewer = PermissionsDriftViewer(project_dir=Path("."))
    matrix = viewer.build_matrix()
    print(viewer.format_matrix(matrix))

    # Check if a specific deny propagated everywhere:
    gaps = viewer.find_missing_denies(matrix)
    if gaps:
        print("Deny rules NOT propagated:", gaps)
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class PermissionEntry:
    """A single tool permission as recorded in a harness config."""

    tool: str        # e.g. "Bash", "WebSearch", "Read"
    action: str      # "allow" | "deny" | "unknown"
    source: str      # "settings.json" | "gemini/settings.json" | …


@dataclass
class HarnessPermissions:
    """Collected permissions for one harness target."""

    harness: str
    entries: list[PermissionEntry] = field(default_factory=list)
    config_found: bool = False
    parse_error: str = ""

    def allowed(self) -> set[str]:
        return {e.tool for e in self.entries if e.action == "allow"}

    def denied(self) -> set[str]:
        return {e.tool for e in self.entries if e.action == "deny"}


@dataclass
class PermissionsDriftMatrix:
    """Cross-harness permission comparison."""

    source: HarnessPermissions                    # Claude Code as the reference
    targets: dict[str, HarnessPermissions]       # harness_name → permissions
    all_tools: list[str] = field(default_factory=list)   # union of all tools mentioned


# ---------------------------------------------------------------------------
# Readers — one per harness config format
# ---------------------------------------------------------------------------

def _read_claude_code_permissions(project_dir: Path, cc_home: Path | None = None) -> HarnessPermissions:
    """Read permissions from Claude Code settings.json."""
    hp = HarnessPermissions(harness="claude-code")
    base = cc_home or (Path.home() / ".claude")
    paths = [
        project_dir / ".claude" / "settings.json",
        project_dir / ".claude" / "settings.local.json",
        base / "settings.json",
    ]
    for path in paths:
        if not path.exists():
            continue
        hp.config_found = True
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            perms = data.get("permissions", {})
            for tool in perms.get("allow", []):
                hp.entries.append(PermissionEntry(tool=str(tool), action="allow", source=path.name))
            for tool in perms.get("deny", []):
                hp.entries.append(PermissionEntry(tool=str(tool), action="deny", source=path.name))
        except Exception as exc:
            hp.parse_error = str(exc)
    return hp


def _read_gemini_permissions(project_dir: Path) -> HarnessPermissions:
    """Read permissions from .gemini/settings.json."""
    hp = HarnessPermissions(harness="gemini")
    path = project_dir / ".gemini" / "settings.json"
    if not path.exists():
        return hp
    hp.config_found = True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        tools = data.get("tools", {})
        for tool in tools.get("allowed", []):
            hp.entries.append(PermissionEntry(tool=str(tool), action="allow", source=".gemini/settings.json"))
        for tool in tools.get("exclude", []):
            hp.entries.append(PermissionEntry(tool=str(tool), action="deny", source=".gemini/settings.json"))
    except Exception as exc:
        hp.parse_error = str(exc)
    return hp


def _read_codex_permissions(project_dir: Path) -> HarnessPermissions:
    """Read permissions from .codex/config.toml.

    Codex uses an ``approval_policy`` field rather than explicit tool lists.
    We map it to a synthetic "auto-approve" allow entry for transparency.
    """
    hp = HarnessPermissions(harness="codex")
    path = project_dir / ".codex" / "config.toml"
    if not path.exists():
        return hp
    hp.config_found = True
    try:
        content = path.read_text(encoding="utf-8")
        m = re.search(r'approval_policy\s*=\s*"([^"]+)"', content)
        if m:
            policy = m.group(1)
            # "full_auto" means all tools auto-approved (allow-all semantics)
            # "none" means every action requires approval (deny-all semantics)
            action = "allow" if policy == "full_auto" else "deny"
            hp.entries.append(PermissionEntry(
                tool="*",
                action=action,
                source=".codex/config.toml",
            ))
    except Exception as exc:
        hp.parse_error = str(exc)
    return hp


def _read_opencode_permissions(project_dir: Path) -> HarnessPermissions:
    """Read permissions from opencode.json."""
    hp = HarnessPermissions(harness="opencode")
    path = project_dir / "opencode.json"
    if not path.exists():
        return hp
    hp.config_found = True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        perms = data.get("permissions", {})
        for tool in perms.get("allow", []):
            hp.entries.append(PermissionEntry(tool=str(tool), action="allow", source="opencode.json"))
        for tool in perms.get("deny", []):
            hp.entries.append(PermissionEntry(tool=str(tool), action="deny", source="opencode.json"))
    except Exception as exc:
        hp.parse_error = str(exc)
    return hp


def _read_cursor_permissions(project_dir: Path) -> HarnessPermissions:
    """Cursor has no declarative tool-permission model; return empty with note."""
    hp = HarnessPermissions(harness="cursor")
    cursor_dir = project_dir / ".cursor"
    if cursor_dir.exists():
        hp.config_found = True
        # Cursor has no formal permission API — permissions are implicit
        hp.parse_error = "no-formal-permissions"
    return hp


def _read_windsurf_permissions(project_dir: Path) -> HarnessPermissions:
    """Windsurf has no formal permission API; return empty with note."""
    hp = HarnessPermissions(harness="windsurf")
    ws_dir = project_dir / ".windsurf"
    rules = project_dir / ".windsurfrules"
    if ws_dir.exists() or rules.exists():
        hp.config_found = True
        hp.parse_error = "no-formal-permissions"
    return hp


def _read_aider_permissions(project_dir: Path) -> HarnessPermissions:
    """Read allowed_commands from .aider.conf.yml."""
    hp = HarnessPermissions(harness="aider")
    path = project_dir / ".aider.conf.yml"
    if not path.exists():
        return hp
    hp.config_found = True
    try:
        content = path.read_text(encoding="utf-8")
        # Simple line-based YAML parse (no PyYAML dependency)
        in_allowed = False
        for line in content.splitlines():
            if re.match(r"^allowed_commands\s*:", line):
                in_allowed = True
                continue
            if in_allowed:
                item_m = re.match(r"^\s+-\s+(.+)", line)
                if item_m:
                    cmd = item_m.group(1).strip().strip('"').strip("'")
                    hp.entries.append(PermissionEntry(tool=cmd, action="allow", source=".aider.conf.yml"))
                elif line and not line[0].isspace():
                    in_allowed = False
    except Exception as exc:
        hp.parse_error = str(exc)
    return hp


# Registry of reader functions
_READERS: dict[str, callable] = {
    "gemini": _read_gemini_permissions,
    "codex": _read_codex_permissions,
    "opencode": _read_opencode_permissions,
    "cursor": _read_cursor_permissions,
    "windsurf": _read_windsurf_permissions,
    "aider": _read_aider_permissions,
}


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PermissionsDriftViewer:
    """Build and display a cross-harness permission comparison matrix.

    Example output::

        Permissions Drift Matrix
        ══════════════════════════════════════════════════════════
        Tool             claude-code  gemini    opencode  cursor
        ────────────────────────────────────────────────────────
        Bash             allow        allow     allow     —
        WebSearch        deny         ✗ MISS    deny      —
        Read             allow        allow     ✗ MISS    —
        ────────────────────────────────────────────────────────
        Legend: allow=✓  deny=✗  missing=—  no-api=·

    ``✗ MISS`` flags where a ``deny`` in Claude Code was not reflected in the
    harness config — a potential security gap.
    """

    def __init__(self, project_dir: Path | None = None, cc_home: Path | None = None):
        self.project_dir = project_dir or Path.cwd()
        self.cc_home = cc_home

    def build_matrix(self, targets: list[str] | None = None) -> PermissionsDriftMatrix:
        """Read permissions from all harness configs and build the comparison matrix.

        Args:
            targets: Harness names to include. Defaults to all known targets.

        Returns:
            PermissionsDriftMatrix with source and per-target permission sets.
        """
        source = _read_claude_code_permissions(self.project_dir, self.cc_home)

        harness_names = targets or list(_READERS.keys())
        harness_perms: dict[str, HarnessPermissions] = {}
        for name in harness_names:
            reader = _READERS.get(name)
            if reader:
                harness_perms[name] = reader(self.project_dir)

        # Collect all tool names from source + all targets
        all_tools: set[str] = {e.tool for e in source.entries}
        for hp in harness_perms.values():
            all_tools.update(e.tool for e in hp.entries)

        # Sort: wildcard first, then alphabetical
        sorted_tools = sorted(all_tools, key=lambda t: (t != "*", t.lower()))

        return PermissionsDriftMatrix(
            source=source,
            targets=harness_perms,
            all_tools=sorted_tools,
        )

    def find_missing_denies(self, matrix: PermissionsDriftMatrix) -> dict[str, list[str]]:
        """Return tools denied in Claude Code but missing from each target harness.

        A "missing deny" is a potential security gap: the user said "deny X" in
        Claude Code but target harness Y has no corresponding restriction.

        Args:
            matrix: Built by ``build_matrix()``.

        Returns:
            Dict mapping harness_name → list of tools with missing deny rules.
            Empty dict means all deny rules propagated correctly (or target has
            no formal permission model to check).
        """
        source_denies = matrix.source.denied()
        if not source_denies:
            return {}

        gaps: dict[str, list[str]] = {}
        for harness_name, hp in matrix.targets.items():
            if hp.parse_error == "no-formal-permissions":
                # Can't verify — flag as unknown rather than a gap
                continue
            if not hp.config_found:
                continue
            target_denies = hp.denied()
            missing = sorted(source_denies - target_denies)
            if missing:
                gaps[harness_name] = missing
        return gaps

    def format_matrix(self, matrix: PermissionsDriftMatrix, color: bool | None = None) -> str:
        """Render the permission matrix as a terminal table.

        Args:
            matrix: Built by ``build_matrix()``.
            color: Force ANSI color on/off. None = auto-detect from TTY.

        Returns:
            Formatted multi-line string.
        """
        import os

        # Color support detection
        use_color = (
            (not os.environ.get("NO_COLOR") and hasattr(os, "isatty") and os.isatty(1))
            if color is None else color
        )

        _RED = "\033[31m"
        _GREEN = "\033[32m"
        _YELLOW = "\033[33m"
        _CYAN = "\033[36m"
        _DIM = "\033[2m"
        _RESET = "\033[0m"

        def _c(text: str, code: str) -> str:
            return f"{code}{text}{_RESET}" if use_color else text

        # Column layout
        harness_cols = [matrix.source.harness] + list(matrix.targets.keys())
        col_w = max(12, *(len(h) for h in harness_cols))
        tool_w = max(16, *(len(t) for t in (matrix.all_tools or ["Tool"])))

        def _cell(hp: HarnessPermissions, tool: str) -> str:
            """Render a single cell: allow/deny/missing/no-api."""
            if hp.parse_error == "no-formal-permissions":
                return _c("·", _DIM)
            if not hp.config_found:
                return _c("—", _DIM)
            allowed = hp.allowed()
            denied = hp.denied()
            if tool in denied:
                return _c("deny", _RED)
            if tool in allowed or "*" in allowed:
                return _c("allow", _GREEN)
            # Not mentioned at all — check if source denies it (potential gap)
            source_denies = matrix.source.denied()
            if tool in source_denies:
                return _c("✗ MISS", _RED + "\033[1m")  # Bold red — active gap
            return _c("—", _DIM)

        lines = [
            _c("Permissions Drift Matrix", _CYAN),
            _c("═" * (tool_w + len(harness_cols) * (col_w + 3)), _CYAN),
        ]

        # Header row
        header = f"{'Tool':<{tool_w}}"
        for col in harness_cols:
            header += f"  {col:<{col_w}}"
        lines.append(_c(header, _DIM))
        lines.append(_c("─" * (tool_w + len(harness_cols) * (col_w + 3)), _DIM))

        if not matrix.all_tools:
            lines.append("  (no permission entries found in any config)")
        else:
            all_hps = [matrix.source] + list(matrix.targets.values())
            for tool in matrix.all_tools:
                row = f"{tool:<{tool_w}}"
                for hp in all_hps:
                    cell = _cell(hp, tool)
                    # Pad without ANSI codes affecting width
                    cell_plain = re.sub(r"\033\[[^m]*m", "", cell)
                    pad = col_w - len(cell_plain)
                    row += "  " + cell + " " * max(0, pad)
                lines.append(row)

        lines.append(_c("─" * (tool_w + len(harness_cols) * (col_w + 3)), _DIM))

        # Summary
        gaps = self.find_missing_denies(matrix)
        if gaps:
            lines.append(_c(
                f"\n⚠ {sum(len(v) for v in gaps.values())} deny gap(s) detected:",
                _RED,
            ))
            for harness, tools in sorted(gaps.items()):
                lines.append(
                    f"  {harness}: {', '.join(tools)}"
                    f" (denied in Claude Code but not in {harness})"
                )
            lines.append(
                "\nRun /sync to propagate these restrictions, or check "
                "if the harness supports per-tool permission config."
            )
        else:
            lines.append(_c("\n✓ All deny rules propagated correctly (or not verifiable).", _GREEN))

        lines.append(
            _c("\nLegend: allow=allow  deny=deny  missing=—  no-formal-api=·  gap=✗ MISS", _DIM)
        )

        return "\n".join(lines)

    def format_summary(self, matrix: PermissionsDriftMatrix) -> str:
        """Return a compact one-paragraph summary of the permission matrix.

        Args:
            matrix: Built by ``build_matrix()``.

        Returns:
            Short human-readable summary string.
        """
        total_tools = len(matrix.all_tools)
        source_allows = len(matrix.source.allowed())
        source_denies = len(matrix.source.denied())
        gaps = self.find_missing_denies(matrix)
        total_gaps = sum(len(v) for v in gaps.values())

        parts = [f"Source: {source_allows} allowed, {source_denies} denied ({total_tools} total tools)."]
        if total_gaps:
            gap_desc = "; ".join(f"{h}: {', '.join(ts)}" for h, ts in sorted(gaps.items()))
            parts.append(f"⚠ {total_gaps} deny gap(s): {gap_desc}.")
        else:
            parts.append("All deny rules appear correctly propagated.")

        no_api = [n for n, hp in matrix.targets.items() if hp.parse_error == "no-formal-permissions"]
        if no_api:
            parts.append(f"Harnesses without formal permission APIs (cannot verify): {', '.join(sorted(no_api))}.")

        return " ".join(parts)
