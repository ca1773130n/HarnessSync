from __future__ import annotations

"""
/sync-capabilities slash command implementation.

Shows a visual matrix of which Claude Code features each target harness
supports natively, partially, or not at all — before sync runs.
Helps users understand what they'll lose before committing to a sync.

Different from /sync-matrix which shows config sections:
/sync-capabilities focuses on behavioral features (hooks, agents, tools,
permissions, sessions, etc.) that aren't just file-format questions.
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path


# Support tiers
FULL = "full"        # Feature works as-in Claude Code
PARTIAL = "partial"  # Feature works but with limitations
NONE = "none"        # Feature not supported


# Feature capability matrix.
# Each entry: (feature_name, category, description, {target: (tier, note)})
_CAPABILITIES: list[tuple[str, str, str, dict]] = [
    (
        "MCP servers",
        "integrations",
        "Model Context Protocol server configuration",
        {
            "codex":    (FULL,    "config.toml [mcpServers]"),
            "gemini":   (FULL,    "settings.json mcpServers"),
            "opencode": (FULL,    "opencode.json mcp.servers"),
            "cursor":   (FULL,    ".cursor/mcp.json"),
            "aider":    (NONE,    "No MCP support"),
            "windsurf": (PARTIAL, ".codeium/windsurf/mcp_config.json (v1.0+)"),
        },
    ),
    (
        "Project rules",
        "instructions",
        "System-level instructions for the AI model",
        {
            "codex":    (FULL,    "AGENTS.md managed section"),
            "gemini":   (FULL,    "GEMINI.md managed section"),
            "opencode": (FULL,    "AGENTS.md managed section"),
            "cursor":   (FULL,    ".cursor/rules/*.mdc files"),
            "aider":    (PARTIAL, "CONVENTIONS.md (no inline tags)"),
            "windsurf": (FULL,    ".windsurfrules"),
        },
    ),
    (
        "Skills / prompts",
        "instructions",
        "Reusable skill and prompt libraries",
        {
            "codex":    (FULL,    "Symlinked into .agents/skills/"),
            "gemini":   (FULL,    "Native .gemini/skills/ format"),
            "opencode": (FULL,    "Symlinked into .opencode/skills/"),
            "cursor":   (PARTIAL, ".mdc conversion — some frontmatter dropped"),
            "aider":    (PARTIAL, "Added to read_files list (no execution)"),
            "windsurf": (PARTIAL, ".windsurf/memories/ (context only)"),
        },
    ),
    (
        "Agents",
        "instructions",
        "Named AI agent definitions",
        {
            "codex":    (PARTIAL, "Converted to skill files — no subagent dispatch"),
            "gemini":   (FULL,    "Native .gemini/agents/ format"),
            "opencode": (PARTIAL, "Converted to skill files"),
            "cursor":   (PARTIAL, ".mdc rules — no native agent dispatch"),
            "aider":    (NONE,    "No agent concept"),
            "windsurf": (PARTIAL, "Memory files — no agent dispatch"),
        },
    ),
    (
        "Pre/post tool hooks",
        "lifecycle",
        "PreToolUse / PostToolUse event hooks",
        {
            "codex":    (NONE,    "No hook system"),
            "gemini":   (NONE,    "No hook system"),
            "opencode": (NONE,    "No hook system"),
            "cursor":   (NONE,    "No hook system"),
            "aider":    (NONE,    "No hook system"),
            "windsurf": (NONE,    "No hook system"),
        },
    ),
    (
        "Session lifecycle hooks",
        "lifecycle",
        "SessionStart / SessionEnd hooks",
        {
            "codex":    (NONE,    "No hook system"),
            "gemini":   (NONE,    "No hook system"),
            "opencode": (NONE,    "No hook system"),
            "cursor":   (NONE,    "No hook system"),
            "aider":    (NONE,    "No hook system"),
            "windsurf": (NONE,    "No hook system"),
        },
    ),
    (
        "Slash commands",
        "commands",
        "Custom /command definitions",
        {
            "codex":    (NONE,    "No slash command support"),
            "gemini":   (NONE,    "No slash command support"),
            "opencode": (NONE,    "No slash command support"),
            "cursor":   (NONE,    "No slash command support"),
            "aider":    (NONE,    "No slash command support"),
            "windsurf": (NONE,    "No slash command support"),
        },
    ),
    (
        "Permission model",
        "security",
        "Tool allow/deny permission lists",
        {
            "codex":    (PARTIAL, "approval_policy field (on-request/on-failure/never)"),
            "gemini":   (PARTIAL, "tools.allowed / tools.exclude (v2.0+)"),
            "opencode": (PARTIAL, "permission.allow / permission.deny per tool"),
            "cursor":   (NONE,    "No fine-grained tool permissions"),
            "aider":    (NONE,    "No permission model"),
            "windsurf": (NONE,    "No permission model"),
        },
    ),
    (
        "Environment variables",
        "settings",
        "Tool-level env var configuration",
        {
            "codex":    (PARTIAL, "env field in config.toml"),
            "gemini":   (PARTIAL, "env field in settings.json"),
            "opencode": (FULL,    "env in server configs"),
            "cursor":   (PARTIAL, "env field in mcp.json"),
            "aider":    (NONE,    "Env vars must be set in shell"),
            "windsurf": (NONE,    "No env var config"),
        },
    ),
    (
        "Project detection",
        "settings",
        "Per-project vs global config separation",
        {
            "codex":    (PARTIAL, "Single config.toml — no project-local override"),
            "gemini":   (FULL,    ".gemini/ dir can be project-local"),
            "opencode": (FULL,    "opencode.json can be project-local"),
            "cursor":   (FULL,    ".cursor/ is per-project"),
            "aider":    (FULL,    ".aider.conf.yml is per-project"),
            "windsurf": (PARTIAL, ".windsurfrules in project root"),
        },
    ),
    (
        "Sync tag filtering",
        "harnesssync",
        "@sync:target inline content routing",
        {
            "codex":    (FULL,    "<!-- sync:codex --> tags respected"),
            "gemini":   (FULL,    "<!-- sync:gemini --> tags respected"),
            "opencode": (FULL,    "<!-- sync:opencode --> tags respected"),
            "cursor":   (FULL,    "<!-- sync:cursor --> tags respected"),
            "aider":    (FULL,    "<!-- sync:aider --> tags respected"),
            "windsurf": (FULL,    "<!-- sync:windsurf --> tags respected"),
        },
    ),
    (
        "Harness-specific overrides",
        "harnesssync",
        "<!-- harness:X --> injection blocks",
        {
            "codex":    (FULL,    "<!-- harness:codex --> blocks injected"),
            "gemini":   (FULL,    "<!-- harness:gemini --> blocks injected"),
            "opencode": (FULL,    "<!-- harness:opencode --> blocks injected"),
            "cursor":   (FULL,    "<!-- harness:cursor --> blocks injected"),
            "aider":    (FULL,    "<!-- harness:aider --> blocks injected"),
            "windsurf": (FULL,    "<!-- harness:windsurf --> blocks injected"),
        },
    ),
    (
        "Config inheritance",
        "harnesssync",
        "Multi-layer base/team/personal config composition",
        {
            "codex":    (FULL,    "Composed before sync"),
            "gemini":   (FULL,    "Composed before sync"),
            "opencode": (FULL,    "Composed before sync"),
            "cursor":   (FULL,    "Composed before sync"),
            "aider":    (FULL,    "Composed before sync"),
            "windsurf": (FULL,    "Composed before sync"),
        },
    ),
    (
        "Env var substitution",
        "harnesssync",
        "${VAR} placeholder expansion from .env.harness",
        {
            "codex":    (FULL,    "Expanded at sync time"),
            "gemini":   (FULL,    "Expanded at sync time"),
            "opencode": (FULL,    "Expanded at sync time"),
            "cursor":   (FULL,    "Expanded at sync time"),
            "aider":    (FULL,    "Expanded at sync time"),
            "windsurf": (FULL,    "Expanded at sync time"),
        },
    ),
]

# All targets shown in columns
_DEFAULT_TARGETS = ["codex", "gemini", "opencode", "cursor", "aider", "windsurf"]

# Visual symbols per tier
_SYMBOLS = {FULL: "✓", PARTIAL: "~", NONE: "✗"}
_LABELS = {FULL: "Full", PARTIAL: "Partial", NONE: "None"}


def _render_table(targets: list[str], category_filter: str | None = None, detail: bool = False) -> str:
    """Render the capabilities matrix as ASCII table.

    Args:
        targets: List of targets to show as columns.
        category_filter: If set, only show rows from this category.
        detail: If True, include per-cell notes.

    Returns:
        Formatted table string.
    """
    rows = _CAPABILITIES
    if category_filter:
        rows = [(f, c, d, t) for (f, c, d, t) in rows if c == category_filter]

    if not rows:
        return f"No capabilities found for category '{category_filter}'."

    col_width = 9
    feature_width = 26

    # Build header
    lines: list[str] = []
    lines.append("Harness Capability Map — Claude Code Feature Support")
    lines.append("=" * (feature_width + len(targets) * (col_width + 1) + 2))
    lines.append(f"  {'Feature':<{feature_width}}" + "".join(f" {t:<{col_width}}" for t in targets))
    lines.append("  " + "-" * feature_width + "".join("-" * (col_width + 1) for _ in targets))

    current_category = None
    for feature_name, category, description, target_map in rows:
        if category != current_category:
            current_category = category
            lines.append(f"\n  [{category.upper()}]")

        # Build tier cells
        cells = []
        for t in targets:
            tier, note = target_map.get(t, (NONE, ""))
            sym = _SYMBOLS[tier]
            cell = f"{sym} {_LABELS[tier]}"
            cells.append(f" {cell:<{col_width}}")

        lines.append(f"  {feature_name:<{feature_width}}" + "".join(cells))

        if detail:
            # Show notes for each target
            for t in targets:
                tier, note = target_map.get(t, (NONE, ""))
                if note:
                    lines.append(f"    {t}: {note}")

    # Legend
    lines.append("")
    lines.append(f"  Legend: {_SYMBOLS[FULL]} Full  {_SYMBOLS[PARTIAL]} Partial  {_SYMBOLS[NONE]} Not supported")

    return "\n".join(lines)


def _render_target_report(target: str) -> str:
    """Show full capability summary for a single target harness.

    Args:
        target: Target harness name.

    Returns:
        Formatted report string.
    """
    lines = [f"Feature Support: {target}", "=" * 50]

    full_count = 0
    partial_count = 0
    none_count = 0

    current_category = None
    for feature_name, category, description, target_map in _CAPABILITIES:
        if category != current_category:
            current_category = category
            lines.append(f"\n  [{category.upper()}]")

        tier, note = target_map.get(target, (NONE, "not listed"))
        sym = _SYMBOLS[tier]
        lines.append(f"  {sym} {feature_name:<28}  {note}")

        if tier == FULL:
            full_count += 1
        elif tier == PARTIAL:
            partial_count += 1
        else:
            none_count += 1

    total = full_count + partial_count + none_count
    pct = int((full_count + partial_count * 0.5) / total * 100) if total else 0

    lines.append("")
    lines.append(f"  Summary: {full_count} full / {partial_count} partial / {none_count} none")
    lines.append(f"  Effective compatibility: {pct}%")

    return "\n".join(lines)


def main() -> None:
    """Entry point for /sync-capabilities command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-capabilities",
        description="Show Claude Code feature support across target harnesses",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Show detailed report for a single target (codex, gemini, opencode, cursor, aider, windsurf)",
    )
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Filter by category (instructions, integrations, lifecycle, security, settings, harnesssync, commands)",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="Show per-cell implementation notes",
    )
    parser.add_argument(
        "--targets",
        type=str,
        default=None,
        help="Comma-separated list of targets to include in the matrix",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    if args.target:
        print(_render_target_report(args.target))
        return

    targets = _DEFAULT_TARGETS
    if args.targets:
        targets = [t.strip() for t in args.targets.split(",") if t.strip()]

    print(_render_table(targets, category_filter=args.category, detail=args.detail))


if __name__ == "__main__":
    main()
