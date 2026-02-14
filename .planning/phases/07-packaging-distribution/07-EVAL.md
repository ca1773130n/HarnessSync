# Evaluation Plan: Phase 7 — Packaging & Distribution

**Designed:** 2026-02-15
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** Plugin structure validation, cross-platform installation, marketplace distribution
**Reference papers:** N/A (engineering phase, based on Claude Code official documentation)

## Evaluation Overview

Phase 7 prepares HarnessSync for public distribution via the Claude Code plugin marketplace and GitHub. Unlike performance-focused research phases, this is a structural/packaging phase where success is binary: either the plugin structure is valid and installs correctly, or it fails validation/installation.

The evaluation focuses on three critical areas:
1. **Structural correctness** — Plugin directory structure, JSON schema compliance, file references
2. **Cross-platform installation** — install.sh and shell-integration.sh work on macOS/Linux/Windows
3. **Distribution readiness** — marketplace.json enables installation from GitHub and marketplace URLs

All metrics are deterministic (pass/fail) rather than performance-based. The primary risk is false confidence from local testing on a single platform — a plugin that works on macOS development machine but fails on Windows/Linux production environments.

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| `claude plugin validate` exit code | Official Claude Code CLI | Authoritative validation of plugin structure and schema compliance |
| Directory structure correctness | 07-RESEARCH.md Pitfall 1 | Most common plugin packaging error — components in wrong location |
| JSON schema validity | plugin.json specification | Required for plugin discovery and installation |
| Version consistency | 07-RESEARCH.md Pitfall 4 | Mismatched versions cause marketplace listing errors |
| install.sh --dry-run exit code | Cross-platform installation testing | Proxy for actual installation success (no system modifications) |
| Shell script syntax validity | bash -n / shellcheck | Catches platform-specific syntax errors before runtime |
| File reference validity | plugin.json file paths | Broken references cause component loading failures |
| GitHub source format | marketplace.json specification | Required for URL-based marketplace installation |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 14 | Structure, syntax, and file existence validation |
| Proxy (L2) | 8 | Automated installation testing and file reference checks |
| Deferred (L3) | 6 | Live Claude Code integration and multi-platform validation |

## Level 1: Sanity Checks

**Purpose:** Verify basic plugin structure, JSON validity, and file existence. These MUST ALL PASS before proceeding.

### S1: Plugin Directory Structure
- **What:** Verify .claude-plugin/ exists and contains only plugin.json and marketplace.json (components at root)
- **Command:**
  ```bash
  test -d .claude-plugin && \
  test -f .claude-plugin/plugin.json && \
  test -f .claude-plugin/marketplace.json && \
  test -d commands && \
  test -d hooks && \
  test -d src && \
  echo "Structure: PASS" || echo "Structure: FAIL"
  ```
- **Expected:** All tests pass, exit code 0
- **Failure means:** Pitfall 1 — components in .claude-plugin/ instead of root, or missing directories

### S2: Root plugin.json Removed
- **What:** Verify legacy root-level plugin.json is deleted (only .claude-plugin/plugin.json exists)
- **Command:**
  ```bash
  test ! -f plugin.json && echo "Root plugin.json removed: PASS" || echo "FAIL: Root plugin.json still exists"
  ```
- **Expected:** Root plugin.json does not exist
- **Failure means:** Plan 07-01 incomplete, migration not finished

### S3: Plugin.json Schema Validity
- **What:** Verify .claude-plugin/plugin.json is valid JSON with all required fields
- **Command:**
  ```bash
  python3 -c "
  import json
  p = json.load(open('.claude-plugin/plugin.json'))
  required = ['name', 'version', 'description', 'hooks', 'commands']
  missing = [f for f in required if f not in p]
  assert not missing, f'Missing fields: {missing}'
  assert p['name'] == 'HarnessSync'
  assert p['version'] == '1.0.0'
  print('plugin.json schema: PASS')
  "
  ```
- **Expected:** No exceptions, prints "plugin.json schema: PASS"
- **Failure means:** Invalid JSON or missing required fields

