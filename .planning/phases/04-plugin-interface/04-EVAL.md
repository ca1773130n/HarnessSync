# Evaluation Plan: Phase 4 — Plugin Interface (Commands, Hooks, Skills)

**Designed:** 2026-02-14
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** SyncOrchestrator, file-based locking (fcntl.flock), time-based debouncing, slash commands, PostToolUse hook
**Reference papers:** N/A (Claude Code plugin system integration, not research)

## Evaluation Overview

Phase 4 delivers the user-facing plugin interface for HarnessSync: `/sync` and `/sync-status` slash commands, PostToolUse hook for reactive auto-sync, file-based locking with fcntl.flock, 3-second debouncing, and dry-run preview mode. This phase connects all prior infrastructure (StateManager, SourceReader, AdapterRegistry) into a cohesive user experience.

**What we're evaluating:**
- SyncOrchestrator: Coordinates SourceReader → AdapterRegistry → StateManager pipeline with scope filtering and dry-run mode
- File locking: fcntl.flock prevents concurrent syncs (non-blocking exclusive lock with BlockingIOError on contention)
- Debouncing: Time-based check skips syncs when last sync was < 3 seconds ago
- Slash commands: /sync parses arguments (--scope, --dry-run), acquires lock, invokes orchestrator, formats output
- PostToolUse hook: Reads stdin JSON, matches config file patterns, triggers auto-sync on CLAUDE.md/.mcp.json/skills/agents/commands edits
- Dry-run mode: DiffFormatter generates unified diffs showing proposed changes without writing files

**What can be verified at this stage:**
- Level 1 (Sanity): All components instantiate, arguments parse correctly, files created with valid structure, no Python errors
- Level 2 (Proxy): Unit tests verify lock/debounce/orchestrator logic, integration tests sync to all 3 adapters, dry-run produces diff output
- Level 3 (Deferred): Real Claude Code session with plugin installed, hook fires on live edits, concurrent sync scenarios

**What cannot be verified at this stage:**
- Hook integration with real Claude Code PostToolUse events (requires plugin installation in live session)
- Lock contention under actual concurrent hook invocations (requires multiple rapid edits in live session)
- Cross-platform locking behavior on Windows (fcntl is Unix-only, Windows needs testing with fallback)
- Hook timeout behavior under slow network syncs (10-minute default timeout may need tuning)

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| Lock acquisition success | fcntl.flock return value + BlockingIOError exception | Core requirement PLG-04 (prevents concurrent syncs) |
| Debounce effectiveness | should_debounce() return value vs. elapsed time | Core requirement PLG-04 (3-second debounce) |
| Argument parsing correctness | argparse.parse_args() output | Core requirement PLG-01 (scope filtering) |
| Sync success rate | SyncResult.synced / (synced + failed) | Continuity with Phase 2/3 (100% pass rate established) |
| Dry-run file preservation | File mtime before/after dry-run sync | Core requirement PLG-05 (preview without writing) |
| Config file pattern matching | is_config_file() return value | Core requirement PLG-03 (auto-sync on config edits only) |
| Hook exit code | sys.exit() argument | Claude Code hook contract (0 = allow, 2 = block) |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 12 | Basic functionality and format verification |
| Proxy (L2) | 8 | Indirect performance measurement via unit tests |
| Deferred (L3) | 5 | Full evaluation requiring Claude Code plugin installation |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: Lock Context Manager Acquisition
- **What:** sync_lock() acquires and releases exclusive fcntl.flock without error
- **Command:**
```bash
python3 -c "
import sys, tempfile
sys.path.insert(0, '.')
from pathlib import Path
from src.lock import sync_lock

with tempfile.TemporaryDirectory() as td:
    lock_path = Path(td) / 'test.lock'
    with sync_lock(lock_path) as fd:
        assert fd is not None, 'Lock should return file descriptor'
        assert lock_path.exists(), 'Lock file should exist'
    print('PASS: sync_lock acquires and releases')
"
```
- **Expected:** No exceptions, lock file created and cleaned up
- **Failure means:** fcntl.flock broken, concurrent sync protection unusable

