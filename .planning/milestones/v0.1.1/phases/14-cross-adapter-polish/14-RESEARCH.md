# Phase 14: Cross-Adapter Polish - Research

**Researched:** 2026-03-09
**Domain:** Configuration adapter field passthrough, env var translation, deduplication, settings preservation
**Confidence:** HIGH

## Summary

Phase 14 addresses four targeted gaps across the Codex and OpenCode adapters, plus a cross-cutting settings preservation concern for both Gemini and Codex. Each requirement is a well-scoped, low-risk change to existing adapter methods -- no new modules, no architectural changes.

The four requirements are: (1) CDX-09: pass through `cwd`, `enabled_tools`, `disabled_tools` MCP fields in Codex adapter, (2) OC-10: translate `${VAR_NAME}` to `{env:VAR_NAME}` in OpenCode MCP headers, (3) OC-11: skip skill symlinks for skills already discoverable from `.claude/skills/`, and (4) PRES-01: preserve non-synced sections when writing Gemini `settings.json` and Codex `config.toml`.

**Primary recommendation:** Implement each requirement as an isolated change to the respective adapter method. No new dependencies, no new files needed.

## Paper-Backed Recommendations

This phase is purely an engineering polish task on an internal sync tool. There are no academic papers relevant to these specific adapter transformations. All recommendations are based on codebase analysis and target CLI documentation.

### Recommendation 1: CDX-09 -- Add `cwd` passthrough to `format_mcp_server_toml`

**Recommendation:** Add `cwd` field handling in `src/utils/toml_writer.py::format_mcp_server_toml()` alongside the existing `enabled_tools`/`disabled_tools` handling.

**Evidence:**
- Codex CLI docs (verified in `.planning/research/v0.1.1/CODEX-LATEST.md` lines 271-287) show `cwd` as a valid MCP server field.
- `enabled_tools` and `disabled_tools` are already handled in `format_mcp_server_toml()` (lines 201-205 of `toml_writer.py`). The `cwd` field is missing.
- The Codex adapter's `sync_mcp`/`sync_mcp_scoped` pass config dicts directly through to `format_mcp_server_toml`, so no adapter-level changes needed -- just the TOML formatter.

**Confidence:** HIGH -- verified against both Codex docs and existing codebase.

**Implementation detail:**
- Add `cwd` string field handling in `format_mcp_server_toml()` after the `command` line (line ~177).
- Format: `cwd = "path/to/dir"` (standard TOML string).
- Location: `/Users/neo/Developer/Projects/HarnessSync/src/utils/toml_writer.py`

### Recommendation 2: OC-10 -- Translate `${VAR}` to `{env:VAR}` in OpenCode MCP headers

**Recommendation:** Add a header-specific env var translation step in `OpenCodeAdapter.sync_mcp()` that rewrites `${VAR_NAME}` references to `{env:VAR_NAME}` syntax within the `headers` dict of remote MCP servers.

**Evidence:**
- OpenCode docs (`.planning/research/v0.1.1/OPENCODE-LATEST.md` line 211): "Env var syntax: Uses `{env:VAR_NAME}` (curly braces), NOT `${VAR_NAME}` (dollar-curly)"
- OpenCode docs example (line 196): `"headers": { "Authorization": "Bearer {env:API_KEY}" }`
- Current code (`opencode.py` lines 303-305) passes `headers` through unchanged, which means `${VAR}` from Claude Code source config remains untranslated.
- The translation only applies to `headers` values in remote (URL-based) MCP servers. The `environment` dict for local servers uses literal values, not interpolation.

**Confidence:** HIGH -- directly from OpenCode documentation.