### S4: Marketplace.json Schema Validity
- **What:** Verify .claude-plugin/marketplace.json is valid JSON with GitHub source
- **Command:**
  ```bash
  python3 -c "
  import json
  m = json.load(open('.claude-plugin/marketplace.json'))
  assert 'plugins' in m and len(m['plugins']) > 0
  p = m['plugins'][0]
  assert p['source']['source'] == 'github', 'Not using GitHub source'
  assert 'repo' in p['source'], 'Missing repo field'
  print('marketplace.json schema: PASS')
  "
  ```
- **Expected:** No exceptions, prints "marketplace.json schema: PASS"
- **Failure means:** Invalid marketplace.json or using relative paths instead of GitHub source (Pitfall 2)

### S5: Version Consistency
- **What:** Verify version field matches across plugin.json and marketplace.json (both locations)
- **Command:**
  ```bash
  python3 -c "
  import json
  p = json.load(open('.claude-plugin/plugin.json'))
  m = json.load(open('.claude-plugin/marketplace.json'))
  v_plugin = p['version']
  v_marketplace_meta = m['metadata']['version']
  v_marketplace_plugin = m['plugins'][0]['version']
  assert v_plugin == v_marketplace_meta == v_marketplace_plugin, \
    f'Version mismatch: plugin={v_plugin}, meta={v_marketplace_meta}, plugins[0]={v_marketplace_plugin}'
  print(f'Version consistency: PASS ({v_plugin})')
  "
  ```
- **Expected:** All three versions match (1.0.0)
- **Failure means:** Pitfall 4 — version update missed in one location

### S6: Hooks.json Validity
- **What:** Verify hooks/hooks.json exists and is valid JSON
- **Command:**
  ```bash
  python3 -c "
  import json
  h = json.load(open('hooks/hooks.json'))
  assert 'PostToolUse' in h or any('Post' in k for k in h.keys())
  print('hooks.json: PASS')
  "
  ```
- **Expected:** Valid JSON with at least one hook defined
- **Failure means:** Hooks file missing or malformed

### S7: Commands Exist
- **What:** Verify command markdown files referenced in plugin.json exist
- **Command:**
  ```bash
  test -f commands/sync.md && \
  test -f commands/sync-status.md && \
  echo "Commands exist: PASS" || echo "FAIL: Missing command files"
  ```
- **Expected:** Both command files exist
- **Failure means:** plugin.json references broken, commands not created

### S8: MCP Server Exists
- **What:** Verify MCP server entry point exists
- **Command:**
  ```bash
  test -f src/mcp/server.py && \
  echo "MCP server exists: PASS" || echo "FAIL: MCP server missing"
  ```
- **Expected:** src/mcp/server.py exists
- **Failure means:** plugin.json mcp field references non-existent file

### S9: install.sh Executable
- **What:** Verify install.sh has execute permissions
- **Command:**
  ```bash
  test -x install.sh && echo "install.sh executable: PASS" || echo "FAIL: Not executable"
  ```
- **Expected:** install.sh is executable
- **Failure means:** chmod +x not applied

### S10: shell-integration.sh Exists
- **What:** Verify shell integration script exists
- **Command:**
  ```bash
  test -f shell-integration.sh && echo "shell-integration.sh exists: PASS" || echo "FAIL: Missing"
  ```
- **Expected:** shell-integration.sh exists
- **Failure means:** install.sh will fail to source shell integration

### S11: No cc2all Legacy References (install.sh)
- **What:** Verify install.sh has no cc2all branding (rebranded to HarnessSync)
- **Command:**
  ```bash
  ! grep -qi "cc2all" install.sh && echo "No cc2all in install.sh: PASS" || echo "FAIL: cc2all references found"
  ```
- **Expected:** No matches for "cc2all" (case-insensitive)
- **Failure means:** Rebranding incomplete

### S12: No cc2all Legacy References (shell-integration.sh)
- **What:** Verify shell-integration.sh has no cc2all branding
- **Command:**
  ```bash
  ! grep -qi "cc2all" shell-integration.sh && echo "No cc2all in shell-integration.sh: PASS" || echo "FAIL: cc2all references found"
  ```
