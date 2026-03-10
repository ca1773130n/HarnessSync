# Phase 13: Gemini Native Format Migration - Research

**Researched:** 2026-03-09
**Domain:** Gemini CLI native skill/agent/command format writing + MCP field passthrough
**Confidence:** HIGH

## Summary

Phase 13 migrates the Gemini adapter from inlining skills, agents, and commands into GEMINI.md to writing native format files that Gemini CLI discovers and loads natively. The research confirms that Gemini CLI v0.32.0 has full native support for SKILL.md files (`.gemini/skills/<name>/SKILL.md`), agent .md files (`.gemini/agents/<name>.md`), and command TOML files (`.gemini/commands/<name>.toml`). The Claude Code source formats are close enough to Gemini's native formats that translation is straightforward with minimal field mapping.

The current adapter (`src/adapters/gemini.py`) inlines all three content types into GEMINI.md using subsection markers (`<!-- HarnessSync:Skills -->`, `<!-- HarnessSync:Agents -->`, `<!-- HarnessSync:Commands -->`). After migration, these subsections must be cleaned from GEMINI.md so only rules remain. The MCP sync also needs updating to pass through four new fields (`trust`, `includeTools`, `excludeTools`, `cwd`) that the current `_write_mcp_to_settings` method silently drops.

**Primary recommendation:** Replace `sync_skills`, `sync_agents`, and `sync_commands` to write native format files, add MCP field passthrough to `_write_mcp_to_settings`, and add a cleanup method to strip stale inlined subsections from GEMINI.md.

## Paper-Backed Recommendations

This phase is a configuration format migration with no research paper domain. Recommendations are backed by Gemini CLI official documentation and codebase analysis.

### Recommendation 1: Write SKILL.md with Minimal Frontmatter Translation

**Recommendation:** Copy Claude Code SKILL.md nearly verbatim to `.gemini/skills/<name>/SKILL.md`. Both formats use identical frontmatter (`name` + `description`) and markdown body. No field stripping or remapping needed.

**Evidence:**
- GEMINI-LATEST.md Section 4 confirms Gemini SKILL.md uses only `name` (required) and `description` (required) frontmatter fields, identical to Claude Code's format.
- Gemini CLI Skills Documentation (geminicli.com/docs/cli/skills/) confirms discovery at `.gemini/skills/<name>/SKILL.md`.
- Current `sync_skills` (gemini.py lines 105-171) already reads SKILL.md and parses frontmatter correctly; it just writes to the wrong target (GEMINI.md inline instead of native file).

**Confidence:** HIGH -- Both source and target formats are identical in schema.
**Caveats:** The current `_parse_frontmatter` strips YAML frontmatter for inlining; for native format, we need to PRESERVE the original frontmatter and body content, essentially copying the file.

### Recommendation 2: Write Agent .md Files with Field Mapping

**Recommendation:** Write agent files to `.gemini/agents/<name>.md` with Gemini-compatible YAML frontmatter. Map Claude Code fields to Gemini fields, strip `<role>` tags and output as plain markdown body.

**Evidence:**
- GEMINI-LATEST.md Section 5 documents agent .md format with fields: `name`, `description`, `kind`, `tools`, `model`, `temperature`, `max_turns`, `timeout_mins`.
- Claude Code agent format uses: `name`, `description`, plus optional `tools`, `color` (Gemini-incompatible), and `<role>` tags for system prompt.
- Current `sync_agents` (gemini.py lines 173-240) already extracts `name`, `description`, and role instructions correctly.

**Confidence:** MEDIUM -- Agents are marked as experimental/preview in Gemini CLI documentation. Core format is stable but edge cases may exist.

**Field mapping:**

| Claude Code Field | Gemini Field | Action |
|-------------------|--------------|--------|
| `name` | `name` | Direct copy |
| `description` | `description` | Direct copy |
| `tools` | `tools` | Pass through if present (list of tool names) |
| `model` | `model` | Pass through if present |
| `max_turns` | `max_turns` | Pass through if present |
| `color` | -- | Drop (Gemini-incompatible) |
| `<role>` body | markdown body | Strip `<role>` tags, output as plain markdown |

