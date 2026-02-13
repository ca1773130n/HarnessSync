# Architecture

**Analysis Date:** 2026-02-13

## System Overview

**cc2all** is a single-source-of-truth synchronization engine that automatically propagates Claude Code configuration to three alternative AI development environments:
- OpenAI Codex CLI
- Google Gemini CLI
- OpenCode

The system enables users to configure rules, skills, agents, commands, and MCP servers in Claude Code once, and have those settings automatically sync to all three harnesses without manual duplication or tooling conflicts.

**Core principle:** Claude Code (`~/.claude/`) is the authoritative source. All other systems pull and adapt configuration from it.

## Design Patterns

### 1. **Adapter Pattern** (Primary)
Each target harness (Codex, Gemini, OpenCode) has its own sync module that translates Claude Code concepts into target-specific formats:

- **Codex adapter** (`sync_to_codex()` in `cc2all-sync.py` lines 330-434): Converts CLAUDE.md rules to AGENTS.md, skills to symlinks, agents to SKILL.md format
- **Gemini adapter** (`sync_to_gemini()` lines 491-557): Generates monolithic GEMINI.md with rules, skills, agents inlined
- **OpenCode adapter** (`sync_to_opencode()` lines 594-681): Creates explicit .opencode/ paths with symlinks and AGENTS.md

### 2. **Composite Source Pattern**
Claude Code supports both **user-scope** (global `~/.claude/`) and **project-scope** (local `.claude/`, `CLAUDE.md`) configuration. The sync engine merges these:

```python
# Example: get_cc_rules() in lines 172-192
# Combines:
#  1. ~/.claude/CLAUDE.md (user-level)
#  2. CLAUDE.md / CLAUDE.local.md (project-root)
#  3. .claude/CLAUDE.md (project subdirectory)
```

This allows project-specific overrides while maintaining global defaults.

### 3. **Scope Abstraction**
Three scope modes control what gets synced:

| Scope | Sources | Targets |
|-------|---------|---------|
| `user` | `~/.claude/`, `~/.mcp.json` | `~/.codex/`, `~/.gemini/`, `~/.config/opencode/` |
| `project` | `.claude/`, `CLAUDE.md`, `.mcp.json` (current dir) | `.codex/`, `GEMINI.md`, `.opencode/`, `opencode.json` (current dir) |
| `all` | Both user and project sources | All targets in both scopes |

### 4. **Symlink Strategy for Caching**
Skills and agents use symlinks rather than file copies:

```
~/.claude/skills/my-skill/  ← Source (single copy, mutable)
        ↓ symlink
~/.codex/skills/my-skill/ → ~/.claude/skills/my-skill/
~/.config/opencode/skills/my-skill/ → ~/.claude/skills/my-skill/
```

**Benefit:** When a skill is updated in Claude Code, Codex and OpenCode see changes immediately without re-sync.

### 5. **File Hash Change Detection**
State tracking prevents redundant syncs (`file_hash()` in lines 119-123):

```python
def file_hash(path: Path) -> str:
    """SHA256 first 16 chars for change detection."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
```

Used in watch mode to trigger sync only on actual changes.

### 6. **Conversion Engine for Format Differences**
Claude Code agents → Codex skills (no native agent support):

```python
# sync_to_codex() lines 376-398
# Wraps agent .md in SKILL.md format with frontmatter
skill_md = f"---\nname: agent-{name}\n---\n\n{agent_content}"
```

Similar conversion for commands → SKILL.md format.

## Key Components

### 1. **Configuration Reader** (`get_cc_*` functions, lines 172-323)

Discovers and reads Claude Code configuration across user and project scopes.

| Function | Purpose | Returns |
|----------|---------|---------|
| `get_cc_rules(scope, project_dir)` | Read CLAUDE.md rules | `str` (merged rules markdown) |
| `get_cc_skills(scope, project_dir)` | Discover skill directories | `dict[name: Path]` |
| `get_cc_agents(scope, project_dir)` | Discover agent .md files | `dict[name: Path]` |
| `get_cc_commands(scope, project_dir)` | Discover command .md files | `dict[name: Path]` |
| `get_cc_mcp(scope, project_dir)` | Read MCP server configs | `dict` (mcpServers) |
| `get_cc_settings(scope, project_dir)` | Read env/permissions | `dict` (settings) |

**Scanning order for skills:**
1. `~/.claude/skills/` (user skills)
2. `~/.claude/plugins/cache/` (plugin-installed skills)
3. `.claude/skills/` (project skills)

### 2. **Sync Orchestrator** (`run_sync()`, lines 776-806)

Main dispatcher that calls target-specific adapters based on scope:

```python
def run_sync(scope: str, project_dir: Path = None, dry_run: bool = False):
    # 1. Load all Claude Code configuration
    # 2. Dispatch to target adapters (codex, gemini, opencode)
    # 3. Log results with summary statistics
    # 4. Save state for cooldown/throttling
```

Returns structured output:
- Lines synced/skipped/errored
- Duration in milliseconds
- State saved to `~/.cc2all/sync-state.json`

### 3. **Watch & Trigger System** (lines 813-916)

Three monitoring strategies with automatic fallback:

