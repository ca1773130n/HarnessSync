# HarnessSync Project State

## Project Reference

**Core Value:** One harness to rule them all — configure Claude Code once, sync everywhere (Codex, Gemini CLI, OpenCode) without manual duplication or format translation.

**Current Focus:** Milestone v2.0 — Plugin & MCP Scope Sync (Phase 9)

---

## Current Position

**Milestone:** v2.0
**Phase:** 9 - Plugin Discovery & Scope-Aware Source Reading
**Plan:** N/A (awaiting planning)
**Status:** Ready for planning

**Progress:**
[░░░░░░░░░░] 0%
Milestone v2.0: Plugin & MCP Scope Sync
Phase 9: Plugin Discovery & Scope-Aware Source Reading

---

## Performance Metrics

### Velocity
- **Milestones completed:** 1 (v1.0)
- **Phases completed:** 8/11
- **Plans completed:** 24 (all v1.0)
- **Average plan duration:** ~3 min
- **v1.0 complete:** 2026-02-15
- **v2.0 started:** 2026-02-15

### Quality
- **Verification passes:** 101 (82 prior + 14 sanity + 5 proxy)
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

**v2.0 deferred validations:** None planned (all phases use proxy verification)

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
13. **Env var references preserved in TOML** - ${VAR} kept literal for runtime expansion (02-01)
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

### Active Todos

v1.0:
- [x] Complete all 8 phases (Foundation → Multi-Account Support)
- [x] Archive v1.0 milestone to MILESTONES.md

v2.0:
- [ ] Plan Phase 9: Plugin Discovery & Scope-Aware Source Reading
- [ ] Plan Phase 10: Scope-Aware Target Sync & Environment Translation
- [ ] Plan Phase 11: State Enhancements & Integration

### Roadmap Evolution

- **2026-02-13:** Created v1.0 roadmap (7 phases)
- **2026-02-15:** Added Phase 8 (Multi-Account Support)
- **2026-02-15:** Completed Phase 8, archived v1.0 to MILESTONES.md
- **2026-02-15:** Created v2.0 roadmap (Phases 9-11)

### Blockers

None. v1.0 complete, v2.0 roadmap ready for planning.

### Recent Changes

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

Created v2.0 roadmap with 3 phases (9-11) covering plugin MCP discovery, scope-aware sync with env var translation, and state enhancements with drift detection.

### What's Next

Plan Phase 9: Plugin Discovery & Scope-Aware Source Reading. Extend SourceReader to discover installed plugins from installed_plugins.json and extract MCPs from plugin cache directories with ${CLAUDE_PLUGIN_ROOT} resolution. Implement 3-tier scope awareness (user/project/local) with proper precedence handling.

### Context for Next Session

v1.0 complete (8 phases, 24 plans, 101 verification checks). v2.0 roadmap created with 19 requirements mapped to 3 phases. Research complete (v2-SUMMARY.md) confirms Gemini extensions are NOT the target — plugin MCPs sync to settings.json with scope awareness. Ready to plan Phase 9.

---

*Last updated: 2026-02-15*
*Session: v2.0 roadmap creation*
*Stopped at: v2.0 roadmap complete, awaiting Phase 9 planning*