### Recommendation 3: Write Command TOML Files with Syntax Mapping

**Recommendation:** Write command files to `.gemini/commands/<name>.toml` with `description` and `prompt` fields. Map `$ARGUMENTS` to `{{args}}` in the prompt body.

**Evidence:**
- GEMINI-LATEST.md Section 6 documents TOML command format with `description` (optional) and `prompt` (required) fields.
- Gemini CLI Custom Commands Documentation (geminicli.com/docs/cli/custom-commands/) confirms naming: file path determines command name (e.g., `test.toml` -> `/test`).
- Current `sync_commands` (gemini.py lines 242-302) extracts `name` and `description` from frontmatter but only writes bullet points. The full body content (the prompt template) is discarded.

**Confidence:** HIGH -- TOML command format is well-documented and stable.

**Key syntax translations:**

| Claude Code | Gemini TOML | Notes |
|-------------|-------------|-------|
| `$ARGUMENTS` | `{{args}}` | User-provided arguments placeholder |
| Markdown body after frontmatter | `prompt` field value | Use TOML multi-line string `"""..."""` |
| `name` frontmatter | Filename stem | `<name>.toml` determines `/name` command |
| `description` frontmatter | `description` field | Direct copy |

### Recommendation 4: Pass Through New MCP Fields

**Recommendation:** Add `trust`, `includeTools`, `excludeTools`, and `cwd` to the MCP server config passthrough in `_write_mcp_to_settings`.

**Evidence:**
- GEMINI-LATEST.md Section 3 documents these four fields with their types: `trust` (boolean), `includeTools` (string[]), `excludeTools` (string[]), `cwd` (string).
- Current `_write_mcp_to_settings` (gemini.py lines 384-451) only passes `command`, `args`, `env`, `timeout`, `url`/`httpUrl`, and `headers`. The four new fields are silently dropped.
- Claude Code MCP config supports `cwd` for stdio servers. The `trust`/`includeTools`/`excludeTools` fields may appear in manually crafted configs or future Claude Code versions.

**Confidence:** HIGH -- Fields are documented in official Gemini CLI config reference.

### Recommendation 5: Clean Stale Inlined Sections from GEMINI.md

**Recommendation:** After writing native format files, remove the `<!-- HarnessSync:Skills -->`, `<!-- HarnessSync:Agents -->`, and `<!-- HarnessSync:Commands -->` subsections from GEMINI.md. Only the main rules managed section should remain.

**Evidence:**
- If both inlined and native formats exist, Gemini CLI would see duplicate content (inlined in GEMINI.md plus native files), causing confusion.
- The subsection marker pattern is already well-defined in gemini.py (`_write_subsection` method, lines 664-733) and can be reversed for cleanup.

**Confidence:** HIGH -- The marker-based cleanup is a simple regex/string operation on content we control.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `pathlib` | 3.9+ | File path manipulation | Already used throughout codebase |
| Python stdlib `re` | 3.9+ | Frontmatter parsing, marker cleanup | Already used in adapter |
| Python stdlib `json` | 3.9+ | settings.json read/write | Already used for MCP sync |

### Supporting

No new dependencies required. All operations use existing utilities:
- `src/utils/paths.ensure_dir` -- Create target directories
- `src/utils/paths.write_json_atomic` -- Atomic settings.json writes
- `src/utils/paths.read_json_safe` -- Safe settings.json reads

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Decision |
|------------|-----------|----------|----------|
| Manual TOML string building for commands | `tomli_w` library | Would add dependency; command TOML is trivial (2 fields) | Manual -- zero-dependency constraint |
| File copy for skills | `shutil.copy2` | Loses ability to strip/normalize; but skill format is identical | Direct file read + write (normalize whitespace) |

## Architecture Patterns

### Recommended Project Structure Changes

```
.gemini/
  skills/
    <name>/
      SKILL.md          # NEW: native skill files (was inlined in GEMINI.md)
  agents/
    <name>.md           # NEW: native agent files (was inlined in GEMINI.md)
  commands/
    <name>.toml         # NEW: native command files (was bullet points in GEMINI.md)
  settings.json         # EXISTING: MCP servers + settings (add new fields)
GEMINI.md               # EXISTING: rules only (skills/agents/commands sections removed)
```

