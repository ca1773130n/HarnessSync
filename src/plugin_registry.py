from __future__ import annotations

"""Static plugin equivalence mapping for cross-harness plugin sync.

Maps Claude Code plugin names to their native equivalents in each target
harness. When a native equivalent exists, the adapter can reference/enable
it directly instead of decomposing the plugin into individual skills,
agents, commands, MCP servers, and hooks.

Users can override or extend the mapping via `.harnesssync` config:
    {"plugin_map": {"my-plugin": {"codex": "codex-equivalent"}}}
"""

import json
from pathlib import Path


# Static mapping: claude_code_plugin -> {target: native_equivalent_or_None}
# None means the target has no equivalent — decompose as fallback.
# Maintained manually as new plugin equivalents are discovered.
PLUGIN_EQUIVALENTS: dict[str, dict[str, str | None]] = {
    "context-mode": {
        "codex": None,
        "gemini": None,
        "opencode": None,
    },
    "sentry": {
        "codex": "@sentry/codex-plugin",
        "gemini": None,
        "opencode": "@sentry/opencode-plugin",
    },
    "linear": {
        "codex": None,
        "gemini": "linear-gemini-extension",
        "opencode": None,
    },
    "github-notifications": {
        "codex": None,
        "gemini": None,
        "opencode": None,
    },
}


def lookup_native_equivalent(
    plugin_name: str,
    target: str,
    user_overrides: dict[str, dict[str, str | None]] | None = None,
) -> str | None:
    """Look up the native equivalent of a Claude Code plugin for a target harness.

    Resolution order (highest priority wins):
    1. User overrides from `.harnesssync` config `plugin_map` key
    2. Static `PLUGIN_EQUIVALENTS` mapping

    Args:
        plugin_name: Claude Code plugin identifier (e.g. "sentry")
        target: Target harness name (e.g. "codex")
        user_overrides: Optional user-provided plugin_map dict

    Returns:
        Native plugin identifier string if an equivalent exists,
        or None if no equivalent is known (decompose as fallback).
    """
    # Check user overrides first
    if user_overrides:
        plugin_overrides = user_overrides.get(plugin_name, {})
        if isinstance(plugin_overrides, dict) and target in plugin_overrides:
            return plugin_overrides[target]

    # Fall back to static registry
    plugin_entry = PLUGIN_EQUIVALENTS.get(plugin_name, {})
    if isinstance(plugin_entry, dict) and target in plugin_entry:
        return plugin_entry[target]

    return None


def load_user_plugin_map(project_dir: Path | None = None) -> dict[str, dict[str, str | None]]:
    """Load user plugin_map overrides from `.harnesssync` config.

    Args:
        project_dir: Project directory containing `.harnesssync` config

    Returns:
        Dict mapping plugin_name -> {target: equivalent_or_None}.
        Empty dict if no config or no plugin_map key.
    """
    if not project_dir:
        return {}
    config_path = project_dir / ".harnesssync"
    if not config_path.is_file():
        return {}
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        plugin_map = data.get("plugin_map", {})
        if isinstance(plugin_map, dict):
            return plugin_map
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {}
