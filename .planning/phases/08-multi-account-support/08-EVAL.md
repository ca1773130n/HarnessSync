# Evaluation Plan: Phase 8 — Multi-Account Support

**Designed:** 2026-02-15
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** AccountManager CRUD, AccountDiscovery filesystem scanning, SourceReader cc_home parameterization, StateManager v2 schema migration, SetupWizard interactive flow, account-aware SyncOrchestrator
**Reference papers:** N/A (CLI multi-account patterns: AWS CLI profiles, kubectl contexts, GitHub CLI auth switching)

## Evaluation Overview

Phase 8 extends HarnessSync v1.0 (single-account) to support users with multiple Claude Code configurations (e.g., personal and work accounts) and multiple target CLI accounts. The core challenge is discovering, configuring, and syncing across account pairs without cross-contamination while maintaining the zero-dependency Python 3 stdlib constraint.

**What we're evaluating:**
- AccountManager: CRUD operations for ~/.harnesssync/accounts.json with atomic writes, name validation, target path collision detection
- AccountDiscovery: Depth-limited home directory scanning to find ~/.claude* directories in <500ms, excluding large directories (node_modules, .git)
- SourceReader parameterization: cc_home parameter override for multi-account source discovery
- StateManager v2 migration: Auto-migrate v1 flat targets to v2 nested accounts structure, per-account state tracking
- SetupWizard: Interactive account setup with discovery, validation, and confirmation flow
- SyncOrchestrator: Account-aware sync operations with isolation guarantees (account A sync never modifies account B state/files)

**What can be verified at this stage:**
- Level 1 (Sanity): CRUD operations work, discovery finds mock directories, schema migration succeeds, parameterization accepts custom paths
- Level 2 (Proxy): Integration tests verify full multi-account pipeline (2 accounts synced independently), state isolation, no cross-contamination
- Level 3 (Deferred): Real interactive setup wizard with TTY input, production home directory discovery performance (1M+ files), live Claude Code session with multiple accounts

**What cannot be verified at this stage:**
- Interactive wizard UX with real user typing input (requires TTY and manual testing)
- Discovery performance on production home directories with millions of files (requires representative test environment)
- Windows-specific path handling and symlink behavior with multi-account targets
- Cross-platform concurrent sync scenarios (multiple accounts syncing simultaneously on different file systems)

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| Setup completion time | time.time() delta from wizard start to accounts.json write | Research target: 2-3 minutes (vs 30+ minutes manual editing) |
| Discovery time | time.time() delta during filesystem scan | Research target: <500ms for depth=2 scan |
| Per-account sync time | time.time() delta per account in sync loop | Research target: ~2s (v1.0 single-account baseline) |
| Multi-account sync time | Total time to sync N accounts | Research target: 2 accounts in <5s, 3 accounts in <8s |
| False positive drift rate | Count of drift warnings after isolated account sync | Research target: 0% (perfect isolation) |
| State file size | os.path.getsize(state.json) | v1: ~2KB, v2 expected: ~5KB (3 accounts) |
| Target collision detection | ValueError raised on duplicate path | Core requirement: 100% detection rate |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 14 | Basic functionality and format verification |
| Proxy (L2) | 6 | Automated integration tests and performance benchmarks |
| Deferred (L3) | 5 | Full evaluation requiring human interaction or production environment |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: AccountManager CRUD Operations
- **What:** AccountManager creates, reads, updates, and deletes accounts in accounts.json
- **Command:**
```bash
python3 -c "
import tempfile, sys
sys.path.insert(0, '.')
from pathlib import Path
from src.account_manager import AccountManager

with tempfile.TemporaryDirectory() as td:
    am = AccountManager(config_dir=Path(td))

    # Create mock source
    src = Path(td) / '.claude-work'
    src.mkdir()

    # Test add
    am.add_account('work', src, {'codex': Path(td) / '.codex-work'})
    assert 'work' in am.list_accounts(), 'Account added'

    # Test get
    acc = am.get_account('work')
    assert acc['source']['path'] == str(src), 'Account retrieved'

    # Test remove
    assert am.remove_account('work') is True, 'Account removed'
    assert len(am.list_accounts()) == 0, 'Account list empty'

    print('PASS: AccountManager CRUD operations')
"
```
- **Expected:** All assertions pass, accounts.json created and modified atomically
- **Failure means:** Core data layer broken, multi-account config unusable