- **Expected:** No matches for "cc2all" (case-insensitive)
- **Failure means:** Rebranding incomplete

### S13: HarnessSync Branding Present (install.sh)
- **What:** Verify install.sh contains HarnessSync branding
- **Command:**
  ```bash
  grep -q "HarnessSync" install.sh && echo "HarnessSync branding: PASS" || echo "FAIL: No HarnessSync branding"
  ```
- **Expected:** At least one "HarnessSync" reference
- **Failure means:** Generic installer without project branding

### S14: CI Workflow Exists
- **What:** Verify GitHub Actions workflow file exists
- **Command:**
  ```bash
  test -f .github/workflows/validate.yml && echo "CI workflow exists: PASS" || echo "FAIL: Missing workflow"
  ```
- **Expected:** .github/workflows/validate.yml exists
- **Failure means:** No automated validation configured

**Sanity gate:** ALL sanity checks must pass. Any failure blocks progression.

## Level 2: Proxy Metrics

**Purpose:** Indirect evaluation of installation and distribution readiness.
**IMPORTANT:** Proxy metrics are NOT validated substitutes for full evaluation. Treat results with appropriate skepticism.

### P1: install.sh Dry-Run Success
- **What:** Test install.sh --dry-run completes without errors (proxy for actual installation)
- **How:** Run install.sh with --dry-run flag, check exit code
- **Command:**
  ```bash
  bash install.sh --dry-run
  echo "Exit code: $?"
  ```
- **Target:** Exit code 0, no error output
- **Evidence:** dry-run tests all code paths except actual file writes (07-RESEARCH.md Pattern 3)
- **Correlation with full metric:** HIGH — dry-run tests platform detection, directory creation logic, shell detection without system modifications
- **Blind spots:** Doesn't test actual directory creation, shell RC modification, or symlink operations
- **Validated:** No — awaiting deferred validation at Phase 7 integration testing

### P2: Shell Script Syntax Validity (install.sh)
- **What:** Bash syntax check for install.sh
- **How:** bash -n (syntax check without execution)
- **Command:**
  ```bash
  bash -n install.sh && echo "install.sh syntax: PASS" || echo "FAIL"
  ```
- **Target:** Exit code 0
- **Evidence:** bash -n catches syntax errors, undefined variables (with set -u), and common bashisms
- **Correlation with full metric:** MEDIUM — catches syntax errors but not runtime errors (command not found, permission denied)
- **Blind spots:** Doesn't test logic errors, platform-specific command availability, or runtime behavior
- **Validated:** No — awaiting cross-platform execution testing

### P3: Shell Script Syntax Validity (shell-integration.sh)
- **What:** Bash syntax check for shell-integration.sh
- **How:** bash -n (syntax check without execution)
- **Command:**
  ```bash
  bash -n shell-integration.sh && echo "shell-integration.sh syntax: PASS" || echo "FAIL"
  ```
- **Target:** Exit code 0
- **Evidence:** Same as P2
- **Correlation with full metric:** MEDIUM — syntax validation only
- **Blind spots:** Doesn't test function definitions work correctly, wrappers trigger sync, or cooldown logic
- **Validated:** No — awaiting live shell integration testing

### P4: GitHub Actions Workflow Structure
- **What:** Verify CI workflow contains required platform matrix and validation steps
- **How:** Parse workflow YAML for key structure elements
- **Command:**
  ```bash
  python3 -c "
  import sys
  with open('.github/workflows/validate.yml') as f:
      content = f.read()
  checks = [
      ('matrix:', 'Matrix strategy'),
      ('ubuntu-latest', 'Ubuntu runner'),
      ('macos-latest', 'macOS runner'),
      ('windows-latest', 'Windows runner'),
      ('plugin.json', 'Plugin validation'),
      ('marketplace.json', 'Marketplace validation'),
      ('install.sh', 'Install script testing'),
  ]
  missing = [name for pattern, name in checks if pattern not in content]
  if missing:
      print(f'FAIL: Missing {missing}')
      sys.exit(1)
  print('Workflow structure: PASS')
  "
  ```
