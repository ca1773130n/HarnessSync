from __future__ import annotations

"""
/sync-activate slash command — Harness Context Switcher (item 9).

Activates a harness context: shows a summary of what's synced to it,
outputs shell env-var exports so callers can source the output, and
optionally opens the primary config file for that harness.

Usage:
    /sync-activate <harness>              # show summary + export env vars
    /sync-activate <harness> --export     # emit shell exports only (eval-able)
    /sync-activate <harness> --open       # open primary config file in $EDITOR
    /sync-activate --list                 # list available harnesses

Shell integration (add to ~/.zshrc or ~/.bashrc):
    harness() { eval "$(/path/to/sync-activate "$1" --export)"; }

Then: `harness codex` sets ACTIVE_HARNESS=codex in your shell.
"""

import os
import sys
import shlex
import argparse
import json
import subprocess
from pathlib import Path
from datetime import datetime

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.state_manager import StateManager
from src.harness_detector import scan_all_with_versions


# Known config entry-points per harness, relative to $HOME.
# First existing path wins.
_PRIMARY_CONFIG: dict[str, list[str]] = {
    "codex":    ["AGENTS.md", ".codex/AGENTS.md"],
    "gemini":   ["GEMINI.md", ".gemini/GEMINI.md"],
    "opencode": [".opencode/config.json"],
    "cursor":   [".cursor/rules/claude-code-rules.mdc", ".cursor/rules/"],
    "aider":    ["CONVENTIONS.md", ".aider.conf.yml"],
    "windsurf": [".windsurfrules", ".windsurf/"],
}

# Env var names set when activating a harness
_ENV_ACTIVE_HARNESS = "ACTIVE_HARNESS"
_ENV_HARNESS_CONFIG = "HARNESS_CONFIG"
_ENV_HARNESS_SYNCED = "HARNESS_LAST_SYNCED"


def _find_primary_config(harness: str, project_dir: Path) -> Path | None:
    """Return the first existing primary config file for *harness*.

    Checks project-local paths first (relative to *project_dir*),
    then falls back to home-directory paths.
    """
    candidates = _PRIMARY_CONFIG.get(harness, [])
    search_roots = [project_dir, Path.home()]

    for root in search_roots:
        for rel in candidates:
            p = root / rel
            if p.exists():
                return p
    return None


def _build_summary(harness: str, project_dir: Path, state: StateManager) -> dict:
    """Build a structured summary of the harness sync state."""
    status = state.get_target_status(harness) or {}

    detected = scan_all_with_versions()
    harness_info = detected.get(harness, {})

    config_path = _find_primary_config(harness, project_dir)

    # Count synced items from state
    synced_counts: dict[str, int] = {}
    last_sync = status.get("last_sync", "never")
    if isinstance(last_sync, (int, float)):
        last_sync = datetime.fromtimestamp(last_sync).strftime("%Y-%m-%d %H:%M")

    for key in ("rules", "skills", "agents", "commands", "mcp", "settings"):
        count = status.get(f"synced_{key}", 0)
        if count:
            synced_counts[key] = count

    return {
        "harness": harness,
        "installed": harness_info.get("detected", False),
        "version": harness_info.get("version"),
        "config_path": str(config_path) if config_path else None,
        "last_sync": last_sync,
        "synced_counts": synced_counts,
    }


def _format_summary(summary: dict) -> str:
    """Format a harness summary for human display."""
    harness = summary["harness"].upper()
    installed = summary["installed"]
    version = summary["version"]
    config = summary["config_path"] or "(no config found)"
    last_sync = summary["last_sync"]
    counts = summary["synced_counts"]

    lines = [
        f"  Harness: {harness}",
        f"  Installed: {'yes' if installed else 'not detected'}",
    ]
    if version:
        lines.append(f"  Version: {version}")
    lines.append(f"  Config: {config}")
    lines.append(f"  Last sync: {last_sync}")

    if counts:
        parts = [f"{k}: {v}" for k, v in sorted(counts.items())]
        lines.append(f"  Synced: {', '.join(parts)}")
    else:
        lines.append("  Synced: (no sync recorded yet)")

    return "\n".join(lines)


