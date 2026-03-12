from __future__ import annotations

"""Git hook installer for auto-sync (items 14 and 15).

Installs a post-commit hook that triggers HarnessSync whenever CLAUDE.md,
.claude/, or .mcp.json changes in a commit, and optionally a pre-commit hook
that syncs and stages the updated target files (AGENTS.md, GEMINI.md, etc.)
in the same commit.

Pre-commit hook (item 15):
When --pre-commit is used, the pre-commit hook:
1. Detects staged changes to CLAUDE.md / .claude/ / .mcp.json
2. Runs HarnessSync synchronously (blocking, not in background)
3. Stages the updated target files (AGENTS.md, GEMINI.md, etc.)
   so they are included in the same commit automatically.
"""

import stat
from pathlib import Path


# Files/patterns that trigger auto-sync when changed in a commit
TRIGGER_PATTERNS = [
    "CLAUDE.md",
    ".claude/",
    ".mcp.json",
    ".harness-sync/",
]

# Hook script template
HOOK_SCRIPT_TEMPLATE = """\
#!/bin/sh
# HarnessSync post-commit hook
# Auto-syncs config when Claude Code files change
# Installed by: harness-sync git-hook install
# Remove with: harness-sync git-hook uninstall

HARNESSSYNC_MARKER="# harnesssync-hook-v1"
$HARNESSSYNC_MARKER

# Check if any trigger files changed in this commit
changed=$(git diff-tree --no-commit-id -r --name-only HEAD 2>/dev/null)

triggers=0
for pattern in CLAUDE.md .claude/ .mcp.json .harness-sync/; do
    if echo "$changed" | grep -q "^$pattern"; then
        triggers=1
        break
    fi
done

if [ "$triggers" -eq 0 ]; then
    exit 0
fi

# Find HarnessSync plugin root
if [ -n "$CLAUDE_PLUGIN_ROOT" ]; then
    HS_ROOT="$CLAUDE_PLUGIN_ROOT"
elif [ -f "$HOME/.claude/plugins/harness-sync/src/commands/sync.py" ]; then
    HS_ROOT="$HOME/.claude/plugins/harness-sync"
else
    # Not installed — skip silently
    exit 0
fi

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
    exit 0
fi

# Run sync in background (don't block git commit)
"$PY" "$HS_ROOT/src/commands/sync.py" --scope all >/dev/null 2>&1 &

exit 0
"""

HARNESSSYNC_MARKER = "# harnesssync-hook-v1"

# Pre-commit hook: syncs synchronously and stages target files in the same commit
PRE_COMMIT_HOOK_TEMPLATE = """\
#!/bin/sh
# HarnessSync pre-commit hook
# Syncs harness configs and stages updated target files automatically
# Installed by: /sync-git-hook install --pre-commit
# Remove with: /sync-git-hook uninstall --pre-commit

HARNESSSYNC_PRE_MARKER="# harnesssync-pre-commit-v1"
$HARNESSSYNC_PRE_MARKER

# Check if any trigger files are staged
staged=$(git diff --cached --name-only 2>/dev/null)

triggers=0
for pattern in CLAUDE.md .claude/ .mcp.json .harness-sync/; do
    if echo "$staged" | grep -q "^$pattern"; then
        triggers=1
        break
    fi
done

if [ "$triggers" -eq 0 ]; then
    exit 0
fi

# Find HarnessSync plugin root
if [ -n "$CLAUDE_PLUGIN_ROOT" ]; then
    HS_ROOT="$CLAUDE_PLUGIN_ROOT"
elif [ -f "$HOME/.claude/plugins/harness-sync/src/commands/sync.py" ]; then
    HS_ROOT="$HOME/.claude/plugins/harness-sync"
else
    # Not installed — skip silently
    exit 0
fi

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
    exit 0
fi

# Run sync synchronously (blocking — ensures files are ready before commit)
echo "HarnessSync: syncing harness configs..."
if ! "$PY" "$HS_ROOT/src/commands/sync.py" --scope all 2>&1; then
    echo "HarnessSync: sync failed; continuing commit without auto-stage." >&2
    exit 0
fi

# Stage known target config files if they were updated by sync
TARGET_FILES="AGENTS.md GEMINI.md opencode.json codex.toml .cursor/mcp.json .windsurf/rules .aider.conf.yml CONVENTIONS.md"
staged_count=0
for f in $TARGET_FILES; do
    if [ -f "$f" ]; then
        git add "$f" 2>/dev/null && staged_count=$((staged_count + 1))
    fi
done

if [ "$staged_count" -gt 0 ]; then
    echo "HarnessSync: staged $staged_count updated harness config file(s)."
fi

exit 0
"""

