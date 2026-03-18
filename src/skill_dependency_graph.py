from __future__ import annotations

"""Skill Dependency Graph — visualize relationships between Claude Code skills.

Parses SKILL.md files to detect explicit and implicit skill invocations,
builds a directed dependency graph, renders it as both an ASCII tree and a
Mermaid diagram, and detects circular dependencies before they cause sync
or runtime issues.

Detection heuristics (no external tooling needed):
  - Explicit: ``invoke skill: <name>`` / ``use skill: <name>``
  - Shorthand: ``/<skill-name>`` references in skill bodies
  - MCP shared: skills that reference the same named MCP server
  - Mentioned by name: skill names that appear verbatim in other skills' text

Usage::

    graph = SkillDependencyGraph.from_source_data(source_data)
    print(graph.to_ascii())
    print(graph.to_mermaid())

    cycles = graph.find_cycles()
    if cycles:
        for cycle in cycles:
            print(f"Circular dependency: {' → '.join(cycle)}")
"""

import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Regex patterns for dependency detection
# ---------------------------------------------------------------------------

# Explicit invocations: "invoke skill: name" / "use skill: name"
_EXPLICIT_RE = re.compile(
    r"\b(?:invoke|use|call|load|run)\s+skill[:\s]+[\"']?(\w[\w-]*)[\"']?",
    re.IGNORECASE,
)

# Slash-command references: /skill-name (common Claude Code convention)
_SLASH_CMD_RE = re.compile(r"(?<!\w)/(\w[\w-]{1,})\b")

# Shared MCP server references: `mcp server "name"` or `use mcp: name`
_MCP_SERVER_RE = re.compile(
    r"\b(?:mcp\s+server|use\s+mcp)\s*[:\s]+[\"']?(\w[\w-]*)[\"']?",
    re.IGNORECASE,
)

# Direct mcp__ tool call references: mcp__server__tool_name
_MCP_TOOL_CALL_RE = re.compile(r"\bmcp__([a-zA-Z0-9_-]+)__([a-zA-Z0-9_-]+)\b")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SkillNode:
    """A node in the dependency graph representing one skill."""

    name: str
    dependencies: list[str] = field(default_factory=list)   # skills this skill depends on
    dependents: list[str] = field(default_factory=list)      # skills that depend on this one
    mcp_servers: list[str] = field(default_factory=list)     # MCP servers referenced
    description: str = ""                                    # first line of SKILL.md


@dataclass
class DependencyEdge:
    """A directed edge: ``source`` depends on ``target``."""

    source: str
    target: str
    kind: str  # "explicit" | "slash" | "mcp_shared" | "mention"


