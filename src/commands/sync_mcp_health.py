from __future__ import annotations

"""
/sync-mcp-health slash command implementation.

Pings all configured MCP servers across all harnesses, shows which are
reachable and which are misconfigured or down, and flags harnesses where a
server was synced but is unreachable.

Usage:
    /sync-mcp-health [--verbose] [--project-dir PATH]
"""

import json
import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.mcp_reachability import McpReachabilityChecker, McpReachabilityResult


# Known per-harness MCP config file locations
_HARNESS_MCP_FILES: dict[str, list[str]] = {
    "codex":    [".codex/config.toml"],           # Codex stores MCP in TOML
    "gemini":   [".gemini/settings.json"],          # Gemini settings.json
    "opencode": ["opencode.json"],                  # opencode.json
    "cursor":   [".cursor/mcp.json"],               # Cursor mcp.json
}

# Global MCP files always checked
_GLOBAL_MCP_FILES = [".mcp.json"]


def _load_mcp_from_json(path: Path) -> dict:
    """Read MCP server configs from a JSON file.

    Understands both flat {name: config} and nested {mcpServers: {...}} formats.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}

    if "mcpServers" in data:
        return data["mcpServers"]
    if "mcp" in data and isinstance(data["mcp"], dict):
        return data["mcp"].get("servers", {})
    # Fallback: treat top-level as server map if values look like server configs
    if all(isinstance(v, dict) for v in data.values()):
        return data
    return {}


def _load_mcp_from_toml(path: Path) -> dict:
    """Read MCP server configs from a TOML file (Codex config.toml).

    Returns empty dict if the file has no [mcp.servers] section or if
    toml parsing is unavailable. Falls back to regex extraction.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    servers: dict = {}

    # Try tomllib (Python 3.11+) or tomli fallback
    try:
        import tomllib  # type: ignore
        data = tomllib.loads(content)
        mcp_section = data.get("mcp", {})
        return mcp_section.get("servers", {})
    except ImportError:
        pass

    try:
        import tomli  # type: ignore
        data = tomli.loads(content)
        mcp_section = data.get("mcp", {})
        return mcp_section.get("servers", {})
    except ImportError:
        pass

    # Regex fallback: extract [mcp.servers.*] sections
    import re
    server_re = re.compile(r'^\[mcp\.servers\."?([^"\]]+)"?\]', re.MULTILINE)
    for m in server_re.finditer(content):
        servers[m.group(1)] = {}  # Config details not extracted — just names

    return servers


def _collect_harness_mcp(project_dir: Path) -> dict[str, dict]:
    """Collect MCP server configs per harness.

    Returns:
        Dict mapping harness_name -> {server_name: config_dict}
    """
    harness_mcp: dict[str, dict] = {}

    for harness, rel_paths in _HARNESS_MCP_FILES.items():
        for rel in rel_paths:
            path = project_dir / rel
            if not path.is_file():
                continue
            if path.suffix == ".toml":
                servers = _load_mcp_from_toml(path)
            else:
                servers = _load_mcp_from_json(path)
            if servers:
                harness_mcp[harness] = servers
                break

    # Global MCP
    for rel in _GLOBAL_MCP_FILES:
        path = project_dir / rel
        if path.is_file():
            servers = _load_mcp_from_json(path)
            if servers:
                harness_mcp["global"] = servers
                break

    return harness_mcp


def _latency_label(response_ms: float | None) -> str:
    """Return a human-readable latency label with colour hint."""
    if response_ms is None:
        return ""
    if response_ms < 100:
        return f"  ({response_ms:.0f}ms ✓)"
    if response_ms < 500:
        return f"  ({response_ms:.0f}ms ~)"
    return f"  ({response_ms:.0f}ms ⚠)"


def _format_results(
    harness: str,
    servers: dict,
    results: list[McpReachabilityResult],
    verbose: bool,
) -> list[str]:
    """Format health check results for one harness including response times."""
    ok = [r for r in results if r.reachable]
    fail = [r for r in results if not r.reachable]

    status_icon = "✓" if not fail else ("⚠" if ok else "✗")
    lines = [f"\n[{harness.upper()}]  {status_icon}  {len(ok)}/{len(servers)} servers reachable"]

    if verbose or fail:
        for r in results:
            icon = "✓" if r.reachable else "✗"
            latency = _latency_label(r.response_ms)
            if r.reachable:
                lines.append(f"  {icon} {r.name}{latency}")
            else:
                lines.append(f"  {icon} {r.name}  — {r.reason}")

    return lines


def main() -> None:
    """Entry point for /sync-mcp-health command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-mcp-health",
        description="MCP server health dashboard across all harnesses",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show all servers including reachable ones",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        help="Project directory (default: cwd)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="TCP connection timeout in seconds (default: 3.0)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    print("MCP Server Health Dashboard")
    print("=" * 60)
    print(f"Project: {project_dir}")

    harness_mcp = _collect_harness_mcp(project_dir)

    if not harness_mcp:
        print("\nNo MCP server configurations found.")
        print("Tip: Run /sync first to populate harness config files.")
        return

    checker = McpReachabilityChecker(timeout=args.timeout)
    total_ok = 0
    total_fail = 0
    any_failed_harness = False

    for harness in sorted(harness_mcp):
        servers = harness_mcp[harness]
        if not servers:
            continue

        results = checker.check_all(servers)
        ok = sum(1 for r in results if r.reachable)
        fail = sum(1 for r in results if not r.reachable)
        total_ok += ok
        total_fail += fail
        if fail:
            any_failed_harness = True

        lines = _format_results(harness, servers, results, args.verbose)
        for line in lines:
            print(line)

    print(f"\n{'=' * 60}")
    print(f"Total: {total_ok} reachable, {total_fail} unreachable across {len(harness_mcp)} harness(es)")

    if any_failed_harness:
        print(
            "\nUnreachable servers were synced to target harnesses but won't work."
            "\nFix server configs in CLAUDE.md or MCP settings and re-run /sync."
        )
    else:
        print("\nAll MCP servers are reachable.")


if __name__ == "__main__":
    main()