| Strategy | Detection | OS | Code |
|----------|-----------|----|----|
| **fswatch** | Real-time events | macOS | `_watch_fswatch()` (lines 854-868) |
| **inotifywait** | Kernel events | Linux | `_watch_inotify()` (lines 871-884) |
| **Polling** | File hash + mtime | All | `_watch_polling()` (lines 887-916) |

Each triggers `run_sync()` with 3-second cooldown to debounce rapid changes.

### 4. **Shell Integration** (`shell-integration.sh`)

Provides three auto-sync mechanisms:

**A. Command Wrappers** (lines 42-67):
```bash
codex() {
    _cc2all_auto_sync all &  # Background sync, 5min cooldown
    "$_cc2all_original_codex" "$@"
}
# Same for: gemini(), opencode()
```

**B. Cooldown Timer** (lines 17-27):
```bash
_cc2all_should_sync() {
    # Check: last_sync + CC2ALL_COOLDOWN < now
    # Returns true only after 300s (5 min default)
}
```

**C. Manual Helpers** (lines 71-130):
- `cc2all [sync] [scope]` — Sync now
- `cc2all watch [scope]` — Watch mode
- `cc2all force [scope]` — Ignore cooldown
- `cc2all status` — Show sync status

### 5. **Claude Code Hook Integration** (`install.sh` lines 67-109)

When Claude Code writes to config files (`CLAUDE.md`, `.mcp.json`, `skills/`, etc.), a PostToolUse hook triggers:

```json
{
  "hook": {
    "type": "command",
    "command": "bash -c 'if [[ config-file ]] then python3 ~/.cc2all/cc2all-sync.py --scope all & fi'"
  }
}
```

This achieves immediate sync on configuration changes without needing shell interaction.

### 6. **macOS Background Daemon** (`com.cc2all.sync.plist`)

launchd daemon runs sync continuously in watch mode:

```xml
<key>ProgramArguments</key>
<array>
    <string>/usr/bin/python3</string>
    <string>~/.cc2all/cc2all-sync.py</string>
    <string>--watch</string>
    <string>--scope</string>
    <string>user</string>
</array>
<key>KeepAlive</key>
<true/>  <!-- Restart if crashed -->
```

## Entry Points

### 1. **Python Main** (`cc2all-sync.py`)

```bash
python3 ~/.cc2all/cc2all-sync.py [--scope user|project|all] [--watch] [--dry-run] [--verbose]
```

Entry point: `main()` function (lines 932-979)

**Argument parsing:**
- `--scope` — What to sync (default: `all`)
- `--watch` — Enable watch mode (default: one-shot)
- `--project-dir` — Override project detection (auto-detects `.git`)
- `--dry-run` — Preview without writing
- `--verbose` — Show detailed output

**Flow:**
1. Parse arguments
2. Auto-detect project directory (walk up for `.git`)
3. Choose mode:
   - Watch mode: `watch_and_sync()` → continuous monitoring
   - One-shot: `run_sync()` → sync once, exit

### 2. **Shell Wrapper** (`shell-integration.sh`)

```bash
source ~/.cc2all/shell-integration.sh
```

Defines function `cc2all()` with subcommands and wraps `codex`, `gemini`, `opencode` CLI commands.

### 3. **Installer** (`install.sh`)

```bash
bash ~/.cc2all/install.sh
```

Five-step installation:
1. Copy Python script and shell integration
2. Verify CLI tools installed (Claude Code, Codex, Gemini, OpenCode)
3. Create target directories
4. Register Claude Code hook (optional)
5. Add shell integration to `.bashrc` or `.zshrc`

### 4. **macOS Daemon** (via `launchctl`)

```bash
launchctl load ~/Library/LaunchAgents/com.cc2all.sync.plist
```

Starts background daemon running `cc2all-sync.py --watch --scope user` continuously.

## State Management

### Persistence

**State file:** `~/.cc2all/sync-state.json`

```json
{
  "last_sync": "2026-02-13 14:30:45",
  "scope": "all",
  "elapsed_ms": 234
}
```

Saved after every sync to track last run. Used by shell integration for cooldown timer (reads `last_sync` timestamp).

### Caching Strategy

**No output caching.** Each sync reads all source files fresh and compares hashes to detect changes. Targets (Codex, Gemini, OpenCode) decide what to load based on file mtimes and their own caching.

### Cooldown/Throttling

Two levels:

1. **Shell integration cooldown** (`CC2ALL_COOLDOWN=300` env var, 5 minutes default)
   - Prevents repeated syncs when running `codex`, `gemini`, `opencode` frequently
   - Stored in timestamp file: `~/.cc2all/.last-sync`

2. **Watch mode debounce** (3 second delay in lines 862, 878)
   - Prevents sync on every file event during bulk changes
   - Accumulates changes, then syncs once

### Logging

**Log directory:** `~/.cc2all/logs/`
- `daemon.log` — launchd daemon stdout (from plist)
- `daemon.err` — launchd daemon stderr (from plist)
- Console output during manual runs (if `--verbose`)

**Logger class** (`Logger`, lines 75-109 in `cc2all-sync.py`):
- Colored output with status counts
- `info()`, `warn()`, `error()`, `skip()`, `debug()` methods
- `summary()` for final report

---

*Architecture analysis: 2026-02-13*
