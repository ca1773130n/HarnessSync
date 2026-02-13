# Evaluation Plan: Phase 3 — Gemini & OpenCode Adapters

**Designed:** 2026-02-13
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** GeminiAdapter (inline content transformation), OpenCodeAdapter (symlink-based sync)
**Reference papers:** N/A (engineering implementation, not research)

## Evaluation Overview

Phase 3 extends the proven adapter pattern from Phase 2 (Codex) to two additional AI CLI targets: Google Gemini CLI and OpenCode. This evaluation plan validates that both adapters implement all 6 required sync methods correctly and that the adapter pattern scales to three fundamentally different target architectures.

**What we're evaluating:**
- GeminiAdapter: Inline content transformation (no symlinks), YAML frontmatter stripping, settings.json MCP configuration
- OpenCodeAdapter: Symlink-based sync with stale cleanup, type-discriminated MCP configs (local/remote)
- Multi-adapter integration: All three adapters (Codex, Gemini, OpenCode) working together via AdapterRegistry

**What can be verified at this stage:**
- Level 1 (Sanity): All adapters instantiate, files created with correct structure, no Python errors
- Level 2 (Proxy): Unit tests verify each sync method, integration test syncs test project to all 3 targets
- Level 3 (Deferred): Real CLI tools load the generated configs (requires Gemini/OpenCode installed)

**What cannot be verified at this stage:**
- Real Gemini CLI skill activation from GEMINI.md (requires Gemini CLI installed and configured)
- Real OpenCode skill loading from .opencode/ symlinks (requires OpenCode installed)
- Production use across diverse project types and edge cases

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| Adapter registration count | AdapterRegistry.list_targets() | Proves all adapters auto-register on import |
| Sync success rate (synced/failed) | SyncResult from each adapter method | Direct measure of sync reliability from Phase 2 pattern |
| YAML frontmatter presence | Grep GEMINI.md for `^---$` patterns | Validates content transformation (frontmatter must be stripped) |
| Symlink validity | os.readlink() + exists() check | Validates symlink creation and stale cleanup |
| Config file validity | JSON/TOML parsing | Validates generated configs are syntactically correct |
| MCP type discrimination | JSON schema validation | Validates OpenCode uses correct type field (local/remote) |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 9 | Basic functionality and format verification |
| Proxy (L2) | 8 | Indirect performance measurement via unit/integration tests |
| Deferred (L3) | 4 | Full evaluation requiring real CLI tools |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: Adapter Registration
- **What:** All three adapters registered in AdapterRegistry after import
- **Command:** `python3 -c "from src.adapters import AdapterRegistry; print(sorted(AdapterRegistry.list_targets()))"`
- **Expected:** `['codex', 'gemini', 'opencode']`
- **Failure means:** Decorator registration broken or __init__.py missing imports

### S2: GeminiAdapter Instantiation
- **What:** GeminiAdapter can be instantiated without error
- **Command:** `python3 -c "from src.adapters import AdapterRegistry; AdapterRegistry.get_adapter('gemini', '/tmp/test')"`
- **Expected:** No exceptions, returns GeminiAdapter instance
- **Failure means:** Import errors, missing dependencies, or broken __init__

### S3: OpenCodeAdapter Instantiation
- **What:** OpenCodeAdapter can be instantiated without error
- **Command:** `python3 -c "from src.adapters import AdapterRegistry; AdapterRegistry.get_adapter('opencode', '/tmp/test')"`
- **Expected:** No exceptions, returns OpenCodeAdapter instance
- **Failure means:** Import errors, missing dependencies, or broken __init__

### S4: GEMINI.md File Creation
- **What:** GeminiAdapter.sync_rules creates GEMINI.md with HarnessSync markers
- **Command:** Unit test creates adapter, calls sync_rules, checks file exists
- **Expected:** GEMINI.md exists, contains `<!-- Managed by HarnessSync -->`
- **Failure means:** File I/O broken, marker injection failed

### S5: GEMINI.md Valid Markdown
- **What:** Generated GEMINI.md is valid markdown (no YAML frontmatter outside code blocks)
- **Command:** `grep -E '^---$' GEMINI.md | wc -l` (should be 0 or only in separators, not frontmatter)
- **Expected:** No YAML frontmatter patterns (`---\nkey: value\n---`) present
- **Failure means:** Frontmatter stripping failed

