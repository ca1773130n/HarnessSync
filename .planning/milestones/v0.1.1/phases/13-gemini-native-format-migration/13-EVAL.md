# Evaluation Plan: Phase 13 -- Gemini Native Format Migration

**Designed:** 2026-03-09
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** Gemini native file format writing (skills, agents, commands, MCP passthrough, GEMINI.md cleanup)
**Reference:** 13-RESEARCH.md (Gemini CLI v0.32.0 native format documentation)

## Evaluation Overview

Phase 13 is a deterministic format migration, not a probabilistic ML task. The Gemini adapter currently inlines skills, agents, and commands into GEMINI.md. This phase rewrites three sync methods to produce native files at Gemini CLI's discovery paths (`.gemini/skills/`, `.gemini/agents/`, `.gemini/commands/`), adds MCP field passthrough for four new fields, and cleans stale inlined subsections from GEMINI.md.

Because this is a format translation with well-defined input/output schemas, all critical checks can be performed as Level 1 sanity checks or Level 2 proxy tests. The only deferred items involve actual Gemini CLI integration (does the CLI discover and load the generated files correctly).

There are no ML benchmarks or probabilistic metrics. Success is binary: files are written in the correct format at the correct paths, or they are not.

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| File existence at native paths | GMN-07, GMN-08, GMN-09 requirements | Core deliverable -- files must land at discovery paths |
| Frontmatter field correctness | 13-RESEARCH.md Recommendations 1-2 | Gemini CLI requires specific frontmatter schema |
| TOML validity | 13-RESEARCH.md Recommendation 3 | Gemini CLI must parse command files |
| Argument mapping ($ARGUMENTS -> {{args}}) | GMN-09 requirement | Gemini uses different placeholder syntax |
| MCP field presence | GMN-11 requirement | Four fields currently silently dropped |
| GEMINI.md cleanup | GMN-12 requirement | Prevents duplicate content |
| No regressions in existing sync | Baseline adapter behavior | Rules/settings sync must still work |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 8 | Import, file format, path structure, value correctness |
| Proxy (L2) | 3 | End-to-end sync, regression check, edge cases |
| Deferred (L3) | 2 | Gemini CLI integration, stale file cleanup across syncs |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: Import and Syntax Check
- **What:** GeminiAdapter imports without errors after code changes
- **Command:** `python3 -c "from src.adapters.gemini import GeminiAdapter; print('OK')"`
- **Expected:** Prints `OK` with exit code 0
- **Failure means:** Syntax error or broken import in modified code

### S2: Skill Native File Output
- **What:** sync_skills writes SKILL.md to `.gemini/skills/<name>/SKILL.md` with preserved frontmatter
- **Command:** Run sync_skills with a mock skill dict, then check:
  ```
  python3 -c "
  import tempfile, sys
  from pathlib import Path
  sys.path.insert(0, '.')
  from src.adapters.gemini import GeminiAdapter
  d = Path(tempfile.mkdtemp())
  # Create source skill
  sk = d / 'source_skills' / 'test-skill'
  sk.mkdir(parents=True)
  (sk / 'SKILL.md').write_text('---\nname: test-skill\ndescription: A test skill\n---\nDo the thing.\n')
  # Run sync
  a = GeminiAdapter(d)
  r = a.sync_skills({'test-skill': sk})
  # Verify
  out = d / '.gemini' / 'skills' / 'test-skill' / 'SKILL.md'
  assert out.exists(), f'SKILL.md not at {out}'
  content = out.read_text()
  assert 'name: test-skill' in content, 'name missing from frontmatter'
  assert 'description: A test skill' in content, 'description missing'
  assert 'Do the thing.' in content, 'body missing'
  print('S2 PASS')
  "
  ```
- **Expected:** Prints `S2 PASS`
- **Failure means:** sync_skills does not write to native path or corrupts content

### S3: Agent Native File Output
- **What:** sync_agents writes `.gemini/agents/<name>.md` with Gemini-compatible frontmatter, `<role>` tags stripped, `color` field dropped
- **Command:** Create mock agent with `<role>` tags and `color` field, run sync_agents, verify output file has correct frontmatter and clean body
- **Expected:** File exists at `.gemini/agents/<name>.md`, frontmatter has `name` and `description`, no `color` field, body has no `<role>` tags
- **Failure means:** Agent field mapping is incorrect

### S4: Command TOML Output
- **What:** sync_commands writes `.gemini/commands/<name>.toml` with `description` and `prompt` fields
- **Command:** Create mock command .md with `$ARGUMENTS`, run sync_commands, verify TOML output
- **Expected:** File at `.gemini/commands/<name>.toml` contains `description = "..."` and `prompt = """..."""` with `{{args}}` replacing `$ARGUMENTS`
- **Failure means:** TOML formatting or argument mapping broken

