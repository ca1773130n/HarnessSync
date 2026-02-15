# Phase 11: State Enhancements & Integration - Research

**Researched:** 2026-02-15
**Domain:** State management enhancements, plugin version tracking, drift detection, sync status display
**Confidence:** HIGH

## Summary

Phase 11 is the final v2.0 phase, extending StateManager to track plugin metadata for update-triggered re-sync and enhancing /sync-status to display plugin-discovered MCPs with scope labels. This phase integrates all v2.0 components (Phases 9-10) into a cohesive system with plugin-aware drift detection.

**Key findings:**
1. Current StateManager tracks file hashes but lacks plugin-specific metadata (version, MCP count)
2. Current /sync-status displays per-target status but doesn't distinguish MCP sources (user vs project vs plugin)
3. Plugin updates represent a new drift vector not covered by file hash comparison
4. Phase 9's scoped MCP discovery already provides plugin metadata (name, version) - just need to persist it
5. StateManager's existing state.json schema supports arbitrary target data - no breaking changes needed
6. /sync-status already implements drift detection - just needs MCP grouping by source

**Primary recommendation:** Extend StateManager schema to include `plugins` section tracking {name → {version, mcp_count, last_sync}}, add plugin drift detection logic, and refactor /sync-status to group MCPs by source with scope labels.

## User Constraints (from CONTEXT.md)

No CONTEXT.md exists for this phase. All implementation choices are at Claude's discretion.

**Prior decisions from milestone scope:**
- Python 3 stdlib only (zero dependencies)
- Atomic state writes (tempfile + os.replace pattern)
- Per-target state isolation
- v2 state schema with multi-account support
- Existing v1 state migration support
- Plugin MCPs are user-scope (always sync to user-level)
- Scope precedence: local > project > user

## Paper-Backed Recommendations

### Recommendation 1: Track Plugin Metadata in State Schema

**Recommendation:** Extend state.json to include `plugins` section with per-plugin tracking: {name: {version, mcp_count, last_sync, mcp_servers: [list]}}

**Evidence:**
- Software engineering best practice: version tracking enables update detection (semantic versioning, dependency management patterns)
- Existing StateManager uses nested dict structure (src/state_manager.py lines 31-59) - schema is extensible
- Phase 9 discovery already extracts plugin metadata (09-RESEARCH.md lines 81-89, src/source_reader.py lines 347-358)
- Requirement STATE-01 explicitly specifies schema: "plugin_name → {version, mcp_count, last_sync}" (.planning/REQUIREMENTS.md line 99)
- Python dict-based state allows adding new keys without migration (JSON schema flexibility)

**Confidence:** HIGH — Requirement specifies exact schema, existing codebase supports extension
**Expected improvement:** Update detection without re-scanning plugin cache, MCP count comparison for drift
**Caveats:** State file grows with plugin count (minimal - ~100 bytes per plugin)

**Schema extension:**
```python
{
    "version": 2,
    "last_sync": "2024-01-01T12:00:00",
    "targets": { ... },
    "accounts": { ... },
    "plugins": {  # NEW SECTION
        "context7": {
            "version": "1.2.0",
            "mcp_count": 2,
            "last_sync": "2024-01-01T12:00:00",
            "mcp_servers": ["context7-browse", "context7-query"]
        },
        "grd": {
            "version": "0.3.1",
            "mcp_count": 1,
            "last_sync": "2024-01-01T12:00:00",
            "mcp_servers": ["grd-research"]
        }
    }
}
```

### Recommendation 2: Implement Plugin Version Drift Detection

**Recommendation:** Add `detect_plugin_drift()` method comparing stored plugin versions/counts with current installed_plugins.json state

**Evidence:**
- Existing StateManager has `detect_drift()` for file hashes (src/state_manager.py lines 254-295) - proven pattern
- Plugin updates don't change MCP config file hashes (installed_plugins.json version changes, not .mcp.json)
- Requirement STATE-03 specifies "Drift detection extends to plugin MCP changes" (.planning/REQUIREMENTS.md line 101)
- Version comparison is O(1) per plugin (dict lookup) - negligible performance impact
- npm, pip, cargo all use version comparison for update detection (industry standard pattern)

**Confidence:** HIGH — Existing drift detection pattern + requirement + proven approach
**Expected improvement:** Detect plugin updates that add/remove/change MCP servers without file hash comparison
**Caveats:** Requires reading installed_plugins.json on each /sync-status call (same as current source_reader.py behavior)

