# Project Research Summary

**Project:** HarnessSync - AI Harness Configuration Sync Plugin
**Domain:** Claude Code Plugin Development (Multi-CLI Configuration Management)
**Researched:** 2026-02-13
**Confidence:** HIGH

## Executive Summary

HarnessSync is a Claude Code plugin that synchronizes configuration across multiple AI coding assistants (Claude Code, Codex CLI, Gemini CLI, OpenCode). The project involves building a sophisticated configuration translation system that must handle semantic differences in permission models, file formats (JSON vs TOML), and feature gaps across CLIs. The recommended approach uses Python stdlib exclusively with an adapter pattern architecture, exposing sync capabilities through slash commands, auto-invoked skills, and PostToolUse hooks for reactive synchronization.

The research landscape is sparse - existing tools like skillshare only handle skills (not rules/MCP/settings) and lack intelligent semantic translation. The biggest technical challenges are configuration drift detection (55% of cloud breaches trace to drift), permission model normalization (each CLI has incompatible security models), and cross-platform symlink reliability (Windows requires admin privileges or junction fallbacks). The existing Python script (cc2all-sync.py) provides a working proof-of-concept but needs refactoring into a modular plugin architecture with state tracking, conflict detection, and rollback capabilities.

Critical success factors include implementing hash-based drift detection from day one (not retrofitted), using conservative permission translation to avoid security gaps, and providing robust symlink fallback strategies for Windows. The architecture must be extensible - adding new target CLIs should require only a new adapter implementation, not core engine changes. MCP server format translation is particularly complex due to TOML/JSON schema mismatches and requires extensive testing with all transport types (stdio, HTTP, SSE).

## Key Findings

### Recommended Stack

**Core Technologies:**
- **Python 3.10+ (stdlib only)** - Mandatory constraint, provides pathlib, json, shutil, subprocess, hashlib for all sync operations
- **Bash 5.x+** - Installation scripts and shell integration (macOS ships with 3.2, need Homebrew for modern features)
- **Node.js 25.x + TypeScript 5.x** - CONDITIONAL: only if MCP server integration needed for exposing sync tools to other agents

**Architecture Decisions:**
- Standard Claude Code plugin structure with all components at root level (not nested in .claude-plugin/)
- Python hooks with JSON stdin/stdout (no TypeScript SDK dependency)
- Markdown slash commands with YAML frontmatter and embedded bash execution
- External binaries (fswatch/inotify-tools) for watch mode, not Python watchdog library
- JSON-only configuration (no YAML/TOML dependencies)

**Key Constraint:** No pip install allowed - all dependencies must be Python stdlib or external system binaries. This rules out watchdog, PyYAML, tomli (pre-3.11), and other common libraries.

### Expected Features

**Table Stakes (MVP v1.0):**
- Unidirectional sync (Claude → all targets) with state tracking
- Conflict detection and warnings (no auto-merge initially)
- Dry run mode for previewing changes
- Watch mode for real-time sync
- MCP server format translation (JSON ↔ TOML)
- Permission model validation with warnings
- Rollback support with pre-sync backups
- Shell integration via PostToolUse hooks
- Scope isolation (user vs project configurations)

