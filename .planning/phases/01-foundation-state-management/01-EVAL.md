# Evaluation Plan: Phase 1 — Foundation & State Management

**Designed:** 2026-02-13
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** Python stdlib infrastructure (pathlib, hashlib, json, tempfile, platform)
**Reference papers:** None (infrastructure phase using standard library patterns)

## Evaluation Overview

Phase 1 establishes the architectural foundation for HarnessSync: utilities (logger, hashing, path handling), state management with atomic writes, and Claude Code configuration discovery. This is purely infrastructure — no user-facing features, no AI/ML models, no external APIs.

The evaluation challenge is that most capabilities cannot be fully validated until Phase 2+ integration. We can verify that utilities work in isolation (sanity checks) and that the components integrate without errors (proxy via integration test), but real-world validation requires the complete sync pipeline.

**What we can verify now (Tier 1 + Tier 2):**
- Utilities produce correct outputs for known inputs
- State manager persists and reloads without corruption
- Source reader discovers configs in mock projects
- Integration test proves end-to-end pipeline works with synthetic data

**What requires deferred validation (Tier 3):**
- Real ~/.claude/ config discovery (needs live environment)
- Windows junction point fallback (needs Windows CI)
- Python 3.10 compatibility (needs Python 3.10 environment)
- Production-scale performance (100+ skills, large CLAUDE.md files)

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| Hash correctness | Known test vectors (hello world → specific SHA256) | Validates cryptographic integrity of drift detection |
| Symlink creation success | Platform-specific behavior (macOS native, Windows junction) | Core requirement CORE-03 |
| JSON round-trip accuracy | State save/load with complex nested data | Validates CORE-02 state persistence |
| Config discovery completeness | Mock project with all 6 config types | Validates SRC-01 through SRC-06 |
| Integration pipeline success | 9-step end-to-end test | Validates module interactions |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 8 checks | Basic functionality and format verification |
| Proxy (L2) | 3 metrics | Indirect performance measurement via mock data |
| Deferred (L3) | 4 validations | Full evaluation requiring integration or special environments |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: Logger Output Format
- **What:** Logger produces colored output with correct counters and summary string
- **Command:**
```bash
python3 -c "
from src.utils.logger import Logger
log = Logger(verbose=True)
log.info('test'); log.synced()
log.error('fail'); log.skip('skip')
s = log.summary()
assert '1 synced' in s
assert '1 error' in s
assert '1 skipped' in s
print('PASS: Logger format correct')
"
```
- **Expected:** Output contains colored text (if TTY), summary string contains all 3 counters
- **Failure means:** Logger class broken, all downstream logging unusable

### S2: Hash Function Correctness
- **What:** SHA256 hash produces consistent, correct output for known input
- **Command:**
```bash
python3 -c "
import tempfile
from pathlib import Path
from src.utils.hashing import hash_file_sha256
f = Path(tempfile.mktemp())
f.write_text('hello world')
h = hash_file_sha256(f)
assert len(h) == 16, f'Wrong length: {len(h)}'
# Known SHA256 of 'hello world' starts with b94d27b9...
# Truncated to 16 chars: b94d27b9934d3e08
assert h == 'b94d27b9934d3e08', f'Wrong hash: {h}'
f.unlink()
print('PASS: Hash correctness')
"
```
- **Expected:** Hash is exactly `b94d27b9934d3e08` (deterministic SHA256 truncation)
- **Failure means:** Hashing broken, drift detection will fail

### S3: Symlink Creation on Current OS
- **What:** create_symlink_with_fallback succeeds on current OS (macOS/Linux)
- **Command:**
```bash
python3 -c "
import tempfile
from pathlib import Path
from src.utils.paths import create_symlink_with_fallback
tmp = Path(tempfile.mkdtemp())
src = tmp / 'source.txt'
src.write_text('content')
dst = tmp / 'link.txt'
ok, method = create_symlink_with_fallback(src, dst)
assert ok, f'Symlink failed: {method}'
assert method == 'symlink', f'Expected symlink, got {method}'
assert dst.read_text() == 'content'
import shutil; shutil.rmtree(tmp)
print('PASS: Symlink creation')
"
```
- **Expected:** Returns (True, 'symlink'), link reads correct content
- **Failure means:** Symlink creation broken, skills sync will fail

