# OpenCode Research: September 2025 - March 2026

## Project Identity & History

**Two distinct projects exist:**

1. **opencode-ai/opencode** (Go version) - Archived September 18, 2025. Original Go-based TUI.
   The creator partnered with Charm and continued as **Crush**.
2. **anomalyco/opencode** (TypeScript/Bun version) - Active. Fork by Dax Raad / SST team.
   Rewritten from Go to TypeScript on Bun runtime. Rebranded from `sst/opencode` to
   `anomalyco/opencode` in early 2026. 125k GitHub stars. This is the "opencode.ai" project.

**HarnessSync targets the anomalyco/opencode (opencode.ai) version.**

---

## Version Timeline

| Version | Date | Significance |
|---------|------|--------------|
| v1.0.x | Through Dec 2024 | Initial TypeScript release series |
| v1.1.1 | Jan 4, 2025 | **Major**: Permissions overhaul |
| v1.1.64 | Feb 12, 2025 | Last v1.1.x |
| v1.2.0 | Feb 14, 2025 | **Major**: SQLite migration, SDK PartDelta |
| v1.2.7 | Feb 19, 2025(6) | Bun.file() -> Filesystem module migration |
| v1.2.17 | Mar 4, 2026 | Workspace integration rework |
| v1.2.27 | Mar 16, 2026 | Latest (as of research date) |

---

## Major Changes Affecting Sync (Sept 2025 - Mar 2026)

### 1. Config File Format (opencode.json / opencode.jsonc)

- **Format**: JSON or JSONC (JSON with Comments)
- **Schema**: `https://opencode.ai/config.json`
- **Location precedence** (later overrides earlier):
  1. Remote config (`.well-known/opencode`) - org defaults
  2. Global config (`~/.config/opencode/opencode.json`)
  3. Custom config (`OPENCODE_CONFIG` env var)
  4. Project config (`opencode.json` in project root)
  5. `.opencode` directories (agents, commands, plugins, etc.)
  6. Inline config (`OPENCODE_CONFIG_CONTENT` env var)
- **TUI config** is separate: `tui.json` (project) or `~/.config/opencode/tui.json` (global)
- **Directory convention**: `.opencode/` and `~/.config/opencode/` use **plural** subdirectory
  names: `agents/`, `commands/`, `modes/`, `plugins/`, `skills/`, `tools/`, `themes/`.
  Singular names still supported for backwards compatibility.

### 2. Permissions System (v1.1.1+)

- **`tools` config deprecated** -> merged into `permission` (singular) field
- Old `tools` config still supported for backwards compat, auto-migrated
- Three actions: `"allow"`, `"ask"`, `"deny"`
- **Granular object syntax** with glob pattern matching:
  ```json
  {
    "permission": {
      "bash": {
        "*": "ask",
        "git *": "allow",
        "rm *": "deny"
      },
      "edit": {
        "*.md": "allow",
        "*": "deny"
      }
    }
  }
  ```
- Wildcard matching: `*` (zero or more chars), `?` (exactly one char)
- Home directory expansion: `~` and `$HOME` in patterns
- **`external_directory`** permission for paths outside working directory
- **Per-agent permission overrides** in agent config
- **MCP tool wildcards**: `"mymcp_*": "ask"` controls all tools from an MCP server

### 3. MCP Server Configuration

- Config key: `"mcp"` in opencode.json
- **Local servers**: `"type": "local"`, command as array, environment vars
  ```json
  {
    "mcp": {
      "my-server": {
        "type": "local",
        "command": ["npx", "-y", "my-mcp-command"],
        "enabled": true,
        "environment": { "MY_VAR": "value" }
      }
    }
  }
  ```
- **Remote servers**: `"type": "remote"`, url, optional headers
  ```json
  {
    "mcp": {
      "my-remote": {
        "type": "remote",
        "url": "https://example.com/mcp",
        "headers": { "Authorization": "Bearer token" },
        "enabled": true
      }
    }
  }
  ```
- **`enabled` field**: Can be `true`/`false` to toggle without removing
- **Remote org defaults**: Organizations can provide MCP servers via `.well-known/opencode`
  endpoint, disabled by default, users opt in locally

