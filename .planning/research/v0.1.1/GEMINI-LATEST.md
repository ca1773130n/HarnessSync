# Gemini CLI Configuration Research (March 2026)

**Researched:** 2026-03-09
**Gemini CLI version:** v0.32.0 (2026-03-03)
**Overall confidence:** HIGH (verified against official docs + GitHub)

## Executive Summary

Gemini CLI has undergone massive changes since the initial HarnessSync adapter was written. The most significant are:

1. **settings.json format migration** (Sept 2025) -- flat keys like `allowedTools`/`blockedTools` are now nested under `tools.allowed`/`tools.exclude`
2. **Extensions system** (v0.8.0, Sept 2025) -- full plugin system with manifest, MCP, commands, hooks, skills, agents, themes
3. **Agent Skills** (v0.23.0, Jan 2026) -- native SKILL.md support with `name`/`description` frontmatter
4. **Subagents** (v0.12.0, Oct 2025) -- native agent .md files with YAML frontmatter
5. **Custom Commands** (native) -- TOML-based slash commands in `.gemini/commands/`
6. **Hooks** (native) -- lifecycle hooks in settings.json
7. **Policy Engine** (v0.18.0, Nov 2025) -- fine-grained TOML policies for tool access
8. **New MCP fields** -- `trust`, `includeTools`, `excludeTools`, `oauth` per server

**Impact on HarnessSync:** Our current adapter inlines skills/agents/commands into GEMINI.md as plain text. Gemini CLI now has NATIVE support for all three. We should sync to native formats instead.

---

## 1. GEMINI.md Format

**Status:** Unchanged core format, new features added.

### Current Format
- Plain markdown, no special metadata/tags required
- Hierarchical loading: `~/.gemini/GEMINI.md` (global) -> project root + ancestors (up to .git) -> subdirectories
- Respects `.gitignore` and `.geminiignore`

### New Features
- **`@` import syntax**: `@./relative/path/file.md` to modularize content
- **Configurable filename**: `context.fileName` in settings.json accepts string or array:
  ```json
  { "context": { "fileName": ["AGENTS.md", "CONTEXT.md", "GEMINI.md"] } }
  ```
- **Discovery limits**: `context.discoveryMaxDirs` (default 200)
- **Memory commands**: `/memory show`, `/memory refresh`, `/memory add <text>`

### HarnessSync Impact
- Our managed marker approach still works fine
- The `@` import syntax could allow us to write separate files instead of inlining everything
- **LOW PRIORITY** -- current approach is compatible

---

## 2. settings.json Format (BREAKING CHANGE)

### Old v1 Format (Pre-Sept 2025) -- WHAT WE CURRENTLY TARGET
```json
{
  "allowedTools": ["ShellTool(git status)"],
  "blockedTools": ["run_shell_command"],
  "coreTools": ["ReadFileTool", "GlobTool"],
  "mcpServers": { ... }
}
```

### New v2 Format (Post-Sept 2025) -- CURRENT STANDARD
```json
{
  "general": { "vimMode": false, "editor": "code" },
  "ui": { "theme": "default", "showBanner": true },
  "model": { "name": "gemini-3-pro", "maxSessionTurns": 200 },
  "context": {
    "fileName": "GEMINI.md",
    "discoveryMaxDirs": 200,
    "importFormat": "auto"
  },
  "tools": {
    "sandbox": false,
    "core": ["run_shell_command(git)"],
    "allowed": ["run_shell_command(git)", "run_shell_command(npm test)"],
    "exclude": ["run_shell_command(rm -rf)"],
    "shell": { "enableInteractiveShell": true },
    "truncateToolOutputThreshold": 40000
  },
  "mcp": {
    "serverCommand": "...",
    "allowed": ["server-name"]
  },
  "mcpServers": { ... },
  "security": {
    "disableYoloMode": false,
    "enablePermanentToolApproval": false,
    "folderTrust": { "enabled": true },
    "environmentVariableRedaction": { "enabled": false }
  },
  "privacy": { ... },
  "telemetry": { "enabled": false },
  "hooks": { ... },
  "advanced": { ... }
}
```

### Key Mapping Changes for HarnessSync
| Old (v1) | New (v2) | Notes |
|----------|----------|-------|
| `allowedTools` (flat) | `tools.allowed` (nested) | Same semantics |
| `blockedTools` (flat) | `tools.exclude` (nested) | Same semantics |
| `coreTools` (flat) | `tools.core` (nested) | Allowlist of built-in tools |
| `mcpServers` (flat) | `mcpServers` (flat) | **UNCHANGED** -- still top-level |