def _build_exports(summary: dict) -> str:
    """Build shell export statements for the active harness context."""
    lines = [
        f'export {_ENV_ACTIVE_HARNESS}="{summary["harness"]}"',
    ]
    if summary["config_path"]:
        lines.append(f'export {_ENV_HARNESS_CONFIG}="{summary["config_path"]}"')
    if summary["last_sync"] not in ("never", None):
        lines.append(f'export {_ENV_HARNESS_SYNCED}="{summary["last_sync"]}"')
    return "\n".join(lines)


def _open_config(config_path: str | None) -> None:
    """Open the config file in $EDITOR or a sensible fallback."""
    if not config_path:
        print("No config file found for this harness.", file=sys.stderr)
        return

    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", ""))
    if editor:
        subprocess.run([editor, config_path])
    elif sys.platform == "darwin":
        subprocess.run(["open", config_path])
    else:
        print(f"Set $EDITOR to open: {config_path}", file=sys.stderr)


def _list_harnesses(project_dir: Path, state: StateManager) -> None:
    """Print a summary table of all known harnesses and their sync state."""
    detected = scan_all_with_versions()
    all_harnesses = sorted(set(list(detected.keys()) + list(_PRIMARY_CONFIG.keys())))

    print("Available harnesses:")
    print(f"  {'Harness':<12} {'Installed':<12} {'Last Sync':<22} Version")
    print("  " + "-" * 60)
    for name in all_harnesses:
        info = detected.get(name, {})
        status = state.get_target_status(name) or {}
        installed = "yes" if info.get("detected") else "—"
        version = info.get("version") or "—"
        last_sync = status.get("last_sync", "never")
        if isinstance(last_sync, (int, float)):
            last_sync = datetime.fromtimestamp(last_sync).strftime("%Y-%m-%d %H:%M")
        print(f"  {name:<12} {installed:<12} {str(last_sync):<22} {version}")


def main() -> None:
    """Entry point for /sync-activate command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-activate",
        description="Activate a harness context: show sync summary and export env vars.",
    )
    parser.add_argument("harness", nargs="?", default=None,
                        help="Harness name to activate (codex, gemini, opencode, cursor, aider, windsurf)")
    parser.add_argument("--export", action="store_true",
                        help="Emit only shell export statements (suitable for eval)")
    parser.add_argument("--open", dest="open_config", action="store_true",
                        help="Open primary config file in $EDITOR after showing summary")
    parser.add_argument("--list", action="store_true",
                        help="List all harnesses and their sync state")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Output summary as JSON")
    parser.add_argument("--project-dir", default=None,
                        help="Project directory (default: cwd)")
    args = parser.parse_args(raw_args)

    project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()
    state = StateManager()

    if args.list:
        _list_harnesses(project_dir, state)
        return

    if not args.harness:
        # Show currently active harness from env, or prompt
        active = os.environ.get(_ENV_ACTIVE_HARNESS)
        if active:
            print(f"Active harness: {active}")
            summary = _build_summary(active, project_dir, state)
            print(_format_summary(summary))
        else:
            parser.print_help()
        return

    harness = args.harness.lower()
    summary = _build_summary(harness, project_dir, state)

    if args.output_json:
        print(json.dumps(summary, indent=2))
        return

    if args.export:
        # Emit only the shell exports — caller does: eval $(sync-activate codex --export)
        print(_build_exports(summary))
        return

    # Default: print summary + env exports
    print(f"\n{'─' * 50}")
    print(f"  Context: {harness.upper()}")
    print(f"{'─' * 50}")
    print(_format_summary(summary))
    print()
    print("  Shell integration (eval to set env vars):")
    for line in _build_exports(summary).splitlines():
        print(f"    {line}")
    print()

    if args.open_config:
        _open_config(summary["config_path"])


if __name__ == "__main__":
    main()
