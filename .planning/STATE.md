# HarnessSync Project State

## Project Reference

**Core Value:** One harness to rule them all — configure Claude Code once, sync everywhere (Codex, Gemini CLI, OpenCode) without manual duplication or format translation.

**Current Focus:** Phase 4 - Plugin Interface (Complete)

---

## Current Position

**Phase:** 5
**Plan:** 03 (completed)
**Status:** In Progress

**Progress:**
[██████████] 100%
Phase 5: Safety Validation
██████████ 100% (3/3 plans complete)

Overall Project: 4/7 phases complete (Phase 5 in progress)
```

---

## Performance Metrics

### Velocity
- **Phases completed:** 4/7 (Phase 5 in progress)
- **Plans completed:** 14 (01-01, 01-02, 01-03, 01-04, 02-01, 02-02, 02-03, 03-01, 03-02, 04-01, 04-02, 04-03, 05-01, 05-02, 05-03)
- **Average plan duration:** ~3.5 min
- **Estimated completion:** TBD

### Quality
- **Verification passes:** 41 (31 prior + 10 from 05-03: 5 sanity + 5 proxy)
- **Verification failures:** 0
- **Pass rate:** 100%

### Scope
- **Requirements delivered:** 42/44 (CORE-01 through CORE-05, SRC-01 through SRC-06, ADP-01 through ADP-03, CDX-01 through CDX-06, GMN-01 through GMN-06, OC-01 through OC-06, PLG-01 through PLG-06, SAF-01 through SAF-04)
- **v1 coverage:** 95%
- **Deferred to v2:** 0

---

## Experiment Metrics

### Research Context
- **Landscape analysis:** Complete (SUMMARY.md exists with 6-phase suggestions)
- **Baseline established:** Not applicable (new plugin, no existing metrics)
- **Competing approaches:** skillshare (skills-only), dotfile managers (no AI semantics)

### Deferred Validations
Phase 3 deferred validations (DEFER-03-01 through DEFER-03-04):
- Real Gemini CLI skill activation (requires Gemini CLI installed)
- Real OpenCode symlink loading (requires OpenCode installed)
- MCP server connection (requires MCP infrastructure)
- Permission security audit (requires security expert review)

Phase 4 deferred validations (DEFER-04-01 through DEFER-04-05):
- Hook fires in live Claude Code session (requires plugin installed)
- Concurrent hook invocations handle lock correctly (requires rapid edits)
- Cross-platform locking on Windows (requires Windows environment)
- Hook timeout tuning (requires production-scale config)
- /sync command integration in live session (requires plugin installed)

Phase 5 deferred validations (DEFER-05-03 through DEFER-05-04):
- Secret detection on production .env files (requires sanitized test data)
- Entropy-based detection (deferred per research - start with keyword+regex)

**Integration Phase:** May need for Level 3 deferred validations from Phase 3/4/5

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
34. **Type-discriminated MCP format** - OpenCode uses type: 'local' for stdio servers and type: 'remote' for URL servers for clarity (03-02, 2026-02-13)
35. **Command array format for OpenCode** - OpenCode expects command as array [cmd, arg1, arg2], combine command+args during translation (03-02, 2026-02-13)
36. **Environment key for OpenCode** - OpenCode uses 'environment' not 'env' for environment variables (03-02, 2026-02-13)
37. **Orchestrator delegates concurrency** - SyncOrchestrator does NOT handle locks/debounce; callers (commands, hooks) manage concurrency (04-01, 2026-02-14)
38. **Deferred imports in hook** - PostToolUse hook defers sync module imports until after config file pattern match for fast non-config edit path (04-03, 2026-02-14)
39. **Hook always exits 0** - PostToolUse hook never blocks Claude Code tool execution even on sync errors (04-03, 2026-02-14)
40. **hmac.compare_digest for hash comparison** - Use hmac.compare_digest() instead of == for secure hash comparison to prevent timing attacks (05-02, 2026-02-14)
41. **Keyword+regex secret detection** - Start with keyword+regex approach (15-20% false positive rate) instead of entropy-based (60% FP), defer entropy as future enhancement (05-02, 2026-02-14)
42. **Whitelist safe prefixes** - Skip TEST_/EXAMPLE_/DEMO_/MOCK_/FAKE_/DUMMY_ prefixes to reduce false positives in secret detection (05-02, 2026-02-14)
43. **Never expose secret values** - Secret detector logs variable names only, never actual values, for security (05-02, 2026-02-14)
44. **Safety pipeline order** - Execute safety checks in order: secrets -> conflicts -> backup -> sync -> cleanup -> report -> retention (05-03, 2026-02-14)
45. **Secret detection blocks by default** - Sync blocked when secrets detected, explicit --allow-secrets override required for opt-in (05-03, 2026-02-14)
46. **Conflict detection non-blocking** - Conflict warnings displayed but sync proceeds (user may intentionally overwrite manual edits) (05-03, 2026-02-14)
47. **Compatibility report on issues only** - Report generated and displayed only when adapted or failed items need user attention (05-03, 2026-02-14)

### Active Todos
- [x] Complete Plan 01-01: Foundation utilities (Logger, hashing, paths)
- [x] Complete Plan 01-02: State Manager with drift detection
- [x] Complete Plan 01-03: Source Reader with .claude/ discovery
- [x] Complete Plan 01-04: Integration verification and plugin manifest
- [x] Complete Plan 02-01: Adapter framework infrastructure
- [x] Complete Plan 02-02: Codex adapter implementation
- [x] Complete Plan 02-03: Codex integration and verification
- [x] Complete Plan 03-01: Gemini adapter implementation
- [x] Complete Plan 03-02: OpenCode adapter implementation
- [x] Complete Plan 04-01: Core orchestrator, lock, diff formatter
- [x] Complete Plan 04-02: /sync and /sync-status commands
- [x] Complete Plan 04-03: PostToolUse hook and plugin config
- [x] Complete Plan 05-01: BackupManager and SymlinkCleaner
- [x] Complete Plan 05-02: ConflictDetector and SecretDetector
- [x] Complete Plan 05-03: CompatibilityReporter and safety integration
- [ ] Continue Phase 5: Testing & Validation (evaluation plan)

### Blockers
None currently.

### Recent Changes
- **2026-02-14:** Completed Plan 05-03 (CompatibilityReporter + safety integration) - CompatibilityReporter generates per-target breakdown of synced/adapted/skipped/failed items with explanations, full safety pipeline integrated into orchestrator (secrets -> conflicts -> backup -> sync -> cleanup -> report -> retention), /sync command with --allow-secrets flag, 10 verification tests passed (5 sanity + 5 proxy)
- **2026-02-14:** Completed Plan 05-02 (ConflictDetector + SecretDetector) - ConflictDetector with hmac.compare_digest() hash comparison, detects modifications/deletions, SecretDetector with keyword+regex approach (15-20% FP), whitelist filtering, 16+ char complexity check, never exposes secret values, 11 verification tests passed (5 sanity + 6 proxy)
- **2026-02-14:** Completed Plan 05-01 (BackupManager + SymlinkCleaner) - BackupManager with timestamped backup and LIFO rollback, SymlinkCleaner for broken symlink removal, 10 verification tests passed
- **2026-02-14:** Completed Plan 04-03 (PostToolUse hook + plugin config) - PostToolUse hook with 7 config patterns, deferred imports, always exits 0, hooks.json with Edit|Write|MultiEdit matcher, plugin.json updated with file references, 8 verification tests passed
- **2026-02-14:** Completed Plan 04-02 (/sync + /sync-status commands) - /sync with --scope/--dry-run, debounce/lock integration, formatted summary table, /sync-status with per-target display and drift detection, 9 verification tests passed
- **2026-02-14:** Completed Plan 04-01 (Core orchestrator) - SyncOrchestrator coordinating SourceReader→AdapterRegistry→StateManager, sync_lock with fcntl.flock, should_debounce with 3s window, DiffFormatter for dry-run preview, 11 verification tests passed

---

## Session Continuity

### What Just Happened
Completed Plan 05-03 (CompatibilityReporter + safety integration). Implemented CompatibilityReporter for per-target sync analysis with synced/adapted/skipped/failed categorization and explanations. Integrated all Phase 5 safety features into orchestrator (full safety pipeline: secrets -> conflicts -> backup -> sync -> cleanup -> report -> retention). Updated /sync command with --allow-secrets flag. All 10 verification tests passed (5 sanity + 5 proxy). 2 new requirements delivered (SAF-04, integration of SAF-01 through SAF-05). 1 new file created (src/compatibility_reporter.py), 2 files modified (src/orchestrator.py, src/commands/sync.py).

### What's Next
Phase 5 complete (3/3 plans, 100%). Ready for phase evaluation or move to Phase 6: Integration Testing.

### Context for Next Session
Phase 5 complete (100%). All safety features operational: BackupManager (timestamped backup + rollback), ConflictDetector (hash-based drift), SecretDetector (keyword+regex scanning), SymlinkCleaner (broken symlink removal), CompatibilityReporter (sync analysis). Full safety pipeline integrated with orchestrator. 42/44 requirements delivered (95% v1 coverage). 13 deferred validations across Phase 3-4-5 pending live testing.

---

*Last updated: 2026-02-14*
*Session: Phase 5 Plan 03 execution*
*Stopped at: Completed 05-03-PLAN.md*
