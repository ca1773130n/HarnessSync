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
        description="List, install, save, load, and delete named sync profiles.",
    )
    sub = parser.add_subparsers(dest="action")

    # list sub-command
    sub.add_parser("list", help="Show all available presets and saved profiles")

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

    # save sub-command: persist current flags as a named profile
    save_parser = sub.add_parser("save", help="Save a new named profile with explicit options")
    save_parser.add_argument("name", help="Profile name (alphanumeric, hyphens, underscores)")
    save_parser.add_argument("--scope", choices=["user", "project", "all"], default="all")
    save_parser.add_argument("--only", type=str, default=None,
                             help="Comma-separated sections to sync (rules,skills,mcp,...)")
    save_parser.add_argument("--skip", type=str, default=None,
                             help="Comma-separated sections to skip")
    save_parser.add_argument("--targets", type=str, default=None,
                             help="Comma-separated harness targets (cursor,gemini,...)")
    save_parser.add_argument("--description", type=str, default="",
                             help="Human-readable description for this profile")

    # load sub-command: display a profile's settings
    load_parser = sub.add_parser("load", help="Show settings for a saved profile")
    load_parser.add_argument("name", help="Profile name to display")

    # delete sub-command
    delete_parser = sub.add_parser("delete", help="Delete a saved profile")
    delete_parser.add_argument("name", help="Profile name to delete")

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    mgr = ProfileManager()

    # Default action is list
    if args.action is None or args.action == "list":
        print(list_presets())
        saved = mgr.list_profiles()
        if saved:
            print()
            print("Saved profiles:")
            for profile_name in saved:
                cfg = mgr.get_profile(profile_name) or {}
                desc = cfg.get("description", "")
                suffix = f" — {desc}" if desc else ""
                print(f"  {profile_name}{suffix}")
        return

    if args.action == "install":
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
        return

    if args.action == "save":
        config: dict = {"scope": args.scope}
        if args.description:
            config["description"] = args.description
        if args.only:
            config["only_sections"] = [s.strip() for s in args.only.split(",") if s.strip()]
        if args.skip:
            config["skip_sections"] = [s.strip() for s in args.skip.split(",") if s.strip()]
        if args.targets:
            config["targets"] = [t.strip() for t in args.targets.split(",") if t.strip()]
        try:
            mgr.save_profile(args.name, config)
            print(f'Profile "{args.name}" saved. Activate with: /sync --profile {args.name}')
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if args.action == "load":
        cfg = mgr.get_profile(args.name)
        if cfg is None:
            print(f'Profile "{args.name}" not found.', file=sys.stderr)
            sys.exit(1)
        import json
        print(f"Profile: {args.name}")
        print(json.dumps(cfg, indent=2))
        return

    if args.action == "delete":
        deleted = mgr.delete_profile(args.name)
        if deleted:
            print(f'Profile "{args.name}" deleted.')
        else:
            print(f'Profile "{args.name}" not found.', file=sys.stderr)
            sys.exit(1)
        return


if __name__ == "__main__":
    main()
