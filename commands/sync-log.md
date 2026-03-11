---
description: Show sync audit log — persistent history of every sync operation
---

Display the persistent sync audit log showing timestamp, what changed, and which targets were updated.

Usage: /sync-log [--tail N] [--clear]

Options:
- --tail N: Show only the last N log entries
- --clear: Clear the sync log (irreversible)

!PY=$(command -v python3 || command -v python) && [ -n "$PY" ] || { echo "Error: Python not found. Install Python 3 to use HarnessSync." >&2; exit 1; }; "$PY" ${CLAUDE_PLUGIN_ROOT}/src/commands/sync_log.py $ARGUMENTS