### S6: settings.json Valid JSON
- **What:** GeminiAdapter.sync_mcp creates valid JSON config
- **Command:** `python3 -m json.tool .gemini/settings.json > /dev/null`
- **Expected:** Exit code 0 (valid JSON)
- **Failure means:** JSON generation broken, write_json_atomic failed

### S7: opencode.json Valid JSON with Schema
- **What:** OpenCodeAdapter.sync_mcp creates valid JSON with $schema field
- **Command:** `python3 -c "import json; c=json.load(open('opencode.json')); assert c.get('\$schema') == 'https://opencode.ai/config.json'"`
- **Expected:** Exit code 0, schema field present
- **Failure means:** Config structure broken, missing schema declaration

### S8: Symlink Creation (.opencode/skills/)
- **What:** OpenCodeAdapter.sync_skills creates valid symlinks
- **Command:** `test -L .opencode/skills/test-skill && test -e .opencode/skills/test-skill`
- **Expected:** Both tests pass (symlink exists and target exists)
- **Failure means:** Symlink creation failed or create_symlink_with_fallback broken

### S9: No Broken Symlinks
- **What:** No broken symlinks remain after sync with stale cleanup
- **Command:** `find .opencode -type l ! -exec test -e {} \; -print | wc -l`
- **Expected:** 0 (no broken symlinks found)
- **Failure means:** Stale cleanup logic not working

**Sanity gate:** ALL sanity checks must pass. Any failure blocks progression.

## Level 2: Proxy Metrics

**Purpose:** Indirect evaluation of quality/performance.
**IMPORTANT:** Proxy metrics are NOT validated substitutes for full evaluation. Treat results with appropriate skepticism.

### P1: GeminiAdapter Sync Success Rate
- **What:** All 6 sync methods return SyncResult with synced > 0, failed == 0
- **How:** Unit test calls each method with valid test data
- **Command:** `python3 tests/test_gemini_adapter.py -v`
- **Target:** 6/6 methods pass (100% success rate)
- **Evidence:** Phase 2 Codex adapter achieved 100% success rate (02-03-SUMMARY.md)
- **Correlation with full metric:** HIGH — If unit tests pass, real CLI likely works (proven in Phase 2)
- **Blind spots:** Real Gemini CLI may have undocumented format requirements
- **Validated:** No — awaiting deferred validation with real Gemini CLI

### P2: OpenCodeAdapter Sync Success Rate
- **What:** All 6 sync methods return SyncResult with synced > 0, failed == 0
- **How:** Unit test calls each method with valid test data
- **Command:** `python3 tests/test_opencode_adapter.py -v`
- **Target:** 6/6 methods pass (100% success rate)
- **Evidence:** Phase 2 Codex adapter achieved 100% success rate
- **Correlation with full metric:** HIGH — Unit test coverage proven reliable in Phase 2
- **Blind spots:** Real OpenCode CLI may reject configs for undocumented reasons
- **Validated:** No — awaiting deferred validation with real OpenCode CLI

### P3: YAML Frontmatter Stripping
- **What:** Inlined skills in GEMINI.md have frontmatter removed
- **How:** Parse test SKILL.md with frontmatter, sync, verify GEMINI.md has no `---` patterns
- **Command:** `grep -c '^---$' GEMINI.md` (expect 0 or only in separators)
- **Target:** 0 frontmatter blocks detected
- **Evidence:** Research 03-RESEARCH.md confirms Gemini expects plain markdown sections
- **Correlation with full metric:** HIGH — Gemini CLI documented to require plain markdown
- **Blind spots:** Frontmatter in code blocks might trigger false positives
- **Validated:** No — awaiting Gemini CLI skill activation test

