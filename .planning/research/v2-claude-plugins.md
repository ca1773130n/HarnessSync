# Claude Code Plugin Discovery & MCP Scope Research

**Research Date:** 2026-02-15
**Context:** HarnessSync v2.0 - Plugin & MCP Scope Sync milestone
**Confidence Level:** HIGH (verified with actual system inspection + official documentation)

## Executive Summary

Claude Code manages plugins and MCP servers through a multi-layered configuration system with clear scope boundaries. Plugins are discovered via `~/.claude/plugins/installed_plugins.json`, cached in `~/.claude/plugins/cache/`, and can operate at user or project scope. MCP servers can be standalone (in `~/.claude.json` or `.mcp.json`) or plugin-bundled, with a three-tier scope system (user/project/local).

## 1. Plugin Discovery Mechanism

### 1.1 Plugin Registry Location

**File:** `~/.claude/plugins/installed_plugins.json`

**Structure:**
```json
{
  "version": 2,
  "plugins": {
    "plugin-name@marketplace-name": [
      {
        "scope": "user",  // or "project"
        "installPath": "/Users/user/.claude/plugins/cache/marketplace/plugin/version",
        "version": "1.0.0",
        "installedAt": "2026-01-12T01:15:21.006Z",
        "lastUpdated": "2026-01-12T01:15:21.006Z",
        "gitCommitSha": "abc123..."  // if from git source
      }
    ]
  }
}
```

**Key Insights:**
- Plugins are keyed by `name@marketplace` format
- Multiple installations possible (different versions/scopes)
- Each entry contains absolute install path
- Project-scoped plugins include `projectPath` field
- User-scoped plugins omit `projectPath`

**Example (User Scope):**
```json
"context7@claude-plugins-official": [
  {
    "scope": "user",
    "installPath": "/Users/edward.seo/.claude/plugins/cache/claude-plugins-official/context7/2cd88e7947b7",
    "version": "2cd88e7947b7",
    "installedAt": "2026-02-08T05:09:51.768Z",
    "lastUpdated": "2026-02-08T21:53:07.629Z",
    "gitCommitSha": "2cd88e7947b7382e045666abee790c7f55f669f3"
  }
]
```

**Example (Project Scope):**
```json
"prp-core@prp-marketplace": [
  {
    "scope": "project",
    "projectPath": "/Users/edward.seo/dev/private/research/DeepResearch/HypePaper",
    "installPath": "/Users/edward.seo/.claude/plugins/cache/prp-marketplace/prp-core/unknown",
    "version": "unknown",
    "installedAt": "2026-01-15T11:00:06.759Z",
    "lastUpdated": "2026-02-10T17:04:32.065Z",
    "gitCommitSha": "90419a00f87d948b608a74358355e038ef9630f3"
  }
]
```

### 1.2 Plugin Cache Directory Structure

**Base Path:** `~/.claude/plugins/cache/`

**Organization:**
```
~/.claude/plugins/cache/
├── marketplace-name/
│   └── plugin-name/
│       └── version/
│           ├── .claude-plugin/
│           │   └── plugin.json
│           ├── .mcp.json (if plugin provides MCP servers)
│           ├── agents/
│           ├── commands/
│           ├── skills/
│           └── hooks/
└── temp_git_*/  (temporary git clone directories)
```

**Example (Context7 Plugin):**
```
~/.claude/plugins/cache/claude-plugins-official/context7/2cd88e7947b7/
├── .claude-plugin/
│   └── plugin.json
└── .mcp.json
```

**Example (Multi-CLI Harness Plugin):**
```
~/.claude/plugins/cache/claude-plugin-marketplace/multi-cli-harness/1.0.0/
├── agents/
├── commands/
├── hooks/
├── lib/
├── plugin.json (at root, NOT in .claude-plugin/)
├── scripts/
├── skills/
└── templates/
```

### 1.3 Plugin Metadata Format

**File:** `{installPath}/.claude-plugin/plugin.json` OR `{installPath}/plugin.json`

**Minimal Schema:**
```json
{
  "name": "plugin-name",
  "description": "Plugin description",
  "author": {
    "name": "Author Name"
  }
}
```

