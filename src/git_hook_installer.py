from __future__ import annotations

"""Git post-commit hook installer for auto-sync.

Installs a post-commit hook that triggers HarnessSync whenever CLAUDE.md,
.claude/, or .mcp.json changes in a commit. Config changes are always tied
to code — this makes sync automatic as part of the developer's git workflow.
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


def _make_executable(path: Path) -> None:
    """Make a file executable (chmod +x)."""
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _is_harnesssync_line(line: str) -> bool:
    """Return True if a line is part of the HarnessSync hook block."""
    return HARNESSSYNC_MARKER in line or line.strip().startswith("# HarnessSync")
