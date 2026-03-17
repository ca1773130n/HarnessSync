from __future__ import annotations

"""
/sync-new-adapter slash command — Custom Adapter Scaffold Generator.

Generates a skeleton adapter from a template given a harness name and config
file format. Lowers the contribution bar from 'read source code' to
'fill in a template', growing the ecosystem without core team effort.

Usage:
    /sync-new-adapter --harness myharness [--name "My Harness"] [--format json]
    /sync-new-adapter --harness myharness --config-path .myharness/config.json
    /sync-new-adapter --harness myharness --dry-run

Options:
    --harness ID        Short harness identifier (e.g. myharness, my-ide)
    --name NAME         Human-readable name (default: title-case of --harness)
    --format FORMAT     Config format: markdown|json|yaml|toml|directory
    --config-path PATH  Override default config file path
    --dry-run           Preview generated files without writing them
    --output-dir DIR    Write files to this directory (default: current project)
"""

import argparse
import os
import shlex
import sys
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.adapter_scaffold import generate_adapter_scaffold


def main() -> None:
    """Entry point for /sync-new-adapter command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-new-adapter",
        description="Generate a skeleton adapter for a new harness",
    )
    parser.add_argument(
        "--harness", "-H", required=True,
        help="Short harness identifier (e.g. myharness, my-ide)",
    )
    parser.add_argument(
        "--name", "-n", default=None,
        help="Human-readable name (default: title-case of --harness)",
    )
    parser.add_argument(
        "--format", "-f", default="markdown",
        choices=["markdown", "json", "yaml", "toml", "directory"],
        help="Config file format (default: markdown)",
    )
    parser.add_argument(
        "--config-path", default=None,
        help="Override default config file path inside project dir",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview generated files without writing them",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Write files to this directory (default: current project root)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    output_dir: Path | None = None
    if not args.dry_run:
        output_dir = Path(args.output_dir).expanduser() if args.output_dir else Path(PLUGIN_ROOT)

    result = generate_adapter_scaffold(
        harness_id=args.harness,
        harness_name=args.name,
        config_format=args.format,
        config_path=args.config_path,
        output_dir=output_dir,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print("=== [dry-run] Generated adapter scaffold ===\n")
        print(f"Adapter:  {result.adapter_path}")
        print(f"Command:  {result.command_path}")
        print(f"Tests:    {result.test_path}")
        print()
        print("--- Adapter preview (first 40 lines) ---")
        for line in result.adapter_content.splitlines()[:40]:
            print(f"  {line}")
        print("  ...")
    else:
        print("Generated adapter scaffold:")
        print(f"  ✓ {result.adapter_path}")
        print(f"  ✓ {result.command_path}")
        print(f"  ✓ {result.test_path}")

    print()
    print("Next steps:")
    for step in result.next_steps:
        print(f"  {step}")


if __name__ == "__main__":
    main()
