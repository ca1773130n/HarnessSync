# Plan 09-02 Summary: Scope-Aware MCP Discovery

**Completed:** 2026-02-15
**Files modified:** src/source_reader.py

## What Was Done

Implemented 3-tier scope-aware MCP discovery with precedence-based deduplication and origin tagging:

1. **`_get_user_scope_mcps()`** — Reads user-scope MCPs from `~/.claude.json` top-level `mcpServers` field (NOT `~/.mcp.json` or `~/.claude/.mcp.json` which were v1.0 incorrect sources).

2. **`_get_project_scope_mcps()`** — Reads project-scope MCPs from `.mcp.json` in project root (mcpServers wrapper).

3. **`_get_local_scope_mcps()`** — Reads local-scope MCPs from `~/.claude.json` under `projects[absolutePath].mcpServers`. Critical: local MCP scope is in `~/.claude.json` (home dir), NOT `.claude/settings.local.json`.

4. **`get_mcp_servers_with_scope()`** — Public method implementing layered discovery:
   - Layer 1: User-scope file-based MCPs (tagged scope=user, source=file)
   - Layer 2: Plugin MCPs (tagged scope=user, source=plugin with plugin_name/version)
   - Layer 3: Project-scope MCPs (tagged scope=project, overrides user)
   - Layer 4: Local-scope MCPs (tagged scope=local, highest precedence)
   - Returns: `{server_name: {"config": {...}, "metadata": {...}}}`

5. **`get_mcp_servers()`** — Reimplemented to call `get_mcp_servers_with_scope()` internally, returns flat dict for backward compatibility.

6. **`discover_all()`** — Updated to include both `mcp_servers` (flat) and `mcp_servers_scoped` (with metadata).

7. **`get_source_paths()`** — Updated MCP sources: `~/.claude.json` replaces v1.0 `~/.mcp.json` and `~/.claude/.mcp.json`.

## Verification Results

**Level 2 (Proxy) — ALL PASSED:**
- Discovery: 6/6 servers (100%) from 4 sources
- Scope precedence: shared-server resolves to local (local > project > user)
- Metadata tagging: 100% correct (scope + source on every server)
- Backward compatibility: get_mcp_servers() returns flat dict without metadata
- discover_all() includes mcp_servers_scoped key

## Design Decisions

- **User-scope MCPs from ~/.claude.json:** v2.0 reads from `~/.claude.json` top-level mcpServers, replacing v1.0's `~/.mcp.json` and `~/.claude/.mcp.json` which were incorrect sources for user-scope MCPs.
- **Plugin MCPs cleaned before metadata:** Underscore-prefixed keys (`_plugin_name`, etc.) stripped from config dict and moved to metadata dict in `get_mcp_servers_with_scope()`.
- **File-based user MCPs win over plugins:** When same server name exists in both user files and plugins, the file-based config takes priority.
