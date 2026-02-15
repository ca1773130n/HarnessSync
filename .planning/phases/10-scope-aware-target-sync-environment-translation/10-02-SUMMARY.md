# Plan 10-02 Summary: Scope-Aware Adapters & Orchestrator

**Status:** COMPLETE
**Duration:** ~2 min
**Files modified:** src/adapters/base.py, src/adapters/codex.py, src/adapters/gemini.py, src/adapters/opencode.py, src/orchestrator.py

## What Was Done

### base.py
- Added `sync_mcp_scoped()` with default fallback to `sync_mcp()` for backward compatibility
- Updated `sync_all()` to check for `mcp_scoped` key first, fall back to `mcp`

### orchestrator.py
- Added `adapter_data['mcp_scoped']` alongside existing `adapter_data['mcp']`
- Data flows: `SourceReader.discover_all()['mcp_servers_scoped']` -> `adapter_data['mcp_scoped']` -> `adapter.sync_mcp_scoped()`

### codex.py
- Added import for `translate_env_vars_for_codex` and `check_transport_support`
- Override `sync_mcp_scoped()`: routes user/local/plugin -> `~/.codex/codex.toml`, project -> `.codex/codex.toml`
- Calls `translate_env_vars_for_codex()` on each config before TOML generation
- Calls `check_transport_support()` to skip SSE with warning
- Extracted `_write_mcp_to_path()` helper; `sync_mcp()` delegates to it

### gemini.py
- Added import for `check_transport_support`
- Override `sync_mcp_scoped()`: routes user/local/plugin -> `~/.gemini/settings.json`, project -> `.gemini/settings.json`
- No env var translation (Gemini supports `${VAR}` natively)
- Extracted `_write_mcp_to_settings()` helper; `sync_mcp()` delegates to it

### opencode.py
- Added import for `check_transport_support`
- Override `sync_mcp_scoped()`: all servers go to `opencode.json` (project-level only)
- Transport validation filters unsupported SSE servers

## Verification

- All 5 modules import without errors (Level 1: Sanity)
- All adapters have both `sync_mcp()` and `sync_mcp_scoped()` methods
- Backward compatibility preserved via default fallback in base class
