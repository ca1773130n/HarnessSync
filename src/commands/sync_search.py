from __future__ import annotations

"""
/sync search slash command implementation.

Search across all synced configs with a keyword — finds matching rules,
skills, commands, agents, and MCP server names across all harnesses.

Usage:
    /sync search 'database'
    /sync search --target codex 'security'
    /sync search --type mcp 'postgres'
"""

import json
import os
import re
import shlex
import sys
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

# Known harness config locations relative to project root
_HARNESS_RULES_FILES = {
    "codex": "AGENTS.md",
    "gemini": "GEMINI.md",
    "opencode": "OPENCODE.md",
    "cursor": ".cursor/rules/harnesssync.mdc",
    "aider": "CONVENTIONS.md",
    "windsurf": ".windsurfrules",
}

_HARNESS_SKILL_DIRS = {
    "codex": ".agents/skills",
    "gemini": ".gemini/skills",
    "opencode": ".opencode/skills",
}

_HARNESS_AGENT_DIRS = {
    "gemini": ".gemini/agents",
    "opencode": ".opencode/agents",
}

_HARNESS_COMMAND_DIRS = {
    "gemini": ".gemini/commands",
    "opencode": ".opencode/commands",
}

_HARNESS_MCP_FILES = {
    "gemini": ".gemini/settings.json",
    "opencode": ".opencode/settings.json",
    "cursor": ".cursor/mcp.json",
}


def _search_file(path: Path, query: str, case_sensitive: bool = False) -> list[dict]:
    """Search a text file for query string, returning matched line info."""
    if not path.is_file():
        return []
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    flags = 0 if case_sensitive else re.IGNORECASE
    matches = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        if re.search(re.escape(query), line, flags):
            matches.append({
                "line": lineno,
                "text": line.strip()[:120],
            })
    return matches


def _search_dir_names(directory: Path, query: str, case_sensitive: bool = False) -> list[str]:
    """Search directory entry names for query."""
    if not directory.is_dir():
        return []
    flags = 0 if case_sensitive else re.IGNORECASE
    return sorted(
        d.name for d in directory.iterdir()
        if re.search(re.escape(query), d.name, flags)
    )


def _search_mcp_file(path: Path, query: str, case_sensitive: bool = False) -> list[str]:
    """Search MCP config JSON for server names matching query."""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    mcp_servers = data.get("mcpServers", {})
    flags = 0 if case_sensitive else re.IGNORECASE
    return sorted(
        name for name in mcp_servers
        if re.search(re.escape(query), name, flags)
    )


def search_all(
    query: str,
    project_dir: Path,
    targets: list[str] | None = None,
    search_types: set[str] | None = None,
    case_sensitive: bool = False,
) -> dict[str, dict]:
    """Search across all synced harness configs for a keyword.

    Args:
        query: Search term
        project_dir: Project root directory
        targets: List of harness names to search (None = all)
        search_types: Set of types to search: rules, skills, agents, commands, mcp
                      (None = all)
        case_sensitive: If True, use case-sensitive matching

    Returns:
        Dict mapping harness_name -> {
            "rules": [{"line": int, "text": str}, ...],
            "skills": [str, ...],
            "agents": [str, ...],
            "commands": [str, ...],
            "mcp": [str, ...],
        }
        Only includes entries with at least one match.
    """
    all_targets = list(_HARNESS_RULES_FILES.keys())
    if targets:
        all_targets = [t for t in all_targets if t in targets]

    types = search_types or {"rules", "skills", "agents", "commands", "mcp"}
    results: dict[str, dict] = {}

    for harness in all_targets:
        harness_results: dict[str, list] = {}

        # Rules
        if "rules" in types:
            rules_file = project_dir / _HARNESS_RULES_FILES[harness]
            matches = _search_file(rules_file, query, case_sensitive)
            if matches:
                harness_results["rules"] = matches

        # Skills
        if "skills" in types and harness in _HARNESS_SKILL_DIRS:
            skills_dir = project_dir / _HARNESS_SKILL_DIRS[harness]
            names = _search_dir_names(skills_dir, query, case_sensitive)
            if names:
                harness_results["skills"] = names

        # Agents
        if "agents" in types and harness in _HARNESS_AGENT_DIRS:
            agents_dir = project_dir / _HARNESS_AGENT_DIRS[harness]
            names = _search_dir_names(agents_dir, query, case_sensitive)
            if names:
                harness_results["agents"] = names

        # Commands
        if "commands" in types and harness in _HARNESS_COMMAND_DIRS:
            cmds_dir = project_dir / _HARNESS_COMMAND_DIRS[harness]
            names = _search_dir_names(cmds_dir, query, case_sensitive)
            if names:
                harness_results["commands"] = names

        # MCP servers
        if "mcp" in types and harness in _HARNESS_MCP_FILES:
            mcp_file = project_dir / _HARNESS_MCP_FILES[harness]
            names = _search_mcp_file(mcp_file, query, case_sensitive)
            if names:
                harness_results["mcp"] = names

        if harness_results:
            results[harness] = harness_results

    return results


def format_results(query: str, results: dict[str, dict]) -> str:
    """Format search results for terminal display."""
    if not results:
        return f"No matches found for '{query}' across synced harness configs."

    total = sum(
        sum(len(v) for v in hr.values())
        for hr in results.values()
    )
    lines = [f"Search results for '{query}' — {total} match(es) across {len(results)} harness(es)"]
    lines.append("=" * 60)

    for harness, hr in sorted(results.items()):
        lines.append(f"\n[{harness}]")

        if "rules" in hr:
            lines.append(f"  rules ({len(hr['rules'])} line(s)):")
            for m in hr["rules"][:10]:
                lines.append(f"    L{m['line']}: {m['text']}")
            if len(hr["rules"]) > 10:
                lines.append(f"    ... +{len(hr['rules']) - 10} more lines")

        for section in ("skills", "agents", "commands", "mcp"):
            if section in hr:
                items = hr[section]
                lines.append(f"  {section}: {', '.join(items[:20])}")
                if len(items) > 20:
                    lines.append(f"    ... +{len(items) - 20} more")

    return "\n".join(lines)


def main() -> None:
    """Entry point for /sync search command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-search",
        description="Search across all synced harness configs",
    )
    parser.add_argument("query", nargs="?", help="Search term")
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Limit search to specific harness (codex, gemini, opencode, ...)",
    )
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        help="Limit search to section type: rules, skills, agents, commands, mcp",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Use case-sensitive matching",
    )
    parser.add_argument("--project-dir", type=str, default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    if not args.query:
        parser.print_help()
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    targets = [args.target] if args.target else None
    types = {args.type} if args.type else None

    results = search_all(
        query=args.query,
        project_dir=project_dir,
        targets=targets,
        search_types=types,
        case_sensitive=args.case_sensitive,
    )
    print(format_results(args.query, results))


if __name__ == "__main__":
    main()
