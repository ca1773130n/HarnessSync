from __future__ import annotations

"""Plugin & Extension Sync — map Claude Code plugins to equivalent harness extensions.

When a user installs a Claude Code plugin, this mapper identifies equivalent
extensions or tools available in target harnesses (Cursor, Windsurf, VS Code/Cline,
etc.) and notes gaps where no equivalent exists.

The database is a curated mapping of popular Claude Code plugins to their
closest equivalents in each target ecosystem. "Equivalent" means:
- Provides the same MCP server (same tool names, compatible protocol)
- Provides the same skill/agent category (code review, test generation, etc.)
- Is the officially maintained port of the same upstream tool

Users see:
  Plugin 'context7' → cursor: not available | windsurf: not available | cline: community port
  Plugin 'playwright' → cursor: Playwright MCP (install via cursor extensions)
  Plugin 'github' → cursor: GitHub Copilot extension (built-in) | cline: github MCP

Gap report flags plugins that have no equivalent in any target harness.
"""

from dataclasses import dataclass, field
from pathlib import Path


# Availability status for a plugin in a target harness
AVAILABLE = "available"      # Exact equivalent exists, auto-installable
PARTIAL = "partial"          # Partial equivalent — some features
MANUAL = "manual"            # Exists but requires manual setup
COMMUNITY = "community"      # Community/unofficial port
NOT_AVAILABLE = "none"       # No equivalent found


@dataclass
class ExtensionMapping:
    """Mapping from a Claude Code plugin to a target harness extension."""

    harness: str
    status: str               # AVAILABLE | PARTIAL | MANUAL | COMMUNITY | NOT_AVAILABLE
    extension_name: str = ""  # Extension/package name in the target harness
    install_hint: str = ""    # How to install (e.g. "Extensions: search 'playwright'")
    notes: str = ""           # Fidelity notes, caveats


@dataclass
class PluginCompatibility:
    """Compatibility info for a single Claude Code plugin across all harnesses."""

    plugin_name: str
    plugin_description: str
    category: str             # "mcp" | "skill" | "agent" | "hook" | "mixed"
    mappings: list[ExtensionMapping] = field(default_factory=list)

    def available_in(self) -> list[str]:
        return [m.harness for m in self.mappings if m.status in (AVAILABLE, PARTIAL)]

    def gaps(self) -> list[str]:
        return [m.harness for m in self.mappings if m.status == NOT_AVAILABLE]

    def get_mapping(self, harness: str) -> ExtensionMapping | None:
        for m in self.mappings:
            if m.harness == harness:
                return m
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Plugin equivalence database
# ──────────────────────────────────────────────────────────────────────────────

