from __future__ import annotations

"""
/sync-parity slash command implementation.

Produces a structured report of every Claude Code feature in use (MCP servers,
skills, rules, agents, commands) with a per-target compatibility score and
specific gaps. Helps users understand what they give up when working in a
non-Claude harness.
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.source_reader import SourceReader
from src.adapters import AdapterRegistry


# Per-target feature support matrix
# Value: "full" | "partial" | "none" | "via-translation"
_SUPPORT_MATRIX: dict[str, dict[str, str]] = {
    "codex": {
        "rules": "full",
        "skills": "full",
        "agents": "partial",   # converted to SKILL.md format, some fields dropped
        "commands": "partial", # converted to SKILL.md format
        "mcp": "partial",      # stdio supported; SSE/HTTP limited
        "settings": "partial", # permission model differs
    },
    "gemini": {
        "rules": "full",
        "skills": "full",
        "agents": "partial",   # native agent format, CC fields dropped
        "commands": "partial", # converted to TOML
        "mcp": "full",         # JSON mcpServers format
        "settings": "partial", # tools.exclude / tools.allowed mapping
    },
    "opencode": {
        "rules": "full",
        "skills": "full",
        "agents": "partial",   # symlinked, not converted
        "commands": "partial", # symlinked
        "mcp": "partial",      # type-discriminated local/remote only
        "settings": "partial", # per-tool permission entries
    },
    "cline": {
        "rules": "full",       # .clinerules + .roo/rules/harnesssync.md
        "skills": "partial",   # .roo/rules/skills/<name>.md content copy
        "agents": "partial",   # .roo/rules/agents/<name>.md content copy
        "commands": "none",    # No command concept in Cline
        "mcp": "full",         # .roo/mcp.json mcpServers format
        "settings": "none",    # Managed by VS Code extension
    },
    "continue": {
        "rules": "full",       # .continue/rules/harnesssync.md
        "skills": "partial",   # .continue/rules/skills/<name>.md
        "agents": "partial",   # .continue/prompts/<name>.prompt
        "commands": "partial", # .continue/prompts/cmd-<name>.prompt
        "mcp": "full",         # .continue/config.json mcpServers
        "settings": "none",    # Managed by Continue extension
    },
    "zed": {
        "rules": "full",       # .rules
        "skills": "partial",   # .zed/prompts/skills/<name>.md
        "agents": "partial",   # .zed/prompts/agent-<name>.md
        "commands": "partial", # .zed/prompts/cmd-<name>.md
        "mcp": "via-translation",  # context_servers format differs from mcpServers
        "settings": "none",    # Managed by Zed editor
    },
    "neovim": {
        "rules": "full",       # .avante/rules/system-prompt.avanterules + .codecompanion/system-prompt.md
        "skills": "partial",   # .avante/rules/skills/<name>.avanterules
        "agents": "partial",   # .avante/rules/agents/<name>.avanterules
        "commands": "partial", # .codecompanion/slash-commands/<name>.md
        "mcp": "full",         # .avante/mcp.json mcpServers
        "settings": "none",    # Managed by Neovim config
    },
}

# Capability descriptions for "partial" support
_GAPS: dict[str, dict[str, str]] = {
    "codex": {
        "agents": "CC fields (color, tools allowlist) are dropped; role body is preserved",
        "commands": "Converted to SKILL.md; $ARGUMENTS becomes [user-provided arguments]",
        "mcp": "SSE/HTTP transports may not be supported; env vars translated",
        "settings": "Approval policy mapped; no equivalent for tool-level allow/deny lists",
    },
    "gemini": {
        "agents": "name/description/role preserved; color and tool allowlist dropped",
        "commands": "Converted to .gemini/commands/*.toml; $ARGUMENTS adapted",
        "settings": "tools.exclude/tools.allowed used; no native bash-restriction equivalent",
    },
    "opencode": {
        "agents": "Symlinked verbatim — CC-specific frontmatter visible in OpenCode",
        "commands": "Symlinked verbatim — $ARGUMENTS may appear literally in OpenCode",
        "mcp": "type: local (stdio) and type: remote (URL) only; env vars adapted",
        "settings": "per-tool permission (singular) with allow/ask/deny values",
    },
    "cline": {
        "skills": "Content copy to .roo/rules/skills/ — not a native skill format",
        "agents": "Content copy to .roo/rules/agents/ — injected as context rules",
        "commands": "No command equivalent — Cline uses slash commands via extension UI",
        "settings": "Extension-managed — no config file sync possible",
    },
    "continue": {
        "skills": "Synced as context rules in .continue/rules/skills/ — not native skills",
        "agents": "Converted to .prompt files — no agent tool-access controls",
        "commands": "Converted to .prompt files — $ARGUMENTS adapted",
        "settings": "Extension-managed via VS Code settings — not syncable",
    },
    "zed": {
        "skills": "Synced as prompt files — not a native Zed skill concept",
        "agents": "Synced as prompt library entries — no tool access control",
        "commands": "Synced as prompt library entries — $ARGUMENTS adapted",
        "mcp": "Zed uses context_servers format (different from standard mcpServers)",
        "settings": "Zed settings are editor-managed and not written by HarnessSync",
    },
    "neovim": {
        "skills": "Synced to .avante/rules/skills/ — injected as context",
        "agents": "Synced to .avante/rules/agents/ — injected as context rules",
        "commands": "Synced to .codecompanion/slash-commands/ — $ARGUMENTS adapted",
        "settings": "Neovim config is Lua-managed — not written by HarnessSync",
    },
}


def _score(support: dict[str, str]) -> float:
    """Compute a 0–100 compatibility score for a target."""
    weights = {"full": 1.0, "partial": 0.6, "via-translation": 0.4, "none": 0.0}
    total = sum(weights.get(v, 0) for v in support.values())
    return round(100 * total / max(len(support), 1), 1)


# ANSI color helpers
_RESET = "\033[0m"
_BOLD = "\033[1m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_DIM = "\033[2m"


def _color(text: str, code: str, use_color: bool) -> str:
    return f"{code}{text}{_RESET}" if use_color else text


def _status_color(status: str, text: str, use_color: bool) -> str:
    """Colorize a cell based on support status."""
    if not use_color:
        return text
    if status == "full":
        return f"{_GREEN}{text}{_RESET}"
    if status in ("partial", "via-translation"):
        return f"{_YELLOW}{text}{_RESET}"
    if status == "none":
        return f"{_RED}{text}{_RESET}"
    return text


def _score_color(score: float, text: str, use_color: bool) -> str:
    """Colorize a score based on its value."""
    if not use_color:
        return text
    if score >= 80:
        return f"{_GREEN}{text}{_RESET}"
    if score >= 50:
        return f"{_YELLOW}{text}{_RESET}"
    return f"{_RED}{text}{_RESET}"


def _format_heatmap(source_data: dict, targets: list[str], use_color: bool = True) -> str:
    """Render a color-coded terminal heatmap table of feature support per harness.

    Each cell shows: full (green ✓), partial (yellow ~), none (red ✗),
    or via-translation (yellow ~). A per-target score column shows overall
    coverage at a glance.

    Args:
        source_data: Discovered source config from SourceReader.
        targets: Registered harness target names.
        use_color: Emit ANSI escape codes (default True, auto-disabled for non-TTY).

    Returns:
        Formatted heatmap string ready for terminal output.
    """
    features = ["rules", "skills", "agents", "commands", "mcp", "settings"]
    STATUS_CELL = {
        "full": "  ✓  ",
        "partial": "  ~  ",
        "via-translation": "  ~  ",
        "none": "  ✗  ",
    }

    # Header
    col_w = 7  # width of each feature column
    target_w = 12
    score_w = 8

    header_cells = [f"{f:^{col_w}}" for f in features]
    header_line = (
        f"{'Target':<{target_w}}"
        + "".join(header_cells)
        + f"{'Score':>{score_w}}"
    )
    sep = "-" * len(header_line)

    lines: list[str] = []
    title = "HarnessSync Feature Parity Heatmap"
    lines.append(_color(title, _BOLD, use_color))
    lines.append(_color(sep, _DIM, use_color))
    lines.append(_color(header_line, _BOLD, use_color))
    lines.append(_color(sep, _DIM, use_color))

    for target in sorted(targets):
        support = _SUPPORT_MATRIX.get(target, {})
        score = _score(support)
        row_cells: list[str] = []
        for feature in features:
            status = support.get(feature, "?")
            raw_cell = STATUS_CELL.get(status, "  ?  ")
            row_cells.append(_status_color(status, f"{raw_cell:^{col_w}}", use_color))

        target_col = f"{target:<{target_w}}"
        score_str = f"{score:>6.0f}%"
        score_col = _score_color(score, score_str, use_color)

        lines.append(target_col + "".join(row_cells) + f"  {score_col}")

    lines.append(_color(sep, _DIM, use_color))

    # Legend
    legend = (
        f"  {_status_color('full', '✓ full', use_color)}   "
        f"{_status_color('partial', '~ partial/translation', use_color)}   "
        f"{_status_color('none', '✗ not supported', use_color)}"
    )
    lines.append(legend)

    # Feature inventory counts
    rules = source_data.get("rules", "")
    rules_count = len(rules.splitlines()) if isinstance(rules, str) else sum(
        len(r.get("content", "").splitlines()) for r in (rules or []) if isinstance(r, dict)
    )
    inventory = (
        f"\nYour config: {rules_count} rule-lines  "
        f"{len(source_data.get('skills', {}))!s} skills  "
        f"{len(source_data.get('agents', {}))!s} agents  "
        f"{len(source_data.get('commands', {}))!s} commands  "
        f"{len(source_data.get('mcp_servers', {}))!s} MCP servers"
    )
    lines.append(_color(inventory, _CYAN, use_color))

    return "\n".join(lines)


def _format_report(source_data: dict, targets: list[str]) -> str:
    """Build the parity report string."""
    lines: list[str] = ["HarnessSync Feature Parity Report", "=" * 60, ""]

    # Feature inventory
    rules = source_data.get("rules", "")
    rules_count = len(rules.splitlines()) if isinstance(rules, str) else sum(
        len(r.get("content", "").splitlines()) for r in (rules or []) if isinstance(r, dict)
    )
    skills_count = len(source_data.get("skills", {}))
    agents_count = len(source_data.get("agents", {}))
    commands_count = len(source_data.get("commands", {}))
    mcp_count = len(source_data.get("mcp_servers", {}))

    lines.append("Source inventory (Claude Code):")
    lines.append(f"  Rules:    {rules_count} lines")
    lines.append(f"  Skills:   {skills_count}")
    lines.append(f"  Agents:   {agents_count}")
    lines.append(f"  Commands: {commands_count}")
    lines.append(f"  MCP:      {mcp_count} servers")
    lines.append("")

    # Per-target parity
    lines.append("Per-Target Compatibility:")
    lines.append("-" * 60)

    for target in sorted(targets):
        support = _SUPPORT_MATRIX.get(target, {})
        score = _score(support)
        gaps = _GAPS.get(target, {})

        lines.append(f"\n[{target.upper()}]  Score: {score}/100")
        for feature in ["rules", "skills", "agents", "commands", "mcp", "settings"]:
            status = support.get(feature, "?")
            icon = {"full": "✓", "partial": "~", "none": "✗", "via-translation": "~"}.get(status, "?")
            gap_note = f"  — {gaps[feature]}" if feature in gaps else ""
            lines.append(f"  {icon} {feature:<10} [{status}]{gap_note}")

    lines.append("")
    lines.append("Legend: ✓ full  ~ partial  ✗ not supported")
    lines.append("")
    lines.append(
        "Tip: Use <!-- sync:exclude --> tags in CLAUDE.md to skip CC-only rules,\n"
        "     or <!-- sync:codex-only --> to restrict content to specific harnesses."
    )

    return "\n".join(lines)


def main() -> None:
    """Entry point for /sync-parity command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-parity",
        description="Feature parity report across harness targets"
    )
    parser.add_argument("--scope", choices=["user", "project", "all"], default="all")
    parser.add_argument(
        "--heatmap", action="store_true",
        help="Render a color-coded terminal heatmap table instead of the full text report"
    )
    parser.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI colors in heatmap output"
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    reader = SourceReader(scope=args.scope, project_dir=project_dir)
    source_data = reader.discover_all()

    targets = AdapterRegistry.list_targets()

    if args.heatmap:
        use_color = not args.no_color and sys.stdout.isatty()
        print(_format_heatmap(source_data, targets, use_color=use_color))
    else:
        print(_format_report(source_data, targets))

    # Item 25 — Feature parity upgrade alerts: warn when installed harness versions
    # unlock new sync capabilities that were previously unavailable.
    try:
        from src.harness_version_compat import suggest_capability_upgrades
        upgrade_suggestions = suggest_capability_upgrades(
            project_dir=project_dir,
            source_data=source_data,
        )
        if upgrade_suggestions:
            print()
            print("Feature Parity Upgrade Alerts:")
            print("-" * 40)
            for suggestion in upgrade_suggestions:
                print(f"  + {suggestion}")
    except Exception:
        pass  # Non-critical; upgrade suggestions are informational


if __name__ == "__main__":
    main()