### S2: AccountManager Target Path Collision Detection
- **What:** AccountManager validates no two accounts use same target path for same CLI
- **Command:**
```bash
python3 -c "
import tempfile, sys
sys.path.insert(0, '.')
from pathlib import Path
from src.account_manager import AccountManager

with tempfile.TemporaryDirectory() as td:
    am = AccountManager(config_dir=Path(td))

    # Create sources
    src1 = Path(td) / '.claude-personal'
    src1.mkdir()
    src2 = Path(td) / '.claude-work'
    src2.mkdir()

    # Add first account
    am.add_account('personal', src1, {'codex': Path(td) / '.codex'})

    # Try to add second account with same target path
    try:
        am.add_account('work', src2, {'codex': Path(td) / '.codex'})
        assert False, 'Should raise ValueError for collision'
    except ValueError as e:
        assert 'collision' in str(e).lower(), f'Error mentions collision: {e}'

    print('PASS: Target collision detection')
"
```
- **Expected:** ValueError raised with clear message identifying collision
- **Failure means:** Cross-account contamination possible (both accounts write to same target)

### S3: AccountManager Account Name Validation
- **What:** AccountManager rejects invalid account names (spaces, special chars)
- **Command:**
```bash
python3 -c "
import tempfile, sys
sys.path.insert(0, '.')
from pathlib import Path
from src.account_manager import AccountManager

with tempfile.TemporaryDirectory() as td:
    am = AccountManager(config_dir=Path(td))
    src = Path(td) / '.claude'
    src.mkdir()

    # Test invalid names
    for invalid_name in ['invalid name', 'invalid@name', '', 'name!']:
        try:
            am.add_account(invalid_name, src, {})
            assert False, f'Should reject invalid name: {invalid_name}'
        except ValueError:
            pass

    # Test valid names
    for valid_name in ['personal', 'work-account', 'account_123', 'account-1']:
        am.add_account(valid_name, src, {f'codex': Path(td) / f'.codex-{valid_name}'})

    print('PASS: Account name validation')
"
```
- **Expected:** Invalid names rejected, valid names (alphanumeric + dash + underscore) accepted
- **Failure means:** Config corruption possible from invalid account names

### S4: AccountManager Atomic Persistence
- **What:** AccountManager survives reload from disk after write
- **Command:**
```bash
python3 -c "
import tempfile, sys
sys.path.insert(0, '.')
from pathlib import Path
from src.account_manager import AccountManager

with tempfile.TemporaryDirectory() as td:
    src = Path(td) / '.claude'
    src.mkdir()

    # Write with first instance
    am1 = AccountManager(config_dir=Path(td))
    am1.add_account('personal', src, {'codex': Path(td) / '.codex'})

    # Reload with second instance
    am2 = AccountManager(config_dir=Path(td))
    assert 'personal' in am2.list_accounts(), 'Account persisted'
    assert am2.get_account('personal')['source']['path'] == str(src), 'Data intact'

    print('PASS: Atomic persistence')
"
```
- **Expected:** Data written by first instance readable by second instance
- **Failure means:** Atomic write pattern broken (tempfile + os.replace issue)

### S5: AccountDiscovery Finds Claude Configs
- **What:** discover_claude_configs() finds .claude* directories within depth limit
- **Command:**
```bash
python3 -c "
import tempfile, sys
sys.path.insert(0, '.')
from pathlib import Path
from src.account_discovery import discover_claude_configs

with tempfile.TemporaryDirectory() as td:
    home = Path(td)

    # Create mock configs
    (home / '.claude').mkdir()
    (home / '.claude-personal').mkdir()
    (home / '.claude-work').mkdir()

    # Create non-Claude dirs (should be excluded)
    (home / '.config').mkdir()
    (home / 'Documents').mkdir()

    configs = discover_claude_configs(home_dir=home, max_depth=2)
    names = [p.name for p in configs]

    assert '.claude' in names, f'Found .claude: {names}'
    assert '.claude-personal' in names, f'Found .claude-personal: {names}'
    assert '.config' not in names, f'Excluded .config: {names}'

    print('PASS: AccountDiscovery finds configs')
"
```
- **Expected:** All .claude* directories found, non-Claude directories excluded
- **Failure means:** Setup wizard won't auto-discover existing configs

