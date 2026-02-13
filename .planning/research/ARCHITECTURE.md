# Architecture Research

**Domain:** Claude Code Plugin — Multi-Target Configuration Sync
**Researched:** 2026-02-13
**Confidence:** HIGH

## Standard Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    CLAUDE CODE PLUGIN                        │
│                     (HarnessSync)                            │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │   Skills     │  │   Commands   │  │     MCP      │      │
│  │ /sync-status │  │    /sync     │  │   Server     │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                  │                  │              │
│         └──────────────────┼──────────────────┘              │
│                            │                                 │
│                    ┌───────▼────────┐                        │
│                    │  SYNC ENGINE   │                        │
│                    │  (Orchestrator)│                        │
│                    └───────┬────────┘                        │
│                            │                                 │
│         ┌──────────────────┼──────────────────┐              │
│         │                  │                  │              │
│  ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐       │
│  │   Source    │   │    State    │   │   Adapter   │       │
│  │   Reader    │   │   Manager   │   │   Registry  │       │
│  └──────┬──────┘   └──────┬──────┘   └──────┬──────┘       │
│         │                  │                  │              │
└─────────┼──────────────────┼──────────────────┼──────────────┘
          │                  │                  │
          │                  │      ┌───────────┴───────────┐
          │                  │      │                       │
          │                  │  ┌───▼────┐  ┌───▼────┐  ┌──▼──────┐
          │                  │  │ Codex  │  │ Gemini │  │OpenCode │
          │                  │  │Adapter │  │Adapter │  │ Adapter │
          │                  │  └───┬────┘  └───┬────┘  └──┬──────┘
          │                  │      │           │          │
          ▼                  ▼      ▼           ▼          ▼
    ┌─────────┐        ┌─────────────────────────────────────┐
    │ Claude  │        │      Target CLI Configurations      │
    │  Code   │        │   (Codex, Gemini, OpenCode)         │
    │ Config  │        │                                     │
    └─────────┘        └─────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | Typical Implementation |
|-----------|----------------|------------------------|
| **Skills** | Model-invoked capabilities for agent use | `/sync-status` skill (auto-invoke: true) |
| **Commands** | User-invoked slash commands | `/sync` command for manual sync |
| **MCP Server** | Expose sync tools to other Claude agents | MCP tools: `sync_to_target`, `get_sync_status` |
| **Sync Engine** | Orchestrates sync workflow, coordinates components | Core sync loop with scope handling |
| **Source Reader** | Reads Claude Code config (rules, skills, agents, MCP) | Scoped readers: user vs project |
| **State Manager** | Tracks sync state, change detection, last sync time | Hash-based change detection |
| **Adapter Registry** | Manages target adapters, routes sync requests | Pluggable adapter system |
| **Target Adapters** | Format translation, target-specific logic | One per target CLI (Codex, Gemini, OpenCode) |
| **PostToolUse Hook** | Auto-triggers sync on config changes | Watches Write/Edit tools on Claude Code config files |

## Recommended Project Structure

```
harness-sync/
├── .claude-plugin/
│   └── plugin.json              # Plugin manifest
├── commands/
│   └── sync.md                  # Manual sync slash command
├── skills/
│   └── sync-status/
│       └── SKILL.md             # Auto-invoked sync status skill
├── hooks/
│   └── hooks.json               # PostToolUse hook config
├── .mcp.json                    # MCP server for inter-agent sync
├── src/
│   ├── core/
│   │   ├── sync_engine.py       # Main orchestrator
│   │   ├── source_reader.py     # Claude Code config reader
│   │   └── state_manager.py     # State tracking & change detection
│   ├── adapters/
│   │   ├── base.py              # Abstract adapter interface
│   │   ├── registry.py          # Adapter registration & discovery
│   │   ├── codex.py             # Codex adapter
│   │   ├── gemini.py            # Gemini adapter
│   │   └── opencode.py          # OpenCode adapter
│   ├── mcp_server/
│   │   ├── server.py            # MCP server implementation
│   │   └── tools.py             # MCP tool definitions
│   └── utils/
│       ├── paths.py             # Path resolution utilities
│       └── logger.py            # Logging infrastructure
├── scripts/
│   └── post_tool_use.py         # Hook handler script
├── README.md
└── pyproject.toml
```