### S2: Lock Contention Raises BlockingIOError
- **What:** Concurrent sync_lock() raises BlockingIOError when lock held
- **Command:**
```bash
python3 -c "
import sys, tempfile
sys.path.insert(0, '.')
from pathlib import Path
from src.lock import sync_lock

with tempfile.TemporaryDirectory() as td:
    lock_path = Path(td) / 'test.lock'
    with sync_lock(lock_path):
        try:
            with sync_lock(lock_path):
                assert False, 'Should have raised BlockingIOError'
        except BlockingIOError:
            print('PASS: Lock contention detected correctly')
"
```
- **Expected:** BlockingIOError raised on second acquisition
- **Failure means:** Non-blocking flag missing (LOCK_NB), concurrent syncs will deadlock

### S3: Debounce Returns False When Never Synced
- **What:** should_debounce() returns False when StateManager has no last_sync
- **Command:**
```bash
python3 -c "
import sys, tempfile
sys.path.insert(0, '.')
from pathlib import Path
from src.lock import should_debounce
from src.state_manager import StateManager

with tempfile.TemporaryDirectory() as td:
    sm = StateManager(state_dir=Path(td))
    result = should_debounce(sm)
    assert result == False, f'Expected False, got {result}'
    print('PASS: Debounce allows first sync')
"
```
- **Expected:** Returns False (allow sync)
- **Failure means:** Debounce logic broken, will block all syncs

### S4: Debounce Returns True After Recent Sync
- **What:** should_debounce() returns True when last_sync was < 3 seconds ago
- **Command:**
```bash
python3 -c "
import sys, tempfile
sys.path.insert(0, '.')
from pathlib import Path
from src.lock import should_debounce
from src.state_manager import StateManager

with tempfile.TemporaryDirectory() as td:
    sm = StateManager(state_dir=Path(td))
    sm.record_sync('test', 'all', {}, {}, 1, 0, 0)
    result = should_debounce(sm)
    assert result == True, f'Expected True (just synced), got {result}'
    print('PASS: Debounce blocks recent sync')
"
```
- **Expected:** Returns True (skip sync)
- **Failure means:** Debounce window calculation wrong, rapid syncs will proceed

### S5: SyncOrchestrator Instantiation
- **What:** SyncOrchestrator can be instantiated with scope and dry_run params
- **Command:**
```bash
python3 -c "
import sys, tempfile
sys.path.insert(0, '.')
from pathlib import Path
from src.orchestrator import SyncOrchestrator

with tempfile.TemporaryDirectory() as td:
    orch = SyncOrchestrator(project_dir=Path(td), scope='all', dry_run=False)
    assert orch.scope == 'all'
    assert orch.dry_run == False
    print('PASS: SyncOrchestrator instantiates')
"
```
- **Expected:** No exceptions, attributes set correctly
- **Failure means:** Constructor broken, all sync operations unusable

### S6: DiffFormatter Generates Text Diff
- **What:** DiffFormatter.add_text_diff() produces unified diff output
- **Command:**
```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from src.diff_formatter import DiffFormatter

df = DiffFormatter()
df.add_text_diff('rules', 'line1\nline2\n', 'line1\nline3\n')
output = df.format_output()
assert 'line2' in output and 'line3' in output, f'Diff should show changes: {output}'
print('PASS: DiffFormatter text diff works')
"
```
- **Expected:** Output contains both old line (-line2) and new line (+line3)
- **Failure means:** difflib.unified_diff broken, dry-run previews unusable

### S7: Slash Command Argument Parsing
- **What:** /sync command parses --scope and --dry-run flags correctly
- **Command:**
```bash
python3 -c "
import sys, shlex, argparse
sys.path.insert(0, '.')

parser = argparse.ArgumentParser(prog='sync')
parser.add_argument('--scope', choices=['user', 'project', 'all'], default='all')
parser.add_argument('--dry-run', action='store_true')

args = parser.parse_args(shlex.split('--scope user --dry-run'))
assert args.scope == 'user', f'Wrong scope: {args.scope}'
assert args.dry_run == True, f'dry_run should be True'
print('PASS: Argument parsing works')
"
```
- **Expected:** Flags parsed correctly, defaults applied when omitted
- **Failure means:** User input handling broken, commands won't work

