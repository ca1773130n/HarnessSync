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
        else:
            # Default: run interactive wizard
            wizard.run_add_account()

    except KeyboardInterrupt:
        print("\nSetup cancelled.")

    except Exception as e:
        print(f"Setup error: {e}", file=sys.stderr)


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
