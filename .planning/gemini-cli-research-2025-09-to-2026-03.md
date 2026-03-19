# Gemini CLI Research: September 2025 - March 2026

Research date: 2026-03-19
Source: https://github.com/google-gemini/gemini-cli (98.3k stars, 5,374 commits)
Current stable: v0.34.0 (2026-03-17) | Preview: v0.35.0-preview.1 (2026-03-17)

---

## 1. Configuration File Format & Location

### GEMINI.md (context/instructions file)
- **Location hierarchy** (loaded in order, all concatenated):
  1. Global: `~/.gemini/GEMINI.md`
  2. Workspace: `<project>/.gemini/GEMINI.md` (and parent directories)
  3. JIT (just-in-time): auto-discovered when tools access files in a directory (scans ancestors up to trusted root)
- **Import syntax**: `@file.md` imports content from other files (relative and absolute paths)
- **`/memory` command**: `show`, `reload`, `add <text>` (appends to global GEMINI.md)
- JIT context loading enabled by default with deduplication (v0.35 preview)

### settings.json
- **User settings**: `~/.gemini/settings.json`
- **Workspace settings**: `<project>/.gemini/settings.json`
- **System settings**: `/etc/gemini-cli/settings.json`
- Workspace overrides user; has JSON schema at `https://raw.githubusercontent.com/google-gemini/gemini-cli/main/schemas/settings.schema.json`
- **Major setting categories**: General, Output, UI, IDE, Billing, Model, Context, Tools, Security, Advanced, Experimental, Skills, HooksConfig

### .gemini/ directory structure
```
~/.gemini/                    # User-level (global)
  GEMINI.md                   # Global context
  settings.json               # User settings
  commands/                   # Global custom commands (.toml)
  skills/                     # Global skills (SKILL.md per directory)
  agents/                     # Global agents (.md files)
  extensions/                 # Installed extensions

<project>/.gemini/            # Project-level
  GEMINI.md                   # Project context (replaces old top-level GEMINI.md)
  settings.json               # Project settings
  commands/                   # Project custom commands
  skills/                     # Project skills
  agents/                     # Project agents
  config.yaml                 # Gemini Code Assist (PR review) config, NOT CLI config
```

---

## 2. MCP Server Configuration

### Location
- Defined in `settings.json` under `"mcpServers"` key (both user and workspace level)
- Also definable in extensions via `gemini-extension.json` `"mcpServers"` field

### MCPServerConfig Schema
```json
{
  "mcpServers": {
    "server-name": {
      "command": "string",       // Executable for stdio transport
      "args": ["string"],        // Command-line arguments
      "url": "string",           // URL for SSE/HTTP transport
      "env": { "KEY": "val" },   // Environment variables
      "cwd": "string",           // Working directory
      "trust": "boolean"         // Trust level (not available in extensions)
      // includeTools / excludeTools available in extension mcpServers
    }
  }
}
```

### Key details
- Extension MCP servers support all options EXCEPT `trust`
- Extensions use `${extensionPath}` and `${/}` for portable paths
- If both extension and settings.json define same server name, settings.json takes precedence
- Admin can allowlist specific MCP server configurations (v0.29)
- SSE MCP servers supported on native build

---

## 3. Custom Commands (TOML format)

### Locations
- User: `~/.gemini/commands/*.toml`
- Project: `<project>/.gemini/commands/*.toml`
- Project commands override user commands with same name
- Subdirectories create namespaced commands: `git/commit.toml` -> `/git:commit`

### TOML Format
```toml
description = "Brief description"
prompt = "The prompt text with optional {{args}} placeholder"
```

### Features
- `{{args}}` placeholder for argument injection (raw or shell-escaped)
- Shell command execution with `{{!command}}` syntax
- `/commands reload` to pick up changes without restart

---

## 4. Skills

### Structure
```
skills/<skill-name>/
  SKILL.md          # Required - YAML frontmatter + markdown instructions
  scripts/          # Optional - executable scripts
  references/       # Optional - static documentation
  assets/           # Optional - templates and other resources
```

### SKILL.md Format
```markdown
---
name: skill-name
description: When to use this skill
---
# Instructions in markdown
```

- User-level: `~/.gemini/skills/`
- Project-level: `<project>/.gemini/skills/`
- Built-in `skill-creator` skill to generate new skills (v0.26)
- Skills enabled by default (v0.26)

---

## 5. Agents / Subagents

### Local Subagents
- Experimental feature, enabled by default via `experimental.enableAgents: true`
- Built-in: `codebase_investigator`, `cli_help`
- Override via `settings.json` under `agents.overrides.<name>`
- Can override model, maxTurns, etc.

### Remote Subagents (A2A Protocol)
- Defined as `.md` files with YAML frontmatter in `.gemini/agents/` (project) or `~/.gemini/agents/` (user)
- Support `@agent_name` syntax for direct delegation
- Authentication types: `apiKey`, `http` (Bearer/Basic), `google-credentials`, `oauth2`
- Dynamic values via `$ENV_VAR` or `$( command )` syntax
- Multi-agent definition in single file (remote only)
- HTTP auth for A2A introduced in v0.33

