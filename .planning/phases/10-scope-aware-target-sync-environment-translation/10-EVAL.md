# Evaluation Plan: Phase 10 — Scope-Aware Target Sync & Environment Translation

**Designed:** 2026-02-15
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** Scope-aware MCP routing, environment variable translation, transport type detection
**Reference papers:** 10-RESEARCH.md (scope mapping, env var syntax analysis, transport compatibility)

## Evaluation Overview

Phase 10 implements scope-to-target mapping for Codex and Gemini adapters, translates environment variable syntax between Claude Code (bash-style `${VAR}`) and Codex (literal `env` map) formats, and validates transport type support per target CLI. This phase depends critically on Phase 9's scope-tagged MCP discovery — the metadata must flow through to correct file writes.

**Key challenges:**
1. **Scope routing correctness** — User/project/local MCPs must write to correct target-level config files (not collapse to single file)
2. **Environment variable translation** — Codex requires literal expansion (no interpolation support), Gemini preserves syntax natively
3. **Transport compatibility** — Codex doesn't support SSE; Gemini/OpenCode do. Detection and warnings required
4. **Backward compatibility** — Existing adapters may call old `sync_mcp()` interface; fallback required

This is primarily a **configuration mapping and format translation** phase with no algorithmic innovation — correctness depends on faithful implementation of 10-RESEARCH.md recommendations and specification accuracy in requirements (SYNC-01..04, ENV-01..03).

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| Scope routing accuracy | Requirements SYNC-01, SYNC-02 | Validating user/project file separation |
| Scope routing completeness | Requirements SYNC-03 | Plugin MCPs route to user-scope (not project) |
| Environment variable translation (Codex) | Recommendation 2 (10-RESEARCH.md) | Codex doesn't support `${VAR}` natively |
| Environment variable preservation (Gemini) | Requirement ENV-03 | Gemini supports `${VAR}` natively |
| Transport detection accuracy | Requirement SYNC-04 + 10-RESEARCH.md | Validating SSE/HTTP/stdio categorization |
| Transport validation warnings | Requirement SYNC-04 | Unsupported combos (SSE on Codex) must warn |
| Backward compatibility | Existing adapter interface | v1.0 adapters must continue working |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 6 | Basic functionality — imports, method existence, fixture setup |
| Proxy (L2) | 6 | Comprehensive routing, translation, and transport validation |
| Deferred (L3) | 3 | Real CLI integration, full end-to-end pipeline, production robustness |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: Module Imports
- **What:** All new and modified modules import without errors
- **Command:**
  ```bash
  python3 -c "
  from src.utils.env_translator import translate_env_vars_for_codex, preserve_env_vars_for_gemini, detect_transport_type, check_transport_support
  from src.adapters.base import Adapter
  from src.adapters.codex import CodexAdapter
  from src.adapters.gemini import GeminiAdapter
  from src.adapters.opencode import OpenCodeAdapter
  from src.orchestrator import Orchestrator
  print('S1: OK')
  "
  ```
- **Expected:** "S1: OK" printed, no ImportError
- **Failure means:** Syntax errors, circular imports, or missing dependencies

### S2: Env Translator Functions Exist
- **What:** All required functions in env_translator module exist with correct signatures
- **Command:**
  ```bash
  python3 -c "
  import inspect
  from src.utils.env_translator import translate_env_vars_for_codex, preserve_env_vars_for_gemini, detect_transport_type, check_transport_support

  # Check signatures
  sig1 = inspect.signature(translate_env_vars_for_codex)
  assert 'config' in sig1.parameters, 'translate_env_vars_for_codex missing config param'

  sig2 = inspect.signature(preserve_env_vars_for_gemini)
  assert 'config' in sig2.parameters, 'preserve_env_vars_for_gemini missing config param'

  sig3 = inspect.signature(detect_transport_type)
  assert 'config' in sig3.parameters, 'detect_transport_type missing config param'

  sig4 = inspect.signature(check_transport_support)
  assert 'transport_type' in sig4.parameters, 'check_transport_support missing transport_type param'
  assert 'target' in sig4.parameters, 'check_transport_support missing target param'

  print('S2: OK')
  "
  ```
- **Expected:** "S2: OK"
- **Failure means:** Function signatures don't match expected interface

