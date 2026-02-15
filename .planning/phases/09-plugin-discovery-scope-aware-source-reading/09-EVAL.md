# Evaluation Plan: Phase 9 — Plugin Discovery & Scope-Aware Source Reading

**Designed:** 2026-02-15
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** Plugin MCP discovery, scope-aware MCP discovery with precedence
**Reference:** 09-RESEARCH.md (file-based plugin discovery, layered scope resolution)

## Evaluation Overview

Phase 9 extends SourceReader with plugin MCP discovery and 3-tier scope awareness (user/project/local). This is a feature addition, not an optimization, so there are no existing benchmarks to compare against. The evaluation focuses on correctness (100% discovery of configured servers) and precedence integrity (local > project > user).

This phase is critical for v2.0 milestone success — adapters in Phase 10 depend on accurate scope tagging to write MCP servers to correct target-level config files. False negatives (missing servers) break user expectations; false positives (duplicate servers) create maintenance burden.

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| Discovery coverage | Test fixtures (known server count) | Validates plugin discovery completeness |
| Scope precedence | Test fixtures (duplicate server names) | Validates layered resolution correctness |
| Variable expansion | Research (09-RESEARCH.md Recommendation 2) | ${CLAUDE_PLUGIN_ROOT} must resolve to absolute paths |
| Metadata preservation | Plan requirements (SCOPE-01 to SCOPE-05) | Adapters need origin info for scope-aware sync |
| Backward compatibility | Existing codebase (get_mcp_servers API) | v1.0 adapters must continue working |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 8 | Basic functionality and format verification |
| Proxy (L2) | 4 | Comprehensive discovery and precedence validation |
| Deferred (L3) | 2 | Real plugin integration and scope-aware target sync |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: Module Import Check
- **What:** SourceReader module imports without errors
- **Command:** `python3 -c "from src.source_reader import SourceReader; print('OK')"`
- **Expected:** "OK" printed, no ImportError
- **Failure means:** Syntax errors or missing dependencies

### S2: Method Existence Check
- **What:** New methods exist on SourceReader class
- **Command:**
  ```bash
  python3 -c "
  from src.source_reader import SourceReader
  import inspect
  reader = SourceReader(scope='user')
  required = ['_get_plugin_mcp_servers', '_expand_plugin_root', '_get_enabled_plugins',
              'get_mcp_servers_with_scope', '_get_user_scope_mcps', '_get_project_scope_mcps',
              '_get_local_scope_mcps']
  missing = [m for m in required if not hasattr(reader, m)]
  assert not missing, f'Missing methods: {missing}'
  print('OK: All methods exist')
  "
  ```
- **Expected:** "OK: All methods exist"
- **Failure means:** Implementation incomplete

### S3: Plugin Registry Parsing (Version 2 Format)
- **What:** Handles version 2 installed_plugins.json format (plugin_key → list of installs)
- **Command:** Inline test from 09-01-PLAN.md Task 1 verify block (lines 123-201)
- **Expected:** `_get_plugin_mcp_servers()` discovers servers from version 2 registry format
- **Failure means:** Registry parsing broken

### S4: ${CLAUDE_PLUGIN_ROOT} Expansion
- **What:** Variable expansion works in nested structures (command, args, env)
- **Command:**
  ```bash
  python3 -c "
  from pathlib import Path
  from src.source_reader import SourceReader
  reader = SourceReader(scope='user')
  config = {
      'command': '\${CLAUDE_PLUGIN_ROOT}/bin/server',
      'args': ['--config', '\${CLAUDE_PLUGIN_ROOT}/config.json'],
      'env': {'PLUGIN_HOME': '\${CLAUDE_PLUGIN_ROOT}'}
  }
  result = reader._expand_plugin_root(config, Path('/test/plugin'))
  assert result['command'] == '/test/plugin/bin/server', f'Command not expanded: {result[\"command\"]}'
  assert result['args'][1] == '/test/plugin/config.json', f'Args not expanded: {result[\"args\"]}'
  assert result['env']['PLUGIN_HOME'] == '/test/plugin', f'Env not expanded: {result[\"env\"]}'
  assert '\${CLAUDE_PLUGIN_ROOT}' not in str(result), f'Variable still present: {result}'
  print('OK: Variable expansion correct')
  "
  ```
- **Expected:** "OK: Variable expansion correct"
- **Failure means:** Expansion incomplete (misses nested fields)