**Implementation detail:**
- Create a helper function `translate_env_vars_for_opencode_headers(headers: dict) -> dict` in `env_translator.py` or inline in the adapter.
- Regex: replace `${([A-Z_][A-Z0-9_]*)}` with `{env:\1}` in header string values.
- Also handle `${VAR:-default}` -- strip the default syntax since OpenCode's `{env:VAR}` does not support defaults (warn if defaults found).
- Apply only to `headers` dict values, not to `url` or `command` fields.
- Apply in both `sync_mcp()` and `sync_mcp_scoped()`.
- Location: `/Users/neo/Developer/Projects/HarnessSync/src/adapters/opencode.py` and optionally `/Users/neo/Developer/Projects/HarnessSync/src/utils/env_translator.py`

### Recommendation 3: OC-11 -- Skip skill symlinks for natively discovered skills

**Recommendation:** In `OpenCodeAdapter.sync_skills()`, check whether each skill directory already resides under `.claude/skills/` (which OpenCode natively discovers). If so, skip the symlink creation for that skill.

**Evidence:**
- OpenCode natively reads `.claude/skills/` directory (`.planning/STATE.md` line 75, `.planning/research/v0.1.1/OPENCODE-LATEST.md`).
- Current `sync_skills()` (opencode.py lines 113-157) creates symlinks for ALL skills into `.opencode/skills/`, including those from `.claude/skills/` -- causing duplicates.
- The SourceReader `get_skills()` returns skills from both `~/.claude/skills/` (user scope) and `.claude/skills/` (project scope). Only project-scope skills from `.claude/skills/` are natively discovered by OpenCode.

**Confidence:** HIGH -- confirmed by OpenCode docs and codebase analysis.

**Implementation detail:**
- In `sync_skills()`, before creating a symlink, check if `source_path` is under `self.project_dir / ".claude" / "skills"`.
- If yes, skip with a message like `"{name}: natively discovered by OpenCode"`.
- User-scope skills (`~/.claude/skills/`) and plugin skills still need symlinks.
- Location: `/Users/neo/Developer/Projects/HarnessSync/src/adapters/opencode.py`

### Recommendation 4: PRES-01 -- Preserve non-synced sections in config files

**Recommendation:** Modify the Codex `_write_mcp_to_path` and `sync_settings` methods to preserve ALL existing top-level keys (not just `sandbox_mode`, `approval_policy`, and `mcp_servers`). Modify the Gemini `_write_mcp_to_settings` and `sync_settings` methods to preserve all existing keys (not just `mcpServers` and `tools`).

**Evidence:**
- **Codex clobbering bug:** `_write_mcp_to_path()` (codex.py lines 385-397) only preserves `sandbox_mode` and `approval_policy` from existing config. Any `[agents]`, `[profiles]`, `[features]`, or other user-defined sections are lost.
- `_build_config_toml()` (codex.py lines 689-712) reconstructs the file from only settings_section + mcp_section, discarding everything else.
- `sync_settings()` (codex.py lines 467-474) similarly only preserves `mcp_servers`, losing other sections.
- **Gemini clobbering bug:** `_write_mcp_to_settings()` (gemini.py lines 396-451) reads existing JSON with `read_json_safe()` then only adds `mcpServers` keys. This actually works correctly via `setdefault` -- existing keys ARE preserved because we update into the existing dict.
- `sync_settings()` (gemini.py lines 471-506) reads existing and sets `tools` key. Same dict-update pattern preserves other keys. **Gemini JSON is NOT clobbered** -- the JSON dict update pattern naturally preserves keys.
- The Codex problem is in the TOML serialization: `_build_config_toml` only knows about settings and MCP sections, so it drops everything else.

**Confidence:** HIGH -- confirmed by reading the actual implementation.

**Implementation detail -- Codex (the real bug):**
- Option A (simpler): Store the raw TOML content of non-synced sections and re-emit them. Read existing file, identify sections we manage (`sandbox_mode`, `approval_policy`, `[mcp_servers.*]`), preserve everything else verbatim.
- Option B (more robust): Extend `_build_config_toml` to accept a `preserved_sections: str` parameter containing raw TOML lines for sections we do not manage. When reading existing config, capture any lines/tables that are not `sandbox_mode`, `approval_policy`, or `[mcp_servers.*]`.
- Recommended: Option B. Read existing file as raw text, extract non-managed lines/tables, pass to `_build_config_toml` for re-emission.