**Full Schema:**
```json
{
  "name": "plugin-name",
  "version": "1.0.0",
  "description": "Brief plugin description",
  "author": {
    "name": "Author Name",
    "email": "author@example.com",
    "url": "https://github.com/author"
  },
  "homepage": "https://docs.example.com/plugin",
  "repository": "https://github.com/author/plugin",
  "license": "MIT",
  "keywords": ["keyword1", "keyword2"],
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "bash \"${CLAUDE_PLUGIN_ROOT}/scripts/setup.sh\""
          }
        ]
      }
    ]
  },
  "mcpServers": {
    "server-name": {
      "command": "${CLAUDE_PLUGIN_ROOT}/servers/server",
      "args": ["--config", "${CLAUDE_PLUGIN_ROOT}/config.json"]
    }
  }
}
```

**Important Notes:**
- `${CLAUDE_PLUGIN_ROOT}` expands to absolute plugin install path
- Only `name` is required if manifest exists
- If no manifest, Claude auto-discovers components in default locations
- `.claude-plugin/` directory holds ONLY `plugin.json`
- All other directories (agents/, commands/, skills/) must be at plugin root

**Verified Examples:**

1. **Context7 (minimal):**
```json
{
  "name": "context7",
  "description": "Upstash Context7 MCP server...",
  "author": { "name": "Upstash" }
}
```

2. **Superpowers (full metadata):**
```json
{
  "name": "superpowers",
  "description": "Core skills library for Claude Code...",
  "version": "4.3.0",
  "author": {
    "name": "Jesse Vincent",
    "email": "jesse@fsck.com"
  },
  "homepage": "https://github.com/obra/superpowers",
  "repository": "https://github.com/obra/superpowers",
  "license": "MIT",
  "keywords": ["skills", "tdd", "debugging", "collaboration"]
}
```

