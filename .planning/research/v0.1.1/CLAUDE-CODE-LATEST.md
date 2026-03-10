# Claude Code Configuration Changes: What HarnessSync Is Missing

**Researched:** 2026-03-09
**Sources:** Official docs at code.claude.com, GitHub changelog, web research
**Overall confidence:** HIGH (verified against official docs)

## Executive Summary

Claude Code has evolved significantly since HarnessSync's initial implementation. The biggest gaps are: (1) the `.claude/rules/` directory system with path-scoped YAML frontmatter, (2) the expanded hooks system now in settings.json, (3) managed/enterprise config tiers, (4) agent-memory directories, and (5) several new CLAUDE.md locations we partially cover but may not fully handle. Below is a detailed delta analysis.

---

## 1. NEW: `.claude/rules/` Directory (HIGH priority gap)

**Status:** NOT supported by HarnessSync
**Confidence:** HIGH (official docs at code.claude.com/docs/en/memory)

This is a significant new configuration surface. Rules are modular markdown files that replace or supplement large CLAUDE.md files.

### Locations
- `~/.claude/rules/*.md` -- User-level rules (all projects)
- `.claude/rules/*.md` -- Project-level rules (checked into git)
- Recursive subdirectory discovery (e.g., `.claude/rules/frontend/components.md`)
- Symlinks supported and resolved

### Format
Rules are markdown files with **optional YAML frontmatter** for path-scoping:

```markdown
---
paths:
  - "src/api/**/*.ts"
  - "lib/**/*.{ts,tsx}"
---

# API Development Rules

- All API endpoints must include input validation
```

Rules WITHOUT a `paths` field load unconditionally (same as CLAUDE.md).
Rules WITH a `paths` field only load when Claude works with matching files.

### Priority
- User-level rules load before project rules
- Project rules have higher priority
- Same priority level as `.claude/CLAUDE.md`

### Impact on HarnessSync
This is a **new config type** that needs its own discovery in SourceReader and translation logic in adapters. The path-scoping frontmatter is Claude Code-specific and has no direct equivalent in other CLIs, but the rule content itself can be synced as instruction text.

---

## 2. NEW: Hooks System in settings.json (MEDIUM priority gap)

**Status:** HarnessSync reads settings.json but does NOT parse or sync hooks
**Confidence:** HIGH (official docs at code.claude.com/docs/en/hooks)

Hooks are now a first-class config section in settings.json. They are NOT the same as the plugin `hooks/hooks.json` files HarnessSync already handles.

### Hook Events (16 total)
| Event | Description |
|-------|-------------|
| `SessionStart` | Session begins or resumes |
| `UserPromptSubmit` | Prompt submitted |
| `PreToolUse` | Before tool execution (can block) |
| `PermissionRequest` | Permission dialog |
| `PostToolUse` | After tool succeeds |
| `PostToolUseFailure` | After tool fails |
| `Notification` | Notification sent |
| `SubagentStart` | Subagent spawned |
| `SubagentStop` | Subagent finishes |
| `Stop` | Claude finishes responding |
| `TeammateIdle` | Agent team member idle |
| `TaskCompleted` | Task marked complete |
| `InstructionsLoaded` | CLAUDE.md or rules file loaded |
| `ConfigChange` | Config file changes |
| `WorktreeCreate` | Worktree created |
| `WorktreeRemove` | Worktree removed |
| `PreCompact` | Before context compaction |
| `SessionEnd` | Session terminates |

### Hook Types (4)
1. **`command`** -- Shell command, receives JSON on stdin
2. **`http`** -- POST to URL with JSON body, supports headers + env var interpolation
3. **`prompt`** -- Single-turn LLM evaluation (yes/no decision)
4. **`agent`** -- Spawns subagent to verify conditions

