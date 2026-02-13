# Project Structure

**Analysis Date:** 2026-02-13

## Directory Layout

```
HarnessSync/
├── cc2all-sync.py                 # Main sync engine (984 lines)
├── shell-integration.sh           # Shell function wrappers and helpers (164 lines)
├── install.sh                     # Installation and setup script (161 lines)
├── com.cc2all.sync.plist          # macOS launchd daemon config (30 lines)
├── README.md                      # Documentation and usage guide
├── LICENSE                        # License file
└── .planning/
    └── codebase/
        ├── ARCHITECTURE.md        # (this document)
        └── STRUCTURE.md           # System organization guide
```

## Root-Level Files & Purposes

| File | Lines | Purpose |
|------|-------|---------|
| `cc2all-sync.py` | 984 | Main Python sync engine. Reads Claude Code config, adapts to Codex/Gemini/OpenCode formats, manages state and watch mode. Single entrypoint for all sync operations. |
| `shell-integration.sh` | 164 | Shell function definitions. Wraps `codex`, `gemini`, `opencode` commands; provides `cc2all` manual command; handles cooldown logic and target status checks. |
| `install.sh` | 161 | Interactive installer. Copies files to `~/.cc2all/`, verifies CLI tools, creates target directories, registers Claude Code hooks, integrates with shell RC files. |
| `com.cc2all.sync.plist` | 30 | macOS launchd plist. Configures background daemon to run `cc2all-sync.py --watch --scope user` continuously with auto-restart on crash. |
| `README.md` | 157 | Korean-language documentation. Explains architecture diagram, sync mapping table, installation steps, usage commands, and troubleshooting. |
| `LICENSE` | — | Standard software license |

## Installation File Structure

After `bash install.sh`, the following directories are created:

### Installation Target: `~/.cc2all/`

```
~/.cc2all/
├── cc2all-sync.py              # Copied from repo
├── shell-integration.sh         # Copied from repo
├── .last-sync                  # Timestamp file (cooldown tracking)
├── sync-state.json             # State persistence (last sync info)
└── logs/
    ├── daemon.log              # launchd stdout
    └── daemon.err              # launchd stderr
```

### Shell Integration: Modified RC Files

- `~/.bashrc` or `~/.zshrc` — One line added: `source "$HOME/.cc2all/shell-integration.sh"`

### Claude Code Hook: `~/.claude/hooks.json`

Created/modified to register PostToolUse hook that auto-syncs when Claude Code edits config files.

### Target Directories Created

```
~/.codex/
├── skills/                     # Symlinks to ~/.claude/skills/
├── AGENTS.md                   # Auto-generated from CLAUDE.md
└── config.toml                 # MCP server config

~/.gemini/
├── GEMINI.md                   # Auto-generated monolithic config
├── settings.json               # MCP servers (if present)
└── extensions/                 # User's Gemini extensions (untouched)

~/.config/opencode/
├── skills/                     # Symlinks to ~/.claude/skills/
├── agents/                     # Symlinks to ~/.claude/agents/
├── commands/                   # Symlinks to ~/.claude/commands/
└── AGENTS.md                   # Auto-generated from CLAUDE.md
```

## File Naming Conventions

### Python Code (`cc2all-sync.py`)

**Constants** (SCREAMING_SNAKE_CASE):
- `VERSION = "1.0.0"` (line 34)
- `CC_HOME = Path.home() / ".claude"` (line 37)
- `CODEX_HOME`, `GEMINI_HOME`, `OC_HOME` (lines 47-59)
- `STATE_DIR`, `STATE_FILE`, `LOG_DIR` (lines 67-69)

**Functions** (snake_case):
- `ensure_dir(path: Path)` (line 115)
- `file_hash(path: Path) -> str` (line 119)
- `read_json(path: Path) -> dict` (line 126)
- `write_json(path: Path, data: dict)` (line 136)
- `sync_to_codex()`, `sync_to_gemini()`, `sync_to_opencode()` (main adapters)
- `get_cc_rules()`, `get_cc_skills()`, `get_cc_agents()`, etc. (config readers)
- `_watch_fswatch()`, `_watch_inotify()`, `_watch_polling()` (watch implementations)
- Helper functions prefixed with `_`: `_build_codex_mcp_toml()`, `_sync_gemini_mcp()`, etc.

**Classes** (PascalCase):
- `Logger` (line 75) — Logging utility with colored output

**Type annotations:**
Used throughout for clarity:
```python
def get_cc_skills(scope: str, project_dir: Path = None) -> dict[str, Path]:
def sync_to_codex(scope: str, project_dir: Path = None, dry_run: bool = False):
```

### Shell Script (`shell-integration.sh`)

