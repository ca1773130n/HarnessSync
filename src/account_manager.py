"""
Multi-account registry management with atomic persistence.

AccountManager handles CRUD operations for ~/.harnesssync/accounts.json,
enabling users to configure multiple Claude Code source directories
mapped to separate target CLI directories. Follows AWS CLI profiles
pattern for multi-account management.
"""

import json
import os
import re
import tempfile
from pathlib import Path


class AccountManager:
    """Manages account registry in ~/.harnesssync/accounts.json.

    Account registry schema:
    {
        "version": 1,
        "default_account": "personal",
        "accounts": {
            "personal": {
                "source": {"path": "/Users/john/.claude-personal", "scope": "user"},
                "targets": {"codex": "/Users/john/.codex-personal", ...}
            }
        }
    }
    """

    # Valid account name: alphanumeric, dash, underscore, non-empty
    _NAME_PATTERN = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$')

    def __init__(self, config_dir: Path = None):
        """Initialize AccountManager.

        Args:
            config_dir: Directory for accounts.json (default: ~/.harnesssync)
        """
        self.config_dir = config_dir or (Path.home() / ".harnesssync")
        self.accounts_file = self.config_dir / "accounts.json"
        self._accounts = self._load()

    def _load(self) -> dict:
        """Load accounts from JSON file."""
        if not self.accounts_file.exists():
            return {"version": 1, "default_account": None, "accounts": {}}

        try:
            with open(self.accounts_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"version": 1, "default_account": None, "accounts": {}}
            # Ensure required keys
            data.setdefault("version", 1)
            data.setdefault("default_account", None)
            data.setdefault("accounts", {})
            return data
        except (json.JSONDecodeError, OSError):
            return {"version": 1, "default_account": None, "accounts": {}}

    def _save(self) -> None:
        """Save accounts to JSON with atomic write (tempfile + os.replace)."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        temp_fd = None
        temp_path = None

        try:
            temp_fd = tempfile.NamedTemporaryFile(
                mode='w',
                dir=self.config_dir,
                suffix='.tmp',
                delete=False,
                encoding='utf-8'
            )
            temp_path = Path(temp_fd.name)

            json.dump(self._accounts, temp_fd, indent=2, ensure_ascii=False)
            temp_fd.write('\n')
            temp_fd.flush()
            os.fsync(temp_fd.fileno())
            temp_fd.close()

            os.replace(str(temp_path), str(self.accounts_file))

        except Exception:
            if temp_fd and not temp_fd.closed:
                temp_fd.close()
            if temp_path and temp_path.exists():
                temp_path.unlink()
            raise

    def _validate_name(self, name: str) -> None:
        """Validate account name format.

        Raises:
            ValueError: If name is invalid
        """
        if not name:
            raise ValueError("Account name must be non-empty")
        if not self._NAME_PATTERN.match(name):
            raise ValueError(
                f"Invalid account name '{name}': must be alphanumeric with "
                f"dashes/underscores, starting with alphanumeric character"
            )

    def validate_no_target_collision(self, name: str, targets: dict[str, Path]) -> list[str]:
        """Check for target path collisions with existing accounts.

        Args:
            name: Account name (excluded from collision check for updates)
            targets: Dict mapping CLI name -> target path

        Returns:
            List of collision error messages (empty = valid)
        """
        errors = []
        for acc_name, acc_data in self._accounts.get("accounts", {}).items():
            if acc_name == name:
                continue  # Skip self when updating
            existing_targets = acc_data.get("targets", {})
            for target_name, target_path in targets.items():
                if target_name in existing_targets:
                    existing_path = Path(existing_targets[target_name])
                    if existing_path == Path(target_path):
                        errors.append(
                            f"Target path collision: {target_name} path "
                            f"{target_path} already used by account '{acc_name}'"
                        )
        return errors

    def add_account(self, name: str, source_path: Path, targets: dict[str, Path]) -> None:
        """Add or update account configuration.

        Args:
            name: Account name (alphanumeric + dash + underscore)
            source_path: Path to Claude Code config directory
            targets: Dict mapping CLI name -> target directory path

        Raises:
            ValueError: If name invalid, source doesn't exist, or target collision
        """
        self._validate_name(name)

        if not source_path.is_dir():
            raise ValueError(f"Source path does not exist: {source_path}")

        # Check target collisions
        collisions = self.validate_no_target_collision(name, targets)
        if collisions:
            raise ValueError("; ".join(collisions))

        self._accounts["accounts"][name] = {
            "source": {
                "path": str(source_path),
                "scope": "user"
            },
            "targets": {k: str(v) for k, v in targets.items()}
        }

        # Auto-set default if first account
        if self._accounts["default_account"] is None:
            self._accounts["default_account"] = name

        self._save()

    def remove_account(self, name: str) -> bool:
        """Remove account by name.

        Args:
            name: Account name to remove

        Returns:
            True if account existed and was removed, False otherwise
        """
        if name not in self._accounts.get("accounts", {}):
            return False

        del self._accounts["accounts"][name]

        # Update default if removed was default
        if self._accounts.get("default_account") == name:
            remaining = list(self._accounts["accounts"].keys())
            self._accounts["default_account"] = remaining[0] if remaining else None

        self._save()
        return True

    def get_account(self, name: str) -> dict | None:
        """Get account configuration by name.

        Returns:
            Account config dict, or None if not found
        """
        return self._accounts.get("accounts", {}).get(name)

    def list_accounts(self) -> list[str]:
        """List all account names sorted alphabetically."""
        return sorted(self._accounts.get("accounts", {}).keys())

    def get_default_account(self) -> str | None:
        """Get default account name."""
        return self._accounts.get("default_account")

    def set_default_account(self, name: str) -> None:
        """Set default account.

        Raises:
            ValueError: If account name doesn't exist
        """
        if name not in self._accounts.get("accounts", {}):
            raise ValueError(f"Account '{name}' does not exist")
        self._accounts["default_account"] = name
        self._save()

    def has_accounts(self) -> bool:
        """Return True if any accounts are configured."""
        return len(self._accounts.get("accounts", {})) > 0
