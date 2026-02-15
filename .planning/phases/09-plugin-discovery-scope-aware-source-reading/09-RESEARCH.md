# Phase 9: Plugin Discovery & Scope-Aware Source Reading - Research

**Researched:** 2026-02-15
**Domain:** Claude Code plugin discovery, MCP scoping, source configuration
**Confidence:** HIGH

## Summary

Phase 9 extends SourceReader to discover MCP servers from installed Claude Code plugins and implement 3-tier scope awareness (user/project/local) with proper precedence handling. The research reveals that Claude Code has a well-documented plugin cache structure at `~/.claude/plugins/`, a plugin registry at `~/.claude/plugins/installed_plugins.json`, and a 3-tier MCP scoping system that differs from general settings scopes.

**Key findings:**
1. Plugin discovery is straightforward via installed_plugins.json version 2 format
2. Plugin MCPs can be in `.mcp.json` OR inline in `plugin.json.mcpServers`
3. `${CLAUDE_PLUGIN_ROOT}` variable must be expanded to absolute paths during sync
4. MCP "local" scope stores configs in `~/.claude.json` under projects[path], NOT in project directory
5. Scope precedence is local > project > user, with plugin MCPs treated as user-scope
6. Current SourceReader already handles user/project MCP discovery but lacks plugin and local-scope support

**Primary recommendation:** Extend SourceReader with `get_plugin_mcp_servers()` and `get_local_scope_mcp_servers()` methods, implement scope tagging, and add plugin metadata tracking.

## User Constraints (from CONTEXT.md)

No CONTEXT.md exists for this phase. All implementation choices are at Claude's discretion.

**Prior decisions from milestone scope:**
- Python 3 stdlib only (zero dependencies)
- Adapter pattern for targets (Codex, Gemini, OpenCode)
- Conservative permission mapping
- Plugin MCPs are user-scope (always sync to user-level target configs)
- Gemini extensions NOT the target — use settings.json
- 3-tier scope precedence: local > project > user

## Paper-Backed Recommendations

### Recommendation 1: Use File-Based Plugin Discovery (Not IPC)

**Recommendation:** Read `~/.claude/plugins/installed_plugins.json` directly rather than attempting IPC with Claude Code process

**Evidence:**
- Claude Code plugin system uses file-based registry (installed_plugins.json version 2 format)
- Official Claude Code docs show filesystem-based plugin cache structure
- Verified implementation in HarnessSync existing codebase (src/source_reader.py lines 48, 125-154) already reads this file for skill discovery
- File-based approach is synchronous, requires no daemon/service dependencies

**Confidence:** HIGH — Multiple official sources confirm file-based registry
**Expected improvement:** Zero runtime dependencies, works offline, no IPC complexity
**Caveats:** Registry format could change (mitigated by version field in JSON)

### Recommendation 2: Expand `${CLAUDE_PLUGIN_ROOT}` at Discovery Time

**Recommendation:** Resolve `${CLAUDE_PLUGIN_ROOT}` variable to absolute paths during MCP server discovery, not at sync time

**Evidence:**
- Claude Code plugin.json docs specify `${CLAUDE_PLUGIN_ROOT}` expands to plugin cache path
- Research shows real-world examples: `"command": "${CLAUDE_PLUGIN_ROOT}/bin/server"` (v2-claude-plugins.md lines 517-519)
- Target CLIs (Codex TOML, Gemini settings.json) do NOT support this variable
- Expansion must happen during HarnessSync processing to produce portable target configs

**Confidence:** HIGH — Official docs + verified examples
**Expected improvement:** Target configs work correctly without custom variable support
**Caveats:** Absolute paths less portable across machines (documented limitation)

### Recommendation 3: Tag MCP Servers with Origin Metadata

**Recommendation:** Attach scope and plugin metadata to each discovered MCP server for precedence resolution and debugging