### P4: MCP Type Discrimination (OpenCode)
- **What:** Stdio servers get type: "local", URL servers get type: "remote"
- **How:** Sync MCP with both types, parse opencode.json, verify type fields
- **Command:** `python3 -c "import json; c=json.load(open('opencode.json')); assert c['mcp']['stdio-server']['type']=='local'; assert c['mcp']['url-server']['type']=='remote'"`
- **Target:** Both assertions pass
- **Evidence:** OpenCode config schema at https://opencode.ai/config.json requires type field
- **Correlation with full metric:** HIGH — Schema validation will catch incorrect types
- **Blind spots:** OpenCode may silently ignore servers with wrong type
- **Validated:** No — awaiting OpenCode MCP connection test

### P5: Permission Mapping Conservative
- **What:** No adapter auto-enables dangerous modes (yolo, danger-full-access)
- **How:** Sync settings with deny list, verify target configs use restrictive modes
- **Command:** Grep configs for `yolo`, `danger-full-access`, `unrestricted`
- **Target:** 0 occurrences in generated configs
- **Evidence:** Phase 2 established conservative mapping (deny → read-only sandbox)
- **Correlation with full metric:** HIGH — Security regression would be obvious in configs
- **Blind spots:** CLI may have other dangerous modes not documented
- **Validated:** No — awaiting manual security audit

### P6: Stale Symlink Cleanup
- **What:** Broken symlinks removed after sync
- **How:** Create stale symlink, sync skills, verify stale symlink deleted
- **Command:** Unit test creates broken symlink, calls sync_skills, checks symlink gone
- **Target:** cleanup_stale_symlinks removes 1 stale link
- **Evidence:** Research pattern from 03-RESEARCH.md (stale cleanup logic)
- **Correlation with full metric:** MEDIUM — Tests synthetic case, not real drift scenario
- **Blind spots:** Race conditions, permission errors on deletion
- **Validated:** No — awaiting production drift testing

### P7: Config Merge Preservation
- **What:** Existing config content preserved during sync (merge, not overwrite)
- **How:** Create config with custom field, sync MCP, verify custom field still present
- **Command:** Unit test writes settings.json with `{"custom": "value"}`, syncs MCP, verifies custom preserved
- **Target:** Custom fields retained after merge
- **Evidence:** Phase 2 decision (Config Merge Strategy in 02-03-SUMMARY.md)
- **Correlation with full metric:** HIGH — Overwrite would delete custom content (obvious failure)
- **Blind spots:** Deep nested merge edge cases
- **Validated:** No — awaiting production config evolution testing

### P8: 3-Adapter Integration Test
- **What:** All three adapters sync same test project successfully
- **How:** Create test project with rules/skills/agents/commands/MCP, sync to all 3 targets
- **Command:** `python3 tests/test_3_adapter_integration.py`
- **Target:** 3/3 adapters succeed, 0 failures, all artifacts created
- **Evidence:** Plan 03-02 specifies 3-adapter integration as success criteria
- **Correlation with full metric:** MEDIUM — Proves adapters don't interfere, not that they work correctly
- **Blind spots:** Adapters might all succeed but generate incorrect configs
- **Validated:** No — awaiting real CLI multi-target testing

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring integration or resources not available in-phase.

### D1: Real Gemini CLI Skill Activation — DEFER-03-01
- **What:** Gemini CLI loads GEMINI.md and activates inlined skills
- **How:** Install Gemini CLI, run in test project, verify skills available via `/help`
- **Why deferred:** Requires Gemini CLI installed (not available in CI/testing environment)
- **Validates at:** phase-04-manual-testing or user acceptance testing
- **Depends on:** Gemini CLI installation, API key configuration
- **Target:** All synced skills appear in Gemini skill list, can be invoked
- **Risk if unmet:** Gemini format incompatible (would need to debug with real CLI, potentially 1 additional plan)
- **Fallback:** Check Gemini CLI logs, compare GEMINI.md format to official examples, adjust inlining

### D2: Real OpenCode Symlink Loading — DEFER-03-02
- **What:** OpenCode CLI loads skills/agents/commands from .opencode/ via symlinks
- **How:** Install OpenCode, run in test project, verify skills discovered
- **Why deferred:** Requires OpenCode installed (not available in CI/testing environment)
- **Validates at:** phase-04-manual-testing or user acceptance testing
- **Depends on:** OpenCode installation, project initialization
- **Target:** All symlinked skills/agents/commands appear in OpenCode and work correctly
- **Risk if unmet:** OpenCode symlink traversal broken (would need copy fallback, 0.5 additional plans)
- **Fallback:** Switch to file copy instead of symlinks (increases sync time, loses zero-copy benefit)