### Pattern 1: Native File Writer Pattern

**What:** Each `sync_*` method writes individual files to Gemini's native discovery directories instead of accumulating content into GEMINI.md.
**When to use:** When the target CLI has native support for the content type with its own discovery mechanism.
**Example:**

```python
def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
    for name, skill_dir in skills.items():
        skill_md = skill_dir / "SKILL.md"
        content = skill_md.read_text(encoding='utf-8')

        # Write to native discovery path
        target_dir = self.project_dir / ".gemini" / "skills" / name
        ensure_dir(target_dir)
        target_md = target_dir / "SKILL.md"
        target_md.write_text(content, encoding='utf-8')
```

### Pattern 2: TOML Multi-line String for Command Prompts

**What:** Use TOML triple-quoted strings (`"""..."""`) for command prompt bodies that span multiple lines.
**When to use:** When writing `.gemini/commands/<name>.toml` files.
**Example:**

```python
def _format_command_toml(self, description: str, prompt: str) -> str:
    # Escape for TOML basic string
    desc_escaped = description.replace('\\', '\\\\').replace('"', '\\"')

    toml_lines = []
    toml_lines.append(f'description = "{desc_escaped}"')
    toml_lines.append(f'prompt = """\n{prompt}\n"""')
    return '\n'.join(toml_lines)
```

### Pattern 3: Post-Migration Cleanup

**What:** After writing native files, scan GEMINI.md for stale HarnessSync subsections and remove them.
**When to use:** On every sync, to ensure GEMINI.md stays clean after migration.
**Example:**

```python
def _cleanup_stale_subsections(self) -> None:
    content = self._read_gemini_md()
    for section_name in ["Skills", "Agents", "Commands"]:
        start = f"<!-- HarnessSync:{section_name} -->"
        end = f"<!-- End HarnessSync:{section_name} -->"
        # Remove section between markers (inclusive)
        content = self._remove_section(content, start, end)
    self._write_gemini_md(content)
```

### Anti-Patterns to Avoid

- **Dual-writing:** Do NOT write to both GEMINI.md inline AND native files. This creates duplicate content that confuses Gemini CLI and wastes context window.
- **Hardcoded paths:** Use `self.project_dir / ".gemini"` consistently, never hardcode `~/.gemini` (MEMORY.md: known pitfall).
- **Missing frontmatter validation:** Always verify `name` and `description` exist before writing SKILL.md or agent .md. Gemini CLI requires both.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| YAML frontmatter generation | Full YAML serializer | Simple string formatting (`---\nname: X\n---`) | Only 2-6 flat fields, no nested YAML needed |
| TOML generation for commands | Full TOML library | Manual `f'description = "{d}"\nprompt = """\n{p}\n"""'` | Only 2 fields, trivial format |
| Subsection marker cleanup | Custom parser | Regex with `re.sub` or `str.find`/`str.replace` | Markers are well-defined HTML comments |

**Key insight:** The Gemini native formats are intentionally simple (2-6 field frontmatter + body). Hand-rolling the output is appropriate given the zero-dependency constraint and trivial schema.

## Common Pitfalls

### Pitfall 1: Command Name Sanitization

**What goes wrong:** Claude Code command names may contain colons (namespaced commands like `harness:setup`). Gemini uses the filename as the command name, and colons map to subdirectory separators.
**Why it happens:** Gemini CLI interprets `/` in filenames as `:` in command names (e.g., `.gemini/commands/git/commit.toml` -> `/git:commit`).
**How to avoid:** For namespaced commands like `harness:setup`, create `.gemini/commands/harness/setup.toml` (subdirectory for namespace). For simple commands, use `<name>.toml` directly.
**Warning signs:** Commands not appearing in `/help` or appearing with wrong names.

### Pitfall 2: TOML Triple-Quote Escaping