### Agent Definition Format
```markdown
---
kind: remote
name: my-agent
agent_card_url: https://example.com/agent-card
auth:
  type: apiKey
  key: $MY_API_KEY
  name: X-API-Key
---
```

---

## 6. Hooks System

### Configuration
- Defined in `settings.json` under `"hooks"` key (project, user, or system level)
- Extensions define hooks in `hooks/hooks.json` (NOT in gemini-extension.json manifest)

### Hook Events
| Event | When | Impact |
|-------|------|--------|
| SessionStart | Session begins | Inject Context |
| SessionEnd | Session ends | Advisory |
| BeforeAgent | After prompt, before planning | Block Turn / Context |
| AfterAgent | Agent loop ends | Retry / Halt |
| BeforeModel | Before LLM request | Block Turn / Mock |
| AfterModel | After LLM response | Block Turn / Redact |
| BeforeToolSelection | Before tool selection | Filter Tools |
| BeforeTool | Before tool executes | Block Tool / Rewrite |
| AfterTool | After tool executes | Block Result / Context |
| PreCompress | Before context compression | Advisory |
| Notification | System notification | Advisory |

### Format
```json
{
  "hooks": {
    "BeforeTool": [
      {
        "matcher": "write_file|replace",
        "hooks": [
          {
            "name": "security-check",
            "type": "command",
            "command": "/path/to/script.sh",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
```

### Communication
- Input via stdin (JSON), output via stdout (JSON)
- Exit code 0 = success, 2 = system block, other = warning
- Tool matchers are regex; lifecycle matchers are exact strings

---

## 7. Extensions System (v0.8+, Sep 2025)

### Install & Management
```bash
gemini extensions install <github-url|local-path> [--ref <ref>] [--auto-update] [--pre-release] [--consent]
gemini extensions uninstall <name>
gemini extensions enable|disable <name> [--scope user|workspace]
gemini extensions update <name|--all>
gemini extensions new <path> [template]  # Templates: mcp-server, context, custom-commands
gemini extensions link <path>            # Symlink for dev
```

### Extension Manifest (gemini-extension.json)
```json
{
  "name": "extension-name",
  "version": "1.0.0",
  "description": "Description",
  "contextFileName": "GEMINI.md",
  "mcpServers": { ... },
  "excludeTools": ["run_shell_command(rm -rf)"],
  "migratedTo": "https://github.com/new/repo",
  "plan": { "directory": ".gemini/plans" }
}
```

### Extension Features
- MCP servers, custom commands, context (GEMINI.md), agent skills, sub-agents, hooks, themes, policy engine
- Installed to `~/.gemini/extensions/`
- Cryptographic integrity verification for updates (v0.35)
- `disableAlwaysAllow` setting to prevent auto-approvals (v0.35)
- Extension gallery at geminicli.com/extensions
- Can be scoped to user or workspace

---

## 8. Permissions & Security

### Approval Modes
- `default`: prompts for approval
- `auto_edit`: auto-approves edit tools
- `plan`: read-only mode
- `yolo`: auto-approve all (CLI flag only, not settable in config)

### Security Settings
| Setting | Description |
|---------|-------------|
| `security.toolSandboxing` | Experimental tool-level sandboxing |
| `security.disableYoloMode` | Disable YOLO even if flag passed |
| `security.disableAlwaysAllow` | Disable "Always allow" in dialogs |
| `security.enablePermanentToolApproval` | "Allow for all future sessions" option |
| `security.autoAddToPolicyByDefault` | Auto-add to policy for low-risk tools |
| `security.blockGitExtensions` | Block extensions from Git |
| `security.allowedExtensions` | Regex allowlist for extensions |
| `security.folderTrust.enabled` | Folder trust system |

### Policy Engine (v0.30+)
- `policyPaths`: additional policy files/dirs to load
- `adminPolicyPaths`: admin-level policy files
- `--policy` flag for user-defined policies
- Strict seatbelt profiles
- `--allowed-tools` deprecated in favor of policy engine
- Project-level policies, MCP server wildcards, tool annotation matching (v0.31)

### Sandboxing (v0.34)
- Native gVisor (runsc) sandboxing
- Experimental LXC container sandboxing
- SandboxManager for all process-spawning tools (v0.35)

---

## 9. Release Timeline (Sep 2025 - Mar 2026)

### v0.4.0 (2025-09-01)
- CloudRun and Security extension integrations
- Experimental edit tool (`useSmartEdit` setting)
- Custom commands `@{path}` file embedding syntax
- Footer visibility configuration in settings.json
- Citations support for enterprise
- 2.5 Flash Lite support

### v0.5.0 (2025-09-08)
- Continued polish and fixes

### v0.6.0 (2025-09-15)
- Feature updates and stability improvements

### v0.7.0 (2025-09-22)
- More features and polish

### v0.8.0 (2025-09-29) -- MAJOR
- **Extensions system launched** (install, uninstall, link, enable/disable, update, new)
- Extensions gallery at geminicli.com/extensions
- New documentation site at geminicli.com
- Non-interactive `--allowed-tools`
- Terminal title status (`showStatusInTitle`)

