---
description: Sync Claude Code config to all targets (Codex, Gemini, OpenCode)
---

Sync your Claude Code configuration to all configured targets.

Usage: /sync [--scope user|project|all] [--dry-run] [--allow-secrets] [--account NAME]

Options:
- --scope: Sync scope (user, project, or all). Default: all
- --dry-run: Preview changes without writing files
- --allow-secrets: Allow sync even when secrets detected in env vars
- --account NAME: Sync specific account only (omit to sync all accounts)

!(command -v python3 >/dev/null 2>&1 && python3 ${CLAUDE_PLUGIN_ROOT}/src/commands/sync.py $ARGUMENTS || python ${CLAUDE_PLUGIN_ROOT}/src/commands/sync.py $ARGUMENTS)
