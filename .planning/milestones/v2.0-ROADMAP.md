# HarnessSync Roadmap

## Overview

HarnessSync syncs Claude Code configuration to Codex, Gemini CLI, and OpenCode. v1.0 delivered the core plugin with hooks, slash commands, MCP server, and multi-account support. **v2.0** extends MCP discovery to include Claude Code plugins with proper scope-aware syncing (user/project/local scopes to target-native scopes).

**Phases:** 11 (8 complete, 3 in v2.0)
**Depth:** Standard (3-4 phases for v2.0)
**Coverage:** 47/47 v1 requirements + 19/19 v2.0 requirements mapped

---

## v1.0 Phases (Complete)

### Phase 1: Foundation & State Management ✓

**Goal:** Establish core infrastructure with hash-based drift detection, OS-aware symlink creation, and Claude Code config discovery.

**Status:** Complete (2026-02-13)
**Requirements:** CORE-01, CORE-02, CORE-03, CORE-04, CORE-05, SRC-01, SRC-02, SRC-03, SRC-04, SRC-05, SRC-06
**Plans:** 4/4 complete
**Verification:** sanity (passed)

---

### Phase 2: Adapter Framework & Codex Sync ✓

**Goal:** Create extensible adapter pattern and implement Codex adapter with full JSON→TOML translation, agent→skill conversion, and MCP server format mapping.

**Status:** Complete (2026-02-13)
**Requirements:** ADP-01, ADP-02, ADP-03, CDX-01, CDX-02, CDX-03, CDX-04, CDX-05, CDX-06
**Plans:** 3/3 complete
**Verification:** proxy (passed)

---

### Phase 3: Gemini & OpenCode Adapters ✓

**Goal:** Implement remaining target adapters (Gemini with inline skills, OpenCode with native agent/command support) to validate adapter pattern extensibility.

**Status:** Complete (2026-02-13)
**Requirements:** GMN-01, GMN-02, GMN-03, GMN-04, GMN-05, GMN-06, OC-01, OC-02, OC-03, OC-04, OC-05, OC-06
**Plans:** 2/2 complete
**Verification:** proxy (passed)

---

### Phase 4: Plugin Interface (Commands, Hooks, Skills) ✓

**Goal:** Deliver user-facing components for manual control (/sync), reactive auto-sync (PostToolUse hooks), and status visibility (/sync-status).

**Status:** Complete (2026-02-14)
**Requirements:** PLG-01, PLG-02, PLG-03, PLG-04, PLG-05
**Plans:** 3/3 complete
**Verification:** proxy (passed)

---

### Phase 5: Safety & Validation ✓

**Goal:** Implement security validations (permission audits, secret detection, conflict warnings) and rollback capabilities before MVP release.

**Status:** Complete (2026-02-14)
**Requirements:** SAF-01, SAF-02, SAF-03, SAF-04, SAF-05
**Plans:** 3/3 complete
**Verification:** proxy (passed)

---

### Phase 6: MCP Server Integration ✓

**Goal:** Expose sync capabilities as MCP tools for programmatic access by other agents and cross-CLI orchestration.

**Status:** Complete (2026-02-15)
**Requirements:** MCP-01, MCP-02
**Plans:** 2/2 complete
**Verification:** proxy (passed)

---

### Phase 7: Packaging & Distribution ✓

**Goal:** Prepare plugin for marketplace distribution with proper structure validation, installation testing, and documentation.

**Status:** Complete (2026-02-15)
**Requirements:** PKG-01, PKG-02, PKG-03
**Plans:** 3/3 complete
**Verification:** proxy (passed)

---

### Phase 8: Multi-Account Support ✓

**Goal:** Enable sync across multiple harness accounts with discovery, configuration, and account-scoped sync operations.

**Status:** Complete (2026-02-15)
**Requirements:** MULTI-01 through MULTI-10 (10 requirements)
**Plans:** 4/4 complete
**Verification:** proxy (passed)

---

## v2.0 Phases (Milestone: Plugin & MCP Scope Sync)

### Phase 9: Plugin Discovery & Scope-Aware Source Reading ✓

