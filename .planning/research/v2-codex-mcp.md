# Research: Codex MCP Configuration & Claude Code Plugin MCP Mechanisms

**Project:** HarnessSync v2.0 — Plugin & MCP Scope Sync
**Research focus:** Codex MCP format + Claude Code plugin MCP registration
**Researched:** 2026-02-15
**Overall confidence:** HIGH (official docs + verified examples)

---

## Executive Summary

This research establishes the foundation for v2.0's plugin/MCP scoping features:

1. **Codex MCP format is stable** (TOML-based, introduced Sept 2025) with comprehensive field support
2. **Claude Code has 3 MCP scopes** (user `~/.claude.json`, project `.mcp.json`, plugin-provided via `plugin.json` or `.mcp.json`)
3. **Critical gap discovered**: Codex only supports STDIO transport currently, not HTTP/SSE natively (needs npx wrapper or similar)
4. **Plugin MCP registration** is well-documented with `${CLAUDE_PLUGIN_ROOT}` variable support
5. **Environment variable handling** differs significantly between Codex and Claude Code

---

## 1. Codex MCP Server Configuration Format

### 1.1 Current Format (2026)

**Location:**
- User-level: `~/.codex/config.toml` (default)
- Project-level: `.codex/config.toml` (trusted projects only)

**CRITICAL:** Section name MUST be `[mcp_servers]` with underscore, not `[mcp-servers]` (silently ignored if wrong)

### 1.2 Complete TOML Schema

```toml
[mcp_servers.server_name]
# STDIO transport (local subprocess)
command = "npx"                           # Required for stdio servers
args = ["-y", "@package/mcp-server"]      # Command arguments
cwd = "/path/to/working/directory"        # Working directory for process
env = { KEY = "value" }                   # Literal environment variables
env_vars = ["ALLOWED_VAR1", "VAR2"]       # Whitelist additional env vars from shell

# HTTP transport (remote server)
url = "https://api.example.com/mcp"       # Required for HTTP servers
http_headers = { Authorization = "Bearer token" }  # Static HTTP headers
env_http_headers = { "X-API-Key" = "API_KEY_ENV_VAR" }  # Headers from env vars
bearer_token_env_var = "TOKEN_ENV_VAR"    # Env var name for bearer token

# Common settings
enabled = true                            # Enable/disable without removing config
required = false                          # Fail startup if server can't initialize
startup_timeout_sec = 10                  # Override default 10s startup timeout
tool_timeout_sec = 60                     # Override default 60s per-tool timeout

# Tool filtering
enabled_tools = ["tool1", "tool2"]        # Allowlist of exposed tools
disabled_tools = ["restricted_tool"]      # Denylist applied after allowlist
```

### 1.3 Example Configurations

**STDIO server with environment variables:**
```toml
[mcp_servers.github]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]
env = { "GITHUB_TOKEN" = "ghp_xxxxx" }    # Literal value
enabled = true
required = false
```

**HTTP server with authentication:**
```toml
[mcp_servers.sentry]
url = "https://mcp.sentry.dev/mcp"
bearer_token_env_var = "SENTRY_TOKEN"     # References shell env var name
http_headers = { "User-Agent" = "Codex/1.0" }
enabled = true
```

**Tool filtering example:**
```toml
[mcp_servers.restricted_api]
command = "python"
args = ["/usr/local/bin/api-server.py"]
enabled_tools = ["read_data", "search"]   # Only expose these tools
disabled_tools = ["delete_data"]          # Block dangerous operations
```

### 1.4 Environment Variable Handling in Codex

**CRITICAL DISTINCTION:**

1. **`env` field** — Literal values (map of strings)
   ```toml
   env = { "API_KEY" = "abc123", "DEBUG" = "true" }
   ```
   - Values are passed as-is to the MCP server process
   - No variable interpolation

2. **`env_vars` field** — Whitelist of shell env var names
   ```toml
   env_vars = ["GITHUB_TOKEN", "HOME"]
   ```
   - Codex reads these var names from shell environment
   - Values are passed to MCP server process

