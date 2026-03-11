from __future__ import annotations

"""MCP server aliasing per harness.

Define alias mappings so that an MCP server named 'my-sentry-mcp' in
Claude Code is registered as 'sentry' in Cursor and 'sentry-mcp' in Codex—
matching each tool's naming conventions.

Prevents broken references when target harnesses use different naming
schemas in their own config files.

Alias configuration is read from .harnesssync (per-project) or from
~/.harnesssync/mcp_aliases.json (global, shared across projects).

Configuration format in .harnesssync:
{
    "mcp_aliases": {
        "my-sentry-mcp": {
            "cursor": "sentry",
            "codex": "sentry-mcp",
            "gemini": "sentry"
        },
        "context7-server": {
            "aider": "ctx7"
        }
    }
}

Global format in ~/.harnesssync/mcp_aliases.json:
{
    "my-sentry-mcp": {
        "cursor": "sentry",
        "codex": "sentry-mcp"
    }
}
"""

import json
from pathlib import Path


# Global alias config location
_GLOBAL_ALIASES_FILE = Path.home() / ".harnesssync" / "mcp_aliases.json"


def load_aliases(project_dir: Path | None = None) -> dict[str, dict[str, str]]:
    """Load MCP server alias mappings from config files.

    Merges global aliases (~/.harnesssync/mcp_aliases.json) with per-project
    aliases from .harnesssync. Project aliases take precedence on conflict.

    Args:
        project_dir: Project root directory (for .harnesssync config).
                     None means global aliases only.

    Returns:
        Dict mapping original_name -> {target: alias_name}.
        Example: {"my-sentry": {"cursor": "sentry", "codex": "sentry-mcp"}}
    """
    aliases: dict[str, dict[str, str]] = {}

    # Load global aliases
    if _GLOBAL_ALIASES_FILE.exists():
        try:
            global_data = json.loads(_GLOBAL_ALIASES_FILE.read_text(encoding="utf-8"))
            if isinstance(global_data, dict):
                for server, target_map in global_data.items():
                    if isinstance(target_map, dict):
                        aliases[server] = {k: v for k, v in target_map.items()
                                           if isinstance(k, str) and isinstance(v, str)}
        except (OSError, json.JSONDecodeError):
            pass

    # Load per-project aliases (overrides global)
    if project_dir:
        project_config_path = project_dir / ".harnesssync"
        if project_config_path.exists():
            try:
                project_data = json.loads(project_config_path.read_text(encoding="utf-8"))
                project_aliases = project_data.get("mcp_aliases", {})
                if isinstance(project_aliases, dict):
                    for server, target_map in project_aliases.items():
                        if isinstance(target_map, dict):
                            # Merge: project overrides global
                            existing = aliases.get(server, {})
                            existing.update({
                                k: v for k, v in target_map.items()
                                if isinstance(k, str) and isinstance(v, str)
                            })
                            aliases[server] = existing
            except (OSError, json.JSONDecodeError):
                pass

    return aliases


def apply_aliases(
    mcp_servers: dict[str, dict],
    target: str,
    aliases: dict[str, dict[str, str]],
) -> dict[str, dict]:
    """Apply alias mappings to an MCP server config dict for a specific target.

    Renames server keys according to the alias map for the given target.
    Server configs are preserved unchanged — only the key (name) changes.

    If a server has no alias defined for this target, its original name is kept.
    If an alias collision occurs (two servers aliased to the same target name),
    the later entry wins and a warning key is preserved.

    Args:
        mcp_servers: Dict mapping original_name -> server_config.
        target: Target harness name (e.g., "cursor", "codex").
        aliases: Output of load_aliases() — original_name -> {target: alias}.

    Returns:
        New dict with renamed keys for the given target.
    """
    if not aliases:
        return dict(mcp_servers)

    result: dict[str, dict] = {}
    seen_aliases: dict[str, str] = {}  # alias_name -> original_name (collision detection)

    for original_name, config in mcp_servers.items():
        target_aliases = aliases.get(original_name, {})
        alias_name = target_aliases.get(target, original_name)

        if alias_name in seen_aliases:
            # Collision: append suffix to avoid silent override
            alias_name = f"{alias_name}--{original_name}"

        seen_aliases[alias_name] = original_name
        result[alias_name] = config

    return result


def save_global_aliases(aliases: dict[str, dict[str, str]]) -> None:
    """Save alias mappings to global config.

    Args:
        aliases: Dict to save (merges with existing global aliases).

    Raises:
        OSError: If writing fails.
    """
    from src.utils.paths import ensure_dir
    ensure_dir(_GLOBAL_ALIASES_FILE.parent)

    existing: dict[str, dict[str, str]] = {}
    if _GLOBAL_ALIASES_FILE.exists():
        try:
            existing = json.loads(_GLOBAL_ALIASES_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    merged = {**existing, **aliases}
    _GLOBAL_ALIASES_FILE.write_text(json.dumps(merged, indent=2), encoding="utf-8")


def format_alias_table(aliases: dict[str, dict[str, str]]) -> str:
    """Format alias mappings as a human-readable table.

    Args:
        aliases: Output of load_aliases().

    Returns:
        Formatted table string.
    """
    if not aliases:
        return "No MCP server aliases configured."

    lines: list[str] = ["MCP Server Aliases:", ""]
    lines.append(f"{'Original Name':<30}  {'Target':<12}  Alias")
    lines.append("-" * 60)

    for original, target_map in sorted(aliases.items()):
        for target, alias in sorted(target_map.items()):
            lines.append(f"{original:<30}  {target:<12}  {alias}")

    return "\n".join(lines)
