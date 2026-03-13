from __future__ import annotations

"""MCP Server Dependency-Aware Startup Ordering (item 30).

Detects dependency relationships between MCP servers and generates target
configs with correct startup ordering. Solves subtle bugs where MCP servers
fail because they start in the wrong order (e.g., a memory server must start
before a task server that depends on it).

Dependency detection strategies:
1. **Explicit annotation**: `_depends_on` key in the server's config dict.
2. **Name heuristics**: Known naming conventions (e.g., "task-*" depends on "memory").
3. **Env var reference**: A server's env vars reference another server's name.
4. **Topological sort**: Once dependencies are detected, servers are ordered
   so all dependencies come before their dependents.

Usage::

    from src.mcp_dependency_resolver import MCPDependencyResolver

    resolver = MCPDependencyResolver()
    ordered = resolver.resolve(mcp_servers_dict)
    warnings = resolver.check_cycles(mcp_servers_dict)

    # Get ordered server names only
    names = [s["name"] for s in ordered]
"""

import re
from dataclasses import dataclass, field


# ── Known dependency heuristics ─────────────────────────────────────────────

# (dependent_pattern, dependency_pattern) — both are regex patterns matched
# against server names (case-insensitive). If dependent_pattern matches a
# server name and dependency_pattern matches another server name, a dependency
# edge is inferred.
_HEURISTIC_DEPS: list[tuple[re.Pattern, re.Pattern, str]] = [
    # Task servers depend on memory/storage servers
    (
        re.compile(r"task|todo|kanban|planner", re.I),
        re.compile(r"memory|store|storage|persist|db|database", re.I),
        "task management servers typically depend on a memory/storage server",
    ),
    # LLM/AI overlay servers depend on the base model or context servers
    (
        re.compile(r"context|recall|retriev|search", re.I),
        re.compile(r"embed|vector|index", re.I),
        "retrieval servers typically depend on an embedding/vector server",
    ),
    # Orchestrator/router servers depend on worker servers
    (
        re.compile(r"orchestrat|router|gateway", re.I),
        re.compile(r"worker|executor|runner|agent", re.I),
        "orchestrator servers depend on worker/executor servers",
    ),
    # Auth/session servers must start before anything that uses sessions
    (
        re.compile(r"api|web|http|proxy|service", re.I),
        re.compile(r"auth|session|iam|oauth|token", re.I),
        "API servers typically depend on an auth/session server",
    ),
    # Cache-aware servers depend on the cache server
    (
        re.compile(r".*"), # catch-all (only fires when env var check matches)
        re.compile(r"cache|redis|memcach", re.I),
        "servers that reference cache servers depend on the cache server starting first",
    ),
]


# ── Data types ──────────────────────────────────────────────────────────────

@dataclass
class DependencyEdge:
    """A single detected dependency between two MCP servers."""

    dependent: str     # Server that depends on another
    dependency: str    # Server that must start first
    reason: str        # Human-readable explanation of why this dependency was inferred
    source: str        # "explicit" | "heuristic" | "env_ref"


@dataclass
class MCPOrderResult:
    """Result of dependency-aware ordering."""

    ordered: list[str]              # Server names in startup order
    edges: list[DependencyEdge]     # All detected dependency edges
    cycle_warnings: list[str]       # Names of servers in dependency cycles

    def format_order(self) -> str:
        """Human-readable startup order."""
        if not self.ordered:
            return "No MCP servers to order."
        lines = ["MCP Server Startup Order:"]
        for i, name in enumerate(self.ordered, 1):
            lines.append(f"  {i:>2}. {name}")
        if self.edges:
            lines.append("\nDetected dependencies:")
            for edge in self.edges:
                lines.append(f"  {edge.dependent} → {edge.dependency}  [{edge.source}]")
        if self.cycle_warnings:
            lines.append("\nWARNING — circular dependency detected:")
            for name in self.cycle_warnings:
                lines.append(f"  {name}")
        return "\n".join(lines)

    def format_warnings(self) -> str:
        """Return only warnings, empty string if none."""
        if not self.cycle_warnings:
            return ""
        lines = ["MCP dependency cycle detected — startup order may be incorrect:"]
        lines.extend(f"  {n}" for n in self.cycle_warnings)
        return "\n".join(lines)


# ── Graph utilities ─────────────────────────────────────────────────────────