3. **Fields ending in `_env_var`** — Reference to env var name
   ```toml
   bearer_token_env_var = "SENTRY_TOKEN"
   ```
   - Codex looks up `SENTRY_TOKEN` from shell environment
   - Uses value for authentication

**WARNING:** Never use `${VAR}` interpolation syntax in `config.toml`. Not supported in Codex.

---

## 2. Codex MCP Format Changes (2025-2026)

### 2.1 Introduction Timeline

**September 2025:** MCP support introduced to Codex CLI
- Initial TOML-based configuration
- STDIO transport support
- Basic HTTP server support (via streamable-http)

### 2.2 Notable Updates (Changelog Analysis)

**Late 2025:**
- ✅ Required MCP servers now fail fast during startup (breaking change: no silent failures)
- ✅ Process-group cleanup for stdio servers (prevents orphan processes)
- ✅ Session-scoped "Allow and remember" for tool approvals (UX improvement)
- ✅ Apps config integration (`app_servers` in `config.toml`)

**Early 2026:**
- ✅ Dynamic tool validation removed (chore: performance optimization)
- ✅ `/debug-config` command added (inspect effective configuration)

### 2.3 Stable Fields (No Changes Since Sept 2025)

The core MCP server configuration schema (`command`, `args`, `env`, `url`, `enabled`, `required`, timeouts) has been stable since introduction. New fields added:
- `enabled_tools` / `disabled_tools` (tool filtering)
- `env_vars` (environment variable whitelisting)

### 2.4 Confidence Assessment

**HIGH confidence** — Format is stable, well-documented, and no breaking changes to core schema since introduction.

---

## 3. Codex Project-Level MCP Configuration

### 3.1 Project Scope Support

**YES** — Codex supports project-level MCP configs via `.codex/config.toml`

**Location:** `.codex/config.toml` in project root

**Security restriction:** Only loaded when project is trusted

### 3.2 Configuration Resolution Order

Codex resolves values with this precedence (highest first):
1. Project config files: `.codex/config.toml` (closest to CWD wins)
2. User config: `~/.codex/config.toml`

Multiple `.codex/config.toml` files can exist in nested directories. Codex walks from project root to CWD and loads every file, with closest to CWD winning for conflicts.

### 3.3 Path Resolution

Relative paths in project config (e.g., `command = "./scripts/server.py"`) are resolved relative to the `.codex/` folder containing the config.

### 3.4 Implications for HarnessSync

**Strategy for v2.0:**
- Sync to user-level `~/.codex/config.toml` by default (current behavior)
- Add flag for project-level sync to `.codex/config.toml`
- Warn that project-level requires trusted project status
- Use `write_toml_atomic` to merge with existing config (preserve non-MCP settings)

---

## 4. Codex MCP Server Discovery & Runtime Loading

### 4.1 Discovery Mechanism

**Automatic discovery on startup:**
1. Codex reads `config.toml` (user-level and project-level)
2. Parses `[mcp_servers.*]` sections
3. Filters by `enabled = true` (default)
4. Starts all enabled servers

**No dynamic discovery** — Changes to `config.toml` require Codex restart

### 4.2 Startup Process

For each enabled MCP server:
1. Launch subprocess (stdio) or connect to URL (HTTP)
2. Wait up to `startup_timeout_sec` (default 10s)
3. If `required = true` and server fails: **abort Codex startup**
4. If `required = false` and server fails: log warning, continue
5. Expose server tools to Codex agent loop

### 4.3 Runtime Behavior

**Tools available immediately:** Once started, MCP tools appear alongside built-in Codex tools

**Tool filtering applied:** Only `enabled_tools` are exposed (if specified), minus `disabled_tools`

**Process lifecycle:**
- STDIO servers: child processes of Codex CLI
- HTTP servers: external services (Codex is client)

**No hot-reload** — Config changes require restart

---

## 5. Codex Supported MCP Transport Types

### 5.1 Current Support (2026)

