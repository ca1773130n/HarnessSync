# Gemini CLI Extensions System Research

**Researched:** 2026-02-15
**Focus:** Gemini CLI extension system for v2.0 milestone (Plugin & MCP Scope Sync)
**Overall Confidence:** HIGH

## Executive Summary

Gemini CLI has a well-defined **extension system** distinct from but complementary to MCP servers. Extensions are installed packages that can contain MCP servers, custom commands, skills, agents, hooks, and context files. They are **not the same concept** as Claude Code plugins, though they serve similar purposes.

**Key findings:**
1. Extensions are installed to `~/.gemini/extensions/` (user-level) or `<workspace>/.gemini/extensions/` (project-level)
2. Extension manifest is `gemini-extension.json` with fields for MCP servers, settings, context files, etc.
3. MCP servers can be defined in **either** extensions OR `settings.json` — settings.json takes precedence
4. Extensions support programmatic configuration via JSON, but installation is CLI-driven
5. February 2026 update added extension settings with automatic prompts on installation
6. User vs workspace scope is fully supported for both extensions and settings

**Claude Code plugin mapping:** Plugins don't directly translate to Gemini extensions. Instead:
- Plugin-bundled MCP servers → `settings.json` mcpServers (existing HarnessSync pattern)
- Plugin commands → Cannot sync (Gemini uses TOML commands in extensions)
- Plugin hooks → Cannot sync (different hook system)
- Plugin context → GEMINI.md (already synced by HarnessSync)

## 1. What is Gemini CLI's Extension System?

### Definition

Gemini CLI extensions are **packaged bundles** that can contain:
- MCP servers
- Custom commands (TOML format)
- Skills (SKILL.md files)
- Sub-agents (.md files)
- Hooks (hooks.json)
- Context files (GEMINI.md)
- Settings definitions (for user configuration)

Extensions are **separate from MCP servers** — an extension can bundle MCP servers, but MCP servers can also be configured independently in `settings.json`.

### Installation Methods

```bash
# From GitHub URL
gemini extensions install https://github.com/user/extension-name

# From local path
gemini extensions install /path/to/extension

# Noninteractive mode (for automation)
gemini extensions install <url> --non-interactive
```

**Discovery:** Gemini CLI automatically scans two locations on startup:
- **User-level:** `~/.gemini/extensions/` (available to all projects)
- **Workspace-level:** `<workspace>/.gemini/extensions/` (project-specific)

**Management commands:**
```bash
gemini extensions list                      # Show installed extensions
gemini extensions uninstall extension-name  # Remove extension
gemini extensions update extension-name     # Update to latest version
gemini extensions update --all              # Update all extensions
gemini extensions disable extension-name    # Disable at user level
gemini extensions disable extension-name --scope=workspace  # Disable for current workspace only
gemini extensions enable extension-name --scope=workspace   # Enable for current workspace
gemini extensions config                    # Manage extension settings
```

**Important:** Extensions require CLI restart to reflect management changes.

### Discovery Process

On startup, Gemini CLI:
1. Scans `~/.gemini/extensions/` for user-level extensions
2. Scans `<workspace>/.gemini/extensions/` for workspace-level extensions
3. Loads each extension's `gemini-extension.json` manifest
4. Merges MCP servers, commands, skills, hooks from all enabled extensions
5. Prompts for missing extension settings (if first run)

## 2. Extension Format and Directory Structure

### Extension Directory Structure

```
~/.gemini/extensions/my-extension/
├── gemini-extension.json     # REQUIRED manifest
├── GEMINI.md                 # Optional context file
├── .env                      # Extension settings storage
├── commands/                 # Optional custom commands
│   └── my-command.toml
├── hooks/
│   └── hooks.json            # Optional hooks definition
├── skills/                   # Optional skills
│   └── skill-name/
│       └── SKILL.md
├── agents/                   # Optional sub-agents
│   └── agent-name.md
└── [MCP server files]        # If extension bundles MCP server
    ├── package.json
    ├── tsconfig.json
    └── example.ts
```

**Key constraints:**
- Extension directory name MUST match the `name` field in `gemini-extension.json`
- Name must be lowercase/numbers with dashes (not underscores or spaces)
- `gemini-extension.json` is the only required file

### gemini-extension.json Manifest Format

```json
{
  "name": "my-extension",
  "version": "1.0.0",
  "description": "Brief overview displayed on geminicli.com/extensions",
  "contextFileName": "GEMINI.md",
  "excludeTools": ["dangerous_tool"],
  "mcpServers": {
    "server-name": {
      "command": "node",
      "args": ["${extensionPath}${/}run.ts"],
      "env": {
        "API_KEY": "${MY_API_KEY}"
      }
    }
  },
  "settings": [
    {
      "name": "API Key",
      "description": "Your API key for this service",
      "envVar": "MY_API_KEY",
      "sensitive": true
    },
    {
      "name": "Base URL",
      "description": "Base URL for the service",
      "envVar": "BASE_URL",
      "sensitive": false
    }
  ]
}
```

