# HarnessSync Project State

## Project Reference

**Core Value:** One harness to rule them all — configure Claude Code once, sync everywhere (Codex, Gemini CLI, OpenCode) without manual duplication or format translation.

**Current Focus:** Phase 2 - Adapter Framework & Codex Sync

---

## Current Position

**Phase:** 2
**Plan:** 03 (completed)
**Status:** Complete

**Progress:**
```
Phase 2: Adapter Framework & Codex Sync
██████████ 100% (3/3 plans complete)

Overall Project: 2/7 phases complete
```

---

## Performance Metrics

### Velocity
- **Phases completed:** 2/7 (Phase 2 complete)
- **Plans completed:** 7 (01-01, 01-02, 01-03, 01-04, 02-01, 02-02, 02-03)
- **Average plan duration:** 3.1 min
- **Estimated completion:** TBD after Phase 3

### Quality
- **Verification passes:** 13 (Logger, Hashing, Paths, StateManager, SourceReader-basic, SourceReader-edges, Phase1-Integration, AdapterFramework, TOMLWriter, CodexRulesSkills, CodexAgentsCommands, CodexMCPSettings, Phase2-Integration)
- **Verification failures:** 0
- **Pass rate:** 100%

### Scope
- **Requirements delivered:** 20/44 (CORE-01 through CORE-05, SRC-01 through SRC-06, ADP-01 through ADP-03, CDX-01 through CDX-06)
- **v1 coverage:** 45%
- **Deferred to v2:** 0

---

## Experiment Metrics

### Research Context
- **Landscape analysis:** Complete (SUMMARY.md exists with 6-phase suggestions)
- **Baseline established:** Not applicable (new plugin, no existing metrics)
- **Competing approaches:** skillshare (skills-only), dotfile managers (no AI semantics)

### Deferred Validations
No deferred validations yet. All phases use proxy or sanity verification.

**Integration Phase:** Not needed (no Level 3 deferred validations)

---

## Accumulated Context

### Key Decisions
1. **Python 3 stdlib only** - Zero dependency footprint, proven from cc2all (2026-02-13)
2. **Adapter pattern for targets** - Codex first (most complex), then Gemini/OpenCode (2026-02-13)
3. **Foundation-first approach** - Drift detection and symlink handling are architectural, not features (2026-02-13)
4. **Conservative permission mapping** - Claude "deny" → skip tool in target, never downgrade security (2026-02-13)
5. **Manual ANSI codes over colorama** - Windows Terminal supports ANSI natively, check WT_SESSION for CMD detection (01-01, 2026-02-13)
6. **16-char SHA256 truncation** - Balance collision risk vs readability in state files (01-01, 2026-02-13)
7. **3-tier symlink fallback** - Native symlink → junction (Windows dirs) → copy with marker (01-01, 2026-02-13)
8. **Audit trail in Logger** - Enable watch mode reset and debugging (01-01, 2026-02-13)
9. **Atomic write pattern for state** - Tempfile + os.replace prevents corruption on interrupted writes (01-02, 2026-02-13)
10. **Per-target state isolation** - Codex/Gemini/OpenCode tracked independently for partial sync support (01-02, 2026-02-13)
11. **Status derived from counts** - Success/partial/failed auto-calculated from sync results (01-02, 2026-02-13)
12. **Backup corrupted state** - Graceful degradation with timestamped backup instead of hard failure (01-02, 2026-02-13)
13. **Symlinks recorded as-is** - Skill directory symlinks stored as-is (not followed) to prevent duplicate discovery (01-03, 2026-02-13)
14. **Settings merge with local precedence** - user < project < project.local for Claude Code settings (01-03, 2026-02-13)
15. **Malformed config filtering** - Silently skip invalid entries (MCP without command/url, non-dict settings) for graceful degradation (01-03, 2026-02-13)
16. **Plugin manifest declares future structure** - plugin.json includes hooks/commands/mcp even though Phase 4-6 scripts don't exist yet (standard plugin pattern) (01-04, 2026-02-13)
17. **Preserve migration code during rebrand** - migrate_from_cc2all() retains intentional old path references for backwards compatibility (01-04, 2026-02-13)
18. **Integration tests use tempdir mocks** - Test against mock project instead of real ~/.claude/ for safety and CI compatibility (01-04, 2026-02-13)
19. **Manual TOML generation via f-strings** - tomllib (stdlib 3.11+) is read-only, manual generation maintains zero-dep constraint (02-01, 2026-02-13)
20. **Backslash-first escaping order** - TOML string escaping must process \ before " to prevent double-escaping (02-01, 2026-02-13)
21. **Registry validates at registration time** - AdapterRegistry checks issubclass at decorator application, not instantiation (02-01, 2026-02-13)
22. **sync_rules receives list[dict]** - Allows adapters to merge multiple rule files instead of single concatenated string (02-01, 2026-02-13)
23. **Env var references preserved in TOML** - ${VAR} syntax kept literal, target CLI expands at runtime not sync time (02-01, 2026-02-13)
24. **Simple regex frontmatter parsing** - Use regex pattern matching for YAML frontmatter instead of PyYAML to maintain zero-dependency constraint (02-02, 2026-02-13)
25. **Marker-based AGENTS.md management** - Use HTML comment markers to delineate synced content in AGENTS.md, preserving user content outside markers (02-02, 2026-02-13)
26. **Role extraction with fallback** - Extract agent instructions from <role> tags when present, use full body as fallback (02-02, 2026-02-13)
27. **Agent/command directory prefixes** - Agents sync to .agents/skills/agent-{name}/, commands to cmd-{name}/ to prevent naming conflicts (02-02, 2026-02-13)
28. **Python 3.10 TOML parser** - Minimal parse_toml_simple for Python 3.10 compatibility since tomllib requires 3.11+ (02-03, 2026-02-13)
29. **Config merge preservation** - Always read existing config.toml, merge changes, write atomically to preserve both settings and MCP sections (02-03, 2026-02-13)
30. **Conservative sandbox mapping** - ANY denied tool -> read-only sandbox mode, never auto-map to danger-full-access for security (02-03, 2026-02-13)