_PLUGIN_DB: list[PluginCompatibility] = [
    PluginCompatibility(
        plugin_name="context7",
        plugin_description="Up-to-date library docs via MCP",
        category="mcp",
        mappings=[
            ExtensionMapping("codex", AVAILABLE, "context7-mcp",
                             "Add context7 MCP to codex config",
                             "Same MCP server, same tool names"),
            ExtensionMapping("gemini", AVAILABLE, "context7-mcp",
                             "Add context7 MCP to gemini settings",
                             "Same MCP server"),
            ExtensionMapping("cursor", MANUAL, "",
                             "Add context7 MCP server to .cursor/mcp.json",
                             "MCP works in Cursor ≥ 0.43"),
            ExtensionMapping("windsurf", MANUAL, "",
                             "Add via windsurf MCP bridge",
                             "Requires HTTP bridge setup"),
            ExtensionMapping("cline", AVAILABLE, "context7-mcp",
                             "Add to Cline MCP config",
                             "Full MCP support"),
            ExtensionMapping("aider", NOT_AVAILABLE, "",
                             "", "Aider does not support MCP"),
        ],
    ),
    PluginCompatibility(
        plugin_name="playwright",
        plugin_description="Browser automation via Playwright MCP",
        category="mcp",
        mappings=[
            ExtensionMapping("codex", AVAILABLE, "playwright-mcp",
                             "Add playwright MCP to codex"),
            ExtensionMapping("gemini", AVAILABLE, "playwright-mcp",
                             "Add playwright MCP to gemini"),
            ExtensionMapping("cursor", MANUAL, "",
                             "Add playwright MCP to .cursor/mcp.json",
                             "Full MCP support in Cursor"),
            ExtensionMapping("windsurf", MANUAL, "",
                             "Requires bridge — see windsurf-mcp-bridge"),
            ExtensionMapping("cline", AVAILABLE, "playwright-mcp",
                             "Full support"),
            ExtensionMapping("aider", NOT_AVAILABLE, "",
                             "", "No MCP support"),
        ],
    ),
    PluginCompatibility(
        plugin_name="github",
        plugin_description="GitHub issues, PRs, and repo management",
        category="mcp",
        mappings=[
            ExtensionMapping("codex", AVAILABLE, "github-mcp",
                             "Add github MCP to codex config"),
            ExtensionMapping("gemini", AVAILABLE, "github-mcp",
                             "Add github MCP to gemini"),
            ExtensionMapping("cursor", PARTIAL, "GitHub Copilot",
                             "Built-in GitHub integration",
                             "Copilot provides GitHub context but not all MCP tools"),
            ExtensionMapping("windsurf", MANUAL, "github-mcp",
                             "Add via MCP bridge",
                             "Requires OAuth token"),
            ExtensionMapping("cline", AVAILABLE, "github-mcp",
                             "Add github MCP server"),
            ExtensionMapping("aider", PARTIAL, "",
                             "aider has native GitHub integration via CLI",
                             "Limited to PR creation — no issue management"),
        ],
    ),
    PluginCompatibility(
        plugin_name="serena",
        plugin_description="Semantic code navigation and editing via MCP",
        category="mcp",
        mappings=[
            ExtensionMapping("codex", AVAILABLE, "serena-mcp",
                             "Add serena MCP to codex"),
            ExtensionMapping("gemini", AVAILABLE, "serena-mcp",
                             "Add serena MCP to gemini"),
            ExtensionMapping("cursor", MANUAL, "serena-mcp",
                             "Add to .cursor/mcp.json",
                             "Cursor has built-in code nav but serena adds semantic layer"),
            ExtensionMapping("windsurf", MANUAL, "serena-mcp",
                             "Requires MCP bridge"),
            ExtensionMapping("cline", AVAILABLE, "serena-mcp"),
            ExtensionMapping("aider", NOT_AVAILABLE, "",
                             "", "No MCP support"),
        ],
    ),
    PluginCompatibility(
        plugin_name="sentry",
        plugin_description="Sentry error monitoring and issue analysis",
        category="mcp",
        mappings=[
            ExtensionMapping("codex", AVAILABLE, "sentry-mcp"),
            ExtensionMapping("gemini", AVAILABLE, "sentry-mcp"),
            ExtensionMapping("cursor", MANUAL, "",
                             "Add sentry MCP to .cursor/mcp.json"),
            ExtensionMapping("windsurf", MANUAL, "",
                             "Add via bridge"),
            ExtensionMapping("cline", AVAILABLE, "sentry-mcp"),
            ExtensionMapping("aider", NOT_AVAILABLE),
        ],
    ),
    PluginCompatibility(
        plugin_name="pr-review-toolkit",
        plugin_description="Code review agents and PR analysis tools",
        category="agent",
        mappings=[
            ExtensionMapping("codex", PARTIAL, "",
                             "Skills convert to .agents/skills/ files",
                             "Agent orchestration not available in Codex"),
            ExtensionMapping("gemini", PARTIAL, "",
                             "Agents convert to .gemini/agents/",
                             "Most review agents work; hook-based ones don't"),
            ExtensionMapping("cursor", PARTIAL, "Cursor Rules",
                             "Review rules sync to .mdc files",
                             "Agent execution not available"),
            ExtensionMapping("windsurf", PARTIAL, "",
                             "Rules sync to .windsurfrules"),
            ExtensionMapping("cline", PARTIAL, "",
                             "Rules sync via Cline rules"),
            ExtensionMapping("aider", PARTIAL, "",
                             "Rules only — agents dropped"),
        ],
    ),
    PluginCompatibility(
        plugin_name="superpowers",
        plugin_description="Claude Code workflow skills (TDD, debugging, etc.)",
        category="skill",
        mappings=[
            ExtensionMapping("codex", PARTIAL, "",
                             "Skills sync as .agents/skills/",
                             "Skill invocation syntax differs"),
            ExtensionMapping("gemini", PARTIAL, "",
                             "Skills in .gemini/skills/"),
            ExtensionMapping("cursor", COMMUNITY, "",
                             "Cursor rules equivalent — community adaptation",
                             "Some skills work as Cursor rules"),
            ExtensionMapping("windsurf", COMMUNITY, "",
                             "Adapted as Windsurf memories"),
            ExtensionMapping("cline", PARTIAL, ""),
            ExtensionMapping("aider", MANUAL, "",
                             "Add skill files to aider read list",
                             "Used as context files only"),
        ],
    ),
    PluginCompatibility(
        plugin_name="grd",
        plugin_description="GRD research & development workflow system",
        category="mixed",
        mappings=[
            ExtensionMapping("codex", NOT_AVAILABLE, "",
                             "", "GRD uses Claude Code-specific Agent tool extensively"),
            ExtensionMapping("gemini", NOT_AVAILABLE),
            ExtensionMapping("cursor", NOT_AVAILABLE),
            ExtensionMapping("windsurf", NOT_AVAILABLE),
            ExtensionMapping("cline", NOT_AVAILABLE),
            ExtensionMapping("aider", NOT_AVAILABLE),
        ],
    ),
]