**Implementation detail -- Gemini:**
- The Gemini adapter already preserves non-synced fields correctly via JSON dict merging (`read_json_safe` + `setdefault`/`update` + `write_json_atomic`). No changes needed for Gemini MCP sync or settings sync -- the success criterion in the phase description is already met by the current implementation.
- Verify with a test to confirm.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.9+ | All implementation | Zero-dependency constraint |
| pathlib | stdlib | Path manipulation | Already used throughout |
| re | stdlib | Regex for env var translation | Already used in env_translator.py |
| json | stdlib | JSON read/write for Gemini/OpenCode | Already used |

### Supporting
No additional libraries needed. All changes use existing utilities.

## Architecture Patterns

### Recommended Project Structure
No structural changes needed. All modifications are to existing files:
```
src/
  adapters/
    codex.py          # CDX-09 (minor), PRES-01 (Codex config preservation)
    opencode.py       # OC-10 (header translation), OC-11 (skill dedup)
  utils/
    toml_writer.py    # CDX-09 (add cwd field)
    env_translator.py # OC-10 (add opencode header translation function)
```

### Pattern 1: Field Passthrough (CDX-09)
**What:** When the source config contains an optional field, pass it through to the target format if the target supports it.
**When to use:** Any new MCP field the source supports that the target also supports.
**Example:**
```python
# In format_mcp_server_toml():
if 'cwd' in config and isinstance(config['cwd'], str):
    lines.append(f'cwd = {format_toml_value(config["cwd"])}')
```

### Pattern 2: Syntax Translation (OC-10)
**What:** Replace source syntax with target-specific equivalent using regex.
**When to use:** When source and target use different syntax for the same concept.
**Example:**
```python
import re
VAR_PATTERN = re.compile(r'\$\{([A-Z_][A-Z0-9_]*)(:-[^}]+)?\}')

def translate_env_for_opencode(value: str) -> str:
    """Translate ${VAR} to {env:VAR} for OpenCode."""
    return VAR_PATTERN.sub(lambda m: f'{{env:{m.group(1)}}}', value)
```

### Pattern 3: Native Discovery Skip (OC-11)
**What:** Before creating a symlink, check if the target CLI natively discovers the source path.
**When to use:** When the target CLI has built-in path scanning that would pick up the same content.
**Example:**
```python
claude_skills_dir = self.project_dir / ".claude" / "skills"
if source_path.is_relative_to(claude_skills_dir):
    result.skipped += 1
    result.skipped_files.append(f"{name}: natively discovered by OpenCode")
    continue
```

### Pattern 4: Non-Destructive Config Write (PRES-01)
**What:** When writing to a config file, preserve sections the tool does not manage.
**When to use:** When the target config file may contain user-defined sections beyond what HarnessSync writes.
**Example approach for TOML:**
```python
def _extract_preserved_sections(self, config_path: Path) -> str:
    """Extract TOML sections we don't manage for re-emission."""
    if not config_path.exists():
        return ''
    content = config_path.read_text(encoding='utf-8')
    # Filter out managed sections (comments, sandbox_mode, approval_policy, [mcp_servers.*])
    # Return remaining lines as raw TOML
    ...
```

### Anti-Patterns to Avoid
- **Clobbering:** Never reconstruct a config file from only the fields you manage. Always read-then-merge.
- **Over-translation:** Do not translate env vars in fields that do not support interpolation (e.g., `environment` dict values in OpenCode local servers are literal, not interpolated).
- **Broad symlink creation:** Do not create symlinks for content the target already discovers natively.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TOML parsing | Full TOML parser | Existing `parse_toml_simple` + raw text preservation | Our custom parser handles what we generate; raw text preservation avoids needing a full parser |
| JSON merging | Custom merge logic | Python dict `update()`/`setdefault()` | Already works correctly in Gemini adapter |
| Env var regex | Custom string scanning | `re.compile()` with existing `VAR_PATTERN` | Pattern already defined in `env_translator.py` |

