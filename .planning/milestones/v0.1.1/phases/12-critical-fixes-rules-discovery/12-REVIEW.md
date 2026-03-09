---
phase: 12-critical-fixes-rules-discovery
wave: "all"
plans_reviewed: ["12-01", "12-02", "12-03"]
timestamp: 2026-03-09T02:15:00Z
blockers: 0
warnings: 0
info: 3
verdict: pass
---

# Code Review: Phase 12 (All Plans)

## Verdict: PASS

All three plans executed faithfully against their specifications. Adapter output formats now match current official CLI documentation, rules directory discovery is implemented with correct frontmatter parsing, and 14 integration tests verify the changes. Zero deprecated patterns remain in active source code.

## Stage 1: Spec Compliance

### Plan Alignment

**Plan 12-01 (Adapter Config Format Fixes):**
- Task 1 (Codex fixes): Commit `ca54f8f` changes CONFIG_TOML to "config.toml" and approval_policy to "on-request". Verified in source. Codebase-wide sweep for remaining references done (plan requirement "narrow fix prevention"). Test files updated in same commit.
- Task 2 (Gemini + OpenCode fixes): Commit `24ae64f` changes Gemini keys to exclude/allowed and rewrites OpenCode to per-tool permission format. TOOL_MAPPING constant and bash wildcard pattern extraction implemented as specified.
- SUMMARY lists 6 files modified; git history confirms codex.py, gemini.py, opencode.py plus 3 test files. All match.
- Deviation documented: test files needed updating for new key names (auto-fixed, properly recorded).

**Plan 12-02 (Rules Directory Discovery):**
- Task 1 (SourceReader): Commit `1e1e408` adds `_parse_rules_frontmatter()` and `get_rules_files()` to source_reader.py. Uses `self.cc_home / "rules"` for user scope (not hardcoded). `discover_all()` updated with `rules_files` key.
- Task 2 (Orchestrator): Commit `1d567f5` merges rules_files into adapter data flow in orchestrator.py.
- SUMMARY reports zero deviations; confirmed accurate.
- Backward compatibility preserved: `get_rules()` remains unchanged, returns string.

**Plan 12-03 (Integration Tests + Sweep):**
- Task 1 (Tests): Commit `d39c7ce` creates `tests/test_phase12_integration.py` with 14 tests covering all requirements.
- Task 2 (Codebase sweep): No commit needed; sweep confirmed zero deprecated patterns in active source. Dead code (cc2all_sync.py) correctly excluded per MEMORY.md.
- Orphan codex.toml at project root documented (not deleted -- correct decision).

No issues found.

### Research Methodology

Research recommendations (12-RESEARCH.md) are faithfully implemented:
- Recommendation 1 (Codex approval_policy): `on-request` value matches official Codex Config Reference.
- Recommendation 2 (Codex filename): `config.toml` matches official docs.
- Recommendation 3 (Gemini keys): `exclude`/`allowed` match Gemini CLI Configuration docs.
- Recommendation 4 (OpenCode permissions): Per-tool `permission` (singular) with allow/ask/deny matches OpenCode Permissions Docs. Bash wildcard pattern format matches documented examples.
- Recommendation 5 (Rules discovery): `rglob("*.md")` with frontmatter parsing for `paths:`/`globs:` matches Claude Code Memory Docs and Claude Fast Rules Guide.
- Anti-patterns avoided: No breaking change to `get_rules()`, no hardcoded `~/.claude` paths, no PyYAML dependency.

No issues found.

### Context Decision Compliance

N/A -- no CONTEXT.md exists for this phase.

### Known Pitfalls

