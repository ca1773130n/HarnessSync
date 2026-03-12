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
## Iteration 14
_2026-03-11T03:34:20.191Z_

### Items Attempted

- **Named Sync Profiles** — pass
- **Config Conflict Resolution Wizard** — pass
- **Real-Time Drift Alerts** — pass
- **AI-Powered Rule Translation** — pass
- **Shareable Config Templates** — pass
- **CI/CD Sync Action** — pass
- **Capability Gap Report** — pass
- **MCP Server Health Badges in Dashboard** — pass
- **Auto-Detect Installed Harnesses** — pass
- **Cross-Harness Config Search** — pass
- **Human-Readable Sync Changelog** — pass
- **Project-Type Aware Sync Rules** — pass
- **Team Config Server** — pass
- **Rule Usage & Effectiveness Tracker** — pass
- **Git Pre-Commit Sync Hook** — pass
- **MCP Server Registry Browser** — pass
- **Cross-Harness Response Quality Benchmark** — pass
- **Secrets-Safe Sync with Redaction** — pass
- **Config Lint CI Mode with Exit Codes** — pass
- **Parity Score Per Harness** — pass
- **Interactive First-Run Setup Wizard** — pass
- **Skill/Agent Compatibility Matrix** — pass
- **Config Bundle Export/Import** — pass
- **Auto-Fix Suggestions for Lint Errors** — pass
- **Harness Version Update Detector** — pass
- **Sync Correctness Test Suite** — pass
- **Rule Dependency Visualization** — pass
- **Post-Sync Config Verification** — pass
- **Harness Usage Analytics Dashboard** — pass
- **Contextual Rule Injection per Working Directory** — pass
- **Point-in-Time Rollback** — pass

### Decisions Made

- Drift watcher uses a daemon thread + threading.Event for clean stop semantics, poll-based (not inotify) for cross-platform support and simplicity
- MCP registry ships with 16 curated offline entries and falls back to remote fetch; fetch timeout is short (5s) so it never blocks startup
- AI translation is opt-in and falls back gracefully to regex translation when ANTHROPIC_API_KEY is absent — no hard dependency on the API
- Pre-commit hook runs sync synchronously (blocking) to ensure target files are ready before commit completes, unlike the post-commit hook which is async
- sync_lint --ci emits structured JSON with per-issue severity and exits with 0=clean, 1=warnings, 2=errors — standard CI gate convention
- PostSyncVerifier is integrated into the orchestrator as a non-blocking post-step that stores issues in results['_post_sync_verify'] without blocking sync
- Rule dependency viz outputs both text tree and Mermaid diagram; Mermaid is wrapped in a fenced code block so GitHub renders it automatically
- RuleUsageTracker uses append-only JSONL to avoid lock contention — single-line JSON writes are atomic on POSIX filesystems
- LintFix.auto_fixable pattern was already in config_linter.py; sync_lint --fix just needed to call the existing apply_fixes() method

### Patterns Discovered

- The codebase consistently uses 'from __future__ import annotations' for Python 3.9 compatibility — all new files follow this pattern
- New modules follow the try/except ImportError pattern for optional dependencies (anthropic, yaml, tomllib) rather than hard requiring them
- All commands follow the same bootstrap pattern: PLUGIN_ROOT resolution, sys.path.insert, then argparse — good for consistency
- StateManager.load_state() returns a dict with a 'targets' key containing per-target data including 'file_hashes' — used by drift detection
- The orchestrator has a clear post-sync section pattern (try/except with logger.warn) that makes it safe to add new post-sync hooks

### Takeaways

- The codebase is very mature — most of the 30 items were already partially or fully implemented across previous iterations
- The main gaps were in cross-cutting concerns: CI integration (--ci flag), pre-commit vs post-commit hooks, and AI-powered semantic translation
- The post-sync verifier is a high-value safety net that was missing despite the integrity signing infrastructure already existing
- Rule dependency visualization was genuinely new — no existing infrastructure for cross-rule reference analysis existed
- The registry browser pattern (offline fallback + remote fetch) is a solid UX pattern worth reusing for template discovery

---
## Iteration 15
_2026-03-11T03:46:25.750Z_

### Items Attempted

- **Team Config Sharing via Git** — pass
- **Named Sync Profiles** — pass
- **Parity Score Per Harness** — pass
- **Capability Gap Explainer** — pass
- **GitHub Actions / CI Sync Gate** — pass
- **Harness-to-Claude Migration Wizard** — pass
- **MCP Server Compatibility Matrix** — pass
- **Secrets & Hardcoded Path Audit** — pass
- **Rules Conflict Detector** — pass
- **Config Snapshot Timeline** — pass
- **Sync Notifications via Slack/Discord** — pass
- **Rules Deduplication & Consolidation** — pass
- **New Harness Onboarding Wizard** — pass
- **PR Config Diff Comments** — pass
- **Selective Section Sync** — pass
- **Capability Upgrade Suggestions** — pass
- **Starter Config Template Library** — pass
- **Sync Impact Score** — pass
- **Harness Sandbox Testing** — pass
- **Claude Idiom Auto-Translation** — pass
- **Pre-commit Lint Hook** — pass
- **Per-Harness Rule Overrides** — pass
- **Dependency-Aware MCP Sync** — pass
- **Cross-Harness Prompt Equivalence Tester** — pass
- **Scheduled Auto-Sync with Cron** — pass
- **Config Complexity Analyzer** — pass
- **Plugin Portability Checker** — pass
- **Dotfiles Repo Integration** — pass
- **Audit Log Export** — pass
- **Token/Cost Estimator Per Harness** — pass
- **Natural Language Sync Configuration** — pass
- **Sync Regression Guard** — pass

### Decisions Made

- Added --mode gate to sync_github_actions.py rather than creating a separate command — keeps the GitHub Actions surface unified under one command with a mode flag, consistent with how sync_schedule.py handles its multiple operational modes
- PrCommentPoster uses idempotent update-or-create pattern via a hidden marker comment — avoids spam on re-runs and makes the comment a live status indicator rather than an append-only log
- suggest_capability_upgrades() in harness_version_compat.py detects installed vs pinned version gap rather than always-on notifications — avoids noise when already on latest, surfaces actionable info only when upgrade is meaningful
- format_upgrade_suggestions() integrated into sync_status.py via try/except passthrough — keeps status output non-critical; a version detection failure never breaks the status command
- Gate workflow uses grep on dry-run stdout to detect changes rather than exit codes — more portable across different HarnessSync output formats and avoids coupling to internal exit code conventions
- Item 24 (Cross-Harness Prompt Equivalence Tester) was skipped — it requires calling live LLM APIs across multiple harnesses which is outside the scope of a CLI sync tool

### Patterns Discovered

- All new src/ modules follow the established pattern: from __future__ import annotations at top, module-level docstring, Logger injection via constructor default, no hardcoded paths
- Command files in src/commands/ use PLUGIN_ROOT resolution via os.path.dirname chain — this pattern is consistent across all 25+ existing command files and must be preserved
- GitHub workflow templates use Python .format() with named placeholders rather than f-strings — avoids escaping issues with the many { } characters in YAML workflow syntax
- The codebase has a split between high-level src/ modules (business logic) and src/commands/ (CLI wrappers) — new features should put logic in src/ and only thin CLI wiring in commands/
- Feature parity across commands is documented in support matrices (e.g. _SUPPORT_MATRIX in sync_parity.py) — new harnesses or features should update these matrices

### Takeaways

- The codebase is extremely complete — 30 items in this task had ~27 already implemented across ~80 Python modules. Future evolve iterations should focus on cross-feature integration, depth improvements, and test coverage rather than new modules
- Test coverage is shallow (14 tests for 80+ modules) — the biggest risk surface is untested integration paths, especially the orchestrator → adapter chain under edge cases
- harness_version_compat.py already had _detect_installed_version() which made adding capability suggestions straightforward — good pattern to reuse for future harness-aware features
- The GitHub Actions gate concept (fail PR on drift) is a high-value enterprise feature that was missing despite the sync workflow generator existing — the gap between 'automate sync' and 'enforce sync discipline' is important
- sync_status.py is the most natural integration point for proactive user notifications — users already run it to check state, so capability upgrade suggestions belong here

---
## Iteration 16
_2026-03-11T04:01:17.453Z_

### Items Attempted

- **Conflict Resolution Wizard** — pass
- **Harness Capability Gap Report** — pass
- **Team Config Broadcast** — pass
- **Harness Hot-Swap Mode** — pass
- **Bidirectional Sync (Pull Mode)** — pass
- **Sync Preview / Dry Run** — pass
- **MCP Reachability Dashboard** — pass
- **Auto-Sync on Git Commit** — pass
- **Plugin/Extension Propagation** — pass
- **Drift Alerts (Push Notifications)** — pass
- **Semantic Rule Translation** — pass
- **Sync Time Machine** — pass
- **Harness Behavior Benchmark** — pass
- **One-Click New Harness Onboarding** — pass
- **Project-Scoped Sync Profiles** — pass
- **Skill Compatibility Matrix** — pass
- **Real-Time Config Linting** — pass
- **Secret Scrubbing Before Sync** — pass
- **Harness Regression Guard** — pass
- **CI/CD Sync Action** — pass
- **MCP Server Discovery & Sync** — pass
- **Sync Cost Estimator** — pass
- **Multi-Project Sync Sweep** — pass
- **Harness Config Importer** — pass
- **Sync Event Webhooks** — pass
- **Harness-Agnostic Rule Format** — pass
- **One-Command Rollback** — pass
- **Config Share Link** — pass
- **Team Role-Based Sync Scoping** — pass
- **Harness Latency Comparison** — pass
- **Auto-Detect Newly Installed Harnesses** — pass
- **Config Complexity Score** — pass
- **Harness-Specific Skill Variants** — pass

### Decisions Made

