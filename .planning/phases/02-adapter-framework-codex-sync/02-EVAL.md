# Evaluation Plan: Phase 2 — Adapter Framework & Codex Sync

**Designed:** 2026-02-13
**Designer:** Claude (grd-eval-planner)
**Phase components:** Adapter framework infrastructure, Codex rules/skills/agents/commands sync, Codex MCP translation + permission mapping
**Requirements covered:** ADP-01, ADP-02, ADP-03, CDX-01, CDX-02, CDX-03, CDX-04, CDX-05, CDX-06

## Evaluation Overview

Phase 2 builds the extensible adapter framework and implements the first complete target adapter (Codex CLI). This phase has three critical dimensions to evaluate:

1. **Framework correctness**: ABC enforcement, registry pattern, structured results
2. **Format translation accuracy**: JSON→TOML, Agent→SKILL.md, permission mapping
3. **Integration reliability**: Full pipeline from source discovery to target sync

The evaluation strategy uses sanity checks for framework patterns (ABC validation, TOML round-trips), proxy metrics for translation quality (format validation, conservative mapping verification), and defers end-to-end Codex CLI validation to Phase 4 integration testing.

**What makes this phase verifiable now:** All adapter code is pure Python stdlib transformations. TOML generation can be verified by parsing with tomllib. Agent conversion can be verified by checking output format. Permission mapping can be verified against documented rules.

**What cannot be verified until later:** Whether Codex CLI actually loads the generated configs correctly, whether symlinked skills work in Codex's resolution order, whether permission settings achieve intended security boundaries.

## Evaluation Philosophy

This phase implements **three distinct patterns** that must all work correctly:

1. **Extension pattern** (adapter framework): Validates at registration time, not runtime
2. **Translation pattern** (format conversion): Must be lossless where possible, conservative where not
3. **Merge pattern** (config coexistence): Must preserve existing user content while updating managed sections

Evaluation must verify each pattern independently before testing integration.

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality and prevent catastrophic failures. These MUST ALL PASS before proceeding to proxy metrics.

### S1: Adapter Framework Registration

**What:** AdapterRegistry validates inheritance and prevents non-adapter registration

**Command:**
```bash
python3 -c "
from pathlib import Path
from src.adapters import AdapterBase, AdapterRegistry

# Should raise TypeError at registration time
try:
    @AdapterRegistry.register('bad')
    class NotAnAdapter:
        pass
    assert False, 'Should have raised TypeError'
except TypeError as e:
    assert 'AdapterBase' in str(e)
    print('Registry validation: PASS')
"
```

**Expected:** TypeError raised with message mentioning AdapterBase
**Failure means:** Registry pattern broken, any class can register (security risk)

### S2: ABC Abstract Method Enforcement

**What:** AdapterBase enforces all 6 sync methods + target_name property

**Command:**
```bash
python3 -c "
from pathlib import Path
from src.adapters import AdapterBase

class IncompleteAdapter(AdapterBase):
    @property
    def target_name(self) -> str:
        return 'test'
    # Missing: sync_rules, sync_skills, sync_agents, sync_commands, sync_mcp, sync_settings

try:
    adapter = IncompleteAdapter(Path('.'))
    assert False, 'Should have raised TypeError'
except TypeError as e:
    assert 'abstract' in str(e).lower()
    print('ABC enforcement: PASS')
"
```

**Expected:** TypeError with "abstract" in message
**Failure means:** ABC pattern broken, incomplete adapters can be instantiated

### S3: TOML Escaping Round-Trip

**What:** All special characters escape correctly and parse back identically

**Command:**
```bash
python3 -c "
import tomllib
from src.utils.toml_writer import escape_toml_string

test_cases = [
    'simple',
    'with\"quotes',
    'with\\\\backslash',
    'path\\\\to\\\\file',
    'multi\\nline',
    '\${API_KEY}',
    'combo: \"quoted\\\\path\\n\"',
]

for s in test_cases:
    escaped = escape_toml_string(s)
    toml_str = f'test = \"{escaped}\"'
    parsed = tomllib.loads(toml_str)
    assert parsed['test'] == s, f'Round-trip failed: {s}'

print('TOML escaping: PASS')
"
```

**Expected:** All test cases parse and round-trip identically
**Failure means:** TOML generation is broken (Pitfall 1 - escaping order)

### S4: SyncResult Merge Logic

**What:** Merging two SyncResults combines counts additively and concatenates file lists

