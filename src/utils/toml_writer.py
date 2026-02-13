"""Manual TOML string formatting utilities.

This module provides manual TOML generation since Python's tomllib is read-only.
We use f-strings and templates with proper escaping per TOML v1.0.0 spec.

Why manual generation:
- tomllib (stdlib 3.11+) is read-only - no write support
- Zero-dependency constraint prevents using tomli-w or tomlkit
- TOML format is simple enough for manual generation
- Full control over formatting and escaping

Escaping rules (TOML v1.0.0):
- Backslash must be escaped FIRST: \ -> \\
- Then quotes: " -> \"
- Then control chars: \\n -> \\\\n, \\r -> \\\\r, \\t -> \\\\t

Environment variables:
- Env var references like ${VAR} are preserved as-is (literal strings)
- Target CLI handles env var expansion at runtime, not sync time

Atomic writes:
- Use write_toml_atomic() for safe config file updates
- Follows tempfile + os.replace pattern from Phase 1 state_manager
"""

import os
import tempfile
from pathlib import Path


def escape_toml_string(s: str) -> str:
    """Escape special characters for TOML basic strings.

    CRITICAL: Backslash must be escaped FIRST, then quotes, then control chars.
    Wrong order creates invalid escape sequences.

    Args:
        s: String to escape

    Returns:
        Escaped string (without surrounding quotes)

    Example:
        >>> escape_toml_string('path\\\\to\\\\file')
        'path\\\\\\\\to\\\\\\\\file'
        >>> escape_toml_string('has"quote')
        'has\\\\"quote'
    """
    return (s
        .replace('\\', '\\\\')      # Backslash FIRST
        .replace('"', '\\"')         # Quote
        .replace('\n', '\\n')        # Newline
        .replace('\r', '\\r')        # Carriage return
        .replace('\t', '\\t'))       # Tab


def format_toml_value(value) -> str:
    """Format a Python value as a TOML value string.

    Args:
        value: Python value (str, int, float, bool, list, dict, None)

    Returns:
        TOML-formatted value string

    Examples:
        >>> format_toml_value('hello')
        '"hello"'
        >>> format_toml_value(42)
        '42'
        >>> format_toml_value(True)
        'true'
        >>> format_toml_value(['a', 'b'])
        '["a", "b"]'
    """
    if value is None:
        return ''
    elif isinstance(value, bool):
        # Must check bool before int (bool is subclass of int)
        return 'true' if value else 'false'
    elif isinstance(value, int):
        return str(value)
    elif isinstance(value, float):
        return str(value)
    elif isinstance(value, str):
        return f'"{escape_toml_string(value)}"'
    elif isinstance(value, list):
        # Recursively format list elements
        elements = [format_toml_value(item) for item in value]
        return f"[{', '.join(elements)}]"
    elif isinstance(value, dict):
        # Dicts become nested tables, handled separately
        return ''
    else:
        return ''


def format_toml_table(table_path: str, data: dict, skip_nested: bool = True) -> str:
    """Format a TOML table section.

    Args:
        table_path: Table path (e.g., 'mcp_servers.name')
        data: Dict of key-value pairs
        skip_nested: If True, skip dict values (they become separate tables)

    Returns:
        TOML table string

    Example:
        >>> format_toml_table('server', {'command': 'node', 'port': 3000})
        '[server]\\ncommand = "node"\\nport = 3000\\n'
    """
    lines = [f'[{table_path}]']

    for key, val in data.items():
        # Skip nested dicts if requested
        if skip_nested and isinstance(val, dict):
            continue

        # Skip None values
        if val is None:
            continue

        # Quote keys if they contain special characters
        if any(c in key for c in ('.', '"', ' ')):
            key_str = f'"{key}"'
        else:
            key_str = key

        # Format value
        val_str = format_toml_value(val)
        if val_str:  # Skip if format_toml_value returned empty string
            lines.append(f'{key_str} = {val_str}')

    return '\n'.join(lines)


