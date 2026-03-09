---
phase: 13-gemini-native-format-migration
wave: 1
plans_reviewed: [13-01]
timestamp: 2026-03-09T11:00:00Z
blockers: 0
warnings: 2
info: 3
verdict: warnings_only
---

# Code Review: Phase 13 Wave 1

## Verdict: WARNINGS ONLY

Plan 13-01 was executed faithfully. Both tasks completed with commits matching plan descriptions. The core migration from inline GEMINI.md writing to native file output is well-implemented. Two warnings relate to a missing `adapt_command_content` call in the new `sync_commands` and bare `except Exception` clauses that silently swallow error details.

## Stage 1: Spec Compliance

### Plan Alignment

Both tasks from 13-01-PLAN.md are completed with corresponding commits:

| Task | Plan Description | Commit | Match |
|------|-----------------|--------|-------|
| 1 | Rewrite sync_skills and sync_agents to write native files | 4fbf7dd | Exact match |
| 2 | Rewrite sync_commands to TOML and add MCP field passthrough | 44055fe | Exact match |

SUMMARY.md reports "No deviations from plan" which is accurate -- the diff confirms all plan requirements are met:

- sync_skills writes to `.gemini/skills/<name>/SKILL.md` with content preserved verbatim
- sync_agents writes to `.gemini/agents/<name>.md` with rebuilt frontmatter, `color` dropped, `<role>` tags stripped
- sync_commands writes to `.gemini/commands/<name>.toml` with `$ARGUMENTS` mapped to `{{args}}`, namespaced commands creating subdirectories
- `_write_mcp_to_settings` passes through `trust`, `includeTools`, `excludeTools`, `cwd`
- None of the three sync methods call `_write_subsection` anymore

No issues found.

### Research Methodology Match

Implementation follows 13-RESEARCH.md recommendations closely:

- **Recommendation 1 (Skills):** Verbatim copy with frontmatter validation -- matches implementation exactly.
- **Recommendation 2 (Agents):** Field mapping table honored. `color` dropped, `tools`/`model`/`max_turns` passed through, `kind` omitted (per research recommendation).
- **Recommendation 3 (Commands):** TOML format with `description` and `prompt` fields, `$ARGUMENTS` -> `{{args}}` mapping -- matches.
- **Recommendation 4 (MCP passthrough):** Four fields passed through with allowlist approach -- matches.
- **Recommendation 5 (Stale cleanup):** Deferred to Plan 13-02 (wave 2) as expected.

No issues found.

### Context Decision Compliance

No CONTEXT.md exists for this phase. Decisions documented in SUMMARY.md are reasonable and consistent with research recommendations.

No issues found.

### Known Pitfalls (KNOWHOW/Research)

Pitfalls from 13-RESEARCH.md checked against implementation:

| Pitfall | Status |
|---------|--------|
| 1: Command name sanitization (colons) | Handled -- colon splits to subdirectory path (lines 303-308) |
| 2: TOML triple-quote escaping | Handled -- `"""` replaced with `""\\"` (lines 344-345) |
| 3: Stale native files after source deletion | Not in scope for this plan (documented as Phase 14+ per research) |
| 4: Frontmatter quoting for special chars | Handled -- `_quote_yaml_value` helper (lines 244-259) |
| 5: GEMINI.md cleanup race condition | Deferred to Plan 13-02 (cleanup runs after all writes) |

MEMORY.md pitfalls:
- Path hardcoding: All paths use `self.project_dir / ".gemini"` -- correct.
- Python 3.9 compat: `from __future__ import annotations` present -- correct.

No issues found.

### Eval Coverage

13-EVAL.md defines 8 sanity checks (S1-S8) and 3 proxy metrics (P1-P3). Checking coverage against Plan 13-01 deliverables:

- S1 (import check): Runnable against current code.
- S2-S5 (native file outputs): Runnable -- all sync methods implemented.
- S6 (MCP passthrough): Runnable -- field passthrough implemented.
- S7 (GEMINI.md cleanup): Requires Plan 13-02 (wave 2) -- not yet implemented.
- S8 (no dual writing): Runnable -- sync methods confirmed to not call `_write_subsection`.
- P1 (E2E script): Requires Plan 13-02 verification script -- not yet created.
- P2 (regression): Runnable with existing test scripts.

7 of 8 sanity checks and 1 of 3 proxy metrics can be evaluated against wave 1 output. The remaining items depend on wave 2 (Plan 13-02), which is expected.

No issues found.

## Stage 2: Code Quality

### Architecture

The implementation follows existing project patterns well:

- Uses `ensure_dir()` from `src/utils/paths` consistently
- Uses `read_json_safe` / `write_json_atomic` for settings.json
- Returns `SyncResult` with proper counting (synced/skipped/failed)
- Integrates cleanly with the adapter base class pattern

One observation: the old `sync_commands` called `self.adapt_command_content(content)` (defined in base.py) which handles broader Claude Code syntax adaptation beyond just `$ARGUMENTS`. The new implementation only maps `$ARGUMENTS` -> `{{args}}` and skips other adaptations. Since the old `adapt_command_content` was designed for inline text (not TOML prompt bodies), this is likely intentional but should be verified.

### Reproducibility

N/A -- deterministic format migration, no experimental code.

### Documentation

Code documentation is thorough:
- Module docstring updated to reflect native file writing
- Each method has a complete docstring with Args/Returns
- Inline comments explain design choices (e.g., "Drop color field (Gemini-incompatible)")
- GMN-11 comment marks the MCP passthrough addition

### Deviation Documentation

SUMMARY.md key_files lists `src/adapters/gemini.py` as the only modified file, which matches `git diff --name-only` output exactly. Commit messages are descriptive and align with SUMMARY task descriptions.

No issues found.

## Findings Summary

| # | Severity | Stage | Area | Description |
|---|----------|-------|------|-------------|
| 1 | WARNING | 2 | Architecture | `adapt_command_content` no longer called in `sync_commands` -- old adapter called it for portable syntax adaptation beyond `$ARGUMENTS` mapping. The TOML prompt body may miss other Claude Code-specific syntax translations. |
| 2 | WARNING | 2 | Architecture | All three sync methods use bare `except Exception` that increments `failed` counter but discards the exception message. The `failed_files` entry is generic (e.g., `"{name}: write failed"`). Logging or preserving `str(e)` would aid debugging. |
| 3 | INFO | 2 | Architecture | `_write_subsection` method remains in the codebase (lines 716-785) but is no longer called by any sync method. Plan 13-02 documents it as "legacy, keep for backward compatibility" which is acceptable. |
| 4 | INFO | 1 | Plan Alignment | Stale GEMINI.md cleanup (GMN-12) is correctly deferred to Plan 13-02 (wave 2) as designed. |
| 5 | INFO | 2 | Documentation | `_quote_yaml_value` helper is well-implemented with comprehensive character coverage. The quoting character set (`:"'{}[]|>&*!%#`@,`) is thorough. |

## Recommendations

**WARNING 1 (adapt_command_content):** Verify whether `adapt_command_content` performs any transformations beyond `$ARGUMENTS` mapping that are relevant to Gemini TOML prompt bodies. If it does (e.g., shebang line stripping, path normalization), those transformations may need to be replicated or consciously skipped. If `$ARGUMENTS` is the only relevant transformation, document this decision in the code with a comment explaining why `adapt_command_content` is not used.

**WARNING 2 (exception swallowing):** Consider preserving the exception message in the `failed_files` entry. For example: `result.failed_files.append(f"{name}: {e}")`. This is a minor change that significantly improves debuggability without changing behavior.
