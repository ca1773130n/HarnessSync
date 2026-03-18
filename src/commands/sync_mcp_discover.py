from __future__ import annotations

"""
/sync-mcp-discover slash command — MCP Server Auto-Discovery.

Scans the local system for MCP servers that are installed (via npm, Python
packages, or known executables) but not yet configured in Claude Code.
Also scans other harnesses (Cursor, Windsurf, Codex) for MCP servers they
have configured that Claude Code doesn't know about.

Solves the common pain of setting up MCP servers in one tool and forgetting
to bring them into Claude Code / HarnessSync.

Usage:
    /sync-mcp-discover                   # Scan and report
    /sync-mcp-discover --json            # Machine-readable JSON output
    /sync-mcp-discover --from-harnesses  # Also scan harness configs for MCP servers
    /sync-mcp-discover --apply           # Import into .mcp.json (writes file)
    /sync-mcp-discover --dry-run         # Preview import without writing

Exit codes:
    0 — scan complete (new servers may or may not be found)
    1 — apply/import failed
    2 — config read error
"""

import argparse
import json
import os
import sys
import shlex
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.mcp_autodiscovery import McpAutoDiscovery


def _scan_harness_mcp_servers(project_dir: Path) -> dict[str, dict]:
    """Scan other harness config files for MCP servers not in Claude Code.

    Reads .cursor/mcp.json, .windsurf/mcp_config.json (or .codeium equivalent),
    and .codex/config.toml to collect MCP servers configured elsewhere.

    Returns:
        {server_name: {"source_harness": str, "config": dict}}
    """
    found: dict[str, dict] = {}

    # Cursor: .cursor/mcp.json
    cursor_mcp = project_dir / ".cursor" / "mcp.json"
    if cursor_mcp.is_file():
        try:
            data = json.loads(cursor_mcp.read_text(encoding="utf-8"))
            for name, cfg in (data.get("mcpServers") or {}).items():
                if name not in found:
                    found[name] = {"source_harness": "cursor", "config": cfg}
        except Exception:
            pass

    # Windsurf: .codeium/windsurf/mcp_config.json
    for ws_path in [
        project_dir / ".codeium" / "windsurf" / "mcp_config.json",
        Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
    ]:
        if ws_path.is_file():
            try:
                data = json.loads(ws_path.read_text(encoding="utf-8"))
                for name, cfg in (data.get("mcpServers") or {}).items():
                    if name not in found:
                        found[name] = {"source_harness": "windsurf", "config": cfg}
            except Exception:
                pass
            break

    return found


def _load_claude_mcp_servers(cc_home: Path, project_dir: Path) -> set[str]:
    """Return names of MCP servers already configured in Claude Code."""
    configured: set[str] = set()

    # Project-level .mcp.json
    mcp_json = project_dir / ".mcp.json"
    if mcp_json.is_file():
        try:
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
            configured.update((data.get("mcpServers") or {}).keys())
        except Exception:
            pass

    # User-level ~/.claude/settings.json
    settings_json = cc_home / "settings.json"
    if settings_json.is_file():
        try:
            data = json.loads(settings_json.read_text(encoding="utf-8"))
            configured.update((data.get("mcpServers") or {}).keys())
        except Exception:
            pass

    # Per-project in ~/.claude.json
    claude_json = cc_home.parent / ".claude.json"
    if claude_json.is_file():
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
            for proj_cfg in (data.get("projects") or {}).values():
                configured.update((proj_cfg.get("mcpServers") or {}).keys())
        except Exception:
            pass

    return configured