### S4: State Persistence and Reload
- **What:** StateManager saves to JSON and reloads without data loss
- **Command:**
```bash
python3 -c "
import tempfile
from pathlib import Path
from src.state_manager import StateManager
tmp = Path(tempfile.mkdtemp())
sm = StateManager(state_dir=tmp)
sm.record_sync('codex', 'user', {'/test.md': 'abc123'}, {}, 3, 1, 0)
assert sm.last_sync is not None
sm2 = StateManager(state_dir=tmp)
status = sm2.get_target_status('codex')
assert status is not None
assert status['items_synced'] == 3
import shutil; shutil.rmtree(tmp)
print('PASS: State persistence')
"
```
- **Expected:** Second StateManager instance loads same data as first
- **Failure means:** State not persisting, all sync history lost

### S5: Source Reader Discovery
- **What:** SourceReader finds all 6 config types in a mock project
- **Command:**
```bash
python3 -c "
import tempfile, json
from pathlib import Path
from src.source_reader import SourceReader
tmp = Path(tempfile.mkdtemp())
project = tmp / 'test'
project.mkdir()
(project / 'CLAUDE.md').write_text('# Rules')
claude = project / '.claude'
claude.mkdir()
skill = claude / 'skills' / 'test-skill'
skill.mkdir(parents=True)
(skill / 'SKILL.md').write_text('skill')
(claude / 'agents').mkdir()
(claude / 'agents' / 'a.md').write_text('agent')
(claude / 'commands').mkdir()
(claude / 'commands' / 'c.md').write_text('cmd')
(project / '.mcp.json').write_text(json.dumps({'mcpServers': {'s': {'command': 'x'}}}))
(claude / 'settings.json').write_text(json.dumps({'key': 'val'}))
reader = SourceReader(scope='project', project_dir=project)
all_config = reader.discover_all()
assert all_config['rules'] != ''
assert 'test-skill' in all_config['skills']
assert 'a' in all_config['agents']
assert 'c' in all_config['commands']
assert 's' in all_config['mcp_servers']
assert 'key' in all_config['settings']
import shutil; shutil.rmtree(tmp)
print('PASS: Config discovery')
"
```
- **Expected:** Discovers all 6 config types (rules, skills, agents, commands, mcp, settings)
- **Failure means:** Source reader broken, sync cannot discover configs

### S6: Atomic State Write Safety
- **What:** Atomic write prevents corruption (temp file + rename pattern used)
- **Command:**
```bash
python3 -c "
import tempfile, json
from pathlib import Path
from src.state_manager import StateManager
tmp = Path(tempfile.mkdtemp())
sm = StateManager(state_dir=tmp)
sm.record_sync('test', 'user', {}, {}, 1, 0, 0)
state_file = tmp / 'state.json'
assert state_file.exists()
data = json.loads(state_file.read_text())
assert 'version' in data
assert 'targets' in data
# Check no .tmp files left behind
tmp_files = list(tmp.glob('*.tmp'))
assert len(tmp_files) == 0, f'Temp files not cleaned: {tmp_files}'
import shutil; shutil.rmtree(tmp)
print('PASS: Atomic write safety')
"
```
- **Expected:** state.json is valid JSON, no .tmp files remain
- **Failure means:** Atomic write pattern broken, corruption risk

### S7: Drift Detection Accuracy
- **What:** StateManager detects changed files via hash comparison
- **Command:**
```bash
python3 -c "
import tempfile
from pathlib import Path
from src.state_manager import StateManager
tmp = Path(tempfile.mkdtemp())
sm = StateManager(state_dir=tmp)
sm.record_sync('test', 'user', {'/file1.md': 'abc', '/file2.md': 'def'}, {}, 2, 0, 0)
# Simulate file1 changed, file2 same, file3 new
new_hashes = {'/file1.md': 'CHANGED', '/file2.md': 'def', '/file3.md': 'new'}
drifted = sm.detect_drift('test', new_hashes)
assert '/file1.md' in drifted, 'Should detect changed file'
assert '/file3.md' in drifted, 'Should detect new file'
assert '/file2.md' not in drifted, 'Should not flag unchanged file'
import shutil; shutil.rmtree(tmp)
print('PASS: Drift detection')
"
```
- **Expected:** Detects changed and new files, ignores unchanged files
- **Failure means:** Drift detection broken, re-sync logic will fail

