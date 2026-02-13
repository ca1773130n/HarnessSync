# Code Conventions

**Analysis Date:** 2026-02-13

## Style & Formatting

### Python

**Code Style:**
- PEP 8 compliant with practical deviations
- Line length: implied 120+ characters (no enforced limit detected)
- No linting configuration files present (`.flake8`, `.pylintrc`, etc.)

**Formatting:**
- 4-space indentation throughout
- No automated formatting tools configured (no black, ruff, or similar)
- Files are hand-formatted with consistent style

**File Structure:**
- Module docstring at top (`#!/usr/bin/env python3` shebang, triple-quoted docstring)
- Imports grouped by standard library, then custom code
- Constants defined in all-caps, grouped in sections marked with comment separators
- Main execution guarded by `if __name__ == "__main__":`

Example from `cc2all-sync.py` (line 1-32):
```python
#!/usr/bin/env python3
"""
cc2all-sync: Claude Code → All Harnesses Sync Engine
[docstring content]
"""

import argparse
import hashlib
...
from typing import Any

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

VERSION = "1.0.0"
CC_HOME = Path.home() / ".claude"
```

### Bash

**Code Style:**
- POSIX-compatible shell scripting with bash-specific features
- Strict mode: `set -euo pipefail` for safety
- Long lines with continuation via implicit wrapping inside commands
- No external dependencies beyond standard Unix utilities

**Formatting:**
- 4-space indentation for nested blocks
- Function names use snake_case with `_` prefix for private functions
- Comments use `# ─────` ASCII dividers for section headers

Example from `install.sh` (line 6-14):
```bash
set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
BLUE="\033[34m"
YELLOW="\033[33m"
RED="\033[31m"
NC="\033[0m"
```

## Naming Conventions

### Python

**Constants:**
- All uppercase with underscores: `VERSION`, `CC_HOME`, `STATE_FILE`
- Group-related constants together
- Use `pathlib.Path` for file paths instead of strings

**Functions:**
- Lowercase with underscores: `get_cc_rules()`, `sync_to_codex()`, `file_hash()`
- Private functions prefixed with `_`: `_build_codex_mcp_toml()`, `_watch_fswatch()`
- Helper functions grouped together, not scattered

**Classes:**
- PascalCase: `Logger` (line 75)
- Constructor methods use `__init__`
- Single-responsibility classes (e.g., `Logger` only handles output formatting)

**Variables:**
- Lowercase with underscores for normal variables: `scope`, `project_dir`, `dry_run`
- Dictionary keys use snake_case: `"scope"`, `"synced_at"`
- Type hints used in function signatures: `def sync_to_codex(scope: str, project_dir: Path = None, dry_run: bool = False):`

**File Paths:**
- Use `pathlib.Path` exclusively, never string paths
- Always use `.exists()`, `.is_dir()`, `.is_file()` to check before operations
- Compose paths with `/` operator: `project_dir / ".claude" / "CLAUDE.md"`

### Bash

**Variables:**
- Uppercase for environment variables: `BOLD`, `GREEN`, `SCRIPT_DIR`, `CC2ALL_HOME`
- Lowercase for local/temporary variables: `last`, `now`, `diff`
- Quote variables in double quotes to prevent word splitting: `"$CC2ALL_SYNC"`

**Functions:**
- Lowercase with underscores: `check_cli()`, `_cc2all_should_sync()`
- Prefix private/internal functions with `_`: `_cc2all_auto_sync()`, `_cc2all_check_target()`

**File Paths:**
- Always quote paths: `"$HOME/.cc2all"`, `"$SCRIPT_DIR/cc2all-sync.py"`
- Use variable substitution for common paths: `CC2ALL_HOME`, `CC2ALL_SYNC`

## Code Patterns

### Error Handling

**Python:**
- Use specific exception types in try-except blocks
- Log errors with `log.error()` method, increment error counter
- Return empty defaults on failure (empty dict, empty string, etc.)

Example from `cc2all-sync.py` (line 126-133):
```python
def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.error(f"Failed to read {path}: {e}")
        return {}
```

**Bash:**
- Use `set -euo pipefail` to fail fast on errors
- Suppress stderr when checking tool availability: `command -v "$cmd" &>/dev/null`
- Wrap unsafe operations in conditional checks: `if [[ -f "$file" ]]; then`

Example from `install.sh` (line 40-48):
```bash
check_cli() {
    local name="$1" cmd="$2" install="$3"
    if command -v "$cmd" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $name"
    else
        echo -e "  ${YELLOW}·${NC} $name — not installed"
        echo -e "      Install: ${install}"
        ((MISSING++)) || true
    fi
}
```

### Logging Patterns

**Python:**
- Use global `log` instance (Logger class)
- Methods: `info()`, `warn()`, `error()`, `skip()`, `debug()`, `header()`
- Track statistics: `synced()`, `cleaned()`, `summary()`
- Color-coded output with ANSI escapes