**What goes wrong:** If the prompt body contains `"""` (three consecutive double quotes), the TOML multi-line string will terminate prematurely.
**Why it happens:** TOML multi-line basic strings end at the first unescaped `"""`.
**How to avoid:** Scan prompt body for `"""` and escape one of the quotes with `\"`. Alternatively, use single-line string with `\n` escapes if prompt is short.
**Warning signs:** TOML parse errors when Gemini CLI loads the command file.

### Pitfall 3: Stale Native Files After Source Deletion

**What goes wrong:** If a skill/agent/command is removed from Claude Code, the corresponding native file in `.gemini/` remains, creating ghost entries.
**Why it happens:** The sync writes new/updated files but has no mechanism to detect and remove files that no longer have a source counterpart.
**How to avoid:** Track synced file paths in state manager. On each sync, compare current output set vs. previous output set and delete orphans. Alternatively, use a HarnessSync marker comment in each native file to identify managed files, then scan and remove unmarked or source-absent files.
**Warning signs:** Skills/agents/commands appearing in Gemini CLI that no longer exist in Claude Code.

### Pitfall 4: Frontmatter Quoting for Special Characters

**What goes wrong:** YAML frontmatter `name` or `description` fields containing colons, quotes, or other YAML special characters cause parse errors.
**Why it happens:** Simple `name: value` format breaks when value contains `: ` or starts with `[`, `{`, `*`, etc.
**How to avoid:** Quote frontmatter values that contain YAML-unsafe characters. The existing `_format_skill_md` in `codex.py` (lines 563-603) already handles this with the `quoted_desc` logic -- reuse that pattern.
**Warning signs:** Gemini CLI fails to load skills/agents with "YAML parse error" messages.

### Pitfall 5: GEMINI.md Cleanup Race Condition

**What goes wrong:** If cleanup runs before all native writes complete successfully, and a native write fails, the inlined content is lost with no native replacement.
**Why it happens:** Cleanup removes inlined sections; if native file write then fails, data is lost.
**How to avoid:** Run cleanup AFTER all native writes succeed. If any native write fails, skip cleanup for that section type. Return cleanup results as part of SyncResult.
**Warning signs:** Skills/agents/commands disappear from both GEMINI.md and native files after a failed sync.

## Experiment Design

### Recommended Experimental Setup

Not applicable -- this is a deterministic format migration, not a machine learning experiment. Validation is through functional testing.

### Validation Plan

**Independent variables:** Source content (skills/agents/commands from Claude Code)
**Dependent variables:** Generated native files (content correctness, Gemini CLI discoverability)
**Controlled variables:** Gemini CLI version (v0.32.0)

**Test cases:**
1. Skill with simple name/description -> SKILL.md output matches expected format
2. Skill with special characters in description -> proper YAML quoting
3. Agent with `<role>` tags -> tags stripped, body written as plain markdown
4. Agent with extra frontmatter fields (tools, model) -> fields passed through
5. Command with `$ARGUMENTS` -> mapped to `{{args}}` in TOML prompt
6. Command with namespaced name (colon) -> correct subdirectory structure
7. MCP server with `trust`/`includeTools`/`excludeTools`/`cwd` -> fields present in output
8. GEMINI.md with existing inlined sections -> sections cleaned after successful native write
9. GEMINI.md with rules + inlined sections -> only rules remain after cleanup

## Verification Strategy

### Recommended Verification Tiers for This Phase

| Item | Recommended Tier | Rationale |
|------|-----------------|-----------|
| SKILL.md files written with correct frontmatter | Level 1 (Sanity) | Read back file, verify frontmatter keys |
| Agent .md files with correct field mapping | Level 1 (Sanity) | Read back, check name/description/body |
| Command .toml files with correct format | Level 1 (Sanity) | Parse TOML, verify description + prompt |
| `$ARGUMENTS` -> `{{args}}` mapping | Level 1 (Sanity) | String contains check |
| MCP new fields in settings.json | Level 1 (Sanity) | Read JSON, verify field presence |
| GEMINI.md cleanup removes stale sections | Level 1 (Sanity) | Read GEMINI.md, verify no subsection markers |
| Gemini CLI discovers native files | Level 2 (Proxy) | Run `gemini skills list` / check discovery |
| End-to-end sync with all content types | Level 2 (Proxy) | Full orchestrator run, verify all outputs |

