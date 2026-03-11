---
description: Sync Claude Code config to all targets (Codex, Gemini, OpenCode, Cursor, Aider, Windsurf)
---

Sync your Claude Code configuration to all configured targets.

Usage: /sync [--scope user|project|all] [--dry-run] [--allow-secrets] [--account NAME] [--only SECTIONS] [--skip SECTIONS]

Options:
- --scope: Sync scope (user, project, or all). Default: all
- --dry-run: Preview changes without writing files
- --allow-secrets: Allow sync even when secrets detected in env vars
- --account NAME: Sync specific account only (omit to sync all accounts)
- --only SECTIONS: Sync only specific sections (comma-separated: rules,skills,agents,commands,mcp,settings)
- --skip SECTIONS: Skip specific sections (comma-separated: rules,skills,agents,commands,mcp,settings)

Examples:
- /sync --only mcp,rules     # Only sync MCP servers and rules
- /sync --skip rules          # Sync everything except rules

!PY=$(command -v python3 || command -v python) && [ -n "$PY" ] || { echo "Error: Python not found. Install Python 3 to use HarnessSync." >&2; exit 1; }; "$PY" ${CLAUDE_PLUGIN_ROOT}/src/commands/sync.py $ARGUMENTS
