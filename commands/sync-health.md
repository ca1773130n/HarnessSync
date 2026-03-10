---
description: Check harness installation, version, and config health
---

Check whether each target harness is installed, authenticated, and functional.
Shows version info, detected capabilities, and known compatibility issues.

Usage: /sync-health

!PY=$(command -v python3 || command -v python) && [ -n "$PY" ] || { echo "Error: Python not found. Install Python 3 to use HarnessSync." >&2; exit 1; }; "$PY" ${CLAUDE_PLUGIN_ROOT}/src/commands/sync_health.py $ARGUMENTS
