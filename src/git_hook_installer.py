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


# Drift-check hook: fails the commit when target harness configs are out of sync.
# Unlike the pre-commit hook (which syncs silently), this hook BLOCKS the commit
# and prints actionable diagnostics so the team notices config drift before it ships.
DRIFT_CHECK_HOOK_TEMPLATE = """\
#!/bin/sh
# HarnessSync drift-check pre-commit hook
# Fails the commit if harness configs (AGENTS.md, GEMINI.md, etc.) are out of sync
# with CLAUDE.md. Run /sync or harnesssync to update before committing.
# Installed by: /sync-git-hook install --drift-check
# Remove with:  /sync-git-hook uninstall --drift-check

HARNESSSYNC_DRIFT_MARKER="# harnesssync-drift-check-v1"
$HARNESSSYNC_DRIFT_MARKER

# Only run when CLAUDE.md or .claude/ is staged — no Claude config, no check needed
staged=$(git diff --cached --name-only 2>/dev/null)
claude_staged=0
for pattern in CLAUDE.md .claude/ .mcp.json; do
    if echo "$staged" | grep -q "^$pattern"; then
        claude_staged=1
        break
    fi
done

if [ "$claude_staged" -eq 0 ]; then
    exit 0
fi

# Locate HarnessSync
if [ -n "$CLAUDE_PLUGIN_ROOT" ]; then
    HS_ROOT="$CLAUDE_PLUGIN_ROOT"
elif [ -f "$HOME/.claude/plugins/harness-sync/src/commands/sync_status.py" ]; then
    HS_ROOT="$HOME/.claude/plugins/harness-sync"
else
    exit 0
fi

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
    exit 0
fi

# Run sync in dry-run mode to check for drift without writing
drift_output=$("$PY" "$HS_ROOT/src/commands/sync.py" --dry-run --scope all 2>&1)
exit_code=$?

if echo "$drift_output" | grep -qiE "(would (write|update|create)|drift detected|out.of.sync|CONFLICT)"; then
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║  HarnessSync: COMMIT BLOCKED — harness configs are drifted   ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "  Your CLAUDE.md changed but target harness configs are out of sync."
    echo "  Committing now would leave teammates with inconsistent AI tooling."
    echo ""
    echo "  Fix options:"
    echo "    1) Run /sync (inside Claude Code) to sync all targets, then re-commit"
    echo "    2) Run: harnesssync force"
    echo "    3) Skip this check: git commit --no-verify  (not recommended for shared repos)"
    echo ""
    if [ -n "$drift_output" ]; then
        echo "  Drift summary (first 10 lines):"
        echo "$drift_output" | head -10 | sed 's/^/    /'
        echo ""
    fi
    exit 1
fi

exit 0
"""

DRIFT_CHECK_MARKER = "# harnesssync-drift-check-v1"


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


# ──────────────────────────────────────────────────────────────────────────────
# Post-checkout Auto-Sync Hook (Item 11 — Git Branch-Aware Auto-Sync)
#
# Installs a git post-checkout hook that automatically runs HarnessSync
# whenever the user switches branches (git checkout, git switch) or pulls
# a team member's config changes (git pull). This removes the need to
# remember to run /sync after updating CLAUDE.md — the most common cause
# of config drift.
#
# The hook is non-blocking: sync runs in the background so it never delays
# the git checkout. Branch-profile activation is handled by the sync command
# itself (via branch_aware_sync.py).
# ──────────────────────────────────────────────────────────────────────────────

POST_CHECKOUT_HOOK_MARKER = "# harnesssync-post-checkout-v1"

