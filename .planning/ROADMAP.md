# HarnessSync Roadmap

## Overview

HarnessSync syncs Claude Code configuration to Codex, Gemini CLI, and OpenCode. v0.0.1 delivered the core plugin with hooks, slash commands, MCP server, and multi-account support. v0.0.2 added scope-aware MCP sync with plugin discovery. **v0.1.1** modernizes all three adapters to match the latest CLI versions -- fixing broken settings formats, adding rules directory discovery, migrating Gemini to native skills/agents/commands, and rewriting OpenCode's permission system.

**Phases:** 14 (11 complete, 3 in v0.1.1)
**Depth:** Standard (3 phases for v0.1.1)
**Coverage:** 47/47 v1 + 19/19 v0.0.2 + 19/19 v0.1.1 requirements mapped

---

## v0.0.1 Phases (Complete)

### Phase 1: Foundation & State Management

**Goal:** Establish core infrastructure with hash-based drift detection, OS-aware symlink creation, and Claude Code config discovery.

**Status:** Complete (2026-02-13)
**Requirements:** CORE-01, CORE-02, CORE-03, CORE-04, CORE-05, SRC-01, SRC-02, SRC-03, SRC-04, SRC-05, SRC-06
**Plans:** 4/4 complete
**Verification:** sanity (passed)

---

### Phase 2: Adapter Framework & Codex Sync

**Goal:** Create extensible adapter pattern and implement Codex adapter with full JSON-to-TOML translation, agent-to-skill conversion, and MCP server format mapping.

**Status:** Complete (2026-02-13)
**Requirements:** ADP-01, ADP-02, ADP-03, CDX-01, CDX-02, CDX-03, CDX-04, CDX-05, CDX-06
**Plans:** 3/3 complete
**Verification:** proxy (passed)

---

### Phase 3: Gemini & OpenCode Adapters

**Goal:** Implement remaining target adapters (Gemini with inline skills, OpenCode with native agent/command support) to validate adapter pattern extensibility.

**Status:** Complete (2026-02-13)
**Requirements:** GMN-01, GMN-02, GMN-03, GMN-04, GMN-05, GMN-06, OC-01, OC-02, OC-03, OC-04, OC-05, OC-06
**Plans:** 2/2 complete
**Verification:** proxy (passed)

---

### Phase 4: Plugin Interface (Commands, Hooks, Skills)

**Goal:** Deliver user-facing components for manual control (/sync), reactive auto-sync (PostToolUse hooks), and status visibility (/sync-status).

**Status:** Complete (2026-02-14)
**Requirements:** PLG-01, PLG-02, PLG-03, PLG-04, PLG-05
**Plans:** 3/3 complete
**Verification:** proxy (passed)

---

### Phase 5: Safety & Validation

**Goal:** Implement security validations (permission audits, secret detection, conflict warnings) and rollback capabilities before MVP release.

**Status:** Complete (2026-02-14)
**Requirements:** SAF-01, SAF-02, SAF-03, SAF-04, SAF-05
**Plans:** 3/3 complete
**Verification:** proxy (passed)

---

### Phase 6: MCP Server Integration

**Goal:** Expose sync capabilities as MCP tools for programmatic access by other agents and cross-CLI orchestration.

**Status:** Complete (2026-02-15)
**Requirements:** MCP-01, MCP-02
**Plans:** 2/2 complete
**Verification:** proxy (passed)

---

### Phase 7: Packaging & Distribution

**Goal:** Prepare plugin for marketplace distribution with proper structure validation, installation testing, and documentation.

**Status:** Complete (2026-02-15)
**Requirements:** PKG-01, PKG-02, PKG-03
**Plans:** 3/3 complete
**Verification:** proxy (passed)

---

### Phase 8: Multi-Account Support

**Goal:** Enable sync across multiple harness accounts with discovery, configuration, and account-scoped sync operations.

**Status:** Complete (2026-02-15)
**Requirements:** MULTI-01 through MULTI-10 (10 requirements)
**Plans:** 4/4 complete
**Verification:** proxy (passed)

---

## v0.0.2 Phases (Complete)

### Phase 9: Plugin Discovery & Scope-Aware Source Reading

**Goal:** Extend SourceReader to discover MCP servers from installed Claude Code plugins and implement 3-tier scope awareness (user/project/local) with proper precedence handling.