PRE_COMMIT_MARKER = "# harnesssync-pre-commit-v1"


def find_git_dir(start: Path) -> Path | None:
    """Walk up from start to find .git directory.

    Args:
        start: Starting directory

    Returns:
        Path to .git directory, or None if not in a git repo
    """
    current = start.resolve()
    for _ in range(20):  # Max depth
        git_dir = current / ".git"
        if git_dir.is_dir():
            return git_dir
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def install_hook(project_dir: Path) -> tuple[bool, str]:
    """Install post-commit hook in the git repo containing project_dir.

    Args:
        project_dir: Project directory to start searching for git repo

    Returns:
        (success, message) tuple
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False, "Not inside a git repository"

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    hook_path = hooks_dir / "post-commit"

    # Check if hook already exists
    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if HARNESSSYNC_MARKER in existing:
            return True, f"Hook already installed at {hook_path}"
        # Append to existing hook
        with open(hook_path, "a", encoding="utf-8") as f:
            f.write("\n" + HOOK_SCRIPT_TEMPLATE)
        _make_executable(hook_path)
        return True, f"HarnessSync hook appended to existing post-commit hook at {hook_path}"

    # Write fresh hook
    hook_path.write_text(HOOK_SCRIPT_TEMPLATE, encoding="utf-8")
    _make_executable(hook_path)
    return True, f"Post-commit hook installed at {hook_path}"


def uninstall_hook(project_dir: Path) -> tuple[bool, str]:
    """Remove HarnessSync section from the post-commit hook.

    Args:
        project_dir: Project directory to search for git repo

    Returns:
        (success, message) tuple
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False, "Not inside a git repository"

    hook_path = git_dir / "hooks" / "post-commit"
    if not hook_path.exists():
        return True, "No post-commit hook found (nothing to remove)"

    content = hook_path.read_text(encoding="utf-8")
    if HARNESSSYNC_MARKER not in content:
        return True, "HarnessSync hook not found in post-commit hook"

    # If the entire script is ours, delete the hook
    lines = content.splitlines(keepends=True)
    non_hs_lines = [
        line for line in lines
        if not _is_harnesssync_line(line)
    ]
    new_content = "".join(non_hs_lines).strip()

    if not new_content or new_content == "#!/bin/sh":
        hook_path.unlink()
        return True, f"Post-commit hook removed from {hook_path}"
    else:
        hook_path.write_text(new_content + "\n", encoding="utf-8")
        return True, f"HarnessSync section removed from {hook_path}"


