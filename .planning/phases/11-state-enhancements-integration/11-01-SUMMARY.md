# Phase 11 Plan 01: Plugin Tracking & Drift Detection Summary

**One-liner:** StateManager now tracks plugin metadata (version, MCP count) and detects drift, with orchestrator automatically persisting plugin data after each sync.

---

## Plan Metadata

```yaml
phase: 11-state-enhancements-integration
plan: 01
subsystem: state-management
type: execute
wave: 1
autonomous: true
verification_level: proxy
```

---

## What Was Built

Extended StateManager with plugin version tracking and drift detection capabilities, integrated into the sync orchestrator to automatically persist plugin metadata after successful syncs.

### Key Components

1. **StateManager Plugin Tracking Methods** (`src/state_manager.py`)
   - `record_plugin_sync()`: Persists plugin metadata to state.json
   - `detect_plugin_drift()`: Detects version changes, MCP count changes, additions, removals
   - `get_plugin_status()`: Returns stored plugin data
   - Supports both flat and account-scoped plugin tracking
   - Replacement semantics prevent stale plugin accumulation

2. **Orchestrator Plugin Metadata Integration** (`src/orchestrator.py`)
   - `_extract_plugin_metadata()`: Extracts plugin info from mcp_scoped data
   - Filters to plugin-sourced MCPs (source=='plugin')
   - Groups by plugin_name with version, mcp_count, mcp_servers list
   - `_update_state()`: Calls record_plugin_sync() after successful target syncs
   - Optimization: passes source_data to avoid double discover_all() call

---

## Dependencies

### Requires
- `src/state_manager.py` (existing atomic write infrastructure)
- `src/orchestrator.py` (existing sync coordination)
- `src/source_reader.py` (provides mcp_servers_scoped with plugin metadata)

### Provides
- Plugin tracking schema in state.json (STATE-01)
- Plugin drift detection API (STATE-03)
- Automatic plugin metadata persistence after sync

### Affects
- state.json schema (adds "plugins" section at root or per-account)
- SyncOrchestrator._update_state() signature (added source_data parameter)

---

## Tech Stack

### Added
- None (stdlib only - uses datetime for timestamps)

### Patterns
- **Replacement semantics**: record_plugin_sync() replaces entire plugins section to avoid stale accumulation
- **Account-scoped nesting**: Follows existing pattern from record_sync() for multi-account support
- **Drift detection**: Compares stored vs current plugin metadata with prioritized drift reasons
- **Decoupled design**: detect_plugin_drift() accepts current_plugins dict (caller provides data, no SourceReader coupling)

---

## Key Files

### Created
None (extended existing files)

### Modified
- `src/state_manager.py` (+101 lines): Plugin tracking methods
- `src/orchestrator.py` (+54 lines, -3 lines): Plugin metadata extraction and persistence

---

## Verification Results

**Level 2 (Proxy): 9/9 checks PASSED**

### StateManager Tests (7 checks)
- ✅ record_plugin_sync (flat): Persists to state.json["plugins"]
- ✅ record_plugin_sync (account-scoped): Persists to state.json["accounts"][account]["plugins"]
- ✅ detect_plugin_drift - version change: Detects version_changed with old -> new
- ✅ detect_plugin_drift - mcp count change: Detects mcp_count_changed with old -> new
- ✅ detect_plugin_drift - added/removed: Detects "added" and "removed" plugins
- ✅ get_plugin_status: Returns stored plugin data
- ✅ Replacement semantics: Clears stale plugins on each record_plugin_sync() call

### Orchestrator Tests (2 checks)
- ✅ _extract_plugin_metadata filters correctly: Excludes file-based MCPs, includes only plugin-sourced
- ✅ _extract_plugin_metadata groups by plugin_name: Aggregates MCP count and servers per plugin

---

## Decisions Made

1. **Replacement vs Merge**: record_plugin_sync() REPLACES entire plugins section rather than merging
   - Rationale: Prevents stale accumulation from uninstalled plugins (per 11-RESEARCH.md Pitfall 2)
   - Trade-off: Requires full plugin metadata on each call (not incremental)

2. **Drift Priority**: Version changes take priority over MCP count changes when both occur
   - Rationale: Version changes are more significant and often cause MCP count changes
   - Implementation: detect_plugin_drift() reports version_changed if both changed

3. **Decoupled Drift Detection**: detect_plugin_drift() accepts current_plugins dict instead of calling SourceReader
   - Rationale: Keeps StateManager decoupled from SourceReader (single responsibility)
   - Trade-off: Caller must provide current plugin data

4. **Optimized source_data Flow**: _update_state() accepts optional source_data parameter
   - Rationale: Avoids double discover_all() call in sync_all() (performance)
   - Fallback: If not provided, calls reader.discover_all() for backward compatibility

---

## Deviations from Plan

None - plan executed exactly as written.

---

## Self-Check

### Files Created/Modified
```bash
✅ FOUND: src/state_manager.py (modified with plugin tracking methods)
✅ FOUND: src/orchestrator.py (modified with plugin metadata extraction)
```

### Commits
```bash
✅ FOUND: abe4a4a (feat(11-01): add plugin tracking methods to StateManager)
✅ FOUND: 0f7de5a (feat(11-01): integrate plugin metadata persistence into orchestrator)
```

### Verification
```bash
✅ PASSED: All 7 StateManager checks
✅ PASSED: All 2 Orchestrator checks
```

## Self-Check: PASSED

---

## Integration Points

### state.json Schema Extension
```json
{
  "version": 2,
  "plugins": {
    "context7": {
      "version": "1.2.0",
      "mcp_count": 2,
      "mcp_servers": ["context7-browse", "context7-query"],
      "last_sync": "2026-02-15T06:30:00Z"
    }
  },
  "accounts": {
    "work": {
      "plugins": {
        "grd": {
          "version": "0.3.1",
          "mcp_count": 1,
          "mcp_servers": ["grd-research"],
          "last_sync": "2026-02-15T06:30:00Z"
        }
      }
    }
  }
}
```

### Orchestrator Flow
```
sync_all()
  → reader.discover_all() → source_data with mcp_servers_scoped
  → adapter.sync_all() for each target
  → _update_state(results, reader, source_data)
    → _extract_plugin_metadata(mcp_scoped) → filters source=='plugin'
    → state_manager.record_plugin_sync(plugins_metadata, account)
```

### Drift Detection API
```python
# Get current plugin state from SourceReader
source_data = reader.discover_all()
mcp_scoped = source_data.get('mcp_servers_scoped', {})
current_plugins = orchestrator._extract_plugin_metadata(mcp_scoped)

# Detect drift
drift = state_manager.detect_plugin_drift(current_plugins, account='work')
# Returns: {'context7': 'version_changed: 1.2.0 -> 1.3.0', 'old-plugin': 'removed'}
```

---

## Next Steps

Phase 11 Plan 02 will extend this foundation to:
- Add plugin drift detection to /sync-status command output
- Add drift warnings to sync orchestrator (warn before sync if plugins changed)
- Implement plugin re-discovery trigger (--refresh flag to force plugin metadata update)

---

## Metrics

- **Duration**: 106 seconds (~2 minutes)
- **Tasks completed**: 2/2
- **Files modified**: 2
- **Lines added**: 155
- **Lines removed**: 3
- **Verification checks**: 9/9 passed
- **Commits**: 2

---

**Completed**: 2026-02-15T06:30:40Z
**Phase**: 11-state-enhancements-integration
**Plan**: 01
**Status**: ✅ Complete
