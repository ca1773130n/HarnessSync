# Claude Code Changes: September 2025 - March 2026

Research compiled 2026-03-19. Focused on changes affecting HarnessSync.

---

## 1. Plugin System (v2.0.12, October 9, 2025)

**Major new feature.** Extends Claude Code with custom commands, agents, hooks, and MCP servers distributed through marketplaces.

- `/plugin install`, `/plugin enable/disable`, `/plugin marketplace`, `/plugin validate` commands
- Repository-level plugin config via `extraKnownMarketplaces` in settings.json
- Plugin config in settings.json: `enabledPlugins`, `extraKnownMarketplaces`, `strictKnownMarketplaces`
- Plugin output styles: sharing and installing output styles (v2.0.38)
- Output styles frontmatter: `keep-coding-instructions` option (v2.0.37)
- Plugin autoupdate setting: `FORCE_AUTOUPDATE_PLUGIN` env var (v2.1.2)
- `CLAUDE_CODE_PLUGIN_SEED_DIR` supports multiple seed directories (v2.1.79)
- `CLAUDE_CODE_PLUGIN_GIT_TIMEOUT_MS` to configure git timeout (default 30s -> 120s)
- Custom npm registries and version pinning for npm plugin sources
- `--plugin-dir` local dev copies override installed marketplace plugins (v2.1.74)
- Managed marketplace restrictions via `strictKnownMarketplaces` (managed-settings only)
- Plugin-provided MCP server deduplication to suppress duplicate connections (v2.1.71)

**HarnessSync Impact:** New config sections (`enabledPlugins`, `extraKnownMarketplaces`) in settings.json need to be read by SourceReader. Plugin-provided hooks/commands/MCP servers overlap with what HarnessSync already syncs.

---

## 2. Hooks System Changes

### HTTP Hooks (v2.1.63, February 28, 2026)
- New hook type: POST JSON to a URL and receive JSON instead of running a shell command
- Settings: `allowedHttpHookUrls` (URL pattern allowlist with `*` wildcard)
- Settings: `httpHookAllowedEnvVars` (env var allowlist for header interpolation)
- Setting: `allowManagedHooksOnly` (managed-settings only) blocks user/project/plugin hooks

### New Hook Events
- `Elicitation` and `ElicitationResult` hooks (v2.1.76, March 14, 2026) - intercept and override MCP elicitation responses
- `PostCompact` hook (v2.1.76) - fires after context compaction completes
- `PermissionRequest` hooks can now process 'always allow' suggestions (v2.0.54, November 26, 2025)
- `Notification` hook events with matcher values (v2.0.37, November 11, 2025)
- `SessionEnd` hooks fixed to fire on interactive `/resume` session switch (v2.1.79)
- `SessionStart` hooks: `agent_type` field added to input (v2.1.2)
- `SessionStart` hooks firing twice on `--resume`/`--continue` fixed (v2.1.73)

### Hook Security
- `statusLine` and `fileSuggestion` hook commands: security fix for execution without workspace trust (v2.1.69)
- Async hook completion messages suppressed by default (v2.1.75)

**HarnessSync Impact:** HTTP hooks are a new hook format alongside shell command hooks. New hook events (Elicitation, ElicitationResult, PostCompact) need adapter support. Hook security settings need syncing.

---

## 3. Settings.json Changes

### New Settings (Sync-Relevant)
| Setting | Version | Description |
|---------|---------|-------------|
| `autoMemoryDirectory` | v2.1.74 | Custom directory for auto-memory storage. Not allowed in project settings. |
| `modelOverrides` | v2.1.73 | Map model picker entries to custom model IDs (e.g. Bedrock inference profile ARNs) |
| `worktree.symlinkDirectories` | v2.1.76 | Directories to symlink in worktrees |
| `worktree.sparsePaths` | v2.1.76 | Directories to sparse-checkout in worktrees |
| `language` | v2.1.69 | Configure Claude's response language (e.g., "japanese") |
| `respectGitignore` | v2.1.69 | Control @-mention file picker behavior |
| `enabledPlugins` | v2.0.12 | Map of enabled plugins with versions |
| `extraKnownMarketplaces` | v2.0.12 | Repository-level marketplace config |
| `strictKnownMarketplaces` | v2.0.12+ | Managed-only: restrict allowed marketplaces |
| `companyAnnouncements` | v2.0.32 | Display announcements on startup |
| `attribution` | Recent | Customize git commit/PR attribution text |
| `cleanupPeriodDays` | Recent | Session cleanup period (default 30 days) |
| `allowedHttpHookUrls` | v2.1.63 | HTTP hook URL allowlist |
| `httpHookAllowedEnvVars` | v2.1.63 | HTTP hook env var allowlist |
| `allowManagedHooksOnly` | v2.1.63 | Block non-managed hooks |
| `allowManagedPermissionRulesOnly` | Recent | Block non-managed permission rules |
| `feedbackSurveyRate` | v2.1.76 | Enterprise survey sample rate |
| `spinnerTipsOverride` | v2.1.45 | Custom spinner tips |
| `showTurnDuration` | v2.1.79 | Show turn duration (in ~/.claude.json, NOT settings.json) |
| `terminalProgressBarEnabled` | Recent | Terminal progress bar toggle (in ~/.claude.json) |

