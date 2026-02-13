# Testing

**Analysis Date:** 2026-02-13

## Test Framework & Tools

### Current State

**No formal test framework is present in the codebase.**

- No test files found (no `*_test.py`, `test_*.py`, `*.spec.py`)
- No test configuration files present (no `pytest.ini`, `setup.cfg`, `tox.ini`, `conftest.py`)
- No testing libraries in dependencies (no `pytest`, `unittest`, `nose`, etc.)
- No test runner scripts or Makefile targets for testing
- No CI/CD pipeline configured (no `.github/workflows/`, `.gitlab-ci.yml`, `.travis.yml`)

### Recommended Testing Setup

For future test implementation, the codebase should use:

**Framework:** `pytest`
- Lightweight, plugin-based test framework
- Well-suited for functional/integration testing of CLI scripts
- Provides fixtures for test isolation

**Assertion Library:** `pytest` built-in assertions
- Simple `assert` statements sufficient
- `pytest` rewrites assertions for better error messages

**Mocking:** `unittest.mock`
- Standard library inclusion (no extra dependency)
- Adequate for mocking file operations, subprocess calls, path operations

**CLI Testing:** `click.testing.CliRunner` (if using Click) or custom fixture
- Current codebase uses `argparse`, not Click
- Can use `subprocess.run()` or mock `argparse` directly

## Test Organization

### No Current Test Directory

No test directory structure exists. Recommended structure for future tests:

```
/Users/edward.seo/dev/private/project/harness/HarnessSync/
├── cc2all-sync.py              # Main module
├── shell-integration.sh         # Shell integration
├── tests/                       # (To be created)
│   ├── __init__.py
│   ├── conftest.py              # Shared fixtures
│   ├── test_sync.py             # Test sync operations
│   ├── test_codex.py            # Test Codex-specific sync
│   ├── test_gemini.py           # Test Gemini-specific sync
│   ├── test_opencode.py         # Test OpenCode-specific sync
│   ├── test_config.py           # Test config reading
│   ├── test_cli.py              # Test CLI argument parsing
│   └── fixtures/                # Test fixtures/mock data
│       ├── claude_config/       # Sample .claude/ structure
│       └── state/               # Sample state files
```

### Naming Conventions

**Test Files:**
- Prefix: `test_` for test modules
- Location: `tests/` subdirectory
- Naming: `test_{component}.py` (e.g., `test_codex.py`)

**Test Functions:**
- Prefix: `test_` for test functions
- Naming: `test_{behavior}()` or `test_{function}_{scenario}()`
- Examples:
  - `test_sync_to_codex_with_skills()`
  - `test_read_json_missing_file_returns_empty_dict()`
  - `test_safe_symlink_creates_new_symlink()`

**Test Classes:**
- Use `class TestComponentName:` for grouping related tests
- Example: `class TestCodexSync:` containing multiple codex-related tests

## Test Patterns

### File I/O Testing Pattern

Since the codebase has heavy file I/O, tests should:

1. **Use temporary directories** via `pytest` `tmp_path` fixture
2. **Mock `Path` operations** when testing without actual file system
3. **Test both success and failure cases** for file operations

**Example pattern (future implementation):**

```python
# tests/conftest.py
import pytest
from pathlib import Path

@pytest.fixture
def claude_config(tmp_path):
    """Create minimal Claude Code config structure."""
    claude_home = tmp_path / ".claude"
    claude_home.mkdir()

    # Create CLAUDE.md
    (claude_home / "CLAUDE.md").write_text("# Test Rules\n")

    # Create skills directory
    skills = claude_home / "skills"
    skills.mkdir()

    return claude_home

# tests/test_config.py
def test_read_json_valid_file(tmp_path):
    """read_json parses valid JSON file."""
    json_file = tmp_path / "config.json"
    json_file.write_text('{"key": "value"}')

    result = read_json(json_file)
    assert result == {"key": "value"}

def test_read_json_missing_file_returns_empty_dict(tmp_path):
    """read_json returns empty dict for missing file."""
    missing = tmp_path / "nonexistent.json"

    result = read_json(missing)
    assert result == {}

def test_read_json_invalid_json_logs_error_returns_empty_dict(tmp_path, caplog):
    """read_json logs error and returns empty dict for invalid JSON."""
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{invalid json")

    result = read_json(bad_json)
    assert result == {}
    assert "Failed to read" in caplog.text
```

### Subprocess/Command Testing Pattern

Tests for watch mode and CLI argument handling should mock subprocess calls:

**Example pattern:**