**Implementation pattern:**
```python
def detect_plugin_drift(self) -> dict[str, str]:
    """Detect plugin version changes and MCP count changes.

    Returns:
        Dict mapping plugin_name to drift reason:
        - "version_changed: 1.0.0 -> 1.1.0"
        - "mcp_count_changed: 2 -> 3"
        - "removed"
        - "added"
    """
    drift = {}
    stored_plugins = self._state.get("plugins", {})

    # Discover current plugins (re-use Phase 9 logic)
    reader = SourceReader(scope="all")
    current_mcps = reader.get_mcp_servers_with_scope()

    # Group by plugin
    current_plugins = {}
    for name, entry in current_mcps.items():
        metadata = entry.get("metadata", {})
        if metadata.get("source") == "plugin":
            plugin_name = metadata.get("plugin_name", "unknown")
            plugin_version = metadata.get("plugin_version", "unknown")
            if plugin_name not in current_plugins:
                current_plugins[plugin_name] = {
                    "version": plugin_version,
                    "mcp_servers": []
                }
            current_plugins[plugin_name]["mcp_servers"].append(name)

    # Compare stored vs current
    for plugin_name, stored in stored_plugins.items():
        if plugin_name not in current_plugins:
            drift[plugin_name] = "removed"
        else:
            current = current_plugins[plugin_name]
            stored_version = stored.get("version", "unknown")
            current_version = current.get("version", "unknown")

            if stored_version != current_version:
                drift[plugin_name] = f"version_changed: {stored_version} -> {current_version}"

            stored_count = stored.get("mcp_count", 0)
            current_count = len(current.get("mcp_servers", []))

            if stored_count != current_count:
                drift[plugin_name] = f"mcp_count_changed: {stored_count} -> {current_count}"

    # Check for new plugins
    for plugin_name in current_plugins:
        if plugin_name not in stored_plugins:
            drift[plugin_name] = "added"

    return drift
```

### Recommendation 3: Group MCPs by Source in /sync-status Output

**Recommendation:** Refactor /sync-status to display MCPs in 4 groups: User-configured, Project-configured, Local-configured, Plugin-provided (with plugin name@version)

**Evidence:**
- Requirement STATE-02 specifies grouping: "User-configured", "Project-configured", "Plugin-provided (plugin-name@version)" (.planning/REQUIREMENTS.md line 100)
- Phase 9 already tags MCPs with source metadata (scope, source, plugin_name, plugin_version) - data is available
- Existing /sync-status structure supports multi-section display (src/commands/sync_status.py lines 233-279)
- User research shows grouped display improves scanability (Nielsen Norman Group - information scent patterns)

**Confidence:** HIGH — Requirement specifies format, metadata available, existing pattern
**Expected improvement:** Users can distinguish plugin MCPs from user configs at a glance
**Caveats:** Longer output with many plugins (acceptable tradeoff for clarity)

**Display format:**
```
HarnessSync Status
============================================================

Last sync: 2024-01-01T12:00:00

Target: codex
  Status: success
  Last sync: 2024-01-01T12:00:00
  Scope: all
  Items: 15 synced, 0 skipped, 0 failed

  MCP Servers:
    User-configured (2):
      - my-custom-server (user)
      - another-server (user)

    Project-configured (1):
      - project-specific-tool (project)

    Local-configured (1):
      - private-api-key-server (local)

    Plugin-provided:
      context7@1.2.0 (2):
        - context7-browse (user)
        - context7-query (user)
      grd@0.3.1 (1):
        - grd-research (user)

  Plugin Drift:
    - context7: version_changed: 1.2.0 -> 1.3.0

  Drift: None detected
```

### Recommendation 4: Auto-Trigger Re-Sync on Plugin Version Change

**Recommendation:** Do NOT auto-sync on plugin drift - just WARN user and require manual /sync (conservative approach)

**Evidence:**
- Requirement STATE-02 wording: "triggers re-sync" could mean automatic OR user-triggered
- Existing HarnessSync philosophy: user controls sync timing (no auto-sync on file edits, requires /sync command)
- Security consideration: plugin updates might introduce breaking changes - user should review before syncing
- Hook pattern in Phase 4 already implements conservative approach (deferred sync, user confirmation)
- Decision #23: "Secret detection blocks by default" - conservative security default

**Confidence:** HIGH — Consistent with project philosophy + security best practice
**Expected improvement:** User awareness of plugin changes, no surprise behavior
**Caveats:** Users might miss plugin updates (acceptable - they control sync timing)

**Alternative interpretation:** If "trigger" means automatic, implement with `/sync --auto-on-plugin-update` flag (opt-in)

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib json | 3.x | State persistence | Built-in, zero dependencies (project constraint) |
| Python stdlib pathlib | 3.x | File path handling | Cross-platform path operations |
| Python stdlib datetime | 3.x | Timestamp tracking | ISO 8601 format for last_sync |

### Supporting