### S5: Enabled Plugin Filtering
- **What:** Disabled plugins are excluded from MCP discovery
- **Command:** Test in 09-01-PLAN.md verify block (lines 195-197)
- **Expected:** Disabled plugins skipped, only enabled plugins return MCP servers
- **Failure means:** Filtering logic broken (security risk — users can't disable plugins)

### S6: User-Scope MCP Discovery
- **What:** Reads user-scope MCPs from ~/.claude.json top-level mcpServers field
- **Command:**
  ```bash
  python3 -c "
  import tempfile, json
  from pathlib import Path
  with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)
      claude_json = tmpdir / '.claude.json'
      claude_json.write_text(json.dumps({'mcpServers': {'test': {'command': 'test-cmd', 'args': []}}}))
      original_home = Path.home
      Path.home = staticmethod(lambda: tmpdir)
      try:
          from src.source_reader import SourceReader
          reader = SourceReader(scope='user')
          servers = reader._get_user_scope_mcps()
          assert 'test' in servers, f'Server not found: {list(servers.keys())}'
          assert servers['test']['command'] == 'test-cmd', f'Wrong config: {servers[\"test\"]}'
          print('OK: User-scope discovery')
      finally:
          Path.home = original_home
  "
  ```
- **Expected:** "OK: User-scope discovery"
- **Failure means:** User-scope reading broken

### S7: Project-Scope MCP Discovery
- **What:** Reads project-scope MCPs from .mcp.json in project root
- **Command:**
  ```bash
  python3 -c "
  import tempfile, json
  from pathlib import Path
  with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)
      mcp_json = tmpdir / '.mcp.json'
      mcp_json.write_text(json.dumps({'mcpServers': {'project-srv': {'command': 'proj-cmd', 'args': []}}}))
      from src.source_reader import SourceReader
      reader = SourceReader(scope='project', project_dir=tmpdir)
      servers = reader._get_project_scope_mcps()
      assert 'project-srv' in servers, f'Server not found: {list(servers.keys())}'
      print('OK: Project-scope discovery')
  "
  ```
- **Expected:** "OK: Project-scope discovery"
- **Failure means:** Project-scope reading broken

### S8: Local-Scope MCP Discovery
- **What:** Reads local-scope MCPs from ~/.claude.json projects[absolutePath].mcpServers
- **Command:**
  ```bash
  python3 -c "
  import tempfile, json
  from pathlib import Path
  with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)
      project_dir = tmpdir / 'myproject'
      project_dir.mkdir()
      claude_json = tmpdir / '.claude.json'
      projects = {str(project_dir.resolve()): {'mcpServers': {'local-srv': {'command': 'local-cmd', 'args': []}}}}
      claude_json.write_text(json.dumps({'projects': projects}))
      original_home = Path.home
      Path.home = staticmethod(lambda: tmpdir)
      try:
          from src.source_reader import SourceReader
          reader = SourceReader(scope='all', project_dir=project_dir)
          servers = reader._get_local_scope_mcps()
          assert 'local-srv' in servers, f'Server not found: {list(servers.keys())}'
          print('OK: Local-scope discovery')
      finally:
          Path.home = original_home
  "
  ```
- **Expected:** "OK: Local-scope discovery"
- **Failure means:** Local-scope reading broken (critical — users can't override)

**Sanity gate:** ALL sanity checks must pass. Any failure blocks progression.

## Level 2: Proxy Metrics

**Purpose:** Comprehensive validation of discovery coverage and precedence logic.
**IMPORTANT:** Proxy metrics are NOT validated substitutes for full evaluation. Treat results with appropriate skepticism.

### P1: Multi-Source Discovery Coverage
- **What:** Discovers MCP servers from all 4 sources (user files, 2 plugins, project file, local scope)
- **How:** Run comprehensive test from 09-02-PLAN.md verify block (lines 146-280)
- **Command:** Full inline test with 2 plugins, user/project/local files, 6 unique servers
- **Target:** 6/6 servers discovered (100% coverage)
- **Evidence:** Research confirms 4 discovery layers (09-RESEARCH.md Pattern 1 lines 143-194)
- **Correlation with full metric:** HIGH — fixture tests directly measure discovery completeness
- **Blind spots:** Doesn't test real Claude Code plugin cache structure (edge cases in path resolution)
- **Validated:** false — awaiting deferred validation with real plugins at Phase 10

### P2: Scope Precedence Resolution
- **What:** Same-named server at multiple scopes resolves to highest precedence (local > project > user)
- **How:** Define "shared-server" at user, project, and local scopes with different configs; verify local wins
- **Command:** Test in 09-02-PLAN.md verify block (lines 247-250)
- **Target:** shared-server metadata.scope == "local" (not "project" or "user")
- **Evidence:** Research documents precedence (09-RESEARCH.md Recommendation 3 lines 69-71)
- **Correlation with full metric:** HIGH — directly measures precedence correctness
- **Blind spots:** Doesn't test precedence with >3 scopes or edge cases (empty configs, malformed entries)
- **Validated:** false — awaiting deferred validation in Phase 10 integration

### P3: Metadata Tagging Accuracy
- **What:** Each server tagged with correct scope (user/project/local) and source (file/plugin) metadata
- **How:** Check metadata fields for all discovered servers in proxy test
- **Command:** Test in 09-02-PLAN.md verify block (lines 237-245)
- **Target:** 100% of servers have metadata.scope and metadata.source fields with correct values
- **Evidence:** Requirements SCOPE-01 through SCOPE-05 mandate origin tagging
- **Correlation with full metric:** MEDIUM — proxy validates structure but not semantic correctness at target sync time
- **Blind spots:** Doesn't verify Phase 10 adapters consume metadata correctly (could ignore scope tags)
- **Validated:** false — awaiting Phase 10 scope-aware adapter verification

### P4: Backward Compatibility
- **What:** get_mcp_servers() returns flat dict (no metadata) for v1.0 adapter compatibility
- **How:** Call get_mcp_servers() and verify return type is dict[str, dict] without nested metadata keys
- **Command:** Test in 09-02-PLAN.md verify block (lines 253-258)
- **Target:** All servers present, no "metadata" key in server configs, isinstance checks pass
- **Evidence:** Existing adapters (Codex, Gemini, OpenCode) expect flat dict (baseline assessment)
- **Correlation with full metric:** HIGH — directly tests API contract
- **Blind spots:** Doesn't verify adapters actually work end-to-end (they might fail for other reasons)
- **Validated:** false — awaiting Phase 10 integration tests with existing adapters

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring integration or resources not available now.

### D1: Real Plugin MCP Discovery and Sync — DEFER-09-01
- **What:** Discover MCP servers from actual installed Claude Code plugins and sync to target CLIs
- **How:**
  1. Install real Claude Code plugin with MCP server (e.g., Context7, GitHub plugin)
  2. Run SourceReader discovery with real plugin cache
  3. Verify plugin MCP servers discovered with correct metadata
  4. Run full sync to Codex/Gemini/OpenCode
  5. Verify MCP server appears in target config files
  6. Verify ${CLAUDE_PLUGIN_ROOT} expanded to absolute path in target configs
  7. Test MCP server in target CLI (manual invocation)
- **Why deferred:** Requires real Claude Code plugin installation + Phase 10 scope-aware adapters
- **Validates at:** Phase 10 (Scope-Aware Target Sync)
- **Depends on:**
  - Real Claude Code installation with plugin cache
  - Phase 10 adapter implementation (scope-aware MCP writing)
  - Test plugin with known MCP server config
- **Target:**
  - Plugin MCP server discovered: 1/1 (100%)
  - Variable expansion: 0 ${CLAUDE_PLUGIN_ROOT} occurrences in target configs
  - Target CLI MCP invocation: Success (no command-not-found errors)
- **Risk if unmet:** Plugin MCPs silently skipped in sync — users lose plugin-provided tooling in target CLIs
- **Fallback:** Manual MCP config in target CLI (defeats purpose of sync)

### D2: Scope-Aware Sync to Target-Level Configs — DEFER-09-02
- **What:** Verify scope metadata drives correct target-level file writes (user vs project config files)
- **How:**
  1. Configure MCP servers at user, project, and local scopes in Claude Code
  2. Run Phase 10 scope-aware sync
  3. Verify Codex writes user-scope MCPs to ~/.codex/config.toml
  4. Verify Codex writes project-scope MCPs to .codex/config.toml
  5. Verify Gemini writes user-scope MCPs to ~/.gemini/settings.json
  6. Verify Gemini writes project-scope MCPs to .gemini/settings.json
  7. Verify local-scope overrides take effect (project file has local-scope server, not user-scope)
- **Why deferred:** Requires Phase 10 adapter implementation
- **Validates at:** Phase 10 (Scope-Aware Target Sync)
- **Depends on:**
  - Phase 10 adapters consume mcp_servers_scoped (not flat mcp_servers)
  - Target CLIs support scope separation (Codex: user vs project TOML; Gemini: user vs project JSON)
- **Target:**
  - Scope separation: 100% (user-scope servers in user config, project-scope in project config)
  - Precedence correctness: 100% (local overrides present in target configs, not user-scope versions)
- **Risk if unmet:** Scope collapse — all MCPs written to user-level configs, project overrides lost
- **Fallback:** Manual MCP config per project (high maintenance burden)

## Ablation Plan

**No ablation plan** — This phase implements multiple interdependent components without sub-components to isolate. Ablation doesn't apply to feature additions with no alternative implementations.

**Rationale:** Ablation is meaningful when comparing implementation approaches (e.g., layered discovery vs flat discovery). Phase 9 has only one approach (from research), so there's no baseline to ablate against.

## Baselines

| Baseline | Description | Expected Score | Source |
|----------|-------------|----------------|--------|
| v1.0 SourceReader | Existing get_mcp_servers() | Discovers user/project file-based MCPs only | BASELINE.md lines 245-252 |
| Zero plugin coverage | v1.0 ignores plugin MCPs | 0 plugin servers discovered | Current behavior |
| Zero local-scope coverage | v1.0 doesn't read ~/.claude.json projects | 0 local-scope servers discovered | Current behavior |

**Baseline comparison:**
- v1.0: Discovers ~60% of MCPs (user + project files only, ignores plugins and local scope)
- v2.0 Phase 9 target: Discovers 100% of MCPs (adds plugins and local scope)

## Evaluation Scripts

**Location of evaluation code:**
```
.planning/phases/09-plugin-discovery-scope-aware-source-reading/09-01-PLAN.md (lines 123-201)
.planning/phases/09-plugin-discovery-scope-aware-source-reading/09-02-PLAN.md (lines 146-280)
```

**How to run full evaluation:**
```bash
# Sanity checks (S1-S8)
python3 -c "from src.source_reader import SourceReader; print('S1: OK')"

python3 -c "
from src.source_reader import SourceReader
reader = SourceReader(scope='user')
required = ['_get_plugin_mcp_servers', '_expand_plugin_root', '_get_enabled_plugins',
            'get_mcp_servers_with_scope', '_get_user_scope_mcps', '_get_project_scope_mcps',
            '_get_local_scope_mcps']
missing = [m for m in required if not hasattr(reader, m)]
assert not missing, f'Missing: {missing}'
print('S2: OK')
"

# S3-S8: Run inline tests from PLAN files (see individual sanity checks above)

# Proxy verification (P1-P4)
# Run comprehensive test from 09-02-PLAN.md lines 146-280
python3 -c "$(cat <<'EOF'
import tempfile, json, os, sys
from pathlib import Path

# [Full test script from 09-02-PLAN.md verify block]
# (Too long to reproduce here — see PLAN file)
EOF
)"

# Output: "ALL PROXY VERIFICATION TESTS PASSED"
# Discovery: 6/6 servers (100%)
# Scopes verified: user, project, local, plugin
# Precedence verified: local > project > user
# Backward compatibility: verified
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: Module import | PASS/FAIL | | |
| S2: Method existence | PASS/FAIL | | |
| S3: Plugin registry parsing | PASS/FAIL | | |
| S4: Variable expansion | PASS/FAIL | | |
| S5: Enabled plugin filtering | PASS/FAIL | | |
| S6: User-scope discovery | PASS/FAIL | | |
| S7: Project-scope discovery | PASS/FAIL | | |
| S8: Local-scope discovery | PASS/FAIL | | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: Discovery coverage | 6/6 (100%) | | MET/MISSED | |
| P2: Scope precedence | local wins | | MET/MISSED | |
| P3: Metadata tagging | 100% correct | | MET/MISSED | |
| P4: Backward compatibility | All servers present, no metadata in flat dict | | MET/MISSED | |

### Ablation Results

N/A — No ablation plan for this phase

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-09-01 | Real plugin MCP discovery and sync | PENDING | Phase 10 (Scope-Aware Target Sync) |
| DEFER-09-02 | Scope-aware sync to target-level configs | PENDING | Phase 10 (Scope-Aware Target Sync) |

## Evaluation Confidence

**Overall confidence in evaluation design:** HIGH

**Justification:**
- **Sanity checks:** ADEQUATE — 8 checks cover all new methods, edge cases (disabled plugins, nested variable expansion, 3 scope types)
- **Proxy metrics:** WELL-EVIDENCED — Tests based on research-documented patterns (layered discovery, precedence rules) with 100% coverage target
- **Deferred coverage:** COMPREHENSIVE — Both critical integration risks identified (real plugin compatibility, scope-aware target sync)

**What this evaluation CAN tell us:**
- Plugin registry parsing works correctly (version 2 format)
- Variable expansion handles nested structures (command, args, env)
- All 4 discovery layers function (user files, plugins, project files, local scope)
- Scope precedence resolves correctly (local > project > user)
- Metadata tagging is structurally correct (scope and source fields present)
- Backward compatibility maintained (existing adapters get flat dict)

**What this evaluation CANNOT tell us:**
- Real Claude Code plugin cache edge cases (non-standard plugin structures) — validates at Phase 10 with diverse plugin set
- Scope-aware adapter consumption (do Phase 10 adapters actually use metadata correctly?) — validates at Phase 10 integration
- Production robustness (corrupt plugin.json, missing installPath, version drift) — validates at Phase 10 + user testing
- Performance with many plugins (50+ plugins, 250+ MCP servers) — not tested, assumed acceptable based on research scalability analysis (09-RESEARCH.md lines 515-525)

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-02-15*