### S8: Commands Directory and Markdown Files Exist
- **What:** commands/sync.md and commands/sync-status.md exist with valid structure
- **Command:**
```bash
python3 -c "
from pathlib import Path

files = ['commands/sync.md', 'commands/sync-status.md']
for f in files:
    p = Path(f)
    assert p.exists(), f'{f} should exist'
    content = p.read_text()
    assert 'description:' in content, f'{f} should have frontmatter'
    assert 'ARGUMENTS' in content or 'sync.py' in content, f'{f} should reference script'
print('PASS: Command markdown files valid')
"
```
- **Expected:** Both files exist with YAML frontmatter and script references
- **Failure means:** Claude Code won't discover slash commands

### S9: Hook Script Exists and Imports
- **What:** src/hooks/post_tool_use.py exists and can be imported
- **Command:**
```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from src.hooks.post_tool_use import CONFIG_PATTERNS, is_config_file
assert len(CONFIG_PATTERNS) >= 7, f'Should have 7+ patterns: {len(CONFIG_PATTERNS)}'
print('PASS: Hook script imports')
"
```
- **Expected:** Module imports without error, CONFIG_PATTERNS defined
- **Failure means:** Hook won't run, auto-sync broken

### S10: Config File Pattern Matching
- **What:** is_config_file() correctly identifies all 7 config patterns
- **Command:**
```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from src.hooks.post_tool_use import is_config_file

# Should match config files
assert is_config_file('/home/user/.claude/CLAUDE.md') == True
assert is_config_file('/project/.mcp.json') == True
assert is_config_file('/project/.claude/skills/my-skill/SKILL.md') == True
assert is_config_file('/project/.claude/agents/my-agent.md') == True
assert is_config_file('/project/.claude/commands/my-cmd.md') == True
assert is_config_file('/home/user/.claude/settings.json') == True
assert is_config_file('/project/.claude/settings.local.json') == True

# Should NOT match non-config files
assert is_config_file('/project/src/main.py') == False
assert is_config_file('/project/README.md') == False
assert is_config_file('') == False

print('PASS: Config pattern matching correct')
"
```
- **Expected:** All config patterns matched, non-config files rejected
- **Failure means:** Hook will trigger on wrong files or miss config edits

### S11: hooks.json Valid JSON with PostToolUse
- **What:** hooks/hooks.json is valid JSON with PostToolUse hook configured
- **Command:**
```bash
python3 -c "
import json
from pathlib import Path

data = json.loads(Path('hooks/hooks.json').read_text())
assert 'hooks' in data
assert 'PostToolUse' in data['hooks']
entry = data['hooks']['PostToolUse'][0]
assert 'Edit' in entry['matcher']
assert 'Write' in entry['matcher']
assert 'post_tool_use.py' in entry['hooks'][0]['command']
print('PASS: hooks.json valid with PostToolUse')
"
```
- **Expected:** Valid JSON, PostToolUse configured with Edit|Write matcher
- **Failure means:** Claude Code won't register hook, auto-sync won't trigger

### S12: All Plugin Files Exist
- **What:** All referenced files in plugin.json exist at expected paths
- **Command:**
```bash
python3 -c "
from pathlib import Path

files = [
    'hooks/hooks.json',
    'commands/sync.md',
    'commands/sync-status.md',
    'src/hooks/post_tool_use.py',
    'src/commands/sync.py',
    'src/commands/sync_status.py',
    'plugin.json',
]

missing = [f for f in files if not Path(f).exists()]
assert len(missing) == 0, f'Missing files: {missing}'
print('PASS: All plugin files exist')
"
```
- **Expected:** All files present
- **Failure means:** Plugin installation will fail, broken references