## Common Pitfalls

### Pitfall 1: `is_relative_to()` requires Python 3.9+
**What goes wrong:** Using `Path.is_relative_to()` may fail on older Python versions.
**Why it happens:** This method was added in Python 3.9.
**How to avoid:** The project already targets 3.9+, so this is safe. But an alternative is `str(source_path).startswith(str(claude_skills_dir))`.
**Warning signs:** CI failure on Python 3.9.

### Pitfall 2: Codex TOML preservation losing section ordering
**What goes wrong:** When extracting and re-emitting non-managed TOML sections, ordering may change.
**Why it happens:** Dict iteration order is insertion-order in Python 3.7+, but TOML table ordering matters for readability.
**How to avoid:** Preserve raw text lines rather than parsing and re-serializing. Read the file as text, identify managed regions, keep everything else as-is.

### Pitfall 3: Regex over-matching in header env var translation
**What goes wrong:** Translating `${VAR}` in non-header fields (like `url`) where `${VAR}` might be intentional.
**Why it happens:** Applying translation too broadly.
**How to avoid:** Only translate within the `headers` dict of remote servers, not in `url`, `command`, or `environment`.

### Pitfall 4: Narrow fix leaving other instances broken
**What goes wrong:** Fix OC-10 in `sync_mcp()` but forget `sync_mcp_scoped()`, or fix PRES-01 in `_write_mcp_to_path()` but forget `sync_settings()`.
**Why it happens:** Multiple code paths write the same config file.
**How to avoid:** Search for all callers of the config write functions and ensure all paths use the preservation logic. Per user's preference: always check the entire codebase for the same pattern.

### Pitfall 5: Gemini settings.json false positive
**What goes wrong:** Spending time "fixing" Gemini settings preservation when it already works.
**Why it happens:** The phase description says "Writing Gemini settings.json preserves existing hooks, security, general..." but the current JSON dict-merge implementation already does this.
**How to avoid:** Write a verification test first. Confirm behavior before changing code. The fix may only need a test, not a code change.

## Experiment Design

Not applicable -- this is a polish phase with deterministic correctness criteria, not an experimental/R&D task.

### Verification Approach
Each requirement has clear pass/fail criteria testable with unit tests.

## Verification Strategy

### Recommended Verification Tiers for This Phase

| Item | Recommended Tier | Rationale |
|------|-----------------|-----------|
| CDX-09: `cwd` field appears in TOML output | Level 1 (Sanity) | Simple string presence check |
| CDX-09: `enabled_tools`/`disabled_tools` still work | Level 1 (Sanity) | Regression check |
| OC-10: `${VAR}` becomes `{env:VAR}` in headers | Level 1 (Sanity) | Regex substitution check |
| OC-10: Non-header fields unchanged | Level 1 (Sanity) | Negative test |
| OC-11: `.claude/skills/` paths skipped | Level 1 (Sanity) | Path comparison check |
| OC-11: User-scope skills still symlinked | Level 1 (Sanity) | Ensure no over-filtering |
| PRES-01: Codex config preserves `[agents]` section | Level 2 (Proxy) | Requires file round-trip test |
| PRES-01: Gemini config preserves `hooks` key | Level 2 (Proxy) | Requires file round-trip test |
| Full sync pipeline preserves all fields | Level 3 (Deferred) | Needs integration test with real configs |

