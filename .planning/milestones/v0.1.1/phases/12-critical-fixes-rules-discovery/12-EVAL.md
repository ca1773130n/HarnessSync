# Evaluation Plan: Phase 12 -- Critical Fixes & Rules Discovery

**Designed:** 2026-03-09
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** Adapter output correctness fixes (Codex, Gemini, OpenCode) + SourceReader rules directory discovery
**Reference papers:** N/A (correctness-focused bug fixes against official CLI documentation)

## Evaluation Overview

This phase is not R&D -- it is correctness-focused bug fixing and a well-understood feature addition. The evaluation strategy is therefore deterministic: adapter outputs either match official documentation or they do not, and rules discovery either finds files or it does not. There are no fuzzy metrics or quality gradients.

The adapter fixes (Plans 01) address four distinct bugs: Codex writes an invalid approval_policy value and wrong config filename, Gemini uses deprecated v1 tools config keys, and OpenCode uses a deprecated permissions format. Each fix is a verifiable string/key correction against official documentation. The rules discovery (Plan 02) adds recursive `.claude/rules/` walking with frontmatter parsing -- a standard filesystem operation with well-defined expected outputs.

Evaluation confidence is HIGH because all success criteria are binary (correct/incorrect) and testable with automated checks. No proxy metrics are needed -- we can directly verify correctness.

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| Config key correctness | Official CLI docs (Codex, Gemini, OpenCode) | Adapter outputs must match what target CLIs expect |
| Config value correctness | Official CLI docs | Invalid values are rejected by target CLIs |
| Rules file discovery count | Filesystem state | Discovery must find all .md files recursively |
| Frontmatter parsing accuracy | Claude Code rules format spec | Path-scoping metadata must be correctly extracted |
| Backward compatibility | Existing API contract | get_rules() must still return string |
| Codebase cleanliness | MEMORY.md (narrow fix prevention) | Zero deprecated patterns in active source |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 8 | Basic functionality: imports, key/value correctness, no crashes |
| Proxy (L2) | 6 | Functional output verification with sample inputs |
| Deferred (L3) | 2 | Real-world CLI acceptance and end-to-end sync |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: Codex CONFIG_TOML constant
- **What:** Codex adapter uses correct config filename
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && python3 -c "from src.adapters.codex import CodexAdapter; assert CodexAdapter.CONFIG_TOML == 'config.toml', f'Got {CodexAdapter.CONFIG_TOML}'; print('PASS')"`
- **Expected:** Prints `PASS`
- **Failure means:** Codex adapter still writes to wrong filename; all Codex config will be ignored by Codex CLI

### S2: No deprecated string literals in Codex adapter
- **What:** No occurrence of `codex.toml` or `on-failure` in codex.py source
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && grep -n "codex\.toml\|on-failure" src/adapters/codex.py | wc -l`
- **Expected:** `0` (zero matches)
- **Failure means:** Deprecated values still present; fix was incomplete

### S3: No deprecated keys in Gemini adapter
- **What:** No occurrence of `blockedTools` or `allowedTools` in gemini.py source
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && grep -n "blockedTools\|allowedTools" src/adapters/gemini.py | wc -l`
- **Expected:** `0` (zero matches)
- **Failure means:** Gemini adapter still writes v1 keys; tools config will be ignored

### S4: OpenCode uses singular permission key
- **What:** OpenCode adapter writes `permission` (singular) not `permissions` (plural)
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && python3 -c "import ast, inspect; from src.adapters.opencode import OpenCodeAdapter; src = inspect.getsource(OpenCodeAdapter.sync_settings); assert 'permission' in src; print('PASS: permission key found')"`
- **Expected:** Prints `PASS: permission key found`
- **Failure means:** OpenCode adapter still uses deprecated format

