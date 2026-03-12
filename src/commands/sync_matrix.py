from __future__ import annotations

"""
/sync-matrix slash command implementation.

Shows a capability matrix of every config section and which target harnesses
support it natively, which get approximate translation, and which silently drop it.
"""

import os
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.mcp_tool_compat import format_mcp_tool_matrix
from src.utils.constants import EXTENDED_TARGETS


# Support level constants
NATIVE = "native"      # Full native support — round-trips cleanly
ADAPTED = "adapted"    # Translated/approximated — may lose fidelity
PARTIAL = "partial"    # Some features supported, others dropped
DROPPED = "dropped"    # Silently dropped — no equivalent in target
NA = "N/A"             # Not applicable


# Matrix definition: section -> {target: (level, note)}
# Targets: codex, gemini, opencode, cursor, aider, windsurf
CAPABILITY_MATRIX: list[dict] = [
    {
        "section": "rules",
        "description": "CLAUDE.md project rules",
        "codex":     (NATIVE,  "AGENTS.md managed section"),
        "gemini":    (NATIVE,  "GEMINI.md managed section"),
        "opencode":  (NATIVE,  "AGENTS.md managed section"),
        "cursor":    (NATIVE,  ".cursor/rules/*.mdc files"),
        "aider":     (ADAPTED, "CONVENTIONS.md managed section"),
        "windsurf":  (NATIVE,  ".windsurfrules managed section"),
        "cline":     (NATIVE,  ".clinerules + .roo/rules/harnesssync.md"),
        "continue":  (NATIVE,  ".continue/rules/harnesssync.md"),
        "zed":       (NATIVE,  ".zed/system-prompt.md"),
        "neovim":    (NATIVE,  ".avante/system-prompt.md + .codecompanion/system-prompt.md"),
    },
    {
        "section": "skills",
        "description": "Claude Code skill directories",
        "codex":    (NATIVE,  "Symlinks in .agents/skills/"),
        "gemini":   (NATIVE,  "Native .gemini/skills/<name>/SKILL.md"),
        "opencode": (NATIVE,  "Symlinks in .opencode/skills/"),
        "cursor":   (ADAPTED, ".cursor/rules/skills/*.mdc (content copy)"),
        "aider":    (ADAPTED, "Added to .aider.conf.yml read list"),
        "windsurf": (ADAPTED, ".windsurf/memories/<name>.md"),
        "cline":    (ADAPTED, ".roo/rules/skills/<name>.md"),
        "continue": (ADAPTED, ".continue/rules/skills/<name>.md"),
        "zed":      (ADAPTED, ".zed/prompts/skills/<name>.md"),
        "neovim":   (ADAPTED, ".avante/rules/skills/<name>.md"),
    },
    {
        "section": "agents",
        "description": "Agent .md files",
        "codex":    (ADAPTED, "Converted to SKILL.md in .agents/skills/"),
        "gemini":   (NATIVE,  "Native .gemini/agents/<name>.md"),
        "opencode": (NATIVE,  "Symlinks in .opencode/agents/"),
        "cursor":   (ADAPTED, ".cursor/rules/agents/*.mdc files"),
        "aider":    (DROPPED, "No agent concept in Aider"),
        "windsurf": (ADAPTED, ".windsurf/workflows/<name>.md"),
        "cline":    (ADAPTED, ".roo/rules/agents/<name>.md"),
        "continue": (ADAPTED, ".continue/prompts/<name>.prompt"),
        "zed":      (ADAPTED, ".zed/prompts/agent-<name>.md"),
        "neovim":   (ADAPTED, ".avante/rules/agents/<name>.md"),
    },
    {
        "section": "commands",
        "description": "Slash command .md files",
        "codex":    (ADAPTED, "Converted to SKILL.md in .agents/skills/cmd-*"),
        "gemini":   (NATIVE,  "Native .gemini/commands/<name>.toml"),
        "opencode": (NATIVE,  "Symlinks in .opencode/commands/"),
        "cursor":   (ADAPTED, ".cursor/rules/commands/*.mdc (no $ARGUMENTS)"),
        "aider":    (DROPPED, "No command concept in Aider"),
        "windsurf": (ADAPTED, ".windsurf/workflows/cmd-*.md (no $ARGUMENTS)"),
        "cline":    (DROPPED, "No command concept in Cline"),
        "continue": (ADAPTED, ".continue/prompts/cmd-<name>.prompt"),
        "zed":      (ADAPTED, ".zed/prompts/cmd-<name>.md"),
        "neovim":   (ADAPTED, ".codecompanion/slash-commands/<name>.md"),
    },
    {
        "section": "mcp_servers",
        "description": "MCP server configurations",
        "codex":    (NATIVE,  "config.toml [mcp_servers] section"),
        "gemini":   (NATIVE,  "settings.json mcpServers key"),
        "opencode": (NATIVE,  "opencode.json mcp section (type-discriminated)"),
        "cursor":   (NATIVE,  ".cursor/mcp.json mcpServers"),
        "aider":    (PARTIAL, "Server names noted in .aider.conf.yml; no exec support"),
        "windsurf": (NATIVE,  ".codeium/windsurf/mcp_config.json mcpServers"),
        "cline":    (NATIVE,  ".roo/mcp.json mcpServers"),
        "continue": (NATIVE,  ".continue/config.json mcpServers"),
        "zed":      (ADAPTED, ".zed/settings.json context_servers (format differs)"),
        "neovim":   (NATIVE,  ".avante/mcp.json mcpServers"),
    },
    {
        "section": "settings",
        "description": "IDE/tool settings (approval mode, permissions)",
        "codex":    (ADAPTED, "config.toml approval_policy (conservative mapping)"),
        "gemini":   (ADAPTED, "settings.json tools.exclude/tools.allowed"),
        "opencode": (ADAPTED, "opencode.json permission per-tool entries"),
        "cursor":   (DROPPED, "Managed by Cursor IDE — not written"),
        "aider":    (ADAPTED, ".aider.conf.yml --yes flag mapping"),
        "windsurf": (DROPPED, "Managed by Windsurf IDE — not written"),
        "cline":    (DROPPED, "Managed by VS Code extension — not written"),
        "continue": (DROPPED, "Managed by Continue extension — not written"),
        "zed":      (DROPPED, "Managed by Zed editor — not written"),
        "neovim":   (DROPPED, "Managed by Neovim config — not written"),
    },
    {
        "section": "sync_tags",
        "description": "<!-- sync:target-only --> content filtering",
        "codex":    (NATIVE,  "codex-only / exclude regions filtered"),
        "gemini":   (NATIVE,  "gemini-only / exclude regions filtered"),
        "opencode": (NATIVE,  "opencode-only / exclude regions filtered"),
        "cursor":   (DROPPED, "Tags not interpreted — content passed through"),
        "aider":    (DROPPED, "Tags not interpreted — content passed through"),
        "windsurf": (DROPPED, "Tags not interpreted — content passed through"),
        "cline":    (DROPPED, "Tags not interpreted — content passed through"),
        "continue": (DROPPED, "Tags not interpreted — content passed through"),
        "zed":      (DROPPED, "Tags not interpreted — content passed through"),
        "neovim":   (DROPPED, "Tags not interpreted — content passed through"),
    },
    {
        "section": "harness_overrides",
        "description": ".harness-sync/overrides/<target>.md per-harness injections",
        "codex":    (NATIVE,  "Appended after HarnessSync section"),
        "gemini":   (NATIVE,  "Appended after HarnessSync section"),
        "opencode": (NATIVE,  "Appended after HarnessSync section"),
        "cursor":   (DROPPED, "Override file not applied to .mdc format"),
        "aider":    (DROPPED, "Override file not applied to CONVENTIONS.md"),
        "windsurf": (DROPPED, "Override file not applied to .windsurfrules"),
        "cline":    (DROPPED, "Override file not applied to .clinerules"),
        "continue": (DROPPED, "Override file not applied to .continue/rules"),
        "zed":      (DROPPED, "Override file not applied to system-prompt.md"),
        "neovim":   (DROPPED, "Override file not applied to avante config"),
    },
]

