# HarnessSync: Multi-Harness Feature Sync Update

**Date:** 2026-03-19
**Scope:** Full round-trip sync for Claude Code, Codex CLI, Gemini CLI, OpenCode + opportunistic updates to Cursor/Cline/Windsurf
**Approach:** Vertical slices (source + adapters per feature), source-first within each slice
**Slices:** 6 PRs — Permissions, MCP, Skills/Agents/Config, Hooks, Plugins, New Settings (Slice 5 depends on Slice 4)

---

## Context

Claude Code, Codex CLI, Gemini CLI, and OpenCode have all shipped significant features between September 2025 and March 2026. HarnessSync's source reader and adapters need updating to reflect:

- **Permissions evolution** — All 4 harnesses now have richer permission models
- **MCP enhancements** — OAuth scopes, timeouts, elicitation, streamable HTTP
- **Skills/Agents maturation** — New frontmatter fields, @include directives, instructions arrays
- **Hooks systems** — Claude Code HTTP hooks, Codex experimental hooks, Gemini 11-event hooks
- **Plugin ecosystems** — Claude Code, Codex, and OpenCode all have plugin systems
- **New settings** — modelOverrides, attribution, autoMemoryDirectory, respectGitignore

Research files with full changelogs:
- `.planning/claude-code-changes-sep2025-mar2026.md`
- `.planning/gemini-cli-research-2025-09-to-2026-03.md`
- `.planning/opencode-research-2025-2026.md`

---

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Prioritization | Source-first within vertical slices | Adapters always have richest data available |
| Adapter scope | 4 primary + opportunistic | Focus effort where features exist; easy wins elsewhere |
| Hooks strategy | Best-effort mapping | Lifecycle events map cleanly; tool-specific matchers may not |
| Plugin strategy | Native-first, decompose fallback | Prefer native target plugin when it exists; extract contents otherwise |

---

## Slice 1: Permissions Sync

### SourceReader: `get_permissions()` → `dict`

New method extracting the permissions shape from merged settings:

```python
{
    "allow": ["Bash(npm *)", "Read", "Edit"],
    "deny": ["Bash(rm -rf *)"],
    "ask": ["Bash(git push *)"],
}
```

Helper in `src/utils/permissions.py`:
- `extract_permissions(settings: dict) -> dict` — pulls from `permissions.allow`, `permissions.deny`, `permissions.ask` keys
- `parse_permission_string(perm: str) -> tuple[str, str]` — parses `"Bash(npm *)"` into `("Bash", "npm *")`

**Data flow:** `get_permissions()` provides a pre-extracted convenience in `source_data["permissions"]`. Adapters consume this for the new permission-mapping logic instead of digging into `source_data["settings"]["permissions"]`. Existing `sync_settings()` logic continues handling non-permission settings fields — the permission keys are not removed from settings, just also provided separately for cleaner adapter code.

**`discover_all()` update:** Add `"permissions": self.get_permissions()` to the returned dict.

### Codex Adapter

Map Claude Code permissions to Codex's coarser model:

| Claude Code | Codex config.toml |
|---|---|
| Restrictive stance (many deny rules) | `approval_policy = "untrusted"` |
| Balanced (default ask) | `approval_policy = "on-request"` |
| Permissive (many allow rules) | `approval_policy = "never"` |
| Specific deny rules | Documented as warnings in synced AGENTS.md |

The mapping is intentionally lossy. Codex's model doesn't support per-tool glob patterns in the same way. We map **intent** and document **specifics** in rules.

### Gemini Adapter

Map to Gemini's policy engine:

- Create `.gemini/policies/harnesssync-policy.json` with deny rules in Gemini's policy format
- Add `"policyPaths": [".gemini/policies/harnesssync-policy.json"]` to `.gemini/settings.json`
- Set `"disableAlwaysAllow": true` when deny rules are present
- Set `"disableYoloMode": true` when deny rules are present

### OpenCode Adapter

Closest 1:1 mapping of all three:

| Claude Code | opencode.json `permission` |
|---|---|
| `permissions.allow: ["Bash(npm *)"]` | `{"permission": {"bash": {"npm *": "allow"}}}` |
| `permissions.deny: ["Bash(rm -rf *)"]` | `{"permission": {"bash": {"rm -rf *": "deny"}}}` |
| `permissions.ask: ["Bash(git push *)"]` | `{"permission": {"bash": {"git push *": "ask"}}}` |

