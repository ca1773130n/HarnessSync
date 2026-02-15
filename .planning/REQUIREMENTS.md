# HarnessSync Requirements

## v1 Requirements

### Core Infrastructure
- [ ] **CORE-01**: Plugin has proper plugin.json manifest with hooks, skills, and commands declarations
- [ ] **CORE-02**: State manager tracks sync timestamps, file hashes (SHA256), and per-target sync status in JSON
- [ ] **CORE-03**: OS-aware symlink creation with junction fallback on Windows, copy fallback with marker if both fail
- [ ] **CORE-04**: Logger with colored output, audit trail, and summary statistics (synced/skipped/error/cleaned counts)
- [ ] **CORE-05**: All cc2all references renamed to HarnessSync throughout codebase

### Source Reading
- [ ] **SRC-01**: Source reader discovers CLAUDE.md rules from user scope (~/.claude/) and project scope (.claude/, CLAUDE.md, CLAUDE.local.md)
- [ ] **SRC-02**: Source reader discovers skills from user skills dir, plugin cache (installed_plugins.json), and project .claude/skills/
- [ ] **SRC-03**: Source reader discovers agents (.md files) from user and project .claude/agents/
- [ ] **SRC-04**: Source reader discovers commands (.md files) from user and project .claude/commands/
- [ ] **SRC-05**: Source reader discovers MCP servers from ~/.mcp.json, ~/.claude/.mcp.json, and project .mcp.json
- [ ] **SRC-06**: Source reader discovers settings (env vars, allowedTools) from settings.json and settings.local.json

### Adapter Framework
- [ ] **ADP-01**: Abstract adapter base class with sync_rules(), sync_skills(), sync_agents(), sync_commands(), sync_mcp(), sync_settings() interface
- [ ] **ADP-02**: Adapter registry that discovers and routes to target-specific adapters
- [ ] **ADP-03**: Each adapter reports sync results (what synced, what skipped, what failed, what adapted)

### Codex Adapter
- [ ] **CDX-01**: Sync rules to AGENTS.md with cc2all/HarnessSync header marker
- [ ] **CDX-02**: Sync skills via symlinks to .codex/skills/ and .agents/skills/
- [ ] **CDX-03**: Convert agents to SKILL.md format in .codex/skills/agent-{name}/ with extracted description
- [ ] **CDX-04**: Convert commands to SKILL.md format in .codex/skills/cmd-{name}/
- [ ] **CDX-05**: Translate MCP servers from JSON to TOML [mcp_servers."name"] format with env var support
- [ ] **CDX-06**: Map Claude Code permission settings to Codex sandbox levels (read-only/workspace-write/danger-full-access)

### Gemini Adapter
- [ ] **GMN-01**: Sync rules to GEMINI.md with header marker
- [ ] **GMN-02**: Inline skills content into GEMINI.md (strip YAML frontmatter, add section headers)
- [ ] **GMN-03**: Inline agent descriptions into GEMINI.md
- [ ] **GMN-04**: Summarize commands in GEMINI.md as brief descriptions
- [ ] **GMN-05**: Translate MCP servers to Gemini settings.json mcpServers format (npx mcp-remote for URL types)
- [ ] **GMN-06**: Map Claude Code permission settings to Gemini yolo mode and tools.allowedTools/blockedTools

### OpenCode Adapter
- [ ] **OC-01**: Sync rules to AGENTS.md with header marker
- [ ] **OC-02**: Sync skills via symlinks to .opencode/skills/
- [ ] **OC-03**: Sync agents via symlinks to .opencode/agents/
- [ ] **OC-04**: Sync commands via symlinks to .opencode/commands/
- [ ] **OC-05**: Translate MCP servers to opencode.json format (type: "remote" for URL types)
- [ ] **OC-06**: Map Claude Code permission settings to OpenCode permission mode

### Plugin Interface
- [ ] **PLG-01**: /sync slash command syncs all targets with optional scope argument (user/project/all)
- [ ] **PLG-02**: /sync-status slash command shows last sync time, per-target status, and drift detection
- [ ] **PLG-03**: PostToolUse hook triggers auto-sync when Claude Code writes to config files (CLAUDE.md, .mcp.json, skills/, agents/, commands/, settings.json)
- [ ] **PLG-04**: Hook implements 3-second debounce and file-based locking to prevent concurrent syncs
- [ ] **PLG-05**: Dry run mode previews changes without writing