### S3: Environment Variable Pattern Matching
- **What:** Regex pattern correctly identifies `${VAR}` and `${VAR:-default}` syntax
- **Command:**
  ```bash
  python3 -c "
  import os, re
  os.environ['TEST_VAR'] = 'test_value'

  from src.utils.env_translator import translate_env_vars_for_codex

  # Test basic ${VAR}
  config = {'command': 'server', 'args': ['\${TEST_VAR}']}
  result, warnings = translate_env_vars_for_codex(config)
  assert result['args'][0] == 'test_value', f'Expected test_value, got {result[\"args\"][0]}'

  # Test ${VAR:-default}
  config = {'command': 'server', 'args': ['\${UNDEFINED:-fallback}']}
  result, warnings = translate_env_vars_for_codex(config)
  assert result['args'][0] == 'fallback', f'Expected fallback, got {result[\"args\"][0]}'
  assert len(warnings) > 0, 'Expected warnings for undefined var'

  print('S3: OK')
  "
  ```
- **Expected:** "S3: OK"
- **Failure means:** Pattern matching incomplete (misses some var syntax)

### S4: Transport Type Detection
- **What:** Correctly classifies MCP server transport types
- **Command:**
  ```bash
  python3 -c "
  from src.utils.env_translator import detect_transport_type

  # Test stdio (command-based)
  assert detect_transport_type({'command': 'npx', 'args': []}) == 'stdio'

  # Test SSE URL
  assert detect_transport_type({'url': 'http://localhost:3000/sse'}) == 'sse'

  # Test HTTP URL
  assert detect_transport_type({'url': 'http://localhost:3000/rpc'}) == 'http'

  # Test unknown
  result = detect_transport_type({'invalid_key': 'value'})
  assert result == 'unknown', f'Expected unknown, got {result}'

  print('S4: OK')
  "
  ```
- **Expected:** "S4: OK"
- **Failure means:** Transport detection returns wrong types

### S5: Transport Support Validation
- **What:** Correctly identifies unsupported transport/target combinations
- **Command:**
  ```bash
  python3 -c "
  from src.utils.env_translator import check_transport_support

  # SSE supported on Gemini
  supported, msg = check_transport_support('sse', 'gemini')
  assert supported == True, 'SSE should be supported on Gemini'

  # SSE NOT supported on Codex
  supported, msg = check_transport_support('sse', 'codex')
  assert supported == False, 'SSE should NOT be supported on Codex'
  assert 'sse' in msg.lower(), f'Message should mention SSE: {msg}'

  # Stdio supported on all
  supported, msg = check_transport_support('stdio', 'codex')
  assert supported == True, 'Stdio should be supported on Codex'

  print('S5: OK')
  "
  ```
- **Expected:** "S5: OK"
- **Failure means:** Transport validation logic broken

### S6: Adapter Interface Compatibility
- **What:** Adapters have sync_mcp_scoped() method and fallback to sync_mcp()
- **Command:**
  ```bash
  python3 -c "
  import inspect
  from src.adapters.codex import CodexAdapter
  from src.adapters.gemini import GeminiAdapter

  # Check method existence
  assert hasattr(CodexAdapter, 'sync_mcp_scoped'), 'CodexAdapter missing sync_mcp_scoped'
  assert hasattr(GeminiAdapter, 'sync_mcp_scoped'), 'GeminiAdapter missing sync_mcp_scoped'

  # Check fallback method still exists
  assert hasattr(CodexAdapter, 'sync_mcp'), 'CodexAdapter missing sync_mcp (fallback)'

  print('S6: OK')
  "
  ```
- **Expected:** "S6: OK"
- **Failure means:** Adapter interface incomplete

**Sanity gate:** ALL 6 checks must pass. Any failure blocks progression to proxy metrics.

## Level 2: Proxy Metrics

**Purpose:** Comprehensive validation of scope routing, environment variable translation, and transport handling.
**IMPORTANT:** Proxy metrics are NOT validated substitutes for full evaluation. Treat results with appropriate skepticism.

