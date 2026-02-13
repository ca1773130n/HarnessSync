---
phase: 03-gemini-opencode-adapters
plan: 02
subsystem: adapters
status: complete
completed: 2026-02-13

tags:
  - adapter-pattern
  - opencode-cli
  - symlink-support
  - type-discriminated-mcp
  - 3-adapter-integration

dependency_graph:
  requires:
    - AdapterBase (02-01)
    - AdapterRegistry (02-01)
    - SyncResult (02-01)
    - paths utilities (01-01)
    - GeminiAdapter (03-01)
  provides:
    - OpenCodeAdapter
    - 3-adapter integration
  affects:
    - src/adapters/opencode.py (new file)
    - src/adapters/__init__.py (auto-registration imports)

tech_stack:
  added:
    - OpenCode CLI adapter (symlink-based, .opencode/ directories)
    - Type-discriminated MCP config (local/remote)
  patterns:
    - Native symlink support with stale cleanup
    - Type-discriminated MCP server format
    - Conservative permission mapping (restricted/default mode)

key_files:
  created:
    - src/adapters/opencode.py (474 lines)
  modified:
    - src/adapters/__init__.py (added auto-registration imports)

decisions:
  - title: "Type-discriminated MCP format for OpenCode"
    rationale: "OpenCode uses type: 'local' for stdio servers and type: 'remote' for URL servers, following research findings for clarity and explicit transport specification"
    alternatives: "Single unified format with transport auto-detection"
    date: 2026-02-13

  - title: "Command array format for stdio servers"
    rationale: "OpenCode expects command as array [cmd, arg1, arg2] not command+args split, combine them during translation"
    alternatives: "Keep command and args separate"
    date: 2026-02-13

  - title: "Environment key for OpenCode"
    rationale: "OpenCode uses 'environment' not 'env' for environment variables, map accordingly during MCP translation"
    alternatives: "Use 'env' and let OpenCode CLI handle it"
    date: 2026-02-13

metrics:
  duration_minutes: 25
  tasks_completed: 2
  files_created: 1
  files_modified: 1
  verification_tests: 18
  test_pass_rate: 100%
---

# Phase 03 Plan 02: OpenCode Adapter & 3-Adapter Integration Summary

**One-liner:** OpenCodeAdapter with all 6 sync methods (symlinks to .opencode/, type-discriminated MCP to opencode.json, conservative permissions) plus verified 3-adapter integration (Codex, Gemini, OpenCode all sync test project with 0 failures).

## Overview

Completed Phase 3 by implementing the OpenCode adapter with native symlink support and type-discriminated MCP config format. Verified the adapter pattern scales to three distinct target architectures (Codex: directory-based with TOML, Gemini: monolithic with JSON, OpenCode: symlink-based with JSON). All 12 Phase 3 requirements (GMN-01 through GMN-06, OC-01 through OC-06) delivered and verified.

## Tasks Completed

### Task 1: Implement OpenCodeAdapter with all 6 sync methods

**What was built:**
- Created `src/adapters/opencode.py` with OpenCodeAdapter registered via `@AdapterRegistry.register('opencode')`
- Implemented sync_rules: concatenates rules into AGENTS.md (project root) with HarnessSync markers
- Implemented sync_skills: creates symlinks from .claude/skills/ to .opencode/skills/ with stale cleanup
- Implemented sync_agents: creates symlinks from .claude/agents/ to .opencode/agents/ with .md extension
- Implemented sync_commands: creates symlinks from .claude/commands/ to .opencode/commands/ with .md extension
- Implemented sync_mcp: translates MCP servers to opencode.json with type discrimination:
  - Stdio transport (has "command") → type: "local" with command array and environment
  - URL transport (has "url") → type: "remote" with url and headers
- Implemented sync_settings: maps permissions conservatively to opencode.json:
  - Deny list → restricted mode with denied tools
  - Allow list (no deny) → default mode with allowed tools
  - Both empty → default mode
  - NEVER sets yolo or unrestricted mode
- Stale symlink cleanup using cleanup_stale_symlinks after all sync operations
- Preserves environment variable references (${VAR}) in MCP configs

