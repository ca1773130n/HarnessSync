---
description: Restore a target harness config to a previous backed-up state
---

List available sync backups and restore any target harness config to a previous state. HarnessSync automatically creates backups before each sync.

Usage: /sync-rollback [--list] [--target TARGET] [--backup NAME]

Options:
- --list: List all available backups for all targets
- --target TARGET: Target to restore (codex, gemini, opencode, cursor, etc.)
- --backup NAME: Specific backup to restore (default: most recent)

Examples:
- /sync-rollback --list
- /sync-rollback --target codex
- /sync-rollback --target gemini --backup AGENTS.md_20240115_143022

!PY=$(command -v python3 || command -v python) && [ -n "$PY" ] || { echo "Error: Python not found. Install Python 3 to use HarnessSync." >&2; exit 1; }; "$PY" ${CLAUDE_PLUGIN_ROOT}/src/commands/sync_rollback.py $ARGUMENTS
