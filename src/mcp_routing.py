from __future__ import annotations

"""MCP Server Routing — specify which MCP servers sync to which harnesses.

Allows users to configure fine-grained routing rules so that heavy or
specialized MCP servers only appear in harnesses that should use them.

Example use case: a ``database-mcp`` server with broad file/network access
should only appear in Claude Code and Cursor — not in lightweight Aider
sessions or Gemini.

Configuration file: ``.harnesssync/mcp_routing.json``

    {
        "routes": {
            "database-mcp":   ["cursor", "codex"],
            "context7":       "all",
            "heavy-indexer":  ["cursor"],
            "lightweight-mcp": ["aider", "gemini", "codex"]
        },
        "default": "all"
    }

Keys in ``routes`` are MCP server names (matching keys in ``.mcp.json``).
Values are either:
  - ``"all"``  — sync to every harness (same as omitting the entry)
  - A list of harness names — sync only to those harnesses

The ``default`` key controls what happens to servers not listed in
``routes``:
  - ``"all"``  — sync everywhere (default behavior, backward-compatible)
  - ``"none"`` — do NOT sync unlisted servers to any harness
  - A list of harness names — sync unlisted servers only to those harnesses

Usage::

    router = McpRouter(project_dir=Path.cwd())

    # Filter mcp_servers dict for a specific target
    filtered = router.filter_for_target(mcp_servers, target="aider")

    # Get a routing summary for display
    print(router.format_summary(mcp_servers))
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.constants import EXTENDED_TARGETS

_CONFIG_FILENAME = "mcp_routing.json"
_CONFIG_DIR = ".harnesssync"


@dataclass
class McpRoute:
    """Routing rule for a single MCP server."""

    server_name: str
    targets: list[str] | str  # "all" or list of harness names

    def includes(self, target: str) -> bool:
        """Return True if this route sends the server to *target*."""
        if self.targets == "all" or self.targets == ["all"]:
            return True
        if isinstance(self.targets, list):
            return target.lower() in [t.lower() for t in self.targets]
        return False


@dataclass
class McpRoutingConfig:
    """Parsed MCP routing configuration."""

    routes: dict[str, McpRoute] = field(default_factory=dict)
    default: str | list[str] = "all"  # "all", "none", or list of targets

    def is_empty(self) -> bool:
        return not self.routes and self.default == "all"

    def target_receives(self, server_name: str, target: str) -> bool:
        """Return True if *target* should receive *server_name*."""
        if server_name in self.routes:
            return self.routes[server_name].includes(target)
        # Fall back to default policy
        if self.default == "all":
            return True
        if self.default == "none":
            return False
        if isinstance(self.default, list):
            return target.lower() in [t.lower() for t in self.default]
        return True


def _load_routing_config(project_dir: Path) -> McpRoutingConfig:
    """Load mcp_routing.json from the project's .harnesssync directory.

    Returns an empty config (route everything) if the file doesn't exist
    or cannot be parsed.
    """
    path = project_dir / _CONFIG_DIR / _CONFIG_FILENAME
    if not path.exists():
        return McpRoutingConfig()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return McpRoutingConfig()

    if not isinstance(data, dict):
        return McpRoutingConfig()

    routes: dict[str, McpRoute] = {}
    for server_name, targets in data.get("routes", {}).items():
        if isinstance(targets, str):
            routes[server_name] = McpRoute(server_name=server_name, targets=targets)
        elif isinstance(targets, list):
            routes[server_name] = McpRoute(
                server_name=server_name,
                targets=[str(t) for t in targets],
            )

    default = data.get("default", "all")
    if not isinstance(default, (str, list)):
        default = "all"

    return McpRoutingConfig(routes=routes, default=default)


class McpRouter:
    """Filter MCP server dicts based on per-harness routing rules.

    Args:
        project_dir: Project root directory (used to locate .harnesssync/).
    """

    def __init__(self, project_dir: Path | None = None) -> None:
        self._project_dir = project_dir or Path.cwd()
        self._config = _load_routing_config(self._project_dir)

    @property
    def is_configured(self) -> bool:
        """Return True if a non-trivial routing config was loaded."""
        return not self._config.is_empty()

    def filter_for_target(
        self,
        mcp_servers: dict,
        target: str,
    ) -> dict:
        """Return a filtered copy of *mcp_servers* for *target*.

        Servers not permitted by the routing config are removed.  If no
        routing config exists all servers pass through unchanged.

        Args:
            mcp_servers: Dict of ``{server_name: config_dict}`` from SourceReader.
            target: Harness name to filter for (e.g. ``"aider"``).

        Returns:
            Filtered dict containing only servers routed to *target*.
        """
        if self._config.is_empty():
            return mcp_servers

        return {
            name: cfg
            for name, cfg in mcp_servers.items()
            if self._config.target_receives(name, target)
        }

    def dropped_servers(self, mcp_servers: dict, target: str) -> list[str]:
        """Return names of servers that will NOT be synced to *target*.

        Useful for capability gap warnings.
        """
        if self._config.is_empty():
            return []
        return [
            name
            for name in mcp_servers
            if not self._config.target_receives(name, target)
        ]

    def format_summary(self, mcp_servers: dict) -> str:
        """Return a human-readable routing summary table.

        Shows which servers reach which harnesses.
        """
        if not mcp_servers:
            return "No MCP servers configured."

        if self._config.is_empty():
            return (
                "MCP routing: all servers sync to all harnesses "
                "(no .harnesssync/mcp_routing.json found)."
            )

        lines: list[str] = ["MCP Server Routing", "=" * 40]
        for server_name in sorted(mcp_servers):
            route = self._config.routes.get(server_name)
            if route:
                if route.targets == "all":
                    targets_str = "→ all harnesses"
                else:
                    targets_str = "→ " + ", ".join(sorted(route.targets))
            else:
                default = self._config.default
                if default == "all":
                    targets_str = "→ all harnesses (default)"
                elif default == "none":
                    targets_str = "→ BLOCKED (default=none)"
                else:
                    targets_str = "→ " + ", ".join(sorted(default)) + " (default)"
            lines.append(f"  {server_name:<30} {targets_str}")

        return "\n".join(lines)

    def format_dropped_warnings(self, mcp_servers: dict) -> list[str]:
        """Return warning strings for servers that won't reach some harnesses.

        Surfaces routing decisions that users may not have intended.
        """
        if self._config.is_empty() or not mcp_servers:
            return []

        warnings: list[str] = []
        for server_name in sorted(mcp_servers):
            excluded_targets = [
                t for t in EXTENDED_TARGETS
                if not self._config.target_receives(server_name, t)
            ]
            if excluded_targets:
                warnings.append(
                    f"MCP routing: '{server_name}' will NOT sync to "
                    f"{', '.join(excluded_targets)} (per mcp_routing.json)."
                )
        return warnings


def create_default_routing_config(
    project_dir: Path,
    mcp_servers: dict | None = None,
) -> Path:
    """Write a starter mcp_routing.json with all known servers set to 'all'.

    Useful for onboarding — gives users a template to edit.

    Args:
        project_dir: Project root (config written to .harnesssync/ inside it).
        mcp_servers: Optional dict of current MCP servers to pre-populate.

    Returns:
        Path to the written config file.
    """
    config_dir = project_dir / _CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / _CONFIG_FILENAME

    routes: dict[str, str] = {}
    if mcp_servers:
        for name in mcp_servers:
            routes[name] = "all"

    data = {
        "_comment": (
            "MCP Server Routing — control which MCP servers sync to which harnesses. "
            "Values can be 'all', 'none', or a list of harness names. "
            "See: https://github.com/harnesssync/harnesssync#mcp-routing"
        ),
        "routes": routes,
        "default": "all",
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