### S5: Namespaced Command Creates Subdirectory
- **What:** Command name with colon (e.g., `harness:setup`) creates subdirectory path (`harness/setup.toml`)
- **Command:** Run sync_commands with a colon-namespaced command, check path
- **Expected:** File at `.gemini/commands/harness/setup.toml`
- **Failure means:** Namespace-to-subdirectory logic missing

### S6: MCP Field Passthrough
- **What:** `_write_mcp_to_settings` preserves `trust`, `includeTools`, `excludeTools`, `cwd` fields
- **Command:** Call MCP sync with config containing all four fields, read back settings.json
- **Expected:** All four fields present in the output server config in settings.json
- **Failure means:** New field passthrough not implemented

### S7: GEMINI.md Stale Section Cleanup
- **What:** `cleanup_legacy_inline_sections` removes `<!-- HarnessSync:Skills -->`, `<!-- HarnessSync:Agents -->`, `<!-- HarnessSync:Commands -->` markers and their content
- **Command:** Create GEMINI.md with rules section + stale subsections, run cleanup, read back
- **Expected:** No subsection markers remain; rules managed section (`<!-- Managed by HarnessSync -->`) preserved
- **Failure means:** Cleanup regex/logic incorrect or too aggressive (removes rules)

### S8: No Dual Writing
- **What:** sync_skills, sync_agents, sync_commands do NOT write to GEMINI.md (no `_write_subsection` calls)
- **Command:** Run all three sync methods, verify GEMINI.md was not modified by them
- **Expected:** GEMINI.md unchanged after calling sync_skills, sync_agents, sync_commands individually
- **Failure means:** Old inline writing code still active alongside new native writing

**Sanity gate:** ALL 8 sanity checks must pass. Any failure blocks progression.

## Level 2: Proxy Metrics

**Purpose:** End-to-end validation through the verification script and regression checks.
**IMPORTANT:** Proxy metrics here are HIGH-confidence because this is a deterministic format migration with well-defined expected outputs, not a probabilistic system.

### P1: End-to-End Verification Script
- **What:** All Phase 13 requirements verified in a single automated run
- **How:** Execute the verification script from Plan 13-02
- **Command:** `python3 tests/verify_phase13_native_formats.py`
- **Target:** All checks PASS, zero FAIL
- **Evidence:** Script covers GMN-07, GMN-08, GMN-09, GMN-11, GMN-12 with isolated temp directories
- **Correlation with full metric:** HIGH -- deterministic format checks have no ambiguity
- **Blind spots:** Does not test Gemini CLI actually loading the files; does not test edge cases beyond what the script includes
- **Validated:** No -- deferred Gemini CLI integration (D1) needed

### P2: Regression Check -- Rules and Settings Sync
- **What:** Existing sync_rules and sync_settings still work correctly after code changes
- **How:** Run existing verification scripts that test rules and settings sync
- **Command:**
  ```
  python3 tests/verify_task1_gemini.py
  python3 tests/verify_task2_gemini.py
  ```
- **Target:** All existing tests pass
- **Evidence:** These scripts were written for previous phases and validate core adapter behavior
- **Correlation with full metric:** HIGH -- directly tests unchanged functionality
- **Blind spots:** Does not test interaction between new native file writes and existing rules sync
- **Validated:** No -- existing scripts may need updates if adapter interface changed

### P3: Edge Case Coverage
- **What:** Special characters in frontmatter, TOML triple-quote edge case, empty inputs
- **How:** Run sync with inputs containing YAML-unsafe characters (colons, brackets), prompt bodies with `"""`, and empty skill/agent/command dicts
- **Command:** Part of verify_phase13_native_formats.py (Task 2 of Plan 13-02)
- **Target:** No crashes, correct escaping in output
- **Evidence:** 13-RESEARCH.md Pitfalls 2 and 4 identify these as known risks
- **Correlation with full metric:** MEDIUM -- covers known edge cases but cannot exhaustively test all possible inputs
- **Blind spots:** Unicode edge cases, very large prompt bodies, deeply nested command namespaces
- **Validated:** No

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring Gemini CLI installation or multi-sync lifecycle testing.

### D1: Gemini CLI Native File Discovery -- DEFER-13-01
- **What:** Gemini CLI actually discovers and loads the generated skill, agent, and command files
- **How:** Install Gemini CLI v0.32.0+, run sync, then run `gemini` and verify skills/agents/commands appear
- **Why deferred:** Requires Gemini CLI installed and configured; CI does not have it
- **Validates at:** Manual testing or future integration test phase
- **Depends on:** Gemini CLI v0.32.0+ installed, valid Google Cloud auth
- **Target:** `gemini skills list` shows synced skills; `/help` shows synced commands; agents available via `@agent_name`
- **Risk if unmet:** Generated files have correct content but wrong structure for Gemini's discovery mechanism. Probability: LOW (format verified against official docs). Mitigation: compare generated file structure against a manually-created working example.
- **Fallback:** Revert to inline GEMINI.md approach (code still exists as `_write_subsection`)

