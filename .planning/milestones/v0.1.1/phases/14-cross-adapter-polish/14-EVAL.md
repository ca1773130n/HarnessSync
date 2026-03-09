# Evaluation Plan: Phase 14 -- Cross-Adapter Polish

**Designed:** 2026-03-09
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** CDX-09 (cwd passthrough), OC-10 (header env var translation), OC-11 (skill deduplication), PRES-01 (config preservation)
**Reference:** 14-RESEARCH.md -- codebase analysis + CLI documentation (no academic papers; engineering polish phase)

## Evaluation Overview

Phase 14 is a deterministic engineering polish phase with four well-scoped requirements. Each has binary pass/fail correctness criteria -- there are no probabilistic or quality-threshold metrics. This makes evaluation straightforward: either the field appears in output, the regex translates correctly, the skip logic fires, and the config survives, or it does not.

Because all four requirements modify existing adapter methods with clear input/output contracts, Level 1 (sanity) and Level 2 (proxy) checks can cover nearly everything. The only meaningful deferred validation is a full orchestrator run with real-world configs to catch edge cases not anticipated by unit-level tests.

Gemini PRES-01 is expected to already pass with no code changes (JSON dict-merge pattern preserves keys). The evaluation plan includes a verification test to confirm this assumption.

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| cwd field in TOML output | Codex CLI docs (CODEX-LATEST.md L271-287) | CDX-09 requires this field to appear when present |
| ${VAR} -> {env:VAR} translation | OpenCode docs (OPENCODE-LATEST.md L211) | OC-10 requires correct syntax translation |
| Skill skip count for native paths | OpenCode native discovery behavior | OC-11 requires no duplicate skills |
| Non-managed TOML section survival | Config file round-trip integrity | PRES-01 requires no clobbering |
| Non-managed JSON key survival | Config file round-trip integrity | PRES-01 Gemini verification |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 8 | Import checks, format checks, value range, regression |
| Proxy (L2) | 5 | Round-trip adapter tests with filesystem |
| Deferred (L3) | 2 | Full orchestrator run, real-world config edge cases |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: Import Cleanliness
- **What:** All modified modules import without error
- **Command:** `python3 -c "from src.utils.toml_writer import format_mcp_server_toml; from src.utils.env_translator import translate_env_vars_for_opencode_headers; from src.adapters.opencode import OpenCodeAdapter; from src.adapters.codex import CodexAdapter; print('All imports OK')"`
- **Expected:** `All imports OK` -- no ImportError, no SyntaxError
- **Failure means:** Code has syntax errors or missing dependencies

### S2: CDX-09 -- cwd Field Emitted
- **What:** `format_mcp_server_toml()` includes `cwd` in output when config dict contains it
- **Command:** `python3 -c "from src.utils.toml_writer import format_mcp_server_toml; r = format_mcp_server_toml('test', {'command': 'node', 'cwd': '/tmp/work'}); assert 'cwd = \"/tmp/work\"' in r, f'Missing cwd in: {r}'; print('S2 PASS: cwd field emitted')"`
- **Expected:** `S2 PASS: cwd field emitted`
- **Failure means:** cwd passthrough not implemented in toml_writer.py

### S3: CDX-09 -- Regression: enabled_tools/disabled_tools Still Work
- **What:** Existing field handling not broken by cwd addition
- **Command:** `python3 -c "from src.utils.toml_writer import format_mcp_server_toml; r = format_mcp_server_toml('test', {'command': 'x', 'enabled_tools': ['a', 'b'], 'disabled_tools': ['c']}); assert 'enabled_tools' in r and 'disabled_tools' in r, f'Regression: {r}'; print('S3 PASS: no regression')"`
- **Expected:** `S3 PASS: no regression`
- **Failure means:** cwd addition broke existing field handling

### S4: CDX-09 -- cwd Absent When Not in Config
- **What:** `cwd` does not appear in output when not provided
- **Command:** `python3 -c "from src.utils.toml_writer import format_mcp_server_toml; r = format_mcp_server_toml('test', {'command': 'node'}); assert 'cwd' not in r, f'Unexpected cwd in: {r}'; print('S4 PASS: cwd absent when missing')"`
- **Expected:** `S4 PASS: cwd absent when missing`
- **Failure means:** cwd is being emitted unconditionally