**Command:**
```bash
python3 -c "
from src.adapters import SyncResult

r1 = SyncResult(synced=2, failed=1, synced_files=['a', 'b'], failed_files=['c'])
r2 = SyncResult(synced=1, skipped=3, synced_files=['d'], skipped_files=['e', 'f', 'g'])
merged = r1.merge(r2)

assert merged.synced == 3
assert merged.failed == 1
assert merged.skipped == 3
assert merged.synced_files == ['a', 'b', 'd']
assert merged.skipped_files == ['e', 'f', 'g']
assert merged.failed_files == ['c']

print('SyncResult merge: PASS')
"
```

**Expected:** All assertions pass
**Failure means:** Result aggregation is broken

### S5: Codex Adapter Registration

**What:** CodexAdapter is discoverable via registry

**Command:**
```bash
python3 -c "
from src.adapters import AdapterRegistry
from pathlib import Path

# Import to trigger registration
import src.adapters.codex

assert 'codex' in AdapterRegistry.list_targets()
adapter = AdapterRegistry.get_adapter('codex', Path('.'))
assert adapter.target_name == 'codex'

print('Codex registration: PASS')
"
```

**Expected:** 'codex' in registry, adapter instantiates
**Failure means:** Self-registration decorator broken

### S6: MCP TOML Round-Trip

**What:** Generated MCP server config parses back to same values

**Command:**
```bash
python3 -c "
import tomllib
from src.utils.toml_writer import format_mcp_server_toml

config = {
    'command': '/usr/bin/mcp-server',
    'args': ['--verbose', '--port', '3000'],
    'env': {'API_TOKEN': '\${MCP_TOKEN}', 'DB_HOST': 'localhost'},
    'enabled': True,
    'startup_timeout_sec': 10,
}

toml_str = format_mcp_server_toml('test-server', config)
parsed = tomllib.loads(toml_str)

srv = parsed['mcp_servers']['test-server']
assert srv['command'] == '/usr/bin/mcp-server'
assert srv['args'] == ['--verbose', '--port', '3000']
assert srv['env']['API_TOKEN'] == '\${MCP_TOKEN}'  # Env var preserved
assert srv['env']['DB_HOST'] == 'localhost'
assert srv['enabled'] == True
assert srv['startup_timeout_sec'] == 10

print('MCP round-trip: PASS')
"
```

**Expected:** All fields match, env vars preserved as literal strings
**Failure means:** TOML generation or env var preservation broken (Pitfall 2)

**Sanity gate:** ALL 6 sanity checks must pass. Any failure blocks progression to proxy metrics.

## Level 2: Proxy Metrics

**Purpose:** Validate translation accuracy and integration behavior without requiring Codex CLI installation.

**IMPORTANT:** These are proxy metrics. They validate format correctness but NOT whether Codex CLI accepts the output. Treat results with appropriate skepticism.

### P1: Agent-to-SKILL.md Conversion Accuracy

**What:** Claude Code agent .md files convert to valid Codex SKILL.md format
**How:** Parse converted SKILL.md, verify frontmatter and structure
**Command:**
```bash
python3 -c "
import tempfile, shutil, re
from pathlib import Path
from src.adapters.codex import CodexAdapter

tmp = Path(tempfile.mkdtemp())
adapter = CodexAdapter(tmp)

# Create test agent with all features
agent_file = tmp / 'test-agent.md'
agent_file.write_text('''---
name: code-reviewer
description: Reviews code for quality
tools: Read, Grep
color: blue
---

<role>
You review code. Check for:
1. Style
2. Bugs
</role>
''')

result = adapter.sync_agents({'reviewer': agent_file})
skill_md = tmp / '.agents' / 'skills' / 'agent-reviewer' / 'SKILL.md'
content = skill_md.read_text()

# Validate structure
assert re.search(r'^---\\nname: code-reviewer\\ndescription: Reviews code', content, re.MULTILINE)
assert 'You review code' in content
assert 'tools:' not in content  # Claude-specific fields removed
assert 'color:' not in content
assert 'When to Use This Skill' in content

shutil.rmtree(tmp)
print('PASS: Agent conversion preserves name/description, extracts role, strips Claude fields')
"
```

**Target:** 100% of test agents convert with valid frontmatter and content
**Evidence from:** 02-RESEARCH.md Pattern 4 (Agent→Skill Conversion), Codex SKILL.md format spec
**Correlation with full metric:** HIGH — format matches Codex spec exactly
**Blind spots:** Does not verify Codex CLI loads the skill correctly, or that skill instructions are semantically accurate
**Validated:** No — awaiting deferred validation in Phase 4 integration

