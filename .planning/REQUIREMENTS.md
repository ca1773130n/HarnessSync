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

## v2 Requirements (Deferred)

- [ ] Bidirectional sync (target → Claude Code) with conflict detection
- [ ] 3-way merge strategies instead of overwrite
- [ ] Semantic agent → skill conversion (extract tools, adapt permissions intelligently)
- [ ] AI-assisted conflict resolution via Claude API
- [ ] Drift reports with scheduled diffs
- [ ] Profile support (work/home with different sync rules)
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

<!-- Updated by roadmapper -->

---
*Requirements defined: 2026-02-13*
*Source: Research FEATURES.md, SUMMARY.md, PROJECT.md*
