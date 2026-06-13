# HarnessSync Modernization Plan — June 2026

Gap analysis + prioritized, independently-shippable work plan synthesizing two research streams: (1) a full codebase map (current state) and (2) feature research on the latest Claude Code and Codex config surfaces (mid-2026).

**Headline conclusions**
- **Remove Gemini** (deprecated). It is a first-class CORE target woven through ~165 `src/*.py` files, 28 test files, 12 command markdown files, scripts, plugin manifests, and a 98,372-line `GEMINI.md` artifact. Removal is driven by deleting **one adapter** + **one constant**, then fanning out. Result: **12 → 11 harnesses**, **11 → 10 adapters**.
- **Claude Code has moved on.** SourceReader does not read several now-standard surfaces: `statusLine`, `outputStyle` / output-styles dirs, `settings.env`, `model`/`effort`/`advisorModel`, the `sandbox` block, MCP enable/disable gates, new hook events, and namespaced (nested) agents/commands. Several of these matter for sync.
- **The Codex adapter is behind.** It targets an early-2026 Codex schema. Missing: HTTP MCP `type`/`url` first-class handling, `model_reasoning_effort`/`model_verbosity`, granular `approval_policy`, `[sandbox_workspace_write]`, `model_instructions_file`, `project_doc_fallback_filenames`, `[tools] web_search`, Codex-native skills dir, and `xhigh` effort.
- **AGENTS.md is becoming the cross-harness standard.** Only `codex` and `opencode` emit it today. Worth treating as a shared capability.

---

## Section 1 — GEMINI REMOVAL (complete enumeration)

Gemini is deprecated and must be fully removed. **Counts to change everywhere: "12 AI harnesses" → "11"; "11 adapters" → "10".** Verified literal `12 AI harnesses` strings: `README.md:5`, `CLAUDE.md:3`, `AGENTS.md:8`, `CONVENTIONS.md:8` (plus synced dotfile copies that regenerate). `tests/test_new_modules.py:34` asserts "All 11 harnesses" → becomes 10.

### 1A. CRITICAL root changes (do FIRST — most downstream code is registry/constant-driven)

| # | File | Edit |
|---|------|------|
| 1 | `src/adapters/gemini.py` | **DELETE entire file** (the `GeminiAdapter`, `@AdapterRegistry.register("gemini")`). |
| 2 | `src/adapters/__init__.py` | Remove `from . import gemini  # noqa: F401` (line 42). Fix docstring "(Codex, Gemini, OpenCode)" (lines 10-11). |
| 3 | `src/utils/constants.py` | Remove `"gemini"` from `CORE_TARGETS` (line 4). Cascades to `EXTENDED_TARGETS`/`ALL_TARGETS` and every module iterating the canonical list. CORE_TARGETS: 6→5, ALL_TARGETS: 11→10. |
| 4 | `src/mcp/schemas.py` | Remove from MCP tool surface: description (line 12), `enum` (line 40 `["codex","gemini","opencode"]`), `valid_targets` (line 121). **Externally-exposed MCP tool list.** |

Once 1–4 land, the orchestrator (registry-driven), `source_reader.py`, and `hooks/hooks.json` need **no** gemini-specific edits — confirm during edit.

### 1B. Hard-coded gemini dicts/tables (NOT list-driven — edit each individually)

These carry literal gemini rows/keys and won't be fixed by the constant change:

- `src/utils/harness_validator.py` — binary tuple, `.gemini/GEMINI.md` config path, `~/.gemini/GEMINI.md`.
- `src/utils/env_translator.py` — transport set (line 36 `{"stdio","http","sse"}`), `preserve_env_vars_for_gemini()` (124-127), env-var maps (GEMINI_API_KEY/MODEL/API_BASE/STREAMING/MAX_OUTPUT_TOKENS), docstrings (10/16-17/203), embedded self-tests asserting Gemini SSE/passthrough.
- `src/utils/env_var_matrix.py` (18 hits), `src/permission_translator.py` (22), `src/filter_rules.py` (18), `src/model_routing.py` (24), `src/harness_cost_advisor.py` (24), `src/reverse_sync.py` (23), `src/harness_comparison.py` (21), `src/compatibility_reporter.py` (19), `src/harness_feature_matrix.py` (19), `src/token_estimator.py` (cost/context/display/`"gemini":["GEMINI.md"]` map), `src/harness_readiness.py` (full `"gemini": {...}` block — `npm install -g @google/gemini-cli`, `~/.gemini`, `GEMINI_API_KEY`), `src/context_budget_sync.py` (`_translate_gemini` + registration), `src/config_health.py` (14), `src/config_linter.py` (sync markers `gemini-only` / `@harness:skip-gemini`, regexes, prose), `src/secret_detector.py` (GEMINI_API_KEY pattern).

### 1C. Fan-out files (per-harness map entries — remove the gemini key)

Grouped by approximate hit count (verified ~165 `src/` files total touch gemini):

- **10–17 hits:** `task_router.py`, `nl_config_generator.py`, `commands/sync_capabilities.py`, `skill_translator.py`, `migration_assistant.py`, `config_snapshot.py`, `git_hook_installer.py`, `post_sync_verifier.py`, `project_detector.py`, `skill_transpiler.py`, `sync_impact_predictor.py`, `native_preview.py`, `agent_mesh_sync.py`, `harness_detector.py`, `compat_rules.py`, `skill_smoke_tester.py`, `analysis/skill_linter.py`.
- **5–9 hits:** `account_discovery.py`, `cross_harness_memory_sync.py`, `profile_manager.py`, `filter_engine.py`, `harness_annotation.py`, `skill_compatibility.py`, `mcp_tool_compat.py`, `harness_adoption.py`, `harness_override.py`, `capability_matrix.py`, `rule_simulator.py`, `prompt_consistency_checker.py`, `annotation_filter.py`, `compat_transforms.py`, `skill_sync_tags.py`, `feature_gap_issue_creator.py`, `skill_gap_analyzer.py`, `pre_sync_summary.py`, `capability_advisor.py`, `config_complexity.py`, `dead_config_detector.py`, `rule_annotation_suggester.py`, `session_handoff.py`, `mcp_reachability.py`, `version_detection.py`, `plugin_registry.py`, `setup_wizard.py`, `filter_helpers.py`, `sync_preview.py`, `mcp_aliasing.py`.
- **1–3 hits (mostly docstrings/target lists/examples):** `state_manager.py`, `changelog_manager.py`, `symlink_cleaner.py`, `conflict_scanner.py`, `version_pinning.py`, `config_discovery.py` (the hardcoded override-target list `codex,gemini,opencode,cursor,aider,windsurf` in `get_harness_override*`), `harness_rule_dsl.py`, `harness_health_score.py`, `permission_escalation_guard.py`, `team_github_sync.py`, `remote_sync.py`, `rule_deduplicator.py`, `mcp_routing.py`, `mcp_registry.py`, `mcp_catalog.py`, `sync_ignore.py`, `sync_anomaly.py`, `html_report.py`, `transform_engine.py`, `sync_scheduler.py`, `adapter_sdk.py`, `rule_priority_sorter.py`, `sync_metrics.py`, `audit_log.py`, `desktop_notifier.py`, `rule_tagger.py`, `filter_ignore.py`, `backup_manager.py`, `ci_pipeline_generator.py`, `offline_queue.py`, `annotation_preserver.py`, `orchestrator.py` (docstring example line 73), `drift_semantic.py`, `skip_reason_reporter.py`, `sync_undo_stack.py`, `skill_dependency_graph.py`, `skill_marketplace.py`, `rule_rationale.py`, `diff_formatter.py`, `webhook_notifier.py`, `sync_pauser.py`, `branch_aware_sync.py`, `config_time_machine.py`, `adapter_scaffold.py`, `team_broadcast.py`, `rule_categorizer.py`, `startup_check.py`, `ab_config_tester.py`, `override_manager.py`, `dotfile_integration.py`, `sync_integrity.py`, `sync_policy.py`, `webhook_server.py`, `feature_watchlist.py`.