**Variables** (snake_case for local, SCREAMING_SNAKE_CASE for env):
- `CC2ALL_HOME`, `CC2ALL_SYNC`, `CC2ALL_COOLDOWN` (env vars, lines 12-14)
- `_cc2all_should_sync()`, `_cc2all_auto_sync()` (private functions)
- `codex()`, `gemini()`, `opencode()`, `cc2all()` (public functions)

**Naming convention:**
- Private functions prefixed with `_cc2all_`
- Public command wrappers match their CLI names exactly

### Installation Script (`install.sh`)

**Color codes** (ANSI escapes):
- `BOLD`, `BLUE`, `GREEN`, `YELLOW`, `RED`, `NC` (lines 8-13)

**Variables** (SCREAMING_SNAKE_CASE):
- `SCRIPT_DIR`, `CC2ALL_HOME`, `SHELL_RC`, `SOURCE_LINE` (lines 15-121)

**Functions** (snake_case):
- `check_cli()` (lines 40-49) — Verify CLI tool is installed

## Module Organization

### Monolithic Architecture

All functionality is in **one Python file** (`cc2all-sync.py`, 984 lines) with logical sections:

| Lines | Section | Modules |
|-------|---------|---------|
| 30-70 | Constants | Path definitions for Claude Code, Codex, Gemini, OpenCode |
| 75-112 | Logger class | Colored output, counters, formatting |
| 115-166 | Utility functions | File I/O, symlink creation, state persistence |
| 172-323 | Source readers | `get_cc_*()` family of config discovery functions |
| 330-485 | Codex adapter | `sync_to_codex()` + TOML builder |
| 491-588 | Gemini adapter | `sync_to_gemini()` + settings sync |
| 594-715 | OpenCode adapter | `sync_to_opencode()` + MCP sync |
| 721-770 | Settings sync | Project-level env/permissions propagation |
| 776-806 | Orchestrator | `run_sync()` main dispatcher |
| 813-916 | Watch mode | Monitoring strategies (fswatch, inotify, polling) |
| 923-983 | CLI | Argument parsing and main entry point |

### Dependency Flow

```
main() ─────────────┐
                    ▼
            run_sync(scope)
               │
    ┌──────────┼──────────────┐
    │          │              │
    ▼          ▼              ▼
Config Readers   Target Adapters   Watch & State
├─ get_cc_rules()  ├─ sync_to_codex()    ├─ watch_and_sync()
├─ get_cc_skills() ├─ sync_to_gemini()   ├─ load_state()
├─ get_cc_agents() ├─ sync_to_opencode() └─ save_state()
├─ get_cc_commands()
├─ get_cc_mcp()
└─ get_cc_settings()
```

### Import Pattern

Only standard library imports, no external dependencies:

```python
import argparse        # CLI argument parsing
import hashlib         # SHA256 for file hashing
import json            # JSON read/write
import os              # Environment variables
import re              # Regex for YAML frontmatter stripping
import shutil          # File operations, command detection
import subprocess      # Execute fswatch/inotifywait
import sys             # Exit codes
import time            # Cooldown timing
from datetime import datetime  # Timestamps
from pathlib import Path       # Modern path handling
from typing import Any        # Type hints
```

**No external packages required.** This is intentional — the tool must work with minimal dependencies.

## Key Files & What They Do

### `cc2all-sync.py` — Configuration Read → Transform → Write

**Main tasks:**

1. **Discover Claude Code config** (lines 172-323)
   - Scan `~/.claude/` and `.claude/` directories
   - Read `.md` files (rules, agents, commands)
   - Parse `.json` files (settings, MCP)
   - Merge plugin-installed skills

2. **Transform to target formats** (lines 330-715)
   - **Codex:** Rules → AGENTS.md, skills → symlinks, agents → SKILL.md wrappers, MCP → TOML
   - **Gemini:** Rules + skills + agents → monolithic GEMINI.md, MCP → settings.json
   - **OpenCode:** Rules → AGENTS.md, everything → symlinks, MCP → opencode.json

3. **Handle scope logic** (lines 776-806)
   - User scope: Only use `~/.claude/`
   - Project scope: Only use `.claude/` + `CLAUDE.md`
   - All scope: Merge both

4. **Monitor & react** (lines 813-916)
   - Watch mode: Detect changes → trigger sync
   - Cooldown: Prevent rapid re-syncs
   - Fallback strategies: fswatch → inotify → polling

### `shell-integration.sh` — User-Facing Interface

**Responsibilities:**

1. **Command wrappers** (lines 42-67)
   - Intercept `codex()`, `gemini()`, `opencode()` calls
   - Trigger background sync with cooldown check
   - Pass through to original commands

2. **Cooldown logic** (lines 17-27)
   - Track last sync timestamp in `~/.cc2all/.last-sync`
   - Only run sync if `now - last_sync > CC2ALL_COOLDOWN` (300s default)

3. **Manual commands** (lines 71-130)
   - `cc2all [sync]` — One-shot sync
   - `cc2all watch` — Watch mode
   - `cc2all force` — Ignore cooldown
   - `cc2all status` — Show last sync time + target status