**Level 1 checks to always include:**
- File exists at expected path
- Frontmatter contains required fields (`name`, `description`)
- TOML is valid (parseable)
- No duplicate content (GEMINI.md cleaned + native files exist, not both)
- MCP new fields preserved when present in source

**Level 2 proxy metrics:**
- Run sync, then read all generated files and verify content
- Compare GEMINI.md before/after to confirm subsection removal
- Verify settings.json contains new MCP fields

**Level 3 deferred items:**
- Actual Gemini CLI integration test (requires installed Gemini CLI)
- Stale file cleanup (requires multi-sync scenario testing)

## Production Considerations (from KNOWHOW.md)

### Known Failure Modes

- **Configuration Drift (Pitfall 1):** After migrating to native files, manually editing `.gemini/skills/` or `.gemini/agents/` will be overwritten on next sync. The managed markers in GEMINI.md served as a visual warning; native files lack this. Consider adding a header comment to each generated file (e.g., `# Managed by HarnessSync - do not edit manually`).
- **MCP Format Translation (Pitfall 3):** The new `trust`, `includeTools`, `excludeTools` fields add complexity to the MCP config passthrough. Ensure unknown future fields are also passed through (use allowlist vs. blocklist approach for field filtering).

### Scaling Concerns

- **File count:** Each skill, agent, and command creates a separate file. With 50+ skills, this creates many small files. Not a performance concern but worth noting for git noise (all these files will appear in git status).
- **Batch writes:** Current approach writes files one at a time. For large skill sets (>20), consider batching error reporting but individual file writes are fine (each is <10KB).

### Common Implementation Traps

- **Path hardcoding (MEMORY.md):** Use `self.project_dir / ".gemini"` everywhere. Never `Path.home() / ".gemini"`.
- **Python 3.9 compat (MEMORY.md):** Ensure `from __future__ import annotations` is present. The gemini.py file already has it.
- **Atomic writes:** For settings.json (MCP fields), continue using `write_json_atomic`. For native skill/agent/command files, simple `write_text` is acceptable since they're individual small files and corruption is recoverable (next sync regenerates).

## Code Examples

### Writing a Gemini Native SKILL.md

```python
# Source: Direct file copy with whitespace normalization
def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
    result = SyncResult()
    for name, skill_dir in skills.items():
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue

        content = skill_md.read_text(encoding='utf-8')

        # Validate frontmatter has required fields
        frontmatter, body = self._parse_frontmatter(content)
        if 'name' not in frontmatter or 'description' not in frontmatter:
            result.skipped += 1
            continue

        # Write to native path
        target_dir = self.project_dir / ".gemini" / "skills" / name
        ensure_dir(target_dir)
        (target_dir / "SKILL.md").write_text(content, encoding='utf-8')
        result.synced += 1

    return result
```

### Writing a Gemini Command TOML

```python
# Source: Claude Code command .md -> Gemini .toml translation
def _format_command_toml(self, description: str, prompt: str) -> str:
    """Format a Gemini command TOML file."""
    lines = []

    if description:
        # Escape for TOML basic string
        desc = description.replace('\\', '\\\\').replace('"', '\\"')
        lines.append(f'description = "{desc}"')

    # Map $ARGUMENTS -> {{args}}
    prompt = prompt.replace('$ARGUMENTS', '{{args}}')

    # Use multi-line string for prompt
    lines.append(f'prompt = """\n{prompt}\n"""')

    return '\n'.join(lines)
```

### Cleaning Stale Subsections from GEMINI.md

```python
def _cleanup_stale_subsections(self) -> int:
    """Remove HarnessSync:Skills/Agents/Commands from GEMINI.md. Returns count removed."""
    content = self._read_gemini_md()
    if not content:
        return 0

    removed = 0
    for section in ["Skills", "Agents", "Commands"]:
        start_marker = f"<!-- HarnessSync:{section} -->"
        end_marker = f"<!-- End HarnessSync:{section} -->"

        if start_marker in content:
            start_idx = content.find(start_marker)
            end_idx = content.find(end_marker)
            if end_idx != -1:
                end_pos = end_idx + len(end_marker)
                before = content[:start_idx].rstrip()
                after = content[end_pos:].lstrip()
                content = f"{before}\n\n{after}" if before and after else (before or after)
                removed += 1

    if removed > 0:
        self._write_gemini_md(content.strip())

    return removed
```

