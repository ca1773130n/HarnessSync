# Codex CLI Configuration — Verified Reference (2026-06)

Verified against official OpenAI Codex docs (developers.openai.com/codex) and openai/codex GitHub.
All snippets below are quoted verbatim from primary sources. Codex CLI ~v0.135+ era.

Primary sources used:
- Skills: https://developers.openai.com/codex/skills.md
- Config basics: https://developers.openai.com/codex/config-basic.md
- Advanced config: https://developers.openai.com/codex/config-advanced.md
- Config reference (full key table): https://developers.openai.com/codex/config-reference.md
- AGENTS.md guide: https://developers.openai.com/codex/guides/agents-md.md
- MCP: https://developers.openai.com/codex/mcp.md
- Hooks: https://developers.openai.com/codex/hooks.md
- Custom prompts: https://developers.openai.com/codex/custom-prompts.md
- GitHub config index: https://raw.githubusercontent.com/openai/codex/main/docs/config.md

---

## 1. SKILLS DIRECTORY (CRITICAL)

**Definitive answer:** Codex does NOT use `CODEX_HOME/skills` (`~/.codex/skills`). The documented
skills search paths are all `*/.agents/skills/<name>/SKILL.md` directories. The user-level skills
dir is `$HOME/.agents/skills` (NOT `~/.codex/skills`). Project-local skills live in `.agents/skills`
at every directory from CWD up to the repo root. So **yes, Codex reads `.agents/skills/<name>/SKILL.md`** —
that is in fact the ONLY documented filesystem layout for skills.

Source: https://developers.openai.com/codex/skills.md — section "Where to save skills":

> Codex reads skills from repository, user, admin, and system locations. For repositories, Codex scans `.agents/skills` in every directory from your current working directory up to the repository root. If two skills share the same `name`, Codex doesn't merge them; both can appear in skill selectors.

Full scope table (verbatim):

| Skill Scope | Location | Suggested use |
| :--- | :--- | :--- |
| `REPO` | `$CWD/.agents/skills` <br /> Current working directory: where you launch Codex. | If you're in a repository or code environment, teams can check in skills relevant to a working folder. |
| `REPO` | `$CWD/../.agents/skills` <br /> A folder above CWD when you launch Codex inside a Git repository. | Skills relevant to a shared area in a parent folder. |
| `REPO` | `$REPO_ROOT/.agents/skills` <br /> The topmost root folder when you launch Codex inside a Git repository. | Skills relevant to everyone using the repository. |
| `USER` | `$HOME/.agents/skills` <br /> Any skills checked into the user's personal folder. | Curate skills relevant to a user that apply to any repository. |
| `ADMIN` | `/etc/codex/skills` <br /> Any skills checked into the machine or container in a shared, system location. | SDK scripts, automation, default admin skills. |
| `SYSTEM` | Bundled with Codex by OpenAI. | Skill-creator and plan skills, etc. |

Notes:
- USER scope = `$HOME/.agents/skills` (home, NOT `~/.codex`). ADMIN scope = `/etc/codex/skills` (this
  one IS under a codex dir, but it is admin/system scope, not the per-user dir).
- SKILL.md frontmatter requires `name` and `description`:
  > A skill is a directory with a `SKILL.md` file plus optional scripts and references. The `SKILL.md` file must include `name` and `description`.
- Disable a skill (does NOT change the search path) via `~/.codex/config.toml`:
  ```toml
  [[skills.config]]
  path = "/path/to/skill/SKILL.md"
  enabled = false
  ```
- Initial skills list is capped at ~2% of context window (or 8000 chars when unknown); full SKILL.md
  loaded only when the skill is selected (progressive disclosure).

**CONCLUSION FOR THE ADAPTER:** write skills to `.agents/skills/<name>/SKILL.md` (project-local) and/or
`~/.agents/skills/<name>/SKILL.md` (user-global). Do NOT write to `~/.codex/skills`.

---

## 2. config.toml TOP-LEVEL KEYS

All confirmed from https://developers.openai.com/codex/config-reference.md `config.toml` ConfigTable.

### `model`
> key: "model", type: "string", description: "Model to use (e.g., `gpt-5.5`)."
```toml
model = "gpt-5.5"
```

### `model_reasoning_effort`
> key: "model_reasoning_effort", type: "minimal | low | medium | high | xhigh", description: "Adjust reasoning effort for supported models (Responses API only; `xhigh` is model-dependent)."

**Allowed values: `minimal`, `low`, `medium`, `high`, `xhigh`.** `xhigh` IS valid (model-dependent).
Note: `none` is NOT a valid value for `model_reasoning_effort` itself. (`none` appears only for the
separate `plan_mode_reasoning_effort` key, whose type is `none | minimal | low | medium | high | xhigh`.)
```toml
model_reasoning_effort = "xhigh"
```