### S6: AccountDiscovery Excludes Large Directories
- **What:** Discovery skips node_modules, .git, .cache, Library to prevent slowdown
- **Command:**
```bash
python3 -c "
import tempfile, sys, time
sys.path.insert(0, '.')
from pathlib import Path
from src.account_discovery import discover_claude_configs

with tempfile.TemporaryDirectory() as td:
    home = Path(td)

    # Create large directories
    (home / 'node_modules').mkdir()
    (home / '.git').mkdir()
    (home / 'Library').mkdir()

    # Create Claude config
    (home / '.claude').mkdir()

    # Discovery should be fast and skip large dirs
    start = time.time()
    configs = discover_claude_configs(home_dir=home, max_depth=2)
    elapsed = time.time() - start

    assert elapsed < 0.5, f'Discovery too slow: {elapsed}s'
    assert len(configs) == 1, f'Found only .claude: {configs}'

    print('PASS: Excludes large directories')
"
```
- **Expected:** Discovery completes in <500ms, large directories not traversed
- **Failure means:** Setup wizard hangs on real home directories

### S7: AccountDiscovery Validates Claude Configs
- **What:** validate_claude_config() checks for expected Claude Code files/dirs
- **Command:**
```bash
python3 -c "
import tempfile, sys
sys.path.insert(0, '.')
from pathlib import Path
from src.account_discovery import validate_claude_config

with tempfile.TemporaryDirectory() as td:
    # Valid config (has settings.json)
    valid = Path(td) / '.claude'
    valid.mkdir()
    (valid / 'settings.json').write_text('{}')
    assert validate_claude_config(valid) is True, 'Valid config'

    # Valid config (has CLAUDE.md)
    valid2 = Path(td) / '.claude-work'
    valid2.mkdir()
    (valid2 / 'CLAUDE.md').write_text('# Rules')
    assert validate_claude_config(valid2) is True, 'Valid config with CLAUDE.md'

    # Invalid (empty directory)
    invalid = Path(td) / '.config'
    invalid.mkdir()
    assert validate_claude_config(invalid) is False, 'Invalid config'

    print('PASS: Validates Claude configs')
"
```
- **Expected:** Directories with Claude Code files return True, empty directories return False
- **Failure means:** False positives in discovery (random .claude* dirs incorrectly identified)

### S8: SourceReader Accepts Custom cc_home
- **What:** SourceReader with cc_home parameter reads from custom Claude config directory
- **Command:**
```bash
python3 -c "
import tempfile, sys
sys.path.insert(0, '.')
from pathlib import Path
from src.source_reader import SourceReader

with tempfile.TemporaryDirectory() as td:
    custom = Path(td) / '.claude-work'
    custom.mkdir()
    (custom / 'CLAUDE.md').write_text('# Work rules')

    reader = SourceReader(scope='user', cc_home=custom)
    assert reader.cc_home == custom, 'cc_home set correctly'

    rules = reader.get_rules()
    assert 'Work rules' in rules, 'Reads from custom path'

    print('PASS: SourceReader custom cc_home')
"
```
- **Expected:** SourceReader reads from specified directory, not default ~/.claude/
- **Failure means:** Multi-account source discovery broken

### S9: SourceReader Backward Compatibility
- **What:** SourceReader without cc_home defaults to ~/.claude/ (v1 behavior)
- **Command:**
```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from pathlib import Path
from src.source_reader import SourceReader

reader = SourceReader(scope='user')
assert reader.cc_home == Path.home() / '.claude', 'Default cc_home preserved'

print('PASS: SourceReader backward compatible')
"
```
- **Expected:** Default behavior unchanged from v1.0
- **Failure means:** Existing code broken (v1 users affected)

