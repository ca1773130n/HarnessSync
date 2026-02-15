# Plan 09-01 Summary: Plugin MCP Discovery

**Completed:** 2026-02-15
**Files modified:** src/source_reader.py

## What Was Done

Added three private methods to SourceReader for plugin MCP server discovery:

1. **`_get_enabled_plugins()`** — Reads `enabledPlugins` from settings.json (user + project scope), returns set of explicitly enabled plugin identifiers. Used for filtering.

2. **`_expand_plugin_root(config, plugin_path)`** — Serializes config to JSON string, replaces all `${CLAUDE_PLUGIN_ROOT}` occurrences with absolute plugin path, parses back. Handles expansion in all nested fields (command, args, env).

3. **`_get_plugin_mcp_servers()`** — Discovers MCP servers from installed plugins:
   - Reads version 2 `installed_plugins.json` (plugin_key → list of installs)
   - Filters explicitly disabled plugins (enabledPlugins[key] == False)
   - Supports dual MCP registration: standalone `.mcp.json` (flat or nested format) and inline `plugin.json.mcpServers`
   - Checks `.claude-plugin/plugin.json` first, then root `plugin.json`
   - Expands `${CLAUDE_PLUGIN_ROOT}` and tags each server with `_plugin_name`, `_plugin_version`, `_source` metadata

## Verification Results

**Level 1 (Sanity) — ALL PASSED:**
- `_get_enabled_plugins()` correctly reads enabledPlugins from settings.json
- `_expand_plugin_root()` replaces ${CLAUDE_PLUGIN_ROOT} in command, args, env fields
- `_get_plugin_mcp_servers()` discovers servers from both .mcp.json and inline plugin.json
- Disabled plugins are filtered out
- Version 2 installed_plugins.json format parsed correctly
- Plugin metadata (_plugin_name, _plugin_version, _source) attached to each server config

## Design Decisions

- **Disabled plugin filtering:** Only plugins explicitly set to `False` in `enabledPlugins` are skipped. Plugins not mentioned are treated as enabled (backward compatible with Claude Code behavior).
- **Variable expansion at discovery time:** `${CLAUDE_PLUGIN_ROOT}` resolved during discovery, not deferred to sync time, because target CLIs don't support this variable.
- **Underscore-prefixed metadata:** Plugin metadata stored as `_plugin_name`, `_plugin_version`, `_source` in config dict for Plan 02 to extract and clean.