### D2: Stale File Cleanup Across Multiple Syncs -- DEFER-13-02
- **What:** When a skill/agent/command is removed from Claude Code source, the corresponding native file in `.gemini/` is cleaned up on next sync
- **How:** Run sync with 3 skills, remove 1 from source, run sync again, verify orphan file removed
- **Why deferred:** 13-RESEARCH.md Open Question 1 defers orphan cleanup to Phase 14+. Current phase does not implement orphan detection.
- **Validates at:** Phase 14 or later (stale file cleanup feature)
- **Depends on:** State tracking of managed files
- **Target:** No orphan files remain in `.gemini/skills/`, `.gemini/agents/`, `.gemini/commands/` after sync
- **Risk if unmet:** Ghost skills/agents/commands appear in Gemini CLI from deleted source files. Probability: HIGH (known gap). Impact: LOW (cosmetic, not functional). Mitigation: user can manually delete `.gemini/skills/<name>/` directories.
- **Fallback:** Document as known limitation; manual cleanup instructions

## Ablation Plan

**No ablation plan** -- This phase implements five independent requirements (GMN-07 through GMN-12). Each is a self-contained format change, not a sub-component of a shared algorithm. The verification script (P1) tests each requirement independently, which serves the same purpose as ablation.

## WebMCP Tool Definitions

WebMCP tool definitions skipped -- phase does not modify frontend views. This is a backend adapter/file-format migration.

## Baselines

| Baseline | Description | Expected Score | Source |
|----------|-------------|----------------|--------|
| Current GeminiAdapter | Inlines skills/agents/commands into GEMINI.md | All existing verify scripts pass | BASELINE.md + existing tests |
| sync_skills inline | Writes skills as subsection in GEMINI.md | N/A (being replaced) | src/adapters/gemini.py lines 105-171 |
| sync_agents inline | Writes agents as subsection in GEMINI.md | N/A (being replaced) | src/adapters/gemini.py lines 173-240 |
| sync_commands inline | Writes commands as bullet list in GEMINI.md | N/A (being replaced) | src/adapters/gemini.py lines 242-302 |

## Evaluation Scripts

**Location of evaluation code:**
```
tests/verify_phase13_native_formats.py  (to be created in Plan 13-02)
tests/verify_task1_gemini.py            (existing -- regression check)
tests/verify_task2_gemini.py            (existing -- regression check)
```

**How to run full evaluation:**
```bash
# Sanity: import check
python3 -c "from src.adapters.gemini import GeminiAdapter; print('OK')"

# Proxy: end-to-end verification
python3 tests/verify_phase13_native_formats.py

# Proxy: regression checks
python3 tests/verify_task1_gemini.py
python3 tests/verify_task2_gemini.py
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: Import check | [PASS/FAIL] | [output] | |
| S2: Skill native file | [PASS/FAIL] | [output] | |
| S3: Agent native file | [PASS/FAIL] | [output] | |
| S4: Command TOML | [PASS/FAIL] | [output] | |
| S5: Namespaced command | [PASS/FAIL] | [output] | |
| S6: MCP passthrough | [PASS/FAIL] | [output] | |
| S7: GEMINI.md cleanup | [PASS/FAIL] | [output] | |
| S8: No dual writing | [PASS/FAIL] | [output] | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: E2E verification | All PASS | [actual] | [MET/MISSED] | |
| P2: Regression check | All PASS | [actual] | [MET/MISSED] | |
| P3: Edge cases | No crashes | [actual] | [MET/MISSED] | |

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-13-01 | Gemini CLI discovery | PENDING | Manual testing |
| DEFER-13-02 | Stale file cleanup | PENDING | Phase 14+ |

## Evaluation Confidence

**Overall confidence in evaluation design:** HIGH

**Justification:**
- Sanity checks: Adequate -- 8 checks covering every requirement (GMN-07 through GMN-12) with specific pass/fail criteria
- Proxy metrics: Well-evidenced -- deterministic format migration means proxy tests have near-perfect correlation with real behavior. The only gap is actual Gemini CLI integration.
- Deferred coverage: Partial -- D1 (CLI discovery) is the only meaningful gap; D2 (orphan cleanup) is a known future feature

**What this evaluation CAN tell us:**
- Whether native files are written at correct paths with correct content
- Whether frontmatter, TOML, and argument mapping are correctly formatted
- Whether MCP fields are passed through
- Whether GEMINI.md cleanup preserves rules and removes stale sections
- Whether existing adapter behavior regressed

**What this evaluation CANNOT tell us:**
- Whether Gemini CLI v0.32.0 actually discovers and loads the files correctly -- deferred to manual testing (DEFER-13-01)
- Whether orphan files accumulate across multiple syncs when source content is removed -- deferred to Phase 14+ (DEFER-13-02)

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-03-09*