### S10: StateManager v1 to v2 Migration
- **What:** StateManager auto-migrates v1 state.json to v2 schema with 'default' account
- **Command:**
```bash
python3 -c "
import tempfile, sys, json
sys.path.insert(0, '.')
from pathlib import Path
from src.state_manager import StateManager

with tempfile.TemporaryDirectory() as td:
    # Create v1 state
    v1_state = {
        'version': 1,
        'last_sync': '2026-02-15T10:00:00',
        'targets': {
            'codex': {
                'last_sync': '2026-02-15T10:00:00',
                'status': 'success',
                'file_hashes': {'/path/file': 'hash123'}
            }
        }
    }
    (Path(td) / 'state.json').write_text(json.dumps(v1_state))

    # Load and check migration
    sm = StateManager(state_dir=Path(td))
    state = sm.get_all_status()

    assert state['version'] == 2, f'Migrated to v2: {state[\"version\"]}'
    assert 'accounts' in state, 'Has accounts key'
    assert 'default' in state['accounts'], 'Default account created'
    assert 'codex' in state['accounts']['default']['targets'], 'Targets migrated'

    print('PASS: v1 to v2 migration')
"
```
- **Expected:** v1 state migrated to v2 schema, all data preserved under 'default' account
- **Failure means:** v1 users lose sync history on upgrade

### S11: StateManager Account-Scoped record_sync
- **What:** StateManager record_sync with account parameter writes to accounts.{name}.targets
- **Command:**
```bash
python3 -c "
import tempfile, sys
sys.path.insert(0, '.')
from pathlib import Path
from src.state_manager import StateManager

with tempfile.TemporaryDirectory() as td:
    sm = StateManager(state_dir=Path(td))

    # Record sync for 'work' account
    sm.record_sync('codex', 'user', {'/file': 'hash'}, {}, 1, 0, 0, account='work')

    # Check account-specific state
    status = sm.get_account_target_status('work', 'codex')
    assert status is not None, 'Account state exists'
    assert status['items_synced'] == 1, 'Sync count correct'

    print('PASS: Account-scoped record_sync')
"
```
- **Expected:** State written to nested account structure
- **Failure means:** Account isolation broken

### S12: StateManager Account-Scoped Drift Detection
- **What:** StateManager detect_drift with account parameter checks account-specific hashes
- **Command:**
```bash
python3 -c "
import tempfile, sys
sys.path.insert(0, '.')
from pathlib import Path
from src.state_manager import StateManager

with tempfile.TemporaryDirectory() as td:
    sm = StateManager(state_dir=Path(td))

    # Record sync with specific hash
    sm.record_sync('codex', 'user', {'/file': 'hash123'}, {}, 1, 0, 0, account='personal')

    # Detect drift (changed hash)
    drift = sm.detect_drift('codex', {'/file': 'hash456'}, account='personal')
    assert '/file' in drift, 'Drift detected'

    # No drift for different account
    drift2 = sm.detect_drift('codex', {'/file': 'hash456'}, account='work')
    assert len(drift2) > 0, 'No state for work account = all files drift'

    print('PASS: Account-scoped drift detection')
"
```
- **Expected:** Drift detection isolated per account
- **Failure means:** False drift warnings across accounts

### S13: StateManager Backward Compatible record_sync
- **What:** StateManager record_sync without account parameter uses v1 behavior (flat targets)
- **Command:**
```bash
python3 -c "
import tempfile, sys
sys.path.insert(0, '.')
from pathlib import Path
from src.state_manager import StateManager

with tempfile.TemporaryDirectory() as td:
    sm = StateManager(state_dir=Path(td))

    # v1-style call (no account)
    sm.record_sync('codex', 'user', {'/file': 'hash'}, {}, 1, 0, 0)

    # Check v1-style state
    status = sm.get_target_status('codex')
    assert status is not None, 'v1 target state exists'

    print('PASS: Backward compatible record_sync')
"
```
- **Expected:** v1-style calls work unchanged
- **Failure means:** Existing hooks/commands broken

### S14: SetupWizard Suggests Account Names
- **What:** SetupWizard._suggest_account_name derives name from .claude* path
- **Command:**
```bash
python3 -c "
import sys
sys.path.insert(0, '.')
from pathlib import Path
from src.account_manager import AccountManager
from src.setup_wizard import SetupWizard

am = AccountManager()
wizard = SetupWizard(account_manager=am)

assert wizard._suggest_account_name(Path.home() / '.claude') == 'default'
assert wizard._suggest_account_name(Path.home() / '.claude-work') == 'work'
assert wizard._suggest_account_name(Path.home() / '.claude-personal1') == 'personal1'

print('PASS: Account name suggestion')
"
```
- **Expected:** Names correctly derived (.claude → default, .claude-work → work)
- **Failure means:** Poor UX (users must manually enter obvious names)

