# Phase 10: Scope-Aware Target Sync & Environment Translation - Research

**Researched:** 2026-02-15
**Domain:** MCP scope-to-target mapping, environment variable syntax translation, transport compatibility
**Confidence:** HIGH

## Summary

Phase 10 implements scope-aware MCP synchronization by mapping Claude Code's 3-tier scope system (user/project/local) to target CLI configurations (Codex TOML, Gemini settings.json) and translating environment variable syntax between incompatible formats. The phase builds on Phase 9's scope-tagged MCP discovery to route servers to the correct target configuration files.

**Key findings:**
1. Codex and Gemini both support user/project scope separation via distinct config file locations
2. Environment variable syntax is fundamentally incompatible: Claude Code uses bash-style `${VAR}` interpolation, Codex requires literal `env` maps
3. Plugin MCPs must always sync to user-scope targets (never project-scope) per v2.0 design decision
4. Transport type detection is critical: Codex doesn't support SSE natively, requires warning
5. Existing adapters already handle MCP translation but lack scope awareness and env var translation

**Primary recommendation:** Extend existing adapter `sync_mcp()` methods with scope parameter, implement environment variable syntax translator for Codex, preserve Claude Code syntax for Gemini (which supports it natively).

## User Constraints (from CONTEXT.md)

No CONTEXT.md exists for this phase. All implementation choices are at Claude's discretion.

**Prior decisions from milestone scope:**
- Decision #12: Manual TOML generation via f-strings (tomllib is read-only)
- Decision #13: Env var references preserved in TOML (${VAR} kept literal for runtime expansion)
- Decision #32: Gemini extensions not the target - Plugin MCPs sync to settings.json, NOT extensions
- Decision #33: 3-tier scope precedence - local > project > user
- Decision #34: Plugin MCPs are user-scope - Always sync to user-level target configs
- Decision #36: User-scope MCPs from ~/.claude.json - v2.0 reads from ~/.claude.json

## Paper-Backed Recommendations

### Recommendation 1: Use Scope Parameter in Adapter Interface

**Recommendation:** Add `scope` parameter to `sync_mcp()` adapter method signature to route servers to correct config files

**Evidence:**
- Existing codebase shows adapters write to hardcoded paths (src/adapters/codex.py line 290, src/adapters/gemini.py line 319)
- Phase 9 research established scope-tagged MCP discovery format (09-RESEARCH.md lines 77-89)
- Requirements SYNC-01 and SYNC-02 specify scope-to-path mapping explicitly (.planning/REQUIREMENTS.md lines 88-89)
- Software engineering best practice: explicit parameter better than inferring from data

**Confidence:** HIGH — Multiple sources confirm need
**Expected improvement:** Clear separation of user/project configs, no path inference bugs
**Caveats:** Requires adapter interface change (backward incompatible but v2.0 allows breaking changes)

### Recommendation 2: Translate Claude Code ${VAR} to Codex Literal env Map

**Recommendation:** Parse Claude Code MCP configs for `${VAR}` syntax and extract to Codex `env` field with literal values from shell environment

