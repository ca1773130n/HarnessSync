# v2.0 Research Summary: Plugin & MCP Scope Sync

**Researched:** 2026-02-15
**Confidence:** HIGH

## Executive Summary

v2.0 extends HarnessSync to discover MCP servers from installed Claude Code plugins and sync them with proper scope awareness (user/project) to Gemini and Codex. **Critical finding: Gemini extensions are NOT the target** — plugin-provided MCP servers sync to Gemini's `settings.json` mcpServers section (same as v1.0 pattern), just with scope and plugin discovery enhancements.

## Key Findings

### 1. Gemini Extensions ≠ Claude Plugins
- Architecturally incompatible: different manifests, hook systems, command formats
- **DO NOT generate Gemini extensions** — continue using settings.json for MCP servers
- settings.json MCPs take precedence over extension-bundled servers
- Gemini supports user-scope (`~/.gemini/settings.json`) and workspace-scope (`.gemini/settings.json`)

### 2. Claude Code 3-Tier MCP Scoping
- **User scope:** `~/.claude.json` (top-level `mcpServers`)
- **Project scope:** `.mcp.json` (team-shared, git-committed)
- **Local scope:** `~/.claude.json` under `projects[path].mcpServers` (private, per-project)
- Precedence: local > project > user

### 3. Plugin MCP Discovery
- Installed plugins tracked in `~/.claude/plugins/installed_plugins.json`
- Plugin cache at `~/.claude/plugins/cache/{marketplace}/{plugin}/{version}/`
- Plugins register MCPs via plugin's `.mcp.json` or inline in `plugin.json`
- Path variables: `${CLAUDE_PLUGIN_ROOT}` needs expansion to absolute paths
- Plugin metadata in `.claude-plugin/plugin.json` (new) or root `plugin.json` (old)

### 4. Codex: MCP Only
- No plugin/extension system — Skills are the extension mechanism
- MCP config in `config.toml` with `[mcp_servers."name"]` sections
- Supports STDIO and HTTP transports only (SSE needs workaround)
- Project-level: `.codex/config.toml` (trusted projects only)
- Env vars: literal `env` map or `env_vars` whitelist (differs from Claude's `${VAR}` syntax)

### 5. Critical Pitfalls
- **Scope precedence collapse:** v1.0 merges flat, losing precedence semantics → fix in v2.0
- **Path portability:** Absolute paths in MCP configs break across machines
- **Env var translation:** `${VAR}` (Claude) vs literal map (Codex) vs settings.json (Gemini)
- **Transport gaps:** Codex doesn't support SSE, Gemini has different HTTP formats
- **Security:** Plugin MCP servers may expose tools that bypass permission models

## Architecture Recommendation

### What's Actually Needed
1. **SourceReader extension** — Discover MCPs from installed Claude Code plugins (installed_plugins.json + plugin cache)
2. **Scope-aware sync** — Map Claude's 3-tier scoping to target CLI scopes (user→user, project→workspace)
3. **Plugin path resolution** — Expand `${CLAUDE_PLUGIN_ROOT}` to absolute paths during sync
4. **Env var format translation** — Convert between Claude/Codex/Gemini env var syntaxes
5. **Transport compatibility warnings** — Flag unsupported transports per target

### What's NOT Needed
- Gemini extension generation (extensions ≠ plugins)
- Codex plugin support (doesn't exist)
- Bidirectional plugin sync
- Plugin capability decomposition (hooks/skills → not translatable)

## Scope Mapping

| Claude Code Scope | Gemini Target | Codex Target |
|-------------------|---------------|--------------|
| User (~/.claude.json mcpServers) | ~/.gemini/settings.json | ~/.codex/config.toml |
| Project (.mcp.json) | .gemini/settings.json | .codex/config.toml |
| Local (~/.claude.json projects[].mcpServers) | .gemini/settings.json | .codex/config.toml |
| Plugin MCPs (plugin cache) | ~/.gemini/settings.json | ~/.codex/config.toml |

## Sources

- Official Gemini CLI docs (extensions, settings.json, mcpServers)
- Official Codex CLI docs (config.toml, MCP servers)
- Claude Code plugin structure docs (plugin.json, installed_plugins.json)
- MCP specification (transport types, scoping)

---
*Research complete: 2026-02-15*
*Ready for requirements: yes*