### MCP Field Passthrough

```python
# Add to _write_mcp_to_settings, after existing field handling:
# New Gemini CLI fields (GMN-11)
for field in ('trust', 'includeTools', 'excludeTools', 'cwd'):
    if field in config:
        server_config[field] = config[field]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Inline skills in GEMINI.md | Native `.gemini/skills/<name>/SKILL.md` | Gemini CLI v0.23.0 (Jan 2026) | Skills get lazy-loading + activate_skill tool flow |
| Inline agents in GEMINI.md | Native `.gemini/agents/<name>.md` | Gemini CLI v0.12.0 (Oct 2025) | Agents run as subagents with own model/tools |
| Bullet-point commands in GEMINI.md | Native `.gemini/commands/<name>.toml` | Gemini CLI native feature | Commands become real slash commands with `/help` |
| MCP with basic fields only | MCP with trust/includeTools/excludeTools/cwd | Gemini CLI v0.32.0 | Fine-grained per-server tool filtering |

**Deprecated/outdated:**
- Inlining skills/agents/commands into GEMINI.md: still works but misses native discovery, lazy-loading, and tool integration

## Open Questions

1. **Stale file cleanup strategy**
   - What we know: New files are written on each sync; old files are not removed
   - What's unclear: Should we track managed files in state and delete orphans, or add a marker header and scan?
   - Recommendation: Start with marker-based approach (header comment in each file). Track in state manager for Phase 14+. For v0.1.1, orphan cleanup is acceptable as a future improvement.

2. **Agent `kind` field default**
   - What we know: Gemini agents support `kind: local` (default)
   - What's unclear: Whether Claude Code agents should always map to `kind: local` or if there's a meaningful distinction
   - Recommendation: Omit `kind` from output (let Gemini use its default of `local`). Only pass through if explicitly set in source.

3. **Command prompt special syntax**
   - What we know: Gemini commands support `!{shell command}` and `@{file/path}` in prompts
   - What's unclear: Whether Claude Code command bodies contain equivalent syntax that should be mapped
   - Recommendation: Pass through as-is for now. Only map `$ARGUMENTS` -> `{{args}}`. Other special syntax mapping can be added incrementally.

## Sources

### Primary (HIGH confidence)
- `.planning/research/v0.1.1/GEMINI-LATEST.md` -- Comprehensive Gemini CLI v0.32.0 research (verified against official docs)
- `src/adapters/gemini.py` -- Current adapter implementation (codebase analysis)
- `src/source_reader.py` -- Source data format and discovery logic (codebase analysis)
- Gemini CLI Skills Documentation (geminicli.com/docs/cli/skills/)
- Gemini CLI Subagents Documentation (geminicli.com/docs/core/subagents/)
- Gemini CLI Custom Commands Documentation (geminicli.com/docs/cli/custom-commands/)
- Gemini CLI MCP Documentation (google-gemini.github.io/gemini-cli/docs/tools/mcp-server.html)

### Secondary (MEDIUM confidence)
- Gemini CLI Changelog (geminicli.com/docs/changelogs/) -- Version history for feature introduction dates
- `.planning/research/PITFALLS.md` -- Known failure modes and integration gotchas

### Tertiary (LOW confidence)
- Agent `kind` field behavior -- only `local` is documented; remote agents may exist but are undocumented

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new dependencies, all existing utilities
- Architecture: HIGH -- straightforward file-writing pattern, well-understood target formats
- Recommendations: HIGH -- target formats verified against official documentation
- Pitfalls: HIGH -- derived from codebase analysis and existing pitfalls research

**Research date:** 2026-03-09
**Valid until:** 2026-04-09 (30 days -- Gemini CLI format is stable post-v0.23.0)