> Recommended approach for 1C: a single mechanical scrub pass per file, guarded by a repo-wide `grep -rin gemini src/` that must reach **zero** (excluding any intentionally-historical strings) plus a full `pytest` run after each batch.

### 1D. Commands (`src/commands/*.py` + `commands/*.md`)

- **Python:** `sync_capabilities.py` (16), `sync_add_harness.py`, `sync_import.py`, `sync_setup.py`, `sync_search.py`, `sync_git_hook.py`, `sync_matrix.py`, `sync_health.py`, `sync_hotswap.py`, `sync_restore.py`, `sync_handoff.py`, `sync_parity.py`, `sync.py`, `sync_diff.py`, `sync_merge.py`, plus 1–2 hit: `sync_log`, `sync_coverage`, `sync_ab`, `sync_reverse`, `sync_cost`, `sync_lint`, `sync_consistency`, `sync_rollback`, `sync_bootstrap`, `import_helpers`, `sync_github_actions`, `sync_wizard`, `test_probes`, `sync_compare`, `sync_migrate`, `sync_test`, `sync_watch`, `sync_activate`, `sync_score`, `sync_memory`, `sync_gaps`, `sync_mcp_health`, `sync_agent_mesh`, `sync_preset`, `sync_pause`.
- **Markdown (12 files):** `sync.md`, `sync-add-harness.md`, `sync-activate.md`, `sync-capabilities.md`, `sync-coverage.md`, `sync-diff.md`, `sync-import.md`, `sync-memory.md` (incl. `~/.gemini/context.md`), `sync-resolve.md`, `sync-restore.md`, `sync-rollback.md`, `sync-setup.md` (`.gemini*` glob + `gemini=~/.gemini`).

### 1E. Tests (28 files)

- **DELETE wholesale:** `tests/verify_task1_gemini.py`, `tests/verify_task2_gemini.py`. Likely `tests/verify_phase13_native_formats.py` (48 hits, phase 13 = Gemini native-format migration — delete if entirely gemini-scoped).
- **Prune gemini cases:** `test_new_settings_sync.py` (45), `test_hooks_sync.py` (41), `test_iter67_miscellaneous.py` (39), `test_mcp_enhancements.py` (36), `test_permissions_sync.py` (32), `test_iter65_miscellaneous.py` (28), `verify_task2_opencode.py` (27), `verify_phase10_integration.py` (22), `test_skills_agents_config.py` (19), `test_plugins_sync.py` (18), `test_phase12_integration.py` (16), `test_iter68/64/72/66/61/63/69_miscellaneous.py`, `verify_phase14_preservation.py` (8), `test_state_manager.py` (7), `test_iter44_py_harness_annotations.py` (6), `test_skill_sync_tags.py` (6), `test_new_modules.py` (4 — update "11 harnesses" → 10), `test_config_linter.py` (1).
- Re-run `python3 -m pytest tests/` after; assertions on harness totals/lists shift from 11→10 adapters.

### 1F. Delete the output artifact + scripts + manifests + CI

| File | Edit |
|------|------|
| `GEMINI.md` (repo root) | **DELETE** — 98,372-line synced artifact. |
| `.github/workflows/sync-state-validate.yml` | Remove `- 'GEMINI.md'` watched path (line 16). |
| `scripts/shell-integration.sh` | Remove `gemini()` wrapper (60-66), `_harnesssync_check_target 'Gemini'` (107), usage line (135), comment (7). |
| `scripts/install.sh` | Remove banner "Codex + Gemini + OC" (30), `~/.gemini/` creation (73/77/82). |
| `.claude-plugin/plugin.json` | Description "Codex, Gemini CLI, and OpenCode" (line 4) → drop Gemini CLI. |
| `.claude-plugin/marketplace.json` | Descriptions (lines 7, 17). |

