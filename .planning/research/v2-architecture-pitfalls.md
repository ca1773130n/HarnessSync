# v2.0 Architecture & Pitfalls Research: Plugin & MCP Scope Sync

**Researched:** 2026-02-15
**Domain:** Cross-CLI plugin ecosystem bridging, MCP scope management, multi-level configuration sync
**Confidence:** MEDIUM-HIGH

## Executive Summary

Milestone v2.0 introduces two major architectural challenges beyond v1.0's configuration sync: (1) **plugin capability model mapping** across fundamentally different ecosystems (Claude Code's hooks+skills+commands+agents+MCP vs Gemini's extensions vs Codex's MCP-only), and (2) **MCP scope conflict resolution** when the same server appears at user, project, and local levels with potentially conflicting configurations.

**Key finding:** Unlike v1.0's config-to-config translation (CLAUDE.md → GEMINI.md), v2.0 faces **semantic impedance mismatches** where capabilities don't have direct equivalents. Claude Code plugins bundle hooks (auto-triggers), commands (user-invoked workflows), agents (orchestrators), and MCP servers. Gemini CLI extensions primarily provide commands and skills (with experimental hook support). Codex has no plugin system—only MCP servers. This creates a **capability degradation problem**: syncing a full-featured Claude Code plugin to Gemini loses hooks; syncing to Codex loses everything except MCP.

**Critical insight from research:** The MCP scope precedence model (local > project > user) creates a **deduplication paradox**. If HarnessSync naively syncs `~/.claude/.mcp.json` (user scope) to `~/.codex/config.toml`, but the user also has `.mcp.json` (project scope) with the same server configured differently, which wins? Claude Code's client-side resolution says "project wins," but after sync, Codex only sees the user-level copy. The sync operation **collapses scope hierarchy**, breaking precedence.

**Primary recommendation:** v2.0 must implement (1) **capability degradation tracking** with explicit warnings when features are lost during sync, (2) **scope-aware MCP merging** that preserves precedence semantics in the target CLI, and (3) **version compatibility matrix** in plugin.json to prevent syncing incompatible configurations.

---

## Research Questions Addressed

### 1. Key Challenges in Mapping Plugins Across Different CLI Ecosystems

#### Challenge 1.1: Capability Model Fragmentation

**Finding:** Each CLI has a fundamentally different extension model with non-overlapping capabilities.

**Evidence:**

| Capability | Claude Code Plugin | Gemini CLI Extension | Codex |
|------------|-------------------|---------------------|-------|
| **Hooks** (auto-triggers) | ✅ Full support via `hooks/hooks.json` | ⚠️ Experimental/limited | ❌ Not supported |
| **Commands** (slash commands) | ✅ `.md` files in `commands/` | ✅ Custom commands in extensions | ❌ Not supported |
| **Skills** (LLM-invoked) | ✅ `SKILL.md` in `skills/` | ✅ Skills in extensions | ❌ Not supported |
| **Agents** (orchestrators) | ✅ `@agent-name` invocation | ✅ Via skills/commands | ❌ Not supported |
| **MCP Servers** | ✅ `mcp` section in plugin.json | ✅ MCP support in settings.json | ✅ Only MCP (config.toml) |

