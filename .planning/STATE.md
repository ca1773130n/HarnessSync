# HarnessSync Project State

## Project Reference

**Core Value:** One harness to rule them all -- configure Claude Code once, sync everywhere (Codex, Gemini CLI, OpenCode) without manual duplication or format translation.

**Current Focus:** v0.1.1 -- Target CLI Modernization

---

## Current Position

**Milestone:** v0.1.1
**Phase:** 12 - Critical Fixes & Rules Discovery
**Plan:** 02 of 03 complete
**Status:** Executing phase 12 plans

**Progress:**
[░░░░░░░░░░] 0%
v0.0.1: Complete (8 phases) | v0.0.2: Complete (3 phases) | v0.1.1: 0/3 phases

---

## Performance Metrics

### Velocity
- **Milestones completed:** 2 (v0.0.1, v0.0.2)
- **Phases completed:** 11/14
- **Plans completed:** 33 (24 v0.0.1 + 7 v0.0.2 + 2 v0.1.1)
- **Average plan duration:** ~2.5 min
- **v0.0.1 complete:** 2026-02-15
- **v0.0.2 complete:** 2026-02-15

### Quality
- **Verification passes:** 193+
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
- **12-02:** Added get_rules_files() as new method (not modifying get_rules() return type) for backward compatibility
- **12-02:** Regex-based frontmatter parsing instead of PyYAML dependency; support both paths: and globs: keys

### v0.1.1 Research Findings
- **Claude Code:** New `.claude/rules/` directory with YAML frontmatter path-scoping (HIGH priority gap)
- **Codex CLI v0.112.0:** `on-failure` approval policy deprecated (use `on-request`); config filename is `config.toml` not `codex.toml`
- **Gemini CLI v0.32.0:** settings.json migrated from `allowedTools`/`blockedTools` to `tools.allowed`/`tools.exclude`; native skills/agents/commands support added
- **OpenCode v1.2.22:** Permission system rewritten from `permissions.mode` to granular `permission` with per-tool `allow`/`ask`/`deny`; env var syntax is `{env:VAR}` not `${VAR}`; natively reads `.claude/skills/`

### Blockers
None.

### Recent Changes
- **2026-03-09:** Phase 12 Plan 02 complete -- rules directory discovery added to SourceReader
- **2026-03-09:** Phase 12 Plan 01 complete -- Codex/Gemini/OpenCode adapter fixes
- **2026-03-09:** v0.1.1 requirements defined from CLI research
- **2026-03-09:** v0.1.1 roadmap created (3 phases, 19 requirements)
- **2026-02-15:** v0.0.2 milestone complete

---

## Session Continuity

### What Just Happened
Completed Phase 12 Plan 02 -- added rules directory discovery to SourceReader with YAML frontmatter parsing and orchestrator integration.

### What's Next
Execute Phase 12 Plan 03 (remaining phase 12 work).

### Context for Next Session
Phase 12 Plans 01-02 complete. SourceReader now discovers .claude/rules/ directories recursively with frontmatter path-scoping. Orchestrator merges rules files into adapter data flow. All adapter fixes (Codex, Gemini, OpenCode) applied in Plan 01.

---

*Last updated: 2026-03-09*
*Session: Phase 12 Plan 02 execution*
*Stopped at: Completed 12-02-PLAN.md*
