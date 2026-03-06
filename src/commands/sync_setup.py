from __future__ import annotations

"""
/sync-setup slash command implementation.

Configure multi-account sync setup: discover, add, list, remove, show accounts.
"""

import os
import sys
import shlex
import argparse
import json

# Resolve project root for imports
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.account_manager import AccountManager
from src.account_discovery import auto_discover_accounts
from src.setup_wizard import SetupWizard


def main():
    """Entry point for /sync-setup command."""
    # Parse arguments from $ARGUMENTS
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-setup",
        description="Configure HarnessSync multi-account support"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_accounts",
        help="List all configured accounts"
    )
    parser.add_argument(
        "--remove",
        type=str,
        metavar="NAME",
        help="Remove account by name"
    )
    parser.add_argument(
        "--show",
        type=str,
        metavar="NAME",
        help="Show detailed account configuration"
    )
    parser.add_argument(
        "--config-file",
        type=str,
        metavar="PATH",
        help="Import accounts from JSON file (non-interactive)"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Auto-discover and configure accounts from home directory"
    )
    parser.add_argument(
        "--add",
        type=str,
        metavar="NAME",
        help="Add account non-interactively (use with --source)"
    )
    parser.add_argument(
        "--source",
        type=str,
        metavar="PATH",
        help="Source Claude Code config directory (use with --add)"
    )
    parser.add_argument(
        "--targets",
        type=str,
        metavar="CLI=PATH,...",
        help="Target paths as codex=/path,gemini=/path,opencode=/path (use with --add)"
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    try:
        wizard = SetupWizard()

        if args.list_accounts:
            wizard.run_list()
        elif args.remove:
            wizard.run_remove(args.remove)
        elif args.show:
            wizard.run_show(args.show)
        elif args.config_file:
            _import_config_file(args.config_file)
        elif args.add:
            _add_account_inline(args.add, args.source, args.targets)
        elif args.auto or not sys.stdin.isatty():
            _auto_setup()
        else:
            wizard.run_add_account()

    except KeyboardInterrupt:
        print("\nSetup cancelled.")

    except Exception as e:
        print(f"Setup error: {e}", file=sys.stderr)


def _auto_setup() -> None:
    """Auto-discover accounts by scanning home directory.

    Finds .claude* sources matched to .codex*/.gemini*/.opencode* targets
    by suffix, filtering out targets without auth credentials.
    """
    print("Scanning home directory for CLI accounts...")
    print()

    discovered = auto_discover_accounts()

    if not discovered:
        print("No matching accounts found.")
        print()
        print("HarnessSync looks for:")
        print("  Source:  ~/.claude, ~/.claude-<name>")
        print("  Targets: ~/.codex[-<name>], ~/.gemini[-<name>], ~/.opencode[-<name>]")
        print()
        print("Targets must have auth credentials (e.g. auth.json for Codex,")
        print("settings.json for Gemini) to be recognized.")
        return

    am = AccountManager()
    added = 0
    skipped = 0

    for account in discovered:
        name = account['name']
        source = account['source']
        targets = account['targets']

        # Check if already configured with same paths
        existing = am.get_account(name)
        if existing:
            existing_targets = existing.get('targets', {})
            existing_source = existing.get('source', {}).get('path', '')
            if (str(source) == existing_source and
                    all(str(targets.get(k)) == existing_targets.get(k) for k in targets)):
                print(f"  [{name}] already configured (unchanged)")
                skipped += 1
                continue

        target_list = ", ".join(f"{cli}" for cli in sorted(targets))
        print(f"  [{name}]")
        print(f"    source:  {source}")
        print(f"    targets: {target_list}")

        try:
            am.add_account(name, source, targets)
            print(f"    -> configured")
            added += 1
        except ValueError as e:
            print(f"    -> skipped: {e}")
            skipped += 1

    print()
    if added:
        print(f"Configured {added} account(s).", end="")
        if skipped:
            print(f" ({skipped} unchanged)", end="")
        print()
    else:
        print(f"All {skipped} account(s) already up to date.")


def _add_account_inline(name: str, source: str, targets_str: str) -> None:
    """Add account non-interactively via CLI args.

    Args:
        name: Account name
        source: Path to Claude Code config directory
        targets_str: Comma-separated CLI=PATH pairs (e.g. codex=~/.codex,gemini=~/.gemini)
    """
    if not source:
        print("Error: --source is required with --add", file=sys.stderr)
        return

    source_path = Path(source).expanduser()

    # Parse targets
    if targets_str:
        targets = {}
        for pair in targets_str.split(","):
            pair = pair.strip()
            if "=" not in pair:
                print(f"Error: Invalid target format '{pair}'. Use CLI=PATH", file=sys.stderr)
                return
            cli, path = pair.split("=", 1)
            targets[cli.strip()] = Path(path.strip()).expanduser()
    else:
        # Default target paths
        suffix = "" if name == "default" else f"-{name}"
        targets = {
            cli: Path.home() / f".{cli}{suffix}"
            for cli in ["codex", "gemini", "opencode"]
        }

    am = AccountManager()
    try:
        am.add_account(name, source_path, targets)
        print(f"Account '{name}' configured successfully!")
        print(f"  Source:  {source_path}")
        for cli, path in sorted(targets.items()):
            print(f"  Target:  {cli} -> {path}")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)


def _import_config_file(config_path: str) -> None:
    """Import accounts from a JSON config file (non-interactive mode).

    Args:
        config_path: Path to accounts.json file to import
    """
    path = Path(config_path).expanduser()
    if not path.exists():
        print(f"Error: Config file not found: {path}", file=sys.stderr)
        return

    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error reading config file: {e}", file=sys.stderr)
        return

    accounts = data.get("accounts", {})
    if not accounts:
        print("No accounts found in config file.")
        return

    am = AccountManager()
    imported = 0

    for name, config in accounts.items():
        source_path = Path(config.get("source", {}).get("path", ""))
        targets = {k: Path(v) for k, v in config.get("targets", {}).items()}

        try:
            am.add_account(name, source_path, targets)
            print(f"  Imported account: {name}")
            imported += 1
        except ValueError as e:
            print(f"  Skipped '{name}': {e}", file=sys.stderr)

    print(f"\nImported {imported} account(s).")


if __name__ == "__main__":
    main()
