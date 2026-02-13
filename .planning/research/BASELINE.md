# Performance Baseline — HarnessSync (cc2all)

**Last updated:** 2026-02-13
**Updated by:** Claude (grd-baseline-assessor)
**Trigger:** Initial baseline assessment before plugin rewrite

## Current Baseline

**Established:** 2026-02-13
**Git hash:** `0759f071e30af4e874b10f79e35ba5fef11cd03b`
**Git branch:** main
**Environment:** Python 3.10.14, macOS Darwin 25.1.0 (arm64)
**Status:** Pre-rewrite monolithic implementation

---

## 1. Code Quality Metrics

### Lines of Code (Physical)

| File | Lines | Type | Purpose |
|------|-------|------|---------|
| `cc2all-sync.py` | 983 | Python | Main sync engine and CLI |
| `shell-integration.sh` | 163 | Bash | Shell wrappers and command interception |
| `install.sh` | 160 | Bash | Installation script |
| `com.cc2all.sync.plist` | 29 | XML | macOS launchd daemon configuration |
| **Total** | **1,335** | — | — |

**Breakdown by language:**
- Python: 983 lines (73.6%)
- Bash: 323 lines (24.2%)
- XML: 29 lines (2.2%)

### Code Structure (cc2all-sync.py)

| Metric | Count | Notes |
|--------|-------|-------|
| **Functions** | 29 | 26 module-level functions, 7 class methods |
| **Classes** | 1 | `Logger` utility class |
| **Comment lines** | 92 | 9.4% documentation density |
| **Imports** | 11 | All from Python stdlib (zero external dependencies) |
| **Try/except blocks** | 4 | Limited error handling coverage |
| **Raise statements** | 0 | No custom exceptions raised |

**Function breakdown by category:**
- Utility functions: 9 (`ensure_dir`, `file_hash`, `read_json`, `write_json`, `write_text`, `safe_symlink`, `load_state`, `save_state`, `detect_project_dir`)
- Source readers: 6 (`get_cc_rules`, `get_cc_skills`, `get_cc_agents`, `get_cc_commands`, `get_cc_mcp`, `get_cc_settings`)
- Target adapters: 6 (`sync_to_codex`, `sync_to_gemini`, `sync_to_opencode`, `_build_codex_mcp_toml`, `_sync_gemini_mcp`, `_sync_opencode_mcp`)
- Orchestration: 2 (`run_sync`, `sync_project_settings`)
- Watch mode: 5 (`watch_and_sync`, `_watch_fswatch`, `_watch_inotify`, `_watch_polling`, `_reset_log`)
- CLI: 1 (`main`)

### Cyclomatic Complexity (Estimated)

**High-complexity functions** (visual inspection):
- `get_cc_skills()`: ~8 branches (multiple scope checks, registry parsing, directory traversal)
- `sync_to_codex()`: ~12 branches (rules, skills, agents, commands, MCP, cleanup logic)
- `_build_codex_mcp_toml()`: ~8 branches (TOML parsing, MCP server type detection, env handling)
- `sync_to_gemini()`: ~7 branches (rules, skills, agents, commands, MCP)
- `sync_to_opencode()`: ~8 branches (similar to Codex)
- `main()`: ~6 branches (argument parsing, scope detection, watch vs one-shot)

**Average complexity:** Medium to high. Functions do not follow single-responsibility principle — each sync function handles multiple concerns (rules, skills, agents, commands, MCP).

### Modularity Assessment

**Current structure:** Monolithic single-file design

**Problems:**
- All sync logic in one 983-line file
- Adapter functions intermixed with utilities and orchestration
- No separation between concerns (source reading, target writing, format conversion)
- Difficult to test individual components
- Hard to extend with new targets (would add ~150 lines per target)

**Opportunities for refactoring:**
1. Extract adapters into separate modules (`adapters/codex.py`, `adapters/gemini.py`, `adapters/opencode.py`)
2. Extract source reading into `core/source_reader.py`
3. Extract utilities into `core/utils.py`
4. Extract watch mode into `core/watch.py`
5. Create adapter interface/protocol for consistency

---

## 2. Test Coverage

**Test suite status:** ❌ **No tests exist**

