# Pitfalls Research

**Domain:** AI harness configuration sync tools & Claude Code plugin architecture
**Researched:** 2026-02-13
**Confidence:** MEDIUM-HIGH

## Critical Pitfalls

### Pitfall 1: Configuration Drift Between Source and Targets

**What goes wrong:** Claude Code config changes but target harnesses (Codex, Gemini, OpenCode) fall out of sync. Users modify Codex/Gemini configs directly, creating divergence. Settings drift becomes invisible until runtime failures occur (missing MCP servers, wrong permissions, outdated skills).

**Why it happens:**
- Multi-directional sync not enforced (users expect bi-directional, but only uni-directional is safe)
- Cooldown windows create sync gaps (current: 5 minutes means 4:59 of potential drift)
- Hook failures silently ignored (PostToolUse timeouts, permission errors)
- No conflict detection when target configs manually modified
- 55% of cloud breaches trace to configuration drift [1]

**How to avoid:**
- Implement drift detection at plugin startup (hash comparison before any operation)
- Add `--verify` mode that compares source vs targets and reports discrepancies
- Lock target configs with warning headers and file permissions (read-only where possible)
- Log all sync operations to `~/.cc2all/logs/sync-audit.log` with timestamps
- Add pre-flight check: "Target configs modified since last sync - overwrite? [y/N]"

**Warning signs:**
- User reports "it works in Claude Code but not Codex"
- MCP servers available in one CLI but missing in others
- Skills visible in `~/.claude/skills/` but not in target harnesses
- Inconsistent behavior across harnesses for same task

**Phase to address:** Phase 1 (Core Sync Engine) - drift detection must be built-in from start, not retrofitted

---

### Pitfall 2: Symlink Fragility Across Operating Systems

**What goes wrong:** Symlinks break on Windows, require admin privileges, fail silently when targets move. Directory symlinks particularly problematic - `ls` shows "no such directory" in PowerShell but Python can still access [2]. Plugin cache updates break symlinks when plugin reinstalls change install paths. Users on Windows can't create symlinks without "Run as Administrator" [3].

**Why it happens:**
- Windows treats symlinks as security risk (requires SeCreateSymbolicLinkPrivilege)
- Different symlink types: Windows junctions vs NTFS symlinks vs Unix symlinks
- Plugin cache reorganization changes paths (e.g., marketplace updates)
- Git clone doesn't preserve symlinks by default on Windows
- Relative vs absolute symlink handling differs by OS