- **Target:** All structure elements present
- **Evidence:** Matrix workflows are standard pattern for cross-platform CI (07-RESEARCH.md Pattern 2)
- **Correlation with full metric:** MEDIUM — structure presence doesn't guarantee workflow runs successfully
- **Blind spots:** Doesn't validate YAML syntax, step order, or whether steps actually execute
- **Validated:** No — awaiting GitHub Actions execution after push

### P5: File Reference Validity (plugin.json)
- **What:** Verify all file paths referenced in plugin.json point to existing files
- **How:** Parse plugin.json and check each file path exists
- **Command:**
  ```bash
  python3 -c "
  import json, os, sys
  p = json.load(open('.claude-plugin/plugin.json'))
  refs = []
  # Commands
  if 'commands' in p:
      refs.extend(p['commands'].values())
  # Hooks
  if 'hooks' in p and isinstance(p['hooks'], str):
      refs.append(p['hooks'])
  # MCP
  if 'mcp' in p and 'server' in p['mcp']:
      refs.append(p['mcp']['server'])

  missing = [f for f in refs if not os.path.isfile(f)]
  if missing:
      print(f'FAIL: Missing files {missing}')
      sys.exit(1)
  print(f'File references: PASS ({len(refs)} files checked)')
  "
  ```
- **Target:** All referenced files exist
- **Evidence:** Broken file references cause component loading failures (07-RESEARCH.md Pitfall 6)
- **Correlation with full metric:** HIGH — file existence is necessary (but not sufficient) for plugin loading
- **Blind spots:** Doesn't validate file contents, syntax, or whether files actually work when loaded
- **Validated:** No — awaiting live plugin loading in Claude Code

### P6: Shellcheck Linting (Non-blocking)
- **What:** Run shellcheck on both shell scripts for common issues
- **How:** shellcheck with default rules (if available)
- **Command:**
  ```bash
  if command -v shellcheck >/dev/null 2>&1; then
    shellcheck install.sh shell-integration.sh && echo "Shellcheck: PASS" || echo "Shellcheck: WARNINGS (non-blocking)"
  else
    echo "Shellcheck: SKIPPED (not installed)"
  fi
  ```
- **Target:** No errors (warnings acceptable)
- **Evidence:** shellcheck catches common bash pitfalls (07-RESEARCH.md Supporting Tools)
- **Correlation with full metric:** MEDIUM — catches many issues but produces false positives
- **Blind spots:** May flag valid code patterns, doesn't test actual execution
- **Validated:** No — informational only, not blocking

### P7: Python Entry Point Validity
- **What:** Verify Python entry points (orchestrator, MCP server) have valid syntax
- **How:** python3 -m py_compile (syntax check)
- **Command:**
  ```bash
  python3 -m py_compile src/orchestrator.py src/mcp/server.py && \
  echo "Python entry points: PASS" || echo "FAIL"
  ```
- **Target:** No syntax errors
- **Evidence:** Basic sanity check for Python code
- **Correlation with full metric:** MEDIUM — syntax validity doesn't guarantee runtime correctness
- **Blind spots:** Doesn't test imports, runtime errors, or integration with shell scripts
- **Validated:** No — awaiting integration testing

### P8: Idempotent Shell RC Modification
- **What:** Verify install.sh doesn't create duplicate entries when run multiple times
- **How:** Create temporary shell RC file, run install.sh twice (dry-run), count entries
- **Command:**
  ```bash
  # This is a manual test documented in verification plan but not automated
  # Rationale: Requires mocking $HOME/.bashrc which is complex for quick check
  echo "Idempotency test: MANUAL (documented in plan, verify during execution)"
  ```
- **Target:** Only one "HarnessSync" entry in shell RC after multiple runs
- **Evidence:** Idempotent checks prevent duplicate entries (07-RESEARCH.md Pitfall 5)
- **Correlation with full metric:** HIGH — grep -q check in install.sh ensures idempotency
- **Blind spots:** Doesn't test edge cases (corrupted RC file, concurrent installs)
- **Validated:** No — manual test during execution

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring integration, live Claude Code environment, or multi-platform testing.

