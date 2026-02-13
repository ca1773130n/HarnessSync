# External Integrations

**Analysis Date:** 2026-02-13

## APIs & External Services

### Claude Code (Source System)
- **Purpose**: Single source of truth for configuration (rules, skills, agents, commands, MCP servers)
- **Integration Point**: File system monitoring + JSON/Markdown reading
- **Paths Monitored**:
  - `~/.claude/settings.json` - Settings and environment variables
  - `~/.claude/CLAUDE.md` - User-level rules
  - `~/.claude/skills/` - Skill definitions
  - `~/.claude/agents/` - Agent definitions
  - `~/.claude/commands/` - Slash command definitions
  - `~/.mcp.json` - MCP server configurations
  - Project-level: `.claude/`, `CLAUDE.md`, `CLAUDE.local.md`, `.mcp.json`
- **Auth**: None (local filesystem)
- **Key Implementation**: `get_cc_*` functions in `cc2all-sync.py` (lines 172-306)

### OpenAI Codex CLI
- **Purpose**: Sync destination for Claude Code configurations
- **What Gets Synced**:
  - Rules (CLAUDE.md) → `~/.codex/AGENTS.md`
  - Skills → `~/.codex/skills/` (as symlinks to Claude Code originals)
  - Agents (converted) → `~/.codex/skills/agent-{name}/SKILL.md`
  - Commands (converted) → `~/.codex/skills/cmd-{name}/SKILL.md`
  - MCP servers → `~/.codex/config.toml [mcp_servers]`
  - Environment variables → `~/.codex/config.toml [shell_environment_policy]`
- **Config Format**: TOML for `config.toml`, symlinks for skills
- **Implementation**: `sync_to_codex()` in `cc2all-sync.py` (lines 330-434)
- **Symlink Cleanup**: Stale symlinks removed after sync (lines 428-433)

### Google Gemini CLI
- **Purpose**: Sync destination for Claude Code configurations
- **What Gets Synced**:
  - Rules (CLAUDE.md) → `~/.gemini/GEMINI.md` (inline, at top)
  - Skills → `~/.gemini/GEMINI.md` (inlined as `## Skill: {name}` sections)
  - Agents → `~/.gemini/GEMINI.md` (inlined as `## Agent: {name}` sections)
  - Commands → `~/.gemini/GEMINI.md` (summary list in `## Available Commands`)
  - MCP servers → `~/.gemini/settings.json [mcpServers]`
  - Environment variables → `~/.gemini/.env`
- **Config Format**: Markdown (GEMINI.md), JSON (settings.json), .env file
- **Implementation**: `sync_to_gemini()` and `_sync_gemini_mcp()` in `cc2all-sync.py` (lines 491-588)
- **Special Handling**: Gemini has no native skills system, so skills are inlined into single GEMINI.md file with frontmatter stripped

### OpenCode AI
- **Purpose**: Sync destination for Claude Code configurations
- **What Gets Synced**:
  - Rules (CLAUDE.md) → `~/.config/opencode/AGENTS.md`
  - Skills → `~/.config/opencode/skills/` (as symlinks)
  - Agents → `~/.config/opencode/agents/` (as symlinks to agent .md files)
  - Commands → `~/.config/opencode/commands/` (as symlinks to command .md files)
  - MCP servers → `~/.config/opencode/opencode.json [mcpServers]`
  - Environment variables → `~/.config/opencode/opencode.json [env]`
- **Config Format**: JSON (opencode.json), symlinks for skills/agents/commands
- **Implementation**: `sync_to_opencode()` and `_sync_opencode_mcp()` in `cc2all-sync.py` (lines 594-714)
- **Symlink Cleanup**: Stale symlinks removed after sync (lines 673-680)
- **Fallback Compatibility**: OpenCode natively reads `~/.claude/` as fallback, but explicit `.opencode/` paths take precedence

## MCP Server Integration

**Model Context Protocol (MCP) Sync:**
- **Source Format**: Read from `~/.mcp.json` or `~/.claude/.mcp.json` or project `.mcp.json`
- **Schema Expected**: `{ "mcpServers": { "server_name": { "command", "args", "env", "type", "url" } } }`
- **Target Conversions**:
  - **Codex**: TOML format in `config.toml [mcp_servers.{name}]` section
  - **Gemini**: JSON format in `settings.json [mcpServers]`
  - **OpenCode**: JSON format in `opencode.json [mcpServers]` (with `type: "remote"` for URL-based)
- **URL Handling**: Remote MCP servers (with `url` field) detected and converted to each target's remote format
- **Implementation**: `_build_codex_mcp_toml()` (lines 436-484), `_sync_gemini_mcp()` (lines 559-588), `_sync_opencode_mcp()` (lines 683-714)

## Shell Command Interception

### Shell Integration Wrappers
- **File**: `shell-integration.sh` (sourced in `.bashrc` or `.zshrc`)
- **Wrapped Commands**: `codex`, `gemini`, `opencode`
- **Mechanism**: Function wrapping with background sync trigger
- **Cooldown**: 300 seconds (5 minutes) between auto-syncs to prevent excessive syncing
- **Implementation** (lines 42-67):
  ```bash
  codex() {
      _cc2all_auto_sync all &     # Background sync
      "$_cc2all_original_codex" "$@"
  }
  ```