| Metric | Value | Status |
|--------|-------|--------|
| **Unit tests** | 0 | None |
| **Integration tests** | 0 | None |
| **Test files** | 0 | No `test*.py`, `*_test.py`, or `tests/` directory |
| **Test framework** | None | Not configured |
| **Coverage measurement** | N/A | No tooling |

**Untested areas (critical):**
- Path resolution logic (especially symlink handling)
- JSON parsing and merging (MCP configs, settings)
- File synchronization logic across three different target formats
- Regex transformations (agents → skills conversion, YAML frontmatter parsing)
- Watch mode event handling (fswatch, inotifywait, polling)
- TOML string-based merging (data corruption risk)
- Error handling paths (currently only 4 try/except blocks)

**Impact:**
- No confidence in refactoring safety
- Regressions could silently break symlinks or corrupt target configs
- No validation of generated config formats

**Recommended:**
- Add pytest-based test suite with fixtures for temporary directories
- Parametrized tests for each sync target (Codex, Gemini, OpenCode)
- Mock file systems for reproducible tests
- Integration tests that validate generated configs against real CLI tools

---

## 3. Error Handling Patterns

### Current Error Handling

**Exception handling blocks:** 4 total

| Location | Pattern | Scope |
|----------|---------|-------|
| `read_json()` (line 131) | `except (json.JSONDecodeError, OSError) as e` | JSON parsing errors only; logs error and returns `{}` |
| `_watch_fswatch()` (line 867) | `except KeyboardInterrupt` | Graceful shutdown on Ctrl+C |
| `_watch_inotify()` (line 883) | `except KeyboardInterrupt` | Graceful shutdown on Ctrl+C |
| `_watch_polling()` (line 915) | `except KeyboardInterrupt` | Graceful shutdown on Ctrl+C |

**Custom exceptions:** 0
**Raise statements:** 0

### Error Handling Gaps

**Critical gaps:**
1. **Subprocess errors not handled** — `fswatch`/`inotifywait` can crash silently (lines 857, 873)
   - If subprocess exits unexpectedly, watch loop stops with no warning
   - No restart or fallback logic

2. **File operations assume success** — No error handling for:
   - `write_text()` — disk full, permission denied
   - `write_json()` — same issues
   - `safe_symlink()` — permission errors, filesystem doesn't support symlinks
   - Directory creation in `ensure_dir()` — permission issues

3. **No validation of generated content** — TOML/JSON syntax errors not detected until target CLI fails

4. **Missing state file permissions enforcement** (line 164) — Could be world-readable on shared systems

5. **Regex parsing fragility** (lines 384, 511) — YAML frontmatter extraction fails silently on malformed input
   - Uses regex instead of proper YAML parser
   - Different line endings (CRLF) cause failures

6. **String-based TOML merging** (lines 443-455) — Brittle to whitespace, could corrupt user's config
   - Should use `tomllib` (Python 3.11+) instead

### Error Recovery Patterns

**Current pattern:** Fail silently and continue
- Most functions return empty dicts/strings on error
- `log.error()` prints to console but doesn't halt execution
- No retry logic for transient failures

**Recommended pattern:**
- Distinguish between fatal errors (halt) and recoverable errors (warn and continue)
- Add retry logic for file I/O operations
- Validate generated configs before writing
- Use proper parsers (YAML, TOML) instead of regex

---

## 4. Code Organization (Modularity)

### Current Structure

**Monolithic design:** Single 983-line Python file

**Logical sections (via comments):**
1. Constants (lines 30-69)
2. Utility functions (lines 75-165)
3. Source readers (lines 172-323)
4. Target adapters (lines 330-714)
   - Codex adapter (lines 330-484)
   - Gemini adapter (lines 491-587)
   - OpenCode adapter (lines 594-714)
5. Project settings sync (lines 721-769)
6. Orchestrator (lines 776-806)
7. Watch mode (lines 813-916)
8. CLI (lines 923-983)

### Separation of Concerns

**Problems:**

