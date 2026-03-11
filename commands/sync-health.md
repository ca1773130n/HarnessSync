---
description: Check harness installation, config health score, readiness checklist, and skill compatibility
---

Comprehensive health dashboard: harness installation status, config health score (completeness, portability, security, size), readiness checklist for each target, and skill compatibility analysis.

Usage: /sync-health [--score] [--readiness] [--skills] [--all]

Options:
- --score: Show config health score and recommendations
- --readiness: Show harness readiness checklist (prerequisites per target)
- --skills: Show skill compatibility report across targets
- --all: Show everything (default behavior)

!PY=$(command -v python3 || command -v python) && [ -n "$PY" ] || { echo "Error: Python not found. Install Python 3 to use HarnessSync." >&2; exit 1; }; "$PY" ${CLAUDE_PLUGIN_ROOT}/src/commands/sync_health.py $ARGUMENTS