### P1: Scope-Aware MCP Routing for Codex
- **What:** User-scope MCPs route to `~/.codex/config.toml`, project-scope MCPs route to `.codex/config.toml`
- **How:** Create test fixture with 2 user-scope and 1 project-scope MCP, call CodexAdapter.sync_mcp_scoped(), verify file writes
- **Command:**
  ```bash
  python3 -c "
  import os, json, tempfile, tomllib
  from pathlib import Path
  os.chdir('/tmp')  # Isolate test

  # Create temp Codex directory
  with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)
      home_dir = tmpdir / 'home'
      proj_dir = tmpdir / 'project'
      home_dir.mkdir()
      proj_dir.mkdir()

      # Mock home/project paths
      import src.adapters.codex as codex_module
      original_expanduser = Path.expanduser

      def mock_expanduser(self):
          if str(self).startswith('~'):
              return home_dir / str(self)[2:]
          return original_expanduser(self)

      Path.expanduser = mock_expanduser

      try:
          from src.adapters.codex import CodexAdapter
          adapter = CodexAdapter(scope='all', project_dir=proj_dir)

          # Test data
          scoped_mcps = {
              'user-server-1': {'config': {'command': 'cmd1'}, 'metadata': {'scope': 'user', 'source': 'file'}},
              'user-server-2': {'config': {'command': 'cmd2'}, 'metadata': {'scope': 'user', 'source': 'file'}},
              'proj-server-1': {'config': {'command': 'proj-cmd'}, 'metadata': {'scope': 'project', 'source': 'file'}}
          }

          # Run sync
          result = adapter.sync_mcp_scoped(scoped_mcps)

          # Verify files written
          user_config = home_dir / '.codex' / 'config.toml'
          proj_config = proj_dir / '.codex' / 'config.toml'

          assert user_config.exists(), f'User config not written: {user_config}'
          assert proj_config.exists(), f'Project config not written: {proj_config}'

          # Verify scope routing
          user_content = user_config.read_text()
          assert 'cmd1' in user_content or 'user-server-1' in user_content, 'User MCP 1 not in user config'
          assert 'cmd2' in user_content or 'user-server-2' in user_content, 'User MCP 2 not in user config'

          proj_content = proj_config.read_text()
          assert 'proj-cmd' in proj_content or 'proj-server-1' in proj_content, 'Project MCP not in project config'

          print('P1: OK')
      finally:
          Path.expanduser = original_expanduser
  "
  ```
- **Target:** User config contains 2 servers, project config contains 1 server (100% correct routing)
- **Evidence:** Requirements SYNC-01, SYNC-02 explicitly mandate scope-to-file mapping
- **Correlation with full metric:** MEDIUM-HIGH — Fixture tests correct behavior but doesn't test with real Codex installation
- **Blind spots:** Doesn't verify generated TOML is syntactically valid for real Codex; doesn't test edge cases (empty scope files, conflicts)
- **Validated:** false — awaiting Phase 10 deferred validation with real Codex CLI

### P2: Scope-Aware MCP Routing for Gemini
- **What:** User-scope MCPs route to `~/.gemini/settings.json`, project-scope MCPs route to `.gemini/settings.json`
- **How:** Similar to P1 but for Gemini, verify JSON structure
- **Command:**
  ```bash
  python3 -c "
  import os, json, tempfile
  from pathlib import Path
  os.chdir('/tmp')

  with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)
      home_dir = tmpdir / 'home'
      proj_dir = tmpdir / 'project'
      home_dir.mkdir()
      proj_dir.mkdir()

      # Mock paths for Gemini
      import src.adapters.gemini as gemini_module
      original_expanduser = Path.expanduser

      def mock_expanduser(self):
          if str(self).startswith('~'):
              return home_dir / str(self)[2:]
          return original_expanduser(self)

      Path.expanduser = mock_expanduser

      try:
          from src.adapters.gemini import GeminiAdapter
          adapter = GeminiAdapter(scope='all', project_dir=proj_dir)

          scoped_mcps = {
              'user-srv': {'config': {'command': 'usercmd'}, 'metadata': {'scope': 'user'}},
              'proj-srv': {'config': {'command': 'projcmd'}, 'metadata': {'scope': 'project'}}
          }

          result = adapter.sync_mcp_scoped(scoped_mcps)

          user_config = home_dir / '.gemini' / 'settings.json'
          proj_config = proj_dir / '.gemini' / 'settings.json'

          assert user_config.exists(), f'User Gemini config not written'
          assert proj_config.exists(), f'Project Gemini config not written'

          user_json = json.loads(user_config.read_text())
          proj_json = json.loads(proj_config.read_text())

          assert 'mcpServers' in user_json or 'user-srv' in str(user_json), 'User MCP not in user Gemini config'
          assert 'mcpServers' in proj_json or 'proj-srv' in str(proj_json), 'Project MCP not in project Gemini config'

          print('P2: OK')
      finally:
          Path.expanduser = original_expanduser
  "
  ```
- **Target:** User config contains 1 server, project config contains 1 server (100% correct routing)
- **Evidence:** Requirements SYNC-01 mandate Gemini scope separation
- **Correlation with full metric:** MEDIUM-HIGH — Similar to P1, tests structure but not real CLI integration
- **Blind spots:** Doesn't validate JSON schema matches real Gemini; doesn't test mcpServers field merging logic
- **Validated:** false — awaiting deferred validation