### 4. Rules / Instructions

- **Primary**: `AGENTS.md` in project root (equivalent to CLAUDE.md)
- **Global**: `~/.config/opencode/AGENTS.md`
- **Claude Code compatibility** (fallback if no AGENTS.md):
  - `CLAUDE.md` in project (if no `AGENTS.md`)
  - `~/.claude/CLAUDE.md` (if no `~/.config/opencode/AGENTS.md`)
  - `~/.claude/skills/` (if no opencode skills)
- **Disable compat** via env vars:
  - `OPENCODE_DISABLE_CLAUDE_CODE=1` (all)
  - `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1` (only ~/.claude/CLAUDE.md)
  - `OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1` (only skills)
- **Custom instructions in config**:
  ```json
  {
    "instructions": ["CONTRIBUTING.md", "docs/guidelines.md", ".cursor/rules/*.md"]
  }
  ```
  Supports glob patterns and remote URLs (fetched with 5s timeout).
  All instruction files combined with AGENTS.md.
- **`/init` command** auto-generates AGENTS.md by scanning project

### 5. Agents System (replaces Modes)

- **`mode` config deprecated** -> replaced by `agent` config
- Two types: **primary agents** (direct interaction, Tab to switch) and **subagents** (invoked by primary agents or via @ mention)
- Built-in primary: **Build** (all tools) and **Plan** (restricted)
- Built-in subagents: **General** (full access) and **Explore** (read-only)
- Hidden system agents: **Compaction** and **Title**
- **Custom agents** via JSON config or markdown files:
  - Global: `~/.config/opencode/agents/`
  - Project: `.opencode/agents/`
  - Markdown frontmatter: model, temperature, tools, description, mode, permission
- **Per-agent permissions** override global permissions

### 6. Agent Skills

- **Location**: `.opencode/skills/<name>/SKILL.md`
- **Global**: `~/.config/opencode/skills/<name>/SKILL.md`
- **Claude compat paths**: `.claude/skills/*/SKILL.md`, `.agents/skills/*/SKILL.md`
- **Frontmatter**: name (required), description (required), license, compatibility, metadata
- **Name validation**: lowercase alphanumeric, single-hyphen separators, 1-64 chars
- Skills are loaded on-demand via the native `skill` tool
- OpenCode walks up from cwd to git worktree root, loading skills along the way

### 7. Custom Commands

- **Location**: `.opencode/commands/<name>.md` (project) or `~/.config/opencode/commands/` (global)
- Also configurable in JSON:
  ```json
  {
    "command": {
      "test": {
        "template": "Run tests...",
        "description": "Run tests with coverage",
        "agent": "build",
        "model": "anthropic/claude-3-5-sonnet-20241022"
      }
    }
  }
  ```
- Markdown frontmatter: description, agent, model
- Supports `$ARGUMENTS`, `$1`/`$2` positional params
- `!command` syntax injects bash output into prompt
- `@filename` includes files in prompt
- Can override built-in commands

### 8. Custom Tools

- **Location**: `.opencode/tools/<name>.ts` (project) or `~/.config/opencode/tools/` (global)
- Defined as TypeScript/JavaScript files using `@opencode-ai/plugin` SDK
- `tool()` helper with Zod schema for args
- Filename becomes tool name; multiple exports create `<file>_<export>` names
- Can override built-in tools (custom takes precedence)
- External npm deps via `.opencode/package.json`

### 9. Plugin System

- **Location**: `.opencode/plugins/` (project) or `~/.config/opencode/plugins/` (global)
- Also from npm packages in config:
  ```json
  { "plugin": ["opencode-helicone-session", "opencode-wakatime"] }
  ```
- npm plugins auto-installed via Bun, cached in `~/.cache/opencode/node_modules/`
- Local plugins need `.opencode/package.json` for external deps
- **Plugin hooks** (event-based): tool.execute.before, tool.execute.after, etc.
- Load order: global config -> project config -> global plugins dir -> project plugins dir