**Status:** Complete (2026-02-15)
**Dependencies:** Phase 1 (SourceReader exists), Phase 8 (account-aware infrastructure)
**Requirements:** PLGD-01, PLGD-02, PLGD-03, PLGD-04, SCOPE-01, SCOPE-02, SCOPE-03, SCOPE-04, SCOPE-05
**Plans:** 2/2 complete
**Verification:** proxy (passed)

---

### Phase 10: Scope-Aware Target Sync & Environment Translation

**Goal:** Implement scope-to-target mapping for Gemini and Codex adapters, translate environment variable syntax between Claude/Codex/Gemini formats, and detect unsupported transport types.

**Status:** Complete (2026-02-15)
**Dependencies:** Phase 9 (scope-tagged MCPs available), Phase 2 (Codex adapter), Phase 3 (Gemini adapter)
**Requirements:** SYNC-01, SYNC-02, SYNC-03, SYNC-04, ENV-01, ENV-02, ENV-03
**Plans:** 3/3 complete
**Verification:** proxy (passed)

---

### Phase 11: State Enhancements & Integration

**Goal:** Extend StateManager to track plugin versions for update-triggered re-sync, enhance /sync-status to display plugin-discovered MCPs with scope labels, and implement drift detection for plugin MCP changes.

**Status:** Complete (2026-02-15)
**Dependencies:** Phase 9 (plugin discovery), Phase 10 (scope-aware sync working)
**Requirements:** STATE-01, STATE-02, STATE-03
**Plans:** 2/2 complete
**Verification:** proxy (passed)

---

## v0.1.1 Phases (Milestone: Target CLI Modernization)

### Phase 12: Critical Fixes & Rules Discovery

**Goal:** Fix broken adapter outputs (Codex deprecated approval policy, Codex config filename, Gemini v1 settings keys, OpenCode permission system) and extend SourceReader to discover `.claude/rules/` directory content as a new config surface.

**Status:** Pending
**Dependencies:** Phase 1 (SourceReader), Phase 2 (Codex adapter), Phase 3 (Gemini/OpenCode adapters)
**Verification Level:** proxy

**Requirements:** RULES-01, RULES-02, RULES-03, RULES-04, CDX-07, CDX-08, GMN-10, OC-07, OC-08, OC-09

**Success Criteria:**
1. SourceReader returns content from `.claude/rules/*.md` and `~/.claude/rules/*.md` (including recursive subdirectories) alongside existing CLAUDE.md content
2. Rules with `paths:` YAML frontmatter are tagged with their path patterns in the output; rules without frontmatter load unconditionally
3. Codex adapter writes `approval_policy = 'on-request'` (not deprecated `'on-failure'`) when mapping Claude Code auto-approve settings
4. Codex adapter writes to `config.toml` (official name) instead of `codex.toml`
5. Gemini adapter writes `tools.allowed` and `tools.exclude` (v2 format) instead of `tools.allowedTools` and `tools.blockedTools` (v1 format)
6. OpenCode adapter writes `permission` (singular) with per-tool `allow`/`ask`/`deny` values instead of deprecated `permissions.mode` format
7. OpenCode adapter maps Claude Code allowed tools to `permission.bash` patterns (e.g., `"git *": "allow"`) and denied tools to deny patterns

---

### Phase 13: Gemini Native Format Migration

**Goal:** Migrate Gemini adapter from inlining skills/agents/commands into GEMINI.md to writing native format files (SKILL.md, agent .md, command .toml) that Gemini CLI discovers and loads natively with proper lazy-loading and activation.

**Status:** Pending
**Dependencies:** Phase 12 (rules discovery available for adapters, settings fix landed)
**Verification Level:** proxy

**Requirements:** GMN-07, GMN-08, GMN-09, GMN-11, GMN-12

**Success Criteria:**
1. Skills sync to `.gemini/skills/<name>/SKILL.md` files with `name` and `description` frontmatter instead of being inlined in GEMINI.md
2. Agents sync to `.gemini/agents/<name>.md` files with Gemini-compatible frontmatter (`name`, `description`, and optional `tools`, `model`, `max_turns`) instead of being inlined in GEMINI.md
3. Commands sync to `.gemini/commands/<name>.toml` files with `description` and `prompt` fields, with `$ARGUMENTS` mapped to `{{args}}`, instead of bullet points in GEMINI.md
4. MCP server configs pass through `trust`, `includeTools`, `excludeTools`, and `cwd` fields when present in source config
5. After migration to native formats, stale inlined skills/agents/commands sections are cleaned from GEMINI.md (only rules remain)