## Architectural Patterns

### Pattern 1: Adapter Pattern (Target Format Translation)

**What:** Each target CLI has its own adapter implementing a common interface for format translation and sync operations.

**When to use:** When syncing to multiple targets with different configuration formats (TOML vs JSON vs Markdown).

**Trade-offs:**
- **Pros:** Easy to add new targets, isolated logic, testable in isolation
- **Cons:** More files/classes, potential code duplication for similar targets

**Implementation:**
```python
# Abstract adapter interface
class TargetAdapter(ABC):
    @abstractmethod
    def sync_rules(self, rules: str, scope: str, project_dir: Path) -> None: pass

    @abstractmethod
    def sync_skills(self, skills: dict[str, Path], scope: str, project_dir: Path) -> None: pass

    @abstractmethod
    def sync_mcp(self, mcp_servers: dict, scope: str, project_dir: Path) -> None: pass

# Concrete adapter for Codex
class CodexAdapter(TargetAdapter):
    def sync_rules(self, rules: str, scope: str, project_dir: Path) -> None:
        # Codex-specific: rules → AGENTS.md
        target = self._get_target_path("AGENTS.md", scope, project_dir)
        write_text(target, self._format_rules(rules))

    def sync_mcp(self, mcp_servers: dict, scope: str, project_dir: Path) -> None:
        # Codex-specific: MCP → config.toml [mcp_servers] section
        toml_content = self._build_mcp_toml(mcp_servers)
        write_text(self._get_config_toml(scope, project_dir), toml_content)
```

### Pattern 2: Registry Pattern (Extensible Adapter Discovery)

**What:** Central registry dynamically discovers and manages available adapters.

**When to use:** When supporting plugin-style extensibility for adding new targets without modifying core code.

**Trade-offs:**
- **Pros:** Open-closed principle, easy third-party extensions, clean separation
- **Cons:** More indirection, runtime discovery overhead

**Implementation:**
```python
class AdapterRegistry:
    _adapters: dict[str, type[TargetAdapter]] = {}

    @classmethod
    def register(cls, name: str, adapter_class: type[TargetAdapter]) -> None:
        cls._adapters[name] = adapter_class

    @classmethod
    def get_adapter(cls, name: str) -> TargetAdapter:
        if name not in cls._adapters:
            raise ValueError(f"Unknown adapter: {name}")
        return cls._adapters[name]()

    @classmethod
    def list_targets(cls) -> list[str]:
        return list(cls._adapters.keys())

# Registration (can be in adapter __init__.py or via decorators)
AdapterRegistry.register("codex", CodexAdapter)
AdapterRegistry.register("gemini", GeminiAdapter)
AdapterRegistry.register("opencode", OpenCodeAdapter)
```

### Pattern 3: Hook-Based Reactive Sync (Event-Driven)

**What:** PostToolUse hooks detect config file changes and trigger sync automatically.

**When to use:** For seamless "edit Claude Code config, everything else follows" UX without manual intervention.

**Trade-offs:**
- **Pros:** Zero-friction UX, instant feedback, no manual sync needed
- **Cons:** Hook execution overhead, need cooldown logic, debugging complexity

**Implementation:**
```json
// hooks/hooks.json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "jq -r '.tool_input.file_path' | xargs ${CLAUDE_PLUGIN_ROOT}/scripts/post_tool_use.py"
          }
        ]
      }
    ]
  }
}
```

```python
# scripts/post_tool_use.py
import sys
import json
from pathlib import Path

# Read hook context from stdin
hook_input = json.load(sys.stdin)
file_path = Path(hook_input.get("tool_input", {}).get("file_path", ""))

# Trigger sync only for Claude Code config files
if _is_claude_config_file(file_path):
    sync_engine.run_sync(scope="all", cooldown_secs=300)
```

### Pattern 4: Scope-Aware Sync (Multi-Level Configuration)

**What:** Support both user-level (global) and project-level (local) configurations with separate sync paths.

**When to use:** When users need personal settings AND team-shared project settings.

**Trade-offs:**
- **Pros:** Matches Claude Code's native scope system, team collaboration friendly
- **Cons:** More complex state tracking, potential conflicts between scopes