### `model_verbosity`
> key: "model_verbosity", type: "low | medium | high", description: "Optional GPT-5 Responses API verbosity override; when unset, the selected model/preset default is used."

**Allowed values: `low`, `medium`, `high`.**

### `model_instructions_file` (and the deprecated old name)
> key: "model_instructions_file", type: "string (path)", description: "Replacement for built-in instructions instead of `AGENTS.md`."

Deprecation of old name confirmed (config-reference, schema note):
> Note: Rename `experimental_instructions_file` to `model_instructions_file`. Codex deprecates the old key; update existing configs to the new name.

So YES: `experimental_instructions_file` is the deprecated old name; current key is `model_instructions_file`.

### `project_doc_fallback_filenames`
> key: "project_doc_fallback_filenames", type: "array<string>", description: "Additional filenames to try when `AGENTS.md` is missing."

It IS an array. Docs do not explicitly enumerate values, but it accepts arbitrary filenames, so
`"CLAUDE.md"` is a valid entry (it is "additional filenames to try when AGENTS.md is missing").
From config-advanced.md:
> `project_doc_fallback_filenames`: additional filenames to try when `AGENTS.md` is missing at a directory level

Example (typical usage to make Codex fall back to CLAUDE.md):
```toml
project_doc_fallback_filenames = ["CLAUDE.md"]
```
(CONFIRMED as a feature/array; the specific value "CLAUDE.md" is supported by the semantics but not
spelled out verbatim in the official doc — it is the canonical community usage.)

### `project_doc_max_bytes`
> key: "project_doc_max_bytes", type: "number", description: "Maximum bytes read from `AGENTS.md` when building project instructions."

Default = 32 KiB. From agents-md.md:
> Codex skips empty files and stops adding files once the combined size reaches the limit defined by `project_doc_max_bytes` (32 KiB by default).

### `approval_policy`
> key: "approval_policy", type: "untrusted | on-request | never | { granular = { sandbox_approval = bool, rules = bool, mcp_elicitations = bool, request_permissions = bool, skill_approval = bool } }", description: "Controls when Codex pauses for approval before executing commands. You can also use `approval_policy = { granular = { ... } }` to allow or auto-reject specific prompt categories while keeping other prompts interactive. `on-failure` is deprecated; use `on-request` for interactive runs or `never` for non-interactive runs."

**Allowed STRING values: `untrusted`, `on-request`, `never`.** `on-failure` is DEPRECATED.
**A granular OBJECT form EXISTS:**
```toml
approval_policy = { granular = { sandbox_approval = true, rules = true, mcp_elicitations = true, request_permissions = true, skill_approval = true } }
```

### `sandbox_mode`
> key: "sandbox_mode", type: "read-only | workspace-write | danger-full-access", description: "Sandbox policy for filesystem and network access during command execution."

**Allowed values: `read-only`, `workspace-write`, `danger-full-access`.**

---

## 3. `[sandbox_workspace_write]` TABLE

All from config-reference.md. Keys are written as `sandbox_workspace_write.<key>`:

> key: "sandbox_workspace_write.writable_roots", type: "array<string>", description: 'Additional writable roots when `sandbox_mode = "workspace-write"`.'
> key: "sandbox_workspace_write.network_access", type: "boolean", description: "Allow outbound network access inside the workspace-write sandbox."
> key: "sandbox_workspace_write.exclude_tmpdir_env_var", type: "boolean", description: "Exclude `$TMPDIR` from writable roots in workspace-write mode."
> key: "sandbox_workspace_write.exclude_slash_tmp", type: "boolean", description: "Exclude `/tmp` from writable roots in workspace-write mode."

Snippet:
```toml
[sandbox_workspace_write]
writable_roots = ["/Users/me/scratch"]
network_access = false
exclude_tmpdir_env_var = false
exclude_slash_tmp = false
```

---

## 4. `[mcp_servers.<name>]` TABLE

From mcp.md and config-reference.md.

### (a) STDIO servers
> - `command` (required): The command that starts the server.
> - `args` (optional): Arguments to pass to the server.
> - `env` (optional): Environment variables to set for the server.
> - `env_vars` (optional): Environment variables to allow and forward.
> - `cwd` (optional): Working directory to start the server from.
> - `experimental_environment` (optional): Set to `remote` ...

Plus shared keys:
> - `startup_timeout_sec` (optional): Timeout (seconds) for the server to start. Default: `10`.
> - `tool_timeout_sec` (optional): Timeout (seconds) for the server to run a tool. Default: `60`.
> - `enabled` / `required` / `enabled_tools` / `disabled_tools`

