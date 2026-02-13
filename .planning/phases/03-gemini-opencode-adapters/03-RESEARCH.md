# Phase 3: Gemini & OpenCode Adapters - Research

**Researched:** 2026-02-13
**Domain:** Multi-target AI CLI adapter implementation (Gemini CLI, OpenCode)
**Confidence:** HIGH

## Summary

Phase 3 extends the proven adapter pattern from Phase 2 (Codex) to two additional AI CLI targets: Google Gemini CLI and OpenCode. Both targets support the Agent Skills open standard (making skills portable), but have fundamentally different architectural approaches to content management and MCP server configuration.

**Key architectural differences identified:**
1. **Gemini CLI**: Cannot use symlinks for skills; requires inlining skill content into GEMINI.md with YAML frontmatter stripping and section headers. MCP servers use settings.json with mcpServers object supporting stdio/SSE/HTTP transports.
2. **OpenCode**: Native support for skills/agents/commands as separate entities via symlinks to .opencode/ directories. MCP servers use opencode.json with type-discriminated local vs remote servers.
3. **Permission mapping**: Both targets use different permission models than Claude Code, requiring conservative translation to avoid security downgrades.

**Primary recommendation:** Implement both adapters using the established AdapterBase pattern with format-specific content transformation (Gemini inline, OpenCode symlink) and conservative permission mapping (Claude "deny" → skip tool, warn on downgrades).

## User Constraints (from CONTEXT.md)

**No CONTEXT.md exists for this phase** — user has not provided explicit constraints via `/grd:discuss-phase`. All architectural decisions are within Claude's discretion, following the patterns established in Phase 1-2.

## Paper-Backed Recommendations

### Recommendation 1: Use Adapter Pattern Extension (Proven in Phase 2)

**Recommendation:** Extend the existing AdapterBase ABC to implement GeminiAdapter and OpenCodeAdapter with identical 6-method interface.

**Evidence:**
- Phase 2 verification (02-03-SUMMARY.md) — Codex adapter achieved 100% success rate across all 6 sync methods with 7 items synced, 5 adapted, 0 failed
- Adapter registry pattern enables zero-modification addition of new targets (Open/Closed Principle)
- SyncResult dataclass provides consistent tracking across all adapters

**Confidence:** HIGH — Pattern is proven working in production with complete Phase 2 test coverage.

**Expected improvement:** Each adapter implementation completes in 1-2 plans (estimated 2 plans for Phase 3: one for Gemini, one for OpenCode + integration).

**Caveats:** None — pattern is stable and tested.

### Recommendation 2: Inline Content Transformation for Gemini

**Recommendation:** Strip YAML frontmatter from skills/agents and inline content into GEMINI.md with section headers, as Gemini CLI cannot use symlinks.