**Implementation:**
```python
class SyncEngine:
    def run_sync(self, scope: str, project_dir: Path = None) -> None:
        if scope in ("user", "all"):
            self._sync_user_scope()

        if scope in ("project", "all") and project_dir:
            self._sync_project_scope(project_dir)

    def _sync_user_scope(self) -> None:
        # User scope: ~/.claude/ → ~/.codex/, ~/.gemini/, ~/.config/opencode/
        rules = source_reader.get_rules("user")
        for target in adapter_registry.list_targets():
            adapter = adapter_registry.get_adapter(target)
            adapter.sync_rules(rules, scope="user", project_dir=None)

    def _sync_project_scope(self, project_dir: Path) -> None:
        # Project scope: .claude/ → .codex/, .gemini/, .opencode/
        rules = source_reader.get_rules("project", project_dir)
        for target in adapter_registry.list_targets():
            adapter = adapter_registry.get_adapter(target)
            adapter.sync_rules(rules, scope="project", project_dir=project_dir)
```

### Pattern 5: Adapter Layer for Settings Drift

**What:** Intermediate translation layer when settings don't map 1:1 between source and target.

**When to use:** When target CLIs have different capability sets or naming conventions for equivalent features.

**Trade-offs:**
- **Pros:** Handles format mismatches, preserves semantic meaning
- **Cons:** Lossy translations possible, requires domain knowledge

**Implementation:**
```python
class GeminiAdapter(TargetAdapter):
    def sync_mcp(self, mcp_servers: dict, scope: str, project_dir: Path) -> None:
        # Gemini uses different format for remote MCP servers
        gemini_mcp = {}
        for name, config in mcp_servers.items():
            if config.get("type") == "url":
                # Translation: url-based → npx mcp-remote wrapper
                gemini_mcp[name] = {
                    "command": "npx",
                    "args": ["-y", "mcp-remote", config.get("url")]
                }
            else:
                # Direct mapping for local servers
                gemini_mcp[name] = {
                    "command": config.get("command"),
                    "args": config.get("args", []),
                    "env": config.get("env", {})
                }

        # Write to Gemini's settings.json format
        target_settings = self._get_settings_json(scope, project_dir)
        settings = read_json(target_settings)
        settings["mcpServers"] = gemini_mcp
        write_json(target_settings, settings)

class CodexAdapter(TargetAdapter):
    def sync_skills(self, skills: dict[str, Path], scope: str, project_dir: Path) -> None:
        # Codex doesn't have agents → convert agents to skills
        # Skills: symlink (efficient, auto-updates)
        # Agents: convert to SKILL.md format (semantic preservation)
        for name, path in skills.items():
            if _is_agent(path):
                self._convert_agent_to_skill(name, path, scope, project_dir)
            else:
                self._symlink_skill(name, path, scope, project_dir)
```

## Data Flow

### Request Flow (Manual Sync)

```
User invokes /sync
    → Command handler parses scope argument
    → SyncEngine.run_sync(scope)
    → SourceReader.get_all_config(scope, project_dir)
        → Returns: {rules, skills, agents, commands, mcp, settings}
    → StateManager.check_changes(config_hash)
        → If unchanged → early return (skip sync)
    → For each registered target adapter:
        → Adapter.sync_all(config, scope, project_dir)
            → Adapter.sync_rules()
            → Adapter.sync_skills()
            → Adapter.sync_mcp()
            → Adapter cleanup_stale_links()
    → StateManager.save_state(config_hash, timestamp)
    → Return summary: {synced: 5, skipped: 2, errors: 0}
```

### Hook Flow (Auto Sync)

```
Claude executes Write tool on .claude/settings.json
    → PostToolUse hook triggers
    → Hook command receives tool context via stdin (JSON)
    → Hook script extracts file_path from JSON
    → If file_path matches Claude Code config pattern:
        → Check cooldown (last_sync + 300s < now?)
        → If cooldown expired:
            → Trigger SyncEngine.run_sync(scope="all")
            → (follows same flow as manual sync above)
        → Else: skip (prevent spam on rapid edits)
```

### MCP Server Flow (Inter-Agent Sync)

```
External agent calls MCP tool: sync_to_target("codex", scope="project")
    → MCP server receives request
    → Validates: target in adapter_registry?
    → Calls: SyncEngine.sync_single_target(target="codex", scope="project")
        → SourceReader.get_all_config(scope, project_dir)
        → Adapter = AdapterRegistry.get_adapter("codex")
        → Adapter.sync_all(config, scope, project_dir)
    → Returns: {success: true, synced_files: [...]}
```

