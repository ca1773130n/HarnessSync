# HarnessSync

## Vision

Claude Code plugin that synchronizes Claude Code's environment (rules, skills, agents, commands, MCP servers, settings) to all other AI coding harnesses. Claude Code is the single source of truth — configure once, sync everywhere.

## Core Value

**One harness to rule them all.** Users invest in Claude Code's rich ecosystem (plugins, skills, agents, MCP servers) and get that investment reflected across every AI coding CLI they use, without manual duplication or format translation.

## Background

Evolved from **cc2all** — a standalone Python sync script. HarnessSync elevates this into a proper Claude Code plugin with hooks, slash commands, and MCP server integration. The existing cc2all-sync.py (~980 lines) provides proven sync logic for Codex, Gemini CLI, and OpenCode.

## Problem

AI developers use multiple coding harnesses (Claude Code, Codex, Gemini CLI, OpenCode, etc.). Each has its own config format:
- Claude Code: `CLAUDE.md`, `.claude/skills/`, `.mcp.json`, `settings.json`
- Codex: `AGENTS.md`, `.codex/skills/`, `config.toml`
- Gemini: `GEMINI.md`, `settings.json`
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

### Active

- [ ] Rewrite as Claude Code plugin architecture
- [ ] PostToolUse hook for auto-sync
- [ ] Slash commands (/sync, /sync-status)
- [ ] MCP server exposing sync tools
- [ ] Adapter layer for settings drift (env vars, permissions, allowed tools)
- [ ] Improved Codex format accuracy (deeper TOML generation, permission mapping)
- [ ] Improved Gemini format accuracy (settings parity, extension mapping)
- [ ] Improved OpenCode format accuracy (full config.json schema support)
- [ ] Sync compatibility report (what mapped, what adapted, what can't)
- [ ] Rename cc2all → HarnessSync throughout
- [ ] Test suite
- [ ] Plugin marketplace packaging

### Out of Scope

- Cursor/Windsurf/Aider support — deferred to future milestone
- Bidirectional sync (target → Claude Code) — Claude Code is always source of truth
- GUI/web dashboard — CLI-only tool

---

## Current Milestone: v2.0 — Plugin & MCP Scope Sync

**Goal:** Synchronize Claude Code's installed/configured plugins and MCP servers (both user and project scope) to Gemini extensions and Codex MCP configurations. Gemini gets full plugin-to-extension mapping; Codex gets MCP server sync only (no plugin concept).

**Target Features:**
- Discover installed Claude Code plugins (from installed_plugins.json, plugin cache)
- Map Claude Code plugins to Gemini extensions format
- Sync plugin-provided MCP servers to Gemini and Codex
- Scope-aware sync: user-scope plugins/MCPs and project-scope plugins/MCPs
- Handle plugin dependencies and capabilities translation

**Scope Notes:**
- Codex: MCP servers only (Codex has no plugin/extension equivalent)
- Gemini: Full plugin-to-extension mapping + MCP servers
- OpenCode: Out of scope for this milestone (revisit later)

---
*Last updated: 2026-02-15 — v2.0 milestone started*