### P3: Plugin MCPs Route to User-Scope Only
- **What:** MCPs with metadata.source == 'plugin' always route to user-scope target config, never project-scope
- **How:** Create test with 1 user MCP, 1 project MCP, 1 plugin MCP; verify plugin writes only to user config for both Codex and Gemini
- **Command:**
  ```bash
  python3 -c "
  import tempfile, json
  from pathlib import Path

  with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)
      home_dir = tmpdir / 'home'
      proj_dir = tmpdir / 'project'
      home_dir.mkdir()
      proj_dir.mkdir()

      # Mock path expansion
      original_expanduser = Path.expanduser
      def mock_expanduser(self):
          if str(self).startswith('~'):
              return home_dir / str(self)[2:]
          return original_expanduser(self)
      Path.expanduser = mock_expanduser

      try:
          from src.adapters.codex import CodexAdapter

          scoped_mcps = {
              'user-srv': {'config': {'command': 'user-cmd'}, 'metadata': {'scope': 'user', 'source': 'file'}},
              'proj-srv': {'config': {'command': 'proj-cmd'}, 'metadata': {'scope': 'project', 'source': 'file'}},
              'plugin-srv': {'config': {'command': 'plugin-cmd'}, 'metadata': {'scope': 'user', 'source': 'plugin', 'plugin': 'TestPlugin@1.0'}}
          }

          adapter = CodexAdapter(scope='all', project_dir=proj_dir)
          adapter.sync_mcp_scoped(scoped_mcps)

          # Plugin MCP must NOT appear in project config
          proj_config = proj_dir / '.codex' / 'config.toml'
          proj_content = proj_config.read_text()

          assert 'plugin-cmd' not in proj_content, 'Plugin MCP should NOT be in project config'
          assert 'plugin-srv' not in proj_content, 'Plugin MCP should NOT be in project config'

          # Plugin MCP must appear in user config
          user_config = home_dir / '.codex' / 'config.toml'
          user_content = user_config.read_text()
          assert 'plugin-cmd' in user_content or 'plugin-srv' in user_content, 'Plugin MCP should be in user config'

          print('P3: OK')
      finally:
          Path.expanduser = original_expanduser
  "
  ```
- **Target:** Plugin MCP(s) in user config only, zero in project config (100% correct routing per SYNC-03)
- **Evidence:** Requirement SYNC-03 explicitly states "Plugin-discovered MCPs sync to user-scope target configs"
- **Correlation with full metric:** HIGH — Directly tests requirement
- **Blind spots:** Doesn't test with real plugins or multiple plugins
- **Validated:** false — deferred to Phase 10 integration

### P4: Environment Variable Translation for Codex
- **What:** Codex adapter extracts `${VAR}` and `${VAR:-default}` from config, expands to literal values, and merges into Codex env map
- **How:** Create fixture with 2 env vars (`${TEST_KEY}` and `${UNDEFINED:-fallback}`), call sync_mcp_scoped, verify TOML has literal values and env map
- **Command:**
  ```bash
  python3 -c "
  import os, tempfile
  from pathlib import Path

  os.environ['TEST_KEY'] = 'resolved-value'
  if 'UNDEFINED_VAR' in os.environ:
      del os.environ['UNDEFINED_VAR']

  with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)
      home_dir = tmpdir / 'home'
      proj_dir = tmpdir / 'project'
      home_dir.mkdir()
      proj_dir.mkdir()

      original_expanduser = Path.expanduser
      def mock_expanduser(self):
          if str(self).startswith('~'):
              return home_dir / str(self)[2:]
          return original_expanduser(self)
      Path.expanduser = mock_expanduser

      try:
          from src.adapters.codex import CodexAdapter

          scoped_mcps = {
              'env-server': {
                  'config': {
                      'command': 'server',
                      'args': ['--key', '\${TEST_KEY}', '--port', '\${UNDEFINED_VAR:-9000}'],
                      'env': {'EXISTING': 'kept'}
                  },
                  'metadata': {'scope': 'user', 'source': 'file'}
              }
          }

          adapter = CodexAdapter(scope='user', project_dir=proj_dir)
          adapter.sync_mcp_scoped(scoped_mcps)

          user_config = home_dir / '.codex' / 'config.toml'
          content = user_config.read_text()

          # Verify expanded values (literal, not \${VAR})
          assert 'resolved-value' in content, 'TEST_KEY should be expanded to resolved-value'
          assert '9000' in content, 'Default value should be used for UNDEFINED_VAR'
          assert '\${TEST_KEY}' not in content or 'env' in content, 'Should not have bare \${VAR} after expansion'
          assert 'EXISTING' in content, 'Existing env entries should be preserved'

          print('P4: OK')
      finally:
          Path.expanduser = original_expanduser
  "
  ```