**Evidence:**
- Claude Code uses 3-tier scope system (user/project/local) with precedence rules
- Research shows plugin MCPs treated as user-scope (v2-SUMMARY.md line 7)
- Precedence order: local > project > user (v2-claude-plugins.md lines 511-517)
- Adapter implementations need origin info to write to correct target location

**Confidence:** HIGH — Documented in official Claude Code MCP scoping
**Expected improvement:** Correct precedence handling, better debugging, clear source attribution
**Caveats:** Increases memory footprint (minimal — metadata is small)

**Implementation pattern:**
```python
{
    "server-name": {
        "config": {...},  # Original MCP config
        "metadata": {
            "scope": "user",  # user | project | local
            "source": "plugin",  # plugin | file
            "plugin_name": "my-plugin",  # if source == plugin
            "plugin_version": "1.0.0"  # if source == plugin
        }
    }
}
```

### Recommendation 4: Handle Both .mcp.json and plugin.json Formats

**Recommendation:** Check both standalone `.mcp.json` at plugin root AND inline `plugin.json.mcpServers` field

**Evidence:**
- Research shows two plugin MCP registration methods (v2-codex-mcp.md lines 499-524)
- Method 1: Standalone `.mcp.json` file at plugin root
- Method 2: Inline `mcpServers` field in `plugin.json`
- Real-world examples use both patterns (Context7 uses .mcp.json, GRD uses plugin.json inline)

**Confidence:** HIGH — Verified in plugin cache inspection
**Expected improvement:** 100% plugin MCP discovery coverage
**Caveats:** Plugin.json at two possible locations (.claude-plugin/plugin.json OR root plugin.json)

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib json | 3.x | JSON parsing | Built-in, zero dependencies (project constraint) |
| Python stdlib pathlib | 3.x | File path handling | Robust path operations, cross-platform |

### Supporting

N/A — Phase uses only Python standard library (project constraint)

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Rationale |
|------------|-----------|----------|-----------|
| File reading | Claude Code IPC/API | IPC would need daemon running | File-based is simpler, works offline, no new dependencies |
| Manual JSON parse | pydantic models | Pydantic adds validation but violates zero-dependency constraint | Stdlib json + dict validation sufficient for well-defined formats |

## Architecture Patterns

### Recommended Project Structure

Current structure is correct. Extensions go in `src/source_reader.py`:

```
src/
├── source_reader.py        # EXTEND: Add plugin + local scope methods
├── adapters/
│   ├── base.py            # EXTEND: Handle scope metadata
│   ├── codex.py           # EXTEND: Write to correct scope
│   ├── gemini.py          # EXTEND: Write to correct scope
│   └── opencode.py        # EXTEND: Write to correct scope
└── state_manager.py       # EXTEND: Track plugin versions for drift detection
```

### Pattern 1: Layered MCP Discovery

**What:** Discover MCP servers in layers (file → plugin → local scope), merge with precedence

**When to use:** When multiple configuration sources can define overlapping servers

**Example:**
```python
def get_all_mcp_servers_with_scope(self) -> dict[str, dict]:
    """Discover all MCP servers with scope metadata."""
    servers = {}

    # Layer 1: User-scope file-based MCPs (lowest precedence)
    user_file_mcps = self._get_file_mcp_servers(scope="user")
    for name, config in user_file_mcps.items():
        servers[name] = {
            "config": config,
            "metadata": {"scope": "user", "source": "file"}
        }

    # Layer 2: User-scope plugin MCPs (same precedence as user files)
    plugin_mcps = self._get_plugin_mcp_servers()
    for name, config in plugin_mcps.items():
        if name not in servers:  # Don't override file configs
            servers[name] = {
                "config": config,
                "metadata": {
                    "scope": "user",
                    "source": "plugin",
                    "plugin_name": config.get("_plugin_name"),
                    "plugin_version": config.get("_plugin_version")
                }
            }

    # Layer 3: Project-scope MCPs (override user)
    project_mcps = self._get_file_mcp_servers(scope="project")
    for name, config in project_mcps.items():
        servers[name] = {
            "config": config,
            "metadata": {"scope": "project", "source": "file"}
        }

    # Layer 4: Local-scope MCPs (highest precedence)
    local_mcps = self._get_local_scope_mcp_servers()
    for name, config in local_mcps.items():
        servers[name] = {
            "config": config,
            "metadata": {"scope": "local", "source": "file"}
        }

    return servers
```