### v0.9.0 (2025-10-06)
- Continued improvements

### v0.10.0 (2025-10-13)
- Continued improvements

### v0.11.0 (2025-10-20)
- Feature updates

### v0.12.0 (2025-10-27)
- Significant feature additions

### v0.15.0 (2025-11-03)
- Major feature set additions

### v0.16.0 (2025-11-10) -- MAJOR
- **Gemini 3 + Gemini CLI launch**
- Data Commons extension

### v0.18.0 (2025-11-17)
- Significant features

### v0.19.0 (2025-11-24)
- Feature updates

### v0.20.0 (2025-12-01)
- Feature updates

### v0.21.0 (2025-12-15)
- Feature updates

### v0.22.0 (2025-12-22)
- Feature updates

### v0.23.0 (2026-01-07)
- Feature updates

### v0.24.0 (2026-01-14)
- Major feature set

### v0.25.0 (2026-01-20)
- Feature additions

### v0.26.0 (2026-01-27) -- MAJOR
- **Agents and Skills enabled by default**
- `skill-creator` skill introduced
- Generalist agent for task routing
- `/rewind` command for conversation history
- Core scheduler refactoring

### v0.27.0 (2026-02-03)
- Event-driven scheduler for tool execution
- Queued tool confirmations
- `/rewind` command
- Expandable large text pastes

### v0.28.0 (2026-02-10)
- Positron IDE support
- Custom themes in extensions
- Automatic theme switching
- OAuth consent improvements

### v0.29.0 (2026-02-17)
- Extension exploration UI
- Admin MCP server allowlisting
- Extension settings management

### v0.30.0 (2026-02-25) -- MAJOR
- **SDK package** with dynamic system instructions, SessionContext
- **Custom skills support via SDK**
- **Policy engine** with `--policy` flag, strict seatbelt profiles
- `--allowed-tools` deprecated in favor of policy engine
- Searchable settings/extensions list, Solarized themes

### v0.31.0 (2026-02-27)
- Gemini 3.1 Pro Preview model support
- Experimental browser agent
- Policy engine: project-level policies, MCP wildcards, tool annotation matching
- Experimental direct web fetch, rate limiting

### v0.32.0 (2026-03-03)
- Generalist agent enabled
- Model steering in workspace
- Plan mode enhancements (external editor, multi-select)

### v0.33.0 (2026-03-11) -- MAJOR
- **A2A remote agents** with HTTP authentication
- Authenticated A2A agent card discovery
- Plan Mode: research subagents, annotation feedback, `copy` subcommand
- Compact header redesign, 30-day chat history retention

### v0.34.0 (2026-03-17) -- STABLE
- **Plan Mode enabled by default**
- Native gVisor (runsc) sandboxing
- Experimental LXC container sandboxing
- Loop detection & recovery
- Customizable footer via `/footer`
- Subagent tracker visualization

### v0.35.0-preview.1 (2026-03-17) -- PREVIEW
- Subagent tool isolation
- Proxy routing for remote A2A
- SandboxManager for all process-spawning tools
- **Customizable keyboard shortcuts**
- **JIT context loading enabled by default** with deduplication
- Model-driven parallel tool scheduler
- Cryptographic integrity for extension updates
- `disableAlwaysAllow` security setting
- Code splitting & deferred UI loading

---

## 10. Impact on HarnessSync Gemini Adapter

### Current adapter syncs (already implemented)
- Rules -> GEMINI.md (with managed markers)
- Skills -> .gemini/skills/<name>/SKILL.md
- Agents -> .gemini/agents/<name>.md
- Commands -> .gemini/commands/<name>.toml
- MCP servers -> settings.json mcpServers
- Settings -> settings.json tools.exclude/tools.allowed

### Potential gaps to investigate
1. **config.yaml**: This is for Gemini Code Assist (PR review bot), NOT CLI - no sync needed
2. **MCP trust field**: Already in adapter docstring - verify implementation handles it correctly
3. **Policy engine** (v0.30+): `policyPaths`, `adminPolicyPaths` - may need sync for deny rules
4. **Hooks**: The hooks format in settings.json is different from Claude Code hooks - need mapping
5. **Extensions**: Extensions are managed via `gemini extensions` CLI - not a sync target, but adapter should avoid conflicting with extension-provided config
6. **Security settings**: New settings like `disableAlwaysAllow`, `disableYoloMode`, `toolSandboxing` could be synced from Claude Code deny permissions
7. **Context settings**: `context.discoveryMaxDirs`, `context.loadMemoryFromIncludeDirectories`, `context.fileFiltering.*` - potential sync targets
8. **Model settings**: `model.alias`, `model.aliases` - map Claude Code model preferences
9. **JIT context**: GEMINI.md files in subdirectories are auto-discovered - adapter should be aware
10. **GEMINI.md import syntax**: `@file.md` imports could be leveraged for modular sync
11. **Remote agents**: A2A remote agent definitions in `.gemini/agents/*.md` with auth - new sync capability
12. **Experimental features**: `experimental.plan`, `experimental.enableAgents`, `experimental.modelSteering` etc.