def format_mcp_server_toml(name: str, config: dict) -> str:
    """Format a single MCP server as TOML.

    Follows Codex [mcp_servers."name"] format with support for:
    - command/args (stdio transport)
    - url/bearer_token_env_var (HTTP transport)
    - env dict (nested table)
    - enabled/required flags
    - startup_timeout_sec/tool_timeout_sec
    - enabled_tools/disabled_tools lists

    Args:
        name: Server name
        config: Server config dict

    Returns:
        TOML string for this server

    Example:
        >>> format_mcp_server_toml('test', {
        ...     'command': 'node',
        ...     'args': ['server.js'],
        ...     'env': {'API_KEY': '${API_KEY}'},
        ... })
        '[mcp_servers."test"]\\ncommand = "node"\\nargs = ["server.js"]...'
    """
    lines = [f'[mcp_servers."{name}"]']

    # Command-based (stdio) server
    if 'command' in config:
        lines.append(f'command = {format_toml_value(config["command"])}')

    # URL-based (HTTP) server
    if 'url' in config:
        lines.append(f'url = {format_toml_value(config["url"])}')

    # Args array
    if 'args' in config and isinstance(config['args'], list):
        lines.append(f'args = {format_toml_value(config["args"])}')

    # Boolean flags
    if 'enabled' in config:
        lines.append(f'enabled = {format_toml_value(config["enabled"])}')

    if 'required' in config:
        lines.append(f'required = {format_toml_value(config["required"])}')

    # Integer timeouts
    if 'startup_timeout_sec' in config:
        lines.append(f'startup_timeout_sec = {config["startup_timeout_sec"]}')

    if 'tool_timeout_sec' in config:
        lines.append(f'tool_timeout_sec = {config["tool_timeout_sec"]}')

    # Tool filtering lists
    if 'enabled_tools' in config and isinstance(config['enabled_tools'], list):
        lines.append(f'enabled_tools = {format_toml_value(config["enabled_tools"])}')

    if 'disabled_tools' in config and isinstance(config['disabled_tools'], list):
        lines.append(f'disabled_tools = {format_toml_value(config["disabled_tools"])}')

    # HTTP-specific fields
    if 'bearer_token_env_var' in config:
        lines.append(f'bearer_token_env_var = {format_toml_value(config["bearer_token_env_var"])}')

    # Environment variables (nested table)
    if 'env' in config and isinstance(config['env'], dict):
        lines.append('')
        lines.append(f'[mcp_servers."{name}".env]')
        for key, val in config['env'].items():
            # Preserve env var references like ${API_KEY} as-is
            lines.append(f'{key} = {format_toml_value(str(val))}')

    # HTTP headers (nested table)
    if 'http_headers' in config and isinstance(config['http_headers'], dict):
        lines.append('')
        lines.append(f'[mcp_servers."{name}".http_headers]')
        for key, val in config['http_headers'].items():
            lines.append(f'{key} = {format_toml_value(str(val))}')

    return '\n'.join(lines)


def format_mcp_servers_toml(servers: dict[str, dict]) -> str:
    """Format multiple MCP servers as TOML.

    Adds HarnessSync header comment and separates servers with blank lines.

    Args:
        servers: Dict mapping server name to server config dict

    Returns:
        Complete TOML string for all servers

    Example:
        >>> servers = {
        ...     'server-a': {'command': 'a'},
        ...     'server-b': {'command': 'b'},
        ... }
        >>> toml = format_mcp_servers_toml(servers)
        >>> 'HarnessSync' in toml
        True
    """
    sections = [
        '# MCP servers managed by HarnessSync',
        '# Do not edit manually - changes will be overwritten on next sync',
        '',
    ]

    # Format each server
    server_sections = [
        format_mcp_server_toml(name, config)
        for name, config in servers.items()
    ]

    sections.extend(server_sections)

    # Separate servers with double newlines
    return '\n\n'.join(sections)


def write_toml_atomic(path: Path, content: str) -> None:
    """Write TOML content atomically using tempfile + os.replace.

    Uses the atomic write pattern from Phase 1 state_manager to prevent
    corrupted config files on interrupted writes.

    Args:
        path: Target file path
        content: TOML content string

    Raises:
        OSError: If write or rename fails
    """
    from src.utils.paths import ensure_dir

    # Ensure parent directory exists
    ensure_dir(path.parent)

    # Create temp file in same directory for atomic rename
    temp_fd = tempfile.NamedTemporaryFile(
        mode='w',
        dir=path.parent,
        suffix='.tmp',
        delete=False,
        encoding='utf-8'
    )
    temp_path = Path(temp_fd.name)

    try:
        # Write content
        temp_fd.write(content)
        temp_fd.flush()
        os.fsync(temp_fd.fileno())
        temp_fd.close()

        # Atomic rename
        os.replace(str(temp_path), str(path))

    except Exception:
        # Cleanup on failure
        if not temp_fd.closed:
            temp_fd.close()
        if temp_path.exists():
            temp_path.unlink()
        raise
