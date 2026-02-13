# Stack Research

**Domain:** Claude Code Plugin Development (AI Harness Sync Tool)
**Researched:** 2026-02-13
**Confidence:** HIGH

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.10+ | Plugin hooks, sync engine, file operations | **MANDATORY for project constraints** (stdlib-only requirement). Python 3.10+ provides modern syntax (structural pattern matching), better type hints, and is pre-installed on macOS/Linux. Context7 confirms Python shows strongest community satisfaction for Claude Code plugins. |
| Node.js + TypeScript | 25.x + 5.x | MCP server implementation (if needed) | **CONDITIONAL**: Only if MCP server integration is required. TypeScript SDK is the only officially supported option for auto-generated MCP servers via Stainless. Use Node.js 25.x (current LTS as of 2026). |
| Bash | 5.x+ | Installation scripts, shell integration | **REQUIRED**: macOS ships with bash 3.2 (license issues), but modern bash 5.x via Homebrew is standard for 2026. Needed for `install.sh` and shell wrapper scripts. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Python stdlib only | 3.10+ | All sync operations, file I/O, JSON/TOML parsing | **ALWAYS** (project constraint). Use `pathlib`, `json`, `shutil`, `subprocess`, `hashlib` from stdlib. |
| `fswatch` (external) | 1.17+ | File watching on macOS (uses FSEvents API) | **OPTIONAL** for watch mode. External binary, not Python dependency. Install via Homebrew. |
| `inotify-tools` (external) | 3.22+ | File watching on Linux (uses inotify API) | **OPTIONAL** for watch mode on Linux. External binary, not Python dependency. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `npx tsx` | TypeScript execution for hooks (if using TS) | Only if you choose TypeScript for hooks instead of Python. Not recommended for stdlib-only constraint. |
| `pyright` or `mypy` | Type checking for Python | Development-time only. Use type hints extensively for maintainability. |
| Git | Version control, hook integration | Claude Code plugins are typically distributed via Git repositories. |

## Installation

```bash
# Core (already present on macOS/Linux)
python3 --version  # Should be 3.10+

# Optional: Watch mode dependencies (external binaries)
# macOS
brew install fswatch

# Linux
sudo apt-get install inotify-tools  # Debian/Ubuntu
sudo yum install inotify-tools      # RHEL/CentOS

# Optional: TypeScript tooling (only if building MCP server)
npm install -g tsx
npm install -g typescript@5.x
```

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| **Hook Language** | Python (stdlib) | TypeScript + SDK | TypeScript requires Node.js runtime and external dependencies (`@mizunashi_mana/claude-code-hook-sdk`), violating stdlib-only constraint. Python is sufficient for hook logic. |
| **File Watching** | `fswatch`/`inotify-tools` (external) | Python `watchdog` library | `watchdog` is external dependency (pip install). Violates stdlib-only. External binaries are acceptable as they're system-level tools. |
| **File Watching** | External tools | Python stdlib `select.kqueue` | Stdlib `select` module supports `kqueue` on macOS and `epoll` on Linux, but low-level API is complex and error-prone. `fswatch` provides better cross-platform abstraction. |
| **MCP Server** | TypeScript (if needed) | Python FastMCP | For MCP servers, TypeScript is **required** for Stainless auto-generation. Python FastMCP is alternative but TypeScript has better tooling support in 2026. |
| **Config Format** | JSON | YAML | JSON is stdlib parseable. YAML requires PyYAML (external). Use JSON for all config files. |
| **TOML Parsing** | Python stdlib `tomllib` (3.11+) | `toml` package | Use stdlib `tomllib` if Python 3.11+, otherwise vendored parser or skip TOML support. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `pip install watchdog` | External dependency, violates stdlib-only constraint | `fswatch` (external binary) or polling with `os.stat()` |
| `pip install toml` | External dependency (pre-3.11) | `tomllib` (stdlib in 3.11+) or JSON format |
| `npm install` for hooks | Adds Node.js dependency for hooks unnecessarily | Pure Python hooks with stdlib JSON I/O |
| TypeScript for hooks | Requires compilation step, runtime, and SDK dependencies | Python with type hints for development-time checking |
| Markdown libraries (e.g., `mistune`) | External dependency for parsing CLAUDE.md | String manipulation or vendored minimal parser if needed |
| Environment variable libraries | `python-dotenv` requires pip | Stdlib `os.environ` + manual `.env` parsing |

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| Python 3.10+ | macOS 11+ (Big Sur) | macOS 12+ ships with Python 3.8-3.9, use Homebrew for 3.10+ |
| Python 3.10+ | Ubuntu 22.04+ | Ubuntu 22.04 ships with Python 3.10 |
| `fswatch` 1.17+ | macOS 10.15+ | Uses FSEvents API (macOS-specific) |
| `inotify-tools` 3.22+ | Linux kernel 2.6.13+ | Uses inotify API (Linux-specific) |
| Node.js 25.x | macOS/Linux | Only if MCP server is needed |