def is_hook_installed(project_dir: Path) -> bool:
    """Check if HarnessSync post-commit hook is installed.

    Args:
        project_dir: Project directory to search for git repo

    Returns:
        True if hook is installed
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False
    hook_path = git_dir / "hooks" / "post-commit"
    if not hook_path.exists():
        return False
    return HARNESSSYNC_MARKER in hook_path.read_text(encoding="utf-8")


def install_pre_commit_hook(project_dir: Path) -> tuple[bool, str]:
    """Install pre-commit hook that syncs and auto-stages target files.

    The pre-commit hook runs synchronously before a commit completes,
    syncs harness configs, and stages the updated target files so they
    are included in the same commit.

    Args:
        project_dir: Project directory to start searching for git repo

    Returns:
        (success, message) tuple
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False, "Not inside a git repository"

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    hook_path = hooks_dir / "pre-commit"

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if PRE_COMMIT_MARKER in existing:
            return True, f"Pre-commit hook already installed at {hook_path}"
        with open(hook_path, "a", encoding="utf-8") as f:
            f.write("\n" + PRE_COMMIT_HOOK_TEMPLATE)
        _make_executable(hook_path)
        return True, f"HarnessSync pre-commit hook appended to existing hook at {hook_path}"

    hook_path.write_text(PRE_COMMIT_HOOK_TEMPLATE, encoding="utf-8")
    _make_executable(hook_path)
    return True, f"Pre-commit hook installed at {hook_path}"


def uninstall_pre_commit_hook(project_dir: Path) -> tuple[bool, str]:
    """Remove HarnessSync section from the pre-commit hook.

    Args:
        project_dir: Project directory to search for git repo

    Returns:
        (success, message) tuple
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False, "Not inside a git repository"

    hook_path = git_dir / "hooks" / "pre-commit"
    if not hook_path.exists():
        return True, "No pre-commit hook found (nothing to remove)"

    content = hook_path.read_text(encoding="utf-8")
    if PRE_COMMIT_MARKER not in content:
        return True, "HarnessSync hook not found in pre-commit hook"

    lines = content.splitlines(keepends=True)
    non_hs_lines = [
        line for line in lines
        if PRE_COMMIT_MARKER not in line and not line.strip().startswith("# HarnessSync pre-commit")
    ]
    new_content = "".join(non_hs_lines).strip()

    if not new_content or new_content == "#!/bin/sh":
        hook_path.unlink()
        return True, f"Pre-commit hook removed from {hook_path}"
    else:
        hook_path.write_text(new_content + "\n", encoding="utf-8")
        return True, f"HarnessSync section removed from pre-commit hook at {hook_path}"


def is_pre_commit_hook_installed(project_dir: Path) -> bool:
    """Check if HarnessSync pre-commit hook is installed."""
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False
    hook_path = git_dir / "hooks" / "pre-commit"
    if not hook_path.exists():
        return False
    return PRE_COMMIT_MARKER in hook_path.read_text(encoding="utf-8")


def _make_executable(path: Path) -> None:
    """Make a file executable (chmod +x)."""
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _is_harnesssync_line(line: str) -> bool:
    """Return True if a line is part of the HarnessSync hook block."""
    return HARNESSSYNC_MARKER in line or line.strip().startswith("# HarnessSync")


# ──────────────────────────────────────────────────────────────────────────────
# Pre-commit Sync Gate (item 9)
# Blocks commits when Claude Code config has changed but harness targets are
# out of date.  Unlike the pre-commit auto-stage hook, this hook is a hard
# gate: it exits 1 (blocking the commit) and tells the user to run /sync first.
# ──────────────────────────────────────────────────────────────────────────────

GATE_HOOK_MARKER = "# harnesssync-gate-v1"

GATE_HOOK_TEMPLATE = """\
#!/bin/sh
# HarnessSync pre-commit sync gate
# Blocks commits when harness configs are stale (out of sync with CLAUDE.md).
# Installed by: /sync-git-hook install --gate
# Remove with:  /sync-git-hook uninstall --gate

HARNESSSYNC_GATE_MARKER="# harnesssync-gate-v1"
$HARNESSSYNC_GATE_MARKER

# Only activate when source config files are staged
staged=$(git diff --cached --name-only 2>/dev/null)

triggers=0
for pattern in CLAUDE.md .claude/ .mcp.json .harness-sync/; do
    if echo "$staged" | grep -q "^$pattern"; then
        triggers=1
        break
    fi
done

if [ "$triggers" -eq 0 ]; then
    exit 0
fi

