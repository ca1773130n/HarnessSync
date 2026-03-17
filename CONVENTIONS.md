<!-- Managed by HarnessSync -->
# Project Conventions (synced from Claude Code)

# [Project rules from CLAUDE.md]

# HarnessSync

Syncs Claude Code config (CLAUDE.md, skills, agents, commands, MCP servers, settings) to 12 AI harnesses automatically.

## Commands

```bash
python3 -m pytest tests/                # run all tests
python3 src/commands/sync.py             # manual sync (all targets)
python3 src/commands/sync_status.py      # show sync status + drift
python3 src/commands/sync.py --dry-run   # preview without writing
```

## Architecture

- `src/orchestrator.py` — central sync coordinator; reads source, runs adapters, writes targets
- `src/source_reader.py` — discovers and reads Claude Code config (CLAUDE.md, .mcp.json, settings.json, skills/, agents/, commands/)
- `src/adapters/` — one adapter per target harness, all extend `src/adapters/base.py`
  - Targets: aider, cline, codex, continue, cursor, gemini, neovim, opencode, vscode, windsurf, zed
- `src/commands/` — slash command implementations (27 commands: sync, sync-status, sync-diff, sync-health, sync-lint, sync-scope, etc.)
- `commands/` — slash command markdown definitions that Claude Code discovers
- `hooks/hooks.json` — PostToolUse hook triggers sync on Edit/Write/MultiEdit; SessionStart hook runs startup checks
- `src/mcp/` — MCP server (JSON-RPC over stdio) exposing sync_all, sync_target, get_status tools
- `src/utils/` — shared helpers (logging, hashing, paths)
- `.planning/` — project roadmap, milestones, and evolve state (not runtime code)

## Key Patterns

- Pure Python 3.10+, stdlib only, no external dependencies
- Adapters follow a registry pattern: `src/adapters/registry.py` maps harness names to adapter classes
- Commands parse args with argparse in `src/commands/*.py` and delegate to library modules in `src/`
- Module-level functions for stateless transforms; classes for stateful managers
- SourceReader is the canonical read path — never read config files directly in commands or orchestrator
- Best-effort try/except around optional features in orchestrator so they never break the core sync path
- Return types are dataclasses or simple primitives, never raw JSON strings from library functions

## MCP Tools (context-mode)

Prefer these over Bash for file reads and large output operations:

| Tool | Purpose |
|------|---------|
| `ctx_execute` | Run shell commands with output captured server-side |
| `ctx_execute_file` | Read and analyze files without loading into context |
| `ctx_batch_execute` | Run multiple commands in one call |
| `ctx_index` | Index file content for BM25 search |
| `ctx_search` | Search indexed content with BM25 ranking |
| `ctx_fetch_and_index` | Fetch URL and index for search |
| `ctx_doctor` | Diagnose context-mode setup |
| `ctx_stats` | Show context-mode usage stats |
| `ctx_upgrade` | Upgrade context-mode |

## Safety

- Secret detection blocks sync when API keys/tokens found in env vars
- Conflict detection warns when target files were manually edited since last sync
- Backup manager snapshots target files before overwriting; automatic rollback on failure
- Claude Code `"deny"` permissions are never downgraded in targets


---
*Last synced by HarnessSync: 2026-03-17 23:47:10 UTC*
<!-- End HarnessSync managed content -->