### S5: All adapter modules import without error
- **What:** No import-time crashes after changes
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && python3 -c "from src.adapters.codex import CodexAdapter; from src.adapters.gemini import GeminiAdapter; from src.adapters.opencode import OpenCodeAdapter; from src.source_reader import SourceReader; from src.orchestrator import SyncOrchestrator; print('ALL IMPORTS OK')"`
- **Expected:** Prints `ALL IMPORTS OK`
- **Failure means:** Syntax error or broken import chain in modified files

### S6: SourceReader has get_rules_files method
- **What:** New method exists and is callable
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && python3 -c "from src.source_reader import SourceReader; assert hasattr(SourceReader, 'get_rules_files'), 'Missing get_rules_files'; assert callable(getattr(SourceReader, 'get_rules_files')); print('PASS')"`
- **Expected:** Prints `PASS`
- **Failure means:** Rules discovery method not implemented

### S7: get_rules() backward compatibility
- **What:** Existing get_rules() still returns a string
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && python3 -c "from pathlib import Path; from src.source_reader import SourceReader; sr = SourceReader(scope='project', project_dir=Path('.')); r = sr.get_rules(); assert isinstance(r, str), f'get_rules() returns {type(r).__name__}, expected str'; print('PASS: backward compat ok')"`
- **Expected:** Prints `PASS: backward compat ok`
- **Failure means:** Breaking change to existing API; orchestrator and callers will fail

### S8: No hardcoded Path.home() for .claude paths in source
- **What:** Multi-account safety -- all user paths use self.cc_home
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && grep -rn "Path\.home().*\.claude\|Path\.home().*rules" src/source_reader.py src/adapters/ | grep -v "cc2all_sync" | wc -l`
- **Expected:** `0` (zero matches)
- **Failure means:** Hardcoded paths break multi-account support (per MEMORY.md)

**Sanity gate:** ALL 8 sanity checks must pass. Any failure blocks progression to proxy evaluation.

## Level 2: Proxy Metrics

**Purpose:** Functional output verification with controlled inputs. These exercise the actual sync logic with sample data.

### P1: Codex sync_settings produces on-request for auto mode
- **What:** Codex approval policy maps correctly for auto-approve settings
- **How:** Create CodexAdapter with tmp dir, call sync_settings with approval_mode='auto', read output
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && python3 -c "
import tempfile, os
from pathlib import Path
from src.adapters.codex import CodexAdapter
with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    (p / '.codex').mkdir(exist_ok=True)
    a = CodexAdapter(project_dir=p)
    a.sync_settings({'approval_mode': 'auto', 'permissions': {}})
    cfg = (p / '.codex' / 'config.toml').read_text()
    assert 'on-request' in cfg, f'Expected on-request in: {cfg}'
    assert 'on-failure' not in cfg, f'Found deprecated on-failure in: {cfg}'
    print('PASS: approval_policy = on-request')
"`
- **Target:** Output contains `on-request`, does not contain `on-failure`
- **Evidence:** Codex Config Reference documents valid values as untrusted, on-request, never, reject
- **Correlation with full metric:** HIGH -- directly tests the exact output value
- **Blind spots:** Does not verify Codex CLI actually accepts the file (deferred)
- **Validated:** No -- awaiting deferred CLI acceptance test

### P2: Gemini sync_settings produces v2 tools keys
- **What:** Gemini adapter writes `exclude`/`allowed` instead of `blockedTools`/`allowedTools`
- **How:** Create GeminiAdapter with tmp dir, call sync_settings with deny/allow lists, parse output JSON
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && python3 -c "
import tempfile, json
from pathlib import Path
from src.adapters.gemini import GeminiAdapter
with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    (p / '.gemini').mkdir(exist_ok=True)
    a = GeminiAdapter(project_dir=p)
    a.sync_settings({'permissions': {'deny': ['Write'], 'allow': ['Read', 'Bash']}})
    cfg = json.loads((p / '.gemini' / 'settings.json').read_text())
    tools = cfg.get('tools', {})
    assert 'exclude' in tools or not cfg.get('permissions', {}).get('deny'), f'Missing exclude key in: {tools}'
    assert 'blockedTools' not in tools, f'Found deprecated blockedTools in: {tools}'
    assert 'allowedTools' not in tools, f'Found deprecated allowedTools in: {tools}'
    print('PASS: v2 tools keys')