### Pattern 2: Plugin Cache Path Resolution

**What:** Resolve plugin paths from registry → cache → MCP config

**When to use:** When reading plugin-provided MCP servers

**Example:**
```python
def _get_plugin_mcp_servers(self) -> dict[str, dict]:
    """Discover MCP servers from installed plugins."""
    servers = {}

    # Read plugin registry
    if not self.cc_plugins_registry.exists():
        return servers

    registry = read_json_safe(self.cc_plugins_registry)
    plugins = registry.get("plugins", {})

    for plugin_key, installs in plugins.items():
        # Handle list format (version 2)
        if not isinstance(installs, list):
            installs = [installs]

        for install in installs:
            # Only process user-scope plugins
            if install.get("scope") != "user":
                continue

            install_path = Path(install.get("installPath", ""))
            if not install_path.exists():
                continue

            # Check both MCP registration methods
            plugin_mcps = {}

            # Method 1: Standalone .mcp.json
            mcp_json = install_path / ".mcp.json"
            if mcp_json.exists():
                data = read_json_safe(mcp_json)
                if isinstance(data, dict):
                    plugin_mcps.update(data)

            # Method 2: Inline in plugin.json
            for plugin_json_path in [
                install_path / ".claude-plugin" / "plugin.json",
                install_path / "plugin.json"
            ]:
                if plugin_json_path.exists():
                    plugin_data = read_json_safe(plugin_json_path)
                    inline_mcps = plugin_data.get("mcpServers", {})
                    if isinstance(inline_mcps, dict):
                        plugin_mcps.update(inline_mcps)
                    break  # Only check one plugin.json location

            # Expand ${CLAUDE_PLUGIN_ROOT} and tag with plugin metadata
            for name, config in plugin_mcps.items():
                expanded_config = self._expand_plugin_root(config, install_path)
                expanded_config["_plugin_name"] = plugin_key.split("@")[0]
                expanded_config["_plugin_version"] = install.get("version", "unknown")
                servers[name] = expanded_config

    return servers

def _expand_plugin_root(self, config: dict, plugin_path: Path) -> dict:
    """Expand ${CLAUDE_PLUGIN_ROOT} in MCP server config."""
    import json

    # Convert to JSON string, replace variable, parse back
    config_str = json.dumps(config)
    config_str = config_str.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_path))
    return json.loads(config_str)
```

### Pattern 3: Local Scope MCP Discovery

**What:** Read local-scope MCPs from `~/.claude.json` under projects[absolutePath].mcpServers

**When to use:** When implementing local-scope MCP support (private, per-project overrides)

**Example:**
```python
def _get_local_scope_mcp_servers(self) -> dict[str, dict]:
    """Read local-scope MCP servers from ~/.claude.json projects map."""
    if not self.project_dir:
        return {}

    claude_json = Path.home() / ".claude.json"
    if not claude_json.exists():
        return {}

    data = read_json_safe(claude_json)
    projects = data.get("projects", {})

    # Key is absolute project path
    project_key = str(self.project_dir.resolve())
    project_config = projects.get(project_key, {})

    mcp_servers = project_config.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        return {}

    # Filter out malformed entries
    valid_servers = {}
    for name, config in mcp_servers.items():
        if isinstance(config, dict) and (config.get("command") or config.get("url")):
            valid_servers[name] = config

    return valid_servers
```

### Anti-Patterns to Avoid

