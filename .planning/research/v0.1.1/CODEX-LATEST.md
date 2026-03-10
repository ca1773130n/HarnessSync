# Research: Codex CLI Configuration — Latest State (March 2026)

**Project:** HarnessSync v0.1.1
**Researched:** 2026-03-09
**Overall confidence:** HIGH (official docs, changelog, config reference verified)
**Codex CLI version at time of research:** 0.112.0 (released 2026-03-08)

---

## Executive Summary

Codex CLI has evolved significantly since HarnessSync v0.0.2 research (2026-02-15). The core MCP and AGENTS.md formats remain stable, but several **new configuration domains** have been added that HarnessSync should consider syncing:

1. **Plugin system (v0.110)** — Loads skills, MCP entries, and app connectors from config/marketplace
2. **Multi-agent configuration** — `[agents]` section with named roles, per-role config files
3. **Profiles** — Named configuration presets (`[profiles.<name>]`)
4. **Network permissions** — `[permissions.network]` with domain allowlists
5. **Granular approval policy** — `approval_policy = { reject = { ... } }` object form
6. **Feature flags** — Stable/experimental/dev feature toggles
7. **Skills: `agents/openai.yaml`** — NEW optional metadata file for UI, invocation policy, and tool dependencies
8. **`on-failure` deprecated** — Use `on-request` instead (our adapter currently maps to `on-failure`)

---

## 1. AGENTS.md Format — No Breaking Changes

### Current Specification (Stable)

The AGENTS.md format has NOT changed since our v0.0.2 research. Key facts:

- **Precedence:** Global (`~/.codex/AGENTS.override.md` or `AGENTS.md`) then project root down to CWD
- **Override mechanism:** `AGENTS.override.md` takes precedence at each directory level
- **Merging:** Concatenated root-down with blank line separators; later files override earlier
- **Size limit:** `project_doc_max_bytes` (default 32 KiB)
- **Fallback filenames:** Configurable via `project_doc_fallback_filenames`
- **Injection format:** Each file becomes a user-role message: `# AGENTS.md instructions for <directory>`

### HarnessSync Impact: NONE

Our current managed-marker approach in AGENTS.md remains compatible. No changes needed.

