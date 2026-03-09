# HarnessSync Requirements

## v1 Requirements

### Core Infrastructure
- [x] **CORE-01**: Plugin has proper plugin.json manifest with hooks, skills, and commands declarations
- [x] **CORE-02**: State manager tracks sync timestamps, file hashes (SHA256), and per-target sync status in JSON
- [x] **CORE-03**: OS-aware symlink creation with junction fallback on Windows, copy fallback with marker if both fail
- [x] **CORE-04**: Logger with colored output, audit trail, and summary statistics (synced/skipped/error/cleaned counts)
- [x] **CORE-05**: All cc2all references renamed to HarnessSync throughout codebase

### Source Reading
- [x] **SRC-01**: Source reader discovers CLAUDE.md rules from user scope (~/.claude/) and project scope (.claude/, CLAUDE.md, CLAUDE.local.md)
- [x] **SRC-02**: Source reader discovers skills from user skills dir, plugin cache (installed_plugins.json), and project .claude/skills/
- [x] **SRC-03**: Source reader discovers agents (.md files) from user and project .claude/agents/
- [x] **SRC-04**: Source reader discovers commands (.md files) from user and project .claude/commands/
- [x] **SRC-05**: Source reader discovers MCP servers from ~/.mcp.json, ~/.claude/.mcp.json, and project .mcp.json
- [x] **SRC-06**: Source reader discovers settings (env vars, allowedTools) from settings.json and settings.local.json

### Adapter Framework
- [x] **ADP-01**: Abstract adapter base class with sync_rules(), sync_skills(), sync_agents(), sync_commands(), sync_mcp(), sync_settings() interface
- [x] **ADP-02**: Adapter registry that discovers and routes to target-specific adapters
- [x] **ADP-03**: Each adapter reports sync results (what synced, what skipped, what failed, what adapted)

### Codex Adapter
- [x] **CDX-01**: Sync rules to AGENTS.md with cc2all/HarnessSync header marker
- [x] **CDX-02**: Sync skills via symlinks to .codex/skills/ and .agents/skills/
- [x] **CDX-03**: Convert agents to SKILL.md format in .codex/skills/agent-{name}/ with extracted description
- [x] **CDX-04**: Convert commands to SKILL.md format in .codex/skills/cmd-{name}/
- [x] **CDX-05**: Translate MCP servers from JSON to TOML [mcp_servers."name"] format with env var support
- [x] **CDX-06**: Map Claude Code permission settings to Codex sandbox levels (read-only/workspace-write/danger-full-access)

### Gemini Adapter
- [x] **GMN-01**: Sync rules to GEMINI.md with header marker
- [x] **GMN-02**: Inline skills content into GEMINI.md (strip YAML frontmatter, add section headers)
- [x] **GMN-03**: Inline agent descriptions into GEMINI.md
- [x] **GMN-04**: Summarize commands in GEMINI.md as brief descriptions
- [x] **GMN-05**: Translate MCP servers to Gemini settings.json mcpServers format (npx mcp-remote for URL types)
- [x] **GMN-06**: Map Claude Code permission settings to Gemini yolo mode and tools.allowedTools/blockedTools

### OpenCode Adapter
- [x] **OC-01**: Sync rules to AGENTS.md with header marker
- [x] **OC-02**: Sync skills via symlinks to .opencode/skills/
- [x] **OC-03**: Sync agents via symlinks to .opencode/agents/
- [x] **OC-04**: Sync commands via symlinks to .opencode/commands/
- [x] **OC-05**: Translate MCP servers to opencode.json format (type: "remote" for URL types)
- [x] **OC-06**: Map Claude Code permission settings to OpenCode permission mode

### Plugin Interface
- [x] **PLG-01**: /sync slash command syncs all targets with optional scope argument (user/project/all)
- [x] **PLG-02**: /sync-status slash command shows last sync time, per-target status, and drift detection
- [x] **PLG-03**: PostToolUse hook triggers auto-sync when Claude Code writes to config files (CLAUDE.md, .mcp.json, skills/, agents/, commands/, settings.json)
- [x] **PLG-04**: Hook implements 3-second debounce and file-based locking to prevent concurrent syncs
- [x] **PLG-05**: Dry run mode previews changes without writing

### Safety & Validation
- [x] **SAF-01**: Pre-sync backup of target configs enables rollback on failure
- [x] **SAF-02**: Conflict detection warns when target configs were modified outside HarnessSync
- [x] **SAF-03**: Secret detection warns when env vars match patterns (API_KEY, SECRET, PASSWORD, TOKEN) before syncing
- [x] **SAF-04**: Sync compatibility report shows what mapped cleanly, what was adapted, and what couldn't be synced
- [x] **SAF-05**: Stale symlink cleanup removes broken symlinks in target directories after sync

