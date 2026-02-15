# HarnessSync Milestones

## v1.0: Core Plugin + Multi-Account (Complete)

**Completed:** 2026-02-15
**Phases:** 8 (24 plans)
**Verification:** 101 checks passed (100% rate)
**Deferred:** 27 validations pending live testing

### What Shipped
1. **Foundation** — State manager (SHA256 drift detection), OS-aware symlinks (3-tier fallback), source reader (6 config types, 2 scopes)
2. **Adapter System** — Abstract adapter base + registry pattern, Codex adapter (JSON→TOML, agent→skill), Gemini adapter (inline skills, settings.json MCP), OpenCode adapter (native symlinks, opencode.json MCP)
3. **Plugin Interface** — SyncOrchestrator, /sync + /sync-status commands, PostToolUse hook (3s debounce, file locking)
4. **Safety** — BackupManager, ConflictDetector, SecretDetector, CompatibilityReporter, full safety pipeline
5. **MCP Server** — JSON-RPC 2.0 stdio transport, sync_all/sync_target/get_status tools, worker thread concurrency
6. **Packaging** — .claude-plugin/ structure, marketplace.json, install.sh, shell-integration.sh, GitHub Actions CI
7. **Multi-Account** — AccountManager, AccountDiscovery, SetupWizard, account-aware orchestrator and commands

### Key Stats
- 47 v1 requirements + 10 multi-account requirements delivered
- 68 key decisions documented
- ~5,000 lines of Python (stdlib only)
- 3 target CLIs: Codex, Gemini, OpenCode

---

*Archive created: 2026-02-15*

## v2.0: Plugin & MCP Scope Sync (Shipped: 2026-02-15)

**Delivered:** Scope-aware MCP sync with Claude Code plugin discovery, env var translation, and plugin drift detection.

**Phases completed:** 9-11 (7 plans total)
**Verification:** 93 checks passed (39 phase 11 + 42 phase 10 + 12 phase 9, 100% rate)
**Deferred:** 8 validations pending live testing (DEFER-09-01/02, DEFER-10-01/02/03, DEFER-11-01/02/03)

### What Shipped
1. **Plugin MCP Discovery** — SourceReader discovers installed Claude Code plugins from installed_plugins.json, extracts MCPs from plugin cache dirs, resolves ${CLAUDE_PLUGIN_ROOT}, handles dual plugin.json formats
2. **3-Tier Scope Awareness** — User/project/local scope reading from ~/.claude.json, .mcp.json, and projects section. Precedence: local > project > user. Origin tagging on every MCP.
3. **Scope-Aware Target Sync** — Adapters route user-scope MCPs to user configs, project-scope to project configs. Plugin MCPs always user-scope. SSE transport filtering for Codex/OpenCode.
4. **Environment Variable Translation** — ${VAR} extraction and ${VAR:-default} expansion for Codex literal env maps. Gemini preserves ${VAR} natively. Uppercase-only pattern matching.
5. **Plugin Version Tracking** — StateManager records plugin metadata (version, mcp_count, mcp_servers, last_sync) with replacement semantics preventing stale accumulation.
6. **Plugin Drift Detection** — Detects version changes, MCP count changes, plugin additions/removals. Account-scoped isolation for multi-account setups.
7. **Enhanced /sync-status** — MCP servers grouped by source (User-configured, Project-configured, Local-configured, Plugin-provided with plugin@version). Plugin drift warnings displayed.

### Key Stats
- 19 v2.0 requirements delivered (100%)
- 42 key decisions documented (32 v1.0 + 10 v2.0)
- +910 lines of Python (stdlib only)
- 7 plans across 3 phases
- 4 source files modified + 1 created + 1 integration test

---

*Archive created: 2026-02-15*