### Active Todos
- [x] Complete Plan 01-01: Foundation utilities (Logger, hashing, paths)
- [x] Complete Plan 01-02: State Manager with drift detection
- [x] Complete Plan 01-03: Source Reader with .claude/ discovery
- [x] Complete Plan 01-04: Integration verification and plugin manifest
- [x] Complete Plan 02-01: Adapter framework infrastructure
- [x] Complete Plan 02-02: Codex adapter implementation
- [x] Complete Plan 02-03: Codex integration and verification
- [ ] Begin Phase 3: Main sync orchestration

### Blockers
None currently.

### Recent Changes
- **2026-02-13:** Completed Plan 02-03 (Codex integration) - sync_mcp with MCP-to-TOML translation and env var preservation, sync_settings with conservative permission mapping, Python 3.10 TOML parser, 15 verification tests passed (2 tasks, 5.5min)
- **2026-02-13:** Completed Plan 02-02 (Codex adapter) - CodexAdapter with rules→AGENTS.md (marker-based), skills→symlinks, agents/commands→SKILL.md conversion, regex frontmatter parsing (2 tasks, 2.6min)
- **2026-02-13:** Completed Plan 02-01 (Adapter framework) - AdapterBase ABC with 6 sync methods, AdapterRegistry decorator-based, SyncResult dataclass, manual TOML writer with proper escaping (2 tasks, 3min)
- **2026-02-13:** Completed Plan 01-04 (Plugin manifest & integration) - plugin.json created, HarnessSync rebranding, 9-step integration test validates entire Phase 1 pipeline (2 tasks, 1.6min)
- **2026-02-13:** Completed Plan 01-03 (Source Reader) - 6 discovery methods (rules, skills, agents, commands, mcp, settings), plugin cache support, edge case handling (2 tasks, 4.3min)

---

## Session Continuity

### What Just Happened
Completed Plan 02-03 (Codex integration and verification) and finished Phase 2. Implemented sync_mcp (MCP server JSON-to-TOML translation with env var preservation and config merging) and sync_settings (conservative permission mapping: any deny -> read-only sandbox). Added Python 3.10 TOML parser (parse_toml_simple, read_toml_safe) to handle tomllib absence. All 8 Task 1 verification tests passed (MCP stdio/HTTP, env vars, settings, coexistence). 7-step Phase 2 integration test passed (7 synced, 5 adapted, 0 failed). All 9 Phase 2 requirements (ADP-01/02/03, CDX-01/02/03/04/05/06) delivered. Task committed (1f55572).

### What's Next
Begin Phase 3 (Main Sync Orchestration). Implement SyncOrchestrator to coordinate SourceReader + AdapterRegistry, add CLI commands (init, sync, status), implement dry-run mode and logging.

### Context for Next Session
Phase 2 complete with zero dependencies maintained. CodexAdapter has all 6 sync methods working end-to-end. Python 3.10+ compatible via parse_toml_simple. Ready for orchestration layer that ties SourceReader -> AdapterRegistry -> StateManager together for production CLI. Phase 3 will add user-facing commands and workflow automation.

---

*Last updated: 2026-02-13*
*Session: Plan 02-03 execution*
*Stopped at: Completed 02-03-PLAN.md*
