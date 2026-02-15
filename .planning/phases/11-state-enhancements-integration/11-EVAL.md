# Evaluation Plan: Phase 11 — State Enhancements & Integration

**Designed:** 2026-02-15
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** Plugin metadata tracking, plugin drift detection, MCP source grouping display
**Reference papers:** 11-RESEARCH.md (state schema extension, drift detection patterns, display formatting)

## Evaluation Overview

Phase 11 is the final v2.0 phase, completing the plugin and scope-aware sync system by extending StateManager to track plugin metadata (version, MCP count) for update-triggered re-sync detection, and enhancing /sync-status to display MCP servers grouped by source (user/project/local/plugin) with scope labels. This phase integrates all v2.0 components (Phases 9-11) into a cohesive system with plugin-aware drift detection.

**Key challenges:**
1. **Plugin metadata persistence** — Must record plugin version/count after successful sync without corrupting state on partial failures
2. **Plugin drift detection** — Must detect version changes, MCP count changes, added/removed plugins without false positives
3. **MCP source grouping** — Must distinguish plugin MCPs from user-configured MCPs in /sync-status display
4. **State schema extension** — Must add `plugins` section without breaking existing v1/v2 state structure or migration paths
5. **Account-scoped plugin tracking** — Multi-account support requires per-account plugin state isolation

This is primarily a **state management and display enhancement** phase with no algorithmic innovation — correctness depends on faithful implementation of 11-RESEARCH.md patterns (incremental state updates, drift comparison logic) and accurate tracking of plugin lifecycle (install/update/remove).

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| Plugin metadata persistence | Requirement STATE-01 | StateManager must track plugin versions and MCP counts for update detection |
| Plugin version drift detection | Requirement STATE-03 | Detects when plugins update (version changes) |
| Plugin MCP count drift detection | Requirement STATE-03 | Detects when plugin updates add/remove MCPs (functional changes) |
| Plugin added/removed detection | Requirement STATE-03 | Tracks plugin installation/uninstallation lifecycle |
| MCP source grouping accuracy | Requirement STATE-02 | /sync-status must separate plugin MCPs from user-configured MCPs |
| MCP scope label display | Requirement STATE-02 | Each MCP shows its scope (user/project/local) for clarity |
| Account-scoped plugin isolation | StateManager v2 schema | Multi-account setups must isolate plugin state per account |
| Stale plugin cleanup | 11-RESEARCH.md Pitfall 2 | Removed plugins must not accumulate in state.json (replacement semantics) |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 7 | Basic functionality — method existence, format validation, pattern matching |
| Proxy (L2) | 8 | Comprehensive state tracking, drift detection, display formatting |
| Deferred (L3) | 3 | Real plugin updates, production multi-account testing, full v2.0 pipeline |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: StateManager Plugin Methods Exist
- **What:** StateManager has all three new plugin tracking methods with correct signatures
- **Command:**
  ```bash
  python3 -c "
  import inspect
  from src.state_manager import StateManager

  # Check method existence
  assert hasattr(StateManager, 'record_plugin_sync'), 'StateManager missing record_plugin_sync'
  assert hasattr(StateManager, 'detect_plugin_drift'), 'StateManager missing detect_plugin_drift'
  assert hasattr(StateManager, 'get_plugin_status'), 'StateManager missing get_plugin_status'

  # Check signatures
  sig1 = inspect.signature(StateManager.record_plugin_sync)
  assert 'plugins_metadata' in sig1.parameters, 'record_plugin_sync missing plugins_metadata param'

  sig2 = inspect.signature(StateManager.detect_plugin_drift)
  assert 'current_plugins' in sig2.parameters, 'detect_plugin_drift missing current_plugins param'

  sig3 = inspect.signature(StateManager.get_plugin_status)
  # No required params for get_plugin_status

  print('S1: OK')
  "
  ```
- **Expected:** "S1: OK" printed, no errors
- **Failure means:** Methods missing or signatures don't match plan specifications

### S2: Orchestrator Plugin Metadata Extraction Exists
- **What:** Orchestrator has _extract_plugin_metadata() private method
- **Command:**
  ```bash
  python3 -c "
  from src.orchestrator import SyncOrchestrator

  assert hasattr(SyncOrchestrator, '_extract_plugin_metadata'), 'Orchestrator missing _extract_plugin_metadata'

  # Check it's callable
  import inspect
  sig = inspect.signature(SyncOrchestrator._extract_plugin_metadata)
  assert 'mcp_scoped' in sig.parameters, '_extract_plugin_metadata missing mcp_scoped param'

  print('S2: OK')
  "
  ```
- **Expected:** "S2: OK"
- **Failure means:** Orchestrator integration incomplete

### S3: Sync-Status Helper Functions Exist
- **What:** /sync-status module has all four new helper functions
- **Command:**
  ```bash
  python3 -c "
  from src.commands.sync_status import _group_mcps_by_source, _format_mcp_groups, _format_plugin_drift, _extract_current_plugins

  # All four functions exist
  import inspect
  assert callable(_group_mcps_by_source), '_group_mcps_by_source not callable'
  assert callable(_format_mcp_groups), '_format_mcp_groups not callable'
  assert callable(_format_plugin_drift), '_format_plugin_drift not callable'
  assert callable(_extract_current_plugins), '_extract_current_plugins not callable'

  print('S3: OK')
  "
  ```