### S5: OC-10 -- Basic ${VAR} Translation
- **What:** `translate_env_vars_for_opencode_headers()` converts `${VAR}` to `{env:VAR}`
- **Command:** `python3 -c "from src.utils.env_translator import translate_env_vars_for_opencode_headers; h, w = translate_env_vars_for_opencode_headers({'Authorization': 'Bearer \${API_KEY}'}); assert h['Authorization'] == 'Bearer {env:API_KEY}', f'Got: {h}'; assert len(w) == 0; print('S5 PASS: basic translation')"`
- **Expected:** `S5 PASS: basic translation`
- **Failure means:** Regex substitution not working

### S6: OC-10 -- Default Value Stripping
- **What:** `${VAR:-default}` becomes `{env:VAR}` with a warning
- **Command:** `python3 -c "from src.utils.env_translator import translate_env_vars_for_opencode_headers; h, w = translate_env_vars_for_opencode_headers({'X-Token': '\${TOKEN:-fallback}'}); assert h['X-Token'] == '{env:TOKEN}', f'Got: {h}'; assert len(w) == 1 and 'fallback' in w[0].lower() or 'default' in w[0].lower(), f'Warning: {w}'; print('S6 PASS: default stripped')"`
- **Expected:** `S6 PASS: default stripped`
- **Failure means:** Default syntax handling missing

### S7: OC-10 -- Non-String Passthrough
- **What:** Non-string header values pass through unchanged
- **Command:** `python3 -c "from src.utils.env_translator import translate_env_vars_for_opencode_headers; h, w = translate_env_vars_for_opencode_headers({'Count': 42, 'Flag': True}); assert h['Count'] == 42 and h['Flag'] is True; print('S7 PASS: non-string passthrough')"`
- **Expected:** `S7 PASS: non-string passthrough`
- **Failure means:** Function crashes or mangles non-string values

### S8: OC-10 -- No Translation on Empty/No-Var Headers
- **What:** Headers without env vars are unchanged
- **Command:** `python3 -c "from src.utils.env_translator import translate_env_vars_for_opencode_headers; h, w = translate_env_vars_for_opencode_headers({'Content-Type': 'application/json'}); assert h['Content-Type'] == 'application/json'; assert len(w) == 0; print('S8 PASS: no false translation')"`
- **Expected:** `S8 PASS: no false translation`
- **Failure means:** Regex over-matching on non-variable content

**Sanity gate:** ALL sanity checks must pass. Any failure blocks progression.

## Level 2: Proxy Metrics

**Purpose:** Round-trip adapter-level tests that exercise the full code path with filesystem side effects. These approximate integration testing without requiring the full orchestrator.

**IMPORTANT:** These are adapter-level tests, not full pipeline tests. They validate the adapter in isolation with mocked project directories. Treat results with appropriate skepticism -- real configs may have edge cases these don't cover.

### P1: OpenCode Header Translation End-to-End
- **What:** OpenCode `sync_mcp()` translates `${VAR}` in remote server headers to `{env:VAR}` in the written opencode.json
- **How:** Create an OpenCodeAdapter with a temp dir, sync a remote MCP server with env var headers, read the output JSON
- **Command:**
  ```bash
  python3 -c "
  import json, tempfile
  from pathlib import Path
  from src.adapters.opencode import OpenCodeAdapter
  with tempfile.TemporaryDirectory() as tmpdir:
      adapter = OpenCodeAdapter(Path(tmpdir))
      result = adapter.sync_mcp({
          'remote-api': {
              'url': 'https://api.example.com/mcp',
              'headers': {'Authorization': 'Bearer \${API_KEY}', 'X-Custom': '\${TOKEN:-default}'}
          }
      })
      config = json.loads((Path(tmpdir) / 'opencode.json').read_text())
      headers = config['mcp']['remote-api']['headers']
      assert headers['Authorization'] == 'Bearer {env:API_KEY}', f'Got: {headers}'
      assert headers['X-Custom'] == '{env:TOKEN}', f'Got: {headers}'
      assert result.synced == 1
      print('P1 PASS: header translation end-to-end')
  "
  ```