@dataclass
class ImpactReport:
    """Removal impact for a single skill node."""

    skill_name: str
    broken_dependents: list[str] = field(default_factory=list)  # skills that depend on this one
    mcp_tools_orphaned: list[str] = field(default_factory=list)  # mcp__s__t tokens used only here
    active_harnesses: list[str] = field(default_factory=list)   # harnesses where skill is live

    def format(self) -> str:
        lines = [f"Removal impact: /{self.skill_name}", "=" * 48]
        if self.broken_dependents:
            lines.append(
                f"  Skills that depend on this:  {', '.join(sorted(self.broken_dependents))}"
            )
        if self.mcp_tools_orphaned:
            lines.append(
                f"  MCP tools orphaned by removal: {', '.join(sorted(self.mcp_tools_orphaned))}"
            )
        if self.active_harnesses:
            lines.append(
                f"  Harnesses where skill is active: {', '.join(sorted(self.active_harnesses))}"
            )
        if not any([self.broken_dependents, self.mcp_tools_orphaned]):
            lines.append("  No downstream skill impact — safe to remove.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

class SkillDependencyGraph:
    """Directed dependency graph for Claude Code skills.

    Build with :meth:`from_source_data` or :meth:`from_skills_dir`,
    then render with :meth:`to_ascii` or :meth:`to_mermaid`.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, SkillNode] = {}
        self._edges: list[DependencyEdge] = []

    # ------------------------------------------------------------------ #
    # Constructors                                                         #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_source_data(cls, source_data: dict) -> "SkillDependencyGraph":
        """Build graph from SourceReader.discover_all() output.

        Args:
            source_data: Dict with at least a ``"skills"`` key mapping
                         skill names to their content or metadata dicts.

        Returns:
            Populated SkillDependencyGraph.
        """
        graph = cls()
        skills: dict = source_data.get("skills", {})
        for name, data in skills.items():
            content = ""
            description = ""
            if isinstance(data, dict):
                content = data.get("content", "") or data.get("description", "")
                description = data.get("description", "")
            elif isinstance(data, str):
                content = data
            if not description and content:
                # Extract first non-blank, non-header line as description
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        description = stripped[:100]
                        break
            graph.add_skill(name, content, description=description)

        graph._resolve_edges()
        return graph

    @classmethod
    def from_skills_dir(cls, skills_dir: Path) -> "SkillDependencyGraph":
        """Build graph by scanning a skills directory for SKILL.md files.

        Args:
            skills_dir: Directory containing skill subdirectories.

        Returns:
            Populated SkillDependencyGraph.
        """
        graph = cls()
        if not skills_dir.is_dir():
            return graph

        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_md = skill_dir / "SKILL.md"
            if not skill_md.exists():
                continue
            try:
                content = skill_md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                content = ""
            description = ""
            for line in content.splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    description = stripped[:100]
                    break
            graph.add_skill(skill_dir.name, content, description=description)

        graph._resolve_edges()
        return graph

    # ------------------------------------------------------------------ #
    # Graph construction                                                   #
    # ------------------------------------------------------------------ #

    def add_skill(self, name: str, content: str, description: str = "") -> SkillNode:
        """Add a skill node to the graph.

        Args:
            name:        Skill directory name / identifier.
            content:     Raw SKILL.md content for dependency extraction.
            description: Short description (first line of skill body).

        Returns:
            The created or updated SkillNode.
        """
        node = self._nodes.setdefault(name, SkillNode(name=name))
        node.description = description or node.description

        # Extract MCP server references for shared-MCP edge detection
        node.mcp_servers = _MCP_SERVER_RE.findall(content)

        # Extract direct mcp__server__tool call references
        node._mcp_tool_calls = {  # type: ignore[attr-defined]
            f"{m.group(1)}__{m.group(2)}" for m in _MCP_TOOL_CALL_RE.finditer(content)
        }

        # Store raw content for later edge resolution
        node._raw_content = content  # type: ignore[attr-defined]
        return node

    def _resolve_edges(self) -> None:
        """Resolve all dependency edges after all skills have been added."""
        all_names = set(self._nodes.keys())
        mcp_to_skills: dict[str, list[str]] = defaultdict(list)

        for name, node in self._nodes.items():
            content = getattr(node, "_raw_content", "")

            # Explicit invocations
            for match in _EXPLICIT_RE.finditer(content):
                dep = match.group(1)
                if dep in all_names and dep != name:
                    self._add_edge(name, dep, "explicit")

            # Slash-command references
            for match in _SLASH_CMD_RE.finditer(content):
                dep = match.group(1)
                if dep in all_names and dep != name:
                    self._add_edge(name, dep, "slash")

            # Name mention (weak dependency)
            for other_name in all_names:
                if other_name == name:
                    continue
                # Only flag if the name appears as a whole word
                if re.search(rf"\b{re.escape(other_name)}\b", content, re.IGNORECASE):
                    self._add_edge(name, other_name, "mention")

            # Collect MCP servers for shared-MCP detection
            for server in node.mcp_servers:
                mcp_to_skills[server].append(name)

        # Shared-MCP edges: skills sharing the same MCP server are related
        for server, skill_list in mcp_to_skills.items():
            if len(skill_list) > 1:
                for i, s1 in enumerate(skill_list):
                    for s2 in skill_list[i + 1:]:
                        self._add_edge(s1, s2, "mcp_shared")

        # Populate dependents on nodes from edges
        for edge in self._edges:
            if edge.source in self._nodes and edge.target in self._nodes:
                src = self._nodes[edge.source]
                tgt = self._nodes[edge.target]
                if edge.target not in src.dependencies:
                    src.dependencies.append(edge.target)
                if edge.source not in tgt.dependents:
                    tgt.dependents.append(edge.source)

    def _add_edge(self, source: str, target: str, kind: str) -> None:
        """Add an edge if it doesn't already exist."""
        for e in self._edges:
            if e.source == source and e.target == target:
                return
        self._edges.append(DependencyEdge(source=source, target=target, kind=kind))

    # ------------------------------------------------------------------ #
    # Analysis                                                             #
    # ------------------------------------------------------------------ #

    def find_cycles(self) -> list[list[str]]:
        """Detect all cycles in the dependency graph using DFS.

        Returns:
            List of cycles, each cycle is a list of skill names forming a loop.
            Empty list if no cycles exist.
        """
        visited: set[str] = set()
        stack: set[str] = set()
        cycles: list[list[str]] = []

        def dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            stack.add(node)
            path.append(node)

            for dep in self._nodes.get(node, SkillNode(name=node)).dependencies:
                if dep not in visited:
                    dfs(dep, path)
                elif dep in stack:
                    # Found a cycle — extract it
                    cycle_start = path.index(dep)
                    cycles.append(path[cycle_start:] + [dep])

            path.pop()
            stack.discard(node)

        for name in self._nodes:
            if name not in visited:
                dfs(name, [])

        return cycles

    def roots(self) -> list[str]:
        """Return skills with no dependents (entry points)."""
        return sorted(
            name for name, node in self._nodes.items() if not node.dependents
        )

    def leaves(self) -> list[str]:
        """Return skills with no dependencies (pure utilities)."""
        return sorted(
            name for name, node in self._nodes.items() if not node.dependencies
        )

    # ------------------------------------------------------------------ #
    # Rendering                                                            #
    # ------------------------------------------------------------------ #

    def to_ascii(self, max_depth: int = 6) -> str:
        """Render the dependency graph as an ASCII tree.

        Each root skill is rendered with its dependency subtree. Skills
        that appear in multiple branches are shown once in full and then
        abbreviated with ``(see above)``.

        Args:
            max_depth: Maximum nesting depth to prevent runaway output.

        Returns:
            Multi-line ASCII tree string.
        """
        if not self._nodes:
            return "Skill Dependency Graph: No skills found."

        lines = [
            "Skill Dependency Graph",
            "=" * 40,
            f"  {len(self._nodes)} skill(s), {len(self._edges)} edge(s)",
            "",
        ]

        rendered: set[str] = set()

        def _render(name: str, prefix: str, depth: int) -> None:
            if depth > max_depth:
                lines.append(f"{prefix}… (max depth reached)")
                return
            node = self._nodes.get(name, SkillNode(name=name))
            already = name in rendered
            desc_str = f"  — {node.description[:50]}" if node.description else ""
            marker = "(see above)" if already else ""
            lines.append(f"{prefix}{name}{desc_str} {marker}".rstrip())
            if already or not node.dependencies:
                return
            rendered.add(name)
            deps = sorted(node.dependencies)
            for i, dep in enumerate(deps):
                is_last = i == len(deps) - 1
                branch = "└── " if is_last else "├── "
                child_prefix = prefix + ("    " if is_last else "│   ")
                lines.append(f"{prefix}{branch}", )
                _render(dep, child_prefix, depth + 1)

        for root in self.roots() or sorted(self._nodes.keys()):
            _render(root, "  ", depth=0)
            lines.append("")

        cycles = self.find_cycles()
        if cycles:
            lines.append(f"  ⚠ {len(cycles)} circular dependency/ies detected:")
            for cycle in cycles[:3]:
                lines.append(f"    {' → '.join(cycle)}")
            lines.append("")

        lines.append("Legend: ├── dependency  (← skill uses →)")
        return "\n".join(lines)

    def to_mermaid(self) -> str:
        """Render the dependency graph as a Mermaid flowchart.

        Returns:
            Mermaid diagram string (LR direction, paste into any Mermaid renderer).
        """
        if not self._nodes:
            return "graph LR\n  empty[No skills found]"

        lines = ["graph LR"]

        # Node definitions with labels
        for name, node in sorted(self._nodes.items()):
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
            label = node.description[:40].replace('"', "'") if node.description else name
            lines.append(f'  {safe_name}["{name}\\n{label}"]')

        lines.append("")

        # Edges
        kind_styles = {
            "explicit": "-->",
            "slash": "-.->",
            "mcp_shared": "-.->",
            "mention": "-.->",
        }
        rendered_edges: set[tuple[str, str]] = set()
        for edge in self._edges:
            src = re.sub(r"[^a-zA-Z0-9_]", "_", edge.source)
            tgt = re.sub(r"[^a-zA-Z0-9_]", "_", edge.target)
            key = (src, tgt)
            if key in rendered_edges:
                continue
            rendered_edges.add(key)
            arrow = kind_styles.get(edge.kind, "-->")
            label = "" if edge.kind in ("explicit",) else f"|{edge.kind}|"
            lines.append(f"  {src} {arrow}{label} {tgt}")

        # Cycle highlighting
        cycles = self.find_cycles()
        if cycles:
            lines.append("")
            lines.append("  %% Circular dependencies:")
            for cycle in cycles[:3]:
                nodes_in_cycle = [re.sub(r"[^a-zA-Z0-9_]", "_", n) for n in cycle]
                lines.append(f"  %% {' -> '.join(nodes_in_cycle)}")

        return "\n".join(lines)

    def removal_impact(self, skill_name: str) -> ImpactReport:
        """Analyse the downstream impact of removing *skill_name*.

        Args:
            skill_name: Skill identifier to analyse (case-insensitive match
                        against stored node names).

        Returns:
            :class:`ImpactReport` describing which skills break and which
            MCP tools become orphaned.
        """
        name = skill_name.lower()
        # Try exact match first, then case-insensitive
        node = self._nodes.get(name) or self._nodes.get(skill_name)
        if node is None:
            return ImpactReport(skill_name=skill_name)

        # Dependents: skills that list this one as a dependency
        broken = list(node.dependents)

        # MCP tool calls unique to this skill (not used by any other skill)
        this_tools: set[str] = getattr(node, "_mcp_tool_calls", set())
        other_tools: set[str] = set()
        for other_name, other_node in self._nodes.items():
            if other_name == name or other_name == skill_name:
                continue
            other_tools |= getattr(other_node, "_mcp_tool_calls", set())
        orphaned = sorted(this_tools - other_tools)

        # Harnesses where skills are synced (non-"none" support)
        _HARNESS_SKILL_SUPPORT = {
            "codex": "partial", "gemini": "partial", "opencode": "partial",
            "cursor": "full", "aider": "none", "windsurf": "partial",
            "cline": "partial", "continue": "partial", "vscode": "partial",
            "neovim": "none", "zed": "partial",
        }
        active = [h for h, lvl in _HARNESS_SKILL_SUPPORT.items() if lvl != "none"]

        return ImpactReport(
            skill_name=skill_name,
            broken_dependents=sorted(broken),
            mcp_tools_orphaned=orphaned,
            active_harnesses=active,
        )

    @classmethod
    def from_skills_and_agents_dir(
        cls,
        skills_dir: Path,
        agents_dir: Path | None = None,
    ) -> "SkillDependencyGraph":
        """Build graph from skill and agent directories.

        Agents that reference skills (via ``/skill-name`` or ``invoke skill:
        name``) are added as virtual skill nodes so their edges appear in the
        graph.

        Args:
            skills_dir: Directory containing skill subdirectories.
            agents_dir: Directory containing agent ``.md`` files (optional).

        Returns:
            Populated :class:`SkillDependencyGraph`.
        """
        graph = cls.from_skills_dir(skills_dir)
        if agents_dir is None or not agents_dir.is_dir():
            return graph

        all_names = set(graph._nodes.keys())
        for agent_file in sorted(agents_dir.glob("*.md")):
            try:
                content = agent_file.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            agent_id = f"@{agent_file.stem}"
            agent_node = graph.add_skill(agent_id, content, description=f"Agent: {agent_file.stem}")

            # Resolve edges for this agent node against known skills
            for match in _EXPLICIT_RE.finditer(content):
                dep = match.group(1)
                if dep in all_names:
                    graph._add_edge(agent_id, dep, "explicit")
                    graph._nodes[dep].dependents.append(agent_id)
            for match in _SLASH_CMD_RE.finditer(content):
                dep = match.group(1)
                if dep in all_names:
                    graph._add_edge(agent_id, dep, "slash")
                    if agent_id not in graph._nodes[dep].dependents:
                        graph._nodes[dep].dependents.append(agent_id)

        return graph

    def format_summary(self) -> str:
        """Return a short text summary of the graph."""
        if not self._nodes:
            return "No skills found."

        cycles = self.find_cycles()
        roots = self.roots()
        leaves = self.leaves()

        parts = [
            f"Skills: {len(self._nodes)}",
            f"Dependencies: {len(self._edges)}",
            f"Entry points: {', '.join(roots) if roots else 'none'}",
            f"Utilities: {', '.join(leaves) if leaves else 'none'}",
        ]
        if cycles:
            parts.append(f"⚠ Circular deps: {len(cycles)}")

        return " | ".join(parts)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def build_graph(source_data: dict) -> SkillDependencyGraph:
    """Build and return a SkillDependencyGraph from source_data.

    Args:
        source_data: Output of SourceReader.discover_all().

    Returns:
        SkillDependencyGraph ready for rendering or analysis.
    """
    return SkillDependencyGraph.from_source_data(source_data)