POST_CHECKOUT_HOOK_TEMPLATE = """\
#!/bin/sh
# HarnessSync post-checkout hook
# Automatically syncs config when switching branches or pulling team config changes.
# Installed by: /sync-git-hook install --post-checkout
# Remove with:  /sync-git-hook uninstall --post-checkout

HARNESSSYNC_POST_CHECKOUT_MARKER="# harnesssync-post-checkout-v1"
$HARNESSSYNC_POST_CHECKOUT_MARKER

# $3 is 1 for branch checkouts, 0 for file checkouts — only sync on branch change
CHECKOUT_TYPE="$3"
if [ "$CHECKOUT_TYPE" != "1" ]; then
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

# Check if any HarnessSync-managed source files changed between branches.
# If no relevant files changed, skip the sync to avoid noise.
PREV_HEAD="$1"
NEW_HEAD="$2"

changed=$(git diff --name-only "$PREV_HEAD" "$NEW_HEAD" 2>/dev/null)
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

# Run sync in background (non-blocking)
"$PY" "$HS_ROOT/src/commands/sync.py" --scope all >/dev/null 2>&1 &

exit 0
"""


def install_post_checkout_hook(project_dir: Path) -> tuple[bool, str]:
    """Install git post-checkout hook that auto-syncs on branch switch.

    The hook fires after ``git checkout`` / ``git switch`` (branch checkouts
    only, not file-level checkouts) and runs HarnessSync in the background
    when CLAUDE.md or related config files differ between the old and new
    branch. This removes the need to remember to run /sync after pulling
    team config changes.

    If a post-checkout hook already exists in the repository, the
    HarnessSync block is appended rather than replacing the existing hook,
    preserving any other scripts already registered.

    Args:
        project_dir: Starting directory for git repo discovery.

    Returns:
        Tuple of (success: bool, message: str).
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False, "No git repository found"

    hook_path = git_dir / "hooks" / "post-checkout"

    # If hook already contains our marker, it's already installed
    if hook_path.exists() and POST_CHECKOUT_HOOK_MARKER in hook_path.read_text(encoding="utf-8"):
        return True, f"Post-checkout hook already installed at {hook_path}"

    if hook_path.exists():
        # Append to existing hook
        existing = hook_path.read_text(encoding="utf-8")
        new_content = existing.rstrip() + "\n\n" + POST_CHECKOUT_HOOK_TEMPLATE
    else:
        new_content = POST_CHECKOUT_HOOK_TEMPLATE

    try:
        hook_path.write_text(new_content, encoding="utf-8")
        _make_executable(hook_path)
        return True, f"Post-checkout hook installed at {hook_path}"
    except OSError as e:
        return False, f"Failed to install post-checkout hook: {e}"


def uninstall_post_checkout_hook(project_dir: Path) -> tuple[bool, str]:
    """Remove the HarnessSync block from the git post-checkout hook.

    Removes only the HarnessSync-managed block. If the hook has other
    content, it is preserved. If the hook becomes empty after removal,
    the hook file is deleted.

    Args:
        project_dir: Starting directory for git repo discovery.

    Returns:
        Tuple of (success: bool, message: str).
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False, "No git repository found"

    hook_path = git_dir / "hooks" / "post-checkout"
    if not hook_path.exists():
        return True, "Post-checkout hook not installed"

    content = hook_path.read_text(encoding="utf-8")
    if POST_CHECKOUT_HOOK_MARKER not in content:
        return True, "HarnessSync post-checkout hook block not found"

    # Remove the HarnessSync block (from shebang/marker to the trailing blank line)
    lines = content.splitlines(keepends=True)
    out: list[str] = []
    in_block = False
    for line in lines:
        if POST_CHECKOUT_HOOK_MARKER in line:
            in_block = True
        if not in_block:
            out.append(line)
        elif line.strip() == "exit 0" and in_block:
            # End of our block
            in_block = False

    remaining = "".join(out).strip()
    if not remaining or remaining == "#!/bin/sh":
        hook_path.unlink()
        return True, f"Post-checkout hook removed (file deleted)"

    try:
        hook_path.write_text(remaining + "\n", encoding="utf-8")
        return True, f"HarnessSync block removed from {hook_path}"
    except OSError as e:
        return False, f"Failed to update post-checkout hook: {e}"


