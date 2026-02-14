# Evaluation Plan: Phase 6 — MCP Server Integration

**Designed:** 2026-02-15
**Designer:** Claude (grd-eval-planner)
**Method(s) evaluated:** JSON-RPC 2.0 protocol implementation, MCP tool handlers, concurrent request handling
**Reference papers:** MCP Specification (2026), JSON-RPC 2.0 Specification, MCP Build Server Guide (2026)

## Evaluation Overview

Phase 6 implements an MCP (Model Context Protocol) server to expose HarnessSync's sync capabilities as programmatic tools. This is a **software engineering integration phase** — no ML benchmarks apply. Evaluation focuses on protocol correctness, concurrency safety, response latency, and integration with Claude Code.

**Core challenge:** Implementing MCP with Python stdlib only (zero dependencies) while ensuring:
- JSON-RPC 2.0 protocol compliance
- Concurrent request handling without race conditions
- <5 second response time for typical projects
- Graceful handling of in-progress syncs

**What can be verified independently:** Protocol conformance, tool schema validation, concurrent request correctness, response latency (Level 1 + Level 2)

**What requires integration:** Full Claude Code MCP client integration, external agent invocation, production load testing (Level 3)

**Evaluation confidence:** HIGH for protocol/concurrency verification (automated), MEDIUM for integration (requires full environment)

### Metric Sources

| Metric | Source | Why This Metric |
|--------|--------|----------------|
| Protocol conformance | JSON-RPC 2.0 spec, MCP spec | Ensures interoperability with MCP clients |
| Response latency (<5s) | Success criteria #3 from phase requirements | User experience requirement |
| Concurrent request correctness | MCP concurrency patterns, file system integrity | Prevents data corruption from race conditions |
| Tool schema validity | MCP Tools Specification 2026 | Required for tool discovery and validation |
| Queue behavior | Python threading.Queue semantics | Ensures serialized sync operations |

### Verification Level Summary

| Level | Count | Purpose |
|-------|-------|---------|
| Sanity (L1) | 8 | Protocol structure, imports, basic functionality |
| Proxy (L2) | 6 | End-to-end MCP handshake, latency, concurrency, file correctness |
| Deferred (L3) | 3 | Full Claude Code integration, external agents, production load |

## Level 1: Sanity Checks

**Purpose:** Verify basic functionality. These MUST ALL PASS before proceeding.

### S1: Module Imports
- **What:** All MCP modules import without errors
- **Command:** `python -c "from src.mcp.transport import StdioTransport; from src.mcp.protocol import ProtocolHandler; from src.mcp.schemas import TOOLS, VALIDATORS; from src.mcp.tools import ToolHandlers; from src.mcp.server import MCPServer; print('OK')"`
- **Expected:** Output "OK" with exit code 0, no import errors
- **Failure means:** Module structure broken, missing files, or syntax errors

### S2: Logging Configuration
- **What:** No output to stdout except JSON-RPC messages
- **Command:** `python src/mcp/server.py < /dev/null 2>&1 | head -1 | python -c "import sys, json; json.loads(sys.stdin.read())"`
- **Expected:** Parses as valid JSON (or EOF immediately if no initialize sent)
- **Failure means:** Logging or print() statements polluting stdout

### S3: Tool Schema JSON Serialization
- **What:** All tool schemas are valid JSON
- **Command:** `python -c "from src.mcp.schemas import TOOLS; import json; json.dumps(TOOLS); print(f'{len(TOOLS)} tools valid')"`
- **Expected:** "3 tools valid" — no JSON serialization errors
- **Failure means:** Tool schemas contain non-serializable types

### S4: Tool Schema Structure
- **What:** Each tool has required fields (name, description, inputSchema)
- **Command:** `python -c "from src.mcp.schemas import TOOLS; assert all('name' in t and 'description' in t and 'inputSchema' in t for t in TOOLS); print('Schema structure OK')"`
- **Expected:** "Schema structure OK"
- **Failure means:** Incomplete tool definitions

### S5: Input Validation - Valid Inputs
- **What:** Validators accept valid inputs
- **Command:**
```bash
python -c "
from src.mcp.schemas import VALIDATORS
assert VALIDATORS['sync_all']({}) == {'dry_run': False, 'allow_secrets': False}
assert VALIDATORS['sync_all']({'dry_run': True}) == {'dry_run': True, 'allow_secrets': False}
assert VALIDATORS['sync_target']({'target': 'codex'})['target'] == 'codex'
assert VALIDATORS['get_status']({}) == {}
print('Valid inputs OK')
"
```
- **Expected:** "Valid inputs OK"
- **Failure means:** Validators rejecting valid inputs