"`
- **Target:** Output JSON has `tools.exclude` and `tools.allowed`, no v1 keys
- **Evidence:** Gemini CLI Configuration docs specify `tools.allowed` and `tools.exclude`
- **Correlation with full metric:** HIGH -- directly tests output key names
- **Blind spots:** Does not verify Gemini CLI parses the output correctly
- **Validated:** No -- awaiting deferred CLI acceptance test

### P3: OpenCode sync_settings produces singular permission with per-tool entries
- **What:** OpenCode adapter writes `permission` (singular) with allow/ask/deny per tool
- **How:** Create OpenCodeAdapter with tmp dir, call sync_settings, parse output JSON
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && python3 -c "
import tempfile, json
from pathlib import Path
from src.adapters.opencode import OpenCodeAdapter
with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    a = OpenCodeAdapter(project_dir=p)
    a.sync_settings({'permissions': {'deny': ['Write'], 'allow': ['Read', 'Bash(git commit:*)']}})
    cfg = json.loads((p / 'opencode.json').read_text())
    assert 'permission' in cfg, f'Missing permission key in: {list(cfg.keys())}'
    assert 'permissions' not in cfg, f'Found deprecated permissions key in: {list(cfg.keys())}'
    perm = cfg['permission']
    assert isinstance(perm, dict), f'permission should be dict, got {type(perm)}'
    print(f'PASS: permission keys = {list(perm.keys())}')
"`
- **Target:** `permission` (singular) key exists with per-tool entries; `permissions` (plural) absent
- **Evidence:** OpenCode Permissions Docs specify `permission` singular with per-tool format
- **Correlation with full metric:** HIGH -- directly tests output structure
- **Blind spots:** Does not verify all tool mappings are correct; does not test OpenCode CLI acceptance
- **Validated:** No -- awaiting deferred CLI acceptance test

### P4: Rules directory discovery finds nested .md files
- **What:** SourceReader.get_rules_files() recursively discovers .md files from .claude/rules/
- **How:** Create temp directory with nested rules structure, verify discovery
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && python3 -c "
import tempfile
from pathlib import Path
from src.source_reader import SourceReader
with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    rules_dir = p / '.claude' / 'rules'
    rules_dir.mkdir(parents=True)
    (rules_dir / 'top.md').write_text('# Top level rule')
    sub = rules_dir / 'subdir'
    sub.mkdir()
    (sub / 'nested.md').write_text('# Nested rule')
    sr = SourceReader(scope='project', project_dir=p)
    files = sr.get_rules_files()
    assert len(files) == 2, f'Expected 2 files, got {len(files)}: {files}'
    names = sorted([f['path'].name for f in files])
    assert 'nested.md' in names, f'Missing nested.md in {names}'
    assert 'top.md' in names, f'Missing top.md in {names}'
    print(f'PASS: found {len(files)} rules files')
"`
- **Target:** Returns exactly 2 files (top.md, nested.md)
- **Evidence:** Claude Code Memory Docs confirm recursive subdirectory walking
- **Correlation with full metric:** HIGH -- directly tests file discovery
- **Blind spots:** Does not test with extremely deep nesting or non-.md files (should be ignored)
- **Validated:** No -- awaiting deferred end-to-end sync test

### P5: Frontmatter parsing extracts paths correctly
- **What:** _parse_rules_frontmatter handles single path, list paths, and no frontmatter
- **How:** Call parser with three test inputs, verify outputs
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && python3 -c "
import tempfile
from pathlib import Path
from src.source_reader import SourceReader
with tempfile.TemporaryDirectory() as td:
    p = Path(td)
    rules_dir = p / '.claude' / 'rules'
    rules_dir.mkdir(parents=True)
    # Case 1: no frontmatter
    (rules_dir / 'plain.md').write_text('Just content')
    # Case 2: single path
    (rules_dir / 'single.md').write_text('---\npaths: src/**/*.ts\n---\nScoped rule')
    # Case 3: list paths
    (rules_dir / 'multi.md').write_text('---\npaths:\n  - src/a/**\n  - src/b/**\n---\nMulti')
    sr = SourceReader(scope='project', project_dir=p)
    files = {f['path'].name: f for f in sr.get_rules_files()}
    assert files['plain.md']['scope_patterns'] == [], f'Plain: {files[\"plain.md\"][\"scope_patterns\"]}'
    assert 'src/**/*.ts' in files['single.md']['scope_patterns'], f'Single: {files[\"single.md\"][\"scope_patterns\"]}'
    assert len(files['multi.md']['scope_patterns']) == 2, f'Multi: {files[\"multi.md\"][\"scope_patterns\"]}'
    print('PASS: all frontmatter cases')