- **Expected:** "S3: OK"
- **Failure means:** Sync-status display helpers not implemented

### S4: Plugin Metadata Schema Validation
- **What:** Plugin metadata dict has required fields (version, mcp_count, mcp_servers, last_sync)
- **Command:**
  ```bash
  python3 -c "
  from datetime import datetime

  # Test fixture
  plugin_metadata = {
      'test-plugin': {
          'version': '1.0.0',
          'mcp_count': 2,
          'mcp_servers': ['server1', 'server2'],
          'last_sync': datetime.now().isoformat()
      }
  }

  # Validate schema
  for plugin_name, data in plugin_metadata.items():
      assert 'version' in data, 'Missing version field'
      assert 'mcp_count' in data, 'Missing mcp_count field'
      assert 'mcp_servers' in data, 'Missing mcp_servers field'
      assert 'last_sync' in data, 'Missing last_sync field'
      assert isinstance(data['mcp_servers'], list), 'mcp_servers must be list'
      assert isinstance(data['mcp_count'], int), 'mcp_count must be int'

  print('S4: OK')
  "
  ```
- **Expected:** "S4: OK"
- **Failure means:** Plugin metadata schema doesn't match STATE-01 requirement

### S5: State.json Plugins Section Format
- **What:** state.json with plugins section is valid JSON and has correct structure
- **Command:**
  ```bash
  python3 -c "
  import json, tempfile
  from pathlib import Path

  # Create test state with plugins section
  state = {
      'version': 2,
      'last_sync': '2024-01-01T12:00:00',
      'targets': {},
      'accounts': {},
      'plugins': {
          'context7': {
              'version': '1.2.0',
              'mcp_count': 2,
              'mcp_servers': ['browse', 'query'],
              'last_sync': '2024-01-01T12:00:00'
          }
      }
  }

  # Write and re-read to validate JSON
  with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
      json.dump(state, f, indent=2)
      temp_path = f.name

  # Re-read
  loaded = json.loads(Path(temp_path).read_text())
  assert loaded['version'] == 2, 'State version corrupted'
  assert 'plugins' in loaded, 'Plugins section missing'
  assert loaded['plugins']['context7']['version'] == '1.2.0', 'Plugin version corrupted'

  Path(temp_path).unlink()
  print('S5: OK')
  "
  ```
- **Expected:** "S5: OK"
- **Failure means:** JSON serialization issue with plugin metadata

### S6: MCP Source Grouping Pattern Matching
- **What:** Grouping logic correctly identifies plugin vs file-based MCPs
- **Command:**
  ```bash
  python3 -c "
  # Test fixture
  mcp_scoped = {
      'user-server': {
          'config': {},
          'metadata': {'scope': 'user', 'source': 'file'}
      },
      'plugin-server': {
          'config': {},
          'metadata': {
              'scope': 'user',
              'source': 'plugin',
              'plugin_name': 'test-plugin',
              'plugin_version': '1.0.0'
          }
      }
  }

  # Validate pattern matching
  for name, entry in mcp_scoped.items():
      metadata = entry.get('metadata', {})
      source = metadata.get('source', 'file')

      if name == 'plugin-server':
          assert source == 'plugin', 'Plugin server should have source=plugin'
          assert 'plugin_name' in metadata, 'Plugin server missing plugin_name'
          assert 'plugin_version' in metadata, 'Plugin server missing plugin_version'
      else:
          assert source == 'file', 'User server should have source=file'

  print('S6: OK')
  "
  ```
- **Expected:** "S6: OK"
- **Failure means:** Metadata structure doesn't match Phase 9 output format

### S7: Drift Detection Comparison Logic
- **What:** Drift detection correctly compares version strings and MCP counts
- **Command:**
  ```bash
  python3 -c "
  # Test drift comparison logic
  stored = {
      'plugin-a': {'version': '1.0.0', 'mcp_count': 2},
      'plugin-b': {'version': '2.1.0', 'mcp_count': 1}
  }

  current = {
      'plugin-a': {'version': '1.1.0', 'mcp_count': 2},  # Version changed
      'plugin-b': {'version': '2.1.0', 'mcp_count': 3},  # MCP count changed
      'plugin-c': {'version': '1.0.0', 'mcp_count': 1}   # Added
  }

  # Simulate drift detection logic
  drift = {}

  # Check stored plugins
  for name, data in stored.items():
      if name not in current:
          drift[name] = 'removed'
      else:
          if stored[name]['version'] != current[name]['version']:
              drift[name] = f'version_changed: {stored[name][\"version\"]} -> {current[name][\"version\"]}'
          elif stored[name]['mcp_count'] != current[name]['mcp_count']:
              drift[name] = f'mcp_count_changed: {stored[name][\"mcp_count\"]} -> {current[name][\"mcp_count\"]}'

  # Check for new plugins
  for name in current:
      if name not in stored:
          drift[name] = 'added'

  # Validate results
  assert 'plugin-a' in drift, 'Version change not detected'
  assert 'version_changed' in drift['plugin-a'], 'Wrong drift type for version change'
  assert 'plugin-b' in drift, 'MCP count change not detected'
  assert 'mcp_count_changed' in drift['plugin-b'], 'Wrong drift type for count change'
  assert 'plugin-c' in drift, 'Added plugin not detected'
  assert drift['plugin-c'] == 'added', 'Wrong drift type for added plugin'

  print('S7: OK')
  "
  ```