3. **GRD (with hooks):**
```json
{
  "name": "grd",
  "version": "0.3.1",
  "description": "Get Research Done — R&D workflow automation",
  "author": { "name": "Cameleon X" },
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "node \"${CLAUDE_PLUGIN_ROOT}/bin/grd-tools.js\" verify-path-exists .planning",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

## 2. Plugin Installation Scopes

### 2.1 User Scope (Default)

**Settings File:** `~/.claude/settings.json`
**Visibility:** Available across all projects
**Use Case:** Personal utilities, development tools

**Configuration:**
```json
{
  "enabledPlugins": {
    "plugin-name@marketplace": true
  }
}
```

**Installation:**
```bash
claude plugin install formatter@my-marketplace
# or explicitly
claude plugin install formatter@my-marketplace --scope user
```

### 2.2 Project Scope

**Settings File:** `.claude/settings.json` (in project root)
**Visibility:** Shared with team via version control
**Use Case:** Project-specific tools, team-shared configurations

**Configuration:**
```json
{
  "enabledPlugins": {
    "prp-core@prp-marketplace": true
  }
}
```

**Installation:**
```bash
claude plugin install formatter@my-marketplace --scope project
```

**Project Settings Example (from HypePaper project):**
```json
{
  "enabledPlugins": {
    "prp-core@prp-marketplace": true
  },
  "enabledMcpjsonServers": ["claude-flow"],
  "hooks": { ... },
  "permissions": { ... }
}
```

### 2.3 Local Scope

**Settings File:** `.claude/settings.local.json` (gitignored)
**Visibility:** Personal, project-specific (not shared)
**Use Case:** Personal overrides, experimental configurations

**Installation:**
```bash
claude plugin install formatter@my-marketplace --scope local
```

### 2.4 Scope Precedence

**Priority (highest to lowest):**
1. Local scope (`.claude/settings.local.json`)
2. Project scope (`.claude/settings.json`)
3. User scope (`~/.claude/settings.json`)
4. Managed scope (`managed-settings.json` - read-only)

**Implication:** Project-scoped plugin overrides user-scoped when both exist

## 3. Plugin MCP Server Registration

### 3.1 Plugin-Provided MCP Configuration

Plugins can bundle MCP servers in two ways:

**Method 1: Separate `.mcp.json` file (at plugin root)**
```json
{
  "server-name": {
    "command": "npx",
    "args": ["-y", "@upstash/context7-mcp"]
  }
}
```

**Method 2: Inline in `plugin.json`**
```json
{
  "name": "my-plugin",
  "mcpServers": {
    "server-name": {
      "command": "${CLAUDE_PLUGIN_ROOT}/servers/server",
      "args": ["--config", "${CLAUDE_PLUGIN_ROOT}/config.json"]
    }
  }
}
```

### 3.2 MCP Server Types

**1. Stdio (local process):**
```json
{
  "context7": {
    "command": "npx",
    "args": ["-y", "@upstash/context7-mcp"]
  }
}
```

**2. HTTP (remote):**
```json
{
  "github": {
    "type": "http",
    "url": "https://api.githubcopilot.com/mcp/",
    "headers": {
      "Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"
    }
  }
}
```

**3. SSE (deprecated, use HTTP):**
```json
{
  "figma": {
    "type": "http",
    "url": "https://mcp.figma.com/mcp"
  }
}
```

### 3.3 Plugin MCP Examples from System

**Context7:**
```json
{
  "context7": {
    "command": "npx",
    "args": ["-y", "@upstash/context7-mcp"]
  }
}
```

**GitHub:**
```json
{
  "github": {
    "type": "http",
    "url": "https://api.githubcopilot.com/mcp/",
    "headers": {
      "Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"
    }
  }
}
```

**Figma (multiple servers):**
```json
{
  "mcpServers": {
    "figma": {
      "type": "http",
      "url": "https://mcp.figma.com/mcp"
    },
    "figma-desktop": {
      "type": "http",
      "url": "http://127.0.0.1:3845/mcp"
    }
  }
}
```

**Sentry:**
```json
{
  "mcpServers": {
    "sentry": {
      "type": "http",
      "url": "https://mcp.sentry.dev/mcp"
    }
  }
}
```

## 4. MCP Server Scope System

### 4.1 Three-Tier Scope Model

**Note:** MCP scopes differ from general settings scopes!

| Scope | Storage Location | Visibility | Use Case |
|-------|-----------------|------------|----------|
| **User** | `~/.claude.json` (top-level `mcpServers`) | All projects for this user | Personal utilities |
| **Project** | `.mcp.json` (project root) | Team-shared via git | Project-specific tools |
| **Local** | `~/.claude.json` (under `projects[path].mcpServers`) | Current project only (private) | Personal project overrides |

**Important Distinction:**
- MCP "local scope" → stored in `~/.claude.json` (home directory)
- General "local scope" → stored in `.claude/settings.local.json` (project directory)

### 4.2 User Scope MCP Servers

**File:** `~/.claude.json`
**Top-level field:** `mcpServers`

**Example:**
```json
{
  "mcpServers": {
    "serena": {
      "type": "sse",
      "url": "http://127.0.0.1:9121/sse"
    }
  }
}
```

**Installation:**
```bash
claude mcp add --transport http hubspot --scope user https://mcp.hubspot.com/anthropic
```

### 4.3 Project Scope MCP Servers

**File:** `.mcp.json` (in project root)
**Committed to git:** YES
**Team-shared:** YES

**Example:**
```json
{
  "mcpServers": {
    "paypal": {
      "type": "http",
      "url": "https://mcp.paypal.com/mcp"
    }
  }
}
```

**Installation:**
```bash
claude mcp add --transport http paypal --scope project https://mcp.paypal.com/mcp
```

**Security:** Claude Code prompts for approval before using project-scoped servers from `.mcp.json`

### 4.4 Local Scope MCP Servers

**File:** `~/.claude.json`
**Field:** `projects[absolutePath].mcpServers`

**Example:**
```json
{
  "projects": {
    "/Users/edward.seo/if(kakao) 2025 demo/Library/PackageCache/com.coplaydev.unity-mcp@ad848f06df": {
      "mcpServers": {
        "UnityMCP": {
          "type": "stdio",
          "command": "uv",
          "args": ["--directory", "UnityMcpServer~/src", "run", "server.py"],
          "env": {}
        }
      },
      "enabledMcpjsonServers": [],
      "disabledMcpjsonServers": []
    }
  }
}
```

**Installation:**
```bash
claude mcp add --transport http stripe https://mcp.stripe.com  # default is local
# or explicitly
claude mcp add --transport http stripe --scope local https://mcp.stripe.com
```

### 4.5 Scope Precedence

**Priority (highest to lowest):**
1. Local scope (private, per-project)
2. Project scope (shared, per-project)
3. User scope (global, cross-project)

## 5. Settings.json MCP Reference

### 5.1 User Settings (~/.claude/settings.json)

```json
{
  "enabledPlugins": {
    "context7@claude-plugins-official": true,
    "github@claude-plugins-official": true,
    "multi-cli-harness@claude-plugin-marketplace": true
  },
  "hooks": { ... },
  "statusLine": { ... },
  "env": { ... }
}
```

**Note:** MCP servers are NOT in user settings.json - they're in `~/.claude.json`

### 5.2 Project Settings (.claude/settings.json)

```json
{
  "enabledPlugins": {
    "prp-core@prp-marketplace": true
  },
  "enabledMcpjsonServers": ["claude-flow"],
  "hooks": { ... },
  "permissions": { ... },
  "env": { ... }
}
```

**Key Fields:**
- `enabledPlugins`: Plugin activation map
- `enabledMcpjsonServers`: Which servers from `.mcp.json` to enable (if `.mcp.json` exists)
- `permissions`: Tool allowlists/denylists
- `hooks`: Event handlers
- `env`: Environment variables

### 5.3 Plugin Reference in Settings

Plugins are referenced in settings by their **full identifier:**
```
plugin-name@marketplace-name
```

**Examples:**
- `context7@claude-plugins-official`
- `grd@claude-plugin-marketplace`
- `multi-cli-harness@claude-plugin-marketplace`
- `prp-core@prp-marketplace`

**Enabling/Disabling:**
```json
{
  "enabledPlugins": {
    "plugin-name@marketplace": true,  // enabled
    "other-plugin@marketplace": false // disabled
  }
}
```

## 6. Plugin MCPs vs Standalone MCPs

### 6.1 Relationship

**Plugin-Provided MCPs:**
- Bundled with plugin installation
- Auto-start when plugin enabled (requires restart to apply)
- Managed via plugin lifecycle (install/uninstall)
- Defined in plugin's `.mcp.json` or `plugin.json`
- Use `${CLAUDE_PLUGIN_ROOT}` for paths

**Standalone MCPs:**
- User-configured via `claude mcp add`
- Independent of plugins
- Stored in `~/.claude.json` or `.mcp.json`
- Can reference system binaries or npm packages

### 6.2 MCP Server List During Session

**Command:** `/mcp` (within Claude Code)

**Display includes:**
- All user-scope MCP servers
- All project-scope MCP servers (from `.mcp.json`)
- All local-scope MCP servers
- All plugin-provided MCP servers (from enabled plugins)
- Authentication status for remote servers
- Connection status

**Indicators:**
- Plugin servers shown with plugin origin
- Remote servers show OAuth status
- Disabled servers indicated

### 6.3 Example: Mixed MCP Configuration

**User-level (`~/.claude.json`):**
```json
{
  "mcpServers": {
    "serena": {
      "type": "sse",
      "url": "http://127.0.0.1:9121/sse"
    }
  }
}
```

**Project-level (`.mcp.json`):**
```json
{
  "mcpServers": {
    "paypal": {
      "type": "http",
      "url": "https://mcp.paypal.com/mcp"
    }
  }
}
```

**Plugin-provided (Context7 plugin `.mcp.json`):**
```json
{
  "context7": {
    "command": "npx",
    "args": ["-y", "@upstash/context7-mcp"]
  }
}
```

**Result:** All three servers available in `/mcp` list when:
- Plugin is enabled
- Project has `.mcp.json` approved
- User scope always available

## 7. Project-Level Plugin Installation

### 7.1 Plugin Installation Location

**Physical cache location:** ALWAYS `~/.claude/plugins/cache/` (never in project)

**Key insight:** Plugins are never physically copied to project directory. Project-scope only affects:
1. Which `settings.json` gets the `enabledPlugins` entry
2. Whether other team members see it (via git)

### 7.2 Project-Scoped Plugin Metadata

**In installed_plugins.json:**
```json
{
  "plugins": {
    "prp-core@prp-marketplace": [
      {
        "scope": "project",
        "projectPath": "/Users/edward.seo/dev/private/research/DeepResearch/HypePaper",
        "installPath": "/Users/edward.seo/.claude/plugins/cache/prp-marketplace/prp-core/unknown",
        "version": "unknown",
        "installedAt": "2026-01-15T11:00:06.759Z"
      }
    ]
  }
}
```

**In project settings (.claude/settings.json):**
```json
{
  "enabledPlugins": {
    "prp-core@prp-marketplace": true
  }
}
```

### 7.3 Project Directory Structure (No Local Plugin Cache)

**What EXISTS in project:**
```
project/
└── .claude/
    ├── settings.json (enabledPlugins reference)
    ├── settings.local.json (optional, gitignored)
    ├── agents/ (optional)
    ├── commands/ (optional)
    └── skills/ (optional)
