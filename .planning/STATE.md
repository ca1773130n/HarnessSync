# HarnessSync Project State

## Project Reference

**Core Value:** One harness to rule them all — configure Claude Code once, sync everywhere (Codex, Gemini CLI, OpenCode) without manual duplication or format translation.

**Current Focus:** Milestone v2.0 — Plugin & MCP Scope Sync (Phase 11)

---

## Current Position

**Milestone:** v2.0
**Phase:** 11 - State Enhancements & Integration
**Plan:** 02 - Drift Detection Integration
**Status:** In Progress

**Progress:**
[████████░░] 80%
Milestone v2.0: Plugin & MCP Scope Sync
Phase 9: Complete | Phase 10: Complete | Phase 11: In Progress (2/3 plans)

---

## Performance Metrics

### Velocity
- **Milestones completed:** 1 (v1.0)
- **Phases completed:** 10/11
- **Plans completed:** 31 (24 v1.0 + 7 v2.0)
- **Average plan duration:** ~2.5 min
- **v1.0 complete:** 2026-02-15
- **v2.0 started:** 2026-02-15

### Quality
- **Verification passes:** 193 (113 prior + 12 sanity + 30 integration + 9 proxy + 29 integration)
- **Verification failures:** 0
- **Pass rate:** 100%

### Scope
- **v1.0 coverage:** 100% (47 requirements delivered)
- **v1.1 coverage:** 100% (10 multi-account requirements)
- **v2.0 coverage:** 100% (19 requirements mapped to phases 9-11)
- **Deferred to v3:** 0

---

## Experiment Metrics

### Research Context
- **v1.0 research:** Complete (SUMMARY.md with 7-phase suggestions)
- **v2.0 research:** Complete (v2-SUMMARY.md with plugin/scope findings)
- **Baseline established:** Not applicable (new plugin, no existing metrics)
- **Competing approaches:** skillshare (skills-only), dotfile managers (no AI semantics)

### Key v2.0 Research Findings
1. **Gemini extensions ≠ Claude plugins** — DO NOT generate extensions, use settings.json
2. **Claude has 3-tier MCP scoping** — user/project/local with precedence
3. **Plugin MCPs in cache dirs** — with ${CLAUDE_PLUGIN_ROOT} variable expansion needed
4. **Codex: MCP only, no plugins** — TOML format, env var literal maps
5. **Scope precedence:** local > project > user (v1.0 flattened incorrectly)

### Deferred Validations

**v1.0 deferred validations (27 total):**

Phase 3 (DEFER-03-01 through DEFER-03-04):
- Real Gemini CLI skill activation (requires Gemini CLI installed)
- Real OpenCode symlink loading (requires OpenCode installed)
- MCP server connection (requires MCP infrastructure)
- Permission security audit (requires security expert review)

Phase 4 (DEFER-04-01 through DEFER-04-05):
- Hook fires in live Claude Code session (requires plugin installed)
- Concurrent hook invocations handle lock correctly (requires rapid edits)
- Cross-platform locking on Windows (requires Windows environment)
- Hook timeout tuning (requires production-scale config)
- /sync command integration in live session (requires plugin installed)

Phase 5 (DEFER-05-03 through DEFER-05-04):
- Secret detection on production .env files (requires sanitized test data)
- Entropy-based detection (deferred per research - start with keyword+regex)

Phase 6 (DEFER-06-01 through DEFER-06-03):
- Claude Code MCP client integration (requires plugin installed)
- External agent cross-CLI invocation (requires MCP client library)
- Production load testing (requires sustained testing environment)

Phase 7 (DEFER-07-01 through DEFER-07-06):
- `claude plugin validate .` passes (requires Claude Code CLI)
- GitHub installation via `/plugin install github:username/HarnessSync` (requires published repo)
- Marketplace URL installation (requires hosted marketplace.json)
- Linux cross-platform install.sh (requires GitHub Actions run)
- Windows cross-platform install.sh (requires Windows environment)
- Live plugin integration (hooks/commands/MCP in live session)

Phase 8 (DEFER-08-01 through DEFER-08-05):
- Interactive wizard UX with TTY (requires manual testing)
- Production home directory discovery (1M+ files) (requires beta testing)
- Windows multi-account path handling (requires Windows environment)
- Concurrent multi-account sync (requires live usage)
- Live /sync --account in Claude Code session (requires integration testing)

**v2.0 deferred validations:**