- **Expected:** "S7: OK"
- **Failure means:** Drift comparison logic has bugs

**Sanity gate:** ALL 7 checks must pass. Any failure blocks progression to proxy metrics.

## Level 2: Proxy Metrics

**Purpose:** Comprehensive validation of plugin tracking, drift detection, and display formatting.
**IMPORTANT:** Proxy metrics are NOT validated substitutes for full evaluation. Treat results with appropriate skepticism.

### P1: Plugin Metadata Record and Retrieve (Flat State)
- **What:** StateManager.record_plugin_sync() persists plugin metadata to state.json, get_plugin_status() retrieves it
- **How:** Create temp state dir, record plugin metadata, verify state.json written correctly, retrieve and compare
- **Command:**
  ```bash
  python3 -c "
  import tempfile, json
  from pathlib import Path
  from src.state_manager import StateManager

  with tempfile.TemporaryDirectory() as tmpdir:
      state_dir = Path(tmpdir)
      sm = StateManager(state_dir=state_dir)

      # Test data
      plugins = {
          'context7': {
              'version': '1.2.0',
              'mcp_count': 2,
              'mcp_servers': ['browse', 'query'],
              'last_sync': '2024-01-01T12:00:00'
          },
          'grd': {
              'version': '0.3.1',
              'mcp_count': 1,
              'mcp_servers': ['research'],
              'last_sync': '2024-01-01T12:00:00'
          }
      }

      # Record
      sm.record_plugin_sync(plugins)

      # Verify file written
      state_file = state_dir / 'state.json'
      assert state_file.exists(), 'state.json not written'

      # Verify content
      state = json.loads(state_file.read_text())
      assert 'plugins' in state, 'plugins section missing'
      assert state['plugins']['context7']['version'] == '1.2.0', 'context7 version wrong'
      assert state['plugins']['context7']['mcp_count'] == 2, 'context7 count wrong'
      assert state['plugins']['grd']['mcp_count'] == 1, 'grd count wrong'

      # Retrieve
      retrieved = sm.get_plugin_status()
      assert 'context7' in retrieved, 'context7 not retrieved'
      assert retrieved['context7']['version'] == '1.2.0', 'Retrieved version wrong'

  print('P1: PASS')
  "
  ```
- **Target:** 100% persistence accuracy (all plugins written and retrieved correctly)
- **Evidence:** Requirement STATE-01 specifies exact schema: plugin_name -> {version, mcp_count, last_sync}
- **Correlation with full metric:** HIGH — Directly tests requirement
- **Blind spots:** Doesn't test concurrent access, state file corruption recovery, very large plugin counts (50+)
- **Validated:** false — awaiting Phase 11 deferred validation with production use

### P2: Plugin Metadata Record (Account-Scoped)
- **What:** record_plugin_sync() with account parameter stores under accounts.{account}.plugins
- **How:** Call with account='work', verify nested structure in state.json
- **Command:**
  ```bash
  python3 -c "
  import tempfile, json
  from pathlib import Path
  from src.state_manager import StateManager

  with tempfile.TemporaryDirectory() as tmpdir:
      state_dir = Path(tmpdir)
      sm = StateManager(state_dir=state_dir)

      plugins = {
          'test-plugin': {
              'version': '1.0.0',
              'mcp_count': 1,
              'mcp_servers': ['server1'],
              'last_sync': '2024-01-01T12:00:00'
          }
      }

      # Record with account
      sm.record_plugin_sync(plugins, account='work')

      # Verify nested structure
      state = json.loads((state_dir / 'state.json').read_text())
      assert 'accounts' in state, 'accounts section missing'
      assert 'work' in state['accounts'], 'work account missing'
      assert 'plugins' in state['accounts']['work'], 'plugins section missing in account'
      assert state['accounts']['work']['plugins']['test-plugin']['version'] == '1.0.0', 'Version wrong'

      # Retrieve with account
      retrieved = sm.get_plugin_status(account='work')
      assert 'test-plugin' in retrieved, 'Plugin not retrieved for account'

  print('P2: PASS')
  "
  ```
- **Target:** 100% account isolation (account-scoped plugins stored separately from flat/other accounts)
- **Evidence:** StateManager v2 schema supports per-account nesting (11-RESEARCH.md lines 31-59)
- **Correlation with full metric:** HIGH — Tests multi-account isolation
- **Blind spots:** Doesn't test multiple accounts simultaneously, account migration
- **Validated:** false — awaiting production multi-account testing