- **Plugin IPC communication:** Don't try to communicate with running Claude Code process — file-based discovery is simpler and works offline
- **Lazy variable expansion:** Don't defer `${CLAUDE_PLUGIN_ROOT}` expansion to adapters — resolve at discovery time for cleaner separation
- **Scope mixing:** Don't merge all scopes into flat dict — preserve metadata for debugging and precedence handling
- **Plugin version ignorance:** Don't ignore plugin version field — needed for drift detection when plugins update

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON parsing | Custom parser | stdlib json.loads | Edge cases (encoding, escape sequences) are hard |
| Path resolution | String concatenation | pathlib.Path | Cross-platform, handles edge cases (trailing slashes, etc.) |
| File atomic writes | Manual rename | Existing write_json_atomic util | Race conditions, permission errors already handled |
| Variable expansion | Regex replacement | json.dumps → str.replace → json.loads | Preserves JSON structure, handles nested values |

**Key insight:** Python stdlib + existing HarnessSync utils are sufficient. Don't add dependencies or reimplement proven patterns.

## Common Pitfalls

### Pitfall 1: MCP "Local" Scope ≠ General "Local" Settings

**What goes wrong:** Confusing MCP local scope (in `~/.claude.json`) with general local settings (in `.claude/settings.local.json`)

**Why it happens:** Both use the term "local" but store configs in different locations

**How to avoid:**
- MCP local: `~/.claude.json` under `projects[absolutePath].mcpServers`
- General local: `.claude/settings.local.json`
- Document clearly in code comments

**Warning signs:** Reading from wrong file, local-scope MCPs not discovered

**Reference:** v2-claude-plugins.md lines 419-431, v2-codex-mcp.md lines 406-420

### Pitfall 2: Plugin.json Location Ambiguity

**What goes wrong:** Only checking `.claude-plugin/plugin.json` and missing root `plugin.json`

**Why it happens:** Older plugins use root location, newer use .claude-plugin/ subdirectory

**How to avoid:** Check both locations in order: `.claude-plugin/plugin.json` first, then root `plugin.json`

**Warning signs:** Plugin MCPs not discovered even though plugin is installed

**Reference:** v2-claude-plugins.md lines 163-169, examples show both patterns

### Pitfall 3: Plugin Scope Filtering

**What goes wrong:** Including project-scoped plugins in user-scope discovery

**Why it happens:** installed_plugins.json can contain plugins at multiple scopes

**How to avoid:** Filter by `install.get("scope") == "user"` when discovering user-level plugins

**Warning signs:** Project-scoped plugin MCPs appearing in user-level sync

**Reference:** v2-claude-plugins.md lines 134-142, scope field usage

### Pitfall 4: Precedence Collapse

**What goes wrong:** Later configs completely replace earlier ones instead of respecting scope precedence

**Why it happens:** Using dict.update() without tracking origin

**How to avoid:** Tag each server with metadata before merging, implement layered discovery pattern

**Warning signs:** Local-scope overrides not working, unexpected server configs active

**Reference:** v2-SUMMARY.md line 39 (scope precedence collapse identified as critical pitfall)

### Pitfall 5: ${CLAUDE_PLUGIN_ROOT} in Nested Structures

**What goes wrong:** Variable expansion misses nested occurrences in env vars or arrays

**Why it happens:** String replacement on serialized JSON can miss complex structures

**Evidence:** v2-claude-plugins.md lines 736-761 show variable usage in command, args, env fields

**How to avoid:**
- Serialize entire config to JSON string
- Replace all occurrences: `config_str.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_path))`
- Parse back to dict

**Warning signs:** Some paths expanded, others still have variable

## Experiment Design

Not applicable — This phase extends existing SourceReader with new discovery methods. No experimental algorithms or novel techniques.

**Validation approach:**
- Unit tests with fixture data (mock installed_plugins.json, plugin cache directories)
- Integration tests with real Claude Code plugin installation
- Verification that scope precedence matches Claude Code behavior

## Verification Strategy