- **Target:** Literal values in args/command, env map has both extracted and existing values, no `${VAR}` syntax (100% translation)
- **Evidence:** Recommendation 2 in 10-RESEARCH.md documents Codex env var incompatibility; ENV-01, ENV-02 requirements
- **Correlation with full metric:** MEDIUM — Tests extraction logic but doesn't verify Codex CLI can actually parse generated TOML
- **Blind spots:** Edge cases (empty values, special characters), complex nested structures, unquoted TOML strings
- **Validated:** false — deferred to real Codex testing

### P5: Environment Variable Preservation for Gemini
- **What:** Gemini adapter preserves `${VAR}` syntax unchanged (Gemini supports natively per ENV-03)
- **How:** Create fixture with `${API_KEY}` in config, verify it appears unchanged in Gemini settings.json
- **Command:**
  ```bash
  python3 -c "
  import json, tempfile
  from pathlib import Path

  with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)
      home_dir = tmpdir / 'home'
      proj_dir = tmpdir / 'project'
      home_dir.mkdir()
      proj_dir.mkdir()

      original_expanduser = Path.expanduser
      def mock_expanduser(self):
          if str(self).startswith('~'):
              return home_dir / str(self)[2:]
          return original_expanduser(self)
      Path.expanduser = mock_expanduser

      try:
          from src.adapters.gemini import GeminiAdapter

          scoped_mcps = {
              'api-server': {
                  'config': {
                      'command': 'server',
                      'args': ['--api-key', '\${API_KEY}', '--port', '\${PORT:-8080}']
                  },
                  'metadata': {'scope': 'user', 'source': 'file'}
              }
          }

          adapter = GeminiAdapter(scope='user', project_dir=proj_dir)
          adapter.sync_mcp_scoped(scoped_mcps)

          user_config = home_dir / '.gemini' / 'settings.json'
          settings = json.loads(user_config.read_text())

          # Find api-server in mcpServers
          mcps = settings.get('mcpServers', {})
          assert 'api-server' in mcps, 'Server not found in mcpServers'

          config_str = json.dumps(mcps['api-server'])
          assert '\${API_KEY}' in config_str, 'API_KEY var syntax should be preserved'
          assert '\${PORT:-8080}' in config_str, 'PORT var with default should be preserved'

          print('P5: OK')
      finally:
          Path.expanduser = original_expanduser
  "
  ```
- **Target:** Both `${API_KEY}` and `${PORT:-8080}` appear unchanged in Gemini settings.json (100% preservation)
- **Evidence:** ENV-03 requirement states "Preserve env var references in Gemini settings.json format (Gemini supports `${VAR}` natively)"
- **Correlation with full metric:** MEDIUM-HIGH — Tests JSON content but doesn't verify Gemini CLI interpretation
- **Blind spots:** Complex env var syntax (nested expansions), Gemini's actual runtime interpolation behavior
- **Validated:** false — deferred to Phase 10 integration with real Gemini