### Key Data Flows

1. **Configuration Discovery Flow:**
   ```
   SourceReader
     → Scan ~/.claude/ (user scope)
     → Scan .claude/ (project scope)
     → Scan plugin cache (installed plugins with skills)
     → Return unified config dict
   ```

2. **Change Detection Flow:**
   ```
   StateManager
     → Hash all source config files
     → Compare with state file hash
     → If match → return "no changes"
     → If diff → return "needs sync" + changed items
   ```

3. **Format Translation Flow:**
   ```
   Source: Claude Code .mcp.json (JSON)
     → CodexAdapter → config.toml TOML [mcp_servers] section
     → GeminiAdapter → settings.json JSON mcpServers key
     → OpenCodeAdapter → opencode.json JSON mcpServers key
   ```

4. **Symlink Strategy Flow:**
   ```
   Skills/Agents in plugin cache
     → Codex: symlink to .codex/skills/{name}
     → OpenCode: symlink to .opencode/skills/{name}
     → Gemini: inline into GEMINI.md (no symlink support)
   Rationale: Symlinks auto-update when /plugin update runs
   ```

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| **3-5 targets** | Current adapter pattern sufficient, registry-based discovery |
| **10+ targets** | Add adapter auto-discovery via entry points, lazy loading |
| **100+ config items** | Incremental sync (only changed items), parallel adapter execution |
| **Team of 50+** | Centralized sync service, webhook-based triggers instead of local hooks |
| **Multi-repo projects** | Workspace-aware sync, aggregate project detection |

## Anti-Patterns

### Anti-Pattern 1: Monolithic Sync Script

**What people do:** Put all sync logic in a single 1000-line script with inline target-specific code.

**Why it's wrong:**
- Adding new targets requires editing core sync logic
- No clear separation of concerns
- Difficult to test individual targets
- Hard to maintain as targets evolve

**Do this instead:** Use adapter pattern with registry for extensibility. Current cc2all-sync.py is a monolith → refactor into modular plugin architecture.

### Anti-Pattern 2: Polling for Changes

**What people do:** Run `while true; do sync; sleep 5; done` to detect changes.

**Why it's wrong:**
- CPU/battery waste
- 5s delay feels sluggish
- Misses rapid consecutive edits
- No native integration with Claude Code

**Do this instead:** Use PostToolUse hooks for event-driven sync. Immediate feedback, zero overhead when idle.

### Anti-Pattern 3: Copy Instead of Symlink

**What people do:** Copy skill directories instead of symlinking.

**Why it's wrong:**
- Duplicate storage
- Out of sync after plugin updates
- Manual re-sync needed
- Violates DRY principle

**Do this instead:** Symlink when target supports it (Codex, OpenCode). Only inline when forced (Gemini).

### Anti-Pattern 4: No State Tracking

**What people do:** Re-sync everything on every trigger without checking what changed.

**Why it's wrong:**
- Unnecessary I/O on unchanged files
- Slow sync times
- Confusing logs (looks like sync happened when nothing changed)

**Do this instead:** Hash-based change detection, skip sync if no changes.

### Anti-Pattern 5: Hardcoded Paths

**What people do:** Assume `~/.claude/` and `~/.codex/` locations.

**Why it's wrong:**
- Breaks on custom installations
- Not portable across environments
- Hard to test

**Do this instead:** Environment variable overrides (`CLAUDE_HOME`, `CODEX_HOME`), fallback to standard locations.

## Component Build Order (Dependencies)

Recommended build order based on component dependencies:

### Phase 1: Core Infrastructure (Foundation)
1. **utils/logger.py** — Logging infrastructure (no dependencies)
2. **utils/paths.py** — Path resolution utilities (no dependencies)
3. **core/state_manager.py** — State tracking (depends on: utils)

### Phase 2: Source Reading (Input Layer)
4. **core/source_reader.py** — Claude Code config reader (depends on: utils)

### Phase 3: Adapter Framework (Extensibility Layer)
5. **adapters/base.py** — Abstract adapter interface (depends on: utils)
6. **adapters/registry.py** — Adapter registration (depends on: base)