**Level 1 checks to always include:**
- CDX-09: `format_mcp_server_toml("test", {"command": "x", "cwd": "/tmp"})` contains `cwd = "/tmp"`
- OC-10: Header `{"Authorization": "Bearer ${API_KEY}"}` becomes `{"Authorization": "Bearer {env:API_KEY}"}`
- OC-11: Skill with source path under `.claude/skills/` is skipped
- PRES-01: Write MCP to codex config.toml that already has `[agents]` section, verify `[agents]` survives

**Level 2 proxy metrics:**
- Round-trip test: create config with non-managed sections, run sync, verify sections preserved
- Sync with mixed skills (user-scope + project .claude/skills/), verify correct skip/sync counts

**Level 3 deferred items:**
- Full orchestrator run with real-world configs from multiple CLIs

## Production Considerations (from KNOWHOW.md)

KNOWHOW.md is empty (initialized placeholder). No production considerations documented.

### Known Failure Modes
- **Config corruption on interrupted write:** Already mitigated by `write_toml_atomic` and `write_json_atomic` patterns using tempfile + os.replace.
- **Permission errors on config files:** Already handled with try/except in adapter methods.

### Common Implementation Traps
- **Hardcoded paths:** Per MEMORY.md, never hardcode `~/.claude`, `~/.codex`, `~/.gemini`. Use `self.project_dir` for target paths. All current code follows this pattern.
- **Narrow fixes:** Per user preference, always check the entire codebase for the same pattern when fixing a bug.

## Code Examples

### CDX-09: Add `cwd` to TOML formatter
```python
# In format_mcp_server_toml(), after command handling:
# Source: codebase analysis of toml_writer.py
if 'cwd' in config and isinstance(config['cwd'], str):
    lines.append(f'cwd = {format_toml_value(config["cwd"])}')
```

### OC-10: OpenCode header env var translation
```python
# New function in env_translator.py
# Source: OpenCode docs -- {env:VAR_NAME} syntax
def translate_env_vars_for_opencode_headers(headers: dict) -> tuple[dict, list[str]]:
    """Translate ${VAR} references in headers to OpenCode {env:VAR} syntax."""
    translated = {}
    warnings = []
    for key, value in headers.items():
        if isinstance(value, str):
            # Replace ${VAR_NAME} with {env:VAR_NAME}
            new_value = re.sub(
                r'\$\{([A-Z_][A-Z0-9_]*)(:-[^}]+)?\}',
                lambda m: f'{{env:{m.group(1)}}}',
                value
            )
            if m := re.search(r'\$\{[A-Z_][A-Z0-9_]*:-([^}]+)\}', value):
                warnings.append(
                    f"Header '{key}': default value syntax not supported by OpenCode, stripped"
                )
            translated[key] = new_value
        else:
            translated[key] = value
    return translated, warnings
```

### OC-11: Skip natively discovered skills
```python
# In OpenCodeAdapter.sync_skills(), before symlink creation:
# Source: codebase analysis
claude_skills_dir = self.project_dir / ".claude" / "skills"
for name, source_path in skills.items():
    # Skip skills OpenCode natively discovers from .claude/skills/
    try:
        if source_path.is_relative_to(claude_skills_dir):
            result.skipped += 1
            result.skipped_files.append(f"{name}: natively discovered by OpenCode")
            continue
    except (ValueError, TypeError):
        pass  # Not relative, proceed with symlink
    # ... existing symlink creation ...
```