### P6: Transport Type Detection and Unsupported Warnings
- **What:** Adapters detect transport types and warn (not skip) for unsupported combos like SSE on Codex
- **How:** Create MCP with SSE transport, call CodexAdapter.sync_mcp_scoped(), verify warning logged, MCP not written
- **Command:**
  ```bash
  python3 -c "
  import tempfile, io, sys, logging
  from pathlib import Path

  with tempfile.TemporaryDirectory() as tmpdir:
      tmpdir = Path(tmpdir)
      home_dir = tmpdir / 'home'
      proj_dir = tmpdir / 'project'
      home_dir.mkdir()
      proj_dir.mkdir()

      original_expanduser = Path.expanduser
      def mock_expanduser(self):
          if str(self).startswith('~'):
              return home_dir / str(self)[2:]
          return original_expanduser(self)
      Path.expanduser = mock_expanduser

      try:
          # Capture log output
          log_capture = io.StringIO()
          handler = logging.StreamHandler(log_capture)
          handler.setLevel(logging.WARNING)

          from src.adapters.codex import CodexAdapter

          scoped_mcps = {
              'sse-server': {
                  'config': {'url': 'http://localhost:3000/sse'},  # SSE transport
                  'metadata': {'scope': 'user', 'source': 'file'}
              },
              'stdio-server': {
                  'config': {'command': 'normal-server'},
                  'metadata': {'scope': 'user', 'source': 'file'}
              }
          }

          adapter = CodexAdapter(scope='user', project_dir=proj_dir)
          result = adapter.sync_mcp_scoped(scoped_mcps)

          user_config = home_dir / '.codex' / 'config.toml'
          content = user_config.read_text()

          # SSE server should be skipped/warned, not written
          assert 'sse-server' not in content, 'SSE server should be skipped on Codex'

          # Stdio server should be present
          assert 'stdio-server' in content or 'normal-server' in content, 'Stdio server should be written'

          # Check result or logs for warning
          assert 'sse' in str(result).lower() or 'SSE' in str(result) or 'unsupported' in str(result).lower(), \
              f'Result should mention SSE unsupported: {result}'

          print('P6: OK')
      finally:
          Path.expanduser = original_expanduser
  "
  ```
- **Target:** SSE MCP not written to Codex config, warning present in result/logs, stdio MCP written normally
- **Evidence:** Requirement SYNC-04 states "Adapters detect unsupported transport types per target (e.g., SSE on Codex) and warn instead of silently failing"
- **Correlation with full metric:** HIGH — Directly tests requirement
- **Blind spots:** Doesn't test all transport combos (HTTP/stdio on all targets), edge cases
- **Validated:** false — deferred to Phase 10 integration

**Proxy metrics confidence:** MEDIUM-HIGH for routing/translation/transport validation. Actual CLI parsing/interpretation not tested in proxy.

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring integration or resources not available now.

### D1: Real Codex CLI Integration Test — DEFER-10-01
- **What:** Generated Codex config.toml files are syntactically valid and can be parsed by real Codex CLI
- **How:**
  1. Run Phase 10 sync with mixed MCP types (user-scope with env vars, project-scope, SSE, stdio)
  2. Validate generated TOML files using `tomllib` or `toml` library parser
  3. Invoke real Codex CLI with generated config (e.g., `codex --version` to verify config loads)
  4. Inspect Codex MCP server registry after loading (if tool available)
  5. Test MCP invocation through Codex
- **Why deferred:** Requires real Codex installation + Claude Code environment
- **Validates at:** Phase 10 (same phase, but integration test after all plans complete)
- **Depends on:**
  - Real Codex CLI installed and functional
  - Phase 10-02 adapter implementation complete
  - Test MCP server(s) for invocation testing
- **Target:**
  - Generated TOML parses without errors: 100%
  - Codex CLI loads config without warnings: 100%
  - User-scope MCPs in user config: 100%
  - Project-scope MCPs in project config: 100%
  - Env vars expanded to literal values: 100%
  - SSE MCPs skipped with warning: 100%
- **Risk if unmet:** Generated TOML has syntax errors (quote escaping, section nesting), Codex can't parse it — Phase 10 blocked
- **Fallback:** Manual TOML inspection + syntax checking tool (tomllib); skip Codex CLI testing

### D2: Real Gemini CLI Integration Test — DEFER-10-02
- **What:** Generated Gemini settings.json files are valid JSON and load into real Gemini CLI
- **How:**
  1. Run Phase 10 sync with mixed scopes and env var syntax
  2. Validate JSON structure using `json` module
  3. Invoke real Gemini CLI with generated config
  4. Verify MCPs appear in Gemini's available tools
  5. Test MCP invocation through Gemini
- **Why deferred:** Requires real Gemini installation
- **Validates at:** Phase 10 integration tests
- **Depends on:**
  - Real Gemini CLI installed and functional
  - Phase 10-02 adapter implementation
  - Functional test MCP server
- **Target:**
  - Generated JSON valid: 100%
  - Gemini CLI loads config: 100%
  - User-scope MCPs in user config: 100%
  - Project-scope MCPs in project config: 100%
  - Env var syntax preserved: 100%
  - MCP invocation works: 100%
- **Risk if unmet:** JSON structure wrong (mcpServers field missing, scope nesting incorrect) — Phase 10 blocked
- **Fallback:** Python JSON validation only; skip Gemini CLI testing

