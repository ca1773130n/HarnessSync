---
description: Show HarnessSync status and drift detection for all targets
---

Show sync status, last sync time per target, and drift detection.

Usage: /sync-status [--account NAME] [--list-accounts]

Options:
- --account NAME: Show status for specific account
- --list-accounts: List all configured accounts with sync status

!(command -v python3 >/dev/null 2>&1 && python3 ${CLAUDE_PLUGIN_ROOT}/src/commands/sync_status.py $ARGUMENTS || python ${CLAUDE_PLUGIN_ROOT}/src/commands/sync_status.py $ARGUMENTS)