### MCP Server
- [x] **MCP-01**: MCP server exposes sync_all, sync_target, get_status tools for programmatic access by other agents
- [x] **MCP-02**: MCP server returns structured sync results (targets synced, items per target, errors)

### Packaging
- [x] **PKG-01**: Plugin published to Claude Code marketplace with proper marketplace.json
- [x] **PKG-02**: Plugin installable from GitHub repository via /plugin command
- [x] **PKG-03**: install.sh creates target directories and configures shell integration

## v0.0.2 Requirements — Plugin & MCP Scope Sync

### Plugin MCP Discovery
- [x] **PLGD-01**: SourceReader discovers installed Claude Code plugins from `~/.claude/plugins/installed_plugins.json` registry
- [x] **PLGD-02**: SourceReader extracts MCP server configs from plugin cache directories (both `.mcp.json` and inline `plugin.json` formats)
- [x] **PLGD-03**: SourceReader resolves `${CLAUDE_PLUGIN_ROOT}` variable to absolute plugin cache paths in MCP server configs
- [x] **PLGD-04**: SourceReader handles both `.claude-plugin/plugin.json` (new format) and root `plugin.json` (old format) for plugin metadata

### Scope-Aware MCP Reading
- [x] **SCOPE-01**: SourceReader reads user-scope MCP servers from `~/.claude.json` top-level `mcpServers`
- [x] **SCOPE-02**: SourceReader reads project-scope MCP servers from `.mcp.json` in project root
- [x] **SCOPE-03**: SourceReader reads local-scope MCP servers from `~/.claude.json` under `projects[path].mcpServers`
- [x] **SCOPE-04**: SourceReader tags each discovered MCP server with its origin scope (user/project/local/plugin)
- [x] **SCOPE-05**: SourceReader deduplicates MCP servers appearing at multiple scopes, respecting precedence (local > project > user)

### Scope-Aware Target Sync
- [x] **SYNC-01**: Gemini adapter writes user-scope MCPs to `~/.gemini/settings.json` and project-scope MCPs to `.gemini/settings.json`
- [x] **SYNC-02**: Codex adapter writes user-scope MCPs to `~/.codex/config.toml` and project-scope MCPs to `.codex/config.toml`
- [x] **SYNC-03**: Plugin-discovered MCPs sync to user-scope target configs (plugin MCPs are always user-level)
- [x] **SYNC-04**: Adapters detect unsupported transport types per target (e.g., SSE on Codex) and warn instead of silently failing

### Environment Variable Translation
- [x] **ENV-01**: Translate Claude Code `${VAR}` env var interpolation syntax to Codex literal `env` map format
- [x] **ENV-02**: Translate Claude Code `${VAR:-default}` default value syntax to target equivalents or warn on unsupported
- [x] **ENV-03**: Preserve env var references in Gemini settings.json format (Gemini supports `${VAR}` natively)

### State & Status Enhancements
- [x] **STATE-01**: StateManager tracks plugin versions and MCP server counts per plugin for update-triggered re-sync
- [x] **STATE-02**: /sync-status shows plugin-discovered MCPs separately from user-configured MCPs with scope labels
- [x] **STATE-03**: Drift detection extends to plugin MCP changes (plugin updated → MCPs may have changed)

## v0.1.1 Requirements — Target CLI Modernization

### Source Reader: Claude Code Rules Discovery
- [ ] **RULES-01**: SourceReader discovers `.claude/rules/*.md` files (project-level rules with optional YAML frontmatter path-scoping)
- [ ] **RULES-02**: SourceReader discovers `~/.claude/rules/*.md` files (user-level rules) with recursive subdirectory walking
- [ ] **RULES-03**: Rules content (markdown body after optional frontmatter) is included in rules output alongside CLAUDE.md content
- [ ] **RULES-04**: Rules with `paths:` frontmatter are tagged with their path patterns for adapters that can use scoping

### Codex Adapter: Config Modernization
- [ ] **CDX-07**: Fix approval policy mapping: `approval_policy = 'on-request'` instead of deprecated `'on-failure'`
- [ ] **CDX-08**: Verify and fix config filename: use `config.toml` (official) instead of `codex.toml` if Codex CLI requires it
- [ ] **CDX-09**: Pass through new MCP fields (`cwd`, `enabled_tools`, `disabled_tools`) when present in source config