### 10. SQLite Data Migration (v1.2.0+)

- All flat files in data directory migrated to single SQLite database on first run
- Database location: `~/.local/share/opencode/opencode.db*` (Linux/Mac), `%APPDATA%` (Windows)
- Can retrigger by deleting db files; original data preserved for downgrade

### 11. Desktop App & IDE Extension

- **Desktop**: Tauri (primary) and Electron (alternative) implementations
- **VS Code extension**: Auto-installs when running `opencode` in VS Code integrated terminal
- Works with VS Code, Cursor, Windsurf, VSCodium
- Keybinds: Cmd+Esc to open, Cmd+Shift+Esc for new session, Cmd+Option+K for file refs

### 12. OpenCode Go (Subscription)

- $5 first month, then $10/month for access to open models (GLM-5, Kimi K2.5, MiniMax M2.5/M2.7)
- Works as a provider, configured via `/connect` command
- Usage limits: 5-hour, weekly, monthly caps

### 13. Built-in Tools

- bash, edit, write, read, grep, glob, list, patch, multiedit, fetch, todoread, todowrite, webfetch, websearch, subagent, skill
- All tools controlled by `permission` config
- `write` tool controlled by `edit` permission (covers edit, write, patch, multiedit)

### 14. Miscellaneous Changes (from release notes)

- **v1.2.7**: Major migration from Bun.file() to Filesystem module across all tools
- **v1.2.7**: Added support for medium reasoning with Gemini 3.1
- **v1.2.17**: Reworked workspace integration and adaptor interface
- **v1.2.27**: Effectify PermissionNext, fix lost sessions across worktrees, increased default chunk timeout from 2 to 5 minutes
- Ongoing: Frequent AI SDK package bumps (Google, Anthropic, Bedrock, etc.)

---

## Impact on HarnessSync Adapter

### Currently Correct in Adapter
- AGENTS.md as rules target with managed markers
- .opencode/skills/, .opencode/agents/, .opencode/commands/ symlinks
- opencode.json with `mcp` key using type: "local"/"remote"
- `permission` (singular) key with per-tool allow/ask/deny
- Bash pattern translation (Bash(git commit:*) -> "git commit *")
- Schema URL: https://opencode.ai/config.json
- Skipping .claude/skills/ (native Claude Code compat)

### Potential Improvements / Gaps
1. **`instructions` config**: Could sync CLAUDE.md path references to `instructions` array
   in opencode.json instead of (or in addition to) writing AGENTS.md directly
2. **`enabled` field on MCP**: Already present in adapter, good
3. **Custom tools**: No sync path for custom tools (TypeScript-specific, may not be relevant)
4. **Plugin system**: No sync path (TypeScript-specific)
5. **`tui.json`**: Separate from opencode.json; keybinds/themes not synced (probably fine)
6. **Per-agent permissions**: Could map Claude Code agent-specific settings
7. **`external_directory` permission**: No equivalent in Claude Code currently
8. **Remote config (.well-known/opencode)**: Organizational feature, not applicable to sync
9. **JSONC support**: Adapter writes JSON, which is valid JSONC (no issue)
10. **`OPENCODE_DISABLE_CLAUDE_CODE`**: If user sets this, AGENTS.md still works but
    .claude/ fallbacks are disabled - adapter should be aware

---

## Sources

- https://github.com/anomalyco/opencode/releases
- https://opencode.ai/docs/config/
- https://opencode.ai/docs/mcp-servers/
- https://opencode.ai/docs/agents/
- https://opencode.ai/docs/tools/
- https://opencode.ai/docs/rules/
- https://opencode.ai/docs/permissions/
- https://opencode.ai/docs/custom-tools/
- https://opencode.ai/docs/plugins/
- https://opencode.ai/docs/skills/
- https://opencode.ai/docs/commands/
- https://opencode.ai/docs/modes/
- https://opencode.ai/docs/ide/
- https://opencode.ai/docs/go/
- https://github.com/anomalyco/opencode/releases/tag/v1.1.1
- https://github.com/anomalyco/opencode/releases/tag/v1.2.0