- **Target:** Headers translated, server synced, no errors
- **Evidence:** OpenCode docs specify `{env:VAR}` syntax (OPENCODE-LATEST.md L211); adapter must apply translation before writing
- **Correlation with full metric:** HIGH -- exercises the exact code path used in production sync
- **Blind spots:** Does not test `sync_mcp_scoped()` delegation path directly (though it delegates to `sync_mcp()`)
- **Validated:** No -- awaiting deferred validation with real configs (D1)

### P2: OpenCode Skill Deduplication
- **What:** `sync_skills()` skips skills under `.claude/skills/` and symlinks external skills
- **How:** Create adapter with temp dir containing both native and external skills, run sync, check counts
- **Command:**
  ```bash
  python3 -c "
  import tempfile
  from pathlib import Path
  from src.adapters.opencode import OpenCodeAdapter
  with tempfile.TemporaryDirectory() as tmpdir:
      project = Path(tmpdir)
      adapter = OpenCodeAdapter(project)
      native_skill = project / '.claude' / 'skills' / 'my-skill'
      native_skill.mkdir(parents=True)
      (native_skill / 'skill.md').write_text('test')
      external_skill = Path(tmpdir) / 'external-skills' / 'ext-skill'
      external_skill.mkdir(parents=True)
      (external_skill / 'skill.md').write_text('test')
      result = adapter.sync_skills({'my-skill': native_skill, 'ext-skill': external_skill})
      assert result.skipped == 1, f'Expected 1 skipped, got {result.skipped}'
      assert result.synced == 1, f'Expected 1 synced, got {result.synced}'
      assert any('natively discovered' in s for s in result.skipped_files)
      print('P2 PASS: skill deduplication')
  "
  ```
- **Target:** 1 skipped (native), 1 synced (external)
- **Evidence:** OpenCode reads `.claude/skills/` natively (OPENCODE-LATEST.md); symlinks would cause duplicates
- **Correlation with full metric:** HIGH -- directly tests the skip logic
- **Blind spots:** Does not test user-scope skills from `cc_home/.claude/skills/` (those should NOT be skipped)
- **Validated:** No -- awaiting deferred validation (D1)

### P3: Codex Config Preservation Round-Trip
- **What:** Writing MCP servers to a Codex config.toml that contains `[agents]` and `[profiles]` sections preserves those sections
- **How:** Create a config.toml with non-managed sections, run adapter's MCP write, re-read and check
- **Command:** `python3 tests/verify_phase14_preservation.py` (test created during plan 14-02 execution)
- **Target:** `[agents]` section with its keys survives, `[profiles.default]` survives, MCP section also present
- **Evidence:** PRES-01 requirement; `_build_config_toml()` currently drops non-managed sections (14-RESEARCH.md L77-83)
- **Correlation with full metric:** HIGH -- round-trip file test is the gold standard for preservation
- **Blind spots:** Uses simple non-managed sections; real configs may have comments, inline tables, multi-line strings
- **Validated:** No -- awaiting deferred validation with real user configs (D2)

### P4: Gemini Settings Preservation Round-Trip
- **What:** Writing settings to Gemini settings.json that already has `hooks` and `security` keys preserves those keys
- **How:** Part of `tests/verify_phase14_preservation.py`
- **Command:** `python3 tests/verify_phase14_preservation.py` (same test as P3)
- **Target:** `hooks` and `security` keys survive settings sync
- **Evidence:** Gemini adapter uses JSON dict-merge (14-RESEARCH.md L80-81) which should already preserve; this test confirms
- **Correlation with full metric:** HIGH -- JSON dict-merge is well-understood; if the test passes, production behavior matches
- **Blind spots:** Nested key overwriting (e.g., if synced key has sub-keys that collide with existing sub-keys)
- **Validated:** No -- awaiting deferred validation (D2)

