"""
Filesystem discovery for Claude Code configuration directories.

Scans home directory with depth limits to find ~/.claude* directories,
validates them for Claude Code structure, and discovers target CLI
directories (.codex*, .gemini*, .opencode*).
"""

from pathlib import Path


# Directories to skip during discovery (large or irrelevant)
_EXCLUDE_DIRS = frozenset({
    '.git', 'node_modules', '.cache', 'Library', 'Applications',
    '.npm', '.cargo', '.venv', '__pycache__', '.Trash', '.local',
    '.pyenv', '.nvm', '.rbenv', '.docker', '.vagrant', '.gradle',
    'Downloads', 'Documents', 'Desktop', 'Pictures', 'Music', 'Movies',
    '.Spotlight-V100', '.fseventsd', '.vol',
})

# Expected Claude Code config files/dirs for validation
_CLAUDE_CONFIG_MARKERS = [
    'settings.json', 'CLAUDE.md', 'skills', 'agents',
    'commands', '.mcp.json', 'plugins',
]


def discover_claude_configs(home_dir: Path = None, max_depth: int = 2) -> list[Path]:
    """Discover Claude Code config directories in home directory.

    Scans for directories whose name starts with '.claude' using
    depth-limited traversal. Excludes known large directories
    to maintain <500ms performance.

    Args:
        home_dir: Directory to search (default: Path.home())
        max_depth: Maximum recursion depth (1 = immediate children only)

    Returns:
        Sorted list of paths to .claude* directories
    """
    home_dir = home_dir or Path.home()
    configs = []

    def scan_level(path: Path, depth: int):
        if depth > max_depth:
            return
        try:
            for entry in path.iterdir():
                # Skip excluded directories
                if entry.name in _EXCLUDE_DIRS:
                    continue

                if not entry.is_dir():
                    continue

                # Check if this is a Claude config directory
                if entry.name.startswith('.claude'):
                    configs.append(entry)
                    continue

                # At depth 1 (home level), only recurse into hidden dirs
                # to check for nested .claude* configs. Skip visible dirs
                # like Documents, Projects, etc. to avoid slow scanning.
                if depth == 1 and entry.name.startswith('.') and depth < max_depth:
                    scan_level(entry, depth + 1)

        except (OSError, PermissionError):
            pass  # Skip directories we can't read

    scan_level(home_dir, depth=1)

    # Sort by name for deterministic output
    configs.sort(key=lambda p: p.name)
    return configs


def validate_claude_config(path: Path) -> bool:
    """Check if path looks like a valid Claude Code config directory.

    Validates by checking for at least one expected Claude Code
    file or subdirectory (settings.json, CLAUDE.md, skills/, etc.).

    Args:
        path: Path to check

    Returns:
        True if path contains at least one Claude Code marker
    """
    if not path.is_dir():
        return False

    try:
        for marker in _CLAUDE_CONFIG_MARKERS:
            if (path / marker).exists():
                return True
    except (OSError, PermissionError):
        pass

    return False


def discover_target_configs(home_dir: Path = None) -> dict[str, list[Path]]:
    """Scan for target CLI directories (.codex*, .gemini*, .opencode*).

    Useful for setup wizard to suggest existing target paths.

    Args:
        home_dir: Directory to search (default: Path.home())

    Returns:
        Dict mapping CLI name -> list of discovered paths
    """
    home_dir = home_dir or Path.home()
    targets = {
        'codex': [],
        'gemini': [],
        'opencode': [],
    }

    try:
        for entry in home_dir.iterdir():
            if not entry.is_dir():
                continue

            name = entry.name
            if name.startswith('.codex'):
                targets['codex'].append(entry)
            elif name.startswith('.gemini'):
                targets['gemini'].append(entry)
            elif name.startswith('.opencode'):
                targets['opencode'].append(entry)
    except (OSError, PermissionError):
        pass

    # Sort each list for deterministic output
    for cli in targets:
        targets[cli].sort(key=lambda p: p.name)

    return targets