def _apply_import(new_servers: dict[str, dict], project_dir: Path, dry_run: bool) -> tuple[int, str]:
    """Merge new servers into project-level .mcp.json.

    Args:
        new_servers: {name: config_dict} to add
        project_dir: Project root directory
        dry_run: If True, return preview without writing

    Returns:
        (count_added, status_message)
    """
    if not new_servers:
        return 0, "Nothing to import."

    mcp_json = project_dir / ".mcp.json"
    existing: dict = {}
    if mcp_json.is_file():
        try:
            existing = json.loads(mcp_json.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    mcp_servers = dict(existing.get("mcpServers") or {})
    added = 0
    for name, cfg in new_servers.items():
        if name not in mcp_servers:
            mcp_servers[name] = cfg
            added += 1

    if dry_run:
        return added, f"[dry-run] would add {added} server(s) to {mcp_json}"

    existing["mcpServers"] = mcp_servers
    mcp_json.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    return added, f"Added {added} server(s) to {mcp_json}"


def main() -> None:
    """Entry point for /sync-mcp-discover command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-mcp-discover",
        description=(
            "Scan the local system for MCP servers not yet configured in Claude Code, "
            "including servers configured in other harnesses (Cursor, Windsurf)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output results as machine-readable JSON",
    )
    parser.add_argument(
        "--from-harnesses",
        action="store_true",
        dest="from_harnesses",
        help="Also scan other harness configs (Cursor, Windsurf) for configured MCP servers",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Import discovered servers into .mcp.json (writes file)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Preview import without writing (implies --apply output)",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        dest="project_dir",
        help="Project directory (default: cwd)",
    )
    parser.add_argument(
        "--cc-home",
        type=str,
        default=None,
        dest="cc_home",
        help="Claude Code home directory (default: ~/.claude)",
    )

    try:
        args = parser.parse_args(raw_args)
    except SystemExit:
        return

    project_dir = Path(args.project_dir) if args.project_dir else Path(
        os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    )
    cc_home = Path(args.cc_home) if args.cc_home else Path.home() / ".claude"

    try:
        # System-level scan (npm packages, Python packages, known executables)
        discoverer = McpAutoDiscovery(cc_home=cc_home, project_dir=project_dir)
        report = discoverer.discover()

        harness_new: dict[str, dict] = {}
        if getattr(args, "from_harnesses", False):
            # Scan other harness configs
            harness_servers = _scan_harness_mcp_servers(project_dir)
            configured_names = _load_claude_mcp_servers(cc_home, project_dir)
            for name, info in harness_servers.items():
                if name not in configured_names:
                    harness_new[name] = info["config"]

        if args.json_output:
            output = {
                "already_configured": report.already_configured,
                "discovered_new": [
                    {
                        "name": s.name,
                        "source": s.source,
                        "description": s.description,
                        "command": s.command,
                        "args": s.args,
                        "env": s.env,
                    }
                    for s in report.new_servers
                ],
                "from_harnesses": [
                    {"name": n, "config": c} for n, c in harness_new.items()
                ],
                "scan_errors": report.scan_errors,
            }
            print(json.dumps(output, indent=2))
        else:
            print(report.format())

            if harness_new:
                print()
                print("## MCP Servers Found in Other Harnesses\n")
                print(
                    f"Found {len(harness_new)} server(s) configured in Cursor/Windsurf "
                    "but not in Claude Code:\n"
                )
                for name, cfg in harness_new.items():
                    cmd = cfg.get("command", "?")
                    srv_args = " ".join(cfg.get("args", []))
                    print(f"  {name}:  {cmd} {srv_args}".rstrip())
                print()

        if args.apply or args.dry_run:
            # Merge system-discovered + harness-found into import dict
            to_import: dict[str, dict] = {}
            for s in report.new_servers:
                entry: dict = {"command": s.command}
                if s.args:
                    entry["args"] = s.args
                if s.env:
                    entry["env"] = s.env
                to_import[s.name] = entry
            to_import.update(harness_new)

            count, msg = _apply_import(to_import, project_dir, dry_run=args.dry_run)
            print(msg)
            if count and not args.dry_run:
                print("Run /sync to propagate the new servers to all harnesses.")

    except Exception as e:
        print(f"Error during MCP discovery: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
