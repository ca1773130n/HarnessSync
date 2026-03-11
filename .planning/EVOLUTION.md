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