### Recommended Verification Tiers for This Phase

| Item | Recommended Tier | Rationale |
|------|-----------------|-----------|
| Plugin registry parsing | Level 1 (Sanity) | Can check with fixture JSON immediately |
| Plugin MCP discovery (.mcp.json) | Level 1 (Sanity) | Mock plugin directory with .mcp.json |
| Plugin MCP discovery (inline) | Level 1 (Sanity) | Mock plugin.json with mcpServers field |
| ${CLAUDE_PLUGIN_ROOT} expansion | Level 1 (Sanity) | Simple string replacement check |
| Local scope MCP discovery | Level 1 (Sanity) | Mock ~/.claude.json with projects map |
| Scope precedence resolution | Level 2 (Proxy) | Requires multiple scope configs, check winner |
| Plugin version tracking | Level 2 (Proxy) | Check metadata preservation |
| Real plugin MCP sync to targets | Level 3 (Deferred) | Needs real Claude Code plugin + target CLI |

### Level 1 Checks (Sanity)

**Plugin registry parsing:**
```python
def test_plugin_registry_version_2():
    """Verify installed_plugins.json version 2 parsing."""
    fixture = {
        "version": 2,
        "plugins": {
            "test-plugin@test-marketplace": [
                {
                    "scope": "user",
                    "installPath": "/tmp/test/plugin",
                    "version": "1.0.0"
                }
            ]
        }
    }
    # Write fixture, call SourceReader, verify parsed
```

**Plugin MCP discovery:**
```python
def test_plugin_mcp_standalone():
    """Verify .mcp.json discovery at plugin root."""
    # Create temp plugin dir with .mcp.json
    # Call _get_plugin_mcp_servers()
    # Assert server discovered with plugin metadata
```

**Variable expansion:**
```python
def test_plugin_root_expansion():
    """Verify ${CLAUDE_PLUGIN_ROOT} expanded correctly."""
    config = {
        "command": "${CLAUDE_PLUGIN_ROOT}/bin/server",
        "args": ["--config", "${CLAUDE_PLUGIN_ROOT}/config.json"]
    }
    result = _expand_plugin_root(config, Path("/plugin/path"))
    assert result["command"] == "/plugin/path/bin/server"
    assert result["args"][1] == "/plugin/path/config.json"
```

**Local scope discovery:**
```python
def test_local_scope_mcp():
    """Verify local-scope MCP discovery from ~/.claude.json."""
    # Create temp ~/.claude.json with projects map
    # Call _get_local_scope_mcp_servers()
    # Assert correct servers returned
```

### Level 2 Proxy Metrics

**Scope precedence:**
- Define same MCP server name at user, project, and local scopes
- Call get_all_mcp_servers_with_scope()
- Assert local scope wins (metadata.scope == "local")

**Plugin metadata preservation:**
- Discover plugin MCP server
- Check metadata contains plugin_name, plugin_version
- Verify StateManager can track version changes

### Level 3 Deferred Items

**Real plugin MCP sync:**
- Install real Claude Code plugin with MCP server
- Run HarnessSync /sync
- Verify MCP server appears in Codex/Gemini/OpenCode config
- Verify ${CLAUDE_PLUGIN_ROOT} expanded to absolute path
- Verify target MCP server works (manual test in target CLI)

**Scope sync to targets:**
- Configure MCPs at user, project, local scopes
- Run HarnessSync /sync
- Verify Codex writes to correct scope (~/.codex/config.toml vs .codex/config.toml)
- Verify Gemini writes to correct scope (~/.gemini/settings.json vs .gemini/settings.json)

## Production Considerations

### Known Failure Modes

**Plugin cache corruption:**
- **Description:** installed_plugins.json or plugin cache directories damaged/incomplete
- **Prevention:** Use read_json_safe (returns empty dict on error), check file existence before reading
- **Detection:** Empty plugin MCP discovery when plugins are installed (warn user)