### P5: Existing Test Suite Passes
- **What:** All pre-existing verification tests still pass (no regressions)
- **How:** Run all test files in tests/ directory
- **Command:**
  ```bash
  for f in tests/verify_*.py; do echo "--- $f ---"; python3 "$f"; done
  ```
- **Target:** All tests exit 0
- **Evidence:** Phase 14 modifies adapters used by earlier phases; regressions must be caught
- **Correlation with full metric:** MEDIUM -- tests may not cover all interactions
- **Blind spots:** Tests only cover what was previously written; new interactions untested
- **Validated:** No

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring the orchestrator, real configs, or manual review.

### D1: Full Orchestrator Sync With Mixed MCP Configs -- DEFER-14-01
- **What:** End-to-end orchestrator run syncing real Claude Code configs (with cwd fields, env var headers, mixed skill scopes) to all three targets
- **How:** Run `python3 -m src.cli sync --all` (or equivalent) on a project with representative configs
- **Why deferred:** Requires assembled orchestrator, real config files, and all three target CLIs available for output inspection
- **Validates at:** Manual testing after phase 14 merge
- **Depends on:** All four requirements implemented and passing L1/L2 checks
- **Target:** All fields synced correctly: cwd appears in Codex TOML, headers translated in OpenCode JSON, no duplicate skills in OpenCode
- **Risk if unmet:** Individual adapter fixes may have subtle interactions (e.g., header translation applied to wrong field, cwd formatting edge case)
- **Fallback:** Fix-forward in a subsequent patch; each fix is isolated so regressions are easily bisected

### D2: Real-World Config Preservation Stress Test -- DEFER-14-02
- **What:** Codex config.toml and Gemini settings.json preservation with real user configs containing complex sections (comments, nested tables, custom fields)
- **How:** Collect 3-5 real config.toml files from Codex users, run sync, diff before/after for non-managed sections
- **Why deferred:** Requires real user configs with varied structure; test configs may not represent production complexity
- **Validates at:** User acceptance testing after phase 14 merge
- **Depends on:** PRES-01 implemented and P3/P4 passing
- **Target:** Zero data loss in non-managed sections across all test configs
- **Risk if unmet:** TOML section extraction regex may miss edge cases (inline comments on managed lines, unusual section ordering)
- **Fallback:** Improve `_extract_unmanaged_toml()` regex/logic based on failing cases; fundamental approach (raw text preservation) is sound

## Ablation Plan

**No ablation plan** -- Each requirement (CDX-09, OC-10, OC-11, PRES-01) is an independent, atomic fix. There are no sub-components to isolate; each either works or it does not. Ablation analysis is not applicable to deterministic correctness fixes.

## WebMCP Tool Definitions

WebMCP tool definitions skipped -- phase does not modify frontend views.

## Baselines

| Baseline | Description | Expected Score | Source |
|----------|-------------|----------------|--------|
| Pre-phase cwd support | `format_mcp_server_toml()` does NOT emit cwd | cwd absent | Current codebase |
| Pre-phase header translation | `${VAR}` passed through verbatim to OpenCode | No translation | Current codebase |
| Pre-phase skill dedup | All skills symlinked regardless of source | 0 skipped | Current codebase |
| Pre-phase Codex preservation | `[agents]` section lost after sync | Section missing | Current codebase (14-RESEARCH.md L77) |
| Pre-phase Gemini preservation | Non-synced keys preserved via dict-merge | Keys present | Current codebase (14-RESEARCH.md L80) |

## Evaluation Scripts

**Location of evaluation code:**
```
tests/verify_phase14_preservation.py  (created during plan 14-02 execution)
```