4. **Status reporting** (lines 132-141)
   - `_cc2all_check_target()` — Show line count + mtime for each target

### `install.sh` — First-Run Setup

**Five phases:**

1. **Copy files** (lines 23-34)
   - `cc2all-sync.py` → `~/.cc2all/`
   - `shell-integration.sh` → `~/.cc2all/`
   - Make executable

2. **Verify CLI tools** (lines 37-54)
   - Check for Claude Code, Codex, Gemini, OpenCode
   - Warn if any are missing

3. **Create target directories** (lines 57-65)
   - `~/.codex/skills/`
   - `~/.gemini/`
   - `~/.config/opencode/{skills,agents,commands}/`

4. **Register Claude Code hook** (lines 68-109)
   - Read or create `~/.claude/hooks.json`
   - Add PostToolUse hook to trigger sync on config changes

5. **Shell integration** (lines 112-136)
   - Detect shell (zsh or bash)
   - Add source line to RC file
   - Provide manual instructions if shell detection fails

### `com.cc2all.sync.plist` — Background Daemon

**macOS launchd configuration:**

- **Program:** `/usr/bin/python3`
- **Arguments:** `~/.cc2all/cc2all-sync.py --watch --scope user`
- **RunAtLoad:** Yes (start on login)
- **KeepAlive:** Yes (restart if crashed)
- **Output:** `~/.cc2all/logs/daemon.log` and `.err`

**Note:** Runs as user (not root), so only has access to user-scope configuration.

## Configuration Files & Their Roles

### Consumed Configurations

| Path | Format | Purpose | Scope | Optional |
|------|--------|---------|-------|----------|
| `~/.claude/CLAUDE.md` | Markdown | Global rules/system prompt | User | Yes |
| `~/.claude/skills/*/SKILL.md` | Markdown + YAML FM | Skill definitions | User | Yes |
| `~/.claude/agents/*.md` | Markdown | Agent definitions | User | Yes |
| `~/.claude/commands/*.md` | Markdown | Slash command definitions | User | Yes |
| `~/.mcp.json` or `~/.claude/.mcp.json` | JSON | MCP server configs | User | Yes |
| `~/.claude/settings.json` | JSON | Environment variables, permissions | User | Yes |
| `CLAUDE.md` | Markdown | Project rules (project root) | Project | Yes |
| `.claude/CLAUDE.md` | Markdown | Project rules (project subdir) | Project | Yes |
| `.claude/skills/*/SKILL.md` | Markdown + YAML FM | Project skills | Project | Yes |
| `.claude/agents/*.md` | Markdown | Project agents | Project | Yes |
| `.claude/commands/*.md` | Markdown | Project commands | Project | Yes |
| `.mcp.json` | JSON | Project MCP servers | Project | Yes |
| `.claude/settings.json` | JSON | Project env/permissions | Project | Yes |

### Generated Configurations

| Path | Format | Generated By | Target | Scope |
|------|--------|--------------|--------|-------|
| `~/.codex/AGENTS.md` | Markdown | cc2all | Codex | User |
| `~/.codex/skills/` | Symlinks | cc2all | Codex | User |
| `~/.codex/config.toml` | TOML | cc2all | Codex | User |
| `.codex/AGENTS.md` | Markdown | cc2all | Codex | Project |
| `.codex/skills/`, `.agents/skills/` | Symlinks | cc2all | Codex | Project |
| `~/.gemini/GEMINI.md` | Markdown | cc2all | Gemini | User |
| `~/.gemini/settings.json` | JSON | cc2all | Gemini | User |
| `GEMINI.md` | Markdown | cc2all | Gemini | Project |
| `.gemini/settings.json` | JSON | cc2all | Gemini | Project |
| `~/.config/opencode/AGENTS.md` | Markdown | cc2all | OpenCode | User |
| `~/.config/opencode/skills/` | Symlinks | cc2all | OpenCode | User |
| `~/.config/opencode/agents/` | Symlinks | cc2all | OpenCode | User |
| `~/.config/opencode/commands/` | Symlinks | cc2all | OpenCode | User |
| `.opencode/AGENTS.md` | Markdown | cc2all | OpenCode | Project |
| `.opencode/skills/`, `.opencode/agents/`, `.opencode/commands/` | Symlinks | cc2all | OpenCode | Project |

### State & Logs

| Path | Format | Purpose |
|------|--------|---------|
| `~/.cc2all/.last-sync` | Text timestamp | Cooldown tracking (shell integration) |
| `~/.cc2all/sync-state.json` | JSON | Last sync metadata (time, scope, duration) |
| `~/.cc2all/logs/daemon.log` | Text | Background daemon stdout |
| `~/.cc2all/logs/daemon.err` | Text | Background daemon stderr |

---

*Structure analysis: 2026-02-13*
