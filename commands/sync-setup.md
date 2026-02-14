---
description: Configure multi-account sync setup (discover, add, remove accounts)
---

Configure HarnessSync multi-account support.

Usage: /sync-setup [--list] [--remove NAME] [--show NAME] [--config-file PATH]

Default (no args): Run interactive setup wizard to add a new account.

Options:
- --list: List all configured accounts
- --remove NAME: Remove account configuration
- --show NAME: Show detailed account configuration
- --config-file PATH: Import accounts from JSON file (non-interactive)

!python ${CLAUDE_PLUGIN_ROOT}/src/commands/sync_setup.py $ARGUMENTS