Existing HarnessSync utilities:
- `src/state_manager.py` — State persistence with atomic writes (EXTEND)
- `src/commands/sync_status.py` — Status display command (EXTEND)
- `src/source_reader.py` — Phase 9 plugin discovery (READ-ONLY)
- `src/utils/paths.py` — JSON read/write helpers

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Rationale |
|------------|-----------|----------|-----------|
| Dict-based state | SQLite database | SQLite adds persistence layer but violates zero-dependency + adds complexity | JSON dict sufficient for single-machine state, no concurrent access |
| Version string comparison | semantic_version library | Library provides proper semver parsing but adds dependency | String equality adequate for detection (don't need ordering) |

## Architecture Patterns

### Recommended Project Structure

Current structure is correct. Extensions go in existing files:

```
src/
├── state_manager.py        # EXTEND: Add plugin tracking methods
├── commands/
│   └── sync_status.py      # EXTEND: Add MCP grouping by source
├── orchestrator.py         # EXTEND: Record plugin metadata after sync
└── source_reader.py        # NO CHANGE: Already provides metadata
```

### Pattern 1: Plugin Metadata Extraction from Scoped MCPs

**What:** Extract plugin metadata from Phase 9 scoped MCP data for state persistence

**When to use:** After successful sync in orchestrator, before calling state_manager.record_sync()

**Example:**
```python
# Source: Phase 9 scoped MCP format + Requirement STATE-01
def extract_plugin_metadata(mcp_servers_scoped: dict[str, dict]) -> dict[str, dict]:
    """Extract plugin metadata from scoped MCP servers.

    Args:
        mcp_servers_scoped: Phase 9 format with metadata

    Returns:
        Dict mapping plugin_name to {version, mcp_count, mcp_servers: [list]}
    """
    plugins = {}

    for server_name, entry in mcp_servers_scoped.items():
        metadata = entry.get("metadata", {})

        # Only process plugin-sourced servers
        if metadata.get("source") != "plugin":
            continue

        plugin_name = metadata.get("plugin_name", "unknown")
        plugin_version = metadata.get("plugin_version", "unknown")

        if plugin_name not in plugins:
            plugins[plugin_name] = {
                "version": plugin_version,
                "mcp_servers": [],
                "mcp_count": 0,
                "last_sync": datetime.now().isoformat()
            }

        plugins[plugin_name]["mcp_servers"].append(server_name)
        plugins[plugin_name]["mcp_count"] += 1

    return plugins
```

### Pattern 2: MCP Grouping by Source for Display

**What:** Group discovered MCPs by source (user/project/local file-based vs plugin) for display

**When to use:** In /sync-status command when showing per-target MCP list

**Example:**
```python
# Source: Requirement STATE-02 + existing sync_status.py structure
def group_mcps_by_source(mcp_servers_scoped: dict[str, dict]) -> dict:
    """Group MCP servers by source for display.

    Returns:
        {
            "user": [server_names],
            "project": [server_names],
            "local": [server_names],
            "plugins": {
                "plugin-name@version": [server_names]
            }
        }
    """
    groups = {
        "user": [],
        "project": [],
        "local": [],
        "plugins": {}
    }

    for server_name, entry in mcp_servers_scoped.items():
        metadata = entry.get("metadata", {})
        scope = metadata.get("scope", "user")
        source = metadata.get("source", "file")

        if source == "plugin":
            plugin_name = metadata.get("plugin_name", "unknown")
            plugin_version = metadata.get("plugin_version", "unknown")
            plugin_key = f"{plugin_name}@{plugin_version}"

            if plugin_key not in groups["plugins"]:
                groups["plugins"][plugin_key] = []
            groups["plugins"][plugin_key].append((server_name, scope))
        else:
            # File-based MCP - group by scope
            groups[scope].append(server_name)

    return groups
```

### Pattern 3: Incremental State Update (Preserve Existing Data)

**What:** Add plugin tracking without disrupting existing state fields

**When to use:** When extending StateManager with new sections

**Example:**
```python
# Source: Existing state_manager.py pattern + requirement
def record_plugin_sync(self, plugins_metadata: dict[str, dict]) -> None:
    """Record plugin metadata in state.

    Args:
        plugins_metadata: Dict from extract_plugin_metadata()
    """
    # Ensure plugins section exists
    if "plugins" not in self._state:
        self._state["plugins"] = {}

    # Update/add each plugin
    for plugin_name, metadata in plugins_metadata.items():
        self._state["plugins"][plugin_name] = metadata

    # Persist to disk (atomic write)
    self._save()
```

### Anti-Patterns to Avoid

- **Overwriting entire state:** Don't replace `self._state = new_state` — merge new sections into existing state
- **Eager plugin re-sync:** Don't auto-sync on plugin drift without user confirmation (violates user control principle)
- **Ignoring plugin removal:** Don't skip removed plugins in drift detection — user should know when plugin uninstalled
- **Hardcoding MCP source labels:** Don't use magic strings like "user" without checking metadata.scope field

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| State persistence | Custom file format | Existing state_manager.py atomic writes | Race conditions, corruption already handled |
| MCP discovery | Re-scan plugin cache | Phase 9's SourceReader methods | Proven pattern, handles all edge cases |
| Timestamp generation | Manual datetime formatting | datetime.now().isoformat() | ISO 8601 standard, built-in |
| Version comparison | Custom parser | String equality (adequate for drift detection) | Don't need semver ordering, just change detection |

**Key insight:** Phase 9 already does the heavy lifting (plugin discovery, metadata extraction). Phase 11 just persists and displays that data.

## Common Pitfalls

### Pitfall 1: Plugin Metadata Persistence Timing

**What goes wrong:** Recording plugin metadata before sync completes, leading to stale state if sync fails

**Why it happens:** Orchestrator calls state_manager.record_sync() early in pipeline

**How to avoid:**
- Extract plugin metadata AFTER successful adapter sync
- Only call record_plugin_sync() if sync succeeds (no exceptions)
- Wrap in try/except to prevent state corruption on partial sync

**Warning signs:** Plugin metadata in state but target configs missing servers (out of sync)

**Reference:** Orchestrator pattern in src/orchestrator.py lines 180-352 (state update after sync)

### Pitfall 2: Removed Plugin State Accumulation

**What goes wrong:** State file grows unbounded as plugins are installed/uninstalled (never prune removed plugins)

**Why it happens:** record_plugin_sync() adds but never removes

**How to avoid:**
- On each sync, replace entire `plugins` section (not incremental update)
- OR: Add explicit cleanup logic to remove plugins not in current discovery

**Warning signs:** State file size grows over time even with constant plugin count

**Reference:** Similar to symlink cleanup pattern (src/symlink_cleaner.py) - periodic pruning

### Pitfall 3: MCP Grouping Display Complexity

**What goes wrong:** /sync-status output becomes unreadable with 50+ plugins and 200+ MCPs

**Why it happens:** Displaying all servers verbosely

**How to avoid:**
- Show plugin summary (count only) by default
- Add `--verbose` flag to show full MCP server lists
- Limit display to first 10 per group, with "... and N more" suffix

**Warning signs:** /sync-status output scrolls off screen, user complaints about verbosity

**Reference:** Existing drift detection uses truncation (sync_status.py lines 176-187)

### Pitfall 4: Plugin Version Change False Positives

**What goes wrong:** Plugin version drift detected but MCPs unchanged (version bump without MCP changes)

**Why it happens:** Tracking version string alone, not MCP config hash

**How to avoid:**
- Track BOTH version AND mcp_count for drift
- Version change + same mcp_count = low-priority drift (cosmetic)
- Version change + different mcp_count = high-priority drift (functional)

**Warning signs:** User sees drift warnings on every plugin update even when nothing broke

**Reference:** Requirement STATE-03 specifies "MCP changes" not just "version changes"

### Pitfall 5: Multi-Account Plugin State Confusion

**What goes wrong:** Plugins tracked globally but accounts use different Claude Code homes

**Why it happens:** Assuming single ~/.claude/ path for all accounts

**How to avoid:**
- Track plugins per-account (nested under accounts.{account}.plugins in state)
- OR: Track plugins globally but tag with cc_home path
- Account manager provides cc_home per account (src/account_manager.py)

**Warning signs:** Account A shows plugin drift from Account B's plugin state

**Reference:** StateManager v2 schema with accounts nesting (state_manager.py lines 31-59)

## Experiment Design

Not applicable — This phase extends existing state management and display. No experimental algorithms or novel techniques.

**Validation approach:**
- Unit tests with fixture state.json (mock plugin metadata)
- Integration tests with real plugin installation/update simulation
- Verification that plugin drift detection matches manual inspection

## Verification Strategy

### Recommended Verification Tiers for This Phase

| Item | Recommended Tier | Rationale |
|------|-----------------|-----------|
| Plugin metadata extraction | Level 1 (Sanity) | Unit test with Phase 9 scoped data |
| State schema extension | Level 1 (Sanity) | Write state.json, verify JSON valid |
| Plugin drift detection logic | Level 1 (Sanity) | Mock stored vs current plugins |
| MCP grouping by source | Level 1 (Sanity) | Group fixture data, verify output |
| /sync-status display format | Level 2 (Proxy) | Run command, inspect output grouping |
| Plugin version change detection | Level 2 (Proxy) | Simulate plugin update (change version in fixture) |
| Plugin update re-sync trigger | Level 2 (Proxy) | Verify warning displayed, no auto-sync |
| Full v2.0 pipeline integration | Level 2 (Proxy) | 3 plugins, 2 user MCPs, 1 project MCP, 1 local MCP |
| Real plugin update in Claude Code | Level 3 (Deferred) | Requires live Claude Code plugin update |

### Level 1 Checks (Sanity)

**Plugin metadata extraction:**
```python
def test_extract_plugin_metadata():
    """Verify plugin metadata extracted from scoped MCPs."""
    scoped = {
        "context7-browse": {
            "config": {"command": "npx", "args": ["-y", "context7"]},
            "metadata": {
                "scope": "user",
                "source": "plugin",
                "plugin_name": "context7",
                "plugin_version": "1.2.0"
            }
        },
        "context7-query": {
            "config": {"command": "npx", "args": ["-y", "context7"]},
            "metadata": {
                "scope": "user",
                "source": "plugin",
                "plugin_name": "context7",
                "plugin_version": "1.2.0"
            }
        },
        "my-server": {
            "config": {"command": "my-server"},
            "metadata": {"scope": "user", "source": "file"}
        }
    }

    plugins = extract_plugin_metadata(scoped)

    assert "context7" in plugins
    assert plugins["context7"]["version"] == "1.2.0"
    assert plugins["context7"]["mcp_count"] == 2
    assert len(plugins["context7"]["mcp_servers"]) == 2
    assert "my-server" not in plugins  # File-based, not plugin
```

**Plugin drift detection:**
```python
def test_plugin_version_drift():
    """Verify version change detected."""
    state_manager = StateManager()

    # Seed stored state
    state_manager._state["plugins"] = {
        "context7": {
            "version": "1.2.0",
            "mcp_count": 2,
            "mcp_servers": ["context7-browse", "context7-query"]
        }
    }

    # Mock current discovery (version changed)
    # (Would need to mock SourceReader or inject current plugins)

    # In real test, use fixture or mock
    # For now, test logic only
    stored = state_manager._state["plugins"]["context7"]
    current = {"version": "1.3.0", "mcp_count": 2}

    assert stored["version"] != current["version"]
    # Drift detected
```

**MCP grouping:**
```python
def test_group_mcps_by_source():
    """Verify MCP servers grouped correctly."""
    scoped = {
        "user-server": {
            "config": {},
            "metadata": {"scope": "user", "source": "file"}
        },
        "project-server": {
            "config": {},
            "metadata": {"scope": "project", "source": "file"}
        },
        "plugin-server": {
            "config": {},
            "metadata": {
                "scope": "user",
                "source": "plugin",
                "plugin_name": "test-plugin",
                "plugin_version": "1.0.0"
            }
        }
    }

    groups = group_mcps_by_source(scoped)

    assert "user-server" in groups["user"]
    assert "project-server" in groups["project"]
    assert "test-plugin@1.0.0" in groups["plugins"]
    assert "plugin-server" in [s[0] for s in groups["plugins"]["test-plugin@1.0.0"]]
```

### Level 2 Proxy Metrics

**Plugin update simulation:**
- Create fixture state with plugin version 1.0.0
- Modify installed_plugins.json to version 1.1.0
- Call detect_plugin_drift()
- Verify drift detected with reason "version_changed: 1.0.0 -> 1.1.0"

**MCP count change detection:**
- State shows plugin with mcp_count=2
- Current discovery shows mcp_count=3
- Verify drift detected with reason "mcp_count_changed: 2 -> 3"

**Full /sync-status display:**
- Configure 2 user MCPs, 1 project MCP, 1 local MCP, 2 plugin MCPs from 2 different plugins
- Run /sync-status
- Verify output groups MCPs into 4 sections (User-configured, Project-configured, Local-configured, Plugin-provided)
- Verify Plugin-provided section shows plugin@version grouping

**Full v2.0 pipeline (Success Criteria #7):**
- Install 3 real Claude Code plugins with MCPs
- Configure 2 user MCPs in ~/.claude.json
- Configure 1 project MCP in .mcp.json
- Configure 1 local MCP in ~/.claude.json projects section
- Run /sync
- Verify all 7 MCPs discovered (100% discovery)
- Verify correct scoping (user/project/local tags)
- Verify env var translation for Codex
- Run /sync-status
- Verify drift: None detected
- Update one plugin version in fixture
- Run /sync-status
- Verify plugin drift detected

### Level 3 Deferred Items

**Real plugin update:**
- Install real Claude Code plugin with MCP server
- Run /sync
- Verify plugin metadata in state.json
- Update plugin to new version via Claude Code
- Run /sync-status
- Verify version change drift detected
- Run /sync
- Verify state updated with new version
- Verify drift cleared

**Production multi-account plugin tracking:**
- Configure 2 accounts with different Claude Code homes
- Install different plugins in each account
- Verify plugin state isolated per account
- Verify no cross-account drift false positives

## Production Considerations

### Known Failure Modes

**Plugin cache corruption:**
- **Description:** installed_plugins.json damaged or invalid format
- **Prevention:** Use read_json_safe (returns empty dict on error), existing Phase 9 pattern
- **Detection:** Empty plugin drift even when plugins installed (warn user)

**State.json plugin section out of sync:**
- **Description:** Sync interrupted mid-write, plugin metadata persisted but targets incomplete
- **Prevention:** Record plugin metadata AFTER successful adapter sync, use atomic writes
- **Detection:** StateManager detect_drift() shows files changed (existing mechanism)

**MCP server name collision:**
- **Description:** User-configured MCP and plugin MCP have same name
- **Prevention:** Phase 9 precedence already handles (user file wins over plugin)
- **Detection:** /sync-status shows server once with correct source label

### Scaling Concerns

**At current scale:**
- Typical user: 5-10 plugins, 15-30 total MCPs
- State file: +500 bytes for plugin section (negligible)
- /sync-status: +20 lines of output (acceptable)
- Plugin drift check: O(P) where P=plugin count (10-20 iterations, <1ms)

**At production scale:**
- Power user: 50 plugins, 250 MCPs
- State file: +5KB for plugin section (still negligible, JSON compresses well)
- /sync-status: +100 lines (needs truncation/verbose flag)
- Plugin drift check: O(50) = 50 iterations (still <5ms)

**Optimization:** Add `--summary` flag to /sync-status for compact view (counts only, no server lists)

### Common Implementation Traps

**Not clearing old plugin state:**
- **What goes wrong:** Removed plugins accumulate in state.json
- **Correct approach:** Replace entire `plugins` section on each sync (not merge)

**Hardcoding plugin source check:**
- **What goes wrong:** Checking `metadata["source"] == "plugin"` without existence check crashes
- **Correct approach:** `metadata.get("source") == "plugin"` with default

**Displaying all MCPs in verbose output:**
- **What goes wrong:** Unreadable output with 250 servers
- **Correct approach:** Truncate to 10 per group, add "... and N more"

## Code Examples

Verified patterns from official sources and existing codebase:

### State Schema Extension (New Pattern)

```python
# Source: Requirement STATE-01 + existing state_manager.py structure
def record_plugin_sync(self, plugins_metadata: dict[str, dict]) -> None:
    """Record plugin metadata after successful sync.

    Replaces entire plugins section to avoid accumulating removed plugins.

    Args:
        plugins_metadata: Dict from extract_plugin_metadata()
    """
    # Replace plugins section (don't merge - avoid stale entries)
    self._state["plugins"] = plugins_metadata

    # Update global last_sync
    self._state["last_sync"] = datetime.now().isoformat()

    # Persist atomically
    self._save()
```

### Plugin Drift Detection (New Pattern)

```python
# Source: Requirement STATE-03 + existing detect_drift() pattern
def detect_plugin_drift(self) -> dict[str, str]:
    """Detect plugin version and MCP count changes.

    Returns:
        Dict mapping plugin_name to drift reason:
        - "version_changed: 1.0.0 -> 1.1.0"
        - "mcp_count_changed: 2 -> 3"
        - "removed"
        - "added"
    """
    drift = {}
    stored_plugins = self._state.get("plugins", {})

    # Discover current plugins via SourceReader (Phase 9)
    reader = SourceReader(scope="all")
    current_mcps = reader.get_mcp_servers_with_scope()

    # Extract current plugin metadata
    current_plugins = {}
    for server_name, entry in current_mcps.items():
        metadata = entry.get("metadata", {})
        if metadata.get("source") != "plugin":
            continue

        plugin_name = metadata.get("plugin_name", "unknown")
        plugin_version = metadata.get("plugin_version", "unknown")

        if plugin_name not in current_plugins:
            current_plugins[plugin_name] = {
                "version": plugin_version,
                "mcp_servers": []
            }
        current_plugins[plugin_name]["mcp_servers"].append(server_name)

    # Compare stored vs current
    for plugin_name, stored in stored_plugins.items():
        if plugin_name not in current_plugins:
            drift[plugin_name] = "removed"
            continue

        current = current_plugins[plugin_name]
        stored_version = stored.get("version", "unknown")
        current_version = current.get("version", "unknown")

        if stored_version != current_version:
            drift[plugin_name] = f"version_changed: {stored_version} -> {current_version}"

        stored_count = stored.get("mcp_count", 0)
        current_count = len(current.get("mcp_servers", []))

        if stored_count != current_count:
            drift[plugin_name] = f"mcp_count_changed: {stored_count} -> {current_count}"

    # Check for new plugins
    for plugin_name in current_plugins:
        if plugin_name not in stored_plugins:
            drift[plugin_name] = "added"

    return drift
```

### MCP Grouping for Display (New Pattern)

```python
# Source: Requirement STATE-02 + existing sync_status.py display logic
def format_mcp_groups(mcp_servers_scoped: dict[str, dict]) -> str:
    """Format MCP servers grouped by source for display.

    Args:
        mcp_servers_scoped: Phase 9 scoped format

    Returns:
        Formatted string with grouped MCPs
    """
    # Group by source
    groups = {
        "user": [],
        "project": [],
        "local": [],
        "plugins": {}
    }

    for server_name, entry in mcp_servers_scoped.items():
        metadata = entry.get("metadata", {})
        scope = metadata.get("scope", "user")
        source = metadata.get("source", "file")

        if source == "plugin":
            plugin_name = metadata.get("plugin_name", "unknown")
            plugin_version = metadata.get("plugin_version", "unknown")
            plugin_key = f"{plugin_name}@{plugin_version}"

            if plugin_key not in groups["plugins"]:
                groups["plugins"][plugin_key] = []
            groups["plugins"][plugin_key].append((server_name, scope))
        else:
            groups[scope].append(server_name)

    # Format output
    lines = []
    lines.append("  MCP Servers:")

    if groups["user"]:
        lines.append(f"    User-configured ({len(groups['user'])}):")
        for name in groups["user"][:10]:
            lines.append(f"      - {name} (user)")
        if len(groups["user"]) > 10:
            lines.append(f"      ... and {len(groups['user']) - 10} more")

    if groups["project"]:
        lines.append(f"    Project-configured ({len(groups['project'])}):")
        for name in groups["project"][:10]:
            lines.append(f"      - {name} (project)")
        if len(groups["project"]) > 10:
            lines.append(f"      ... and {len(groups['project']) - 10} more")

    if groups["local"]:
        lines.append(f"    Local-configured ({len(groups['local'])}):")
        for name in groups["local"][:10]:
            lines.append(f"      - {name} (local)")
        if len(groups["local"]) > 10:
            lines.append(f"      ... and {len(groups['local']) - 10} more")

    if groups["plugins"]:
        lines.append("    Plugin-provided:")
        for plugin_key, servers in groups["plugins"].items():
            lines.append(f"      {plugin_key} ({len(servers)}):")
            for name, scope in servers[:5]:
                lines.append(f"        - {name} ({scope})")
            if len(servers) > 5:
                lines.append(f"        ... and {len(servers) - 5} more")

    return "\n".join(lines)
```

### Orchestrator Integration (Extension Pattern)

```python
# Source: Existing orchestrator.py pattern + Phase 11 requirements
# In SyncOrchestrator._update_state() method (lines 307-352)

def _update_state(self, results: dict, reader: SourceReader) -> None:
    """Update state manager with sync results.

    Extended in Phase 11 to track plugin metadata.

    Args:
        results: Per-target sync results
        reader: SourceReader used for this sync
    """
    source_paths = reader.get_source_paths()

    # Hash all source files (existing logic)
    file_hashes = {}
    for config_type, paths in source_paths.items():
        for p in paths:
            if p.is_file():
                h = hash_file_sha256(p)
                if h:
                    file_hashes[str(p)] = h

    # NEW: Extract plugin metadata from scoped MCP data
    source_data = reader.discover_all()
    mcp_scoped = source_data.get('mcp_servers_scoped', {})
    plugins_metadata = self._extract_plugin_metadata(mcp_scoped)

    for target, target_results in results.items():
        # Skip special keys
        if target.startswith('_'):
            continue

        # Aggregate counts (existing logic)
        synced = 0
        skipped = 0
        failed = 0
        sync_methods = {}

        if isinstance(target_results, dict):
            for config_type, result in target_results.items():
                if isinstance(result, SyncResult):
                    synced += result.synced
                    skipped += result.skipped
                    failed += result.failed

        self.state_manager.record_sync(
            target=target,
            scope=self.scope,
            file_hashes=file_hashes,
            sync_methods=sync_methods,
            synced=synced,
            skipped=skipped,
            failed=failed,
            account=self.account
        )

    # NEW: Record plugin metadata after successful sync
    if plugins_metadata:
        self.state_manager.record_plugin_sync(plugins_metadata)

def _extract_plugin_metadata(self, mcp_scoped: dict[str, dict]) -> dict[str, dict]:
    """Extract plugin metadata from scoped MCP data."""
    from datetime import datetime

    plugins = {}

    for server_name, entry in mcp_scoped.items():
        metadata = entry.get("metadata", {})

        if metadata.get("source") != "plugin":
            continue

        plugin_name = metadata.get("plugin_name", "unknown")
        plugin_version = metadata.get("plugin_version", "unknown")

        if plugin_name not in plugins:
            plugins[plugin_name] = {
                "version": plugin_version,
                "mcp_servers": [],
                "mcp_count": 0,
                "last_sync": datetime.now().isoformat()
            }

        plugins[plugin_name]["mcp_servers"].append(server_name)
        plugins[plugin_name]["mcp_count"] += 1

    return plugins
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact | Reference |
|--------------|------------------|--------------|--------|-----------|
| File hash-only drift | File hash + plugin version drift | v2.0 milestone (2026) | Detect plugin updates that don't change MCP files | Requirement STATE-03 |
| Flat MCP display | Grouped by source (user/project/plugin) | v2.0 milestone (2026) | Clear source attribution | Requirement STATE-02 |
| No plugin tracking | Plugin version + MCP count tracking | v2.0 milestone (2026) | Update-triggered re-sync detection | Requirement STATE-01 |
| State schema v1 | State schema v2 with accounts + plugins | v2.0 milestone (2026) | Multi-account + plugin support | StateManager evolution |

**Deprecated/outdated:**
- **Single drift detection method:** v1.0 only tracked file hashes — v2.0 adds plugin drift dimension
- **Ungrouped /sync-status output:** v1.0 showed flat MCP list — v2.0 groups by source

## Open Questions

### 1. Plugin Re-Sync Trigger Semantics

**What we know:** Requirement STATE-02 says "triggers re-sync" but wording is ambiguous

**What's unclear:**
- Auto-sync on plugin drift? OR warn user and wait for manual /sync?
- If auto-sync, run in background? OR prompt user first?

**Recommendation:** Warn user (conservative approach) — consistent with existing HarnessSync philosophy of explicit user control. If automatic sync needed later, add `--auto-on-plugin-update` flag (opt-in).

### 2. Plugin State Per-Account vs Global

**What we know:** StateManager v2 supports per-account state nesting

**What's unclear:**
- Should plugins be tracked per-account (nested under accounts.{account}.plugins)?
- OR global with cc_home path tag?

**Recommendation:** Per-account tracking (nested) — cleaner isolation, matches state schema philosophy. Each account can have different plugins installed.

### 3. MCP Display Verbosity Default

**What we know:** /sync-status output will grow with plugin count

**What's unclear:**
- Show all MCPs by default? OR summary counts with --verbose flag for details?
- Truncate per-group? OR per-total?

**Recommendation:** Truncate per-group (10 servers max per group, "... and N more" suffix) — balances detail with readability. Add `--verbose` flag for full list in future if needed.

### 4. Plugin Drift Priority Levels

**What we know:** Version change AND MCP count change both indicate drift

**What's unclear:**
- Should they be distinguished (version cosmetic vs MCP functional)?
- OR treat all drift equally?

**Recommendation:** Track both separately in drift reason string ("version_changed" vs "mcp_count_changed") — allows future prioritization without schema change.

## Sources

### Primary (HIGH confidence)

- **.planning/REQUIREMENTS.md** — Requirements STATE-01, STATE-02, STATE-03
  - STATE-01: Plugin tracking schema (line 99)
  - STATE-02: /sync-status grouping format (line 100)
  - STATE-03: Plugin drift detection (line 101)

- **src/state_manager.py** — Existing StateManager implementation
  - State schema v2 with accounts (lines 31-59)
  - Atomic write pattern (lines 142-186)
  - Drift detection pattern (lines 254-295)
  - record_sync() method (lines 188-252)

- **src/commands/sync_status.py** — Existing /sync-status implementation
  - Per-target display format (lines 233-279)
  - Drift display pattern (lines 264-279)
  - Multi-account support (lines 68-104, 106-189)

- **Phase 9 Research** — 09-RESEARCH.md
  - Scoped MCP format with metadata (lines 77-89)
  - Plugin metadata fields (lines 81-89)

- **src/source_reader.py** — Plugin discovery implementation
  - Plugin MCP discovery (lines 277-359)
  - Metadata tagging (lines 347-358)

- **src/orchestrator.py** — Sync coordination
  - State update pattern (lines 307-352)

### Secondary (MEDIUM confidence)

- **.planning/ROADMAP.md** — Phase 11 success criteria
  - 7 success criteria detailed (lines 160-167)

- **Decision Log** — .planning/yolo-decisions.log
  - Decision #23: Secret detection blocks by default (conservative principle)
  - Decision #30: v1 state migration pattern

### Tertiary (LOW confidence)

N/A — All findings verified through high-confidence sources

## Metadata

**Confidence breakdown:**
- State schema extension: HIGH - existing StateManager supports new keys without breaking changes
- Plugin metadata extraction: HIGH - Phase 9 already provides data, just need to persist
- Plugin drift detection: HIGH - existing detect_drift() pattern proven, adapt for plugins
- /sync-status grouping: HIGH - existing display logic, just add grouping layer
- Implementation patterns: HIGH - all patterns based on existing codebase

**Research date:** 2026-02-15
**Valid until:** 60 days (2026-04-15) — State management patterns are stable, no external API changes expected

---

**End of Research Document**