**Verification:** 11 tests passed (adapter instantiation, sync_rules markers, sync_skills symlinks, sync_agents symlinks, sync_commands symlinks, stale cleanup, stdio MCP local type, URL MCP remote type, env var preservation, deny list restricted mode, MCP+settings coexistence)

**Files:**
- `src/adapters/opencode.py`: OpenCodeAdapter implementation (474 lines)

**Commit:** `25eebe1`

### Task 2: Update adapter imports and run 3-adapter integration verification

**What was built:**
- Updated `src/adapters/__init__.py` to import codex, gemini, opencode modules
- Added `from . import codex`, `from . import gemini`, `from . import opencode` with noqa comments
- This ensures all adapters auto-register when src.adapters package is imported
- Created comprehensive 3-adapter integration test that syncs same test project to all 3 adapters
- Test project contains: 2 rules, 3 skills, 2 agents, 1 command, 2 MCP servers (stdio + URL), permission settings
- Verified adapter discovery: AdapterRegistry.list_targets() returns ['codex', 'gemini', 'opencode']
- Verified target-specific artifacts:
  - **Codex:** AGENTS.md exists, .agents/skills/ has symlinks, .codex/codex.toml has MCP servers
  - **Gemini:** GEMINI.md exists with inlined skills (no YAML frontmatter), .gemini/settings.json has mcpServers
  - **OpenCode:** AGENTS.md exists, .opencode/skills/ has symlinks, .opencode/agents/ has symlinks, opencode.json has type-discriminated MCP
- Verified conservative permission mapping across all 3 adapters

**Verification:** 7 tests passed (adapter discovery, has_target checks, 3-adapter integration, Codex artifacts, Gemini artifacts, OpenCode artifacts, conservative permissions)

**Files:**
- `src/adapters/__init__.py`: Added auto-registration imports (5 lines)

**Commit:** `15d95c6`

## Deviations from Plan

None - plan executed exactly as written.

## Requirements Delivered

**OpenCode Requirements (OC-01 through OC-06):**
- **OC-01**: OpenCodeAdapter registered and sync_rules writes rules to AGENTS.md with HarnessSync markers
- **OC-02**: sync_skills creates symlinks in .opencode/skills/ with stale symlink cleanup
- **OC-03**: sync_agents creates symlinks in .opencode/agents/ with .md extension and stale cleanup
- **OC-04**: sync_commands creates symlinks in .opencode/commands/ with .md extension and stale cleanup
- **OC-05**: sync_mcp translates MCP servers to opencode.json with type discrimination (local/remote)
- **OC-06**: sync_settings maps permissions conservatively (restricted/default mode, never yolo)

**Phase 3 Integration:**
- All 3 adapters (Codex, Gemini, OpenCode) registered and discoverable
- 3-adapter integration test passes with 0 failures across all config types
- Conservative permission mapping verified across all 3 adapters

All 12 Phase 3 requirements complete (GMN-01 through GMN-06, OC-01 through OC-06).

## Key Implementation Details

**OpenCode architecture differences:**
- Uses native symlinks (not inline content like Gemini)
- Separate directories for skills, agents, commands under .opencode/
- Single opencode.json for both MCP and settings (not separate files)
- Type-discriminated MCP format for clarity

**Type-discriminated MCP translation:**
- Stdio servers (has "command" key):
  - Set type: "local"
  - Combine command + args into single array: [command, arg1, arg2]
  - Map env → environment (OpenCode key name)
  - Set enabled: true
- URL servers (has "url" key):
  - Set type: "remote"
  - Copy url directly
  - Include headers if present
  - Set enabled: true
- Environment variables: preserve ${VAR} references as literal strings (OpenCode expands at runtime)

**Symlink management:**
- Skills: .opencode/skills/{name} → .claude/skills/{name}
- Agents: .opencode/agents/{name}.md → .claude/agents/{name}.md
- Commands: .opencode/commands/{name}.md → .claude/commands/{name}.md
- Stale cleanup: cleanup_stale_symlinks removes broken symlinks after sync
- Cross-platform: uses create_symlink_with_fallback (symlink → junction → copy)

**Conservative permission mapping:**
- Deny list → restricted mode with denied tools list
- Allow list (no deny) → default mode with allowed tools list
- Both empty → default mode (no restrictions)
- Auto-approval → log warning, NEVER enable yolo mode (security constraint)

