---
phase: 12-critical-fixes-rules-discovery
plan: 01
subsystem: adapters
tags: [codex, gemini, opencode, config-format, permissions]

requires:
  - phase: none
    provides: existing adapter implementations
provides:
  - "Corrected Codex config filename (config.toml) and approval_policy (on-request)"
  - "Corrected Gemini tools config keys (exclude/allowed instead of blockedTools/allowedTools)"
  - "Rewritten OpenCode permission format (per-tool permission singular with allow/ask/deny)"
affects: [phase-13-gemini-native, phase-14-cross-adapter-polish]

tech-stack:
  added: []
  patterns: [per-tool-permission-mapping, bash-wildcard-pattern-extraction]

key-files:
  created: []
  modified:
    - src/adapters/codex.py
    - src/adapters/gemini.py
    - src/adapters/opencode.py
    - tests/verify_task2_gemini.py
    - tests/verify_task2_opencode.py
    - tests/verify_phase10_integration.py

key-decisions:
  - "OpenCode bash patterns use '*': 'ask' default when specific patterns are allowed"
  - "Old 'permissions' (plural) key deleted from config to prevent ambiguity"

patterns-established:
  - "TOOL_MAPPING class constant for Claude Code -> OpenCode tool name mapping"
  - "Bash pattern extraction: Bash(git commit:*) -> {\"git commit *\": \"allow\"}"

duration: 3min
completed: 2026-03-09
---

# Phase 12 Plan 01: Adapter Config Format Fixes Summary

**Fixed all three adapter outputs to match current official CLI documentation -- Codex uses config.toml with on-request policy, Gemini uses tools.exclude/allowed keys, OpenCode uses per-tool permission with wildcard bash patterns.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-09T01:27:12Z
- **Completed:** 2026-03-09T01:30:12Z
- **Tasks:** 2/2
- **Files modified:** 6

## Accomplishments

- Fixed Codex adapter: CONFIG_TOML constant changed from "codex.toml" to "config.toml", approval_policy from 'on-failure' to 'on-request'
- Fixed Gemini adapter: tools config keys changed from blockedTools/allowedTools to exclude/allowed (v2 format)
- Rewrote OpenCode adapter: replaced deprecated permissions.mode structure with per-tool permission (singular) format using allow/ask/deny values, including bash wildcard pattern support
- Updated all test files referencing deprecated key names (6 files total, no narrow fixes)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix Codex adapter config filename and approval policy** - `ca54f8f` (fix)
2. **Task 2: Fix Gemini adapter tools config keys and rewrite OpenCode permission format** - `24ae64f` (fix)

## Files Created/Modified

- `src/adapters/codex.py` - Fixed CONFIG_TOML constant and approval_policy value
- `src/adapters/gemini.py` - Updated tools config keys to v2 format (exclude/allowed)
- `src/adapters/opencode.py` - Rewrote sync_settings() with per-tool permission format and TOOL_MAPPING
- `tests/verify_task2_gemini.py` - Updated assertions for new Gemini key names
- `tests/verify_task2_opencode.py` - Updated assertions for new config.toml and permission format
- `tests/verify_phase10_integration.py` - Updated config.toml filename references

## Decisions Made

1. **OpenCode bash default policy:** When specific bash patterns are allowed (e.g., "git commit *": "allow"), a default "*": "ask" entry is added to ensure unlisted commands still prompt for approval. This is the conservative approach.
2. **Old permissions key cleanup:** When writing new `permission` (singular), the old `permissions` (plural) key is explicitly deleted from existing config to prevent ambiguity in OpenCode.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated test files with deprecated key references**
- **Found during:** Task 1 and Task 2
- **Issue:** Test files referenced old key names (codex.toml, blockedTools, allowedTools, permissions.mode) that would fail after adapter fixes
- **Fix:** Updated all test assertions to match new output format
- **Files modified:** tests/verify_task2_gemini.py, tests/verify_task2_opencode.py, tests/verify_phase10_integration.py
- **Verification:** grep confirmed no remaining deprecated key references in tests

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug fix in tests)
**Impact on plan:** Minor -- tests needed to match new adapter output

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- All three adapters now produce valid configuration matching current official documentation
- Phase 12 Plan 02 (rules discovery) and Plan 03 can proceed independently
- Phase 13 (Gemini native format migration) can build on the corrected tools config keys
- Phase 14 (cross-adapter polish) can build on the corrected permission format

---
*Phase: 12-critical-fixes-rules-discovery*
*Completed: 2026-03-09*
