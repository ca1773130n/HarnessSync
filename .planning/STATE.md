# HarnessSync Project State

## Project Reference

**Core Value:** One harness to rule them all — configure Claude Code once, sync everywhere (Codex, Gemini CLI, OpenCode) without manual duplication or format translation.

**Current Focus:** Phase 8 - Multi-Account Support (Complete)

---

## Current Position

**Phase:** 8
**Plan:** 04 (completed)
**Status:** Complete

**Progress:**
[██████████] 100%
Phase 8: Multi-Account Support
██████████ 100% (4/4 plans complete)

Overall Project: 8/8 phases complete — v1.0 + Multi-Account DONE
```

---

## Performance Metrics

### Velocity
- **Phases completed:** 8/8
- **Plans completed:** 24 (01-01, 01-02, 01-03, 01-04, 02-01, 02-02, 02-03, 03-01, 03-02, 04-01, 04-02, 04-03, 05-01, 05-02, 05-03, 06-01, 06-02, 07-01, 07-02, 07-03, 08-01, 08-02, 08-03, 08-04)
- **Average plan duration:** ~3 min
- **Project complete:** 2026-02-15

### Quality
- **Verification passes:** 101 (82 prior + 14 sanity + 5 proxy)
- **Verification failures:** 0
- **Pass rate:** 100%

### Scope
- **Requirements delivered:** 47/47 + Phase 8 multi-account extensions (MULTI-01 through MULTI-08)
- **v1 coverage:** 100%
- **v1.1 coverage:** 100% (multi-account support)
- **Deferred to v2:** 0

---

## Experiment Metrics

### Research Context
- **Landscape analysis:** Complete (SUMMARY.md exists with 7-phase suggestions)
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

Phase 6 deferred validations (DEFER-06-01 through DEFER-06-03):
- Claude Code MCP client integration (requires plugin installed)
- External agent cross-CLI invocation (requires MCP client library)
- Production load testing (requires sustained testing environment)

Phase 7 deferred validations (DEFER-07-01 through DEFER-07-06):
- `claude plugin validate .` passes (requires Claude Code CLI)
- GitHub installation via `/plugin install github:username/HarnessSync` (requires published repo)
- Marketplace URL installation (requires hosted marketplace.json)
- Linux cross-platform install.sh (requires GitHub Actions run)
- Windows cross-platform install.sh (requires Windows environment)
- Live plugin integration (hooks/commands/MCP in live session)

Phase 8 deferred validations (DEFER-08-01 through DEFER-08-05):
- Interactive wizard UX with TTY (requires manual testing)
- Production home directory discovery (1M+ files) (requires beta testing)
- Windows multi-account path handling (requires Windows environment)
- Concurrent multi-account sync (requires live usage)
- Live /sync --account in Claude Code session (requires integration testing)

**Total deferred validations:** 27 across Phase 3-8

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
48. **Logging to stderr only** - stdout is JSON-RPC protocol channel, never write anything else to it (06-01, 2026-02-15)
49. **Manual validators over jsonschema** - stdlib constraint, simple type+range checks sufficient for 3 tools (06-01, 2026-02-15)
50. **tools/call marker dict** - Protocol handler returns marker for server to intercept and dispatch to worker thread (06-01, 2026-02-15)
51. **Daemon worker thread** - Auto-exits when main thread ends, no shutdown complexity (06-02, 2026-02-15)
52. **Queue maxsize=1** - Prevents unbounded memory, second sync gets immediate "busy" response (06-02, 2026-02-15)
53. **Early validation before queueing** - Reject invalid args immediately without worker thread overhead (06-02, 2026-02-15)
54. **get_status in main thread** - Status queries should never wait for sync lock or queue (06-02, 2026-02-15)
55. **marketplace.json uses GitHub source** - `"source": "github"` with `"repo": "username/HarnessSync"` placeholder, user updates before publishing (07-01, 2026-02-15)
56. **Version pinned to ref: main** - Stable branch distribution via marketplace (07-01, 2026-02-15)
57. **Shell-integration invokes SyncOrchestrator via Python one-liner** - No standalone CLI script needed, import directly (07-02, 2026-02-15)
58. **HARNESSSYNC_HOME defaults to script directory** - Portable across install locations, not hardcoded path (07-02, 2026-02-15)
59. **Stamp file at $HOME/.harnesssync/.last-sync** - Separate from plugin directory, survives plugin updates (07-02, 2026-02-15)
60. **Account name must start with alphanumeric** - Prevents `.` or `-` prefixed names that could cause filesystem issues (08-01, 2026-02-15)
61. **Discovery excludes 20+ directory patterns** - Including Downloads, Documents, Desktop to avoid scanning user data directories (08-01, 2026-02-15)
62. **Global MCP not scoped per account** - `~/.mcp.json` stays global, only `cc_home`-relative paths change per account (08-02, 2026-02-15)
63. **v1 migration wraps targets in "default" account** - Preserves all data including file_hashes and timestamps (08-02, 2026-02-15)
64. **Fresh state starts at version 2** - With empty accounts dict (08-02, 2026-02-15)
65. **Default target paths: ~/.{cli}-{account_name}** - Plain ~/.{cli} only for "default" account (08-03, 2026-02-15)
66. **Config-file import skips invalid accounts** - Warning instead of failing entire import (08-03, 2026-02-15)
67. **sync_all_accounts() falls back to v1** - Catches exceptions and falls back to single sync_all() (08-04, 2026-02-15)
68. **Auto-detect multi-account in status** - If accounts exist, show all; otherwise v1 status (08-04, 2026-02-15)

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
- [x] Complete Plan 06-01: MCP Protocol Foundation (transport, protocol, schemas)
- [x] Complete Plan 06-02: MCP Server & Tool Handlers (tools, server)
- [x] Complete Plan 07-01: Plugin directory structure + marketplace.json
- [x] Complete Plan 07-02: install.sh + shell-integration.sh rewrite
- [x] Complete Plan 07-03: CI workflow + final verification
- [x] Complete Plan 08-01: AccountManager + AccountDiscovery
- [x] Complete Plan 08-02: SourceReader cc_home + StateManager v2
- [x] Complete Plan 08-03: SetupWizard + /sync-setup command
- [x] Complete Plan 08-04: Account-aware orchestrator + commands

### Roadmap Evolution
- Phase 8 added: Multi-Account Support — setup process for multiple harness accounts with sync across all backends (2026-02-15)
- Phase 8 completed: 4 plans executed, 19 verification checks passed (2026-02-15)

### Blockers
None. v1.0 + Phase 8 complete. All 8 phases delivered.

### Recent Changes
- **2026-02-15:** Completed Phase 8 (Multi-Account Support) - 4 plans executed. AccountManager + AccountDiscovery (290 lines), SourceReader cc_home parameterization, StateManager v2 schema with auto-migration, SetupWizard + /sync-setup command, account-aware orchestrator + /sync --account + /sync-status --list-accounts. 19/19 verification checks passed (14 sanity + 5 proxy), 5 deferred validations tracked.
- **2026-02-15:** Completed Phase 7 (Packaging & Distribution) - 3 plans executed. .claude-plugin/ directory with plugin.json and marketplace.json (GitHub source), install.sh rewritten with HarnessSync branding, --dry-run, platform detection (macOS/Linux/Windows/WSL), shell-integration.sh rewritten with HARNESSSYNC_* naming, GitHub Actions CI workflow with 3-platform x 2-Python matrix, 27/27 verification checks passed (19 sanity + 8 proxy), 6 deferred validations tracked.
- **2026-02-15:** Completed Phase 6 (MCP Server Integration) - 6 new files in src/mcp/ (658 lines total), 14 verification tests passed
- **2026-02-14:** Completed Phase 5 (Safety & Reliability) - BackupManager, ConflictDetector, SecretDetector, CompatibilityReporter, full safety pipeline
- **2026-02-14:** Completed Phase 4 (Plugin Interface) - SyncOrchestrator, /sync + /sync-status commands, PostToolUse hook
- **2026-02-13:** Completed Phase 3 (Target Adapters: Gemini + OpenCode)
- **2026-02-13:** Completed Phase 2 (Target Adapters: Codex)
- **2026-02-13:** Completed Phase 1 (Foundation & State Management)

---

## Session Continuity

### What Just Happened
Completed Phase 8 (Multi-Account Support). All 4 plans executed successfully:
- **08-01:** Created AccountManager (CRUD, atomic writes, collision detection) + AccountDiscovery (depth-limited scanning, validation)
- **08-02:** Parameterized SourceReader with cc_home, upgraded StateManager to v2 schema with auto v1 migration
- **08-03:** Created SetupWizard (interactive 4-step flow) + /sync-setup command (list/remove/show/config-file)
- **08-04:** Extended SyncOrchestrator, /sync, /sync-status with --account and --list-accounts flags

### What's Next
**Project v1.0 + Multi-Account is complete.** All 8 phases delivered, 24 plans executed, 101 verification checks passed with 0 failures. 27 deferred validations pending live testing.

**Before publishing:**
1. Update `username` placeholder in marketplace.json with actual GitHub username
2. Push to GitHub and verify CI workflow passes
3. Run `claude plugin validate .` when CLI is available
4. Test installation via `/plugin install github:YOUR_USERNAME/HarnessSync`
5. Test `/sync-setup` interactive wizard with real TTY

### Context for Next Session
All 8 phases complete. 24 plans executed across 8 phases. 68 key decisions documented. 47/47 v1 requirements + 8 multi-account extensions delivered. 101 verification checks passed (100% pass rate). 27 deferred validations tracked across Phase 3-8. 5 new files created in Phase 8 (~650 lines), 7 existing files modified (~435 lines). Project ready for GitHub publish.

---

*Last updated: 2026-02-15*
*Session: Phase 8 execution*
*Stopped at: Phase 8 complete (all 8 phases delivered)*