Format follows OpenCode's existing schema: group by tool name (lowercased), then glob pattern → permission level. This matches the existing adapter code at `opencode.py` lines 392-464. Parse permission strings using `parse_permission_string()`, then invert the grouping.

### Files

- New: `src/utils/permissions.py`
- Modified: `src/source_reader.py` (add `get_permissions()`)
- Modified: `src/orchestrator.py` (extract permissions, add to source_data)
- Modified: `src/adapters/codex.py`
- Modified: `src/adapters/gemini.py`
- Modified: `src/adapters/opencode.py`
- New: `tests/test_permissions_sync.py`

---

## Slice 2: MCP Enhancements

### SourceReader Enhancement

The existing SourceReader already preserves all fields from source config dicts — the `command`/`url`/`type` check only gates whether a server entry is included, not which fields survive. **No SourceReader changes needed for field passthrough.** The real work is in adapter mapping tables below, where each adapter selects and transforms the fields it understands.

New fields now available in MCP config dicts (already present in source JSON, just not previously consumed by adapters):

- `essential` (bool)
- `timeout` (int, milliseconds)
- `oauth_scopes` (list[str])
- `elicitation` (bool or dict)
- `cwd` (str)
- `enabled_tools` / `disabled_tools` (list[str])

### Codex Adapter