**Differentiators (Competitive Advantage):**
- **Semantic translation** - Convert Claude agents → Codex skills intelligently (extract tools, adapt permissions), not just wrap in SKILL.md
- **Permission normalization** - Map Claude's allowedTools → Codex sandbox levels → Gemini yolo/allowedTools → OpenCode permission modes
- **Validation before sync** - Catch incompatibilities early (e.g., Gemini can't symlink skills, must inline)
- **Drift reports** - Scheduled diffs showing config divergence across CLIs
- **Built for Claude Code first** - Native plugin integration vs external tool

**Deferred to v1.x+:**
- Bidirectional sync (complex, requires user testing of conflict resolution UX)
- Merge strategies (3-way merge instead of overwrite)
- AI-assisted conflict resolution (use Claude API to propose solutions)
- Profile support (work/home profiles with different sync rules)
- Team sharing via git (version-controlled sync rules)

**Anti-Features (Explicitly Avoid):**
- GUI/TUI dashboard (scope creep, use JSON output for external tools)
- Support for non-AI CLIs (mission creep, chezmoi exists for general dotfiles)
- Cloud sync to Dropbox/Drive (security nightmare with API keys)
- Full auto-merge (impossible to avoid conflicts safely)
- Support for legacy CLIs like Cursor/Aider (unmaintained, high support burden)

### Architecture Approach

**Component Structure:**
```
Sync Engine (orchestrator)
  ├─ Source Reader (Claude Code config discovery)
  ├─ State Manager (hash-based change detection)
  └─ Adapter Registry (pluggable target adapters)
       ├─ Codex Adapter (JSON → TOML, agent → skill conversion)
       ├─ Gemini Adapter (symlink → inline, MCP → npx wrapper)
       └─ OpenCode Adapter (native agent/command support)
```

**Design Patterns:**
1. **Adapter Pattern** - Each target CLI has isolated format translation logic implementing common interface (sync_rules, sync_skills, sync_mcp)
2. **Registry Pattern** - Central registry for adapter discovery, enables adding new targets without modifying core
3. **Hook-Based Reactive Sync** - PostToolUse hooks detect config changes, trigger sync automatically with debouncing
4. **Scope-Aware Sync** - Separate user-level (~/.claude/) and project-level (.claude/) sync paths
5. **Translation Layer** - Intermediate representation (IR) for configs before format-specific serialization

**Data Flow:**
- Manual sync: /sync command → SyncEngine → SourceReader → StateManager (hash check) → Adapters (parallel) → Save state
- Auto sync: PostToolUse hook → File path check → Cooldown check → SyncEngine (same as manual)
- MCP integration: External agent → MCP tool call → SyncEngine.sync_single_target → Return status

**Build Order (by dependency):**
1. Phase 1 - Foundation: utils (logger, paths) → state_manager
2. Phase 2 - Input: source_reader
3. Phase 3 - Extensibility: adapters/base → adapters/registry
4. Phase 4 - Targets: codex/gemini/opencode adapters (parallel)
5. Phase 5 - Orchestration: sync_engine
6. Phase 6 - UI: commands, skills, hooks
7. Phase 7 - Inter-agent: MCP server (optional)

### Critical Pitfalls

**Top 5 Pitfalls with Prevention:**

1. **Configuration Drift** (55% of cloud breaches trace to drift)
   - Implement hash comparison before every sync
   - Lock target configs with warning headers
   - Add --verify mode for drift detection
   - Log all syncs to audit trail
   - Pre-flight check warns if targets modified manually

2. **Symlink Fragility on Windows**
   - Detect OS and use junction points (no admin) vs native symlinks
   - Validate symlink targets exist before creating
   - Fallback to copy with .cc2all-copied marker if symlink fails
   - Check symlink health on every sync
   - Store metadata to detect when plugin paths change

3. **MCP Format Translation Errors**
   - Build canonical IR for MCP configs
   - Validate against schema BEFORE format translation
   - Serialize TOML dates to RFC 3339 strings
   - Test all server types: stdio, URL (HTTP/SSE), with env vars
   - Add --test-mcp mode for validation without writing

4. **PostToolUse Hook Timing Issues**
   - Implement 3-second debouncing (skip if last sync < 3s ago)
   - File-based locking (~/.cc2all/sync.lock) prevents concurrent runs
   - Make sync idempotent (running twice = same as once)
   - Use async/background execution for large syncs
   - Document that hook settings changes require session restart

5. **Permission Model Mismatches**
   - Conservative translation: Claude "deny" → skip tool in target
   - Never sync env values with secrets (API_KEY, SECRET, PASSWORD, TOKEN patterns)
   - Warn on permission downgrades (e.g., "ask" mode unsupported in target)
   - Add --audit-permissions mode showing differences
   - Allowlist safe env vars (PATH, LANG, TZ)

**Additional Concerns:**
- File watcher reliability degrades with >1000 files (inotify queue overflow, fd limits)
- Schema validation failures at TOML/JSON boundaries (null handling, date serialization)
- Plugin marketplace packaging issues (directory structure, CLAUDE.md bloat, validation timing)

## Research Landscape Summary

**Existing Tools:**
- **skillshare** - Syncs skills only across Claude Code/OpenClaw/OpenCode, no rules/MCP/settings, no semantic translation
- **claude_code_bridge** - Multi-AI collaboration focused, not config sync
- **cmux** - Execution orchestration, not config management
- **Dotfile managers (chezmoi, DotState)** - General-purpose, no AI CLI semantics, no MCP translation

**HarnessSync Differentiation:**
- AI harness specialization with deep format knowledge
- Semantic translation (agents → skills with intelligence)
- Permission normalization across incompatible models
- MCP translation (TOML ↔ JSON, URL vs command)
- Built as Claude Code plugin with native integration

**Gap:** No existing tool handles full-spectrum sync (rules + skills + agents + commands + MCP + settings) with semantic awareness. This is a greenfield opportunity.

## Implications for Roadmap

### Suggested Phase Structure (6 phases)

### Phase 1: Core Foundation & State Management
**Type:** implement
**Rationale:** Drift detection, state tracking, and OS-aware symlink handling must be architectural from day one - cannot be retrofitted. Pitfalls research shows 55% of cloud breaches trace to drift, and symlink failures are silent on Windows without proper handling.
**Delivers:**
- State manager with hash-based change detection
- Path utilities with OS-aware symlink creation (junction fallback on Windows)
- Logging infrastructure with audit trail
- Basic source reader for Claude Code config discovery
**Features:** None directly (foundation layer)
**Pitfalls Avoided:** Configuration Drift (#1), Symlink Fragility (#2)

### Phase 2: Adapter Framework & Codex Sync
**Type:** implement
**Rationale:** Adapter pattern proves extensibility early. Codex is first target because it's the most complex (TOML format, agent → skill conversion, no native command support). If Codex adapter works, others will be easier.
**Delivers:**
- Abstract adapter base class and registry
- Codex adapter with JSON → TOML translation
- Agent → skill semantic conversion
- MCP server format translation (JSON → TOML tables)
**Features:** Sync rules, skills, and MCP servers to Codex
**Pitfalls Avoided:** MCP Format Translation (#3), Schema Validation Failures (#7)

### Phase 3: Gemini & OpenCode Adapters
**Type:** implement
**Rationale:** Gemini requires inline skills (no symlinks), OpenCode has native agent/command support. These adapters validate the registry pattern works for diverse capabilities.
**Delivers:**
- Gemini adapter with inline skill compilation
- OpenCode adapter with native agent/command symlinks
- Cross-adapter validation and testing
**Features:** Sync to all 3 target CLIs
**Pitfalls Avoided:** Feature Parity Gaps (from FEATURES.md), Translation Layer complexity

### Phase 4: Plugin Interface (Commands, Skills, Hooks)
**Type:** implement
**Rationale:** User-facing components depend on working sync engine + adapters. Commands provide manual control, hooks enable reactive sync, skills expose status to agents.
**Delivers:**
- /sync slash command with scope arguments (user/project/all)
- /sync-status skill (auto-invoked)
- PostToolUse hook with debouncing and file locking
- Dry-run mode and rollback support
**Features:** User can manually sync, auto-sync on config changes, query sync status
**Pitfalls Avoided:** PostToolUse Hook Timing (#4), Hook execution storms

### Phase 5: Permission Validation & Security
**Type:** implement
**Rationale:** Security cannot be deferred - syncing permissive settings to restrictive CLIs or exposing secrets in plaintext configs creates vulnerabilities. Must happen before MVP release.
**Delivers:**
- Permission model translation with conservative mapping
- Secret detection for env vars (API_KEY, TOKEN, PASSWORD patterns)
- Permission audit mode (--audit-permissions)
- Validation warnings for incompatible configs
**Features:** Safe permission sync, secret detection, audit reports
**Pitfalls Avoided:** Permission Model Mismatches (#5), Security Gaps

### Phase 6: Packaging & Marketplace Distribution
**Type:** implement
**Rationale:** Plugin structure validation, marketplace.json, and installation testing ensure distribution works. Must run `claude plugin validate` early to catch structure issues.
**Delivers:**
- Correct directory structure (components at root, not in .claude-plugin/)
- Minimal CLAUDE.md (<300 lines)
- plugin.json with proper hooks/commands/skills config
- marketplace.json with absolute URLs
- Installation testing (local + remote)
**Features:** Distributable plugin via marketplace
**Pitfalls Avoided:** Plugin Marketplace Packaging (#8)

### Phase Ordering Rationale

**Why this order:**
1. **Foundation first** - State management and symlink handling are architectural requirements, not features
2. **Prove adapter pattern early** - Codex (hardest) validates extensibility before building 2 more adapters
3. **Complete engine before UI** - No point in slash commands if sync engine doesn't work
4. **Security before release** - Permission validation cannot be "added later" without risk
5. **Packaging last** - Only validate structure after all components implemented

**Dependency chain:**
- Phase 1 (utils, state) → all other phases
- Phase 2 (adapters/base) → Phase 3 (concrete adapters)
- Phase 2+3 (all adapters) → Phase 4 (plugin UI)
- Phase 4 (working plugin) → Phase 5 (security audit)
- Phase 5 (complete feature set) → Phase 6 (packaging)

**How this avoids pitfalls:**
- Drift detection built-in from Phase 1 (not retrofitted)
- Symlink OS detection in Phase 1 (before any adapter uses symlinks)
- MCP translation tested in Phase 2 (with most complex format)
- Hook debouncing in Phase 4 (prevents storms from day one)
- Permission audit in Phase 5 (catches security issues before release)

### Research Flags

**Phases needing deeper research during planning:**
- **Phase 2 (Codex Adapter)** - MCP TOML schema requires validation with real-world Codex configs. Need `/grd:research-phase` for:
  - TOML datetime serialization edge cases
  - Codex sandbox permission levels mapping
  - Agent → skill conversion heuristics
- **Phase 5 (Permission Validation)** - Security model comparison across 4 CLIs needs comprehensive analysis. Need `/grd:research-phase` for:
  - Complete permission model matrix
  - Secret detection pattern validation (false positives/negatives)
  - Conservative translation policy (what to do with unsupported modes)

**Phases with well-documented patterns (skip research):**
- Phase 1 - State management and file I/O are standard patterns
- Phase 3 - Gemini/OpenCode follow same adapter pattern as Codex
- Phase 4 - Plugin components follow official Claude Code examples
- Phase 6 - Packaging follows official plugin structure guide

### Deferred Features (Post-MVP)

**v1.1 - Bidirectional Sync:**
- Requires conflict resolution UX design
- Needs user testing of merge strategies
- High complexity, high user value
- Trigger: user requests for reverse sync in production

**v1.2 - Advanced Features:**
- Drift reports (scheduled diffs with notifications)
- Hooks for custom transformations (.cc2all/hooks/)
- Profile support (work/home profiles)
- AI-assisted conflict resolution (experimental)

**v2.0 - Ecosystem Integration:**
- Plugin marketplace integration (auto-install skills)
- Config linting (pre-sync validation)
- Migration wizard (import existing CLI configs)
- Cross-CLI skill catalog

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| **Stack** | **HIGH** | Python stdlib requirement well-researched. Context7 confirms Python hooks sufficient. JSON-only config proven in existing tools. External binaries (fswatch) acceptable for watch mode. |
| **Features** | **HIGH** | Table stakes validated against Codex/Gemini/OpenCode docs. Differentiators (semantic translation, permission normalization) address real pain points from competitive analysis. Anti-features informed by scope creep examples from other plugins. |
| **Architecture** | **HIGH** | Adapter pattern proven for multi-target sync (dotfile managers, cloud sync tools). Component dependencies clear. Build order validated against similar plugin projects (deep-plan, skillshare). |
| **Pitfalls** | **MEDIUM-HIGH** | Top 5 pitfalls sourced from production experience (cloud drift stats, Windows symlink issues, MCP format mismatches). Hook timing issues documented in GitHub issues. Some edge cases (TOML datetime serialization) need testing. |
| **Research Landscape** | **MEDIUM** | Existing tools surveyed but ecosystem is sparse (no direct competitors for full-spectrum sync). Gap analysis solid but limited to 2026 snapshot. |

**Overall Confidence:** HIGH - All core areas well-researched with multiple source validation. Medium confidence on pitfalls due to some edge cases requiring hands-on testing, but prevention strategies are sound.

## Gaps to Address During Planning

1. **TOML parsing for Python 3.10** - tomllib only in 3.11+. Options:
   - Require Python 3.11+ (may break for some users)
   - Vendor minimal TOML parser (acceptable for stdlib-only?)
   - Use manual string parsing for simple Codex config.toml
   - **Recommendation:** Check Python version, use tomllib if available, fallback to manual parsing

2. **Watch mode priority** - Is it critical or nice-to-have?
   - PostToolUse hooks cover 95% of use cases
   - Watch mode adds complexity (fd limits, battery drain)
   - **Recommendation:** Optional feature, disabled by default, document battery implications

3. **MCP server testing coverage** - Need real-world configs:
   - stdio servers (most common)
   - URL servers (HTTP, SSE)
   - Servers with environment variables
   - Servers with special characters in paths/args
   - **Recommendation:** Create test fixture suite with all MCP types in Phase 2

4. **Windows testing environment** - Symlink behavior varies:
   - Native Windows (admin required)
   - Windows + WSL2 (Unix symlinks)
   - Junction points (no admin)
   - **Recommendation:** CI testing on all 3 Windows variants before Phase 6

5. **Cross-platform shell integration** - Bash vs Zsh:
   - macOS default: zsh (as of 10.15+)
   - Linux default: bash
   - install.sh needs to detect shell and configure appropriately
   - **Recommendation:** Provide both bash and zsh wrappers, auto-detect in installer

## Sources

### Primary (HIGH confidence)

**Claude Code Official Documentation:**
- [Claude Code plugin structure](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/plugin-structure/SKILL.md)
- [Claude Code hooks configuration](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/plugin-structure/examples/advanced-plugin.md)
- [Claude Code MCP integration](https://github.com/anthropics/claude-code/blob/main/plugins/plugin-dev/skills/mcp-integration/SKILL.md)
- [Slash commands documentation](https://code.claude.com/docs/en/slash-commands)
- [Hooks guide](https://code.claude.com/docs/en/hooks-guide)
- [Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)

**Target CLI Documentation:**
- [Codex Configuration Reference](https://developers.openai.com/codex/config-reference/)
- [Codex Advanced Configuration](https://developers.openai.com/codex/config-advanced/)
- [Gemini CLI Configuration](https://geminicli.com/docs/get-started/configuration/)
- [GEMINI.md Files](https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html)
- [OpenCode Config](https://opencode.ai/docs/config/)
- [OpenCode Agents](https://opencode.ai/docs/agents/)
- [OpenCode Permissions](https://opencode.ai/docs/permissions/)

**Python & System:**
- [Python select module](https://docs.python.org/3/library/select.html)

### Secondary (MEDIUM confidence)

**Best Practices & Patterns:**
- [MCP SDK comparison TypeScript vs Python](https://www.stainless.com/mcp/mcp-sdk-comparison-python-vs-typescript-vs-go-implementations)
- [Claude Code plugin best practices 2026](https://pierce-lamb.medium.com/the-deep-trilogy-claude-code-plugins-for-writing-good-software-fast-33b76f2a022d)
- [What I learned building Claude Code Plugins](https://pierce-lamb.medium.com/what-i-learned-while-building-a-trilogy-of-claude-code-plugins-72121823172b)
- [Building /deep-plan plugin](https://pierce-lamb.medium.com/building-deep-plan-a-claude-code-plugin-for-comprehensive-planning-30e0921eb841)
- [My Claude Code Setup](https://medium.com/@kumaran.isk/my-claude-code-setup-heres-what-i-learned-d0403b1b1fec)
- [Understanding Claude Code's Full Stack](https://alexop.dev/posts/understanding-claude-code-full-stack/)

**Configuration Management:**
- [Configuration Management Best Practices](https://cloudaware.com/blog/configuration-management-best-practices/)
- [Configuration Drift Detection](https://spacelift.io/blog/what-is-configuration-drift)
- [50 Cloud Misconfiguration Statistics For 2025–2026](https://www.datastackhub.com/insights/cloud-misconfiguration-statistics/)

**Technical Implementation:**
- [Cross-platform dotfile Management with dotbot](https://brianschiller.com/blog/2024/08/05/cross-platform-dotbot/)
- [Fixing Git Symlink Issues on Windows](https://sqlpey.com/git/fixing-git-symlink-issues-windows/)
- [fswatch - Cross-platform file change monitor](https://github.com/emcrisostomo/fswatch)
- [a quick review of file watchers](https://anarc.at/blog/2019-11-20-file-monitoring-tools/)
- [FileSystem Watcher: Consider polling API](https://github.com/dotnet/runtime/issues/17111)
- [Schema Validation for TOML](https://json-schema-everywhere.github.io/toml)
- [TOML schema validation discussion](https://github.com/toml-lang/toml/discussions/1038)

**Adapter Pattern:**
- [Adapter Pattern - Refactoring.Guru](https://refactoring.guru/design-patterns/adapter)
- [Plugin Architecture Design Pattern](https://www.devleader.ca/2023/09/07/plugin-architecture-design-pattern-a-beginners-guide-to-modularity/)

**Existing Tools:**
- [skillshare](https://github.com/runkids/skillshare)
- [cmux](https://www.cmux.dev/)
- [One Gateway for 3 CLIs](https://evolink.ai/blog/one-endpoint-coding-clis)
- [DotState](https://dotstate.serkan.dev/)
- [chezmoi](https://www.chezmoi.io/)

---
*Research completed: 2026-02-13*
*Ready for roadmap: yes*