### D1: Claude Plugin Validate — DEFER-07-01
- **What:** Run `claude plugin validate .` to verify plugin structure and schema compliance
- **How:** Execute Claude Code CLI validation command in plugin directory
- **Why deferred:** Requires Claude Code CLI installed (not available in development environment)
- **Validates at:** phase-07-integration (manual testing before release)
- **Depends on:** Claude Code CLI installed, plugin directory structure complete
- **Target:** Exit code 0, no validation errors
- **Risk if unmet:** Plugin fails marketplace submission or installation — must fix structure and re-validate
- **Fallback:** Use manual JSON schema validation and structure checks (already in Level 1/2)

### D2: GitHub Installation — DEFER-07-02
- **What:** Install plugin from GitHub using `/plugin install github:username/HarnessSync`
- **How:** Push to GitHub repository, run installation command in Claude Code
- **Why deferred:** Requires public GitHub repository and Claude Code CLI
- **Validates at:** phase-07-integration (after repository published)
- **Depends on:** GitHub repository created, plugin.json and marketplace.json pushed, Claude Code CLI installed
- **Target:** Plugin installs successfully, all components loaded (commands, hooks, MCP available)
- **Risk if unmet:** Users cannot install from GitHub — must fix marketplace.json source configuration
- **Fallback:** Local installation via `/plugin install ./local-path` for development testing

### D3: Marketplace URL Installation — DEFER-07-03
- **What:** Install plugin from marketplace.json URL using `/plugin marketplace add`
- **How:** Host marketplace.json on GitHub Pages or raw.githubusercontent.com, add marketplace, install plugin
- **Why deferred:** Requires public hosting and Claude Code CLI
- **Validates at:** phase-07-integration (after marketplace.json published)
- **Depends on:** marketplace.json hosted at public URL, GitHub source accessible
- **Target:** Marketplace addition succeeds, plugin installable via marketplace name
- **Risk if unmet:** URL-based distribution fails — users must use GitHub installation instead
- **Fallback:** GitHub direct installation (DEFER-07-02)

### D4: Cross-Platform Installation (Linux) — DEFER-07-04
- **What:** Run install.sh on Linux (Ubuntu 22.04+) and verify installation succeeds
- **How:** GitHub Actions ubuntu-latest runner or local Ubuntu VM/container
- **Why deferred:** Requires Linux environment (development on macOS)
- **Validates at:** phase-07-ci (GitHub Actions workflow after push)
- **Depends on:** GitHub repository with workflow pushed, ubuntu-latest runner
- **Target:** install.sh completes with exit code 0, creates directories, modifies .bashrc correctly
- **Risk if unmet:** Plugin installation fails on Linux — must debug platform-specific issues (PATH differences, missing utilities)
- **Fallback:** Document Linux-specific installation steps or provide Docker container

### D5: Cross-Platform Installation (Windows) — DEFER-07-05
- **What:** Run install.sh on Windows (WSL2 and native Git Bash)
- **How:** GitHub Actions windows-latest runner with both WSL and bash tests
- **Why deferred:** Requires Windows environment (development on macOS)
- **Validates at:** phase-07-ci (GitHub Actions workflow) and manual Windows testing
- **Depends on:** GitHub repository with workflow, windows-latest runner (has WSL2 and Git Bash pre-installed)
- **Target:** install.sh completes on both WSL2 and Git Bash, junction fallback works for native Windows
- **Risk if unmet:** Windows users cannot install — must debug symlink/junction fallback, path handling
- **Fallback:** Require WSL2 for Windows users (native Windows support as best-effort)