### PRES-01: Codex config preservation
```python
# In CodexAdapter._write_mcp_to_path() and sync_settings():
# Source: codebase analysis
def _extract_unmanaged_toml(self, config_path: Path) -> str:
    """Extract TOML sections not managed by HarnessSync."""
    if not config_path.exists():
        return ''
    content = config_path.read_text(encoding='utf-8')
    unmanaged_lines = []
    in_managed_section = False
    for line in content.split('\n'):
        stripped = line.strip()
        # Skip comments and blank lines at top
        if stripped.startswith('#') and ('HarnessSync' in stripped or 'MCP servers' in stripped):
            continue
        # Skip managed top-level keys
        if stripped.startswith('sandbox_mode') or stripped.startswith('approval_policy'):
            continue
        # Skip MCP server sections
        if stripped.startswith('[mcp_servers'):
            in_managed_section = True
            continue
        if stripped.startswith('[') and in_managed_section:
            # New section that isn't mcp_servers -- stop skipping
            if not stripped.startswith('[mcp_servers'):
                in_managed_section = False
        if in_managed_section:
            continue
        unmanaged_lines.append(line)
    return '\n'.join(unmanaged_lines).strip()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Codex: reconstruct config.toml from scratch | Should: read-merge-write preserving unmanaged sections | This phase | Prevents clobbering user config |
| OpenCode: pass `${VAR}` in headers verbatim | Should: translate to `{env:VAR}` | This phase | Headers with env vars actually work in OpenCode |
| OpenCode: symlink ALL skills | Should: skip `.claude/skills/` (native discovery) | This phase | No duplicate skills |

## Open Questions

1. **Codex `env_vars` field**
   - What we know: Codex docs mention `env_vars = ["ALLOWED_VAR"]` in MCP config (line 273 of CODEX-LATEST.md).
   - What's unclear: Whether HarnessSync should pass this through. Claude Code source configs do not have an equivalent field.
   - Recommendation: Defer to future phase. Not in CDX-09 scope.

2. **OpenCode `{env:VAR}` in non-header fields**
   - What we know: OpenCode uses `{env:VAR}` syntax for config-level variable substitution (model names, API keys, etc.).
   - What's unclear: Whether `environment` dict values in local MCP servers also use `{env:VAR}` or literal values.
   - Recommendation: For OC-10, only translate `headers` as specified. `environment` dict values are literal (the server process receives them as-is).

3. **Gemini PRES-01 already working?**
   - What we know: The Gemini adapter uses `read_json_safe()` + dict merging + `write_json_atomic()`, which inherently preserves all existing keys.
   - What's unclear: Whether there are edge cases (e.g., nested key overwriting).
   - Recommendation: Write a verification test. If it passes, PRES-01 for Gemini is just adding the test, no code change.

## Sources

### Primary (HIGH confidence)
- `/Users/neo/Developer/Projects/HarnessSync/src/adapters/codex.py` -- current Codex adapter implementation
- `/Users/neo/Developer/Projects/HarnessSync/src/adapters/opencode.py` -- current OpenCode adapter implementation
- `/Users/neo/Developer/Projects/HarnessSync/src/adapters/gemini.py` -- current Gemini adapter implementation
- `/Users/neo/Developer/Projects/HarnessSync/src/utils/toml_writer.py` -- TOML formatting utilities
- `/Users/neo/Developer/Projects/HarnessSync/src/utils/env_translator.py` -- env var translation utilities
- `.planning/research/v0.1.1/CODEX-LATEST.md` -- Codex CLI format documentation
- `.planning/research/v0.1.1/OPENCODE-LATEST.md` -- OpenCode CLI format documentation
- `.planning/research/v0.1.1/GEMINI-LATEST.md` -- Gemini CLI format documentation
- `.planning/REQUIREMENTS.md` -- CDX-09, OC-10, OC-11, PRES-01 requirement definitions

### Secondary (MEDIUM confidence)
- `.planning/STATE.md` -- OpenCode native `.claude/skills/` discovery note

### Tertiary (LOW confidence)
- None. All findings verified against codebase and documented CLI formats.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries needed, all stdlib
- Architecture: HIGH - all changes to existing methods, no structural changes
- Recommendations: HIGH - verified against codebase and CLI documentation
- Pitfalls: HIGH - derived from codebase analysis and user-stated preferences

**Research date:** 2026-03-09
**Valid until:** 2026-04-09 (stable -- target CLI formats unlikely to change in 30 days)