**Path portability:**
- **Description:** Expanded ${CLAUDE_PLUGIN_ROOT} creates absolute paths that break across machines
- **Prevention:** Document that synced configs are machine-specific, recommend per-machine sync
- **Detection:** User reports MCP servers fail on different machine (expected behavior)

**Plugin version drift:**
- **Description:** Plugin updates change MCP server configs without re-sync
- **Prevention:** Track plugin versions in state file, warn on version mismatch
- **Detection:** StateManager hash comparison detects drift

### Scaling Concerns

**At current scale:**
- Typical user: 5-10 plugins, 1-3 MCPs per plugin = 15-30 total MCP servers
- File I/O: Read ~10 JSON files (negligible overhead)
- Memory: Dict of MCP configs (few KB max)

**At production scale:**
- Power user: 50 plugins, 5 MCPs each = 250 MCP servers
- Approach: Same (file-based discovery is fast even at 100+ files)
- No optimization needed (pathlib + json.loads handle thousands of files easily)

### Common Implementation Traps

**Forgetting to filter by scope:**
- **What goes wrong:** Project-scoped plugins included in user-scope discovery
- **Correct approach:** Always check `install.get("scope") == "user"` when iterating plugins

**Not handling missing installPath:**
- **What goes wrong:** Crash when plugin registry has null/empty installPath
- **Correct approach:** `if not install_path: continue` before Path() construction

**Mutating original config dict:**
- **What goes wrong:** Modifying source config when expanding variables
- **Correct approach:** json.dumps → replace → json.loads creates new dict

## Code Examples

Verified patterns from official sources and existing codebase:

### Reading installed_plugins.json (Existing Pattern)

```python
# Source: src/source_reader.py lines 125-154 (verified working)
if self.cc_plugins_registry.exists():
    registry = read_json_safe(self.cc_plugins_registry)
    plugins_data = registry.get("plugins", {})

    # Handle both dict and list formats
    plugin_entries = []
    if isinstance(plugins_data, dict):
        plugin_entries = plugins_data.values()
    elif isinstance(plugins_data, list):
        plugin_entries = plugins_data

    for plugin_info in plugin_entries:
        if not isinstance(plugin_info, dict):
            continue
        if plugin_info.get("scope") != "user":
            continue
        install_path = plugin_info.get("installPath", "")
        if not install_path:
            continue
        # Process plugin...
```

### Expanding Plugin Variables (New Pattern)

```python
# Source: v2-claude-plugins.md lines 551-569 (documented pattern)
def _expand_plugin_root(config: dict, plugin_path: Path) -> dict:
    """Expand ${CLAUDE_PLUGIN_ROOT} in MCP server config.

    Handles expansion in command, args, env, url, headers fields.
    """
    import json

    # Serialize to JSON, replace all occurrences, parse back
    config_str = json.dumps(config)
    config_str = config_str.replace("${CLAUDE_PLUGIN_ROOT}", str(plugin_path))
    expanded = json.loads(config_str)

    return expanded
```

### Local Scope MCP Discovery (New Pattern)