### P2: AGENTS.md Managed Section Preservation

**What:** sync_rules preserves user content outside HarnessSync markers
**How:** Write AGENTS.md with user content, sync rules, verify user content intact
**Command:**
```bash
python3 -c "
import tempfile, shutil
from pathlib import Path
from src.adapters.codex import CodexAdapter

tmp = Path(tempfile.mkdtemp())
adapter = CodexAdapter(tmp)

# Initial sync
rules1 = [{'path': Path('CLAUDE.md'), 'content': 'Rule set 1'}]
adapter.sync_rules(rules1)

# User adds custom content
agents_md = tmp / 'AGENTS.md'
original = agents_md.read_text()
agents_md.write_text('# My Custom Instructions\\n\\nDo X always.\\n\\n' + original)

# Sync again with different rules
rules2 = [{'path': Path('CLAUDE.md'), 'content': 'Rule set 2 (updated)'}]
adapter.sync_rules(rules2)

content = agents_md.read_text()
assert 'My Custom Instructions' in content
assert 'Do X always' in content
assert 'Rule set 2' in content
assert 'Rule set 1' not in content  # Old managed content replaced

shutil.rmtree(tmp)
print('PASS: User content preserved, managed section updated')
"
```

**Target:** User content present before and after sync
**Evidence from:** 02-RESEARCH.md AGENTS.md Format (marker-based managed sections)
**Correlation with full metric:** HIGH — directly tests the merge pattern
**Blind spots:** Does not test with malformed markers or edge cases (multiple marker sections)
**Validated:** No — awaiting manual testing with real user workflows

### P3: Permission Mapping Conservatism

**What:** Claude Code permission settings map conservatively (any deny → read-only)
**How:** Test various permission combinations, verify sandbox_mode
**Command:**
```bash
python3 -c "
import tempfile, shutil, tomllib
from pathlib import Path
from src.adapters.codex import CodexAdapter

def test_permissions(settings, expected_sandbox):
    tmp = Path(tempfile.mkdtemp())
    adapter = CodexAdapter(tmp)
    adapter.sync_settings(settings)
    config = tmp / '.codex' / 'codex.toml'
    with open(config, 'rb') as f:
        parsed = tomllib.load(f)
    actual = parsed.get('sandbox_mode')
    shutil.rmtree(tmp)
    assert actual == expected_sandbox, f'Expected {expected_sandbox}, got {actual}'

# Test 1: Any denied tool -> read-only
test_permissions(
    {'permissions': {'allow': ['Bash'], 'deny': ['WebSearch']}},
    'read-only'
)

# Test 2: All allowed -> workspace-write
test_permissions(
    {'permissions': {'allow': ['Bash', 'Read', 'Write']}},
    'workspace-write'
)

# Test 3: Empty permissions -> workspace-write (default)
test_permissions({}, 'workspace-write')

print('PASS: Permission mapping is conservative')
"
```

**Target:** 100% of test cases map as expected
**Evidence from:** 02-RESEARCH.md Recommendation 4 (Conservative Permission Mapping), Codex sandbox documentation
**Correlation with full metric:** MEDIUM — validates mapping logic but not actual security behavior
**Blind spots:** Does not verify Codex CLI enforces these settings correctly, or whether workspace-write is sufficient/excessive for given tools
**Validated:** No — awaiting security review in Phase 5

### P4: MCP Config Merge Behavior

**What:** Multiple sync_mcp calls merge servers, don't overwrite entire config
**How:** Sync MCP servers, sync settings, verify both present
**Command:**
```bash
python3 -c "
import tempfile, shutil, tomllib
from pathlib import Path
from src.adapters.codex import CodexAdapter

tmp = Path(tempfile.mkdtemp())
adapter = CodexAdapter(tmp)

# Sync MCP servers first
adapter.sync_mcp({'server-a': {'command': 'a'}})

# Sync settings (should preserve MCP section)
adapter.sync_settings({'permissions': {'allow': ['Bash']}})

# Sync more MCP servers (should preserve settings + merge servers)
adapter.sync_mcp({'server-b': {'command': 'b'}})

config = tmp / '.codex' / 'codex.toml'
with open(config, 'rb') as f:
    parsed = tomllib.load(f)

assert 'sandbox_mode' in parsed, 'Settings lost'
assert 'mcp_servers' in parsed, 'MCP servers lost'
assert 'server-a' in parsed['mcp_servers'], 'First server lost'
assert 'server-b' in parsed['mcp_servers'], 'Second server lost'

shutil.rmtree(tmp)
print('PASS: MCP and settings sections coexist without overwriting')
"
```