### HarnessSync Impact -- CRITICAL
Our `sync_settings()` currently writes `tools.blockedTools` and `tools.allowedTools`. This is **wrong for the new format**. We need to write:
- `tools.allowed` (not `tools.allowedTools`)
- `tools.exclude` (not `tools.blockedTools`)

**Verify:** Check if our adapter actually writes `tools.blockedTools` or `tools.exclude`. Based on the code review, the adapter writes:
```python
tools_config['blockedTools'] = deny_list  # WRONG for v2 format
tools_config['allowedTools'] = allow_list  # WRONG for v2 format
```
This needs to be updated to:
```python
tools_config['exclude'] = deny_list   # Correct v2 format
tools_config['allowed'] = allow_list  # Correct v2 format
```

And the nesting: `existing_settings['tools'] = tools_config` -- this IS correct for v2 (nested under `tools`).

**Confidence:** HIGH -- verified against official configuration reference.

---

## 3. MCP Server Config (NEW FIELDS)

### Current mcpServers Format (still top-level, unchanged location)

**Stdio transport:**
```json
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["server.js"],
      "cwd": "/path/to/dir",
      "env": { "KEY": "${VAR_NAME}" },
      "timeout": 600000,
      "trust": false,
      "includeTools": ["tool1", "tool2"],
      "excludeTools": ["dangerous_tool"]
    }
  }
}
```

**HTTP transport:**
```json
{
  "mcpServers": {
    "my-http-server": {
      "httpUrl": "https://api.example.com/mcp/",
      "headers": { "Authorization": "Bearer ${TOKEN}" },
      "timeout": 5000,
      "trust": false,
      "includeTools": ["safe_tool"],
      "excludeTools": ["risky_tool"]
    }
  }
}
```

**SSE transport:**
```json
{
  "mcpServers": {
    "my-sse-server": {
      "url": "https://example.com/sse",
      "headers": { "Authorization": "Bearer ${TOKEN}" }
    }
  }
}
```

### New Fields (not in our adapter yet)
| Field | Type | Purpose |
|-------|------|---------|
| `trust` | boolean | Bypass tool confirmations for this server |
| `includeTools` | string[] | Allowlist specific tools from server |
| `excludeTools` | string[] | Blocklist specific tools from server |
| `cwd` | string | Working directory for stdio servers |
| `targetAudience` | string | OAuth Client ID for IAP |
| `targetServiceAccount` | string | Service account for impersonation |
| `oauth` | object | Full OAuth config (clientId, scopes, etc.) |

### Environment Variable Interpolation
- Gemini CLI natively supports `$VAR_NAME` and `${VAR_NAME}` in `env` blocks
- Our adapter correctly preserves `${VAR}` syntax (ENV-03)

### HarnessSync Impact -- MODERATE
- Our MCP sync already handles `command`/`args`/`env`/`timeout`/`url`/`httpUrl`/`headers` -- this is correct
- We should pass through `trust`, `includeTools`, `excludeTools`, `cwd` if present in source config
- OAuth fields are unlikely to come from Claude Code, low priority

**Confidence:** HIGH

---

## 4. Native Skills Support (NEW)

### Gemini CLI Now Has Native SKILL.md

**Discovery locations** (precedence order):
1. `.gemini/skills/` or `.agents/skills/` (workspace, committed)
2. `~/.gemini/skills/` or `~/.agents/skills/` (user, personal)
3. Extension skills (bundled)

Within each tier, `.agents/skills/` takes precedence over `.gemini/skills/`.

### SKILL.md Format
```yaml
---
name: code-reviewer
description: Use this skill to review code for quality and best practices.
---

# Code Reviewer

Instructions for the agent when this skill is active...
```

Only two frontmatter fields: `name` (required) and `description` (required).

### Loading Mechanism
1. CLI scans discovery tiers, injects name+description into system prompt
2. Model calls `activate_skill` tool when it detects a matching task
3. User approves skill access
4. SKILL.md body + folder structure injected into conversation history

### Management
```bash
gemini skills list
gemini skills install <source> [--scope workspace]
gemini skills link <path>
gemini skills enable/disable <name>
```

### HarnessSync Impact -- HIGH
**Current approach:** We inline skill content into GEMINI.md as plain markdown sections.
**Better approach:** Write SKILL.md files directly to `.gemini/skills/<name>/SKILL.md`.

This is a much better sync because:
- Skills get proper lazy-loading (not always in context)
- Skills get the `activate_skill` tool flow
- Users can `gemini skills list` to see them
- Skills can include additional assets (scripts, resources)