(Also `startup_timeout_ms` is an alias for `startup_timeout_sec` in ms, per config-reference.)

```toml
[mcp_servers.context7]
command = "npx"
args = ["-y", "@upstash/context7-mcp"]
env_vars = ["LOCAL_TOKEN"]

[mcp_servers.context7.env]
MY_ENV_VAR = "MY_ENV_VALUE"
```

### (b) HTTP (Streamable HTTP) servers
> - `url` (required): The server address.
> - `bearer_token_env_var` (optional): Environment variable name for a bearer token to send in `Authorization`.
> - `http_headers` (optional): Map of header names to static values.
> - `env_http_headers` (optional): Map of header names to environment variable names (values pulled from the environment).

```toml
[mcp_servers.figma]
url = "https://mcp.figma.com/mcp"
bearer_token_env_var = "FIGMA_OAUTH_TOKEN"
http_headers = { "X-Figma-Region" = "us-east-1" }
```

### Transport: inferred, NO `type` field
There is no `type`/`transport` key. Transport is inferred from presence of `url` (HTTP) vs `command`
(stdio). Docs list only two server kinds ("STDIO servers" = "started by a command"; "Streamable HTTP
servers" = "you access at an address"), and every documented example sets either `command` or `url`,
never a `type` field.

### Per-tool approval
> - `default_tools_approval_mode` (optional): Default approval behavior for tools from this server. Supported values are `auto`, `prompt`, and `approve`.
> - `tools.<tool>.approval_mode` (optional): Per-tool approval behavior override.

Snippet:
```toml
[mcp_servers.chrome_devtools]
url = "http://localhost:3000/mcp"
enabled_tools = ["open", "screenshot"]
disabled_tools = ["screenshot"] # applied after enabled_tools
default_tools_approval_mode = "prompt"
startup_timeout_sec = 20
tool_timeout_sec = 45
enabled = true

[mcp_servers.chrome_devtools.tools.open]
approval_mode = "approve"
```
(Confirms BOTH `default_tools_approval_mode` and `tools.<tool>.approval_mode` exist.)

---

## 5. `[tools]` TABLE

From config-reference.md:

### `tools.web_search` — EXISTS, boolean OR object
> key: "tools.web_search", type: 'boolean | { context_size = "low|medium|high", allowed_domains = [string], location = { country, region, city, timezone } }', description: "Optional web search tool configuration. The legacy boolean form is still accepted, but the object form lets you set search context size, allowed domains, and approximate user location."

```toml
[tools]
web_search = true
# or object form:
# web_search = { context_size = "medium", allowed_domains = ["docs.python.org"], location = { country = "US" } }
```

### `tools.view_image` — EXISTS, boolean
> key: "tools.view_image", type: "boolean", description: "Enable the local-image attachment tool `view_image`."

```toml
[tools]
view_image = true
```

---

## 6. `[hooks.<Event>]`

From hooks.md. **Hooks are STABLE (enabled by default)**, not experimental:
> Hooks are enabled by default. If you need to turn them off in `config.toml`, set:
> ```toml
> [features]
> hooks = false
> ```
> Use `hooks` as the canonical feature key. `codex_hooks` still works as a deprecated alias.

(Disabled on Windows. Non-managed command hooks require review/trust before they run.)

### Supported hook events (verbatim from the matcher table + scope list):
`SessionStart`, `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`,
`UserPromptSubmit`, `SubagentStart`, `SubagentStop`, `Stop`.

Scope:
> `PreToolUse`, `PermissionRequest`, `PostToolUse`, `PreCompact`, `PostCompact`, `UserPromptSubmit`, `SubagentStop`, and `Stop` run at turn scope. `SessionStart` and `SubagentStart` run at thread or subagent-start scope.

Matcher filtering (verbatim table):
| Event | What `matcher` filters | Notes |
| --- | --- | --- |
| `PermissionRequest` | tool name | `Bash`, `apply_patch`, MCP tool names |
| `PostToolUse` | tool name | `Bash`, `apply_patch`, MCP tool names |
| `PostCompact` | compaction trigger | `manual` or `auto` |
| `PreCompact` | compaction trigger | `manual` or `auto` |
| `PreToolUse` | tool name | `Bash`, `apply_patch`, MCP tool names |
| `SessionStart` | start source | `startup`, `resume`, `clear`, `compact` |
| `SubagentStart` | subagent type | depends on subagent |
| `SubagentStop` | subagent type | depends on subagent |
| `UserPromptSubmit` | not supported | matcher ignored |
| `Stop` | not supported | matcher ignored |

Note: There is **no `PermissionDenied` / `PostToolUseFailure` / `Notification` / `UserPromptExpansion`**
event in Codex (those are Claude Code events). Codex's `notify` key is separate and only fires on
`agent-turn-complete`.

### Inline TOML hook config (verbatim):
```toml
[[hooks.PreToolUse]]
matcher = "^Bash$"

[[hooks.PreToolUse.hooks]]
type = "command"
command = '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/pre_tool_use_policy.py"'
timeout = 30
statusMessage = "Checking Bash command"
```

### Equivalent hooks.json form (verbatim):
```json
{
  "hooks": {
    "SessionStart": [
      { "matcher": "startup|resume",
        "hooks": [ { "type": "command", "command": "python3 ~/.codex/hooks/session_start.py", "statusMessage": "Loading session notes" } ] }
    ],
    "PreToolUse": [
      { "matcher": "Bash",
        "hooks": [ { "type": "command", "command": "/usr/bin/python3 \"$(git rev-parse --show-toplevel)/.codex/hooks/pre_tool_use_policy.py\"", "statusMessage": "Checking Bash command" } ] }
    ]
  }
}
```

Hook discovery locations (verbatim):
> - `~/.codex/hooks.json`
> - `~/.codex/config.toml`
> - `<repo>/.codex/hooks.json`
> - `<repo>/.codex/config.toml`

---

## 7. AGENTS.md — discovery / precedence / merge / byte limit

From agents-md.md, section "How Codex discovers guidance" (verbatim):

> Codex builds an instruction chain when it starts ... Discovery follows this precedence order:
> 1. **Global scope:** In your Codex home directory (defaults to `~/.codex`, unless you set `CODEX_HOME`), Codex reads `AGENTS.override.md` if it exists. Otherwise, Codex reads `AGENTS.md`. Codex uses only the first non-empty file at this level.
> 2. **Project scope:** Starting at the project root (typically the Git root), Codex walks down to your current working directory. ... In each directory along the path, it checks for `AGENTS.override.md`, then `AGENTS.md`, then any fallback names in `project_doc_fallback_filenames`. Codex includes at most one file per directory.
> 3. **Merge order:** Codex concatenates files from the root down, joining them with blank lines. Files closer to your current directory override earlier guidance because they appear later in the combined prompt.

> Codex skips empty files and stops adding files once the combined size reaches the limit defined by `project_doc_max_bytes` (32 KiB by default).

So precedence per directory level: `AGENTS.override.md` > `AGENTS.md` > `project_doc_fallback_filenames`
entries. Global `~/.codex` (or `$CODEX_HOME`) is read first (lowest precedence); project files read
root->cwd with closest-to-cwd winning. Byte cap = `project_doc_max_bytes`, default 32 KiB.

`~/.codex/AGENTS.override.md`:
> Use `~/.codex/AGENTS.override.md` when you need a temporary global override without deleting the base file.

---

## 8. Custom prompts / slash commands (`~/.codex/prompts/*.md`)

From custom-prompts.md — **DEPRECATED in favor of skills, but still functional**:

> Custom prompts are deprecated. Use [skills](https://developers.openai.com/codex/skills) for reusable instructions that Codex can invoke explicitly or implicitly.

> Custom prompts (deprecated) let you turn Markdown files into reusable prompts that you can invoke as slash commands in both the Codex CLI and the Codex IDE extension.

Still works: created under `~/.codex/prompts/`, invoked as `/prompts:<name>`:
> Create the prompts directory: `mkdir -p ~/.codex/prompts` ... Create `~/.codex/prompts/draftpr.md` ...
> Manage prompts by editing or deleting files under `~/.codex/prompts/`. Codex scans only the top-level Markdown files in that folder.

Frontmatter supported: `description:`, `argument-hint:`. Placeholders `$1`-`$9`, `$ARGUMENTS`,
named `$FOO` (via `KEY=value`), `$$` for literal `$`.

**CONCLUSION:** `~/.codex/prompts/*.md` slash commands are still supported but officially deprecated;
OpenAI directs new work to skills (`.agents/skills`).

---

## ITEMS NOT FULLY VERIFIABLE

- `project_doc_fallback_filenames = ["CLAUDE.md"]`: the KEY and array type are officially confirmed,
  and the semantics ("additional filenames to try when AGENTS.md is missing") clearly permit
  "CLAUDE.md". But the official docs do NOT print the literal string "CLAUDE.md" as an example value.
  Treat the value as supported-by-semantics, not doc-quoted.
- Exact Codex CLI version that introduced each key was not pinned; reference reflects the current
  (~0.134-0.138 era) docs as of 2026-06.
