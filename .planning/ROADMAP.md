# HarnessSync Roadmap

## Overview

Transform the proven cc2all sync script into a production-ready Claude Code plugin with hooks, slash commands, and MCP server integration. The roadmap prioritizes foundation-first (state management, symlink handling) then proves the adapter pattern with Codex (most complex), extends to Gemini/OpenCode, adds user-facing interfaces, validates security, and packages for distribution.

**Phases:** 7
**Depth:** Standard (5-8 phases)
**Coverage:** 44/44 v1 requirements mapped

---

## Phase 1: Foundation & State Management

**Goal:** Establish core infrastructure with hash-based drift detection, OS-aware symlink creation, and Claude Code config discovery.

**Dependencies:** None (starting point)

**Requirements:** CORE-01, CORE-02, CORE-03, CORE-04, CORE-05, SRC-01, SRC-02, SRC-03, SRC-04, SRC-05, SRC-06

**Plans:** 4 plans

Plans:
- [ ] 01-01-PLAN.md — Core utilities: Logger, SHA256 hashing, OS-aware symlink with fallback chain
- [ ] 01-02-PLAN.md — State manager with atomic writes, per-target tracking, drift detection
- [ ] 01-03-PLAN.md — Source reader discovering all 6 Claude Code config types
- [ ] 01-04-PLAN.md — Plugin manifest, cc2all rename, integration smoke test

**Success Criteria:**
1. State manager tracks sync timestamps and file hashes (SHA256) for all target configs in JSON format
2. OS-aware symlink creation succeeds on macOS/Linux (native) and Windows (junction fallback, copy with marker as last resort)
3. Source reader discovers all Claude Code configs (CLAUDE.md, skills, agents, commands, MCP servers, settings) from both user scope (~/.claude/) and project scope (.claude/)
4. Logger produces colored output with summary statistics (synced/skipped/error/cleaned counts) and audit trail
5. All references to cc2all renamed to HarnessSync across codebase

**Verification Level:** sanity

---

## Phase 2: Adapter Framework & Codex Sync

**Goal:** Create extensible adapter pattern and implement Codex adapter with full JSON→TOML translation, agent→skill conversion, and MCP server format mapping.

**Dependencies:** Phase 1 (needs source reader, state manager, path utilities)

**Requirements:** ADP-01, ADP-02, ADP-03, CDX-01, CDX-02, CDX-03, CDX-04, CDX-05, CDX-06

**Plans:** 3 plans

Plans:
- [ ] 02-01-PLAN.md — Adapter framework: ABC base class, decorator registry, SyncResult dataclass, TOML writer utility
- [ ] 02-02-PLAN.md — Codex adapter: rules to AGENTS.md, skills symlinks, agent-to-skill and command-to-skill conversion
- [ ] 02-03-PLAN.md — Codex adapter: MCP server JSON-to-TOML translation, permission mapping, integration verification

**Success Criteria:**
1. Abstract adapter base class defines sync_rules(), sync_skills(), sync_agents(), sync_commands(), sync_mcp(), sync_settings() interface
2. Adapter registry discovers and routes to target-specific adapters without modifying core engine
3. Codex adapter translates MCP servers from JSON to TOML [mcp_servers."name"] format with env var preservation
4. Codex adapter converts Claude Code agents to SKILL.md format in .codex/skills/agent-{name}/ with extracted descriptions
5. Codex adapter maps Claude Code permission settings to Codex sandbox levels (read-only/workspace-write/danger-full-access) with conservative defaults
6. Each adapter returns structured sync results (synced/skipped/failed/adapted counts with specific file paths)

**Verification Level:** proxy

---

## Phase 3: Gemini & OpenCode Adapters

**Goal:** Implement remaining target adapters (Gemini with inline skills, OpenCode with native agent/command support) to validate adapter pattern extensibility.

**Dependencies:** Phase 2 (needs adapter base class, registry pattern proven)

**Requirements:** GMN-01, GMN-02, GMN-03, GMN-04, GMN-05, GMN-06, OC-01, OC-02, OC-03, OC-04, OC-05, OC-06

**Plans:** 2 plans

Plans:
- [ ] 03-01-PLAN.md — Gemini adapter: GEMINI.md inline content (rules, skills, agents, commands), settings.json MCP translation, permission mapping, write_json_atomic utility
- [ ] 03-02-PLAN.md — OpenCode adapter: symlink-based sync (skills, agents, commands), opencode.json MCP translation, permission mapping, 3-adapter integration verification

**Success Criteria:**
1. Gemini adapter inlines skills content into GEMINI.md (strips YAML frontmatter, adds section headers) since Gemini cannot use symlinks
2. Gemini adapter translates MCP servers to settings.json mcpServers format with npx mcp-remote wrapper for URL types
3. OpenCode adapter creates symlinks for skills/agents/commands to .opencode/ directories with stale symlink cleanup
4. OpenCode adapter translates MCP servers to opencode.json format with type: "remote" for URL servers
5. All three adapters (Codex, Gemini, OpenCode) successfully sync a test project with rules, 3 skills, 2 agents, 1 command, 2 MCP servers, and permission settings
6. Permission mapping for all adapters uses conservative translation (Claude "deny" → skip tool in target, warn on permission downgrades)

**Verification Level:** proxy

---

## Phase 4: Plugin Interface (Commands, Hooks, Skills)

**Goal:** Deliver user-facing components for manual control (/sync), reactive auto-sync (PostToolUse hooks), and status visibility (/sync-status).

**Dependencies:** Phase 3 (needs working sync engine with all adapters)

**Requirements:** PLG-01, PLG-02, PLG-03, PLG-04, PLG-05

**Plans:** 3 plans