---

### Phase 14: Cross-Adapter Polish

**Goal:** Complete remaining targeted fixes across Codex and OpenCode adapters -- MCP field passthrough, env var translation, skill deduplication, and settings preservation -- ensuring adapters do not clobber non-synced config fields.

**Status:** Pending
**Dependencies:** Phase 12 (critical fixes landed), Phase 13 (Gemini migration validates the pattern)
**Verification Level:** proxy

**Requirements:** CDX-09, OC-10, OC-11, PRES-01

**Success Criteria:**
1. Codex MCP config passes through `cwd`, `enabled_tools`, and `disabled_tools` fields when present in source config
2. OpenCode MCP `headers` env var references use `{env:VAR_NAME}` syntax instead of `${VAR_NAME}`
3. OpenCode adapter skips skill symlinks for skills that already exist in `.claude/skills/` (which OpenCode natively discovers), avoiding duplicate skill loading
4. Writing Gemini `settings.json` preserves existing `hooks`, `security`, `general`, and other non-synced sections instead of clobbering them
5. Writing Codex `config.toml` preserves existing `[agents]`, `[profiles]`, `[features]`, and other non-synced sections instead of clobbering them

---

## Progress

| Phase | Status | Plans | Verification | Progress |
|-------|--------|-------|--------------|----------|
| 1 - Foundation & State Management | Complete | 4/4 | sanity | ██████████ 100% |
| 2 - Adapter Framework & Codex Sync | Complete | 3/3 | proxy | ██████████ 100% |
| 3 - Gemini & OpenCode Adapters | Complete | 2/2 | proxy | ██████████ 100% |
| 4 - Plugin Interface | Complete | 3/3 | proxy | ██████████ 100% |
| 5 - Safety & Validation | Complete | 3/3 | proxy | ██████████ 100% |
| 6 - MCP Server Integration | Complete | 2/2 | proxy | ██████████ 100% |
| 7 - Packaging & Distribution | Complete | 3/3 | proxy | ██████████ 100% |
| 8 - Multi-Account Support | Complete | 4/4 | proxy | ██████████ 100% |
| 9 - Plugin Discovery & Scope-Aware Reading | Complete | 2/2 | proxy | ██████████ 100% |
| 10 - Scope-Aware Sync & Env Translation | Complete | 3/3 | proxy | ██████████ 100% |
| 11 - State Enhancements & Integration | Complete | 2/2 | proxy | ██████████ 100% |
| 12 - Critical Fixes & Rules Discovery | Pending | 0/? | proxy | ░░░░░░░░░░ 0% |
| 13 - Gemini Native Format Migration | Pending | 0/? | proxy | ░░░░░░░░░░ 0% |
| 14 - Cross-Adapter Polish | Pending | 0/? | proxy | ░░░░░░░░░░ 0% |

---

## v0.1.1 Coverage

| Requirement | Phase | Status |
|-------------|-------|--------|
| RULES-01 | Phase 12 | Pending |
| RULES-02 | Phase 12 | Pending |
| RULES-03 | Phase 12 | Pending |
| RULES-04 | Phase 12 | Pending |
| CDX-07 | Phase 12 | Pending |
| CDX-08 | Phase 12 | Pending |
| GMN-10 | Phase 12 | Pending |
| OC-07 | Phase 12 | Pending |
| OC-08 | Phase 12 | Pending |
| OC-09 | Phase 12 | Pending |
| GMN-07 | Phase 13 | Pending |
| GMN-08 | Phase 13 | Pending |
| GMN-09 | Phase 13 | Pending |
| GMN-11 | Phase 13 | Pending |
| GMN-12 | Phase 13 | Pending |
| CDX-09 | Phase 14 | Pending |
| OC-10 | Phase 14 | Pending |
| OC-11 | Phase 14 | Pending |
| PRES-01 | Phase 14 | Pending |

**Coverage:** 19/19 v0.1.1 requirements mapped (100%)

---

## Integration Phase

Not required for v0.1.1. All phases use proxy verification with no deferred validations.

---

*v0.0.1 roadmap created: 2026-02-13*
*v0.0.1 complete: 2026-02-15 (8 phases, 24 plans)*
*v0.0.2 roadmap created: 2026-02-15*
*v0.0.2 complete: 2026-02-15 (3 phases, 7 plans, 19 requirements)*
*v0.1.1 roadmap created: 2026-03-09*
