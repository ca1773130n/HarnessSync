from __future__ import annotations

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


# Auth credential markers per CLI — if none exist, the CLI isn't set up
_TARGET_AUTH_MARKERS = {
    'codex': ['auth.json'],
    'gemini': ['settings.json', '.gemini/oauth_creds.json', '.gemini/google_accounts.json'],
    'opencode': ['package.json', 'config.json'],
}


def _has_auth(target_dir: Path, cli: str) -> bool:
    """Check if a target CLI directory has valid auth credentials."""
    markers = _TARGET_AUTH_MARKERS.get(cli, [])
    for marker in markers:
        if (target_dir / marker).exists():
            return True
    return False


def _extract_suffix(name: str, prefix: str) -> str:
    """Extract account suffix from directory name.

    .claude-personal1 with prefix '.claude' -> 'personal1'
    .codex with prefix '.codex' -> ''
    .gemini-work with prefix '.gemini' -> 'work'
    """
    rest = name[len(prefix):]
    return rest.lstrip('-')


def auto_discover_accounts(home_dir: Path = None) -> list[dict]:
    """Auto-discover accounts by scanning home directory.

    Matches .claude* source dirs to .codex*/.gemini*/.opencode* target dirs
    by suffix pattern. Filters targets that lack auth credentials.

    Args:
        home_dir: Directory to search (default: Path.home())

    Returns:
        List of account dicts with keys: name, source, targets
        Each targets dict maps cli name -> Path
    """
    home_dir = home_dir or Path.home()

    # Step 1: Discover all .claude* source directories
    sources = discover_claude_configs(home_dir, max_depth=1)
    valid_sources = [p for p in sources if validate_claude_config(p)]

    # Step 2: Build suffix -> source mapping
    # .claude -> 'default', .claude-personal1 -> 'personal1'
    suffix_to_source = {}
    for src in valid_sources:
        suffix = _extract_suffix(src.name, '.claude')
        account_name = suffix if suffix else 'default'
        suffix_to_source[account_name] = src

    # Step 3: Scan for target dirs and match by suffix
    cli_prefixes = {'codex': '.codex', 'gemini': '.gemini', 'opencode': '.opencode'}
    # Build suffix -> {cli: path} mapping from targets
    suffix_to_targets: dict[str, dict[str, Path]] = {}

    try:
        for entry in home_dir.iterdir():
            if not entry.is_dir():
                continue
            for cli, prefix in cli_prefixes.items():
                if entry.name.startswith(prefix):
                    suffix = _extract_suffix(entry.name, prefix)
                    account_name = suffix if suffix else 'default'
                    # Check auth credentials
                    if not _has_auth(entry, cli):
                        continue
                    suffix_to_targets.setdefault(account_name, {})[cli] = entry
    except (OSError, PermissionError):
        pass

    # Step 4: Match sources to targets
    accounts = []
    for account_name, source_path in sorted(suffix_to_source.items()):
        targets = suffix_to_targets.get(account_name, {})
        if not targets:
            continue  # No valid targets for this source
        accounts.append({
            'name': account_name,
            'source': source_path,
            'targets': targets,
        })

    return accounts