### Settings.json Format
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": ".claude/hooks/block-rm.sh",
            "timeout": 30,
            "async": false
          }
        ]
      }
    ]
  }
}
```

### Hook Locations
- `~/.claude/settings.json` -- User scope
- `.claude/settings.json` -- Project scope
- `.claude/settings.local.json` -- Local scope
- Managed policy settings -- Organization scope
- Plugin `hooks/hooks.json` -- Plugin scope (already supported)
- Skill/Agent frontmatter -- Component scope

### Impact on HarnessSync
Hooks in settings.json are Claude Code-specific. No direct equivalent in Codex/Gemini/OpenCode. HarnessSync should at minimum **preserve** hooks when reading/writing settings.json (avoid clobbering them). Syncing hooks to other CLIs is not meaningful.

---

## 3. CHANGED: Agent (Subagent) Format Expanded (MEDIUM priority gap)

**Status:** HarnessSync syncs agent .md files but may not understand all new frontmatter
**Confidence:** HIGH (official docs at code.claude.com/docs/en/sub-agents)

### New Frontmatter Fields Since Initial Implementation
| Field | Description |
|-------|-------------|
| `name` | Required, unique identifier |
| `description` | Required, when to delegate |
| `tools` | Tool allowlist |
| `disallowedTools` | Tool denylist |
| `model` | `sonnet`, `opus`, `haiku`, `inherit` |
| `permissionMode` | `default`, `acceptEdits`, `dontAsk`, `bypassPermissions`, `plan` |
| `maxTurns` | Max agentic turns |
| `skills` | Skills to preload into context |
| `mcpServers` | MCP servers for this agent |
| `hooks` | Lifecycle hooks scoped to agent |
| `memory` | Persistent memory scope: `user`, `project`, `local` |
| `background` | Run as background task |
| **`isolation`** | **NEW: Set to `worktree` for git worktree isolation** |

### Agent Memory Directories (NEW)
When `memory` is set, agents get persistent storage:
- `memory: user` -> `~/.claude/agent-memory/<agent-name>/`
- `memory: project` -> `.claude/agent-memory/<agent-name>/`
- `memory: local` -> `.claude/agent-memory-local/<agent-name>/`

Each contains a `MEMORY.md` entrypoint (first 200 lines loaded at startup).

### CLI-Defined Agents (NEW)
Agents can be passed via `--agents` CLI flag as JSON (session-only, not saved to disk).

### Impact on HarnessSync
HarnessSync already copies agent .md files. The new frontmatter fields are transparent to file copying. However, the **agent-memory directories** are a new config surface that might need awareness (though they are runtime state, not config to sync).

---

## 4. CHANGED: Skill Format Evolved (LOW priority -- mostly transparent)

**Status:** HarnessSync copies skill directories; format changes are transparent
**Confidence:** HIGH (official docs at code.claude.com/docs/en/skills)

### Current SKILL.md Frontmatter (Complete)
```yaml
---
name: my-skill
description: What this skill does
argument-hint: "[issue-number]"
disable-model-invocation: true
user-invocable: false
allowed-tools: Read, Grep, Glob
model: sonnet
context: fork
agent: Explore
hooks:
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./validate.sh"
---
```

### New Features
- **`context: fork`** -- Run skill in isolated subagent context
- **`agent` field** -- Which agent type to use with `context: fork`
- **`hooks` in frontmatter** -- Lifecycle hooks scoped to skill
- **`model` field** -- Override model for this skill
- **String substitutions:** `$ARGUMENTS`, `$ARGUMENTS[N]`, `$N`, `${CLAUDE_SESSION_ID}`, `${CLAUDE_SKILL_DIR}`
- **`!`command`` syntax** -- Shell command preprocessing (runs before skill content sent)
- **Bundled skills** -- `/simplify`, `/batch`, `/debug`, `/loop`, `/claude-api` ship built-in

### Skills Follow Agent Skills Open Standard
Skills now follow the [Agent Skills](https://agentskills.io) open standard, which works across multiple AI tools.

### Impact on HarnessSync
File-level copying is sufficient. HarnessSync does not need to parse SKILL.md frontmatter for syncing purposes. The directory structure (SKILL.md + supporting files) is preserved by current copy logic.

---

## 5. NEW: Managed/Enterprise Configuration Tier (LOW priority for personal use)

**Status:** NOT supported by HarnessSync
**Confidence:** HIGH (official docs)

### Managed Settings Locations
| OS | Settings | MCP | CLAUDE.md |
|----|----------|-----|-----------|
| macOS | `/Library/Application Support/ClaudeCode/managed-settings.json` | `/Library/Application Support/ClaudeCode/managed-mcp.json` | `/Library/Application Support/ClaudeCode/CLAUDE.md` |
| Linux/WSL | `/etc/claude-code/managed-settings.json` | `/etc/claude-code/managed-mcp.json` | `/etc/claude-code/CLAUDE.md` |
| Windows | `C:\Program Files\ClaudeCode\managed-settings.json` | `C:\Program Files\ClaudeCode\managed-mcp.json` | `C:\Program Files\ClaudeCode\CLAUDE.md` |

### Key Properties
- **Highest precedence** -- Cannot be overridden by any other scope
- Managed settings support `allowManagedHooksOnly` to block user/project hooks
- Enterprise managed MCP allowlist/denylist
- `strictKnownMarketplaces` and `blockedMarketplaces` for plugin control

### Impact on HarnessSync
These are system-level admin configs. Unlikely to need syncing for personal use. If enterprise support is added later, HarnessSync would need read access to these paths.

---

## 6. CHANGED: Settings.json Schema Expanded (MEDIUM priority)

**Status:** HarnessSync reads settings.json but may not handle all new fields
**Confidence:** HIGH (official docs)

### New/Notable Settings Fields
```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": ["Bash(npm run lint)"],
    "deny": ["Bash(curl *)"],
    "ask": ["Bash(git push *)"],
    "additionalDirectories": ["../docs/"],
    "defaultMode": "acceptEdits"
  },
  "env": {
    "VARIABLE_NAME": "value"
  },
  "sandbox": {
    "enabled": true,
    "filesystem": {
      "allowWrite": ["//tmp/build"],
      "denyWrite": ["//etc"],
      "denyRead": ["~/.aws/credentials"]
    },
    "network": {
      "allowedDomains": ["github.com"]
    }
  },
  "hooks": { "..." },
  "disableAllHooks": false,
  "model": "claude-sonnet-4-6",
  "attribution": {
    "commit": "Generated with Claude Code",
    "pr": "Generated with Claude Code"
  },
  "companyAnnouncements": ["text"],
  "autoMemoryEnabled": true,
  "claudeMdExcludes": ["**/other-team/CLAUDE.md"],
  "enabledPlugins": { "formatter@acme": true },
  "extraKnownMarketplaces": {},
  "strictKnownMarketplaces": [],
  "blockedMarketplaces": []
}
```

### Settings Precedence (highest to lowest)
1. Managed (system-level)
2. Command line arguments
3. Local (`.claude/settings.local.json`, `CLAUDE.local.md`)
4. Project (`.claude/settings.json`, `CLAUDE.md`)
5. User (`~/.claude/settings.json`, `~/.claude/CLAUDE.md`)

### Array Setting Merge Rule
Arrays are **concatenated and deduplicated** across scopes, NOT replaced.

### Impact on HarnessSync
HarnessSync's `get_settings()` uses simple `dict.update()` which replaces values. This is wrong for array fields like `permissions.allow` which should concatenate. However, fixing this is a separate concern from discovery -- the current approach works for the sync use case since we sync the merged result.

---

## 7. NEW: CLAUDE.md Import Syntax (LOW priority gap)

**Status:** NOT handled by HarnessSync
**Confidence:** HIGH (official docs)

CLAUDE.md files can now import other files using `@path/to/file` syntax:

```markdown
See @README for project overview.
@docs/git-instructions.md
@~/.claude/my-project-instructions.md
```

- Relative paths resolve relative to the CLAUDE.md file
- Absolute paths and `~/` paths supported
- Recursive imports up to 5 hops deep
- First-time imports require user approval

### Impact on HarnessSync
When syncing CLAUDE.md content, imports are NOT expanded by HarnessSync. The `@import` references would be copied literally. This could break if the imported files don't exist at the target location. For now this is acceptable -- imports are an advanced feature and the references serve as documentation.

---

## 8. NEW: Agent Teams (EXPERIMENTAL, LOW priority)

**Status:** NOT supported, experimental feature
**Confidence:** MEDIUM (requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`)