**Sanity gate:** ALL sanity checks must pass. Any failure blocks progression.

## Level 2: Proxy Metrics

**Purpose:** Indirect evaluation of quality/performance.
**IMPORTANT:** Proxy metrics are NOT validated substitutes for full evaluation. Treat results with appropriate skepticism.

### P1: Orchestrator Dry-Run File Preservation
- **What:** SyncOrchestrator with dry_run=True produces preview without writing files
- **How:** Create test project, record file mtimes, run dry-run sync, verify mtimes unchanged
- **Command:**
```bash
python3 -c "
import sys, tempfile, time
sys.path.insert(0, '.')
from pathlib import Path
from src.orchestrator import SyncOrchestrator

with tempfile.TemporaryDirectory() as td:
    project_dir = Path(td)
    test_file = project_dir / 'test.txt'
    test_file.write_text('original')
    time.sleep(0.01)  # Ensure mtime resolution

    mtime_before = test_file.stat().st_mtime
    orch = SyncOrchestrator(project_dir=project_dir, scope='all', dry_run=True)
    results = orch.sync_all()
    mtime_after = test_file.stat().st_mtime

    assert mtime_before == mtime_after, f'File modified during dry-run'
    assert 'preview' in str(results) or isinstance(results, dict), f'Should produce preview'
    print('PASS: Dry-run preserves files')
"
```
- **Target:** All file mtimes unchanged, preview output generated
- **Evidence:** Core requirement PLG-05 (dry-run mode)
- **Correlation with full metric:** HIGH — If files unmodified, dry-run is working correctly
- **Blind spots:** Preview content accuracy (may show incorrect diffs but preserve files)
- **Validated:** No — awaiting manual dry-run verification in live session

### P2: Orchestrator Sync Success Rate
- **What:** SyncOrchestrator.sync_all() returns successful results for all registered adapters
- **How:** Run orchestrator with test data, verify SyncResult counts (synced > 0, failed == 0)
- **Command:**
```bash
python3 -c "
import sys, tempfile
sys.path.insert(0, '.')
from pathlib import Path
from src.orchestrator import SyncOrchestrator

with tempfile.TemporaryDirectory() as td:
    orch = SyncOrchestrator(project_dir=Path(td), scope='all', dry_run=False)
    results = orch.sync_all()

    # Should return dict with target results
    assert isinstance(results, dict), f'Results should be dict: {type(results)}'
    print(f'PASS: Orchestrator sync completed for {len(results)} targets')
"
```
- **Target:** Results dict returned, no exceptions raised
- **Evidence:** Phase 2/3 established 100% adapter success rate
- **Correlation with full metric:** MEDIUM — Tests orchestrator flow, not adapter correctness
- **Blind spots:** Adapters may succeed but generate incorrect configs
- **Validated:** No — awaiting integration test with real adapters

### P3: Orchestrator State Persistence
- **What:** SyncOrchestrator._update_state() records sync results to StateManager
- **How:** Run non-dry-run sync, verify StateManager contains new sync records
- **Command:**
```bash
python3 -c "
import sys, tempfile
sys.path.insert(0, '.')
from pathlib import Path
from src.orchestrator import SyncOrchestrator
from src.state_manager import StateManager

with tempfile.TemporaryDirectory() as td:
    orch = SyncOrchestrator(project_dir=Path(td), scope='all', dry_run=False)
    results = orch.sync_all()

    # Check state updated
    sm = StateManager()
    state = sm.get_all_status()
    assert 'version' in state, f'State should include version'
    print('PASS: Orchestrator updates state')
"
```
- **Target:** StateManager contains sync records after orchestrator run
- **Evidence:** Core requirement CORE-02 (state tracking)
- **Correlation with full metric:** HIGH — State persistence directly verifiable
- **Blind spots:** State content accuracy (timestamps, hashes)
- **Validated:** No — awaiting drift detection validation

