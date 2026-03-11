from __future__ import annotations

"""
/sync-map slash command implementation.

Generates a Markdown diagram showing the entire config topology:
source, all targets, what's synced vs skipped per section, which MCP
servers are active where, and which skills/agents exist in each harness.
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
from src.state_manager import StateManager


def _count_section(data, key: str) -> int:
    """Count items in a source data section."""
    val = data.get(key)
    if isinstance(val, dict):
        return len(val)
    if isinstance(val, list):
        return len(val)
    if isinstance(val, str) and val.strip():
        return 1
    return 0


def generate_map(project_dir: Path, scope: str = "all") -> str:
    """Generate a Markdown config topology map.

    Args:
        project_dir: Project root directory
        scope: Source read scope ("user"/"project"/"all")

    Returns:
        Markdown string with config map
    """
    reader = SourceReader(scope=scope, project_dir=project_dir)
    source_data = reader.discover_all()
    state = StateManager()
    targets = AdapterRegistry.list_targets()

    lines: list[str] = []
    lines.append("# HarnessSync Config Map")
    lines.append("")

    # Source section
    lines.append("## Source: Claude Code")
    lines.append("")
    lines.append("```")
    lines.append("~/.claude/  (user scope)")
    lines.append(f"  rules:    {_count_section(source_data, 'rules') or 'none'} file(s)")
    mcp_count = len(source_data.get('mcp_servers', {}))
    lines.append(f"  mcp:      {mcp_count} server(s)")
    lines.append(f"  skills:   {_count_section(source_data, 'skills')} skill(s)")
    lines.append(f"  agents:   {_count_section(source_data, 'agents')} agent(s)")
    lines.append(f"  commands: {_count_section(source_data, 'commands')} command(s)")
    lines.append(f"  settings: {'present' if source_data.get('settings') else 'none'}")
    lines.append("```")
    lines.append("")

    # MCP servers detail
    mcp_servers = source_data.get('mcp_servers', {})
    if mcp_servers:
        lines.append("### MCP Servers")
        lines.append("")
        for name, cfg in list(mcp_servers.items())[:20]:
            url = cfg.get("url") or cfg.get("serverUrl", "")
            cmd = cfg.get("command") or cfg.get("cmd", "")
            transport = f"url={url[:40]}" if url else f"cmd={cmd.split('/')[-1]}"
            lines.append(f"- `{name}` ({transport})")
        if len(mcp_servers) > 20:
            lines.append(f"- ... and {len(mcp_servers) - 20} more")
        lines.append("")

    # Target sections
    lines.append("## Sync Targets")
    lines.append("")

    status_state = state.get_all_status()
    targets_state = status_state.get("targets", {})

    for target in targets:
        target_state = targets_state.get(target)
        last_sync = target_state.get("last_sync", "never") if target_state else "never"
        status = target_state.get("status", "unknown") if target_state else "never synced"

        lines.append(f"### {target.capitalize()}")
        lines.append("")
        lines.append(f"- Status: {status}")
        lines.append(f"- Last sync: {last_sync}")
        if target_state:
            synced = target_state.get("items_synced", 0)
            skipped = target_state.get("items_skipped", 0)
            failed = target_state.get("items_failed", 0)
            lines.append(f"- Items: {synced} synced / {skipped} skipped / {failed} failed")
        lines.append("")

    # Topology diagram (ASCII)
    lines.append("## Topology")
    lines.append("")
    lines.append("```")
    lines.append("  ┌──────────────────┐")
    lines.append("  │   Claude Code    │  ← Source of truth")
    lines.append("  │   ~/.claude/     │")
    lines.append("  └────────┬─────────┘")
    lines.append("           │")
    lines.append("  ┌────────┴─────────┐")
    lines.append("  │   HarnessSync    │  ← This plugin")
    lines.append("  └──┬──┬──┬──┬──┬──┘")

    # Build target list for display
    target_boxes = []
    for t in targets:
        target_boxes.append(f"[{t}]")

    if target_boxes:
        lines.append("     │  " + "  ".join(target_boxes[:3]))
        if len(target_boxes) > 3:
            lines.append("     │  " + "  ".join(target_boxes[3:]))

    lines.append("```")
    lines.append("")

    # Section support matrix summary
    from src.commands.sync_matrix import CAPABILITY_MATRIX, TARGETS, _level_symbol
    lines.append("## Section Support Summary")
    lines.append("")
    lines.append("| Section | " + " | ".join(TARGETS) + " |")
    lines.append("|---------|" + "---------|" * len(TARGETS))
    for row in CAPABILITY_MATRIX:
        section = row["section"]
        cells = []
        for t in TARGETS:
            cell = row.get(t)
            if cell:
                level, note = cell
                cells.append(_level_symbol(level))
            else:
                cells.append("-")
        lines.append(f"| {section} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("_Legend: ✓ native  ~ adapted  ? partial  ✗ dropped_")

    return "\n".join(lines)


def main() -> None:
    """Entry point for /sync-map command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(prog="sync-map", description="Show config topology map")
    parser.add_argument("--scope", choices=["user", "project", "all"], default="all")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write map to file instead of stdout",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    try:
        map_content = generate_map(project_dir, scope=args.scope)
    except Exception as e:
        print(f"Error generating map: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(map_content, encoding="utf-8")
        print(f"Config map written to {output_path}")
    else:
        print(map_content)


if __name__ == "__main__":
    main()
