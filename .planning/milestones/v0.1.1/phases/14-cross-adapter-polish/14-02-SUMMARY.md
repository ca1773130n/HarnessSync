---
phase: 14-cross-adapter-polish
plan: 02
subsystem: adapters
tags: [opencode, codex, gemini, toml, skill-dedup, config-preservation]

requires:
  - phase: 14-01
    provides: cwd passthrough and header env var translation
provides:
  - OpenCode skill deduplication for natively discovered .claude/skills/
  - Non-destructive Codex config.toml writing with section preservation
  - Verification tests confirming Codex and Gemini config preservation
affects: [sync-pipeline, adapter-stability]

tech-stack:
  added: []
  patterns: [raw-text-section-preservation, is_relative_to-path-check]

key-files:
  created:
    - tests/verify_phase14_preservation.py
  modified:
    - src/adapters/opencode.py
    - src/adapters/codex.py

key-decisions:
  - "Raw text preservation for TOML sections (not parsed/re-serialized) to maintain user formatting"
  - "is_relative_to() for skill path check (Python 3.9+ guaranteed)"
  - "claude_skills_dir computed once outside loop for efficiency"

patterns-established:
  - "Extract-preserve-reemit: read raw file, extract non-managed content, re-emit after managed sections"
  - "Skill dedup by path ancestry: check if source is under natively discovered directory"

duration: 3min
completed: 2026-03-09
---

# Phase 14 Plan 02: OpenCode Skill Dedup and Config Preservation Summary

**OpenCode skips natively discovered .claude/skills/ to prevent duplicates; Codex config.toml writes now preserve user-defined [agents], [profiles], [features] sections intact.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-09T02:06:36Z
- **Completed:** 2026-03-09T02:09:10Z
- **Tasks:** 2/2
- **Files modified:** 3

## Accomplishments

- OpenCode `sync_skills()` skips skills whose source path is under `project_dir/.claude/skills/` with descriptive skip message (OC-11)
- Codex `_write_mcp_to_path()` and `sync_settings()` both preserve non-managed TOML sections via raw-text extraction (PRES-01)
- Added `_extract_unmanaged_toml()` method that identifies HarnessSync-managed content (header comments, sandbox_mode, approval_policy, [mcp_servers.*]) and preserves everything else verbatim
- Gemini settings.json preservation confirmed via test (no code change needed -- JSON dict-merge already works)
- Verification test covers all three adapters' preservation behavior

## Task Commits

Each task was committed atomically:

1. **Task 1: Skip natively discovered skills in OpenCode adapter** - `dd60b5b` (feat)
2. **Task 2: Preserve non-managed TOML sections in Codex config writes** - `defafca` (feat)

## Files Created/Modified

- `src/adapters/opencode.py` - Added claude_skills_dir check in sync_skills() loop (563 lines)
- `src/adapters/codex.py` - Added _extract_unmanaged_toml(), updated _build_config_toml() and both callers (780 lines)
- `tests/verify_phase14_preservation.py` - Round-trip tests for Codex MCP write, Codex settings, and Gemini settings preservation (138 lines)

## Decisions Made

- **Raw text preservation:** Non-managed TOML sections are preserved as raw text (not parsed and re-serialized) to maintain user formatting, comments, and whitespace
- **Path ancestry check:** Used `Path.is_relative_to()` instead of string comparison for robustness with symlinks and normalized paths
- **Loop-external computation:** `claude_skills_dir` is computed once before the skills loop rather than inside it

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 14 is now complete (both plans executed). All v0.1.1 adapter polish requirements (CDX-09, OC-10, OC-11, PRES-01) are implemented and verified.

## Self-Check: PASSED

- [x] src/adapters/opencode.py exists (563 lines >= 520 min)
- [x] src/adapters/codex.py exists (780 lines >= 720 min)
- [x] tests/verify_phase14_preservation.py exists (138 lines >= 40 min)
- [x] Commit dd60b5b found
- [x] Commit defafca found
- [x] OC-11 verification passed
- [x] PRES-01 verification passed

---
*Phase: 14-cross-adapter-polish*
*Completed: 2026-03-09*