Agent teams allow multiple Claude Code sessions to work in parallel and communicate. Configuration:
- Enable via env var `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- Config at `~/.claude/teams/{team-name}/config.json`
- Tasks at `~/.claude/tasks/{team-name}/`
- Requires Opus 4.6 model
- No static agent definition files -- teams are created via natural language

### Impact on HarnessSync
Experimental feature, no static config to sync. Skip for now.

---

## 9. CHANGED: Auto Memory System (LOW priority -- runtime state)

**Status:** NOT synced (runtime state, not config)
**Confidence:** HIGH (official docs)

### Memory Locations
- `~/.claude/projects/<project>/memory/MEMORY.md` -- Per-project auto memory
- `~/.claude/agent-memory/<agent-name>/` -- Per-agent user-scope memory
- `.claude/agent-memory/<agent-name>/` -- Per-agent project-scope memory
- `.claude/agent-memory-local/<agent-name>/` -- Per-agent local-scope memory

### Properties
- `MEMORY.md` entrypoint (first 200 lines loaded per session)
- Topic files (loaded on demand)
- Enabled by default, toggle with `autoMemoryEnabled` in settings
- Machine-local, not designed for cross-machine sync

### Impact on HarnessSync
This is runtime state, not configuration. Should NOT be synced. However, HarnessSync should be aware of these directories to avoid accidentally treating them as config.

---

## 10. CHANGED: MCP Server Config -- Minor Updates

**Status:** Mostly covered by HarnessSync
**Confidence:** HIGH

### What's New
- **`managed-mcp.json`** at system paths (enterprise allowlist/denylist)
- **MCP in settings.json** via `mcpServers` field in `.claude/settings.local.json`
- **MCP in agent frontmatter** -- agents can declare their own MCP servers
- **`ENABLE_CLAUDEAI_MCP_SERVERS=false`** env var to opt out of claude.ai MCP servers
- **MCP `structuredContent` field** in tool responses

### Impact on HarnessSync
HarnessSync already handles the main MCP discovery paths. The settings.local.json MCP path might be a gap -- needs verification that settings merge captures MCP servers defined there.

---

## 11. CONFIRMED: What HarnessSync Already Handles Correctly

- `~/.claude/CLAUDE.md` (user rules) -- YES
- `./CLAUDE.md` and `.claude/CLAUDE.md` (project rules) -- YES
- `./CLAUDE.local.md` (local rules) -- YES
- `~/.claude/skills/` (user skills) -- YES
- `.claude/skills/` (project skills) -- YES
- `~/.claude/agents/` (user agents) -- YES
- `.claude/agents/` (project agents) -- YES
- `~/.claude/commands/` (user commands) -- YES
- `.claude/commands/` (project commands) -- YES
- `.mcp.json` (project MCP) -- YES
- `~/.claude.json` (user MCP) -- YES
- `~/.claude/settings.json` (user settings) -- YES
- `.claude/settings.json` (project settings) -- YES
- `.claude/settings.local.json` (local settings) -- YES
- Plugin-installed skills, agents, commands, MCP -- YES

---

## Priority Summary: What to Add

| Priority | Gap | Effort | Impact |
|----------|-----|--------|--------|
| **HIGH** | `.claude/rules/` directory (user + project) | Medium | Major new config surface, actively used |
| **MEDIUM** | Hooks in settings.json (preserve, don't clobber) | Low | Avoid data loss during settings sync |
| **MEDIUM** | Settings array merge semantics | Low | Correctness of merged settings |
| **LOW** | Agent memory directories (awareness) | Low | Avoid treating as syncable config |
| **LOW** | Managed/enterprise config paths | Low | Enterprise use case only |
| **LOW** | CLAUDE.md `@import` syntax awareness | Low | Edge case, copy-as-is is acceptable |
| **LOW** | Agent Teams config | None needed | Experimental, no static config |

---

## Sources

- [Claude Code Settings](https://code.claude.com/docs/en/settings) -- Official settings reference
- [Claude Code Skills](https://code.claude.com/docs/en/skills) -- Skills format and configuration
- [Claude Code Subagents](https://code.claude.com/docs/en/sub-agents) -- Agent format and configuration
- [Claude Code Hooks](https://code.claude.com/docs/en/hooks) -- Hooks reference
- [Claude Code Memory](https://code.claude.com/docs/en/memory) -- CLAUDE.md, rules, and auto memory
- [Claude Code Changelog](https://github.com/anthropics/claude-code/blob/main/CHANGELOG.md) -- Version history
- [Claude Code Agent Teams](https://code.claude.com/docs/en/agent-teams) -- Experimental agent teams