**Target:** All sections present after multiple syncs
**Evidence from:** 02-RESEARCH.md section on merging existing TOML configs
**Correlation with full metric:** HIGH — directly tests merge logic
**Blind spots:** Does not test concurrent writes or race conditions
**Validated:** No — awaiting concurrency testing in Phase 5

### P5: Skills Symlink Idempotency

**What:** Syncing same skills twice skips already-linked skills
**How:** Sync skills, verify synced count, sync again, verify skipped count
**Command:**
```bash
python3 -c "
import tempfile, shutil
from pathlib import Path
from src.adapters.codex import CodexAdapter

tmp = Path(tempfile.mkdtemp())
adapter = CodexAdapter(tmp)

# Create source skill
skill_src = tmp / 'source' / 'my-skill'
skill_src.mkdir(parents=True)
(skill_src / 'SKILL.md').write_text('---\\nname: my-skill\\n---\\nContent')

# First sync
result1 = adapter.sync_skills({'my-skill': skill_src})
assert result1.synced == 1

# Second sync (idempotent)
result2 = adapter.sync_skills({'my-skill': skill_src})
assert result2.skipped >= 1, f'Expected skipped >= 1, got {result2.skipped}'

shutil.rmtree(tmp)
print('PASS: Skills sync is idempotent')
"
```

**Target:** Second sync skips already-linked skills
**Evidence from:** Phase 1 atomic symlink pattern (checks if symlink exists before creating)
**Correlation with full metric:** MEDIUM — tests skip logic but not drift detection
**Blind spots:** Does not test if symlink target changed, or if symlink is broken
**Validated:** No — awaiting drift detection testing in Phase 4

## Level 3: Deferred Validations

**Purpose:** Full validation requiring Codex CLI or integration with other phases.

### D1: Codex CLI Config Loading — DEFER-02-01

**What:** Codex CLI successfully reads generated config.toml without errors
**How:** Run `codex config list` or `codex --help` after sync
**Why deferred:** Requires Codex CLI installed in test environment
**Validates at:** Phase 4 (Plugin Interface & Integration)
**Depends on:** Codex CLI installation, project with generated config.toml
**Target:** Codex CLI exits 0, no parse errors in output
**Risk if unmet:** TOML format may be incorrect despite passing tomllib (different parsers), may require TOML format fixes
**Fallback:** Manual TOML inspection, test with online TOML validator

### D2: Codex Skills Discovery — DEFER-02-02

**What:** Codex CLI discovers and loads skills from .agents/skills/ directory
**How:** Run `codex skills list` after sync, verify converted agents/commands appear
**Why deferred:** Requires Codex CLI and full project setup
**Validates at:** Phase 4 (Plugin Interface & Integration)
**Depends on:** Codex CLI installation, synced skills directory
**Target:** All agent- and cmd- prefixed skills appear in `codex skills list` output
**Risk if unmet:** Skills directory location or naming convention incorrect, may need adapter fixes
**Fallback:** Manually inspect Codex skill resolution order in docs

### D3: Sandbox Mode Enforcement — DEFER-02-03

**What:** Codex CLI respects sandbox_mode setting (blocks restricted operations)
**How:** Set sandbox_mode to read-only, attempt file write, verify blocked
**Why deferred:** Requires Codex CLI and security testing setup
**Validates at:** Phase 5 (Safety & Validation)
**Depends on:** Codex CLI, test environment with permission testing
**Target:** read-only mode blocks writes, workspace-write allows writes in project
**Risk if unmet:** Permission mapping incorrect, may create security hole
**Fallback:** Conservative override (document that users should manually verify)

### D4: MCP Server Startup — DEFER-02-04

**What:** Codex CLI starts MCP servers correctly from generated config
**How:** Run Codex with synced MCP config, check server processes start
**Why deferred:** Requires MCP server binaries, Codex CLI, full integration
**Validates at:** Phase 6 (MCP Server Integration)
**Depends on:** Codex CLI, MCP servers installed, valid env vars
**Target:** MCP servers start without error, Codex connects successfully
**Risk if unmet:** TOML format issue or env var expansion broken, may need fixes
**Fallback:** Manual server testing outside Codex