```

**What DOES NOT exist in project:**
- NO `.claude/plugins/` directory
- NO local plugin cache
- NO plugin files copied to project

**Implication:** Team members must install plugins separately. Project settings only track which plugins should be enabled.

## 8. Environment Variable Expansion

### 8.1 In Plugin Configurations

**`${CLAUDE_PLUGIN_ROOT}`:**
- Expands to absolute plugin install path
- Used in hooks, MCP servers, scripts
- Example: `/Users/edward.seo/.claude/plugins/cache/claude-plugin-marketplace/grd/0.3.1`

**Usage:**
```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "node \"${CLAUDE_PLUGIN_ROOT}/bin/grd-tools.js\" verify-path-exists .planning"
          }
        ]
      }
    ]
  }
}
```

### 8.2 In MCP Configurations

**Standard environment variables:**
- `${API_KEY}`, `${GITHUB_PERSONAL_ACCESS_TOKEN}`, etc.
- Expanded at runtime from user environment
- Supports default values: `${VAR:-default}`

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

## 9. File Path Summary

| File | Purpose | Scope | Committed to Git? |
|------|---------|-------|-------------------|
| `~/.claude/plugins/installed_plugins.json` | Plugin registry | User + All Projects | NO |
| `~/.claude/plugins/cache/` | Plugin physical storage | User + All Projects | NO |
| `~/.claude/settings.json` | User settings, enabled plugins | User (all projects) | NO |
| `~/.claude.json` | MCP servers, project metadata | User + Per-project | NO |
| `.claude/settings.json` | Project settings, enabled plugins | Project (team-shared) | YES |
| `.claude/settings.local.json` | Local overrides | Local (personal) | NO (gitignored) |
| `.mcp.json` | Project MCP servers | Project (team-shared) | YES |

## 10. Key Insights for HarnessSync v2.0

### 10.1 Sync Requirements

**For Plugin Sync:**
1. Read `~/.claude/plugins/installed_plugins.json` to discover installed plugins
2. Parse each plugin's `plugin.json` from install path
3. Map scope to target CLI equivalent
4. Handle marketplace references (plugin@marketplace format)
5. Support both `.claude-plugin/plugin.json` and root `plugin.json` locations

**For MCP Sync:**
1. Read user-scope MCPs from `~/.claude.json` (top-level `mcpServers`)
2. Read project-scope MCPs from `.mcp.json` (if exists)
3. Read local-scope MCPs from `~/.claude.json` (`projects[path].mcpServers`)
4. Distinguish plugin-provided MCPs (from plugin `.mcp.json`) vs standalone
5. Map scope correctly (user/project/local)

### 10.2 Challenges

**Plugin Discovery:**
- Plugins can have multiple versions installed
- Same plugin can be at different scopes
- Project-scoped plugins need project path tracking
- Marketplace namespace must be preserved

**MCP Scope Complexity:**
- Three different scope systems (plugins vs MCP vs general settings)
- MCP "local" != general "local" (different file locations)
- Plugin MCPs auto-enable when plugin enabled
- Project MCPs require user approval

**Environment Variables:**
- `${CLAUDE_PLUGIN_ROOT}` needs translation for target CLI
- User environment variables must be available
- OAuth credentials for remote MCPs stored in system keychain

### 10.3 Recommended Sync Strategy

**Phase 1: Plugin Discovery**
1. Parse `installed_plugins.json`
2. Filter by scope (user vs project)
3. Read metadata from each plugin's install path
4. Extract MCP configurations if present

**Phase 2: Standalone MCP Discovery**
1. Parse `~/.claude.json` for user/local scope
2. Parse `.mcp.json` for project scope
3. Merge with plugin-provided MCPs
4. Maintain scope hierarchy

**Phase 3: Settings Sync**
1. Read enabled plugins from appropriate settings.json
2. Read enabled MCP servers (enabledMcpjsonServers)
3. Sync to target CLI format
4. Handle scope-specific paths

**Phase 4: Validation**
1. Verify plugin install paths exist
2. Check MCP server connectivity
3. Validate environment variable availability
4. Test scope precedence

## 11. Verified File Examples

### 11.1 Actual installed_plugins.json (excerpt)

```json
{
  "version": 2,
  "plugins": {
    "code-simplifier@claude-plugins-official": [
      {
        "scope": "user",
        "installPath": "/Users/edward.seo/.claude/plugins/cache/claude-plugins-official/code-simplifier/1.0.0",
        "version": "1.0.0",
        "installedAt": "2026-01-12T01:15:21.006Z",
        "lastUpdated": "2026-01-12T01:15:21.006Z"
      }
    ],
    "prp-core@prp-marketplace": [
      {
        "scope": "project",
        "projectPath": "/Users/edward.seo/dev/private/research/DeepResearch/HypePaper",
        "installPath": "/Users/edward.seo/.claude/plugins/cache/prp-marketplace/prp-core/unknown",
        "version": "unknown",
        "installedAt": "2026-01-15T11:00:06.759Z",
        "lastUpdated": "2026-02-10T17:04:32.065Z",
        "gitCommitSha": "90419a00f87d948b608a74358355e038ef9630f3"
      }
    ],
    "grd@claude-plugin-marketplace": [
      {
        "scope": "user",
        "installPath": "/Users/edward.seo/.claude/plugins/cache/claude-plugin-marketplace/grd/0.3.1",
        "version": "0.3.1",
        "installedAt": "2026-02-13T05:22:55.260Z",
        "lastUpdated": "2026-02-13T05:22:55.260Z",
        "gitCommitSha": "27bc6265703e75e7d9fb07d2cffc78771c08bba1"
      }
    ]
  }
}
```

### 11.2 Actual User Settings (~/.claude/settings.json)

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "node \"/Users/edward.seo/.claude/hooks/gsd-check-update.js\""
          }
        ]
      }
    ]
  },
  "statusLine": {
    "type": "command",
    "command": "input=$(cat); user=$(whoami); host=$(hostname -s); ..."
  },
  "enabledPlugins": {
    "code-simplifier@claude-plugins-official": true,
    "context7@claude-plugins-official": true,
    "github@claude-plugins-official": true,
    "grd@claude-plugin-marketplace": true,
    "multi-cli-harness@claude-plugin-marketplace": true
  },
  "autoUpdatesChannel": "latest",
  "skipDangerousModePermissionPrompt": true
}
```