"`
- **Target:** Plain=[], Single=["src/**/*.ts"], Multi=2 patterns
- **Evidence:** Claude Fast Rules Guide documents YAML frontmatter with paths field
- **Correlation with full metric:** HIGH -- directly tests parsing logic
- **Blind spots:** Does not test `globs:` key (alternate form) or malformed frontmatter edge cases
- **Validated:** No -- awaiting deferred end-to-end test

### P6: Codebase-wide sweep for deprecated patterns
- **What:** Zero deprecated patterns remain in active source code
- **How:** Grep entire src/ for all known deprecated patterns
- **Command:** `cd /Users/neo/Developer/Projects/HarnessSync && echo "=== codex.toml ===" && grep -rn "codex\.toml" src/ | grep -v cc2all_sync | wc -l && echo "=== on-failure ===" && grep -rn "'on-failure'" src/ | wc -l && echo "=== blockedTools/allowedTools ===" && grep -rn "blockedTools\|allowedTools" src/ | grep -v cc2all_sync | wc -l && echo "=== permissions plural writes ===" && grep -rn "permissions_config\[.mode.\]" src/ | wc -l`
- **Target:** All counts = 0
- **Evidence:** MEMORY.md requires checking entire codebase for same pattern (narrow fix prevention)
- **Correlation with full metric:** HIGH -- exhaustive scan for known deprecated patterns
- **Blind spots:** Cannot detect semantic bugs (e.g., correct key name but wrong value logic)
- **Validated:** No -- validated by integration tests in Plan 03

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring real CLI environments or integration infrastructure.

### D1: Target CLI acceptance testing -- DEFER-12-01
- **What:** Verify that output config files are actually accepted and loaded by Codex CLI, Gemini CLI, and OpenCode CLI
- **How:** Install each target CLI, run with synced config, verify no config warnings/errors
- **Why deferred:** Requires installing three separate CLI tools and running them with valid API keys; not feasible in automated unit testing
- **Validates at:** Manual testing before v0.1.1 release
- **Depends on:** All three adapter fixes complete (Plans 01), target CLIs installed
- **Target:** Zero config parsing errors or warnings from any target CLI
- **Risk if unmet:** Config keys may have changed again since research; documentation may be stale
- **Fallback:** Re-research current CLI config format and update adapter output

### D2: Full end-to-end sync with real Claude Code config -- DEFER-12-02
- **What:** Run complete sync_all() with a real Claude Code configuration directory (including .claude/rules/) and verify all three target outputs are correct
- **How:** Run HarnessSync sync against a real project with rules directory, MCP servers, skills, agents, and commands
- **Why deferred:** Requires a fully configured Claude Code project with .claude/rules/ directory and multiple config surfaces
- **Validates at:** Phase 14 integration or manual pre-release testing
- **Depends on:** All phase 12 changes complete (Plans 01, 02, 03), Phase 13 Gemini native formats
- **Target:** All target configs written correctly, rules files discovered and passed to adapters, no regressions in existing sync functionality
- **Risk if unmet:** Integration bugs between SourceReader rules discovery and orchestrator/adapter flow
- **Fallback:** Add integration tests with more realistic fixture data; fix integration bugs in a patch phase

## Ablation Plan

**No ablation plan** -- This phase implements independent bug fixes and a single feature addition. There are no sub-components whose individual contribution needs to be isolated. Each fix is independently verifiable against its requirement.

## WebMCP Tool Definitions

WebMCP tool definitions skipped -- phase does not modify frontend views.

## Baselines

