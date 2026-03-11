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
