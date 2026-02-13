# Feature Research

**Domain:** AI Harness Configuration Sync Tools
**Researched:** 2026-02-13
**Confidence:** HIGH

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Bidirectional sync** | Users switch between CLIs and expect changes to propagate back | HIGH | Current cc2all is unidirectional (Claude → all). Users need reverse sync or will manually edit targets. |
| **Automatic trigger on CLI invocation** | "It just works" - no manual sync step | MEDIUM | Shell wrapper pattern (current) works but fragile. Hook-based better. |
| **Dry run mode** | Preview changes before applying | LOW | Safety net for high-stakes configs. Already implemented. |
| **Conflict detection & resolution** | When same config edited in multiple places | HIGH | Requires state tracking + merge strategies. Drift is #1 pain point. |
| **Watch mode for real-time sync** | Dev modifies Claude config, sees it instantly elsewhere | MEDIUM | fswatch/inotify implemented. Battery/CPU overhead concern. |
| **State tracking (what's synced when)** | Avoid re-syncing unchanged files, detect drift | MEDIUM | Basic state file exists. Needs hash comparison + timestamp tracking. |
| **Symlink support for plugin caches** | Plugin update → instant propagation without re-sync | LOW | Implemented for Codex/OpenCode. Gemini needs inline (no symlink support). |
| **Scope isolation (user vs project)** | Different configs per project, global defaults | MEDIUM | Implemented. Standard pattern across all target CLIs. |
| **MCP server translation** | Each CLI has different MCP format (TOML vs JSON) | HIGH | Format differences + env var handling + URL vs command. Complex mapping. |
| **Rollback/undo** | "Sync broke my setup, restore previous" | MEDIUM | Config backup before changes. State file enables restore. |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Semantic config translation** | Translate Claude agent → Codex skill intelligently, not just copy | HIGH | Current: dumb conversion (wrap in SKILL.md). Smart: extract tools, permissions, adapt to target constraints. |
| **Permission model normalization** | Claude's allowedTools → Codex sandbox → Gemini YOLO → OpenCode permission | HIGH | Killer feature. Settings drift happens because permission models incompatible. Need policy engine. |
| **Env var propagation with secrets detection** | Sync env vars but warn/redact secrets (API keys, tokens) | MEDIUM | Target CLIs have redaction (Gemini's allowedVariables, Codex's env filter). Source-side detection missing. |
| **Validation before sync** | Check target CLI supports feature before syncing (e.g., Gemini can't symlink skills) | MEDIUM | Prevents broken configs. Schema validation per target. |
| **Merge strategies (not just overwrite)** | User customized Codex config → don't nuke it, merge Claude additions | HIGH | Current: overwrite between markers. Better: 3-way merge (base, source, target). |
| **Hooks for custom transformations** | Project-specific rules: "skill X → rename to Y in Codex" | MEDIUM | Plugin architecture. `.cc2all/hooks/pre-sync.sh` or JS callbacks. |
| **Config drift reports** | Daily/weekly summary: "GEMINI.md diverged from CLAUDE.md, 12 lines" | MEDIUM | Scheduled diff + notification. Helps teams spot unauthorized changes. |
| **Team sharing via git** | Commit `.cc2all/sync-rules.json` to repo, team gets same mappings | LOW | Dotfile manager pattern. Makes sync behavior version-controlled. |
| **Profile support** | "work" profile → exclude personal skills, "home" profile → full sync | MEDIUM | Codex has profiles. Extend to sync tool: `cc2all sync --profile work`. |
| **AI-assisted conflict resolution** | When merge conflict, ask Claude to resolve it | HIGH | Use Claude API to analyze diffs and propose resolution. Novel feature. |
| **Cross-CLI skill catalog** | `cc2all skills list --all-clis` shows what's available everywhere | LOW | Convenience. Helps users discover skills they forgot in other CLIs. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **GUI/TUI dashboard** | "I want to see sync status visually" | Scope creep. CLI tool should stay CLI. Adds maintenance burden. | Provide `cc2all status --format json`, let users build dashboards if wanted. |
| **Support for non-AI CLIs** | "Can you sync to my tmux.conf too?" | Mission creep. Becomes generic dotfile manager (chezmoi already exists). | Stay focused: AI harness configs only. Refer to chezmoi for general dotfiles. |
| **Sync to cloud (Dropbox, Drive)** | "Backup my configs to cloud" | Security nightmare (API keys in configs). Adds external dependencies. | Git is sufficient. Users can commit `.claude/` to private repo. |
| **Full bidirectional auto-merge** | "Just keep everything in sync automatically" | Impossible to avoid conflicts safely. Race conditions, data loss risk. | Explicit sync direction. Detect conflicts, require manual resolution. |
| **Support for legacy CLIs (Cursor, Aider)** | "I still use Cursor, sync to it" | Legacy formats, unmaintained, high support burden. | Provide migration guide to supported CLIs. Don't support deprecated tools. |
| **Real-time collaborative editing** | "Team edits same config, see changes live" | Operational Transform complexity. Websocket infrastructure. Out of scope. | Git-based workflow: commit, pull, sync. Proven pattern. |
| **Auto-install target CLIs** | "Detect Codex missing, install it for me" | Package manager hell (Homebrew vs npm vs cargo). Permissions issues. | Assumption: user already has CLIs installed. Provide install guide. |

## Feature Dependencies

```
[Conflict Detection] → requires → [State Tracking]
[Rollback] → requires → [State Tracking] + [Backup]
[Semantic Translation] → requires → [Validation]
[AI Conflict Resolution] → requires → [Conflict Detection]
[Merge Strategies] → requires → [State Tracking]
[Permission Normalization] → requires → [Validation]
[Drift Reports] → requires → [State Tracking]
[Profile Support] → enhances → [Scope Isolation]
[Hooks] → enhances → [Semantic Translation]
```

## Target CLI Configuration Support Matrix

### Codex CLI

**Config Format:** TOML (`~/.codex/config.toml`, `.codex/config.toml`)

**Key Capabilities:**
- **Rules:** `AGENTS.md` file (markdown)
- **Skills:** Symlink support to `~/.codex/skills/` and `.agents/skills/`
- **Agents:** NO native support → convert to skills
- **Commands:** NO native support → convert to skills
- **MCP:** `[mcp_servers."name"]` in TOML with `command`, `args`, `env`
- **Permissions:** `sandbox = "read-only" | "workspace-write" | "danger-full-access"`
- **Env vars:** `[shell_environment_policy]` with `include_only` allowlist
- **Scope:** User (`~/.codex/`) + Project (`.codex/`)
- **Profiles:** YES - multi-profile support experimental

**Limitations:**
- No agent system (must convert to skills)
- No slash commands (must convert to skills)
- MCP URL-based servers less documented (command-based preferred)

**Sources:** [Codex Configuration Reference](https://developers.openai.com/codex/config-reference/), [Config basics](https://developers.openai.com/codex/config-basic)

### Gemini CLI

**Config Format:** JSON (`~/.gemini/settings.json`, `.gemini/settings.json`)

**Key Capabilities:**
- **Rules:** `GEMINI.md` file (markdown, hierarchical loading)
- **Skills:** NO symlink support → must inline into GEMINI.md
- **Agents:** Inline into GEMINI.md as sections
- **Commands:** Brief descriptions in GEMINI.md
- **MCP:** `mcpServers` object with `command`, `args`, `env`, `url`, `httpUrl`
- **Permissions:** `yolo` mode (disable approvals), `tools.allowedTools` / `tools.blockedTools`
- **Env vars:** `.gemini/.env` file + `security.allowedEnvVars` / `blockedEnvVars`
- **Scope:** User (`~/.gemini/`) + Project (`.gemini/`)
- **Extensions:** YES - `experimental.extensionManagement`

**Limitations:**
- No symlink support for skills (forces file duplication)
- GEMINI.md size can balloon with many skills
- Context file concatenation limited to 200 directories
- No profile support

**Sources:** [Gemini CLI Configuration](https://geminicli.com/docs/get-started/configuration/), [GEMINI.md Files](https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html)

### OpenCode

**Config Format:** JSON/JSONC (`opencode.json`, `~/.config/opencode/opencode.json`)

**Key Capabilities:**
- **Rules:** `AGENTS.md` file + `instructions` paths in config
- **Skills:** Symlink support to `~/.config/opencode/skills/` and `.opencode/skills/`
- **Agents:** YES - `.opencode/agents/*.md` (native support, compatible with Claude format)
- **Commands:** YES - `.opencode/commands/*.md` (native support)
- **MCP:** `mcp` object with `command`, `args`, `env`, `type: "remote"` for URLs
- **Permissions:** `permission = "ask"` (approval mode)
- **Env vars:** `{env:VAR_NAME}` substitution in config
- **Scope:** Global (`~/.config/opencode/`) + Project (`opencode.json`)
- **Claude Code compatibility:** YES - reads `~/.claude/` as fallback

**Limitations:**
- Newer CLI, smaller ecosystem than Codex/Gemini
- Less documentation on advanced features
- No native profile support

**Sources:** [OpenCode Config](https://opencode.ai/docs/config/), [OpenCode Agents](https://opencode.ai/docs/agents/)

## Configuration Translation Challenges

### MCP Server Formats

**Challenge:** Each CLI uses different MCP config syntax.

| CLI | Format | URL Support | Env Vars |
|-----|--------|-------------|----------|
| Claude Code | `.mcp.json` with `mcpServers` object | `"url"` field | `"env": {}` |
| Codex | TOML `[mcp_servers."name"]` | `type = "url"` + `url` | `[mcp_servers."name".env]` |
| Gemini | JSON `mcpServers` object | `"url"` or `"httpUrl"` | `"env": {}` |
| OpenCode | JSON `mcp` object | `"type": "remote"` + `"url"` | `"env": {}` |

**Complexity:** HIGH - requires format translator + validation.

**Current Implementation:** Separate functions per target (`_build_codex_mcp_toml`, `_sync_gemini_mcp`, `_sync_opencode_mcp`).

### Permission Model Mapping

**Challenge:** Incompatible permission philosophies.

| Claude Code | Codex | Gemini | OpenCode |
|-------------|-------|--------|----------|
| `allowedTools: ["write", "bash"]` | `sandbox = "workspace-write"` | `yolo = false` + `tools.allowedTools` | `permission = "ask"` |

**Problem:** Claude's granular tool list doesn't map 1:1 to Codex's coarse sandbox levels.

**Current Implementation:** Settings sync exists but NO intelligent mapping. Just copies env vars.

**Needed:** Policy engine:
- `allowedTools: ["read"]` → Codex `sandbox = "read-only"`
- `allowedTools: ["write", "bash"]` → Codex `sandbox = "workspace-write"`
- `allowedTools: ["*"]` → Codex `sandbox = "danger-full-access"` (warn!)

### Skills/Agents/Commands Conversion

**Challenge:** Feature parity gaps.

| Feature | Claude Code | Codex | Gemini | OpenCode |
|---------|-------------|-------|--------|----------|
| Skills | ✅ Symlink | ✅ Symlink | ❌ Inline only | ✅ Symlink |
| Agents | ✅ Native | ❌ Convert to skill | ❌ Inline to GEMINI.md | ✅ Native |
| Commands | ✅ Native | ❌ Convert to skill | ❌ Describe in GEMINI.md | ✅ Native |

**Complexity:** HIGH for Gemini (no symlinks, must inline everything).

**Current Implementation:**
- Codex: Agents → `agent-{name}` skill, Commands → `cmd-{name}` skill ✅
- Gemini: Agents/Commands → inline to GEMINI.md ✅
- OpenCode: Agents/Commands → symlink ✅

### Scope Semantics

**Challenge:** Slightly different scope precedence.

| CLI | User Scope | Project Scope | Merge Behavior |
|-----|------------|---------------|----------------|
| Claude Code | `~/.claude/` | `.claude/`, `CLAUDE.md` | Project overrides user |
| Codex | `~/.codex/` | `.codex/` (trusted projects only) | Closest wins |
| Gemini | `~/.gemini/` | `.gemini/`, `GEMINI.md` | Hierarchical concatenation |
| OpenCode | `~/.config/opencode/` | `opencode.json`, `.opencode/` | Merge with later override |

**Complexity:** MEDIUM - mostly compatible, but Gemini's concatenation is unique.

## MVP Definition

### Launch With (v1.0 - Plugin Rewrite)

- [x] **Unidirectional sync (Claude → all)** - Already implemented in Python
- [ ] **State tracking with change detection** - Upgrade from basic state file to hash-based diffing
- [ ] **Conflict detection (warn only, no auto-resolve)** - Detect drift, surface to user
- [ ] **Dry run mode** - Already implemented, keep it
- [ ] **Watch mode** - Already implemented, keep it
- [ ] **MCP translation for all targets** - Already implemented, keep it
- [ ] **Permission model validation** - Warn when Claude config incompatible with target
- [ ] **Rollback support** - Backup before sync, restore on failure
- [ ] **Shell integration (hooks)** - Already implemented, port to plugin hooks
- [ ] **Slash command interface** - `/sync`, `/sync status`, `/sync rollback`
- [ ] **Scope isolation (user/project)** - Already implemented, keep it

**Why these?** Minimum to replace Python script with feature parity + safety (validation, rollback).

### Add After Validation (v1.x)

- [ ] **Bidirectional sync** - User edits Codex, detect and pull back to Claude (complex, needs user testing first)
- [ ] **Merge strategies** - 3-way merge instead of overwrite (requires conflict resolution UX)
- [ ] **Semantic translation** - Smart agent → skill conversion (extract tools, adapt permissions)
- [ ] **Permission normalization** - Auto-map Claude allowedTools → Codex sandbox levels
- [ ] **Drift reports** - Scheduled diffs with notifications
- [ ] **Hooks for custom transformations** - `.cc2all/hooks/` with JS/shell scripts
- [ ] **Profile support** - `cc2all sync --profile work`
- [ ] **Team sharing** - Version-controlled sync rules

**Trigger for adding:** User requests for reverse sync + merge conflicts in production use.

### Future Consideration (v2+)

- [ ] **AI-assisted conflict resolution** - Use Claude API to propose merge resolutions
- [ ] **Cross-CLI skill catalog** - Unified view of all skills across CLIs
- [ ] **Plugin marketplace integration** - Auto-install skills when referenced
- [ ] **Config linting** - Pre-sync validation against target CLI schemas
- [ ] **Migration wizard** - First-time setup to import existing CLI configs

**Why defer:**
- AI conflict resolution: Novel but risky. Need v1 data to train prompts.
- Skill catalog: Nice-to-have, not critical path.
- Plugin marketplace: Depends on Claude Code plugin ecosystem maturity.

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| State tracking + change detection | HIGH | MEDIUM | **P0** (Foundation for everything else) |
| Conflict detection | HIGH | MEDIUM | **P0** (Prevents data loss) |
| Rollback support | HIGH | LOW | **P0** (Safety net) |
| Permission validation | HIGH | MEDIUM | **P0** (Prevents broken configs) |
| Slash command interface | HIGH | LOW | **P0** (Plugin UX requirement) |
| Bidirectional sync | HIGH | HIGH | **P1** (Complex, defer to v1.1) |
| Semantic translation | MEDIUM | HIGH | **P1** (Differentiator but non-critical) |
| Merge strategies | MEDIUM | HIGH | **P1** (Needed for bidirectional) |
| Drift reports | MEDIUM | MEDIUM | **P2** (Nice-to-have) |
| Hooks | MEDIUM | MEDIUM | **P2** (Power users only) |
| Profile support | MEDIUM | LOW | **P2** (Niche use case) |
| AI conflict resolution | LOW | HIGH | **P3** (Experimental) |
| Skill catalog | LOW | MEDIUM | **P3** (Convenience) |

## Competitive Landscape

### Existing Tools (as of Feb 2026)

**skillshare** ([GitHub](https://github.com/runkids/skillshare)) - Sync skills across Claude Code, OpenClaw, OpenCode. Non-destructive merge mode.
- **Gap:** Skills only, no rules/MCP/settings. No intelligent translation.

**claude_code_bridge** ([GitHub](https://github.com/bfly123/claude_code_bridge)) - Multi-AI collaboration with persistent context.
- **Gap:** Real-time collab (anti-feature for us). Not about config sync.

**cmux** ([cmux.dev](https://www.cmux.dev/)) - Run multiple CLIs in parallel.
- **Gap:** Execution orchestration, not config management.

**One Gateway approach** ([evolink.ai](https://evolink.ai/blog/one-endpoint-coding-clis)) - Route all CLIs through single LLM gateway.
- **Gap:** API proxying, not config sync. Different problem space.

**Dotfile managers (chezmoi, DotState)** - General-purpose config sync.
- **Gap:** No AI CLI semantics. No MCP translation. No permission mapping.

### HarnessSync's Differentiation

**What we do better:**
1. **AI harness specialization** - Deep knowledge of Claude/Codex/Gemini/OpenCode formats
2. **Semantic translation** - Agents → Skills with intelligence, not just file copy
3. **Permission normalization** - Map incompatible permission models
4. **MCP translation** - Handle TOML ↔ JSON + URL vs command differences
5. **Built for Claude Code first** - Native integration as plugin, not external tool

**What competitors don't do:**
- Validate before sync (prevent broken configs)
- Detect permission model incompatibilities
- Provide rollback
- Track sync state and drift
- Offer conflict resolution (planned)

## User Pain Points (Inferred from Research)

### Settings Drift
**Problem:** User configures Claude, switches to Codex, realizes permissions are different, manually fixes Codex, forgets what they changed, Claude and Codex diverge.

**Solution:** Drift detection + reports. Permission normalization to prevent divergence.

### Feature Parity Gaps
**Problem:** Gemini doesn't support agent symlinks, so syncing creates huge GEMINI.md file. User edits it manually, now it's out of sync with Claude.

**Solution:** Validation warnings ("Gemini will inline N skills, ~50KB GEMINI.md"). Bidirectional sync to pull changes back.

### MCP Format Confusion
**Problem:** User defines MCP server in Claude's `.mcp.json`, expects it to work in Codex, but Codex uses TOML. Manually translates, makes typo, server won't start.

**Solution:** Automatic translation with validation. Test that generated TOML is parseable.

### Team Coordination
**Problem:** Team member adds skill to Claude, syncs locally. Other team members don't know skill exists. Manual "hey everyone run cc2all sync" messages.

**Solution:** Git-based workflow. Commit `.cc2all/sync-state.json` and sync rules. CI/CD hook to validate on PR.

### Rollback Fear
**Problem:** "What if sync breaks my Codex setup?" User avoids syncing, maintains separate configs manually (defeating the purpose).

**Solution:** Automatic backup before sync. Easy rollback: `cc2all sync rollback`. Show diff before applying.

## Sources

**Codex CLI:**
- [Configuration Reference](https://developers.openai.com/codex/config-reference/)
- [Config Basics](https://developers.openai.com/codex/config-basic)
- [Advanced Configuration](https://developers.openai.com/codex/config-advanced/)

**Gemini CLI:**
- [Gemini CLI Configuration](https://geminicli.com/docs/get-started/configuration/)
- [GEMINI.md Files](https://google-gemini.github.io/gemini-cli/docs/cli/gemini-md.html)
- [Settings Documentation](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/settings.md)

**OpenCode:**
- [OpenCode Config](https://opencode.ai/docs/config/)
- [OpenCode Agents](https://opencode.ai/docs/agents/)
- [OpenCode CLI](https://opencode.ai/docs/cli/)

**Configuration Management Best Practices:**
- [Configuration Management Best Practices](https://cloudaware.com/blog/configuration-management-best-practices/)
- [Configuration Drift Detection](https://spacelift.io/blog/what-is-configuration-drift)
- [Infrastructure Drift Detection](https://spacelift.io/blog/drift-detection)

**Dotfile Managers:**
- [DotState](https://dotstate.serkan.dev/)
- [chezmoi](https://www.chezmoi.io/)
- [dotfiles.github.io](https://dotfiles.github.io/utilities/)

**Multi-CLI Tools:**
- [skillshare](https://github.com/runkids/skillshare)
- [cmux](https://www.cmux.dev/)
- [One Gateway for 3 CLIs](https://evolink.ai/blog/one-endpoint-coding-clis)

---
*Feature research for: AI Harness Configuration Sync Tools*
*Researched: 2026-02-13*