### Watch Mode Integration
- **Mechanism**: File system monitoring via `fswatch` (macOS), `inotifywait` (Linux), or polling
- **Cooldown**: 3 seconds between sync triggers (debounce)
- **Events Monitored**: Updated, Created, Removed, Renamed
- **Fallback Chain**:
  1. `fswatch -r -l 2` (macOS preferred, recursive, 2s latency)
  2. `inotifywait -mrq` (Linux, modify+create+delete+move)
  3. Polling mode (5s interval) if neither tool available
- **Implementation**: `_watch_fswatch()` (lines 854-868), `_watch_inotify()` (lines 871-884), `_watch_polling()` (lines 887-916)

## Claude Code Hook Integration

### PostToolUse Hook
- **Purpose**: Auto-sync triggered immediately when Claude Code modifies config files
- **Hook Pattern**: Regex matcher on tool input to detect config file changes
- **Files Triggering Sync**: `CLAUDE.md`, `settings.json`, `.mcp.json`, `skills/`, `agents/`, `commands/`
- **Execution**: Asynchronous background process (`&`) to avoid blocking Claude Code
- **Hook Registration**: Created during `install.sh` at `~/.claude/hooks.json` (lines 91-109)
- **Hook Command** (line 101):
  ```bash
  bash -c 'if echo "$CLAUDE_TOOL_INPUT" | grep -qiE "(CLAUDE\.md|settings\.json|\.mcp\.json|skills/|agents/|commands/)" 2>/dev/null; then python3 ~/.cc2all/cc2all-sync.py --scope all >/dev/null 2>&1 & fi'
  ```

## Configuration & Secrets Management

### Environment Variables
- **Supported Env Vars** (from `shell-integration.sh`):
  - `CC2ALL_HOME` - Installation directory (default: `~/.cc2all`)
  - `CC2ALL_COOLDOWN` - Seconds between auto-syncs (default: `300`)
  - `CC2ALL_VERBOSE` - Show sync output on auto-sync (default: `0`)
  - `CODEX_HOME` - Codex home override (default: `~/.codex`)

**How Config Flows**:
1. Claude Code user-level settings in `~/.claude/settings.json`
2. Claude Code project-level settings in `.claude/settings.json` or `.claude/settings.local.json`
3. Function `get_cc_settings()` (line 309-323) merges them
4. Settings are then split by target:
   - `env` field → passed to Codex/Gemini/OpenCode as environment variables
   - `allowedTools` field → (prepared but not currently synced)

### State Persistence
- **Location**: `~/.cc2all/sync-state.json`
- **Contents** (line 802-806):
  ```json
  {
    "last_sync": "2026-02-13 15:30:45",
    "scope": "all",
    "elapsed_ms": 245,
    "_cc2all": {"synced_at": "2026-02-13T15:30:45.123456", "version": "1.0.0"}
  }
  ```
- **Purpose**: Track last sync time, elapsed duration, and sync metadata

### Logs
- **Location**: `~/.cc2all/logs/`
  - `daemon.log` - stdout from launchd daemon
  - `daemon.err` - stderr from launchd daemon
- **Created by**: launchd when running `com.cc2all.sync.plist`

## Sync Scope Architecture

**Two-Level Scope System**:

| Scope | Claude Code Source | Target Directories | Use Case |
|-------|-------------------|-------------------|----------|
| **User** (global) | `~/.claude/` + `~/.mcp.json` | `~/.codex/`, `~/.gemini/`, `~/.config/opencode/` | Global rules, skills, agents for all projects |
| **Project** (local) | `.claude/`, `CLAUDE.md`, `CLAUDE.local.md`, `.mcp.json` | `.codex/`, `GEMINI.md`, `.opencode/`, `opencode.json` | Project-specific rules, skills, and MCP |
| **All** (both) | User + Project (project overrides user) | All targets in both scopes | Complete sync |

**Implementation** (line 785-794):
```python
if scope in ("user", "all"):
    sync_to_codex("user", dry_run=dry_run)
    sync_to_gemini("user", dry_run=dry_run)
    sync_to_opencode("user", dry_run=dry_run)

if scope in ("project", "all") and project_dir:
    sync_to_codex("project", project_dir, dry_run=dry_run)
    sync_to_gemini("project", project_dir, dry_run=dry_run)
    sync_to_opencode("project", project_dir, dry_run=dry_run)
```

## Third-Party CLI Tools Required

**Installation Check** (in `install.sh`):
- Claude Code: `npm install -g @anthropic-ai/claude-code`
- Codex: `npm install -g @openai/codex`
- Gemini CLI: `npm install -g @google/gemini-cli` (note: install script has incorrect package name, should verify)
- OpenCode: `brew install opencode-ai/tap/opencode` (macOS)

**File Watching Tools** (optional but recommended):
- macOS: `fswatch` (check via `command -v fswatch`)
- Linux: `inotifywait` (part of `inotify-tools` package)
- Fallback: Python polling (always works but less efficient)

---

*Integration audit: 2026-02-13*