### D3: MCP Server Connection (Both Adapters) — DEFER-03-03
- **What:** MCP servers connect successfully via Gemini settings.json and OpenCode opencode.json
- **How:** Configure test MCP server, sync configs, verify connection in CLI logs
- **Why deferred:** Requires MCP server running (complex setup, not in scope for Phase 3)
- **Validates at:** phase-05-production-evaluation or when MCP feature needed
- **Depends on:** MCP server implementation, network access, auth credentials
- **Target:** 2/2 MCP servers connect (1 stdio, 1 URL) in both Gemini and OpenCode
- **Risk if unmet:** MCP translation incorrect (HIGH impact — MCP is key feature, would need 1 full plan to fix)
- **Fallback:** Manual MCP config editing, document translation limitations

### D4: Permission Security Audit — DEFER-03-04
- **What:** Manual security review of permission mappings across all 3 adapters
- **How:** Security expert reviews deny lists, sandbox modes, yolo settings
- **Why deferred:** Requires domain expertise and threat modeling (not automatable)
- **Validates at:** phase-06-security-review or pre-production checklist
- **Depends on:** Security expert availability, production threat model
- **Target:** Zero permission downgrades (Claude deny → target allow), zero auto-enabled dangerous modes
- **Risk if unmet:** Security vulnerability shipped (CRITICAL — would need immediate hotfix)
- **Fallback:** Add warning banner to docs, require manual permission review before use

## Ablation Plan

**No ablation plan** — Phase 3 implements two complete adapters following the same pattern. No sub-components to isolate. The pattern itself was validated in Phase 2 (Codex adapter).

**Alternative comparison:**
| Adapter | Content Strategy | MCP Format | Permission Model |
|---------|-----------------|------------|------------------|
| Codex | Symlinks + AGENTS.md markers | TOML (config.toml) | Sandbox modes (read-only/danger-full-access) |
| Gemini | Inline to GEMINI.md (no symlinks) | JSON (settings.json mcpServers) | Tools allow/deny lists (never yolo) |
| OpenCode | Symlinks to .opencode/ | JSON (opencode.json with type discrimination) | Permission mode (restricted/default) |

All three must achieve 100% sync success to prove adapter pattern scales.

## Baselines

| Baseline | Description | Expected Score | Source |
|----------|-------------|----------------|--------|
| Phase 2 Codex | Single adapter sync success | 7 synced, 5 adapted, 0 failed | 02-03-SUMMARY.md |
| Zero adapters | Before Phase 2 | No adapters registered | Initial state |
| Target: 3 adapters | Phase 3 goal | 3 registered, all pass integration test | Plan 03-02 success criteria |

