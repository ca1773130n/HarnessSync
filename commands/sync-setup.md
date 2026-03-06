---
description: Configure multi-account sync setup (discover, add, remove accounts)
---

Configure HarnessSync multi-account support.

Usage: /sync-setup [--add NAME --source PATH [--targets CLI=PATH,...]] [--list] [--remove NAME] [--show NAME] [--config-file PATH]

Default (no args): Run interactive setup wizard (TTY required), or show usage hint.

Options:
- --add NAME --source PATH: Add account non-interactively
- --targets CLI=PATH,...: Target paths (e.g. codex=~/.codex,gemini=~/.gemini). Defaults to ~/.{cli} or ~/.{cli}-{name}
- --list: List all configured accounts
- --remove NAME: Remove account configuration
- --show NAME: Show detailed account configuration
- --config-file PATH: Import accounts from JSON file (non-interactive)

!PY=$(command -v python3 || command -v python) && [ -n "$PY" ] || { echo "Error: Python not found. Install Python 3 to use HarnessSync." >&2; exit 1; }; "$PY" ${CLAUDE_PLUGIN_ROOT}/src/commands/sync_setup.py $ARGUMENTS