### Safety & Validation
- [ ] **SAF-01**: Pre-sync backup of target configs enables rollback on failure
- [ ] **SAF-02**: Conflict detection warns when target configs were modified outside HarnessSync
- [ ] **SAF-03**: Secret detection warns when env vars match patterns (API_KEY, SECRET, PASSWORD, TOKEN) before syncing
- [ ] **SAF-04**: Sync compatibility report shows what mapped cleanly, what was adapted, and what couldn't be synced
- [ ] **SAF-05**: Stale symlink cleanup removes broken symlinks in target directories after sync

### MCP Server
- [ ] **MCP-01**: MCP server exposes sync_all, sync_target, get_status tools for programmatic access by other agents
- [ ] **MCP-02**: MCP server returns structured sync results (targets synced, items per target, errors)

### Packaging
- [ ] **PKG-01**: Plugin published to Claude Code marketplace with proper marketplace.json
- [ ] **PKG-02**: Plugin installable from GitHub repository via /plugin command
- [ ] **PKG-03**: install.sh creates target directories and configures shell integration

## v2.0 Requirements — Plugin & MCP Scope Sync

### Plugin MCP Discovery
- [ ] **PLGD-01**: SourceReader discovers installed Claude Code plugins from `~/.claude/plugins/installed_plugins.json` registry
- [ ] **PLGD-02**: SourceReader extracts MCP server configs from plugin cache directories (both `.mcp.json` and inline `plugin.json` formats)
- [ ] **PLGD-03**: SourceReader resolves `${CLAUDE_PLUGIN_ROOT}` variable to absolute plugin cache paths in MCP server configs
- [ ] **PLGD-04**: SourceReader handles both `.claude-plugin/plugin.json` (new format) and root `plugin.json` (old format) for plugin metadata

### Scope-Aware MCP Reading
- [ ] **SCOPE-01**: SourceReader reads user-scope MCP servers from `~/.claude.json` top-level `mcpServers`
- [ ] **SCOPE-02**: SourceReader reads project-scope MCP servers from `.mcp.json` in project root
- [ ] **SCOPE-03**: SourceReader reads local-scope MCP servers from `~/.claude.json` under `projects[path].mcpServers`
- [ ] **SCOPE-04**: SourceReader tags each discovered MCP server with its origin scope (user/project/local/plugin)
- [ ] **SCOPE-05**: SourceReader deduplicates MCP servers appearing at multiple scopes, respecting precedence (local > project > user)

### Scope-Aware Target Sync
- [ ] **SYNC-01**: Gemini adapter writes user-scope MCPs to `~/.gemini/settings.json` and project-scope MCPs to `.gemini/settings.json`
- [ ] **SYNC-02**: Codex adapter writes user-scope MCPs to `~/.codex/config.toml` and project-scope MCPs to `.codex/config.toml`
- [ ] **SYNC-03**: Plugin-discovered MCPs sync to user-scope target configs (plugin MCPs are always user-level)
- [ ] **SYNC-04**: Adapters detect unsupported transport types per target (e.g., SSE on Codex) and warn instead of silently failing

### Environment Variable Translation
- [ ] **ENV-01**: Translate Claude Code `${VAR}` env var interpolation syntax to Codex literal `env` map format
- [ ] **ENV-02**: Translate Claude Code `${VAR:-default}` default value syntax to target equivalents or warn on unsupported
- [ ] **ENV-03**: Preserve env var references in Gemini settings.json format (Gemini supports `${VAR}` natively)

### State & Status Enhancements
- [ ] **STATE-01**: StateManager tracks plugin versions and MCP server counts per plugin for update-triggered re-sync
- [ ] **STATE-02**: /sync-status shows plugin-discovered MCPs separately from user-configured MCPs with scope labels
- [ ] **STATE-03**: Drift detection extends to plugin MCP changes (plugin updated → MCPs may have changed)

## v3 Requirements (Deferred)

- [ ] Bidirectional sync (target → Claude Code) with conflict detection
- [ ] 3-way merge strategies instead of overwrite
- [ ] Semantic agent → skill conversion (extract tools, adapt permissions intelligently)
- [ ] AI-assisted conflict resolution via Claude API
- [ ] Drift reports with scheduled diffs
- [ ] Team sharing via git (version-controlled sync rules)
- [ ] Cross-CLI skill catalog
- [ ] Support for additional targets (Cursor, Windsurf, Aider)

## Out of Scope

- GUI/TUI dashboard — stay CLI-focused, provide JSON output for external tools
- Support for non-AI CLIs — chezmoi exists for general dotfiles
- Cloud sync (Dropbox, Drive) — security risk with API keys in configs
- Full bidirectional auto-merge — impossible to avoid conflicts safely
- Real-time collaborative editing — OT complexity out of scope

## Traceability

### v1.0 (Phases 1-7) — Complete

