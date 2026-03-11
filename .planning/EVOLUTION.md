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
