# OpenCode Configuration Research (March 2026)

**Researched:** 2026-03-09
**OpenCode version:** v1.2.22 (latest as of 2026-03-08)
**Active repo:** github.com/anomalyco/opencode (the old opencode-ai/opencode was archived Sept 2025)
**Overall confidence:** HIGH (verified against official docs at opencode.ai)

## Executive Summary

OpenCode has evolved significantly since HarnessSync's adapter was written. The current version (v1.2.22) has a mature configuration system with several features that our adapter either doesn't leverage or handles with outdated patterns. The most impactful changes are:

1. **Permission system overhaul** (v1.1.1) -- the old `tools` boolean config is deprecated, merged into `permission` with granular pattern matching
2. **Native skills system** -- OpenCode now has a first-class `skill` tool with `SKILL.md` frontmatter format
3. **Plugin system** -- TypeScript/JS plugins with lifecycle hooks (replaces the concept of hooks entirely)
4. **`instructions` field** -- opencode.json can reference external instruction files via globs and remote URLs
5. **Custom tools** -- TypeScript-based tools in `.opencode/tools/`
6. **Remote config** -- `.well-known/opencode` for org-level defaults

---

## 1. AGENTS.md Format

**Status: UNCHANGED fundamentally, but extended**

AGENTS.md remains the primary rules file. Key details:

- **File locations searched (in order):**
  1. Local files traversing up from CWD: `AGENTS.md`, then fallback to `CLAUDE.md`
  2. Global: `~/.config/opencode/AGENTS.md`
  3. Claude Code compat fallback: `~/.claude/CLAUDE.md`
- **AGENTS.md supersedes CLAUDE.md** when both exist
- The `/init` command generates an AGENTS.md by scanning the project
- **NEW: `instructions` field** in opencode.json supplements AGENTS.md (see section 5)

**HarnessSync impact:** Our current approach of writing managed sections into AGENTS.md is still correct. However, we could alternatively use the `instructions` field in opencode.json to point at source rule files directly, avoiding the marker-based append approach entirely.

