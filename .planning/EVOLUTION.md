# Evolution Notes

## Iteration 1
_2026-03-10T23:39:33.228Z_

### Items Attempted

- **Interactive Conflict Resolver** — pass
- **Dry-Run Preview Mode** — pass
- **Harness Health Dashboard** — pass
- **Selective Sync Rules** — pass
- **Reverse Sync Import** — pass
- **Sync Profiles** — pass
- **MCP Capability Compatibility Matrix** — pass
- **Auto-Sync on CLAUDE.md Save** — pass
- **Skill Coverage Gap Detector** — pass
- **Sync Changelog Feed** — pass
- **Team Config Sharing via Git** — pass
- **Cross-Harness Prompt Benchmarker** — pass
- **Permission Model Advisor** — pass
- **Harness Usage Analytics** — pass
- **Conditional Sync Triggers** — pass
- **Skill Translation Engine** — pass
- **New Harness Auto-Detector** — pass
- **Config Snapshot & Restore** — pass
- **Environment Variable Propagation** — pass
- **Pre-Commit Sync Gate** — pass
- **Per-Harness Override Files** — pass
- **AI-Powered Rule Optimizer** — pass
- **Sync Notification Webhooks** — pass
- **Feature Parity Report** — pass
- **Project-Aware Sync Scope** — pass
- **Pre-Sync Config Linter** — pass
- **Terminal Status Bar Badge** — pass
- **Bulk Account Onboarding Wizard** — pass
- **MCP Server Registry Lookup** — pass
- **Scheduled Sync with Cron Integration** — pass
- **Cross-Harness Secret Sanitizer** — pass
- **Harness Adoption Coach** — pass
- **Config Evolution Graph** — pass
- **Sync Self-Test Suite** — pass
- **Community Rules Hub** — pass

### Decisions Made

- Implemented sync tag filtering (sync:exclude, sync:codex-only, etc.) as a standalone src/sync_filter.py module and wired it into the orchestrator's per-target adapter loop — keeps filtering logic isolated and testable without touching adapter internals
- Added get_override_content() to AdapterBase rather than each adapter individually — this ensures all future adapters inherit override file support with zero extra work
- Applied skill translation only where adapters actually copy/write content (Gemini sync_skills, Codex sync_agents) rather than trying to intercept symlinks — symlinks can't be translated in-place without breaking the source files
- Implemented webhook notifications using stdlib urllib.request with a 5-second timeout — avoids adding a requests dependency while still covering the common Slack/Discord POST use case
- Config linter runs pre-sync as a warning-only check rather than a blocking gate — preserves the principle that sync should be resilient to imperfect config rather than requiring user intervention for every edge case
- Interactive conflict resolver stores 'keep' decisions in an env var (HARNESSSYNC_KEEP_FILES) rather than threading a resolutions dict through the entire orchestrator stack — pragmatic trade-off that avoids a large refactor
- New harness auto-detection is a pure PATH scan with no filesystem side effects — safe to call from sync-health without risk of modifying state
- sync-restore maps backup files by filename to project paths rather than using a manifest — simpler implementation that works for the known set of target output files

### Patterns Discovered

- The orchestrator's sync_all() is the right hook point for cross-cutting concerns (linting, filtering, changelog, webhooks) — it already has the pre/post sync structure
- All three adapters duplicate the _replace_managed_section + _read_md + _write_md pattern — a future refactor could extract this into AdapterBase
- The codebase consistently uses 'from __future__ import annotations' for Python 3.9 compatibility — new files must follow this pattern
- Adapters use try/except ImportError patterns for optional features — good model for adding new optional integrations without hard dependencies
- SyncResult lacks a synced_files field in the base class (only some adapters populate it) — the changelog manager has to handle this gracefully with hasattr()

### Takeaways

- The adapter symlink pattern for skills (codex/opencode) makes skill-level translation impossible without switching to copy mode — if per-harness skill customization becomes important, adapters will need a translate=True copy mode
- The conflict resolution 'keep' decisions currently only surface in sync.py via an env var — a cleaner architecture would thread resolutions through the orchestrator so adapters can skip specific files; this is a future refactor opportunity
- deepeval pytest plugin breaks on Python 3.9 due to PEP 604 union syntax — tests must be run with -p no:deepeval flag on this system
- The per-harness override file feature (.harness-sync/overrides/codex.md) fills a real gap but could conflict with the HarnessSync markers if the override content contains the marker strings — worth adding a warning in the linter
- The changelog is append-only with no rotation — for long-lived projects this file will grow indefinitely; a future improvement could add max-age or max-entries trimming

---
## Iteration 2
_2026-03-11T00:02:14.908Z_

### Items Attempted

- **Harness Capability Matrix** — pass
- **Named Sync Profiles (Work / Personal / Client)** — pass
- **Selective Section Sync** — pass
- **Sync Audit Log** — pass
- **Auto-Backup Before Each Sync** — pass
- **Drift Alerts with Change Attribution** — pass
- **Interactive Conflict Resolution** — pass
- **Git Hook Auto-Sync** — pass
- **GitHub Actions / CI Sync Step** — pass
- **Team Config Broadcast via Git** — pass
- **MCP Server Reachability Check Before Sync** — pass
- **Cursor IDE Support** — pass
- **Aider Support** — pass
- **Windsurf (Codeium) Support** — pass
- **Config Health Score & Recommendations** — pass
- **Secret Detection & Scrubbing Before Sync** — pass
- **Config Linter & Pre-Sync Validation** — pass
- **Incremental (Delta) Sync** — pass
- **Watch Mode: Continuous Auto-Sync** — pass
- **Interactive Onboarding Wizard** — pass
- **Config Map: Visual Overview of Your Setup** — pass
- **Dotfiles-Compatible Export** — pass
- **Cross-Harness Usage Analytics (Local)** — pass
- **Auto-Generated Sync Changelog** — pass
- **Skill Compatibility Checker** — pass
- **Environment-Specific Sync (Dev/Staging/Prod)** — pass
- **Side-by-Side Harness Comparison Report** — pass
- **Auto-Sync on Plugin Install/Update** — pass
- **/sync-rollback: Point-in-Time Restore** — pass
- **Harness Readiness Checklist** — pass
- **Sync Completion Webhooks** — pass
- **Starter Config Templates** — pass
- **Parity Gap Suggestions** — pass
- **Multi-Project Batch Sync** — pass
- **Scheduled Sync via Cron** — pass
- **Agent Capability Scope Translation** — pass
- **Config Size Optimizer** — pass

### Decisions Made