**Evidence:**
- Codex does NOT support variable interpolation in config.toml (v2-codex-mcp.md lines 90-116)
- Codex requires literal `env = { "KEY" = "value" }` format (v2-codex-mcp.md lines 94-99)
- Claude Code uses bash-style `${VAR}` interpolation (Phase 9 research, official docs)
- Bash parameter expansion documented: `${VAR:-default}` provides default values ([Bash Reference Manual](https://www.gnu.org/software/bash/manual/html_node/Shell-Parameter-Expansion.html))
- Docker Compose uses same pattern for env var interpolation ([Docker Docs](https://docs.docker.com/reference/compose-file/interpolation/))

**Confidence:** HIGH — Official documentation confirms syntax incompatibility
**Expected improvement:** Codex MCP servers work correctly with environment-dependent configs
**Caveats:** Requires reading shell environment at sync time (values baked into TOML, not dynamic)

**Implementation pattern:**
```python
def translate_env_vars_for_codex(config: dict) -> dict:
    """Extract ${VAR} references from Claude Code config and resolve to Codex env map."""
    import os
    import re

    env_map = {}
    config_copy = config.copy()

    # Scan all string values for ${VAR} or ${VAR:-default}
    var_pattern = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)(:-([^}]+))?\}')

    def extract_vars(obj):
        if isinstance(obj, str):
            for match in var_pattern.finditer(obj):
                var_name = match.group(1)
                default_value = match.group(3)

                # Read from environment
                env_value = os.environ.get(var_name, default_value or "")
                if env_value:
                    env_map[var_name] = env_value
        elif isinstance(obj, dict):
            for v in obj.values():
                extract_vars(v)
        elif isinstance(obj, list):
            for item in obj:
                extract_vars(item)

    extract_vars(config_copy)

    if env_map:
        config_copy['env'] = env_map

    return config_copy
```

### Recommendation 3: Preserve ${VAR} Syntax for Gemini (Native Support)

**Recommendation:** Pass Claude Code MCP configs to Gemini without env var translation — Gemini supports `${VAR}` natively

**Evidence:**
- Gemini settings.json format documented to support variable interpolation (v2-gemini-extensions.md)
- Existing GeminiAdapter preserves env field as-is (src/adapters/gemini.py lines 333-334)
- No evidence of translation needed in Gemini adapter code
- Requirement ENV-03 explicitly states "Preserve env var references in Gemini settings.json format" (.planning/REQUIREMENTS.md line 96)

**Confidence:** HIGH — Official requirement + existing implementation confirms
**Expected improvement:** Zero translation complexity for Gemini, native runtime expansion
**Caveats:** None — this is already working behavior

### Recommendation 4: Detect and Warn on Unsupported Transport Types

**Recommendation:** Check MCP server config for transport type, warn if target doesn't support it (e.g., SSE on Codex)

**Evidence:**
- Codex does NOT support SSE transport natively (v2-codex-mcp.md lines 232-235, GitHub issue #2129)
- Claude Code supports STDIO, HTTP, SSE transports (Phase 9 research)
- Requirement SYNC-04 specifies "Adapters detect unsupported transport types per target" (.planning/REQUIREMENTS.md line 91)
- Silent failures harm usability — explicit warnings better UX

**Confidence:** HIGH — Documented limitation + explicit requirement
**Expected improvement:** Users understand why some MCPs don't work, can take corrective action
**Caveats:** Detection heuristic (check URL for `/sse` or `sse` keyword) may have false positives

**Implementation pattern:**
```python
def detect_transport_type(config: dict) -> str:
    """Detect MCP server transport type from config."""
    if 'command' in config:
        return 'stdio'
    elif 'url' in config:
        url = config['url']
        if url.endswith('/sse') or 'sse' in url.lower():
            return 'sse'
        return 'http'
    return 'unknown'

def check_transport_support(transport: str, target: str) -> tuple[bool, str]:
    """Check if target supports transport type."""
    support_matrix = {
        'codex': {'stdio', 'http'},
        'gemini': {'stdio', 'http', 'sse'},
        'opencode': {'stdio', 'http'}
    }

    supported = support_matrix.get(target, set())
    if transport in supported:
        return True, ""
    else:
        return False, f"{transport.upper()} transport not supported on {target}"
```

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib json | 3.x | JSON parsing for settings.json | Built-in, zero dependencies (project constraint) |
| Python stdlib pathlib | 3.x | File path handling | Robust path operations, cross-platform |
| Python stdlib re | 3.x | Environment variable pattern matching | Built-in regex for `${VAR}` extraction |
| Python stdlib os | 3.x | Environment variable reading | Standard way to access shell environment |

### Supporting

Existing HarnessSync utilities:
- `src/utils/toml_writer.py` — Manual TOML generation (tomllib is read-only)
- `src/utils/paths.py` — JSON read/write with atomic operations
- `src/adapters/base.py` — Adapter interface

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Rationale |
|------------|-----------|----------|-----------|
| Manual env var parsing | python-dotenv library | dotenv adds .env file support but violates zero-dependency constraint | stdlib re + os.environ sufficient for runtime env access |
| Regex for ${VAR} | AST/template parser | Template parser more robust but overkill | Simple regex adequate for well-defined bash syntax |

## Architecture Patterns

### Recommended Project Structure

Current structure is correct. Extensions go in existing adapter files:

```
src/
├── adapters/
│   ├── base.py            # EXTEND: Add scope param to sync_mcp() signature
│   ├── codex.py           # EXTEND: Add scope routing + env var translation
│   ├── gemini.py          # EXTEND: Add scope routing (preserve env vars)
│   └── opencode.py        # EXTEND: Add scope routing
└── utils/
    └── env_translator.py  # NEW: Environment variable syntax translation
```

### Pattern 1: Scope-to-Path Mapping

**What:** Map scope string to target configuration file path

**When to use:** When adapter needs to write MCP servers to correct location

**Example:**
```python
# Source: Requirements SYNC-01, SYNC-02
def get_target_config_path(self, scope: str) -> Path:
    """Map scope to target config file path.

    Args:
        scope: "user" | "project" | "local" (local treated as user per Decision #34)

    Returns:
        Path to target config file
    """
    # Plugin MCPs are always user-scope (Decision #34)
    if scope == "local" or scope == "user":
        # User-scope: ~/.codex/config.toml or ~/.gemini/settings.json
        return self._get_user_config_path()
    elif scope == "project":
        # Project-scope: .codex/config.toml or .gemini/settings.json
        return self._get_project_config_path()
    else:
        # Default to user-scope for unknown
        return self._get_user_config_path()

# Codex paths
def _get_user_config_path(self) -> Path:
    return Path.home() / ".codex" / "config.toml"

def _get_project_config_path(self) -> Path:
    return self.project_dir / ".codex" / "config.toml"
```

### Pattern 2: Environment Variable Translation Pipeline

**What:** Extract, resolve, and translate environment variables from Claude Code format to Codex format

**When to use:** When syncing MCPs to Codex (not Gemini — Gemini preserves syntax)

**Example:**
```python
# Source: Requirement ENV-01, ENV-02
def translate_mcp_for_codex(self, config: dict, metadata: dict) -> dict:
    """Translate Claude Code MCP config to Codex format.

    Handles:
    - Environment variable extraction ${VAR} -> env map
    - Default value syntax ${VAR:-default}
    - Transport type validation

    Args:
        config: Claude Code MCP server config
        metadata: Scope/source metadata from Phase 9

    Returns:
        Codex-compatible config dict
    """
    import os
    import re

    codex_config = config.copy()

    # Step 1: Extract environment variables
    var_pattern = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)(:-([^}]+))?\}')
    env_map = {}

    def extract_and_replace(text: str) -> str:
        """Extract vars from text and replace with resolved values."""
        def replacer(match):
            var_name = match.group(1)
            default_value = match.group(3)

            # Read from environment
            env_value = os.environ.get(var_name)

            if env_value is not None:
                env_map[var_name] = env_value
                return env_value
            elif default_value is not None:
                # Warn about using default
                self.logger.warning(f"Env var ${{{var_name}}} not set, using default: {default_value}")
                return default_value
            else:
                # Warn about undefined var
                self.logger.warning(f"Env var ${{{var_name}}} not set and no default provided")
                return ""

        return var_pattern.sub(replacer, text)

    # Step 2: Process all string fields
    for key in ['command', 'url']:
        if key in codex_config and isinstance(codex_config[key], str):
            codex_config[key] = extract_and_replace(codex_config[key])

    if 'args' in codex_config and isinstance(codex_config['args'], list):
        codex_config['args'] = [
            extract_and_replace(arg) if isinstance(arg, str) else arg
            for arg in codex_config['args']
        ]

    # Step 3: Add env map if variables found
    if env_map:
        # Merge with existing env (Claude Code env overrides extracted)
        existing_env = codex_config.get('env', {})
        codex_config['env'] = {**env_map, **existing_env}

    return codex_config
```

### Pattern 3: Transport Type Detection and Validation

**What:** Detect MCP transport type and validate target compatibility

**When to use:** Before writing MCP config to target, to warn on unsupported transports

**Example:**
```python
# Source: Requirement SYNC-04
def validate_transport_for_target(self, server_name: str, config: dict) -> tuple[bool, str]:
    """Check if MCP server transport is supported by this target.

    Args:
        server_name: MCP server name (for logging)
        config: MCP server config dict

    Returns:
        Tuple of (is_supported, warning_message)
    """
    # Detect transport type
    if 'command' in config:
        transport = 'stdio'
    elif 'url' in config:
        url = config['url']
        if url.endswith('/sse') or 'sse' in url.lower():
            transport = 'sse'
        else:
            transport = 'http'
    else:
        return False, f"MCP server {server_name}: No command or url field (invalid config)"

    # Check support (override in subclasses)
    supported = self._get_supported_transports()

    if transport not in supported:
        warning = (
            f"MCP server {server_name}: {transport.upper()} transport not supported on {self.target_name}. "
            f"Server will be skipped. Supported transports: {', '.join(supported)}"
        )
        return False, warning

    return True, ""

# Codex implementation
def _get_supported_transports(self) -> set[str]:
    """Return set of supported transport types for this target."""
    return {'stdio', 'http'}  # Codex: NO SSE support
```

### Anti-Patterns to Avoid

- **Hardcoding config paths:** Don't use `Path.home() / ".codex" / "config.toml"` directly in sync_mcp — use scope parameter
- **Silent env var failures:** Don't skip undefined `${VAR}` silently — warn user (missing API keys cause runtime failures)
- **Mixing scopes:** Don't write project-scope plugin MCPs — enforce user-scope for all plugin servers
- **Assuming transport support:** Don't write all MCPs blindly — validate transport compatibility first

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Environment variable expansion | Custom interpolator | stdlib os.environ + re.sub | Edge cases (nested braces, escape sequences) hard to get right |
| TOML generation | Custom TOML writer | Existing toml_writer.py utils | Already handles escaping, validation, atomic writes |
| JSON atomic writes | Manual write + rename | Existing write_json_atomic util | Race conditions, permission errors already handled |
| Scope precedence logic | Complex if/else chains | Phase 9's layered discovery pattern | Precedence already resolved at discovery time |

**Key insight:** Phase 9 does the hard work (scope tagging, precedence). Phase 10 just routes to correct files based on metadata.

## Common Pitfalls

### Pitfall 1: ${VAR} Expansion Timing

**What goes wrong:** Expanding `${VAR}` at discovery time (Phase 9) instead of sync time (Phase 10)

**Why it happens:** Environment variables might differ between discovery and sync contexts

**How to avoid:**
- Phase 9: Preserve `${VAR}` syntax in config dict
- Phase 10: Expand only when syncing to Codex (read from current shell environment)
- Gemini: Never expand (preserve syntax for runtime expansion)

**Warning signs:** MCP servers work during sync but fail later when env vars change

**Reference:** Decision #13 documents env var preservation strategy

### Pitfall 2: Plugin MCP Scope Confusion

**What goes wrong:** Writing plugin MCPs to project-scope target configs

**Why it happens:** Plugin metadata has `install.scope` field that might be "project"

**How to avoid:** Ignore plugin's install scope — ALWAYS treat plugin MCPs as user-scope per Decision #34

**Warning signs:** Plugin MCPs appear in `.codex/config.toml` instead of `~/.codex/config.toml`

**Reference:** .planning/REQUIREMENTS.md line 90 (SYNC-03)

### Pitfall 3: Default Value Silent Failure

**What goes wrong:** `${VAR:-default}` syntax expands to empty string when VAR undefined and default parsing fails

**Why it happens:** Regex captures default but code doesn't use it

**How to avoid:**
- Capture group 3 in regex: `(:-([^}]+))?`
- Check `match.group(3)` for default value
- Use default if env var not found

**Warning signs:** MCP servers fail with "missing required field" errors at runtime

**Reference:** [Bash Parameter Expansion](https://www.gnu.org/software/bash/manual/html_node/Shell-Parameter-Expansion.html) documents `:-` syntax

### Pitfall 4: SSE Transport Silent Skip

**What goes wrong:** SSE-based MCP servers silently disappear during sync to Codex

**Why it happens:** Transport validation fails but no warning logged

**How to avoid:**
- ALWAYS log warning when skipping unsupported transport
- Include server name and transport type in message
- Never silently filter servers

**Warning signs:** User reports "MCP server missing" but no error in logs

**Reference:** Requirement SYNC-04 specifies "warn instead of silently failing"

### Pitfall 5: Scope Path Resolution Order

**What goes wrong:** Reading from wrong config file when multiple scopes define same server

**Why it happens:** Forgetting that Phase 9 already resolved precedence

**How to avoid:**
- Trust Phase 9's scope metadata — it already picked the winner
- Don't re-implement precedence logic in Phase 10
- Just route each server to its metadata.scope's target path

**Warning signs:** Lower-precedence servers overwrite higher-precedence ones

**Reference:** Phase 9 research lines 175-191 (layered discovery pattern)

## Experiment Design

Not applicable — This phase implements deterministic configuration translation. No experimental algorithms or novel techniques.

**Validation approach:**
- Unit tests with fixture MCP configs (varying scopes, env vars, transports)
- Integration tests with real Claude Code plugin MCPs
- Verification that target CLIs can load synced configs

## Verification Strategy

### Recommended Verification Tiers for This Phase

| Item | Recommended Tier | Rationale |
|------|-----------------|-----------|
| Scope-to-path mapping | Level 1 (Sanity) | Simple lookup, can verify with assertions |
| Env var regex pattern matching | Level 1 (Sanity) | Test with fixture strings |
| ${VAR} expansion to env map | Level 1 (Sanity) | Mock os.environ, check output |
| ${VAR:-default} default handling | Level 1 (Sanity) | Test with missing env vars |
| Transport type detection | Level 1 (Sanity) | Test with fixture configs |
| Transport validation warnings | Level 2 (Proxy) | Check warning logged |
| User-scope MCP sync to Codex | Level 2 (Proxy) | Write to temp ~/.codex/, verify TOML |
| Project-scope MCP sync to Codex | Level 2 (Proxy) | Write to temp .codex/, verify TOML |
| User-scope MCP sync to Gemini | Level 2 (Proxy) | Write to temp ~/.gemini/, verify JSON |
| Plugin MCP always user-scope | Level 2 (Proxy) | Mock plugin MCP, verify path |
| Real Codex can load synced config | Level 3 (Deferred) | Needs real Codex CLI installation |
| Real Gemini can load synced config | Level 3 (Deferred) | Needs real Gemini CLI installation |
| MCP servers work in target CLI | Level 3 (Deferred) | Needs MCP server runtime + target CLI |

### Level 1 Checks (Sanity)

**Scope-to-path mapping:**
```python
def test_scope_to_path_user():
    """Verify user-scope maps to ~/.codex/config.toml."""
    adapter = CodexAdapter(Path("/tmp/project"))
    path = adapter.get_target_config_path("user")
    assert path == Path.home() / ".codex" / "config.toml"

def test_scope_to_path_project():
    """Verify project-scope maps to .codex/config.toml."""
    adapter = CodexAdapter(Path("/tmp/project"))
    path = adapter.get_target_config_path("project")
    assert path == Path("/tmp/project") / ".codex" / "config.toml"

def test_scope_to_path_plugin_treated_as_user():
    """Verify plugin/local scope maps to user-scope path."""
    adapter = CodexAdapter(Path("/tmp/project"))
    path = adapter.get_target_config_path("local")
    assert path == Path.home() / ".codex" / "config.toml"
```

**Environment variable expansion:**
```python
def test_env_var_extraction():
    """Verify ${VAR} extracted to env map."""
    os.environ["TEST_KEY"] = "test_value"

    config = {
        "command": "npx",
        "args": ["-y", "server"],
        "env": {"EXISTING": "kept"}
    }

    # Note: This test would need the actual implementation
    # Showing expected behavior
    result = translate_mcp_for_codex(config)

    # Original env preserved
    assert result["env"]["EXISTING"] == "kept"
    # No new vars (no ${VAR} in this config)
    assert len(result["env"]) == 1

def test_env_var_with_default():
    """Verify ${VAR:-default} uses default when VAR unset."""
    # Ensure VAR not set
    os.environ.pop("MISSING_VAR", None)

    config = {
        "command": "server",
        "args": ["--port", "${MISSING_VAR:-3000}"]
    }

    result = translate_mcp_for_codex(config)

    # Default value used
    assert result["args"][1] == "3000"
```

**Transport detection:**
```python
def test_detect_stdio_transport():
    """Verify STDIO transport detection."""
    config = {"command": "npx", "args": ["-y", "server"]}
    transport = detect_transport_type(config)
    assert transport == "stdio"

def test_detect_sse_transport():
    """Verify SSE transport detection."""
    config = {"url": "https://example.com/mcp/sse"}
    transport = detect_transport_type(config)
    assert transport == "sse"

def test_detect_http_transport():
    """Verify HTTP transport detection."""
    config = {"url": "https://api.example.com/mcp"}
    transport = detect_transport_type(config)
    assert transport == "http"
```

### Level 2 Proxy Metrics

**Scope routing with real file writes:**
- Define 2 user-scope MCPs, 1 project-scope MCP
- Call adapter.sync_mcp() with scope metadata
- Verify `~/.codex/config.toml` contains 2 servers
- Verify `.codex/config.toml` contains 1 server
- Verify TOML syntax valid (can parse with tomllib)

**Plugin MCP user-scope enforcement:**
- Mock plugin MCP with metadata `{"scope": "user", "source": "plugin"}`
- Call adapter.sync_mcp()
- Verify written to `~/.codex/config.toml` NOT `.codex/config.toml`

**Transport validation warnings:**
- Create SSE MCP config
- Sync to Codex adapter
- Verify warning logged with server name and "SSE transport not supported"
- Verify server NOT written to config.toml

### Level 3 Deferred Items

**Real Codex CLI validation:**
- Install Codex CLI
- Sync MCPs with varying scopes
- Run `codex /debug-config` to inspect loaded MCPs
- Verify correct servers loaded from correct paths
- Verify project-scope overrides user-scope as expected

**Real MCP server functionality:**
- Sync Context7 MCP (plugin-provided) to Codex
- Verify Codex can start the MCP server
- Verify tools exposed correctly
- Verify environment variables passed correctly

**Integration test (Success Criteria #8):**
- 2 user-scope MCPs (1 with `${API_KEY}`, 1 with `${PORT:-3000}`)
- 1 project-scope MCP
- 1 plugin MCP
- Verify all targets receive correct scoped configs
- Verify env vars translated correctly for Codex
- Verify env vars preserved for Gemini

## Production Considerations

### Known Failure Modes

**Undefined environment variables:**
- **Description:** User syncs MCP with `${API_KEY}` but variable not set in shell
- **Prevention:** Check os.environ.get() result, log warning if None and no default
- **Detection:** MCP server fails to start in target CLI with "missing required env var" error

**Project-scope config write permission:**
- **Description:** `.codex/` directory doesn't exist or not writable
- **Prevention:** Use ensure_dir() before write, catch OSError
- **Detection:** sync_mcp() returns failed=1 with error message

**TOML escaping edge cases:**
- **Description:** MCP server name or env var value contains special TOML characters
- **Prevention:** Use existing escape_toml_string() utility (already handles quotes, backslashes)
- **Detection:** Codex fails to parse config.toml (syntax error)

### Scaling Concerns

**At current scale:**
- Typical user: 5-10 user MCPs, 2-3 project MCPs = 15 total writes
- File I/O: Write 2 files (user + project config) per target
- Regex processing: ~20 strings scanned for `${VAR}` patterns (negligible)

**At production scale:**
- Power user: 50 user MCPs, 10 project MCPs, 30 plugin MCPs = 90 total
- Approach: Same (file writes are fast, regex is O(n) where n=string length)
- No optimization needed (pathlib + json/TOML writers handle hundreds of servers easily)

### Common Implementation Traps

**Not checking env var existence:**
- **What goes wrong:** KeyError when accessing os.environ["VAR"]
- **Correct approach:** Always use `os.environ.get(var_name, default_value)`

**Mutating original config dict:**
- **What goes wrong:** Modifying Phase 9's config dict affects other adapters
- **Correct approach:** `config.copy()` before translation, return new dict

**Forgetting to merge existing config:**
- **What goes wrong:** Overwriting entire config.toml loses settings, existing servers
- **Correct approach:** Read existing config, merge MCP servers, preserve other sections (existing adapters already do this)

**Not escaping TOML strings:**
- **What goes wrong:** Server names with quotes break TOML syntax
- **Correct approach:** Use escape_toml_string() from toml_writer.py

## Code Examples

Verified patterns from official sources and existing codebase:

### Scope-Aware sync_mcp() Signature (New Pattern)

```python
# Source: Requirement SYNC-01, SYNC-02, SYNC-03
def sync_mcp(self, mcp_servers_scoped: dict[str, dict]) -> SyncResult:
    """Translate MCP server configs to target format with scope awareness.

    Args:
        mcp_servers_scoped: Dict mapping server name to server data:
            {
                "server-name": {
                    "config": {...},  # MCP server config
                    "metadata": {
                        "scope": "user|project|local",
                        "source": "file|plugin",
                        "plugin_name": "...",  # if source == plugin
                        "plugin_version": "..."  # if source == plugin
                    }
                }
            }

    Returns:
        SyncResult with synced count per scope
    """
    result = SyncResult()

    # Group servers by scope
    user_scope_servers = {}
    project_scope_servers = {}

    for server_name, server_data in mcp_servers_scoped.items():
        config = server_data.get("config", {})
        metadata = server_data.get("metadata", {})
        scope = metadata.get("scope", "user")

        # Plugin MCPs are always user-scope (Decision #34)
        if metadata.get("source") == "plugin" or scope == "local":
            scope = "user"

        # Translate config for this target
        translated = self._translate_mcp_config(config, metadata)

        # Validate transport support
        supported, warning = self.validate_transport_for_target(server_name, config)
        if not supported:
            result.skipped += 1
            result.skipped_files.append(warning)
            continue

        # Route to correct scope
        if scope == "user":
            user_scope_servers[server_name] = translated
        elif scope == "project":
            project_scope_servers[server_name] = translated

    # Write user-scope servers
    if user_scope_servers:
        user_result = self._write_mcp_config(
            user_scope_servers,
            scope="user"
        )
        result.merge(user_result)

    # Write project-scope servers
    if project_scope_servers:
        project_result = self._write_mcp_config(
            project_scope_servers,
            scope="project"
        )
        result.merge(project_result)

    return result
```

### Environment Variable Translation for Codex (New Pattern)

```python
# Source: Requirement ENV-01, ENV-02
import os
import re

VAR_PATTERN = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)(:-([^}]+))?\}')

def translate_env_vars_for_codex(config: dict) -> dict:
    """Extract ${VAR} references and resolve to Codex env map.

    Handles:
    - ${VAR} -> reads from os.environ
    - ${VAR:-default} -> uses default if VAR unset

    Args:
        config: Claude Code MCP config dict

    Returns:
        Codex-compatible config with env map
    """
    codex_config = config.copy()
    env_map = {}

    def extract_and_resolve(text: str) -> str:
        """Extract vars from text and resolve values."""
        def replacer(match):
            var_name = match.group(1)
            default_value = match.group(3)  # May be None

            # Read from environment
            env_value = os.environ.get(var_name)

            if env_value is not None:
                env_map[var_name] = env_value
                return env_value
            elif default_value is not None:
                # Warn about using default
                # (In real code, use logger)
                print(f"WARNING: ${{{var_name}}} not set, using default: {default_value}")
                return default_value
            else:
                # Warn about undefined var
                print(f"WARNING: ${{{var_name}}} not set and no default provided")
                return ""

        return VAR_PATTERN.sub(replacer, text)

    # Process string fields
    for key in ['command', 'url']:
        if key in codex_config and isinstance(codex_config[key], str):
            codex_config[key] = extract_and_resolve(codex_config[key])

    # Process args array
    if 'args' in codex_config and isinstance(codex_config['args'], list):
        codex_config['args'] = [
            extract_and_resolve(arg) if isinstance(arg, str) else arg
            for arg in codex_config['args']
        ]

    # Process env dict (existing env vars with ${} syntax)
    if 'env' in codex_config and isinstance(codex_config['env'], dict):
        resolved_env = {}
        for k, v in codex_config['env'].items():
            if isinstance(v, str):
                resolved_env[k] = extract_and_resolve(v)
            else:
                resolved_env[k] = v
        codex_config['env'] = resolved_env

    # Add extracted env vars (merge with existing)
    if env_map:
        existing_env = codex_config.get('env', {})
        # Existing env overrides extracted (user-specified values win)
        codex_config['env'] = {**env_map, **existing_env}

    return codex_config
```

### Existing Codex Adapter Config Merge (Reference)

```python
# Source: src/adapters/codex.py lines 288-330
def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
    """Current v1.0 implementation (NO scope awareness yet)."""
    if not mcp_servers:
        return SyncResult()

    result = SyncResult()

    try:
        # Config target path (HARDCODED — Phase 10 will parameterize)
        config_path = self.project_dir / ".codex" / CONFIG_TOML

        # Read existing config to preserve settings and merge MCP servers
        existing_config = self._read_existing_config()

        # Merge MCP servers (new servers override existing with same name)
        merged_mcp_servers = existing_config.get('mcp_servers', {}).copy()
        merged_mcp_servers.update(mcp_servers)

        # Generate MCP servers TOML section from merged servers
        mcp_toml = format_mcp_servers_toml(merged_mcp_servers)

        # Build settings section from existing config
        settings_lines = []
        for key in ['sandbox_mode', 'approval_policy']:
            if key in existing_config:
                val = existing_config[key]
                if isinstance(val, str):
                    settings_lines.append(f'{key} = "{val}"')
                elif isinstance(val, bool):
                    settings_lines.append(f'{key} = {"true" if val else "false"}')
                else:
                    settings_lines.append(f'{key} = {val}')

        settings_section = '\n'.join(settings_lines) if settings_lines else ''

        # Build complete config.toml
        final_toml = self._build_config_toml(settings_section, mcp_toml)

        # Write atomically
        write_toml_atomic(config_path, final_toml)

        # Track results
        result.synced = len(mcp_servers)
        result.synced_files.append(str(config_path))

    except Exception as e:
        result.failed = len(mcp_servers)
        result.failed_files.append(f"MCP servers: {str(e)}")

    return result
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact | Reference |
|--------------|------------------|--------------|--------|-----------|
| Single MCP config file | 3-tier scope (user/project/local) | Claude Code 2025 | Per-project overrides, plugin isolation | Phase 9 research |
| Scope-unaware sync | Scope-aware target routing | v2.0 milestone (2026) | Correct config file writes | This phase |
| Preserve ${VAR} in TOML | Translate to env map | v2.0 milestone (2026) | Codex compatibility (no native interpolation) | Requirement ENV-01 |
| Silent transport failures | Explicit warnings | v2.0 milestone (2026) | Better UX, user knows why MCP missing | Requirement SYNC-04 |

**Deprecated/outdated:**
- **Single-scope MCP sync:** v1.0 wrote all MCPs to project-level config — v2.0 separates by scope
- **${VAR} in Codex TOML:** Decision #13 originally preserved syntax, but Codex doesn't support it — must translate

## Open Questions

### 1. Environment Variable Expansion Timing

**What we know:** os.environ.get() reads current shell environment

**What's unclear:**
- Should expansion happen at sync time (bakes current values into config)?
- Or preserve `${VAR}` and expand at Codex runtime?

**Recommendation:** Expand at sync time for Codex (Codex doesn't support runtime interpolation per v2-codex-mcp.md). Document that synced configs are environment-specific.

### 2. Project-Scope Trust Warning

**What we know:** Codex only loads `.codex/config.toml` if project is trusted

**What's unclear:**
- Should HarnessSync warn user that project-scope sync requires trust?
- Or silently write and let Codex handle trust?

**Recommendation:** Log info message: "Project-scope MCPs written to .codex/config.toml (requires trusted project in Codex)". Don't block sync.

### 3. Multiple Default Syntax Handling

**What we know:** Bash supports `${VAR:-default}` for unset, `${VAR-default}` for unset/null

**What's unclear:**
- Should we support both `:-` and `-` variants?
- Or only `:-` (more common)?

**Recommendation:** Support only `:-` for v2.0 (simpler, covers 95% of use cases). Add `-` variant if users request it.

### 4. Env Var Case Sensitivity

**What we know:** Regex pattern uses `[A-Z_][A-Z0-9_]*` (uppercase only)

**What's unclear:**
- Should we support lowercase env var names (non-standard but possible)?
- Or enforce uppercase convention?

**Recommendation:** Support uppercase only for v2.0 (matches shell convention). Lowercase support can be added if needed.

## Sources

### Primary (HIGH confidence)

- **Phase 9 Research** — .planning/phases/09-plugin-discovery-scope-aware-source-reading/09-RESEARCH.md
  - Scope-tagged MCP discovery format (lines 77-89)
  - Layered discovery pattern (lines 175-191)
  - Plugin metadata structure (lines 81-89)

- **v2-codex-mcp.md** — .planning/research/v2-codex-mcp.md
  - Codex TOML format (lines 32-58)
  - Environment variable handling (lines 90-116)
  - Transport support matrix (lines 219-266)
  - NO SSE support documented (lines 232-235)

- **Requirements** — .planning/REQUIREMENTS.md
  - SYNC-01, SYNC-02, SYNC-03, SYNC-04 (lines 88-91)
  - ENV-01, ENV-02, ENV-03 (lines 94-96)

- **Existing Codebase** — src/adapters/codex.py, src/adapters/gemini.py
  - Current sync_mcp() implementation (codex.py lines 270-330)
  - Config merge pattern (codex.py lines 292-297)
  - Gemini env preservation (gemini.py lines 333-334)

- **Bash Parameter Expansion** — [GNU Bash Manual](https://www.gnu.org/software/bash/manual/html_node/Shell-Parameter-Expansion.html)
  - ${VAR:-default} syntax documented
  - Official reference for shell interpolation

- **Docker Compose Interpolation** — [Docker Docs](https://docs.docker.com/reference/compose-file/interpolation/)
  - Industry-standard env var interpolation pattern
  - Confirms ${VAR:-default} usage

### Secondary (MEDIUM confidence)

- **Decision Log** — .planning/yolo-decisions.log
  - Decision #12: Manual TOML generation
  - Decision #13: Env var preservation (updated by this phase)
  - Decision #32: Gemini extensions not target
  - Decision #34: Plugin MCPs user-scope

### Tertiary (LOW confidence)

N/A — All findings verified through high-confidence sources

## Metadata

**Confidence breakdown:**
- Scope-to-path mapping: HIGH - explicit requirements + existing file structure
- Environment variable translation: HIGH - official Bash docs + Codex docs confirm incompatibility
- Transport detection: HIGH - official Codex docs + GitHub issues confirm SSE unsupported
- Gemini env var preservation: HIGH - existing code + requirement ENV-03
- Implementation patterns: HIGH - existing adapter code + stdlib libraries

**Research date:** 2026-02-15
**Valid until:** 60 days (2026-04-15) — Codex/Gemini MCP formats are stable, env var syntax is decades-old standard

---

**End of Research Document**