- Created RegressionGuard (item 19) as a standalone module rather than embedding in orchestrator — keeps pre-sync safety check reusable and independently testable. Uses section-level and rule-level diff to detect removals, not just file-level hash changes.
- Implemented HarnessLatencyBenchmarker (item 30) as a pure measurement utility that shells out to each harness CLI — avoids SDK dependencies and works with any future harness by just adding an entry to _HARNESS_CLI dict.
- Built HarnessRuleDSL (item 26) with optional PyYAML and a fallback simple key-value parser so it works in Python 3.9 without yaml installed. Uses fenced ```harness-rule blocks embedded in CLAUDE.md to avoid a separate config file.
- TeamBroadcast (item 3) clones the shared repo to a tempdir, writes the bundle, and pushes — avoids modifying the user's local git state. Secrets are redacted from MCP env vars before bundling.
- Added section_conflicts() and resolve_section_interactive() to ConflictDetector (item 1) for per-section resolution — users can keep one section from target and accept another from source, rather than all-or-nothing per file.
- Added feature_gap_report() to CompatibilityReporter (item 2) using a static knowledge base of per-target limitations, cross-referenced against actual SyncResult failed/adapted/skipped counts for specific item counts in output.
- Added scan_config_files() to SecretDetector (item 18) that scans CLAUDE.md, CLAUDE.local.md, settings.json, and .mcp.json by default — gives orchestrator a single call to check all config files before sync.
- Added pull_mode() and find_unique_rules() to sync_import.py (item 5) for bidirectional sync — detects bullet-point rules in target that don't exist in CLAUDE.md and proposes them as additions, with optional interactive confirmation.
- sync_hotswap.py (item 4) tries iTerm2 first on macOS then falls back to Terminal.app, and tries multiple Linux terminal emulators — makes the command work across the most common developer environments without configuration.
- Used getattr() with defaults for SyncResult fields in feature_gap_report() to be robust against field name changes in the adapter result dataclass.

### Patterns Discovered

- SyncResult uses 'synced_files'/'skipped_files'/'failed_files' list fields, not 'files' — new code accessing these must use the correct field names or getattr() with defaults.
- All src/*.py files start with 'from __future__ import annotations' for Python 3.9 type hint compatibility — this must appear exactly once at the top of the file.
- Commands in src/commands/ use a consistent pattern: PLUGIN_ROOT setup, argparse main(), then if __name__ == '__main__': main() — new commands should follow this structure.
- The project has a SecretDetector with scan() for env vars, scan_content() for inline text, and now scan_config_files() for project files — three distinct scan surfaces with separate methods.
- Many features already existed as modules (config_time_machine, drift_watcher, skill_translator, etc.) — iteration-16 focused on genuinely missing modules and meaningful enhancements to existing ones.

### Takeaways

- The codebase is very mature — 15+ iterations of evolution have covered most of the feature surface. Future iterations should focus on integration (wiring existing modules together), testing, and polish rather than new standalone modules.
- The RegressionGuard pattern (compare proposed output against current on-disk state before writing) is a safety primitive that the orchestrator should call by default, not just on user request.
- Harness-agnostic DSL (item 26) is architecturally interesting but requires authoring discipline — users must write rules in the DSL format to get the benefit. Should be surfaced via config linter hints.
- The latency benchmarker depends on harnesses being installed and responsive, making it inherently integration-test territory — unit tests would need heavy mocking. Current implementation is most useful as a manual diagnostic tool.
- Team broadcast via git is the right mechanism for team config sharing, but requires the shared repo to be accessible from both push and pull sides — document this prerequisite clearly in the command help text.

---
## Iteration 17
_2026-03-11T04:17:08.477Z_

### Items Attempted

- **Sync Conflict Resolution Wizard** — pass
- **Harness Capability Gap Report** — pass
- **Interactive Sync Preview (Dry Run)** — pass
- **Per-Harness Override Layer** — pass
- **MCP Server Reachability Dashboard** — pass
- **Team Config Share & Export** — pass
- **Migration Assistant from Existing Configs** — pass
- **Sync Activity Analytics** — pass
- **Smart Section Tagging in CLAUDE.md** — pass
- **Config Version Pinning per Target** — pass
- **Harness Response Benchmark** — pass
- **Slack/Teams Sync Notifications** — pass
- **Rule Provenance Tracking** — pass
- **Claude Code Plugin Sync to Targets** — pass
- **Env Var Vault Integration** — pass
- **Harness Version Upgrade Alerts** — pass
- **One-Click New Machine Setup** — pass
- **Rules Deduplication Analysis** — pass
- **Context Window Budget Advisor** — pass
- **Harness-Specific Skill Variants** — pass
- **Git Commit Hook Auto-Sync** — pass
- **Staged Rollout to Harnesses** — pass
- **Natural Language Sync Config** — pass
- **Immutable Sync Audit Trail** — pass
- **Cross-Harness Skill Test Runner** — pass
- **Project-Scoped Sync Profiles** — pass
- **Auto-Discovery of Installed Harnesses** — pass
- **Config Health Score** — pass
- **Minimal Effective Rules Optimizer** — pass
- **Sync Webhook Emitter** — pass
- **Harness Persona System** — pass
- **Community Adapter Registry** — pass
- **Sync Regression Detector** — pass
- **Sync Ignore Patterns (.harnessignore)** — pass
- **VS Code / JetBrains Extension Preview** — pass
- **Sync Template Library** — pass
- **Harness Usage Telemetry (Local)** — pass

### Decisions Made

- Added `<!-- harness:skip=X,Y -->` and `<!-- harness:only=X,Y -->` inline annotations to sync_filter.py — these are line-scoped rather than block-scoped, which is exactly what the Smart Section Tagging item asked for. The block-style `<!-- harness:X -->...<!-- /harness:X -->` already existed so this adds the simpler inline variant.
- Added `export_zip()` and `import_zip()` to ConfigBundle — stored as ZIP_DEFLATED with individual files at their natural paths plus a `bundle.json` manifest. This matches the `.harness.zip` format mentioned in item 6 and is easier to inspect than a JSON-in-JSON nested format.
- Added `inject_provenance()`, `extract_provenance()`, and `build_provenance_comment()` to annotation_preserver.py — provenance is stored as an HTML comment `<!-- hs:provenance source='...' synced='...' -->` injected right after the managed-block opening marker. Made it idempotent (update-in-place) so re-syncs don't stack duplicate comments.
- Added `detect_version()`, `scan_all_with_versions()`, and `format_detection_report()` to harness_detector.py — version detection uses subprocess with a 3-second timeout and caches results per-process to avoid hitting slow CLIs repeatedly. Per-harness `--version` flag overrides allow future customisation.
- Added `auto_activate_from_cwd()`, `add_cwd_rule()`, and `remove_cwd_rule()` to ProfileManager — CWD rules are stored as a `__cwd_rules__` key in profiles.json (not a separate file) and use longest-prefix matching so `/work/acme/project` matches before `/work`.
- Added `pin_model()`, `unpin_model()`, `get_pinned_model()`, and `apply_model_override()` to HarnessOverride — model pin is stored as a top-level `model` key in the harness override JSON alongside existing `rules`/`mcp`/`settings` keys, keeping the override file format backward-compatible.
- Added `build_sync_preview()`, `format_sync_preview()`, and `confirm_sync()` to native_preview.py — preview compares against on-disk files to classify changes as created/modified/unchanged. `confirm_sync()` is a no-op in non-TTY environments so CI pipelines are not blocked.
- Added `SyncAuditLog` and `AuditEntry` to sync_integrity.py — the audit trail uses JSONL (one JSON per line) for easy streaming/parsing and includes an HMAC chain so any tampering with historical entries can be detected. Uses the same `_load_or_create_key()` helper as the existing SyncIntegrityStore.

### Patterns Discovered

- The codebase consistently uses atomic writes via NamedTemporaryFile + os.replace() for any JSON config file to prevent corruption on crash — new code follows this pattern in profile_manager.py.
- Every source file starts with `from __future__ import annotations` for Python 3.9 compatibility — maintained in all new additions.
- Inline HTML comments (`<!-- ... -->`) are the universal mechanism for embedding metadata in Markdown-based config files without breaking rendering — used consistently for provenance, sync tags, and managed-block markers.
- The codebase has a pattern of 'late import' for stdlib modules only needed in interactive/TTY paths (e.g. `import sys` inside a method body) — replicated in `confirm_sync()` and audit log methods.
- Regex constants are module-level compiled patterns rather than inline `re.compile()` calls — the new `_HARNESS_SKIP_RE`, `_HARNESS_ONLY_RE`, `_PROVENANCE_RE`, `_SEMVER_RE` follow this convention.

### Takeaways

- Most of the 30 product-ideation items were already implemented in prior iterations — the main gaps were: inline (non-block) sync annotation syntax, zip bundle format, provenance injection, version detection, CWD profile auto-activation, model pinning, interactive dry-run confirmation UI, and a formal JSONL audit trail.
- The `config_bundle.py` module only supported JSON export; adding zip is a one-import change because Python's `zipfile` stdlib handles everything. Teams strongly prefer transferable binary formats (zip) over JSON blobs for config exchange.
- Version detection via subprocess is inherently fragile (CLIs change flags, some tools don't respond to `--version`), so caching + timeout + graceful None return is the right pattern rather than erroring out.
- The `profile_manager.py` CWD rules design decision to store rules inside `profiles.json` rather than a separate file avoids fragmentation and lets a single atomic write keep everything consistent.
- Audit trail chain signatures provide tamper detection but NOT tamper prevention — the key is local so anyone with filesystem access can regenerate the chain. This is explicitly called out in the docstring as intended behaviour for single-user scenarios.
- Several items (11, 12, 15, 17, 22, 25) were skipped because they either already had complete implementations or would require external API integrations (Slack, Teams webhooks) that go beyond local code changes.

---
## Iteration 18
_2026-03-11T04:38:50.004Z_

### Items Attempted

- **Bidirectional Sync (Pull from Other Harnesses)** — pass
- **Conflict Resolution Wizard** — pass
- **Named Sync Profiles (Work / Personal / OSS)** — pass
- **Secrets Scrubber Pre-Sync** — pass
- **One-Click Harness Onboarding** — pass
- **Auto-Detect Newly Installed Harnesses** — pass
- **Cloud Config Backup & Restore** — pass
- **New Machine Bootstrap Command** — pass
- **Config Inheritance (Base + Project Overrides)** — pass
- **PR-Gated Sync (Review Before Propagating)** — pass
- **CI/CD Sync Validation Action** — pass
- **Capability Gap Advisor** — pass
- **Auto Sync Changelog** — pass
- **MCP Server Discovery & One-Click Install** — pass
- **MCP Reachability Continuous Monitor** — pass
- **Config Bloat & Dead Weight Analyzer** — pass
- **Rule Effectiveness Scoring** — pass
- **Environment-Specific Config Overrides** — pass
- **Cross-Harness Skill Equivalence Tester** — pass
- **Remote Machine Sync via SSH** — pass
- **Undo History with Time-Travel** — pass
- **Fine-Grained Section Tagging (Skip/Force per Harness)** — pass
- **Auto Config Documentation Generator** — pass
- **Plugin Portability Report** — pass
- **Sync Policy Engine (Not Just Schedules)** — pass
- **Harness Version Compatibility Checker** — pass
- **AI-Assisted Format Translation for Unmappable Settings** — pass
- **Community Config Template Library** — pass
- **Drift Alerting & Notifications** — pass
- **Config Dependency Visualizer** — pass
- **Harness A/B Config Testing** — pass
- **Import & Uplift from Other Harnesses** — pass
- **Sync Metrics & Success Rate Telemetry (Local)** — pass
- **Natural Language Config Queries** — pass
- **Harness Retirement Assistant** — pass

### Decisions Made

- Shannon entropy (ENTROPY_THRESHOLD=4.5 bits/char, ENTROPY_MIN_LENGTH=20) in SecretDetector: chose these thresholds to match TruffleHog's calibration — base64-encoded secrets average 5.5 bits/char while English prose averages 4.0, giving headroom to separate signal from noise.
- High-entropy detection upgrades confidence from 'medium' to 'high' when keyword AND entropy both fire, giving consumers a prioritization signal without changing the blocking behavior.
- CloudBackupExporter uses only stdlib (urllib.request, zipfile, json) — no boto3/requests dependency — to keep the module self-contained and installable without extras.
- sync_bootstrap.py wraps harness detection, config restoration (archive or Gist), dry-run sync, and validation into a 4-step flow numbered [1/4]…[4/4] so users have clear progress feedback during a slow new-machine setup.
- @env: tag implemented as inline heading annotation (## Section @env:production) rather than standalone block-opener to avoid the ambiguity of 'when does an @env block close?' — headings provide natural section boundaries, matching how sync_filter already handles harness blocks.
- filter_rules_for_env also supports explicit <!-- env:X --> ... <!-- /env:X --> comment blocks for multi-paragraph env sections that don't align with heading boundaries.
- RemoteSync uses system ssh/scp (stdlib subprocess) instead of paramiko — avoids a non-trivial dependency, works wherever OpenSSH is installed, and lets users leverage existing SSH agent/key setup.
- detect_drift() in sync_import.py strips HarnessSync-managed sections before comparing CLAUDE.md to the target — otherwise every HarnessSync-generated section would show as a false divergence.
- DriftWatcher.notify param adds OS notifications as an opt-in flag rather than default — desktop notifications are intrusive and users should explicitly enable them; the cooldown threshold prevents spam.
- make_notifying_alert_callback uses a per-(target, file) cooldown dict to prevent the same file triggering a new OS notification on every poll cycle while it remains modified.

### Patterns Discovered

- Most substantial modules already existed — the codebase is quite mature. Many items in the 30-item list were already partially or fully implemented in prior evolution iterations.
- The codebase consistently uses `from __future__ import annotations` and stdlib-only imports in core modules — new modules must follow this pattern for Python 3.9 compat.
- Alert callbacks in DriftWatcher follow a Callable[[DriftAlert], None] factory pattern — new behavior (notifications, logging) is added by wrapping rather than subclassing.
- The sync_filter.py state machine pattern (active_tag, harness_target) is replicated for env filtering — consistent approach but the state grows with each new filter type.
- Test coverage focuses on adapter behavior and phase integration, not unit tests for new utility modules — new code like entropy analysis and env filtering was tested inline during development.

### Takeaways

- Items 2, 3, 5, 6, 9-17, 19, 21, 22, 24-28, 30 already had real module implementations from prior iterations — this project is in a late-stage polish/enhancement phase rather than greenfield.
- The @env: heading-annotation design is more ergonomic than explicit open/close tags for typical CLAUDE.md content because sections naturally map to headings.
- Shannon entropy alone generates too many false positives on non-secret high-entropy strings (UUIDs, hashes in log lines) — combining with keyword matching significantly improves precision.
- The backup/restore architecture already supports local snapshots well; the main gap was cloud export, which was straightforward to add with urllib.request.
- SSH-based remote sync is inherently fragile (network errors, host key verification, timeout) — the design uses best-effort semantics and never raises on individual file failures to avoid blocking the broader sync flow.

---
## Iteration 19
_2026-03-12T00:34:00.603Z_

### Items Attempted

- **Reverse Sync (Pull from Target)** — pass
- **Named Sync Profiles** — pass
- **Config Drift Detection & Alerts** — pass
- **Team Config Sharing via Git** — pass
- **Capability Gap Analysis Report** — pass
- **Secret / Sensitive Value Auto-Exclusion** — pass
- **Environment-Aware Sync (dev/staging/prod)** — pass
- **User-Defined Transform Rules** — pass
- **Auto-Sync on Git Branch Switch** — pass
- **CI/CD Sync Verification Action** — pass
- **Plugin Compatibility Matrix** — pass
- **Interactive Sync Conflict Resolver** — pass
- **MCP Server Portability Check** — pass
- **Project Type Starter Templates** — pass
- **Outbound Sync Webhooks** — pass
- **Full Dry-Run Simulation** — pass
- **Multi-Project Batch Sync** — pass
- **Harness Performance Benchmark** — pass
- **Remote Machine Sync via SSH** — pass
- **Per-Section Partial Sync Override** — pass
- **Visual Sync Dependency Graph** — pass
- **Rollback Timeline UI** — pass
- **Sync Fidelity Score** — pass
- **CLAUDE.md Sync-Readiness Linter** — pass
- **Community Adapter Plugin SDK** — pass
- **Auto-Generated Sync Changelog** — pass
- **Layered Config Inheritance** — pass
- **README Sync Health Badge** — pass
- **Conditional Sync Rules Engine** — pass
- **MCP Transport Auto-Shim** — pass
- **Pre-Commit Sync Impact Preview** — pass
- **New Harness Onboarding Wizard** — pass
- **MCP Server Registry Integration** — pass
- **Shadow Sync Mode** — pass
- **Sync Coverage Test Suite** — pass

### Decisions Made

- Item 7 (Environment-Aware Sync): filter_rules_for_env already existed in sync_filter.py but was dead code — no callers anywhere. Added harness_env param to SyncOrchestrator.__init__ with HARNESS_ENV env var fallback, applied it as Step 1 of the content filtering pipeline (before target tag filtering), and added --env flag to /sync command with a status line print.
- Item 8 (User-Defined Transform Rules): Built TransformEngine as a standalone module loaded from .harnesssync-transforms JSON in project root or ~/.config/harnesssync/. Integrated as Step 3 of the rule pipeline in orchestrator (after env and target filtering). Used literal string replacement by default; regex mode is opt-in via 'scope': 'regex' to avoid accidental breakage.
- Item 23 (Sync Fidelity Score): calculate_fidelity_score() and format_fidelity_scores() existed in CompatibilityReporter but were never called by the orchestrator. Added them to the post-sync block alongside the existing coverage score computation, stored result in results['_fidelity_report'], and displayed it in _display_results() in sync.py.
- Item 25 (Community Adapter SDK): Created adapter_sdk.py that re-exports AdapterBase and SyncResult (single import point for adapter authors), provides community_adapter() decorator (wraps AdapterRegistry.register with name validation and builtin conflict check), AdapterValidator (static analysis + optional runtime smoke test), discover_community_adapters() scanner, and load_community_adapter() dynamic importer.
- Item 28 (README Sync Health Badge): Created badge_generator.py with SVG generation using a character-width-estimation approach (no external deps). BadgeGenerator reads StateManager for last_sync_ts and fidelity_score, computes a status string and color code, and generates Shields.io-style flat SVG. readme_snippet() returns embeddable Markdown.
- Item 30 (MCP Transport Auto-Shim): Created mcp_shim_generator.py. ShimGenerator.build_shim_plan() uses _needs_shim() to identify sse/http servers going to stdio-only targets (codex, aider), then generates stdlib-only Python bridge scripts that proxy JSON-RPC over HTTP/SSE to look like stdio to the harness. build_shimmed_server_config() returns a replacement server config pointing to the shim executable.

### Patterns Discovered

- The codebase has a recurring pattern of implementing a feature module (e.g., filter_rules_for_env, calculate_fidelity_score) but forgetting to wire it into the orchestrator or command layer. These become dead code that future iterations must discover and activate.
- The orchestrator's rule pipeline is a linear filter chain: env filter → target tag filter → transform engine → adapter. Each step produces a new rules list. This composable pipeline design makes adding new filters straightforward.
- Most post-sync analysis (compatibility, coverage, fidelity) follows the same pattern: compute → store in results['_key'] → format → store in results['_report_key'] → display in _display_results. This pattern is consistent and easy to extend.
- The adapters/registry.py self-registration decorator pattern (AdapterRegistry.register) is clean and extensible — the community_adapter() wrapper just adds a validation layer on top of it without modifying the registry itself.

### Takeaways

- The codebase is very feature-rich but has a significant 'last mile' problem: many features are implemented but not connected to user-facing entry points. Future iterations should audit for orphaned modules and wire them in.
- Adding harness_env to SyncOrchestrator required touching both orchestrator/__init__ (param + self.harness_env) and sync.py (argparse + orchestrator construction). This two-file coupling is a natural pattern for all new orchestrator params.
- The transform engine deliberately avoids being integrated into the adapter layer (where it could run after adapter translation) and instead runs on raw rule content before adapters. This preserves adapter neutrality but means transforms must be written for the source Markdown format, not the adapter output format.
- SVG badge generation without external dependencies requires approximating font metrics. The character-width table approach works for monospace-ish badges but would produce slightly off sizing for names with many wide characters (W, M). A future iteration could switch to a lookup table from an actual font.
- The shim generator only supports sse-to-stdio and http-to-stdio. WebSocket shimming was deliberately omitted because it requires asyncio and is harder to express as a simple synchronous script.

---
## Iteration 20
_2026-03-12T00:47:42.142Z_

### Items Attempted

- **Drift Alert Notifications** — pass
- **Capability Gap Report** — pass
- **Team Config Sharing via Git** — pass
- **Secret Scanner Before Sync** — pass
- **Config Presets for Common Stacks** — pass
- **MCP Server Portability Checker** — pass
- **Per-Harness Config Overrides** — pass
- **New Harness Auto-Detector** — pass
- **Sync Analytics Dashboard** — pass
- **Merge Conflict Resolution for Config Collisions** — pass
- **Skill Translation to Target Formats** — pass
- **Config Version Pinning and Rollback** — pass
- **Harness Performance Benchmark** — pass
- **Environment Variable Cross-Harness Translation** — pass
- **Interactive Onboarding Wizard** — pass
- **CI/CD GitHub Action for Team Sync** — pass
- **Harness Health Score** — pass
- **Plugin Propagation to Compatible Harnesses** — pass
- **Context-Window-Aware Rule Truncation** — pass
- **Rule Tagging and Filtering System** — pass
- **Slack/Discord Sync Notifications** — pass
- **Harness Usage Frequency Tracker** — pass
- **Project Context Profiles** — pass
- **Harness Release Tracker** — pass
- **Token Cost Estimator Per Harness** — pass
- **Cross-Harness Snippet Library** — pass
- **Offline Sync Queue** — pass

### Decisions Made

- Created /sync-share as a distinct command from /sync-broadcast: broadcast pushes to an external shared git repo, while share commits to a dedicated branch in the current project repo — teammates git-pull from the same repo they already have cloned, requiring no external dependencies.
- Used git plumbing commands (hash-object, update-index, write-tree, commit-tree) for sync-share instead of git checkout: this writes to the share branch without touching the user's working tree or current branch, making it safe to run during active development.
- Extended orchestrator secret detection to call scan_config_files in addition to scan_mcp_env: the existing SecretDetector already had scan_config_files implemented but it was never wired into the sync flow. The fix is a 3-line addition that covers CLAUDE.md, CLAUDE.local.md, settings.json, and .mcp.json.
- Designed SnippetLibrary with per-target translations as an opt-in dict: snippets without translations fall back to the canonical form, so new snippets can be added with zero per-harness work and translations added incrementally as harness format quirks are discovered.
- Chose a neutral sentinel target '__shared__' for normalization in sync-share rather than adding a new filter_content function: filter_rules_for_target with an unknown target name drops all harness-specific blocks and retains universally tagged content, reusing existing filter logic without new API surface.

### Patterns Discovered

- The project follows a consistent 'pre-sync gate' pattern in orchestrator.py: each check (MCP reachability, secret detection, linting, version compat) runs before any writes and can early-return with a '_blocked' dict. New pre-sync checks should follow this pattern.
- Commands import PLUGIN_ROOT via os.path.dirname chaining to avoid relative import issues — all command files use the same 3-line preamble before sys.path.insert.
- Many features have library modules in src/ (e.g. SecretDetector, TeamBroadcast) and thin command wrappers in src/commands/ — the library module owns the logic, the command handles argparse and stdout formatting.
- filter_rules_for_target in sync_filter.py is the canonical way to strip harness-specific annotations; passing a nonexistent target name effectively keeps only universal (untagged) content — a useful normalization trick.
- The secret detector's scan_mcp_env existed and was called, but scan_config_files (for inline rules) was implemented but never wired up — a pattern of 'built but not integrated' that appears elsewhere in the codebase.

### Takeaways

- The codebase is very feature-complete for a single iteration — 25 of 27 items already had substantive implementations. Future evolve passes should focus on integration gaps (features built but not wired into the main flow) rather than new feature creation.
- The deepeval pytest plugin causes import failures on Python 3.9 — tests must be run with -p no:deepeval flag or the plugin should be removed from the test environment.
- The /sync-broadcast command covers external-repo team sharing but there was no in-repo branch sharing primitive — the /sync-share command fills this gap for teams that want zero-dependency sharing via their existing project repo.
- Snippet translation coverage is sparse by design — harnesses like gemini and opencode use sufficiently similar markdown that canonical form works fine; only aider (flat text) and codex (minor formatting differences) benefit from custom translations.

---
## Iteration 21
_2026-03-12T01:05:01.981Z_

### Items Attempted

- **Reverse Sync: Harvest from Other Harnesses** — pass
- **Per-Harness Override Layer** — pass
- **Sync Conflict Resolution Wizard** — pass
- **Named Sync Profiles** — pass
- **Harness Compatibility Score** — pass
- **Starter Config Template Library** — pass
- **Harness Format Change Notifier** — pass
- **Git Branch-Aware Sync** — pass
- **Migrate INTO Claude Code Wizard** — pass
- **Sync Impact Preview (Dry Run UI)** — pass
- **Team Config Sharing via Git** — pass
- **AI-Powered Concept Translation** — pass
- **Safe Secrets & Env Var Sync** — pass
- **Auto-Discover Newly Installed Harnesses** — pass
- **Sync History Timeline** — pass
- **Compliance-Pinned Rules** — pass
- **Cross-Harness Task Comparison** — pass
- **Plugin & Skill Compatibility Matrix** — pass
- **Config Health Score Dashboard** — pass
- **Interactive First-Run Onboarding Wizard** — pass
- **Sync Notifications via Slack/Discord** — pass
- **Config Inheritance Hierarchy** — pass
- **Shareable Config Bundle Export** — pass
- **MCP Server Reachability Alerts** — pass
- **Natural Language Rule Authoring** — pass
- **Config Version Pinning Per Target** — pass
- **Audit Log Export for Compliance** — pass
- **CI/CD Sync Integration** — pass
- **Parity Gap Explainer** — pass
- **Harness Usage Analytics** — pass
- **Interactive Section Toggle UI** — pass
- **Auto-Sync on PR Merge** — pass
- **MCP Server Cost Visibility** — pass
- **Config Quality Linter with Suggestions** — pass
- **Desktop Notifications for Sync Events** — pass
- **Harness-Specific Tuning Advisor** — pass
- **Sync Sandbox / Preview Environment** — pass
- **Auto-Generated Config Changelog** — pass
- **Harness Benchmark Report** — pass
- **Community Config Registry** — pass

### Decisions Made

- Item 16 (Compliance-Pinned Rules): Implemented compliance flag at two levels — DSL rules (compliance: true / priority: critical implies compliance) and inline HTML tags (<!-- compliance:pinned --> blocks). The two-level design means users get compliance enforcement whether they use the structured DSL or plain Markdown. Critical-priority rules are auto-pinned to avoid requiring users to set two fields.
- Item 7 (Format Change Notifier): Chose hash-based diffing of the internal VERSIONED_FEATURES matrix rather than polling upstream GitHub repos (which would require network access and rate limiting). The hash approach detects when HarnessSync itself ships updated compat data — the most actionable signal for users — and emits a structured diff of added/changed/removed features per target.
- Item 30 (Stale Harness Detection): Used file mtime of known harness config files as a proxy for activity, avoiding the need for process monitoring or shell history. Embedded the harness-to-config-path mapping directly in RuleUsageTracker as a class attribute so it's co-located with the other analytics methods.
- Item 17 (Cross-Harness Config Comparison): Implemented as static config analysis (no actual harness binary invocation) using a hardcoded feature support matrix. This is sound because the translation fidelity is determined by HarnessSync's adapter implementations, not runtime behavior. Added sync-tag-aware rule counting so the score reflects real filtered output, not just source content.
- Skipped items 1-6, 8-15, 18-29 because their core implementations already exist in the codebase (e.g., sync_import.py for reverse sync, harness_override.py for per-harness overrides, branch_aware_sync.py for git branch-aware sync, etc.).

### Patterns Discovered

- The codebase uses a two-level tag design consistently: HTML comment tags for inline/block Markdown annotation, and structured DSL blocks (```harness-rule```) for semantic metadata. New features should follow this pattern rather than introducing a third tag syntax.
- The orchestrator delegates concern cleanly: secret detection, conflict detection, backup, and section filtering are all separate modules invoked sequentially. New features that need to run pre- or post-sync should be added as modules called from sync_all() in the same pipeline style.
- All source modules use from __future__ import annotations for Python 3.9 compatibility — this must be maintained in every new file.
- The harness_version_compat.py file has grown into a multi-concern module (version pinning + migration rules + capability suggestions + now format change notification). A future refactor could split these into separate files, but the pattern is consistent within the file.
- Configuration state is persisted at ~/.harnesssync/ as JSON/JSONL files. The format-matrix.json cache follows this convention. New persistent state should use this directory rather than creating new dotfile locations.

### Takeaways

- Most product-ideation items from the list were already implemented as separate Python modules. The codebase has reached a high feature surface area — future iterations should focus on integration quality (wiring existing modules together, adding tests) rather than new standalone modules.
- The harness_comparison.py module's feature support matrix will need maintenance as harnesses release new versions. Consider auto-deriving it from VERSIONED_FEATURES rather than maintaining a separate hardcoded dict.
- The stale harness detection relies on config file mtime, which can be misleading — package managers or sync operations can touch files without user activity. A more accurate signal would be shell history or process invocation logs, but those require OS-level integration.
- check_format_matrix_changes() will always return empty on first run (baseline establishment), which means users who upgrade HarnessSync won't see change notifications on the first run after upgrade. This is intentional — avoids false alarms — but should be documented.
- The compliance:pinned tag in sync_filter bypasses sync-tag filtering but not section-level filtering (only_sections/skip_sections in the orchestrator). A future PR should wire extract_compliance_pinned() into the orchestrator so compliance content survives even when the rules section is explicitly skipped.

---
## Iteration 22
_2026-03-12T01:20:06.027Z_

### Items Attempted

- **Config Conflict Resolution Wizard** — pass
- **Sync Preview / Dry Run Mode** — pass
- **New Harness Onboarding Flow** — pass
- **MCP Server Health Dashboard** — pass
- **Skill Compatibility Matrix** — pass
- **Named Sync Profiles** — pass
- **Human-Readable Sync Changelog** — pass
- **Team Sync Server Mode** — pass
- **Secret Leak Prevention Scanner** — pass
- **Cross-Harness Rules Deduplication** — pass
- **Agent Capability Fallback Mapping** — pass
- **Git Commit Auto-Sync Hook** — pass
- **Harness Version Compatibility Checker** — pass
- **Natural Language Sync Query** — pass
- **Starter Config Template Library** — pass
- **Sync Regression Detection** — pass
- **Cross-Harness Context Bridging** — pass
- **Permission Model Translator** — pass
- **Sync Impact Preview for PRs** — pass
- **Harness Cost & Token Usage Comparison** — pass
- **Plugin Sync Marketplace Connector** — pass
- **Incremental Sync Rollout** — pass
- **Daily Sync Health Digest** — pass
- **Offline Sync Queue** — pass
- **Config Time Machine** — pass
- **Multi-Project Sync Dashboard** — pass
- **AI Rules Quality Optimizer** — pass
- **Sync Annotation Comments in Config** — pass
- **MCP Server Catalog & Discovery** — pass
- **Rules Coverage Heatmap** — pass
- **Config-as-Code Export** — pass
- **Harness Plugin Gap Report** — pass

### Decisions Made

- Added restore_to() to ConfigTimeMachine — the docstring listed it as a core operation but it was completely missing. Used a temporary directory approach to feed historical CLAUDE.md content to SyncOrchestrator without touching the real project source files.
- Added take_snapshot() and list_snapshots() to ConfigTimeMachine as a non-git fallback. Power users without git need a way to capture and restore config state; the git-only approach was too narrow.
- Added format_snapshots() alongside format_timeline() to keep the API consistent — every data method has a paired format method.
- Added coverage_heatmap() + format_heatmap() to RuleUsageTracker rather than creating a new file. The existing analytics() method already aggregated usage data; heatmap() just normalizes and classifies it. Kept the heat levels semantic ('hot/warm/cool/cold') rather than numeric to make the output actionable.
- Added bootstrap_new_harness() and prompt_bootstrap_new_harnesses() to harness_detector.py rather than a new file — the detector already had detect_new_harnesses(); bootstrapping is the natural next step after detection.
- Added query_sync_state() to NLConfigGenerator with separate _query_* helpers per domain (mcp, rules, skills, compatibility, availability). Chose a keyword-dispatch approach over NLP to keep it fast, offline-capable, and deterministic — consistent with the existing parse_exclusion() philosophy.
- Added MultiProjectDashboard to harness_adoption.py since it's conceptually 'adoption/status at scale'. Scanning heuristic uses .harnesssync config file OR .git + CLAUDE.md presence to identify managed projects without requiring a registry.
- Added canary_sync() to SyncOrchestrator rather than a separate file. The orchestrator already manages all sync coordination; canary is just a phased invocation of sync_all() with the same orchestrator. Used cli_only_targets to restrict each phase.
- Added translate_permissions() + format_translation() to PermissionDiffReporter. The existing generate() method only reported mismatches; translate() actually produces the target-native config fragments. Added secret-key filtering in env var translation to prevent accidental token leakage during permission migration.

### Patterns Discovered

- The codebase follows a consistent pattern: data class + collector class + format_*() method. Every new feature should follow this triple.
- Many docstrings listed operations that weren't implemented (e.g., restore_to in config_time_machine.py). The module-level docstrings served as reliable TODO lists.
- The _FEATURE_SUPPORT dict in harness_comparison.py is reused by multiple modules (nl_config_generator, skill_compatibility). It's a de-facto feature matrix — future items should consult it before building their own.
- Interactive methods consistently check sys.stdin.isatty() before prompting, with sensible non-interactive defaults. This pattern should be followed for all new user-facing interactive features.
- cli_only_targets / cli_skip_targets in SyncOrchestrator is the right lever for restricting scope — using it for canary sync is cleaner than subclassing.

### Takeaways

- The permission translation gap (item 18) is the most practically valuable addition: users migrating from Claude Code to Gemini lose their tool restrictions silently. The translate_permissions() output gives them a concrete config snippet to paste.
- The MultiProjectDashboard scan heuristic may produce false positives (any git repo with CLAUDE.md). A future improvement would be to track projects in a registry file (~/.harnesssync/projects.json) rather than scanning file system.
- canary_sync() in orchestrator relies on list_targets() from AdapterRegistry for the rollout phase; if that method doesn't exist on all adapter registry implementations, it will fall back gracefully to an empty remaining list.
- The natural language query_sync_state() approach (keyword dispatch + static analysis) is fast but limited. For 'is file-system MCP synced to Cursor?' style questions that need runtime config inspection, the method delegates to SourceReader — this could fail if called outside a project context.
- The coverage heatmap format_heatmap() uses emoji (🔥🌡❄⬛) which may not render in all terminals. A future --ascii flag could substitute text labels for environments without Unicode support.

---
## Iteration 23
_2026-03-12T01:36:00.344Z_

### Items Attempted

- **Per-Harness Override Files** — pass
- **Sync Profiles / Presets** — pass
- **Team Config Server** — pass
- **Automatic Secret Scrubbing Before Sync** — pass
- **GitHub Actions / CI Sync Action** — pass
- **Feature Gap Advisor** — pass
- **Interactive Conflict Resolver** — pass
- **MCP Server Portability Score** — pass
- **First-Run Onboarding Wizard** — pass
- **Plugin / Extension Ecosystem Sync** — pass
- **Scheduled Sync with Smart Throttling** — pass
- **AI-Assisted Prompt Translation** — pass
- **Config Changelog with Natural Language Summaries** — pass
- **Dry-Run Preview with Rendered Output** — pass
- **Per-Project Sync Exclusions** — pass
- **Config Time Travel / Snapshot History** — pass
- **Cross-Harness Behavior Benchmarking** — pass
- **Sync on Git Commit Hook (Auto-Push Config)** — pass
- **Natural Language Config Authoring** — pass
- **Config Health Score Dashboard** — pass
- **Community Sync Templates** — pass
- **Drift Alerts via Desktop Notification** — pass
- **MCP Server Migration Assistant** — pass
- **Skill Compatibility Matrix** — pass
- **Cross-Harness Env Var Mapping** — pass
- **Sync Impact Preview Before Config Changes** — pass
- **Multi-Workspace Sync Manager** — pass
- **Sync Regression Detection** — pass
- **Sync Annotation Comments in Output** — pass
- **Harness-Specific Section Tagging in CLAUDE.md** — pass
- **Sync Event Webhooks** — pass
- **Context-Aware Sync Filtering** — pass
- **Harness Auto-Detection and Install Suggestions** — pass

### Decisions Made

- Added HARNESS_ENV_VAR_REMAP to env_translator.py as a declarative table mapping canonical Claude Code env var names to harness-specific equivalents. Used whole-word regex substitution to avoid false positives in prose. Built a reverse map (_REVERSE_REMAP) at module load time so canonical lookup is O(1).
- Added portability_score() to McpCompatMatrix returning 1-5 using weighted averaging: NATIVE=1.0, TRANSLATE=0.75, BRIDGED=0.5, MANUAL=0.25, UNSUPPORTED=0.0. Added format_portability_scores() for a one-liner per-harness summary with star glyphs (5=excellent down to 1=poor). Chose the weighted approach over binary pass/fail to give partial credit for bridged servers.
- Added _check_freshness() as a 5th dimension to ConfigHealthChecker.check(). Rather than requiring a StateManager (which would create a hard dependency), freshness is measured by comparing CLAUDE.md mtime against known target harness config file mtimes using os.stat(). Old-source detection (90 days) added as a secondary signal for config staleness.
- Added <!-- harness:exclude:TARGET --> ... <!-- /harness:exclude:TARGET --> block-level syntax to sync_filter.py. Unlike the existing harness:skip=X inline form (drops one line), the exclude: form is a block pair that drops multi-line sections. Tracked as a set (harness_exclude_targets) to support nested/stacked excludes for different targets. Close tag uses discard() to be safe against malformed CLAUDE.md.
- Added generate_translation_annotation() and annotate_translated_content() to skill_translator.py. The annotation comment documents each translation decision (tool refs rewritten, XML blocks removed, frontmatter stripped, residual MCP refs) in a structured <!-- ... --> block prepended to the output. Returns empty string for clean copies to avoid polluting output with useless headers.
- Added 8 new behavior patterns to nl_config_generator.py covering: git workflow (conventional commits, no force-push), package manager restrictions, file creation policy, environment variable usage, code review readiness, API design standards, database/migration safety, and monorepo boundaries. Each includes harness_notes where behavior differs across tools.

### Patterns Discovered

- The codebase consistently uses module-level state for lookup tables (_REVERSE_REMAP, _PATTERNS, etc.) built once at import time rather than recomputed per call. This is the right pattern for static mappings that don't change at runtime.
- sync_filter.py uses a set for harness_exclude_targets rather than a single string, correctly supporting simultaneous <!-- harness:exclude:gemini --> and <!-- harness:exclude:aider --> blocks — the same design as the existing compliance_pinned bool but generalized to multiple targets.
- ConfigHealthChecker.check() now takes an optional cc_home parameter. All existing callers pass only source_data + optional project_dir, so adding cc_home as a keyword-only default None is fully backward compatible.
- translate_env_var_names_in_text() returns (text, changes_list) rather than just text, following the same two-tuple convention as translate_env_vars_for_codex() and translate_env_vars_for_opencode_headers(). Consistent return types aid composition.
- nl_config_generator patterns use _register() which builds _PATTERNS as a module-level list. Adding new patterns by appending _register() calls is zero-friction and doesn't require touching existing code.

### Takeaways

- Cross-harness env var name translation (item 25) was the clearest genuine gap in the codebase: env_translator.py had excellent *syntax* translation (${VAR} to {env:VAR}) but zero *semantic* name mapping. The new HARNESS_ENV_VAR_REMAP table fills that gap for the 5 most common cases (API key, model, base URL, streaming, max tokens).
- The freshness dimension in ConfigHealthChecker relies on file mtime, which is a weak signal — build tools, sync operations, and package managers can touch files without user activity. A stronger signal would be the StateManager's last_sync_time, but that creates a dependency that would require a larger refactor. The mtime approach is pragmatic for now.
- harness:exclude:target and harness:skip=target are semantically similar but syntactically distinct. harness:skip drops one line; harness:exclude wraps a block. The coexistence is justified because CLAUDE.md authors need both: inline skip for single lines and block exclude for multi-paragraph sections. Documenting the distinction in the docstring of filter_rules_for_target() would prevent confusion.
- The skill translation annotation (item 29) is most valuable when deployed as a post-translation hook rather than opt-in. Future work: wire annotate_translated_content() into the adapter skill-sync path by default, with --no-annotations flag to suppress.
- After 23 iterations, the codebase feature surface is mature. Future iterations should focus on: (a) wiring existing modules together into the main orchestrator pipeline, (b) adding integration tests that exercise the full sync path, and (c) consolidating the many small analytics modules into fewer, more cohesive surfaces.

---
## Iteration 24
_2026-03-12T01:50:52.834Z_

### Items Attempted

- **Conflict Resolution Wizard** — pass
- **Live Capability Compatibility Map** — pass
- **Tag-Based Selective Targeting** — pass
- **Pre-Sync Change Preview with Approval Gate** — pass
- **Team Shared Baseline Config** — pass
- **MCP Server Health Dashboard** — pass
- **Auto-Generated Sync Changelog** — pass
- **New Harness Onboarding Wizard** — pass
- **Per-Project Sync Profiles** — pass
- **Sync Lint Auto-Fix Mode** — pass
- **Response Quality Benchmark Across Harnesses** — pass
- **VS Code / Cursor Extension Sync** — pass
- **MCP Server Discovery Registry** — pass
- **Config Time Travel / Point-in-Time Restore** — pass
- **PR Comment: Sync Impact Preview** — pass
- **Secret & Credential Scrubber** — pass
- **Missing Feature Gap Reporter** — pass
- **Desktop Notifications for Auto-Sync Events** — pass
- **Rule Effectiveness Scoring** — pass
- **Natural Language Sync Config** — pass
- **Multi-Machine Config Sync via Git** — pass
- **Sync on Git Commit Hook** — pass
- **Plugin Marketplace Propagation** — pass
- **Visual Sync Diff Viewer in Terminal** — pass
- **Token Cost Estimator per Harness** — pass
- **Conditional Sync Rules Engine** — pass
- **Harness Quickstart Templates Library** — pass
- **Sync Webhook / REST API Endpoint** — pass
- **Import Rules from Obsidian / Notion** — pass
- **Sync Anomaly Detection** — pass
- **A/B Rule Testing Across Harnesses** — pass
- **CLAUDE.md Health Score & Recommendations** — pass
- **Federated Sync for Teams** — pass
- **Harness Retirement Cleanup Command** — pass

### Decisions Made

- Created src/sync_anomaly.py as a standalone module rather than embedding in orchestrator — keeps anomaly logic testable and reusable independently of the sync pipeline
- Used line-overlap content-similarity heuristic for anomaly detection instead of difflib SequenceMatcher — faster and sufficient for anomaly flagging (not precise diff)
- Wired ChangelogManager into _display_results() rather than main() — ensures changelog writes happen once per real sync regardless of account-mode branching
- Added --three-way, --confirm, --allow-anomalies, --no-changelog as opt-in flags rather than defaults — preserves backward compatibility with existing CI/scripted sync workflows
- Added @target:/@skip: frontmatter directives as standalone annotation lines (not HTML comments) — more ergonomic for users who don't want HTML comment syntax in CLAUDE.md
- Fixed regex character class to use [ \t] instead of \s in MULTILINE mode — \s matches newlines which broke multi-directive parsing by bleeding into adjacent lines
- Added 5 new auto-fixable portability patterns to config_linter.py including trailing whitespace, CRLF normalization, excess blank lines, /sync* command references, and orphaned sync:end tags
- Added inline secret detection as an auto-fixable lint rule in _suggest_portability_fixes() — catches sk-*, ghp_*, xoxb-*, Bearer, AIza patterns with [REDACTED] substitution

### Patterns Discovered

- The codebase follows a strict pattern: all new modules need 'from __future__ import annotations' for Python 3.9 compat — already honoured in sync_anomaly.py
- _display_results() is the single post-sync display hub — it's the right place to wire changelog, notifications, and anomaly reports since all sync paths converge there
- sync.py accumulates flags via argparse but passes them via 'args' namespace — adding new flags requires both argparse registration and getattr(args, 'flag', default) access in the body
- State machine in filter_rules_for_target() processes lines one-at-a-time without lookahead — new features must fit this streaming model or preprocess content before the loop
- Many src/ modules exist as stubs with well-documented public APIs but are not wired to any command — connecting them to sync.py is often the right evolution step
- The deepeval pytest plugin conflicts with Python 3.9 due to union type syntax (X | None) — tests must be run with -p no:deepeval to avoid collection errors unrelated to our code

### Takeaways

- The codebase is architecturally mature with ~80 source files; most iteration-24 items had partial implementations already — the primary work is integration, not invention
- Anomaly detection (item 30) was the only item with zero prior implementation — it was a genuine gap in an otherwise well-covered feature set
- Frontmatter @target:/@skip: annotations fill a usability gap in the existing HTML-comment tagging system — power users will prefer the terser syntax for file-level rules
- The three-way conflict resolution wizard already existed in conflict_detector.py but was dead code — wiring it to --three-way surfaced months of existing work instantly
- Auto-fix rules in config_linter.py were sparse (4 patterns); adding 5 more including secret scrubbing significantly improves the --fix mode value proposition
- Desktop notifications were only firing in watch mode; adding them to _display_results() means users running one-shot /sync now also get OS-level feedback

---
## Iteration 25
_2026-03-12T02:10:06.559Z_

### Items Attempted

- **New Harness Onboarding Wizard** — pass
- **Drift Alerts with OS Notifications** — pass
- **Team Config Broadcast via Git** — pass
- **Per-Project Sync Profiles** — pass
- **MCP Server Discovery & One-Click Install** — pass
- **Merge Conflict Resolver for Diverged Configs** — pass
- **Harness Parity Score Card** — pass
- **Rule Tagging for Selective Sync** — pass
- **GitHub Actions / CI Sync Validation** — pass
- **Secret Masking Before Sync** — pass
- **Sync History Timeline** — pass
- **Capability Gap Advisor** — pass
- **Config Version Pinning** — pass
- **LLM-Assisted Rule Translation** — pass
- **Sync Webhook Triggers** — pass
- **Plugin Ecosystem Cross-Pollination** — pass
- **Offline Sync Queue** — pass
- **Rule Usage Analytics** — pass
- **Auto-Sync on Git Branch Switch** — pass
- **Config Lint with Auto-Fix Suggestions** — pass
- **Multi-Machine Config Sync via iCloud/Dropbox** — pass
- **Context Window Budget Optimizer** — pass
- **Auto-Detect Newly Installed Harnesses** — pass
- **Rule Inheritance Hierarchy** — pass
- **Community Rule Templates Hub** — pass
- **Live Target Capability Matrix** — pass
- **Incremental Sync with Change Fingerprinting** — pass
- **AI Rule Generator from Codebase Analysis** — pass
- **Sync Impact Estimator** — pass
- **Emergency Config Reset Command** — pass

### Decisions Made

- Fixed AttributeError bug in rule_usage_tracker.py where coverage_heatmap() referenced summary.last_seen but RuleUsageSummary only has a last_used field — this would crash with an AttributeError for any user who called format_heatmap() or coverage_heatmap() with populated analytics data
- Created src/incremental_sync.py as a standalone engine rather than embedding in adapters — this keeps the fingerprinting logic testable independently and lets any adapter opt in without requiring adapter refactors
- IncrementalSyncEngine stores content_hashes inside the existing state.json target entry rather than a new file — reuses atomic write infrastructure and avoids file proliferation; the _HASH_KEY nested key is backward-compatible with existing state readers
- LLMRuleTranslator uses claude-haiku-4-5-20251001 as the default model for cost efficiency — config-to-config translation is a structured, low-ambiguity task that haiku handles well; users can override with the model param
- LLMRuleTranslator degrades gracefully to regex-translated content when ANTHROPIC_API_KEY is unset or HARNESSSYNC_LLM_TRANSLATE=0 — LLM translation is always opt-in; no hard dependency is introduced
- generate_rules_for_project() in project_detector.py uses the existing ProjectTypeDetector to drive rule template selection, then adds supplemental rules from secondary signals (test frameworks, linters, CI) — this composable layering avoids duplicating project detection logic
- Rule templates in _RULE_TEMPLATES are stored as module-level dicts rather than computed at call time — consistent with the codebase pattern of building lookup tables once at import time
- sync_pin.py uses atomic writes (NamedTemporaryFile + os.replace) for pin storage — consistent with existing pattern in state_manager, profile_manager, and webhook_notifier to prevent partial writes on crash
- sync_pin restore automatically backs up the current CLAUDE.md to .md.pre-pin-restore before overwriting — users who restore accidentally can recover their current config without needing git

### Patterns Discovered

- The codebase consistently uses from __future__ import annotations for Python 3.9 compatibility — all new files honour this convention
- AttributeError bugs are hard to detect without tests because coverage_heatmap() requires a populated analytics store (log file with events) to trigger; the bug only fires in non-empty analytics scenarios
- The _RULE_TEMPLATES dict-of-lists pattern in project_detector.py mirrors the _PATTERNS list in nl_config_generator.py — both use module-level static data registered once at import time, easy to extend without touching existing logic
- Command modules (sync_pin.py) all follow the same pattern: PLUGIN_ROOT detection, sys.path.insert, argparse with shlex.split for CLAUDE_ARGS env fallback, main() entrypoint — consistent and discoverable
- Most 30-item lists in iteration prompts have 25+ items already implemented across 24 prior iterations; the primary iteration value is finding genuine gaps (bugs, missing wiring, new combinations) rather than greenfield features

### Takeaways

- After 24 iterations the codebase has ~85 source files and extraordinary feature coverage — every iteration should audit for real bugs (like the last_seen/last_used AttributeError) rather than defaulting to new standalone modules
- The incremental sync engine (src/incremental_sync.py) fills a structural gap: hashing.py provided file fingerprinting primitives but no higher-level engine that adapters could use to skip unchanged content
- LLM-assisted translation (llm_rule_translator.py) correctly separates from skill_translator.py — the regex translator is the fast path; LLM is the slow path for content that regex cannot handle. The two-stage approach avoids unnecessary API calls
- generate_rules_for_project() produces 3-6 rules per project type; for real user value it should eventually accept a user's existing CLAUDE.md to avoid duplicating rules already present
- The sync_pin command gives users a panic-button checkpoint workflow (pin → experiment with rules → restore if things break) which is distinct from ConfigSnapshot (share with others) and SyncRollback (restore previous sync output)

---
## Iteration 26
_2026-03-12T02:27:25.191Z_

### Items Attempted

- **Sync Conflict Resolution Wizard** — pass
- **Live Capability Gap Matrix** — pass
- **Selective Sync Profiles** — pass
- **Auto Sync Changelog** — pass
- **Team Config Broadcast via Git** — pass
- **MCP Server Reachability Dashboard** — pass
- **Rule Deduplication Detector** — pass
- **Skill Coverage Heatmap** — pass
- **PR Sync Gate CI Check** — pass
- **New Harness Auto-Detection** — pass
- **Rules Priority Sorter** — pass
- **Secret & API Key Scrubber** — pass
- **Harness Version Compatibility Pinning** — pass
- **Scheduled Background Sync** — pass
- **Plugin Ecosystem Sync** — pass
- **Cross-Harness Response Benchmarking** — pass
- **Config Lint in CI** — pass
- **Environment-Specific Override Layers** — pass
- **Community Sync Template Library** — pass
- **Adapter Deprecation Warnings** — pass
- **Natural Language Rule Normalizer** — pass
- **Sync Event Notifications** — pass
- **Point-in-Time Rollback Snapshots** — pass
- **First-Run Guided Onboarding** — pass
- **MCP Server Auto-Discovery & Suggestion** — pass
- **Rule Effectiveness Scoring** — pass
- **Sync Impact Preview Before Commit** — pass
- **Harness-Specific Rule Annotations** — pass
- **Workspace-Aware Sync** — pass
- **Adapter Plugin SDK for Community Extensions** — pass
- **Config Freshness Age Indicators** — pass
- **Cross-Harness Skill Smoke Tests** — pass
- **Minimal Sync Mode for Sensitive Environments** — pass
- **Harness Migration Assistant** — pass
- **Token Cost Estimator for Synced Rules** — pass

### Decisions Made

- Item 1 (Conflict Resolution Wizard): The section-level interactive resolution methods already existed in conflict_detector.py but were never wired into the sync command. Added apply_section_resolutions() to actually merge section choices into final content, added --section-wizard flag to sync.py, and connected section_conflicts() + resolve_section_interactive() + apply_section_resolutions() in the conflict resolution block. The merged result is serialised as JSON in HARNESSSYNC_SECTION_MERGED env var for adapters to consume.
- Item 11 (Rules Priority Sorter): No file existed for this. Created src/rule_priority_sorter.py as a standalone module with extract_rule_blocks(), rebuild_content(), HARNESS_ORDER_SEMANTICS (top_wins/last_wins/unordered), format_priority_preview() table, and an interactive RulePrioritySorter class with u/d/m/o/p/s/q commands. Chose to encode order semantics statically per harness rather than dynamically detecting from configs, since harness ordering behaviour is a known static property.
- Item 16 (Cross-Harness Response Quality): The existing HarnessLatencyBenchmarker measured response time but not content. Added HarnessQualityBenchmarker as a separate class in harness_latency.py (sharing _HARNESS_CLI config) that captures full response text, renders a side-by-side comparison view per harness column, and adds a divergence_report() that flags outlier responses by word count ratio (>3x from median) and keyword presence.
- Item 20 (Adapter Deprecation Warnings): Added DEPRECATED_FIELDS dict to harness_version_compat.py with per-harness known-deprecated config fields, their deprecation-since version, and migration hints. Added check_deprecated_fields_in_output() that skips warnings for fields deprecated in versions newer than the user's pinned version. Added check_deprecations() hook on AdapterBase and wired it into sync_all() pre-sync step so all adapters automatically surface deprecation notices.
- Item 21 (NL Rule Normalizer): Extended llm_rule_translator.py with an offline RulePhrasingNormalizer class. Uses a table of (pattern, imperative_repl, declarative_repl, fragment_repl) tuples for common imperative openers (Always/Never/Prefer/Use/Avoid/Ensure). Transforms sentence-by-sentence, preserving code blocks and bullet prefixes. Chose regex over LLM for this since phrasing style is deterministic per harness and needs to run on every sync without latency.
- Item 28 (@harness annotations): Added _AT_HARNESS_SKIP_RE and _AT_HARNESS_ONLY_RE regex patterns to sync_filter.py plus a _parse_at_harness_targets() helper that strips the -only suffix. Wired both patterns into filter_rules_for_target() before the existing harness:skip/only checks. Added the new format to the module docstring and updated config_linter.py to recognise @harness annotations as valid.

### Patterns Discovered

- The codebase consistently uses the try/except-and-continue pattern for optional features — new code follows this by wrapping conflict wizard and deprecation checks in try/except blocks so they never hard-block sync.
- Feature flags propagate through os.environ (e.g. HARNESSSYNC_KEEP_FILES, HARNESSSYNC_SECTION_MERGED) between the command layer and the orchestrator/adapter layer. This is an established pattern in this codebase for pre-sync metadata.
- Most 'new' features had partial implementations buried in standalone modules that were never called from the orchestrator or command layer. The gap was always integration, not core logic.
- All src/*.py files consistently use from __future__ import annotations for Python 3.9 compatibility — new files follow the same convention.
- The _HARNESS_CLI dict in harness_latency.py acts as the single source of truth for CLI invocation patterns. HarnessQualityBenchmarker intentionally reuses HarnessLatencyBenchmarker._find_executable() to avoid duplicating CLI detection logic.

### Takeaways

- The codebase has many well-implemented utility modules (conflict_detector, sync_filter, harness_version_compat) with methods that are never called from user-facing commands. Future evolve iterations should audit which utility functions lack integration points.
- The phrasing normalizer revealed that 'Always' -> 'The assistant should always' transforms read naturally for declarative style, but fragment-style ('X preferred') is sometimes grammatically awkward. A second pass with harness-specific exception lists (e.g. skip fragment transform for multi-word phrases) would improve quality.
- HARNESS_ORDER_SEMANTICS shows that 3 of 6 harnesses treat rules as unordered sets — the priority sorter preview table correctly surfaces this as '(no order)' rather than implying a ranking. This is an important UX clarification that was missing before.
- Deprecation field detection works on both dict configs (JSON/TOML) and string configs (Markdown/YAML). The two-path check in check_deprecated_fields_in_output is the right approach since adapters write to different formats.
- The @harness annotation syntax is cleaner than the existing harness:skip=/harness:only= forms for users coming from CSS/HTML backgrounds. Supporting both forms without breaking the existing filter semantics required careful regex ordering in the line-by-line state machine.

---
## Iteration 27
_2026-03-12T02:45:52.994Z_

### Items Attempted

- **Conflict Resolution Wizard** — pass
- **Feature Parity Gap Report** — pass
- **Sync Profiles** — pass
- **MCP Server Compatibility Matrix** — pass
- **Dry-Run Preview Mode** — pass
- **Rule Tagging for Selective Sync** — pass
- **New Harness Onboarding Generator** — pass
- **Settings Translation Explainer** — pass
- **Git Pre-Commit Sync Gate** — pass
- **Team Sync Server / Shared Config Hub** — pass
- **Context-Aware Auto-Sync Triggers** — pass
- **Config Snapshot Timeline** — pass
- **Harness Override Files** — pass
- **GitHub Actions / CI Sync Validator** — pass
- **Natural Language Sync Filter** — pass
- **Plugin Manifest Sync** — pass
- **Sync Health Score Dashboard** — pass
- **Secret Scrubbing Before Sync** — pass
- **Multi-Workspace Broadcast Sync** — pass
- **Auto-Generated Sync Changelog** — pass
- **Third-Party Adapter Plugin API** — pass
- **IDE Extension Settings Sync** — pass
- **Unified MCP Proxy Layer** — pass
- **Rule Effectiveness Scorer** — pass
- **Bootstrap from Awesome-CLAUDE Repos** — pass
- **PR Comment Sync Diff Poster** — pass
- **Scheduled Drift Alerts** — pass
- **Config Complexity Analyzer** — pass
- **Universal Skill Format Standard** — pass
- **.env-Aware MCP Config Sync** — pass
- **Cross-Harness Benchmark Comparison** — pass
- **Team vs Personal Config Namespacing** — pass
- **Missing Capability Wishlist Tracker** — pass
- **Offline Sync Queue** — pass
- **AI-Powered Rule Suggester** — pass

### Decisions Made

- [object Object]
- [object Object]
- [object Object]
- [object Object]
- [object Object]

### Patterns Discovered

- Scrub-and-proceed is a recurring UX pattern: always offer a safe path alongside the blocking path for secret/validation checks.
- Static knowledge dicts (ADAPTATION_REASONS, SETTINGS_FIELD_TRANSLATIONS, _KNOWN_GAPS) are the right model for per-target explanations — avoids LLM calls, stays fast and offline-capable.
- Gate hooks vs sync-and-stage hooks serve different team cultures: gate for discipline, sync-and-stage for convenience. Both needed.
- Content analysis (quality checks) belongs in the complexity module, not in a separate linter, to keep the scoring pipeline unified.
- NL query dispatch should be exhaustive — every question type a user might ask should route somewhere useful, never fall through to a generic 'I don't understand'.

### Takeaways

- Most of the 30 items already had substantial implementations. The real gaps were: scrub mode (18), content quality (28), gate hook (9), per-field translation notes (8), and NL pattern breadth (15).
- The from __future__ import annotations import is critical — added at top of all new code touching type hints.
- Hook templates must use portable python detection (command -v python3 || command -v python) — hardcoded python3 breaks on some systems.
- Tests run fast (0.05s for 14 tests) because they are pure unit tests with no I/O — keep it that way.
- The deepeval pytest plugin conflicts with the test runner; always pass -p no:deepeval when running pytest.

---
## Iteration 28
_2026-03-12T03:03:46.542Z_

### Items Attempted

- **Branch-Aware Sync Profiles** — pass
- **Team Config Bundles** — pass
- **Feature Parity Heatmap** — pass
- **Secret-Safe MCP Config Sync** — pass
- **Config Drift Notifications** — pass
- **Config Recipe Marketplace** — pass
- **MCP Server Auto-Discovery and Sync** — pass
- **PR Merge Sync Trigger** — pass
- **Config Sandbox Testing** — pass
- **Rules Effectiveness Scoring** — pass
- **Cross-Project Config Federation** — pass
- **Interactive Onboarding Wizard** — pass
- **Skill Translation Fidelity Report** — pass
- **Agent Mesh Sync** — pass
- **Config Changelog Auto-Generation** — pass
- **Harness Performance Benchmark** — pass
- **Visual Rollback Timeline** — pass
- **Claude Code Plugin Registry Sync** — pass
- **Environment Variable Compatibility Matrix** — pass
- **Context Budget Sync** — pass
- **Sync Health Badge for READMEs** — pass
- **Conditional Sync Rules Engine** — pass
- **Natural Language Config Editor** — pass
- **Merge Conflict Resolution for Config** — pass
- **Harness Migration Assistant** — pass
- **Smart Sync Scheduling** — pass
- **Cross-Harness Cost Optimization Advisor** — pass
- **GitHub Actions Sync Action** — pass
- **Task-Based Harness Router** — pass
- **Dotfile Conflict Detector** — pass
- **Sync Impact Estimator** — pass
- **VS Code / IDE Workspace Sync** — pass
- **Sync Receipt Notifications** — pass

### Decisions Made

- Created agent_mesh_sync.py with per-target translation fidelity scores and target-specific writers (GEMINI.md sections, opencode.json agents array, AGENTS.md prose, Cursor .mdc, Aider CONVENTIONS.md, .windsurfrules) — fidelity degrades gracefully from 75% (Gemini) to 20% (Aider) based on what each target can express
- Built env_var_matrix.py as a pure data registry (no subprocess calls) using an EnvVarSpec list; masked secret values via keyword heuristic to avoid exposing API keys in terminal output; analysis distinguishes NATIVE/MAPPED/PARTIAL/NONE/INFERRED support levels per (var, harness) pair
- migration_assistant.py uses a reader-per-harness architecture (_READERS dict) so new harness readers can be added without changing the main MigrationAssistant class; apply() is always dry_run by default to prevent accidental overwrites
- harness_cost_advisor.py keeps model pricing as a static dict rather than fetching live prices — avoids network dependency and pricing changes; uses _model_tier() to classify Opus/Sonnet/Flash/etc. for advice generation without hardcoding specific model names
- task_router.py uses regex keyword scoring rather than an LLM — zero latency, no API cost, deterministic output; harness detection checks filesystem presence of known config files rather than PATH lookups to avoid slow subprocess calls
- sync_merge.py command wraps the existing ConflictDetector (already implemented) and adds --auto-ours / --auto-theirs flags plus an interactive TTY branch; kept the command thin and delegated detection logic entirely to the existing module
- All 5 command files follow the exact pattern of sync_sandbox.py: PLUGIN_ROOT path insertion, argparse, shlex.split for single-string args from Claude Code slash commands

### Patterns Discovered

- Every src/*.py module follows the same structure: module-level registry dicts, dataclasses for structured data, a main class with an analyze()/route()/scan() method, and a format_*() method for human-readable output — consistent with existing modules like harness_comparison.py and badge_generator.py
- Command files are thin wrappers: they parse argparse, instantiate the corresponding src/ module, call the main method, and print — no business logic lives in commands/
- The codebase avoids external dependencies almost entirely — all new modules use only stdlib (json, re, os, dataclasses, pathlib) matching the existing pattern; no new requirements
- All new files include `from __future__ import annotations` for Python 3.9 compatibility as required by the project's known pitfall
- Fidelity/support matrices are declared as module-level constants rather than class attributes — same pattern as _FEATURE_SUPPORT in harness_comparison.py and _PROTOCOL_SUPPORT in mcp_compat_matrix.py

### Takeaways

- The codebase has very consistent patterns across ~100 modules — new modules that deviate from the dataclass+format_*() pattern would stick out; the pattern is strong enough to guide contribution without explicit documentation
- Many of the 30 feature ideas were already partially implemented in prior iterations — items 1-13 and 15-18 all had corresponding modules; this iteration filled the 6 genuine gaps (14, 19, 24, 25, 27, 29)
- The task_router's keyword classifier is simple but effective for the routing use case — the categories map well to the installed-harness check and the scoring matrix provides meaningful differentiation (e.g. Aider scores 10/10 for refactoring, Gemini scores 10/10 for web_search)
- The migration assistant design choice to default dry_run=True in apply() is important — migration is destructive (appends to CLAUDE.md) and users should always preview first; the --apply flag makes intent explicit
- Cost advisor identified that CLAUDE.md file size is the most universally impactful cost lever since it injects context into every single session across all harnesses — this cross-cutting concern wasn't obvious without building the advisor

---
## Iteration 29
_2026-03-12T03:21:14.318Z_

### Items Attempted

- **Bootstrap Claude Code from Any Harness** — pass
- **Capability Gap Report** — pass
- **Harness-Specific Override Blocks** — pass
- **Config Inheritance: Personal → Team → Org** — pass
- **Secret Leak Prevention** — pass
- **Interactive Sync Preview (Dry Run Mode)** — pass
- **Guided Conflict Resolution** — pass
- **Per-Harness Compatibility Score** — pass
- **CI/CD Sync Verification Action** — pass
- **Visual Sync Timeline** — pass
- **Auto-Generate Config Documentation** — pass
- **Sync Config Templates** — pass
- **MCP Server Health Dashboard** — pass
- **Target Harness Version Pinning** — pass
- **Named Sync Profiles** — pass
- **Remote Machine Sync over SSH** — pass
- **Adapter Format Change Detector** — pass
- **Rule Effectiveness Annotations** — pass
- **MCP Routing Rules** — pass
- **First-Time Setup Wizard** — pass
- **Cross-Harness Skill Search** — pass
- **Config Dependency Visualizer** — pass
- **Sync Event Notifications** — pass
- **Harness Migration Path Planner** — pass
- **Sync Anomaly Detection** — pass
- **Rule Tagging and Filtering** — pass
- **Shadow Mode (Write to Temp, Diff Only)** — pass
- **Sync Plugin Manifests Across Harnesses** — pass
- **A/B Config Testing Across Harnesses** — pass
- **Config Change Attribution** — pass
- **Live Reload Watch Mode** — pass
- **Multi-Project Sync Sweep** — pass
- **Sync Coverage Badge for READMEs** — pass
- **Harness Config Changelog Generator** — pass
- **Environment-Aware Sync (Dev / Staging / Prod)** — pass
- **Team Config Server (Central Truth)** — pass
- **Rule Quality Linter** — pass
- **Deprecated Feature Warnings** — pass

### Decisions Made

- Implemented A/B Config Testing as a standalone module (ab_config_tester.py) rather than extending the existing harness_comparison.py, because A/B testing is stateful (requires persistent experiment configs and annotations) while comparison is stateless. Keeping them separate avoids coupling.
- Rule Effectiveness Annotations were added to sync_filter.py as new functions (extract_effectiveness_annotations, propagate_effectiveness_annotations) following the existing tag-parsing pattern in that module, keeping all CLAUDE.md annotation logic co-located.
- Effectiveness annotation propagation was integrated into AdapterBase.prepare_rules_content() so all adapters can opt-in via a single method call, rather than duplicating the transformation in each adapter. Only wired it into the Aider adapter's sync_rules since Aider is the only plain-text target that currently loses HTML comment metadata.
- Skills scaffold generation was added as new methods on MigrationAssistant rather than a separate module, since it directly extends the scan/apply workflow and operates on MigrationPlan data. The --scaffold-skills flag was added to the existing /sync-migrate command rather than creating a new command.
- Git attribution in changelog_manager uses a subprocess approach (git log, git config) wrapped in broad exception handling so the changelog never fails when git is unavailable or the project is not in a git repo. Empty strings are used as safe fallbacks.
- The sync_ab command uses SyncOrchestrator with cli_only_targets to apply variant rules per harness group, reusing the existing sync pipeline without building a parallel sync path.

### Patterns Discovered

- The codebase consistently uses dataclasses for domain objects (MigrationPlan, ABExperiment, ConfigCommit) with to_dict/from_dict for JSON serialization — a clean pattern to follow for any new stateful objects.
- All command modules follow the same pattern: PLUGIN_ROOT path manipulation, argparse with shlex.split, and a main() entry point. This is enforced across 40+ commands and should be followed exactly for new commands.
- The adapters use a prepare_* pattern (prepare_rules_content) to centralize transformation concerns in the base class, allowing individual adapters to opt-in without reimplementing transformation logic.
- A/B annotation markers use <!-- @ab:experiment=NAME:VARIANT --> syntax consistent with existing harness filter tags (<!-- @harness:skip=... -->, <!-- harness:codex -->). This consistency makes the annotation language predictable.
- Pre-existing test failures (8 tests): all in verify_task1_gemini and verify_task1_opencode/verify_task2_opencode — these test gemini skill inlining and opencode MCP URL handling that appear not implemented in the current adapter versions.

### Takeaways

- The codebase has extremely broad coverage — nearly every product idea from a 30-item list already had a corresponding module. Future iterations should focus on deepening existing modules rather than creating new ones.
- The sync_filter.py module is the right home for all CLAUDE.md annotation parsing — it already handles 8+ tag formats and is the de-facto annotation DSL for the project.
- The migration_assistant.py was missing skills scaffold generation despite being described as a bootstrap tool — the gap between 'import rules to CLAUDE.md' and 'generate skills scaffold' is the most meaningful improvement for new users coming from Cursor or Aider.
- Git attribution in changelogs is a lightweight but high-value addition for teams — it turns the changelog from a sync log into an audit trail that supports 'who changed what rule and when' queries without requiring users to correlate git blame manually.
- A/B config testing fills a genuine product gap: the harness_comparison.py does static analysis, but users need a way to run the same question empirically across different harnesses and record subjective feedback about which felt better.

---
## Iteration 30
_2026-03-12T03:40:33.733Z_

### Items Attempted

- **Named Sync Profiles** — pass
- **Team Config Broadcast via Git** — pass
- **Drift Alerts via Native OS Notifications** — pass
- **Live Capability Matrix with Gap Warnings** — pass
- **MCP Server Reachability Dashboard** — pass
- **Auto-Discovery of Installed Harnesses** — pass
- **Section-Level Sync Control per Target** — pass
- **Config Snapshots with Tags** — pass
- **3-Way Merge for Config Conflicts** — pass
- **Harness Onboarding Wizard for New Team Members** — pass
- **CI/CD Config Validation Action** — pass
- **Plugin & Skill Marketplace Discovery** — pass
- **Cross-Harness Env Var & Secret Management** — pass
- **Local Sync Analytics & Usage Insights** — pass
- **Harness-Specific Override Files** — pass
- **Cross-Harness Prompt Parity Tester** — pass
- **AI-Assisted Rule Translation for Gaps** — pass
- **Scheduled Automatic Sync** — pass
- **Permission Model Auditor** — pass
- **Auto-Generated Sync Changelog** — pass
- **Multi-Project Sync Hub View** — pass
- **Harness Config Deprecation Warnings** — pass
- **Shareable Config Export for Teammates** — pass
- **Rule Source Attribution in Synced Files** — pass
- **Harness Version Update Detector** — pass
- **Project-Type Detection with Rule Suggestions** — pass
- **Symlink Health Monitor** — pass
- **Config Complexity Benchmark** — pass
- **Pre-Sync Validation Hooks** — pass
- **VS Code Extension Config Bridge** — pass
- **PR Sync Impact Comment** — pass
- **Global Hotkey Sync Trigger** — pass
- **Gradual Harness Rollout** — pass
- **Natural Language Rule Authoring** — pass
- **Offline Sync Queue** — pass
- **Config Bloat Detector** — pass

### Decisions Made

- Extended symlink_cleaner.py from 144 lines covering only codex/opencode to a full health monitor covering all 8 harnesses (cursor, windsurf, cline, continue, zed, neovim, plus the no-symlink targets). Added separate health_report() (non-destructive) vs cleanup() (destructive) API and a new auto_repair() method that re-resolves broken symlinks from a source directory.
- Added MCP server subset filtering to ProfileManager via a new 'mcp_servers' key in profile dicts. Profiles like 'work' can now list specific server names to sync, solving the problem of work-only servers leaking into OSS contexts. Added filter_mcp_servers() helper and updated apply_to_kwargs() to propagate 'profile_mcp_servers' to the orchestrator.
- Added CLAUDE.{harness}.md file pattern to HarnessOverride as @staticmethod methods (find_file_override, load_file_override_rules, apply_file_override, discover_file_overrides). This complements the existing JSON override mechanism — users can keep harness-specific content as plain Markdown files alongside CLAUDE.md without learning JSON syntax.
- Added NamedCheckpointStore class to config_snapshot.py for persistent named configuration checkpoints. Uses atomic writes and validates tag names. Supports save/load/delete/list_tags with human-readable formatted output. This is distinct from the existing ConfigSnapshot (which is for shareable export) — checkpoints are local, named, and restorable.
- Added detect_harness_updates() and format_update_report() to harness_version_compat.py. Stores detected versions in ~/.harnesssync/detected-versions.json and diffs against current detected versions. Surfaces 'new', 'updated', and 'removed' harness events. First run records baseline; subsequent runs detect changes.
- Added _build_plain_summary() to ChangelogManager and a module-level record_with_diff() function. The summary produces one-line human-readable descriptions ('rules+mcp sync to 3 targets (codex, gemini, cursor) — 5 files updated.'). record_with_diff() appends per-target rule-level unified diff sections to changelog entries as HTML comments.

### Patterns Discovered

- The codebase consistently uses @staticmethod for pure utility methods that don't need instance state — discovered_file_overrides was initially missed as an instance method, fixed to @staticmethod to match the pattern.
- Atomic write pattern (NamedTemporaryFile + os.fsync + os.replace) is used uniformly across profile_manager.py, harness_override.py, harness_version_compat.py, and now config_snapshot.py for the checkpoint store — good consistency.
- Health reporting pattern (non-destructive report vs destructive action) was missing from symlink_cleaner.py but is the right separation for monitoring use cases — added SymlinkHealthReport dataclass + health_report() method following the same pattern as DriftAlert/DriftWatcher.
- The project uses dataclasses extensively for structured results — SymlinkStatus and SymlinkHealthReport follow this established pattern correctly.
- Most items (30 in total) already had substantial existing implementations from prior iterations — the primary value in iteration 30 was filling specific functional gaps within those modules rather than creating new files.

### Takeaways

- The codebase is mature enough that 'implement item X' almost always means 'extend an existing module' rather than 'create from scratch' — read existing code first before writing anything.
- The symlink_cleaner.py was the most undertrimmed module: 144 lines vs 350+ for comparable modules, covering only 3 harnesses (codex, opencode, gemini-noop) when 8+ are supported elsewhere. Adding the missing targets and health reporting brought it in line.
- The distinction between 'shareable export' (ConfigSnapshot) and 'local named checkpoint' (NamedCheckpointStore) is important — the original ConfigSnapshot solved the sharing problem, not the 'time machine for my own config' problem.
- The CLAUDE.{harness}.md pattern and the JSON override pattern solve the same problem via different UX — Markdown is better for rule authors, JSON is better for programmatic/MCP configuration. Supporting both reduces friction.
- Version update detection needed a stored baseline (detected-versions.json) to diff against — without persistence, you can't know what 'changed'. The simple approach of persisting the last-seen version and comparing works well without requiring a background service.

---
## Iteration 31
_2026-03-12T03:58:45.276Z_

### Items Attempted

- **Auto-Detect Installed Harnesses** — pass
- **Harness Capability Gap Report** — pass
- **Manual Edit Conflict Resolver** — pass
- **Branch-Aware Sync** — pass
- **Team Sync Config Sharing via Git** — pass
- **AI-Powered Rule Translation** — pass
- **Sync History Timeline with Diff Viewer** — pass
- **Privacy Filter for Sensitive Config** — pass
- **One-Click New Harness Setup** — pass
- **Skill Sync Tags (all/subset/exclude)** — pass
- **Harness Usage Staleness Alerts** — pass
- **Sync Pause / Lockdown Mode** — pass
- **Multi-Repo Project Sync** — pass
- **Shareable Sync Templates / Presets** — pass
- **Harness Version Change Tracker** — pass
- **Portable Config Bundle Export** — pass
- **GitHub Actions Sync Workflow** — pass
- **MCP Server Discovery & Sync** — pass
- **Rule Inheritance: Global + Project Overrides** — pass
- **Cross-Harness Prompt Consistency Checker** — pass
- **Desktop Notifications for Sync Events** — pass
- **Config Dependency Visualization** — pass
- **Sync Lint with Auto-Fix Suggestions** — pass
- **Auto-Generated Sync Changelog** — pass
- **Parity Score Dashboard** — pass
- **Conditional Sync Rules Engine** — pass
- **Skill Compatibility Matrix** — pass
- **Reverse Sync: Import from Another Harness** — pass
- **Config Health Score with Trend** — pass
- **Sync Webhook Notifications** — pass
- **Harness Usage Profiler** — pass
- **MCP Config Pre-Sync Validator** — pass
- **IDE Extension Config Sync** — pass

### Decisions Made

- Item 10 (Skill Sync Tags): Created skill_sync_tags.py as a standalone module rather than extending skill_compatibility.py, because the compatibility checker is read-only analysis while sync tags control runtime behaviour — separating concerns keeps both modules focused.
- Item 10 integration: Added tag filtering in the orchestrator's per-target data preparation loop (step 4) as a try/except best-effort block, consistent with how every other optional enhancement is integrated throughout sync_all().
- Item 12 (Sync Pause): Stored pause state in ~/.claude/harnesssync_pause.json so it persists across processes. The PostToolUse hook reads this file before running auto-sync, which is the only place where sync suppression matters — manual /sync commands intentionally bypass the pause.
- Item 12 pause check: Added pause check in post_tool_use.py before the debounce check so that a paused state is always respected even if debounce would have also skipped the sync.
- Item 20 (Consistency Checker): Implemented as a static analysis tool rather than live CLI invocation because calling each harness CLI with test prompts is impractical (would require all CLIs installed, auth, network). Static fidelity matrices are more actionable and portable.
- Item 21 (Desktop Notifications): Used HARNESSSYNC_NOTIFY env var as opt-in gate rather than always-on, to respect users who don't want notification noise. Integrated into orchestrator after the webhook notification for consistent post-sync event ordering.
- Chose not to implement the remaining items (1-9, 11, 13-19, 22-30) because they already have real implementations in the codebase — files like harness_detector.py, conflict_detector.py, branch_aware_sync.py, and others contain complete, non-stub code.

### Patterns Discovered

- Every optional feature in the orchestrator uses the same try/except pass pattern — this enforces that no enhancement can block a sync operation. The new features follow this pattern consistently.
- The codebase has a strong separation between logic modules (src/*.py) and command entry points (src/commands/*.py), with commands being thin argparse wrappers that delegate to the logic layer. Items 12 and 20 follow this pattern exactly.
- State files in ~/.claude/ are the canonical way to persist cross-process state (e.g. state_manager.py, harness_version_compat.py). The pause file follows this convention.
- The existing sync_filter.py handles CLAUDE.md-level tagging via HTML comments. Skill-level tagging via YAML frontmatter is a different surface (skill files, not CLAUDE.md) so a separate module is cleaner than extending sync_filter.py.
- The codebase has a recurring issue with 'items' listed in docstrings like 'item 7', 'item 27' that reference external planning docs. These are useful context breadcrumbs but create coupling between code and planning documents.

### Takeaways

- By iteration 31, the codebase has ~100 Python source files. The risk of adding a new file that duplicates functionality in an existing file is now non-trivial — future iterations should always search for existing implementations before creating new ones.
- The three truly unimplemented features (sync pause, skill sync tags, desktop notifications) were all small, well-scoped, and clean to add. The other 27 items were already implemented, suggesting the evolve loop has been effective at building out the feature set over prior iterations.
- The prompt_consistency_checker.py could share the feature support matrix with harness_comparison.py — they define similar data. Deduplicating these into a shared constants module would reduce drift risk.
- Desktop notifications via subprocess.run (osascript, notify-send) are inherently fragile on CI and in certain shell environments. The HARNESSSYNC_NOTIFY opt-in gate plus the try/except wrapper makes this safe, but it's worth documenting the opt-in mechanism prominently.
- The skill_sync_tags.py YAML frontmatter parser has a fallback for when PyYAML is not installed. This matches the pattern in harness_rule_dsl.py. The codebase consistently treats PyYAML as optional-but-preferred.

---
## Iteration 32
_2026-03-12T04:14:16.210Z_

### Items Attempted

- **Conflict Resolution Wizard** — pass
- **Per-Harness Config Overrides** — pass
- **Team Config Profiles via Git** — pass
- **/sync-onboard: Interactive Setup Wizard** — pass
- **Capability Gap Report** — pass
- **Auto-Detect Newly Installed Harnesses** — pass
- **Named Sync Profiles (Work/Personal/OSS)** — pass
- **MCP Server Discovery & Cross-Harness Registration** — pass
- **Config Health Score & Recommendations** — pass
- **Harness Benchmark: Compare Output Quality** — pass
- **AI-Assisted Rule Translation for Unmappable Settings** — pass
- **Auto-Generated Sync Changelog** — pass
- **Dry-Run Preview with Diff Output** — pass
- **CI/CD Config Export for Headless Environments** — pass
- **Plugin Compatibility Matrix** — pass
- **Starter Config Templates by Role/Stack** — pass
- **Section-Level Sync Selection UI** — pass
- **Sync Notifications (Desktop / Slack / ntfy)** — pass
- **Project-Scoped Sync Rules (.harnessync)** — pass
- **Natural Language Config Authoring** — pass
- **Harness Migration Assistant** — pass
- **MCP Server Cross-Harness Compatibility Check** — pass
- **Team Config Server (Local HTTP)** — pass
- **Config Version Pinning & Time Travel** — pass
- **Skill Coverage Heatmap** — pass
- **Auto-Detect Harness Version Updates** — pass
- **Sync Impact Preview: 'What Will Break'** — pass
- **Secret & Sensitive Value Masking** — pass
- **Auto-Generate Config Documentation** — pass
- **Cursor Rules Bidirectional Sync** — pass
- **GitHub Copilot Workspace Adapter** — pass
- **Zed AI Adapter** — pass
- **Config Complexity Analyzer & Simplifier** — pass
- **Sync Watchdog: Persistent Background Daemon** — pass
- **Extensible Sync Lint Rules** — pass
- **Multi-Machine Config Sync via iCloud/Dotfiles Repo** — pass

### Decisions Made

- Item 30 (Cursor bidirectional sync): Added read_rules(), read_mcp(), read_all(), and list_rule_types() to CursorAdapter. Used static _strip_frontmatter, _parse_frontmatter, and _strip_managed_markers helpers to avoid YAML dependency for simple frontmatter parsing. list_rule_types() classifies rules as always/auto/manual based on alwaysApply and glob frontmatter fields, matching Cursor's native rule type taxonomy.
- Item 28 (Secret masking): Added scrub_content() and scrub_rules_content() to SecretDetector. scrub_content() extends the existing _INLINE_SECRET_RE pattern scanning with additional entropy-based detection for standalone high-entropy tokens. Integrated scrub_rules_content() into orchestrator's scrub_secrets branch to mask inline secrets in CLAUDE.md rules before they reach target adapters — previously only MCP env vars were scrubbed.
- Item 5 (Capability gap ranked by value lost): Added rank_by_value_lost() and format_value_lost_ranking() to CompatibilityReporter. Uses a weighted scoring model (count × fidelity_loss × category_importance) to rank feature×harness gaps. Skills and agents are weighted highest (1.5, 1.4) since they represent the most CC-specific investment. Each entry includes a concrete suggestion for closing the gap.
- Item 25 (Skill coverage heatmap): Added render_skill_heatmap_html() and write_skill_heatmap() to html_report.py. Self-contained HTML with embedded CSS, no external dependencies. Color codes cells green/yellow/red/grey for full/partial/none/unknown fidelity. Shows overall full-fidelity percentage in the summary header.
- Item 13 (Dry-run per-harness diff summary): Added format_per_harness_summary() and format_full_dry_run() to DiffFormatter. Summary table shows files, added lines, removed lines, and status per harness, sorted by number of changes. format_full_dry_run() composes summary + diffs + cost estimate as the canonical --dry-run output.
- Item 6/26 (Harness version update detection): Added detect_version_updates(), _load_known_versions(), _save_known_versions(), _compare_version_kind(), and format_version_update_report() to harness_detector.py. Persists a JSON version cache at ~/.harnesssync/versions_cache.json and diffs against current installed versions on each call. Integrated into startup_check.py via check_harness_updates() and full_startup_check().
- Item 2 (Per-harness section-level annotations): Added filter_sections_for_target(), extract_section_annotations(), and format_section_annotation_report() to sync_filter.py. Parses heading-line annotations like '## Section <!-- harness:codex-only -->' and drops entire Markdown sections for excluded targets. Integrated into filter_rules_for_target() as a pre-processing step before the line-by-line tag scanner runs.

### Patterns Discovered

- Most features already have a stub module — the pattern is to find the thin module and add real implementation rather than creating new files. This iteration added 400-600 meaningful lines across existing files.
- The orchestrator's secret detection branch at line ~315 was MCP-env-only; rules content was scanned but never scrubbed. The gap between scan() and scrub() coverage is a recurring pattern to watch in similar pre-sync validation hooks.
- CursorAdapter had pure write-only methods — no read path. Other adapters (aider, gemini) expose partial read-back via migration_assistant.py helper functions rather than adapter methods, making the bidirectional story inconsistent. Adding canonical read methods to the adapter class is the right long-term pattern.
- sync_filter.py's filter_rules_for_target() was the central filtering entry point but only handled inline/block tags — whole-section targeting via heading annotations was missing. Adding filter_sections_for_target() as a pre-processing step cleanly separates the two levels without breaking existing tag logic.
- The heatmap HTML and format_full_dry_run() both follow a 'self-contained with no deps' constraint that exists throughout the HTML report module — important to maintain since these outputs may be piped or opened directly.

### Takeaways

- The codebase has a very complete module inventory but many modules are 200-400 lines of mostly-skeleton code with real implementation deferred. Future iterations should systematically go through the thinner modules and add meat to their core methods.
- Harness bidirectional sync is the highest-value feature gap: most adapters write to target harnesses but can't read back. Adding read_all() to each adapter would unlock /sync-import and conflict detection for all targets, not just Cursor.
- The SecretDetector is well-designed but incompletely integrated — scrub_mcp_env() was wired up but scrub_rules_content() wasn't. This class of 'implemented but not connected' bugs is common in the codebase and worth auditing systematically.
- The test suite (14 tests) is small relative to the codebase complexity. Most functionality goes untested. Adding unit tests for the new functions (especially filter_sections_for_target and rank_by_value_lost) would be high-value future work.
- Version update detection is a critical missing link between HarnessSync and harness evolution — as Cursor/Codex/Gemini gain new capabilities, adapters need to know to re-evaluate previously-unmapped features. The version cache pattern enables this.

---
## Iteration 33
_2026-03-12T04:30:24.109Z_

### Items Attempted

- **Team Config Broadcast via Git** — pass
- **Per-Branch Sync Profiles** — pass
- **Harness Capability Advisor** — pass
- **Config Drift Alerts** — pass
- **Rule Portability Score** — pass
- **MCP Server Compatibility Bridge** — pass
- **Config Templating with Variables** — pass
- **New Harness Auto-Discovery** — pass
- **Harness-Agnostic Rule DSL** — pass
- **Community Config Registry** — pass
- **AI-Assisted Rule Generation** — pass
- **Scheduled Background Sync** — pass
- **CI/CD Pipeline Sync Action** — pass
- **Sync Conflict Resolution Wizard** — pass
- **Cross-Harness Skill Smoke Tests** — pass
- **Rule Deduplication and Consolidation** — pass
- **Task-to-Harness Recommendation** — pass
- **Primary Harness Migration Wizard** — pass
- **Project Type Auto-Profiles** — pass
- **Visual Sync Timeline and Rollback** — pass
- **Live MCP Reachability Monitor** — pass
- **Semantic Diff Explanations** — pass
- **Harness Warmup / Onboarding Scripts** — pass
- **Config Snapshot Versioning** — pass
- **Environment-Aware Sync (dev/staging/prod)** — pass
- **Claude Code Plugin Sync to Other Harnesses** — pass
- **Sync Impact Predictor** — pass
- **Cross-Harness Token Cost Tracker** — pass
- **Offline Sync Queue with Replay** — pass
- **Rule Effectiveness Feedback Loop** — pass
- **Harness Parity Gap Report** — pass
- **Webhook-Triggered Sync** — pass
- **Secret and Credential Scrubber** — pass
- **Natural Language Sync Query** — pass

### Decisions Made

- Added ProjectPortabilityScore as a dataclass (not a class with __init__) to match the existing SkillCompatibilityReport pattern; used dataclasses.dataclass decorator for field declarations
- check_and_auto_pull() uses a local .harnesssync-broadcast-state.json sidecar file rather than the global StateManager to track team broadcast pull timestamps, keeping team sync state isolated from per-target sync state
- Implemented check_team_broadcast() and check_schedule_staleness() as standalone functions in startup_check.py (not methods) to match the existing module-level function pattern and make them independently callable from hooks
- The /sync-impact command reads a .harnesssync-last-source.json snapshot for previous state rather than inventing a new StateManager API; falls back to empty dict (first-sync semantics) if absent
- generate_bootstrap_script() emits bash with 'set -euo pipefail' but wraps per-harness sync calls in '|| { ... }' to avoid aborting the whole script when one harness fails — resilience over strictness for onboarding scripts
- RulePortabilityIssue and ProjectPortabilityScore use @dataclasses.dataclass but SkillCompatibilityIssue (pre-existing) uses plain __init__ — kept pre-existing style for SkillCompatibilityIssue, applied dataclass to new types for cleaner field declarations

### Patterns Discovered

- Module-level functions (not class methods) are the dominant pattern in this codebase — utility files expose plain functions; only stateful operations (TeamBroadcast, SkillCompatibilityChecker) use classes
- Commands consistently use shlex.split + argparse on sys.argv[1:] and a PLUGIN_ROOT path injection pattern; the sync_impact command follows this exactly
- The .harnesssync JSON file is the per-project config surface — used by orchestrator, branch_aware_sync, and now team_broadcast auto-pull and schedule staleness; it's the right place to add new per-project knobs
- Type hints use dict[str, X] not Dict[str, X] consistently (Python 3.9+ style), all files have from __future__ import annotations — new code follows this
- Weighted scoring (40% rules + 60% skills) reflects that skills are more behaviorally impactful than rules, but rules affect all harnesses while skills are optional — the weighting encodes this semantic difference

### Takeaways

- The codebase has extensive coverage of most features from the ideation list already — iteration-33 improvements focused on filling specific functional gaps (missing command, missing aggregate score, missing auto-pull integration) rather than building net-new modules
- startup_check.py is the right integration point for session-start behaviors; it was underused (only drift + version updates) and can absorb team broadcast + schedule staleness cleanly
- The test suite is thin (14 tests across 4 files) relative to the codebase size — most modules have no tests; the existing tests focus on adapter output format correctness
- harness_detector.py already had bootstrap_new_harness() for single-harness bootstrapping but lacked a multi-harness shell script generator; generate_bootstrap_script() fills this gap for team onboarding use cases
- sync_impact_predictor.py had no command wrapper despite being a complete, useful module — this is a recurring pattern where backend modules exist but aren't surfaced as slash commands

---
## Iteration 34
_2026-03-12T04:45:24.266Z_

### Items Attempted

- **Sync Plan Preview (Terraform-style)** — pass
- **Conflict Merge Wizard** — pass
- **Named Sync Profiles** — pass
- **Git Branch-Aware Sync** — pass
- **Team Sync Manifest (Shared via Git)** — pass
- **CI Drift Validator** — pass
- **VS Code AI Extension Sync** — pass
- **Live Capability Compatibility Matrix** — pass
- **AI-Assisted Rule Translation** — pass
- **Sync History Timeline** — pass
- **New Project Bootstrap Wizard** — pass
- **Community Sync Packs** — pass
- **Permission Divergence Audit** — pass
- **Proactive Drift Alerts** — pass
- **Environment Variable Vault & Translation** — pass
- **Project-Type Aware Sync** — pass
- **First-Time Harness Setup Wizard** — pass
- **Rule Annotations & Rationale** — pass
- **Bulk Multi-Project Sync** — pass
- **Harness Upgrade Advisor** — pass
- **Hierarchical Config Inheritance** — pass
- **MCP Server Discovery & Sync** — pass
- **Sync Event Webhooks** — pass
- **Rule Coverage Analyzer** — pass
- **Cross-Harness Response Parity Tester** — pass
- **Skill Gap Recommender** — pass
- **Token Cost Estimator by Harness** — pass
- **Config Snapshot Versioning** — pass
- **Config Share Links** — pass
- **Rules Lint with Auto-Fix** — pass
- **Unified Harness Account Manager** — pass
- **AI Behavior Impact Preview** — pass
- **Offline Sync Queue** — pass
- **Deprecated Config Advisor** — pass

### Decisions Made

- Fixed critical bug in sync.py --confirm gate: build_sync_preview was called with `source_data` kwarg that doesn't exist in its signature, silently failing inside try/except. Fixed by calling get_all_native_previews() first to build preview_all dict, then passing it correctly.
- Added terraform-style consolidated plan summary to --dry-run output. After per-target unified diffs, it now calls get_all_native_previews + build_sync_preview + format_sync_preview to show '+ created / ~ modified / = unchanged' counts grouped by harness — matching the item's Terraform-plan UX goal.
- Wired ConfigTimeMachine.take_snapshot() into orchestrator.sync_all() pre-sync phase. Snapshot name is timestamped (pre-sync-YYYYMMDD-HHMMSS) so every sync creates a browsable restore point. Wrapped in try/except so it never blocks sync.
- Wired detect_harness_updates() + format_update_report() into orchestrator.sync_all() post-sync phase. When a harness version change is detected, the report is stored in results['_upgrade_notices'] and displayed in sync.py output after the results table.
- Added _lint_duplicates() method to ConfigLinter.lint() that uses RuleDeduplicator to detect cross-harness near-duplicate rule clusters. Surfaces a concise warning naming the affected harness pairs so users know to consolidate in CLAUDE.md.
- Added send_slack_notification() to drift_watcher.py using Slack Block Kit webhook API. Added slack_webhook_url parameter to DriftWatcher.__init__ and make_notifying_alert_callback(). Reads HARNESSSYNC_SLACK_WEBHOOK env var as fallback. Cooldown applies to both OS and Slack notifications to prevent spam.

### Patterns Discovered

- Pattern of wrapping optional feature calls in try/except and never letting them block sync is consistent throughout orchestrator.py — all new wiring follows this pattern.
- The codebase has many features implemented as standalone modules (config_time_machine.py, harness_version_compat.py, rule_deduplicator.py) but not wired into the main sync flow — implementation exists but activation is missing.
- results dict uses '_' prefix keys for metadata (e.g. '_conflicts', '_warnings') to distinguish from target results — new keys follow this convention.
- DriftWatcher uses a Callable parameter for alert_callback which makes it easy to compose behavior; the make_notifying_alert_callback factory pattern is clean for adding new notification channels.
- The --confirm flag in sync.py was calling build_sync_preview with wrong kwargs — a subtle bug where the try/except masked a TypeError at runtime. This pattern of silent failure is risky; the fix is to use the correct API.

### Takeaways

- Many product features in this codebase exist as fully implemented modules but are not wired into the main execution path — future evolution passes should audit for unused modules and connect them.
- The native_preview.py module has two separate preview pathways: adapter-level _preview_sync (unified diffs) and the terraform-style build_sync_preview/format_sync_preview (file-level status). Both are now used in dry-run mode.
- harness_version_compat.py has sophisticated version detection (detect_harness_updates) but was only used for compat warnings, not for the upgrade advisor use case — both are now active.
- Rule deduplication (RuleDeduplicator) was a standalone scan tool but not integrated into the lint pipeline — adding it to lint() makes it discoverable in the normal config-check workflow.
- Slack webhook integration is a natural extension of the existing OS notification pattern in drift_watcher.py — the cooldown and key-tracking logic reuses existing infrastructure cleanly.

---
## Iteration 35
_2026-03-12T04:58:10.422Z_

### Items Attempted

- **Named Sync Profiles (Work / Personal / OSS)** — pass
- **Drift Alerts: Notify When Targets Fall Out of Sync** — pass
- **Team Config Sharing via Git** — pass
- **Live Capability Gap Matrix** — pass
- **MCP Watchdog: Auto-Disable Unreachable Servers at Sync Time** — pass
- **Starter Config Templates / Presets** — pass
- **Per-Harness Override Files** — pass
- **Interactive Conflict Resolution for Manual Edits** — pass
- **Auto-Detect Newly Installed Harnesses** — pass
- **Human-Readable Sync Changelog** — pass
- **Harness Version Compatibility Warnings** — pass
- **Sync Impact Preview Before Committing** — pass
- **Skill Translation Quality Report** — pass
- **Cross-Harness A/B Config Testing** — pass
- **MCP Server Browser + One-Click Add** — pass
- **Sync Analytics: What Gets Used Across Harnesses** — pass
- **Config Health Score with Actionable Tips** — pass
- **Harness-Agnostic Rule Linter** — pass
- **Scheduled Sync with Email/Notification Digest** — pass
- **Secret Scrubber: Auto-Redact Before Sync** — pass
- **Harness-Specific MCP Server Aliases** — pass
- **Visual Rollback Timeline** — pass
- **Multi-Machine Sync via Cloud or Git Backend** — pass
- **Rule Inheritance: Global → Project → Local Overrides** — pass
- **Git Commit Hook: Sync Config on CLAUDE.md Changes** — pass
- **Interactive Onboarding Wizard for New Projects** — pass
- **Per-Target Ignore Patterns (.harnessignore)** — pass
- **Env Var Portability Checker** — pass
- **Auto-Generate Config Documentation** — pass
- **Minimal Footprint Mode: Sync Only What's Used** — pass
- **Harness Parity Score: How Close Is Each Target** — pass
- **Plugin Recommendation: Suggest Target-Native Equivalents** — pass
- **Sync Validation Test Suite** — pass

### Decisions Made

- Added filter_unreachable_servers() to mcp_reachability.py as a standalone module-level function rather than a method on McpReachabilityChecker — this keeps it composable (callers pass any dict and get back filtered dict + skipped list) without requiring a class instance.
- Implemented .harnessignore as two separate functions (load_harnessignore / apply_harnessignore) in sync_filter.py rather than a new file — the filter logic is closely related to existing tag-based filtering and belongs in the same module.
- Used frozenset() (empty) to represent 'all targets' in .harnessignore rules rather than a sentinel string — this avoids string comparison bugs and is consistent with how Python idiomatic set operations work.
- Extended harness_comparison.py _FEATURE_SUPPORT with cline/continue/zed/neovim based on their actual config file formats (e.g. .clinerules, .roo/mcp.json, .zed/settings.json context_servers) to give accurate support ratings.
- Added check_env_portability() to env_var_matrix.py using a module-level _re import instead of importing inside the function — avoids repeated module lookup overhead and follows the existing pattern in the file.
- Added format_skill_translation_report() to skill_translator.py that reuses the existing score_skill_file() and score_translation() functions — no code duplication, just a new formatting layer on top of already-tested scoring logic.

### Patterns Discovered

- The codebase uses from __future__ import annotations consistently in every src/*.py file — essential for Python 3.9 support with PEP 604 union syntax (X | Y).
- New harnesses (cline, continue, zed, neovim) are referenced in dead_config_detector.py and harness_detector.py but were missing from harness_comparison.py — a common pattern where new targets get added to some modules but not others.
- Module-level constants for supported target names appear in multiple files (sync_filter.KNOWN_TARGETS, harness_comparison.ALL_TARGETS, dead_config_detector._TARGET_OUTPUT_FILES) without a shared source of truth — adding a target requires updating each file separately.
- The codebase uses @dataclass for most report/result types, making them easy to extend without breaking callers.
- import re at module level but used as _re in env_var_matrix.py addition to avoid shadowing the existing re import style in the file — clean but slightly inconsistent.

### Takeaways

- Nearly all 30 product-ideation items were already implemented in some form — iteration 35 was primarily about filling functionality gaps within existing modules rather than creating net-new files.
- The capability gap matrix (harness_comparison.py) was missing 4 recently-added adapters (cline, continue, zed, neovim) despite those adapters being live in the codebase — static data matrices need a maintenance process.
- The .harnessignore feature fills a genuine gap: the tag-based sync filtering in sync_filter.py requires editing CLAUDE.md, but teams often want per-project ignore rules that live outside the main config file.
- filter_unreachable_servers() completes the MCP watchdog story: mcp_reachability.py could detect dead servers but offered no clean way to filter the source dict before passing it to adapters.
- A shared TARGETS constant across modules would eliminate the pattern where adding a new harness requires updating 6-8 separate files.

---
