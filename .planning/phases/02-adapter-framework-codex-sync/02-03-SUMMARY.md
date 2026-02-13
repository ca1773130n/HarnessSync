---
phase: 02-adapter-framework-codex-sync
plan: 03
subsystem: adapter
tags: [codex, mcp, toml, permissions, security, python310-compat]

# Dependency graph
requires:
  - phase: 02-adapter-framework-codex-sync
    provides: Adapter framework, TOML writer, Codex adapter stubs
provides:
  - Complete Codex adapter with all 6 sync methods (rules, skills, agents, commands, mcp, settings)
  - MCP server JSON-to-TOML translation with env var preservation
  - Conservative permission mapping (Claude Code -> Codex sandbox modes)
  - Python 3.10 compatible TOML parser (parse_toml_simple, read_toml_safe)
affects: [phase-03-main-sync-orchestration, phase-04-watch-mode]

# Tech tracking
tech-stack:
  added: [toml-parser-simple]
  patterns: [config-merge-preservation, conservative-permission-mapping, python310-polyfill]

key-files:
  created: []
  modified:
    - src/adapters/codex.py (added sync_mcp, sync_settings, _read_existing_config, _build_config_toml)
    - src/utils/toml_writer.py (added parse_toml_simple, _parse_toml_value, read_toml_safe)

key-decisions:
  - "Added minimal TOML parser for Python 3.10 compatibility (tomllib requires 3.11+)"
  - "Conservative permission mapping: ANY denied tool -> read-only sandbox (never auto-maps to danger-full-access)"
  - "MCP servers merge with existing config preserving both settings and other servers"
  - "Environment variables preserved as literal ${VAR} strings (no expansion during sync)"

patterns-established:
  - "Config merge pattern: read existing -> merge changes -> write atomically"
  - "Security-first permission mapping: default to most restrictive when ambiguous"
  - "Graceful Python version compatibility via minimal stdlib reimplementation"

# Metrics
duration: 5.5min
completed: 2026-02-13
---

# Phase 2 Plan 3: Codex Integration & Verification Summary

**Complete Codex adapter with MCP-to-TOML translation, conservative permission mapping, and end-to-end Phase 2 integration verified across all 6 config types**

## Performance

- **Duration:** 5.5 min (5 min 27 sec)
- **Started:** 2026-02-13T08:57:09Z
- **Completed:** 2026-02-13T09:02:34Z
- **Tasks:** 2 completed
- **Files modified:** 2

## Accomplishments
- Implemented CodexAdapter.sync_mcp with JSON-to-TOML translation, env var preservation, and config merging
- Implemented CodexAdapter.sync_settings with conservative permission mapping (deny -> read-only)
- Added Python 3.10 compatible TOML parser (parse_toml_simple) to handle tomllib absence
- Full Phase 2 integration test passed: 7 items synced, 5 adapted, 0 failed across all 6 config types

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement MCP translation and permission mapping** - `1f55572` (feat)
2. **Task 2: Run Phase 2 integration verification** - No code changes (verification-only)

**Plan metadata:** (will be added in final commit)

## Files Created/Modified
- `src/adapters/codex.py` - Added sync_mcp (MCP server translation), sync_settings (permission mapping), helper methods
- `src/utils/toml_writer.py` - Added parse_toml_simple, _parse_toml_value, read_toml_safe for Python 3.10 compatibility

## Decisions Made

**1. Python 3.10 TOML Parser (Blocking Issue Fix)**
- **Context:** Python 3.10 lacks tomllib (added in 3.11), blocking verification tests
- **Decision:** Implemented minimal TOML parser (parse_toml_simple) instead of adding dependency
- **Rationale:** Maintains zero-dependency constraint; only need to parse config.toml we generate
- **Deviation:** Rule 3 (auto-fix blocking issue)

**2. Conservative Permission Mapping**
- **Context:** Claude Code permissions need mapping to Codex sandbox modes
- **Decision:** ANY denied tool -> read-only sandbox (most restrictive)
- **Rationale:** Never downgrade security; user must manually enable danger-full-access
- **Research:** Follows Recommendation 4 from 02-RESEARCH.md

