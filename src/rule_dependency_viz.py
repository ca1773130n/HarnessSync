from __future__ import annotations

"""Rule dependency visualization (item 27).

Analyzes CLAUDE.md and .claude/rules/ to detect when rules reference or
depend on each other (e.g. rule A says "follow rule B for X") and visualizes
the dependency graph. Helps users understand the structure of their config
before syncing and identify circular or conflicting rule references.

Detection approach:
1. Parse rule sections / files to extract named rules
2. Scan each rule's text for references to other rule names
3. Build a directed dependency graph (rule A depends on rule B)
4. Detect cycles, orphan rules, and highly-connected hubs
5. Output as text tree, adjacency list, or Mermaid diagram

Usage:
    viz = RuleDependencyViz(project_dir)
    graph = viz.build_graph()
    print(viz.format_text(graph))
    print(viz.format_mermaid(graph))
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator  # noqa: F401


# Heading patterns that introduce named sections/rules
_HEADING_RE = re.compile(r"^#{1,3}\s+(.+?)(?:\s+#+)?$", re.MULTILINE)

# Patterns that indicate a rule is referencing another rule/section
_REF_PATTERNS = [
    # "see rule X", "follow rule X", "refer to X", "apply rule X"
    re.compile(
        r"\b(?:see|follow|refer(?:ence)?|apply|use|per|as\s+in|described\s+in)\s+"
        r"(?:rule|section|the\s+rule|the\s+section)?\s*['\"]?([A-Z][a-z\-]+(?:\s+[A-Z][a-z\-]+){0,3})['\"]?",
        re.IGNORECASE,
    ),
    # "see ## Heading" or "per ## Heading"
    re.compile(
        r"\b(?:see|per|follow|as\s+in)\s+#{1,3}\s+(.+?)(?:\.|,|$)",
        re.IGNORECASE | re.MULTILINE,
    ),
    # Explicit cross-references: [Rule Name](#anchor)
    re.compile(r"\[([^\]]+)\]\(#[^\)]+\)", re.IGNORECASE),
    # "rule: XYZ" or "follows: XYZ" in bullet points
    re.compile(r"^\s*[-*]\s+(?:follows?|see|per):\s+(.+?)$", re.IGNORECASE | re.MULTILINE),
]


@dataclass
class RuleNode:
    """A single rule (section or file) in the dependency graph."""
    name: str
    source_file: str  # relative path
    line_number: int = 0
    content_snippet: str = ""  # first 200 chars of content


@dataclass
class RuleDependencyGraph:
    """Directed dependency graph for a set of rules."""
    nodes: dict[str, RuleNode] = field(default_factory=dict)
    # Edges: {rule_name: set of rule names it depends on}
    edges: dict[str, set[str]] = field(default_factory=dict)

    def add_node(self, node: RuleNode) -> None:
        self.nodes[node.name] = node
        if node.name not in self.edges:
            self.edges[node.name] = set()

    def add_edge(self, from_rule: str, to_rule: str) -> None:
        if from_rule not in self.edges:
            self.edges[from_rule] = set()
        self.edges[from_rule].add(to_rule)

    def find_cycles(self) -> list[list[str]]:
        """Return list of cycles (each cycle is a list of rule names)."""
        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycles: list[list[str]] = []

        def _dfs(node: str, path: list[str]) -> None:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)

            for neighbor in self.edges.get(node, set()):
                if neighbor not in visited:
                    _dfs(neighbor, path)
                elif neighbor in rec_stack:
                    # Found a cycle — extract the cycle portion
                    cycle_start = path.index(neighbor)
                    cycles.append(list(path[cycle_start:]))

            path.pop()
            rec_stack.discard(node)

        for node in self.nodes:
            if node not in visited:
                _dfs(node, [])

        return cycles

    def find_orphans(self) -> list[str]:
        """Return rules that neither depend on nor are depended on by others."""
        referenced = set()
        for deps in self.edges.values():
            referenced.update(deps)

        orphans = []
        for name in self.nodes:
            has_deps = bool(self.edges.get(name))
            is_referenced = name in referenced
            if not has_deps and not is_referenced:
                orphans.append(name)
        return sorted(orphans)

    def find_hubs(self, threshold: int = 3) -> list[tuple[str, int]]:
        """Return rules referenced by ≥ threshold other rules (hotspots)."""
        in_degree: dict[str, int] = {n: 0 for n in self.nodes}
        for deps in self.edges.values():
            for dep in deps:
                in_degree[dep] = in_degree.get(dep, 0) + 1
        hubs = [(name, count) for name, count in in_degree.items() if count >= threshold]
        return sorted(hubs, key=lambda x: x[1], reverse=True)


class RuleDependencyViz:
    """Analyzes rule files and builds a dependency graph."""

    def __init__(self, project_dir: Path, cc_home: Path | None = None):
        self.project_dir = project_dir
        self.cc_home = cc_home or Path.home() / ".claude"

    def build_graph(self) -> RuleDependencyGraph:
        """Parse all rule sources and build the dependency graph.

        Returns:
            RuleDependencyGraph with nodes for each rule/section and
            edges for detected dependencies.
        """
        graph = RuleDependencyGraph()

        # Discover rule sources
        sources = list(self._discover_rule_sources())

        # First pass: extract all rule names (nodes)
        rules_by_file: dict[str, list[tuple[str, int, str]]] = {}
        for file_path, content in sources:
            sections = self._extract_sections(content, file_path)
            rules_by_file[file_path] = sections
            for name, lineno, snippet in sections:
                graph.add_node(RuleNode(
                    name=name,
                    source_file=file_path,
                    line_number=lineno,
                    content_snippet=snippet[:200],
                ))

        # Second pass: detect references (edges)
        all_rule_names = list(graph.nodes.keys())
        for file_path, content in sources:
            sections = rules_by_file.get(file_path, [])
            self._detect_edges(graph, content, file_path, sections, all_rule_names)

        return graph

    # ------------------------------------------------------------------
    # Source discovery
    # ------------------------------------------------------------------

    def _discover_rule_sources(self) -> Generator[tuple[str, str], None, None]:
        """Yield (relative_path, content) for all rule-containing files."""
        # Project CLAUDE.md
        claude_md = self.project_dir / "CLAUDE.md"
        if claude_md.exists():
            yield "CLAUDE.md", claude_md.read_text(encoding="utf-8", errors="replace")

        # User-scope CLAUDE.md
        user_claude = self.cc_home / "CLAUDE.md"
        if user_claude.exists():
            try:
                yield "~/.claude/CLAUDE.md", user_claude.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

        # .claude/rules/ directory
        rules_dir = self.cc_home / "rules"
        if rules_dir.is_dir():
            for md_file in sorted(rules_dir.glob("*.md")):
                try:
                    yield f".claude/rules/{md_file.name}", md_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass

        # Project-local .claude/rules/
        local_rules = self.project_dir / ".claude" / "rules"
        if local_rules.is_dir():
            for md_file in sorted(local_rules.glob("*.md")):
                try:
                    yield f".claude/rules/{md_file.name}", md_file.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass

    def _extract_sections(
        self, content: str, source_file: str
    ) -> list[tuple[str, int, str]]:
        """Extract named sections from markdown content.

        Returns list of (section_name, line_number, snippet).
        """
        sections: list[tuple[str, int, str]] = []
        lines = content.split("\n")

        for i, line in enumerate(lines):
            m = _HEADING_RE.match(line)
            if m:
                heading = m.group(1).strip()
                # Grab snippet: up to 10 lines after heading
                snippet_lines = lines[i + 1 : i + 11]
                snippet = "\n".join(snippet_lines).strip()
                sections.append((heading, i + 1, snippet))

        # If no headings found, treat whole file as one rule named after file
        if not sections:
            from pathlib import Path as _Path
            name = _Path(source_file).stem
            sections.append((name, 1, content[:200]))

        return sections

    def _detect_edges(
        self,
        graph: RuleDependencyGraph,
        content: str,
        source_file: str,
        sections: list[tuple[str, int, str]],
        all_rule_names: list[str],
    ) -> None:
        """Detect rule cross-references and add edges to the graph."""
        # Build a map of (line_number → section_name) to attribute refs to correct section
        section_starts = [(lineno, name) for name, lineno, _ in sections]
        section_starts.sort()

        def _find_owning_section(lineno: int) -> str | None:
            owner = None
            for start, name in section_starts:
                if start <= lineno:
                    owner = name
                else:
                    break
            return owner

        lines = content.split("\n")
        for i, line in enumerate(lines):
            lineno = i + 1
            owner = _find_owning_section(lineno)
            if owner is None:
                continue

            # Try each reference pattern
            for pattern in _REF_PATTERNS:
                for m in pattern.finditer(line):
                    ref_text = m.group(1).strip()
                    # Check if ref_text matches any known rule name
                    matched = self._fuzzy_match_rule(ref_text, all_rule_names)
                    if matched and matched != owner:
                        graph.add_edge(owner, matched)

    def _fuzzy_match_rule(self, ref_text: str, all_rules: list[str]) -> str | None:
        """Match a reference text to the closest rule name.

        Returns exact match first, then case-insensitive, then substring.
        """
        # Exact match
        if ref_text in all_rules:
            return ref_text
        # Case-insensitive
        ref_lower = ref_text.lower()
        for name in all_rules:
            if name.lower() == ref_lower:
                return name
        # Substring: ref is contained in rule name or vice versa
        for name in all_rules:
            if ref_lower in name.lower() or name.lower() in ref_lower:
                return name
        return None

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def format_text(self, graph: RuleDependencyGraph) -> str:
        """Format the dependency graph as a text tree."""
        if not graph.nodes:
            return "No rules found to analyze."

        lines = ["Rule Dependency Graph", "=" * 50, ""]

        cycles = graph.find_cycles()
        orphans = graph.find_orphans()
        hubs = graph.find_hubs(threshold=2)

        # Summary
        dep_count = sum(len(deps) for deps in graph.edges.values())
        lines.append(f"Rules: {len(graph.nodes)}  |  Dependencies: {dep_count}")
        if cycles:
            lines.append(f"WARNING: {len(cycles)} circular dependency cycle(s) detected!")
        lines.append("")

        # Dependency tree per rule
        lines.append("Dependencies:")
        lines.append("-" * 40)
        for name in sorted(graph.nodes.keys()):
            deps = sorted(graph.edges.get(name, set()))
            if deps:
                lines.append(f"  {name}")
                for dep in deps:
                    lines.append(f"    └── {dep}")
            else:
                lines.append(f"  {name}  (no dependencies)")

        if cycles:
            lines.append("\nCircular Dependencies Detected:")
            lines.append("-" * 40)
            for cycle in cycles:
                lines.append("  " + " → ".join(cycle) + " → " + cycle[0])

        if hubs:
            lines.append("\nHighly Referenced Rules (hubs):")
            lines.append("-" * 40)
            for name, count in hubs:
                lines.append(f"  {name}  (referenced by {count} rules)")

        if orphans:
            lines.append(f"\nOrphan Rules ({len(orphans)}) — no dependencies in/out:")
            lines.append("-" * 40)
            for name in orphans:
                node = graph.nodes[name]
                lines.append(f"  {name}  ({node.source_file}:{node.line_number})")

        return "\n".join(lines)

    def format_mermaid(self, graph: RuleDependencyGraph) -> str:
        """Format the dependency graph as a Mermaid flowchart diagram.

        Returns a Markdown code block with Mermaid syntax that can be
        rendered by GitHub, Notion, or any Mermaid-compatible viewer.
        """
        if not graph.nodes:
            return "```mermaid\ngraph LR\n    NoRules[No rules found]\n```"

        lines = ["```mermaid", "graph LR"]

        # Node definitions (sanitize names for Mermaid IDs)
        def _mermaid_id(name: str) -> str:
            return re.sub(r"[^a-zA-Z0-9_]", "_", name)

        for name, node in sorted(graph.nodes.items()):
            mid = _mermaid_id(name)
            label = name.replace('"', "'")
            lines.append(f'    {mid}["{label}"]')

        # Edges
        cycles = graph.find_cycles()
        cycle_pairs: set[tuple[str, str]] = set()
        for cycle in cycles:
            for i in range(len(cycle)):
                a = cycle[i]
                b = cycle[(i + 1) % len(cycle)]
                cycle_pairs.add((a, b))

        for from_rule, deps in sorted(graph.edges.items()):
            for dep in sorted(deps):
                fid = _mermaid_id(from_rule)
                did = _mermaid_id(dep)
                if (from_rule, dep) in cycle_pairs:
                    lines.append(f"    {fid} -->|cycle| {did}")
                else:
                    lines.append(f"    {fid} --> {did}")

        lines.append("```")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Rule Scope & Priority Visualizer (item 19)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class ScopedRule:
    """A rule with its scope level and source information."""
    name: str
    scope: str           # "global", "project", "subdirectory"
    source_file: str
    line_number: int
    priority: int        # Lower number = higher priority (1 = highest)
    content_snippet: str = ""
    conflicts_with: list[str] = field(default_factory=list)


def _detect_scope(source_file: str, project_dir: Path) -> str:
    """Determine the scope of a rule based on its source file path."""
    path = Path(source_file)
    # Global: user's ~/.claude/
    if "~/" in source_file or source_file.startswith(str(Path.home())):
        return "global"
    # Subdirectory: has a directory component other than project root
    if path.parts and len(path.parts) > 1 and path.parts[0] not in (".", "CLAUDE.md"):
        return "subdirectory"
    return "project"


def build_scope_map(
    project_dir: Path,
    cc_home: Path | None = None,
) -> list[ScopedRule]:
    """Build a list of all rules with their scope and priority.

    Priority ordering (highest to lowest):
        1. Subdirectory rules (most specific)
        2. Project rules (CLAUDE.md in project root)
        3. Global rules (~/.claude/CLAUDE.md)

    Args:
        project_dir: Project root directory.
        cc_home: Claude home directory (default: ~/.claude).

    Returns:
        List of ScopedRule objects sorted by (scope_priority, source_file, line).
    """
    cc_home = cc_home or Path.home() / ".claude"
    viz = RuleDependencyViz(project_dir, cc_home)
    sources = list(viz._discover_rule_sources())

    scope_priority = {"subdirectory": 1, "project": 2, "global": 3}
    rules: list[ScopedRule] = []
    name_to_rules: dict[str, list[ScopedRule]] = {}

    for source_file, content in sources:
        sections = viz._extract_sections(content, source_file)
        scope = _detect_scope(source_file, project_dir)
        prio = scope_priority[scope]
        for rule_name, lineno, snippet in sections:
            sr = ScopedRule(
                name=rule_name,
                scope=scope,
                source_file=source_file,
                line_number=lineno,
                priority=prio,
                content_snippet=snippet[:200],
            )
            rules.append(sr)
            name_to_rules.setdefault(rule_name.lower(), []).append(sr)

    # Detect conflicts: same rule name at different scopes
    for rule_name_lower, scoped_list in name_to_rules.items():
        if len(scoped_list) > 1:
            all_names = [r.source_file for r in scoped_list]
            for sr in scoped_list:
                sr.conflicts_with = [
                    other.source_file
                    for other in scoped_list
                    if other is not sr
                ]

    rules.sort(key=lambda r: (r.priority, r.source_file, r.line_number))
    return rules


def format_scope_tree(rules: list[ScopedRule]) -> str:
    """Format a tree view of rules organized by scope.

    Shows global → project → subdirectory hierarchy with conflict markers.
    Rules that override a higher-scope rule are annotated with "(overrides ...)".

    Args:
        rules: List from build_scope_map().

    Returns:
        Multi-line formatted string.
    """
    if not rules:
        return "No rules found."

    lines = ["Rule Scope & Priority View", "=" * 50, ""]
    lines.append("Priority: subdirectory (1) > project (2) > global (3)")
    lines.append("")

    scopes = ["subdirectory", "project", "global"]
    scope_labels = {
        "subdirectory": "Subdirectory rules (highest priority — most specific)",
        "project": "Project rules (CLAUDE.md in project root)",
        "global": "Global rules (~/.claude/CLAUDE.md)",
    }

    by_scope: dict[str, list[ScopedRule]] = {"subdirectory": [], "project": [], "global": []}
    for rule in rules:
        by_scope.setdefault(rule.scope, []).append(rule)

    # Track which rule names appear at multiple scopes
    all_names: dict[str, list[str]] = {}
    for rule in rules:
        all_names.setdefault(rule.name.lower(), []).append(rule.scope)

    for scope in scopes:
        scope_rules = by_scope.get(scope, [])
        if not scope_rules:
            continue
        lines.append(f"[{scope.upper()}] {scope_labels[scope]}")
        lines.append("─" * 45)
        for rule in scope_rules:
            conflict_marker = ""
            if len(all_names.get(rule.name.lower(), [])) > 1:
                other_scopes = [s for s in all_names[rule.name.lower()] if s != scope]
                conflict_marker = f"  ⚠ overrides {', '.join(other_scopes)}"
            lines.append(f"  • {rule.name}  ({rule.source_file}:{rule.line_number}){conflict_marker}")
        lines.append("")

    # Conflict summary
    conflicts = [r for r in rules if r.conflicts_with]
    if conflicts:
        seen: set[str] = set()
        lines.append("Scope Conflicts (same rule name at multiple levels):")
        lines.append("─" * 45)
        for rule in conflicts:
            key = rule.name.lower()
            if key not in seen:
                seen.add(key)
                conflicting = [r for r in rules if r.name.lower() == key]
                parts = [f"{r.scope}:{r.source_file}" for r in conflicting]
                lines.append(f"  ⚠ '{rule.name}' defined in: {', '.join(parts)}")
        lines.append("")
    else:
        lines.append("No scope conflicts detected.")

    return "\n".join(lines)