| Concern | Current State | Issue |
|---------|---------------|-------|
| **Source reading** | Mixed with orchestration | Hard to test independently |
| **Target writing** | Three separate functions with duplicated patterns | Code duplication (skills → symlinks repeated 3x) |
| **Format conversion** | Embedded in sync functions | Agent → Skill conversion logic (lines 376-398) not reusable |
| **Configuration** | Hardcoded constants at top | No config file support |
| **Logging** | Global mutable `log` object | Thread-unsafe, non-idiomatic |
| **State management** | Simple JSON file, no schema | No versioning, no migration path |

### Dependency Flow

**Current:** Tightly coupled, hard to test

```
main() → run_sync() → sync_to_*() → get_cc_*() + write_*()
                                       ↓
                                   safe_symlink(), write_text(), write_json()
```

**All functions access global constants directly** — No dependency injection

### Code Duplication

**Repeated patterns:**
1. **Symlink creation** — Same logic in `sync_to_codex()`, `sync_to_opencode()` (skills, agents, commands)
2. **MCP server conversion** — Similar logic in `_build_codex_mcp_toml()`, `_sync_gemini_mcp()`, `_sync_opencode_mcp()`
3. **Scope handling** — `if scope in ("user", "all")` repeated in every reader function
4. **Target directory resolution** — `if scope == "project" and project_dir` pattern repeated
5. **Dry-run checks** — `if not dry_run: write_*()` repeated throughout

**Opportunities for abstraction:**
- Common MCP formatter base class
- Scope abstraction (UserScope, ProjectScope classes)
- Symlink manager utility
- Dry-run decorator pattern

---

## 5. Security Patterns

### Secret Handling

**Current approach:** No explicit secret detection or masking

**Risks:**
1. **Environment variables in MCP configs** — Synced verbatim to target files
   - No detection of secrets in env vars (API keys, tokens)
   - Plain text in `~/.codex/config.toml`, `~/.gemini/settings.json`, `opencode.json`

2. **No `.gitignore` enforcement** — Installer doesn't verify target directories are excluded from git

3. **State file contains sync timestamps** — Low risk, but no permission enforcement (line 164)

**Recommendations:**
- Add secret detection patterns (check for `API_KEY`, `TOKEN`, `PASSWORD`, `SECRET` in env var names)
- Warn users when secrets detected
- Document `.gitignore` requirements for target directories
- Set file permissions explicitly (`chmod 600` for state files)

### Input Validation

**Validation gaps:**

| Input | Current State | Risk |
|-------|---------------|------|
| **File paths** | No sanitization | Path traversal if user controls `.mcp.json` content |
| **JSON parsing** | Basic `try/except` | Malformed JSON returns empty dict, silent failure |
| **TOML content** | String manipulation, no parsing validation | Syntax errors in output not detected |
| **YAML frontmatter** | Regex extraction, no validation | Malformed YAML silently fails |
| **Shell commands in MCP** | Passed through verbatim | No validation of command safety |
| **CLI arguments** | `argparse` with basic choices | Good validation for user input |

**Recommendations:**
- Use proper parsers (`yaml.safe_load`, `tomllib.loads`) instead of regex
- Validate shell commands in MCP configs (detect suspicious patterns)
- Add path sanitization for user-provided directories
- Validate generated configs before writing (syntax check)

### File System Security

**Current issues:**

1. **Symlink race conditions** — `safe_symlink()` (line 146) has TOCTOU vulnerability:
   ```python
   if dst.is_symlink():  # Check
       dst.unlink()      # Time gap
   dst.symlink_to(src)  # Use
   ```
   Another process could modify `dst` between check and use.

2. **Directory permissions not enforced** — `ensure_dir()` uses default umask
   - Directories could be world-writable on misconfigured systems

3. **No atomic file writes** — Direct writes to files (line 143):
   ```python
   path.write_text(content, encoding="utf-8")
   ```
   If interrupted mid-write, file is corrupted. Should use temp file + atomic rename.

**Recommendations:**
- Use atomic file operations (write to temp, then `os.replace()`)
- Set explicit directory permissions (`mode=0o700` for sensitive dirs)
- Use `os.replace()` for symlink updates (atomic on POSIX)

---

## 6. Documentation Quality

### Code Documentation

