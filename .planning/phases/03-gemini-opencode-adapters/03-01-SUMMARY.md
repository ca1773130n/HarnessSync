---
phase: 03-gemini-opencode-adapters
plan: 01
subsystem: adapters
status: complete
completed: 2026-02-13

tags:
  - adapter-pattern
  - gemini-cli
  - inline-content
  - json-atomic-write
  - permission-mapping

dependency_graph:
  requires:
    - AdapterBase (02-01)
    - AdapterRegistry (02-01)
    - SyncResult (02-01)
    - paths utilities (01-01)
  provides:
    - GeminiAdapter
    - write_json_atomic utility
  affects:
    - src/utils/paths.py (added write_json_atomic)
    - src/adapters/gemini.py (new file)

tech_stack:
  added:
    - Gemini CLI adapter (monolithic GEMINI.md)
    - JSON atomic writes (tempfile + os.replace)
  patterns:
    - Subsection markers for incremental syncing
    - Conservative permission mapping (never auto-enable yolo)
    - Inline content with frontmatter stripping (no symlinks)

key_files:
  created:
    - src/adapters/gemini.py (446 lines)
  modified:
    - src/utils/paths.py (added write_json_atomic, 60 lines)

decisions:
  - title: "Subsection markers within main managed block"
    rationale: "Use subsection markers (<!-- HarnessSync:Skills -->) within main HarnessSync managed block to allow incremental syncing (skills-only, agents-only) without losing other sections"
    alternatives: "Store sections as instance state during sync_all flow"
    date: 2026-02-13

  - title: "Direct URL config for MCP URL transport"
    rationale: "Start with direct URL config (url/httpUrl fields) instead of npx mcp-remote wrapper, following research recommendation for simplicity"
    alternatives: "Use npx mcp-remote wrapper for all URL-based MCP servers"
    date: 2026-02-13

  - title: "Never auto-enable yolo mode"
    rationale: "Conservative security default: even if Claude Code has auto-approval, Gemini yolo mode stays disabled. Log warning in SyncResult instead"
    alternatives: "Map auto-approval -> yolo mode"
    date: 2026-02-13

metrics:
  duration_minutes: 4.1
  tasks_completed: 2
  files_created: 1
  files_modified: 1
  verification_tests: 17
  test_pass_rate: 100%
---

# Phase 03 Plan 01: Gemini CLI Adapter Implementation Summary

**One-liner:** GeminiAdapter with all 6 sync methods: inlines rules/skills/agents to GEMINI.md (no symlinks, frontmatter stripped), translates MCP to settings.json mcpServers, maps permissions conservatively (never auto-enable yolo mode).

## Overview