def is_post_checkout_hook_installed(project_dir: Path) -> bool:
    """Check if the HarnessSync post-checkout hook is installed.

    Args:
        project_dir: Project directory.

    Returns:
        True if the HarnessSync post-checkout hook block is present.
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False
    hook_path = git_dir / "hooks" / "post-checkout"
    if not hook_path.exists():
        return False
    return POST_CHECKOUT_HOOK_MARKER in hook_path.read_text(encoding="utf-8")


def install_drift_check_hook(project_dir: Path) -> tuple[bool, str]:
    """Install a pre-commit hook that FAILS the commit when harness configs are drifted.

    Unlike the auto-sync pre-commit hook (which silently syncs and stages),
    this hook acts as a gate: it checks for drift and blocks the commit with
    a clear error message and instructions to fix. Intended for teams who
    version their Claude Code config and need CI-like enforcement locally.

    The check only triggers when CLAUDE.md or .claude/ files are staged,
    so it doesn't add overhead to normal code commits.

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
        if DRIFT_CHECK_MARKER in existing:
            return True, f"Drift-check hook already installed at {hook_path}"
        # Append to existing hook
        with open(hook_path, "a", encoding="utf-8") as f:
            f.write("\n" + DRIFT_CHECK_HOOK_TEMPLATE)
        _make_executable(hook_path)
        return True, f"HarnessSync drift-check hook appended to {hook_path}"

    hook_path.write_text(DRIFT_CHECK_HOOK_TEMPLATE, encoding="utf-8")
    _make_executable(hook_path)
    return True, f"Drift-check pre-commit hook installed at {hook_path}"


def uninstall_drift_check_hook(project_dir: Path) -> tuple[bool, str]:
    """Remove the HarnessSync drift-check hook block from the pre-commit hook.

    Args:
        project_dir: Project directory.

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
    if DRIFT_CHECK_MARKER not in content:
        return True, "Drift-check hook not found in pre-commit hook"

    lines = content.splitlines(keepends=True)
    non_dc_lines = [l for l in lines if DRIFT_CHECK_MARKER not in l
                    and not l.strip().startswith("# HarnessSync drift-check")]
    new_content = "".join(non_dc_lines).strip()

    if not new_content or new_content == "#!/bin/sh":
        hook_path.unlink()
        return True, f"Drift-check hook removed (file deleted)"

    hook_path.write_text(new_content + "\n", encoding="utf-8")
    return True, f"HarnessSync drift-check block removed from {hook_path}"


def is_drift_check_hook_installed(project_dir: Path) -> bool:
    """Check if the HarnessSync drift-check pre-commit hook is installed.

    Args:
        project_dir: Project directory.

    Returns:
        True if the drift-check hook block is present in the pre-commit hook.
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False
    hook_path = git_dir / "hooks" / "pre-commit"
    if not hook_path.exists():
        return False
    return DRIFT_CHECK_MARKER in hook_path.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# Commit Message Annotation Hook (item 7 — Git Commit-Triggered Sync)
#
# A post-commit hook that:
# 1. Runs HarnessSync when CLAUDE.md / .claude/ files changed in the commit
# 2. Appends a brief sync summary to the commit message via git commit --amend
#    so the sync results are part of the permanent git history.
#
# This fulfills the item 7 requirement: "sync results included in the commit
# message".  The annotation looks like:
#
#   HarnessSync: synced codex, gemini, opencode (3 targets, 0 errors)
#
# The amend is safe because it is done immediately after the original commit,
# before the branch is pushed, so it does not affect shared history.
# ──────────────────────────────────────────────────────────────────────────────

COMMIT_ANNOTATE_MARKER = "# harnesssync-commit-annotate-v1"