**Auto-registration pattern:**
- __init__.py imports all adapter modules to trigger @AdapterRegistry.register() decorators
- This ensures adapters are registered on package import, not lazy loading
- Allows AdapterRegistry.list_targets() to work immediately

## Verification Results

**Task 1:** 11/11 tests passed
1. OpenCodeAdapter instantiation
2. sync_rules writes to AGENTS.md with markers and content
3. sync_skills creates symlinks in .opencode/skills/
4. sync_agents creates symlinks in .opencode/agents/{name}.md
5. sync_commands creates symlinks in .opencode/commands/{name}.md
6. Stale symlinks are cleaned up after sync
7. sync_mcp with stdio server creates type: local config
8. sync_mcp with URL server creates type: remote config
9. sync_mcp preserves environment variable references
10. sync_settings with deny list creates restricted mode
11. sync_settings + sync_mcp coexist in same opencode.json

**Task 2:** 7/7 tests passed
1. Adapter discovery (AdapterRegistry.list_targets() returns 3 targets)
2. has_target() checks work for all targets
3. 3-adapter integration (all adapters sync test project with 0 failures)
4. Codex-specific artifacts verified (AGENTS.md, symlinks, codex.toml)
5. Gemini-specific artifacts verified (GEMINI.md inline, no frontmatter, settings.json)
6. OpenCode-specific artifacts verified (symlinks, type-discriminated MCP)
7. Conservative permission mapping across all 3 adapters

**Total:** 18/18 tests passed (100% pass rate)

**3-Adapter Integration Summary Table:**

```
Target   | Rules | Skills | Agents | Cmds | MCP | Settings | Status
---------|-------|--------|--------|------|-----|----------|-------
codex    | 1/0   | 3/0    | 2/0    | 1/0  | 2/0 | 1/0      | PASS
gemini   | 1/0   | 3/0    | 2/0    | 1/0  | 2/0 | 1/0      | PASS
opencode | 1/0   | 3/0    | 2/0    | 1/0  | 2/0 | 1/0      | PASS
```
Format: synced/failed for each column.

**Phase 3 Success Criteria:**
- ✓ Gemini adapter inlines skills into GEMINI.md (strips frontmatter)
- ✓ Gemini adapter translates MCP to settings.json mcpServers
- ✓ OpenCode adapter creates symlinks to .opencode/ with stale cleanup
- ✓ OpenCode adapter translates MCP to opencode.json with type discrimination
- ✓ All 3 adapters sync test project successfully
- ✓ Conservative permission mapping for all adapters

## Artifacts

**Created files:**
- `src/adapters/opencode.py` (474 lines) - Complete OpenCodeAdapter with all 6 sync methods

**Modified files:**
- `src/adapters/__init__.py` - Added auto-registration imports (5 lines)

**Key exports:**
- `OpenCodeAdapter` class (registered as "opencode")
- AdapterRegistry now lists 3 targets: ['codex', 'gemini', 'opencode']

## Next Steps

1. **Plan 03-03**: Phase 3 integration verification (cross-adapter consistency, end-to-end sync)
2. **Phase 4**: Main sync orchestration (tie SourceReader → AdapterRegistry → StateManager)
3. **Integration test**: Verify all 3 adapters end-to-end with real .claude/ directory

## Performance

- **Duration:** 25 min
- **Started:** 2026-02-13T09:58:44Z
- **Completed:** 2026-02-13T10:24:13Z
- **Tasks:** 2 completed
- **Files modified:** 2 (1 created, 1 modified)

## Self-Check: PASSED

Files verified:
```bash
FOUND: src/adapters/opencode.py
FOUND: src/adapters/__init__.py (imports codex, gemini, opencode)
```

Commits verified:
```bash
FOUND: 25eebe1 (Task 1: OpenCodeAdapter implementation)
FOUND: 15d95c6 (Task 2: 3-adapter integration)
```

Verification tests:
```bash
PASSED: verify_task1_opencode.py (11/11 tests)
PASSED: verify_task2_opencode.py (7/7 tests)
```

Adapter registry check:
```bash
VERIFIED: AdapterRegistry.list_targets() == ['codex', 'gemini', 'opencode']
VERIFIED: All 3 adapters instantiate and sync successfully
```

All claims validated. Phase 3 Plan 02 complete.
