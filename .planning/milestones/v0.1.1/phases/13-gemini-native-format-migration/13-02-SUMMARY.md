---
phase: 13-gemini-native-format-migration
plan: 02
subsystem: adapters/gemini
tags: [gemini, cleanup, verification, native-format]
dependency_graph:
  requires: [13-01]
  provides: [gemini-stale-cleanup, phase13-verification]
  affects: [src/adapters/gemini.py, GEMINI.md]
tech_stack:
  added: []
  patterns: [post-migration-cleanup, safety-gated-cleanup]
key_files:
  created: [tests/verify_phase13_native_formats.py]
  modified: [src/adapters/gemini.py]
decisions:
  - "Cleanup only runs after all three native-format syncs succeed (safety constraint)"
  - "sync_all override in GeminiAdapter calls cleanup automatically post-sync"
  - "_write_subsection marked as legacy but retained for backward compatibility"
metrics:
  duration: "2m 36s"
  completed: "2026-03-09"
---

# Phase 13 Plan 02: Stale Subsection Cleanup and E2E Verification Summary

Added post-migration cleanup of legacy inlined Skills/Agents/Commands subsections from GEMINI.md with safety gating, and created comprehensive end-to-end verification covering all 5 Phase 13 requirements (66 checks, 0 failures).

## Tasks Completed

| Task | Name | Commit | Status |
|------|------|--------|--------|
| 1 | Add stale subsection cleanup to GEMINI.md | 0983b8b | Done |
| 2 | Create end-to-end verification script for Phase 13 | e8ae5b0 | Done |

## Changes Made

### Task 1: Stale Subsection Cleanup

Added three methods to `GeminiAdapter`:

- **`_cleanup_stale_subsections()`** -- Scans GEMINI.md for `<!-- HarnessSync:Skills -->`, `<!-- HarnessSync:Agents -->`, `<!-- HarnessSync:Commands -->` marker pairs and removes everything between and including the markers. Preserves the main rules managed section. Returns count of removed sections (0-3).

- **`cleanup_legacy_inline_sections()`** -- Public API wrapper around `_cleanup_stale_subsections()`. Safe to call multiple times (idempotent).

- **`sync_all()` override** -- Calls `super().sync_all(source_data)` first, then checks that skills, agents, and commands results all have `failed == 0`. Only then calls cleanup. If any native-format sync failed, cleanup is skipped to avoid data loss (inlined version serves as fallback).

Also marked `_write_subsection()` as legacy in its docstring (retained for backward compatibility).

### Task 2: End-to-End Verification Script

Created `tests/verify_phase13_native_formats.py` with 66 checks covering:

- **GMN-07** (7 checks): Skills written to `.gemini/skills/<name>/SKILL.md` with preserved frontmatter and body
- **GMN-08** (10 checks): Agents written to `.gemini/agents/<name>.md` with correct field mapping, color dropped, `<role>` tags stripped
- **GMN-09** (9 checks): Commands written to `.gemini/commands/<name>.toml` with `$ARGUMENTS` -> `{{args}}` mapping and namespaced subdirectory paths
- **GMN-11** (12 checks): MCP field passthrough (trust, includeTools, excludeTools, cwd) in settings.json
- **GMN-12** (14 checks): Stale subsection cleanup removes all markers and content while preserving rules
- **Integration** (14 checks): Full `sync_all` produces native files AND clean GEMINI.md simultaneously

## Verification Results

### Level 1 (Sanity)
- Import check: `from src.adapters.gemini import GeminiAdapter` -- PASS
- Cleanup removes all 3 subsection marker pairs -- PASS
- Rules managed section survives cleanup -- PASS
- Cleanup is idempotent (second call returns 0) -- PASS

### Level 2 (Proxy)
- `python3 tests/verify_phase13_native_formats.py` -- ALL 66 CHECKS PASSED
- Full sync_all produces native files at correct paths AND clean GEMINI.md -- PASS
- No data loss: rules preserved, native files contain correct content -- PASS
- Phase 12 integration tests (14 tests) -- PASS (regression check)

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

1. **Cleanup gated on zero failures across all three native syncs** -- If even one skill/agent/command fails to write its native file, the entire cleanup is skipped. This prevents the scenario where inlined content is removed but native files don't exist.

2. **sync_all override rather than modifying individual sync methods** -- Cleanup runs once after all syncs complete, not inline within each sync method. This is cleaner and matches the plan's explicit instruction.

3. **_write_subsection retained as legacy** -- Not removed despite being unused by current sync methods. Other code or tests may reference it. Docstring updated to note legacy status.

## Self-Check: PASSED
