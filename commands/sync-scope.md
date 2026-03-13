---
description: Visualize rule scope hierarchy and detect conflicts between global/project/subdirectory rules
---

Show which CLAUDE.md rules apply at each scope level (global, project, subdirectory) and highlight conflicts where the same rule name appears at multiple scopes.

Usage: /sync-scope [--project-dir DIR]

Options:
- --project-dir DIR: Override project directory

!PY=$(command -v python3 || command -v python) && [ -n "$PY" ] || { echo "Error: Python not found. Install Python 3 to use HarnessSync." >&2; exit 1; }; "$PY" ${CLAUDE_PLUGIN_ROOT}/src/commands/sync_scope.py $ARGUMENTS