**Evidence:**
- [Gemini CLI GEMINI.md documentation](https://geminicli.com/docs/cli/gemini-md/) — "GEMINI.md context files provide instructional context to the Gemini model"
- [Agent Skills format](https://geminicli.com/docs/cli/creating-skills/) — Skills use YAML frontmatter (name, description) + markdown body for instructions
- [Mastering Agent Skills in Gemini CLI](https://danicat.dev/posts/agent-skills-gemini-cli/) — "The frontmatter contains name and description fields, which are the only fields that Gemini CLI reads to determine when the skill gets used"
- Phase 2 Codex adapter — Already implements frontmatter parsing via `_parse_frontmatter()` regex pattern

**Confidence:** HIGH — Official documentation confirms format requirements. Frontmatter parsing is proven in Codex adapter.

**Expected improvement:** Skills inline successfully with semantic preservation (name → section header, description → intro text, body → instructions).

**Caveats:** Inlining loses modularity (cannot update individual skills without regenerating entire GEMINI.md). Use marker-based sections similar to AGENTS.md pattern from Codex adapter.

### Recommendation 3: Use npx mcp-remote for URL-based MCP Servers (Gemini)

**Recommendation:** Wrap URL-based MCP servers with `npx mcp-remote` command for Gemini's settings.json mcpServers configuration.

**Evidence:**
- [mcp-remote npm package](https://www.npmjs.com/package/mcp-remote) — Official MCP remote server wrapper supporting SSE and HTTP transports
- [Gemini CLI MCP configuration](https://geminicli.com/docs/tools/mcp-server/) — Supports command (stdio), url (SSE), and httpUrl (HTTP streaming) transports
- Usage pattern: `npx mcp-remote https://remote.mcp.server/sse` converts remote server to stdio interface

**Confidence:** MEDIUM — Official tool and format, but requires npx runtime. May need fallback if npx unavailable.

**Expected improvement:** URL-based MCP servers work in Gemini CLI without custom HTTP client implementation.

**Caveats:** Requires Node.js/npx on system. Consider detection + warning if npx missing. Alternative: Direct url/httpUrl configuration (simpler, no wrapper needed).

### Recommendation 4: Type-Discriminated MCP Server Translation (OpenCode)

**Recommendation:** Use `type: "local"` for stdio servers (command/args) and `type: "remote"` for URL servers in OpenCode's opencode.json.

**Evidence:**
- [OpenCode MCP configuration](https://opencode.ai/docs/mcp-servers/) — "Local servers have type 'local', remote servers have type 'remote' with url property"
- [OpenCode config schema](https://opencode.ai/config.json) — Provides JSON schema validation for type field
- Example from docs: Local requires `command: [...]`, Remote requires `url: "..."`

**Confidence:** HIGH — Official documentation with clear schema definition and examples.

**Expected improvement:** MCP servers translate cleanly with type safety from schema validation.

**Caveats:** OpenCode requires explicit type discrimination; cannot auto-detect from presence of command vs url like Claude Code.

### Recommendation 5: Conservative Permission Mapping (All Adapters)

**Recommendation:** Map Claude Code permissions conservatively: any "deny" → skip tool in target, warn on permission downgrades, never auto-enable dangerous modes.

**Evidence:**
- Phase 2 decision (02-03-SUMMARY.md) — "Conservative permission mapping: ANY denied tool -> read-only sandbox (never auto-maps to danger-full-access)"
- [Gemini CLI yolo mode](https://www.oreateai.com/blog/how-to-have-gemini-go-yolo-mode/9dcf87073dec6b38923f26fb94625946) — Yolo mode auto-approves all tools (dangerous default)
- [OpenCode permissions](https://opencode.ai/docs/permissions/) — "Most permissions default to 'allow'. Use 'ask' or 'deny' for restricted tools"
- Security principle: Never downgrade user-specified restrictions during translation

**Confidence:** HIGH — Security-first principle with Phase 2 proven implementation.

**Expected improvement:** Zero security regressions during sync. Users explicitly opt-in to permissive modes.

**Caveats:** May result in overly restrictive initial config requiring manual relaxation. Better than accidental privilege escalation.

## Standard Stack

### Core (Python 3.10+ stdlib only)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.10+ | All adapter logic, file I/O, JSON parsing | **MANDATORY** project constraint (zero dependencies). Phase 1-2 proven compatible. |
| pathlib | stdlib | Path operations, symlink creation | Cross-platform path handling. Used throughout Phase 1-2. |
| json | stdlib | Parse MCP configs, settings.json | Native format for Claude Code, OpenCode configs. |
| re | stdlib | YAML frontmatter parsing, content extraction | Proven in Codex adapter `_parse_frontmatter()`, `_extract_role_section()`. |

### Supporting (Zero external dependencies)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| hashlib (stdlib) | 3.10+ | SHA256 for state tracking | Already used in Phase 1 state_manager for drift detection. |
| tempfile (stdlib) | 3.10+ | Atomic file writes | Used in toml_writer.py `write_toml_atomic()` pattern. |
| shutil (stdlib) | 3.10+ | Directory operations | For cleanup of stale symlinks in .opencode/. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Decision |
|------------|-----------|----------|----------|
| Manual frontmatter parsing | PyYAML library | PyYAML violates zero-dep constraint. Regex parsing sufficient for simple frontmatter. | **Use regex** (Phase 2 proven) |
| npx mcp-remote wrapper | Direct url/httpUrl config | Wrapper adds npx dependency. Direct config simpler but may need auth handling. | **Use direct config** (simpler, no runtime dep) |
| Symlink for Gemini skills | Copy with marker | Symlinks fail on Gemini (official docs confirm). Must inline. | **Inline content** (Gemini limitation) |
| JSON for Gemini MCP | Keep .mcp.json format | Gemini uses settings.json mcpServers, not .mcp.json. Must translate. | **Translate to settings.json** (Gemini requirement) |

## Architecture Patterns

### Recommended Project Structure

```
src/adapters/
├── base.py              # AdapterBase ABC (Phase 2 - complete)
├── registry.py          # AdapterRegistry decorator (Phase 2 - complete)
├── result.py            # SyncResult dataclass (Phase 2 - complete)
├── codex.py             # CodexAdapter (Phase 2 - complete)
├── gemini.py            # NEW: GeminiAdapter
└── opencode.py          # NEW: OpenCodeAdapter
```

### Pattern 1: Content Inlining with Markers (Gemini)

**What:** Strip YAML frontmatter, inline skill/agent content into GEMINI.md with section headers and HarnessSync markers.

**When to use:** When target cannot use symlinks and requires monolithic context files.

**Example:**
```python
# GeminiAdapter.sync_skills()
def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
    """Inline skills into GEMINI.md (Gemini cannot use symlinks)."""
    sections = []

    for name, skill_dir in skills.items():
        skill_md = skill_dir / "SKILL.md"
        content = skill_md.read_text(encoding='utf-8')

        # Strip YAML frontmatter (reuse Codex pattern)
        frontmatter, body = self._parse_frontmatter(content)

        # Build section with header
        section = f"## Skill: {frontmatter.get('name', name)}\n\n"
        if frontmatter.get('description'):
            section += f"**Purpose:** {frontmatter['description']}\n\n"
        section += body

        sections.append(section)

    # Combine into managed section of GEMINI.md
    managed_content = "\n\n---\n\n".join(sections)
    self._write_gemini_md_section("Skills", managed_content)

    return SyncResult(synced=len(skills), adapted=len(skills))
```

**Reference:** Codex adapter's `_replace_managed_section()` pattern (lines 520-565 in codex.py).

### Pattern 2: Type-Discriminated Config Generation (OpenCode)

**What:** Generate type-discriminated MCP server configs based on transport type (stdio → local, URL → remote).

**When to use:** When target requires explicit type field for polymorphic config structures.

**Example:**
```python
# OpenCodeAdapter.sync_mcp()
def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
    """Translate MCP servers to opencode.json format."""
    opencode_servers = {}

    for name, config in mcp_servers.items():
        if config.get("command"):
            # Stdio transport → local type
            opencode_servers[name] = {
                "type": "local",
                "command": [config["command"]] + config.get("args", []),
                "environment": config.get("env", {}),
                "enabled": True,
            }
        elif config.get("url"):
            # URL transport → remote type
            opencode_servers[name] = {
                "type": "remote",
                "url": config["url"],
                "headers": config.get("headers", {}),
                "enabled": True,
            }

    # Write to opencode.json
    config_path = self.project_dir / ".opencode" / "opencode.json"
    existing = read_json_safe(config_path)
    existing["mcp"] = {**existing.get("mcp", {}), **opencode_servers}

    write_json_atomic(config_path, existing)
    return SyncResult(synced=len(opencode_servers))
```

**Reference:** OpenCode config schema at https://opencode.ai/config.json.

### Pattern 3: Symlink with Stale Cleanup (OpenCode)

**What:** Create symlinks to .opencode/skills/, .opencode/agents/, .opencode/commands/, then remove stale symlinks pointing to non-existent sources.

**When to use:** When target supports native directory discovery and benefits from zero-copy sync.

**Example:**
```python
# OpenCodeAdapter.sync_skills()
def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
    """Sync skills via symlinks to .opencode/skills/."""
    target_dir = self.project_dir / ".opencode" / "skills"
    ensure_dir(target_dir)

    result = SyncResult()

    # Create symlinks for current skills
    for name, source_path in skills.items():
        target_path = target_dir / name
        success, method = create_symlink_with_fallback(source_path, target_path)
        if success and method != 'skipped':
            result.synced += 1

    # Remove stale symlinks (target exists but source missing)
    for existing in target_dir.iterdir():
        if existing.is_symlink():
            if not existing.resolve().exists():
                existing.unlink()  # Stale symlink
                result.cleaned += 1

    return result
```

**Reference:** Codex adapter's `sync_skills()` (lines 111-149 in codex.py) + stale cleanup logic.

### Anti-Patterns to Avoid

- **Downgrading permissions during translation:** Never map Claude "deny" to target "allow". Always map to most restrictive equivalent.
- **Assuming symlink support:** Gemini CLI cannot use symlinks (official docs confirm). Must inline content.
- **Hardcoding tool names:** Use tool allow/deny lists from source config, don't hardcode known tool names.
- **Skipping frontmatter stripping:** Gemini expects plain markdown sections, not YAML frontmatter within GEMINI.md.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML parsing | Full YAML parser | Regex for simple frontmatter | Codex adapter proves regex sufficient for `key: value` format. PyYAML violates zero-dep. |
| JSON writing | Manual escaping + formatting | json.dump() from stdlib | Native escaping, handles edge cases (unicode, special chars). |
| Atomic writes | Manual temp file + rename | Existing `write_toml_atomic()` pattern | Phase 1 proven pattern for config files. Extend to JSON with `write_json_atomic()`. |
| Symlink fallback chain | OS detection + multiple attempts | `create_symlink_with_fallback()` from paths.py | Phase 1 proven: symlink → junction → copy with marker. Handles Windows/macOS/Linux. |

**Key insight:** Phase 1-2 established robust file operation patterns. Reuse rather than reimplement.

## Common Pitfalls

### Pitfall 1: Forgetting to Strip YAML Frontmatter (Gemini)

**What goes wrong:** Inlining skills with frontmatter causes `---\nname: foo\n---` to appear in GEMINI.md, confusing the model.

**Why it happens:** Codex skills need frontmatter (SKILL.md format requires it), but Gemini context files expect plain markdown sections.

**How to avoid:** Always call `_parse_frontmatter()` before inlining content. Use frontmatter for metadata (name → section header, description → intro), discard YAML syntax.

**Warning signs:** GEMINI.md contains triple-dash markers or `key: value` syntax outside code blocks.

**Paper reference:** N/A (format specification from official docs)

### Pitfall 2: Creating Broken Symlinks (OpenCode)

**What goes wrong:** Symlinks point to moved/deleted source directories, causing OpenCode to fail loading skills.

**Why it happens:** Skills may be removed from Claude Code but symlinks persist in .opencode/ directories.

**How to avoid:** Implement stale symlink cleanup: iterate .opencode/{skills,agents,commands}, check `symlink.resolve().exists()`, unlink if False.

**Warning signs:** OpenCode logs "skill not found" errors despite sync claiming success.

**Paper reference:** N/A (filesystem hygiene best practice)

### Pitfall 3: Permission Downgrade During Translation (Security)

**What goes wrong:** Claude Code denies Bash tool, adapter maps to target "allow" mode, user accidentally grants shell access.

**Why it happens:** Targets have different default-allow policies (OpenCode defaults most tools to "allow"). Direct mapping can increase privileges.

**How to avoid:** Conservative mapping rule: if Claude denies, target must deny or skip. Log warnings for unmappable restrictions.

**Warning signs:** Security-sensitive tools (Bash, Write, Edit) work in target but were denied in Claude Code.

**Paper reference:** Principle of least privilege (security best practice, not ML paper)

### Pitfall 4: Overwriting User Edits in GEMINI.md (Gemini)

**What goes wrong:** User adds custom notes to GEMINI.md, sync overwrites everything with synced content.

**Why it happens:** Without marker-based sections, sync cannot distinguish user content from managed content.

**How to avoid:** Use HarnessSync markers (similar to Codex AGENTS.md pattern). Preserve content outside markers.

**Warning signs:** User complaints about lost content after sync. git diff shows entire GEMINI.md rewritten.

**Paper reference:** N/A (UX best practice)

### Pitfall 5: npx Dependency for mcp-remote (Gemini)

**What goes wrong:** Adapter uses `npx mcp-remote` wrapper, but user's system lacks Node.js, MCP servers fail to start.

**Why it happens:** Assuming npx is available because it's common in dev environments.

**How to avoid:** Detect npx availability via `shutil.which('npx')`. If missing, fall back to direct url/httpUrl config (simpler, no wrapper). Log warning about potential auth issues.

**Warning signs:** MCP server startup fails with "npx: command not found".

**Paper reference:** N/A (dependency management best practice)

## Experiment Design

**Not applicable for this phase.** This is a practical engineering task (adapter implementation), not an ML/research project requiring experimental validation.

Verification strategy uses **proxy-level testing** (unit tests + integration tests) rather than experimental baselines or ablation studies.

## Verification Strategy

### Recommended Verification Tiers for This Phase

| Item | Recommended Tier | Rationale |
|------|-----------------|-----------|
| Gemini adapter 6 sync methods | Level 2 (Proxy) | Unit tests verify each method in isolation |
| OpenCode adapter 6 sync methods | Level 2 (Proxy) | Unit tests verify each method in isolation |
| Skills inline correctly (Gemini) | Level 1 (Sanity) | Check GEMINI.md contains expected sections without frontmatter |
| Symlinks created (OpenCode) | Level 1 (Sanity) | Check .opencode/{skills,agents,commands} have valid symlinks |
| Stale symlink cleanup (OpenCode) | Level 2 (Proxy) | Create stale symlink, verify removed after sync |
| MCP translation (both adapters) | Level 2 (Proxy) | Parse output config, verify structure and values |
| Permission mapping (both adapters) | Level 2 (Proxy) | Test conservative mapping (deny → most restrictive) |
| Integration: all 3 adapters | Level 2 (Proxy) | Sync same project to Codex/Gemini/OpenCode, verify all succeed |
| Full test project sync | Level 3 (Deferred) | Manual testing with real CLI tools (requires Gemini/OpenCode installed) |

**Level 1 checks to always include:**
- GEMINI.md exists and contains expected section headers (not YAML frontmatter)
- .opencode/{skills,agents,commands} directories exist with correct symlinks
- Config files (settings.json, opencode.json) are valid JSON with expected structure
- No broken symlinks in .opencode/ directories after sync

**Level 2 proxy metrics:**
- Each sync method returns SyncResult with expected synced/adapted counts
- Frontmatter successfully stripped from inlined content
- MCP servers have correct type discrimination (local vs remote)
- Permission settings map conservatively (no privilege escalation)

**Level 3 deferred items:**
- Real Gemini CLI loads GEMINI.md and activates skills correctly
- Real OpenCode loads agents/commands from .opencode/ via symlinks
- MCP servers connect successfully in both Gemini and OpenCode
- Manual verification of permission restrictions (tools blocked as expected)

## Production Considerations (from KNOWHOW.md)

**KNOWHOW.md is minimal** (no production notes from prior phases). Considerations derived from Phase 2 patterns:

### Known Failure Modes

- **Symlink creation fails on Windows without admin:**
  - Prevention: Use `create_symlink_with_fallback()` with junction → copy fallback chain
  - Detection: Check SyncResult.failed_files for "symlink failed" messages

- **GEMINI.md grows unbounded with many skills:**
  - Prevention: Limit inlined skill count (warn if >20 skills, suggest skill pruning)
  - Detection: Check GEMINI.md size, warn if >100KB

- **MCP server config overwrite loses custom settings:**
  - Prevention: Use merge pattern from Codex adapter (read existing, merge, write)
  - Detection: git diff shows unexpected deletions in settings.json/opencode.json

### Scaling Concerns

- **At current scale (3-10 skills):** Inline all skills into GEMINI.md works fine
- **At production scale (50+ skills):** Consider skill selection mechanism (only inline active skills, rest symlinked if Gemini adds symlink support)

### Common Implementation Traps

- **Not preserving env vars:** Gemini/OpenCode MCP configs support `${VAR}` syntax. Preserve literally, don't expand during sync.
  - Correct approach: Use `json.dumps()` which preserves string content, or manual escaping for special cases

- **Forgetting atomic writes:** Config file corruption on interrupted sync.
  - Correct approach: Use tempfile + os.replace pattern from Phase 1 toml_writer.py

## Code Examples

Verified patterns from Phase 2 and official documentation:

### Frontmatter Parsing (Reuse from Codex)

```python
# Source: src/adapters/codex.py lines 409-446
def _parse_frontmatter(self, content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from markdown content."""
    if not content.startswith('---'):
        return {}, content

    match = re.match(r'^---\n(.*?)\n---\n(.*)$', content, re.DOTALL)
    if not match:
        return {}, content

    frontmatter_text = match.group(1)
    body = match.group(2)

    frontmatter = {}
    for line in frontmatter_text.split('\n'):
        if ':' in line:
            key, val = line.split(':', 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            frontmatter[key] = val

    return frontmatter, body
```

### JSON Atomic Write (New utility needed)

```python
# Source: Extend Phase 1 pattern from toml_writer.py
import json
import os
import tempfile
from pathlib import Path

def write_json_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically using tempfile + os.replace."""
    from src.utils.paths import ensure_dir

    ensure_dir(path.parent)

    temp_fd = tempfile.NamedTemporaryFile(
        mode='w',
        dir=path.parent,
        suffix='.tmp',
        delete=False,
        encoding='utf-8'
    )
    temp_path = Path(temp_fd.name)

    try:
        json.dump(data, temp_fd, indent=2, ensure_ascii=False)
        temp_fd.flush()
        os.fsync(temp_fd.fileno())
        temp_fd.close()
        os.replace(str(temp_path), str(path))
    except Exception:
        if not temp_fd.closed:
            temp_fd.close()
        if temp_path.exists():
            temp_path.unlink()
        raise
```

### Stale Symlink Cleanup (OpenCode)

```python
# Source: New pattern for Phase 3
def _cleanup_stale_symlinks(self, directory: Path) -> int:
    """Remove symlinks pointing to non-existent sources.

    Returns:
        Count of removed stale symlinks
    """
    if not directory.is_dir():
        return 0

    removed = 0
    for item in directory.iterdir():
        if item.is_symlink():
            try:
                # resolve() raises if target doesn't exist
                if not item.resolve().exists():
                    item.unlink()
                    removed += 1
            except (OSError, RuntimeError):
                # Broken symlink or circular reference
                item.unlink()
                removed += 1

    return removed
```

### Gemini MCP Server Config Format

```json
// Source: https://geminicli.com/docs/tools/mcp-server/
{
  "mcpServers": {
    "server-name": {
      "command": "npx",
      "args": ["-y", "server-package"],
      "env": {
        "API_KEY": "$MY_API_KEY"
      },
      "timeout": 30000,
      "includeTools": ["tool1"],
      "excludeTools": ["tool2"]
    },
    "url-server": {
      "url": "https://api.example.com/sse",
      "headers": {
        "Authorization": "Bearer token"
      }
    }
  }
}
```

### OpenCode MCP Server Config Format

```json
// Source: https://opencode.ai/docs/mcp-servers/
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "local-server": {
      "type": "local",
      "command": ["npx", "-y", "server-package"],
      "environment": {
        "API_KEY": "${MY_API_KEY}"
      },
      "enabled": true
    },
    "remote-server": {
      "type": "remote",
      "url": "https://mcp.example.com",
      "headers": {
        "Authorization": "Bearer ${TOKEN}"
      },
      "enabled": true
    }
  }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact | Reference |
|--------------|------------------|--------------|--------|-----------|
| Codex-only sync | Multi-target adapter pattern | Phase 2 (2026-02-13) | Extensible to any AI CLI | Phase 2 verification |
| Custom per-target scripts | AdapterBase ABC with registry | Phase 2 (2026-02-13) | Zero core changes for new targets | src/adapters/base.py |
| Manual config editing | Automated sync with conservative permissions | Phase 1-2 (2026-02-13) | Reduces config drift across CLIs | Phase 1 foundation |
| Symlinks only | Adaptive: inline (Gemini) or symlink (OpenCode/Codex) | Phase 3 (planned) | Supports diverse target architectures | This research |

**Deprecated/outdated:**
- **Single-target cc2all script:** Replaced by multi-target HarnessSync with adapter pattern (Phase 1-2 renamed project)
- **Direct symlink without fallback:** Replaced by `create_symlink_with_fallback()` chain (Phase 1 paths.py)

## Open Questions

1. **Gemini npx mcp-remote vs direct URL config**
   - What we know: mcp-remote wrapper converts URL servers to stdio, official Gemini docs show both approaches
   - What's unclear: Which approach is more reliable? Does direct URL config handle auth correctly?
   - Recommendation: **Start with direct URL config** (simpler, no npx dependency). Add mcp-remote wrapper only if auth issues arise in testing.

2. **OpenCode skill loading priority**
   - What we know: `.opencode/skills/` has "highest priority" for project-local skills (official docs)
   - What's unclear: Does OpenCode merge skills from multiple directories or override entirely?
   - Recommendation: **Assume merge behavior** (safest). Verify in Level 3 testing with OpenCode CLI.

3. **Gemini tool name mapping**
   - What we know: Gemini uses `includeTools`/`excludeTools` with tool name strings
   - What's unclear: Do Gemini tool names match Claude Code exactly (e.g., "Write" vs "write_file")?
   - Recommendation: **Conservative default** — if tool name unclear, exclude from `includeTools` rather than risk permission leak. Document as known limitation.

4. **Stale symlink detection edge cases**
   - What we know: `Path.resolve().exists()` detects broken symlinks
   - What's unclear: Handling of circular symlinks or permission-denied targets
   - Recommendation: **Wrap in try/except** (OSError, RuntimeError). Treat as stale if resolve fails.

## Sources

### Primary (HIGH confidence)

**Official Documentation:**
- [Gemini CLI MCP Servers](https://geminicli.com/docs/tools/mcp-server/) — mcpServers configuration format
- [Gemini CLI GEMINI.md](https://geminicli.com/docs/cli/gemini-md/) — Context file format
- [Gemini CLI Agent Skills](https://geminicli.com/docs/cli/creating-skills/) — YAML frontmatter + markdown body
- [OpenCode MCP Servers](https://opencode.ai/docs/mcp-servers/) — Type-discriminated local/remote format
- [OpenCode Permissions](https://opencode.ai/docs/permissions/) — Permission system (allow/deny/ask)
- [OpenCode Agent Skills](https://opencode.ai/docs/skills) — Skills directory structure

**Codebase (Phase 2 proven patterns):**
- `/Users/edward.seo/dev/private/project/harness/HarnessSync/src/adapters/codex.py` — Frontmatter parsing, marker-based sections
- `/Users/edward.seo/dev/private/project/harness/HarnessSync/src/adapters/base.py` — AdapterBase ABC interface
- `/Users/edward.seo/dev/private/project/harness/HarnessSync/src/utils/toml_writer.py` — Atomic write pattern
- `/Users/edward.seo/dev/private/project/harness/HarnessSync/.planning/phases/02-adapter-framework-codex-sync/02-03-SUMMARY.md` — Phase 2 verification (100% pass)

### Secondary (MEDIUM confidence)

**Tools and Libraries:**
- [mcp-remote npm package](https://www.npmjs.com/package/mcp-remote) — Remote MCP wrapper tool
- [Mastering Agent Skills in Gemini CLI](https://danicat.dev/posts/agent-skills-gemini-cli/) — Community guide (2026)
- [Writing OpenCode Agent Skills](https://blog.devgenius.io/writing-opencode-agent-skills-a-practical-guide-with-examples-870ff24eec66) — Practical examples (Jan 2026)

**Blog Posts (Verified with official docs):**
- [How to Enable Claude Code & Gemini CLI Yolo Mode](https://apidog.com/blog/claude-code-gemini-yolo-mode/) — Yolo mode permissions
- [Gemini CLI Tutorial Series Part 3](https://medium.com/google-cloud/gemini-cli-tutorial-series-part-3-configuration-settings-via-settings-json-and-env-files-669c6ab6fd44) — settings.json format

### Tertiary (LOW confidence)

None — all research backed by official documentation or proven codebase patterns.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Python 3.10 stdlib proven in Phase 1-2 with zero issues
- Architecture patterns: HIGH - Adapter pattern proven in Phase 2 with 100% test pass
- Content transformation: HIGH - Official docs confirm Gemini inline requirement and OpenCode symlink support
- MCP translation: HIGH - Official schemas and examples for both targets
- Permission mapping: HIGH - Conservative mapping proven in Phase 2, adapted for new targets
- Pitfalls: MEDIUM - Derived from official docs and Phase 2 experience, not yet tested with Gemini/OpenCode

**Research date:** 2026-02-13
**Valid until:** 60 days (2026-04-14) — stable engineering domain, official docs unlikely to change rapidly

---

## Ready for Planning

Research complete. All 6 sync methods for both adapters have clear implementation paths based on:
1. Proven AdapterBase pattern from Phase 2
2. Official configuration format specifications
3. Conservative permission mapping strategy
4. Reusable code patterns (frontmatter parsing, atomic writes, symlink fallback)

**Key decision points for planner:**
1. **Plan structure:** Recommend 2 plans (Gemini adapter, OpenCode adapter + integration) or 3 plans (Gemini, OpenCode, integration separately)
2. **npx mcp-remote:** Use direct URL config first, add wrapper only if needed (defer to testing)
3. **Tool name mapping:** Document as known limitation, require manual verification in Level 3 testing

**No blockers identified.** Phase 2 provides all necessary infrastructure (AdapterBase, registry, SyncResult, atomic writes, symlink utilities).