All pitfalls from 12-RESEARCH.md addressed:
- Pitfall 1 (get_rules() return type): Avoided -- new `get_rules_files()` method added instead.
- Pitfall 2 (Codex CONFIG_TOML scope): Noted in research as out of scope; path logic left as-is per plan.
- Pitfall 3 (OpenCode permission key collision): Addressed -- `del existing_config['permissions']` at line 448 removes old plural key.
- Pitfall 4 (Frontmatter YAML lists): Handled -- three formats supported (single string, YAML list, inline list).
- Pitfall 5 (Narrow fix syndrome): Addressed -- codebase-wide grep performed; test files updated alongside adapter fixes.

No issues found.

### Eval Coverage

12-EVAL.md defines 8 sanity checks (S1-S8) and 6 proxy metrics (P1-P6). All are executable against the current implementation:
- S1-S4: Constant/key checks directly testable against modified source.
- S5: Import check covers all modified modules.
- S6-S7: Method existence and backward compatibility verifiable.
- S8: Hardcoded path check executable via grep.
- P1-P6: Each uses tempdir + adapter construction pattern that matches the integration test approach.
- Evaluation scripts reference correct file paths and interfaces.

No issues found.

## Stage 2: Code Quality

### Architecture

- All modified files follow existing project patterns: `from __future__ import annotations` present in every file, adapter class structure preserved, SourceReader method style consistent.
- `TOOL_MAPPING` as a class constant on OpenCodeAdapter follows the established pattern of adapter-level constants (cf. `CONFIG_TOML` on CodexAdapter).
- `_parse_rules_frontmatter()` uses regex (not PyYAML), consistent with existing `_parse_frontmatter()` patterns in other adapters.
- Orchestrator integration is minimal and non-invasive: two lines added to merge rules_files into existing flow.
- No duplicate implementations introduced.

Consistent with existing patterns.

### Reproducibility

N/A -- no experimental code. This phase contains deterministic bug fixes and a feature addition.

### Documentation

- Codex adapter docstring updated to reference "config.toml" (commit `ca54f8f`).
- Gemini adapter docstrings updated for "tools.exclude/tools.allowed" (commit `24ae64f`).
- OpenCode adapter docstring updated for "permission (singular)" (commit `24ae64f`).
- `get_rules_files()` has complete docstring with return type description.
- `_parse_rules_frontmatter()` purpose clear from name and usage context.

Adequate.

### Deviation Documentation

SUMMARY.md files accurately reflect git history:
- 12-01 SUMMARY: 2 commits (ca54f8f, 24ae64f), 6 files -- matches git.
- 12-02 SUMMARY: 2 commits (1e1e408, 1d567f5), 2 files -- matches git.
- 12-03 SUMMARY: 1 commit (d39c7ce), 1 file -- matches git. Task 2 correctly noted as no-commit (sweep only).
- One deviation documented (test file updates in 12-01) -- accurate and properly categorized.

SUMMARY.md matches git history.

## Findings Summary

| # | Severity | Stage | Area | Description |
|---|----------|-------|------|-------------|
| 1 | INFO | 1 | Research | Codex user-scope config path (research open question #1) left unresolved as planned -- project_dir / CONFIG_TOML may write to wrong location for user-scope, but fixing path logic was explicitly out of scope |
| 2 | INFO | 2 | Architecture | cc2all_sync.py retains deprecated patterns (blockedTools, Path.home()) but is correctly identified as dead code and excluded from fixes |
| 3 | INFO | 2 | Documentation | Orphan codex.toml at project root documented but no migration/cleanup mechanism provided -- acceptable for a minor release |

## Recommendations

No blockers or warnings to address. Informational items for future consideration:

1. **Codex user-scope path** (INFO #1): Consider addressing research open question #1 in Phase 14 (cross-adapter polish) -- the user-scope config path may need to write to `~/.codex/config.toml` rather than project root.

2. **Dead code cleanup** (INFO #2): Consider removing cc2all_sync.py in a future cleanup phase since it is dead code with deprecated patterns.

3. **Orphan file cleanup** (INFO #3): Consider adding a migration note or optional cleanup command for orphan codex.toml files in v0.1.1 release notes.
