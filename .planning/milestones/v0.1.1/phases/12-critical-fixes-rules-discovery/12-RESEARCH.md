# Phase 12: Critical Fixes & Rules Discovery - Research

**Researched:** 2026-03-09
**Domain:** Configuration sync adapter correctness / Claude Code rules discovery
**Confidence:** HIGH

## Summary

This phase addresses two distinct workstreams: (1) fixing broken adapter outputs for Codex, Gemini, and OpenCode, and (2) extending SourceReader to discover `.claude/rules/` directory content. The adapter fixes are all verified against current official documentation and are straightforward value/key corrections. The rules discovery is a well-understood file-system walk with YAML frontmatter parsing.

The Codex adapter has two bugs: it uses `'on-failure'` (an invalid approval_policy value) and writes to `codex.toml` instead of the official `config.toml`. The Gemini adapter uses deprecated v1 keys (`blockedTools`/`allowedTools`) instead of v2 keys (`allowed`/`exclude`) under `tools`. The OpenCode adapter uses a deprecated `permissions.mode` structure instead of the current per-tool `permission` (singular) format with `allow`/`ask`/`deny` values.

**Primary recommendation:** Fix each adapter's output format based on verified official documentation, then add rules directory discovery to SourceReader using recursive `Path.rglob('*.md')` with simple frontmatter parsing (reusing existing `_parse_frontmatter` patterns).

## Source-Backed Recommendations

Every recommendation below cites specific evidence from official documentation.

### Recommendation 1: Fix Codex approval_policy Value

