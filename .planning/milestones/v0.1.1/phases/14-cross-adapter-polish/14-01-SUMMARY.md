---
phase: 14-cross-adapter-polish
plan: 01
subsystem: adapters
tags: [toml, opencode, env-vars, mcp, headers]

# Dependency graph
requires:
  - phase: 12-critical-fixes-rules-discovery
    provides: "Updated adapter methods and env_translator utilities"
provides:
  - "cwd field passthrough in Codex TOML MCP formatter"
  - "translate_env_vars_for_opencode_headers() utility function"
  - "OpenCode adapter header env var translation in sync_mcp()"
affects: [14-02-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns: ["Syntax translation pattern for env var format differences between CLIs"]

key-files:
  created: []
  modified:
    - src/utils/toml_writer.py
    - src/utils/env_translator.py
    - src/adapters/opencode.py

key-decisions:
  - "cwd field added after args array, before boolean flags in TOML output order"
  - "Reused existing VAR_PATTERN regex for header translation (no new regex)"
  - "Default values stripped with warning -- OpenCode {env:VAR} does not support defaults"
  - "Translation applied only in sync_mcp() remote branch; sync_mcp_scoped() inherits via delegation"

patterns-established:
  - "Syntax translation: regex-based env var format conversion between CLI syntaxes"

# Metrics
duration: 1min
completed: 2026-03-09
---

# Phase 14 Plan 01: MCP Field Passthrough and Header Env Var Translation Summary

**Added cwd field support to Codex TOML formatter and ${VAR} to {env:VAR} translation for OpenCode MCP headers**

## Performance

- **Duration:** 1 min
- **Started:** 2026-03-09T02:03:14Z
- **Completed:** 2026-03-09T02:04:35Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments
- CDX-09: format_mcp_server_toml() now emits `cwd = "path"` for MCP servers with a working directory field
- OC-10: New translate_env_vars_for_opencode_headers() converts `${VAR}` to `{env:VAR}` and strips `${VAR:-default}` with warnings
- OpenCode adapter sync_mcp() applies header translation for remote servers, with warnings captured in SyncResult

## Task Commits

Each task was committed atomically:

1. **Task 1: Add cwd field to TOML formatter and OpenCode header env var translation** - `11bda84` (feat)
2. **Task 2: Wire OpenCode adapter to translate headers in sync_mcp** - `4857a2c` (feat)

## Files Created/Modified
- `src/utils/toml_writer.py` - Added cwd string field passthrough in format_mcp_server_toml()
- `src/utils/env_translator.py` - Added translate_env_vars_for_opencode_headers() function
- `src/adapters/opencode.py` - Updated import and sync_mcp() to translate header env vars

## Decisions Made
- Placed cwd field after args array and before boolean flags in TOML output ordering (matches Codex docs field order)
- Reused existing VAR_PATTERN regex constant for consistency with translate_env_vars_for_codex()
- Default value stripping emits per-header warning with the stripped value for user awareness
- No changes needed in sync_mcp_scoped() since it delegates to sync_mcp() which handles translation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Plan 14-02 (OC-11 skill dedup and PRES-01 config preservation) can proceed
- All existing tests and inline assertions continue to pass
- No regressions in enabled_tools/disabled_tools TOML output

---
*Phase: 14-cross-adapter-polish*
*Completed: 2026-03-09*