The Claude Code SKILL.md format (name + description frontmatter + body) is nearly identical to Gemini's format. This could be almost a direct copy.

**Confidence:** HIGH

---

## 5. Native Subagents/Agents Support (NEW, EXPERIMENTAL)

### Agent File Format

**Discovery locations:**
- `.gemini/agents/*.md` (project-level, team-shared)
- `~/.gemini/agents/*.md` (user-level, personal)

### Agent .md Format
```yaml
---
name: security-auditor
description: Specialized agent for security analysis and vulnerability detection.
kind: local
tools:
  - read_file
  - glob
  - run_shell_command(grep)
model: gemini-3-pro
temperature: 0.3
max_turns: 15
timeout_mins: 5
---

You are a security auditor. Your role is to...
```

### Full Schema
| Field | Type | Required | Default |
|-------|------|----------|---------|
| `name` | string | Yes | -- |
| `description` | string | Yes | -- |
| `kind` | string | No | `local` |
| `tools` | string[] | No | default access |
| `model` | string | No | inherit from session |
| `temperature` | number | No | -- |
| `max_turns` | number | No | 15 |
| `timeout_mins` | number | No | 5 |

### HarnessSync Impact -- HIGH
**Current approach:** We inline agent content into GEMINI.md, extracting `<role>` tags.
**Better approach:** Write agent .md files directly to `.gemini/agents/<name>.md`.

The Claude Code agent format uses:
- YAML frontmatter with `name`, `description`
- `<role>` tags for the system prompt

Gemini uses:
- YAML frontmatter with `name`, `description`, plus optional `tools`, `model`, `temperature`, `max_turns`, `timeout_mins`
- Markdown body as system prompt (no `<role>` tags needed)

Translation: Strip `<role>` tags, extract content as markdown body. Map frontmatter fields.

**Confidence:** MEDIUM (subagents are experimental/preview)

---

## 6. Native Custom Commands (NEW)

### Command Format

**Discovery locations:**
- `~/.gemini/commands/` (user-scoped)
- `.gemini/commands/` (project-scoped)

### TOML Format
```toml
description = "Generate a git commit message for staged changes."
prompt = """Review the staged changes and generate a commit message.
Follow conventional commits format.
{{args}}"""
```

**Fields:**
- `prompt` (required): The prompt sent to model
- `description` (optional): Shown in `/help` menu

**Naming:** File path determines command name:
- `.gemini/commands/test.toml` -> `/test`
- `.gemini/commands/git/commit.toml` -> `/git:commit`

**Special syntax in prompts:**
- `{{args}}` -- user-provided arguments
- `!{shell command}` -- inject shell output
- `@{file/path}` -- embed file content

### HarnessSync Impact -- HIGH
**Current approach:** We write brief command descriptions as bullet points in GEMINI.md.
**Better approach:** Write TOML command files to `.gemini/commands/<name>.toml`.

Claude Code commands have:
- YAML frontmatter with `name`, `description`
- A prompt body (the template content)

Translation: Convert to TOML with `description` and `prompt` fields. Map `$ARGUMENTS` -> `{{args}}`.

**Confidence:** HIGH

---

## 7. Extensions System (NEW)

### Extension Structure
```
~/.gemini/extensions/my-extension/
  gemini-extension.json    # Manifest (required)
  GEMINI.md                # Context file (optional)
  commands/                # Custom commands (optional)
    deploy.toml
  skills/                  # Agent skills (optional)
    SKILL.md
  agents/                  # Sub-agents (optional)
  policies/                # Policy rules (optional)
  hooks/hooks.json         # Hooks (optional)
```

### Manifest Format (`gemini-extension.json`)
```json
{
  "name": "my-extension",
  "version": "1.0.0",
  "description": "What this extension does",
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["${extensionPath}/server.js"]
    }
  },
  "contextFileName": "GEMINI.md",
  "excludeTools": ["run_shell_command(rm -rf)"],
  "plan": { "directory": ".gemini/plans" },
  "settings": [
    { "name": "API_KEY", "description": "Your API key", "envVar": "MY_API_KEY", "sensitive": true }
  ],
  "themes": []
}
```

### Variable Substitution
- `${extensionPath}` -- absolute extension directory path
- `${workspacePath}` -- current workspace path
- `${/}` -- platform path separator

### Installation
```bash
gemini extensions install https://github.com/user/my-extension
gemini extensions install /local/path
```

### HarnessSync Impact -- LOW (for now)
- Extensions are their own ecosystem, not directly comparable to Claude Code plugins
- HarnessSync could eventually sync as an extension, but that is a larger architectural change
- For now, continue syncing to individual config files