**Confidence:** HIGH (verified at https://opencode.ai/docs/rules/)

---

## 2. Skills System

**Status: NATIVE FIRST-CLASS FEATURE -- significant changes needed**

OpenCode now has a native `skill` tool that discovers and loads skills on-demand. This is NOT the same as Claude Code's skills.

### SKILL.md Format (required frontmatter)

```yaml
---
name: my-skill-name
description: What this skill does (1-1024 chars)
license: MIT          # optional
compatibility: react  # optional
metadata:             # optional, string-to-string map
  key: value
---

Skill content/instructions here...
```

### Name validation rules
- 1-64 characters
- Lowercase alphanumeric with single hyphens: `^[a-z0-9]+(-[a-z0-9]+)*$`
- Cannot start/end with `-` or contain `--`
- **Must match the containing directory name**

### Discovery paths (project-level)
- `.opencode/skills/<name>/SKILL.md`
- `.claude/skills/<name>/SKILL.md`  (Claude Code compat!)
- `.agents/skills/<name>/SKILL.md`

### Discovery paths (global)
- `~/.config/opencode/skills/<name>/SKILL.md`
- `~/.claude/skills/<name>/SKILL.md`
- `~/.agents/skills/<name>/SKILL.md`

### Skill permissions in opencode.json
```json
{
  "permission": {
    "skill": {
      "*": "allow",
      "internal-*": "deny",
      "experimental-*": "ask"
    }
  }
}
```

### Agent-level skill control
- Use `tools: { skill: false }` on an agent to disable skill loading entirely
- Use `"skills*": false` at project level to prevent context pollution, then enable per-agent

**HarnessSync impact:** CRITICAL. Our adapter currently symlinks skills to `.opencode/skills/`. But OpenCode expects `SKILL.md` files with YAML frontmatter inside named directories. If Claude Code skills don't have the right frontmatter, they won't load. We need to either:
1. Verify Claude Code skill format matches OpenCode's SKILL.md requirements
2. Transform/wrap skills that lack proper frontmatter

Also notable: OpenCode natively reads `.claude/skills/` -- so if we're syncing from Claude Code's `.claude/skills/` to `.opencode/skills/`, OpenCode might already discover the source skills without our symlinks. This could cause duplicates.

**Confidence:** HIGH (verified at https://opencode.ai/docs/skills/)

---

## 3. Config File Format (opencode.json)

**Status: SIGNIFICANTLY EXPANDED since our adapter was written**

### Full schema (current)
```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4-5",
  "small_model": "anthropic/claude-haiku-4-5",
  "provider": {},
  "server": {},
  "tools": {},                    // DEPRECATED in v1.1.1 -> use "permission"
  "agent": {},
  "default_agent": "plan",
  "command": {},
  "formatter": {},
  "permission": {},               // NEW granular permission system
  "share": "manual",
  "autoupdate": true,
  "compaction": {},
  "watcher": {},
  "mcp": {},
  "plugin": [],                   // NEW plugin system
  "instructions": [],             // NEW external instruction files
  "disabled_providers": [],
  "enabled_providers": [],
  "experimental": {}
}
```

### Variable substitution (new)
```json
{
  "model": "{env:OPENCODE_MODEL}",
  "provider": {
    "anthropic": {
      "options": {
        "apiKey": "{file:~/.secrets/key}"
      }
    }
  }
}
```
- `{env:VARIABLE_NAME}` -- environment variables
- `{file:path/to/file}` -- file contents

### Config file locations (loading order, merged not replaced)
1. Remote config (`.well-known/opencode`)
2. Global config (`~/.config/opencode/opencode.json`)
3. Custom config (`OPENCODE_CONFIG` env var)
4. Project config (`opencode.json` in project root)
5. Inline config (`OPENCODE_CONFIG_CONTENT` env var)

Later configs override conflicting keys; non-conflicting settings merge.

### Supports JSONC
Both `.json` and `.jsonc` (JSON with Comments) are supported.

**HarnessSync impact:** Our adapter writes to `opencode.json` correctly. The `$schema` URL is correct. We should be aware that settings merge across levels. New fields like `instructions`, `plugin`, `compaction`, `watcher`, `formatter` exist but we don't need to sync them (they're OpenCode-specific, not things Claude Code has equivalents for).

**Confidence:** HIGH (verified at https://opencode.ai/docs/config/)

---

## 4. MCP Server Configuration Format

**Status: MOSTLY UNCHANGED, minor additions**

### Local servers
```json
{
  "mcp": {
    "server-name": {
      "type": "local",
      "command": ["npx", "-y", "@some/mcp-server"],
      "environment": { "API_KEY": "value" },
      "enabled": true,
      "timeout": 5000
    }
  }
}
```

### Remote servers
```json
{
  "mcp": {
    "server-name": {
      "type": "remote",
      "url": "https://mcp.example.com/mcp",
      "headers": { "Authorization": "Bearer {env:API_KEY}" },
      "oauth": { "clientId": "...", "scope": "..." },
      "enabled": true,
      "timeout": 5000
    }
  }
}
```

### What's new
- **`timeout` field** (optional): milliseconds for tool fetching, default 5000ms
- **`oauth` field** (optional): OAuth configuration for remote servers, or `false` to disable auto-detection
- **OAuth auto-detection**: OpenCode automatically detects 401 responses and initiates OAuth flows
- **CLI commands**: `opencode mcp auth`, `opencode mcp logout`, `opencode mcp list`, `opencode mcp debug`
- **Token storage**: `~/.local/share/opencode/mcp-auth.json`
- **Env var syntax**: Uses `{env:VAR_NAME}` (curly braces), NOT `${VAR_NAME}` (dollar-curly)

### MCP tool enable/disable (via tools/permission)
```json
{
  "tools": {
    "server-name": false
  },
  "agent": {
    "build": {
      "tools": { "server-name": true }
    }
  }
}
```

**HarnessSync impact:** Our adapter correctly translates MCP configs. Two things to check:
1. We currently output `${VAR_NAME}` for env var references in headers. OpenCode docs show `{env:VAR_NAME}` syntax. Need to verify which is actually used -- both may work, but `{env:VAR_NAME}` is the documented pattern.
2. The `timeout` and `oauth` fields are new and we don't set them -- that's fine, they're optional with sensible defaults.

**Confidence:** HIGH (verified at https://opencode.ai/docs/mcp-servers/)

---

## 5. New Config Types and Locations

### `instructions` field (NEW)
```json
{
  "instructions": [
    "CONTRIBUTING.md",
    "docs/guidelines.md",
    ".cursor/rules/*.md",
    "https://raw.githubusercontent.com/my-org/shared-rules/main/style.md"
  ]
}
```
- Array of paths, glob patterns, and remote URLs
- Combined with AGENTS.md content
- Remote instructions fetched with 5-second timeout
- Supports relative paths from project root

**HarnessSync impact:** This is a potential alternative to our marker-based AGENTS.md approach. Instead of writing managed sections into AGENTS.md, we could add Claude Code rule file paths to the `instructions` array. This would be cleaner and avoid marker management entirely. However, the source files need to exist at stable paths.

### `command` field (commands in opencode.json)
```json
{
  "command": {
    "test": {
      "template": "Run full test suite...",
      "description": "Run tests with coverage",
      "agent": "build",
      "model": "anthropic/claude-haiku-4-5"
    }
  }
}
```
Commands can also be defined as `.md` files in `.opencode/commands/`.

### `compaction` field
```json
{
  "compaction": {
    "auto": true,
    "prune": true,
    "reserved": 10000
  }
}
```

### `watcher` field
```json
{
  "watcher": {
    "ignore": ["node_modules/**", "dist/**"]
  }
}
```

### `formatter` field
Custom code formatters per file extension.

### `.well-known/opencode` (remote org config)
Organizations can serve default configs at a `.well-known/opencode` endpoint. Loaded first, overridden by global and project configs.

**Confidence:** HIGH

---

## 6. Permission/Sandbox Model

**Status: MAJOR OVERHAUL in v1.1.1 -- our adapter is outdated**

### Old format (DEPRECATED)
```json
{
  "tools": {
    "write": false,
    "bash": false
  }
}
```

### New format (current)
```json
{
  "permission": {
    "*": "ask",
    "read": "allow",
    "edit": "ask",
    "bash": {
      "*": "ask",
      "git *": "allow",
      "npm *": "allow",
      "rm *": "deny"
    },
    "skill": {
      "*": "allow",
      "internal-*": "deny"
    },
    "external_directory": {
      "~/projects/personal/**": "allow"
    }
  }
}
```

### Permission actions
- `"allow"` -- executes without approval
- `"ask"` -- prompts user for approval
- `"deny"` -- blocks the action

### All permission keys
| Key | Matches Against | Default |
|-----|----------------|---------|
| `read` | file path | `allow` (except `.env` files -> `deny`) |
| `edit` | file path (covers edit, write, patch, multiedit) | `allow` |
| `glob` | glob pattern | `allow` |
| `grep` | regex pattern | `allow` |
| `list` | directory path | `allow` |
| `bash` | parsed commands | `allow` |
| `task` | subagent type | `allow` |
| `skill` | skill name | `allow` |
| `lsp` | non-granular | `allow` |
| `todoread` | -- | `allow` |
| `todowrite` | -- | `allow` |
| `webfetch` | URL | `allow` |
| `websearch` | query | `allow` |
| `codesearch` | query | `allow` |
| `external_directory` | path | `ask` |
| `doom_loop` | -- | `ask` |

### Pattern matching
- `*` matches zero or more characters
- `?` matches exactly one character
- Last matching rule wins
- `~` and `$HOME` expand to home directory

### Agent-level permission overrides
```json
{
  "agent": {
    "build": {
      "permission": {
        "bash": {
          "*": "ask",
          "git commit *": "deny"
        }
      }
    }
  }
}
```

### Shorthand
```json
{ "permission": "allow" }
```
Sets ALL permissions to a single value.

**HarnessSync impact:** CRITICAL. Our `sync_settings` method writes the old format:
```json
{ "permissions": { "mode": "restricted", "denied": [...] } }
```
This is wrong in multiple ways:
1. The key is `permission` (singular), not `permissions` (plural)
2. There's no `mode` field -- it's action-based (`allow`/`ask`/`deny`)
3. There's no `denied`/`allowed` array -- permissions are per-tool with pattern matching
4. The `tools` boolean approach is deprecated

We need to completely rewrite the settings sync to map Claude Code permissions to OpenCode's granular permission system.

**Confidence:** HIGH (verified at https://opencode.ai/docs/permissions/)

---

## 7. Extensions and Plugin System

**Status: NEW -- OpenCode has a full plugin system**

### Plugin format
Plugins are TypeScript/JavaScript modules with lifecycle hooks:

```javascript
export const MyPlugin = async ({ project, client, $, directory, worktree }) => {
  return {
    // Hook implementations
  }
}
```

### Plugin locations
- **Local (project):** `.opencode/plugins/`
- **Local (global):** `~/.config/opencode/plugins/`
- **NPM packages:** declared in opencode.json `plugin` array

### NPM plugin installation
```json
{
  "plugin": ["opencode-helicone-session", "@my-org/custom-plugin"]
}
```
Packages install automatically via Bun at startup, cached in `~/.cache/opencode/node_modules/`.

### Available hooks
- **Command:** `command.executed`
- **File:** `file.edited`, `file.watcher.updated`
- **Message:** `message.part.removed/updated`, `message.removed/updated`
- **Permission:** `permission.asked`, `permission.replied`
- **Session:** `session.created`, `session.compacted`, `session.deleted`, `session.diff`, `session.error`, `session.idle`, `session.status`, `session.updated`
- **Tool:** `tool.execute.before`, `tool.execute.after`
- **Shell:** `shell.env`
- **TUI:** `tui.prompt.append`, `tui.command.execute`, `tui.toast.show`
- **Todo:** `todo.updated`
- **LSP:** `lsp.client.diagnostics`, `lsp.updated`

### Custom tools via plugins
```typescript
import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Query database",
  args: { query: tool.schema.string().describe("SQL query") },
  async execute(args) { return `Result: ${args.query}` }
})
```

### Custom tools directory
- **Local:** `.opencode/tools/`
- **Global:** `~/.config/opencode/tools/`
- Filename becomes tool name
- TypeScript/JavaScript with Zod schema validation

### Dependencies
Create `.opencode/package.json` for local plugin dependencies; OpenCode runs `bun install` at startup.

**HarnessSync impact:** This is entirely new. Claude Code has hooks (JSON-based), while OpenCode has TypeScript plugins. These are fundamentally different systems. We should NOT try to sync Claude Code hooks to OpenCode plugins -- the formats are too different. However, we should be aware that `.opencode/plugins/` exists and not accidentally conflict with it.

**Confidence:** HIGH (verified at https://opencode.ai/docs/plugins/)

---

## 8. Agents Configuration (Expanded)

### Agent modes
- **`primary`** -- main agent you interact with (Build, Plan)
- **`subagent`** -- specialized, invoked via `@mention` or by primary agents
- **`all`** -- available in both modes

### Built-in agents
| Agent | Type | Description |
|-------|------|-------------|
| Build | primary | Default, all tools enabled |
| Plan | primary | Restricted, file edits/bash set to "ask" |
| General | subagent | Full-access research agent |
| Explore | subagent | Read-only codebase exploration |
| Compaction | system | Auto-summarizes long context |
| Title | system | Auto-generates session titles |
| Summary | system | Creates session summaries |

### Agent markdown format (.opencode/agents/ or ~/.config/opencode/agents/)
```yaml
---
description: Agent purpose
mode: subagent
model: anthropic/claude-sonnet-4-20250514
temperature: 0.7
steps: 50
tools:
  write: false
  edit: false
permission:
  bash: ask
color: "#FF5733"
hidden: false
---

System prompt instructions here.
```

### Agent JSON format (opencode.json)
```json
{
  "agent": {
    "review": {
      "mode": "subagent",
      "description": "Reviews code",
      "model": "anthropic/claude-sonnet-4-20250514",
      "tools": { "write": false, "edit": false },
      "permission": { "bash": "ask" }
    }
  },
  "default_agent": "build"
}
```

**HarnessSync impact:** Our adapter symlinks agents to `.opencode/agents/`. This is correct for markdown-format agents. However, we should verify that Claude Code's agent .md files have compatible frontmatter. OpenCode expects specific frontmatter fields (description, mode, model, tools, permission). If Claude Code agents don't have these, they may not load correctly.

**Confidence:** HIGH (verified at https://opencode.ai/docs/agents/)

---

## Summary of Required HarnessSync Changes

### CRITICAL (broken/outdated)
1. **Permission sync is wrong** -- `permissions.mode` doesn't exist; need `permission` (singular) with `allow/ask/deny` per-tool values
2. **Env var syntax in MCP headers** -- verify `${VAR}` vs `{env:VAR}` handling

### IMPORTANT (functional but suboptimal)
3. **Skills may duplicate** -- OpenCode natively reads `.claude/skills/`, so symlinks to `.opencode/skills/` may cause duplicate skill discovery
4. **Skills need SKILL.md frontmatter validation** -- ensure source skills have required `name` and `description` fields
5. **Agents need frontmatter validation** -- ensure source agent .md files have OpenCode-compatible frontmatter

### NICE TO HAVE (new features to leverage)
6. **`instructions` field** -- could replace marker-based AGENTS.md management for cleaner rule syncing
7. **Custom tools awareness** -- don't conflict with `.opencode/tools/`
8. **Plugin awareness** -- don't conflict with `.opencode/plugins/`

### NOT NEEDED (OpenCode-specific, no Claude Code equivalent)
9. Formatters, compaction, watcher, server config -- OpenCode-specific settings
10. Plugin system -- fundamentally different from Claude Code hooks, no sync path
11. Custom tools -- TypeScript-based, no Claude Code equivalent

---

## Sources

- [OpenCode Config docs](https://opencode.ai/docs/config/)
- [OpenCode Rules docs](https://opencode.ai/docs/rules/)
- [OpenCode Skills docs](https://opencode.ai/docs/skills/)
- [OpenCode Agents docs](https://opencode.ai/docs/agents/)
- [OpenCode Tools docs](https://opencode.ai/docs/tools/)
- [OpenCode MCP Servers docs](https://opencode.ai/docs/mcp-servers/)
- [OpenCode Permissions docs](https://opencode.ai/docs/permissions/)
- [OpenCode Plugins docs](https://opencode.ai/docs/plugins/)
- [OpenCode Custom Tools docs](https://opencode.ai/docs/custom-tools/)
- [OpenCode Changelog](https://opencode.ai/changelog)
- [OpenCode Docker Sandbox docs](https://docs.docker.com/ai/sandboxes/agents/opencode/)
- [anomalyco/opencode GitHub](https://github.com/anomalyco/opencode)