### Phase 4: Concrete Adapters (Target Implementations)
7. **adapters/codex.py** — Codex adapter (depends on: base, utils)
8. **adapters/gemini.py** — Gemini adapter (depends on: base, utils)
9. **adapters/opencode.py** — OpenCode adapter (depends on: base, utils)

**Note:** Adapters can be built in parallel — no inter-adapter dependencies.

### Phase 5: Sync Orchestration (Business Logic)
10. **core/sync_engine.py** — Main orchestrator (depends on: source_reader, state_manager, adapter registry)

### Phase 6: Claude Code Plugin Components (User Interface)
11. **commands/sync.md** — Manual sync slash command (depends on: sync_engine)
12. **skills/sync-status/SKILL.md** — Auto-invoked status skill (depends on: sync_engine, state_manager)
13. **hooks/hooks.json** + **scripts/post_tool_use.py** — Auto-sync hook (depends on: sync_engine)

### Phase 7: Inter-Agent Integration (Optional)
14. **mcp_server/tools.py** — MCP tool definitions (depends on: sync_engine)
15. **mcp_server/server.py** — MCP server implementation (depends on: tools)
16. **.mcp.json** — MCP server config (depends on: mcp_server)

**Rationale for ordering:**
- Bottom-up: utilities before consumers
- Interfaces before implementations
- Core logic before user-facing features
- Local features before inter-agent integration

**Critical path:** utils → core (source + state + engine) → adapters → plugin components

**Parallel opportunities:**
- All concrete adapters (Phase 4) can be built in parallel
- Plugin components (Phase 6) can be built in parallel after sync_engine

## Integration Points

### With Claude Code

| Integration Type | Mechanism | Purpose |
|------------------|-----------|---------|
| **Configuration Source** | Read `~/.claude/`, `.claude/` | Discover Claude Code settings |
| **Auto-Trigger** | PostToolUse hook on Write/Edit | React to config changes |
| **User Interface** | Slash command `/sync` | Manual sync control |
| **Agent Interface** | Skill `/sync-status` | Status queries from agents |
| **Plugin System** | `.claude-plugin/plugin.json` | Claude Code plugin packaging |

### With Target CLIs

| Target | Read From | Write To | Format Translation |
|--------|-----------|----------|-------------------|
| **Codex** | `~/.claude/` | `~/.codex/`, `.codex/` | JSON → TOML, Skills → Symlinks, Agents → Skill Conversion |
| **Gemini** | `~/.claude/` | `~/.gemini/`, `GEMINI.md` | All → Markdown Inline, JSON → JSON (mcpServers) |
| **OpenCode** | `~/.claude/` | `~/.config/opencode/`, `.opencode/` | JSON → JSON, Skills → Symlinks |

### With Other Agents (via MCP)

```
External Agent (e.g., deployment agent)
    → Calls MCP tool: sync_to_target("codex", scope="project")
    → HarnessSync plugin processes request
    → Returns: sync status and synced file list
    → Agent proceeds with Codex CLI operations
```

## Sources

**Claude Code Plugin Architecture:**
- [Plugins reference - Claude Code Docs](https://code.claude.com/docs/en/plugins-reference)
- [Create plugins - Claude Code Docs](https://code.claude.com/docs/en/plugins)
- [Claude Code Plugins - GitHub](https://github.com/anthropics/claude-code/blob/main/plugins/README.md)
- [Understanding Claude Code's Full Stack](https://alexop.dev/posts/understanding-claude-code-full-stack/)

**Design Patterns:**
- [Adapter Pattern - Refactoring.Guru](https://refactoring.guru/design-patterns/adapter)
- [Plugin Architecture Design Pattern](https://www.devleader.ca/2023/09/07/plugin-architecture-design-pattern-a-beginners-guide-to-modularity/)
- [Plugin Architecture in Node.js](https://www.n-school.com/plugin-based-architecture-in-node-js/)

**Configuration Sync Architecture:**
- [The End of the Sync Script: Infrastructure as Intent - O'Reilly](https://www.oreilly.com/radar/the-end-of-the-sync-script-infrastructure-as-intent/)

---
*Architecture research for: HarnessSync (Claude Code Plugin — Multi-Target Config Sync)*
*Researched: 2026-02-13*