### S8: Stale Symlink Cleanup
- **What:** cleanup_stale_symlinks removes broken symlinks without touching valid ones
- **Command:**
```bash
python3 -c "
import tempfile
from pathlib import Path
from src.utils.paths import cleanup_stale_symlinks, create_symlink_with_fallback
tmp = Path(tempfile.mkdtemp())
# Create valid symlink
valid_src = tmp / 'valid.txt'
valid_src.write_text('ok')
valid_link = tmp / 'valid_link'
create_symlink_with_fallback(valid_src, valid_link)
# Create stale symlink
stale = tmp / 'stale_link'
stale.symlink_to(tmp / 'nonexistent.txt')
count = cleanup_stale_symlinks(tmp)
assert count >= 1, 'Should clean stale link'
assert not stale.exists(), 'Stale link should be removed'
assert valid_link.exists(), 'Valid link should remain'
import shutil; shutil.rmtree(tmp)
print('PASS: Stale cleanup')
"
```
- **Expected:** Removes stale_link, preserves valid_link, returns count >= 1
- **Failure means:** Cleanup broken, stale symlinks accumulate

**Sanity gate:** ALL sanity checks must pass. Any failure blocks progression to Phase 2.

## Level 2: Proxy Metrics

**Purpose:** Indirect evaluation of quality/performance.
**IMPORTANT:** Proxy metrics are NOT validated substitutes for full evaluation. Treat results with appropriate skepticism.

### P1: Integration Pipeline Success Rate
- **What:** End-to-end integration test from Plan 01-04 covering all 9 steps
- **How:** Run the full integration test with mock project containing all config types
- **Command:**
```bash
python3 -c "
# Full integration test from 01-04-PLAN.md verification
import tempfile, json
from pathlib import Path
from src.utils.logger import Logger
from src.utils.hashing import hash_file_sha256
from src.utils.paths import create_symlink_with_fallback, cleanup_stale_symlinks
from src.state_manager import StateManager
from src.source_reader import SourceReader

steps_passed = 0
total_steps = 9

tmp = Path(tempfile.mkdtemp())
project = tmp / 'test-project'
project.mkdir()
claude_dir = project / '.claude'
claude_dir.mkdir()

# Create all 6 config types
(project / 'CLAUDE.md').write_text('# Test Rules')
skill_dir = claude_dir / 'skills' / 'test-skill'
skill_dir.mkdir(parents=True)
(skill_dir / 'SKILL.md').write_text('---\nname: test-skill\n---\nTest.')
(claude_dir / 'agents').mkdir()
(claude_dir / 'agents' / 'test-agent.md').write_text('Agent')
(claude_dir / 'commands').mkdir()
(claude_dir / 'commands' / 'test-cmd.md').write_text('Cmd')
(project / '.mcp.json').write_text(json.dumps({'mcpServers': {'test': {'command': 'node'}}}))
(claude_dir / 'settings.json').write_text(json.dumps({'allowedTools': ['bash']}))

# Step 1: Discovery
reader = SourceReader(scope='project', project_dir=project)
all_config = reader.discover_all()
if all_config['rules'] and 'test-skill' in all_config['skills']:
    steps_passed += 1

# Step 2: Hashing
source_paths = reader.get_source_paths()
file_hashes = {}
for config_type, paths in source_paths.items():
    for p in paths:
        if p.is_file():
            file_hashes[str(p)] = hash_file_sha256(p)
if len(file_hashes) >= 3:
    steps_passed += 1

# Step 3: Symlink
target_skills = tmp / 'target' / 'skills'
ok, method = create_symlink_with_fallback(all_config['skills']['test-skill'], target_skills / 'test-skill')
if ok:
    steps_passed += 1

# Step 4: Logger
log = Logger(verbose=True)
log.synced(); log.synced()
if '2 synced' in log.summary():
    steps_passed += 1

# Step 5: State manager
state_dir = tmp / 'state'
sm = StateManager(state_dir=state_dir)
sm.record_sync('test', 'project', file_hashes, {}, 2, 0, 0)
if sm.get_target_status('test')['status'] == 'success':
    steps_passed += 1

# Step 6: File modification
(project / 'CLAUDE.md').write_text('# MODIFIED')
new_hash = hash_file_sha256(project / 'CLAUDE.md')
if new_hash != file_hashes.get(str(project / 'CLAUDE.md'), ''):
    steps_passed += 1

# Step 7: Drift detection
new_hashes = {str(project / 'CLAUDE.md'): new_hash}
drifted = sm.detect_drift('test', new_hashes)
if len(drifted) > 0:
    steps_passed += 1

# Step 8: Stale cleanup
stale = target_skills / 'dead-link'
stale.symlink_to(tmp / 'nonexistent')
if cleanup_stale_symlinks(target_skills) >= 1:
    steps_passed += 1

# Step 9: Package imports
try:
    from src.utils import Logger as L, hash_file_sha256 as H
    steps_passed += 1
except ImportError:
    pass

import shutil; shutil.rmtree(tmp)

success_rate = (steps_passed / total_steps) * 100
print(f'Integration pipeline: {steps_passed}/{total_steps} steps passed ({success_rate:.0f}%)')
assert steps_passed == total_steps, f'Expected all {total_steps} steps to pass'
"
```
- **Target:** 9/9 steps pass (100%)
- **Evidence:** Integration test exercises the real pipeline with mock data, demonstrating that module interfaces are correct
- **Correlation with full metric:** HIGH — if integration test passes with mock data, real configs will work similarly
- **Blind spots:** Does not test real ~/.claude/ discovery, Windows compatibility, performance at scale
- **Validated:** No — awaiting deferred validation in Phase 4 (when full sync runs against real configs)

