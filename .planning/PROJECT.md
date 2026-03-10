# HarnessSync

## Vision

Claude Code plugin that synchronizes Claude Code's environment (rules, skills, agents, commands, MCP servers, settings) to all other AI coding harnesses. Claude Code is the single source of truth — configure once, sync everywhere.

## Core Value

**One harness to rule them all.** Users invest in Claude Code's rich ecosystem (plugins, skills, agents, MCP servers) and get that investment reflected across every AI coding CLI they use, without manual duplication or format translation.

## Background

Evolved from **cc2all** — a standalone Python sync script. HarnessSync elevates this into a proper Claude Code plugin with hooks, slash commands, and MCP server integration. The existing cc2all-sync.py (~980 lines) provides proven sync logic for Codex, Gemini CLI, and OpenCode.

## Problem

AI developers use multiple coding harnesses (Claude Code, Codex, Gemini CLI, OpenCode, etc.). Each has its own config format:
- Claude Code: `CLAUDE.md`, `.claude/skills/`, `.claude/rules/`, `.mcp.json`, `settings.json`
- Codex: `AGENTS.md`, `.agents/skills/`, `config.toml`
- Gemini: `GEMINI.md`, `.gemini/skills/`, `.gemini/agents/`, `.gemini/commands/`, `settings.json`
- OpenCode: `AGENTS.md`, `.opencode/skills/`, `opencode.json`

Maintaining these in parallel is tedious, error-prone, and leads to settings drift — permission models, env vars, and allowed tools differ across CLIs, causing inconsistent behavior.

## Solution

A Claude Code plugin that:
1. **Auto-syncs** via PostToolUse hooks when Claude Code config changes
2. **Provides slash commands** (`/sync`, `/sync-status`) for manual control
3. **Exposes MCP tools** for programmatic sync from other agents
4. **Creates adapter layers** that approximate target-native behavior when direct mapping isn't possible
5. **Warns clearly** about incompatible settings that can't be bridged

## Architecture (Target)

```
Claude Code Plugin (HarnessSync)
├── hooks/          — PostToolUse auto-sync trigger
├── skills/         — Slash commands (/sync, /sync-status)
├── mcp/            — MCP server exposing sync tools
├── adapters/       — Per-target format adapters
│   ├── codex.py
│   ├── gemini.py
│   └── opencode.py
├── core/           — Source reader, state management, change detection
└── plugin.json     — Plugin manifest
```

## Constraints

- **Python 3 stdlib only** — no external dependencies (proven approach from cc2all)
- **macOS primary** — with Linux support (fswatch/inotify/polling)
- **Non-destructive** — never modifies Claude Code config; read-only from source
- **Symlink-first** — for skills/agents (instant updates, no re-sync needed)
- **Claude Code plugin structure** — must conform to plugin.json, hooks, skills specs

## Target Users

- AI developers who use Claude Code as primary and switch between Codex/Gemini/OpenCode
- Teams standardizing on Claude Code who need harness portability

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Claude Code plugin (not standalone) | Native integration, hooks, slash commands, marketplace distribution | Decided |
| Adapter layer for settings drift | Best-effort mapping isn't enough — approximate behavior via shim configs | Decided |
| Python 3 stdlib only | Zero dependency footprint, proven from cc2all | Decided |
| Both GitHub + marketplace distribution | GitHub for dev, marketplace for stable | Decided |
| MCP server component | Expose sync as tools for other agents | Decided |
| Priority: deep sync first, more targets later | Get Codex/Gemini/OpenCode right before adding Cursor/Windsurf/Aider | Decided |

## Requirements

### Validated

- V **Source reading** — Reads CLAUDE.md, skills, agents, commands, MCP, settings from both user and project scope — existing
- V **Codex sync** — Rules to AGENTS.md, skills via symlink, agents/commands to SKILL.md, MCP to config.toml — existing
- V **Gemini sync** — Rules/skills/agents to GEMINI.md inline, MCP to settings.json — existing
- V **OpenCode sync** — Rules to AGENTS.md, skills/agents/commands via symlink, MCP to opencode.json — existing
- V **Watch mode** — fswatch/inotify/polling with debounce — existing
- V **Shell wrappers** — Auto-sync on codex/gemini/opencode launch with cooldown — existing
- V **Dry run** — Preview changes without writing — existing
- V **State tracking** — SHA256 change detection, sync timestamps — existing
- V **Stale symlink cleanup** — Removes broken symlinks after sync — existing
- V **macOS daemon** — launchd plist for background watch mode — existing
- V **Plugin architecture** — Claude Code plugin with hooks, commands, MCP server — v0.0.1
- V **PostToolUse hook** — Auto-sync on config file changes with 3s debounce — v0.0.1
- V **Slash commands** — /sync and /sync-status for manual control — v0.0.1
- V **MCP server** — JSON-RPC 2.0 sync tools for programmatic access — v0.0.1
- V **Settings drift adaptation** — Env vars, permissions, allowed tools mapping per target — v0.0.1
- V **Multi-account support** — Account discovery, setup wizard, scoped sync — v0.0.1
- V **Plugin MCP discovery** — Discover MCPs from installed Claude Code plugins — v0.0.2
- V **Scope-aware sync** — 3-tier scope (user/project/local) with target routing — v0.0.2
- V **Env var translation** — ${VAR} and ${VAR:-default} translation per target format — v0.0.2
- V **Plugin drift detection** — Version tracking, MCP count changes, add/remove detection — v0.0.2
- V **Marketplace packaging** — .claude-plugin structure, marketplace.json, install.sh — v0.0.1
- V **Rules directory discovery** — `.claude/rules/*.md` with recursive walking and YAML frontmatter path-scoping — v0.1.1
- V **Codex config modernization** — `config.toml` filename, `on-request` approval policy, MCP `cwd` passthrough — v0.1.1
- V **Gemini native formats** — Skills to SKILL.md, agents to .md, commands to .toml instead of inlining in GEMINI.md — v0.1.1
- V **Gemini settings v2** — `tools.allowed`/`tools.exclude` instead of deprecated v1 keys — v0.1.1
- V **OpenCode permission rewrite** — Granular `permission` (singular) with per-tool allow/ask/deny — v0.1.1
- V **OpenCode env var syntax** — `{env:VAR_NAME}` in MCP headers, skill dedup vs `.claude/skills/` — v0.1.1
- V **Config preservation** — Non-synced fields preserved in Codex TOML and Gemini JSON during writes — v0.1.1
- V **MCP field passthrough** — `trust`, `includeTools`, `excludeTools`, `cwd` forwarded to targets — v0.1.1

### Active

No active milestone. Ready for next milestone planning.

### Deferred

- [ ] Bidirectional sync (target → Claude Code) with conflict detection
- [ ] Support for additional targets (Cursor, Windsurf, Aider)
- [ ] AI-assisted conflict resolution via Claude API

### Out of Scope

- Cursor/Windsurf/Aider support — deferred to future milestone
- Bidirectional sync (target → Claude Code) — Claude Code is always source of truth
- GUI/web dashboard — CLI-only tool

---

## Completed Milestones

- **v0.0.1** — Core Plugin + Multi-Account (2026-02-15): 8 phases, 24 plans, 57 requirements
- **v0.0.2** — Plugin & MCP Scope Sync (2026-02-15): 3 phases, 7 plans, 19 requirements
- **v0.1.1** — Target CLI Modernization (2026-03-10): 3 phases, 7 plans, 19 requirements

See `.planning/MILESTONES.md` for full history.

---
*Last updated: 2026-03-10 — v0.1.1 milestone complete*