### P3: Plugin Version Drift Detection
- **What:** detect_plugin_drift() detects version changes (1.0.0 -> 1.1.0)
- **How:** Seed state with v1.0.0, pass current v1.1.0, verify drift detected with reason
- **Command:**
  ```bash
  python3 -c "
  import tempfile
  from pathlib import Path
  from src.state_manager import StateManager

  with tempfile.TemporaryDirectory() as tmpdir:
      state_dir = Path(tmpdir)
      sm = StateManager(state_dir=state_dir)

      # Seed stored state
      stored_plugins = {
          'test-plugin': {
              'version': '1.0.0',
              'mcp_count': 1,
              'mcp_servers': ['server1'],
              'last_sync': '2024-01-01T12:00:00'
          }
      }
      sm.record_plugin_sync(stored_plugins)

      # Current plugins (version updated)
      current_plugins = {
          'test-plugin': {
              'version': '1.1.0',
              'mcp_count': 1,
              'mcp_servers': ['server1'],
              'last_sync': '2024-01-02T12:00:00'
          }
      }

      # Detect drift
      drift = sm.detect_plugin_drift(current_plugins)

      # Verify
      assert 'test-plugin' in drift, 'Drift not detected'
      assert 'version_changed' in drift['test-plugin'], f'Wrong drift type: {drift[\"test-plugin\"]}'
      assert '1.0.0' in drift['test-plugin'], 'Old version not in reason'
      assert '1.1.0' in drift['test-plugin'], 'New version not in reason'

  print('P3: PASS')
  "
  ```
- **Target:** 100% version change detection (all version updates detected with correct old->new reason)
- **Evidence:** Requirement STATE-03 explicitly requires plugin version drift detection
- **Correlation with full metric:** HIGH — Directly tests core drift detection logic
- **Blind spots:** Doesn't test semantic versioning ordering, pre-release versions, version downgrades
- **Validated:** false — awaiting Phase 11 integration test

### P4: Plugin MCP Count Drift Detection
- **What:** detect_plugin_drift() detects MCP count changes (2 -> 3)
- **How:** Seed state with count=2, pass current count=3, verify drift detected
- **Command:**
  ```bash
  python3 -c "
  import tempfile
  from pathlib import Path
  from src.state_manager import StateManager

  with tempfile.TemporaryDirectory() as tmpdir:
      state_dir = Path(tmpdir)
      sm = StateManager(state_dir=state_dir)

      # Stored: 2 MCPs
      stored_plugins = {
          'test-plugin': {
              'version': '1.0.0',
              'mcp_count': 2,
              'mcp_servers': ['server1', 'server2'],
              'last_sync': '2024-01-01T12:00:00'
          }
      }
      sm.record_plugin_sync(stored_plugins)

      # Current: 3 MCPs (added new server)
      current_plugins = {
          'test-plugin': {
              'version': '1.0.0',  # Version same
              'mcp_count': 3,
              'mcp_servers': ['server1', 'server2', 'server3'],
              'last_sync': '2024-01-02T12:00:00'
          }
      }

      # Detect drift
      drift = sm.detect_plugin_drift(current_plugins)

      # Verify
      assert 'test-plugin' in drift, 'Drift not detected'
      assert 'mcp_count_changed' in drift['test-plugin'], f'Wrong drift type: {drift[\"test-plugin\"]}'
      assert '2' in drift['test-plugin'], 'Old count not in reason'
      assert '3' in drift['test-plugin'], 'New count not in reason'

  print('P4: PASS')
  "
  ```
- **Target:** 100% MCP count change detection (all count changes detected with correct old->new reason)
- **Evidence:** Requirement STATE-03 requires detection of "MCP changes" (functional changes to plugin MCPs)
- **Correlation with full metric:** HIGH — Tests functional drift detection
- **Blind spots:** Doesn't test same count but different server names (content change vs count change)
- **Validated:** false — awaiting Phase 11 integration test

### P5: Plugin Added/Removed Detection
- **What:** detect_plugin_drift() detects newly installed and uninstalled plugins
- **How:** Seed state with plugin-a, pass current with plugin-b (removed a, added b), verify both detected
- **Command:**
  ```bash
  python3 -c "
  import tempfile
  from pathlib import Path
  from src.state_manager import StateManager

  with tempfile.TemporaryDirectory() as tmpdir:
      state_dir = Path(tmpdir)
      sm = StateManager(state_dir=state_dir)

      # Stored: plugin-a
      stored_plugins = {
          'plugin-a': {
              'version': '1.0.0',
              'mcp_count': 1,
              'mcp_servers': ['server-a'],
              'last_sync': '2024-01-01T12:00:00'
          }
      }
      sm.record_plugin_sync(stored_plugins)

      # Current: plugin-b (plugin-a removed, plugin-b added)
      current_plugins = {
          'plugin-b': {
              'version': '1.0.0',
              'mcp_count': 1,
              'mcp_servers': ['server-b'],
              'last_sync': '2024-01-02T12:00:00'
          }
      }

      # Detect drift
      drift = sm.detect_plugin_drift(current_plugins)

      # Verify
      assert 'plugin-a' in drift, 'Removed plugin not detected'
      assert drift['plugin-a'] == 'removed', f'Wrong drift type for removed: {drift[\"plugin-a\"]}'

      assert 'plugin-b' in drift, 'Added plugin not detected'
      assert drift['plugin-b'] == 'added', f'Wrong drift type for added: {drift[\"plugin-b\"]}'

  print('P5: PASS')
  "
  ```
- **Target:** 100% add/remove detection (all plugin installations and uninstallations detected)
- **Evidence:** Requirement STATE-03 drift detection must handle plugin lifecycle (install/update/remove)
- **Correlation with full metric:** HIGH — Tests lifecycle tracking
- **Blind spots:** Doesn't test plugins with no MCPs, plugins that crash on discovery
- **Validated:** false — awaiting Phase 11 integration test