### S6: Input Validation - Invalid Inputs
- **What:** Validators reject invalid inputs with clear error messages
- **Command:**
```bash
python -c "
from src.mcp.schemas import VALIDATORS
try:
    VALIDATORS['sync_target']({})  # Missing target
    assert False, 'Should have raised ValueError'
except ValueError as e:
    assert 'target' in str(e).lower(), f'Error message unclear: {e}'

try:
    VALIDATORS['sync_target']({'target': 'invalid'})  # Invalid target
    assert False, 'Should have raised ValueError'
except ValueError as e:
    assert 'invalid target' in str(e).lower() or 'must be one of' in str(e).lower(), f'Error unclear: {e}'

print('Invalid input rejection OK')
"
```
- **Expected:** "Invalid input rejection OK"
- **Failure means:** Validators not enforcing constraints

### S7: Protocol Message Routing
- **What:** ProtocolHandler routes initialize/tools-list/unknown methods correctly
- **Command:**
```bash
python -c "
from src.mcp.protocol import ProtocolHandler

p = ProtocolHandler(None)

# Test initialize
r = p.handle_message({'jsonrpc': '2.0', 'method': 'initialize', 'id': 1, 'params': {}})
assert r['result']['capabilities']['tools'] is not None, 'Missing tools capability'

# Test unknown method
r = p.handle_message({'jsonrpc': '2.0', 'method': 'unknown', 'id': 2})
assert 'error' in r and r['error']['code'] == -32601, 'Should be method not found'

# Test missing method
r = p.handle_message({'jsonrpc': '2.0', 'id': 3})
assert 'error' in r and r['error']['code'] == -32600, 'Should be invalid request'

print('Protocol routing OK')
"
```
- **Expected:** "Protocol routing OK"
- **Failure means:** Message routing logic broken

### S8: JSON-RPC Error Code Constants
- **What:** All required JSON-RPC 2.0 error codes defined
- **Command:** `python -c "from src.mcp.protocol import PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL_ERROR; assert PARSE_ERROR == -32700; assert METHOD_NOT_FOUND == -32601; print('Error codes OK')"`
- **Expected:** "Error codes OK"
- **Failure means:** Missing or incorrect error code constants

**Sanity gate:** ALL sanity checks must pass. Any failure blocks progression.

## Level 2: Proxy Metrics

**Purpose:** Automated end-to-end testing of MCP server without full Claude Code environment.
**IMPORTANT:** These proxy metrics approximate real integration but cannot fully validate Claude Code client compatibility.

### P1: Full MCP Handshake Completion
- **What:** Server completes initialize → initialized → tools/list → tools/call sequence
- **How:** Automated test script that pipes JSON-RPC requests to server via subprocess
- **Command:** `python .planning/phases/06-mcp-server-integration/test_mcp_handshake.py`
- **Target:** All 5 steps complete without protocol errors
  1. Initialize request returns capabilities with tools
  2. Initialized notification accepted (no response)
  3. tools/list returns exactly 3 tools (sync_all, sync_target, get_status)
  4. get_status tool call returns result without error
  5. Server exits cleanly on stdin EOF
- **Evidence:** MCP Specification section 3.2 (Lifecycle), Build Server Guide handshake example
- **Correlation with full metric:** HIGH — handshake is protocol requirement, same for all MCP clients
- **Blind spots:** Claude Code-specific client behavior, authentication, non-stdio transports
- **Validated:** No — awaiting deferred validation at phase-07-integration

### P2: Tool Invocation Latency (<5 seconds)
- **What:** sync_target("codex") completes within 5 seconds for typical project
- **How:** Measure elapsed time from tools/call request sent to result response received
- **Command:**
```bash
cd /tmp && mkdir -p test-harness-project/.claude/skills && \
echo "# Test" > test-harness-project/.claude/CLAUDE.md && \
time python .planning/phases/06-mcp-server-integration/test_sync_latency.py test-harness-project
```
- **Target:** <5 seconds for project with 10 files (1 rules, 3 skills, 2 agents, 2 commands, 2 MCP servers)
- **Evidence:** Success criteria #3 from phase requirements, baseline sync latency <500ms for direct SyncOrchestrator call
- **Correlation with full metric:** MEDIUM — test project may not represent real project complexity, but validates basic performance
- **Blind spots:** Large projects (100+ files), network latency (if MCP over HTTP), slow file systems
- **Validated:** No — awaiting deferred validation at phase-07-production-eval

