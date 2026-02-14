"""
Interactive setup wizard for multi-account configuration.

Guides users through discovering Claude Code config directories,
naming accounts, and configuring target CLI paths. Follows
git config / poetry init / AWS CLI configure patterns.
"""

import sys
from pathlib import Path

from src.account_manager import AccountManager
from src.account_discovery import discover_claude_configs, validate_claude_config, discover_target_configs


class SetupWizard:
    """Interactive setup wizard for multi-account configuration."""

    # Supported target CLIs
    TARGET_CLIS = ['codex', 'gemini', 'opencode']

    def __init__(self, account_manager: AccountManager = None, config_dir: Path = None):
        """Initialize SetupWizard.

        Args:
            account_manager: AccountManager instance (created if not provided)
            config_dir: Config directory for AccountManager
        """
        self.account_manager = account_manager or AccountManager(config_dir=config_dir)

    def run_interactive(self) -> dict | None:
        """Run full interactive setup wizard.

        Returns:
            Account config dict, or None if cancelled

        Raises:
            SystemExit: If not running in interactive terminal
        """
        if not sys.stdin.isatty():
            print("Error: Interactive setup requires TTY. "
                  "Use --config-file for automation.", file=sys.stderr)
            return None

        print("HarnessSync Multi-Account Setup")
        print("=" * 60)

        return self._run_wizard_flow()

    def run_add_account(self) -> dict | None:
        """Add a new account (shorter header if accounts already exist).

        Returns:
            Account config dict, or None if cancelled
        """
        if not sys.stdin.isatty():
            print("Error: Interactive setup requires TTY. "
                  "Use --config-file for automation.", file=sys.stderr)
            return None

        if self.account_manager.has_accounts():
            print("HarnessSync — Add Account")
            print("-" * 40)
        else:
            print("HarnessSync Multi-Account Setup")
            print("=" * 60)

        return self._run_wizard_flow()

    def _run_wizard_flow(self) -> dict | None:
        """Core wizard flow shared by run_interactive and run_add_account."""
        # Step 1: Discovery
        print("\n[1/4] Discovering Claude Code configurations...")
        discovered = discover_claude_configs(max_depth=2)
        valid_configs = [p for p in discovered if validate_claude_config(p)]

        if valid_configs:
            print(f"Found {len(valid_configs)} configuration(s):")
            for i, path in enumerate(valid_configs, 1):
                print(f"  {i}. {path}")
        else:
            print("No configurations found automatically.")

        # Step 2: Source selection
        print("\n[2/4] Select source configuration:")
        source_path = self._prompt_source_path(valid_configs)
        if source_path is None:
            print("Setup cancelled.")
            return None

        # Step 3: Account naming
        print("\n[3/4] Account configuration:")
        suggested = self._suggest_account_name(source_path)
        account_name = self._prompt_account_name(suggested)
        if account_name is None:
            print("Setup cancelled.")
            return None

        # Check for existing account
        existing = self.account_manager.get_account(account_name)
        if existing:
            overwrite = input(f"Account '{account_name}' already exists. Overwrite? [y/N]: ").strip().lower()
            if overwrite != 'y':
                print("Setup cancelled.")
                return None

        # Step 4: Target directories
        print(f"\n[4/4] Target CLI directories for '{account_name}':")
        targets = self._prompt_target_paths(account_name)
        if targets is None:
            print("Setup cancelled.")
            return None

        # Confirmation
        print("\n" + "=" * 60)
        print("Configuration summary:")
        print(f"  Account: {account_name}")
        print(f"  Source:  {source_path}")
        print(f"  Targets:")
        for name, path in sorted(targets.items()):
            print(f"    - {name}: {path}")

        confirm = input("\nSave configuration? [Y/n]: ").strip().lower()
        if confirm and confirm != 'y':
            print("Setup cancelled.")
            return None

        # Save
        try:
            self.account_manager.add_account(account_name, source_path, targets)
            print(f"\nAccount '{account_name}' configured successfully!")
            print(f"Config saved to: {self.account_manager.accounts_file}")
        except ValueError as e:
            print(f"\nError: {e}", file=sys.stderr)
            return None

        return {
            "name": account_name,
            "source": str(source_path),
            "targets": {k: str(v) for k, v in targets.items()}
        }

    def _prompt_source_path(self, discovered: list[Path]) -> Path | None:
        """Prompt user to select source path."""
        if discovered:
            choice = input(f"Enter number (1-{len(discovered)}) or custom path: ").strip()
            if not choice:
                return None
            if choice.isdigit() and 1 <= int(choice) <= len(discovered):
                return discovered[int(choice) - 1]
            source = Path(choice).expanduser()
        else:
            raw = input("Enter path to Claude Code config directory: ").strip()
            if not raw:
                return None
            source = Path(raw).expanduser()

        if not source.is_dir():
            print(f"Error: Directory does not exist: {source}", file=sys.stderr)
            return None

        return source

    def _prompt_account_name(self, suggested: str) -> str | None:
        """Prompt for account name with validation."""
        prompt = f"Account name [{suggested}]: " if suggested else "Account name: "

        for _ in range(3):  # Max 3 retries
            raw = input(prompt).strip()
            name = raw if raw else suggested

            if not name:
                print("Error: Account name is required.")
                continue

            try:
                self.account_manager._validate_name(name)
                return name
            except ValueError as e:
                print(f"Error: {e}")

        print("Too many invalid attempts.")
        return None

    def _prompt_target_paths(self, account_name: str) -> dict[str, Path] | None:
        """Prompt for target CLI directory paths."""
        # Discover existing targets for suggestions
        existing_targets = discover_target_configs()

        targets = {}
        for cli in self.TARGET_CLIS:
            if account_name == 'default':
                default_path = Path.home() / f".{cli}"
            else:
                default_path = Path.home() / f".{cli}-{account_name}"

            # Show existing targets if any
            existing = existing_targets.get(cli, [])
            if existing:
                existing_str = ", ".join(str(p) for p in existing[:3])
                print(f"  (existing {cli} dirs: {existing_str})")

            raw = input(f"  {cli} path [{default_path}]: ").strip()
            target_path = Path(raw).expanduser() if raw else default_path
            targets[cli] = target_path

        # Validate no collisions
        collisions = self.account_manager.validate_no_target_collision(account_name, targets)
        if collisions:
            for msg in collisions:
                print(f"Error: {msg}", file=sys.stderr)
            return None

        return targets

    def run_list(self) -> None:
        """List all configured accounts."""
        accounts = self.account_manager.list_accounts()
        if not accounts:
            print("No accounts configured. Run /sync-setup to add one.")
            return

        default = self.account_manager.get_default_account()

        print("Configured Accounts")
        print("=" * 60)
        print(f"{'Account':<15}| {'Source':<30}| {'Targets':>7} | {'Default'}")
        print("-" * 15 + "+" + "-" * 30 + "+" + "-" * 9 + "+" + "-" * 8)

        for name in accounts:
            acc = self.account_manager.get_account(name)
            source = acc.get("source", {}).get("path", "?")
            # Shorten source path for display
            if len(source) > 28:
                source = "..." + source[-25:]
            target_count = len(acc.get("targets", {}))
            is_default = "*" if name == default else ""

            print(f"{name:<15}| {source:<30}| {target_count:>7} | {is_default}")

    def run_show(self, account_name: str) -> bool:
        """Show detailed account configuration.

        Returns:
            True if account found, False otherwise
        """
        acc = self.account_manager.get_account(account_name)
        if not acc:
            print(f"Account '{account_name}' not found.")
            return False

        default = self.account_manager.get_default_account()

        print(f"Account: {account_name}" + (" (default)" if account_name == default else ""))
        print(f"Source: {acc['source']['path']}")
        print(f"Scope: {acc['source'].get('scope', 'user')}")
        print(f"Targets:")
        for cli, path in sorted(acc.get("targets", {}).items()):
            exists = Path(path).exists()
            status = "" if exists else " (not created yet)"
            print(f"  - {cli}: {path}{status}")

        return True

    def run_remove(self, account_name: str) -> bool:
        """Remove an account with confirmation.

        Returns:
            True if removed, False otherwise
        """
        acc = self.account_manager.get_account(account_name)
        if not acc:
            print(f"Account '{account_name}' not found.")
            return False

        if sys.stdin.isatty():
            confirm = input(f"Remove account '{account_name}'? This cannot be undone. [y/N]: ").strip().lower()
            if confirm != 'y':
                print("Removal cancelled.")
                return False

        result = self.account_manager.remove_account(account_name)
        if result:
            print(f"Account '{account_name}' removed.")
        return result

    @staticmethod
    def _suggest_account_name(source_path: Path) -> str:
        """Derive account name from .claude* path.

        .claude -> "default"
        .claude-work -> "work"
        .claude-personal1 -> "personal1"
        """
        name = source_path.name
        if name == '.claude':
            return 'default'

        # Strip ".claude" prefix and leading dash
        suffix = name.removeprefix('.claude').lstrip('-')
        return suffix if suffix else 'default'