**How to run full evaluation:**
```bash
# Level 1: Sanity (run all 8 checks)
python3 -c "from src.utils.toml_writer import format_mcp_server_toml; from src.utils.env_translator import translate_env_vars_for_opencode_headers; from src.adapters.opencode import OpenCodeAdapter; from src.adapters.codex import CodexAdapter; print('S1 PASS')"
python3 -c "from src.utils.toml_writer import format_mcp_server_toml; r = format_mcp_server_toml('test', {'command': 'node', 'cwd': '/tmp/work'}); assert 'cwd = \"/tmp/work\"' in r; print('S2 PASS')"
python3 -c "from src.utils.toml_writer import format_mcp_server_toml; r = format_mcp_server_toml('test', {'command': 'x', 'enabled_tools': ['a'], 'disabled_tools': ['b']}); assert 'enabled_tools' in r and 'disabled_tools' in r; print('S3 PASS')"
python3 -c "from src.utils.toml_writer import format_mcp_server_toml; r = format_mcp_server_toml('test', {'command': 'node'}); assert 'cwd' not in r; print('S4 PASS')"
python3 -c "from src.utils.env_translator import translate_env_vars_for_opencode_headers; h, w = translate_env_vars_for_opencode_headers({'Authorization': 'Bearer \${API_KEY}'}); assert h['Authorization'] == 'Bearer {env:API_KEY}'; print('S5 PASS')"
python3 -c "from src.utils.env_translator import translate_env_vars_for_opencode_headers; h, w = translate_env_vars_for_opencode_headers({'X-Token': '\${TOKEN:-fallback}'}); assert h['X-Token'] == '{env:TOKEN}'; assert len(w) == 1; print('S6 PASS')"
python3 -c "from src.utils.env_translator import translate_env_vars_for_opencode_headers; h, w = translate_env_vars_for_opencode_headers({'Count': 42}); assert h['Count'] == 42; print('S7 PASS')"
python3 -c "from src.utils.env_translator import translate_env_vars_for_opencode_headers; h, w = translate_env_vars_for_opencode_headers({'Content-Type': 'application/json'}); assert h['Content-Type'] == 'application/json'; print('S8 PASS')"

# Level 2: Proxy (adapter round-trip tests)
# P1: OpenCode header translation e2e -- see P1 command above
# P2: Skill deduplication -- see P2 command above
# P3+P4: Config preservation
python3 tests/verify_phase14_preservation.py
# P5: Regression suite
for f in tests/verify_*.py; do echo "--- $f ---"; python3 "$f"; done
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: Import cleanliness | [PASS/FAIL] | | |
| S2: cwd field emitted | [PASS/FAIL] | | |
| S3: enabled_tools regression | [PASS/FAIL] | | |
| S4: cwd absent when missing | [PASS/FAIL] | | |
| S5: Basic ${VAR} translation | [PASS/FAIL] | | |
| S6: Default value stripping | [PASS/FAIL] | | |
| S7: Non-string passthrough | [PASS/FAIL] | | |
| S8: No false translation | [PASS/FAIL] | | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: Header translation e2e | Headers translated in opencode.json | [actual] | [MET/MISSED] | |
| P2: Skill deduplication | 1 skipped, 1 synced | [actual] | [MET/MISSED] | |
| P3: Codex preservation | [agents] survives | [actual] | [MET/MISSED] | |
| P4: Gemini preservation | hooks key survives | [actual] | [MET/MISSED] | |
| P5: Regression suite | All tests pass | [actual] | [MET/MISSED] | |

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-14-01 | Full orchestrator sync | PENDING | Manual testing post-merge |
| DEFER-14-02 | Real-world config preservation | PENDING | User acceptance testing |

## Evaluation Confidence

**Overall confidence in evaluation design:** HIGH

**Justification:**
- Sanity checks: Adequate -- 8 checks covering all four requirements with exact assertions
- Proxy metrics: Well-evidenced -- round-trip adapter tests exercise real code paths with filesystem
- Deferred coverage: Partial but acceptable -- real-world edge cases deferred to manual testing

**What this evaluation CAN tell us:**
- Whether each requirement is implemented correctly for standard cases
- Whether existing functionality regresses
- Whether Gemini preservation works without code changes (confirming research finding)

**What this evaluation CANNOT tell us:**
- Whether TOML preservation handles all real-world config formatting variations (addressed by DEFER-14-02)
- Whether `sync_mcp_scoped()` delegation correctly inherits header translation (addressed by DEFER-14-01)
- Whether env var edge cases (nested vars, unusual casing, non-ASCII) are handled (low risk -- documented regex is specific)

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-03-09*