```python
# tests/test_watch.py
from unittest.mock import patch, MagicMock

def test_watch_fswatch_calls_run_sync_on_change():
    """Watch mode calls run_sync when file changes detected."""
    with patch('subprocess.Popen') as mock_popen:
        mock_proc = MagicMock()
        mock_proc.stdout = ['file.md\n']
        mock_popen.return_value = mock_proc

        with patch('cc2all_sync.run_sync') as mock_run_sync:
            _watch_fswatch(['/test/path'], 'user', None)
            # Verify run_sync called after file change
            assert mock_run_sync.called

def test_watch_polling_detects_file_modifications(tmp_path):
    """Polling fallback detects file modifications via mtime."""
    test_file = tmp_path / "test.md"
    test_file.write_text("original")

    hashes = {str(test_file): file_hash(test_file)}

    # Modify file
    test_file.write_text("modified")

    new_hash = file_hash(test_file)
    assert hashes[str(test_file)] != new_hash
```

### Logger Testing Pattern

Since `Logger` class is used extensively, test its behavior:

**Example pattern:**

```python
# tests/test_logger.py
def test_logger_color_codes_output(capsys):
    """Logger applies color codes to output."""
    logger = Logger(verbose=False)
    logger.info("test message")

    captured = capsys.readouterr()
    assert "✓" in captured.out
    assert "\033[32m" in captured.out  # green color code

def test_logger_verbose_mode_shows_debug(capsys):
    """Logger.debug only shows in verbose mode."""
    logger_verbose = Logger(verbose=True)
    logger_quiet = Logger(verbose=False)

    logger_verbose.debug("verbose message")
    captured_verbose = capsys.readouterr()

    logger_quiet.debug("quiet message")
    captured_quiet = capsys.readouterr()

    assert "verbose message" in captured_verbose.out
    assert not captured_quiet.out

def test_logger_tracks_operation_counts():
    """Logger increments counters for operations."""
    logger = Logger()

    logger.synced()
    logger.synced()
    logger.error("test")

    summary = logger.summary()
    assert "2 synced" in summary
    assert "1 errors" in summary
```

### CLI Argument Testing Pattern

Test CLI argument parsing and scope detection:

**Example pattern:**

```python
# tests/test_cli.py
from unittest.mock import patch
import argparse

def test_cli_scope_argument_defaults_to_all():
    """CLI scope argument defaults to 'all'."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", choices=["user", "project", "all"], default="all")

    args = parser.parse_args([])
    assert args.scope == "all"

def test_cli_project_dir_auto_detection_finds_git_root():
    """detect_project_dir finds .git root."""
    with patch('pathlib.Path.cwd') as mock_cwd:
        project_path = Path("/home/user/project")
        mock_cwd.return_value = project_path / "src"

        with patch('pathlib.Path.exists', return_value=True):
            result = detect_project_dir()
            # Should find .git in parent
            assert result is not None

def test_cli_dry_run_prevents_writes(tmp_path):
    """--dry-run flag prevents file writes."""
    test_file = tmp_path / "test.txt"

    write_text(test_file, "content")  # actual write

    # With dry_run flag, write_text should not be called
    # (implementation would need refactoring to support this)
```

### Fixture Patterns

**Sample fixture for reusable test setup:**

```python
# tests/conftest.py
import pytest
from pathlib import Path
from unittest.mock import MagicMock

@pytest.fixture
def temp_harness_env(tmp_path):
    """Create complete temporary harness environment."""
    # User-level (global)
    user_home = tmp_path / "user_home"
    user_home.mkdir()

    cc_home = user_home / ".claude"
    cc_home.mkdir()
    (cc_home / "CLAUDE.md").write_text("# User Rules\n")

    codex_home = user_home / ".codex"
    (codex_home / "skills").mkdir(parents=True)

    gemini_home = user_home / ".gemini"
    gemini_home.mkdir()

    # Project-level
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".git").mkdir()  # simulate git repo

    proj_claude = project_dir / ".claude"
    proj_claude.mkdir()
    (proj_claude / "CLAUDE.md").write_text("# Project Rules\n")

    return {
        'user_home': user_home,
        'cc_home': cc_home,
        'codex_home': codex_home,
        'project_dir': project_dir,
    }

@pytest.fixture
def mock_logger(monkeypatch):
    """Mock global logger to avoid console output."""
    from unittest.mock import MagicMock
    mock_log = MagicMock()
    monkeypatch.setattr('cc2all_sync.log', mock_log)
    return mock_log
```

## Coverage & CI

### Coverage Goals

**Recommended minimum coverage: 75%**