| Documentation Type | Status | Quality |
|-------------------|--------|---------|
| **Docstrings** | Minimal | 5/29 functions have docstrings |
| **Inline comments** | Good section headers | 92 comment lines (9.4% of code) |
| **Type hints** | Partial | Function signatures use types, but not exhaustive |
| **Module docstring** | Yes | Good overview at top of file |

**Functions with docstrings:**
- `file_hash()` — "SHA256 of file contents for change detection."
- `get_cc_rules()` — "Read CLAUDE.md rules. scope: 'user' or 'project'."
- `get_cc_skills()` — "Discover Claude Code skills. Returns {name: path_to_skill_dir}."
- `get_cc_agents()` — "Discover Claude Code agent definitions."
- `get_cc_commands()` — "Discover Claude Code slash commands."
- `get_cc_mcp()` — "Read MCP server configurations."
- `get_cc_settings()` — "Read Claude Code settings for scope sync."
- `sync_project_settings()` — "Sync project-level settings (allowedTools, env, permissions, etc.)."
- `run_sync()` — "Main sync entry point."
- `watch_and_sync()` — "Watch Claude Code config dirs for changes and auto-sync."
- `_watch_polling()` — "Fallback: poll for changes every 5 seconds."
- `detect_project_dir()` — "Find project root by walking up to find .git."

**Functions without docstrings:** 17 (including all utility functions, target adapters, watch helpers)

### External Documentation

**README.md quality:** Excellent
- Clear architecture diagram
- Comprehensive sync mapping table
- Installation instructions
- Usage examples
- Environment variables documented
- Troubleshooting section

**Missing documentation:**
- No API reference for functions
- No developer guide for extending with new targets
- No testing documentation
- No contribution guidelines
- No changelog or version history

### Installation Scripts Documentation

**install.sh:** Well-commented
- Clear section headers
- User-friendly output with colors
- Error messages with suggestions

**shell-integration.sh:** Well-commented
- Function purposes documented
- Hook integration explained