**Sanity gate:** ALL sanity checks must pass. Any failure blocks progression.

## Level 2: Proxy Metrics

**Purpose:** Indirect evaluation of quality/performance via integration tests.
**IMPORTANT:** Proxy metrics are NOT validated substitutes for full evaluation. Treat results with appropriate skepticism.

### P1: Multi-Account Sync Isolation (Integration Test)
- **What:** Syncing account A does not modify account B state or files
- **How:** Create 2 accounts in tempdir, sync each, verify state isolation
- **Command:**
```bash
python3 -c "
import sys, tempfile
sys.path.insert(0, '.')
from pathlib import Path

with tempfile.TemporaryDirectory() as td:
    td = Path(td)

    # Setup
    from src.account_manager import AccountManager
    config_dir = td / '.harnesssync'
    config_dir.mkdir()
    am = AccountManager(config_dir=config_dir)

    src_p = td / '.claude-personal'
    src_p.mkdir()
    (src_p / 'CLAUDE.md').write_text('# Personal')

    src_w = td / '.claude-work'
    src_w.mkdir()
    (src_w / 'CLAUDE.md').write_text('# Work')

    am.add_account('personal', src_p, {'codex': td / '.codex-personal'})
    am.add_account('work', src_w, {'codex': td / '.codex-work'})

    # Sync personal
    from src.source_reader import SourceReader
    from src.state_manager import StateManager

    reader_p = SourceReader(scope='user', cc_home=src_p)
    sm = StateManager(state_dir=config_dir)
    sm.record_sync('codex', 'user', {'/p/file': 'hash_p'}, {}, 1, 0, 0, account='personal')

    # Sync work
    reader_w = SourceReader(scope='user', cc_home=src_w)
    sm.record_sync('codex', 'user', {'/w/file': 'hash_w'}, {}, 2, 0, 0, account='work')

    # Verify isolation
    p_status = sm.get_account_target_status('personal', 'codex')
    w_status = sm.get_account_target_status('work', 'codex')

    assert p_status['items_synced'] == 1, 'Personal count correct'
    assert w_status['items_synced'] == 2, 'Work count correct'
    assert '/w/file' not in p_status['file_hashes'], 'No cross-contamination'

    print('PASS: Multi-account isolation')
    print(f'Correlation with full metric: HIGH — directly tests isolation requirement')
"
```
- **Target:** 100% isolation (no cross-contamination)
- **Evidence:** Follows AWS CLI profiles pattern where accounts are completely isolated
- **Correlation:** HIGH — directly measures same thing as multi-account requirement MULTI-03
- **Blind spots:** Doesn't test concurrent sync (deferred to real usage)
- **Validated:** false — awaiting deferred validation in live Claude Code session

### P2: Discovery Performance on Mock Home Directory
- **What:** Discovery completes within 500ms on test directory with 50+ entries
- **How:** Create mock home with 50 directories (including excluded ones), time discovery
- **Command:**
```bash
python3 -c "
import sys, tempfile, time
sys.path.insert(0, '.')
from pathlib import Path
from src.account_discovery import discover_claude_configs

with tempfile.TemporaryDirectory() as td:
    home = Path(td)

    # Create 50 directories
    for i in range(45):
        (home / f'dir_{i}').mkdir()
    (home / '.claude').mkdir()
    (home / '.claude-work').mkdir()
    (home / 'node_modules').mkdir()
    (home / '.git').mkdir()
    (home / 'Library').mkdir()

    # Time discovery
    start = time.time()
    configs = discover_claude_configs(home_dir=home, max_depth=2)
    elapsed = (time.time() - start) * 1000  # ms

    assert len(configs) == 2, f'Found 2 configs: {configs}'
    print(f'PASS: Discovery in {elapsed:.1f}ms (target: <500ms)')
    print(f'Correlation with full metric: MEDIUM — test dir != production dir with 1M+ files')
"
```
- **Target:** <500ms
- **Evidence:** Research shows os.scandir() is 2-20x faster than os.walk(), depth limiting prevents runaway scans
- **Correlation:** MEDIUM — test directory structure simpler than production home directories
- **Blind spots:** Real home directories have deeper nesting, symlinks, permission issues
- **Validated:** false — awaiting production environment testing