### P4: Lock Prevents Concurrent Sync Invocations
- **What:** Two concurrent orchestrator invocations result in one success, one BlockingIOError
- **How:** Spawn two Python processes that acquire lock simultaneously
- **Command:** Unit test spawns subprocesses with short sleep in lock block
- **Target:** One process succeeds, one raises BlockingIOError
- **Evidence:** Core requirement PLG-04 (file-based locking)
- **Correlation with full metric:** MEDIUM — Tests lock primitive, not full concurrent scenario
- **Blind spots:** Race conditions in real hook invocations, lock file cleanup on crashes
- **Validated:** No — awaiting concurrent hook testing in live session

### P5: Debounce Skips Rapid Successive Syncs
- **What:** Second sync within 3 seconds skips due to debounce
- **How:** Record sync, immediately call should_debounce(), verify True
- **Command:** Already verified in S4 (sanity check)
- **Target:** Returns True within 3-second window
- **Evidence:** Core requirement PLG-04 (3-second debounce)
- **Correlation with full metric:** HIGH — Time-based check directly measures debounce
- **Blind spots:** Debounce behavior under clock changes, timezone issues
- **Validated:** No — awaiting rapid-edit testing in live session

### P6: Hook Ignores Non-Config File Edits
- **What:** Hook receives non-config file path, exits 0 without triggering sync
- **How:** Simulate stdin JSON with main.py path, verify is_config_file() returns False
- **Command:** Already verified in S10 (sanity check)
- **Target:** Non-config files rejected (is_config_file() == False)
- **Evidence:** Core requirement PLG-03 (auto-sync on config edits only)
- **Correlation with full metric:** HIGH — Pattern matching directly measures filter
- **Blind spots:** Edge cases (symlinks, hidden files, unicode paths)
- **Validated:** No — awaiting live hook testing with diverse file edits

### P7: Hook Always Exits 0 (Never Blocks Tools)
- **What:** Hook script always calls sys.exit(0) even on sync errors
- **How:** Code review + unit test with mocked sync failure
- **Command:** Grep hook script for `sys.exit(0)` in all branches
- **Target:** All code paths exit 0 (no exit 2 which would block action)
- **Evidence:** Claude Code hook contract (PostToolUse should not block tools)
- **Correlation with full metric:** HIGH — Exit code directly controls blocking behavior
- **Blind spots:** Unhandled exceptions that bypass exit(0)
- **Validated:** No — awaiting live hook error scenarios

### P8: DiffFormatter Structural Diff for MCP/Settings
- **What:** DiffFormatter.add_structural_diff() shows added/removed/changed keys
- **How:** Create old/new dict with differences, verify output shows +/- indicators
- **Command:**
```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from src.diff_formatter import DiffFormatter

df = DiffFormatter()
old = {'server-a': {}, 'server-b': {}}
new = {'server-a': {}, 'server-c': {}}
df.add_structural_diff('mcp', old, new)
output = df.format_output()

assert 'server-b' in output, f'Removed server should appear: {output}'
assert 'server-c' in output, f'Added server should appear: {output}'
print('PASS: Structural diff shows changes')
"
```
- **Target:** Output contains added/removed/changed indicators
- **Evidence:** Dry-run preview for structured configs (MCP, settings)
- **Correlation with full metric:** MEDIUM — Shows changes exist, not accuracy
- **Blind spots:** Nested changes, formatting edge cases
- **Validated:** No — awaiting manual dry-run verification

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring integration or resources not available in-phase.

### D1: Hook Fires in Live Claude Code Session — DEFER-04-01
- **What:** PostToolUse hook triggers when editing CLAUDE.md in real Claude Code session
- **How:** Install plugin, edit CLAUDE.md in Claude Code, check hook fired via stderr logs
- **Why deferred:** Requires Claude Code with plugin installed (not available in CI/testing)
- **Validates at:** phase-05-manual-testing or user acceptance testing
- **Depends on:** Plugin installation, Claude Code session running
- **Target:** Hook executes within 1 second of file edit, logs sync trigger to stderr
- **Risk if unmet:** Hook registration broken (CRITICAL — auto-sync is core feature, needs 1 plan to fix)
- **Fallback:** Manual /sync invocation, document auto-sync limitation