### P3: Concurrent Request Serialization
- **What:** Multiple sync requests are serialized (only one executes at a time), second request gets immediate "busy" response
- **How:** Start 2 concurrent sync_target requests, verify only one acquires sync_lock and second gets immediate response
- **Command:** `python .planning/phases/06-mcp-server-integration/test_concurrency.py`
- **Target:**
  - Request 1 acquires lock and executes sync
  - Request 2 receives immediate response with status="busy" message
  - No race conditions (both requests don't execute simultaneously)
  - Queue depth never exceeds 1
- **Evidence:** 06-RESEARCH.md Pattern 3 (concurrent request handling), queue.Queue maxsize=1 semantics
- **Correlation with full metric:** HIGH — tests actual concurrency mechanism (queue + worker thread)
- **Blind spots:** Higher concurrency levels (5+ simultaneous requests), stress testing over hours
- **Validated:** No — awaiting deferred validation at phase-07-integration

### P4: get_status Immediate Execution During Sync
- **What:** get_status returns immediately even while sync is in progress (not queued)
- **How:** Start long-running sync, send get_status during sync, measure latency
- **Command:** `python .planning/phases/06-mcp-server-integration/test_status_immediate.py`
- **Target:** get_status latency <500ms even during active sync operation
- **Evidence:** 06-02-PLAN.md truth: "get_status executes immediately without queuing (no sync lock needed)"
- **Correlation with full metric:** HIGH — directly tests the intended behavior
- **Blind spots:** Real-world sync operations may have different blocking characteristics
- **Validated:** No — awaiting deferred validation at phase-07-integration

### P5: File System Correctness After Concurrent Syncs
- **What:** Running concurrent sync requests doesn't corrupt target files (no race conditions)
- **How:** Run 5 sync_target("codex") requests in parallel, verify all generated files are valid JSON/TOML and identical
- **Command:**
```bash
python .planning/phases/06-mcp-server-integration/test_file_correctness.py && \
echo "Verifying Codex config.toml..." && \
python -c "import tomllib; tomllib.loads(open('/tmp/test-codex-home/.codex/config.toml').read()); print('Valid TOML')"
```
- **Target:** 100% file validity, no corrupted JSON/TOML, all files identical across runs
- **Evidence:** sync_lock from src/lock.py provides file-level mutual exclusion (Decision #37)
- **Correlation with full metric:** HIGH — directly tests the safety mechanism
- **Blind spots:** Other file system operations (cleanup, symlink creation), cross-process conflicts with /sync command
- **Validated:** No — awaiting deferred validation at phase-07-integration

### P6: Error Handling - Tool Execution vs Protocol Errors
- **What:** Validation errors return isError=true tool result (not JSON-RPC protocol error)
- **How:** Send sync_target with invalid target, verify response format
- **Command:**
```bash
python -c "
import subprocess, json
proc = subprocess.Popen(['python', 'src/mcp/server.py'],
                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
# Initialize first
init = {'jsonrpc': '2.0', 'method': 'initialize', 'id': 1, 'params': {}}
proc.stdin.write((json.dumps(init) + '\n').encode())
proc.stdin.flush()
proc.stdout.readline()

# Send initialized notification
proc.stdin.write((json.dumps({'jsonrpc': '2.0', 'method': 'initialized'}) + '\n').encode())
proc.stdin.flush()

# Send invalid sync_target
req = {'jsonrpc': '2.0', 'method': 'tools/call', 'id': 2, 'params': {'name': 'sync_target', 'arguments': {'target': 'invalid'}}}
proc.stdin.write((json.dumps(req) + '\n').encode())
proc.stdin.flush()
line = proc.stdout.readline()
r = json.loads(line)
assert 'result' in r, 'Should be JSON-RPC success (not error)'
assert r['result']['isError'] is True, 'Should be tool error'
assert 'invalid target' in r['result']['content'][0]['text'].lower(), 'Error message should mention invalid target'
print('Error handling OK')
"
```
- **Expected:** "Error handling OK"
- **Evidence:** 06-RESEARCH.md Pitfall 4 (two error levels), MCP spec section on error handling
- **Correlation with full metric:** HIGH — validates the error reporting mechanism
- **Blind spots:** Other error types (orchestrator exceptions, file I/O errors)
- **Validated:** No — awaiting deferred validation at phase-07-integration

## Level 3: Deferred Validations

**Purpose:** Full evaluation requiring Claude Code integration or production environment.

### D1: Claude Code MCP Client Integration — DEFER-06-01
- **What:** MCP server works with Claude Code via plugin.json mcp.server entry
- **How:** Launch Claude Code, verify it discovers the 3 MCP tools, invoke sync_target from LLM
- **Why deferred:** Requires full Claude Code environment with plugin loading mechanism
- **Validates at:** phase-07-claude-code-integration
- **Depends on:** Plugin.json manifest, Claude Code plugin system, MCP client implementation
- **Target:** Claude Code discovers 3 tools, LLM can successfully invoke sync_target and receive structured results
- **Risk if unmet:** Server may work standalone but fail in Claude Code environment — would require protocol debugging or client-side adapter
- **Fallback:** Create stdio wrapper script that Claude Code can launch if direct integration fails

### D2: External Agent Cross-CLI Invocation — DEFER-06-02
- **What:** External agent (not Claude Code) can invoke MCP tools for cross-CLI orchestration
- **How:** Create test agent that uses MCP client library to invoke sync_all, verify results
- **Why deferred:** Requires MCP client implementation (not part of this phase)
- **Validates at:** phase-07-external-agent-test
- **Depends on:** MCP client library (or manual JSON-RPC client), agent framework
- **Target:** Agent receives structured sync results with per-target counts and errors, can parse and act on them
- **Risk if unmet:** MCP server may only work with Claude Code's specific client implementation — would require broader protocol compatibility testing
- **Fallback:** Provide JSON-RPC client example code for external agents

### D3: Production Load Testing — DEFER-06-03
- **What:** Server handles sustained load (100+ requests over 1 hour) without memory leaks or queue buildup
- **How:** Stress test with concurrent clients, monitor memory usage, queue depth, response latency over time
- **Why deferred:** Requires production-like environment and sustained testing time
- **Validates at:** phase-08-production-readiness (if applicable)
- **Depends on:** Production environment, monitoring infrastructure, load testing tools
- **Target:**
  - Memory usage stable (<50MB growth over 1 hour)
  - Queue depth never exceeds 2 (maxsize=1 plus active request)
  - Response latency p95 <7 seconds (allows for larger projects)
  - No crashes or deadlocks
- **Risk if unmet:** Server may leak memory, deadlock under load, or accumulate unbounded queue — would require concurrency redesign
- **Fallback:** Document operational limits (max concurrent clients, request rate limits), add monitoring/alerting

## Ablation Plan

**Purpose:** Validate concurrency mechanisms and serialization benefits.

### A1: Worker Thread vs Single-Threaded
- **Condition:** Remove worker thread, execute sync operations in main request handling loop
- **Expected impact:** Request processing blocks during sync, multiple sync requests queue up (bad UX)
- **Command:** Modify server.py to remove threading.Thread, call tool handlers directly in handle_tools_call
- **Evidence:** Research Pattern 3 shows async processing prevents blocking

### A2: Queue vs No Queue
- **Condition:** Remove queue, allow concurrent sync execution with only sync_lock
- **Expected impact:** Second sync request blocks waiting for lock instead of returning immediate "busy" response
- **Command:** Modify server.py to remove queue.Queue, directly acquire sync_lock in handle_tools_call
- **Evidence:** 06-02-PLAN.md truth: "new sync requests return immediate 'sync in progress' response (not queued, not blocked)"

### A3: sync_lock vs No Lock
- **Condition:** Remove sync_lock() from worker thread
- **Expected impact:** Concurrent syncs corrupt files, race conditions in state management
- **Command:** Modify tools.py to remove sync_lock() context manager
- **Evidence:** 06-RESEARCH.md Pitfall 2 (race conditions), src/lock.py provides file-level mutual exclusion

**Ablation recommendation:** Only run A3 in isolated environment — deliberately creates data corruption risk.

## Baselines

| Baseline | Description | Expected Score | Source |
|----------|-------------|----------------|--------|
| Direct SyncOrchestrator call | Invoke sync_all() directly without MCP layer | <500ms for 10-file project | BASELINE.md Section 10 |
| MCP protocol overhead | Additional latency from JSON-RPC serialization | +100-200ms vs direct call | Industry standard JSON-RPC overhead |
| Single-threaded sync | Blocking request handling without worker thread | 5+ seconds blocking time | Performance anti-pattern |

## Evaluation Scripts

**Location of evaluation code:**
```
.planning/phases/06-mcp-server-integration/
├── test_mcp_handshake.py        — P1: Full handshake test
├── test_sync_latency.py         — P2: Latency measurement
├── test_concurrency.py          — P3: Concurrent request test
├── test_status_immediate.py     — P4: get_status during sync
├── test_file_correctness.py     — P5: File corruption test
└── test_error_handling.py       — P6: Error format test
```

**Scripts to be created during phase execution.**

**How to run full evaluation:**
```bash
# Step 1: Sanity checks (manual)
python -c "from src.mcp.server import MCPServer; print('Imports OK')"
# ... run S2-S8 commands above

# Step 2: Proxy metrics (automated)
cd /Users/edward.seo/dev/private/project/harness/HarnessSync
python .planning/phases/06-mcp-server-integration/test_mcp_handshake.py
python .planning/phases/06-mcp-server-integration/test_sync_latency.py
python .planning/phases/06-mcp-server-integration/test_concurrency.py
python .planning/phases/06-mcp-server-integration/test_status_immediate.py
python .planning/phases/06-mcp-server-integration/test_file_correctness.py
python .planning/phases/06-mcp-server-integration/test_error_handling.py

# Step 3: Deferred validations (manual, post-integration)
# See phase-07 evaluation plan
```

## Results Template

*To be filled by grd-eval-reporter after phase execution.*

### Sanity Results

| Check | Status | Output | Notes |
|-------|--------|--------|-------|
| S1: Module Imports | [PASS/FAIL] | [output] | |
| S2: Logging Configuration | [PASS/FAIL] | [output] | |
| S3: Tool Schema JSON | [PASS/FAIL] | [output] | |
| S4: Schema Structure | [PASS/FAIL] | [output] | |
| S5: Valid Inputs | [PASS/FAIL] | [output] | |
| S6: Invalid Inputs | [PASS/FAIL] | [output] | |
| S7: Protocol Routing | [PASS/FAIL] | [output] | |
| S8: Error Codes | [PASS/FAIL] | [output] | |

### Proxy Results

| Metric | Target | Actual | Status | Notes |
|--------|--------|--------|--------|-------|
| P1: Handshake | 5 steps complete | [actual] | [MET/MISSED] | |
| P2: Latency | <5s | [actual] | [MET/MISSED] | |
| P3: Concurrency | Serialized + busy response | [actual] | [MET/MISSED] | |
| P4: Status Immediate | <500ms | [actual] | [MET/MISSED] | |
| P5: File Correctness | 100% valid | [actual] | [MET/MISSED] | |
| P6: Error Handling | isError=true format | [actual] | [MET/MISSED] | |

### Ablation Results

| Condition | Expected | Actual | Conclusion |
|-----------|----------|--------|------------|
| A1: No worker thread | Blocking behavior | [actual] | [what we learned] |
| A2: No queue | Blocking on lock | [actual] | [what we learned] |
| A3: No sync_lock | File corruption | [actual] | [what we learned] |

### Deferred Status

| ID | Metric | Status | Validates At |
|----|--------|--------|-------------|
| DEFER-06-01 | Claude Code integration | PENDING | phase-07-claude-code-integration |
| DEFER-06-02 | External agent invocation | PENDING | phase-07-external-agent-test |
| DEFER-06-03 | Production load testing | PENDING | phase-08-production-readiness |

## Evaluation Confidence

**Overall confidence in evaluation design:** HIGH

**Justification:**
- **Sanity checks:** Adequate — covers all critical module imports, schema validation, protocol routing, error codes
- **Proxy metrics:** Well-evidenced — all proxies directly test MCP protocol compliance and concurrency mechanisms per specification
- **Deferred coverage:** Comprehensive — integration points clearly identified with specific validation phases

**What this evaluation CAN tell us:**
- MCP protocol implementation is correct per JSON-RPC 2.0 and MCP specification
- Tool schemas are valid and validators enforce constraints
- Concurrent requests are handled safely without race conditions
- Response latency meets <5s requirement for typical projects
- Error handling follows two-level pattern (protocol vs tool errors)
- File system operations don't corrupt target configs

**What this evaluation CANNOT tell us:**
- Claude Code client compatibility (deferred to phase-07) — client-specific behavior may differ from test client
- Real-world performance at scale (deferred to phase-08) — test projects are smaller than production
- External agent integration (deferred to phase-07) — requires MCP client library not built in this phase
- Long-term stability (deferred to phase-08) — memory leaks and deadlocks may only appear after hours of operation

---

*Evaluation plan by: Claude (grd-eval-planner)*
*Design date: 2026-02-15*