# Display order for targets
TARGETS = list(EXTENDED_TARGETS)

# Level display config: (symbol, display label)
LEVEL_DISPLAY = {
    NATIVE:  ("✓", "native"),
    ADAPTED: ("~", "adapted"),
    PARTIAL: ("?", "partial"),
    DROPPED: ("✗", "dropped"),
    NA:      ("-", "N/A"),
}


def _level_symbol(level: str) -> str:
    return LEVEL_DISPLAY.get(level, ("?", "?"))[0]


def format_matrix(show_notes: bool = False) -> str:
    """Format the capability matrix as a text table.

    Args:
        show_notes: If True, print per-cell notes below the table

    Returns:
        Formatted table string
    """
    lines: list[str] = []

    lines.append("HarnessSync Capability Matrix")
    lines.append("=" * 72)
    lines.append("")
    lines.append("Legend:  ✓ native  ~ adapted  ? partial  ✗ dropped")
    lines.append("")

    # Header row
    col_w = 10
    section_w = 16
    header = f"{'Section':<{section_w}}"
    for t in TARGETS:
        header += f"  {t[:col_w-2]:<{col_w-2}}"
    lines.append(header)
    lines.append("-" * (section_w + len(TARGETS) * col_w))

    # Data rows
    for row in CAPABILITY_MATRIX:
        section = row["section"]
        line = f"{section:<{section_w}}"
        for t in TARGETS:
            cell = row.get(t)
            if cell:
                level, note = cell
                sym = _level_symbol(level)
                line += f"  {sym + ' ' + level[:col_w-4]:<{col_w-2}}"
            else:
                line += f"  {'-':<{col_w-2}}"
        lines.append(line)

    lines.append("")

    # Notes section
    if show_notes:
        lines.append("Notes:")
        lines.append("-" * 72)
        for row in CAPABILITY_MATRIX:
            section = row["section"]
            desc = row.get("description", "")
            lines.append(f"\n{section}  ({desc})")
            for t in TARGETS:
                cell = row.get(t)
                if cell:
                    level, note = cell
                    sym = _level_symbol(level)
                    lines.append(f"  {t:<10}  {sym} {level:<8}  {note}")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    """Entry point for /sync-matrix command.

    Flags:
        --notes / -n        Show per-cell detail notes under the section table
        --mcp-tools         Show MCP tool compatibility matrix (transports,
                            capability types, config features) instead of the
                            default config-section matrix
        --mcp-section SEC   Which MCP sub-table to show: transport, capabilities,
                            features, or all (default: all)
    """
    show_notes = "--notes" in sys.argv or "-n" in sys.argv
    show_mcp_tools = "--mcp-tools" in sys.argv

    if show_mcp_tools:
        # Determine which MCP sub-section to show
        mcp_section = "all"
        if "--mcp-section" in sys.argv:
            idx = sys.argv.index("--mcp-section")
            if idx + 1 < len(sys.argv):
                mcp_section = sys.argv[idx + 1]
        print(format_mcp_tool_matrix(section=mcp_section))
    else:
        print(format_matrix(show_notes=show_notes))


if __name__ == "__main__":
    main()
