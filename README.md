# HarnessSync

**Configure Claude Code once, sync everywhere.**

HarnessSync automatically synchronizes your Claude Code configuration — rules, skills, agents, commands, MCP servers, and settings — to 12 AI harnesses. No manual duplication. No format translation.

```
         ┌──────────────────┐
         │   Claude Code    │  ← Single source of truth
         │   ~/.claude/     │
         └────────┬─────────┘
                  │
         ┌────────┴─────────┐
         │   HarnessSync    │  ← Automatic
         └──┬──┬──┬──┬──┬───┘
            │  │  │  │  │
     ┌──────┘  │  │  │  └──────┐
     ▼         ▼  ▼  ▼         ▼
  Codex    Gemini  Cursor  Windsurf  ... 7 more
```

## Supported Targets

Aider, Cline, Codex, Continue, Cursor, Gemini, Neovim, OpenCode, VS Code, Windsurf, Zed

## Quickstart

```bash
# Install as Claude Code plugin
claude plugin install github:ca1773130n/HarnessSync

# Verify
/sync-status

# Run first sync
/sync
```

After this, syncing happens automatically via PostToolUse hooks whenever Claude Code edits config files.

## What Gets Synced

| Claude Code | Target |
|---|---|
| `CLAUDE.md` (rules) | `AGENTS.md` / `GEMINI.md` / format-specific equivalent |
| `.claude/skills/` | Symlinked or inlined per target capability |
| `.claude/agents/` | Symlinked or inlined per target capability |
| `.claude/commands/` | Symlinked or summarized per target capability |
| `.mcp.json` | `config.toml`, `settings.json`, or equivalent |
| `settings.json` (env) | Target-specific env format |

Both **user scope** (`~/.claude/`) and **project scope** (`.claude/`, `CLAUDE.md`) are supported.

## How It Works

1. **PostToolUse Hook** — fires on Edit/Write/MultiEdit of config files, syncs immediately
2. **Shell Wrappers** — `codex`, `gemini`, `opencode` auto-sync before launch (5-min cooldown)
3. **Manual** — `/sync` inside Claude Code, or `harnesssync` in terminal

## Commands

| Command | Description |
|---|---|
| `/sync` | Sync all config to all targets |
| `/sync --dry-run` | Preview changes without writing |
| `/sync-status` | Sync status and drift detection |
| `/sync-diff` | Show config differences across targets |
| `/sync-health` | Health check for sync pipeline |
| `/sync-lint` | Lint config for issues |
| `/sync-scope` | Rule scope hierarchy and conflict detection |
| `/sync-preset` | Browse and install sync profile presets |
| `/sync-dashboard` | Visual sync dashboard |
| `/sync-rollback` | Undo last sync |
| `/sync-restore` | Restore from backup |
| `/sync-capabilities` | Show per-target capability support |
| `/sync-gaps` | Feature gap analysis across targets |
| `/sync-matrix` | Full compatibility matrix |
| `/sync-parity` | Config parity report |
| `/sync-permissions` | Permission mapping visualization |
| `/sync-map` | Config dependency map |
| `/sync-log` | Sync history log |
| `/sync-report` | Generate sync report |
| `/sync-memory` | Cross-harness memory sync |
| `/sync-setup` | Multi-account setup |
| `/sync-add-harness` | Add a new harness target |
| `/sync-activate` | Activate/deactivate targets |
| `/sync-schedule` | Configure sync schedule |
| `/sync-sandbox` | Test sync in sandbox |
| `/sync-git-hook` | Install git hooks |
| `/sync-cloud` | Cloud sync |
| `/sync-pr-comment` | PR sync preview comment |

### Terminal

```bash
harnesssync          # sync now
harnesssync status   # show status
harnesssync force    # skip cooldown
```

## Safety

- **Secret Detection** — blocks sync when API keys/tokens found in env vars
- **Conflict Detection** — warns when target files were manually edited
- **Backup & Rollback** — snapshots before overwriting, auto-rollback on failure
- **Permission Safety** — Claude Code `"deny"` permissions are never downgraded

## Configuration

| Variable | Default | Description |
|---|---|---|
| `HARNESSSYNC_COOLDOWN` | `300` | Seconds between auto-syncs |
| `HARNESSSYNC_VERBOSE` | `0` | Show output during auto-sync |

## Requirements

- Python 3.10+
- No external dependencies (stdlib only)
- macOS, Linux, or Windows (WSL2/Git Bash)