### Deprecated/Migrated Settings
- `ignorePatterns` migrated to `permissions.deny` in localSettings (v2.0.35, November 6, 2025)
- `includeCoAuthoredBy` deprecated in favor of `attribution` setting
- Windows managed settings path changed: `C:\ProgramData\ClaudeCode\` -> `C:\Program Files\ClaudeCode\` (v2.1.75)

### Permission System Changes
- `permissions.deny` replaces `ignorePatterns` for excluding sensitive files
- Wildcard pattern matching for Bash tool permissions: `Bash(npm *)`, `Bash(* install)`, `Bash(git * main)` (v2.1.69)
- Managed policy `ask` rules can no longer be bypassed by user `allow` rules or skill `allowed-tools` (v2.1.74)

**HarnessSync Impact:** Many new settings need to be read from SourceReader and potentially mapped to target harness equivalents. Permission model changes (wildcard patterns, deny syntax) affect how permissions are translated.

---

## 4. Memory / CLAUDE.md Changes

- `@include` directives in CLAUDE.md files (v2.1.2+): fixed binary files being accidentally included
- `autoMemoryDirectory` setting for custom auto-memory location (v2.1.74)
- Project configs & auto memory now shared across git worktrees (v2.1.63)
- Last-modified timestamps added to memory files (v2.1.75)
- Large tool outputs (>50K chars, previously 100K) persisted to disk (v2.1.2)
- Large bash command outputs saved to disk instead of truncated (v2.1.2)

**HarnessSync Impact:** `@include` directives in CLAUDE.md mean SourceReader may need to resolve includes. `autoMemoryDirectory` changes where memory files live.

---

## 5. MCP Server Changes

- MCP elicitation support: servers can request structured input mid-task (v2.1.76)
- `ENABLE_CLAUDEAI_MCP_SERVERS=false` env var to opt out of claude.ai MCP servers (v2.1.63)
- Claude.ai MCP connectors now usable in Claude Code (v2.1.46, February 18, 2026)
- MCP OAuth flow improvements: manual URL paste fallback (v2.1.63)
- MCP tool/resource cache leak fixes on server reconnect (v2.1.63)
- `.mcp.json` servers fixed to load with `--dangerously-skip-permissions` (v2.0.71)
- MCP specification version: 2025-03-26 (current)

**HarnessSync Impact:** MCP elicitation is a new capability. Claude.ai connectors as MCP servers is new. The MCP config format in `.mcp.json` appears unchanged.

---

## 6. Skills / Agents / Subagents

- Automatic skill hot-reload: skills in `~/.claude/skills` or `.claude/skills` available without restart (v2.1.69)
- Skill frontmatter: `context: fork` to run in a forked sub-agent context (v2.1.69)
- Skill frontmatter: `agent` field to specify agent type for execution (v2.1.69)
- Skill `allowed-tools` now properly applied to tools invoked by the skill (v2.0.74)
- Explore subagent introduced, powered by Haiku for efficient codebase search (v2.0.17, October 15, 2025)
- Subagents with `model: opus`/`sonnet`/`haiku` fixed for Bedrock/Vertex/Foundry (v2.1.73)
- Agent teams: footer hint improved (v2.1.75)
- `.claude/agents/` directory: spurious warnings for non-agent markdown files fixed (v2.1.43)

**HarnessSync Impact:** New skill frontmatter fields (`context`, `agent`) need to be understood by SourceReader. Skills are hot-reloaded, so the sync tool should handle this gracefully.

---

## 7. Model Changes

- Opus 4.5 released (v2.0.51, November 24, 2025)
- Sonnet 4.6 support added (v2.1.45, February 17, 2026)
- Opus 4.6 with 1M context window by default for Max/Team/Enterprise (v2.1.75, March 13, 2026)
- Opus 4.6 defaults to medium effort for Max/Team (v2.1.68, March 4, 2026)
- Effort levels simplified to low/medium/high (removed max), symbols: circle-empty/circle-half/circle-full
- Opus 4 and 4.1 removed from first-party API (v2.1.68)
- Default max output tokens for Opus 4.6: 64k (upper bound 128k)
- `/effort` slash command added (v2.1.76)

---

## 8. New Tools & Commands

- LSP tool: go-to-definition, find references, hover documentation (v2.0.74, December 19, 2025)
- `/loop` command: run prompts on recurring interval (v2.1.71, March 7, 2026)
- Cron scheduling tools for recurring prompts (v2.1.71)
- `/simplify` and `/batch` bundled slash commands (v2.1.63)
- `/color` command: set prompt-bar color (v2.1.75)
- `/effort` command: set model effort level (v2.1.76)
- `/remote-control` in VSCode: bridge to claude.ai/code (v2.1.79)
- `claude remote-control` CLI subcommand (v2.1.51)
- `/plan` optional description argument (v2.1.69)
- Read tool: `pages` parameter for PDFs (v2.1.69)
- Voice mode / voice dictation (v2.1.69+)
- Chrome extension (beta) for browser integration

---

## 9. Configuration File Locations (Current State)

| File | Scope | Purpose |
|------|-------|---------|
| `~/.claude.json` | User | Preferences, OAuth, MCP servers (user scope), per-project state, caches |
| `~/.claude/settings.json` | User | User-level settings (permissions, env, hooks) |
| `~/.claude/settings.local.json` | User-local | Local user settings (not synced) |
| `.claude/settings.json` | Project | Project-level settings (version-controlled) |
| `.claude/settings.local.json` | Project-local | Local project settings (not synced) |
| `.mcp.json` | Project | Project-scoped MCP servers (version-controlled) |
| `CLAUDE.md` | Project | Instructions/memory (supports `@include`) |
| `~/.claude/CLAUDE.md` | User | User-level instructions |
| `.claude/skills/` | Project | Project skills |
| `~/.claude/skills/` | User | User-level skills |
| `.claude/agents/` | Project | Project subagents |
| `~/.claude/agents/` | User | User-level subagents |
| `commands/` | Project | Slash command markdown definitions |
| `~/.claude/commands/` | User | User-level slash commands |
| `hooks/hooks.json` | Project | Hook definitions (auto-loaded by convention) |
| Managed settings | Enterprise | `C:\Program Files\ClaudeCode\managed-settings.json` (Windows) or MDM/OS-level |

---

## 10. Key Environment Variables (New/Changed)

| Variable | Purpose |
|----------|---------|
| `CLAUDE_CODE_PLUGIN_SEED_DIR` | Multiple seed directories (path-delimiter separated) |
| `CLAUDE_CODE_PLUGIN_GIT_TIMEOUT_MS` | Plugin git timeout (default 120s) |
| `FORCE_AUTOUPDATE_PLUGIN` | Force plugin autoupdate even when main auto-updater disabled |
| `ENABLE_CLAUDEAI_MCP_SERVERS` | Set to `false` to opt out of claude.ai MCP servers |
| `CLAUDE_CODE_EXIT_AFTER_STOP_DELAY` | Auto-exit SDK mode after idle duration |
| `CLAUDE_CODE_TMPDIR` | Override temp directory for internal files |
| `CLAUDE_CODE_DISABLE_TERMINAL_TITLE` | Prevent terminal title changes |
| `IS_DEMO` | Hide email/org from UI |
| `BASH_DEFAULT_TIMEOUT_MS` | Customize bash auto-background timeout |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | Override default Haiku model (for 3P providers) |

---

## Summary: Top Priorities for HarnessSync

1. **Plugin system support** - New config keys in settings.json (`enabledPlugins`, `extraKnownMarketplaces`). SourceReader should discover and read these.
2. **HTTP hooks** - New hook format alongside shell command hooks. Adapters need to handle both types.
3. **New hook events** - Elicitation, ElicitationResult, PostCompact, Notification matchers. Hook sync logic needs updating.
4. **Permission model changes** - `permissions.deny` replaces `ignorePatterns`, wildcard patterns in Bash permissions, managed policy enforcement changes.
5. **New settings** - `autoMemoryDirectory`, `modelOverrides`, `worktree.*`, `language`, `respectGitignore`, `attribution`, hook security settings.
6. **Skill frontmatter changes** - `context: fork` and `agent` fields are new.
7. **@include directives in CLAUDE.md** - SourceReader may need to resolve these.
8. **MCP elicitation** - New MCP capability that may need adapter support.
9. **Large output disk persistence** - Tool outputs >50K chars go to disk; if HarnessSync reads transcripts, this matters.
10. **Claude.ai MCP connectors** - New source of MCP servers beyond `.mcp.json`.

Sources:
- https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md
- https://code.claude.com/docs/en/changelog
- https://code.claude.com/docs/en/settings
- https://code.claude.com/docs/en/permissions