**Recommendation:** Change `approval_policy = 'on-failure'` to `approval_policy = 'on-request'` in `sync_settings()`.
**Evidence:**
- [Codex Config Reference](https://developers.openai.com/codex/config-reference) -- Valid values are `untrusted`, `on-request`, `never`, and `reject` table. `on-failure` is NOT a valid value.
- [Codex Config Basics](https://developers.openai.com/codex/config-basic/) -- Confirms `config.toml` uses `on-request` for interactive approval.

**Confidence:** HIGH -- Official OpenAI documentation explicitly lists valid values.
**Current bug location:** `src/adapters/codex.py` line 453: `approval_policy = 'on-failure'`
**Fix:** Change to `approval_policy = 'on-request'`

### Recommendation 2: Fix Codex Config Filename

**Recommendation:** Change `CONFIG_TOML = "codex.toml"` to `CONFIG_TOML = "config.toml"` in the Codex adapter.
**Evidence:**
- [Codex Config Reference](https://developers.openai.com/codex/config-reference) -- States config file is `config.toml` at `~/.codex/config.toml` (user) and `.codex/config.toml` (project).
- [Codex Config Basics](https://developers.openai.com/codex/config-basic/) -- Confirms filename is `config.toml`.

**Confidence:** HIGH -- Official OpenAI documentation is unambiguous.
**Current bug location:** `src/adapters/codex.py` line 39: `CONFIG_TOML = "codex.toml"`
**Scope of fix:** This constant is referenced in `sync_mcp()`, `sync_mcp_scoped()`, `sync_settings()`, and `_read_existing_config()`. Changing the constant fixes all locations. Also update line 348 where `user_path = self.project_dir / CONFIG_TOML` writes to project root (should this be `.codex/config.toml`?). The existing `codex.toml` in the project root is evidence of this bug in production.

### Recommendation 3: Fix Gemini Tools Config Keys

**Recommendation:** Change `blockedTools` to `exclude` and `allowedTools` to `allowed` under the `tools` key in settings.json output.
**Evidence:**
- [Gemini CLI Configuration](https://google-gemini.github.io/gemini-cli/docs/get-started/configuration.html) -- Documents `tools.allowed` (bypass confirmation) and `tools.exclude` (exclude from discovery) as the correct field names. Does NOT mention `allowedTools` or `blockedTools`.

**Confidence:** HIGH -- Official Google Gemini CLI documentation.
**Current bug location:** `src/adapters/gemini.py` lines 485 and 492: writes `blockedTools` and `allowedTools`.
**Fix:** Change to `exclude` and `allowed` respectively.

### Recommendation 4: Rewrite OpenCode Permission Sync

**Recommendation:** Replace `permissions.mode` structure with `permission` (singular) per-tool format using `allow`/`ask`/`deny` values.
**Evidence:**
- [OpenCode Config Docs](https://opencode.ai/docs/config/) -- Uses `permission` (singular) key with per-tool entries.
- [OpenCode Permissions Docs](https://opencode.ai/docs/permissions) -- Lists identifiers: `read`, `edit`, `glob`, `grep`, `list`, `bash`, `task`, `skill`, `lsp`, `todoread`, `todowrite`, `webfetch`, `websearch`, `codesearch`, `external_directory`, `doom_loop`. Bash supports wildcard patterns like `"git *": "allow"`.

**Confidence:** HIGH -- Official OpenCode documentation.
**Current bug location:** `src/adapters/opencode.py` lines 403-418: writes `permissions` (plural) with `mode` key.
**Fix:** Rewrite to output `permission` (singular) with per-tool `allow`/`ask`/`deny` entries. Map Claude Code allowed tools to bash patterns.

### Recommendation 5: Rules Directory Discovery in SourceReader

**Recommendation:** Add `.claude/rules/` discovery to SourceReader using `Path.rglob('*.md')` with YAML frontmatter parsing for `paths:` field.
**Evidence:**
- [Claude Code Memory Docs](https://code.claude.com/docs/en/memory) -- Documents `.claude/rules/` directory with recursive subdirectory support.
- [Claude Fast Rules Guide](https://claudefa.st/blog/guide/mechanics/rules-directory) -- Confirms recursive discovery, YAML frontmatter with `paths:` field for file scoping, user-level `~/.claude/rules/` support.

**Confidence:** HIGH -- Official Anthropic documentation and community verification.
**Implementation approach:**
1. Walk `.claude/rules/` and `~/.claude/rules/` recursively with `rglob('*.md')`
2. Parse YAML frontmatter for `paths:` field (single string or list)
3. Return structured data: `[{path, content, scope_patterns}]`
4. Rules without `paths:` frontmatter load unconditionally

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pathlib | stdlib | File path operations, rglob | Already used throughout codebase |
| re | stdlib | Frontmatter regex parsing | Already used in all adapters |
| json | stdlib | JSON read/write for settings | Already used throughout |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| PyYAML | - | NOT needed | Simple frontmatter parsing is sufficient; existing adapters already have `_parse_frontmatter()` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff | Rationale |
|------------|-----------|----------|-----------|
| Custom frontmatter parser | python-frontmatter lib | Adds dependency for simple use case | Existing `_parse_frontmatter()` pattern in adapters handles this adequately |
| PyYAML | Custom regex | PyYAML handles edge cases | Rules frontmatter is trivially simple (just `paths:` key); no need for full YAML parser |

## Architecture Patterns

### Recommended Project Structure
```
src/
├── source_reader.py     # Add get_rules_from_dir() or extend get_rules()
├── adapters/
│   ├── codex.py         # Fix CONFIG_TOML, approval_policy
│   ├── gemini.py        # Fix tools config keys
│   └── opencode.py      # Rewrite permission format
```

### Pattern 1: Extend Existing get_rules() Return Type
**What:** Change `get_rules()` to return structured data instead of plain string, OR add a separate `get_rules_files()` method that returns `list[dict]` with path, content, and scope_patterns.
**When to use:** When rules need metadata (path patterns) alongside content.
**Example:**
```python
# Source: Existing pattern in SourceReader
def get_rules_files(self) -> list[dict]:
    """Return list of rule dicts with path, content, scope_patterns."""
    rules = []

    if self.scope in ("user", "all"):
        user_rules_dir = self.cc_home / "rules"
        if user_rules_dir.is_dir():
            for md_file in sorted(user_rules_dir.rglob("*.md")):
                if md_file.is_file():
                    content = md_file.read_text(encoding='utf-8', errors='replace')
                    frontmatter, body = self._parse_frontmatter(content)
                    rules.append({
                        'path': md_file,
                        'content': body,
                        'scope_patterns': self._extract_paths(frontmatter),
                        'scope': 'user',
                    })

    if self.scope in ("project", "all") and self.project_dir:
        proj_rules_dir = self.project_dir / ".claude" / "rules"
        if proj_rules_dir.is_dir():
            for md_file in sorted(proj_rules_dir.rglob("*.md")):
                if md_file.is_file():
                    content = md_file.read_text(encoding='utf-8', errors='replace')
                    frontmatter, body = self._parse_frontmatter(content)
                    rules.append({
                        'path': md_file,
                        'content': body,
                        'scope_patterns': self._extract_paths(frontmatter),
                        'scope': 'project',
                    })

    return rules
```

### Pattern 2: OpenCode Permission Mapping
**What:** Map Claude Code allowed/denied tools to OpenCode per-tool permission format.
**When to use:** In OpenCode `sync_settings()`.
**Example:**
```python
# Source: Official OpenCode docs (https://opencode.ai/docs/permissions)
def _map_permissions(self, settings: dict) -> dict:
    permissions = settings.get('permissions', {})
    allow_list = permissions.get('allow', [])
    deny_list = permissions.get('deny', [])

    permission_config = {}

    # Map Claude Code tool names to OpenCode permission identifiers
    tool_mapping = {
        'Bash': 'bash',
        'Read': 'read',
        'Write': 'edit',
        'Edit': 'edit',
        'Glob': 'glob',
        'Grep': 'grep',
        'WebFetch': 'webfetch',
        'WebSearch': 'websearch',
        'TodoWrite': 'todowrite',
        'TodoRead': 'todoread',
    }

    # Process deny list
    for tool in deny_list:
        oc_tool = tool_mapping.get(tool)
        if oc_tool:
            permission_config[oc_tool] = 'deny'

    # Process allow list (bash gets pattern matching)
    for tool in allow_list:
        if tool.startswith('Bash(') and tool.endswith(')'):
            # Extract bash pattern: Bash(git commit:*) -> "git commit *"
            pattern = tool[5:-1].replace(':', ' ')
            permission_config.setdefault('bash', {})
            if isinstance(permission_config.get('bash'), str):
                permission_config['bash'] = {'*': permission_config['bash']}
            permission_config['bash'][f"{pattern} *"] = 'allow'
        else:
            oc_tool = tool_mapping.get(tool)
            if oc_tool:
                permission_config[oc_tool] = 'allow'

    return permission_config
```

### Anti-Patterns to Avoid
- **Breaking backward compatibility of get_rules():** The existing `get_rules()` method returns a string. Changing its return type would break all callers. Add a new method instead, or ensure the orchestrator handles both.
- **Hardcoding `~/.claude` paths:** Use `self.cc_home` for user-level rules directory, per the MEMORY.md note about multi-account support.
- **Duplicating frontmatter parsing:** Three adapters each have their own `_parse_frontmatter()`. For SourceReader, extract a shared utility or use a minimal inline version.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML frontmatter parsing | Full YAML parser | Simple regex extraction (existing pattern) | Rules frontmatter only uses `paths:` key; full YAML is overkill |
| Glob pattern matching | Custom glob matcher | `fnmatch.fnmatch()` or `pathlib.PurePath.match()` | If adapters need to evaluate path patterns, use stdlib |
| TOML writing | Custom TOML serializer | Existing `toml_writer.py` utility | Already has `write_toml_atomic`, `format_mcp_servers_toml` |

**Key insight:** All fixes are value/key changes in existing code. No new libraries or complex logic needed.

## Common Pitfalls

### Pitfall 1: Changing get_rules() Return Type
**What goes wrong:** Changing `get_rules()` from string to list[dict] breaks the orchestrator (line 93-97 in orchestrator.py) which expects a string.
**Why it happens:** Temptation to modify existing API instead of adding new method.
**How to avoid:** Add `get_rules_files()` as a NEW method. Keep `get_rules()` backward-compatible. Update orchestrator to call `get_rules_files()` and pass structured data to adapters.
**Warning signs:** Test failures in orchestrator, TypeError on string operations.

### Pitfall 2: Codex CONFIG_TOML Scope Confusion
**What goes wrong:** The Codex adapter writes to different paths for user vs project scope. Line 348 writes `user_path = self.project_dir / CONFIG_TOML` (project root) while line 294 writes to `.codex/config.toml`.
**Why it happens:** Unclear scope routing in `sync_mcp_scoped()`.
**How to avoid:** Verify correct paths: user-scope should go to `~/.codex/config.toml`, project-scope to `.codex/config.toml`. The current code may need path corrections beyond just the filename.
**Warning signs:** Config files appearing in unexpected locations.

### Pitfall 3: OpenCode Permission Key Collision
**What goes wrong:** Existing `opencode.json` files in the wild have `"permissions": {"mode": "default"}`. New format uses `"permission"` (singular). Both could coexist causing confusion.
**Why it happens:** Migration from old format to new.
**How to avoid:** When writing new format, remove old `permissions` key if present. Write only `permission` (singular).
**Warning signs:** Both `permissions` and `permission` keys in output JSON.

### Pitfall 4: Frontmatter Parsing for YAML Lists
**What goes wrong:** The `paths:` field can be a single string OR a YAML list. Existing `_parse_frontmatter()` only handles simple `key: value` lines.
**Why it happens:** YAML lists use either inline `[a, b]` or multi-line `- item` format.
**How to avoid:** Handle three cases: (1) `paths: pattern` single string, (2) `paths:` followed by `- pattern` lines, (3) no paths field.
**Warning signs:** Rules with multiple path patterns not being parsed correctly.

### Pitfall 5: Narrow Fix Syndrome
**What goes wrong:** Fixing one instance of a pattern but missing others. Per MEMORY.md: "ALWAYS check the entire codebase for the same pattern."
**Why it happens:** Focusing on the specific requirement without scanning broadly.
**How to avoid:** After each fix, grep the entire codebase for related patterns (e.g., after fixing `codex.toml`, grep for any other references to the old name).
**Warning signs:** User frustration from repeated narrow fixes.

## Experiment Design

### Recommended Experimental Setup

This phase is not R&D -- it is correctness-focused bug fixing and feature addition. The "experiment" is integration testing.

**Independent variables:** Input configuration (Claude Code settings with various permission combinations)
**Dependent variables:** Output file content (correct keys, values, structure)
**Controlled variables:** Adapter code, file system state

**Baseline comparison:**
- Method: Current broken output (codex.toml with on-failure, blockedTools, permissions.mode)
- Expected: Corrected output matching official docs
- Target: 100% correctness for all output formats

**Test matrix:**
1. Codex: auto-approve settings -> `approval_policy = 'on-request'` (not 'on-failure')
2. Codex: MCP servers -> written to `config.toml` (not `codex.toml`)
3. Gemini: deny list -> `tools.exclude` (not `tools.blockedTools`)
4. Gemini: allow list -> `tools.allowed` (not `tools.allowedTools`)
5. OpenCode: deny list -> `permission.{tool}: "deny"` (not `permissions.mode: "restricted"`)
6. OpenCode: allow list with Bash patterns -> `permission.bash.{"git *": "allow"}`
7. SourceReader: project rules dir with no frontmatter -> unconditional load
8. SourceReader: project rules dir with `paths:` frontmatter -> tagged with patterns
9. SourceReader: user rules dir `~/.claude/rules/` -> recursive walk
10. SourceReader: nested subdirectories -> all .md files discovered

### Recommended Metrics

| Metric | Why | How to Compute | Baseline |
|--------|-----|----------------|----------|
| Output key correctness | Core requirement | Assert exact key names in output | 0 (currently wrong) |
| Value correctness | Core requirement | Assert valid values per official docs | 0 (currently wrong) |
| Rules file count | Discovery completeness | Count files found vs files on disk | N/A (new feature) |
| Frontmatter parsing accuracy | Path scoping | Assert parsed patterns match input | N/A (new feature) |

## Verification Strategy

### Recommended Verification Tiers for This Phase

| Item | Recommended Tier | Rationale |
|------|-----------------|-----------|
| Codex writes `config.toml` not `codex.toml` | Level 1 (Sanity) | Check filename string |
| Codex writes `on-request` not `on-failure` | Level 1 (Sanity) | Check output string |
| Gemini writes `allowed`/`exclude` not `allowedTools`/`blockedTools` | Level 1 (Sanity) | Check output keys |
| OpenCode writes `permission` not `permissions` | Level 1 (Sanity) | Check output key |
| OpenCode bash patterns formatted correctly | Level 2 (Proxy) | Test with sample Claude Code allow list |
| SourceReader finds rules files recursively | Level 2 (Proxy) | Create temp dir with nested .md files |
| SourceReader parses frontmatter paths correctly | Level 2 (Proxy) | Test with sample frontmatter |
| Full sync produces correct output for all adapters | Level 3 (Deferred) | Integration test with real configs |

**Level 1 checks to always include:**
- Assert `CONFIG_TOML == "config.toml"` in codex adapter
- Assert no occurrence of `'on-failure'` in codex adapter
- Assert no occurrence of `'blockedTools'` or `'allowedTools'` in gemini adapter
- Assert no occurrence of `'permissions'` (plural) key writes in opencode adapter
- Assert `permission` (singular) key used in opencode adapter output

**Level 2 proxy metrics:**
- Create temp directory with 3 rules files (1 with `paths:` frontmatter, 1 without, 1 in subdirectory)
- Verify SourceReader returns all 3 with correct metadata
- Run each adapter's `sync_settings()` with sample input, verify output matches official format

**Level 3 deferred items:**
- Full end-to-end sync with real Claude Code config directory
- Verify output files are accepted by target CLIs (Codex, Gemini, OpenCode)

## Production Considerations

### Known Failure Modes
- **Existing codex.toml files in projects:** Users may have `codex.toml` files generated by the buggy adapter. After the fix, these orphaned files will remain. The sync will write to `config.toml` but won't clean up old `codex.toml`.
  - Prevention: Consider adding a migration note or cleanup step
  - Detection: Check for existence of both `codex.toml` and `config.toml`

- **OpenCode permission format migration:** Existing `opencode.json` files may have old `permissions.mode` format. Writing new `permission` key without removing old `permissions` key creates ambiguity.
  - Prevention: When writing `permission`, explicitly delete `permissions` key from config dict
  - Detection: Check for both keys in output JSON

### Scaling Concerns
- **Large rules directories:** A project with many nested subdirectories in `.claude/rules/` could have hundreds of .md files.
  - At current scale: `rglob('*.md')` is fine for typical projects
  - At production scale: Still fine -- filesystem walks are fast for reasonable directory depths

### Common Implementation Traps
- **Path.home() hardcoding:** Per MEMORY.md, user-level paths MUST use `self.cc_home`, not `Path.home() / ".claude"`. For rules discovery, `~/.claude/rules/` should be `self.cc_home / "rules"`.
  - Correct approach: Use `self.cc_home / "rules"` for user-scope rules directory

- **Python 3.9 compatibility:** Per MEMORY.md, all src/*.py need `from __future__ import annotations` for 3.9 support. Ensure any new code follows this.

## Code Examples

Verified patterns from official sources:

### Codex config.toml Correct Format
```toml
# Source: https://developers.openai.com/codex/config-reference
approval_policy = "on-request"
sandbox_mode = "workspace-write"
```

### Gemini settings.json Correct Tools Format
```json
// Source: https://google-gemini.github.io/gemini-cli/docs/get-started/configuration.html
{
  "tools": {
    "allowed": ["run_shell_command(git)", "run_shell_command(npm test)"],
    "exclude": ["write_file"]
  }
}
```

### OpenCode opencode.json Correct Permission Format
```json
// Source: https://opencode.ai/docs/permissions
{
  "permission": {
    "edit": "allow",
    "bash": {
      "*": "ask",
      "git *": "allow",
      "npm *": "allow",
      "rm *": "deny"
    },
    "read": "allow"
  }
}
```

### Claude Code Rules Frontmatter Format
```yaml
# Source: https://claudefa.st/blog/guide/mechanics/rules-directory
---
paths: src/api/**/*.ts
---
# API rules content here
```

```yaml
# Multiple paths (list format)
---
paths:
  - src/components/**/*.tsx
  - src/hooks/**/*.ts
---
# Frontend rules content here
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `codex.toml` | `config.toml` | Codex CLI official name | Config not loaded by CLI |
| `approval_policy = 'on-failure'` | `approval_policy = 'on-request'` | Codex valid values | Invalid config rejected |
| `tools.blockedTools` / `tools.allowedTools` | `tools.exclude` / `tools.allowed` | Gemini CLI v2 | Tools config ignored |
| `permissions.mode` | `permission.{tool}` | OpenCode current format | Permissions not applied |

**Deprecated/outdated:**
- `codex.toml`: Never was the official filename; was always `config.toml`
- `on-failure`: Not a valid Codex `approval_policy` value
- `blockedTools`/`allowedTools`: Gemini CLI v1 keys, replaced by `exclude`/`allowed`
- `permissions` (plural) with `mode`: Old OpenCode format, replaced by `permission` (singular) with per-tool entries

## Open Questions

1. **Codex user-scope config path in sync_mcp_scoped()**
   - What we know: Line 348 writes `user_path = self.project_dir / CONFIG_TOML` which puts user-scope MCP servers in the project root. Official docs say user config lives at `~/.codex/config.toml`.
   - What's unclear: Whether HarnessSync should write to `~/.codex/config.toml` or if project-root placement is intentional for some reason.
   - Recommendation: Review the design intent. If user-scope should go to `~/.codex/`, update the path. If project-root is intentional, document why.

2. **How to integrate rules discovery with orchestrator**
   - What we know: Orchestrator currently converts rules string to `[{'path': 'CLAUDE.md', 'content': rules_str}]` at lines 93-97. New rules files need to merge into this flow.
   - What's unclear: Whether rules from `.claude/rules/` should be separate entries or merged into the existing rules string.
   - Recommendation: Add rules files as additional entries in the rules list. Each entry gets `path`, `content`, and optionally `scope_patterns` for path-scoped rules.

3. **Frontmatter parsing: `paths` vs `globs` key**
   - What we know: Official docs use `paths:` but [GitHub issue #17204](https://github.com/anthropics/claude-code/issues/17204) notes that `globs:` works more reliably in Claude Code itself.
   - What's unclear: Whether HarnessSync should support both keys or just `paths:`.
   - Recommendation: Support both `paths:` and `globs:` keys, preferring `paths:` when both are present. This ensures compatibility with both official format and working implementations.

## Sources

### Primary (HIGH confidence)
- [Codex Config Reference](https://developers.openai.com/codex/config-reference) -- Valid approval_policy values, correct filename
- [Codex Config Basics](https://developers.openai.com/codex/config-basic/) -- Config file location and naming
- [Gemini CLI Configuration](https://google-gemini.github.io/gemini-cli/docs/get-started/configuration.html) -- tools.allowed and tools.exclude format
- [OpenCode Config Docs](https://opencode.ai/docs/config/) -- permission (singular) key format
- [OpenCode Permissions Docs](https://opencode.ai/docs/permissions) -- Per-tool identifiers, bash pattern matching, allow/ask/deny values
- [Claude Code Memory Docs](https://code.claude.com/docs/en/memory) -- .claude/rules/ directory support

### Secondary (MEDIUM confidence)
- [Claude Fast Rules Guide](https://claudefa.st/blog/guide/mechanics/rules-directory) -- Detailed rules directory format with frontmatter examples
- [GitHub Issue #17204](https://github.com/anthropics/claude-code/issues/17204) -- globs vs paths frontmatter key behavior
- Codebase analysis of `src/adapters/codex.py`, `gemini.py`, `opencode.py`, `source_reader.py` -- Current bug locations verified

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib, no new dependencies
- Architecture: HIGH - Extending existing patterns (new method on SourceReader, value changes in adapters)
- Recommendations: HIGH - All backed by official documentation from target CLI projects
- Pitfalls: HIGH - Identified from direct codebase analysis and MEMORY.md patterns

**Research date:** 2026-03-09
**Valid until:** 2026-04-09 (30 days -- target CLI APIs are relatively stable)