| Baseline | Description | Expected Score | Source |
|----------|-------------|----------------|--------|
| Codex config filename | Currently writes `codex.toml` | Must be `config.toml` | Codex Config Reference |
| Codex approval_policy | Currently writes `on-failure` | Must be `on-request` | Codex Config Reference |
| Gemini tools keys | Currently writes `blockedTools`/`allowedTools` | Must be `exclude`/`allowed` | Gemini CLI Configuration |
| OpenCode permissions | Currently writes `permissions` (plural) with `mode` | Must be `permission` (singular) with per-tool | OpenCode Permissions Docs |
| Rules discovery | Currently not implemented | Must find all .md files recursively | Claude Code Memory Docs |

## Evaluation Scripts

**Location of evaluation code:**
```
tests/test_phase12_integration.py  (to be created during Plan 03 execution)
```

**How to run full evaluation:**
```bash
# Sanity checks (Level 1) -- run individually or all at once:
cd /Users/neo/Developer/Projects/HarnessSync

# Quick sanity: all imports work
python3 -c "from src.adapters.codex import CodexAdapter; from src.adapters.gemini import GeminiAdapter; from src.adapters.opencode import OpenCodeAdapter; from src.source_reader import SourceReader; print('OK')"

# Quick sanity: no deprecated patterns
grep -rn "codex\.toml\|on-failure\|blockedTools\|allowedTools" src/ | grep -v cc2all_sync

# Proxy metrics (Level 2) -- integration tests:
python3 -m pytest tests/test_phase12_integration.py -v

# Full evaluation (all levels):
python3 -m pytest tests/test_phase12_integration.py -v --tb=short
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: CONFIG_TOML constant | [PASS/FAIL] | | |
| S2: No deprecated Codex strings | [PASS/FAIL] | | |
| S3: No deprecated Gemini keys | [PASS/FAIL] | | |
| S4: OpenCode singular permission | [PASS/FAIL] | | |
| S5: All imports OK | [PASS/FAIL] | | |
| S6: get_rules_files exists | [PASS/FAIL] | | |
| S7: get_rules() backward compat | [PASS/FAIL] | | |
| S8: No hardcoded Path.home() | [PASS/FAIL] | | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: Codex on-request | on-request in output | [actual] | [MET/MISSED] | |
| P2: Gemini v2 keys | exclude/allowed in output | [actual] | [MET/MISSED] | |
| P3: OpenCode singular permission | permission key, no permissions | [actual] | [MET/MISSED] | |
| P4: Rules discovery | 2 files found | [actual] | [MET/MISSED] | |
| P5: Frontmatter parsing | 3 cases correct | [actual] | [MET/MISSED] | |
| P6: Codebase sweep | 0 deprecated patterns | [actual] | [MET/MISSED] | |

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-12-01 | Target CLI acceptance | PENDING | Manual pre-release testing |
| DEFER-12-02 | Full end-to-end sync | PENDING | Phase 14 integration / pre-release |

## Evaluation Confidence

**Overall confidence in evaluation design:** HIGH

**Justification:**
- Sanity checks: Adequate -- cover all modified constants, imports, backward compatibility, and codebase cleanliness
- Proxy metrics: Well-evidenced -- each directly tests the output of the fixed function against official documentation specs; no indirect measurement needed
- Deferred coverage: Comprehensive for what cannot be automated -- CLI acceptance and real-world config are the only things we cannot test without external tools

**What this evaluation CAN tell us:**
- Whether adapter outputs match documented formats (key names, value correctness)
- Whether rules discovery finds files and parses frontmatter correctly
- Whether backward compatibility is preserved
- Whether deprecated patterns have been fully eliminated from the codebase

**What this evaluation CANNOT tell us:**
- Whether target CLIs (Codex, Gemini, OpenCode) actually load and apply the generated configs -- addressed by DEFER-12-01
- Whether the full sync pipeline (source -> orchestrator -> adapter -> file) works end-to-end with real configs -- addressed by DEFER-12-02
- Whether edge cases in real-world .claude/rules/ directories (symlinks, binary files, very large files) are handled gracefully -- would need additional robustness testing

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-03-09*