### D5: Environment Variable Expansion — DEFER-02-05

**What:** Codex CLI expands env var references (${VAR}) at runtime, not parse time
**How:** Set ${TEST_VAR} in config, run Codex without var, observe behavior
**Why deferred:** Requires Codex CLI to verify expansion timing (Open Question 1)
**Validates at:** Phase 4 (Plugin Interface & Integration)
**Depends on:** Codex CLI, MCP server config with env vars
**Target:** Codex parses config successfully, expands vars at server start
**Risk if unmet:** May need to resolve env vars during sync (code change)
**Fallback:** Document limitation, user must define vars before Codex runs

### D6: Full Pipeline Integration — DEFER-02-06

**What:** SourceReader → CodexAdapter → Codex CLI end-to-end
**How:** Run full sync with real Claude Code project, verify in Codex
**Why deferred:** Requires all Phase 1-4 components integrated
**Validates at:** Phase 4 (Plugin Interface & Integration)
**Depends on:** SourceReader (Phase 1), CodexAdapter (Phase 2), state tracking (Phase 1)
**Target:** All 6 config types sync without errors, Codex CLI works as expected
**Risk if unmet:** Integration issues between phases, may require adapter refactoring
**Fallback:** Phased rollout (sync one config type at a time)

## Proxy Metric Confidence Assessment

| Metric | Confidence | Justification |
|--------|-----------|---------------|
| P1: Agent conversion | HIGH | Output format matches spec exactly, validated by parsing |
| P2: Managed section preservation | HIGH | Directly tests merge logic with real files |
| P3: Permission mapping | MEDIUM | Tests logic but not security enforcement |
| P4: MCP config merge | HIGH | Directly tests TOML merge behavior |
| P5: Skills idempotency | MEDIUM | Tests skip logic but not drift detection |

**Overall proxy confidence:** MEDIUM-HIGH
- Format validation is strong (parse-based)
- Merge behavior is testable in isolation
- Security aspects require deferred validation

## Evaluation Scripts

**Location of evaluation code:**
```
.planning/phases/02-adapter-framework-codex-sync/02-EVAL.md (inline verification scripts)
```

**How to run full evaluation:**

```bash
# Level 1: Sanity checks (run all 6)
python3 -c "$(sed -n '/^### S1:/,/^```$/p' .planning/phases/02-adapter-framework-codex-sync/02-EVAL.md | grep -A 100 'python3 -c')"
python3 -c "$(sed -n '/^### S2:/,/^```$/p' .planning/phases/02-adapter-framework-codex-sync/02-EVAL.md | grep -A 100 'python3 -c')"
# ... (repeat for S3-S6)

# Level 2: Proxy metrics (run all 5)
python3 -c "$(sed -n '/^### P1:/,/^```$/p' .planning/phases/02-adapter-framework-codex-sync/02-EVAL.md | grep -A 100 'python3 -c')"
# ... (repeat for P2-P5)

# Or run integration test from 02-03-PLAN.md Task 2
python3 -c "$(cat .planning/phases/02-adapter-framework-codex-sync/02-03-PLAN.md | sed -n '/### Task 2.*verify/,/```$/p' | tail -n +2 | head -n -1)"
```

**Quick validation:**
```bash
# Run Phase 2 integration test (covers all requirements)
python3 .planning/phases/02-adapter-framework-codex-sync/02-03-PLAN.md --extract-verify
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: Registry validation | [PASS/FAIL] | [TypeError with AdapterBase message] | |
| S2: ABC enforcement | [PASS/FAIL] | [TypeError with abstract methods] | |
| S3: TOML escaping | [PASS/FAIL] | [All round-trips pass] | |
| S4: SyncResult merge | [PASS/FAIL] | [All assertions pass] | |
| S5: Codex registration | [PASS/FAIL] | ['codex' in registry] | |
| S6: MCP round-trip | [PASS/FAIL] | [TOML parses correctly] | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: Agent conversion | 100% valid | [%] | [MET/MISSED] | |
| P2: Section preservation | User content intact | [yes/no] | [MET/MISSED] | |
| P3: Permission conservatism | All cases correct | [%] | [MET/MISSED] | |
| P4: Config merge | All sections present | [yes/no] | [MET/MISSED] | |
| P5: Skills idempotency | Skipped on re-sync | [yes/no] | [MET/MISSED] | |

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-02-01 | Codex CLI config loading | PENDING | Phase 4 |
| DEFER-02-02 | Codex skills discovery | PENDING | Phase 4 |
| DEFER-02-03 | Sandbox enforcement | PENDING | Phase 5 |
| DEFER-02-04 | MCP server startup | PENDING | Phase 6 |
| DEFER-02-05 | Env var expansion | PENDING | Phase 4 |
| DEFER-02-06 | Full pipeline integration | PENDING | Phase 4 |

