---
phase: 12-critical-fixes-rules-discovery
verified: 2026-03-09T02:15:00Z
status: passed
score:
  level_1: 8/8 sanity checks passed
  level_2: 6/6 proxy metrics met
  level_3: 2 deferred (tracked below)
gaps: []
deferred_validations:
  - description: "Target CLI acceptance testing (Codex, Gemini, OpenCode)"
    metric: "config_parse_errors"
    target: "0 errors"
    depends_on: "Manual pre-release testing with installed CLIs"
    tracked_in: "DEFER-12-01"
  - description: "Full end-to-end sync with real Claude Code config including .claude/rules/"
    metric: "sync_correctness"
    target: "All target configs correct, no regressions"
    depends_on: "Phase 14 integration or manual pre-release testing"
    tracked_in: "DEFER-12-02"
human_verification: []
---

# Phase 12: Critical Fixes & Rules Discovery Verification Report

**Phase Goal:** Fix broken adapter outputs (Codex deprecated approval policy, Codex config filename, Gemini v1 settings keys, OpenCode permission system) and extend SourceReader to discover `.claude/rules/` directory content as a new config surface.

**Verified:** 2026-03-09
**Status:** passed
**Re-verification:** No -- initial verification

## Verification Summary by Tier

### Level 1: Sanity Checks

| # | Check | Status | Evidence |
|---|-------|--------|----------|
| S1 | Codex CONFIG_TOML constant = 'config.toml' | PASS | Module-level `CONFIG_TOML = "config.toml"` at codex.py:39 |
| S2 | No deprecated `codex.toml` or `on-failure` in codex.py | PASS | 0 matches (grep) |
| S3 | No deprecated `blockedTools`/`allowedTools` in gemini.py | PASS | 0 matches (grep) |
| S4 | OpenCode uses singular `permission` key in sync_settings | PASS | `existing_config['permission'] = permission_config` at opencode.py:451 |
| S5 | All adapter modules import without error | PASS | CodexAdapter, GeminiAdapter, OpenCodeAdapter, SourceReader, SyncOrchestrator all imported |
| S6 | SourceReader has `get_rules_files` method | PASS | Method exists and is callable |
| S7 | `get_rules()` backward compatibility (returns str) | PASS | Returns str type confirmed |
| S8 | No hardcoded Path.home() for .claude paths | PASS | 1 match is the parameterized default fallback at source_reader.py:50 (`cc_home if cc_home is not None else Path.home() / ".claude"`) -- correct pattern |

**Level 1 Score:** 8/8 passed

### Level 2: Proxy Metrics

| # | Metric | Target | Achieved | Status |
|---|--------|--------|----------|--------|
| P1 | Codex approval_policy for auto mode | `on-request` in output | `approval_policy = "on-request"` | PASS |
| P2 | Gemini tools config keys | `exclude`/`allowed` (v2), no v1 keys | `{"exclude": ["Write"]}` | PASS |
| P3 | OpenCode permission format | `permission` (singular) with per-tool dict | `{"edit": "deny", "read": "allow", "bash": {"git commit *": "allow", "*": "ask"}}` | PASS |
| P4 | Rules directory discovery (recursive) | 2 files found (top.md + nested.md) | 2 files found: `['nested.md', 'top.md']` | PASS |
| P5 | Frontmatter parsing (3 cases) | Plain=[], Single=["src/**/*.ts"], Multi=2 patterns | All correct: plain=[], single=["src/**/*.ts"], multi=["src/a/**", "src/b/**"] | PASS |
| P6 | Codebase-wide sweep for deprecated patterns | 0 deprecated patterns in active src/ | codex.toml=0, on-failure=0, blockedTools/allowedTools=0, permissions_config[mode]=0 | PASS |

**Level 2 Score:** 6/6 met target

### Level 3: Deferred Validations

| # | Validation | Metric | Target | Depends On | Status |
|---|-----------|--------|--------|------------|--------|
| DEFER-12-01 | Target CLI acceptance testing | config_parse_errors | 0 errors | Manual testing with Codex/Gemini/OpenCode CLIs installed | DEFERRED |
| DEFER-12-02 | Full end-to-end sync with real config | sync_correctness | All outputs correct | Phase 14 integration or manual pre-release | DEFERRED |

**Level 3:** 2 items tracked for integration/pre-release

## Goal Achievement

### Observable Truths

