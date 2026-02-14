# Phase 4: Plugin Interface (Commands, Hooks, Skills) - Research

**Researched:** 2026-02-14
**Domain:** CLI plugin systems, slash commands, file-watching hooks, debouncing, dry-run modes
**Confidence:** MEDIUM

## Summary

Phase 4 implements user-facing plugin components for HarnessSync: `/sync` and `/sync-status` slash commands, PostToolUse hook for auto-sync, debouncing, file-based locking, and dry-run mode. The research confirms that Claude Code's plugin system supports all required features through its documented plugin.json manifest, command markdown files, and hooks.json configuration. Python's stdlib provides all necessary primitives (fcntl.flock for file locking, time-based debouncing, difflib for diff output) without external dependencies, maintaining the zero-dependency constraint.

**Primary recommendation:** Use Claude Code's native plugin system (command markdown files in commands/ directory, hooks.json for PostToolUse configuration) combined with Python stdlib primitives (fcntl.flock for locking, manual time-based debouncing, argparse for CLI parsing). Build a main orchestrator that connects SourceReader → AdapterRegistry → StateManager → output formatter.

## Paper-Backed Recommendations

Since this phase focuses on CLI plugin integration rather than research algorithms, recommendations are based on official documentation, stdlib capabilities, and established software engineering patterns rather than academic papers.

### Recommendation 1: Use Claude Code's Plugin System

**Recommendation:** Use Claude Code's native plugin manifest structure with commands/ directory for slash commands and hooks/hooks.json for PostToolUse hook configuration.

