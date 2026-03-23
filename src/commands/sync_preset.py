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

    # env-profile sub-command: manage per-harness env var overrides within a profile
    env_sub = sub.add_parser("env-profile", help="Manage per-harness env var overrides in a profile")
    env_sub_action = env_sub.add_subparsers(dest="env_action")

    # env-profile list [NAME]
    env_list_parser = env_sub_action.add_parser("list", help="List env var overrides for a profile")
    env_list_parser.add_argument("name", nargs="?", default=None,
                                 help="Profile name (omit to list all profiles with env vars)")

    # env-profile set NAME TARGET KEY=VALUE [KEY=VALUE ...]
    env_set_parser = env_sub_action.add_parser(
        "set", help="Set env var overrides for a harness target in a profile"
    )
    env_set_parser.add_argument("name", help="Profile name")
    env_set_parser.add_argument("target", help="Harness target (e.g. codex, gemini)")
    env_set_parser.add_argument(
        "assignments", nargs="+", metavar="KEY=VALUE",
        help="Environment variable assignments (e.g. OPENAI_API_KEY=sk-...)",
    )

    # env-profile unset NAME TARGET KEY [KEY ...]
    env_unset_parser = env_sub_action.add_parser(
        "unset", help="Remove env var overrides from a profile target"
    )
    env_unset_parser.add_argument("name", help="Profile name")
    env_unset_parser.add_argument("target", help="Harness target")
    env_unset_parser.add_argument("keys", nargs="+", metavar="KEY",
                                  help="Env var names to remove")

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

    if args.action == "env-profile":
        _handle_env_profile(mgr, args)
        return


def _handle_env_profile(mgr: "ProfileManager", args) -> None:
    """Handle the env-profile sub-commands."""
    import json

    env_action = getattr(args, "env_action", None)

    if env_action is None or env_action == "list":
        # List env vars for a specific profile, or all profiles that have env_vars
        profile_name = getattr(args, "name", None)
        if profile_name:
            cfg = mgr.get_profile(profile_name)
            if cfg is None:
                print(f'Profile "{profile_name}" not found.', file=sys.stderr)
                sys.exit(1)
            env_vars = cfg.get("env_vars", {})
            if not env_vars:
                print(f'Profile "{profile_name}" has no env var overrides.')
            else:
                print(f'Profile "{profile_name}" env var overrides:')
                for target, vars_dict in sorted(env_vars.items()):
                    print(f"  {target}:")
                    for k, v in sorted(vars_dict.items()):
                        # Mask secrets: show first 4 chars + ***
                        masked = str(v)[:4] + "***" if len(str(v)) > 4 else "***"
                        print(f"    {k} = {masked}")
        else:
            # List all profiles that have env_vars
            found_any = False
            for pname in mgr.list_profiles():
                cfg = mgr.get_profile(pname) or {}
                if cfg.get("env_vars"):
                    if not found_any:
                        print("Profiles with env var overrides:")
                        found_any = True
                    targets = sorted(cfg["env_vars"].keys())
                    print(f"  {pname}: targets={', '.join(targets)}")
            if not found_any:
                print("No profiles have env var overrides configured.")
                print("Use: /sync-preset env-profile set <profile> <target> KEY=VALUE")
        return

    if env_action == "set":
        cfg = mgr.get_profile(args.name)
        if cfg is None:
            # Auto-create the profile if it doesn't exist
            cfg = {"description": f"Auto-created for env-profile set"}
            print(f'Profile "{args.name}" not found — creating it.')

        env_vars = cfg.get("env_vars", {})
        if not isinstance(env_vars, dict):
            env_vars = {}

        target_vars = dict(env_vars.get(args.target.lower(), {}))
        errors: list[str] = []
        for assignment in args.assignments:
            if "=" not in assignment:
                errors.append(f"  Invalid assignment (expected KEY=VALUE): {assignment!r}")
                continue
            k, _, v = assignment.partition("=")
            k = k.strip()
            if not k:
                errors.append(f"  Empty key in assignment: {assignment!r}")
                continue
            target_vars[k] = v

        if errors:
            for err in errors:
                print(err, file=sys.stderr)
            if not target_vars:
                sys.exit(1)

        env_vars[args.target.lower()] = target_vars
        cfg["env_vars"] = env_vars

        try:
            mgr.save_profile(args.name, cfg)
            print(f'Saved {len(args.assignments)} env var(s) for "{args.target}" in profile "{args.name}".')
            print(f'Activate with: /sync --profile {args.name}')
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if env_action == "unset":
        cfg = mgr.get_profile(args.name)
        if cfg is None:
            print(f'Profile "{args.name}" not found.', file=sys.stderr)
            sys.exit(1)

        env_vars = cfg.get("env_vars", {})
        target_vars = dict(env_vars.get(args.target.lower(), {}))
        removed: list[str] = []
        for key in args.keys:
            if key in target_vars:
                del target_vars[key]
                removed.append(key)

        if not removed:
            print(f'None of the specified keys found in "{args.name}" / "{args.target}".')
            return

        if target_vars:
            env_vars[args.target.lower()] = target_vars
        else:
            env_vars.pop(args.target.lower(), None)

        cfg["env_vars"] = env_vars
        try:
            mgr.save_profile(args.name, cfg)
            print(f'Removed env var(s) {removed} from "{args.target}" in profile "{args.name}".')
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    # Unknown env_action
    print(f"Unknown env-profile action: {env_action!r}. Use list, set, or unset.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