| Requirement | Phase | Status |
|-------------|-------|--------|
| CORE-01 | Phase 1 | Complete |
| CORE-02 | Phase 1 | Complete |
| CORE-03 | Phase 1 | Complete |
| CORE-04 | Phase 1 | Complete |
| CORE-05 | Phase 1 | Complete |
| SRC-01 | Phase 1 | Complete |
| SRC-02 | Phase 1 | Complete |
| SRC-03 | Phase 1 | Complete |
| SRC-04 | Phase 1 | Complete |
| SRC-05 | Phase 1 | Complete |
| SRC-06 | Phase 1 | Complete |
| ADP-01 | Phase 2 | Complete |
| ADP-02 | Phase 2 | Complete |
| ADP-03 | Phase 2 | Complete |
| CDX-01 | Phase 2 | Complete |
| CDX-02 | Phase 2 | Complete |
| CDX-03 | Phase 2 | Complete |
| CDX-04 | Phase 2 | Complete |
| CDX-05 | Phase 2 | Complete |
| CDX-06 | Phase 2 | Complete |
| GMN-01 | Phase 3 | Complete |
| GMN-02 | Phase 3 | Complete |
| GMN-03 | Phase 3 | Complete |
| GMN-04 | Phase 3 | Complete |
| GMN-05 | Phase 3 | Complete |
| GMN-06 | Phase 3 | Complete |
| OC-01 | Phase 3 | Complete |
| OC-02 | Phase 3 | Complete |
| OC-03 | Phase 3 | Complete |
| OC-04 | Phase 3 | Complete |
| OC-05 | Phase 3 | Complete |
| OC-06 | Phase 3 | Complete |
| PLG-01 | Phase 4 | Complete |
| PLG-02 | Phase 4 | Complete |
| PLG-03 | Phase 4 | Complete |
| PLG-04 | Phase 4 | Complete |
| PLG-05 | Phase 4 | Complete |
| SAF-01 | Phase 5 | Complete |
| SAF-02 | Phase 5 | Complete |
| SAF-03 | Phase 5 | Complete |
| SAF-04 | Phase 5 | Complete |
| SAF-05 | Phase 5 | Complete |
| MCP-01 | Phase 6 | Complete |
| MCP-02 | Phase 6 | Complete |
| PKG-01 | Phase 7 | Complete |
| PKG-02 | Phase 7 | Complete |
| PKG-03 | Phase 7 | Complete |

**v1.0 Coverage:** 44/44 requirements mapped (100%) — delivered 2026-02-15

### v1.1 (Phase 8) — Complete

| Requirement | Phase | Status |
|-------------|-------|--------|
| MULTI-01 | Phase 8 | Complete |
| MULTI-02 | Phase 8 | Complete |
| MULTI-03 | Phase 8 | Complete |
| MULTI-04 | Phase 8 | Complete |
| MULTI-05 | Phase 8 | Complete |
| MULTI-06 | Phase 8 | Complete |
| MULTI-07 | Phase 8 | Complete |
| MULTI-08 | Phase 8 | Complete |
| MULTI-09 | Phase 8 | Complete |
| MULTI-10 | Phase 8 | Complete |

**v1.1 Coverage:** 10/10 multi-account requirements — delivered 2026-02-15

### v2.0 (Phases 9-11) — In Progress

| Requirement | Phase | Status |
|-------------|-------|--------|
| PLGD-01 | Phase 9 | Pending |
| PLGD-02 | Phase 9 | Pending |
| PLGD-03 | Phase 9 | Pending |
| PLGD-04 | Phase 9 | Pending |
| SCOPE-01 | Phase 9 | Pending |
| SCOPE-02 | Phase 9 | Pending |
| SCOPE-03 | Phase 9 | Pending |
| SCOPE-04 | Phase 9 | Pending |
| SCOPE-05 | Phase 9 | Pending |
| SYNC-01 | Phase 10 | Pending |
| SYNC-02 | Phase 10 | Pending |
| SYNC-03 | Phase 10 | Pending |
| SYNC-04 | Phase 10 | Pending |
| ENV-01 | Phase 10 | Pending |
| ENV-02 | Phase 10 | Pending |
| ENV-03 | Phase 10 | Pending |
| STATE-01 | Phase 11 | Pending |
| STATE-02 | Phase 11 | Pending |
| STATE-03 | Phase 11 | Pending |

**v2.0 Coverage:** 19/19 requirements mapped (100%)

---

*Requirements defined: 2026-02-13 (v1), 2026-02-15 (v1.1, v2.0)*
*Source: Research v2-SUMMARY.md, v2-gemini-extensions.md, v2-codex-mcp.md, v2-claude-plugins.md*
*Traceability updated: 2026-02-15*