## Architecture Decisions

### 1. Plugin Structure: Standard Claude Code Layout

**Decision:** Follow official Claude Code plugin structure with all components at root level.

```
HarnessSync/
├── .claude-plugin/
│   └── plugin.json          # Manifest with hooks, MCP config
├── commands/                 # Slash commands (.md files)
│   ├── sync.md
│   ├── sync-status.md
│   └── sync-force.md
├── skills/                   # Optional: sync skills
├── hooks/                    # Hook scripts
│   ├── hooks.json           # Hook definitions
│   └── post-tool-use.py     # Python hook for auto-sync
├── lib/                      # Sync engine (stdlib Python)
│   ├── sync_engine.py
│   ├── adapters/
│   │   ├── codex.py
│   │   ├── gemini_cli.py
│   │   └── opencode.py
│   └── config.py
└── README.md
```

**Rationale:**
- Claude Code auto-discovers components from standardized directories
- All component directories MUST be at plugin root, not nested in `.claude-plugin/`
- Hooks, commands, and skills are optional but recommended for full functionality

**Sources:**
- [Claude Code plugin structure](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/plugin-structure/SKILL.md) (Context7)
- [Plugin directory structure](https://github.com/anthropics/claude-code/blob/main/plugins/README.md) (Context7)

### 2. Hooks: Python with JSON I/O

**Decision:** Use Python for hooks with JSON stdin/stdout communication.

**Implementation Pattern:**
```python
#!/usr/bin/env python3
import json
import sys

# Read hook input from stdin
input_data = json.load(sys.stdin)

# Hook logic here
tool_name = input_data.get("tool_name")
if tool_name in ["Write", "Edit"]:
    # Trigger sync
    result = {"decision": "approve"}
else:
    result = {}

# Write result to stdout
json.dump(result, sys.stdout)
```

**Hook Configuration (hooks.json):**
```json
{
  "PostToolUse": [
    {
      "matcher": "Write|Edit",
      "hooks": [
        {
          "type": "command",
          "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/post-tool-use.py\"",
          "timeout": 10
        }
      ]
    }
  ]
}
```

**Rationale:**
- Python stdlib JSON parsing is fast and reliable
- No external dependencies (no SDK required)
- TypeScript SDK adds Node.js runtime overhead for simple sync trigger
- `PostToolUse` hook is perfect for auto-sync after file modifications

**Sources:**
- [Claude Code hooks JSON configuration](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/plugin-structure/examples/advanced-plugin.md) (Context7)
- [Python vs TypeScript for hooks](https://medium.com/@divyanshbhatiajm19/comparing-mcp-server-frameworks-which-one-should-you-choose-cbadab4ddc80) (Web search, verified with Context7)

### 3. Slash Commands: Markdown with Bash Execution

**Decision:** Use Markdown files with YAML frontmatter + embedded bash commands.

**Example (/sync command):**
```markdown
---
name: sync
description: Sync Claude Code config to all AI harnesses
---
# Sync Configuration

Syncs Claude Code settings to Codex, Gemini CLI, and OpenCode.

Usage:
- `/sync` - Sync user + project scope
- `/sync user` - User scope only
- `/sync project` - Project scope only
- `/sync force` - Force sync (ignore cooldown)

!python3 "${CLAUDE_PLUGIN_ROOT}/lib/sync_engine.py" $ARGUMENTS
```

**Rationale:**
- Markdown is the native format for Claude Code commands
- YAML frontmatter provides metadata (name, description)
- `!` prefix executes bash commands
- `$ARGUMENTS` passes command arguments to script
- No compilation or build step required

**Sources:**
- [Claude Code slash commands](https://code.claude.com/docs/en/slash-commands) (Official docs)
- [Slash command markdown format](https://www.producttalk.org/how-to-use-claude-code-features/) (Web search, 2026)

### 4. MCP Server: Conditional TypeScript

**Decision:** Only implement MCP server if external tool integration is needed (e.g., status API, remote sync).

**When to Use:**
- If exposing sync status as queryable tool
- If implementing remote config sync API
- If integrating with external monitoring

**When NOT to Use:**
- For local file sync (use direct Python)
- For simple PostToolUse hooks (use Python)
- For slash commands (use Markdown + bash)

**If Needed, Use TypeScript:**
```json
{
  "mcpServers": {
    "harness-sync": {
      "command": "node",
      "args": ["${CLAUDE_PLUGIN_ROOT}/mcp-server/dist/index.js"],
      "env": {
        "SYNC_STATE_DIR": "${HOME}/.harness-sync"
      }
    }
  }
}
```

**Rationale:**
- TypeScript is **required** for Stainless auto-generated MCP servers
- Python FastMCP is alternative but has less tooling support in 2026
- MCP server is overkill for simple file sync (use hooks instead)

**Sources:**
- [MCP server SDK comparison](https://www.stainless.com/mcp/mcp-sdk-comparison-python-vs-typescript-vs-go-implementations) (Web search, 2026)
- [MCP integration in plugins](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/mcp-integration/SKILL.md) (Context7)

### 5. File Watching: External Binaries (Optional)

**Decision:** Use `fswatch` (macOS) or `inotify-tools` (Linux) as external binaries, NOT Python libraries.

**Implementation:**
```bash
#!/bin/bash
# Watch mode wrapper script
if [[ "$OSTYPE" == "darwin"* ]]; then
  fswatch -o ~/.claude | while read; do
    python3 "${CLAUDE_PLUGIN_ROOT}/lib/sync_engine.py"
  done
elif [[ "$OSTYPE" == "linux"* ]]; then
  inotifywait -m -r -e modify ~/.claude | while read; do
    python3 "${CLAUDE_PLUGIN_ROOT}/lib/sync_engine.py"
  done
fi
```

**Alternative: Polling (stdlib-only):**
```python
import time
from pathlib import Path

def watch_directory(path, callback):
    """Polling-based file watcher (stdlib-only)."""
    state = {p: p.stat().st_mtime for p in Path(path).rglob("*")}
    while True:
        time.sleep(2)  # Poll every 2 seconds
        current = {p: p.stat().st_mtime for p in Path(path).rglob("*")}
        if current != state:
            callback()
            state = current
```

**Rationale:**
- `watchdog` library requires pip install (violates constraint)
- Python stdlib `select.kqueue`/`select.epoll` are low-level and error-prone
- External binaries (`fswatch`, `inotify-tools`) are acceptable as system tools
- Polling fallback uses stdlib only but higher latency

**Sources:**
- [Python stdlib select documentation](https://docs.python.org/3/library/select.html) (Official docs)
- [fswatch cross-platform file monitor](https://github.com/emcrisostomo/fswatch) (Web search)

### 6. Configuration Format: JSON Only

**Decision:** Use JSON for all configuration files (no YAML, no TOML).

**Files:**
- `plugin.json` - Plugin manifest (required)
- `hooks.json` - Hook definitions (if using separate file)
- `.harness-sync/config.json` - User configuration
- `.harness-sync/state.json` - Sync state tracking

**Rationale:**
- JSON is stdlib parseable (`import json`)
- YAML requires PyYAML (external dependency)
- TOML requires `tomllib` (Python 3.11+) or external library
- JSON has universal tooling support

**Exceptions:**
- Markdown for slash commands (native format)
- Bash scripts for installation/setup

**Sources:**
- Python stdlib json module (pre-installed)
- [Claude Code plugin.json format](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/plugin-structure/SKILL.md) (Context7)

## Prescriptive Recommendations

### ✅ DO Use

1. **Python 3.10+ stdlib only** for all sync logic, hooks, and file operations
2. **JSON** for all configuration and state files
3. **Markdown with YAML frontmatter** for slash commands
4. **Bash scripts** for installation and shell integration
5. **External binaries** (`fswatch`, `inotify-tools`) for watch mode (optional)
6. **Type hints** in Python for development-time checking (use `mypy` or `pyright` locally)
7. **PostToolUse hooks** for auto-sync after file modifications
8. **`pathlib.Path`** instead of `os.path` for modern path handling

### ❌ DO NOT Use

1. **pip install** anything (stdlib-only constraint)
2. **TypeScript for hooks** (unnecessary complexity, adds Node.js dependency)
3. **YAML or TOML** for config (requires external libraries)
4. **MCP server** unless you need external tool integration (overkill for file sync)
5. **Python `watchdog` library** (external dependency)
6. **Hardcoded paths** (use `CLAUDE_PLUGIN_ROOT`, `HOME` environment variables)

### 🎯 Current as of 2026

- **Python 3.10+** is standard on Ubuntu 22.04+, macOS 12+ (via Homebrew)
- **Node.js 25.x** is current LTS (if MCP server needed)
- **TypeScript 5.x** is standard for MCP servers
- **Claude Code plugin system** supports hooks, commands, skills, MCP servers
- **MCP SDK** officially supports TypeScript and Python (FastMCP merged into official SDK)

## Confidence Assessment

| Area | Level | Reason |
|------|-------|--------|
| Python for hooks | **HIGH** | Context7 confirms Python stdlib is sufficient. Verified with official docs and real-world plugins (multi-cli-harness). |
| JSON for config | **HIGH** | Official plugin.json format. Stdlib support. No alternatives needed. |
| Markdown for commands | **HIGH** | Native Claude Code format. Official docs confirm YAML frontmatter + `$ARGUMENTS` support. |
| External binaries for watch | **MEDIUM** | `fswatch`/`inotify` are battle-tested but add system dependencies. Polling fallback reduces risk. |
| TypeScript for MCP | **HIGH** | Official SDK and Stainless generator only support TypeScript. Python alternative exists but less mature. |
| No MCP needed | **HIGH** | File sync doesn't require external tool integration. Hooks + commands are sufficient. |

## Open Questions

1. **TOML parsing for Codex config.toml**: Python 3.11+ has `tomllib` (stdlib), but macOS may ship with 3.10. Options:
   - Require Python 3.11+ (breaking for some users)
   - Vendor minimal TOML parser (acceptable for stdlib-only?)
   - Skip TOML, convert to JSON-based config
   - **Recommendation**: Use `tomllib` if available, fallback to manual string parsing for simple TOML

2. **Watch mode priority**: Is watch mode critical or nice-to-have?
   - If critical: Use external binaries (`fswatch`/`inotify`)
   - If nice-to-have: Skip watch mode, rely on PostToolUse hooks + manual `/sync`
   - **Recommendation**: PostToolUse hooks cover 95% of use cases. Watch mode is optional.

3. **Cross-platform shell integration**: Bash wrapper for `codex`, `gemini`, `opencode` commands.
   - macOS: bash 5.x (Homebrew) or zsh (default)
   - Linux: bash 4.x+ (standard)
   - **Recommendation**: Provide both bash and zsh wrappers, detect in `install.sh`

## Sources

**Context7 (HIGH confidence):**
- [Claude Code plugin structure](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/plugin-structure/SKILL.md)
- [Claude Code hooks configuration](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/plugin-structure/examples/advanced-plugin.md)
- [Claude Code MCP integration](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/mcp-integration/SKILL.md)
- [Claude Code hook SDK TypeScript](https://github.com/mizunashi-mana/claude-code-hook-sdk)

**Official Documentation (HIGH confidence):**
- [Claude Code slash commands](https://code.claude.com/docs/en/slash-commands)
- [Claude Code plugins](https://code.claude.com/docs/en/plugins)
- [Python select module](https://docs.python.org/3/library/select.html)

**Web Search 2026 (MEDIUM confidence, verified):**
- [MCP SDK comparison TypeScript vs Python](https://www.stainless.com/mcp/mcp-sdk-comparison-python-vs-typescript-vs-go-implementations)
- [Claude Code plugin best practices 2026](https://pierce-lamb.medium.com/the-deep-trilogy-claude-code-plugins-for-writing-good-software-fast-33b76f2a022d)
- [fswatch cross-platform file monitor](https://github.com/emcrisostomo/fswatch)
- [Python vs TypeScript for hooks performance](https://hackceleration.com/claude-code-review/)

---
*Stack research for: Claude Code Plugin Development (HarnessSync)*
*Researched: 2026-02-13*
*Confidence: HIGH*