### D6: Live Plugin Integration — DEFER-07-06
- **What:** Test plugin in live Claude Code session (hooks fire, commands execute, MCP server responds)
- **How:** Install plugin, trigger PostToolUse hook with config edit, run /sync command, query MCP server
- **Why deferred:** Requires installed plugin in active Claude Code session
- **Validates at:** phase-07-integration (after plugin installed)
- **Depends on:** Plugin installed successfully (DEFER-07-02 or DEFER-07-03), Claude Code running
- **Target:** PostToolUse hook fires and syncs on config edit, /sync command executes successfully, MCP tools callable
- **Risk if unmet:** Plugin components don't load or execute — must debug hook registration, command parsing, MCP protocol
- **Fallback:** Component-level testing (manual hook execution, direct Python script calls)

## Ablation Plan

**No ablation plan** — Phase 7 is a packaging/distribution phase with no algorithmic components to isolate. Success is binary: plugin structure valid and installs correctly, or fails validation.

Ablation is not applicable for:
- Directory structure (non-negotiable per Claude Code specification)
- JSON schema (required fields per plugin.json specification)
- install.sh (monolithic script with interdependent steps)

## Baselines

| Baseline | Description | Expected Score | Source |
|----------|-------------|----------------|--------|
| Manual installation | User manually creates .claude-plugin/, copies files | N/A (qualitative) | Pre-automation baseline |
| Local plugin load | `/plugin install ./local-path` in development | Should succeed | Development workflow |
| Legacy cc2all | Previous standalone script | Not plugin-compatible | Migration source |

Phase 7 doesn't have quantitative baselines (no performance metrics). Success criteria are binary (validation passes or fails).

## Evaluation Scripts

**Location of evaluation code:**
```
.planning/phases/07-packaging-distribution/verify_phase7.py (to be created)
```

**How to run full evaluation:**

```bash
# Level 1: Sanity checks (run from project root)
python3 .planning/phases/07-packaging-distribution/verify_phase7.py --level sanity

# Level 2: Proxy metrics
python3 .planning/phases/07-packaging-distribution/verify_phase7.py --level proxy

# Combined Level 1 + Level 2
python3 .planning/phases/07-packaging-distribution/verify_phase7.py --level all

# Individual check
python3 .planning/phases/07-packaging-distribution/verify_phase7.py --check S3
```

**Manual verification steps (for deferred items):**