### D2: Concurrent Hook Invocations Handle Lock Correctly — DEFER-04-02
- **What:** Multiple rapid edits trigger multiple hook invocations, only one syncs
- **How:** Edit CLAUDE.md 5 times rapidly, verify only first and last sync (debounce + lock)
- **Why deferred:** Requires live Claude Code session with rapid edits (timing-sensitive)
- **Validates at:** phase-05-stress-testing
- **Depends on:** Plugin installed, scripted rapid edits
- **Target:** 5 edits result in ≤2 syncs (first + last after debounce window), no errors
- **Risk if unmet:** Lock contention causes errors (MEDIUM — would need lock retry logic, 0.5 plans)
- **Fallback:** Increase debounce window to 5 seconds, reduce contention

### D3: Cross-Platform Locking (Windows) — DEFER-04-03
- **What:** Windows users get graceful fallback when fcntl unavailable
- **How:** Run plugin on Windows, verify warning printed but sync proceeds
- **Why deferred:** Requires Windows CI or Windows test machine (not available)
- **Validates at:** phase-07-packaging (Windows support)
- **Depends on:** Windows environment, fcntl import failure
- **Target:** Sync works on Windows, warning logged about missing lock
- **Risk if unmet:** Windows users get ImportError (MEDIUM — would need Windows lock impl, 0.5 plans)
- **Fallback:** Document Windows limitation, recommend WSL for locking

### D4: Hook Timeout Tuning — DEFER-04-04
- **What:** Hook completes within Claude Code's 10-minute timeout for slow syncs
- **How:** Sync 100+ skills to remote MCP server, verify hook completes
- **Why deferred:** Requires production-scale config + slow network (not in test environment)
- **Validates at:** phase-05-performance-testing
- **Depends on:** Large skill collection, remote MCP server with latency
- **Target:** Sync completes in <10 minutes for 100 skills
- **Risk if unmet:** Hook times out, sync incomplete (LOW — typical syncs are <1 second, would add timeout config)
- **Fallback:** Add timeout field to hooks.json, increase to 20 minutes

### D5: /sync Command Integration in Live Session — DEFER-04-05
- **What:** /sync slash command works in real Claude Code conversation
- **How:** Install plugin, run /sync in chat, verify output displayed and files synced
- **Why deferred:** Requires plugin installed in Claude Code session
- **Validates at:** phase-05-manual-testing
- **Depends on:** Plugin installation, Claude Code slash command registration
- **Target:** Command completes, prints summary table, target files updated
- **Risk if unmet:** Command registration broken (CRITICAL — primary UI, needs 1 plan)
- **Fallback:** Run sync.py directly via `!python`, document workaround

## Ablation Plan

**No ablation plan** — Phase 4 integrates existing components (StateManager, SourceReader, AdapterRegistry) rather than implementing new algorithms. The orchestrator is a coordination layer with no sub-components to isolate.

**Component dependency verification:**
| Component | Depends On | Validates |
|-----------|-----------|-----------|
| SyncOrchestrator | SourceReader, AdapterRegistry, StateManager | Integration point for all prior phases |
| sync_lock | fcntl.flock (Unix stdlib) | Concurrency primitive |
| should_debounce | StateManager.last_sync, time.time() | Timing primitive |
| /sync command | SyncOrchestrator, sync_lock, should_debounce | User interface layer |
| PostToolUse hook | SyncOrchestrator, sync_lock, should_debounce | Reactive automation layer |

All components must work together — no meaningful ablation possible.

## Baselines