**STDIO** ✅ — Full support
- Local subprocess communication
- Primary transport for Codex
- Example: `command = "npx"`, `args = ["-y", "@package/server"]`

**HTTP (Streamable HTTP)** ✅ — Full support (as of 2026)
- Remote server communication
- Example: `url = "https://mcp.example.com"`

**SSE (Server-Sent Events)** ❌ — NOT natively supported
- [GitHub Issue #2129](https://github.com/openai/codex/issues/2129): "Native SSE transport support for MCP servers"
- Workaround: Use npx wrapper or proxy

**WebSocket** ⚠️ — Limited (experimental)
- App-server websocket transport reintroduced in late 2025
- Not documented for general MCP server use

### 5.2 MCP Protocol Evolution Context

**Historical timeline:**
- MCP originally used SSE for remote transport
- Protocol version 2026-03-26 deprecated SSE in favor of Streamable HTTP
- Codex adopted Streamable HTTP directly, skipping SSE support

### 5.3 Implications for HarnessSync

**Claude Code → Codex translation challenges:**

| Claude Code Config | Codex Support | Translation Strategy |
|-------------------|---------------|---------------------|
| `"command": "npx ..."` | ✅ STDIO | Direct translation to TOML |
| `"url": "http://..."` | ✅ HTTP | Direct translation to TOML `url` field |
| SSE transport | ❌ NOT SUPPORTED | Skip with warning, or use npx wrapper |

**Current HarnessSync v1.0 behavior:**
- Translates `command` → TOML `[mcp_servers.name]` with `command`/`args`
- Translates `env` → TOML `env` map
- ✅ **No changes needed** — v1.0 already handles STDIO correctly

**Gap for v2.0:**
- Need to detect if Claude Code MCP uses unsupported transport (SSE)
- Warn user or auto-adapt (e.g., suggest npx wrapper)

---

## 6. Codex Plugins/Extensions Beyond MCP

### 6.1 Skills: Primary Extension Mechanism

**Skills are Codex's plugin system** (NOT MCP-based)

**Location:**
- Repository-level: `.agents/skills/`
- User-level: `~/.codex/skills/`
- System-level: `/usr/local/share/codex/skills/`

**Format:**
- Directory with `SKILL.md` file
- Optional scripts, resources, config files

**Features:**
- Automatically discovered on startup
- Live skill update detection (no restart needed)
- Can declare MCP server dependencies
- Implicit invocation when description matches user prompt

**Example structure:**
```
.agents/skills/
├── my-skill/
│   ├── SKILL.md          # Skill instructions
│   ├── config.json       # Optional configuration
│   └── scripts/          # Optional automation
```

### 6.2 Apps (Experimental)

**Apps SDK integration** (experimental feature, 2025-2026)
- JSON-RPC protocol for external app integration
- Configured in `config.toml` under `[app_servers]` (separate from MCP)
- Feature-flag gated (`experimental_apps`)

### 6.3 No Plugin Registry

**Codex does NOT have:**
- Plugin marketplace (like Claude Code)
- Plugin installation commands
- `.claude-plugin/plugin.json` equivalent

**Extension distribution:**
- Skills shared via git repos
- MCP servers distributed as npm packages or docker containers

### 6.4 Implications for HarnessSync v2.0

**CANNOT map Claude Code plugins to Codex plugins** — fundamentally different systems

**Strategy:**
1. Map Claude Code **skills** → Codex skills (already done in v1.0)
2. Map Claude Code **plugin-provided MCP servers** → Codex `[mcp_servers]` (NEW for v2.0)
3. Map Claude Code **agents** → Codex skills with agent prefix (already done in v1.0)
4. **Commands** → Codex skills with cmd prefix (already done in v1.0)

---

## 7. Claude Code Plugin Installation & Discovery

### 7.1 Plugin Cache Directory

**Location:** `~/.claude/plugins/cache/`

**Structure:**
```
~/.claude/plugins/cache/
├── marketplace-name/
│   └── plugin-name/
│       └── version-or-commit/
│           ├── .claude-plugin/
│           │   └── plugin.json
│           ├── commands/
│           ├── agents/
│           ├── skills/
│           └── .mcp.json (optional)
```

**Installation process:**
1. Plugin source resolved from marketplace entry
2. Files copied to cache directory (not used in-place)
3. Symlinks honored during copy
4. Path traversal outside plugin root not allowed

### 7.2 installed_plugins.json Format

**Location:** `~/.claude/plugins/installed_plugins.json`

**Schema:**
```json
{
  "version": 2,
  "plugins": {
    "plugin-name@marketplace-name": [
      {
        "scope": "user",  // or "project", "local"
        "installPath": "/Users/.../plugins/cache/.../plugin-name/version",
        "version": "1.0.0",
        "installedAt": "2026-01-12T01:15:21.006Z",
        "lastUpdated": "2026-01-12T01:15:21.006Z",
        "projectPath": "/path/to/project",  // only for project scope
        "gitCommitSha": "abc123"  // for git sources
      }
    ]
  }
}
```

**Key fields:**
- `scope`: Installation scope (user/project/local)
- `installPath`: Absolute path to cached plugin
- `projectPath`: Required for project-scoped plugins
- `gitCommitSha`: For git-based plugins, tracks version

### 7.3 Plugin Discovery Process

**On Claude Code startup:**
1. Read `installed_plugins.json` for installed plugin list
2. Check enabled plugins in `settings.json` (`enabledPlugins` field)
3. Load plugin manifests from cache directories
4. Discover components:
   - Commands from `commands/` directory
   - Agents from `agents/` directory
   - Skills from `skills/` directory
   - Hooks from `hooks/hooks.json` or `plugin.json`
   - MCP servers from `.mcp.json` or `plugin.json.mcpServers`

**Auto-discovery rules:**
- If `plugin.json` exists: use specified paths (or defaults)
- If no manifest: derive name from directory, discover default locations
- Components are namespaced: `plugin-name:component-name`

---

## 8. Claude Code MCP Server Scoping

### 8.1 Three MCP Scopes

| Scope | File Location | Visibility | Use Case |
|-------|--------------|------------|----------|
| **User** | `~/.claude.json` | All projects for this user | Personal utilities |
| **Project** | `.mcp.json` in project root | All team members | Shared team tools |
| **Local** | `~/.claude.json` under project path | You in this project only | Experimental configs |

**IMPORTANT:** "Local scope" for MCP differs from general local settings:
- MCP local: Stored in `~/.claude.json` under project path
- General local: Stored in `.claude/settings.local.json`

### 8.2 Configuration File Formats

**User/Local scope (`~/.claude.json`):**
```json
{
  "mcpServers": {
    "server-name": {
      "command": "npx",
      "args": ["-y", "@package/server"],
      "env": {
        "API_KEY": "${API_KEY}"
      }
    }
  }
}
```

**Project scope (`.mcp.json`):**
```json
{
  "mcpServers": {
    "team-server": {
      "command": "npx",
      "args": ["-y", "@company/mcp-server"],
      "env": {
        "DB_URL": "${DATABASE_URL}"
      }
    }
  }
}
```

### 8.3 Scope Hierarchy & Precedence

**Resolution order (highest priority first):**
1. Local scope (user + project path)
2. Project scope (`.mcp.json`)
3. User scope (`~/.claude.json` global)

**Conflict resolution:** If same server name exists at multiple scopes, local overrides project overrides user.

### 8.4 Environment Variable Expansion

**Supported syntax:**
- `${VAR}` — Expands to value of env var `VAR`
- `${VAR:-default}` — Uses `VAR` if set, otherwise `default`

**Expansion locations:**
- `command` field
- `args` array
- `env` object
- `url` field (for HTTP servers)
- `headers` object

**Example:**
```json
{
  "mcpServers": {
    "api-server": {
      "type": "http",
      "url": "${API_BASE_URL:-https://api.example.com}/mcp",
      "headers": {
        "Authorization": "Bearer ${API_KEY}"
      }
    }
  }
}
```

### 8.5 Security & Trust

**Project-scoped servers:**
- Require approval before first use
- Prompt: "This project wants to use MCP servers from `.mcp.json`. Allow?"
- Choice persisted per-project
- Reset with `claude mcp reset-project-choices`

---

## 9. Claude Code Plugin MCP Registration

### 9.1 Two Registration Methods

**Method 1: Standalone `.mcp.json` at plugin root**
```
my-plugin/
├── .claude-plugin/
│   └── plugin.json
├── .mcp.json          ← MCP servers here
├── commands/
└── agents/
```

**Method 2: Inline in `plugin.json`**
```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "mcpServers": {
    "plugin-server": {
      "command": "${CLAUDE_PLUGIN_ROOT}/servers/my-server",
      "args": ["--config", "${CLAUDE_PLUGIN_ROOT}/config.json"]
    }
  }
}
```

### 9.2 Plugin MCP Server Configuration Schema

**Identical to standard MCP config, plus `${CLAUDE_PLUGIN_ROOT}` support:**

```json
{
  "mcpServers": {
    "database-tools": {
      "command": "${CLAUDE_PLUGIN_ROOT}/servers/db-server",
      "args": ["--config", "${CLAUDE_PLUGIN_ROOT}/config.json"],
      "env": {
        "DB_PATH": "${CLAUDE_PLUGIN_ROOT}/data",
        "API_KEY": "${USER_API_KEY}"
      }
    },
    "remote-api": {
      "type": "http",
      "url": "https://api.company.com/mcp",
      "headers": {
        "Authorization": "Bearer ${PLUGIN_TOKEN}"
      }
    }
  }
}
```

### 9.3 `${CLAUDE_PLUGIN_ROOT}` Variable

**Purpose:** Resolve plugin-relative paths regardless of installation location

**Behavior:**
- Expands to absolute path of plugin cache directory
- Example: `/Users/user/.claude/plugins/cache/marketplace/plugin-name/version`
- Critical for portable plugin distribution

**Usage:**
```json
{
  "command": "${CLAUDE_PLUGIN_ROOT}/bin/server",
  "args": ["--data", "${CLAUDE_PLUGIN_ROOT}/data.db"],
  "env": {
    "CONFIG_PATH": "${CLAUDE_PLUGIN_ROOT}/config.yaml"
  }
}
```

### 9.4 Plugin MCP Server Lifecycle

**Automatic management:**
1. **Enable plugin** → Start all plugin MCP servers
2. **Disable plugin** → Stop all plugin MCP servers
3. **Update plugin** → Restart MCP servers (requires Claude Code restart)

**Important:** MCP server changes (enable/disable) require Claude Code restart

### 9.5 Plugin MCP Server Features

**Transport support:**
- ✅ STDIO (local subprocess)
- ✅ SSE (legacy remote)
- ✅ HTTP (streamable-http remote)

**Environment access:**
- Plugin servers access same shell environment as user-configured servers
- Can reference user env vars: `"env": { "KEY": "${USER_ENV_VAR}" }`

**Tool integration:**
- Plugin MCP tools appear alongside standard tools
- No visual distinction (seamless integration)
- Namespaced by server name, not plugin name

### 9.6 Viewing Plugin MCP Servers

**CLI command:**
```bash
claude mcp list
```

**TUI command:**
```
/mcp
```

**Output includes:**
- Server name
- Server type (stdio/http/sse)
- Source (user/project/plugin)
- Status (running/failed/disabled)

---

## 10. Key Differences: Codex vs Claude Code MCP

| Aspect | Codex | Claude Code |
|--------|-------|-------------|
| **Config format** | TOML (`config.toml`) | JSON (`.mcp.json`, `.claude.json`) |
| **Section name** | `[mcp_servers.name]` | `"mcpServers": { "name": ... }` |
| **Env var syntax** | `env = { "KEY" = "value" }` (literal) | `"env": { "KEY": "${VAR}" }` (interpolation) |
| **Env var expansion** | `env_vars = ["VAR"]` (whitelist) | `${VAR}` or `${VAR:-default}` |
| **Transport support** | STDIO, HTTP | STDIO, HTTP, SSE |
| **Project scope** | `.codex/config.toml` (trusted projects) | `.mcp.json` (all projects, approval required) |
| **Plugin integration** | N/A (no plugins) | `.mcp.json` or `plugin.json.mcpServers` |
| **Hot-reload** | ❌ Restart required | ✅ Dynamic with `list_changed` notifications |
| **Tool filtering** | `enabled_tools`, `disabled_tools` | Not in config (runtime only) |

---

## 11. Implications for HarnessSync v2.0

### 11.1 New Sync Requirements

**Plugin-provided MCP servers need special handling:**

1. **Detect plugin MCPs** in Claude Code source
   - Check `plugin.json.mcpServers` for each installed plugin
   - Check `.mcp.json` in plugin directories

2. **Translate to Codex TOML**
   - Convert `${CLAUDE_PLUGIN_ROOT}` references → absolute paths
   - Map env var syntax: `${VAR}` → `env_vars = ["VAR"]` whitelist
   - Skip SSE transport servers (warn user)

3. **Scope mapping strategy:**
   - Plugin MCPs → User-level Codex config (default)
   - OR: Create separate `.codex/config.toml` per account (multi-account support)

### 11.2 Translation Challenges

**Environment variable syntax:**
- Claude Code: `"API_KEY": "${API_KEY}"` (interpolation)
- Codex: `env_vars = ["API_KEY"]` (whitelist) OR `env = { "API_KEY" = "value" }` (literal)

**Strategy:** Detect `${VAR}` pattern, extract var name, add to `env_vars` array

**Plugin root paths:**
- Claude Code: `${CLAUDE_PLUGIN_ROOT}/bin/server`
- Codex: Expand to absolute path at sync time

**Strategy:** Resolve `${CLAUDE_PLUGIN_ROOT}` during sync, write absolute path to Codex config

### 11.3 Scope Sync Strategy

**Three-way mapping:**

| Claude Code Scope | Codex Target | Notes |
|------------------|--------------|-------|
| User (`~/.claude.json`) | User (`~/.codex/config.toml`) | Default behavior |
| Project (`.mcp.json`) | Project (`.codex/config.toml`) | Requires trusted project |
| Plugin (plugin-provided) | User (`~/.codex/config.toml`) | No Codex plugin equivalent |

### 11.4 Conflict Detection

**New drift detection needs:**
- Plugin MCP servers may change when plugin updates
- Need to track plugin version in state file
- Re-sync on plugin update

**State schema extension:**
```json
{
  "plugin_mcp_servers": {
    "plugin-name": {
      "version": "1.0.0",
      "servers": ["server1", "server2"],
      "last_synced": "2026-02-15T12:00:00Z"
    }
  }
}
```

### 11.5 User Experience

**New status information:**
```
/sync-status

MCP Servers:
  User scope: 3 servers
    - github (from Claude Code user config)
    - sentry (from Claude Code user config)
    - database-tools (from plugin: my-plugin v1.0.0)

  Plugin servers: 1 plugin
    - my-plugin v1.0.0: 1 server (database-tools)

  Last synced: 2 minutes ago
  Status: ✓ All synced
```

**New warnings:**
```
⚠ Plugin 'my-plugin' updated to v1.1.0 (was v1.0.0)
  Re-run /sync to update MCP server configs
```

---

## 12. Research Gaps & Open Questions

### 12.1 Resolved

✅ **Codex MCP format** — Fully documented
✅ **Claude Code plugin MCP registration** — Well-documented
✅ **Environment variable handling** — Clear distinction found
✅ **Scope hierarchy** — Documented for both systems

### 12.2 Remaining Questions (Low Priority)

❓ **Codex trust model for project configs** — How is project trust established? (CLI flag? Interactive prompt?)
❓ **Claude Code plugin update frequency** — How often do plugin MCP configs change in practice?
❓ **Performance impact** — How many MCP servers before startup time becomes issue?

**Recommendation:** Defer to user testing in v2.0 beta

---

## 13. Recommended v2.0 Approach

### 13.1 Phase 1: Plugin MCP Discovery

**Tasks:**
1. Extend `SourceReader` to discover plugin-provided MCP servers
2. Read `installed_plugins.json` for plugin list
3. For each enabled plugin, check:
   - `plugin.json.mcpServers` (inline)
   - `.mcp.json` in plugin cache directory
4. Track plugin version for drift detection

**Deliverables:**
- `SourceReader.discover_plugin_mcps() -> dict[str, dict]`
- Returns: `{ "plugin-name": { "version": "1.0.0", "servers": {...} } }`

### 13.2 Phase 2: Plugin MCP Translation

**Tasks:**
1. Extend `CodexAdapter.sync_mcp()` to handle plugin MCP servers
2. Resolve `${CLAUDE_PLUGIN_ROOT}` to absolute paths
3. Convert env var syntax: `${VAR}` → `env_vars` array
4. Skip SSE transport servers with warning
5. Add plugin source comment in TOML

**Example output:**
```toml
# Plugin: my-plugin v1.0.0 (synced by HarnessSync)
[mcp_servers.database_tools]
command = "/Users/user/.claude/plugins/cache/.../servers/db-server"
args = ["--config", "/Users/user/.claude/plugins/cache/.../config.json"]
env_vars = ["DB_URL"]  # from ${DB_URL}
enabled = true
```

### 13.3 Phase 3: Scope Sync

**Tasks:**
1. Add `--mcp-scope` flag to `/sync` command
2. Map Claude Code scopes to Codex scopes
3. Handle project-scope trust warning
4. Support multi-account MCP scoping

**User flow:**
```
/sync --mcp-scope project

⚠ Syncing MCP servers to project scope (.codex/config.toml)
  This requires the project to be trusted in Codex.
  Continue? (y/n)
```

### 13.4 Phase 4: Drift Detection

**Tasks:**
1. Extend `StateManager` to track plugin MCP state
2. Detect plugin version changes
3. Warn on plugin updates
4. Auto-sync on plugin enable/disable (hook)

---

## Sources

### Codex Documentation
- [Codex MCP Configuration Reference](https://developers.openai.com/codex/config-reference/)
- [Codex Config Basics](https://developers.openai.com/codex/config-basic/)
- [Codex Configuration Repository](https://github.com/openai/codex/blob/main/docs/config.md)
- [Codex MCP Setup Guide (Vladimir Siedykh)](https://vladimirsiedykh.com/blog/codex-mcp-config-toml-shared-configuration-cli-vscode-setup-2025)
- [Codex Changelog](https://developers.openai.com/codex/changelog/)
- [Codex Advanced Configuration](https://developers.openai.com/codex/config-advanced/)

### Claude Code Documentation
- [Claude Code MCP Documentation](https://code.claude.com/docs/en/mcp)
- [Claude Code Plugins Reference](https://code.claude.com/docs/en/plugins-reference)
- [Claude Code Settings](https://code.claude.com/docs/en/settings)

### GitHub Issues
- [Codex Issue #2129: Native SSE transport support for MCP servers](https://github.com/openai/codex/issues/2129)
- [Codex Issue #3441: Codex does not use MCP servers defined in config.toml](https://github.com/openai/codex/issues/3441)
- [Claude Code Issue #15308: --plugin-dir does not load MCP servers defined in plugin.json](https://github.com/anthropics/claude-code/issues/15308)

### Community Resources
- [MCP Transport Protocols: stdio vs SSE vs StreamableHTTP (MCPcat)](https://mcpcat.io/guides/comparing-stdio-sse-streamablehttp/)
- [Codex MCP configuration: using env vars the right way (JP Caparas)](https://jpcaparas.medium.com/codex-mcp-configuration-using-env-vars-the-right-way-164e8135aa77)
- [Configuring MCP Tools in Claude Code (Scott Spence)](https://scottspence.com/posts/configuring-mcp-tools-in-claude-code)

---

**End of Research Document**