COMMIT_ANNOTATE_HOOK_TEMPLATE = """\
#!/bin/sh
# HarnessSync commit-annotate post-commit hook
# Syncs harness configs on CLAUDE.md changes and appends sync results to the
# commit message so config updates are traceable in git history.
# Installed by: /sync-git-hook install --annotate
# Remove with:  /sync-git-hook uninstall --annotate

HARNESSSYNC_ANNOTATE_MARKER="# harnesssync-commit-annotate-v1"
$HARNESSSYNC_ANNOTATE_MARKER

# Only run when trigger files changed
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
    exit 0
fi

PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
    exit 0
fi

# Run sync and capture output for commit message annotation
sync_output=$("$PY" "$HS_ROOT/src/commands/sync.py" --scope all 2>&1)
sync_exit=$?

# Build annotation line summarising the sync result
if [ "$sync_exit" -eq 0 ]; then
    # Count synced targets from output (look for lines containing "✓")
    synced=$(echo "$sync_output" | grep -c "✓" || true)
    annotation="HarnessSync: synced $synced target(s) — OK"
else
    annotation="HarnessSync: sync completed with warnings (exit $sync_exit)"
fi

# Append annotation to the last commit message via --amend
# We use --no-edit to preserve the original message and just append.
current_msg=$(git log -1 --format="%B" HEAD 2>/dev/null)

# Avoid double-annotating if message already contains our footer
if echo "$current_msg" | grep -q "HarnessSync:"; then
    exit 0
fi

new_msg="${current_msg}

${annotation}"

# Amend silently; if this fails, sync already happened so just exit 0
git commit --amend -m "$new_msg" --no-verify >/dev/null 2>&1 || true

exit 0
"""


def install_commit_annotate_hook(project_dir: Path) -> tuple[bool, str]:
    """Install a post-commit hook that syncs and annotates the commit message.

    The hook fires after every commit.  When CLAUDE.md or related files
    changed, it runs HarnessSync and then amends the commit message to
    include a one-line sync result summary.  This makes harness syncs
    traceable in ``git log`` without any manual effort.

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
    hook_path = hooks_dir / "post-commit"

    if hook_path.exists():
        existing = hook_path.read_text(encoding="utf-8")
        if COMMIT_ANNOTATE_MARKER in existing:
            return True, f"Commit-annotate hook already installed at {hook_path}"
        with open(hook_path, "a", encoding="utf-8") as fh:
            fh.write("\n" + COMMIT_ANNOTATE_HOOK_TEMPLATE)
        _make_executable(hook_path)
        return True, f"HarnessSync commit-annotate hook appended to {hook_path}"

    hook_path.write_text(COMMIT_ANNOTATE_HOOK_TEMPLATE, encoding="utf-8")
    _make_executable(hook_path)
    return True, f"Commit-annotate post-commit hook installed at {hook_path}"


def uninstall_commit_annotate_hook(project_dir: Path) -> tuple[bool, str]:
    """Remove the HarnessSync commit-annotate block from the post-commit hook.

    Args:
        project_dir: Project directory.

    Returns:
        (success, message) tuple.
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False, "Not inside a git repository"

    hook_path = git_dir / "hooks" / "post-commit"
    if not hook_path.exists():
        return True, "No post-commit hook found (nothing to remove)"

    content = hook_path.read_text(encoding="utf-8")
    if COMMIT_ANNOTATE_MARKER not in content:
        return True, "Commit-annotate hook not found in post-commit hook"

    lines = content.splitlines(keepends=True)
    filtered = [ln for ln in lines if COMMIT_ANNOTATE_MARKER not in ln]
    new_content = "".join(filtered).strip()

    if not new_content or new_content == "#!/bin/sh":
        hook_path.unlink()
        return True, "Commit-annotate post-commit hook removed (file deleted)"

    hook_path.write_text(new_content + "\n", encoding="utf-8")
    return True, f"HarnessSync commit-annotate block removed from {hook_path}"


def is_commit_annotate_hook_installed(project_dir: Path) -> bool:
    """Return True if the commit-annotate post-commit hook is installed.

    Args:
        project_dir: Project directory.
    """
    git_dir = find_git_dir(project_dir)
    if not git_dir:
        return False
    hook_path = git_dir / "hooks" / "post-commit"
    if not hook_path.exists():
        return False
    return COMMIT_ANNOTATE_MARKER in hook_path.read_text(encoding="utf-8")