Implemented complete Gemini CLI adapter proving adapter pattern extensibility with fundamentally different target architecture (monolithic context file vs Codex's directory-based approach). Gemini cannot use symlinks, requiring inline content transformation with YAML frontmatter stripping. All 6 sync methods implemented and verified.

## Tasks Completed

### Task 1: Add write_json_atomic utility and implement GeminiAdapter with rules, skills, agents, commands sync

**What was built:**
- Added `write_json_atomic` to `src/utils/paths.py` following tempfile + os.replace pattern from toml_writer
- Created `src/adapters/gemini.py` with GeminiAdapter registered via `@AdapterRegistry.register('gemini')`
- Implemented sync_rules: concatenates rules into GEMINI.md with HarnessSync markers, preserves user content outside markers
- Implemented sync_skills: reads SKILL.md from each skill directory, strips YAML frontmatter, inlines content with section headers
- Implemented sync_agents: parses frontmatter, extracts <role> section, inlines with descriptions
- Implemented sync_commands: creates brief bullet list summaries (not full content)
- Uses subsection markers (<!-- HarnessSync:Skills -->) for incremental syncing

**Verification:** 8 tests passed (write_json_atomic creation, import, sync_rules markers, sync_skills frontmatter stripping, sync_agents role extraction, sync_commands summaries, idempotency, user content preservation)

**Files:**
- `src/utils/paths.py`: Added write_json_atomic (60 lines)
- `src/adapters/gemini.py`: GeminiAdapter implementation (446 lines)

**Commit:** `04ac6bd`

### Task 2: Implement GeminiAdapter MCP translation and permission mapping

**What was built:**
- Implemented sync_mcp: translates Claude Code MCP server configs to Gemini settings.json mcpServers format
- Supports stdio transport: maps command/args/env/timeout directly
- Supports URL transport: uses direct URL config (url field for SSE, httpUrl for HTTP)
- Preserves environment variable references (${VAR}) as literal strings
- Merges with existing settings.json, preserving other settings
- Implemented sync_settings: maps permissions conservatively
- Deny list -> tools.blockedTools, allow list -> tools.allowedTools
- NEVER auto-enables yolo mode (security constraint)
- Logs warning when Claude Code has auto-approval mode

**Verification:** 9 tests passed (stdio MCP, URL MCP, mixed servers, existing settings preservation, env var preservation, deny list -> blockedTools, allow list -> allowedTools, auto-approval warning, MCP+settings coexistence)

**Files:**
- `src/adapters/gemini.py`: Added sync_mcp and sync_settings (118 lines)

**Commit:** `dca66cb`

## Deviations from Plan

None - plan executed exactly as written.

## Requirements Delivered

- **GMN-01**: GeminiAdapter registered and sync_rules writes rules to GEMINI.md with HarnessSync markers
- **GMN-02**: sync_skills strips YAML frontmatter and inlines content (no symlinks)
- **GMN-03**: sync_agents strips frontmatter and inlines role content
- **GMN-04**: sync_commands creates brief bullet list descriptions
- **GMN-05**: sync_mcp translates MCP servers to settings.json mcpServers format (stdio/URL transports)
- **GMN-06**: sync_settings maps permissions conservatively (never auto-enable yolo mode)

All 6 Gemini requirements complete.

## Key Implementation Details

**Inline content transformation:**
- Gemini CLI cannot follow symlinks, requiring all skills/agents to be inlined into GEMINI.md
- YAML frontmatter stripped using regex pattern matching (no PyYAML dependency)
- Skills: read SKILL.md, extract body, inline with "## Skill: {name}" headers
- Agents: extract <role> section, inline with descriptions
- Commands: summary only (brief bullet list), not full content

**Subsection markers:**
- Main managed block: `<!-- Managed by HarnessSync -->` ... `<!-- End HarnessSync managed content -->`
- Subsections: `<!-- HarnessSync:Skills -->`, `<!-- HarnessSync:Agents -->`, `<!-- HarnessSync:Commands -->`
- Allows incremental syncing (skills-only, agents-only) without losing other sections
- Preserves user content outside all markers

**MCP translation:**
- Stdio servers: map command/args/env/timeout directly
- URL servers: detect SSE vs HTTP based on URL pattern (ends with /sse or contains 'sse')
- SSE: use `url` field
- HTTP: use `httpUrl` field
- Environment variables: preserve ${VAR} references as literal strings (Gemini expands at runtime)

**Permission mapping:**
- Conservative defaults: any denied tool -> read-only mode
- Deny list takes precedence: map to blockedTools
- Allow list: map to allowedTools only if no deny list
- Auto-approval: log warning, NEVER enable yolo mode (security constraint)

**Atomic JSON writes:**
- `write_json_atomic` added to paths.py following same pattern as write_toml_atomic
- Creates temp file in same directory, writes JSON, flushes, syncs, renames atomically
- Prevents corrupted settings.json on interrupted writes

## Verification Results

**Task 1:** 8/8 tests passed
1. write_json_atomic creates valid JSON file
2. write_json_atomic importable from src.utils.paths
3. sync_rules writes to GEMINI.md with markers
4. sync_skills strips frontmatter and inlines
5. sync_agents extracts role section and inlines
6. sync_commands creates brief summaries
7. Idempotency: re-sync replaces markers without duplication
8. User content outside markers preserved

**Task 2:** 9/9 tests passed
1. sync_mcp with stdio server (command+args+env)
2. sync_mcp with URL server (SSE/HTTP detection)
3. sync_mcp with mixed server types
4. sync_mcp preserves existing settings.json
5. sync_mcp preserves env var references
6. sync_settings with deny list -> blockedTools
7. sync_settings with allow list -> allowedTools
8. sync_settings auto-approval -> warning (yolo NOT enabled)
9. sync_settings + sync_mcp coexistence in same settings.json

**Total:** 17/17 tests passed (100% pass rate)

## Artifacts

**Created files:**
- `src/adapters/gemini.py` (446 lines) - Complete GeminiAdapter with all 6 sync methods

**Modified files:**
- `src/utils/paths.py` - Added write_json_atomic utility (60 lines)

**Key exports:**
- `GeminiAdapter` class (registered as "gemini")
- `write_json_atomic` function (available to all adapters)

## Next Steps

1. **Plan 03-02**: Implement OpenCodeAdapter with similar inline content strategy
2. **Phase 4**: Main sync orchestration (tie SourceReader -> AdapterRegistry -> StateManager)
3. **Integration test**: Verify GeminiAdapter end-to-end with real .claude/ directory

## Self-Check: PASSED

Files verified:
```bash
FOUND: src/adapters/gemini.py
FOUND: src/utils/paths.py (write_json_atomic present)
```

Commits verified:
```bash
FOUND: 04ac6bd (Task 1)
FOUND: dca66cb (Task 2)
```

Verification tests:
```bash
PASSED: verify_task1_gemini.py (8/8 tests)
PASSED: verify_task2_gemini.py (9/9 tests)
```

All claims validated. Plan complete.