### 1G. Docs + counts + synced-output dotfiles

- **Count + list edits:** `README.md` (line 5 "12 → 11", ASCII banner line 19 "Gemini … 7 more", harness list line 24, table line 45 `AGENTS.md / GEMINI.md`, shell wrappers line 57), `CLAUDE.md` (line 3 + Targets list), `AGENTS.md` (line 8 + line 24), `CONVENTIONS.md` (line 8 + line 24).
- **Synced output dotfiles (auto-regenerate after source fix; stale today):** `.clinerules`, `.continue/rules/harnesssync.md`, `.roo/rules/harnesssync.md`, `.avante/system-prompt.md`, `.cursor/rules/claude-code-rules.mdc`, `.codecompanion/system-prompt.md`, `.zed/system-prompt.md`. Delete any `.gemini/` output dir if present. Re-run sync to regenerate.
- **Docs prose:** `docs/tutorial-reference.md`, `docs/superpowers/specs/2026-03-19-*.md`.
- **Runtime logs (lowest priority, immutable history OK to leave):** `.harness-sync/changelog.md` (198 hits), `.harness-sync/rule-attribution.json` (regenerates).
- **`.planning/**` (~90 files):** historical roadmap/research/phase records. **Leave history intact.** Optionally add a deprecation note to `ROADMAP.md`/`STATE.md`/`PROJECT.md`/`EVOLVE-STATE.json` and a `SYNC-CHANGELOG.md` entry. Do NOT rewrite completed phase records (`.planning/phases/03-gemini-opencode-adapters/`, `.planning/milestones/v0.1.1/phases/13-gemini-native-format-migration/`, research GEMINI-* files).

**Gemini removal file count (files requiring edits or deletion, excluding `.planning/` history and runtime logs): ~120.**

---

## Section 2 — CLAUDE CODE NEW-SURFACE GAPS (SourceReader)

`discover_all()` (config_discovery.py:401) returns: rules, include_refs, rules_files, skills, agents, commands, mcp_servers, mcp_servers_scoped, settings, permissions, harness_overrides, hooks, plugins. The **raw merged `settings` dict is present** but most individual newer keys are never surfaced as adapter-facing fields. Gaps, ranked by sync value:

### HIGH value (target harnesses have equivalents — sync matters)

| Surface | Status | Why it matters |
|---|---|---|
| `settings.env` block | NOT surfaced (only inside raw settings blob) | Canonical way to bake ANTHROPIC_MODEL, MCP_TIMEOUT, DISABLE_TELEMETRY into every session. Codex `[shell_environment_policy].set`, Zed/Continue env maps consume this. |
| `model` (+ `opusplan`, `fable`, full IDs) | NOT individually surfaced | Drives Codex `model` / `[profiles]`, Continue/Zed model config. Adapters currently rely on lossy `modelOverrides`. |
| `outputStyle` + `.claude/output-styles/*.md` | NOT read at all | System-prompt persona (Default/Proactive/Explanatory/Learning + custom). Maps to harness system-prompt files (Zed/neovim already write system-prompt.md). Custom output-style bodies are appendable rules. |
| MCP enable/disable gates: `enableAllProjectMcpServers`, `enabledMcpjsonServers`, `disabledMcpjsonServers` | IGNORED — all `.mcp.json` servers read regardless | We may sync MCP servers the user explicitly disabled. Correctness/safety gap. |
| MCP transport: `http` / `streamable-http` alias; **SSE deprecated** | Partial — `env_translator` transport sets still list `sse` as supported (line 36 etc.) | Should prefer `http`, treat `streamable-http` as alias, and stop emitting/relying on SSE. Affects every MCP-writing adapter. |
| `permissions.defaultMode` (incl. new `auto`, `dontAsk`) + `additionalDirectories` | IGNORED — only allow/deny/ask extracted | `defaultMode` maps to Codex `approval_policy` / `sandbox_mode` intent; `additionalDirectories` maps to Codex `writable_roots`, sandbox allowWrite. |

