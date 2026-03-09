---
phase: 14-cross-adapter-polish
wave: all
plans_reviewed: [14-01, 14-02]
timestamp: 2026-03-09T03:00:00Z
blockers: 0
warnings: 1
info: 3
verdict: warnings_only
---

# Code Review: Phase 14 (Cross-Adapter Polish)

## Verdict: WARNINGS ONLY

All four requirements (CDX-09, OC-10, OC-11, PRES-01) are implemented as specified. Code changes match plan tasks, summaries are accurate, and artifact constraints are met. One minor semantic concern noted.

## Stage 1: Spec Compliance

### Plan Alignment

**Plan 14-01** (2 tasks, 2 commits):
- Task 1 (`11bda84`): cwd field added to `toml_writer.py`, `translate_env_vars_for_opencode_headers()` added to `env_translator.py`. Matches plan exactly.
- Task 2 (`4857a2c`): OpenCode adapter wired to call translation in `sync_mcp()` remote branch. Import updated, warnings captured. Matches plan exactly.
- Files modified: `src/utils/toml_writer.py`, `src/utils/env_translator.py`, `src/adapters/opencode.py` -- matches SUMMARY key-files.

**Plan 14-02** (2 tasks, 2 commits):
- Task 1 (`dd60b5b`): Skill dedup added with `claude_skills_dir` computed outside loop, `is_relative_to()` check, descriptive skip message. Matches plan exactly.
- Task 2 (`defafca`): `_extract_unmanaged_toml()` added, `_build_config_toml()` extended with `preserved_sections` parameter, both `_write_mcp_to_path()` and `sync_settings()` updated. Verification test created. Matches plan exactly.
- Files modified: `src/adapters/opencode.py`, `src/adapters/codex.py`, `tests/verify_phase14_preservation.py` -- matches SUMMARY key-files.

Both summaries report "No deviations from plan." Git history confirms this.

No issues found.

### Research Methodology

All four implementations follow the recommendations from `14-RESEARCH.md`:
- CDX-09: `cwd` field uses `format_toml_value()` as recommended (Pattern 1: Field Passthrough).
- OC-10: Reuses existing `VAR_PATTERN` regex as recommended. Translation applied only to `headers` dict, not `url`/`command`/`environment`. Default-stripping with warning implemented.
- OC-11: Uses `Path.is_relative_to()` as recommended (Pattern 3: Native Discovery Skip). Python 3.9+ is the project target.
- PRES-01: Raw text preservation approach (Option B from research) implemented. Gemini confirmed as already working via test, no code change -- matching research finding.

No issues found.

### Known Pitfalls

Research `14-RESEARCH.md` documents 5 pitfalls. All are addressed:
- Pitfall 1 (`is_relative_to` Python 3.9+): Used correctly; project targets 3.9+.
- Pitfall 2 (TOML section ordering): Raw text preservation maintains original ordering.
- Pitfall 3 (regex over-matching): Translation scoped to `headers` dict only.
- Pitfall 4 (narrow fix): Both `_write_mcp_to_path()` AND `sync_settings()` updated. Confirmed via grep: all 2 callers of `_build_config_toml` pass `preserved`.
- Pitfall 5 (Gemini false positive): Verification test confirms existing behavior, no code change made.

No issues found.

### Eval Coverage

`14-EVAL.md` defines 8 sanity checks (S1-S8), 5 proxy metrics (P1-P5), and 2 deferred validations (D1-D2).
- All sanity checks reference correct function signatures and import paths that exist in the implementation.
- Proxy tests reference `tests/verify_phase14_preservation.py` which was created (138 lines).
- Eval scripts can be run against the current implementation (correct paths, correct interfaces).

No issues found.

## Stage 2: Code Quality

### Architecture

All changes follow existing project patterns:
- `from __future__ import annotations` present in both modified and new files.
- New function `translate_env_vars_for_opencode_headers()` placed in `env_translator.py` alongside existing `translate_env_vars_for_codex()` and `preserve_env_vars_for_gemini()` -- consistent module organization.
- `_extract_unmanaged_toml()` is a private method on `CodexAdapter`, consistent with existing `_build_config_toml()` and `_write_mcp_to_path()` patterns.
- No duplicate utility implementations introduced.
- Import style matches existing codebase conventions.

Consistent with existing patterns.

### Reproducibility

N/A -- no experimental code. All changes are deterministic config transformations.

### Documentation

- `translate_env_vars_for_opencode_headers()` has a clear docstring explaining scope (headers only), return types, and the OpenCode syntax difference. Adequate.
- `_extract_unmanaged_toml()` documents managed vs. unmanaged content categories. Adequate.
- cwd field addition has an inline comment matching the pattern of surrounding code. Adequate.

Adequate.

### Deviation Documentation

SUMMARY key-files match git diff:
- Plan 14-01 SUMMARY lists: `toml_writer.py`, `env_translator.py`, `opencode.py`. Git diff confirms exactly these 3 files.
- Plan 14-02 SUMMARY lists: `opencode.py`, `codex.py`, `verify_phase14_preservation.py`. Git diff confirms exactly these 3 files.
- Note: `.planning/STATE.md` and `14-01-SUMMARY.md` also appear in the full diff (planning artifacts updated during execution), which is expected and not a concern.

Both summaries claim "No deviations from plan" and this is confirmed by comparing plan tasks to commit content.

SUMMARY.md matches git history.

## Findings Summary

| # | Severity | Stage | Area | Description |
|---|----------|-------|------|-------------|
| 1 | WARNING | 2 | Architecture | Header translation warnings stored in `skipped_files` list, which is semantically intended for skipped file names |
| 2 | INFO | 2 | Architecture | `_extract_unmanaged_toml` comment filter uses substring match ("MCP servers") which could theoretically match user comments containing that phrase |
| 3 | INFO | 1 | Eval Coverage | P2 blind spot acknowledged in EVAL.md: user-scope skills from `cc_home/.claude/skills/` not tested (those should NOT be skipped) |
| 4 | INFO | 2 | Documentation | `_build_config_toml` docstring Args section does not document the new `preserved_sections` parameter |

## Recommendations

**Finding 1 (WARNING):** In `opencode.py` line 320, `result.skipped_files.extend(header_warnings)` puts warning messages into a list designed for skipped file paths. This works functionally (both are `list[str]`) but creates a semantic mismatch -- consumers iterating `skipped_files` would see warning text mixed with file names. Consider adding a `warnings` field to `SyncResult` in a future phase, or using `failed_files` if these should surface as issues. Low priority since the plan explicitly specified this approach.

**Finding 2 (INFO):** The comment filter in `_extract_unmanaged_toml` at line 726 skips any comment containing "MCP servers" as a substring. A user comment like `# See MCP servers documentation` in a non-managed section would be incorrectly stripped. This is an edge case acknowledged by the deferred validation D2 in the eval plan.

**Finding 3 (INFO):** The eval plan's P2 test only validates project-scope skill skipping, not the preservation of user-scope skills from a different `cc_home`. This is acknowledged as a blind spot in the eval plan itself and deferred to D1.

**Finding 4 (INFO):** The `_build_config_toml` docstring (line 753-761) still only documents `settings_section` and `mcp_section` in the Args block -- the new `preserved_sections` parameter is not described. Minor documentation gap.