Focus areas:
- All sync functions (`sync_to_codex`, `sync_to_gemini`, `sync_to_opencode`)
- Config reading functions (`get_cc_*` functions)
- File I/O helpers (`read_json`, `write_json`, `safe_symlink`)
- CLI argument parsing
- Error handling paths

**Non-essential to cover:**
- Watch mode threading/subprocess (integration tested manually)
- Color formatting in Logger (visual inspection sufficient)

### Test Commands

**To be defined in project Makefile or setup.cfg:**

```bash
# Run all tests
pytest tests/

# Run with coverage report
pytest tests/ --cov=. --cov-report=html

# Run specific test file
pytest tests/test_codex.py

# Run specific test function
pytest tests/test_codex.py::test_sync_to_codex_with_skills

# Run with verbose output
pytest tests/ -v

# Run with output on print statements (for debugging)
pytest tests/ -s
```

### CI/CD Setup

**Currently:** No CI/CD pipeline configured

**Recommended setup (GitHub Actions):**

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.9', '3.10', '3.11', '3.12']

    steps:
    - uses: actions/checkout@v3
    - uses: actions/setup-python@v4
      with:
        python-version: ${{ matrix.python-version }}
    - run: pip install pytest pytest-cov
    - run: pytest tests/ --cov=. --cov-report=lcov
    - uses: codecov/codecov-action@v3
      with:
        files: ./coverage.lcov
```

**Linting setup (pre-commit hooks):**

```yaml
# .pre-commit-config.yaml
repos:
- repo: https://github.com/psf/black
  rev: '23.1.0'
  hooks:
  - id: black
    language_version: python3.10

- repo: https://github.com/PyCQA/flake8
  rev: '6.0.0'
  hooks:
  - id: flake8
    args: ['--max-line-length=120']

- repo: https://github.com/PyCQA/isort
  rev: '5.12.0'
  hooks:
  - id: isort
```

## Key Test Files

### High-Priority Tests to Implement

**1. `tests/test_sync.py` — Core sync orchestration**
- `test_run_sync_user_scope_calls_all_targets()`
- `test_run_sync_project_scope_requires_project_dir()`
- `test_run_sync_saves_state_with_timestamp()`
- `test_sync_detects_no_changes_and_skips()`

**2. `tests/test_codex.py` — Codex target sync**
- `test_sync_to_codex_writes_rules_to_agents_md()`
- `test_sync_to_codex_creates_skill_symlinks()`
- `test_sync_to_codex_converts_agents_to_skills()`
- `test_sync_to_codex_converts_commands_to_skills()`
- `test_sync_to_codex_builds_mcp_config_toml()`
- `test_sync_to_codex_cleans_stale_symlinks()`

**3. `tests/test_config.py` — Configuration reading**
- `test_get_cc_rules_reads_user_claude_md()`
- `test_get_cc_rules_reads_project_claude_md()`
- `test_get_cc_rules_merges_user_and_project_scopes()`
- `test_get_cc_skills_discovers_user_skills()`
- `test_get_cc_skills_discovers_plugin_installed_skills()`
- `test_get_cc_agents_reads_agent_files()`
- `test_get_cc_mcp_merges_global_and_project_servers()`

**4. `tests/test_cli.py` — CLI interface**
- `test_cli_no_args_defaults_to_all_scope()`
- `test_cli_detects_project_from_git_root()`
- `test_cli_watch_mode_initializes_watcher()`
- `test_cli_dry_run_shows_changes_without_writing()`
- `test_cli_verbose_shows_debug_output()`

**5. `tests/test_logger.py` — Output formatting**
- `test_logger_colors_success_messages()`
- `test_logger_counts_operations()`
- `test_logger_generates_summary()`
- `test_logger_respects_verbose_flag()`

### Coverage Map

```
cc2all-sync.py (984 lines)
├── Logger class (35 lines) — ~70% coverage goal
├── Utility functions (60 lines) — ~90% coverage goal
│   ├── ensure_dir, file_hash, read_json, write_json
│   ├── safe_symlink, load_state, save_state
├── Source readers (110 lines) — ~85% coverage goal
│   ├── get_cc_rules, get_cc_skills, get_cc_agents
│   ├── get_cc_commands, get_cc_mcp, get_cc_settings
├── sync_to_codex (104 lines) — ~80% coverage goal
├── sync_to_gemini (60 lines) — ~80% coverage goal
├── sync_to_opencode (87 lines) — ~80% coverage goal
├── Orchestrator (50 lines) — ~85% coverage goal
│   ├── run_sync, detect_project_dir, main
└── Watch mode (100+ lines) — ~50% coverage goal (manual testing)
```

---

*Testing analysis: 2026-02-13*