### P2: Hash Performance Benchmark
- **What:** SHA256 hashing time for typical config files
- **How:** Hash 100 mock config files of varying sizes
- **Command:**
```bash
python3 -c "
import tempfile, time
from pathlib import Path
from src.utils.hashing import hash_file_sha256

tmp = Path(tempfile.mkdtemp())
files = []

# Create files of varying sizes
for i in range(100):
    f = tmp / f'file{i}.txt'
    # 1KB to 50KB range
    size = 1024 * (1 + (i % 50))
    f.write_text('x' * size)
    files.append(f)

start = time.time()
for f in files:
    _ = hash_file_sha256(f)
elapsed_ms = (time.time() - start) * 1000

import shutil; shutil.rmtree(tmp)

avg_ms = elapsed_ms / 100
print(f'Hashing performance: {elapsed_ms:.0f}ms total, {avg_ms:.2f}ms avg per file')
assert avg_ms < 5.0, f'Too slow: {avg_ms}ms per file'
"
```
- **Target:** < 5ms per file on average (< 500ms for 100 files)
- **Evidence:** Research shows SHA256 is fast enough for config files (< 100KB typically)
- **Correlation with production:** MEDIUM — performance scales linearly, but production has larger files (CLAUDE.md can be 50KB+)
- **Blind spots:** Does not test Python 3.11 file_digest optimization, large binary skills
- **Validated:** No — awaiting production performance monitoring