Phase 9 (DEFER-09-01, DEFER-09-02):
- Real plugin MCP discovery and sync (requires real Claude Code plugins + Phase 10)
- Scope-aware sync to target-level configs (requires Phase 10 adapters)

Phase 10 (DEFER-10-01 through DEFER-10-03):
- Real Codex CLI loads generated config.toml (requires Codex installation)
- Real Gemini CLI loads generated settings.json (requires Gemini installation)
- Full v2.0 pipeline with real plugins, scopes, and MCP invocation (requires full environment)

---

## Accumulated Context

### Key Decisions (v1.0)

1. **Python 3 stdlib only** - Zero dependency footprint, proven from cc2all (2026-02-13)
2. **Adapter pattern for targets** - Codex first (most complex), then Gemini/OpenCode (2026-02-13)
3. **Foundation-first approach** - Drift detection and symlink handling are architectural, not features (2026-02-13)
4. **Conservative permission mapping** - Claude "deny" → skip tool in target, never downgrade security (2026-02-13)
5. **Manual ANSI codes over colorama** - Windows Terminal supports ANSI natively (01-01)
6. **16-char SHA256 truncation** - Balance collision risk vs readability (01-01)
7. **3-tier symlink fallback** - Native → junction (Windows) → copy with marker (01-01)
8. **Atomic write pattern for state** - Tempfile + os.replace prevents corruption (01-02)
9. **Per-target state isolation** - Codex/Gemini/OpenCode tracked independently (01-02)
10. **Symlinks recorded as-is** - Prevent duplicate discovery (01-03)
11. **Settings merge with local precedence** - user < project < project.local (01-03)
12. **Manual TOML generation via f-strings** - tomllib is read-only (02-01)
13. **Env var translation for Codex** - v2.0 translates ${VAR} to literal env map (was preserve in v1.0) (10-01)
14. **Marker-based AGENTS.md management** - HTML comment markers preserve user content (02-02)
15. **Config merge preservation** - Read existing, merge, write atomically (02-03)
16. **Conservative sandbox mapping** - ANY denied tool → read-only mode (02-03)
17. **Never auto-enable yolo mode** - Conservative security default for Gemini (03-01)
18. **Type-discriminated MCP format** - OpenCode uses type: local/remote (03-02)
19. **Deferred imports in hook** - Fast path for non-config edits (04-03)
20. **Hook always exits 0** - Never blocks Claude Code tool execution (04-03)
21. **hmac.compare_digest for hashes** - Prevent timing attacks (05-02)
22. **Keyword+regex secret detection** - 15-20% FP rate, not entropy-based 60% FP (05-02)
23. **Secret detection blocks by default** - Explicit --allow-secrets override (05-03)
24. **Logging to stderr only** - stdout is JSON-RPC channel (06-01)
25. **Manual validators over jsonschema** - stdlib constraint (06-01)
26. **Queue maxsize=1** - Prevents unbounded memory (06-02)
27. **marketplace.json uses GitHub source** - ref: main for stability (07-01)
28. **Account name must start with alphanumeric** - Prevent filesystem issues (08-01)
29. **Discovery excludes 20+ patterns** - Avoid scanning Downloads/Documents (08-01)
30. **v1 state migration wraps in "default"** - Preserves all data (08-02)
31. **Default target paths: ~/.{cli}-{account}** - Only ~/.{cli} for "default" (08-03)

### Key Decisions (v2.0)

32. **Gemini extensions not the target** - Plugin MCPs sync to settings.json, NOT extensions (2026-02-15)
33. **3-tier scope precedence** - local > project > user (v1.0 flattened incorrectly) (2026-02-15)
34. **Plugin MCPs are user-scope** - Always sync to user-level target configs (2026-02-15)
35. **Disabled plugin filtering** - Only plugins with enabledPlugins[key]==False are skipped; unmentioned plugins treated as enabled (09-01)
36. **User-scope MCPs from ~/.claude.json** - v2.0 reads from ~/.claude.json top-level mcpServers, replacing v1.0's ~/.mcp.json (09-02)
37. **Existing env entries win on conflict** - User-specified env values take priority over extracted vars in Codex translation (10-01)
38. **Uppercase-only env var pattern** - VAR_PATTERN matches [A-Z_][A-Z0-9_]* only per shell convention (10-01)
39. **sync_mcp_scoped() with fallback** - New method in base class, falls back to sync_mcp() for backward compat (10-02)
40. **Plugin metadata replacement semantics** - record_plugin_sync() replaces entire plugins section to prevent stale accumulation (11-01)
41. **Drift priority: version > MCP count** - Version changes take priority when both version and MCP count change (11-01)
42. **Decoupled drift detection** - detect_plugin_drift() accepts current_plugins dict instead of calling SourceReader (11-01)