**3. Config Merge Strategy**
- **Context:** Multiple sync operations should not overwrite each other's changes
- **Decision:** Always read existing config, merge changes, write atomically
- **Rationale:** Supports incremental sync (settings then MCP, or vice versa)

**4. Environment Variable Preservation**
- **Context:** MCP configs contain ${VAR} references
- **Decision:** Preserve as literal strings, no expansion during sync
- **Rationale:** Target CLI expands at runtime; sync-time expansion would break configs

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added Python 3.10 TOML parser**
- **Found during:** Task 1 verification
- **Issue:** Python 3.10 lacks tomllib module (added in 3.11+), causing import errors
- **Fix:** Implemented parse_toml_simple with support for basic types, tables, nested tables
- **Files modified:** src/utils/toml_writer.py
- **Verification:** All 8 Task 1 tests + 7-step integration test pass
- **Committed in:** 1f55572 (noted in commit message)

---

**Total deviations:** 1 auto-fixed (Rule 3 - Blocking)
**Impact on plan:** Minimal - added ~100 lines of TOML parsing code, maintains zero-dep constraint

## Issues Encountered
None - plan executed smoothly with one blocking issue auto-fixed per deviation rules.

## User Setup Required
None - no external service configuration required.

## Verification Results

### Task 1: MCP + Settings (8 tests)
1. sync_mcp stdio server - PASS
2. Env var preservation + merge - PASS
3. sync_mcp HTTP server - PASS
4. sync_mcp empty - PASS
5. sync_settings conservative mapping - PASS
6. sync_settings permissive mapping - PASS
7. sync_settings empty - PASS
8. Settings + MCP coexistence - PASS

### Task 2: Phase 2 Integration (7 steps)
1. Rules synced (2 files -> AGENTS.md with markers) - PASS
2. Skills synced (symlink created) - PASS
3. Agents converted (SKILL.md with role extraction) - PASS
4. Commands converted (SKILL.md with full body) - PASS
5. MCP translated (2 servers in valid TOML) - PASS
6. Settings mapped (read-only sandbox for deny) - PASS
7. Idempotency verified (skills skipped on re-sync) - PASS

**Integration Summary:** 7 synced, 5 adapted, 0 failed

## Phase 2 Requirements Coverage

All 9 Phase 2 requirements now delivered:

**Adapter Framework (Plan 02-01):**
- ADP-01: AdapterBase ABC with 6 sync methods ✓
- ADP-02: AdapterRegistry decorator-based registration ✓
- ADP-03: SyncResult dataclass with tracking ✓

**Codex Adapter (Plans 02-02 & 02-03):**
- CDX-01: Rules → AGENTS.md with markers ✓
- CDX-02: Skills → symlinks in .agents/skills/ ✓
- CDX-03: Agents → SKILL.md with role extraction ✓
- CDX-04: Commands → SKILL.md with cmd- prefix ✓
- CDX-05: MCP servers → config.toml with env var preservation ✓
- CDX-06: Settings → sandbox_mode/approval_policy (conservative) ✓

## Next Phase Readiness

**Phase 2 Complete** - All 3 plans executed successfully:
- 02-01: Adapter framework and TOML utilities
- 02-02: Codex adapter (rules, skills, agents, commands)
- 02-03: Codex adapter (MCP, settings) + integration verification

**Ready for Phase 3:** Main sync orchestration
- Implement SyncOrchestrator to coordinate SourceReader + AdapterRegistry
- Add CLI commands (init, sync, status)
- Add dry-run mode and logging

**No blockers** - All Phase 2 verification passed, zero dependency constraint maintained, Python 3.10+ compatible

## Self-Check: PASSED

All claims verified:
- Modified files exist: src/adapters/codex.py, src/utils/toml_writer.py ✓
- Commit 1f55572 exists in repository ✓
- All 8 Task 1 verification tests passed ✓
- All 7 Phase 2 integration tests passed ✓

---
*Phase: 02-adapter-framework-codex-sync*
*Completed: 2026-02-13*
