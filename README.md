# HarnessSync

**Configure Claude Code once, sync everywhere.**

HarnessSync automatically synchronizes your Claude Code configuration — rules, skills, agents, commands, MCP servers, and settings — to OpenAI Codex CLI, Gemini CLI, and OpenCode. No manual duplication. No format translation. Just use Claude Code normally.

```
         ┌──────────────────┐
         │   Claude Code    │  ← Single source of truth
         │   ~/.claude/     │
         └────────┬─────────┘
                  │
         ┌────────┴─────────┐
         │   HarnessSync    │  ← Automatic
         └──┬─────┬─────┬───┘
            │     │     │
     ┌──────┘     │     └──────┐
     ▼            ▼            ▼
┌─────────┐ ┌─────────┐ ┌──────────┐
│  Codex  │ │ Gemini  │ │ OpenCode │
│ ~/.codex│ │~/.gemini│ │~/.config/│
│         │ │         │ │ opencode │
└─────────┘ └─────────┘ └──────────┘
```

## Quickstart

### Install as Claude Code Plugin (Recommended)

```bash
/plugin install github:YOUR_USERNAME/HarnessSync
```

That's it. HarnessSync will automatically sync your config whenever Claude Code edits a configuration file.

### Install from Source

```bash
git clone https://github.com/YOUR_USERNAME/HarnessSync.git
cd HarnessSync
bash install.sh
```

Then restart your shell:

```bash
source ~/.zshrc   # or ~/.bashrc
```

### Verify Installation

Inside Claude Code, run:

```
/sync-status
```

Or from the terminal:

```bash
harnesssync status
```

### Run Your First Sync

```
/sync
```

From this point forward, syncing happens automatically. Every time Claude Code edits your `CLAUDE.md`, `settings.json`, `.mcp.json`, or any file in `.claude/`, HarnessSync detects the change and syncs to all targets.

## What Gets Synced

| Claude Code | Codex | Gemini CLI | OpenCode |
|---|---|---|---|
| `CLAUDE.md` (rules) | `AGENTS.md` | `GEMINI.md` | `AGENTS.md` |
| `.claude/skills/` | `.codex/skills/` (symlink) | Inlined in `GEMINI.md` | `.opencode/skills/` (symlink) |
| `.claude/agents/` | `skills/agent-{name}/` | Inlined in `GEMINI.md` | `.opencode/agents/` (symlink) |
| `.claude/commands/` | `skills/cmd-{name}/` | Summarized in `GEMINI.md` | `.opencode/commands/` (symlink) |
| `.mcp.json` | `config.toml [mcp_servers]` | `settings.json` | `opencode.json` |
| `settings.json` (env) | `config.toml [env]` | `.gemini/.env` | `opencode.json [env]` |

Both **user scope** (`~/.claude/`) and **project scope** (`.claude/`, `CLAUDE.md`) are supported.

## How It Works

HarnessSync triggers automatically via three mechanisms:

1. **PostToolUse Hook** — When Claude Code edits a config file (CLAUDE.md, settings.json, .mcp.json, skills/, agents/, commands/), the hook fires and syncs immediately.

2. **Shell Wrappers** — Running `codex`, `gemini`, or `opencode` in your terminal auto-syncs before launch (with a 5-minute cooldown to avoid redundant work).

3. **Manual Commands** — `/sync` inside Claude Code, or `harnesssync` in your terminal.

You just use Claude Code normally. Everything else follows.

## Commands

### Inside Claude Code

| Command | Description |
|---|---|
| `/sync` | Sync all config to all targets |
| `/sync --scope user` | Sync only user-level config |
| `/sync --scope project` | Sync only project-level config |
| `/sync --dry-run` | Preview changes without writing |
| `/sync-status` | Show sync status and drift detection |

### Terminal

| Command | Description |
|---|---|
| `harnesssync` | Sync now |
| `harnesssync status` | Show sync status per target |
| `harnesssync force` | Force sync (skip cooldown) |
| `harnesssync help` | Show help |

### MCP Tools

HarnessSync exposes an MCP server with three tools for programmatic access:

| Tool | Description |
|---|---|
| `sync_all` | Sync all config to all targets |
| `sync_target` | Sync to a specific target (codex/gemini/opencode) |
| `get_status` | Get sync status as structured JSON |

## Safety Features

- **Secret Detection** — Scans environment variables for API keys, tokens, and passwords. Blocks sync when secrets are found (override with `--allow-secrets`).
- **Conflict Detection** — Warns when target files were manually edited since last sync.
- **Backup & Rollback** — Backs up target files before overwriting. Automatic rollback on failure.
- **Broken Symlink Cleanup** — Removes stale symlinks from previous syncs.
- **Compatibility Reports** — Shows per-target breakdown when config items are adapted or skipped.

## Configuration

### Environment Variables

| Variable | Default | Description |
|---|---|---|
| `HARNESSSYNC_COOLDOWN` | `300` | Seconds between auto-syncs |
| `HARNESSSYNC_VERBOSE` | `0` | Show output during auto-sync |
| `CODEX_HOME` | `~/.codex` | Codex home directory |

### Permissions

HarnessSync follows conservative security defaults:

- Claude Code `"deny"` permissions are **never** downgraded in targets
- Denied tools are skipped entirely rather than mapped to a lower permission
- Gemini `yolo` mode is **never** auto-enabled, even if Claude Code has auto-approval

## Requirements

- Python 3.10+
- No external dependencies (stdlib only)
- macOS, Linux, or Windows (WSL2/Git Bash)

## Project Structure

```
HarnessSync/
├── .claude-plugin/
│   ├── plugin.json          # Plugin manifest
│   └── marketplace.json     # Marketplace distribution
├── commands/                # Slash commands
│   ├── sync.md
│   └── sync-status.md
├── hooks/                   # PostToolUse hook
│   └── hooks.json
├── src/                     # Python sync engine (~4,200 lines)
│   ├── orchestrator.py      # Central coordinator
│   ├── source_reader.py     # Claude Code config discovery
│   ├── state_manager.py     # Drift detection & state tracking
│   ├── adapters/            # Target adapters
│   │   ├── codex.py
│   │   ├── gemini.py
│   │   └── opencode.py
│   ├── mcp/                 # MCP server (JSON-RPC over stdio)
│   │   └── server.py
│   └── utils/               # Logging, hashing, paths
├── install.sh               # Cross-platform installer
├── shell-integration.sh     # Shell wrappers (codex/gemini/opencode)
└── .github/workflows/
    └── validate.yml         # CI validation (3 platforms x 2 Python versions)
```

## Troubleshooting

**"No config found"** — Make sure `~/.claude/` exists. Run Claude Code at least once to create it.

**Gemini doesn't show my skills** — Gemini CLI has no skill system. Skills are inlined into `GEMINI.md`. Check with `cat ~/.gemini/GEMINI.md`.

**Sync not triggering automatically** — Verify the plugin is installed: `/sync-status`. For shell wrappers, check your shell RC file for the `HarnessSync` source line.

**Secrets blocking sync** — HarnessSync detects API keys in env vars by default. Use `/sync --allow-secrets` to override, or remove secrets from `settings.json`.

**Windows symlink errors** — HarnessSync uses junction points on Windows (no admin required). Ensure you're running from Git Bash or WSL2.

## License

MIT