**Confidence:** HIGH

---

## 8. Hooks System (NEW)

### Hook Configuration (in settings.json)
```json
{
  "hooks": {
    "BeforeTool": [
      {
        "matcher": "run_shell_command",
        "sequential": true,
        "hooks": [
          {
            "type": "command",
            "command": "/path/to/script.sh",
            "name": "pre-shell-check",
            "timeout": 5000,
            "description": "Validate shell commands before execution"
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "echo '{}'",
            "name": "session-init"
          }
        ]
      }
    ]
  }
}
```

### Hook Events
- **Tool:** `BeforeTool`, `AfterTool`
- **Agent:** `BeforeAgent`, `AfterAgent`
- **Model:** `BeforeModel`, `BeforeToolSelection`, `AfterModel`
- **Lifecycle:** `SessionStart`, `SessionEnd`, `Notification`, `PreCompress`

### Communication Protocol
- Input via stdin (JSON)
- Output via stdout (strict JSON only)
- Logging via stderr
- Exit code 0 = success, 2 = block

### HarnessSync Impact -- LOW
- Claude Code doesn't have an equivalent hooks concept
- No sync target for now
- Could be relevant for HarnessSync's own plugin hooks

---

## 9. Policy Engine (NEW, v0.18.0+)

### TOML-based policies in `.gemini/policies/`

Not deeply researched for this doc, but worth noting:
- Fine-grained tool access control
- Can override yolo mode for critical operations
- Three tiers: admin > extension > user/project

### HarnessSync Impact -- LOW
- No Claude Code equivalent
- Not a sync target

---

## 10. Sandbox/Permission Model

### Current State
- `tools.sandbox`: boolean or string (`"docker"`, `"podman"`)
- `security.disableYoloMode`: boolean
- `security.enablePermanentToolApproval`: boolean
- `security.folderTrust.enabled`: boolean (default true, changed to untrusted-by-default in v0.24.0)
- `security.environmentVariableRedaction`: object with `enabled`, `allowed`, `blocked`
- `security.enableConseca`: context-aware security checker (experimental)

### HarnessSync Impact -- LOW
- We already correctly refuse to enable yolo mode
- Sandbox settings don't have a Claude Code equivalent
- No changes needed

---

## Summary: What HarnessSync Needs to Change

### CRITICAL (Broken)
1. **settings.json tools format**: `blockedTools` -> `tools.exclude`, `allowedTools` -> `tools.allowed`

### HIGH (Major Improvement)
2. **Skills**: Write to `.gemini/skills/<name>/SKILL.md` instead of inlining in GEMINI.md
3. **Agents**: Write to `.gemini/agents/<name>.md` instead of inlining in GEMINI.md
4. **Commands**: Write to `.gemini/commands/<name>.toml` instead of bullet points in GEMINI.md

### MODERATE (New Capabilities)
5. **MCP new fields**: Pass through `trust`, `includeTools`, `excludeTools`, `cwd` if present
6. **GEMINI.md imports**: Could use `@` imports to reference separate files

### LOW (Future Consideration)
7. **Extensions**: HarnessSync could distribute as a Gemini extension
8. **Hooks**: No Claude Code equivalent to sync
9. **Policies**: No Claude Code equivalent to sync

---

## Sources

- [Gemini CLI Configuration](https://google-gemini.github.io/gemini-cli/docs/get-started/configuration.html)
- [Gemini CLI Configuration Reference](https://geminicli.com/docs/reference/configuration/)
- [GEMINI.md Documentation](https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html)
- [MCP Servers Documentation](https://google-gemini.github.io/gemini-cli/docs/tools/mcp-server.html)
- [Extensions Documentation](https://google-gemini.github.io/gemini-cli/docs/extensions/)
- [Extension Reference](https://geminicli.com/docs/extensions/reference/)
- [Custom Commands](https://geminicli.com/docs/cli/custom-commands/)
- [Agent Skills](https://geminicli.com/docs/cli/skills/)
- [Creating Skills](https://geminicli.com/docs/cli/creating-skills/)
- [Subagents](https://geminicli.com/docs/core/subagents/)
- [Hooks Reference](https://geminicli.com/docs/hooks/reference/)
- [Sandbox Documentation](https://geminicli.com/docs/cli/sandbox/)
- [Gemini CLI Changelog](https://geminicli.com/docs/changelogs/)
- [Settings Schema](https://raw.githubusercontent.com/google-gemini/gemini-cli/main/schemas/settings.schema.json)
- [V1 Configuration (deprecated)](https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/configuration-v1.md)