```python
# Source: v2-claude-plugins.md lines 481-510 (documented format)
def _get_local_scope_mcp_servers(project_dir: Path) -> dict[str, dict]:
    """Read local-scope MCPs from ~/.claude.json projects map."""
    claude_json = Path.home() / ".claude.json"
    if not claude_json.exists():
        return {}

    data = read_json_safe(claude_json)
    projects = data.get("projects", {})

    # Key is absolute project path
    project_key = str(project_dir.resolve())
    project_config = projects.get(project_key, {})

    mcp_servers = project_config.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        return {}

    # Filter malformed entries
    valid_servers = {}
    for name, config in mcp_servers.items():
        if isinstance(config, dict) and (config.get("command") or config.get("url")):
            valid_servers[name] = config

    return valid_servers
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact | Reference |
|--------------|------------------|--------------|--------|-----------|
| Flat MCP discovery | Scope-aware MCP discovery | v2.0 milestone (2026) | Proper precedence handling, plugin support | v2-SUMMARY.md |
| Skip plugin MCPs | Discover plugin MCPs | v2.0 milestone (2026) | Sync plugin-bundled servers to targets | v2-claude-plugins.md |
| 2-tier scoping (user/project) | 3-tier scoping (user/project/local) | Claude Code (2025) | Private per-project overrides | v2-claude-plugins.md lines 419-431 |

**Deprecated/outdated:**
- **installed_plugins.json version 1:** Replaced by version 2 with enhanced metadata (installPath, version, scope, projectPath fields)
- **Root-only plugin.json:** New plugins use `.claude-plugin/plugin.json` but HarnessSync must support both for backward compatibility

## Open Questions

### 1. Plugin MCPs at Project Scope

**What we know:** Plugins can be project-scoped (installPath + projectPath in registry)

**What's unclear:**
- Should project-scoped plugin MCPs be treated as project-scope or user-scope for sync?
- Research says "plugin MCPs are user-scope" but doesn't clarify project-scoped plugins

**Recommendation:** Treat ALL plugin MCPs as user-scope regardless of plugin scope (simplifies precedence, matches research guidance)

### 2. Disabled Plugin Handling

**What we know:** Plugins can be disabled via settings.json enabledPlugins: false

**What's unclear:**
- Should disabled plugin MCPs be skipped during discovery?
- Or discovered but marked as disabled in metadata?

**Recommendation:** Check enabledPlugins field in settings.json, skip MCP discovery for disabled plugins (cleaner, matches runtime behavior)

### 3. Plugin Update Detection Timing

**What we know:** Plugin versions tracked in installed_plugins.json, can detect changes

**What's unclear:**
- When should version check trigger re-sync? On every /sync-status? Only on explicit /sync?
- Should HarnessSync auto-sync when plugin updates or just warn?

**Recommendation:** Detect on /sync-status, warn user, require manual /sync (conservative, user controls sync timing)

## Sources

### Primary (HIGH confidence)

- **v2-claude-plugins.md** — Comprehensive Claude Code plugin discovery research with verified examples
  - Plugin registry format (lines 16-55)
  - Plugin cache structure (lines 74-98)
  - Plugin metadata format (lines 115-221)
  - MCP 3-tier scoping (lines 419-517)
  - ${CLAUDE_PLUGIN_ROOT} expansion (lines 718-740)

- **v2-SUMMARY.md** — Executive summary of v2.0 findings
  - Scope precedence (lines 40-41)
  - Plugin MCP treatment (line 7)
  - Critical pitfalls (line 39)

- **v2-codex-mcp.md** — Codex target translation requirements
  - Plugin MCP registration methods (lines 499-524)
  - Environment variable handling differences (lines 90-115)

- **Existing codebase** — src/source_reader.py
  - Verified plugin registry parsing pattern (lines 125-154)
  - Existing MCP discovery implementation (lines 242-288)

### Secondary (MEDIUM confidence)

- **Claude Code official docs** — Referenced in v2-claude-plugins.md sources
  - Plugin reference: code.claude.com/docs/en/plugins-reference
  - MCP documentation: code.claude.com/docs/en/mcp

### Tertiary (LOW confidence)

N/A — All findings verified through high-confidence sources

## Metadata

**Confidence breakdown:**
- Plugin discovery mechanism: HIGH - verified examples + existing codebase
- Plugin MCP formats: HIGH - official docs + real plugin inspection
- Scope system: HIGH - official Claude Code docs + research analysis
- ${CLAUDE_PLUGIN_ROOT} expansion: HIGH - documented pattern + examples
- Precedence rules: HIGH - official scope documentation
- Implementation patterns: HIGH - existing SourceReader codebase + stdlib

**Research date:** 2026-02-15
**Valid until:** 60 days (2026-04-15) — Plugin system is stable, minor format changes possible

---

**End of Research Document**
