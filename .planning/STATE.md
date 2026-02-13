# HarnessSync Project State

## Project Reference

**Core Value:** One harness to rule them all — configure Claude Code once, sync everywhere (Codex, Gemini CLI, OpenCode) without manual duplication or format translation.

**Current Focus:** Phase 3 - Gemini & OpenCode Adapters

---

## Current Position

**Phase:** 3
**Plan:** 01 (completed)
**Status:** In Progress

**Progress:**
```
Phase 3: Gemini & OpenCode Adapters
███░░░░░░░ 33% (1/3 plans complete)

Overall Project: 2/7 phases complete
```

---

## Performance Metrics

### Velocity
- **Phases completed:** 2/7 (Phase 2 complete)
- **Plans completed:** 8 (01-01, 01-02, 01-03, 01-04, 02-01, 02-02, 02-03, 03-01)
- **Average plan duration:** 3.2 min
- **Estimated completion:** TBD after Phase 3

### Quality
- **Verification passes:** 15 (Logger, Hashing, Paths, StateManager, SourceReader-basic, SourceReader-edges, Phase1-Integration, AdapterFramework, TOMLWriter, CodexRulesSkills, CodexAgentsCommands, CodexMCPSettings, Phase2-Integration, GeminiTask1, GeminiTask2)
- **Verification failures:** 0
- **Pass rate:** 100%

### Scope
- **Requirements delivered:** 26/44 (CORE-01 through CORE-05, SRC-01 through SRC-06, ADP-01 through ADP-03, CDX-01 through CDX-06, GMN-01 through GMN-06)
- **v1 coverage:** 59%
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
31. **Subsection markers for incremental syncing** - Use subsection markers (<!-- HarnessSync:Skills -->) within main managed block to allow incremental syncing without losing other sections (03-01, 2026-02-13)
32. **Direct URL config for MCP** - Start with direct URL config (url/httpUrl fields) instead of npx mcp-remote wrapper for simplicity (03-01, 2026-02-13)
33. **Never auto-enable yolo mode** - Conservative security default: even if Claude Code has auto-approval, Gemini yolo mode stays disabled, log warning instead (03-01, 2026-02-13)

### Active Todos
- [x] Complete Plan 01-01: Foundation utilities (Logger, hashing, paths)
- [x] Complete Plan 01-02: State Manager with drift detection
- [x] Complete Plan 01-03: Source Reader with .claude/ discovery
- [x] Complete Plan 01-04: Integration verification and plugin manifest
- [x] Complete Plan 02-01: Adapter framework infrastructure
- [x] Complete Plan 02-02: Codex adapter implementation
- [x] Complete Plan 02-03: Codex integration and verification
- [x] Complete Plan 03-01: Gemini adapter implementation
- [ ] Complete Plan 03-02: OpenCode adapter implementation
- [ ] Complete Plan 03-03: Phase 3 integration verification

### Blockers
None currently.

### Recent Changes
- **2026-02-13:** Completed Plan 03-01 (Gemini adapter) - GeminiAdapter with all 6 sync methods, inline content (no symlinks), YAML frontmatter stripping, MCP-to-JSON translation, conservative permission mapping (never auto-enable yolo), 17 verification tests passed (2 tasks, 4.1min)
- **2026-02-13:** Completed Plan 02-03 (Codex integration) - sync_mcp with MCP-to-TOML translation and env var preservation, sync_settings with conservative permission mapping, Python 3.10 TOML parser, 15 verification tests passed (2 tasks, 5.5min)
- **2026-02-13:** Completed Plan 02-02 (Codex adapter) - CodexAdapter with rules→AGENTS.md (marker-based), skills→symlinks, agents/commands→SKILL.md conversion, regex frontmatter parsing (2 tasks, 2.6min)
- **2026-02-13:** Completed Plan 02-01 (Adapter framework) - AdapterBase ABC with 6 sync methods, AdapterRegistry decorator-based, SyncResult dataclass, manual TOML writer with proper escaping (2 tasks, 3min)
- **2026-02-13:** Completed Plan 01-04 (Plugin manifest & integration) - plugin.json created, HarnessSync rebranding, 9-step integration test validates entire Phase 1 pipeline (2 tasks, 1.6min)

---

## Session Continuity

### What Just Happened
Completed Plan 03-01 (Gemini adapter implementation). Implemented GeminiAdapter with all 6 sync methods: sync_rules (concatenate to GEMINI.md with markers), sync_skills (inline content, strip frontmatter, no symlinks), sync_agents (extract role section, inline), sync_commands (brief bullet list), sync_mcp (translate to settings.json mcpServers with stdio/URL support), sync_settings (conservative permission mapping, never auto-enable yolo mode). Added write_json_atomic utility to paths.py (tempfile + os.replace pattern). All 17 verification tests passed (8 Task 1, 9 Task 2). All 6 Gemini requirements (GMN-01 through GMN-06) delivered. Tasks committed (04ac6bd, dca66cb).

### What's Next
Continue Phase 3 with Plan 03-02: Implement OpenCodeAdapter with similar inline content strategy. Then Plan 03-03 for integration verification.

### Context for Next Session
Phase 3 started (1/3 plans complete). GeminiAdapter proves adapter pattern extensibility with fundamentally different architecture (monolithic GEMINI.md vs Codex's directory-based approach). Inline content transformation working (YAML frontmatter stripping via regex). JSON atomic writes available for all adapters. Conservative security defaults established (never auto-enable yolo mode). Ready for OpenCodeAdapter implementation following similar patterns.

---

*Last updated: 2026-02-13*
*Session: Plan 03-01 execution*
*Stopped at: Completed 03-01-PLAN.md*