### P6: Stale Plugin Cleanup (Replacement Semantics)
- **What:** record_plugin_sync() replaces entire plugins section, not merging, to avoid stale accumulation
- **How:** Record 2 plugins, then record 1 plugin, verify first record's plugins are gone (not merged)
- **Command:**
  ```bash
  python3 -c "
  import tempfile, json
  from pathlib import Path
  from src.state_manager import StateManager

  with tempfile.TemporaryDirectory() as tmpdir:
      state_dir = Path(tmpdir)
      sm = StateManager(state_dir=state_dir)

      # First record: 2 plugins
      plugins_v1 = {
          'plugin-a': {'version': '1.0.0', 'mcp_count': 1, 'mcp_servers': ['a'], 'last_sync': '2024-01-01'},
          'plugin-b': {'version': '1.0.0', 'mcp_count': 1, 'mcp_servers': ['b'], 'last_sync': '2024-01-01'}
      }
      sm.record_plugin_sync(plugins_v1)

      # Second record: 1 plugin (plugin-b removed)
      plugins_v2 = {
          'plugin-a': {'version': '1.0.0', 'mcp_count': 1, 'mcp_servers': ['a'], 'last_sync': '2024-01-02'}
      }
      sm.record_plugin_sync(plugins_v2)

      # Verify plugin-b removed (replacement, not merge)
      state = json.loads((state_dir / 'state.json').read_text())
      assert 'plugin-a' in state['plugins'], 'plugin-a should still be present'
      assert 'plugin-b' not in state['plugins'], 'plugin-b should be removed (replaced, not merged)'

  print('P6: PASS')
  "
  ```
- **Target:** 0 stale plugins (removed plugins do not accumulate in state.json)
- **Evidence:** 11-RESEARCH.md Pitfall 2 warns against stale accumulation; replacement semantics prevent state file growth
- **Correlation with full metric:** HIGH — Directly tests replacement logic
- **Blind spots:** Doesn't test long-term state file size with many plugin install/uninstall cycles
- **Validated:** false — awaiting production use monitoring

### P7: MCP Source Grouping Accuracy
- **What:** _group_mcps_by_source() correctly groups MCPs into user/project/local/plugins categories
- **How:** Pass mixed scoped MCPs (2 user, 1 project, 1 local, 2 plugin from different plugins), verify grouping
- **Command:**
  ```bash
  python3 -c "
  from src.commands.sync_status import _group_mcps_by_source

  # Test data
  scoped_mcps = {
      'user-srv-1': {'config': {}, 'metadata': {'scope': 'user', 'source': 'file'}},
      'user-srv-2': {'config': {}, 'metadata': {'scope': 'user', 'source': 'file'}},
      'proj-srv': {'config': {}, 'metadata': {'scope': 'project', 'source': 'file'}},
      'local-srv': {'config': {}, 'metadata': {'scope': 'local', 'source': 'file'}},
      'plugin-a-srv': {'config': {}, 'metadata': {'scope': 'user', 'source': 'plugin', 'plugin_name': 'plugin-a', 'plugin_version': '1.0.0'}},
      'plugin-b-srv': {'config': {}, 'metadata': {'scope': 'user', 'source': 'plugin', 'plugin_name': 'plugin-b', 'plugin_version': '2.0.0'}}
  }

  # Group
  groups = _group_mcps_by_source(scoped_mcps)

  # Verify
  assert len(groups['user']) == 2, f'Expected 2 user MCPs, got {len(groups[\"user\"])}'
  assert len(groups['project']) == 1, f'Expected 1 project MCP, got {len(groups[\"project\"])}'
  assert len(groups['local']) == 1, f'Expected 1 local MCP, got {len(groups[\"local\"])}'
  assert len(groups['plugins']) == 2, f'Expected 2 plugin groups, got {len(groups[\"plugins\"])}'

  assert 'plugin-a@1.0.0' in groups['plugins'], 'plugin-a@1.0.0 group missing'
  assert 'plugin-b@2.0.0' in groups['plugins'], 'plugin-b@2.0.0 group missing'

  # Verify user file-based MCPs not in plugins
  assert 'user-srv-1' in groups['user'], 'user-srv-1 should be in user group'
  assert 'user-srv-1' not in str(groups['plugins']), 'user-srv-1 should NOT be in plugins'

  print('P7: PASS')
  "
  ```
- **Target:** 100% grouping accuracy (all 6 MCPs in correct groups, 2 plugin groups created)
- **Evidence:** Requirement STATE-02 specifies grouping format: User-configured, Project-configured, Plugin-provided (plugin-name@version)
- **Correlation with full metric:** HIGH — Directly tests grouping logic
- **Blind spots:** Doesn't test edge cases (missing metadata fields, duplicate plugin@version, empty groups)
- **Validated:** false — awaiting Phase 11 integration test

