# HarnessSync Project State

## Project Reference

**Core Value:** One harness to rule them all -- configure Claude Code once, sync everywhere (Codex, Gemini CLI, OpenCode) without manual duplication or format translation.

**Current Focus:** v0.1.1 -- Target CLI Modernization

---

## Current Position

**Milestone:** v0.1.1
**Phase:** 14 - Cross-Adapter Polish
**Plan:** 02 of 02 complete
**Status:** Phase complete

**Progress:**
[██████████] 100%
v0.0.1: Complete (8 phases) | v0.0.2: Complete (3 phases) | v0.1.1: 3/3 phases complete (12, 13, 14)

---

## Performance Metrics

### Velocity
- **Milestones completed:** 2 (v0.0.1, v0.0.2)
- **Phases completed:** 13/14
- **Plans completed:** 37 (24 v0.0.1 + 7 v0.0.2 + 6 v0.1.1)
- **Average plan duration:** ~2.5 min
- **v0.0.1 complete:** 2026-02-15
- **v0.0.2 complete:** 2026-02-15

### Quality
- **Verification passes:** 273+
- **Verification failures:** 0
- **Pass rate:** 100%

### Scope
- **v0.0.1 coverage:** 100% (57 requirements delivered)
- **v0.0.2 coverage:** 100% (19 requirements delivered)
- **v0.1.1 coverage:** 0/19 requirements (in progress)
- **Total requirements:** 76 delivered, 19 pending

---

## Deferred Validations

**v0.0.1 deferred validations (27 total):**
See MILESTONES.md for full list. Key items:
- Real CLI loading (Codex, Gemini, OpenCode)
- Live plugin integration (hooks/commands/MCP)
- Cross-platform (Windows, Linux)
- Production scale testing

**v0.0.2 deferred validations (8 total):**
- DEFER-09-01/02: Real plugin MCP discovery, scope-aware sync
- DEFER-10-01/02/03: Real CLI config loading, full pipeline
- DEFER-11-01/02/03: Real plugin update detection, multi-account isolation, full v0.0.2 pipeline

**v0.1.1 deferred validations:**
None yet (all phases use proxy verification).

---

## Accumulated Context

### Key Decisions
42 decisions documented across v0.0.1 (31) and v0.0.2 (11). See MILESTONES.md archives.
- **12-01:** OpenCode uses per-tool permission (singular) with allow/ask/deny and bash wildcard patterns
- **12-01:** Old permissions (plural) key deleted when writing new permission format to prevent ambiguity
- **12-02:** Added get_rules_files() as new method (not modifying get_rules() return type) for backward compatibility
- **12-02:** Regex-based frontmatter parsing instead of PyYAML dependency; support both paths: and globs: keys
- **12-03:** Dead code cc2all_sync.py not fixed for deprecated patterns (already documented as dead code)
- **12-03:** Orphan codex.toml at project root left in place (may contain user customizations)
- **13-01:** Skills written as verbatim copies to .gemini/skills/<name>/SKILL.md (identical schema)
- **13-01:** Agent frontmatter rebuilt additively (name, description, then optional tools/model/max_turns)
- **13-01:** TOML command format with triple-quoted multi-line strings for prompts
- **13-01:** MCP passthrough uses explicit allowlist of 4 fields (trust, includeTools, excludeTools, cwd)
- **13-02:** Cleanup gated on zero failures across all three native syncs (safety constraint)
- **13-02:** sync_all override calls cleanup automatically; _write_subsection retained as legacy
- **14-01:** cwd field added after args array in TOML output order; reused VAR_PATTERN for header translation; translation only in sync_mcp() remote branch
- **14-02:** Raw text preservation for non-managed TOML sections; is_relative_to() for skill path ancestry check; claude_skills_dir computed once outside loop

### v0.1.1 Research Findings
- **Claude Code:** New `.claude/rules/` directory with YAML frontmatter path-scoping (HIGH priority gap)
- **Codex CLI v0.112.0:** `on-failure` approval policy deprecated (use `on-request`); config filename is `config.toml` not `codex.toml`
- **Gemini CLI v0.32.0:** settings.json migrated from `allowedTools`/`blockedTools` to `tools.allowed`/`tools.exclude`; native skills/agents/commands support added
- **OpenCode v1.2.22:** Permission system rewritten from `permissions.mode` to granular `permission` with per-tool `allow`/`ask`/`deny`; env var syntax is `{env:VAR}` not `${VAR}`; natively reads `.claude/skills/`

### Blockers
None.

### Recent Changes
- **2026-03-09:** Phase 14 complete -- all 2 plans executed (CDX-09, OC-10, OC-11, PRES-01)
- **2026-03-09:** Phase 14 Plan 02 complete -- OpenCode skill dedup (OC-11) + Codex/Gemini config preservation (PRES-01)
- **2026-03-09:** Phase 14 Plan 01 complete -- cwd TOML passthrough (CDX-09) + OpenCode header env var translation (OC-10)
- **2026-03-09:** Phase 13 complete -- native format migration + stale subsection cleanup + 66-check verification
- **2026-03-09:** Phase 13 Plan 02 complete -- stale GEMINI.md cleanup + end-to-end verification (66 checks)
- **2026-03-09:** Phase 13 Plan 01 complete -- Gemini native format migration (skills, agents, commands, MCP fields)
- **2026-03-09:** Phase 12 complete -- all 3 plans executed, 14 integration tests pass, zero deprecated patterns
- **2026-03-09:** Phase 12 Plan 02 complete -- rules directory discovery added to SourceReader
- **2026-03-09:** Phase 12 Plan 01 complete -- Codex/Gemini/OpenCode adapter fixes
- **2026-03-09:** v0.1.1 requirements defined from CLI research
- **2026-03-09:** v0.1.1 roadmap created (3 phases, 19 requirements)
- **2026-02-15:** v0.0.2 milestone complete

---

## Session Continuity

### What Just Happened
Completed Phase 14 Plan 02 -- OpenCode skill dedup (OC-11) and Codex/Gemini config preservation (PRES-01). Phase 14 is now complete.

### What's Next
v0.1.1 milestone is complete. All 3 phases (12, 13, 14) executed with 6 plans total. Ready for milestone wrap-up or next milestone planning.

### Context for Next Session
Phase 14 complete. OpenCode sync_skills() now skips skills under .claude/skills/ (natively discovered). Codex _extract_unmanaged_toml() preserves [agents], [profiles], [features] sections through config.toml writes. Both _write_mcp_to_path() and sync_settings() pass preserved_sections. Gemini preservation confirmed by test (JSON dict-merge already works). tests/verify_phase14_preservation.py covers all three adapters.

---

*Last updated: 2026-03-09*
*Session: Phase 14 Plan 02 execution*
*Stopped at: Completed 14-02-PLAN.md*
