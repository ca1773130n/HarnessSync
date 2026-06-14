# Changelog

All notable changes to HarnessSync are documented here.

## [Unreleased] — 2026-06-14 — Modernization (Claude Code + Codex)

A maintenance pass bringing the source reader and the Codex adapter up to the
mid-2026 Claude Code and Codex CLI feature sets, and removing the deprecated
Gemini target.

### Removed
- **Gemini target dropped entirely.** Google discontinued the Gemini CLI, so
  HarnessSync no longer syncs to it. Deleted the gemini adapter and scrubbed
  ~200 files of gemini references (capability matrices, env/transport maps,
  marker regexes, command modules, tests, docs, manifests, CI). Supported
  targets: **12 → 10** (Aider, Cline, Codex, Continue, Cursor, Neovim, OpenCode,
  VS Code, Windsurf, Zed). Historical `.planning/` records and runtime logs
  intentionally retain their references.

### Added — cross-target output styles
- The active **custom** `outputStyle` body is now injected into the rules
  pipeline, so it flows into every target's system-prompt content (Zed,
  neovim/avante, Continue, Codex/OpenCode AGENTS.md, Cursor, …). Built-in styles
  (no body) are skipped. Frontmatter is stripped before injection.

### Added — Claude Code source surfaces (`SourceReader.discover_all()`)
- `settings.env` → `get_env()` — session environment variables for adapters
  with env maps.
- `model` + `effort` → `get_model_config()` — real default model / reasoning
  effort (incl. the new `xhigh`).
- `sandbox` block → `get_sandbox()`.
- `permissions.defaultMode` + `additionalDirectories` → `get_permission_mode()`.
- `outputStyle` + `.claude/output-styles/*.md` → `get_output_styles()`.
- Namespaced (nested) agents/commands are now discovered via `rglob`
  (previously missed by non-recursive `iterdir`).
- MCP transport: explicit `type` is honored and `streamable-http` is normalized
  to `http`; `transport_deprecation()` flags the deprecated SSE transport.

### Changed — MCP safety
- **Project `.mcp.json` enable/disable gates are honored.** Servers listed in
  `disabledMcpjsonServers` are no longer synced; skips are reported via
  `get_skipped_mcp_servers()` (`discover_all()["mcp_disabled"]`).

### Changed — Codex adapter (current `config.toml` schema)
- MCP HTTP transport: Claude Code `headers` → `http_headers`, plus
  `env_http_headers` pass-through (both emitted as nested TOML tables).
- New keys: `model` (only OpenAI/Codex model ids; Anthropic aliases are not
  propagated), `model_reasoning_effort` (validated, incl. `xhigh`), and
  `project_doc_fallback_filenames = ["CLAUDE.md"]` (lets Codex read `CLAUDE.md`
  when `AGENTS.md` is absent).
- `[sandbox_workspace_write]` table (`writable_roots`, `network_access`) derived
  from the Claude Code `sandbox` block + `permissions.additionalDirectories`.
- Hooks are now treated as a **stable** feature: written by default unless
  `[features] hooks = false`. Corrected event map (`PostToolUse` stays
  `PostToolUse` — no legacy `AfterToolUse`; `PreToolUse` and `UserPromptSubmit`
  are now supported) and corrected nested `[[hooks.Event]]` /
  `[[hooks.Event.hooks]]` TOML.
- `settings.env` → `[shell_environment_policy.set]` (session env vars).
- Opt-in granular `approval_policy` object form via `settings.codexApprovalGranular`
  (`true` for all categories, or a dict of any of `sandbox_approval`, `rules`,
  `mcp_elicitations`, `request_permissions`, `skill_approval`); the intent-based
  string form remains the default. The minimal TOML reader/writer gained inline-
  table support so the object form round-trips across re-syncs.

### Fixed
- Codex `config.toml`: managed bare top-level keys are preserved at the document
  root across all writers, so a later `sync_mcp` can no longer push them below
  `[mcp_servers.*]` tables (which would silently rebind them).
- Removed the dead `cc_mcp_global` SourceReader attribute (hardcoded
  `Path.home()`, never read).

### Remaining follow-ups
- Propagate `settings.env` into the *non-Codex* env-aware adapters (Continue,
  Zed, Windsurf) — Codex is done; those adapters don't yet emit session env.
- C8 (deferred, low ROI): `statusLine`, user-scope `hooks/hooks.json`,
  ancestor/monorepo `CLAUDE.md`, enterprise managed-settings.