**No performance baselines** — This is a plugin/tool project (not ML). Success is boolean (works/doesn't work), not continuous metric.

## Evaluation Scripts

**Location of evaluation code:**
```
tests/test_gemini_adapter.py       # Unit tests for GeminiAdapter (6 sync methods)
tests/test_opencode_adapter.py     # Unit tests for OpenCodeAdapter (6 sync methods)
tests/test_3_adapter_integration.py  # Integration test (all 3 adapters sync same project)
tests/test_write_json_atomic.py    # Utility test for atomic JSON writes
```

**How to run full evaluation:**
```bash
# Sanity checks (must pass first)
python3 -c "from src.adapters import AdapterRegistry; assert sorted(AdapterRegistry.list_targets()) == ['codex', 'gemini', 'opencode']"

# Proxy metrics (unit tests)
python3 -m pytest tests/test_gemini_adapter.py -v
python3 -m pytest tests/test_opencode_adapter.py -v
python3 -m pytest tests/test_3_adapter_integration.py -v

# Deferred validations (manual, requires CLI tools)
# See TESTING.md for manual test procedures
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: Adapter Registration | [PASS/FAIL] | [output] | |
| S2: GeminiAdapter Instantiation | [PASS/FAIL] | [output] | |
| S3: OpenCodeAdapter Instantiation | [PASS/FAIL] | [output] | |
| S4: GEMINI.md File Creation | [PASS/FAIL] | [output] | |
| S5: GEMINI.md Valid Markdown | [PASS/FAIL] | [output] | |
| S6: settings.json Valid JSON | [PASS/FAIL] | [output] | |
| S7: opencode.json Valid JSON | [PASS/FAIL] | [output] | |
| S8: Symlink Creation | [PASS/FAIL] | [output] | |
| S9: No Broken Symlinks | [PASS/FAIL] | [output] | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: GeminiAdapter Success | 6/6 methods | [actual] | [MET/MISSED] | |
| P2: OpenCodeAdapter Success | 6/6 methods | [actual] | [MET/MISSED] | |
| P3: Frontmatter Stripping | 0 occurrences | [actual] | [MET/MISSED] | |
| P4: MCP Type Discrimination | Both pass | [actual] | [MET/MISSED] | |
| P5: Conservative Permissions | 0 dangerous modes | [actual] | [MET/MISSED] | |
| P6: Stale Symlink Cleanup | 1 removed | [actual] | [MET/MISSED] | |
| P7: Config Merge | Custom preserved | [actual] | [MET/MISSED] | |
| P8: 3-Adapter Integration | 3/3 pass | [actual] | [MET/MISSED] | |

### Ablation Results

N/A — No ablation tests for this phase (pattern already validated in Phase 2)

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-03-01 | Real Gemini CLI skill activation | PENDING | phase-04-manual-testing |
| DEFER-03-02 | Real OpenCode symlink loading | PENDING | phase-04-manual-testing |
| DEFER-03-03 | MCP server connection | PENDING | phase-05-production-eval |
| DEFER-03-04 | Permission security audit | PENDING | phase-06-security-review |

## Evaluation Confidence

**Overall confidence in evaluation design:** MEDIUM-HIGH

**Justification:**
- Sanity checks: ADEQUATE — Cover file creation, format validity, symlink integrity (comprehensive for infrastructure code)
- Proxy metrics: WELL-EVIDENCED — Phase 2 unit tests proven reliable predictor of real CLI compatibility (HIGH evidence)
- Deferred coverage: COMPREHENSIVE — All major risks identified with clear validation plans

**What this evaluation CAN tell us:**
- All three adapters implement the required interface correctly (6 sync methods each)
- Generated configs are syntactically valid (JSON/TOML parse successfully)
- Content transformation works (frontmatter stripped, symlinks created)
- Adapters don't interfere with each other (3-adapter integration passes)
- Permission mappings follow conservative rules (no auto-dangerous modes)

**What this evaluation CANNOT tell us:**
- Whether Gemini CLI actually loads GEMINI.md correctly (DEFER-03-01 — requires real CLI)
- Whether OpenCode follows symlinks correctly (DEFER-03-02 — requires real CLI)
- Whether MCP servers connect via generated configs (DEFER-03-03 — requires MCP infrastructure)
- Whether permission mappings are secure in production (DEFER-03-04 — requires security audit)
- Real-world robustness across diverse projects (only tested with synthetic test data)

**Confidence compared to Phase 2:** SIMILAR — Using same proxy metric strategy (unit tests + integration test) that worked for Codex adapter. Phase 2 achieved 100% success rate with this approach, giving confidence in Phase 3.

**Known gaps:**
1. **Real CLI validation:** Proxy metrics assume CLI format compatibility based on official docs, but not tested against real tools
2. **Production diversity:** Test data is synthetic (simple skills/agents), may not cover edge cases in real projects
3. **Error handling:** Tests focus on happy path, less coverage of malformed inputs or permission errors
4. **Performance:** No load testing (100+ skills, large GEMINI.md files)

**Mitigation:**
- Gap 1: Defer to manual testing phase with real CLIs installed
- Gap 2: Encourage early adopters to test on real projects, collect feedback
- Gap 3: Add error handling tests in future iterations based on bug reports
- Gap 4: Add performance tests if users report slowness (not anticipated for typical project sizes)

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-02-13*