### MEDIUM value

| Surface | Status | Notes |
|---|---|---|
| `statusLine` (+ `subagentStatusLine`) | NOT read | Few targets have an equivalent; Zed/Continue partial. Lower ROI but cheap to surface. |
| `sandbox` block (`enabled`, `excludedCommands`, `filesystem.allowWrite/denyWrite`) | NOT read (note: `src/sync_sandbox.py` is HarnessSync's own *simulation*, unrelated to CC's `sandbox` settings key) | Maps cleanly to Codex `[sandbox_workspace_write]` (`writable_roots`, `network_access`). High value specifically for Codex. |
| MCP per-server `timeout` (ms) | Codex adapter translates `timeout`→`tool_timeout_sec`, but SourceReader doesn't normalize/validate (`<1000` rule v2.1.162+) | Confirm pass-through; document. |
| New hook events (UserPromptExpansion, Setup, PostToolUseFailure, PermissionRequest/Denied, SubagentStart, Task*, Worktree*, ConfigChange, FileChanged, etc.) | Reader normalizes generically (event-keyed), so they pass through — but **no adapter maps them**, and HTTP/prompt hook types beyond command may be dropped downstream | Reader is mostly fine; adapter-side event maps (e.g. Codex) are the gap. |
| Hook `type: http` / `type: prompt` (LLM) + `allowedHttpHookUrls` | Reader supports shell/http normalization; `prompt` type + governance keys unhandled | Codex is shell-only (already skips http) — surface for harnesses that support http hooks. |
| Skill/subagent frontmatter: `when_to_use`, `arguments`, `disable-model-invocation`, `user-invocable`, `allowed-tools`, `model`, `effort`, `context:fork`, subagent `skills`/`memory`/`isolation` | Read as opaque files; new fields not parsed/translated | Affects fidelity of skill/agent translation per adapter. |

### LOW value / correctness fixes

- **`cc_mcp_global` dead attribute** (config_discovery.py:58): `Path.home()/.mcp.json` is set but **never read** — and hardcodes `Path.home()` instead of `self.cc_home` (multi-account bug if it were ever wired). Either wire it through `cc_home` and read it, or delete the attribute.
- **Namespaced/nested agents & commands:** `get_agents`/`get_commands` use `iterdir` (non-recursive), so subfolder-organized (namespaced) commands/agents are **missed**; only rules use `rglob`. Switch to `rglob`.
- **User-scope `cc_home/hooks/hooks.json`** not read (only project `hooks/hooks.json` + settings.json hooks).
- **Project-scope plugins** (`scope != "user"`) excluded from skills/agents/commands install-path discovery.
- **Ancestor-directory / monorepo CLAUDE.md** upward traversal + **managed-settings.json** (enterprise) not discovered.
- Top-level settings keys `apiKeyHelper`, `cleanupPeriodDays`, `includeCoAuthoredBy`, `effort`, `advisorModel`, `agent` — not individually surfaced (low sync value; mostly Claude-only).

---

## Section 3 — CODEX MODERNIZATION (adapter diffs)

The Codex adapter (`src/adapters/codex.py`, 1434 lines) targets an early-2026 schema. Verified absent: `model_reasoning_effort`, `model_verbosity`, `web_search`, `writable_roots`, `model_instructions_file`, `project_doc_fallback_filenames` (grep count = 0). Concrete diffs:

### 3A. MCP — HTTP transport first-class