def _topological_sort(nodes: list[str], edges: list[DependencyEdge]) -> tuple[list[str], list[str]]:
    """Kahn's algorithm for topological sort.

    Returns (ordered_list, cycle_nodes).
    cycle_nodes is non-empty if a cycle was detected.
    """
    from collections import deque

    # Build adjacency (dependency → dependents) and in-degree maps
    in_degree: dict[str, int] = {n: 0 for n in nodes}
    adj: dict[str, list[str]] = {n: [] for n in nodes}

    for edge in edges:
        if edge.dependent in in_degree and edge.dependency in in_degree:
            adj[edge.dependency].append(edge.dependent)
            in_degree[edge.dependent] += 1

    queue: deque[str] = deque(n for n in nodes if in_degree[n] == 0)
    ordered: list[str] = []

    while queue:
        node = queue.popleft()
        ordered.append(node)
        for neighbor in adj.get(node, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    cycle_nodes = [n for n in nodes if n not in ordered]
    # Append cycle nodes at end so they still appear in output
    ordered.extend(cycle_nodes)
    return ordered, cycle_nodes


# ── Resolver ────────────────────────────────────────────────────────────────

class MCPDependencyResolver:
    """Detects MCP server dependencies and produces a startup-safe ordering.

    Args:
        use_heuristics: Enable name-based heuristic dependency detection
                        (default True). Disable for strict explicit-only mode.
    """

    def __init__(self, use_heuristics: bool = True):
        self.use_heuristics = use_heuristics

    def detect_edges(self, servers: dict[str, dict]) -> list[DependencyEdge]:
        """Detect all dependency edges in *servers*.

        Args:
            servers: Dict of {server_name: server_config}.
                     Server config may include ``_depends_on`` key.

        Returns:
            List of DependencyEdge objects.
        """
        edges: list[DependencyEdge] = []
        names = list(servers.keys())

        # 1. Explicit _depends_on annotation
        for name, config in servers.items():
            deps = config.get("_depends_on", [])
            if isinstance(deps, str):
                deps = [deps]
            for dep in deps:
                if dep in servers:
                    edges.append(DependencyEdge(
                        dependent=name,
                        dependency=dep,
                        reason="Explicit _depends_on annotation",
                        source="explicit",
                    ))

        if not self.use_heuristics:
            return edges

        # 2. Name-based heuristics
        for dep_pattern, dep_on_pattern, reason in _HEURISTIC_DEPS:
            dependents = [n for n in names if dep_pattern.search(n)]
            dependencies = [n for n in names if dep_on_pattern.search(n)]
            for dependent in dependents:
                for dependency in dependencies:
                    if dependent == dependency:
                        continue
                    # Avoid adding if already explicit
                    if not any(
                        e.dependent == dependent and e.dependency == dependency
                        for e in edges
                    ):
                        edges.append(DependencyEdge(
                            dependent=dependent,
                            dependency=dependency,
                            reason=reason,
                            source="heuristic",
                        ))

        # 3. Env var cross-references
        # If server A's env values contain server B's name, A depends on B.
        for name, config in servers.items():
            env = config.get("env", {})
            if not isinstance(env, dict):
                continue
            env_values = " ".join(str(v) for v in env.values())
            for other_name in names:
                if other_name == name:
                    continue
                if other_name.lower() in env_values.lower():
                    if not any(
                        e.dependent == name and e.dependency == other_name
                        for e in edges
                    ):
                        edges.append(DependencyEdge(
                            dependent=name,
                            dependency=other_name,
                            reason=f"Env var references server name '{other_name}'",
                            source="env_ref",
                        ))

        return edges

    def resolve(self, servers: dict[str, dict]) -> MCPOrderResult:
        """Produce a dependency-safe startup order for *servers*.

        Args:
            servers: Dict of {server_name: server_config}.

        Returns:
            MCPOrderResult with ordered server names and detected edges.
        """
        if not servers:
            return MCPOrderResult(ordered=[], edges=[], cycle_warnings=[])

        names = list(servers.keys())
        edges = self.detect_edges(servers)
        ordered, cycle_nodes = _topological_sort(names, edges)

        return MCPOrderResult(
            ordered=ordered,
            edges=edges,
            cycle_warnings=cycle_nodes,
        )

    def check_cycles(self, servers: dict[str, dict]) -> list[str]:
        """Return server names involved in dependency cycles.

        Args:
            servers: Dict of {server_name: server_config}.

        Returns:
            List of server names in cycles (empty if no cycles).
        """
        result = self.resolve(servers)
        return result.cycle_warnings

    def apply_ordering_to_dict(
        self, servers: dict[str, dict]
    ) -> dict[str, dict]:
        """Return a new ordered dict with servers in startup-safe order.

        Python 3.7+ dicts preserve insertion order, so callers that iterate
        over the result get servers in dependency order.

        Args:
            servers: Dict of {server_name: server_config}.

        Returns:
            New dict with the same entries in dependency-safe order.
        """
        result = self.resolve(servers)
        return {name: servers[name] for name in result.ordered if name in servers}