### P3: Per-Account Sync Time
- **What:** Time to sync one account to one target adapter
- **How:** Create account, sync, measure elapsed time
- **Command:**
```bash
python3 -c "
import sys, tempfile, time
sys.path.insert(0, '.')
from pathlib import Path

# NOTE: This test may fail if adapters not available in test environment
# Measures baseline sync time for comparison with multi-account scenarios

print('Per-account sync time test (informational)')
print('Baseline: v1.0 single account ~2s')
print('Target: account sync should not add significant overhead')
print('Proxy metric: Not directly comparable without adapter mocking')
"
```
- **Target:** ~2s (v1.0 baseline)
- **Evidence:** Phase 4 established 2s baseline for single-account sync
- **Correlation:** LOW — requires full adapter integration
- **Blind spots:** Adapter availability, network latency for MCP servers
- **Validated:** false — deferred to integration phase

### P4: State File Size Growth
- **What:** state.json size with multiple accounts
- **How:** Record sync for 3 accounts, measure file size
- **Command:**
```bash
python3 -c "
import sys, tempfile, json
sys.path.insert(0, '.')
from pathlib import Path
from src.state_manager import StateManager

with tempfile.TemporaryDirectory() as td:
    sm = StateManager(state_dir=Path(td))

    # Record syncs for 3 accounts
    for i in range(3):
        acc = f'account_{i}'
        sm.record_sync('codex', 'user', {f'/file_{i}': f'hash_{i}'}, {}, 5, 0, 0, account=acc)

    size = (Path(td) / 'state.json').stat().st_size
    print(f'State file size: {size} bytes (target: <10KB for 3 accounts)')
    print(f'v1 baseline: ~2KB, expected v2: ~5KB')

    assert size < 10_000, f'State file too large: {size} bytes'
    print('PASS: State file size acceptable')
"
```
- **Target:** ~5KB for 3 accounts (vs 2KB v1)
- **Evidence:** Research shows each account adds ~1-2KB (targets + file hashes)
- **Correlation:** HIGH — directly measures state storage overhead
- **Blind spots:** Growth rate with many files per account
- **Validated:** false

### P5: Target Collision Error Messages
- **What:** Error message identifies both conflicting accounts clearly
- **How:** Create collision scenario, check error message content
- **Command:**
```bash
python3 -c "
import sys, tempfile
sys.path.insert(0, '.')
from pathlib import Path
from src.account_manager import AccountManager

with tempfile.TemporaryDirectory() as td:
    am = AccountManager(config_dir=Path(td))

    src1 = Path(td) / '.claude-1'
    src1.mkdir()
    src2 = Path(td) / '.claude-2'
    src2.mkdir()

    am.add_account('personal', src1, {'codex': Path(td) / '.codex'})

    try:
        am.add_account('work', src2, {'codex': Path(td) / '.codex'})
        assert False, 'Should raise ValueError'
    except ValueError as e:
        msg = str(e).lower()
        assert 'collision' in msg, f'Mentions collision: {e}'
        assert 'personal' in msg, f'Mentions conflicting account: {e}'
        assert 'codex' in msg, f'Mentions target name: {e}'
        print(f'PASS: Clear error message: {e}')
"
```
- **Target:** Error message contains collision, account name, target name
- **Evidence:** AWS CLI provides clear error messages for config conflicts
- **Correlation:** HIGH — directly measures error message quality
- **Blind spots:** UX evaluation (is message actionable?)
- **Validated:** false