Logger class (`cc2all-sync.py`, line 75-110):
```python
class Logger:
    COLORS = {
        "reset": "\033[0m", "bold": "\033[1m",
        "red": "\033[31m", "green": "\033[32m",
        ...
    }

    def info(self, msg): print(f"  {self._c('green', '✓')} {msg}")
    def error(self, msg): print(f"  {self._c('red', '✗')} {msg}"); self._counts["error"] += 1
```

**Bash:**
- Use ANSI color variables for consistent output
- Echo with `-e` flag for escape sequences
- Standard pattern: `echo -e "  ${GREEN}✓${NC} message"`

### File I/O Patterns

**Python:**
- Always use `Path` object methods: `.read_text()`, `.read_bytes()`, `.write_text()`
- Ensure directories exist before writing: `ensure_dir(path.parent)`
- Specify encoding explicitly: `encoding="utf-8"`

Example from `cc2all-sync.py` (line 136-143):
```python
def write_json(path: Path, data: dict):
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def write_text(path: Path, content: str):
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")
```

### Symlink Management

**Pattern:**
- Always check if symlink already points to correct target before creating
- Use `safe_symlink()` helper to replace existing symlinks if needed
- Don't fail if symlink already exists correctly

Example from `cc2all-sync.py` (line 146-156):
```python
def safe_symlink(src: Path, dst: Path):
    """Create symlink, replacing existing if needed."""
    if dst.is_symlink():
        if dst.resolve() == src.resolve():
            return False  # already correct
        dst.unlink()
    elif dst.exists():
        shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
    ensure_dir(dst.parent)
    dst.symlink_to(src)
    return True
```

### Configuration Management

**Pattern:**
- Use `read_json()` for JSON configs, returns empty dict on failure
- Use `write_json()` to persist state with 2-space indentation
- Separate concerns: state file (`sync-state.json`) vs configs (`.mcp.json`, `settings.json`)

Example from `cc2all-sync.py` (line 159-165):
```python
def load_state() -> dict:
    return read_json(STATE_FILE) if STATE_FILE.exists() else {}

def save_state(state: dict):
    ensure_dir(STATE_DIR)
    write_json(STATE_FILE, state)
```

### Dictionary Key Access

**Pattern:**
- Use `.get(key, default)` for optional values
- Check existence before iterating: `if isinstance(data, dict):`
- Handle both dict and list formats for plugin registry (dual-format compatibility)

Example from `cc2all-sync.py` (line 209-217):
```python
plugins_data = registry.get("plugins", {})

# Handle both dict and list formats
plugin_entries = []
if isinstance(plugins_data, dict):
    plugin_entries = plugins_data.values()
elif isinstance(plugins_data, list):
    plugin_entries = plugins_data
```

## Documentation

### Python

**Module Docstrings:**
- Triple-quoted docstring immediately after shebang
- Single paragraph summary followed by blank line, then detailed description
- List usage examples in docstring

Example from `cc2all-sync.py` (line 2-15):
```python
"""
cc2all-sync: Claude Code → All Harnesses Sync Engine

Syncs Claude Code configuration to:
  - OpenAI Codex CLI    (~/.codex/, .codex/)
  - Gemini CLI           (~/.gemini/, project GEMINI.md)
  - OpenCode             (~/.config/opencode/, .opencode/)

Claude Code is the single source of truth.
Supports both user-scope (global) and project-scope sync.

Usage:
  cc2all-sync.py [--scope user|project|all] [--watch] [--project-dir DIR] [--dry-run] [--verbose]
"""
```

**Function Docstrings:**
- Single-line docstring for simple functions
- Format: verb phrase describing what function does + parameters/return

Examples from `cc2all-sync.py`:
- `def file_hash(path: Path) -> str:` — "SHA256 of file contents for change detection."
- `def safe_symlink(src: Path, dst: Path):` — "Create symlink, replacing existing if needed."

**Inline Comments:**
- Section headers with ASCII dividers: `# ─────────────────────────────────────────────`
- Section names in comments: `# Constants`, `# Source: Claude Code Configuration Reader`
- Comments on complex logic, not obvious code

Section pattern from `cc2all-sync.py` (line 30-32):
```python
# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────
```

### Bash

**Function Docstrings:**
- Comments above function with description
- Format: plain English describing what function does

Example from `shell-integration.sh` (line 17-27):
```bash
_cc2all_should_sync() {
    # Check if enough time has passed since last sync
    if [[ ! -f "$CC2ALL_STAMP" ]]; then
        return 0  # never synced
    fi
```

**Section Headers:**
- ASCII comment separators: `# ─── Wrapper: codex ───`
- Clear labels for logical groupings

## Git & Workflow

### Commit Messages

**Format:**
- Not formally enforced in current codebase
- Based on README.md and initial commit: descriptive, present tense

Initial commit message: `Initial commit` (line c47274e)

### Branch Naming

**Convention:**
- Main branch: `main` (not `master`)
- No feature branch convention enforced

### PR Process

**Setup:**
- GitHub repository: `git@github.com:ca1773130n/HarnessSync.git`
- Remote tracking configured: `origin/main`
- No CI/CD pipeline detected (no `.github/workflows/`, `.gitlab-ci.yml`, `.travis.yml`)

---

*Conventions analysis: 2026-02-13*