```bash
# DEFER-07-01: Claude plugin validate
claude plugin validate .

# DEFER-07-02: GitHub installation
/plugin install github:username/HarnessSync

# DEFER-07-03: Marketplace URL installation
/plugin marketplace add https://raw.githubusercontent.com/username/HarnessSync/main/.claude-plugin/marketplace.json
/plugin install HarnessSync@marketplace-name

# DEFER-07-04: Linux testing (via GitHub Actions or local)
# Push to GitHub, check Actions workflow results

# DEFER-07-05: Windows testing (via GitHub Actions or local VM)
# Push to GitHub, check Actions workflow results for windows-latest

# DEFER-07-06: Live plugin integration
# Install plugin, edit CLAUDE.md, verify PostToolUse hook fires
# Run /sync command, verify sync executes
# Query MCP server: call sync_all tool via MCP client
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: Directory structure | [PASS/FAIL] | [output] | |
| S2: Root plugin.json removed | [PASS/FAIL] | [output] | |
| S3: plugin.json schema | [PASS/FAIL] | [output] | |
| S4: marketplace.json schema | [PASS/FAIL] | [output] | |
| S5: Version consistency | [PASS/FAIL] | [output] | |
| S6: hooks.json validity | [PASS/FAIL] | [output] | |
| S7: Commands exist | [PASS/FAIL] | [output] | |
| S8: MCP server exists | [PASS/FAIL] | [output] | |
| S9: install.sh executable | [PASS/FAIL] | [output] | |
| S10: shell-integration.sh exists | [PASS/FAIL] | [output] | |
| S11: No cc2all (install.sh) | [PASS/FAIL] | [output] | |
| S12: No cc2all (shell-integration) | [PASS/FAIL] | [output] | |
| S13: HarnessSync branding | [PASS/FAIL] | [output] | |
| S14: CI workflow exists | [PASS/FAIL] | [output] | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: install.sh dry-run | Exit 0 | [actual] | [MET/MISSED] | |
| P2: install.sh syntax | Exit 0 | [actual] | [MET/MISSED] | |
| P3: shell-integration syntax | Exit 0 | [actual] | [MET/MISSED] | |
| P4: Workflow structure | All present | [actual] | [MET/MISSED] | |
| P5: File references | All exist | [actual] | [MET/MISSED] | |
| P6: Shellcheck | No errors | [actual] | [MET/MISSED] | |
| P7: Python syntax | No errors | [actual] | [MET/MISSED] | |
| P8: Idempotency | Manual test | [actual] | [MET/MISSED] | |

### Ablation Results

N/A — No ablation plan for packaging phase

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-07-01 | Claude plugin validate | PENDING | phase-07-integration |
| DEFER-07-02 | GitHub installation | PENDING | phase-07-integration |
| DEFER-07-03 | Marketplace URL install | PENDING | phase-07-integration |
| DEFER-07-04 | Linux cross-platform | PENDING | phase-07-ci |
| DEFER-07-05 | Windows cross-platform | PENDING | phase-07-ci |
| DEFER-07-06 | Live plugin integration | PENDING | phase-07-integration |

## Evaluation Confidence

**Overall confidence in evaluation design:** HIGH

**Justification:**
- **Sanity checks:** ADEQUATE — 14 deterministic checks cover all structural requirements from Claude Code specification. Each check maps to a documented pitfall from 07-RESEARCH.md.
- **Proxy metrics:** WELL-EVIDENCED — 8 proxy metrics validate installation readiness without system modifications. Dry-run testing is standard practice for installation scripts. File reference checks catch broken links before runtime.
- **Deferred coverage:** COMPREHENSIVE — 6 deferred validations cover all three critical areas: (1) official CLI validation, (2) live Claude Code integration, (3) multi-platform testing. Each has clear validation criteria and fallback plan.

**What this evaluation CAN tell us:**
- Plugin structure conforms to Claude Code specification (per official documentation)
- All JSON files are syntactically valid and have required fields
- Version consistency maintained across plugin.json and marketplace.json
- File references in plugin.json point to existing files
- install.sh and shell-integration.sh have valid bash syntax and execute without errors in dry-run mode
- No legacy cc2all branding remains (rebranding complete)
- GitHub Actions workflow structure is correct for multi-platform testing

**What this evaluation CANNOT tell us:**
- Whether `claude plugin validate` actually passes (DEFER-07-01 — requires Claude Code CLI)
- Whether plugin installs successfully from GitHub or marketplace URLs (DEFER-07-02, DEFER-07-03 — requires published repository)
- Whether installation works on Linux and Windows (DEFER-07-04, DEFER-07-05 — requires multi-platform testing)
- Whether hooks/commands/MCP work in live Claude Code session (DEFER-07-06 — requires installed plugin)
- Whether install.sh correctly handles edge cases (existing installations, permission errors, missing utilities)
- Whether shell-integration wrappers actually trigger sync on CLI launch (requires live testing with Codex/Gemini/OpenCode installed)

**Evaluation limitations and mitigation:**

1. **Single platform development:** Development on macOS only.
   - **Mitigation:** GitHub Actions matrix tests on ubuntu-latest, macos-latest, windows-latest (DEFER-07-04, DEFER-07-05)

2. **No Claude Code CLI in development environment:** Cannot run `claude plugin validate` during development.
   - **Mitigation:** Level 1/2 checks approximate validation rules, manual validation before release (DEFER-07-01)

3. **Dry-run testing vs actual installation:** Dry-run doesn't test actual file writes, directory creation, or shell RC modification.
   - **Mitigation:** Code review of install.sh logic, manual installation testing on clean VM (DEFER-07-04, DEFER-07-05)

4. **No integration with Codex/Gemini/OpenCode:** Cannot test shell-integration wrappers without all three CLIs installed.
   - **Mitigation:** Deferred to Phase 3 validations (DEFER-03-01 through DEFER-03-04), focus Phase 7 on plugin structure only

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-02-15*
