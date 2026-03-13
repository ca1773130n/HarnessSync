from __future__ import annotations

"""
/sync-preset slash command — Browse and install sync profile presets.

Lists available presets or installs one as a named profile.

Usage:
    /sync-preset                          # list all presets (default)
    /sync-preset list                     # list all presets
    /sync-preset install work             # install the "work" preset
    /sync-preset install oss --name my-oss  # install "oss" as "my-oss"
    /sync-preset install work --no-overwrite  # skip if profile exists
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.profile_manager import (
    PRESET_PROFILES,
    ProfileManager,
    install_preset,
    list_presets,
)


def main() -> None:
    """Entry point for /sync-preset command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-preset",
        description="List and install named sync profile presets.",
    )
    sub = parser.add_subparsers(dest="action")

    # list sub-command
    sub.add_parser("list", help="Show all available presets with descriptions")

    # install sub-command
    install_parser = sub.add_parser("install", help="Install a preset as a named profile")
    install_parser.add_argument(
        "preset",
        help=f"Preset name ({', '.join(sorted(PRESET_PROFILES))})",
    )
    install_parser.add_argument(
        "--name",
        default=None,
        help="Save the preset under a custom profile name",
    )
    install_parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="Don't overwrite if a profile with the same name already exists",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    # Default action is list
    if args.action is None or args.action == "list":
        print(list_presets())
        return

    # install action
    mgr = ProfileManager()
    try:
        saved_name = install_preset(
            mgr,
            args.preset,
            profile_name=args.name,
            overwrite=not args.no_overwrite,
        )
        print(f'Preset "{args.preset}" installed as profile "{saved_name}".')
    except (KeyError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