**Sources:**
- [Claude Code Plugin System](https://code.claude.com/docs/en/plugins) — Hooks, skills, commands, agents, MCP all first-class
- [Understanding Claude Code's Full Stack](https://alexop.dev/posts/understanding-claude-code-full-stack/) — Comprehensive capability breakdown
- [Gemini CLI vs Claude Code Comparison](https://shipyard.build/blog/claude-code-vs-gemini-cli/) — Gemini lacks comprehensive plugin marketplace
- [Codex CLI Documentation](https://www.educative.io/blog/claude-code-vs-codex-vs-gemini-code-assist) — Codex is MCP-only

**Implication for v2.0:** Syncing must implement **lossy conversion** with explicit reporting. Example: Claude Code plugin with 3 hooks, 2 commands, 1 agent, 2 MCP servers → Gemini gets 2 commands, 1 skill (agent converted), 2 MCP servers. **Lost: 3 hooks**. Codex gets 2 MCP servers. **Lost: everything else**.

**Confidence:** HIGH — Official documentation confirms capability gaps.

---

#### Challenge 1.2: Marketplace Distribution Mismatch

**Finding:** Claude Code has a mature plugin marketplace with versioning; Gemini CLI's extension catalog is curated but less mature; Codex has no plugin system at all.

**Evidence:**
- [Claude Code Plugins vs Gemini Extensions](https://harishgarg.com/claude-code-plugins-vs-gemini-cli-extensions-a-comparison) — "Claude Code integrates with GitHub and supports a plugin system for extending its capabilities... Gemini CLI currently supports Skills for workflows, but lacks a comprehensive plugin system with marketplace like Claude Code has."
- [Gemini Extensions Catalog](https://geminicli.com/extensions/) — Curated list, not a full marketplace

**Implication for v2.0:** Cannot sync plugin *distribution metadata* (marketplace.json). v2.0 should only sync plugin *capabilities* (hooks → commands, MCP servers). Users must manually publish to Gemini's extension catalog if they want distribution.

**Confidence:** MEDIUM — Based on current state (early 2026); Gemini marketplace may mature.

---

#### Challenge 1.3: Plugin Installation Mechanism Differences

**Finding:** Claude Code supports `/plugin install github:user/repo`. Gemini and Codex use different installation patterns.

**Evidence:**
- [How to Build Claude Code Plugins](https://www.datacamp.com/tutorial/how-to-build-claude-code-plugins) — GitHub-based plugin installation
- HarnessSync README (project context) — `/plugin install github:YOUR_USERNAME/HarnessSync`

**Implication for v2.0:** HarnessSync cannot automate cross-CLI plugin *installation*, only *configuration sync*. If a Claude Code plugin depends on binary tools (e.g., MCP server is a Python script), those dependencies must be installed separately in Gemini/Codex environments.

**Confidence:** HIGH — Installation mechanisms confirmed in documentation.

---

### 2. Plugin Capability Model Differences

See Challenge 1.1 table above. Key architectural insight:

**Claude Code's "plugin" is a bundle of heterogeneous capabilities.** A single plugin can provide:
- Pre/post hooks (e.g., auto-formatter on file save)
- Slash commands (user-triggered workflows)
- Skills (LLM-invoked capabilities)
- Agents (multi-step orchestrators)
- MCP servers (external tool access)

**Gemini's "extension" is narrower.** Primarily commands + skills, with experimental hook support.

**Codex has no plugin concept.** Only MCP servers via config.toml.

**Architectural decision required:** v2.0 must answer: "What does it mean to sync a Claude Code plugin to Gemini/Codex?"

**Recommended mapping strategy:**

```
Claude Code Plugin → Gemini Extension:
- Hooks → ⚠️ WARN: "Hooks not supported, skipped"
- Commands → Commands (1:1 mapping, .md file conversion)
- Skills → Skills (1:1 mapping)
- Agents → Skills (convert agent to skill pattern)
- MCP servers → settings.json mcpServers

Claude Code Plugin → Codex:
- Hooks → ⚠️ WARN: "Hooks not supported, skipped"
- Commands → ⚠️ WARN: "Commands not supported, skipped"
- Skills → ⚠️ WARN: "Skills not supported, skipped"
- Agents → ⚠️ WARN: "Agents not supported, skipped"
- MCP servers → config.toml [mcp_servers]
```

**Pitfall Prevention:** Generate `COMPATIBILITY_REPORT.md` after plugin sync showing what was lost. Example:

```markdown
# Plugin Sync Compatibility Report

**Plugin:** HarnessSync
**Source:** Claude Code
**Targets:** Gemini CLI, Codex

## Gemini CLI
- ✅ Synced: 2 commands (/sync, /sync-status)
- ✅ Synced: 2 MCP servers
- ⚠️ Skipped: 1 hook (PostToolUse) — Gemini does not support hooks

## Codex
- ✅ Synced: 2 MCP servers
- ⚠️ Skipped: 2 commands — Codex has no command system
- ⚠️ Skipped: 1 hook — Codex has no hook system
```

**Confidence:** HIGH — Based on official plugin/extension documentation.

---

### 3. Risks of Syncing MCP Servers with Local Paths/Binaries

#### Risk 3.1: Path Portability (Absolute vs Relative)

**Finding:** MCP servers often reference local binaries or scripts via absolute paths, which break when synced to different machines or user accounts.

**Evidence:**
- [MCP Portable Configuration Challenge](https://github.com/modelcontextprotocol/servers/issues/1879) — "MCP configurations must use absolute paths in .vscode/mcp.json, which creates issues with portability across different machines or users and causes problems in team environments."
- [VS Code {workspaceFolder} Variable Request](https://github.com/microsoft/vscode/issues/251263) — Feature request to support variable substitution in MCP paths
- [MCP Path Resolution Problem](https://chrisfrew.in/blog/how-to-manage-multiple-environments-with-mcp/) — "the working directory of this subprocess may not match your development directory, making relative file paths to .env files unreliable."

**Example failure scenario:**

User A's Claude Code config:
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "/Users/alice/.local/bin/mcp-server-filesystem",
      "args": ["/Users/alice/projects"]
    }
  }
}
```

Synced to User B's machine → `/Users/alice/` paths don't exist → MCP server fails to start.

**Implication for v2.0:** HarnessSync must detect absolute paths and either:
1. **Reject sync** with error: "MCP server 'filesystem' uses absolute path. Use ${HOME} or ${workspaceFolder} variables."
2. **Transform paths** during sync (e.g., replace `/Users/alice/` with `${HOME}/`).
3. **Warn user** and sync as-is, noting it will likely fail on other machines.

**Recommended approach:** Option 1 (reject) is safest. v2.0 should validate MCP server paths and block sync if:
- `command` or `args` contain absolute paths without variables
- Path contains user-specific segments (`/Users/alice`, `C:\Users\bob`)

**Allowed patterns:**
- `${HOME}/.local/bin/mcp-server`
- `${workspaceFolder}/scripts/mcp.py`
- `npx @modelcontextprotocol/server-filesystem` (package manager, portable)

**Confidence:** HIGH — Path portability is well-documented MCP pain point.

---

#### Risk 3.2: Binary Dependency Mismatch

**Finding:** MCP servers are executables (Python scripts, Node.js packages, compiled binaries). Syncing config doesn't sync the binary itself.

**Evidence:**
- [MCP Server Configuration Best Practices](https://www.stainless.com/mcp/mcp-server-configuration-best-practices) — MCP servers must be installed separately
- HarnessSync v1.0 implementation — Syncs `.mcp.json` config, not MCP server code

**Example failure scenario:**

User A installs MCP server: `pip install --user mcp-server-postgres`

Claude Code config references: `~/.local/bin/mcp-server-postgres`

HarnessSync syncs config to Gemini CLI on User A's machine → works (binary exists).

HarnessSync syncs config to Codex on **another machine** → fails (binary not installed).

**Implication for v2.0:** MCP server sync is **config-only**. v2.0 must:
1. **Document** that users must install MCP server binaries on all target systems
2. **Validate** at sync time that referenced binaries exist (warn if missing)
3. **Provide** installation hints in compatibility report

**Recommended validation:**

```python
def validate_mcp_server(server_config):
    command = server_config.get("command")
    if not command:
        return "ERROR: Missing 'command' field"

    # If command is a path (not npx/package manager)
    if "/" in command or "\\" in command:
        # Check if it uses variables
        if not ("${HOME}" in command or "${workspaceFolder}" in command):
            # Check if binary exists
            command_path = Path(command).expanduser()
            if not command_path.exists():
                return f"WARNING: Binary not found: {command}"

    return None  # Valid
```

**Confidence:** HIGH — Binary dependency management is standard DevOps practice.

---

#### Risk 3.3: Security — Syncing MCP Servers with Elevated Permissions

**Finding:** MCP servers run with user account permissions and can access sensitive files/APIs. Syncing an MCP server config from one context (e.g., personal laptop) to another (e.g., work machine) may grant unintended access.

**Evidence:**
- [MCP Security Considerations](https://modelcontextprotocol.io/docs/develop/connect-local-servers) — "Only grant access to directories you're comfortable with Claude reading and modifying, as the server runs with your user account permissions."
- [Claude Code Sandbox Guide](https://claudefa.st/blog/guide/sandboxing-guide) — OS-level enforcement restricts filesystem/network access
- HarnessSync v1.0 decision log (STATE.md #30) — "Conservative sandbox mapping — ANY denied tool -> read-only sandbox mode"

**Example security risk:**

Personal machine MCP config:
```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx @modelcontextprotocol/server-filesystem",
      "args": ["${HOME}"]  // Full home directory access
    }
  }
}
```

Synced to work machine → Now work Claude Code has full access to work home directory (may contain SSH keys, company credentials, confidential docs).

**Implication for v2.0:** HarnessSync should **never auto-sync MCP servers with dangerous permissions**. Implement safeguards:

1. **Scope-based MCP filtering:** Only sync MCP servers from project scope (`.mcp.json` in project dir), NOT user scope (`~/.claude/.mcp.json`). Rationale: Project-scoped servers are intentionally shared; user-scoped servers are personal.

2. **Permission audit:** Scan MCP server args for dangerous patterns:
   - `${HOME}` without subdirectory → BLOCK
   - Absolute paths to system directories (`/etc`, `C:\Windows`) → BLOCK
   - Network permissions (if detectable) → WARN

3. **Explicit opt-in:** Add `--sync-user-mcp` flag to allow syncing user-scoped MCP servers, disabled by default.

**Recommended policy:**

```
Default behavior (v2.0):
- ✅ Sync project-scoped MCP servers (.mcp.json in project)
- ❌ Skip user-scoped MCP servers (~/.claude/.mcp.json)
- ⚠️ Warn if skipped: "User-scoped MCP servers not synced (security). Use --sync-user-mcp to override."

With --sync-user-mcp flag:
- ✅ Sync all MCP servers
- ⚠️ Audit for dangerous permissions (${HOME}, system paths)
- ❌ Block if dangerous pattern detected (override with --allow-dangerous-mcp)
```

**Confidence:** HIGH — Security isolation is documented MCP best practice.

---

### 4. Scope Conflict Handling (User-Level vs Project-Level MCP)

#### Core Problem: MCP Scope Precedence Collapse

**Finding:** Claude Code resolves MCP servers using precedence: **local > project > user**. When HarnessSync syncs these scopes to targets, the precedence hierarchy collapses because targets see a flat merged config.

**Evidence:**
- [MCP Scope Precedence](https://modelcontextprotocol.io/docs/develop/connect-local-servers) — "Local-scoped servers first, followed by project-scoped servers, and finally user-scoped servers."
- [Claude Code Settings Precedence](https://code.claude.com/docs/en/settings) — "Project settings take precedence... if a permission is allowed in user settings but denied in project settings, the project setting takes precedence and the permission is blocked."
- HarnessSync v1.0 SourceReader implementation (source_reader.py lines 42-53) — Reads both user scope (`cc_home`) and project scope

**Example conflict scenario:**

**User scope** (`~/.claude/.mcp.json`):
```json
{
  "mcpServers": {
    "github": {
      "command": "npx @modelcontextprotocol/server-github",
      "env": {
        "GITHUB_TOKEN": "${GITHUB_PERSONAL_TOKEN}"
      }
    }
  }
}
```

**Project scope** (`.mcp.json`):
```json
{
  "mcpServers": {
    "github": {
      "command": "npx @modelcontextprotocol/server-github",
      "env": {
        "GITHUB_TOKEN": "${GITHUB_WORK_TOKEN}"
      }
    }
  }
}
```

**Claude Code behavior:** Project scope wins → uses `${GITHUB_WORK_TOKEN}`.

**Current HarnessSync v1.0 sync behavior (from source_reader.py):**
1. Read user-scoped `.mcp.json` → `{"github": {...GITHUB_PERSONAL_TOKEN...}}`
2. Read project-scoped `.mcp.json` → `{"github": {...GITHUB_WORK_TOKEN...}}`
3. SourceReader returns **merged** config (project scope likely overwrites user scope in current implementation)
4. Sync merged config to Codex `config.toml` → **Both scopes collapsed into one**

**Post-sync Codex behavior:** Sees only one `github` server (whichever won the merge). **Precedence lost.**

**Implication for v2.0:** Need **scope-aware MCP syncing** that preserves precedence in targets.

---

#### Solution 4.1: Scope-Preserving Sync

**Recommended approach:** Sync each scope separately to equivalent target scope.

**Mapping:**

| Claude Code Scope | Codex Target | Gemini Target | OpenCode Target |
|-------------------|--------------|---------------|----------------|
| User (`~/.claude/.mcp.json`) | `~/.codex/config.toml` | `~/.gemini/settings.json` | `~/.config/opencode/opencode.json` |
| Project (`.mcp.json`) | `./.codex/config.toml` | `./.gemini/settings.json` | `./.opencode/opencode.json` |
| Local (`~/.claude.json` under project path) | ❌ Claude-specific, don't sync | ❌ Claude-specific, don't sync | ❌ Claude-specific, don't sync |

**Rationale:**
- User-to-user sync preserves cross-project MCP servers
- Project-to-project sync preserves project-specific MCP servers
- Local scope is Claude Code-specific (`.claude.json` is a Claude convention), don't sync

**Implementation change required:**

Current v1.0 SourceReader merges scopes. v2.0 must:

```python
class SourceReaderV2:
    def get_mcp_servers_by_scope(self) -> dict[str, list]:
        """
        Return MCP servers grouped by scope.

        Returns:
            {
                "user": [{"name": "github", "config": {...}}, ...],
                "project": [{"name": "local-fs", "config": {...}}, ...]
            }
        """
        # Separate parsing for user vs project scopes
        # Do NOT merge
```

Then adapters sync each scope separately:

```python
class CodexAdapterV2:
    def sync_mcp_servers(self, mcp_by_scope: dict[str, list]) -> SyncResult:
        # User scope → ~/.codex/config.toml
        self._sync_to_user_config(mcp_by_scope["user"])

        # Project scope → ./.codex/config.toml
        self._sync_to_project_config(mcp_by_scope["project"])
```

**Confidence:** MEDIUM — Requires architectural change to v1.0's merged approach. No direct precedent found in other sync tools.

---

#### Solution 4.2: Conflict Detection and User Prompt

**Alternative approach:** If the same MCP server appears in multiple scopes with different configs, prompt user to resolve.

**Example conflict report:**

```
⚠️  MCP Server Conflict Detected

Server: "github"
- User scope: env.GITHUB_TOKEN = ${GITHUB_PERSONAL_TOKEN}
- Project scope: env.GITHUB_TOKEN = ${GITHUB_WORK_TOKEN}

Claude Code will use project scope (precedence: project > user).

How should HarnessSync sync to Codex/Gemini?
[1] Sync both scopes separately (recommended)
[2] Sync project scope only (match Claude behavior)
[3] Skip syncing this server (manual config)

Choice:
```

**Confidence:** MEDIUM — User prompt adds complexity but provides flexibility.

---

### 5. Deduplication Strategies (Same MCP Server at Multiple Scopes)

#### Strategy 5.1: No Deduplication (Scope Preservation)

**Recommendation:** Don't deduplicate. Sync each scope as-is to preserve precedence hierarchy.

**Rationale:** If the same server appears at user and project scopes, that's intentional. User scope provides a default; project scope overrides it. Deduplicating would break this pattern.

**Example:**

User scope: `github` server with personal token
Project scope: `github` server with work token

**After sync to Codex:**
- `~/.codex/config.toml` has `github` with personal token
- `./.codex/config.toml` has `github` with work token

**Codex behavior:** Project-scoped config.toml is read after user-scoped, so work token wins (mimics Claude Code precedence).

**Confidence:** HIGH — Preserves semantic intent.

---

#### Strategy 5.2: Deduplication with Conflict Merging

**Alternative:** If same server in multiple scopes, merge configs using "most specific wins" strategy.

**Merge rules:**
1. Server name identical → merge
2. Field-level precedence: project > user
3. Merged config synced to **user scope only** in target

**Example:**

User scope:
```json
{
  "github": {
    "command": "npx @modelcontextprotocol/server-github",
    "env": {"GITHUB_TOKEN": "${PERSONAL}"}
  }
}
```

Project scope:
```json
{
  "github": {
    "env": {"GITHUB_TOKEN": "${WORK}"}
  }
}
```

**Merged:**
```json
{
  "github": {
    "command": "npx @modelcontextprotocol/server-github",  // from user
    "env": {"GITHUB_TOKEN": "${WORK}"}  // from project (overrides)
  }
}
```

**Synced to:** `~/.codex/config.toml` (user scope in target).

**Confidence:** LOW — This loses scope separation. Not recommended.

---

#### Strategy 5.3: Hash-Based Deduplication (Exact Match Only)

**Recommendation for partial implementation:** If server configs are **byte-for-byte identical** across scopes, sync to user scope only (avoid redundant copies).

**Detection:**

```python
import hashlib
import json

def hash_mcp_config(config: dict) -> str:
    """Hash MCP server config for deduplication."""
    # Normalize config (sorted keys, no whitespace)
    normalized = json.dumps(config, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(normalized.encode()).hexdigest()

def deduplicate_identical_servers(mcp_by_scope: dict[str, list]) -> dict[str, list]:
    """Remove exact duplicates across scopes."""
    user_hashes = {hash_mcp_config(s["config"]): s for s in mcp_by_scope["user"]}
    project_servers = mcp_by_scope["project"]

    deduplicated_project = []
    for server in project_servers:
        server_hash = hash_mcp_config(server["config"])
        if server_hash not in user_hashes:
            deduplicated_project.append(server)
        # else: identical to user scope, skip in project scope

    return {
        "user": mcp_by_scope["user"],
        "project": deduplicated_project
    }
```

**Use case:** User installs MCP server globally, then accidentally adds to project config with identical settings. Deduplication prevents double-syncing.

**Confidence:** MEDIUM — Safe for exact matches, but may miss subtle differences (comment changes, whitespace).

---

### 6. Plugin Versioning Considerations

#### Challenge 6.1: Semantic Versioning Enforcement

**Finding:** Claude Code plugins use semantic versioning (`"version": "1.0.0"` in plugin.json), but there's no enforced compatibility contract.

**Evidence:**
- [Semantic Versioning 2.0.0](https://semver.org/) — "Given a version number MAJOR.MINOR.PATCH, increment the MAJOR version when you make incompatible API changes"
- [Claude Code Plugin Structure](https://deepwiki.com/anthropics/claude-plugins-official/5.1-plugin-structure-and-manifest) — plugin.json includes "version" field
- [Plugin Versioning Best Practices](https://developer.hashicorp.com/terraform/plugin/best-practices/versioning) — "document the offending version and inform your users of the problem"

**Problem:** HarnessSync plugin.json declares `"version": "1.0.0"`. If v2.0 introduces breaking changes (e.g., new MCP scope-aware sync that's incompatible with v1.0 state files), users syncing from v1.0 to v2.0 may experience failures.

**Implication for v2.0:** Must implement **version migration** in StateManager.

**Recommended approach:**

```python
# src/state_manager.py

STATE_FORMAT_VERSION = 2  # v2.0 introduces scope-aware MCP tracking

def load_state(state_path: Path) -> dict:
    """Load state with version migration."""
    state = read_json_safe(state_path)

    current_version = state.get("format_version", 1)

    if current_version < STATE_FORMAT_VERSION:
        # Migrate from v1 to v2
        state = migrate_v1_to_v2(state)

    return state

def migrate_v1_to_v2(state_v1: dict) -> dict:
    """
    Migrate v1.0 state (flat MCP list) to v2.0 (scoped MCP).

    v1 format:
        {"targets": {"codex": {"mcp_servers": ["github", "filesystem"]}}}

    v2 format:
        {"targets": {"codex": {"mcp_servers": {"user": ["github"], "project": ["filesystem"]}}}}
    """
    # Default: assume all v1 MCP servers were user-scoped
    state_v2 = state_v1.copy()
    state_v2["format_version"] = 2

    for target in state_v2.get("targets", {}).values():
        if "mcp_servers" in target and isinstance(target["mcp_servers"], list):
            # Convert list to scope dict
            target["mcp_servers"] = {
                "user": target["mcp_servers"],
                "project": []
            }

    return state_v2
```

**Confidence:** HIGH — State format migration is standard practice (see HarnessSync v1.1 Phase 8 multi-account migration).

---

#### Challenge 6.2: Cross-CLI Version Compatibility

**Finding:** Gemini CLI and Codex evolve independently. A feature available in Claude Code today may not be available in Gemini/Codex, or vice versa.

**Example:** Claude Code adds a new MCP feature (e.g., "resources" in MCP 2.0 spec). HarnessSync syncs MCP servers using resources. Gemini CLI doesn't support resources yet → sync succeeds, but feature doesn't work.

**Implication for v2.0:** Need **feature compatibility matrix** tracked per target.

**Recommended implementation:**

```python
# src/utils/compatibility.py

FEATURE_SUPPORT = {
    "claude": {
        "mcp_tools": True,
        "mcp_resources": True,  # Hypothetical MCP 2.0 feature
        "mcp_prompts": True,
        "hooks": True,
        "commands": True,
        "skills": True,
        "agents": True,
    },
    "gemini": {
        "mcp_tools": True,
        "mcp_resources": False,  # Not supported yet
        "mcp_prompts": True,
        "hooks": False,
        "commands": True,
        "skills": True,
        "agents": False,
    },
    "codex": {
        "mcp_tools": True,
        "mcp_resources": False,
        "mcp_prompts": False,
        "hooks": False,
        "commands": False,
        "skills": False,
        "agents": False,
    },
}

def check_feature_support(target: str, feature: str) -> bool:
    """Check if target CLI supports a feature."""
    return FEATURE_SUPPORT.get(target, {}).get(feature, False)

def warn_unsupported_features(plugin_capabilities: dict, target: str) -> list[str]:
    """Generate warnings for unsupported features."""
    warnings = []

    for capability, enabled in plugin_capabilities.items():
        if enabled and not check_feature_support(target, capability):
            warnings.append(
                f"Feature '{capability}' not supported by {target} (will be skipped)"
            )

    return warnings
```

**Confidence:** MEDIUM — Requires ongoing maintenance as CLIs evolve.

---

#### Challenge 6.3: Plugin Dependency Version Pinning

**Finding:** If a Claude Code plugin depends on an MCP server package (e.g., `npx @modelcontextprotocol/server-filesystem`), the package version may vary across installs.

**Example:**

Developer's machine: `@modelcontextprotocol/server-filesystem@1.2.0`
User's machine (after sync): `@modelcontextprotocol/server-filesystem@1.0.0` (older version cached)

Plugin expects 1.2.0 API → fails on user's 1.0.0 installation.

**Implication for v2.0:** HarnessSync cannot enforce version pinning (would require package manager integration). **Document limitation.**

**Recommended documentation (for plugin authors):**

```markdown
## v2.0 Plugin Sync Limitations

### MCP Server Version Pinning

HarnessSync syncs MCP server **configurations**, not the MCP server binaries themselves.

If your plugin depends on a specific MCP server version:
1. Document the version requirement in plugin README
2. Use package.json to pin versions: `"@modelcontextprotocol/server-filesystem": "^1.2.0"`
3. Instruct users to run `npm install` in plugin directory before syncing

HarnessSync will NOT:
- Install MCP server packages
- Verify MCP server versions
- Pin package versions during sync
```

**Confidence:** HIGH — Package version management is outside sync tool's scope.

---

### 7. Security Considerations (Plugin Permissions, MCP Server Access)

#### Security 7.1: Permission Inheritance During Sync

**Finding:** Claude Code has fine-grained tool permissions (allow/deny per tool). When syncing to Gemini/Codex, permission models differ.

**Evidence:**
- HarnessSync v1.0 decision log (#30, #33) — "Conservative sandbox mapping," "Never auto-enable yolo mode"
- [Claude Code Sandbox Security](https://claudefa.st/blog/guide/sandboxing-guide) — OS-level filesystem restrictions
- [Managing Permissions in Claude Code](https://inventivehq.com/knowledge-base/claude/how-to-manage-permissions-and-sandboxing)

**Current v1.0 behavior (from STATE.md):**
- Claude "deny" → skip tool entirely in Gemini/Codex
- Never downgrade "deny" to "allow"
- Gemini yolo mode never auto-enabled

**v2.0 challenge:** Plugins may bundle MCP servers with **inherent permissions** (e.g., filesystem server grants file access). Syncing the plugin syncs the permission grant.

**Example risk:**

Claude Code plugin.json:
```json
{
  "mcp": {
    "server": "src/mcp/server.py",
    "tools": ["read_file", "write_file", "execute_command"]
  }
}
```

User syncs plugin to Gemini → Gemini now has `execute_command` tool via MCP.

**If user's Claude Code has `execute_command` denied,** but the MCP server still exposes it, **permission bypass**.

**Implication for v2.0:** MCP server permissions are **client-side** (Claude Code enforces), but the server capabilities are **server-side** (server declares tools). Syncing MCP server config to Gemini doesn't sync Claude's permission denials.

**Recommended approach:**

1. **Audit plugin MCP servers** for dangerous tools before syncing.
2. **Warn user** if plugin MCP exposes high-risk tools:
   - File write (`write_file`, `delete_file`)
   - Command execution (`execute_command`, `run_script`)
   - Network access (`http_request`, `send_email`)

**Implementation:**

```python
DANGEROUS_TOOL_PATTERNS = [
    "write", "delete", "remove", "execute", "run", "eval",
    "http", "network", "send", "upload"
]

def audit_mcp_tools(mcp_tools: list[str]) -> list[str]:
    """Identify dangerous tools in MCP server."""
    dangerous = []
    for tool in mcp_tools:
        if any(pattern in tool.lower() for pattern in DANGEROUS_TOOL_PATTERNS):
            dangerous.append(tool)
    return dangerous

def sync_plugin_with_security_check(plugin_manifest: dict):
    """Sync plugin with security audit."""
    mcp_tools = plugin_manifest.get("mcp", {}).get("tools", [])
    dangerous_tools = audit_mcp_tools(mcp_tools)

    if dangerous_tools:
        print(f"⚠️  WARNING: Plugin exposes potentially dangerous MCP tools:")
        for tool in dangerous_tools:
            print(f"   - {tool}")
        print(f"   Target CLIs may not enforce Claude Code's permission denials.")
        print(f"   Review {plugin_manifest['name']} before syncing.")

        response = input("Continue sync? [y/N]: ")
        if response.lower() != 'y':
            raise SyncAborted("User cancelled due to security warning")
```

**Confidence:** HIGH — Permission model mismatch is a real security gap.

---

#### Security 7.2: Credential Exposure via MCP Environment Variables

**Finding:** MCP servers use `env` field for credentials (API tokens, passwords). Syncing these to targets may expose secrets.

**Evidence:**
- [MCP Environment Variables](https://apxml.com/courses/getting-started-model-context-protocol/chapter-4-debugging-and-client-integration/managing-environment-variables) — MCP configs include `env` object with variable mappings
- [MCP Secrets Handling Problem](https://0xhagen.medium.com/mcp-configuration-is-a-sh-tshow-but-heres-how-i-fixed-secrets-handling-5395010762a1) — "MCP configuration is a sh*tshow"
- HarnessSync v1.0 SecretDetector (Phase 5) — Scans environment variables for secrets

**Example exposure:**

Claude Code `.mcp.json`:
```json
{
  "mcpServers": {
    "github": {
      "command": "npx @modelcontextprotocol/server-github",
      "env": {
        "GITHUB_TOKEN": "ghp_1234567890abcdef"  // Hardcoded token (bad practice)
      }
    }
  }
}
```

HarnessSync syncs to Gemini `settings.json` → Token now in plaintext in `~/.gemini/settings.json`.

**v1.0 mitigation (from Phase 5):** SecretDetector scans env vars, blocks sync if secrets detected.

**v2.0 enhancement required:** Extend SecretDetector to scan **MCP `env` fields**.

**Recommended implementation:**

```python
# Extend src/safety/secret_detector.py

def scan_mcp_env(mcp_servers: dict[str, dict]) -> list[str]:
    """Scan MCP server env vars for secrets."""
    detected_secrets = []

    for server_name, server_config in mcp_servers.items():
        env_vars = server_config.get("env", {})

        for var_name, var_value in env_vars.items():
            # Check if value is a reference (${VAR}) or literal
            if var_value.startswith("${") and var_value.endswith("}"):
                # Variable reference, safe (expanded at runtime)
                continue

            # Literal value, scan for secrets
            if is_secret(var_name, var_value):
                detected_secrets.append(f"MCP server '{server_name}': {var_name}")

    return detected_secrets
```

**Best practice recommendation for users:**

```markdown
## MCP Security Best Practices

**DO:**
- Use environment variable references: `"GITHUB_TOKEN": "${GITHUB_TOKEN}"`
- Store tokens in shell profile (.bashrc, .zshrc)
- Use secret management tools (1Password, Vault)

**DON'T:**
- Hardcode tokens in .mcp.json: `"GITHUB_TOKEN": "ghp_abc123"` ❌
- Commit .mcp.json with secrets to version control ❌
```

**Confidence:** HIGH — Secret detection is already implemented in v1.0, just needs MCP extension.

---

### Best Practices for Plugin/Extension Ecosystem Bridging

Based on research findings, here are recommended best practices:

#### Practice 1: Explicit Capability Mapping Declaration

**What:** Plugin manifest should declare which capabilities are synced to which targets.

**Implementation:** Add `sync_targets` field to plugin.json:

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "sync_targets": {
    "gemini": {
      "capabilities": ["commands", "skills", "mcp"],
      "excluded_capabilities": ["hooks"],
      "compatibility_note": "Hooks are not supported by Gemini CLI"
    },
    "codex": {
      "capabilities": ["mcp"],
      "excluded_capabilities": ["hooks", "commands", "skills"],
      "compatibility_note": "Codex only supports MCP servers"
    }
  }
}
```

**Benefit:** Users see what will be synced before installing plugin.

**Confidence:** MEDIUM — Not a standard pattern, but improves transparency.

---

#### Practice 2: Scope-Aware Configuration Management

**What:** Don't mix user and project scopes in a single config file. Keep them separate.

**Evidence:**
- [VS Code Settings Sync Limitation](https://code.visualstudio.com/docs/configure/settings-sync) — "VS Code does not synchronize your extensions to or from a remote window, such as when you're connected to SSH"
- [JetBrains Settings Sync](https://blog.jetbrains.com/idea/2022/10/intellij-idea-2022-3-eap-3/) — "plugins themselves will be synchronized and installed silently"

**Recommendation:** HarnessSync v2.0 should maintain separate state tracking for user vs project scopes:

```python
# State format v2
{
  "format_version": 2,
  "scopes": {
    "user": {
      "targets": {
        "codex": {"synced_files": [...], "file_hashes": {...}},
        "gemini": {...}
      }
    },
    "project": {
      "targets": {
        "codex": {"synced_files": [...], "file_hashes": {...}},
        "gemini": {...}
      }
    }
  }
}
```

**Benefit:** Clear separation enables scope-preserving sync (Solution 4.1).

**Confidence:** MEDIUM — Requires state format change from v1.0.

---

#### Practice 3: Incremental Sync with Diff Detection

**What:** Only sync changed files, not entire config every time.

**Evidence:**
- HarnessSync v1.0 StateManager (from STATE.md) — SHA256 file hashing for drift detection
- [Database Deduplication](https://www.onehouse.ai/blog/data-deduplication-strategies-in-an-open-lakehouse-architecture) — "eliminating duplicates at multiple stages of the data lifecycle"

**Current v1.0 behavior:** Hashes all source files, compares to state, only writes if changed.

**v2.0 enhancement:** Extend to plugin manifest changes. If plugin.json version unchanged, skip re-syncing plugin capabilities.

**Implementation:**

```python
def sync_plugin(plugin_manifest_path: Path):
    """Sync plugin if manifest changed."""
    manifest_hash = hash_file(plugin_manifest_path)

    state = load_state()
    last_hash = state.get("plugin_manifest_hash")

    if manifest_hash == last_hash:
        print(f"Plugin manifest unchanged, skipping sync")
        return

    # Manifest changed, proceed with sync
    sync_plugin_capabilities(plugin_manifest_path)

    # Update state
    state["plugin_manifest_hash"] = manifest_hash
    save_state(state)
```

**Benefit:** Avoid redundant syncs, faster for no-op calls.

**Confidence:** HIGH — Already implemented pattern in v1.0.

---

#### Practice 4: Idempotent Sync Operations

**What:** Running sync multiple times produces the same result. No partial states.

**Evidence:**
- [Transaction Atomicity](https://www.datacamp.com/tutorial/atomicity) — "whole transaction completes or none of it does"
- HarnessSync v1.0 decision #9 — "Atomic write pattern for state — Tempfile + os.replace prevents corruption"

**Current v1.0 behavior:** Atomic file writes via tempfile + os.replace.

**v2.0 requirement:** Extend to multi-scope sync. If project scope sync fails, rollback user scope sync.

**Recommended pattern:**

```python
def sync_all_scopes():
    """Sync user and project scopes atomically."""
    # Create transaction log
    transaction = []

    try:
        # Sync user scope
        user_result = sync_user_scope()
        transaction.append(("user", user_result))

        # Sync project scope
        project_result = sync_project_scope()
        transaction.append(("project", project_result))

        # Commit transaction (update state)
        commit_sync_transaction(transaction)

    except Exception as e:
        # Rollback all changes
        rollback_sync_transaction(transaction)
        raise
```

**Confidence:** HIGH — Transaction pattern is standard for multi-step operations.

---

### How Similar Tools Handle Multi-Scope Configuration Merging

Research findings from IDE sync tools:

#### VSCode Settings Sync

**Approach:** Syncs settings at **user level only**. Workspace (project) settings are explicitly excluded from sync.

**Rationale:** Workspace settings are team-shared via version control. Syncing them across machines would conflict with team settings.

**Relevance to HarnessSync:** Supports **not syncing project-scoped configs** by default. Only sync user scope, let version control handle project scope.

**Source:** [VS Code Settings Sync](https://code.visualstudio.com/docs/configure/settings-sync)

**Confidence:** HIGH — Official VSCode documentation.

---

#### JetBrains Settings Sync

**Approach:** Syncs both user and project settings, but **project settings are per-IDE**, not cross-IDE.

**Quote:** "it is not possible to synchronize settings between different IDEs using Settings Sync"

**Relevance to HarnessSync:** Reinforces that cross-platform sync is hard. Don't try to sync project settings across different CLI tools (Claude Code project config → Gemini project config may not make sense).

**Source:** [JetBrains Settings Sync](https://intellij-support.jetbrains.com/hc/en-us/community/posts/8242369107090)

**Confidence:** HIGH — Official JetBrains support response.

---

#### Git Configuration Precedence

**Approach:** Git uses **system > global > local** precedence for config. `git config --list --show-scope` displays which scope each setting came from.

**Command:** `git config --list --show-scope`

**Output example:**
```
global  user.name=Alice
local   user.email=alice@work.com
```

**Relevance to HarnessSync:** v2.0 could add `harnesssync status --show-scope` to display where each config came from (user vs project).

**Confidence:** HIGH — Git is well-established precedence model.

---

### Rollback Strategies for Plugin Sync Failures

#### Rollback Strategy 1: Backup-Before-Sync (Current v1.0 Approach)

**What:** Before syncing, backup all target files. If sync fails, restore from backup.

**Evidence:**
- HarnessSync v1.0 BackupManager (Phase 5) — Creates timestamped backups before sync
- [Database Rollback Strategies](https://www.harness.io/harness-devops-academy/database-rollback-strategies-in-devops) — "Point-in-time recovery involves taking regular backups"

**Current v1.0 implementation (from STATE.md):**
- BackupManager creates `~/.harnesssync/backups/{target}/{timestamp}/` with pre-sync state
- If sync fails, SyncOrchestrator restores from backup

**v2.0 requirement:** Extend to plugin sync. Backup plugin-installed files (commands, skills, MCP server configs) before syncing new plugin version.

**Recommended enhancement:**

```python
def backup_plugin_state(target: str) -> Path:
    """Backup current plugin state before syncing."""
    timestamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    backup_dir = Path.home() / ".harnesssync" / "backups" / target / "plugin" / timestamp

    # Backup all plugin-installed files
    files_to_backup = [
        "commands/",
        "skills/",
        "agents/",
        ".mcp.json",
        "plugin.json"
    ]

    for file_path in files_to_backup:
        src = get_target_path(target) / file_path
        if src.exists():
            dst = backup_dir / file_path
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)

    return backup_dir
```

**Confidence:** HIGH — Already implemented pattern in v1.0.

---

#### Rollback Strategy 2: Transaction Log with Compensating Actions

**What:** Log each sync operation. If failure occurs, execute inverse operations to undo.

**Evidence:**
- [Microservices Rollback](https://daily.dev/blog/microservices-rollback-ensuring-data-consistency) — "implement compensating transactions to reverse actions if things fail"
- [Transaction Rollback](https://www.tencentcloud.com/techpedia/132683) — "database system reverts all modifications performed during that transaction"

**Example transaction log:**

```json
{
  "transaction_id": "sync-20260215-143022",
  "operations": [
    {"action": "write_file", "path": "~/.codex/AGENTS.md", "backup": "~/.harnesssync/backups/..."},
    {"action": "create_symlink", "src": "~/.claude/skills/python-analyzer", "dst": "~/.codex/skills/python-analyzer"},
    {"action": "update_mcp", "target": "codex", "server": "github", "backup": "~/.harnesssync/backups/..."}
  ],
  "status": "in_progress"
}
```

**Rollback process:**

```python
def rollback_transaction(transaction_log: dict):
    """Rollback sync transaction."""
    for operation in reversed(transaction_log["operations"]):
        if operation["action"] == "write_file":
            # Restore from backup
            shutil.copy2(operation["backup"], operation["path"])
        elif operation["action"] == "create_symlink":
            # Remove symlink
            Path(operation["dst"]).unlink(missing_ok=True)
        elif operation["action"] == "update_mcp":
            # Restore MCP config from backup
            restore_mcp_from_backup(operation["target"], operation["server"], operation["backup"])
```

**Benefit:** More granular than full backup restore. Can rollback partial sync.

**Confidence:** MEDIUM — More complex than v1.0 backup approach, but more precise.

---

#### Rollback Strategy 3: Dry-Run Mode for Safe Testing

**What:** Provide `--dry-run` flag to preview sync without writing files.

**Evidence:**
- HarnessSync v1.0 commands (README.md) — `/sync --dry-run` already implemented
- install.sh (Phase 7) — `--dry-run` flag for installation preview

**Current v1.0 behavior:** DiffFormatter shows what would change without writing.

**v2.0 enhancement:** Extend dry-run to plugin sync. Show which capabilities would be synced, which would be skipped.

**Example output:**

```
$ harnesssync sync-plugin --dry-run my-awesome-plugin

Plugin: my-awesome-plugin
Version: 2.0.0

Sync Preview (dry-run):

→ Gemini CLI:
  ✅ Would sync: 2 commands (/search, /analyze)
  ✅ Would sync: 1 skill (code-reviewer)
  ⚠️ Would skip: 1 hook (auto-format) — Gemini does not support hooks
  ✅ Would sync: 2 MCP servers (github, filesystem)

→ Codex:
  ⚠️ Would skip: 2 commands — Codex has no command system
  ⚠️ Would skip: 1 skill — Codex has no skill system
  ⚠️ Would skip: 1 hook — Codex has no hook system
  ✅ Would sync: 2 MCP servers (github, filesystem)

No files would be modified (dry-run).
Run without --dry-run to apply changes.
```

**Confidence:** HIGH — Already implemented in v1.0, just needs extension.

---

## Summary of Pitfalls and Prevention Strategies

| Pitfall | Risk Level | Prevention Strategy | Confidence |
|---------|-----------|---------------------|------------|
| **Capability degradation** (hooks lost when syncing to Gemini) | HIGH | Explicit compatibility report, warn before sync | HIGH |
| **Scope precedence collapse** (user+project merged in target) | HIGH | Scope-preserving sync (sync each scope separately) | MEDIUM |
| **Path portability** (absolute paths break on other machines) | HIGH | Validate MCP paths, require variable substitution | HIGH |
| **Binary dependency mismatch** (MCP server not installed on target) | MEDIUM | Validate binaries exist, warn if missing | MEDIUM |
| **Permission bypass** (MCP server exposes denied tools) | HIGH | Audit MCP tools, warn on dangerous capabilities | HIGH |
| **Credential exposure** (secrets in MCP env vars) | CRITICAL | Extend SecretDetector to scan MCP env fields | HIGH |
| **Version incompatibility** (plugin v2 synced to CLI v1) | MEDIUM | Feature compatibility matrix, version checks | MEDIUM |
| **Deduplication errors** (same server in multiple scopes) | MEDIUM | No deduplication (preserve scopes) OR hash-based exact match | MEDIUM-HIGH |
| **Rollback failures** (partial sync state) | MEDIUM | Transaction log with compensating actions | MEDIUM |
| **Plugin dependency versions** (MCP package mismatch) | LOW | Document limitation, not in scope | HIGH |

---

## Recommendations for v2.0 Roadmap

Based on research findings:

### Phase 1: Scope-Aware MCP Syncing

**Goal:** Fix scope precedence collapse (most critical pitfall).

**Deliverables:**
1. Refactor SourceReader to return `get_mcp_servers_by_scope()` (user/project separate)
2. Extend StateManager to v2 format (scope-aware tracking)
3. Update all adapters to sync user→user, project→project
4. Add migration from v1 state to v2 state

**Rationale:** Preserving scope semantics is foundational. Must be correct before adding plugin sync.

---

### Phase 2: Plugin Capability Mapping

**Goal:** Sync Claude Code plugins to Gemini extensions / Codex MCP configs.

**Deliverables:**
1. Parse Claude Code plugin.json manifest
2. Map capabilities to target equivalents (hooks→skip, commands→commands, etc.)
3. Generate compatibility report showing lost features
4. Implement `sync-plugin` command

**Rationale:** Core v2.0 feature. Requires Phase 1 scope-awareness for correct MCP syncing.

---

### Phase 3: MCP Security & Portability

**Goal:** Prevent path portability failures and credential exposure.

**Deliverables:**
1. Extend SecretDetector to scan MCP env vars
2. Validate MCP paths (reject absolute paths without variables)
3. Audit MCP tools for dangerous capabilities
4. Implement `--sync-user-mcp` flag (default: skip user-scoped MCP)

**Rationale:** Security and reliability. Users will sync MCP servers with credentials → must detect.

---

### Phase 4: Version Compatibility Matrix

**Goal:** Prevent syncing incompatible plugin versions across CLIs.

**Deliverables:**
1. Define feature support matrix (FEATURE_SUPPORT dict)
2. Check plugin capabilities against target support
3. Warn if unsupported features detected
4. Add `compatibilityMatrix` field to plugin.json (optional)

**Rationale:** Future-proofing. As CLIs evolve, incompatibilities will emerge.

---

### Phase 5: Rollback & Recovery

**Goal:** Reliable rollback when plugin sync fails.

**Deliverables:**
1. Extend BackupManager to backup plugin state
2. Implement transaction log for sync operations
3. Add `harnesssync rollback` command
4. Extend `--dry-run` to plugin sync preview

**Rationale:** Users need confidence that failed sync won't break their setup.

---

## Open Questions for Validation

1. **Should user-scoped MCP servers be synced by default?** Research suggests NO (security risk), but may break user expectations. Needs user testing.

2. **How should HarnessSync handle MCP server name conflicts across scopes?** Current recommendation: preserve both (no deduplication). Alternative: prompt user. Needs UX design.

3. **Should plugin sync require explicit opt-in per target?** E.g., `harnesssync sync-plugin my-plugin --to gemini` instead of auto-syncing to all targets. Research inconclusive.

4. **How to handle plugin updates?** If plugin v1.0 synced, then v2.0 released with breaking changes, should HarnessSync auto-update synced targets or require manual re-sync? Needs policy decision.

---

## Deferred Research

The following questions were identified but not fully researched due to scope constraints:

1. **Plugin dependency resolution across CLIs** — If Claude Code plugin depends on another plugin, how to sync dependencies to Gemini/Codex?

2. **Bi-directional sync** — Currently HarnessSync is unidirectional (Claude → targets). Should v2.0 support reverse sync (Gemini extension → Claude plugin)?

3. **Conflict resolution UI** — When MCP server conflicts detected, should HarnessSync provide interactive resolution (similar to `git mergetool`)?

4. **Plugin marketplace integration** — Should HarnessSync auto-publish synced plugins to Gemini extension catalog?

These should be revisited in v2.1 or later milestones.

---

## Sources

### Plugin Ecosystem Research
- [Create plugins - Claude Code Docs](https://code.claude.com/docs/en/plugins)
- [Understanding Claude Code's Full Stack](https://alexop.dev/posts/understanding-claude-code-full-stack/)
- [Claude Code Skills vs Commands vs Subagents vs Plugins](https://www.youngleaders.tech/p/claude-skills-commands-subagents-plugins)
- [Become a Claude Code Hero](https://medium.com/@diehardankush/become-a-claude-code-hero-core-concepts-of-the-claude-cli-plugins-hooks-skills-mcp-54ae48d7c145)
- [Browse Extensions - Gemini CLI](https://geminicli.com/extensions/)
- [Claude Code vs Gemini CLI Comparison](https://shipyard.build/blog/claude-code-vs-gemini-cli/)
- [Claude Code Plugins vs Gemini CLI Extensions](https://harishgarg.com/claude-code-plugins-vs-gemini-cli-extensions-a-comparison)

### MCP Scope & Configuration
- [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
- [MCP Series: Roots — Defining Scope and Boundaries](https://medium.com/@whatsupai/mcp-series-roots-defining-scope-and-boundaries-6f72a8fcf417)
- [Claude Code Settings Precedence](https://code.claude.com/docs/en/settings)
- [Configuration file precedence - Splunk](https://help.splunk.com/en/splunk-enterprise/administer/admin-manual/9.3/administer-splunk-enterprise-with-configuration-files/configuration-file-precedence)
- [Feature Request: Hierarchical Configuration](https://github.com/anthropics/claude-code/issues/4442)

### Plugin Versioning
- [Semantic Versioning 2.0.0](https://semver.org/)
- [Semantic Versioning Explained](https://talent500.com/blog/semantic-versioning-explained-guide/)
- [Plugin Versioning Best Practices - Terraform](https://developer.hashicorp.com/terraform/plugin/best-practices/versioning)
- [Plugins reference - Claude Code Docs](https://code.claude.com/docs/en/plugins-reference)
- [Plugin Structure and Manifest](https://deepwiki.com/anthropics/claude-plugins-official/5.1-plugin-structure-and-manifest)

### Configuration Sync & Deduplication
- [Write Dispositions and Merge Strategies](https://deepwiki.com/dlt-hub/dlt/5.3-write-dispositions-and-merge-strategies)
- [Data Deduplication Strategies](https://www.onehouse.ai/blog/data-deduplication-strategies-in-an-open-lakehouse-architecture)
- [The Definitive Guide to Two-Way Sync](https://www.stacksync.com/blog/the-definitive-guide-to-two-way-sync-technology-benefits-and-limitations)

### Rollback & Transactions
- [Atomic Commit In SQLite](https://sqlite.org/atomiccommit.html)
- [Atomicity in Databases](https://www.datacamp.com/tutorial/atomicity)
- [Database Rollback Strategies in DevOps](https://www.harness.io/harness-devops-academy/database-rollback-strategies-in-devops)
- [Microservices Rollback: Ensuring Data Consistency](https://daily.dev/blog/microservices-rollback-ensuring-data-consistency)

### Cross-Platform Sync
- [IDE Sync - Connect to VSCode](https://plugins.jetbrains.com/plugin/26201-ide-sync--connect-to-vscode)
- [Settings Sync - Visual Studio](https://code.visualstudio.com/docs/configure/settings-sync)
- [JetBrains Settings Sync](https://blog.jetbrains.com/idea/2022/10/intellij-idea-2022-3-eap-3/)
- [How to Sync VS Code Settings Across Devices](https://medium.com/better-programming/sync-visual-studio-code-settings-extensions-shortcuts-across-multiple-devices-9fa6a980f25e)

### MCP Security & Portability
- [Environment Variable Configuration for Filesystem MCP Server](https://github.com/modelcontextprotocol/servers/issues/1879)
- [How To Manage Multiple Environments with MCP](https://chrisfrew.in/blog/how-to-manage-multiple-environments-with-mcp/)
- [MCP configuration secrets handling](https://0xhagen.medium.com/mcp-configuration-is-a-sh-tshow-but-heres-how-i-fixed-secrets-handling-5395010762a1)
- [Use MCP servers in VS Code](https://code.visualstudio.com/docs/copilot/customization/mcp-servers)
- [Support {workspaceFolder} Variable](https://github.com/microsoft/vscode/issues/251263)
- [Claude Code Sandbox Guide](https://claudefa.st/blog/guide/sandboxing-guide)
- [Managing Permissions in Claude Code](https://inventivehq.com/knowledge-base/claude/how-to-manage-permissions-and-sandboxing)

---

*Research complete. All findings documented with confidence levels and source citations. Ready for roadmap planning.*