### D3: Full v2.0 Pipeline Integration — DEFER-10-03
- **What:** End-to-end validation: Phase 9 scoped discovery → Phase 10 scope-aware routing → correct target configs with proper env translation
- **How:**
  1. Install real Claude Code plugins (Context7, GitHub plugin with MCPs)
  2. Configure user/project/local MCPs in ~/.claude.json and .mcp.json with env vars
  3. Run HarnessSync full sync command
  4. Verify all scopes respected:
     - User MCPs in ~/.codex/config.toml and ~/.gemini/settings.json
     - Project MCPs in .codex/config.toml and .gemini/settings.json
     - Local-scope MCPs in user config (override lower precedence)
     - Plugin MCPs in user config only
  5. Verify env translation:
     - Codex: `${API_KEY}` → literal value from os.environ
     - Gemini: `${API_KEY}` → preserved as-is
  6. Invoke actual MCPs through Codex and Gemini to validate end-to-end
- **Why deferred:** Requires complete Phase 9 + 10 implementation, real Claude Code, real plugins, real target CLIs
- **Validates at:** Phase 10 completion (after all 3 plans complete)
- **Depends on:**
  - Phase 9 implementation + passing tests
  - Phase 10 implementation complete (all 3 plans)
  - Real Claude Code installation with plugins
  - Real Codex and Gemini installations
  - Functional test MCP servers
- **Target:**
  - All 4 scope sources discovered: 100% (user file, plugin, project file, local)
  - Scope routing correct: 100% (user/project MCPs in correct files)
  - Scope precedence respected: 100% (local > project > user)
  - Plugin MCPs user-scope only: 100%
  - Codex env translation: 100% (literal values)
  - Gemini env preservation: 100% (syntax intact)
  - Transport validation: 100% (SSE skipped on Codex/OpenCode)
  - End-to-end MCP invocation: 100% (actual tool calls work)
  - No scope collapse: 0 MCPs in wrong scope (user scope not mixed into project config)
- **Risk if unmet:**
  - Scope collapse: MCPs written to wrong scope files — critical, breaks per-project overrides
  - Env translation incomplete: Codex MCPs don't work at runtime — critical
  - Transport validation silent: SSE MCPs appear in Codex config, fail at runtime — high
  - Plugin MCPs in project config: Breaks installation model — high
- **Fallback:** Manual MCP config per target (defeats purpose of sync); scope separation via separate CLI commands (high maintenance)

## Ablation Plan

**No ablation plan applicable** — This phase implements a single configuration mapping approach with no alternative implementations to compare.

**Rationale:** Ablation is meaningful when comparing different algorithmic approaches (e.g., centralized routing vs decentralized). Phase 10 has one approach: add scope parameter to existing adapters and call translation functions. There's no baseline alternative to ablate.

## Baselines

| Baseline | Description | Current Behavior | v2.0 Target | Source |
|----------|-------------|------------------|------------|--------|
| v1.0 Adapter interface | sync_mcp(flat_dict) | All MCPs write to single project-level config | Route by scope to user/project files | Adapter implementation |
| v1.0 Env var handling | Passed through verbatim | `${VAR}` in Codex TOML (causes errors) | Codex: expand to env map; Gemini: preserve | 10-RESEARCH.md |
| v1.0 Transport support | Assumed all supported | No warnings for unsupported combos | Detect SSE/HTTP/stdio, warn on unsupported | SYNC-04 requirement |
| v1.0 Scope awareness | None | User/project MCPs collapsed to one file | Separate user and project config files | SYNC-01, SYNC-02 |

**Baseline comparison:**
- v1.0: 0% scope separation, 0% env translation, 0% transport validation
- v2.0 Phase 10 target: 100% scope separation, 100% env translation (Codex), 100% transport validation

## Evaluation Scripts

**Location of evaluation code:**
```
.planning/phases/10-scope-aware-target-sync-environment-translation/10-01-PLAN.md (env translator implementation)
.planning/phases/10-scope-aware-target-sync-environment-translation/10-02-PLAN.md (adapter scope routing)
.planning/phases/10-scope-aware-target-sync-environment-translation/10-03-PLAN.md (integration test)
src/utils/env_translator.py (Phase 10-01 output)
verify_phase10_integration.py (Phase 10-03 output)
```