**Evidence:**
- [Claude Code Plugins Reference](https://code.claude.com/docs/en/plugins-reference) (2026) — Official documentation shows commands are markdown files in commands/ directory, automatically discovered and namespaced by plugin name
- [Claude Code Hooks Guide](https://code.claude.com/docs/en/hooks-guide) (2026) — PostToolUse hook fires after tool completion, receives JSON via stdin containing tool_name and tool_input fields, supports matchers like "Edit|Write" to filter specific tools
- Plugin.json manifest declares hooks/commands structure that Claude Code automatically registers on plugin installation

**Confidence:** HIGH — Official Claude Code documentation, current as of 2026-02-14

**Expected improvement:** Native integration eliminates custom slash command parsing, automatic discovery reduces boilerplate

**Caveats:** Commands receive $ARGUMENTS placeholder for user input but must parse it themselves; hooks communicate only via stdin/stdout/stderr/exit codes

### Recommendation 2: Use fcntl.flock() for File-Based Locking

**Recommendation:** Use Python stdlib fcntl.flock() with LOCK_EX | LOCK_NB for non-blocking exclusive locks to prevent concurrent syncs.

**Evidence:**
- [Python fcntl documentation](https://docs.python.org/3/library/fcntl.html) (Official, updated 2026-02-12) — fcntl.flock(fd, operation) performs lock operation on file descriptor, LOCK_EX places exclusive lock, LOCK_NB prevents blocking
- [File locking using fcntl.flock](https://gist.github.com/jirihnidek/430d45c54311661b47fb45a3a7846537) — Community-verified pattern shows context manager wrapping flock for automatic cleanup
- fcntl.flock is preferred over fcntl.fcntl because it avoids packing C data structures, as noted in official documentation

**Confidence:** HIGH — Python stdlib documentation, widely used pattern

**Expected improvement:** Prevents race conditions when multiple Claude Code instances or hook invocations attempt concurrent syncs

**Caveats:** fcntl module is Unix-only; Windows requires alternative approach (use os.open with exclusive flags or skip locking on Windows with warning)

### Recommendation 3: Implement Manual Time-Based Debouncing

**Recommendation:** Use time.time() to track last sync timestamp and skip sync if elapsed time < 3 seconds, stored in state.json.

**Evidence:**
- [Python time module](https://docs.python.org/3/library/time.html) (Official stdlib) — time.time() returns Unix timestamp as float, sufficient precision for debouncing
- [Simple Python debounce implementation](https://gist.github.com/kylebebak/ee67befc156831b3bbaa88fb197487b0) — Community pattern shows decorator using time.time() for debouncing function calls
- No stdlib file-watching capability exists; watchdog/watchfiles are third-party dependencies (violates zero-dependency constraint)

**Confidence:** HIGH — Python stdlib capability, simple time-based check

**Expected improvement:** Prevents redundant syncs when Claude Code makes multiple rapid edits (e.g., Edit then Write)

**Caveats:** Time-based debouncing doesn't batch events; each hook invocation checks timestamp independently rather than waiting for quiet period

### Recommendation 4: Use argparse for Scope Flag Parsing

**Recommendation:** Use argparse.ArgumentParser with add_argument('--scope', choices=['user', 'project', 'all']) for /sync command, add_argument('--dry-run', action='store_true') for preview mode.

**Evidence:**
- [Python argparse documentation](https://docs.python.org/3/library/argparse.html) (Official stdlib, updated 2026) — Supports subcommands, boolean flags, choice validation
- [argparse subcommands tutorial](https://realpython.com/command-line-interfaces-python-argparse/) (2026) — Shows pattern for creating CLI tools with multiple commands and flags
- Boolean flags with action='store_true' create args.dry_run with default False, set to True if provided

**Confidence:** HIGH — Python stdlib, standard CLI parsing approach

**Expected improvement:** Clean flag parsing, automatic --help generation, type validation

**Caveats:** argparse is for command-line scripts; slash commands receive $ARGUMENTS as string and must parse manually or use shlex.split() + argparse.parse_args()

### Recommendation 5: Use difflib.unified_diff() for Dry-Run Output

**Recommendation:** Use difflib.unified_diff(a, b, lineterm='') to generate diff output showing changes without writing files.

**Evidence:**
- [Python difflib documentation](https://docs.python.org/3/library/difflib.html) (Official stdlib) — unified_diff() returns generator yielding lines in unified diff format (Git-style diffs)
- [Creating Git-like diff viewer in Python](https://www.timsanteford.com/posts/creating-a-git-like-diff-viewer-in-python-using-difflib/) (2026) — Shows unified_diff as recommended format for modern workflows
- Unified diffs show changes inline rather than separate before/after blocks, compact and readable

**Confidence:** HIGH — Python stdlib, widely recognized diff format

**Expected improvement:** User-friendly preview of changes before committing to sync

**Caveats:** difflib works on line-by-line text; for binary files or complex structures (JSON/TOML), need custom comparison logic

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.8+ | All functionality | Zero-dependency constraint (REQ-CORE-02), fcntl for locking, time for debouncing, argparse for CLI, difflib for diffs, json for state |
| Claude Code plugin system | Current | Slash commands, hooks | Official Claude Code extension mechanism, automatic discovery and namespacing |

### Supporting

No external libraries required. All functionality achievable with Python stdlib.

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Evidence |
|------------|-----------|----------|----------|
| fcntl.flock | filelock (PyPI) | filelock provides cross-platform locking including Windows, but violates zero-dependency constraint | [filelock docs](https://py-filelock.readthedocs.io/) |
| Manual time debouncing | watchdog/watchfiles | Third-party file watchers provide event batching and debouncing, but add dependencies | [watchdog PyPI](https://pypi.org/project/watchdog/) |
| Manual argparse | click/typer | More ergonomic CLI frameworks, but violate zero-dependency | Standard practice for zero-dep Python CLIs |

**Installation:**
```bash
# No installation needed - Python 3.8+ stdlib only
# fcntl, time, argparse, difflib, json all built-in
```

## Architecture Patterns

### Recommended Project Structure

```
src/
├── commands/          # Slash command entry points
│   ├── sync.py       # /sync implementation
│   └── sync_status.py # /sync-status implementation
├── hooks/             # Hook scripts
│   └── post_tool_use.py # Auto-sync hook
├── orchestrator.py    # Main sync orchestrator
├── lock.py           # File-based locking utility
└── diff_formatter.py  # Dry-run diff output
```

### Pattern 1: Slash Command Entry Point

**What:** Markdown files in commands/ directory invoke Python scripts that receive $ARGUMENTS

**When to use:** For /sync and /sync-status commands

**Official reference:** [Claude Code Plugins Reference - Commands](https://code.claude.com/docs/en/plugins-reference)

**Example:**
```markdown
<!-- .claude/commands/sync.md -->
---
description: Sync Claude Code config to all targets (Codex, Gemini, OpenCode)
---

# Sync Configuration

Syncs your Claude Code configuration to all configured targets.

Usage: /sync [--scope user|project|all] [--dry-run]

!python ${CLAUDE_PLUGIN_ROOT}/src/commands/sync.py $ARGUMENTS
```

### Pattern 2: PostToolUse Hook with Matcher

**What:** Hook configuration in hooks/hooks.json that triggers on Edit|Write tools

**When to use:** For auto-sync after Claude Code writes to config files

**Official reference:** [Claude Code Hooks Guide - PostToolUse](https://code.claude.com/docs/en/hooks-guide)

**Example:**
```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "python ${CLAUDE_PLUGIN_ROOT}/src/hooks/post_tool_use.py"
          }
        ]
      }
    ]
  }
}
```

Hook script reads JSON from stdin:
```python
# src/hooks/post_tool_use.py
import json
import sys

def main():
    # Read hook input from stdin
    hook_data = json.load(sys.stdin)
    tool_name = hook_data.get("tool_name")
    file_path = hook_data.get("tool_input", {}).get("file_path", "")

    # Check if edited file is a config file
    config_patterns = ["CLAUDE.md", ".mcp.json", "/skills/", "/agents/", "/commands/", "settings.json"]
    if not any(pattern in file_path for pattern in config_patterns):
        sys.exit(0)  # Not a config file, allow and skip

    # Check debounce and lock, then trigger sync
    # ... (debounce and sync logic)

    sys.exit(0)  # Exit 0 = allow action to proceed

if __name__ == "__main__":
    main()
```

### Pattern 3: File-Based Locking with Context Manager

**What:** Context manager wrapper around fcntl.flock for automatic lock cleanup

**When to use:** Preventing concurrent sync operations

**Source reference:** [fcntl documentation](https://docs.python.org/3/library/fcntl.html), [Community flock pattern](https://gist.github.com/lonetwin/7b4ccc93241958ff6967)

**Example:**
```python
# src/lock.py
import fcntl
import os
from pathlib import Path
from contextlib import contextmanager

@contextmanager
def sync_lock(lock_path: Path, timeout: float = 0):
    """
    Acquire exclusive lock on lock file.

    Args:
        lock_path: Path to lock file (~/.harnesssync/sync.lock)
        timeout: Seconds to wait for lock (0 = non-blocking)

    Raises:
        BlockingIOError: If lock cannot be acquired (timeout=0)

    Yields:
        File descriptor of lock file
    """
    # Ensure lock directory exists
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Open lock file
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)

    try:
        # Acquire exclusive non-blocking lock
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        # Release lock and close file
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
```

Usage:
```python
from pathlib import Path
from src.lock import sync_lock

lock_path = Path.home() / ".harnesssync" / "sync.lock"

try:
    with sync_lock(lock_path):
        # Perform sync operation
        orchestrator.sync_all()
except BlockingIOError:
    print("Sync already in progress, skipping")
    sys.exit(0)
```

### Pattern 4: Time-Based Debouncing

**What:** Check elapsed time since last sync before triggering new sync

**When to use:** In PostToolUse hook to prevent rapid successive syncs

**Source reference:** [Python time module](https://docs.python.org/3/library/time.html)

**Example:**
```python
# src/hooks/post_tool_use.py
import time
from pathlib import Path
from src.state_manager import StateManager

DEBOUNCE_SECONDS = 3

def should_debounce(state_manager: StateManager) -> bool:
    """
    Check if sync should be skipped due to debounce.

    Returns:
        True if last sync was < 3 seconds ago
    """
    last_sync = state_manager.last_sync
    if not last_sync:
        return False  # Never synced, proceed

    # Parse ISO timestamp to Unix time
    from datetime import datetime
    last_sync_time = datetime.fromisoformat(last_sync).timestamp()
    current_time = time.time()

    elapsed = current_time - last_sync_time
    return elapsed < DEBOUNCE_SECONDS

# In hook main():
state_manager = StateManager()
if should_debounce(state_manager):
    # Exit silently - debounce active
    sys.exit(0)

# Proceed with sync
```

### Pattern 5: Orchestrator Pattern

**What:** Single entry point that coordinates SourceReader → AdapterRegistry → StateManager flow

**When to use:** For /sync command and hook auto-sync to share sync logic

**Example:**
```python
# src/orchestrator.py
from pathlib import Path
from src.source_reader import SourceReader
from src.adapters.registry import AdapterRegistry
from src.state_manager import StateManager
from src.utils.logger import Logger

class SyncOrchestrator:
    """
    Coordinates sync operations across all adapters.
    """

    def __init__(self, project_dir: Path, scope: str = "all", dry_run: bool = False):
        self.project_dir = project_dir
        self.scope = scope
        self.dry_run = dry_run
        self.logger = Logger()

    def sync_all(self) -> dict:
        """
        Sync all configuration to all registered adapters.

        Returns:
            Dict with sync results per target
        """
        # 1. Read source configuration
        reader = SourceReader(scope=self.scope, project_dir=self.project_dir)
        source_data = reader.discover_all()

        # 2. Get all adapters
        registry = AdapterRegistry()
        adapters = registry.get_all_adapters(self.project_dir)

        # 3. Sync to each adapter
        results = {}
        for adapter in adapters:
            if self.dry_run:
                # Preview changes without writing
                results[adapter.target_name] = self._preview_sync(adapter, source_data)
            else:
                # Perform actual sync
                results[adapter.target_name] = adapter.sync_all(source_data)

        # 4. Update state (if not dry-run)
        if not self.dry_run:
            self._update_state(results, reader)

        return results

    def _preview_sync(self, adapter, source_data) -> dict:
        """Generate diff preview without writing files."""
        # Compare current vs. proposed state, generate diffs
        # ... (implementation in diff_formatter.py)
        pass

    def _update_state(self, results: dict, reader: SourceReader) -> None:
        """Update state manager with sync results."""
        state_manager = StateManager()

        # Get source file paths for hashing
        source_paths = reader.get_source_paths()

        for target, result in results.items():
            # Compute hashes for source files
            file_hashes = {}  # ... hash each file

            # Record sync
            state_manager.record_sync(
                target=target,
                scope=self.scope,
                file_hashes=file_hashes,
                sync_methods={},  # Populated by adapter
                synced=result.get("synced", 0),
                skipped=result.get("skipped", 0),
                failed=result.get("failed", 0)
            )
```

### Anti-Patterns to Avoid

- **Polling for file changes:** Don't implement continuous file watching - use hook-based reactive sync instead (PostToolUse hook triggers only when Claude Code edits files)
- **Global mutable state:** Don't store sync state in module-level globals - pass StateManager instance through function calls
- **Ignoring lock acquisition failures:** Don't proceed with sync if lock can't be acquired - exit silently to avoid race conditions
- **Blocking on lock:** Don't use LOCK_EX without LOCK_NB - non-blocking is essential for hook responsiveness

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File locking | Custom lock files with PID tracking | fcntl.flock (LOCK_EX \| LOCK_NB) | Handles process crashes, deadlocks, race conditions automatically |
| File watching | Poll loop checking mtime | PostToolUse hook | Claude Code hook fires only on actual edits, no CPU overhead |
| Diff output | Custom text comparison | difflib.unified_diff() | Standard format, handles edge cases (empty lines, no newline at EOF) |
| CLI parsing | Manual sys.argv splitting | argparse | Handles --help, type validation, error messages, subcommands |
| Timestamp parsing | Manual string manipulation | datetime.fromisoformat() | Handles ISO 8601 format correctly, timezone-aware |

**Key insight:** Zero-dependency constraint means relying heavily on Python stdlib - fortunately, stdlib provides robust implementations of all needed primitives.

## Common Pitfalls

### Pitfall 1: fcntl Unavailable on Windows

**What goes wrong:** fcntl module is Unix-only, import fails on Windows with ImportError

**Why it happens:** fcntl wraps Unix system calls (flock, fcntl, ioctl) not available on Windows

**How to avoid:** Check platform and skip locking on Windows with warning, or use os.open with O_EXCL flag as fallback

**Warning signs:** ImportError on fcntl, Windows users reporting sync issues

**Code example:**
```python
import sys
import os

# Cross-platform lock check
if sys.platform == "win32":
    # Windows: use os.open with O_EXCL or skip locking
    @contextmanager
    def sync_lock(lock_path: Path, timeout: float = 0):
        # Windows fallback: no locking, just warn
        import warnings
        warnings.warn("File locking not available on Windows - concurrent syncs may conflict")
        yield None
else:
    # Unix: use fcntl.flock
    import fcntl
    @contextmanager
    def sync_lock(lock_path: Path, timeout: float = 0):
        # ... fcntl.flock implementation
        pass
```

### Pitfall 2: Hook Receives JSON via stdin, Not Arguments

**What goes wrong:** Hook script tries to parse sys.argv for file_path but receives empty arguments

**Why it happens:** Claude Code hooks receive event data as JSON on stdin, not command-line arguments

**How to avoid:** Always read from stdin with json.load(sys.stdin) in hook scripts

**Warning signs:** Hook exits immediately without processing, "file_path not found" errors

**Code example:**
```python
# WRONG - hooks don't use sys.argv
import sys
file_path = sys.argv[1]  # Will fail - no arguments

# CORRECT - hooks use stdin
import json
import sys
hook_data = json.load(sys.stdin)
file_path = hook_data.get("tool_input", {}).get("file_path", "")
```

### Pitfall 3: Exit Code 2 Blocks Actions, Exit 0 Allows

**What goes wrong:** Hook exits with 2 intending to "allow with warning" but actually blocks the tool call

**Why it happens:** Exit code semantics: 0 = allow, 2 = block, any other = allow but log error

**How to avoid:** Use exit 0 for normal completion, exit 2 only to prevent tool execution

**Warning signs:** Claude Code shows "action blocked" when hook should allow, edits not persisting

**Reference:** [Claude Code Hooks Guide - Exit Codes](https://code.claude.com/docs/en/hooks-guide)

### Pitfall 4: Slash Commands Need Manual Argument Parsing

**What goes wrong:** Command script expects parsed arguments object but receives raw string

**Why it happens:** Claude Code passes $ARGUMENTS as literal string, not parsed argv

**How to avoid:** Use shlex.split() to tokenize arguments, then argparse.parse_args()

**Warning signs:** Flags not recognized, arguments merged into single string

**Code example:**
```python
# src/commands/sync.py
import sys
import shlex
import argparse

# Get raw arguments string from $ARGUMENTS
args_string = sys.argv[1] if len(sys.argv) > 1 else ""

# Split into tokens (handles quotes, escapes)
tokens = shlex.split(args_string)

# Parse with argparse
parser = argparse.ArgumentParser()
parser.add_argument("--scope", choices=["user", "project", "all"], default="all")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args(tokens)

# Now use args.scope, args.dry_run
```

### Pitfall 5: State File Corruption During Concurrent Access

**What goes wrong:** Multiple hook invocations corrupt state.json by writing simultaneously

**Why it happens:** PostToolUse hook fires for each tool use, no automatic serialization

**How to avoid:** Use file-based locking around StateManager._save() operations

**Warning signs:** state.json becomes invalid JSON, sync state lost

**Prevention:**
```python
# StateManager._save() should acquire lock
with sync_lock(self.state_dir / "state.lock"):
    # Write state.json atomically
    # ... (existing atomic write code)
```

## Verification Strategy

### Recommended Verification Tiers for This Phase

| Item | Recommended Tier | Rationale |
|------|-----------------|-----------|
| /sync command syncs all targets | Level 1 (Sanity) | Direct invocation, immediate output verification |
| /sync-status shows correct status | Level 1 (Sanity) | Read state.json, compare displayed values |
| PostToolUse hook triggers on config edit | Level 2 (Proxy) | Requires editing config file in Claude Code session |
| Debounce skips sync within 3 seconds | Level 2 (Proxy) | Needs rapid successive edits to test timing |
| File lock prevents concurrent syncs | Level 2 (Proxy) | Spawn concurrent processes, verify only one proceeds |
| Dry-run shows diff without writing | Level 1 (Sanity) | Compare file mtime before/after, verify no change |

**Level 1 checks to always include:**
- /sync --dry-run produces diff output and writes no files
- /sync-status displays last_sync timestamp and per-target status from state.json
- State.json remains valid JSON after sync operations

**Level 2 proxy metrics:**
- Hook fires when editing CLAUDE.md but not when editing random files
- Second sync within 3 seconds skips due to debounce (check logs for "skipped: debounce")
- Concurrent /sync invocations result in one success + one "sync in progress" message

**Level 3 deferred items:**
- Integration with actual Claude Code session workflow (requires installed plugin)
- Multi-user concurrent sync scenarios (needs multiple machines)
- Cross-platform locking behavior (Unix vs Windows testing)

## Production Considerations

No KNOWHOW.md production considerations documented yet. This section will be populated as implementation reveals production issues.

### Anticipated Failure Modes

- **Hook timeout:** PostToolUse hook has 10-minute default timeout; slow syncs (network delays for remote skills) could trigger timeout. Prevention: Set timeout field in hooks.json, log progress.
- **Lock file orphaned:** If sync process crashes, lock file persists but no owner. Detection: Check lock file mtime, clear if >10 minutes old.
- **Rapid edits overwhelming debounce:** User makes 10 edits in 5 seconds, each triggers hook. Prevention: Debounce checks elapsed time, only first and last sync proceed.

### Scaling Concerns

- **At current scale (1 user, 1-10 targets):** Time-based debouncing sufficient, lock contention unlikely
- **At production scale (teams, 100+ targets):** May need event batching, queue-based sync, distributed locking

### Common Implementation Traps

- **Assuming hooks run in Claude Code's process:** Hooks are separate subprocess, can't access Claude Code internals. Correct approach: Communicate via stdin/stdout only.
- **Hard-coding paths without ${CLAUDE_PLUGIN_ROOT}:** Breaks when plugin installed to cache. Correct approach: Use ${CLAUDE_PLUGIN_ROOT} in all plugin.json paths.
- **Forgetting to make hook scripts executable:** chmod +x required for Unix. Correct approach: Document in README, check in install.sh.

## Code Examples

Verified patterns from official sources:

### PostToolUse Hook Reading stdin

```python
# Source: https://code.claude.com/docs/en/hooks-guide
import json
import sys

# Read hook event data from stdin
hook_data = json.load(sys.stdin)

# Extract relevant fields
tool_name = hook_data.get("tool_name")
file_path = hook_data.get("tool_input", {}).get("file_path", "")
session_id = hook_data.get("session_id")

# Process and exit with status code
if should_sync(file_path):
    perform_sync()
    sys.exit(0)  # Allow action
else:
    sys.exit(0)  # Allow but skip sync
```

### Slash Command with Argument Parsing

```python
# Source: Combining Claude Code plugin docs + argparse stdlib
import sys
import shlex
import argparse

def main():
    # Parse $ARGUMENTS string
    args_string = " ".join(sys.argv[1:])
    tokens = shlex.split(args_string)

    parser = argparse.ArgumentParser(description="Sync Claude Code config")
    parser.add_argument("--scope", choices=["user", "project", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(tokens)

    # Execute sync
    from src.orchestrator import SyncOrchestrator
    orchestrator = SyncOrchestrator(
        project_dir=Path.cwd(),
        scope=args.scope,
        dry_run=args.dry_run
    )
    results = orchestrator.sync_all()

    # Print summary
    print(f"Synced to {len(results)} targets")

if __name__ == "__main__":
    main()
```

### Non-Blocking File Lock

```python
# Source: https://docs.python.org/3/library/fcntl.html + community patterns
import fcntl
import os
from pathlib import Path
from contextlib import contextmanager

@contextmanager
def sync_lock(lock_path: Path):
    """Acquire exclusive non-blocking lock."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    except BlockingIOError:
        os.close(fd)
        raise  # Lock already held
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

# Usage
try:
    with sync_lock(Path.home() / ".harnesssync" / "sync.lock"):
        # Perform sync
        pass
except BlockingIOError:
    print("Sync already in progress")
```

### Unified Diff Generation

```python
# Source: https://docs.python.org/3/library/difflib.html
import difflib

def generate_diff(old_content: str, new_content: str, filename: str) -> str:
    """Generate unified diff showing changes."""
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm=""
    )

    return "".join(diff)

# Usage in dry-run
old_agents_md = read_file("~/.codex/AGENTS.md")
new_agents_md = generate_agents_md(rules)
diff = generate_diff(old_agents_md, new_agents_md, ".codex/AGENTS.md")
print(diff)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact | Source |
|--------------|------------------|--------------|--------|--------|
| Polling file changes | Event-based hooks | Claude Code 2024 | Eliminates CPU overhead, instant reactivity | [Hooks Guide](https://code.claude.com/docs/en/hooks-guide) |
| Shell script commands | Python stdlib commands | HarnessSync design | Zero dependencies, better error handling | Plugin design constraint |
| Blocking locks | Non-blocking locks with LOCK_NB | Modern patterns | Prevents hook hangs, fails fast | fcntl documentation |

**Deprecated/outdated:**
- File watching libraries (watchdog, watchfiles): Eliminated by PostToolUse hook — hook fires only on actual tool use, no continuous monitoring needed

## Open Questions

1. **Windows file locking alternative**
   - What we know: fcntl is Unix-only, Windows needs different approach
   - What's unclear: Best Windows fallback (os.open O_EXCL, msvcrt.locking, or skip locking?)
   - Recommendation: Start with skip-locking-on-Windows with warning, defer full Windows support to Phase 7 (Packaging)

2. **Hook timeout tuning**
   - What we know: Default 10-minute timeout for hooks
   - What's unclear: Typical sync duration, whether 10 minutes sufficient
   - Recommendation: Start with default, add timeout field in hooks.json if needed during testing

3. **Debounce window tuning**
   - What we know: 3 seconds specified in requirements
   - What's unclear: Whether 3 seconds optimal for typical edit patterns
   - Recommendation: Implement 3 seconds as configurable constant, allow adjustment if users report issues

4. **Dry-run diff format for non-text files**
   - What we know: difflib.unified_diff works for text files
   - What's unclear: How to preview changes for binary files, complex JSON/TOML
   - Recommendation: For structured files, show semantic diff (added/removed keys) rather than line diff

## Sources

### Primary (HIGH confidence)

- [Claude Code Hooks Guide](https://code.claude.com/docs/en/hooks-guide) (2026) — PostToolUse hook behavior, stdin JSON format, exit codes
- [Claude Code Plugins Reference](https://code.claude.com/docs/en/plugins-reference) (2026) — Plugin structure, command format, manifest schema
- [Python fcntl documentation](https://docs.python.org/3/library/fcntl.html) (Official, updated 2026-02-12) — File locking with flock
- [Python argparse documentation](https://docs.python.org/3/library/argparse.html) (Official stdlib) — CLI argument parsing
- [Python difflib documentation](https://docs.python.org/3/library/difflib.html) (Official stdlib) — Unified diff generation
- [Python time documentation](https://docs.python.org/3/library/time.html) (Official stdlib) — Timestamp tracking

### Secondary (MEDIUM confidence)

- [File locking using fcntl.flock](https://gist.github.com/jirihnidek/430d45c54311661b47fb45a3a7846537) — Community-verified flock pattern
- [argparse tutorial](https://realpython.com/command-line-interfaces-python-argparse/) (2026) — Subcommands and flags best practices
- [Creating Git-like diff viewer](https://www.timsanteford.com/posts/creating-a-git-like-diff-viewer-in-python-using-difflib/) (2026) — Unified diff recommended format
- [Python file timestamp guide](https://sqlpey.com/python/python-file-timestamp/) (2026) — Cross-platform timestamp handling
- [awesome-claude-code](https://github.com/hesreallyhim/awesome-claude-code) (Community) — Plugin examples and patterns

### Tertiary (LOW confidence)

- [Simple Python debounce](https://gist.github.com/kylebebak/ee67befc156831b3bbaa88fb197487b0) — Unverified time-based debouncing pattern

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Python stdlib only, zero external dependencies
- Architecture: MEDIUM-HIGH - Claude Code plugin system documented, stdlib patterns established
- Hook integration: HIGH - Official documentation with examples
- Cross-platform locking: MEDIUM - fcntl Unix-only, Windows fallback needs testing
- Debouncing: MEDIUM - Simple time-based check, no stdlib event batching
- Dry-run diff: HIGH - difflib stdlib capability well-documented

**Research date:** 2026-02-14
**Valid until:** 2026-03-14 (30 days for stable Python stdlib, Claude Code plugin system)

**Key uncertainties requiring validation:**
1. Windows file locking fallback approach
2. Hook timeout adequacy for slow syncs
3. Debounce window tuning based on user edit patterns
4. Dry-run diff format for structured files (JSON/TOML)