# Index for O(1) lookup
_DB_INDEX: dict[str, PluginCompatibility] = {p.plugin_name: p for p in _PLUGIN_DB}


class PluginExtensionMapper:
    """Map Claude Code plugins to equivalent extensions in target harnesses.

    Args:
        target_harnesses: Which harnesses to include in reports.
                          Defaults to common set.
    """

    DEFAULT_HARNESSES = ["codex", "gemini", "cursor", "windsurf", "cline", "aider"]

    def __init__(self, target_harnesses: list[str] | None = None):
        self.harnesses = target_harnesses or self.DEFAULT_HARNESSES

    def analyze_plugins(self, installed_plugins: list[str]) -> list[PluginCompatibility]:
        """Return compatibility info for each installed plugin.

        Args:
            installed_plugins: List of Claude Code plugin names (from registry).

        Returns:
            List of PluginCompatibility for known plugins.
            Unknown plugins are included with empty mappings.
        """
        result = []
        for name in installed_plugins:
            if name in _DB_INDEX:
                result.append(_DB_INDEX[name])
            else:
                # Unknown plugin — report with no mappings
                result.append(PluginCompatibility(
                    plugin_name=name,
                    plugin_description="(unknown plugin — not in compatibility DB)",
                    category="unknown",
                    mappings=[
                        ExtensionMapping(h, NOT_AVAILABLE, "", "Plugin not in compatibility DB")
                        for h in self.harnesses
                    ],
                ))
        return result

    def gap_report(self, installed_plugins: list[str]) -> dict[str, list[str]]:
        """Return dict of plugins that have no equivalent per harness.

        Args:
            installed_plugins: Installed plugin names.

        Returns:
            {harness: [plugin_names_with_no_equivalent]}
        """
        compat_list = self.analyze_plugins(installed_plugins)
        gaps: dict[str, list[str]] = {h: [] for h in self.harnesses}

        for compat in compat_list:
            for harness in self.harnesses:
                mapping = compat.get_mapping(harness)
                if not mapping or mapping.status == NOT_AVAILABLE:
                    gaps[harness].append(compat.plugin_name)

        return gaps

    def format_report(self, installed_plugins: list[str]) -> str:
        """Format a human-readable plugin compatibility report.

        Args:
            installed_plugins: Installed plugin names.

        Returns:
            Multi-line report string.
        """
        compat_list = self.analyze_plugins(installed_plugins)
        if not compat_list:
            return "No installed plugins to analyze."

        status_sym = {
            AVAILABLE: "✓",
            PARTIAL: "~",
            MANUAL: "M",
            COMMUNITY: "C",
            NOT_AVAILABLE: "✗",
        }

        harness_abbrev = {
            "codex": "CDX", "gemini": "GEM", "opencode": "OPC",
            "cursor": "CRS", "windsurf": "WND", "cline": "CLN",
            "aider": "ADR", "continue": "CNT",
        }

        lines = ["Plugin → Harness Extension Compatibility", "=" * 50]
        lines.append("Legend: ✓=available  ~=partial  M=manual  C=community  ✗=none")
        lines.append("")

        col_headers = [harness_abbrev.get(h, h[:3].upper()) for h in self.harnesses]
        name_w = max(len(p.plugin_name) for p in compat_list) + 2
        header = f"{'Plugin':<{name_w}}" + "".join(f"{h:>5}" for h in col_headers)
        lines.append(header)
        lines.append("-" * len(header))

        for compat in compat_list:
            row = f"{compat.plugin_name:<{name_w}}"
            for harness in self.harnesses:
                mapping = compat.get_mapping(harness)
                sym = status_sym.get(
                    mapping.status if mapping else NOT_AVAILABLE, "?"
                )
                row += f"{sym:>5}"
            lines.append(row)

        lines.append("")
        lines.append("Gap summary (plugins with no equivalent):")
        gaps = self.gap_report(installed_plugins)
        any_gaps = False
        for harness, gap_plugins in sorted(gaps.items()):
            if gap_plugins:
                any_gaps = True
                abbr = harness_abbrev.get(harness, harness)
                lines.append(f"  {abbr}: {', '.join(gap_plugins)}")
        if not any_gaps:
            lines.append("  None — all plugins have equivalents in configured harnesses.")

        # Installation hints for manual/community items
        hints: list[str] = []
        for compat in compat_list:
            for harness in self.harnesses:
                mapping = compat.get_mapping(harness)
                if mapping and mapping.status in (MANUAL, COMMUNITY) and mapping.install_hint:
                    hints.append(f"  [{harness}] {compat.plugin_name}: {mapping.install_hint}")

        if hints:
            lines.append("")
            lines.append("Setup hints for manual/community equivalents:")
            lines.extend(hints)

        return "\n".join(lines)

    def get_install_hints(self, plugin_name: str, harness: str) -> str:
        """Return install hint for a plugin in a specific harness.

        Args:
            plugin_name: Claude Code plugin name.
            harness: Target harness.

        Returns:
            Install hint string, or empty string if none available.
        """
        compat = _DB_INDEX.get(plugin_name)
        if not compat:
            return ""
        mapping = compat.get_mapping(harness)
        if not mapping:
            return ""
        return mapping.install_hint or mapping.notes


def discover_installed_plugins(cc_home: Path | None = None) -> list[str]:
    """Discover installed Claude Code plugins from the registry.

    Args:
        cc_home: Claude Code home directory (default: ~/.claude).

    Returns:
        Sorted list of installed plugin names.
    """
    cc_home = cc_home or (Path.home() / ".claude")
    registry_path = cc_home / "plugins" / "installed_plugins.json"

    if not registry_path.exists():
        return []

    try:
        import json
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        plugins = data.get("plugins", {})
        if isinstance(plugins, dict):
            return sorted(plugins.keys())
        return []
    except Exception:
        return []