**How to run full proxy evaluation:**
```bash
# Sanity checks (S1-S6)
python3 -c "from src.utils.env_translator import translate_env_vars_for_codex; print('S1: OK')"

# S2-S6: Run inline tests from each sanity check definition above
# (See individual S1-S6 commands)

# Proxy metrics (P1-P6)
# Run comprehensive fixture tests for routing, translation, transport validation

# All proxy verification in one command
python3 -c "$(cat <<'EOF'
# P1: Codex scope routing
# P2: Gemini scope routing
# P3: Plugin MCPs to user-scope
# P4: Env var translation (Codex)
# P5: Env var preservation (Gemini)
# P6: Transport detection and warnings
# See individual proxy metric commands above
EOF
)"

# Integration test (Phase 10-03)
python3 verify_phase10_integration.py
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: Module imports | PASS/FAIL | | |
| S2: Function signatures | PASS/FAIL | | |
| S3: Env var pattern matching | PASS/FAIL | | |
| S4: Transport type detection | PASS/FAIL | | |
| S5: Transport support validation | PASS/FAIL | | |
| S6: Adapter interface compatibility | PASS/FAIL | | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: Codex scope routing | 2 user + 1 proj | | MET/MISSED | |
| P2: Gemini scope routing | 1 user + 1 proj | | MET/MISSED | |
| P3: Plugin MCPs user-scope | Plugin not in proj | | MET/MISSED | |
| P4: Codex env translation | 100% literal values | | MET/MISSED | |
| P5: Gemini env preservation | 100% syntax preserved | | MET/MISSED | |
| P6: Transport validation | SSE skipped + warning | | MET/MISSED | |

### Ablation Results

N/A — No ablation plan for this phase (single approach, no alternatives)

### Deferred Status

| ID | Metric | Status | Validates At | Risk |
|----|--------|--------|-------------|------|
| DEFER-10-01 | Real Codex CLI integration | PENDING | Phase 10 integration | TOML syntax/parsing errors |
| DEFER-10-02 | Real Gemini CLI integration | PENDING | Phase 10 integration | JSON structure errors |
| DEFER-10-03 | Full v2.0 pipeline | PENDING | Phase 10 integration | Scope collapse, env translation gaps |

## Evaluation Confidence

**Overall confidence in evaluation design:** MEDIUM-HIGH

**Justification:**

- **Sanity checks:** ADEQUATE — 6 checks cover all new functions, signatures, pattern matching, transport detection, and backward compatibility. No algorithmic gaps.
- **Proxy metrics:** WELL-DESIGNED — Test fixture approach validates core logic (scope routing, env translation, transport detection) without requiring real CLIs. Each metric traces to requirement or research recommendation.
- **Deferred coverage:** COMPREHENSIVE — Three critical integration risks identified: TOML syntax (D1), JSON structure (D2), end-to-end scope/env correctness (D3). Full v2.0 pipeline validation at D3 ensures requirements are actually met in practice.

**What this evaluation CAN tell us:**

- Scope routing logic is correct (user/project MCPs write to separate files)
- Plugin MCPs route to user-scope only
- Environment variable extraction and translation work (Codex literal expansion, Gemini preservation)
- Transport type detection accurately classifies stdio/SSE/HTTP
- Unsupported transport/target combos are detected and warned
- Adapter interface maintains backward compatibility
- Generated TOML/JSON structure matches expected schema (via fixture validation)

**What this evaluation CANNOT tell us:**

- Real Codex CLI can parse generated TOML (syntax, reserved keywords, section nesting) — validates at DEFER-10-01
- Real Gemini CLI can parse generated JSON and invoke MCPs — validates at DEFER-10-02
- Full v2.0 end-to-end flow with real plugins, multiple scopes, and actual MCP invocation — validates at DEFER-10-03
- Edge cases: special characters in env values, very large configs, symlinked plugin paths, non-ASCII env vars — assumes not tested, scope for future phases
- Performance with many MCPs (50+) — assumes acceptable based on Phase 1-3 performance

## Proxy Metric Caveats

The proxy metrics in P1-P6 use fixture testing (mock file systems) rather than real CLI installations. This is necessary to run Phase 10 evaluation independently, but introduces these blind spots:

1. **TOML syntax validation** — Generated TOML checked only for content presence, not parsed by actual Codex
2. **JSON structure validation** — Generated JSON checked only for field presence, not parsed by actual Gemini
3. **Env var expansion correctness** — Values expanded and written, but not consumed by real MCP servers
4. **Transport handling** — Warnings logged, but not tested against actual MCP server transports

**Mitigation strategy:** Deferred validations (D1-D3) cover these gaps by testing with real CLIs. Phase 10 is not complete until all deferred validations pass.

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-02-15*
*Phase 10 context: 3 plans (10-01: env translator, 10-02: scope-aware adapters, 10-03: integration test)*
