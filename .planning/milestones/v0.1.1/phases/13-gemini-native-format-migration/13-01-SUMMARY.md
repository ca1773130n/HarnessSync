---
phase: 13-gemini-native-format-migration
plan: 01
subsystem: adapters/gemini
tags: [gemini, native-format, skills, agents, commands, mcp]
dependency_graph:
  requires: [phase-12]
  provides: [gemini-native-skills, gemini-native-agents, gemini-native-commands, mcp-field-passthrough]
  affects: [src/adapters/gemini.py]
tech_stack:
  added: []
  patterns: [native-file-writer, toml-command-format, yaml-quoting]
key_files:
  created: []
  modified: [src/adapters/gemini.py]
decisions:
  - "Skills written as verbatim copies to .gemini/skills/<name>/SKILL.md (no transformation needed)"
  - "Agent frontmatter rebuilt from scratch with only Gemini-compatible fields (color dropped)"
  - "TOML command format uses triple-quoted multi-line strings for prompt bodies"
  - "Command namespacing via colons maps to subdirectory paths"
  - "MCP passthrough uses allowlist of 4 specific fields (trust, includeTools, excludeTools, cwd)"
  - "YAML values with unsafe characters auto-quoted via _quote_yaml_value helper"
metrics:
  duration: "3m 29s"
  completed: "2026-03-09"
---

# Phase 13 Plan 01: Gemini Native Format Migration Summary

Rewrote sync_skills, sync_agents, sync_commands, and _write_mcp_to_settings to write native Gemini CLI discovery files instead of inlining content into GEMINI.md, enabling lazy-loading, tool integration, and proper slash commands.

## Tasks Completed

| Task | Name | Commit | Status |
|------|------|--------|--------|
| 1 | Rewrite sync_skills and sync_agents to write native files | 4fbf7dd | Done |
| 2 | Rewrite sync_commands to TOML and add MCP field passthrough | 44055fe | Done |

## Changes Made

### sync_skills (GMN-07)
- Writes SKILL.md verbatim to `.gemini/skills/<name>/SKILL.md`
- Validates `name` and `description` frontmatter exist before writing (skips if missing)
- Returns SyncResult with individual file paths instead of GEMINI.md reference
- No longer calls `_write_subsection("Skills", ...)`

### sync_agents (GMN-08)
- Writes `.gemini/agents/<name>.md` with Gemini-compatible frontmatter
- Rebuilds frontmatter: passes through `name`, `description`, `tools`, `model`, `max_turns`
- Drops `color` field (Gemini-incompatible)
- `tools` parsed from comma-separated or block scalar format into YAML list
- Body extracted from `<role>` tags (stripped), falls back to full body
- Added `_quote_yaml_value()` helper for YAML-unsafe character quoting

### sync_commands (GMN-09)
- Writes `.gemini/commands/<name>.toml` with `description` and `prompt` fields
- Maps `$ARGUMENTS` to `{{args}}` in prompt body
- Namespaced commands (colons) create subdirectory paths (e.g., `harness:setup` -> `harness/setup.toml`)
- Added `_format_command_toml()` helper with TOML escaping (handles `"""` in prompt body)

### _write_mcp_to_settings (GMN-11)
- Added passthrough for `trust`, `includeTools`, `excludeTools`, `cwd` fields
- Fields only included when present in source config (backward compatible)
- Works for both stdio and URL transport servers

## Verification Results

### Level 1 (Sanity)
- Import check: `from src.adapters.gemini import GeminiAdapter` -- PASS
- Native file existence at expected paths -- PASS
- Frontmatter contains required name/description fields -- PASS
- TOML command files have description and prompt fields -- PASS
- MCP settings.json contains new passthrough fields -- PASS

### Level 2 (Proxy)
- Full `sync_all` with mock skills, agents, commands, MCP, rules, settings -- PASS
- All native files created at correct paths with correct content -- PASS
- GEMINI.md contains rules ONLY (no inlined skills/agents/commands markers) -- PASS
- settings.json contains trust/includeTools/excludeTools/cwd -- PASS
- SyncResult counts correct for all content types -- PASS
- Existing Phase 12 integration tests (14 tests) -- PASS

## Deviations from Plan

None - plan executed exactly as written.

## Decisions Made

1. **Skill content is verbatim copied** -- Since Claude Code and Gemini use identical SKILL.md frontmatter schemas (name + description), no transformation is needed. The entire file is copied as-is.

2. **Agent frontmatter rebuilt from scratch** -- Rather than filtering fields from source, the agent frontmatter is built additively: always include name/description, then optionally add tools/model/max_turns. This prevents unknown fields from leaking through.

3. **YAML list handling for tools** -- The `tools` field can arrive as comma-separated string ("eslint, ruff") or block scalar. Both formats are parsed into a proper YAML list in the output.

4. **TOML triple-quote escaping** -- If prompt body contains `"""`, one quote is escaped to `"\"` to prevent premature termination of the TOML multi-line string.

5. **MCP passthrough uses explicit allowlist** -- Only four specific fields are passed through rather than a blanket "pass all unknown fields" approach, to prevent accidental leakage of Claude Code-specific fields.

## Self-Check: PASSED