**How to avoid:**
- Detect OS and use appropriate strategy:
  - macOS/Linux: native symlinks
  - Windows: junction points (don't require admin) or hardlinks for files
  - WSL2: Unix symlinks work correctly
- Validate symlink targets exist before creating
- Use absolute paths in symlinks to survive directory moves
- Implement fallback: if symlink creation fails, copy content instead (with ".cc2all-copied" marker)
- Check symlinks health on every sync: `if dst.is_symlink() and not dst.resolve().exists()`
- Store symlink metadata in state file to detect when targets moved

**Warning signs:**
- `FileNotFoundError` on Windows but works on macOS
- Skills disappear after `/plugin update`
- Stale symlinks in `.codex/skills/` pointing to non-existent paths
- Permission denied errors when running as non-admin on Windows

**Phase to address:** Phase 1 (Core Sync Engine) - OS detection and symlink strategy must be foundational

---

### Pitfall 3: MCP Server Format Translation Errors

**What goes wrong:** MCP server configs use different schemas across CLIs. Claude Code uses JSON with `mcpServers` object, Codex uses TOML `[mcp_servers]` tables, Gemini uses JSON but different `sse` type for remote servers, OpenCode uses JSON with `type: "remote"` [4]. Date/time values in TOML fail JSON Schema validation [5]. Environment variable escaping differs (TOML vs JSON string rules). URL-based servers need different wrappers per CLI.

**Why it happens:**
- No standard MCP configuration format across ecosystem
- TOML datetime objects can't serialize to JSON directly
- Environment variable expansion differs (Codex: native TOML, Gemini: .env file, OpenCode: inline JSON)
- Remote MCP servers use different transport mechanisms (HTTP vs SSE vs WebSocket)
- Schema validation happens at different points (parse-time vs runtime)

**How to avoid:**
- Build canonical intermediate representation (IR) for MCP configs
- Validate MCP config against schema BEFORE format translation
- Serialize TOML dates to RFC 3339 strings for JSON Schema validation
- Test MCP translation with all server types:
  - stdio servers (command + args)
  - URL servers (HTTP/SSE endpoints)
  - Servers with environment variables
  - Servers with special characters in env values
- Create translation test suite with fixtures for each CLI
- Add `--test-mcp` mode that validates translated configs without writing

**Warning signs:**
- MCP servers work in Claude Code but fail to start in Codex
- TOML parsing errors in `config.toml`
- Environment variables not expanded in target CLIs
- Remote MCP servers timeout or refuse connections
- Different error messages for "same" MCP config across CLIs

**Phase to address:** Phase 2 (Format Adapters) - translation layer needs extensive testing with real-world MCP configs

---

### Pitfall 4: PostToolUse Hook Timing and Caching Issues

**What goes wrong:** PostToolUse hooks fire too late (after tool completes, can't prevent writes). Hooks fire 10 times if Claude writes 10 files rapidly, overwhelming sync process [6]. Hook settings cached until session restart - config changes don't apply [7]. Fixed 120s timeout too short for large syncs. Hooks can't undo actions, only react. No concurrency control leads to race conditions when multiple hooks trigger simultaneously.

**Why it happens:**
- Hook execution is synchronous and blocking
- No built-in debouncing or rate limiting
- Settings cache optimization prevents mid-session config reloads
- Hook timeout (120s) not configurable per operation
- No hook execution queue or concurrency primitives

**How to avoid:**
- Implement client-side debouncing: track last hook execution time, skip if < 3s since last
- Use file-based locking: `~/.cc2all/sync.lock` prevents concurrent sync runs
- Make sync idempotent: running twice has same effect as running once
- Add `--force` flag to bypass cooldown for manual triggers
- Store hook state in `~/.cc2all/hook-state.json` to detect rapid-fire hooks
- Use async/background execution: hook triggers fast sync job, returns immediately
- Add timeout monitoring: log warnings when hook execution > 60s
- Document in plugin.json that settings changes require session restart

**Warning signs:**
- CPU spikes when Claude makes rapid file edits
- Multiple "synced X files" messages flooding console
- Hook timeout errors in Claude Code logs
- Sync state file shows timestamps < 3 seconds apart
- Race conditions: symlink points to wrong target after concurrent syncs

**Phase to address:** Phase 1 (Core Sync Engine) - debouncing and locking are architectural requirements

---

### Pitfall 5: Permission Model Mismatches Create Security Gaps

**What goes wrong:** Claude Code's three-tier permission model (deny/ask/allow) doesn't map to other CLIs [8]. OpenCode defaults most tools to "allow" while Claude Code requires explicit permission. Gemini uses .env files for secrets (less secure than Claude's encrypted vault). Codex `allowedTools` is binary (allowed or not), no "ask" mode. Syncing permissive settings from one CLI overwrites stricter settings in another. Environment variables with secrets get copied to plaintext config files.

**Why it happens:**
- No standardized permission model across AI CLIs
- Each CLI evolved security features independently
- Permission inheritance rules differ (global vs project vs agent-level)
- Secret storage mechanisms incompatible (encrypted vault vs .env vs inline JSON)
- Deny rules in Claude Code have no equivalent in some CLIs

**How to avoid:**
- Implement conservative permission translation:
  - Claude "deny" → skip tool in target CLI (don't include in allowedTools)
  - Claude "ask" → target CLI's strictest equivalent (or skip if unsupported)
  - Claude "allow" → target CLI "allow"
- Never sync `env` values containing secrets (detect patterns: API_KEY, SECRET, PASSWORD, TOKEN)
- Warn on permission downgrades: "Codex doesn't support 'ask' mode - tool will be fully allowed or blocked"
- Add `--audit-permissions` mode showing permission differences across CLIs
- Create allowlist of safe-to-sync env vars (PATH, LANG, TZ, etc.)
- Document security implications in README: "Syncing to less secure CLIs may expose secrets"

**Warning signs:**
- Tools that required confirmation in Claude Code run automatically in Codex
- API keys visible in `.codex/config.toml` or `opencode.json`
- Permission denied errors in restrictive CLI but works in permissive one
- Audit logs show tool usage without user approval

**Phase to address:** Phase 2 (Format Adapters) - permission translation requires security review before any implementation

---

### Pitfall 6: File Watcher Reliability Degrades at Scale

**What goes wrong:** inotify queue overflows when events generated faster than processed [9]. Polling monitor degrades linearly with file count, becomes unusable with >1000 files [10]. fswatch on macOS misses rapid-fire edits during 2-second latency window. File descriptor limits hit when watching deep directory trees (256 fd limit common) [11]. Remote filesystems (NFS, SMB) don't trigger inotify events. Watcher keeps running after plugin uninstall, consuming resources.

**Why it happens:**
- OS file watching APIs have hard limits (inotify queue size, fd limits)
- Recursive watching requires one fd per directory (kqueue, inotify)
- Network filesystems bypass local kernel notifications
- Polling fallback uses stat() on every file, causing disk I/O bottleneck
- No automatic watcher cleanup on plugin deactivation

**How to avoid:**
- Implement tiered watching strategy:
  - Tier 1: Watch only critical files (CLAUDE.md, settings.json, .mcp.json)
  - Tier 2: Watch skill/agent/command directories (non-recursive)
  - Tier 3: Skip deep plugin caches, use sync-on-demand instead
- Configure inotify limits at install time: `fs.inotify.max_user_watches=524288`
- Use single-file watching for critical paths, skip recursive for large trees
- Add watch health checks: detect queue overflows, restart watcher
- Provide polling interval configuration: `CC2ALL_POLL_INTERVAL` env var (default: 5s)
- Document fd limit requirements: calculate based on directory depth
- Add watch diagnostics: `cc2all watch --status` shows watcher health

**Warning signs:**
- "Queue overflow" errors in inotify logs
- Sync lag increases with number of plugins installed
- Watcher stops responding after installing large plugin
- High CPU usage from polling fallback
- Changes not detected after 10+ seconds

**Phase to address:** Phase 3 (Watch Mode) - reliability testing with large plugin sets before release

---

### Pitfall 7: Schema Validation Failures at Format Boundaries

**What goes wrong:** JSON Schema allows null in arrays, TOML doesn't support nulls [12]. TOML date/time objects fail when passed to JSON Schema validators without string conversion [13]. patternProperties in JSON Schema undefined for non-string keys (YAML supports this, TOML doesn't) [14]. Schema drift: manually maintained schemas (like VS Code TOML extension) become outdated when config structure changes [15]. Nested tables in TOML flatten differently than nested objects in JSON.

**Why it happens:**
- JSON Schema designed for JSON, not TOML/YAML/other formats
- Type system mismatches (TOML has more specific types: datetime, integer, float)
- Schema validation timing: some CLIs validate at parse, others at runtime
- No automated schema generation from config structure
- Each CLI's config evolves independently

**How to avoid:**
- Pre-validate with format-specific validators:
  - TOML: parse with `tomli`, catch exceptions before translation
  - JSON: validate with `jsonschema` before writing
- Normalize IR before validation: convert dates to strings, remove nulls, flatten nested structures
- Generate schemas from examples: use tools like `genson` to derive JSON Schema from real configs
- Version schemas with config format: `config.v1.schema.json`, `config.v2.schema.json`
- Add schema validation to test suite: every example config must pass validation
- Implement graceful degradation: if schema validation fails, log warning but continue with best-effort translation

**Warning signs:**
- "Unexpected value type" errors when loading configs
- TOML parse errors with cryptic line numbers
- JSON Schema validation fails on valid-looking TOML
- Config works when manually written but fails when synced
- Different validation errors across CLI versions

**Phase to address:** Phase 2 (Format Adapters) - schema validation must be part of adapter contract

---

### Pitfall 8: Plugin Marketplace Packaging Requirements Mismatch

**What goes wrong:** Directory structure mistakes: putting commands/ inside .claude-plugin/ instead of root [16]. CLAUDE.md duplication: same content copied to CLAUDE.md, commands, agents, skills causing 600+ line files [17]. State management failures: no file-based state for recovery across sessions [18]. Validation failures: `claude plugin validate` catches issues too late (after implementation). Path resolution errors: relative paths in marketplace.json fail installation [19]. Authentication errors: private git repos need credential helpers configured [20].

**Why it happens:**
- Plugin structure requirements not well documented
- No scaffolding tool for creating plugin boilerplate
- Validation only runs at publish time, not during development
- Marketplace resolution logic differs from local plugin loading
- Git authentication not configured for CI/CD environments

**How to avoid:**
- Run `claude plugin validate` in development loop (pre-commit hook)
- Follow canonical structure strictly:
  ```
  plugin-root/
    .claude-plugin/plugin.json    # Only this in .claude-plugin/
    commands/                      # At root, not inside .claude-plugin/
    agents/
    skills/
    hooks/
  ```
- Keep CLAUDE.md minimal (<300 lines): move domain-specific rules to skills
- Implement file-based state: `~/.cc2all/sync-state.json` for recovery
- Test marketplace installation flow in CI: `claude marketplace add ./local-marketplace.json`
- Use absolute URLs in marketplace.json, not relative paths
- Document authentication requirements in README
- Create `.claude-plugin/schema.json` for IDE autocomplete

**Warning signs:**
- `claude plugin validate` fails with path errors
- Plugin installs locally but fails from marketplace
- "File not found" during plugin installation
- CLAUDE.md ignored or partially applied
- State lost between Claude Code sessions

**Phase to address:** Phase 4 (Plugin Packaging) - validate early and often, not just at release

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Skip symlink health checks | Faster sync (avoid stat() calls) | Stale symlinks accumulate, users confused | Never - health check is O(n) where n=skills, typically <50 |
| Hard-code format translations | Simple implementation, no IR layer | Every new CLI requires forking all translation logic | Prototype only - technical debt explodes with 3+ CLIs |
| Ignore permission mismatches | Avoid complex permission mapping | Security vulnerabilities when syncing to permissive CLIs | Dev/test environments only (never production) |
| Use polling instead of native watchers | Cross-platform consistency | High CPU/disk I/O, poor UX (5s lag) | Acceptable as fallback, not primary strategy |
| Copy instead of symlink | Guaranteed Windows compatibility | Disk space waste, stale copies after plugin updates | Only when symlink creation fails (with .cc2all-copied marker) |
| Sync all env vars blindly | Feature completeness | Secrets exposed in plaintext configs | Never - must implement secret detection |
| Single global lock for all syncs | Simple concurrency control | User-scope and project-scope syncs block each other | Early MVP - refactor to scope-specific locks in Phase 2 |
| Skip schema validation | Faster translation, fewer dependencies | Runtime errors in target CLIs, bad configs persist | Never - validation cost is negligible vs debugging time |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| fswatch (macOS) | Assume events are immediate | Add 2-second debounce buffer, cooldown between syncs |
| inotify (Linux) | Watch recursively without fd limit checks | Calculate fd requirements, fail-fast if ulimit too low |
| Windows symlinks | Use `os.symlink()` without admin check | Detect privileges, fall back to junction/hardlink/copy |
| TOML generation | Concatenate strings to build TOML | Use `tomli_w` library, validate output with `tomli` |
| JSON merging | Overwrite entire config files | Preserve non-cc2all sections with delimiters (`# --- cc2all start ---`) |
| Plugin hooks | Sync on every PostToolUse | Debounce: skip if last sync < 3s ago, use file lock |
| MCP URLs | Copy URL strings directly | Validate URL format, test connectivity, handle auth |
| Permission translation | Map 1:1 across CLIs | Conservative mapping: unsupported modes → deny/skip |
| Marketplace paths | Use relative paths in marketplace.json | Absolute URLs or well-defined relative path base |
| Secret detection | Regex for "password" keyword | Comprehensive patterns: API_KEY, TOKEN, SECRET, *_PASS, etc. |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| stat() polling all files | 100% CPU, slow disk I/O | Watch critical files only, use native OS watchers | >100 files in watch set |
| Unbounded hook execution | Sync runs 10+ times in <1s | File-based lock, 3s debounce, cooldown timer | Claude edits 10+ files rapidly |
| Recursive symlink health checks | O(n²) stat calls | Check only direct symlinks, not transitive | >50 skills installed |
| Re-parsing entire TOML on every sync | Slow sync with large configs | Incremental updates with delimiters, preserve non-cc2all sections | config.toml >500 lines |
| No sync result caching | Redundant format translations | Hash-based change detection, skip if source unchanged | Watch mode with no actual changes |
| Synchronous hook execution | Claude Code UI blocks during sync | Background job queue, return immediately from hook | Sync takes >5s (large plugin set) |
| Deep directory watching | inotify fd exhaustion | Shallow watching: only ~/.claude/ top-level, not caches | Plugin cache >10 levels deep |
| No batch operations | N individual file writes | Batch skills/agents/commands into single write cycle | >20 skills to sync |

## "Looks Done But Isn't" Checklist

- [ ] **Symlinks:** Verified they work on Windows (junction/hardlink fallback implemented)
- [ ] **MCP Servers:** Tested with all transport types (stdio, HTTP, SSE) across all target CLIs
- [ ] **Permissions:** Audited that secrets never sync to plaintext configs (API keys, tokens, passwords)
- [ ] **Watch Mode:** Tested with >100 files, confirmed no queue overflow or fd exhaustion
- [ ] **Hook Timing:** Debounce prevents sync storms when Claude makes rapid edits
- [ ] **Concurrent Syncs:** File lock prevents race conditions when multiple triggers fire
- [ ] **Schema Validation:** TOML dates serialize to strings before JSON Schema validation
- [ ] **Drift Detection:** Users warned when target configs manually modified since last sync
- [ ] **Error Recovery:** Sync failures logged, state preserved, next sync retries cleanly
- [ ] **Plugin Validation:** Runs clean through `claude plugin validate` before packaging
- [ ] **Cross-Platform:** Tested on macOS, Linux, Windows (WSL2 and native)
- [ ] **Marketplace Install:** Plugin installs from both local and remote marketplace URLs
- [ ] **Cleanup:** Stale symlinks removed, orphaned configs cleaned up
- [ ] **Documentation:** Security implications documented (permission downgrades, secret exposure risks)
- [ ] **Rollback:** Failed sync doesn't corrupt configs (atomic writes, backup previous state)

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Configuration Drift | Phase 1 (Core Sync Engine) | Hash comparison shows source=target after sync |
| Symlink Fragility | Phase 1 (Core Sync Engine) | Skills accessible on Windows without admin privileges |
| MCP Format Translation | Phase 2 (Format Adapters) | MCP servers start successfully in all target CLIs |
| PostToolUse Hook Timing | Phase 1 (Core Sync Engine) | 10 rapid edits trigger 1 sync, not 10 syncs |
| Permission Model Mismatches | Phase 2 (Format Adapters) | No secrets found in plaintext target configs |
| File Watcher Reliability | Phase 3 (Watch Mode) | Watcher handles 1000-file repo without overflow |
| Schema Validation Failures | Phase 2 (Format Adapters) | All translated configs parse without errors |
| Plugin Marketplace Packaging | Phase 4 (Plugin Packaging) | `claude plugin validate` passes, marketplace install succeeds |

## Sources

[1] [50 Cloud Misconfiguration Statistics For 2025–2026](https://www.datastackhub.com/insights/cloud-misconfiguration-statistics/)
[2] [Cross-platform dotfile Management with dotbot](https://brianschiller.com/blog/2024/08/05/cross-platform-dotbot/)
[3] [Fixing Git Symlink Issues on Windows with Cross-Platform Repositories](https://sqlpey.com/git/fixing-git-symlink-issues-windows/)
[4] [Connect Claude Code to tools via MCP - Claude Code Docs](https://code.claude.com/docs/en/mcp)
[5] [Documenting how to validate TOML with JSON schema](https://github.com/toml-lang/toml/discussions/1038)
[6] [Claude Code Hooks: Production Patterns Nobody Talks About](https://www.marc0.dev/en/blog/claude-code-hooks-production-patterns-async-setup-guide-1770480024093)
[7] [Hook settings are cached and changes don't take effect until session restart](https://github.com/anthropics/claude-code/issues/22679)
[8] [Permissions | OpenCode](https://opencode.ai/docs/permissions/)
[9] [fswatch - Cross-platform file change monitor](https://github.com/emcrisostomo/fswatch)
[10] [a quick review of file watchers](https://anarc.at/blog/2019-11-20-file-monitoring-tools/)
[11] [FileSystem Watcher: Consider polling API](https://github.com/dotnet/runtime/issues/17111)
[12] [Frequently Asked Questions - jsonschema](https://python-jsonschema.readthedocs.io/en/latest/faq/)
[13] [Schema Validation for TOML | JSON Schema Everywhere](https://json-schema-everywhere.github.io/toml)
[14] [What is wrong with TOML? - HitchDev](https://hitchdev.com/strictyaml/why-not/toml/)
[15] [TOML schema in recommended vscode extension is outdated](https://community.fly.io/t/toml-schema-in-recommended-vscode-extension-is-outdated/12340)
[16] [What I learned while building a trilogy of Claude Code Plugins](https://pierce-lamb.medium.com/what-i-learned-while-building-a-trilogy-of-claude-code-plugins-72121823172b)
[17] [My Claude Code Setup | Here's What I Learned](https://medium.com/@kumaran.isk/my-claude-code-setup-heres-what-i-learned-d0403b1b1fec)
[18] [Building /deep-plan: A Claude Code Plugin for Comprehensive Planning](https://pierce-lamb.medium.com/building-deep-plan-a-claude-code-plugin-for-comprehensive-planning-30e0921eb841)
[19] [Create and distribute a plugin marketplace - Claude Code Docs](https://code.claude.com/docs/en/plugin-marketplaces)
[20] [Automate workflows with hooks - Claude Code Docs](https://code.claude.com/docs/en/hooks-guide)

---
*Pitfalls research for: AI harness configuration sync tools & Claude Code plugin architecture*
*Researched: 2026-02-13*