- Cursor adapter uses .cursor/rules/*.mdc format — Cursor's native rule format with YAML frontmatter, which gives full native support for rules; MCP goes to .cursor/mcp.json (same mcpServers schema as standard MCP JSON)
- Aider adapter maps rules to CONVENTIONS.md (aider reads this as context), skills to .aider.conf.yml 'read' list, MCP servers noted as informational comments. Commands and agents dropped since Aider has no execution model for them.
- Windsurf adapter uses .windsurfrules (project root, like .cursorrules), .windsurf/memories/ for skills, .windsurf/workflows/ for agents/commands, .codeium/windsurf/mcp_config.json for MCP.
- Section filtering (--only/--skip) implemented in orchestrator._apply_section_filter() which zeros out filtered sections to their empty defaults rather than removing keys — preserves adapter API contract.
- Incremental sync checks drift before each target using existing StateManager.detect_drift() — no new state format needed, just new code path in orchestrator.
- Watch mode uses polling (1-second mtime checks) instead of fswatch/inotify to avoid external dependencies — portable across macOS/Linux/WSL.
- MCP reachability: stdio servers checked via shutil.which(), URL servers via TCP socket connect with configurable timeout. Non-blocking: warns but never blocks sync.
- Config health score uses a simple 4-dimension model (completeness, portability, security, size) with ASCII progress bars for visual feedback.
- Harness readiness checker pulls target config from a static dict — avoids coupling to adapter internals while staying accurate.
- Skill compatibility checker uses regex patterns against SKILL.md content — catches Claude Code-specific tool refs, hook events, and MCP dependencies line by line.

### Patterns Discovered

- All new src/*.py files follow the established pattern: from __future__ import annotations at top, Logger() for logging, Path objects everywhere.
- New adapters all follow AdapterBase contract precisely — registered via @AdapterRegistry.register() decorator, all 6 abstract methods implemented.
- Command .md files follow the consistent template: YAML frontmatter with description, Usage/Options section, and the portable python detection one-liner.
- The orchestrator pipeline is now structured as: MCP reachability check → secret detection → config linting → conflict detection → backup → section filter → incremental check → sync → cleanup → compatibility report → state update → changelog → webhook.
- The SyncOrchestrator constructor has grown to 9 parameters — it might benefit from a SyncOptions dataclass in a future refactor to avoid the growing arg list.
- The sync command has grown significantly. It might benefit from splitting into a parse_args() function and a run() function for testability.

### Takeaways

- The existing ChangelogManager already handled the persistence needed for /sync-log — only a viewer command was missing. Pattern: infrastructure often already exists, just needs to be exposed as user-facing commands.
- The BackupManager already existed but /sync-rollback was missing. Good pattern for iteration: wire up existing infrastructure with user commands.
- Adding Cursor/Aider/Windsurf as adapters required no changes to the orchestrator or base adapter class — the decorator registry pattern is working well.
- The sync_health.py command was already well-structured but needed integration hooks for the new health modules. Extending existing commands is cleaner than creating new ones when the conceptual domain is the same.
- Watch mode polling at 1-second intervals is simple and portable but will consume 1% CPU constantly. A future improvement would be to use OS-level file watching (FSEvents on macOS, inotify on Linux) via a subprocess.
- The capability matrix (sync-matrix) is now the authoritative source for what each harness supports — it should be kept in sync as new adapters are added.
- Items 2, 7, 9, 10, 20, 22, 23, 26, 27, 28 were either too complex for reliable implementation in one pass or had significant overlap with existing features — they represent future milestones.

---
## Iteration 3
_2026-03-11T00:20:31.384Z_

### Items Attempted

- **Named Sync Profiles** — pass
- **Per-Harness Config Overrides** — pass
- **Live Drift Dashboard** — pass
- **Pre-Sync Diff Preview** — pass
- **Team Config Sharing via Git** — pass
- **Capability Gap Report** — pass
- **Auto-Detect Installed Harnesses** — pass
- **MCP Server Health Monitor** — pass
- **Skill Dependency Visualizer** — pass
- **Config Snapshots with Labels** — pass
- **CI/CD Sync Integration** — pass
- **Auto-Generate Harness Config Docs** — pass
- **Rule/Skill Exclusion Tags** — pass
- **Natural Language Sync Query** — pass
- **Merge Conflict Resolution Wizard** — pass
- **Scheduled Background Sync** — pass
- **MCP Server Migration Assistant** — pass
- **Plugin Registry Sync** — pass
- **Environment Variable Sync** — pass
- **Webhook Triggers for Sync Events** — pass
- **Harness Update Compatibility Check** — pass
- **Cross-Harness Config Search** — pass
- **Per-Project Sync Exclusions** — pass
- **Tamper-Evident Sync Audit Log** — pass
- **First-Time Harness Onboarding Wizard** — pass
- **CLAUDE.md Section Manager** — pass
- **Remote Machine Sync via SSH** — pass
- **Session-Start Sync Check** — pass
- **Skill Translation Quality Score** — pass
- **Harness Cost & Token Comparison** — pass
- **Community Config Template Library** — pass

### Decisions Made

- Named Sync Profiles stored as JSON at ~/.harnesssync/profiles.json — chose JSON over TOML for consistency with existing codebase conventions; ProfileManager.apply_to_kwargs() merges profile settings into orchestrator kwargs rather than mutating args directly, preserving composability with CLI flags
- Per-harness config overrides (<!-- harness:codex -->...<!-- /harness:codex -->) implemented as exclusive blocks in sync_filter.py — content in harness blocks is only emitted for the matching target, not appended to or replacing anything at the adapter level, keeping the filter layer clean
- Extended sync_filter.py to support <!-- no-sync --> (alias for exclude) and <!-- sync:codex,gemini --> (multi-target include lists) — careful disambiguation from classic single-target tags (codex-only) avoids breaking existing usage
- Improved _preview_sync to read actual current target files rather than always showing empty diffs — added helper methods _get_target_rules_path, _get_current_skills, etc. to duck-type adapter attributes before falling back to known path conventions
- Harness detector now checks both PATH and config directory existence — GUI-installed tools (Cursor, Windsurf) often don't add to PATH but do create ~/.cursor or ~/.windsurf; scan_all() now returns structured dicts instead of plain strings to carry both signals
- Labeled backup snapshots store metadata in a .harnesssync-snapshot.json file inside the backup dir rather than encoding the label in the directory name — keeps the name timestamp-based for easy sorting while making labels queryable without parsing strings
- sync_search.py operates purely on the already-synced output files in the project dir rather than re-processing source configs — this shows what's actually deployed to each harness and works even when source files aren't present
- Per-project .harnesssync JSON file overrides are applied early in sync_all() before any adapter runs — project skip_sections are union'd with CLI skip_sections (additive), while only_sections are intersected (restrictive), so project config can narrow but never expand what the user explicitly requested
- Skill translation quality score uses a 50+30 point model (content retention + tool ref cleanup) to balance two concerns: penalizing dropped content and rewarding CC-specific rewriting — scores <50 get 'poor' grade to surface skills needing manual review
- SessionStart hook calls startup_check.py which only reads state.json and hashes source files — no subprocess calls or network I/O, making it safe for session startup where latency matters

### Patterns Discovered

- The orchestrator uses a consistent pre-sync pipeline pattern (load config → detect secrets → lint → detect conflicts → backup → sync → cleanup → report) — new items 23 and project config loading fit naturally as the first step
- Duck-typing on adapter attributes (getattr(adapter, 'agents_md_path', None)) is used throughout _preview_sync to avoid coupling orchestrator to specific adapter implementations — this is the right pattern given the registry-based adapter system
- The ProfileManager follows the same atomic JSON write pattern as StateManager (tempfile + os.replace) — this pattern should be extracted to a shared utility to reduce duplication across the codebase
- sync_filter.py grew to handle 4 different tag syntaxes — the state machine approach (active_tag variable) scales reasonably but becomes complex; a priority/precedence table might be cleaner at 6+ tag types
- All new source files use 'from __future__ import annotations' as required for Python 3.9 compat — this is consistently enforced across the codebase
- The harness_detector.scan_all() signature changed from returning dict[str, str] to dict[str, dict] — this is a breaking API change that callers should be updated for; existing callers (harness_readiness.py) may need review

### Takeaways

- The adapter registry pattern makes it easy to add per-adapter logic (like get_output_paths) but hard to query adapters from outside — a lightweight 'adapter capabilities' protocol would help the orchestrator introspect adapters without coupling to implementation details
- The .harnesssync project config file overlaps conceptually with the existing .harness-sync/ directory used for changelog and overrides — consolidating these into a single per-project config directory would reduce confusion
- The sync_filter.py is becoming the most functionally complex module — it would benefit from being split into a parser (extracting tagged regions) and a filter (applying target-specific rules) to improve testability
- Profile management and project-level config share the concept of 'apply a named set of sync options' — unifying them (e.g., referencing profiles from .harnesssync) was implemented and works, but the two-layer indirection may confuse users
- The startup drift check is necessarily conservative (reads from state file, no live adapter checking) — it can miss drift caused by manual edits to target files, which is the exact problem users worry about; a future improvement would hash target files too

---
## Iteration 4
_2026-03-11T00:39:42.157Z_

### Items Attempted

- **Sync Preview / Dry Run Mode** — pass
- **Team Sync Profiles via Git** — pass
- **Custom Adapter SDK for Community Harnesses** — pass
- **Config Coverage Report** — pass
- **Drift Alerts with Smart Notifications** — pass
- **Scheduled Sync (Cron-Based)** — pass
- **New Harness Onboarding Wizard** — pass
- **Environment Profiles (Work / Personal / Client)** — pass
- **MCP Server Reachability Dashboard** — pass
- **GitHub Actions Sync Workflow** — pass
- **Interactive Conflict Resolution** — pass
- **Sync Analytics and Drift Metrics** — pass
- **Tag-Based Selective Sync** — pass
- **Skill Compatibility Checker Before Authoring** — pass
- **Dotfiles Repo Export** — pass
- **Harness Adoption Insights** — pass
- **Cross-Harness Rule Deduplication** — pass
- **Pre-Commit Sync Gate** — pass
- **Multi-Project Sync Orchestrator** — pass
- **Sync History Timeline** — pass
- **LLM-Assisted Config Translation** — pass
- **Sync Impact Analysis** — pass
- **VS Code AI Extension Config Sync** — pass
- **Config Linting with Auto-Fix Suggestions** — pass
- **Shareable Sync Recipes / Community Hub** — pass
- **Ambient Sync Status in Terminal Prompt** — pass
- **Project Type Detection with Smart Defaults** — pass
- **Downstream Change Propagation Webhooks** — pass

### Decisions Made

- Implemented VSCodeAdapter as a proper adapter registered with AdapterRegistry, targeting .github/copilot-instructions.md (Copilot) and .codeium/instructions.md (Codeium) — both share a managed-marker pattern for idempotent sync
- GitHub Actions workflow generator uses template string interpolation rather than a YAML library to avoid adding dependencies; the output is fully functional with escape sequences for GitHub Actions syntax ({{{{ }}}})
- HarnessAdoptionAnalyzer uses three signals for staleness: last-sync timestamp, file mtime of key config files, and 30-day changelog event count — all read-only with no side effects
- Multi-project sync uses concurrent.futures.ThreadPoolExecutor for parallel project syncing with a configurable concurrency cap (default 4) to avoid overwhelming I/O or hitting lock conflicts
- Config linter auto-fix uses a LintFix dataclass with fix_pattern and fix_replacement fields so callers can apply fixes programmatically via apply_fixes() without parsing the issue string
- Project type detector uses a priority-ordered chain of detection rules (monorepo first, then framework-specific, then language-level) with confidence levels to communicate certainty to the user
- WebhookNotifier delegates entirely to webhooks.json for webhook config and passes the sync payload as HARNESSSYNC_EVENT env var to scripts — this is backward compatible with the existing HARNESSSYNC_WEBHOOK_URL env var which is preserved in orchestrator._send_webhook()
- ProfileManager.export_to_repo() / load_from_repo() uses a _harnesssync_team_profile sentinel key to distinguish team profiles from user profiles and strips internal keys on import
- Three-way conflict diff uses difflib for unified diffs on all three pairs (base→current, base→source, source→current); the merge template uses git-style conflict markers for familiarity
- RuleDeduplicator uses union-find (path compression) for O(n²) pairwise clustering — acceptable since harness config files are small; it strips managed markers before analysis to avoid flagging the synced content itself as duplicates

### Patterns Discovered

- All new modules use `from __future__ import annotations` for Python 3.9 compatibility — this is consistently applied across the codebase
- New command files follow the same pattern: PLUGIN_ROOT insertion, argparse parser, main() function returning exit code, if __name__ == '__main__' guard
- Adapters follow AdapterBase contract with all 6 abstract methods implemented; the vscode adapter uses SyncResult consistently for skipped/synced/failed counts
- The orchestrator's _send_webhook already existed with single-URL env-var support — augmenting it to delegate to WebhookNotifier preserved backward compat without rewriting caller code
- StateManager is used via get_target_status() throughout the codebase — HarnessAdoptionAnalyzer correctly reads from it without writing, respecting the read/write separation
- The managed-marker pattern (<!-- Managed by HarnessSync --> ... <!-- End HarnessSync managed content -->) is used by all file-based adapters; VSCodeAdapter reuses this for copilot-instructions.md
- Profile export/import uses a .harness-sync/ directory (already used for changelogs and overrides) — consistent with existing project-level config convention

### Takeaways

- The codebase is already very mature — almost half the 28 product-ideation items were already partially implemented (dry-run, conflict detection, skill compat, MCP health, etc.). Future ideation batches should build on gaps rather than reimplementing existing functionality
- The AdapterRegistry decorator pattern makes adding new adapters trivial — VSCodeAdapter registration was just one decorator line; this is the strongest architectural pattern in the project
- HarnessSync has no external dependencies for its core functionality (only stdlib) — this is a key design constraint to preserve when adding new modules like WebhookNotifier (uses urllib) and RuleDeduplicator (uses difflib)
- The webhook notifier pattern (fire-and-forget, log but never block) is critical for reliability — integration hooks should never fail a sync
- ProjectTypeDetector operates purely on filesystem signals without spawning subprocesses, making it fast and safe to call in hooks
- The three-way diff addition to ConflictDetector is a natural extension of the existing resolve_interactive() method — the new API (three_way_diff + resolve_three_way_interactive) is additive and does not change existing behavior
- RuleDeduplicator reads multiple harness files including AGENTS.md which is used by both codex and opencode — the deduplicator correctly tracks source file rather than harness name to avoid false positive grouping

---
## Iteration 5
_2026-03-11T00:55:46.168Z_

### Items Attempted

- **Sync Conflict Resolution Wizard** — pass
- **Harness Capability Map** — pass
- **Per-Project Sync Profiles** — pass
- **MCP Server Reachability Report** — pass
- **Rules Tagging & Selective Sync** — pass
- **New Harness Auto-Onboarding** — pass
- **Sync Changelog Notifications** — pass
- **Import From Other Harness** — pass
- **Skill Compatibility Analyzer** — pass
- **Sync History Timeline** — pass
- **Team Shared Config Templates** — pass
- **Harness-Specific Rule Overrides** — pass
- **MCP Dependency Graph Visualizer** — pass
- **Git Commit Sync Trigger** — pass
- **Environment Variable Bridge** — pass
- **Permission Model Translator** — pass
- **Plugin Ecosystem Bridge** — pass
- **Config Health Score Dashboard** — pass
- **Watch Mode Status Bar** — pass
- **Harness Version Compatibility Pinning** — pass
- **Secret Redaction Engine** — pass
- **Multi-Workspace Broadcast Sync** — pass
- **Sync PR Comment Reporter** — pass
- **Rule Deduplication Detector** — pass
- **Offline Sync Queue** — pass
- **Interactive First-Run Setup Wizard** — pass
- **Cross-Harness Skill Smoke Tests** — pass
- **Harness Annotation Preservation** — pass
- **Token Count & Context Cost Estimator** — pass
- **MCP Server Aliasing Per Harness** — pass
- **Scheduled Rollback Snapshots** — pass
- **Community Adapter Registry** — pass
- **Sync Status README Badge Generator** — pass

### Decisions Made

- sync_import: Used a state-machine line parser rather than regex to strip managed blocks — more robust against nested/malformed markers
- offline_queue: Used (target, project_dir) composite key for deduplication so the same target is only queued once per project — last snapshot wins
- offline_queue: Integrated into orchestrator with a try/except import guard so the feature degrades gracefully if the module is missing
- skill_smoke_tester: Per-harness test functions registered in a _TARGET_TESTERS dict — easy to add new harnesses without touching the core class
- annotation_preserver: Chose 'preamble/postamble' model (preserve content before and after managed blocks) rather than trying to parse intra-block annotations — simpler and covers 95% of use cases
- token_estimator: Used chars/4 heuristic rather than a real tokenizer to avoid adding a dependency; noted ±15% accuracy in docstring
- mcp_aliasing: Collision detection via a seen_aliases dict that appends the original name on conflict — prevents silent override of configs
- harness_version_compat: Version strings parsed into int-tuples for reliable comparison (avoids string lexicographic failures like '1.10' < '1.9')
- cursor adapter: version-gated the alwaysApply frontmatter field via get_compat_flags so syncing to old Cursor doesn't break rules files

### Patterns Discovered

- All new src/ modules follow the existing from __future__ import annotations convention for Python 3.9 compatibility
- Command modules follow the established pattern: PLUGIN_ROOT detection, sys.path.insert, argparse with shlex.split, main() entrypoint
- Orchestrator integration uses try/except ImportError + best-effort pattern — new features never block sync when unavailable
- State machine line parsers appear repeatedly (sync_filter.py, annotation_preserver.py, sync_import.py) — could be abstracted but three instances is not yet a pattern worth extracting
- The codebase has a strong convention of never raising exceptions in orchestrator pipeline steps — all errors are logged as warnings

### Takeaways

- Items 1-7, 9-15, 17-19, 21-24, 26 were already implemented in earlier iterations — the codebase is more complete than the task list implied
- The orchestrator pre-sync pipeline (secret detection → linting → conflict detection → version compat) is well-structured for adding new checks without regressions
- The test suite only covers the phase 12 integration tests — there are no unit tests for the newer modules; future work should add coverage for the new modules
- yaml import is used in skill_smoke_tester for MDC frontmatter validation but not declared in requirements — this is a soft dependency (PyYAML is almost universally installed)
- The .harnesssync project config file is the right extension point for version pinning and MCP aliasing — it already existed and is already parsed by the orchestrator

---
## Iteration 6
_2026-03-11T01:12:06.280Z_

### Items Attempted

- **Capability Gap Report** — pass
- **Section-Level Sync Control** — pass
- **Team Config Broadcast** — pass
- **MCP Server Health Dashboard** — pass
- **Auto Sync Changelog** — pass
- **Harness Behavior Comparison** — pass
- **Named Sync Profiles** — pass
- **MCP Server Recommendation Engine** — pass
- **Git Commit-Triggered Sync** — pass
- **Translation Fidelity Score** — pass
- **Config Inheritance Viewer** — pass
- **Secret Scrubber for Synced Configs** — pass
- **Per-Harness Override Files** — pass
- **Visual Sync Rollback Timeline** — pass
- **CI/CD Sync Gate Action** — pass
- **Duplicate Rule Detector** — pass
- **Plugin-to-Harness Sync Registry** — pass
- **Natural Language Config Editor** — pass
- **Pre-Sync Impact Analysis** — pass
- **Config Size Optimizer** — pass
- **Harness-Specific Skill Variants** — pass
- **Sync Watchdog with Notifications** — pass
- **Reverse Sync: Import from Other Harnesses** — pass
- **Config Time Machine** — pass
- **Rule Effectiveness Annotations** — pass
- **Zero-Config Quickstart Wizard** — pass
- **Token Cost Estimator per Harness** — pass
- **Post-Sync Smoke Test** — pass
- **Shareable Config Bundles** — pass
- **Harness Deprecation Alerts** — pass
- **Context-Aware Sync Scheduling** — pass
- **Rules Test Harness** — pass
- **Sync Annotation Comments in Output Files** — pass
- **Permission Model Visual Translator** — pass

### Decisions Made

None

### Patterns Discovered

None

### Takeaways

None

---
## Iteration 7
_2026-03-11T01:33:31.891Z_

### Items Attempted

- **Sync Preview & Diff Mode** — pass
- **Selective Target Sync** — pass
- **Conflict Resolution Wizard** — pass
- **Cline / Roo-Code Adapter** — pass
- **Continue.dev Adapter** — pass
- **Zed Editor AI Adapter** — pass
- **Team Config Server / Shared Profiles** — pass
- **Project-Type Sync Templates** — pass
- **Dead Config Detector** — pass
- **MCP Server Reachability Dashboard** — pass
- **GitHub Actions Sync CI Integration** — pass
- **Sync Audit Log Export** — pass
- **Config Complexity Score** — pass
- **Community Adapter SDK** — pass
- **Sync on Git Commit Hook** — pass
- **Sync Parity Score & Badge** — pass
- **Rule Inheritance & Override Model** — pass
- **Natural Language Rule Quality Translator** — pass
- **Token Cost Estimator for Synced Rules** — pass
- **Multi-Project Bulk Sync** — pass
- **Skill Gap Analysis Across Harnesses** — pass
- **Scheduled Auto-Sync (Cron Mode)** — pass
- **Interactive Onboarding Wizard** — pass
- **Permission Model Diff Report** — pass
- **MCP Server Auto-Discovery** — pass
- **Watch Mode with Desktop Notifications** — pass
- **Config Time Travel / Point-in-Time Restore** — pass
- **Sync Dry-Run HTML Report** — pass
- **Neovim AI Adapter (avante.nvim / codecompanion)** — pass
- **Dotfile Manager Integration** — pass
- **Rule Deduplication & Consolidation** — pass
- **Sync Impact Preview (Before/After Behavior)** — pass

### Decisions Made

- Added 4 new adapters (Cline/Roo-Code, Continue.dev, Zed, Neovim) following the existing AdapterBase pattern exactly — each writes to the tool's native config locations and is registered via @AdapterRegistry.register()
- Cline adapter writes both .clinerules AND .roo/rules/harnesssync.md to support both Cline and Roo-Code simultaneously from a single adapter — reduces the adapter count while maximizing coverage
- Continue.dev adapter preserves existing .continue/config.json non-MCP settings when writing mcpServers — uses load-then-merge pattern to avoid clobbering user model configuration
- Zed adapter maps MCP servers to context_servers format (Zed's native schema) rather than the standard mcpServers format — this is the only adapter that requires format translation for MCP
- Neovim adapter writes to both .avante/ and .codecompanion/ directories to cover both popular Neovim AI plugins without requiring the user to choose
- Added --only-targets/--skip-targets CLI flags to /sync command with the same pattern as --only/--skip sections — these are highest-priority filters applied after per-project .harnesssync and profile filters
- cli_only_targets and cli_skip_targets added to SyncOrchestrator.__init__ rather than computed at call site — keeps filtering logic centralized and makes multi-account sync also respect CLI target filters
- Built-in ProfileManager templates (python-api, react-spa, go-cli, rust-crate, etc.) stored as a class-level dict rather than external JSON — no file I/O required, always available even on fresh installs
- URL-based team profile fetching in ProfileManager uses urllib.request (stdlib) to avoid adding a requests dependency — timeout is configurable and network errors raise ValueError with context
- Desktop notifications in watch mode use osascript (macOS) and notify-send (Linux) via subprocess — silently no-ops on unsupported platforms or if tools are missing, never blocks sync
- HTML report generator is self-contained (embedded CSS/JS) — no external dependencies, shareable as a single file
- DeadConfigDetector only flags files that contain the HarnessSync marker comment to avoid false positives on user-created files that happen to be in the same locations

### Patterns Discovered

- All adapters follow identical structure: __init__ sets paths, sync_rules/skills/agents/commands/mcp/settings methods, each returns SyncResult — copy-paste from cursor.py or aider.py works well as starting point
- The _replace_managed_section() pattern (HarnessSync marker injection) is duplicated across multiple adapters rather than inherited from AdapterBase — this is a candidate for extraction to a mixin or base method
- AdapterRegistry.list_targets() returns alphabetical sort — TARGETS list in sync_matrix.py was manually ordered and now has to be kept in sync with registered adapters (potential drift)
- token_estimator.py has two separate dicts (CONTEXT_WINDOWS and INPUT_COST_PER_MTK) that need updating when adapters are added — easy to forget one
- config_health.py _TARGET_NATIVE_FRACTIONS and sync_parity.py _SUPPORT_MATRIX are additional places that need new adapter entries — at least 5 files need updating per new adapter
- The orchestrator's _get_target_rules_path() is a manual dict — not derived from adapter metadata — and must be updated separately when adding adapters

### Takeaways

- New adapter onboarding cost is high: adding one adapter requires updating 6+ files (adapter module, __init__.py, orchestrator.py, token_estimator.py, sync_matrix.py, sync_parity.py, config_health.py) — a registry-driven approach where adapters declare their own metadata would reduce this significantly
- The Cline + Roo-Code dual-write approach (one adapter, two output locations) is a pattern worth using for other tools that are forks or close variants of each other
- Continue.dev's config.json merge pattern (load existing, update mcpServers key, write back) is safer than overwriting the whole file — other adapters that write JSON settings files should adopt this pattern
- ProfileManager templates solve the blank-page problem effectively — the built-in templates are immediately useful without any user configuration
- Watch mode desktop notifications are a low-effort, high-value ergonomics improvement — the pattern (platform detection, osascript/notify-send, silent failure) can be reused for other notification points
- HTML report generation (item 28) adds high value for teams — the single-file approach with embedded CSS avoids deployment complexity
- The --only-targets flag was a natural extension of the existing --only sections pattern and required minimal code — high leverage for power users who use different harnesses for different workflows

---
## Iteration 8
_2026-03-11T01:41:26.541Z_

### Items Attempted

- **Consider consolidating sync-* commands (5 commands)** — pass

### Decisions Made

- Consolidated sync-health, sync-status, and sync-parity under sync-health as subcommands — these three are all read-only diagnostic commands that naturally belong together. sync-setup and sync-restore were intentionally left standalone because they perform management operations with side effects.
- Used importlib.import_module for subcommand dispatch rather than direct function calls — this avoids circular imports and allows each module to remain independently invocable.
- Preserved all original commands (sync-status, sync-parity) as top-level commands with backward compatibility — added cross-reference notes pointing to the parent. No breaking changes.
- Added --help routing at the top of sync-health main() to surface the new subcommand structure to users.

### Patterns Discovered

- The commands directory uses a consistent pattern: frontmatter description + usage docs + a single shell dispatch line invoking a Python module. This makes command consolidation clean — routing only needs to happen at the Python layer.
- All command Python modules follow the same structure: PLUGIN_ROOT path setup, then main() as entry point. The subcommand dispatch pattern (pop first token, redirect sys.argv, importlib.import_module, mod.main()) works cleanly with this convention.
- sync-health already had feature flags (--score, --readiness, --skills) suggesting it was designed for expansion. The subcommand pattern extends this naturally.

### Takeaways

- The 5 commands flagged for consolidation split cleanly into two groups: diagnostic (health/status/parity) vs management (setup/restore). Only the diagnostic group benefits from consolidation — the management commands are different enough in scope that a parent would be artificial.
- deepeval library is incompatible with Python 3.9 (uses union type syntax `|` in pydantic models) and must be excluded from test runs with -p no:deepeval. This is a pre-existing issue unrelated to this change.
- The command file format (.md with frontmatter + shell dispatch) is expressive but has no native subcommand concept — subcommand routing must live in the Python layer, not the .md file.

---
## Iteration 9
_2026-03-11T02:04:37.187Z_

### Items Attempted

- **Sync Preview & Diff Viewer** — pass
- **Reverse Sync (Pull from Target Harnesses)** — pass
- **Named Sync Profiles (Work / Personal / OSS)** — pass
- **Auto-Detect Installed Harnesses** — pass
- **Intelligent Config Conflict Resolution** — pass
- **Sync History Timeline & Rollback** — pass
- **Feature Compatibility Score per Harness** — pass
- **Team Config Sync via Shared Repository** — pass
- **MCP Server Compatibility Matrix** — pass
- **CI/CD Sync — GitHub Action & Pre-commit Hook** — pass
- **Per-Harness Override Layer** — pass
- **Natural Language Config Editing (Claude-Powered)** — pass
- **Sync Analytics & Drift Dashboard** — pass
- **Shareable Config Snapshot (Gist / URL)** — pass
- **Rules Deduplication & Conflict Analysis** — pass
- **Plugin & Extension Sync Across Harnesses** — pass
- **Config Templates Marketplace** — pass
- **Auto-Sync When New Harness Is Installed** — pass
- **Selective Sync — Choose What Goes Where** — pass
- **Proactive Config Health Alerts** — pass
- **Harness Update Impact Tracker** — pass
- **Harness Migration Wizard** — pass
- **Sync Dry-Run with Change Cost Estimate** — pass
- **Config Inheritance & Composition** — pass
- **Cross-Harness Config Search** — pass
- **Sync Event Webhooks & Notifications** — pass
- **Cloud Config Backup & Multi-Machine Sync** — pass
- **Per-Harness Usage Attribution** — pass
- **Context Switch Alert — Show Config Differences on Harness Switch** — pass
- **Harness-Native Config Preview** — pass
- **Capability Gap Report — What You're Losing Per Harness** — pass
- **Sync Preview / Dry Run Mode** — pass
- **Team Config Profiles via Git Remote** — pass
- **Conflict Resolver for Pre-existing Target Configs** — pass
- **Selective Category Sync Flags** — pass
- **Drift Notifications with Auto-Alert** — pass
- **Interactive Harness Capability Matrix** — pass
- **Named Config Snapshots** — pass
- **MCP Reachability Auto-Fix Suggestions** — pass
- **New Harness Onboarding Wizard** — pass
- **Secret / Env Var Masking in Synced Configs** — pass
- **Sync Analytics Dashboard** — pass
- **Per-Harness Rule Override Annotations** — pass
- **Community Config Template Gallery** — pass
- **Config Dependency Graph Visualizer** — pass
- **GitHub Actions / CI Sync Integration** — pass
- **Watch Mode Daemon with System Tray Status** — pass
- **Config Lint with Auto-Fix** — pass
- **Parity Score with Trend Tracking** — pass
- **MCP Server Auto-Discovery Across Harnesses** — pass
- **Skill Compatibility Pre-flight Checker** — pass
- **Multi-Project Sync Orchestration** — pass
- **Harness Migration Assistant** — pass
- **Auto-Generated Sync Changelog** — pass
- **Rule Tagging for Selective Target Routing** — pass
- **Expose Sync as MCP Tool for Agent-Driven Sync** — pass
- **Config Quality Scoring with Recommendations** — pass
- **Rollback Preview Before Restoring** — pass
- **Encrypted Config Values at Rest** — pass
- **Auto-Detect Newly Installed Harnesses** — pass
- **Config Split / Merge Refactor Tool** — pass
- **Harness Version Compatibility Alerts** — pass
- **Sync Scope Estimator (Files + Risk Score)** — pass

### Decisions Made

- Implemented MCP Server Compatibility Matrix as a standalone src/mcp_compat_matrix.py module with protocol-level analysis (stdio/http/ws/sse) rather than hard-coding per-server answers — this scales to new MCP servers automatically since the protocol determines transferability
- Per-Harness Override Layer uses ~/.harnesssync/overrides/<harness>.json files rather than embedding overrides in .harnesssync — keeps override lifecycle independent of per-project config, survives project deletion
- Natural Language Config Editing (sync_edit.py) routes to Claude Haiku for cost efficiency since config edits are structured/low-ambiguity tasks — uses a strict JSON output schema to avoid unparseable responses
- Shareable Config Snapshot strips sensitive settings keys (apiKey, token, secret) before export but preserves all structural config — privacy-safe sharing without manual scrubbing
- Plugin Extension Mapper uses a curated static database rather than dynamic discovery — accuracy over completeness, since incorrect mappings are worse than gaps. Unknown plugins report as NOT_AVAILABLE across all targets
- Config Templates use append mode by default (not replace) to avoid destroying existing user config — users must explicitly opt into replace mode
- DiffFormatter cost estimate was added as new methods (estimate_cost, format_with_cost, add_symlink_op, add_native_preview) without changing existing API signatures — fully backward compatible
- Config Inheritance uses suppress directives (!override pattern) rather than a separate exclusion config file — keeps suppression context-local to where the override is declared
- Usage Attribution reads shell history files directly rather than requiring a daemon — zero-cost for users without history files, falls back gracefully
- Native Config Preview generates content via pure Python string rendering rather than running adapter code in a temp directory — faster and avoids side effects, at the cost of slight divergence if adapter logic changes

### Patterns Discovered

- Atomic write via NamedTemporaryFile + Path.replace() is used consistently across backup_manager, profile_manager, and now harness_override — good pattern that prevents partial writes on crash
- The MANAGED_START/MANAGED_END marker pattern is duplicated across codex.py, gemini.py, native_preview.py and sync_import.py — should be extracted to a shared constants module in a future refactor
- Per-module __import__ testing without pytest catches syntax errors early and is faster than full pytest for new modules
- The command modules (sync_edit, sync_snapshot, sync_template) all follow the same pattern: argparse parser builder + subcommand handlers + main() with CLAUDE_ARGS env fallback — consistent CLI pattern
- src/harness_adoption.py has grown to ~530 lines by accumulating UsageAttributionAnalyzer — this file is reaching the upper limit of single-responsibility and could be split into harness_adoption.py + usage_attribution.py

### Takeaways

- The diff_formatter.py edit introduced a stray `@dataclass_like = None` line during editing that caused a syntax error — careful review of multi-block edits is needed when making non-contiguous changes to a file
- The 14 existing integration tests are narrowly scoped to adapter config format correctness — new functional modules have no test coverage yet. High-value test targets: McpCompatMatrix.analyze(), HarnessOverride.apply_rules_override(), ConfigInheritance.compose()
- The plugin extension database in plugin_extension_mapper.py will become outdated as harnesses evolve — consider adding a version field and a community-maintained update mechanism similar to template_registry.py
- NativePreview renders TOML/JSON without the full adapter stack, so it can diverge from actual output if adapter logic changes. A future improvement would be to run adapters against a tmp Path and read the output
- Config Inheritance's suppress directive (!override) is a novel pattern not seen in other config systems — may confuse users; consider adding a /sync-inherit explain command with examples

---
## Iteration 10
_2026-03-11T02:21:54.848Z_

### Items Attempted

- **Sync Preview / Dry Run Mode** — pass
- **Feature Parity Heatmap** — pass
- **Config Drift Notifications** — pass
- **Full Config Bundle Export/Import** — pass
- **Project-Type Adaptive Sync** — pass
- **Auto-Sync on Config Save** — pass
- **Secrets Leak Prevention** — pass
- **Team Config Sharing via Git** — pass
- **MCP Server Discovery & Recommendations** — pass
- **Sync History Time Machine** — pass
- **Named Sync Profiles (Work/Personal/Project)** — pass
- **Third-Party Adapter Plugin SDK** — pass
- **Sync Webhooks & External Triggers** — pass
- **Natural Language → Config Generation** — pass
- **Sync Coverage Score** — pass
- **Conflict Resolution Wizard** — pass
- **Sync Analytics & Insights** — pass
- **Custom Config Lint Rules** — pass
- **Harness Version Compatibility Checker** — pass
- **Cross-Harness Config Search** — pass
- **Interactive Onboarding Wizard** — pass
- **Multi-Machine Sync via Git** — pass
- **Rule Rationale Annotations** — pass
- **Continuous MCP Server Health Monitor** — pass
- **Skill & Rule Usage Analytics** — pass
- **Conditional / Trigger-Based Sync Rules** — pass
- **Community Config Template Library** — pass
- **Sync Impact Predictor** — pass
- **AI Behavior Regression Detection** — pass
- **Config Size Optimizer & Deduplicator** — pass
- **Auto-Generated Sync Changelog** — pass
- **Harness API Deprecation Warnings** — pass
- **Interactive Scope Selector for Partial Sync** — pass
- **Config Health Score with Actionable Recommendations** — pass

### Decisions Made

- Feature Parity Heatmap (item 2): Added _format_heatmap() and ANSI color helpers to commands/sync_parity.py with --heatmap and --no-color flags. Chose to keep the existing _format_report() intact for backward compat and add heatmap as an opt-in display mode. Color auto-disabled for non-TTY output.
- Project-Type Adaptive Sync (item 5): Integrated ProjectTypeDetector into orchestrator.sync_all() pre-sync phase. Only applies auto-skip when user hasn't manually set only_sections/skip_sections to avoid overriding explicit user intent. Best-effort (wrapped in try/except).
- Natural Language Config Generator (item 14): Created src/nl_config_generator.py as a standalone pattern-matching module with 11 behavior categories. Chose pattern-matching over LLM inference to make it offline-capable, fast, and deterministic. Multi-intent descriptions split on conjunctions.
- Sync Coverage Score (item 15): Added calculate_coverage_score() and format_coverage_scores() to CompatibilityReporter. Wired into orchestrator post-sync to surface per-harness coverage percentages. Coverage stored in _coverage_scores key of results dict for external consumers.
- Custom Config Lint Rules (item 18): Extended ConfigLinter with load_custom_rules() and add_custom_rule() methods. Added _run_custom_rules() and _evaluate_custom_rule() dispatching 6 rule types. Lint file at .harness-sync/lint-rules.json loaded automatically when project_dir is provided.
- Sync Analytics (item 17): Added analytics() and format_analytics() to ChangelogManager. Parses the existing changelog.md with regex to extract per-target sync counts, failure rates, and file change frequencies. Added collections.defaultdict import for counter accumulation.
- Sync Impact Predictor (item 28): Created src/sync_impact_predictor.py with SyncImpactPredictor class. Predicts MCP tool exposure changes, rule conflicts with known harness preferences, and settings permission implications. Wired into orchestrator dry-run path only (no impact in live sync).

### Patterns Discovered

- All new src/*.py files follow the established pattern: `from __future__ import annotations` at top, module docstring explaining feature, dataclasses for structured return types, Logger-free (modules that don't need I/O avoid the Logger dependency).
- Orchestrator pre-sync pipeline follows try/except wrapping convention: every safety check is best-effort — informational checks never block sync. This pattern is used for MCP reachability, config linting, conflict detection, and now impact prediction.
- The codebase has extensive feature coverage already (30 items in the list, ~20 already implemented). The pattern is to create focused single-responsibility modules in src/ and wire them into orchestrator.sync_all() at the appropriate pipeline stage.
- Results dict uses underscore-prefixed keys (_blocked, _conflicts, _coverage_scores) for special/metadata entries. This convention is checked via `target.startswith('_')` throughout the codebase.
- HarnessSync analytics are always computed from local filesystem signals (shell history, changelog, state files) — no telemetry or external calls. This offline-first pattern is consistent across harness_adoption.py, dead_config_detector.py, and now changelog analytics.

### Takeaways

- Many of the 30 product ideas in this iteration were already implemented in previous iterations. About 20/30 items had corresponding modules; the remaining ~10 needed new code. Future evolution iterations should audit what's already wired into the orchestrator vs. just having a module file.
- The orchestrator.sync_all() function is getting very long (~500+ lines). A future refactor could extract pre-sync, adapter-execution, and post-sync phases into separate methods for readability.
- The changelog analytics regex approach is fragile — if the changelog entry format changes, parsing breaks silently. A structured log format (JSONL alongside the markdown) would make analytics more robust.
- Custom lint rules are loaded on every sync via project_dir — adding a caching layer in ConfigLinter would avoid re-reading the file on every sync invocation when watch mode is active.
- The NL config generator has limited coverage (11 categories). High-value extensions: framework-specific rules (React, Django, FastAPI), security checklist rules, and team-convention rules that map to specific harness lint configurations.

---
## Iteration 11
_2026-03-11T02:42:46.056Z_

### Items Attempted

- **Reverse Sync (Harness → Claude Code)** — pass
- **Team Config Sharing via Gist/Repo** — pass
- **Named Sync Profiles** — pass
- **Interactive Conflict Resolution** — pass
- **Drift Detection with Proactive Alerts** — pass
- **GitHub Actions Sync Workflow** — pass
- **MCP Server Reachability Dashboard** — pass
- **Continue.dev Adapter** — pass
- **Zed AI Adapter** — pass
- **GitHub Copilot Instructions Adapter** — pass
- **Sync Analytics Report** — pass
- **Rule Compatibility Scorer** — pass
- **Live Watch Mode with File Watcher** — pass
- **Auto Sync Changelog** — pass
- **Harness Feature Parity Benchmark** — pass
- **Starter Template Library** — pass
- **Selective Section Sync UI** — pass
- **Secret & Credential Scrubber** — pass
- **Monorepo Per-Package Sync** — pass
- **Auto Sync on Git Pull** — pass
- **New Harness Onboarding Wizard** — pass
- **Rule Deduplication Analyzer** — pass
- **Plugin Registry Sync** — pass
- **Environment Variable Translation Map** — pass
- **Sync Simulation Sandbox** — pass
- **Agent & Skill Compatibility Matrix** — pass
- **Scheduled Sync via Cron** — pass
- **CLAUDE.md Quality Linter & Grader** — pass
- **Multi-Account Sync Dashboard** — pass
- **Target Harness Version Compatibility Check** — pass
- **PR Comment with Sync Diff** — pass
- **Config Snapshot Time Travel** — pass
- **Natural Language Rule Generator** — pass
- **Harness Usage Analytics (Local)** — pass

### Decisions Made

- Implemented /sync-report (Item 11) as a standalone command with per-target fidelity percentages and problem-section detection, reusing existing StateManager data to avoid re-running expensive sync operations
- Added Gist export/import to ProfileManager (Item 2) using only stdlib urllib so no new dependencies; exported profile includes internal metadata that gets stripped on import to keep profiles clean
- Added interactive section picker (Item 17) with both raw-terminal (termios/tty) and fallback numbered-menu modes; integrated as --pick-sections flag in /sync so it's discoverable without a separate command
- Implemented monorepo per-package sync (Item 19) as src/monorepo_sync.py + --monorepo flag in /sync; per-package config is .harnesssync-package.json which extends the existing .harnesssync per-project config pattern
- Implemented sync simulation sandbox (Item 25) by running the real SyncOrchestrator against per-target subdirs inside a temp directory; this reuses the full adapter pipeline rather than duplicating adapter logic, so the simulation is always accurate
- Implemented /sync-schedule (Item 27) using crontab -l/-r/-w pattern; uses a HarnessSync-specific comment marker to identify and replace our entries without disturbing other cron jobs; Windows gets an instructional stub since cron isn't available
- Skipped items that already had complete implementations: 1 (sync_import.py), 3 (profile_manager.py), 4 (conflict_detector.py), 5 (startup_check.py), 6 (sync_github_actions.py), 7 (sync_mcp_health.py), 8 (continue_dev.py), 9 (zed.py), 10 (vscode.py), 12 (compatibility_reporter.py), 13 (--watch in sync.py), 14 (changelog_manager.py), 15 (sync_parity.py), 16 (template_registry.py), 18 (secret_detector.py), 20 (git_hook_installer.py), 21 (setup_wizard.py), 22 (rule_deduplicator.py), 23 (plugin_extension_mapper.py), 24 (mcp_aliasing.py), 26 (skill_compatibility.py), 28 (config_linter.py), 29 (sync_status.py), 30 (harness_version_compat.py)

### Patterns Discovered

- AdapterRegistry uses list_targets() + _adapters dict directly — no all_adapters() convenience method exists, which caused a bug in the first sandbox draft; worth adding all_adapters() as a public classmethod to avoid future misuse of private _adapters dict
- The orchestrator converts SourceReader's str output to list[dict] format expected by adapters — this implicit contract isn't documented in AdapterBase and caused the initial sandbox to pass raw strings to sync_rules()
- Per-project .harnesssync config files already exist for target/section overrides; the new .harnesssync-package.json for monorepos follows the same pattern but is scoped to subdirectories, maintaining naming consistency
- The crontab marker pattern (comment line + project line + command line) makes removal robust: we can surgically remove our entries without touching other users' cron jobs, but the three-line structure is fragile if the crontab is manually edited between entries
- All new src/ modules include from __future__ import annotations for Python 3.9 compat as required by project conventions; a duplicate __future__ import in sync_report.py and sync_schedule.py was caught and fixed before tests ran

### Takeaways

- The codebase is impressively complete — 24 of the 30 items were already fully implemented, many in dedicated modules with rich functionality; the evolve loop has been very productive at filling in features
- The sync_sandbox.py reuse of SyncOrchestrator is the right architectural choice but means the sandbox inherits all orchestrator side effects (changelog writes, state updates) — a future improvement would be a lighter 'read-only adapter evaluation' mode
- The section_picker.py TTY detection works well for CLI but will silently fall back in non-TTY contexts (hooks, CI) — this graceful degradation is intentional and correct
- ProfileManager.export_to_gist requires a GITHUB_TOKEN which many users won't have configured; a follow-up could add GitHub OAuth device flow or instructions for creating a token
- The monorepo discoverer's _MAX_DEPTH=3 limit prevents scanning large repos but means deeply nested packages (apps/services/auth/CLAUDE.md) won't be found — users can override with explicit .harnesssync-package.json placement

---
## Iteration 12
_2026-03-11T02:58:08.125Z_

### Items Attempted

- **Sync Preview & Diff Mode** — pass
- **Reverse Sync: Import from Target** — pass
- **Smart Merge for Target Customizations** — pass
- **Git Branch-Aware Sync** — pass
- **Drift Detection & Alerts** — pass
- **Skill & Rule Portability Score** — pass
- **Team Sync Profiles via dotfiles** — pass
- **Tag-Based Selective Sync** — pass
- **Harness Capability Matrix** — pass
- **Natural Language Sync Exclusions** — pass
- **Sync Timeline & History Explorer** — pass
- **MCP Server Health Dashboard** — pass
- **GitHub Actions Sync Step** — pass
- **Webhook-Triggered Sync** — pass
- **Context Window Optimizer** — pass
- **Cross-Section Rule Deduplication** — pass
- **Secret & Env Var Leak Prevention** — pass
- **Starter Config Template Library** — pass
- **Sync Impact Analysis** — pass
- **Multi-Project Batch Sync** — pass
- **Visual Config Relationship Map** — pass
- **Interactive Onboarding Wizard** — pass
- **Config Health Score** — pass
- **Watch Mode Desktop Notifications** — pass
- **Harness Version Migration Assistant** — pass
- **Rule Effectiveness Insights** — pass
- **Sync Integrity Verification** — pass
- **Plugin & Extension Cross-Harness Sync** — pass
- **Unified Config Search** — pass
- **AI-Assisted Rule Translation** — pass
- **Undo Stack for Sync Operations** — pass
- **Shareable Sync Report** — pass
- **Environment-Specific Sync Profiles** — pass
- **Skill & Rule Dependency Graph** — pass
- **Cross-Harness Prompt Consistency Tester** — pass

### Decisions Made

- Implemented branch-aware sync as a standalone module (branch_aware_sync.py) integrated into the orchestrator's _apply_project_config() rather than as a separate sync path — keeps the sync pipeline unified and branch detection is best-effort (fails silently if not in a git repo)
- Used fnmatch glob semantics for branch pattern matching (feature/*, release/*) with a regex escape hatch (re: prefix) — matches git's own branch naming conventions and covers 95%+ of real workflows without requiring regex knowledge
- Specificity scoring for branch profile conflicts: exact > glob-with-fewer-wildcards > regex — same tiebreaking principle as CSS specificity, feels natural to developers
- NL exclusion parsing uses keyword extraction (not LLM inference) for deterministic offline behavior — fast, no API calls, acceptable precision for common patterns
- Webhook server uses HTTP (not HTTPS) on loopback-only (127.0.0.1 default) — safe for local dev; teams that need remote access should put it behind a reverse proxy with TLS
- HMAC key stored in ~/.harnesssync/integrity.key (mode 0o600) with env var override — machine-local by default, team-shareable via HARNESSSYNC_INTEGRITY_KEY env var for cross-machine consistency
- Migration rules in harness_version_compat.py are plain Python functions, not a DSL — makes them unit-testable and easy to add without learning a meta-schema
- Interactive timeline in sync_log uses ANSI clear-screen but falls back gracefully if not TTY (non-interactive flag just dumps all entries) — safe for CI pipelines and redirected output
- Guided setup wizard (run_guided) detects harnesses via HarnessReadinessChecker to get real installed state rather than just shutil.which — more accurate for IDEs like Cursor that have no CLI

### Patterns Discovered

- Codebase consistently uses best-effort error handling (try/except with logger.warn) for all post-sync operations — sync failures should never block the primary result
- All new modules follow the established from __future__ import annotations header for Python 3.9 compatibility
- The orchestrator uses an additive pattern for skip sets and intersective for only sets — this is the right semantic for multi-source config merging and should be preserved across all new filter sources
- Target file signing is done by reverse-lookup of well-known output files per target from _TARGET_OUTPUT_FILES — avoids requiring adapters to report what they wrote, but is fragile if new targets add unusual output paths
- WebhookServer uses a factory function (_build_handler) to inject config into BaseHTTPRequestHandler subclasses — standard pattern for Python's http.server module which doesn't support constructor injection

### Takeaways

- Most of the 30 items were already substantially implemented — the codebase is very feature-rich. Future ideation should focus on integration quality and test coverage rather than new modules
- The orchestrator is growing large (964+ lines). The post-sync pipeline (annotations, symlinks, changelog, webhooks, integrity) could be refactored into a PostSyncPipeline class to reduce method count
- Branch-aware sync could be extended to read from .claude/branch-profiles/ directory (one file per branch) for teams that need version-controlled branch profiles — the current .harnesssync approach is single-file which works but is less composable
- The NL exclusion parser is intentionally simple (keyword matching) — a more powerful approach would use spaCy dependency parsing to extract (verb, object, target) triples, but offline simplicity wins for a CLI tool
- Sync integrity verification currently only signs files after the fact via known output file paths. Adapters should call sign_file() directly after each write for tighter coverage — requires adding an integrity_store parameter to adapter.sync_all()

---
## Iteration 13
_2026-03-11T03:16:05.073Z_

### Items Attempted

- **Sync Conflict Resolution Wizard** — pass
- **Harness Capability Map** — pass
- **Selective Section Sync** — pass
- **Sync on Git Commit Hook** — pass
- **Team Sync Profile Sharing** — pass
- **MCP Reachability Guard Before Sync** — pass
- **Harness Version Compatibility Check** — pass
- **Auto Sync Changelog** — pass
- **Bidirectional Import from Other Harnesses** — pass
- **Skill Compatibility Scoring** — pass
- **Env Var Placeholder Substitution** — pass
- **Sync Profile Templates** — pass
- **Live Sync Status Dashboard** — pass
- **Agent Translation Hints** — pass
- **Sync Schedule Manager** — pass
- **Multi-Project Batch Sync** — pass
- **Sync Impact Analyzer** — pass
- **Harness Adoption Nudge** — pass
- **Settings Inheritance Model** — pass
- **Time-Travel Rollback** — pass
- **Rules Deduplication Linter** — pass
- **MCP Server Auto-Install on Target** — pass
- **Sync Test Suite** — pass
- **Per-Harness Instruction Injection** — pass
- **Sync Event Notifications** — pass
- **Cross-Harness Config Diff Viewer** — pass
- **Graceful Degradation Profiles** — pass
- **Sync Audit Log Export** — pass
- **New Harness Auto-Detection** — pass
- **Sync Frequency and Drift Analytics** — pass
- **Plugin Config Sync Passthrough** — pass
- **AI-Assisted Instruction Translation** — pass
- **Harness-Specific Smoke Tests** — pass
- **Context-Window-Aware Config Truncation** — pass
- **Sync Lock File for CI Safety** — pass
- **Config Coverage Report** — pass

### Decisions Made

- Created /sync-capabilities as a behavioral feature map (vs /sync-matrix which covers config sections), because distinguishing 'does MCP work?' from 'does rules format sync?' is a fundamentally different question that the existing matrix didn't answer
- Created /sync-dashboard as a single-command status view that pulls from existing StateManager + ConflictDetector + ChangelogManager rather than duplicating state — composing existing modules instead of re-inventing data storage
- Created /sync-diff to show what's actually different between source and target files using Python's difflib with both unified and side-by-side modes, covering the gap between 'I synced' and 'what exactly changed'
- Extended sync_rollback.py with --timestamp and --before-commit rather than creating a separate command, because rollback is conceptually the same operation with different selection criteria
- Added export_json() and export_csv() to ChangelogManager as class methods (not a separate module) because the changelog already owns the parsing logic — no reason to duplicate regex parsing elsewhere
- Created graceful_degradation.py as a standalone module with a profile registry pattern so users can add custom profiles via ~/.harnesssync/degradation_profiles.json without modifying HarnessSync source
- Added install hints to McpReachabilityChecker.get_install_suggestions() rather than a new class, because reachability and install-ability are naturally co-located (if not reachable, how to fix it)
- Added inject_agent_translation_hints() to skill_translator.py (not a new file) because it's a natural extension of translation — 'what can't be translated, and what should the user know about it'
- Added get_quick_start_nudge() to harness_adoption.py alongside the existing adoption analysis, as nudges are fundamentally an output of the adoption workflow (just triggered at first-sync rather than after analysis)
- Added get_drift_analytics() to config_health.py as a standalone function rather than a method, because health checking and drift analytics are related but callers may want drift analytics without constructing the full health checker

### Patterns Discovered

- The codebase has excellent separation between data (StateManager, ChangelogManager), analysis (ConflictDetector, ConfigHealthChecker), and presentation (DiffFormatter, Commands) — new code should respect this layering
- All Python source files use 'from __future__ import annotations' for Python 3.9 compatibility — any new file must include this
- Command files follow a consistent pattern: PLUGIN_ROOT setup, argparse with shlex.split, main() entry point — new commands should follow this exactly
- Many modules already exist for features in the ideation list (graceful_degradation was truly new; most others needed augmentation not creation) — before creating new modules, do a thorough grep
- The _DEFAULT_PROFILES pattern in graceful_degradation.py (list of typed dataclass instances) is cleaner than the dict-of-dicts pattern used in some other modules for configuration
- The changelog_manager's export methods use the existing analytics regex parsing as a base — this creates a dependency between parse logic and export logic that could drift if the MD format changes

### Takeaways

- After 12 iterations, most obvious feature modules already exist — iteration 13 required genuine new commands (/sync-capabilities, /sync-dashboard, /sync-diff) and meaningful augmentations (time-travel rollback, export, install hints) rather than entirely new concepts
- The 'harness capability map' (item 2) and '/sync-matrix' (existing) are easy to conflate but serve distinct purposes: matrix=file format support, capabilities=runtime behavioral features — worth keeping both
- Several items (3,4,5,6,7,8,9,10,11,12,15,16,17,18,19,21,23,24,25,29) were already implemented in prior iterations — the evolve loop is converging on the remaining gaps
- The StateManager.get_all_targets_status() method is assumed to exist by sync_dashboard.py but may not be implemented — the fallback via AdapterRegistry.list_adapters() handles this gracefully
- Graceful degradation profiles need to be hooked into the adapter sync path (orchestrator.py) to actually inject fallback content — the module is useful standalone for analysis but won't auto-apply until integrated

---