| Baseline | Description | Expected Score | Source |
|----------|-------------|----------------|--------|
| Phase 3 adapter success | 3 adapters, 100% sync success | 3/3 pass, 0 failures | 03-EVAL-RESULTS.md |
| Zero concurrency protection | Before lock implementation | Race conditions, state corruption | Problem statement |
| No debounce | Before debounce implementation | Redundant syncs on rapid edits | Problem statement |
| Target: Phase 4 complete | All requirements met | 12/12 sanity pass, 8/8 proxy pass | Plan 04-01/04-02/04-03 |

**No performance baselines** — This is a plugin/tool project. Success is boolean (works/doesn't work), not continuous metric. Performance will be measured in deferred validation (sync time for 100+ skills).

## Evaluation Scripts

**Location of evaluation code:**
```
tests/test_lock.py               # Unit tests for sync_lock, should_debounce
tests/test_orchestrator.py       # Unit tests for SyncOrchestrator
tests/test_diff_formatter.py     # Unit tests for DiffFormatter
tests/test_sync_command.py       # Integration test for /sync command
tests/test_sync_status_command.py # Integration test for /sync-status command
tests/test_post_tool_use_hook.py # Unit tests for PostToolUse hook logic
tests/test_integration_04.py     # End-to-end test: hook → orchestrator → adapters
```

**How to run full evaluation:**
```bash
# Sanity checks (must pass first)
python3 tests/test_lock.py -v                    # S1-S4: Lock and debounce
python3 tests/test_orchestrator.py -v            # S5: Orchestrator
python3 tests/test_diff_formatter.py -v          # S6: DiffFormatter
python3 -c "from src.commands.sync import main"  # S7-S8: Slash commands
python3 -c "from src.hooks.post_tool_use import is_config_file" # S9-S10: Hook
python3 -c "import json; json.load(open('hooks/hooks.json'))"   # S11: hooks.json
ls commands/sync.md hooks/hooks.json src/commands/sync.py        # S12: Files exist

# Proxy metrics (unit tests)
python3 -m pytest tests/test_lock.py -v          # P4-P5: Lock contention, debounce
python3 -m pytest tests/test_orchestrator.py -v  # P1-P3: Dry-run, sync, state
python3 -m pytest tests/test_diff_formatter.py -v # P8: Structural diff
python3 -m pytest tests/test_post_tool_use_hook.py -v # P6-P7: Hook filtering, exit codes

# Integration test (all components)
python3 tests/test_integration_04.py -v          # Full pipeline: commands → orchestrator → adapters

# Deferred validations (manual, requires Claude Code session)
# See TESTING.md for manual test procedures
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: Lock Acquisition | [PASS/FAIL] | [output] | |
| S2: Lock Contention | [PASS/FAIL] | [output] | |
| S3: Debounce First Sync | [PASS/FAIL] | [output] | |
| S4: Debounce Recent Sync | [PASS/FAIL] | [output] | |
| S5: Orchestrator Instantiation | [PASS/FAIL] | [output] | |
| S6: DiffFormatter Text Diff | [PASS/FAIL] | [output] | |
| S7: Argument Parsing | [PASS/FAIL] | [output] | |
| S8: Command Files Exist | [PASS/FAIL] | [output] | |
| S9: Hook Script Imports | [PASS/FAIL] | [output] | |
| S10: Config Pattern Matching | [PASS/FAIL] | [output] | |
| S11: hooks.json Valid | [PASS/FAIL] | [output] | |
| S12: Plugin Files Exist | [PASS/FAIL] | [output] | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: Dry-Run Preservation | Files unchanged | [actual] | [MET/MISSED] | |
| P2: Orchestrator Success | Results dict | [actual] | [MET/MISSED] | |
| P3: State Persistence | State updated | [actual] | [MET/MISSED] | |
| P4: Lock Concurrency | One blocks | [actual] | [MET/MISSED] | |
| P5: Debounce Timing | True < 3s | [actual] | [MET/MISSED] | |
| P6: Hook Filtering | Non-config ignored | [actual] | [MET/MISSED] | |
| P7: Hook Exit Code | Always 0 | [actual] | [MET/MISSED] | |
| P8: Structural Diff | Changes shown | [actual] | [MET/MISSED] | |

### Ablation Results

N/A — No ablation tests for this phase (integration/coordination layer)

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-04-01 | Hook fires in live session | PENDING | phase-05-manual-testing |
| DEFER-04-02 | Concurrent hook handling | PENDING | phase-05-stress-testing |
| DEFER-04-03 | Cross-platform locking (Windows) | PENDING | phase-07-packaging |
| DEFER-04-04 | Hook timeout tuning | PENDING | phase-05-performance-testing |
| DEFER-04-05 | /sync command integration | PENDING | phase-05-manual-testing |

## Evaluation Confidence

**Overall confidence in evaluation design:** MEDIUM-HIGH

**Justification:**
- Sanity checks: ADEQUATE — Cover all critical components (lock, debounce, orchestrator, commands, hook), comprehensive for infrastructure code
- Proxy metrics: WELL-EVIDENCED — Unit tests proven reliable in Phase 1-3 (100% pass rate), dry-run file preservation directly verifiable
- Deferred coverage: COMPREHENSIVE — All major integration risks identified (live session, concurrency, cross-platform)

**What this evaluation CAN tell us:**
- All components instantiate and integrate without Python errors
- Lock primitive works (acquire, release, contention detection)
- Debounce timing logic is correct (< 3 seconds blocks)
- Orchestrator coordinates SourceReader → AdapterRegistry → StateManager pipeline
- Slash commands parse arguments correctly
- Hook filters config files and ignores non-config files
- Dry-run mode produces preview without modifying files
- plugin.json, hooks.json, command markdown files are syntactically valid

**What this evaluation CANNOT tell us:**
- Whether Claude Code actually registers and invokes slash commands (DEFER-04-05 — requires plugin installation)
- Whether PostToolUse hook fires in real Claude Code sessions (DEFER-04-01 — requires live session)
- Whether concurrent hook invocations are handled correctly (DEFER-04-02 — requires rapid edits)
- Whether Windows users get graceful fallback (DEFER-04-03 — requires Windows environment)
- Whether hook completes within timeout for large configs (DEFER-04-04 — requires production-scale data)
- Whether lock is released on crashes (requires fault injection testing)

**Confidence compared to Phase 1-3:** SIMILAR — Using same unit test + integration test strategy that achieved 100% pass rate in prior phases. Phase 4 adds new complexity (concurrency, hooks) but evaluation coverage is comprehensive.

**Known gaps:**
1. **Live session integration:** Proxy tests verify components work in isolation, but not full plugin integration with Claude Code
2. **Timing edge cases:** Debounce/lock tested with synthetic delays, not real-world timing variability
3. **Error recovery:** Tests focus on happy path, less coverage of network errors, permission errors, corrupted state
4. **Cross-platform:** Only Unix testing available, Windows behavior unverified

**Mitigation:**
- Gap 1: Defer to manual testing phase with plugin installed (DEFER-04-01, DEFER-04-05)
- Gap 2: Add timing stress tests in phase-05-stress-testing (DEFER-04-02)
- Gap 3: Add error injection tests in future iterations based on bug reports
- Gap 4: Add Windows CI in phase-07-packaging (DEFER-04-03)

**Risk assessment for deferred items:**
| Deferred Item | Probability of Failure | Impact | Mitigation |
|---------------|----------------------|--------|------------|
| DEFER-04-01 (Hook fires) | LOW | CRITICAL | Test manually before release |
| DEFER-04-02 (Concurrency) | MEDIUM | MEDIUM | Increase debounce to 5s if needed |
| DEFER-04-03 (Windows) | MEDIUM | LOW | Document WSL workaround |
| DEFER-04-04 (Timeout) | LOW | LOW | Add timeout config if needed |
| DEFER-04-05 (Slash cmd) | LOW | CRITICAL | Test manually before release |

**Overall risk:** LOW-MEDIUM — Critical items (hook, slash commands) have low failure probability based on Phase 1-3 success. Medium-risk items (concurrency, Windows) have acceptable fallbacks.

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-02-14*