**Field descriptions:**

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `name` | string | YES | Extension identifier (must match directory name) |
| `version` | string | YES | Semantic version (e.g., "1.0.0") |
| `description` | string | NO | Short description for extension catalog |
| `contextFileName` | string | NO | Name of context file (defaults to GEMINI.md) |
| `excludeTools` | string[] | NO | Tool names to block from the model |
| `mcpServers` | object | NO | Map of MCP server configurations |
| `settings` | array | NO | User-provided configuration options |

**Variable substitution supported:**
- `${extensionPath}` — Full filesystem path to extension directory
- `${workspacePath}` — Current workspace path
- `${/}` or `${pathSeparator}` — OS-specific path separator

**MCP server precedence:** If both an extension and `settings.json` define the same MCP server name, **settings.json takes precedence**. Extensions cannot override user-level configurations.

### Extension Settings (New in February 2026)

Extensions can define settings that users are prompted to provide upon installation. Settings are specified in the `settings` array:

```json
{
  "settings": [
    {
      "name": "GitHub API Token",
      "description": "Personal access token for GitHub API",
      "envVar": "GITHUB_TOKEN",
      "sensitive": true
    }
  ]
}
```

**Setting object fields:**

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `name` | string | YES | User-friendly label for the setting |
| `description` | string | YES | Explanation of what this setting is for |
| `envVar` | string | YES | Environment variable name for storage |
| `sensitive` | boolean | NO | When true, masks input and stores in system keychain |

**Storage locations:**
- **Non-sensitive settings:** `~/.gemini/extensions/my-extension/.env` (or workspace equivalent)
- **Sensitive settings:** System keychain (macOS Keychain, Windows Credential Manager, Linux Secret Service)

**Configuration management:**
```bash
# Interactive configuration
gemini extensions config

# View settings for specific extension
gemini extensions settings list extension-name

# Settings respect user vs workspace scope
gemini extensions settings list extension-name --scope=workspace
```

**Automatic prompting:** When an extension is installed, users are automatically prompted to provide all required settings. This ensures the extension has what it needs to function from the first run.

## 3. Extensions vs MCP Servers: The Relationship

### Conceptual Difference

| Aspect | Extension | MCP Server |
|--------|-----------|------------|
| **Purpose** | Package multiple capabilities (MCP servers, commands, skills, etc.) | Provide tools/resources to the model via MCP protocol |
| **Installation** | `gemini extensions install` | Configured in `settings.json` or bundled in extension |
| **Scope** | User or workspace | User or workspace (via settings.json location) |
| **Contains** | Can bundle MCP servers, commands, skills, agents, hooks | Just the MCP server itself |
| **Discovery** | `~/.gemini/extensions/` | `settings.json` mcpServers object |

**Key insight:** Extensions are **wrappers** that can contain MCP servers. But MCP servers can also exist independently without being part of an extension.

### Configuration Precedence

When the same MCP server is defined in multiple places:

1. `settings.json` (user or workspace) — **HIGHEST PRECEDENCE**
2. Extension `gemini-extension.json` mcpServers
3. Default configuration (if any)

**Example scenario:**
```
Extension "my-ext" defines MCP server "github" with basic config
User settings.json ALSO defines MCP server "github" with custom API token
→ settings.json version wins (user settings take precedence)
```

This means HarnessSync's current approach of writing to `settings.json` is correct and will override any extension-bundled MCP servers with the same name.

### When to Use Each

**Use settings.json MCP servers when:**
- User wants direct control over MCP configuration
- Syncing from Claude Code (HarnessSync use case)
- No additional extension capabilities needed (commands, skills, etc.)

**Use extension-bundled MCP servers when:**
- Distributing a complete package (server + commands + context)
- Need version-locked server configuration
- Want to share reusable configurations with others

**For HarnessSync v2.0:** Continue using `settings.json` mcpServers. Extensions are a different concept that don't directly map to Claude Code plugins.

## 4. Claude Code Plugins → Gemini Extensions Mapping

### Direct Mapping: NOT POSSIBLE

Claude Code plugins and Gemini extensions have **fundamentally different architectures**:

| Claude Code Plugin | Gemini Extension | Can Sync? |
|-------------------|------------------|-----------|
| plugin.json manifest | gemini-extension.json manifest | NO (different schemas) |
| hooks/hooks.json (PostToolUse, etc.) | hooks/hooks.json (different events) | NO (incompatible hook systems) |
| commands/*.md (slash commands) | commands/*.toml (different format) | NO (format mismatch) |
| MCP servers in plugin | mcpServers in extension | MAYBE (but settings.json is better) |
| CLAUDE.md context | GEMINI.md context | YES (already synced by HarnessSync v1) |

### What Translates and What Doesn't

**Translates:**
- ✅ **Context files** — CLAUDE.md → GEMINI.md (HarnessSync v1 already does this)
- ✅ **Skills** — .claude/skills/ → inlined in GEMINI.md (HarnessSync v1 already does this)
- ✅ **Agents** — .claude/agents/ → inlined in GEMINI.md (HarnessSync v1 already does this)
- ✅ **MCP servers** — Plugin-bundled MCP servers → `settings.json` mcpServers (recommended approach)

**Does NOT translate:**
- ❌ **Plugin manifest** — Different schema, cannot auto-generate `gemini-extension.json`
- ❌ **Hooks** — Different hook event system, incompatible
- ❌ **Commands** — Different format (.md vs .toml), different execution model
- ❌ **Plugin settings** — Claude Code uses different settings model

### Recommended v2.0 Strategy

**DO NOT attempt to create Gemini extensions from Claude Code plugins.**

Instead, for v2.0 milestone:

1. **Continue syncing MCP servers to settings.json** (existing HarnessSync pattern)
   - Read Claude Code plugin's bundled MCP servers (if any)
   - Translate to `settings.json` mcpServers format
   - This works regardless of whether the MCP came from a plugin or user config

2. **Add scope awareness to MCP sync:**
   - User-level: `~/.gemini/settings.json`
   - Workspace-level: `.gemini/settings.json`
   - Match Claude Code's user vs project scope

3. **Document the limitation:**
   - HarnessSync syncs MCP servers from plugins
   - Does NOT convert plugins to extensions (architecturally incompatible)
   - User must manually create Gemini extensions if needed

### Why Not Generate Extensions?

**Technical barriers:**
1. **Hook incompatibility** — Claude Code PostToolUse hooks don't map to Gemini hook events
2. **Command format mismatch** — .md vs .toml, would require parsing Claude Code command markdown and translating to TOML (complex, error-prone)
3. **Manifest schema differences** — plugin.json and gemini-extension.json have different required fields and purposes
4. **Distribution model** — Claude Code plugins install from GitHub with plugin marketplace, Gemini extensions install from GitHub with extension catalog (different discovery mechanisms)

**Practical barriers:**
1. **Maintenance burden** — Auto-generated extensions would need updates whenever plugin changes
2. **User confusion** — Extensions would show up in `gemini extensions list` but be managed by HarnessSync (ownership unclear)
3. **Precedence conflicts** — settings.json takes precedence over extensions, so generated extensions would be overridden anyway

## 5. Programmatic Configuration

### Can Extensions be Configured Programmatically?

**YES, but with limitations.**

**What's programmatic:**
- ✅ Extension manifest (`gemini-extension.json`) is pure JSON
- ✅ Extension settings stored in `.env` files (key=value format)
- ✅ MCP servers defined in `gemini-extension.json` (JSON)
- ✅ Commands, skills, agents are files in subdirectories

**What requires CLI:**
- ❌ Installation (`gemini extensions install` CLI command required)
- ❌ Enabling/disabling extensions (CLI commands)
- ❌ First-time settings prompts (interactive)

### Programmatic Approaches

**Approach 1: Direct file manipulation (NOT RECOMMENDED)**

```python
# Theoretically possible but FRAGILE
extension_dir = Path.home() / ".gemini" / "extensions" / "my-extension"
extension_dir.mkdir(parents=True, exist_ok=True)

manifest = {
    "name": "my-extension",
    "version": "1.0.0",
    "mcpServers": {...}
}

(extension_dir / "gemini-extension.json").write_text(json.dumps(manifest))
```

**Problems:**
- Bypasses Gemini CLI's extension registry
- Extension may not be recognized until CLI restart
- No validation of manifest schema
- Settings not prompted/configured
- Breaking changes if Gemini CLI changes extension loading

**Approach 2: Use settings.json for MCP servers (RECOMMENDED)**

```python
# HarnessSync's current approach - CORRECT
settings_path = Path.home() / ".gemini" / "settings.json"
settings = read_json_safe(settings_path)

settings.setdefault("mcpServers", {})
settings["mcpServers"]["my-server"] = {
    "command": "node",
    "args": ["server.js"]
}

write_json_atomic(settings_path, settings)
```

**Advantages:**
- Official configuration method
- Takes precedence over extensions
- No CLI restart needed (reloaded on next session)
- Schema validated by Gemini CLI
- HarnessSync already uses this pattern

**For HarnessSync v2.0:** Continue using settings.json. Do not attempt to programmatically create extensions.

## 6. Directory Structure and File Paths

### User-Level Configuration

```
~/.gemini/
├── settings.json              # User-level MCP servers, tool config, etc.
├── GEMINI.md                  # Global context file
├── .env                       # User-level environment variables
├── extensions/                # User-level extensions
│   ├── extension-1/
│   │   ├── gemini-extension.json
│   │   ├── .env              # Extension-specific settings
│   │   ├── commands/
│   │   ├── skills/
│   │   └── agents/
│   └── extension-2/
│       └── gemini-extension.json
└── tmp/
    └── <project_hash>/
        └── shell_history      # Project-specific shell history
```

**Key paths:**
- **User settings:** `~/.gemini/settings.json`
- **User extensions:** `~/.gemini/extensions/`
- **User context:** `~/.gemini/GEMINI.md`
- **User env:** `~/.env` (fallback for all projects)

### Workspace-Level Configuration

```
<workspace>/
├── .gemini/
│   ├── settings.json          # Workspace-level MCP servers, tool config
│   ├── GEMINI.md              # Workspace context file
│   ├── .env                   # Workspace environment variables
│   ├── extensions/            # Workspace-level extensions
│   │   └── workspace-ext/
│   │       └── gemini-extension.json
│   ├── sandbox-macos-custom.sb  # Custom sandbox profile (macOS)
│   └── sandbox.Dockerfile     # Custom sandbox Dockerfile
└── .geminiignore              # File filtering rules
```

**Key paths:**
- **Workspace settings:** `.gemini/settings.json`
- **Workspace extensions:** `.gemini/extensions/`
- **Workspace context:** `.gemini/GEMINI.md`
- **Workspace env:** `.gemini/.env` (never excluded from context)

### Configuration Precedence

Settings are applied in this order (later overrides earlier):

1. Default hardcoded values
2. System defaults (`/etc/gemini-cli/system-defaults.json`)
3. **User settings** (`~/.gemini/settings.json`)
4. **Workspace settings** (`.gemini/settings.json`)
5. System settings (`/etc/gemini-cli/settings.json`)
6. Environment variables (`.env` files)
7. Command-line arguments

**For extensions:**
- User-level extensions enabled by default across all workspaces
- Workspace-level extensions only active in that workspace
- Extensions can be disabled per-workspace with `--scope=workspace` flag

## 7. Scope Support: User vs Project Level

### Extension Scope Behavior

**User-level extensions:**
```bash
# Install extension (user-level by default)
gemini extensions install https://github.com/user/extension

# Installed to: ~/.gemini/extensions/extension-name/
# Active in: ALL workspaces
```

**Workspace-level extensions:**
```bash
# Install to workspace (manual - copy to .gemini/extensions/)
# Or enable user extension only for workspace
gemini extensions enable extension-name --scope=workspace

# Installed to: <workspace>/.gemini/extensions/extension-name/
# Active in: ONLY this workspace
```

### MCP Server Scope

**User-level MCP servers:**
```json
// ~/.gemini/settings.json
{
  "mcpServers": {
    "global-server": {
      "command": "global-mcp-server"
    }
  }
}
```

**Workspace-level MCP servers:**
```json
// .gemini/settings.json
{
  "mcpServers": {
    "project-server": {
      "command": "project-mcp-server",
      "cwd": "${workspacePath}"
    }
  }
}
```

**Merging behavior:**
- Workspace settings **override** user settings for the same server name
- Different server names are **merged** (both active)

### Extension Settings Scope

**User-level settings:**
```bash
# Configure extension globally
gemini extensions config extension-name

# Stored in: ~/.gemini/extensions/extension-name/.env
# or system keychain (if sensitive)
```

**Workspace-level settings:**
```bash
# Configure extension for this workspace only
gemini extensions config extension-name --scope=workspace

# Stored in: <workspace>/.gemini/extensions/extension-name/.env
# or workspace-scoped keychain entry
```

**Precedence:** Workspace settings override user settings for the same extension.

### HarnessSync v2.0 Scope Strategy

**For MCP servers:**
1. Read Claude Code scope (user: `~/.mcp.json` vs project: `.mcp.json`)
2. Write to corresponding Gemini settings.json:
   - User scope: `~/.gemini/settings.json`
   - Project scope: `.gemini/settings.json`
3. Workspace settings will naturally override user settings (Gemini CLI's built-in precedence)

**Example:**
```python
# HarnessSync adapter logic
def get_gemini_settings_path(self, scope: str) -> Path:
    if scope == "user":
        return Path.home() / ".gemini" / "settings.json"
    else:  # project scope
        return self.project_dir / ".gemini" / "settings.json"

def sync_mcp(self, mcp_servers: dict[str, dict], scope: str) -> SyncResult:
    settings_path = self.get_gemini_settings_path(scope)
    settings = read_json_safe(settings_path)
    settings.setdefault("mcpServers", {})

    # Translate and merge MCP servers
    for name, config in mcp_servers.items():
        settings["mcpServers"][name] = self._translate_mcp_config(config)

    write_json_atomic(settings_path, settings)
    return SyncResult(synced=len(mcp_servers))
```

## 8. Changes Since Mid-2025

### Extension Settings (February 2026)

**What changed:**
- Extensions can now define `settings` array in `gemini-extension.json`
- Users are automatically prompted for settings during installation
- New `gemini extensions config` command for centralized settings management
- Sensitive settings automatically stored in system keychain
- Support for user vs workspace scope for extension settings

**Impact on HarnessSync:**
- No impact — HarnessSync doesn't generate extensions
- Awareness: If users manually install extensions, settings are prompted
- Documentation: Note that extension settings are separate from synced MCP servers

### FastMCP Integration (Late 2025 - Early 2026)

**What changed:**
- Gemini CLI now integrates with FastMCP (Python MCP server library)
- `fastmcp install gemini-cli` command installs local MCP servers
- Simplifies MCP server development for Python developers

**Impact on HarnessSync:**
- No impact — HarnessSync syncs MCP server configs, not server code
- Awareness: Users may have FastMCP-installed servers alongside synced ones
- Precedence: settings.json (synced by HarnessSync) takes precedence

### MCP Resource Support (v0.20.0+)

**What changed:**
- Users can discover and search MCP resources with `@` command
- Multi-file drag & drop support (auto-prefixes with `@`)
- MCP slash commands can run in non-interactive mode
- MCP loading indicators during startup

**Impact on HarnessSync:**
- No impact — These are runtime features, not configuration changes
- Benefit: Better user experience when using synced MCP servers

### Model Updates (v0.21.0 - v0.22.0)

**What changed:**
- Gemini 3 Flash and Gemini 3 Pro available
- Free tier access to Gemini 3 models (via Preview Features toggle)

**Impact on HarnessSync:**
- No impact — Model selection is runtime, not sync-time

### Custom Themes for Extensions (v0.28.0)

**What changed:**
- Extensions can contribute themes via `themes` property in manifest
- Themes automatically discovered and listed in `/theme` dialog

**Impact on HarnessSync:**
- No impact — Themes are extension feature, not sync target

## 9. Settings.json MCP Format (Detailed)

### Complete Field Reference

```json
{
  "mcpServers": {
    "server-name": {
      // TRANSPORT: Exactly ONE of these required
      "command": "string",              // Executable path for stdio
      "url": "string",                  // SSE endpoint URL
      "httpUrl": "string",              // HTTP streaming endpoint URL

      // STDIO-SPECIFIC OPTIONS (when using "command")
      "args": ["string"],               // Command-line arguments
      "cwd": "string",                  // Working directory
      "env": {                          // Environment variables
        "KEY": "value",                 // Supports ${VAR} and $VAR syntax
        "API_KEY": "${MY_API_KEY}"
      },

      // URL-SPECIFIC OPTIONS (when using "url" or "httpUrl")
      "headers": {                      // Custom HTTP headers
        "Authorization": "Bearer token",
        "X-Custom": "value"
      },
      "authProviderType": "string",     // "dynamic_discovery" | "google_credentials" | "service_account_impersonation"

      // OAUTH CONFIGURATION (for URL transports)
      "oauth": {
        "enabled": true,
        "clientId": "string",
        "clientSecret": "string",
        "authorizationUrl": "string",
        "tokenUrl": "string",
        "scopes": ["scope1", "scope2"],
        "redirectUri": "http://localhost:7777/oauth/callback"
      },

      // GOOGLE CLOUD AUTHENTICATION
      "targetAudience": "string",       // For service account impersonation
      "targetServiceAccount": "string", // Service account email

      // COMMON OPTIONS (all transports)
      "timeout": 600000,                // Milliseconds (default: 600000)
      "trust": false,                   // Bypass confirmations (default: false)
      "includeTools": ["tool1"],        // Allowlist of tool names
      "excludeTools": ["tool2"]         // Blocklist of tool names (takes precedence)
    }
  }
}
```

### Transport Type Examples

**Stdio (command-based):**
```json
{
  "mcpServers": {
    "local-python": {
      "command": "python",
      "args": ["-m", "my_mcp_server", "--port", "8080"],
      "cwd": "./mcp-servers/python",
      "env": {
        "DATABASE_URL": "${DB_CONNECTION_STRING}",
        "API_KEY": "${EXTERNAL_API_KEY}"
      },
      "timeout": 15000,
      "includeTools": ["safe_tool", "file_reader"]
    }
  }
}
```

**SSE (url):**
```json
{
  "mcpServers": {
    "remote-sse": {
      "url": "https://api.example.com/sse",
      "headers": {
        "Authorization": "Bearer ${API_TOKEN}"
      },
      "timeout": 5000
    }
  }
}
```

**HTTP Streaming (httpUrl):**
```json
{
  "mcpServers": {
    "remote-http": {
      "httpUrl": "http://localhost:3000/mcp",
      "headers": {
        "X-Custom-Header": "custom-value"
      }
    }
  }
}
```

**OAuth-enabled:**
```json
{
  "mcpServers": {
    "oauth-server": {
      "url": "https://api.example.com/sse",
      "oauth": {
        "enabled": true,
        "clientId": "your-client-id",
        "clientSecret": "${OAUTH_SECRET}",
        "authorizationUrl": "https://auth.example.com/oauth/authorize",
        "tokenUrl": "https://auth.example.com/oauth/token",
        "scopes": ["read", "write"]
      }
    }
  }
}
```

**Google Cloud with service account impersonation:**
```json
{
  "mcpServers": {
    "gcp-iap-server": {
      "url": "https://my-iap-service.run.app/sse",
      "authProviderType": "service_account_impersonation",
      "targetAudience": "YOUR_IAP_CLIENT_ID.apps.googleusercontent.com",
      "targetServiceAccount": "your-sa@your-project.iam.gserviceaccount.com"
    }
  }
}
```

### Tool Filtering

**includeTools (allowlist):**
```json
{
  "mcpServers": {
    "filtered-server": {
      "command": "node",
      "args": ["server.js"],
      "includeTools": ["safe_tool", "file_reader", "data_processor"]
    }
  }
}
```
Only the listed tools will be available from this server.

**excludeTools (blocklist):**
```json
{
  "mcpServers": {
    "filtered-server": {
      "command": "node",
      "args": ["server.js"],
      "excludeTools": ["dangerous_tool", "system_modifier"]
    }
  }
}
```
Listed tools will NOT be available to the model.

**Precedence:** If a tool appears in BOTH `includeTools` and `excludeTools`, it will be **excluded** (blocklist wins).

### Environment Variable Syntax

Gemini CLI supports two syntaxes for environment variable references:

```json
{
  "mcpServers": {
    "example": {
      "command": "node",
      "env": {
        "VAR1": "$MY_VAR",           // Shell-style
        "VAR2": "${MY_VAR}",         // Brace-style
        "VAR3": "${MY_VAR:-default}" // With default value
      }
    }
  }
}
```

**Resolution order:**
1. Current directory `.env`
2. Parent directories (up to workspace root or home)
3. `~/.env` (user-level fallback)
4. System environment variables

**HarnessSync translation:** Preserve `${VAR}` syntax literally — Gemini CLI expands at runtime, not sync time.

## 10. HarnessSync v2.0 Implementation Recommendations

### What to Sync (v2.0 Scope)

**IN SCOPE:**
1. ✅ MCP servers from Claude Code plugins → Gemini `settings.json` mcpServers
2. ✅ Scope awareness (user vs project) for MCP servers
3. ✅ Environment variable references preserved (${VAR} syntax)
4. ✅ Transport type detection (stdio vs URL) and translation

**OUT OF SCOPE:**
1. ❌ Generating Gemini extensions from Claude Code plugins (architecturally incompatible)
2. ❌ Syncing Claude Code plugin commands to Gemini extension commands (format mismatch)
3. ❌ Syncing Claude Code plugin hooks to Gemini hooks (different event systems)
4. ❌ Managing extension installation/configuration (CLI-only operations)

### Adapter Enhancement Strategy

**Extend GeminiAdapter with scope support:**

```python
class GeminiAdapter(AdapterBase):
    def __init__(self, project_dir: Path, scope: str = "project"):
        """Initialize Gemini adapter with scope awareness.

        Args:
            project_dir: Root directory of the project being synced
            scope: "user" or "project" scope for configuration
        """
        super().__init__(project_dir)
        self.scope = scope

        # Set settings.json path based on scope
        if scope == "user":
            self.settings_path = Path.home() / ".gemini" / "settings.json"
        else:  # project scope
            self.settings_path = project_dir / ".gemini" / "settings.json"

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """Translate MCP server configs to Gemini settings.json.

        Now scope-aware: writes to user or project settings.json.
        """
        if not mcp_servers:
            return SyncResult()

        result = SyncResult()

        try:
            # Read existing settings.json
            existing_settings = read_json_safe(self.settings_path)
            existing_settings.setdefault('mcpServers', {})

            # Translate each MCP server
            for server_name, config in mcp_servers.items():
                server_config = {}

                # Stdio transport (has "command" key)
                if 'command' in config:
                    server_config['command'] = config['command']
                    if 'args' in config:
                        server_config['args'] = config['args']
                    if 'env' in config:
                        server_config['env'] = config['env']
                    if 'timeout' in config:
                        server_config['timeout'] = config['timeout']

                # URL transport (has "url" key)
                elif 'url' in config:
                    url = config['url']
                    # Detect SSE vs HTTP based on URL
                    if url.endswith('/sse') or 'sse' in url.lower():
                        server_config['url'] = url
                    else:
                        server_config['httpUrl'] = url

                    if 'headers' in config:
                        server_config['headers'] = config['headers']

                else:
                    # Skip servers without command or url
                    continue

                # Add to mcpServers (override if exists)
                existing_settings['mcpServers'][server_name] = server_config
                result.synced += 1

            # Write atomically
            write_json_atomic(self.settings_path, existing_settings)
            result.synced_files.append(str(self.settings_path))

        except Exception as e:
            result.failed = len(mcp_servers)
            result.failed_files.append(f"MCP servers: {str(e)}")

        return result
```

### Reading Plugin-Bundled MCP Servers

**Source detection:**

```python
# In SourceReader class
def discover_plugin_mcp_servers(self, plugin_dir: Path) -> dict[str, dict]:
    """Discover MCP servers bundled in Claude Code plugins.

    Args:
        plugin_dir: Path to plugin directory (e.g., ~/.claude/plugins/my-plugin)

    Returns:
        Dict mapping server name to server config
    """
    plugin_json = plugin_dir / "plugin.json"
    if not plugin_json.exists():
        return {}

    try:
        plugin_config = json.loads(plugin_json.read_text(encoding='utf-8'))

        # Check if plugin bundles MCP servers
        mcp_servers = plugin_config.get("mcp", {})

        # Return server configs
        return mcp_servers

    except (json.JSONDecodeError, OSError):
        return {}

def discover_all_mcp_sources(self, scope: str) -> dict[str, dict]:
    """Discover MCP servers from all sources (user config + plugins).

    Args:
        scope: "user" or "project"

    Returns:
        Merged dict of all MCP servers
    """
    all_servers = {}

    # 1. Read from .mcp.json (existing logic)
    mcp_json = self._get_mcp_json_path(scope)
    if mcp_json.exists():
        user_servers = json.loads(mcp_json.read_text(encoding='utf-8'))
        all_servers.update(user_servers)

    # 2. Read from installed plugins
    plugins_dir = self.cc_home / "plugins" if scope == "user" else self.project_dir / ".claude" / "plugins"

    if plugins_dir.exists():
        for plugin_dir in plugins_dir.iterdir():
            if plugin_dir.is_dir():
                plugin_servers = self.discover_plugin_mcp_servers(plugin_dir)
                # Merge, with .mcp.json taking precedence
                for name, config in plugin_servers.items():
                    if name not in all_servers:
                        all_servers[name] = config

    return all_servers
```

### Scope Detection Logic

```python
# In SyncOrchestrator
def sync_all_with_scope(self) -> dict[str, SyncResult]:
    """Sync all targets with scope awareness."""
    results = {}

    # Determine scopes to sync
    scopes = []
    if self._has_user_config():
        scopes.append("user")
    if self._has_project_config():
        scopes.append("project")

    # Sync each scope separately
    for scope in scopes:
        # Discover MCP servers for this scope
        mcp_servers = self.source_reader.discover_all_mcp_sources(scope)

        # Sync to each target with scope awareness
        for adapter_name in ["codex", "gemini", "opencode"]:
            adapter = self._create_adapter(adapter_name, scope)
            result = adapter.sync_mcp(mcp_servers)
            results[f"{adapter_name}_{scope}"] = result

    return results

def _has_user_config(self) -> bool:
    """Check if user-level config exists."""
    user_mcp = Path.home() / ".mcp.json"
    user_claude = Path.home() / ".claude"
    return user_mcp.exists() or user_claude.exists()

def _has_project_config(self) -> bool:
    """Check if project-level config exists."""
    project_mcp = self.project_dir / ".mcp.json"
    project_claude = self.project_dir / ".claude"
    return project_mcp.exists() or project_claude.exists()
```

### Verification Checklist

**Level 1 (Sanity):**
- [ ] User-level MCP servers sync to `~/.gemini/settings.json`
- [ ] Project-level MCP servers sync to `.gemini/settings.json`
- [ ] Plugin-bundled MCP servers detected and synced
- [ ] Environment variable syntax preserved (${VAR})
- [ ] Transport types translated correctly (stdio vs URL)

**Level 2 (Proxy):**
- [ ] Scope precedence works (project overrides user)
- [ ] Same server name in user + project → both written to respective files
- [ ] Invalid MCP configs skipped gracefully
- [ ] Tool filtering (includeTools/excludeTools) preserved

**Level 3 (Deferred):**
- [ ] Real Gemini CLI loads synced MCP servers
- [ ] Workspace-level servers override user-level
- [ ] Plugin MCP servers work in Gemini CLI
- [ ] OAuth-enabled servers authenticate correctly

## 11. Open Questions

### 1. Plugin MCP Server Discovery

**What we know:** Claude Code plugin.json can contain bundled MCP servers
**What's unclear:**
- Standard location/format for MCP servers in plugins?
- Are they in plugin.json directly or external files?
- Do all Claude Code plugins follow a consistent pattern?

**Resolution:** Check Claude Code plugin documentation and example plugins. May need manual testing with real plugins.

### 2. Extension Auto-Discovery Timing

**What we know:** Gemini CLI scans `~/.gemini/extensions/` on startup
**What's unclear:**
- Can extensions be hot-reloaded without restart?
- Does `gemini extensions enable` require restart?

**Resolution:** Test extension enable/disable to determine restart requirement. Document for users.

### 3. OAuth Configuration Complexity

**What we know:** settings.json supports OAuth configuration
**What's unclear:**
- How to auto-detect if MCP server needs OAuth vs basic auth?
- Can HarnessSync safely translate auth configs or should it skip?

**Resolution:** Start conservative — sync basic auth (headers), skip complex OAuth. Document manual OAuth setup required.

### 4. Extension Settings Keychain Access

**What we know:** Sensitive extension settings stored in system keychain
**What's unclear:**
- Can programmatic access retrieve keychain values?
- Security implications of reading/writing keychain from HarnessSync?

**Resolution:** Do NOT attempt to read/write keychain. Extension settings are separate from synced MCP servers.

## Confidence Assessment

| Area | Confidence | Rationale |
|------|------------|-----------|
| Extension system architecture | HIGH | Official docs + recent blog posts (Feb 2026) |
| gemini-extension.json format | HIGH | Official reference documentation with examples |
| MCP servers in settings.json | HIGH | Detailed official docs + existing HarnessSync implementation |
| Extension vs MCP relationship | HIGH | Clear documentation of precedence and separation |
| Scope support (user/workspace) | HIGH | Official docs + GitHub PR #13748 for user-scoped settings |
| Plugin → extension mapping | HIGH | Technical analysis of incompatible architectures |
| Directory structure | HIGH | Official docs + multiple source confirmation |
| Changes since mid-2025 | MEDIUM | Based on changelogs and blog posts, may have missed minor updates |
| Programmatic configuration | MEDIUM | Inferred from file formats, but CLI-centric design |
| Plugin MCP discovery | LOW | Claude Code plugin format not researched yet |

## Sources

**Official Documentation:**
- [Gemini CLI Extensions](https://geminicli.com/docs/extensions/)
- [Extensions Reference](https://geminicli.com/docs/extensions/reference/)
- [MCP Servers with Gemini CLI](https://geminicli.com/docs/tools/mcp-server/)
- [Gemini CLI Configuration](https://geminicli.com/docs/get-started/configuration/)
- [Provide Context with GEMINI.md Files](https://geminicli.com/docs/cli/gemini-md/)

**Official Announcements:**
- [Making Gemini CLI Extensions Easier to Use](https://developers.googleblog.com/making-gemini-cli-extensions-easier-to-use/) (Feb 2026)
- [Gemini CLI Extensions Announcement](https://blog.google/technology/developers/gemini-cli-extensions/)

**GitHub:**
- [google-gemini/gemini-cli Repository](https://github.com/google-gemini/gemini-cli)
- [Gemini CLI Release Notes](https://geminicli.com/docs/changelogs/)
- [Add Support for User-Scoped Extension Settings (PR #13748)](https://github.com/google-gemini/gemini-cli/pull/13748)

**Comparison Articles:**
- [Claude Code Plugins vs Gemini CLI Extensions: A Comparison](https://harishgarg.com/claude-code-plugins-vs-gemini-cli-extensions-a-comparison/)
- [Gemini CLI vs Claude Code: The Better Coding Agent](https://composio.dev/blog/gemini-cli-vs-claude-code-the-better-coding-agent)

**Technical Guides:**
- [Gemini CLI MCP Server Setup: Complete Configuration Guide](https://www.braingrid.ai/blog/gemini-mcp)
- [Getting Started with Gemini CLI Extensions (Google Codelabs)](https://codelabs.developers.google.com/getting-started-gemini-cli-extensions)

---

## Summary for v2.0 Planning

**Key takeaways for HarnessSync v2.0:**

1. **DO NOT generate Gemini extensions from Claude Code plugins** — architecturally incompatible
2. **DO sync MCP servers to settings.json** — existing pattern is correct and takes precedence
3. **DO add scope awareness** — user (`~/.gemini/settings.json`) vs project (`.gemini/settings.json`)
4. **DO discover plugin-bundled MCP servers** — treat them like user-configured servers
5. **DO preserve environment variable syntax** — `${VAR}` expanded by Gemini CLI at runtime
6. **DO NOT attempt programmatic extension management** — CLI-only operations

**v2.0 milestone scope:**
- Extend GeminiAdapter with scope parameter
- Add plugin MCP server discovery to SourceReader
- Enhance sync_mcp to support user vs project settings.json
- Document extension system limitations
- Verify scope precedence works correctly

**No blockers identified.** HarnessSync v1 pattern (settings.json) is the correct approach. v2.0 adds scope awareness and plugin MCP discovery.