| # | Truth | Verification Level | Status | Evidence |
|---|-------|--------------------|--------|----------|
| 1 | SourceReader returns content from `.claude/rules/*.md` including recursive subdirectories | Level 2 (P4) | PASS | Temp dir with top.md + subdir/nested.md both found |
| 2 | Rules with `paths:` YAML frontmatter are tagged with scope_patterns | Level 2 (P5) | PASS | Single path, list paths, and no-frontmatter all parsed correctly |
| 3 | Codex writes `approval_policy = 'on-request'` (not `'on-failure'`) | Level 2 (P1) | PASS | Output TOML contains `on-request`, zero occurrences of `on-failure` in source |
| 4 | Codex writes to `config.toml` (not `codex.toml`) | Level 1 (S1,S2) | PASS | `CONFIG_TOML = "config.toml"`, zero occurrences of `codex.toml` in active source |
| 5 | Gemini writes `tools.exclude` and `tools.allowed` (v2 format) | Level 2 (P2) | PASS | Output JSON uses `exclude` key, zero `blockedTools`/`allowedTools` in source |
| 6 | OpenCode writes `permission` (singular) with per-tool values | Level 2 (P3) | PASS | Output JSON has `permission` key with dict, `permissions` (plural) absent |
| 7 | OpenCode maps bash patterns to wildcard entries | Level 2 (P3) | PASS | `Bash(git commit:*)` mapped to `{"git commit *": "allow", "*": "ask"}` |

### Required Artifacts

| Artifact | Expected | Exists | Sanity | Wired |
|----------|----------|--------|--------|-------|
| `src/adapters/codex.py` | Fixed CONFIG_TOML and approval_policy | Yes (713 lines) | PASS | PASS |
| `src/adapters/gemini.py` | v2 tools keys (exclude/allowed) | Yes (734 lines) | PASS | PASS |
| `src/adapters/opencode.py` | Per-tool permission (singular) with TOOL_MAPPING | Yes (549 lines) | PASS | PASS |
| `src/source_reader.py` | get_rules_files() with frontmatter parsing | Yes (835 lines) | PASS | PASS |
| `src/orchestrator.py` | rules_files merge into rules list | Yes (450 lines) | PASS | PASS |
| `tests/test_phase12_integration.py` | 14 integration tests | Yes (14 tests) | PASS (14/14) | PASS |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| orchestrator.py | source_reader.py | `discover_all()` -> `rules_files` key | WIRED | Lines 100-107: merges rules_files into rules list |
| orchestrator.py | adapters | `adapter.sync_all(adapter_data)` | WIRED | adapter_data includes merged rules with scope_patterns |
| source_reader.py | frontmatter parser | `_parse_rules_frontmatter()` | WIRED | Called in `get_rules_files()` for each .md file |

## Integration Test Results

All 14 tests pass (pytest 0.05s):

| Test | Status |
|------|--------|
| test_codex_config_filename | PASS |
| test_codex_approval_policy_auto | PASS |
| test_codex_approval_policy_ask | PASS |
| test_gemini_deny_list_uses_exclude | PASS |
| test_gemini_allow_list_uses_allowed | PASS |
| test_opencode_permission_singular | PASS |
| test_opencode_bash_patterns | PASS |
| test_opencode_removes_old_permissions | PASS |
| test_rules_discovery_project | PASS |
| test_rules_discovery_nested | PASS |
| test_rules_frontmatter_paths | PASS |
| test_rules_frontmatter_list | PASS |
| test_rules_no_frontmatter | PASS |
| test_rules_user_scope | PASS |

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none found) | -- | -- | -- | -- |

No TODOs, FIXMEs, placeholders, or stub implementations detected in modified files.

## WebMCP Verification

WebMCP verification skipped -- MCP not available (phase does not modify frontend views).

## Requirements Coverage

| Requirement | Status | Blocking Issue |
|-------------|--------|----------------|
| SC1: SourceReader returns .claude/rules/ content recursively | PASS | -- |
| SC2: Rules frontmatter path tagging | PASS | -- |
| SC3: Codex approval_policy = 'on-request' | PASS | -- |
| SC4: Codex writes config.toml | PASS | -- |
| SC5: Gemini v2 tools keys | PASS | -- |
| SC6: OpenCode permission (singular) format | PASS | -- |
| SC7: OpenCode bash pattern mapping | PASS | -- |

## Human Verification Required

None -- all success criteria are binary (correct/incorrect) and fully verifiable with automated checks.

---

_Verified: 2026-03-09_
_Verifier: Claude (grd-verifier)_
_Verification levels applied: Level 1 (sanity), Level 2 (proxy), Level 3 (deferred tracking)_