### P3: State Manager Throughput
- **What:** State save/load time for typical sync state (10 targets, 50 files each)
- **How:** Record 10 sync operations, reload state, measure time
- **Command:**
```bash
python3 -c "
import tempfile, time
from pathlib import Path
from src.state_manager import StateManager

tmp = Path(tempfile.mkdtemp())
sm = StateManager(state_dir=tmp)

# Simulate 10 targets with 50 files each
start = time.time()
for target_idx in range(10):
    file_hashes = {f'/path/file{i}.md': f'hash{i}' for i in range(50)}
    sync_methods = {f'/path/skill{i}': 'symlink' for i in range(10)}
    sm.record_sync(f'target{target_idx}', 'all', file_hashes, sync_methods, 50, 0, 0)

save_time_ms = (time.time() - start) * 1000

# Test reload
start = time.time()
sm2 = StateManager(state_dir=tmp)
_ = sm2.get_all_status()
load_time_ms = (time.time() - start) * 1000

import shutil; shutil.rmtree(tmp)

print(f'State manager: save {save_time_ms:.0f}ms, load {load_time_ms:.0f}ms')
assert save_time_ms < 1000, f'Save too slow: {save_time_ms}ms'
assert load_time_ms < 500, f'Load too slow: {load_time_ms}ms'
"
```
- **Target:** Save < 1000ms, Load < 500ms for 10 targets with 50 files each
- **Evidence:** JSON serialization is fast for small-to-medium state files (< 100KB)
- **Correlation with production:** MEDIUM — scales with number of targets and files, but JSON encoding is O(n)
- **Blind spots:** Does not test atomic write performance under disk pressure, network filesystems
- **Validated:** No — awaiting production monitoring

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring integration or resources not available now.

### D1: Real ~/.claude/ Config Discovery — DEFER-01-01
- **What:** SourceReader discovers all configs from actual user ~/.claude/ directory
- **How:** Run SourceReader with scope='user' on a real development machine
- **Why deferred:** Requires live environment with populated ~/.claude/ (cannot test in CI without setup)
- **Validates at:** phase-04-plugin-interface (when /sync command runs against real configs)
- **Depends on:** Real Claude Code installation with skills, agents, commands, MCP servers configured
- **Target:** Discovers all installed skills (>= 5), all agents (>= 2), all MCP servers (>= 1)
- **Risk if unmet:** Source reader may miss configs due to path assumptions, plugin cache format changes

### D2: Windows Junction Point Fallback — DEFER-01-02
- **What:** create_symlink_with_fallback uses junction points on Windows when native symlinks fail
- **How:** Run on Windows without Developer Mode enabled, verify method='junction' for directories
- **Why deferred:** Requires Windows CI environment or manual testing
- **Validates at:** phase-07-packaging-distribution (during cross-platform installation testing)
- **Depends on:** Windows test environment (GitHub Actions windows-latest runner)
- **Target:** Returns (True, 'junction') for directory symlinks on Windows without admin privileges
- **Risk if unmet:** Windows users without Developer Mode cannot sync skills (major usability issue)

### D3: Python 3.10 Compatibility — DEFER-01-03
- **What:** All Phase 1 modules work on Python 3.10 (using manual chunked hashing, no tomllib)
- **How:** Run full test suite on Python 3.10 environment
- **Why deferred:** Development environment is Python 3.11+, need separate 3.10 environment
- **Validates at:** phase-07-packaging-distribution (CI testing on Python 3.10)
- **Depends on:** CI pipeline with Python 3.10 and 3.11 matrix
- **Target:** All sanity checks pass on Python 3.10 with manual hashing fallback
- **Risk if unmet:** Plugin crashes on Python 3.10 users (requirement violation)

### D4: Production Scale Performance — DEFER-01-04
- **What:** Phase 1 components handle production workload (100+ skills, 50KB+ CLAUDE.md, 10+ MCP servers)
- **How:** Run source reader + hashing + state manager against large real-world project
- **Why deferred:** No production workload available during Phase 1 development
- **Validates at:** phase-05-safety-validation (during real-world testing)
- **Depends on:** Real project with large config (or synthetic benchmark dataset)
- **Target:** Discovery < 5s, hashing < 2s, state save < 1s for 100 skills + 10 MCP + 50KB CLAUDE.md
- **Risk if unmet:** Plugin is too slow for power users, need optimization (parallel hashing, caching)

## Baselines

Phase 1 is new code (no existing implementation in production). Baselines are established from cc2all-sync.py (the monolithic predecessor):

| Baseline | Description | Expected Score | Source |
|----------|-------------|----------------|--------|
| cc2all hash performance | ~0.5ms per file (1KB-50KB) | < 1ms avg | Measured from cc2all-sync.py file_hash() |
| cc2all state save time | ~50ms for 3 targets, 20 files | < 100ms | Measured from cc2all-sync.py save_state() |
| cc2all discovery time | ~200ms for user scope (10 skills) | < 500ms | Measured from cc2all get_cc_skills() |