# Find HarnessSync plugin root
if [ -n "$CLAUDE_PLUGIN_ROOT" ]; then
    HS_ROOT="$CLAUDE_PLUGIN_ROOT"
elif [ -f "$HOME/.claude/plugins/harness-sync/src/commands/sync.py" ]; then
    HS_ROOT="$HOME/.claude/plugins/harness-sync"
else
    exit 0
fi

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
    exit 0
fi

# Check if sync state is stale using drift detection
stale=$("$PY" "$HS_ROOT/src/commands/sync.py" --drift-check 2>/dev/null; echo $?)

if [ "$stale" != "0" ]; then
    echo "" >&2
    echo "HarnessSync GATE: commit blocked — harness configs are stale." >&2
    echo "" >&2
    echo "  Claude Code config changed but target harness files are out of date." >&2
    echo "  Run: /sync" >&2
    echo "  Then re-run: git commit" >&2
    echo "" >&2
    echo "  To bypass: git commit --no-verify  (not recommended)" >&2
    echo "" >&2
    exit 1
fi

exit 0
"""


def install_gate_hook(project_dir: Path) -> tuple[bool, str]:
    """Install pre-commit sync gate hook.

    The gate hook blocks commits when CLAUDE.md or related config files are
    staged but the harness target files (AGENTS.md, GEMINI.md, etc.) are out
    of sync.  Unlike the auto-stage pre-commit hook, this hook does NOT run
    sync automatically — it instructs the user to run /sync first and then
    commit again.

    Args:
        project_dir: Project directory to start searching for git repo.

    Returns:
        (success, message) tuple.
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False, "Not inside a git repository"

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(exist_ok=True)

    hook_path = hooks_dir / "pre-commit"

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if GATE_HOOK_MARKER in existing:
            return True, f"Gate hook already installed at {hook_path}"
        with open(hook_path, "a", encoding="utf-8") as f:
            f.write("\n" + GATE_HOOK_TEMPLATE)
        _make_executable(hook_path)
        return True, f"HarnessSync gate hook appended to existing pre-commit hook at {hook_path}"

    hook_path.write_text(GATE_HOOK_TEMPLATE, encoding="utf-8")
    _make_executable(hook_path)
    return True, f"Pre-commit sync gate hook installed at {hook_path}"


def uninstall_gate_hook(project_dir: Path) -> tuple[bool, str]:
    """Remove the HarnessSync sync gate from the pre-commit hook.

    Args:
        project_dir: Project directory to search for git repo.

    Returns:
        (success, message) tuple.
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False, "Not inside a git repository"

    hook_path = git_dir / "hooks" / "pre-commit"
    if not hook_path.exists():
        return True, "No pre-commit hook found (nothing to remove)"

    content = hook_path.read_text(encoding="utf-8")
    if GATE_HOOK_MARKER not in content:
        return True, "HarnessSync gate hook not found in pre-commit hook"

    # Remove the gate block — everything between GATE_HOOK_MARKER occurrences
    lines = content.splitlines(keepends=True)
    in_gate_block = False
    kept: list[str] = []
    for line in lines:
        if GATE_HOOK_MARKER in line:
            in_gate_block = not in_gate_block
            continue
        if not in_gate_block:
            kept.append(line)

    new_content = "".join(kept).strip()
    if not new_content or new_content == "#!/bin/sh":
        hook_path.unlink()
        return True, f"Gate pre-commit hook removed from {hook_path}"
    hook_path.write_text(new_content + "\n", encoding="utf-8")
    return True, f"HarnessSync gate section removed from pre-commit hook at {hook_path}"


def is_gate_hook_installed(project_dir: Path) -> bool:
    """Check if HarnessSync sync gate pre-commit hook is installed.

    Args:
        project_dir: Project directory.

    Returns:
        True if the gate hook is installed.
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False
    hook_path = git_dir / "hooks" / "pre-commit"
    if not hook_path.exists():
        return False
    return GATE_HOOK_MARKER in hook_path.read_text(encoding="utf-8")