### P8: MCP Display Formatting with Plugin Drift
- **What:** _format_mcp_groups() and _format_plugin_drift() produce correct output strings
- **How:** Generate formatted output, verify sections present, plugin@version format, drift warnings
- **Command:**
  ```bash
  python3 -c "
  from src.commands.sync_status import _group_mcps_by_source, _format_mcp_groups, _format_plugin_drift

  # Test MCP groups
  scoped = {
      'user-srv': {'config': {}, 'metadata': {'scope': 'user', 'source': 'file'}},
      'proj-srv': {'config': {}, 'metadata': {'scope': 'project', 'source': 'file'}},
      'ctx-srv': {'config': {}, 'metadata': {'scope': 'user', 'source': 'plugin', 'plugin_name': 'context7', 'plugin_version': '1.2.0'}}
  }
  groups = _group_mcps_by_source(scoped)
  lines = _format_mcp_groups(groups)
  output = '\\n'.join(lines)

  # Verify sections
  assert 'User-configured' in output, 'User-configured section missing'
  assert 'Project-configured' in output, 'Project-configured section missing'
  assert 'Plugin-provided' in output, 'Plugin-provided section missing'
  assert 'context7@1.2.0' in output, 'Plugin@version format missing'

  # Test drift formatting
  drift = {
      'plugin-a': 'version_changed: 1.0.0 -> 1.1.0',
      'plugin-b': 'removed'
  }
  drift_lines = _format_plugin_drift(drift)
  drift_output = '\\n'.join(drift_lines)

  assert 'Plugin Drift' in drift_output, 'Plugin Drift header missing'
  assert 'plugin-a' in drift_output, 'plugin-a not in drift output'
  assert 'version_changed' in drift_output, 'version_changed not in drift output'
  assert 'plugin-b' in drift_output, 'plugin-b not in drift output'
  assert 'removed' in drift_output, 'removed not in drift output'

  # Test empty drift (no output)
  empty_lines = _format_plugin_drift({})
  assert len(empty_lines) == 0, 'Empty drift should produce no output lines'

  print('P8: PASS')
  "
  ```
- **Target:** 100% format compliance (all sections present, plugin@version format, drift warnings formatted)
- **Evidence:** Requirement STATE-02 specifies display format with plugin-name@version grouping
- **Correlation with full metric:** MEDIUM-HIGH — Tests output formatting but not actual /sync-status command integration
- **Blind spots:** Doesn't test truncation logic (>10 servers), actual terminal display, color codes
- **Validated:** false — awaiting Phase 11 integration test with real /sync-status

**Proxy metrics confidence:** MEDIUM-HIGH for state tracking and drift detection logic. Display formatting tests structure but not user experience.

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring integration or resources not available now.

### D1: Real Plugin Update in Claude Code — DEFER-11-01
- **What:** Real plugin update (version 1.0.0 -> 1.1.0) triggers drift detection in live /sync-status
- **How:**
  1. Install real Claude Code plugin with MCP server (e.g., Context7)
  2. Run /sync to populate state.json with plugin metadata
  3. Verify state.json contains plugin version and MCP count
  4. Update plugin to new version via Claude Code plugin manager
  5. Run /sync-status without syncing
  6. Verify Plugin Drift section shows version change
  7. Run /sync to update state
  8. Run /sync-status again
  9. Verify Plugin Drift section clears (no drift after re-sync)
- **Why deferred:** Requires live Claude Code installation with real plugins and plugin update capability
- **Validates at:** Phase 11 completion (after both plans complete)
- **Depends on:**
  - Real Claude Code installation
  - Claude Code plugin with MCP servers (Context7, GRD, or similar)
  - Plugin update mechanism (version bump)
  - Phase 11 implementation complete (both plans 11-01 and 11-02)
- **Target:**
  - Plugin metadata recorded after first /sync: 100%
  - Version drift detected before re-sync: 100%
  - Drift cleared after re-sync: 100%
  - state.json updated with new version: 100%
  - No false positives (drift when version unchanged): 0%
- **Risk if unmet:**
  - Plugin updates go unnoticed — users don't know when to re-sync
  - False positives cause sync fatigue — users ignore drift warnings
  - State corruption on plugin update — state.json becomes invalid
- **Fallback:** Manual plugin version tracking (user notes which plugins installed); skip drift detection feature