Plans:
- [ ] 04-01-PLAN.md — Orchestrator, file locking, debouncing, and diff formatter (foundation for commands/hooks)
- [ ] 04-02-PLAN.md — /sync and /sync-status slash commands with argument parsing, dry-run mode
- [ ] 04-03-PLAN.md — PostToolUse hook for auto-sync, hooks.json configuration, plugin.json update

**Success Criteria:**
1. /sync slash command syncs all targets with optional scope argument (user/project/all) and returns summary statistics
2. /sync-status slash command shows last sync time per target, drift detection (config modified outside HarnessSync), and file hash comparison
3. PostToolUse hook triggers auto-sync when Claude Code writes to config files (CLAUDE.md, .mcp.json, skills/, agents/, commands/, settings.json)
4. Hook implements 3-second debounce (skip if last sync <3s ago) and file-based locking (~/.harnesssync/sync.lock) to prevent concurrent syncs
5. Dry run mode (--dry-run flag) previews changes without writing, showing diff-like output for rules/skills/MCP changes

**Verification Level:** proxy

---

## Phase 5: Safety & Validation

**Goal:** Implement security validations (permission audits, secret detection, conflict warnings) and rollback capabilities before MVP release.

**Dependencies:** Phase 4 (needs full plugin interface to test validation flows)

**Requirements:** SAF-01, SAF-02, SAF-03, SAF-04, SAF-05

**Plans:** 3 plans

Plans:
- [ ] 05-01-PLAN.md — Backup manager with timestamped backup/rollback and symlink cleaner for broken link removal
- [ ] 05-02-PLAN.md — Conflict detector (hash-based drift) and secret detector (keyword+regex env var scanning)
- [ ] 05-03-PLAN.md — Compatibility reporter and orchestrator/command integration of all safety features

**Success Criteria:**
1. Pre-sync backup creates timestamped copies of target configs in ~/.harnesssync/backups/ and enables rollback on failure
2. Conflict detection warns when target configs have SHA256 hash mismatch from last recorded sync (manual edits detected)
3. Secret detection scans env vars for patterns (API_KEY, SECRET, PASSWORD, TOKEN) and blocks sync with warning unless --allow-secrets flag used
4. Sync compatibility report shows what mapped cleanly, what was adapted (with explanation), and what couldn't be synced per target
5. Stale symlink cleanup removes broken symlinks in .codex/skills/, .opencode/skills/, .opencode/agents/, .opencode/commands/ after every sync

**Verification Level:** proxy

---

## Phase 6: MCP Server Integration

**Goal:** Expose sync capabilities as MCP tools for programmatic access by other agents and cross-CLI orchestration.

**Dependencies:** Phase 5 (needs complete, validated sync engine)

**Requirements:** MCP-01, MCP-02

**Plans:** 2 plans

Plans:
- [ ] 06-01-PLAN.md — MCP protocol foundation: stdio transport, JSON-RPC 2.0 handler, tool schemas with manual validation
- [ ] 06-02-PLAN.md — Tool handlers bridging MCP to SyncOrchestrator, server entry point with worker thread concurrency

**Success Criteria:**
1. MCP server exposes sync_all, sync_target, get_status tools with JSON schema validation
2. MCP server returns structured sync results (targets synced, items per target, errors with file paths and reasons)
3. External agent can invoke sync_target("codex") and receive confirmation within 5 seconds for typical project
4. MCP server handles concurrent requests gracefully (queues syncs, returns status for in-progress operations)

**Verification Level:** proxy

---

## Phase 7: Packaging & Distribution

**Goal:** Prepare plugin for marketplace distribution with proper structure validation, installation testing, and documentation.

**Dependencies:** Phase 6 (needs complete feature set)

**Requirements:** PKG-01, PKG-02, PKG-03

**Success Criteria:**
1. Plugin passes `claude plugin validate` with no errors (correct directory structure, valid plugin.json, hooks config)
2. Plugin published to Claude Code marketplace with marketplace.json containing absolute URLs and proper metadata
3. Plugin installable from GitHub repository via `/plugin install github:username/HarnessSync`
4. install.sh creates target directories (~/.codex/, ~/.gemini/, ~/.opencode/), detects shell (bash/zsh), and configures shell integration
5. Installation testing succeeds on macOS (native), Linux (native), and Windows (WSL2, native with junction fallback)

**Verification Level:** proxy

---

## Progress

| Phase | Status | Plans | Verification | Progress |
|-------|--------|-------|--------------|----------|
| 1 - Foundation & State Management | Complete | 4/4 | sanity | ██████████ 100% |
| 2 - Adapter Framework & Codex Sync | Complete | 3/3 | proxy | ██████████ 100% |
| 3 - Gemini & OpenCode Adapters | Complete | 2/2 | proxy | ██████████ 100% |
| 4 - Plugin Interface | Complete | 3/3 | proxy | ██████████ 100% |
| 5 - Safety & Validation | Complete | 3/3 | proxy | ██████████ 100% |
| 6 - MCP Server Integration | Planned | 0/2 | proxy | ░░░░░░░░░░ 0% |
| 7 - Packaging & Distribution | Pending | 0/TBD | proxy | ░░░░░░░░░░ 0% |

---

*Roadmap created: 2026-02-13*
*Phase 1 planned: 2026-02-13*
*Phase 2 planned: 2026-02-13*
*Phase 2 complete: 2026-02-13*
*Phase 3 planned: 2026-02-13*
*Phase 3 complete: 2026-02-13*
*Phase 4 planned: 2026-02-14*
*Phase 4 complete: 2026-02-14*
*Phase 5 planned: 2026-02-14*
*Phase 5 complete: 2026-02-14*
*Next: `/grd:plan-phase 6`*