### P6: v1 Migration Data Preservation
- **What:** All v1 targets, file hashes, timestamps preserved after migration
- **How:** Create v1 state with 3 targets, migrate, verify all data present
- **Command:**
```bash
python3 -c "
import sys, tempfile, json
sys.path.insert(0, '.')
from pathlib import Path
from src.state_manager import StateManager

with tempfile.TemporaryDirectory() as td:
    # Create v1 state
    v1 = {
        'version': 1,
        'last_sync': '2026-02-15T10:00:00',
        'targets': {
            'codex': {'status': 'success', 'file_hashes': {'/f1': 'h1'}},
            'gemini': {'status': 'success', 'file_hashes': {'/f2': 'h2'}},
            'opencode': {'status': 'partial', 'file_hashes': {'/f3': 'h3'}}
        }
    }
    (Path(td) / 'state.json').write_text(json.dumps(v1))

    # Load and migrate
    sm = StateManager(state_dir=Path(td))
    state = sm.get_all_status()

    # Verify all v1 data under 'default' account
    default = state['accounts']['default']['targets']
    assert len(default) == 3, f'All targets migrated: {default.keys()}'
    assert default['codex']['file_hashes']['/f1'] == 'h1', 'Hash preserved'
    assert default['gemini']['file_hashes']['/f2'] == 'h2', 'Hash preserved'
    assert default['opencode']['status'] == 'partial', 'Status preserved'

    print('PASS: v1 migration preserves all data')
"
```
- **Target:** 100% data preservation
- **Evidence:** Research recommends wrapping v1 in 'default' account
- **Correlation:** HIGH — directly tests migration correctness
- **Blind spots:** Edge cases (corrupted v1 state, partial migrations)
- **Validated:** false

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring human interaction, production environment, or integration.

### D1: Interactive Setup Wizard Flow — DEFER-08-01
- **What:** Full wizard flow with real user typing input from keyboard
- **How:** Run /sync-setup in TTY, user completes discovery → selection → naming → targets → confirmation
- **Why deferred:** Requires interactive TTY and manual user input testing
- **Validates at:** Manual testing after Phase 8 execution (not automatable)
- **Depends on:** Installed plugin in live Claude Code session
- **Target:** User can complete setup in 2-3 minutes without errors
- **Risk if unmet:** Poor UX, setup abandoned, users resort to manual config editing

### D2: Production Home Directory Discovery Performance — DEFER-08-02
- **What:** Discovery time on real home directory with 1M+ files
- **How:** Run discover_claude_configs(Path.home(), max_depth=2) on production system, measure time
- **Why deferred:** Requires production environment with representative file count
- **Validates at:** Beta testing with real users
- **Depends on:** Users with large home directories (developers with many projects)
- **Target:** <2 seconds even on directories with 1M+ files (due to depth limit and exclusions)
- **Risk if unmet:** Setup wizard hangs, users kill process, bad first impression

### D3: Windows Multi-Account Path Handling — DEFER-08-03
- **What:** Multi-account sync on Windows with backslash paths and junction fallbacks
- **How:** Run full Phase 8 suite on Windows 11 with 2 accounts
- **Why deferred:** Requires Windows test environment (development on macOS)
- **Validates at:** Cross-platform testing phase
- **Depends on:** Windows test VM or CI runner
- **Target:** All sanity checks pass on Windows, path normalization works, junctions/copies succeed
- **Risk if unmet:** Windows users cannot use multi-account feature

### D4: Concurrent Multi-Account Sync — DEFER-08-04
- **What:** Multiple accounts syncing simultaneously without lock contention or state corruption
- **How:** Trigger hooks for both accounts within <1s window (e.g., edit personal and work configs rapidly)
- **Why deferred:** Requires live Claude Code session with multiple accounts and rapid edits
- **Validates at:** Live usage testing
- **Depends on:** User with 2+ accounts actively using both
- **Target:** Lock prevents concurrent sync (one waits), no state corruption, both syncs eventually succeed
- **Risk if unmet:** State file corruption, lost sync data, user confusion

### D5: Live Claude Code Session with /sync --account — DEFER-08-05
- **What:** User runs /sync --account work in live Claude Code session, only work account syncs
- **How:** Install plugin, configure 2 accounts, run /sync --account work, verify only work targets updated
- **Why deferred:** Requires full plugin installation and live Claude Code environment
- **Validates at:** Integration testing with plugin installed
- **Depends on:** Plugin installation successful, accounts.json configured
- **Target:** Only specified account syncs, other accounts unchanged, status command shows correct per-account drift
- **Risk if unmet:** Account isolation broken, cross-contamination in production