### D2: Production Multi-Account Plugin Isolation — DEFER-11-02
- **What:** Plugin state correctly isolated per account in multi-account HarnessSync setup
- **How:**
  1. Configure 2 accounts in HarnessSync (e.g., 'work' and 'personal')
  2. Each account has different Claude Code home directory
  3. Install different plugins in each account (plugin-a in work, plugin-b in personal)
  4. Run /sync for account 'work'
  5. Verify state.json has accounts.work.plugins.plugin-a, NO plugin-b
  6. Run /sync for account 'personal'
  7. Verify state.json has accounts.personal.plugins.plugin-b, NO plugin-a
  8. Run /sync-status for 'work'
  9. Verify Plugin Drift section shows only work account plugins
  10. Update plugin-a in work account
  11. Run /sync-status for 'personal'
  12. Verify NO drift detected (work plugin update doesn't affect personal account)
- **Why deferred:** Requires multi-account setup with separate Claude Code installations per account
- **Validates at:** Phase 11 production testing (manual or automated after v2.0 release)
- **Depends on:**
  - Multi-account HarnessSync configuration (Phase 8 feature)
  - Multiple Claude Code installations with different plugin sets
  - Phase 11 account-scoped plugin tracking implementation
- **Target:**
  - Plugin state isolated per account: 100% (no cross-account contamination)
  - Drift detection scoped to account: 100% (account A drift doesn't show in account B)
  - State schema correct: accounts.{account}.plugins structure present
  - No false positives from other accounts: 0%
- **Risk if unmet:**
  - Account A's plugin updates trigger drift in account B — cross-account contamination
  - State.json mixes plugin metadata across accounts — data corruption
  - /sync-status shows wrong account's plugins — user confusion
- **Fallback:** Single-account plugin tracking only; multi-account setups must disable plugin drift detection

### D3: Full v2.0 Pipeline Integration Test — DEFER-11-03
- **What:** End-to-end v2.0 validation: Phase 9 discovery + Phase 10 routing + Phase 11 plugin tracking + full /sync-status display
- **How:**
  1. Setup environment with:
     - 3 real Claude Code plugins with MCPs (Context7, GRD, GitHub plugin)
     - 2 user-configured MCPs in ~/.claude.json mcpServers
     - 1 project-configured MCP in .mcp.json
     - 1 local-configured MCP in ~/.claude.json projects section
  2. Run /sync with scope=all
  3. Verify all 8 MCP sources discovered (100% discovery rate from Phase 9)
  4. Verify scope routing (Phase 10):
     - User MCPs in ~/.codex/config.toml and ~/.gemini/settings.json
     - Project MCPs in .codex/config.toml and .gemini/settings.json
     - Plugin MCPs in user-scope configs only (not project)
  5. Verify plugin tracking (Phase 11):
     - state.json has plugins section with all 3 plugins
     - Each plugin has version, mcp_count, mcp_servers, last_sync
  6. Run /sync-status
  7. Verify MCP source grouping display:
     - User-configured section shows 2 MCPs
     - Project-configured section shows 1 MCP
     - Local-configured section shows 1 MCP (if displayed separately, or in user)
     - Plugin-provided section shows 3 plugin groups with correct @version
  8. Update one plugin (e.g., Context7 1.2.0 -> 1.3.0)
  9. Run /sync-status (without /sync)
  10. Verify Plugin Drift section shows Context7 version change
  11. Run /sync to update state
  12. Run /sync-status again
  13. Verify Plugin Drift section clears
- **Why deferred:** Requires complete Phase 9-11 implementation, real environment setup, multiple plugins
- **Validates at:** Phase 11 integration tests (verify_phase11_integration.py + manual testing)
- **Depends on:**
  - Phase 9 complete (scoped MCP discovery with plugin support)
  - Phase 10 complete (scope-aware routing to targets)
  - Phase 11 complete (plugin tracking and display)
  - Real Claude Code with multiple plugins installed
  - Real Codex and Gemini CLIs
- **Target:**
  - 100% discovery rate: 8/8 MCPs discovered
  - 100% scope routing: all MCPs in correct target configs
  - 100% plugin tracking: 3 plugins in state.json with correct metadata
  - 100% display accuracy: /sync-status shows 4 source groups correctly
  - 100% drift detection: plugin update detected before re-sync, cleared after
  - 0% false positives: no drift when no changes occurred
  - 0% scope collapse: project MCPs not in user configs, plugin MCPs not in project configs
- **Risk if unmet:**
  - v2.0 feature set incomplete — users can't use plugin-aware sync
  - Scope routing broken — per-project MCP overrides don't work
  - Plugin drift undetected — users don't know when to re-sync after updates
  - Display grouping wrong — users can't distinguish plugin MCPs from user configs
- **Fallback:**
  - Fall back to v1.0 flat MCP sync (no scope separation)
  - Skip plugin drift detection (manual version tracking)
  - Basic /sync-status without grouping

## Ablation Plan

**No ablation plan applicable** — This phase implements state extension and display enhancement with a single design approach.

**Rationale:** Ablation is meaningful when comparing alternative algorithmic strategies (e.g., incremental state updates vs full replacement, version string comparison vs semantic versioning). Phase 11 uses the patterns specified in 11-RESEARCH.md (replacement semantics for stale cleanup, string comparison for drift detection, metadata-based grouping for display). There are no alternative implementations to compare.

## Baselines

| Baseline | Description | Current Behavior | Phase 11 Target | Source |
|----------|-------------|------------------|----------------|--------|
| v1.0 State tracking | Tracks file hashes only | No plugin version tracking | Plugin versions and MCP counts tracked | STATE-01 requirement |
| v1.0 Drift detection | File hash comparison | Doesn't detect plugin updates | Detects version/count changes | STATE-03 requirement |
| v1.0 /sync-status | Shows per-target status | All MCPs in flat list | Grouped by source (user/project/plugin) | STATE-02 requirement |
| v1.0 Plugin awareness | No plugin tracking | Plugin updates invisible | Plugin drift warnings displayed | 11-RESEARCH.md |

**Baseline comparison:**
- v1.0: 0% plugin tracking, 0% plugin drift detection, 0% MCP source grouping
- v2.0 Phase 11 target: 100% plugin tracking, 100% drift detection, 100% source grouping

## Evaluation Scripts

**Location of evaluation code:**
```
.planning/phases/11-state-enhancements-integration/11-01-PLAN.md (StateManager plugin methods)
.planning/phases/11-state-enhancements-integration/11-02-PLAN.md (/sync-status enhancements)
src/state_manager.py (Phase 11-01 output: record_plugin_sync, detect_plugin_drift, get_plugin_status)
src/orchestrator.py (Phase 11-01 output: _extract_plugin_metadata)
src/commands/sync_status.py (Phase 11-02 output: grouping and drift display)
verify_phase11_integration.py (Phase 11-02 output: full integration test)
```

**How to run full proxy evaluation:**
```bash
# Sanity checks (S1-S7)
python3 -c "from src.state_manager import StateManager; print('S1: OK')"
python3 -c "from src.orchestrator import SyncOrchestrator; print('S2: OK')"
python3 -c "from src.commands.sync_status import _group_mcps_by_source; print('S3: OK')"
# ... (Run individual S4-S7 commands from sanity check definitions)

# Proxy metrics (P1-P8)
# Run each P1-P8 command from proxy metric definitions above

# Integration test (Phase 11-02)
python3 verify_phase11_integration.py
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: StateManager plugin methods | PASS/FAIL | | |
| S2: Orchestrator integration | PASS/FAIL | | |
| S3: Sync-status helpers | PASS/FAIL | | |
| S4: Plugin metadata schema | PASS/FAIL | | |
| S5: State.json format | PASS/FAIL | | |
| S6: MCP source pattern matching | PASS/FAIL | | |
| S7: Drift comparison logic | PASS/FAIL | | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: Plugin record/retrieve (flat) | 100% persistence | | MET/MISSED | |
| P2: Plugin record (account-scoped) | 100% isolation | | MET/MISSED | |
| P3: Version drift detection | 100% version changes | | MET/MISSED | |
| P4: MCP count drift detection | 100% count changes | | MET/MISSED | |
| P5: Plugin add/remove detection | 100% lifecycle tracking | | MET/MISSED | |
| P6: Stale plugin cleanup | 0 stale plugins | | MET/MISSED | |
| P7: MCP source grouping | 100% grouping accuracy | | MET/MISSED | |
| P8: Display formatting | 100% format compliance | | MET/MISSED | |

### Ablation Results

N/A — No ablation plan for this phase (single implementation approach)

### Deferred Status

| ID | Metric | Status | Validates At | Risk |
|----|--------|--------|-------------|------|
| DEFER-11-01 | Real plugin update detection | PENDING | Phase 11 completion | False positives, undetected updates |
| DEFER-11-02 | Multi-account plugin isolation | PENDING | Phase 11 production | Cross-account contamination |
| DEFER-11-03 | Full v2.0 pipeline integration | PENDING | Phase 11 integration | Scope collapse, incomplete features |

## Evaluation Confidence

**Overall confidence in evaluation design:** HIGH

**Justification:**

- **Sanity checks:** ADEQUATE — 7 checks cover all new methods (StateManager, orchestrator, sync-status), schema validation, pattern matching, and drift comparison logic. Complete coverage of implementation surface area.
- **Proxy metrics:** WELL-EVIDENCED — 8 comprehensive tests trace directly to requirements (STATE-01, STATE-02, STATE-03) and research recommendations (11-RESEARCH.md patterns). Each metric tests a specific success criterion (persistence, drift detection, grouping, formatting).
- **Deferred coverage:** COMPREHENSIVE — Three critical integration risks: real plugin updates (D1), multi-account isolation (D2), full v2.0 pipeline (D3). All success criteria ultimately validated in deferred tests.

**What this evaluation CAN tell us:**

- Plugin metadata persistence works (record, retrieve, account-scoped)
- Plugin drift detection logic correctly identifies version changes, count changes, add/remove
- Stale plugin cleanup prevents unbounded state growth (replacement semantics)
- MCP source grouping accurately categorizes user/project/local/plugin MCPs
- Display formatting produces correct output structure (sections, plugin@version, drift warnings)
- State.json schema extension preserves existing structure (no breaking changes)
- Account-scoped plugin tracking correctly nests under accounts section

**What this evaluation CANNOT tell us:**

- Real plugin updates in live Claude Code trigger drift detection — validates at DEFER-11-01
- Production multi-account setups maintain plugin isolation — validates at DEFER-11-02
- Full v2.0 pipeline (9+10+11) works end-to-end with real plugins and configs — validates at DEFER-11-03
- /sync-status terminal display is readable and user-friendly — assumes formatting tests proxy for UX
- State file size growth with many plugin install/uninstall cycles — assumes replacement semantics sufficient
- Performance with 50+ plugins and 250+ MCPs — assumes O(P) drift detection acceptable
- Edge cases: malformed plugin metadata, concurrent state access, state file corruption recovery — scope for future testing

## Proxy Metric Caveats

The proxy metrics P1-P8 use in-memory state and mock fixtures rather than real plugin installations. This enables independent Phase 11 evaluation but introduces blind spots:

1. **State persistence reliability** — Tests use tempfile, not production state directory with permissions/locks
2. **Plugin metadata extraction** — Simulates orchestrator logic but doesn't test real SourceReader output from Phase 9
3. **Display integration** — Tests helper functions but not actual /sync-status command flow
4. **Plugin lifecycle edge cases** — Doesn't test crashed plugins, incomplete metadata, or corrupted state recovery

**Mitigation strategy:** Deferred validations (D1-D3) bridge these gaps with real installations, live commands, and production scenarios. Phase 11 is not production-ready until all deferred validations pass.

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-02-15*
*Phase 11 context: 2 plans (11-01: StateManager plugin tracking, 11-02: /sync-status enhancements + integration test)*
*Requirements: STATE-01 (plugin tracking schema), STATE-02 (MCP source grouping), STATE-03 (plugin drift detection)*
