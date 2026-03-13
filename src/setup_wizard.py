from __future__ import annotations

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

    def run_guided(self, project_dir: Path | None = None) -> dict | None:
        """Run the guided first-sync onboarding wizard.

        Auto-detects installed harnesses, lets the user pick which sections
        to sync, and writes an initial .harnesssync config — reducing
        time-to-first-sync from 30+ minutes to under 2.

        Unlike run_interactive() which focuses on multi-account setup, this
        wizard is for first-time users who want a working sync config now.

        Args:
            project_dir: Project root to write .harnesssync to. Uses cwd if None.

        Returns:
            Generated .harnesssync config dict, or None if cancelled.
        """
        import shutil
        import json
        from src.harness_readiness import HarnessReadinessChecker

        if not sys.stdin.isatty():
            print("Error: Guided setup requires interactive terminal.", file=sys.stderr)
            return None

        cwd = project_dir or Path.cwd()

        print("HarnessSync — Guided First-Sync Setup")
        print("=" * 60)
        print("This wizard detects installed AI harnesses and configures")
        print("your sync settings. Takes about 2 minutes.")
        print()

        # Step 1: Detect installed harnesses
        print("[1/4] Detecting installed AI harnesses...")
        all_targets = ["codex", "gemini", "opencode", "cursor", "aider", "windsurf",
                       "cline", "continue", "zed", "neovim"]
        installed_map = self.detect_installed_harnesses(include_versions=True)
        detected: list[str] = []
        not_found: list[str] = []
        for target in all_targets:
            info = installed_map.get(target)
            if info and info["installed"]:
                detected.append(target)
                version_str = f" v{info['version']}" if info.get("version") else ""
                method = info.get("detection_method", "")
                method_note = f" ({method})" if method and method != "cli" else ""
                print(f"  ✓ {target}{version_str}{method_note}")
            else:
                not_found.append(target)
                print(f"  ✗ {target} (not detected)")

        if not detected:
            print("\nNo harnesses detected. Install at least one harness and re-run.")
            return None

        print()

        # Step 2: Confirm targets to sync
        print("[2/4] Which harnesses should receive synced config?")
        print(f"  Detected: {', '.join(detected)}")
        raw_targets = input(
            f"  Enter targets to sync [{', '.join(detected)}]: "
        ).strip()
        chosen_targets = (
            [t.strip() for t in raw_targets.split(",") if t.strip() in all_targets]
            if raw_targets
            else detected
        )
        if not chosen_targets:
            print("No valid targets selected. Setup cancelled.")
            return None
        print(f"  Syncing to: {', '.join(chosen_targets)}")
        print()

        # Step 3: Section selection
        print("[3/4] Which config sections should be synced?")
        all_sections = ["rules", "skills", "agents", "commands", "mcp", "settings"]
        section_descriptions = {
            "rules": "CLAUDE.md rules and instructions",
            "skills": "Claude Code skills (slash command prompts)",
            "agents": "Sub-agent configurations",
            "commands": "Custom slash commands",
            "mcp": "MCP server configurations",
            "settings": "Model and permission settings",
        }
        for s in all_sections:
            print(f"  {s:<10} — {section_descriptions[s]}")
        raw_sections = input(
            f"\n  Enter sections to sync (all to include all) [all]: "
        ).strip()
        if not raw_sections or raw_sections.lower() == "all":
            chosen_sections: list[str] = []  # Empty = sync all
        else:
            chosen_sections = [
                s.strip() for s in raw_sections.split(",")
                if s.strip() in all_sections
            ]
        display_sections = ", ".join(chosen_sections) if chosen_sections else "all"
        print(f"  Syncing sections: {display_sections}")
        print()

        # Step 4: Preview diff and confirm
        print("[4/4] Configuration preview")
        config: dict = {}
        if len(chosen_targets) < len(all_targets):
            config["only_targets"] = chosen_targets
        if chosen_sections:
            config["only_sections"] = chosen_sections
        config["_guided_setup"] = True

        harnesssync_path = cwd / ".harnesssync"

        # Build the merged config to preview
        existing: dict = {}
        if harnesssync_path.exists():
            try:
                existing = json.loads(harnesssync_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        merged_preview = dict(existing)
        merged_preview.update({k: v for k, v in config.items() if not k.startswith("_")})

        # Show the diff between current and proposed config
        import difflib
        old_text = json.dumps(existing, indent=2) if existing else "(no existing config)"
        new_text = json.dumps(merged_preview, indent=2)

        print(f"  Config file: {harnesssync_path}")
        print()
        if existing:
            diff_lines = list(difflib.unified_diff(
                old_text.splitlines(),
                new_text.splitlines(),
                fromfile="current .harnesssync",
                tofile="proposed .harnesssync",
                lineterm="",
            ))
            if diff_lines:
                print("  Changes to .harnesssync:")
                for line in diff_lines:
                    prefix = "  "
                    if line.startswith("+") and not line.startswith("+++"):
                        prefix = "+ "
                    elif line.startswith("-") and not line.startswith("---"):
                        prefix = "- "
                    print(f"    {prefix}{line}")
            else:
                print("  No changes to .harnesssync (already up to date).")
        else:
            print("  New .harnesssync will be created:")
            for line in new_text.splitlines():
                print(f"    {line}")

        # Explain each mapping decision
        print()
        print("  Mapping decisions:")
        for target in chosen_targets:
            syncs = display_sections if display_sections != "all" else "all sections"
            print(f"    · {target}: will receive {syncs}")
        for target in not_found:
            print(f"    · {target}: skipped (not detected on this machine)")
        print()

        confirm = input("Write configuration and run first sync? [Y/n]: ").strip().lower()
        if confirm and confirm != "y":
            print("Setup cancelled.")
            return None

        # Write merged config
        harnesssync_path.write_text(
            json.dumps(merged_preview, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\n.harnesssync written to {harnesssync_path}")
        print("Run /sync to perform your first sync.")
        return config

    @staticmethod
    def detect_installed_harnesses(include_versions: bool = True) -> dict[str, dict]:
        """Detect which AI harnesses are installed on this machine.

        Combines CLI binary detection with application manifest inspection to
        identify installed harnesses and their versions. Used by the first-run
        guided wizard and /sync-status to show which harnesses are available.

        Args:
            include_versions: If True, attempt to detect installed version strings.
                              Set to False for faster detection when versions aren't needed.

        Returns:
            Dict mapping harness name -> {
                "installed": bool,
                "version": str | None,
                "config_dir": str | None,   # detected config directory
                "detection_method": str,     # "cli" | "app-bundle" | "config-dir"
            }
        """
        import shutil

        _CLI_BINARIES: dict[str, str] = {
            "codex":    "codex",
            "gemini":   "gemini",
            "opencode": "opencode",
            "aider":    "aider",
            "cursor":   "cursor",
            "windsurf": "windsurf",
            "cline":    "code",      # VS Code hosts Cline
            "continue": "code",      # VS Code hosts Continue
            "zed":      "zed",
            "neovim":   "nvim",
        }
        _CONFIG_DIR_FALLBACKS: dict[str, Path] = {
            "codex":    Path.home() / ".codex",
            "gemini":   Path.home() / ".gemini",
            "opencode": Path.home() / ".config" / "opencode",
            "cursor":   Path.home() / ".cursor",
            "aider":    Path.home() / ".aider",
            "windsurf": Path.home() / ".codeium" / "windsurf",
            "cline":    Path.home() / ".vscode" / "extensions",
            "continue": Path.home() / ".continue",
            "zed":      (
                Path.home() / "Library" / "Application Support" / "Zed"
                if (Path.home() / "Library").exists()
                else Path.home() / ".config" / "zed"
            ),
        }

        results: dict[str, dict] = {}

        for harness, cli in _CLI_BINARIES.items():
            installed = False
            version: str | None = None
            config_dir: str | None = None
            detection_method = "none"

            # Method 1: CLI binary on PATH
            if shutil.which(cli):
                installed = True
                detection_method = "cli"

            # Method 2: Config directory exists (harness installed but not on PATH)
            if not installed:
                fallback = _CONFIG_DIR_FALLBACKS.get(harness)
                if fallback and fallback.exists():
                    installed = True
                    detection_method = "config-dir"

            if installed:
                config_dir_path = _CONFIG_DIR_FALLBACKS.get(harness)
                if config_dir_path and config_dir_path.exists():
                    config_dir = str(config_dir_path)

                if include_versions:
                    try:
                        from src.harness_version_compat import detect_installed_version
                        version = detect_installed_version(harness)
                    except Exception:
                        pass

                results[harness] = {
                    "installed": True,
                    "version": version,
                    "config_dir": config_dir,
                    "detection_method": detection_method,
                }

        return results

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