- **Current:** stdio-centric. For `url` servers it heuristically derives `bearer_token_env_var` from an env key containing TOKEN/KEY/AUTH/BEARER/SECRET (codex.py:834). No explicit transport/type emission.
- **Latest Codex `[mcp_servers.<name>]`:** stdio (`command`/`args`/`env`/`cwd`) **or** HTTP (`url` + `bearer_token_env_var` + `http_headers` + `env_http_headers`). Add: pass through `env_http_headers`; emit `http_headers` from CC `headers`; keep `bearer_token_env_var` but prefer explicit mapping from the auth header rather than heuristic guessing. Per-tool `tools.<tool>.approval_mode` (auto|prompt|approve) and `default_tools_approval_mode` are new — add when CC expresses per-tool gates.
- **SSE:** Codex never supported SSE; current `check_transport_support(..., "codex")` correctly skips. Keep, but align with CC's "SSE deprecated, use http" stance.

### 3B. Settings → config.toml — add new top-level keys

| Add key | Source mapping | Notes |
|---|---|---|
| `model` | from new SourceReader `model` field (Section 2) | Codex `model` (user-level). Currently only `[profiles.<task>]` from lossy `modelOverrides`. |
| `model_reasoning_effort` | from CC `effort` (low/medium/high/**xhigh**) | xhigh is new. Direct value map. |
| `model_verbosity` (low/medium/high) | new; optional | If CC surfaces an equivalent. |
| `[sandbox_workspace_write]` `writable_roots`, `network_access` | from CC `sandbox.filesystem.allowWrite` + `permissions.additionalDirectories` + `sandbox` network | Currently only coarse `sandbox_mode` is emitted. |
| `approval_policy` granular object form | from `permissions.defaultMode` + deny/ask density | Latest Codex supports `{ granular = { sandbox_approval, rules, mcp_elicitations, request_permissions, skill_approval } }`. Current intent-based string map (`untrusted`/`on-request`/`never`) is lossy — keep string form as fallback, add object form when richer CC permissions exist. |
| `model_instructions_file` | optional | Renamed from deprecated `experimental_instructions_file`. |
| `project_doc_fallback_filenames` | should include `CLAUDE.md` | Lets Codex read CLAUDE.md directly as fallback — reduces divergence. |
| `[tools]` `web_search` (object), `view_image` | from CC equivalents if any | `web_search` now `{ context_size, allowed_domains, location }`. |

### 3C. AGENTS.md — precedence + override

- **Current:** writes `AGENTS.md` + subdir `AGENTS.md` (only if subdir exists) + warns if `AGENTS.override.md` present. Honors 32KB limit (`CODEX_SIZE_LIMIT`).
- **Latest precedence:** `AGENTS.override.md` > nearest `AGENTS.md` > parent dirs > `~/.codex/AGENTS.md`. Concatenated root-to-leaf, deeper wins. Adapter behavior is broadly correct; align managed-section docs with `project_doc_max_bytes` (32KiB) and `project_root_markers`. Consider emitting `~/.codex/AGENTS.md` (user scope) for user-scope rules.

### 3D. Codex-native skills (replaces deprecated custom prompts)

- **Current:** writes skills/agents/commands as `.agents/skills/<name>/SKILL.md`. Codex's actual skills dir is `CODEX_HOME/skills/<name>/SKILL.md` (default `~/.codex/skills`). **Custom prompts (`~/.codex/prompts/*.md`) are deprecated** in favor of skills — good that we don't emit those. Verify `.agents/skills` is the path Codex actually reads vs `~/.codex/skills`; this may be a **path correctness bug**.

### 3E. Hooks — expand event map (gated, EXPERIMENTAL)

- **Current map:** `SessionStart`→`SessionStart`, `Stop`→`Stop`, `PostToolUse`→`AfterToolUse`; `PreToolUse` skipped; http skipped; only writes when `[features] hooks = true` already set.
- **Latest Codex `[hooks.<Event>]`:** supports `PreToolUse`, `PostToolUse`, `PermissionRequest`, `SessionStart`, `UserPromptSubmit`, `Stop`. Add `PreToolUse` and `UserPromptSubmit` mappings; add `[features]`/`[agents.<name>]`/`[permissions.<name>]`/`[memories]` awareness.

---

## Section 4 — CROSS-ADAPTER IMPROVEMENTS

1. **AGENTS.md as a shared capability.** Only `codex` and `opencode` emit `AGENTS.md` today. It is becoming the cross-harness standard instruction file (Codex, plus broad adoption). Consider a base-class `sync_agents_md()` helper (managed-section aware) that any adapter can opt into, and document which targets read AGENTS.md natively.
2. **MCP transport normalization (all MCP-writing adapters).** Centralize: prefer `http`, treat `streamable-http` as alias for `http`, treat `sse` as deprecated. Update `env_translator.TRANSPORT_SUPPORT` sets (cursor/windsurf/cline/neovim still list `sse`). Emit a deprecation warning when a source server uses `type: sse`.
3. **MCP env-var expansion `${VAR:-default}`.** CC supports `${VAR}` and `${VAR:-default}` in command/args/env/url/headers. Confirm `config_vars.substitute_config_vars` / `env_translator` handle the `:-default` form for every adapter.
4. **`settings.env` propagation.** Once SourceReader surfaces `env`, route it to adapters with env maps (Codex `[shell_environment_policy].set`, Continue, Zed, Windsurf).
5. **Namespaced commands/agents (rglob).** Fixing the reader (Section 2 low-value) benefits every adapter uniformly.
6. **`model` propagation.** Surfacing `model` lets Codex/Continue/Zed adapters emit a real default model instead of relying on `modelOverrides`.

---

## Section 5 — PRIORITIZED PLAN (independently-shippable)

Ordered. Each item: **effort (S/M/L)** and **risk**. Groups: **(A) Gemini removal**, **(B) Codex modernization**, **(C) CC new-surface support**, **(D) tests/docs/counts**.

### Group A — Gemini removal (do as one milestone, in this order)

- [ ] **A1. Root delete + constant + MCP schema** — S, **risk: M** (constant cascade). Files: `src/adapters/gemini.py` (delete), `src/adapters/__init__.py`, `src/utils/constants.py`, `src/mcp/schemas.py`. Gate: `pytest` + `grep gemini src/adapters` = 0.
- [ ] **A2. Hard-coded gemini tables** — M, risk: M. Files: §1B list (env_translator, harness_validator, model_routing, permission_translator, harness_cost_advisor, reverse_sync, harness_comparison, compatibility_reporter, harness_feature_matrix, token_estimator, harness_readiness, context_budget_sync, config_health, config_linter, secret_detector, env_var_matrix, filter_rules).
- [ ] **A3. Fan-out scrub (per-harness map entries)** — M, risk: L. Files: §1C (~80 files). Mechanical; gate on `grep -rin gemini src/` → 0 + pytest.
- [ ] **A4. Commands py + md** — S, risk: L. Files: §1D.
- [ ] **A5. Tests prune + delete** — M, risk: M (assertion totals 11→10). Files: §1E. Delete `verify_task1/2_gemini.py`, likely `verify_phase13_native_formats.py`.
- [ ] **A6. Artifact + scripts + manifests + CI** — S, risk: L. Files: `GEMINI.md` (delete), `scripts/*.sh`, `.claude-plugin/*.json`, `.github/workflows/sync-state-validate.yml`.
- [ ] **A7. Docs + counts + re-sync dotfiles** — S, risk: L. Files: README/CLAUDE/AGENTS/CONVENTIONS + run sync to regenerate dotfiles; optional `.planning` deprecation note + SYNC-CHANGELOG entry.

### Group B — Codex modernization

- [ ] **B1. Verify/fix Codex skills dir path** (`.agents/skills` vs `~/.codex/skills`) — S, **risk: M** (correctness; could mean skills aren't discovered today). Files: `src/adapters/codex.py`.
- [ ] **B2. MCP HTTP transport first-class** (`http_headers`, `env_http_headers`, explicit bearer mapping, per-tool `approval_mode`) — M, risk: M. Files: `codex.py`, `src/utils/toml_writer.py`, `env_translator.py`.
- [ ] **B3. New config.toml keys** (`model`, `model_reasoning_effort` incl. xhigh, `model_verbosity`, `model_instructions_file`, `project_doc_fallback_filenames=["CLAUDE.md"]`) — M, risk: L. Files: `codex.py`. (Depends on C2/C3 for `model`/`effort` sources.)
- [ ] **B4. `[sandbox_workspace_write]` + granular `approval_policy`** — M, risk: M (permission semantics; never downgrade deny). Files: `codex.py`, `permission_translator.py`. (Depends on C4 sandbox + defaultMode surfacing.)
- [ ] **B5. Hook event map expansion** (`PreToolUse`, `UserPromptSubmit`) — S, risk: L (gated behind `[features] hooks`). Files: `codex.py`.

### Group C — Claude Code new-surface support (SourceReader)

- [ ] **C1. MCP enable/disable gates** (`enableAllProjectMcpServers`/`enabledMcpjsonServers`/`disabledMcpjsonServers`) — M, **risk: M** (changes which servers sync). Files: `src/mcp_reader.py`, `discover_all`. **Correctness/safety win.**
- [ ] **C2. Surface `settings.env`** — S, risk: L. Files: `src/modular_reader.py`, `discover_all`. Unlocks B3 + cross-adapter env.
- [ ] **C3. Surface `model` + `effort`** — S, risk: L. Files: `modular_reader.py`, `discover_all`. Unlocks B3.
- [ ] **C4. Surface `permissions.defaultMode` + `additionalDirectories` + `sandbox` block** — M, risk: M. Files: `modular_reader.py`, `utils/permissions.py`. Unlocks B4.
- [ ] **C5. `outputStyle` + `.claude/output-styles/*.md`** — M, risk: L. Files: `modular_reader.py`, `discover_all`; consumers in system-prompt adapters (zed/neovim/continue).
- [ ] **C6. Namespaced agents/commands via rglob + `cc_mcp_global` cleanup** — S, risk: L. Files: `modular_reader.py`, `config_discovery.py:58`.
- [ ] **C7. MCP transport normalization (http/streamable-http; deprecate sse)** — S, risk: L. Files: `env_translator.py` (TRANSPORT_SUPPORT sets) + per-adapter MCP writers. Cross-adapter.
- [ ] **C8. statusLine + user-scope hooks/hooks.json + ancestor CLAUDE.md + managed-settings** — L, risk: M. Lower ROI; defer.

### Group D — tests / docs / counts

- [ ] **D1. Update harness counts** 12→11, 11→10 across README/CLAUDE/AGENTS/CONVENTIONS + `test_new_modules.py:34` — S, risk: L. (Folds into A7/A5.)
- [ ] **D2. Add tests for new Codex keys** (B2–B5) — M, risk: L. Files: new `tests/test_codex_modernization.py`.
- [ ] **D3. Add tests for new SourceReader surfaces** (C1–C6) — M, risk: L. Files: extend `test_new_settings_sync.py`, `test_mcp_enhancements.py`.
- [ ] **D4. Docs: document AGENTS.md cross-harness standard + new surfaces** — S, risk: L. Files: README, `docs/`.

**Suggested sequencing:** A1→A7 first (clears deprecated weight, stabilizes counts). Then C1–C3 (cheap reader surfacing) which unblocks B2–B4. B1 in parallel (independent path fix). D items track alongside their feature group.

---

## Appendix — Verification gates

- `python3 -m pytest tests/` green after every group.
- `grep -rin gemini src/ commands/ scripts/` → 0 (excluding intentional history) after Group A.
- After A7, run `python3 src/commands/sync.py --dry-run` and confirm no `gemini`/`GEMINI.md` targets appear and `list_targets()` returns 10.
- For Codex (B): round-trip a sample CC config through the adapter and diff emitted `config.toml` against the latest schema keys.