**Goal:** Extend SourceReader to discover MCP servers from installed Claude Code plugins and implement 3-tier scope awareness (user/project/local) with proper precedence handling.

**Status:** Complete (2026-02-15)
**Dependencies:** Phase 1 (SourceReader exists), Phase 8 (account-aware infrastructure)

**Requirements:** PLGD-01, PLGD-02, PLGD-03, PLGD-04, SCOPE-01, SCOPE-02, SCOPE-03, SCOPE-04, SCOPE-05

**Plans:** 2/2 complete
**Verification:** proxy (passed)

Plans:
- [x] 09-01-PLAN.md — Plugin MCP discovery with dual-format support and ${CLAUDE_PLUGIN_ROOT} expansion
- [x] 09-02-PLAN.md — 3-tier scope-aware MCP discovery with precedence and origin tagging

---

### Phase 10: Scope-Aware Target Sync & Environment Translation ✓

**Goal:** Implement scope-to-target mapping for Gemini and Codex adapters, translate environment variable syntax between Claude/Codex/Gemini formats, and detect unsupported transport types.

**Status:** Complete (2026-02-15)
**Dependencies:** Phase 9 (scope-tagged MCPs available), Phase 2 (Codex adapter), Phase 3 (Gemini adapter)

**Requirements:** SYNC-01, SYNC-02, SYNC-03, SYNC-04, ENV-01, ENV-02, ENV-03

**Plans:** 3/3 complete
**Verification:** proxy (passed)

Plans:
- [x] 10-01-PLAN.md -- Env var translator utility and transport detection module
- [x] 10-02-PLAN.md -- Scope-aware adapter interface with Codex/Gemini/OpenCode routing
- [x] 10-03-PLAN.md -- Integration test verifying all 7 requirements end-to-end

---

### Phase 11: State Enhancements & Integration ✓

**Goal:** Extend StateManager to track plugin versions for update-triggered re-sync, enhance /sync-status to display plugin-discovered MCPs with scope labels, and implement drift detection for plugin MCP changes.

**Status:** Complete (2026-02-15)
**Dependencies:** Phase 9 (plugin discovery), Phase 10 (scope-aware sync working)

**Requirements:** STATE-01, STATE-02, STATE-03

**Plans:** 2/2 complete
**Verification:** proxy (passed)

Plans:
- [x] 11-01-PLAN.md -- StateManager plugin tracking + orchestrator metadata persistence
- [x] 11-02-PLAN.md -- /sync-status MCP source grouping + integration tests

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

---

## v2.0 Coverage

| Requirement | Phase | Status |
|-------------|-------|--------|
| PLGD-01 | Phase 9 | Complete |
| PLGD-02 | Phase 9 | Complete |
| PLGD-03 | Phase 9 | Complete |
| PLGD-04 | Phase 9 | Complete |
| SCOPE-01 | Phase 9 | Complete |
| SCOPE-02 | Phase 9 | Complete |
| SCOPE-03 | Phase 9 | Complete |
| SCOPE-04 | Phase 9 | Complete |
| SCOPE-05 | Phase 9 | Complete |
| SYNC-01 | Phase 10 | Complete |
| SYNC-02 | Phase 10 | Complete |
| SYNC-03 | Phase 10 | Complete |
| SYNC-04 | Phase 10 | Complete |
| ENV-01 | Phase 10 | Complete |
| ENV-02 | Phase 10 | Complete |
| ENV-03 | Phase 10 | Complete |
| STATE-01 | Phase 11 | Complete |
| STATE-02 | Phase 11 | Complete |
| STATE-03 | Phase 11 | Complete |

**Coverage:** 19/19 v2.0 requirements mapped (100%)

---

## Integration Phase

Not required for v2.0. All phases use proxy verification with no deferred validations.

---

*v1.0 roadmap created: 2026-02-13*
*v1.0 complete: 2026-02-15 (8 phases, 24 plans)*
*v2.0 roadmap created: 2026-02-15*
*Phase 9 complete: 2026-02-15 (2 plans)*
*Phase 10 complete: 2026-02-15 (3 plans)*
*Phase 11 complete: 2026-02-15 (2 plans)*
*v2.0 complete: 2026-02-15 (3 phases, 7 plans, 19 requirements)*