## Evaluation Confidence

**Overall confidence in evaluation design:** HIGH

**Justification:**
- **Sanity checks:** Comprehensive — cover all critical framework patterns (ABC, registry, TOML escaping)
- **Proxy metrics:** Well-evidenced — format validation via parsing, merge behavior via file inspection
- **Deferred coverage:** Complete — all integration and CLI validation properly deferred with clear validates_at references

**What this evaluation CAN tell us:**
- Adapter framework patterns work correctly (ABC, registry, SyncResult)
- TOML generation is syntactically correct and round-trips through parser
- Agent/command conversion produces valid SKILL.md format
- Permission mapping follows conservative rules
- Config merge preserves existing sections
- Skills sync is idempotent

**What this evaluation CANNOT tell us:**
- Whether Codex CLI actually loads the generated configs (DEFER-02-01)
- Whether skills are discovered in correct resolution order (DEFER-02-02)
- Whether permission settings enforce intended security boundaries (DEFER-02-03)
- Whether MCP servers start correctly from generated TOML (DEFER-02-04)
- Whether env var expansion timing matches our assumptions (DEFER-02-05)
- Whether full pipeline works end-to-end with real projects (DEFER-02-06)

## Known Limitations

### Format Validation vs. Semantic Validation

Proxy metrics validate **format** (TOML parses, SKILL.md has frontmatter) but not **semantics** (whether Codex interprets configs as intended). This is an inherent limitation of in-phase evaluation without the target CLI.

**Mitigation:** Extensive format testing + early deferred validation (Phase 4)

### Conservative Mapping Verification

P3 tests permission mapping **logic** but cannot verify the mapping is **correct for intended use**. A user with tools=[Bash, Read, Write, Edit] denied WebSearch gets read-only sandbox, which may be overly restrictive.

**Mitigation:** Document mapping rules clearly, allow user override, defer security review to Phase 5

### Symlink Resolution Order

P5 tests idempotency of skill syncing but doesn't verify Codex's skill discovery order (.agents/skills/ vs ~/.codex/skills/ vs other locations). Duplicate skill names may cause unexpected behavior.

**Mitigation:** Document Codex skill resolution order (per research), defer conflict testing to Phase 4

## Test Data Requirements

**For sanity checks:**
- No external data needed (inline test cases)

**For proxy metrics:**
- Sample agent files with frontmatter, role tags, various field combinations
- Sample permission settings (allow/deny combinations)
- Sample MCP configs (stdio, HTTP, env vars)

**For deferred validation:**
- Real Claude Code project with all config types
- Codex CLI installation
- MCP server binaries
- Test environment with permission restrictions

## Regression Testing

When Phase 2 code changes in future:

**Must re-run:**
- All 6 sanity checks (framework patterns must not break)
- P1 (agent conversion), P4 (config merge) — core translation logic
- Integration test from 02-03-PLAN.md Task 2

**Can skip if change is isolated:**
- P2, P3, P5 if only MCP code changed
- MCP tests if only agent conversion changed

## Risk Assessment for Deferred Items

| Deferred Item | Probability of Failure | Impact | Mitigation |
|---------------|----------------------|--------|------------|
| DEFER-02-01 (Config loading) | LOW | HIGH — blocks all Codex usage | Pre-validate with online TOML validator |
| DEFER-02-02 (Skills discovery) | MEDIUM | MEDIUM — skills not found | Test manually before Phase 4 |
| DEFER-02-03 (Sandbox enforcement) | MEDIUM | HIGH — security hole | Conservative mapping reduces risk |
| DEFER-02-04 (MCP startup) | MEDIUM | MEDIUM — MCP features broken | Test with simple server first |
| DEFER-02-05 (Env var expansion) | LOW | LOW — documented limitation | Users can work around |
| DEFER-02-06 (Full pipeline) | LOW | HIGH — whole system fails | Incremental integration in Phase 4 |

**Highest risk:** DEFER-02-03 (Sandbox enforcement) — if conservative mapping is insufficient, may create security vulnerability. **Mitigation:** Early security review, document mapping clearly, allow user override.

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-02-13*