| Claude Code field | Codex config.toml field |
|---|---|
| `timeout` (ms) | `tool_timeout_sec` (seconds — divide by 1000) |
| `url` (remote) | `url` + `bearer_token_env_var` if auth env var present |
| `oauth_scopes` | `scopes = [...]` |
| `essential` | Drop silently |
| `elicitation` | Pass through (Codex supports natively since 0.114; unknown keys are silently ignored by Codex's TOML parser so passthrough is safe regardless of Codex version) |
| `enabled_tools` | `enabled_tools` (direct) |
| `disabled_tools` | `disabled_tools` (direct) |

### Gemini Adapter

| Claude Code field | Gemini settings.json field |
|---|---|
| `cwd` | `cwd` (direct map) |
| `essential` | `trust: true` (closest semantic match) |
| `timeout` | Drop (not supported) |
| `oauth_scopes` | Drop (not supported) |
| `url` | `url` (direct map) |

### OpenCode Adapter

| Claude Code field | opencode.json field |
|---|---|
| `command`+`args` (stdio) | `"type": "local"`, `"command"`, `"args"` |
| `url` (remote) | `"type": "remote"`, `"url"` |
| `timeout` | `"timeout"` (direct map) |
| `env` | `"env"` (direct map) |
| `essential` | Drop |
| `oauth_scopes` | Drop |

### Opportunistic: Cursor, Cline, Windsurf

All three get `timeout` and `url` field passthrough in their respective MCP JSON files:
- Cursor: `.cursor/mcp.json`
- Cline: `.roo/mcp.json`
- Windsurf: `.codeium/windsurf/mcp_config.json`

### Files

- No SourceReader changes (fields already pass through)
- Modified: `src/adapters/codex.py`
- Modified: `src/adapters/gemini.py`
- Modified: `src/adapters/opencode.py`
- Modified: `src/adapters/cursor.py`
- Modified: `src/adapters/cline.py`
- Modified: `src/adapters/windsurf.py`
- New: `tests/test_mcp_enhancements.py`

---

## Slice 3: Skills, Agents, and Config Updates

### @include Directive Resolution (SourceReader)

New utility function in `src/utils/includes.py` (follows the canonical-read-path pattern — SourceReader handles all source reading, not the orchestrator):

```python
def resolve_includes(content: str, base_dir: Path) -> tuple[str, list[Path]]
```

- Scans for `@include path/to/file.md` patterns
- Resolves relative paths against source file's directory
- Inlines included content with cycle detection (tracks seen paths, max depth: 10)
- Returns resolved content AND list of included file paths (for hashing)

SourceReader calls `resolve_includes()` inside `get_rules()` after reading each CLAUDE.md file. The `discover_all()` dict provides **both** forms:
- `source_data["rules"]` — fully resolved (includes inlined)
- `source_data["include_refs"]` — list of raw include paths for adapters that prefer native imports (e.g., Gemini's `@file.md`)

### Gemini: @file.md Native Imports

Instead of inlining @include content, the Gemini adapter converts:
- `@include foo.md` → `@foo.md` (Gemini's native import syntax)

This preserves modularity in the target config.

### OpenCode: `instructions` Array

When rules come from multiple source files (user + project + local), emit them as an `instructions` array in opencode.json:

```json
{
    "instructions": [
        ".opencode/rules/user-rules.md",
        ".opencode/rules/project-rules.md"
    ]
}
```

Write individual rule files to `.opencode/rules/` and reference them, rather than concatenating everything into AGENTS.md.

### OpenCode: Agent Config Migration

OpenCode deprecated `mode` in favor of `agent`. The adapter writes agent definitions using the new shape:

```json
{
    "agent": {
        "primary": "developer",
        "agents": {
            "developer": { "instructions": "..." },
            "explorer": { "instructions": "..." }
        }
    }
}
```

### Skill Frontmatter Passthrough

New Claude Code SKILL.md frontmatter fields (`context: fork`, `agent`) are preserved as-is when writing to targets. All three primary targets (Codex, Gemini, OpenCode) read YAML frontmatter from SKILL.md natively.

### Codex: Hierarchical AGENTS.md

Codex supports `child_agents_md` feature for discovering AGENTS.md in subdirectories. When Claude Code has project-scoped rules in subdirectory CLAUDE.md files, map to subdirectory AGENTS.md files for Codex.

### Files

- New: `src/utils/includes.py` (`resolve_includes()` function)
- Modified: `src/source_reader.py` (call `resolve_includes()` in `get_rules()`, expose `include_refs` in `discover_all()`)
- Modified: `src/adapters/gemini.py` (@file.md conversion)
- Modified: `src/adapters/opencode.py` (instructions array, agent config)
- Modified: `src/adapters/codex.py` (hierarchical AGENTS.md)
- New: `tests/test_skills_agents_config.py`

---

## Slice 4: Hooks Sync

### SourceReader: `get_hooks()` → `dict`

New discovery method reading from two locations:

1. `settings.json` → `hooks` key (new format: array of hook objects)
2. Project-level `hooks/hooks.json` (legacy plugin format)

Normalized return structure:

```python
{
    "hooks": [
        {
            "event": "PreToolUse",
            "type": "shell",        # "shell" | "http"
            "command": "...",        # for shell hooks
            "url": "...",           # for HTTP hooks
            "matcher": "Edit|Write",
            "timeout": 10000,
            "scope": "user",        # "user" | "project"
        }
    ]
}
```

### Base Adapter: `sync_hooks()`

New method with default no-op (returns `SyncResult(skipped=len(hooks))`). Only Codex and Gemini override.

**Wiring:** `AdapterBase.sync_all()` must be updated to dispatch `sync_hooks(source_data.get('hooks', []))` after the existing 6 calls, wrapped in the same try/except pattern. The orchestrator's `_apply_section_filter()` must add `'hooks': []` to `section_defaults`.

**`discover_all()` update:** Add `"hooks": self.get_hooks()` to the returned dict.

### Codex Adapter

Codex hooks are experimental (gated behind `[features] hooks = true`).

| Claude Code event | Codex event |
|---|---|
| `SessionStart` | `SessionStart` |
| `Stop` | `Stop` |
| `PostToolUse` | `AfterToolUse` (rename) |
| `PreToolUse` | Skip (unsupported) |
| HTTP hooks | Skip (shell-only) |

**Gate behavior:** If the user already has `features.hooks = true` in their Codex config, write hooks to `.codex/config.toml`. If not, add a comment in AGENTS.md noting available hooks that require the feature flag. Never enable experimental features without consent.

### Gemini Adapter

Richest hook target — 11 events in `.gemini/settings.json` under `"hooks"`.

| Claude Code event | Gemini event | Matcher type |
|---|---|---|
| `PreToolUse` | `PreToolUse` | `regex` (tool name pattern) |
| `PostToolUse` | `PostToolUse` | `regex` |
| `SessionStart` | `SessionStart` | `exact` |
| `Stop` | `Stop` | `exact` |
| `Notification` | `Notification` | `exact` |
| `PreCompact` | Drop (not supported in Gemini as of March 2026) | — |
| `PostCompact` | Drop (not supported in Gemini as of March 2026) | — |
| HTTP hooks | Convert to curl wrapper | See below |

**HTTP-to-curl conversion spec:** Generate a shell command: `curl -sS -X POST -H 'Content-Type: application/json' -d '{"event":"EVENT","tool":"$TOOL_NAME"}' --max-time TIMEOUT_SEC URL`. The `$TOOL_NAME` variable is populated by Gemini's hook context. Timeout defaults to 10s if not specified. No authentication headers — if the HTTP hook requires auth, skip it and log a warning (Gemini hooks don't support bearer token injection).

### Files

- Modified: `src/source_reader.py` (add `get_hooks()`)
- Modified: `src/adapters/base.py` (add `sync_hooks()` default)
- Modified: `src/adapters/codex.py` (hooks override)
- Modified: `src/adapters/gemini.py` (hooks override)
- Modified: `src/orchestrator.py` (route hooks through source_data)
- New: `tests/test_hooks_sync.py`

---

## Slice 5: Plugin Sync

### SourceReader: `get_plugins()` → `dict[str, dict]`

Extends existing `_get_enabled_plugins()` and `_get_plugin_install_paths()` to return full metadata:

```python
{
    "plugin-name": {
        "enabled": True,
        "version": "1.0.0",
        "install_path": Path(...),
        "has_skills": True,
        "has_agents": True,
        "has_commands": True,
        "has_mcp": True,
        "has_hooks": True,
        "manifest": {...},
    }
}
```

### Plugin Equivalence Registry

New file: `src/plugin_registry.py`

```python
PLUGIN_EQUIVALENTS = {
    "context-mode": {"codex": None, "gemini": None, "opencode": None},
    "sentry": {"codex": "@sentry/codex-plugin", "gemini": None, "opencode": None},
    # ... maintained manually
}
```

Static dict — not dynamic lookup. Rationale:
- Plugin ecosystems are small (tens, not thousands)
- False matches from fuzzy naming would be worse than missing matches
- Users override via `.harnesssync`: `{"plugin_map": {"my-plugin": {"codex": "codex-equivalent"}}}`

### Base Adapter: `sync_plugins()`

New method with default no-op. Provides a helper:

```python
def _find_native_plugin(self, plugin_name: str, manifest: dict) -> str | None
```

Checks `PLUGIN_EQUIVALENTS` + user overrides from `.harnesssync` config.

**Wiring:** `AdapterBase.sync_all()` must be updated to dispatch `sync_plugins(source_data.get('plugins', {}))` after `sync_hooks`, wrapped in the same try/except pattern. The orchestrator's `_apply_section_filter()` must add `'plugins': {}` to `section_defaults`.

**`discover_all()` update:** Add `"plugins": self.get_plugins()` to the returned dict.

### Two-Tier Sync Strategy

For each Claude Code plugin:

1. **Check for native equivalent** in the target harness
   - If found → reference/enable it in the target's plugin config
2. **Decompose as fallback** — extract the plugin's contents:
   - Skills → route through `sync_skills()`
   - Agents → route through `sync_agents()`
   - Commands → route through `sync_commands()`
   - MCP servers → route through `sync_mcp()`
   - Hooks → route through `sync_hooks()` (requires Slice 4 to have landed first)

**Dependency note:** Slice 5 depends on Slice 4 for hooks decomposition. Slice 4 must land before Slice 5. If hooks decomposition is needed before Slice 4, the fallback routes through skills/agents/commands/mcp only and skips hooks.

### Codex Adapter

- Native plugin found → add to `.codex/config.toml` plugins section
- No equivalent → decompose through existing pipelines
- Plugin metadata → surface in AGENTS.md as informational context

### Gemini Adapter

- Native extension found → reference in `.gemini/settings.json` extensions config
- No equivalent → decompose through existing pipelines

### OpenCode Adapter

- Native npm plugin found → add to `opencode.json` plugins array
- No equivalent → decompose through existing pipelines
- Skip TypeScript-specific event hooks (can't translate from shell/prompt hooks)

### Files

- Modified: `src/source_reader.py` (add `get_plugins()`)
- New: `src/plugin_registry.py`
- Modified: `src/adapters/base.py` (add `sync_plugins()` default + helper)
- Modified: `src/adapters/codex.py`
- Modified: `src/adapters/gemini.py`
- Modified: `src/adapters/opencode.py`
- Modified: `src/orchestrator.py` (route plugins through source_data)
- New: `tests/test_plugins_sync.py`

---

## Slice 6: New Settings Mapping

### Settings Keys to Map

| Claude Code setting | Codex | Gemini | OpenCode | Skip rationale |
|---|---|---|---|---|
| `modelOverrides` | `[profiles.*]` section | Skip | Skip | Gemini/OpenCode don't have user-configurable model profiles |
| `attribution` | `command_attribution` | Skip | Skip | Only Codex has commit co-author hooks |
| `respectGitignore` | Skip | `fileFiltering.respectGitignore` | Skip | Codex/OpenCode handle gitignore natively without config |
| `autoMemoryDirectory` | Skip | Skip | Skip | Claude Code-internal memory storage path; no equivalent concept |
| `language` | Skip | Skip | Skip | UI language preference; all targets use system locale |
| `cleanupPeriodDays` | Skip | Skip | Skip | Claude Code-internal cache management; no equivalent concept |

### Files

- Modified: `src/adapters/codex.py` (profiles from modelOverrides, command_attribution)
- Modified: `src/adapters/gemini.py` (fileFiltering.respectGitignore)
- New: `tests/test_new_settings_sync.py`

---

## Testing Strategy

Each slice gets its own test file:

| Slice | Test file | Key tests |
|---|---|---|
| 1. Permissions | `tests/test_permissions_sync.py` | Permission string parsing, per-adapter format mapping, round-trip |
| 2. MCP | `tests/test_mcp_enhancements.py` | Field passthrough, timeout ms→sec, type discrimination, opportunistic adapters |
| 3. Skills/Config | `tests/test_skills_agents_config.py` | @include resolution (happy path, self-referential, diamond graph, missing file, symlink boundary, depth=10 limit, depth=11 rejection), @file.md conversion, instructions array |
| 4. Hooks | `tests/test_hooks_sync.py` | Hook normalization, event mapping, HTTP→curl, feature gate behavior |
| 5. Plugins | `tests/test_plugins_sync.py` | Equivalence lookup, user override, decomposition, native plugin reference |
| 6. Settings | `tests/test_new_settings_sync.py` | Per-setting mapping, skip behavior for unsupported keys |

### Not tested
- Harness-side behavior (whether Codex/Gemini/OpenCode actually read our output)
- Plugin marketplace availability (external dependency)
- HTTP hook endpoints (external network)

---

## Implementation Order

```
Slice 1: Permissions ──────────────────────────── PR #1
Slice 2: MCP Enhancements ────────────────────── PR #2
Slice 3: Skills/Agents/Config ─────────────────── PR #3
Slice 4: Hooks ────────────────────────────────── PR #4
Slice 5: Plugins ──────────────────────────────── PR #5 (depends on PR #4)
Slice 6: New Settings ─────────────────────────── PR #6
```

Slices 1-4 and 6 are independently shippable in any order. Slice 5 (Plugins) depends on Slice 4 (Hooks) because plugin decomposition routes extracted hooks through `sync_hooks()`.

---

## Files Summary

### New files
- `src/utils/permissions.py` — Permission string parsing and extraction
- `src/utils/includes.py` — @include directive resolution with cycle detection
- `src/plugin_registry.py` — Static plugin equivalence mapping
- `tests/test_permissions_sync.py`
- `tests/test_mcp_enhancements.py`
- `tests/test_skills_agents_config.py`
- `tests/test_hooks_sync.py`
- `tests/test_plugins_sync.py`
- `tests/test_new_settings_sync.py`

### Modified files
- `src/source_reader.py` — `get_hooks()`, `get_plugins()`, `get_permissions()`, @include resolution in `get_rules()`, `discover_all()` updated with hooks/plugins/permissions/include_refs keys
- `src/adapters/base.py` — `sync_hooks()`, `sync_plugins()` defaults; `sync_all()` updated to dispatch hooks and plugins
- `src/adapters/codex.py` — All 6 slices
- `src/adapters/gemini.py` — All 6 slices
- `src/adapters/opencode.py` — Slices 1-5
- `src/adapters/cursor.py` — Slice 2 (MCP)
- `src/adapters/cline.py` — Slice 2 (MCP)
- `src/adapters/windsurf.py` — Slice 2 (MCP)
- `src/orchestrator.py` — Permissions extraction, new source_data routing, `_apply_section_filter` updated with hooks/plugins defaults