**Confidence:** HIGH — verified against [official AGENTS.md guide](https://developers.openai.com/codex/guides/agents-md/)

---

## 2. Skills System — NEW `agents/openai.yaml`

### Current SKILL.md Format (Stable)

The core SKILL.md format is unchanged:

```yaml
---
name: skill-name
description: "When this skill should trigger"
---

# Instructions
...
```

**Required fields:** `name`, `description`
**Discovery locations:**
- Project: `.agents/skills/` (walked from CWD to repo root)
- User: `~/.codex/skills/`
- System: `/etc/codex/skills/` (new — was `/usr/local/share/codex/skills/` previously)

### NEW: `agents/openai.yaml` (Optional Metadata)

Skills can now include an `agents/openai.yaml` file for richer configuration:

```
my-skill/
  SKILL.md           (required)
  agents/
    openai.yaml      (optional — NEW)
  scripts/           (optional)
  references/        (optional)
  assets/            (optional)
```

**`agents/openai.yaml` schema:**

```yaml
interface:
  display_name: "User-facing name"
  short_description: "Brief description"
  icon_small: "./assets/small-logo.svg"
  icon_large: "./assets/large-logo.png"
  brand_color: "#3B82F6"
  default_prompt: "Optional surrounding prompt"

policy:
  allow_implicit_invocation: false  # default: true

dependencies:
  tools:
    - type: "mcp"
      value: "toolName"
      description: "Tool purpose"
      transport: "streamable_http"
      url: "https://example.com"
```

**Key new capabilities:**
- `allow_implicit_invocation: false` — Skill only triggers with explicit `$skill` invocation
- `dependencies.tools` — Declare MCP tool dependencies (auto-installed with `skill_mcp_dependency_install` feature flag)
- `interface` — UI metadata for Codex app (display names, icons, colors)

### HarnessSync Impact: MEDIUM

**Current behavior:** We write SKILL.md only. This remains correct.

**Potential enhancement:** When syncing Claude Code agents that have tool dependencies, we could generate `agents/openai.yaml` with:
- `allow_implicit_invocation: false` for agents (explicit invocation makes sense)
- MCP tool dependencies if the agent uses specific MCP tools

**Recommendation:** Defer to a future version. The SKILL.md-only approach works fine.

**Confidence:** HIGH — verified against [official Skills docs](https://developers.openai.com/codex/skills/)

---

## 3. Config File Format — Major Expansion

### File Naming: `config.toml` (Not `codex.toml`)

**IMPORTANT NAMING NOTE:** The official docs consistently refer to `config.toml`, not `codex.toml`. Both names appear to work, but the canonical name is `config.toml`. Our adapter currently uses `CONFIG_TOML = "codex.toml"` — this should be verified.

**Locations:**
- User: `~/.codex/config.toml`
- Project: `.codex/config.toml`
- System: `/etc/codex/config.toml` (NEW)

**Precedence (highest to lowest):**
1. CLI flags and `--config` overrides
2. Profile values
3. Project config (`.codex/config.toml`)
4. User config (`~/.codex/config.toml`)
5. System config (`/etc/codex/config.toml`)
6. Built-in defaults

### NEW Configuration Sections

The following are NEW or significantly expanded since our v0.0.2 research:

#### 3a. Profiles (`[profiles.<name>]`)

```toml
[profiles.deep-review]
model = "gpt-5-pro"
model_reasoning_effort = "high"
approval_policy = "never"
```

Run with: `codex --profile deep-review`

#### 3b. Multi-Agent Configuration (`[agents]`)

```toml
[agents]
max_threads = 6                   # Concurrent agent threads (default: 6)
max_depth = 1                     # Nesting depth (default: 1)
job_max_runtime_seconds = 1800    # Per-worker timeout

[agents.reviewer]
description = "Find correctness, security, and test risks in code."
config_file = "./agents/reviewer.toml"  # Relative to defining config.toml
```

#### 3c. Network Permissions (`[permissions.network]`)

```toml
[permissions.network]
enabled = true
mode = "limited"           # or "full"
allowed_domains = ["api.github.com", "registry.npmjs.org"]
denied_domains = ["evil.com"]
enable_socks5 = false
```

#### 3d. Shell Environment Policy (`[shell_environment_policy]`)

```toml
[shell_environment_policy]
inherit = "none"           # "all" | "core" | "none"
include_only = ["PATH", "HOME"]
exclude = ["AWS_*", "AZURE_*"]
```

#### 3e. Feature Flags (`[features]`)

```toml
[features]
# Stable
unified_exec = true
shell_tool = true
fast_mode = true
sqlite = true
skill_mcp_dependency_install = true

# Experimental
multi_agent = true
use_linux_sandbox_bwrap = false
runtime_metrics = false

# Under development
artifact = false
image_generation = false
responses_websockets = false
```

#### 3f. Model Provider Configuration (`[model_providers]`)

```toml
[model_providers.proxy]
base_url = "http://proxy.example.com"
env_key = "OPENAI_API_KEY"
http_headers = { "X-Custom" = "value" }
stream_idle_timeout_ms = 300000
stream_max_retries = 5
supports_websockets = false
```

#### 3g. TUI Customization (`[tui]`)

```toml
[tui]
theme = "monokai"
notifications = true
alternate_screen = "auto"    # "always" | "never"
```

#### 3h. OpenTelemetry (`[otel]`)

```toml
[otel]
exporter = "otlp-http"
trace_exporter = "http://collector:4318"
log_user_prompt = false
```

### HarnessSync Impact: HIGH

**Critical fix needed:** Our adapter maps `approval_mode == 'auto'` to `approval_policy = 'on-failure'`. The `on-failure` value is **deprecated**. Must change to `on-request`.

**New sync opportunities:**
- Profiles could be generated from Claude Code project configurations
- Network permissions could map from Claude Code's allowed/denied tools
- Shell environment policy could map from Claude Code environment settings

**Recommendation:** Fix the `on-failure` deprecation immediately. Consider profiles and network permissions for a future version.

**Confidence:** HIGH — verified against [config reference](https://developers.openai.com/codex/config-reference) and [sample config](https://developers.openai.com/codex/config-sample/)

---

## 4. MCP Server Configuration — Stable with Minor Additions

### Core Format: No Changes

The `[mcp_servers."name"]` format is stable since our v0.0.2 research. All fields documented in v0.0.2 remain current.

### New/Confirmed Fields

```toml
[mcp_servers."server-name"]
# STDIO
command = "npx"
args = ["-y", "@package/server"]
cwd = "/working/dir"                    # NEW in docs (may have existed before)
env = { KEY = "value" }
env_vars = ["ALLOWED_VAR"]

# HTTP
url = "https://api.example.com/mcp"
bearer_token_env_var = "TOKEN_VAR"
http_headers = { "X-Key" = "value" }
env_http_headers = { "X-API-Key" = "API_KEY_ENV_VAR" }  # Headers sourced from env vars

# Universal
enabled = true
required = false
startup_timeout_sec = 10
tool_timeout_sec = 60
enabled_tools = ["tool1"]
disabled_tools = ["tool2"]
```

### OAuth Configuration (Top-Level)

```toml
mcp_oauth_callback_port = 8080          # Fixed port for OAuth callbacks
mcp_oauth_callback_url = "http://..."   # Custom callback URL (remote devboxes)
```

### HarnessSync Impact: LOW

Our current MCP sync is correct. Minor additions:
- `cwd` field — consider mapping if Claude Code provides working directory
- `env_http_headers` — useful for HTTP servers with env-based auth headers
- OAuth settings — not relevant for sync (user-specific)

**Confidence:** HIGH — verified against [MCP docs](https://developers.openai.com/codex/mcp/)

---

## 5. Sandbox Modes and Approval Policies — Updated

### Sandbox Modes (Unchanged)

| Mode | Description |
|------|-------------|
| `read-only` | No file writes, no network |
| `workspace-write` | Write within workspace + writable_roots |
| `danger-full-access` | No restrictions |

**New sub-config:**
```toml
[sandbox_workspace_write]
writable_roots = ["/tmp/build", "/var/cache"]
network_access = true
```

### Approval Policies (CHANGED)

**Valid values:**
| Value | Description |
|-------|-------------|
| `untrusted` | NEW — Ask for everything including reads |
| `on-request` | Ask before writes/commands (replaces `on-failure`) |
| `never` | No approval prompts |
| `{ reject = { ... } }` | NEW — Granular auto-reject |

**`on-failure` is DEPRECATED** — use `on-request` instead.

**Granular reject policy (NEW):**
```toml
approval_policy = { reject = { sandbox_approval = true, rules = false, mcp_elicitations = false } }
```

Fields:
- `sandbox_approval` — Auto-reject sandbox escalation prompts
- `rules` — Auto-reject execpolicy rule prompts
- `mcp_elicitations` — Auto-reject MCP input request prompts

### HarnessSync Impact: CRITICAL

**BUG:** Our `sync_settings` maps `approval_mode == 'auto'` to `approval_policy = 'on-failure'` (line 454 of codex.py). This value is deprecated. Must change to `on-request`.

```python
# CURRENT (BROKEN):
if approval_mode == 'auto':
    approval_policy = 'on-failure'

# SHOULD BE:
if approval_mode == 'auto':
    approval_policy = 'on-request'
```

**New opportunity:** The `untrusted` mode and granular `reject` policy could map from Claude Code's more detailed permission settings.

**Confidence:** HIGH — verified against [config basics](https://developers.openai.com/codex/config-basic/) and [config reference](https://developers.openai.com/codex/config-reference)

---

## 6. Plugin System (v0.110+) — NEW

As of Codex CLI v0.110 (2026-03-05), a plugin system was added:

- Loads skills, MCP entries, and app connectors from config or marketplace
- `@plugin` mentions in chat (v0.112) allow direct plugin references with auto-included context
- Session startup now communicates enabled plugins to the model

### How it works:
- Codex scans `.codex/` folders from CWD up to repo root, plus `~/.codex/` and `/etc/codex/`
- Loads skills, MCP server configs, and app connectors found in these locations
- This is NOT the same as Claude Code's plugin system (different architecture)

### HarnessSync Impact: LOW

The Codex plugin system is about discovery of already-installed skills/MCPs. Since HarnessSync already places skills in `.agents/skills/` and MCP configs in `.codex/config.toml`, the plugin system should automatically discover our synced content.

No changes needed, but good to know that Codex now surfaces synced content to the user at startup.

**Confidence:** MEDIUM — changelog entries only, no dedicated docs page found

---

## 7. Multi-Agent System — NEW Sync Opportunity

### Configuration Format

```toml
[agents]
max_threads = 6
max_depth = 1
job_max_runtime_seconds = 1800

[agents.reviewer]
description = "Find correctness, security, and test risks in code."
config_file = "./agents/reviewer.toml"

[agents.worker]
description = "Execute implementation tasks."
config_file = "./agents/worker.toml"
```

**Per-agent config files** can override: `model`, `model_reasoning_effort`, `sandbox_mode`, `developer_instructions`, and even include their own `[mcp_servers]`.

**Built-in roles:** `default`, `worker`, `explorer`, `monitor` (user-defined override these)

### HarnessSync Impact: MEDIUM (Future)

Claude Code agents could map to Codex multi-agent roles:
- Agent name -> `[agents.<name>]`
- Agent description -> `description`
- Agent instructions -> `developer_instructions` in per-agent config file

This would be a richer mapping than our current SKILL.md approach, but multi-agent is still experimental. The SKILL.md approach remains the safer bet.

**Recommendation:** Track this for a future version when multi-agent stabilizes.

**Confidence:** HIGH — verified against [multi-agent docs](https://developers.openai.com/codex/multi-agent/)

---

## 8. Config File Naming: `config.toml` vs `codex.toml`

### Finding

The official documentation consistently uses `config.toml`:
- User: `~/.codex/config.toml`
- Project: `.codex/config.toml`

Our adapter uses `CONFIG_TOML = "codex.toml"` and writes to:
- User-scope: `{project_dir}/codex.toml`
- Project-scope: `{project_dir}/.codex/codex.toml`

### Verification Needed

Both filenames may work (Codex may accept either), but the canonical name is `config.toml`. Our current `codex.toml` naming may be silently ignored.

**CRITICAL ACTION:** Verify whether Codex actually reads `codex.toml` or only `config.toml`. If only `config.toml`, our sync is completely broken for settings.

**Confidence:** MEDIUM — docs say `config.toml`, but our existing `codex.toml` files exist and we haven't had bug reports

---

## 9. New CLI Commands Relevant to HarnessSync

| Command | Description | Relevance |
|---------|-------------|-----------|
| `codex features list` | Show feature flags with maturity | Could inform settings sync |
| `codex features enable/disable <flag>` | Toggle features | Could be target of settings sync |
| `codex mcp add/remove/list` | Manage MCP servers | Alternative to direct config.toml editing |
| `codex execpolicy` | Validate rule files | Could validate our AGENTS.md output |
| `codex debug clear-memories` | Clear agent memories | Useful for testing |
| `/debug-config` | Inspect effective configuration | Useful for verifying sync results |

---

## 10. Summary: What Needs Updating in HarnessSync

### CRITICAL (Fix Now)

| Issue | Current | Should Be | Impact |
|-------|---------|-----------|--------|
| `on-failure` deprecated | `approval_policy = 'on-failure'` | `approval_policy = 'on-request'` | Settings sync may cause warnings/errors |
| Config filename | `codex.toml` | Verify if `config.toml` is required | Settings/MCP sync may be silently ignored |

### RECOMMENDED (v0.1.1)

| Feature | Description | Effort |
|---------|-------------|--------|
| `untrusted` approval mode | Map from Claude Code restrictive permissions | Small |
| `writable_roots` | Map workspace write directories | Small |
| Network permissions | Map from allowed/denied domains | Medium |

### FUTURE (v0.2+)

| Feature | Description | Effort |
|---------|-------------|--------|
| Multi-agent roles | Map Claude agents to `[agents.<name>]` with config files | Large |
| Profiles | Generate named profiles from Claude project configs | Medium |
| `agents/openai.yaml` | Generate skill metadata for UI, invocation policy | Medium |
| Feature flags sync | Map Claude settings to Codex feature flags | Small |
| Granular reject policy | Map detailed permissions to `{ reject = { ... } }` | Medium |

### NO CHANGES NEEDED

| Area | Status |
|------|--------|
| AGENTS.md format | Stable, our marker approach works |
| SKILL.md format | Stable, our frontmatter approach works |
| MCP TOML format | Stable, our translation works |
| Skills directory | `.agents/skills/` still correct |
| Symlink approach | Still works for skill sharing |

---

## Sources

### Official Documentation
- [AGENTS.md Guide](https://developers.openai.com/codex/guides/agents-md/)
- [Agent Skills](https://developers.openai.com/codex/skills/)
- [Configuration Reference](https://developers.openai.com/codex/config-reference)
- [Config Basics](https://developers.openai.com/codex/config-basic/)
- [Advanced Configuration](https://developers.openai.com/codex/config-advanced/)
- [Sample Configuration](https://developers.openai.com/codex/config-sample/)
- [MCP Configuration](https://developers.openai.com/codex/mcp/)
- [Multi-Agent Configuration](https://developers.openai.com/codex/multi-agent/)
- [CLI Reference](https://developers.openai.com/codex/cli/reference/)
- [CLI Features](https://developers.openai.com/codex/cli/features/)
- [Codex Changelog](https://developers.openai.com/codex/changelog/)

### GitHub
- [openai/codex Repository](https://github.com/openai/codex)
- [openai/skills Catalog](https://github.com/openai/skills)

### Community
- [Skills in OpenAI Codex (blog.fsck.com)](https://blog.fsck.com/2025/12/19/codex-skills/)
- [Agent Skills Standard (agentskills.io)](https://agentskills.io)