**com.cc2all.sync.plist:** No inline comments (XML doesn't support them well)
- **Issue:** Hardcoded `~/.cc2all/` path without expansion (line 10)

---

## 7. Architecture Quality

### Current Architecture Pattern

**Pattern:** Monolithic script with adapter functions

**Strengths:**
- Simple deployment (single file)
- Zero external dependencies
- Easy to understand flow

**Weaknesses:**
- Hard to extend (new target = 150+ lines in main file)
- Hard to test (tightly coupled)
- Hard to maintain (all concerns mixed)

### Extensibility

**Adding a new sync target (e.g., Cursor):**

Current effort estimate:
1. Add new constants (5 lines)
2. Add `sync_to_cursor()` function (~150 lines)
3. Add MCP conversion helper (~50 lines)
4. Update `run_sync()` to call new function (3 lines)
5. Update README (20 lines)

**Total:** ~230 lines, scattered across file

**With plugin architecture:**
1. Create `adapters/cursor.py` (~150 lines)
2. Register in `plugin.json` (5 lines)
3. Update README (20 lines)

**Total:** ~175 lines, isolated in new file

### Plugin Architecture Target

**From PROJECT.md:**

```
Claude Code Plugin (HarnessSync)
├── hooks/          — PostToolUse auto-sync trigger
├── skills/         — Slash commands (/sync, /sync-status)
├── mcp/            — MCP server exposing sync tools
├── adapters/       — Per-target format adapters
│   ├── codex.py
│   ├── gemini.py
│   └── opencode.py
├── core/           — Source reader, state management
└── plugin.json     — Plugin manifest
```

**Benefits of rewrite:**
- Native Claude Code integration (hooks, slash commands, MCP)
- Better separation of concerns
- Easier testing (isolated adapters)
- Marketplace distribution
- Better error handling and reporting

---

## 8. Automation & Tooling

### Automation Coverage

**Current automation:**

| Trigger | Mechanism | Status | Coverage |
|---------|-----------|--------|----------|
| **Shell wrappers** | Auto-sync on `codex`, `gemini`, `opencode` | ✅ Working | Good (5-min cooldown) |
| **Watch mode** | fswatch/inotifywait/polling | ✅ Working | Good (manual activation) |
| **Claude Code hooks** | PostToolUse hook (planned) | ⚠️ Partial | Hook registration in installer, but hook JSON format may be incorrect |
| **launchd daemon** | Background watch on macOS | ⚠️ Broken | Plist uses `~/.cc2all/` without expansion |

**Automation gaps:**
1. **launchd daemon broken** — Path expansion issue (line 10 of plist)
2. **No cross-platform daemon** — launchd is macOS-only, no systemd equivalent for Linux
3. **Watch mode requires manual start** — Not automatically enabled on installation

### CI/CD & Quality Gates

**Status:** ❌ None configured

**Missing:**
- No GitHub Actions workflows
- No linting (pylint, flake8, ruff)
- No formatting checks (black, autopep8)
- No type checking (mypy)
- No security scanning (bandit)
- No dependency scanning (N/A — no deps)

**Recommended for plugin version:**
- Pre-commit hooks for linting and formatting
- GitHub Actions for automated testing
- Type checking with mypy
- Security scanning with bandit

---

## 9. Identified Issues Summary

### Critical (P0)

| Issue | Location | Impact | Mitigation |
|-------|----------|--------|------------|
| **No unit tests** | N/A | Regression risk, low refactor confidence | Add pytest suite |
| **TOML string-based merging** | Lines 443-455 | Data corruption risk | Use `tomllib` parser |
| **Watch mode subprocess errors** | Lines 857, 873 | Silent failure | Add error handling and restart logic |
| **launchd path expansion** | Line 10 (plist) | Daemon fails to start | Use absolute path |

### High (P1)

| Issue | Location | Impact | Mitigation |
|-------|----------|--------|------------|
| **Regex YAML parsing** | Lines 384, 511 | Malformed metadata breaks agent sync | Use `yaml.safe_load()` |
| **No logging infrastructure** | N/A | Poor troubleshooting | Add structured logging to files |
| **No atomic file writes** | Line 143 | Corruption on interrupt | Use temp file + `os.replace()` |
| **No config validation** | All sync functions | Invalid configs not detected | Validate before write |

### Medium (P2)

| Issue | Location | Impact | Mitigation |
|-------|----------|--------|------------|
| **Monolithic structure** | Entire file | Hard to extend and test | Refactor to plugin architecture |
| **Global logger state** | Lines 112, 850 | Thread-unsafe | Use dependency injection |
| **Code duplication** | Multiple locations | Maintenance burden | Extract common patterns |
| **Undefined CYAN color** | install.sh line 154 | Cosmetic | Add `CYAN="\033[36m"` |

### Low (P3)

| Issue | Location | Impact | Mitigation |
|-------|----------|--------|------------|
| **Polling fallback slow** | Line 898 (5-second interval) | CPU overhead if no fswatch | Make interval configurable |
| **No incremental sync** | All sync functions | Slower than necessary | Implement delta-based sync |
| **No config file support** | N/A | All config via env vars | Add `~/.cc2all/config.json` |

---

## 10. Baseline Summary

### Current State (Before Plugin Rewrite)

**Architecture:** Monolithic Python script (983 lines)
**Test coverage:** 0% (no tests)
**Documentation:** Good README, minimal code docs (5/29 functions)
**Error handling:** Minimal (4 try/except blocks, no custom exceptions)
**Security:** Basic (no secret detection, no input validation)
**Modularity:** Low (all in one file)
**Extensibility:** Medium (can add targets, but requires editing main file)

### Key Metrics Snapshot

| Metric | Value |
|--------|-------|
| Total lines of code | 1,335 |
| Python LOC | 983 |
| Functions | 29 |
| Classes | 1 |
| External dependencies | 0 |
| Test files | 0 |
| Test coverage | 0% |
| Documented functions | 12/29 (41%) |
| Critical issues | 4 |
| High-priority issues | 4 |

### Strengths

1. **Zero dependencies** — Uses only Python 3 stdlib
2. **Proven sync logic** — Successfully syncs to 3 targets (Codex, Gemini, OpenCode)
3. **Good README** — Clear documentation and usage examples
4. **Multiple trigger mechanisms** — Shell wrappers, watch mode, manual commands
5. **Scope support** — User-level and project-level sync
6. **Symlink strategy** — Efficient for skills/agents (instant updates)

### Weaknesses

1. **No tests** — Major regression risk
2. **Monolithic design** — Hard to extend and maintain
3. **Fragile parsing** — Regex-based YAML/TOML parsing
4. **Minimal error handling** — Many failure modes not handled
5. **No logging** — Poor troubleshooting capability
6. **Security gaps** — No secret detection, no input validation
7. **launchd daemon broken** — Path expansion issue

### Improvement Priorities (For Plugin Rewrite)

**P0 — Must have:**
1. Test suite (pytest with fixtures)
2. Plugin architecture (hooks, skills, MCP, adapters)
3. Proper parsers (YAML, TOML libraries)
4. Structured logging

**P1 — Should have:**
5. Config validation before write
6. Atomic file operations
7. Secret detection and warnings
8. Adapter abstraction layer

**P2 — Nice to have:**
9. Incremental sync (delta-based)
10. Config file support
11. Better error messages and recovery
12. CI/CD pipeline

---

## 11. Comparison Against Targets

**Note:** No PRODUCT-QUALITY.md exists yet. This section will be updated after product targets are defined via `/grd:product-plan`.

### Target State (From PROJECT.md)

The plugin rewrite aims to:
- Native Claude Code integration (hooks, slash commands, MCP)
- Adapter layer for settings drift
- Improved format accuracy for all three targets
- Sync compatibility reporting
- Test suite
- Marketplace packaging

**Baseline vs. Target:**

| Feature | Baseline | Target | Gap |
|---------|----------|--------|-----|
| **Architecture** | Monolithic script | Plugin with hooks/skills/MCP | Full rewrite needed |
| **Test coverage** | 0% | >80% | Test suite needed |
| **Format accuracy** | Basic | Deep (permissions, env, tools) | Adapter improvements needed |
| **Compatibility reporting** | None | Full report (mapped/adapted/failed) | New feature |
| **Distribution** | Manual install | Plugin marketplace | Packaging needed |

---

## 12. Baseline History

| Date | Git Hash | Trigger | Key Changes |
|------|----------|---------|-------------|
| 2026-02-13 | `0759f071` | Initial baseline | Pre-rewrite assessment of monolithic cc2all implementation |

---

## 13. Evaluation Infrastructure

### Available Scripts

| Script | Metrics | Status | Command |
|--------|---------|--------|---------|
| `cc2all-sync.py` | Lines synced, time elapsed | ✅ Working | `python3 cc2all-sync.py --scope all --verbose` |
| `cc2all-sync.py --dry-run` | Preview changes | ✅ Working | `python3 cc2all-sync.py --dry-run` |

### Missing Infrastructure

| Need | Impact | Priority |
|------|--------|----------|
| Unit test suite | Can't measure code quality or catch regressions | P0 |
| Integration tests | Can't verify generated configs work with target CLIs | P0 |
| Linting/formatting | Code style inconsistency | P1 |
| Type checking (mypy) | Runtime type errors not caught | P1 |
| Security scanning | Vulnerabilities not detected | P1 |
| Performance benchmarks | Can't measure sync speed improvements | P2 |
| Code coverage tool | Can't track test coverage | P2 |

### Recommendations

1. **Add pytest test suite** — Critical for refactoring confidence
   - Fixtures for temp directories and mock file systems
   - Parametrized tests for each adapter (Codex, Gemini, OpenCode)
   - Integration tests that validate generated configs

2. **Add linting and formatting** — Enforce code quality
   - Use `ruff` (fast Python linter)
   - Use `black` for formatting
   - Add pre-commit hooks

3. **Add type checking** — Catch type errors early
   - Use `mypy` with strict mode
   - Add type hints to all remaining functions

4. **Add security scanning** — Detect vulnerabilities
   - Use `bandit` for Python security issues
   - Add to CI/CD pipeline

5. **Add performance benchmarks** — Measure sync speed
   - Benchmark sync time for various project sizes
   - Track regression in sync performance

---

*Baseline assessment by: Claude (grd-baseline-assessor)*
*Assessment date: 2026-02-13*
*Environment: macOS Darwin 25.1.0, Python 3.10.14*
*Git: 0759f071e30af4e874b10f79e35ba5fef11cd03b (main)*