### Gemini Adapter: Native Format Migration
- [ ] **GMN-07**: Sync skills to native `.gemini/skills/<name>/SKILL.md` files instead of inlining in GEMINI.md
- [ ] **GMN-08**: Sync agents to native `.gemini/agents/<name>.md` files with Gemini-compatible frontmatter (name, description, tools, model, max_turns) instead of inlining in GEMINI.md
- [ ] **GMN-09**: Sync commands to native `.gemini/commands/<name>.toml` files with `description` and `prompt` fields, mapping `$ARGUMENTS` → `{{args}}`, instead of bullet points in GEMINI.md
- [ ] **GMN-10**: Fix settings.json tools format: write `tools.allowed` and `tools.exclude` (v2) instead of `tools.allowedTools` and `tools.blockedTools` (v1)
- [ ] **GMN-11**: Pass through new MCP fields (`trust`, `includeTools`, `excludeTools`, `cwd`) when present in source config
- [ ] **GMN-12**: Clean up stale inlined skills/agents/commands sections from GEMINI.md after migrating to native formats

### OpenCode Adapter: Permission System Rewrite
- [ ] **OC-07**: Rewrite permission sync to use `permission` (singular) key with per-tool `allow`/`ask`/`deny` values instead of deprecated `permissions.mode` format
- [ ] **OC-08**: Map Claude Code allowed tools to OpenCode `permission.bash` patterns (e.g., `"git *": "allow"`)
- [ ] **OC-09**: Map Claude Code denied tools to OpenCode `permission` deny patterns
- [ ] **OC-10**: Translate env var references in MCP `headers` to OpenCode `{env:VAR_NAME}` syntax instead of `${VAR_NAME}`
- [ ] **OC-11**: Avoid skill duplication: skip symlinks for skills that OpenCode will natively discover from `.claude/skills/` — only sync skills not already in Claude Code's directories

### Settings Preservation
- [ ] **PRES-01**: When writing settings.json (Gemini) or config.toml (Codex), preserve existing hooks and other non-synced fields instead of clobbering them

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

### v0.0.1 (Phases 1-8) — Complete

| Requirement | Phase | Status |
|-------------|-------|--------|
| CORE-01..05 | Phase 1 | Complete |
| SRC-01..06 | Phase 1 | Complete |
| ADP-01..03 | Phase 2 | Complete |
| CDX-01..06 | Phase 2 | Complete |
| GMN-01..06 | Phase 3 | Complete |
| OC-01..06 | Phase 3 | Complete |
| PLG-01..05 | Phase 4 | Complete |
| SAF-01..05 | Phase 5 | Complete |
| MCP-01..02 | Phase 6 | Complete |
| PKG-01..03 | Phase 7 | Complete |
| MULTI-01..10 | Phase 8 | Complete |

**v0.0.1 Coverage:** 54/54 requirements — delivered 2026-02-15

### v0.0.2 (Phases 9-11) — Complete

| Requirement | Phase | Status |
|-------------|-------|--------|
| PLGD-01..04 | Phase 9 | Complete |
| SCOPE-01..05 | Phase 9 | Complete |
| SYNC-01..04 | Phase 10 | Complete |
| ENV-01..03 | Phase 10 | Complete |
| STATE-01..03 | Phase 11 | Complete |

**v0.0.2 Coverage:** 19/19 requirements — delivered 2026-02-15

### v0.1.1 (Phases TBD) — Active

| Requirement | Phase | Status |
|-------------|-------|--------|
| RULES-01 | TBD | Pending |
| RULES-02 | TBD | Pending |
| RULES-03 | TBD | Pending |
| RULES-04 | TBD | Pending |
| CDX-07 | TBD | Pending |
| CDX-08 | TBD | Pending |
| CDX-09 | TBD | Pending |
| GMN-07 | TBD | Pending |
| GMN-08 | TBD | Pending |
| GMN-09 | TBD | Pending |
| GMN-10 | TBD | Pending |
| GMN-11 | TBD | Pending |
| GMN-12 | TBD | Pending |
| OC-07 | TBD | Pending |
| OC-08 | TBD | Pending |
| OC-09 | TBD | Pending |
| OC-10 | TBD | Pending |
| OC-11 | TBD | Pending |
| PRES-01 | TBD | Pending |

**v0.1.1 Coverage:** 0/19 requirements — in progress

---

*Requirements defined: 2026-02-13 (v1), 2026-02-15 (v0.0.1, v0.0.2), 2026-03-09 (v0.1.1)*
*v0.1.1 source: Research CLAUDE-CODE-LATEST.md, CODEX-LATEST.md, GEMINI-LATEST.md, OPENCODE-LATEST.md*
*Traceability updated: 2026-03-09*