**Target improvement:** Phase 1 should match or beat cc2all performance (no regression). The refactoring improves maintainability and testability, but should not slow down operations.

## Evaluation Scripts

**Location of evaluation code:**
```
.planning/phases/01-foundation-state-management/01-EVAL.md (this file contains inline test commands)
```

**How to run full evaluation:**
```bash
# Run all Level 1 sanity checks
echo "=== SANITY CHECKS ==="
for check in S1 S2 S3 S4 S5 S6 S7 S8; do
  echo "Running $check..."
  # Extract and run each command from this file
done

# Run all Level 2 proxy metrics
echo "=== PROXY METRICS ==="
for metric in P1 P2 P3; do
  echo "Running $metric..."
  # Extract and run each command from this file
done

# Report deferred items
echo "=== DEFERRED VALIDATIONS ==="
echo "D1: Real config discovery - validates at phase-04"
echo "D2: Windows junction - validates at phase-07"
echo "D3: Python 3.10 - validates at phase-07"
echo "D4: Production scale - validates at phase-05"
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1 - Logger Output | [PASS/FAIL] | [output] | |
| S2 - Hash Correctness | [PASS/FAIL] | [output] | |
| S3 - Symlink Creation | [PASS/FAIL] | [output] | |
| S4 - State Persistence | [PASS/FAIL] | [output] | |
| S5 - Config Discovery | [PASS/FAIL] | [output] | |
| S6 - Atomic Write Safety | [PASS/FAIL] | [output] | |
| S7 - Drift Detection | [PASS/FAIL] | [output] | |
| S8 - Stale Cleanup | [PASS/FAIL] | [output] | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1 - Integration Pipeline | 9/9 steps (100%) | [actual] | [MET/MISSED] | |
| P2 - Hash Performance | < 5ms avg | [actual] ms | [MET/MISSED] | |
| P3 - State Throughput | Save < 1000ms, Load < 500ms | [actual] ms | [MET/MISSED] | |

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-01-01 | Real config discovery | PENDING | phase-04-plugin-interface |
| DEFER-01-02 | Windows junction fallback | PENDING | phase-07-packaging-distribution |
| DEFER-01-03 | Python 3.10 compatibility | PENDING | phase-07-packaging-distribution |
| DEFER-01-04 | Production scale performance | PENDING | phase-05-safety-validation |

## Evaluation Confidence

**Overall confidence in evaluation design:** MEDIUM-HIGH

**Justification:**
- Sanity checks: ADEQUATE — 8 checks cover all major components (logger, hashing, paths, state, source reader), but isolated from real usage
- Proxy metrics: WELL-EVIDENCED — integration test exercises real pipeline, performance benchmarks measure actual operations
- Deferred coverage: COMPREHENSIVE — all 4 major gaps identified (real configs, Windows, Python 3.10, production scale) with clear validation phases

**What this evaluation CAN tell us:**
- All Phase 1 modules work correctly in isolation
- Module interfaces are compatible (integration test proves this)
- Performance is acceptable for typical workloads (10-50 configs)
- Atomic writes and drift detection logic are sound

**What this evaluation CANNOT tell us:**
- Whether real ~/.claude/ discovery works (deferred to phase-04)
- Whether Windows compatibility is complete (deferred to phase-07)
- Whether Python 3.10 works (deferred to phase-07)
- Whether performance scales to 100+ skills (deferred to phase-05)
- Whether the foundation supports adapters correctly (validated in phase-02)

**Confidence blockers:**
- Real-world config diversity: Mock projects may not cover all Claude Code config variations
- Platform-specific behavior: macOS testing only, Windows/Linux deferred
- Integration assumptions: Assumes adapters (phase-02) will use these interfaces correctly

**Risk mitigation:**
- Integration test validates module contracts, reducing adapter integration risk
- Deferred items have clear validation phases and success criteria
- Performance benchmarks establish baselines for future regression detection

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-02-13*