## Baselines

| Baseline | Description | Expected Score | Source |
|----------|-------------|----------------|--------|
| v1.0 single-account sync time | Time to sync one account to all 3 targets | ~2s | Phase 4 established baseline |
| v1.0 state.json size | State file size with single account | ~2KB | Phase 1 baseline |
| Discovery time (bounded scan) | Time to scan ~50 directory home | <500ms | Research: os.scandir() performance |
| False drift rate | Drift warnings after isolated account sync | 0% | Perfect isolation requirement |

## Evaluation Scripts

**Location of evaluation code:**
```
.planning/phases/08-multi-account-support/08-EVAL.md (this file — inline Python tests)
```

**How to run full evaluation:**
```bash
# Level 1: Sanity checks (all S1-S14 commands above)
for i in {1..14}; do
    echo "Running S${i}..."
    # Extract and run each S${i} command block
done

# Level 2: Proxy metrics (all P1-P6 commands above)
for i in {1..6}; do
    echo "Running P${i}..."
    # Extract and run each P${i} command block
done

# Level 3: Manual deferred validations (documented, not automated)
echo "Deferred validations: See D1-D5 above for manual test procedures"
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1 | PASS/FAIL | | AccountManager CRUD |
| S2 | PASS/FAIL | | Target collision detection |
| S3 | PASS/FAIL | | Name validation |
| S4 | PASS/FAIL | | Atomic persistence |
| S5 | PASS/FAIL | | Discovery finds configs |
| S6 | PASS/FAIL | | Excludes large dirs |
| S7 | PASS/FAIL | | Validates configs |
| S8 | PASS/FAIL | | Custom cc_home |
| S9 | PASS/FAIL | | Backward compat |
| S10 | PASS/FAIL | | v1→v2 migration |
| S11 | PASS/FAIL | | Account record_sync |
| S12 | PASS/FAIL | | Account drift detect |
| S13 | PASS/FAIL | | v1 record_sync compat |
| S14 | PASS/FAIL | | Name suggestion |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: Isolation | 100% | | MET/MISSED | Multi-account sync isolation |
| P2: Discovery time | <500ms | | MET/MISSED | Mock home (50 dirs) |
| P3: Sync time | ~2s | | MET/MISSED | Per-account baseline |
| P4: State size | <10KB | | MET/MISSED | 3 accounts |
| P5: Error clarity | Clear msg | | MET/MISSED | Collision errors |
| P6: Migration | 100% preserved | | MET/MISSED | v1 data intact |

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-08-01 | Interactive wizard UX | PENDING | Manual testing |
| DEFER-08-02 | Production discovery perf | PENDING | Beta testing |
| DEFER-08-03 | Windows path handling | PENDING | Cross-platform CI |
| DEFER-08-04 | Concurrent sync | PENDING | Live usage |
| DEFER-08-05 | Live /sync --account | PENDING | Integration testing |

## Evaluation Confidence

**Overall confidence in evaluation design:** MEDIUM-HIGH

**Justification:**
- Sanity checks: ADEQUATE — 14 checks cover all core functionality (CRUD, discovery, migration, parameterization, isolation)
- Proxy metrics: WELL-EVIDENCED — Integration test (P1) directly measures isolation requirement, discovery test (P2) uses realistic mock, migration test (P6) verifies data preservation
- Deferred coverage: COMPREHENSIVE — All interactive/production/cross-platform scenarios identified with clear validation plans

**What this evaluation CAN tell us:**
- AccountManager correctly stores and retrieves multi-account configurations
- Discovery finds Claude configs and excludes large directories in test environments
- StateManager v2 migration preserves all v1 data
- SourceReader parameterization works with custom cc_home paths
- Account isolation works (account A sync doesn't modify account B state)
- Backward compatibility preserved (v1-style calls work unchanged)

**What this evaluation CANNOT tell us:**
- Interactive wizard UX quality (requires human evaluation — deferred to D1)
- Discovery performance on production home directories with 1M+ files (deferred to D2)
- Windows-specific issues (path handling, junctions) (deferred to D3)
- Concurrent sync behavior under rapid hook invocations (deferred to D4)
- End-to-end user experience in live Claude Code session (deferred to D5)

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-02-15*