### 11.3 Actual Project Settings (.claude/settings.json from HypePaper)

```json
{
  "env": {
    "CLAUDE_FLOW_AUTO_COMMIT": "false",
    "CLAUDE_FLOW_AUTO_PUSH": "false",
    "CLAUDE_FLOW_HOOKS_ENABLED": "true"
  },
  "enabledMcpjsonServers": ["claude-flow"],
  "hooks": {
    "PreToolUse": [...],
    "PostToolUse": [...],
    "Stop": [...]
  },
  "enabledPlugins": {
    "prp-core@prp-marketplace": true
  },
  "permissions": {
    "allow": ["Bash(git status)", "Bash(git diff :*)", ...]
  }
}
```

### 11.4 Actual .mcp.json (Plugin-provided)

**Context7 Plugin:**
```json
{
  "context7": {
    "command": "npx",
    "args": ["-y", "@upstash/context7-mcp"]
  }
}
```

**GitHub Plugin:**
```json
{
  "github": {
    "type": "http",
    "url": "https://api.githubcopilot.com/mcp/",
    "headers": {
      "Authorization": "Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}"
    }
  }
}
```

**Figma Plugin:**
```json
{
  "mcpServers": {
    "figma": {
      "type": "http",
      "url": "https://mcp.figma.com/mcp"
    },
    "figma-desktop": {
      "type": "http",
      "url": "http://127.0.0.1:3845/mcp"
    }
  }
}
```

