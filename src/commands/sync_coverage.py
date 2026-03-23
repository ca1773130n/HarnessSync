from __future__ import annotations

"""
/sync-coverage slash command implementation.

Reads source config via SourceReader and checks each element (MCP servers,
skills, rules, env vars, permissions) against every adapter's declared
capability map. Outputs a per-harness table showing which config elements
will sync cleanly, which will be approximated, and which will be dropped.
"""

import json
import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.source_reader import SourceReader

# Per-harness capability map: section -> "full" | "partial" | "none"
# "full"    = synced with full fidelity
# "partial" = approximated (e.g. MCP servers written as JSON but not auto-launched)
# "none"    = not supported, element dropped
_CAPABILITIES: dict[str, dict[str, str]] = {
    "codex": {
        "rules":       "full",
        "skills":      "full",
        "agents":      "full",
        "commands":    "full",
        "mcp":         "partial",  # codex reads mcp.json but may not support all transports
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "partial",
        "permissions": "partial",
    },
    "gemini": {
        "rules":       "full",
        "skills":      "full",
        "agents":      "partial",
        "commands":    "none",
        "mcp":         "full",
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "none",
        "permissions": "none",
    },
    "opencode": {
        "rules":       "full",
        "skills":      "none",
        "agents":      "none",
        "commands":    "none",
        "mcp":         "full",
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "none",
        "permissions": "none",
    },
    "cursor": {
        "rules":       "full",
        "skills":      "partial",
        "agents":      "none",
        "commands":    "none",
        "mcp":         "full",
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "none",
        "permissions": "none",
    },
    "aider": {
        "rules":       "full",
        "skills":      "none",
        "agents":      "none",
        "commands":    "none",
        "mcp":         "none",
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "partial",
        "permissions": "none",
    },
    "windsurf": {
        "rules":       "full",
        "skills":      "partial",
        "agents":      "none",
        "commands":    "none",
        "mcp":         "full",
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "none",
        "permissions": "none",
    },
    "cline": {
        "rules":       "full",
        "skills":      "none",
        "agents":      "none",
        "commands":    "none",
        "mcp":         "full",
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "none",
        "permissions": "none",
    },
    "continue": {
        "rules":       "full",
        "skills":      "none",
        "agents":      "none",
        "commands":    "none",
        "mcp":         "partial",
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "none",
        "permissions": "none",
    },
    "zed": {
        "rules":       "full",
        "skills":      "none",
        "agents":      "none",
        "commands":    "none",
        "mcp":         "full",
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "none",
        "permissions": "none",
    },
    "neovim": {
        "rules":       "full",
        "skills":      "none",
        "agents":      "none",
        "commands":    "none",
        "mcp":         "partial",
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "none",
        "permissions": "none",
    },
    "vscode": {
        "rules":       "full",
        "skills":      "none",
        "agents":      "none",
        "commands":    "none",
        "mcp":         "full",
        "settings":    "partial",
        "hooks":       "none",
        "plugins":     "none",
        "env":         "none",
        "permissions": "none",
    },
}

_SYMBOLS = {"full": "✓", "partial": "~", "none": "✗"}
_LABELS  = {"full": "clean", "partial": "approx", "none": "dropped"}


def _source_sections(source_data: dict) -> dict[str, int]:
    """Return a mapping of section -> item count for sections that have content."""
    counts: dict[str, int] = {}
    for section in ("rules", "skills", "agents", "commands", "mcp", "settings", "hooks", "plugins"):
        val = source_data.get(section)
        if isinstance(val, dict):
            if val:
                counts[section] = len(val)
        elif isinstance(val, list):
            if val:
                counts[section] = len(val)

    # env vars and permissions from settings
    settings = source_data.get("settings") or {}
    if settings.get("env"):
        counts["env"] = len(settings["env"])
    if settings.get("permissions"):
        counts["permissions"] = len(settings.get("permissions", {}).get("allow", []))

    return counts


def _print_text_table(source_sections: dict[str, int], targets: list[str]) -> None:
    """Print a human-readable coverage matrix."""
    if not source_sections:
        print("No config elements found in source. Nothing to show.")
        return

    sections = sorted(source_sections.keys())
    col_w = max(len(t) for t in targets) + 2
    row_label_w = max(len(s) for s in sections) + 2

    # Header
    header = f"{'Section':<{row_label_w}} {'Items':>5}  " + "".join(f"{t:^{col_w}}" for t in targets)
    print(header)
    print("-" * len(header))

    for section in sections:
        count = source_sections[section]
        row = f"{section:<{row_label_w}} {count:>5}  "
        for target in targets:
            caps = _CAPABILITIES.get(target, {})
            level = caps.get(section, "none")
            sym = _SYMBOLS[level]
            row += f"{sym:^{col_w}}"
        print(row)

    print()
    print(f"  {_SYMBOLS['full']} = syncs cleanly   {_SYMBOLS['partial']} = approximated   {_SYMBOLS['none']} = dropped")


def main() -> None:
    """Entry point for /sync-coverage command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-coverage",
        description="Show portability coverage matrix for each harness",
    )
    parser.add_argument("--scope", default="all", choices=["user", "project", "all"])
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        metavar="TARGET",
        help="Limit output to a specific harness (e.g. codex)",
    )
    parser.add_argument(
        "--format",
        default="text",
        choices=["text", "json"],
    )
    parser.add_argument("--project-dir", type=str, default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    output_json = args.format == "json"

    try:
        reader = SourceReader(scope=args.scope, project_dir=project_dir)
        source_data = reader.discover_all()
    except Exception as e:
        if output_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error reading config: {e}", file=sys.stderr)
        sys.exit(2)

    source_sections = _source_sections(source_data)

    targets = sorted(_CAPABILITIES.keys())
    if args.target:
        tgt = args.target.lower()
        if tgt not in _CAPABILITIES:
            print(f"Unknown target '{tgt}'. Known: {', '.join(sorted(_CAPABILITIES))}", file=sys.stderr)
            sys.exit(1)
        targets = [tgt]

    if output_json:
        result: dict = {}
        for target in targets:
            caps = _CAPABILITIES[target]
            result[target] = {}
            for section, count in source_sections.items():
                level = caps.get(section, "none")
                result[target][section] = {"items": count, "coverage": level, "label": _LABELS[level]}
        print(json.dumps(result, indent=2))
        return

    print("HarnessSync Portability Coverage Matrix")
    print("=" * 50)
    print()
    _print_text_table(source_sections, targets)


if __name__ == "__main__":
    main()