### Active Todos

v1.0:
- [x] Complete all 8 phases (Foundation → Multi-Account Support)
- [x] Archive v1.0 milestone to MILESTONES.md

v2.0:
- [x] Execute Phase 9: Plugin Discovery & Scope-Aware Source Reading
- [x] Execute Phase 10: Scope-Aware Target Sync & Environment Translation
- [x] Execute Phase 11 Plan 01: Plugin Tracking & Drift Detection
- [x] Execute Phase 11 Plan 02: Drift Detection Integration
- [ ] Execute Phase 11 Plan 03: End-to-End Pipeline Validation

### Roadmap Evolution

- **2026-02-13:** Created v1.0 roadmap (7 phases)
- **2026-02-15:** Added Phase 8 (Multi-Account Support)
- **2026-02-15:** Completed Phase 8, archived v1.0 to MILESTONES.md
- **2026-02-15:** Created v2.0 roadmap (Phases 9-11)
- **2026-02-15:** Completed Phase 9 (2 plans, 12 verification checks)
- **2026-02-15:** Completed Phase 10 (3 plans, 42 verification checks)

### Blockers

None. Phase 10 complete, ready for Phase 11 planning.

### Recent Changes

- **2026-02-15:** Phase 11 Plan 02 complete — drift detection integration & full v2.0 pipeline tests (2 tasks, 29 checks)
- **2026-02-15:** Phase 11 Plan 01 complete — plugin tracking & drift detection (2 tasks, 9 checks)
- **2026-02-15:** Phase 10 complete — scope-aware adapters + env translation + transport detection (3 plans, 42 checks)
- **2026-02-15:** Phase 9 complete — plugin MCP discovery + scope-aware reading (2 plans, 12 checks)
- **2026-02-15:** v2.0 roadmap created with 3 phases (9-11) mapping all 19 v2.0 requirements
- **2026-02-15:** Completed Phase 8 (Multi-Account Support) - AccountManager + discovery, StateManager v2 migration, SetupWizard, account-aware orchestrator
- **2026-02-15:** Completed Phase 7 (Packaging & Distribution) - .claude-plugin/ structure, marketplace.json, install.sh, CI workflow
- **2026-02-15:** Completed Phase 6 (MCP Server Integration) - 6 new files in src/mcp/ (658 lines), 14 verification tests
- **2026-02-14:** Completed Phase 5 (Safety & Validation) - BackupManager, ConflictDetector, SecretDetector, CompatibilityReporter
- **2026-02-14:** Completed Phase 4 (Plugin Interface) - SyncOrchestrator, /sync + /sync-status, PostToolUse hook
- **2026-02-13:** Completed Phases 1-3 (Foundation, Codex adapter, Gemini/OpenCode adapters)

---

## Session Continuity

### What Just Happened

Executed Phase 11 Plan 02 (Drift Detection Integration). Enhanced /sync-status to display MCP servers grouped by source (user/project/local/plugin) with plugin@version labels and drift warnings. Created comprehensive integration test suite with 24 checks covering all Phase 11 success criteria and full v2.0 pipeline validation (3 plugins + 2 user + 1 project + 1 local MCPs). All verification checks passed (5 helper functions + 24 integration tests).

### What's Next

Execute Phase 11 Plan 03: End-to-End Pipeline Validation. Create final integration test with real file system paths, verify complete v2.0 feature set, test edge cases (disabled plugins, missing metadata, concurrent syncs).

### Context for Next Session

v1.0 complete (8 phases, 24 plans). Phase 9 complete (2 plans, 12 checks). Phase 10 complete (3 plans, 42 checks). Phase 11 Plans 01-02 complete (38 checks total). /sync-status now displays MCP source grouping and plugin drift warnings. Integration tests validate: plugin update simulation (1.0.0 -> 1.1.0), drift detection cycle, full pipeline with 8 MCPs, account-scoped plugin tracking. Plan 03 will complete Phase 11 and v2.0 milestone.

---

*Last updated: 2026-02-15*
*Session: Phase 11 Plan 02 execution*
*Stopped at: Phase 11 Plan 02 complete (Drift Detection Integration)*
