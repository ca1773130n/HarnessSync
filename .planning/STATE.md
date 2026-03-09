# HarnessSync Project State

## Project Reference

**Core Value:** One harness to rule them all -- configure Claude Code once, sync everywhere (Codex, Gemini CLI, OpenCode) without manual duplication or format translation.

**Current Focus:** v0.1.1 -- Target CLI Modernization

---

## Current Position

**Milestone:** v0.1.1
**Phase:** 12 - Critical Fixes & Rules Discovery
**Plan:** Not started
**Status:** Roadmap created, awaiting phase planning

**Progress:**
[░░░░░░░░░░] 0%
v0.0.1: Complete (8 phases) | v0.0.2: Complete (3 phases) | v0.1.1: 0/3 phases

---

## Performance Metrics

### Velocity
- **Milestones completed:** 2 (v0.0.1, v0.0.2)
- **Phases completed:** 11/14
- **Plans completed:** 31 (24 v0.0.1 + 7 v0.0.2)
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

### v0.1.1 Research Findings
- **Claude Code:** New `.claude/rules/` directory with YAML frontmatter path-scoping (HIGH priority gap)
- **Codex CLI v0.112.0:** `on-failure` approval policy deprecated (use `on-request`); config filename is `config.toml` not `codex.toml`
- **Gemini CLI v0.32.0:** settings.json migrated from `allowedTools`/`blockedTools` to `tools.allowed`/`tools.exclude`; native skills/agents/commands support added
- **OpenCode v1.2.22:** Permission system rewritten from `permissions.mode` to granular `permission` with per-tool `allow`/`ask`/`deny`; env var syntax is `{env:VAR}` not `${VAR}`; natively reads `.claude/skills/`

### Blockers
None.

### Recent Changes
- **2026-03-09:** v0.1.1 requirements defined from CLI research
- **2026-03-09:** v0.1.1 roadmap created (3 phases, 19 requirements)
- **2026-02-15:** v0.0.2 milestone complete

---

## Session Continuity

### What Just Happened
Created v0.1.1 roadmap with 3 phases (12-14). Phase 12 handles critical fixes (broken Codex/Gemini/OpenCode settings formats) and new rules directory discovery. Phase 13 migrates Gemini to native file formats. Phase 14 polishes remaining cross-adapter issues.

### What's Next
Plan and execute Phase 12 with `/grd:plan-phase 12`.

### Context for Next Session
v0.1.1 milestone roadmap is ready. 19 requirements mapped across 3 phases. Research completed for all 4 target CLIs. Phase 12 is the critical path -- it fixes actively broken functionality and adds upstream rules discovery that Phase 13/14 can leverage.

---

*Last updated: 2026-03-09*
*Session: v0.1.1 roadmap creation*
*Stopped at: Roadmap created, awaiting phase 12 planning*