## 12. References

**Official Documentation:**
- [Plugins reference - Claude Code Docs](https://code.claude.com/docs/en/plugins-reference)
- [Connect Claude Code to tools via MCP - Claude Code Docs](https://code.claude.com/docs/en/mcp)
- [How to Build Claude Code Plugins - DataCamp](https://www.datacamp.com/tutorial/how-to-build-claude-code-plugins)
- [Claude Code Plugin CLI: The Missing Manual - Medium](https://medium.com/@garyjarrel/claude-code-plugin-cli-the-missing-manual-0a4d3a7c99ce)

**Community Resources:**
- [Claude Code Best Practice - GitHub](https://github.com/shanraisshan/claude-code-best-practice/blob/main/reports/claude-global-vs-project-settings.md)
- [Bug Reports - anthropics/claude-code Issues](https://github.com/anthropics/claude-code/issues)

**Verified System Inspection:**
- `~/.claude/plugins/installed_plugins.json` (2026-02-15)
- `~/.claude/settings.json` (2026-02-15)
- `~/.claude.json` (2026-02-15)
- Multiple plugin cache directories inspected
- Multiple project `.claude/settings.json` files examined

---

**Research Confidence:** HIGH - All findings verified through:
1. Direct system file inspection
2. Official Claude Code documentation (code.claude.com)
3. Community documentation and bug reports
4. Multiple real-world plugin examples
5. Live MCP configuration files
