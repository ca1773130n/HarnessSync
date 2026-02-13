# Technology Stack

**Analysis Date:** 2026-02-13

## Languages & Runtimes

**Primary:**
- **Python 3** (3.x) - Main sync engine and cross-platform CLI tool
  - Used in `cc2all-sync.py` for file I/O, JSON manipulation, subprocess handling, and file watching
  - Entry point decorated with `#!/usr/bin/env python3`
  - Leverages standard library: `argparse`, `hashlib`, `json`, `os`, `re`, `shutil`, `subprocess`, `sys`, `time`, `datetime`, `pathlib`, `typing`

**Secondary:**
- **Bash/Sh** - Installation and shell integration
  - Installation script: `install.sh` (5.7KB, pure bash with `set -euo pipefail`)
  - Shell wrapper for command interception: `shell-integration.sh` (5.1KB)
  - Both compatible with bash and zsh

- **XML/PLIST** - macOS daemon configuration
  - `com.cc2all.sync.plist` - launchd property list for background daemon

## Runtime Environment

**Execution Model:**
- Direct Python 3 interpreter execution via shebang
- Shell command wrapping for transparent interception
- Process-based file watching:
  - `fswatch` (preferred on macOS)
  - `inotifywait` (fallback on Linux)
  - Polling-based fallback (5-second interval) when native tools unavailable

**Deployment Targets:**
- macOS (primary - includes launchd integration via `com.cc2all.sync.plist`)
- Linux (fswatch/inotify or polling)
- Bash/Zsh shells (tested on both)

**Package Manager:**
- No package dependencies (Python stdlib only)
- No lockfile (Python dependencies are all from standard library)

## Frameworks & Libraries

**Core Python Libraries Used:**
- `pathlib.Path` - Cross-platform file path handling (replaces `os.path`)
- `json` - Reading/writing JSON for config files and state persistence
- `hashlib` - SHA256 hashing for change detection (see `file_hash()` in `cc2all-sync.py` line 119)
- `subprocess` - Running external commands (`fswatch`, `inotifywait`, codex/gemini/opencode CLIs)
- `argparse` - CLI argument parsing and help generation

**CLI Tools (Not Dependencies, But Executable Prerequisites):**
- `codex` (OpenAI Codex CLI) - Target harness 1
- `gemini` (Google Gemini CLI) - Target harness 2
- `opencode` (OpenCode AI CLI) - Target harness 3
- `fswatch` or `inotifywait` - For file watching in watch mode

## Build & Development Tools

**Installation:**
- `install.sh` - Bash-based installer
  - Copies files to `~/.cc2all/`
  - Creates target directories
  - Modifies shell RC files (`.bashrc` or `.zshrc`)
  - Sets up launchd daemon (macOS)
  - Registers Claude Code hooks

**Execution:**
- Direct Python 3 CLI with `argparse`
- No build system required (no compilation, no transpilation)

**Testing:**
- Not detected - no test framework configured

**Linting/Formatting:**
- Not detected - no linter/formatter configuration found

## Infrastructure & Deployment

**Installation Method:**
1. Manual copy to `~/.cc2all/` (see `install.sh` line 25-31)
2. Shell RC integration via sourcing `shell-integration.sh` (line 128-129 in `install.sh`)
3. Target directory creation (line 57-62 in `install.sh`)

**macOS Background Daemon:**
- `com.cc2all.sync.plist` - launchd property list for continuous watch mode
- Runs `/usr/bin/python3 ~/.cc2all/cc2all-sync.py --watch --scope user`
- Automatic startup via `RunAtLoad: true`
- Keeps alive via `KeepAlive: true`
- Logs to `~/.cc2all/logs/daemon.log` and `~/.cc2all/logs/daemon.err`

**State & Configuration Storage:**
- User state: `~/.cc2all/sync-state.json` (see `STATE_FILE` in `cc2all-sync.py` line 68)
- Logs directory: `~/.cc2all/logs/` (see `LOG_DIR` in `cc2all-sync.py` line 69)

**No CI/CD:**
- Not configured
- Manual installation and updates

## Data Storage

**Configuration Reading:**
- Claude Code source: `~/.claude/settings.json`, `~/.claude/CLAUDE.md`, `~/.claude/skills/`, `~/.claude/agents/`, `~/.claude/commands/`, `~/.mcp.json`
  - Project-level overrides: `.claude/`, `CLAUDE.md`, `CLAUDE.local.md`, `.mcp.json` in project root
  - Code handles multiple formats and precedence (see `get_cc_*` functions lines 172-306)

**Output Targets:**
- **Codex**: `~/.codex/skills/` (symlinks), `~/.codex/AGENTS.md`, `~/.codex/config.toml` (MCP & env)
- **Gemini**: `~/.gemini/GEMINI.md`, `~/.gemini/settings.json` (MCP), `~/.gemini/.env`
- **OpenCode**: `~/.config/opencode/skills/`, `~/.config/opencode/agents/`, `~/.config/opencode/commands/`, `~/.config/opencode/opencode.json` (MCP & env)

**Persistence:**
- Sync state stored in `~/.cc2all/sync-state.json` (see `save_state()` at line 163-165)
- Tracks: `last_sync`, `scope`, `elapsed_ms`

**File Change Detection:**
- SHA256 hashing (first 16 chars) for file comparison (see `file_hash()` at line 119-123)
- Directory modification times for polling mode (see `_watch_polling()` at line 887-916)

---

*Stack analysis: 2026-02-13*
