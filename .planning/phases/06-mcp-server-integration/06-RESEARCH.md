# Phase 6: MCP Server Integration - Research

**Researched:** 2026-02-15
**Domain:** Model Context Protocol (MCP) server implementation
**Confidence:** MEDIUM

## Summary

Phase 6 requires exposing HarnessSync's sync capabilities as MCP tools for programmatic access by other agents and cross-CLI orchestration. The Model Context Protocol (MCP) is an open standard for AI-tool integrations that allows servers to expose tools, resources, and prompts to LLM applications through a JSON-RPC 2.0-based protocol.

The primary challenge for this phase is implementing an MCP server with **Python 3 stdlib only** (zero dependency footprint) while handling concurrent requests, JSON schema validation, and proper transport layer implementation. The official MCP Python SDK (mcp package) requires external dependencies, which violates the project constraint. Therefore, a custom stdlib-only implementation is required.

**Primary recommendation:** Implement a minimal JSON-RPC 2.0 stdio server using Python stdlib (json, sys, threading, queue modules) that exposes three MCP tools (sync_all, sync_target, get_status) and handles concurrent requests via a request queue pattern.

## User Constraints

No CONTEXT.md exists for this phase — full research freedom within project constraints.

**Project constraints (from additional_context):**
- **Python 3 stdlib only** — zero dependency footprint (no external packages allowed)
- Plugin for Claude Code
- Existing modules available: SyncOrchestrator, SourceReader, AdapterRegistry, StateManager, BackupManager, ConflictDetector, SecretDetector, CompatibilityReporter, SymlinkCleaner, DiffFormatter, sync_lock, should_debounce
- plugin.json manifest already declares MCP server entries

## Paper-Backed Recommendations

### Recommendation 1: JSON-RPC 2.0 Protocol for MCP Transport

**Recommendation:** Implement MCP using JSON-RPC 2.0 protocol over stdio transport (standard input/output streams).

**Evidence:**
- [MCP Specification (2026)](https://modelcontextprotocol.io/specification/draft/server/tools) — MCP uses JSON-RPC 2.0 as its underlying protocol for all client-server communication.
- [JSON-RPC 2.0 Specification](https://www.jsonrpc.org/specification) — Defines request/response format: `{"jsonrpc": "2.0", "method": "...", "params": {...}, "id": 1}`.
- [MCP Build Server Guide (2026)](https://modelcontextprotocol.io/docs/develop/build-server) — Python example uses `transport="stdio"` which communicates through stdin/stdout using JSON-RPC messages.

**Confidence:** HIGH — MCP specification explicitly requires JSON-RPC 2.0.

**Implementation requirements:**
- Read JSON-RPC requests from stdin (line-delimited JSON)
- Write JSON-RPC responses to stdout
- Never write to stdout except JSON-RPC messages (logging must use stderr)
- Support both request/response and notification message types

**Caveats:** stdio transport requires careful stream handling — any output to stdout corrupts the protocol.

### Recommendation 2: Request Queue Pattern for Concurrency

**Recommendation:** Use a dedicated worker thread with a request queue to serialize sync operations while allowing concurrent status queries.

**Evidence:**
- [MCP Request Queuing (2026)](https://www.byteplus.com/en/topic/541425) — MCP servers can handle concurrent requests through intelligent queuing where requests are prioritized based on factors like user tier or request type.
- [MCP Concurrent Requests Guide (2026)](https://mcpcat.io/guides/configuring-mcp-servers-multiple-simultaneous-connections/) — Event-driven asynchronous processing where request manager publishes a request event and returns immediately while the agent service processes it asynchronously.
- [Python threading.Queue documentation](https://docs.python.org/3/library/queue.html) — Thread-safe FIFO queue for producer-consumer patterns (stdlib module).

**Confidence:** HIGH — Queue pattern is standard for request serialization in Python stdlib.

**Expected behavior:**
- sync_all and sync_target operations queued (only one sync executes at a time)
- get_status queries execute immediately without queuing
- In-progress sync returns immediate response with "sync in progress" status

**Implementation pattern:**
```python
import queue
import threading

request_queue = queue.Queue()
sync_lock = threading.Lock()

def worker_thread():
    while True:
        request = request_queue.get()
        with sync_lock:
            # Execute sync operation
            result = orchestrator.sync_all()
        send_response(request.id, result)
        request_queue.task_done()
```

**Caveats:** Must handle graceful shutdown of worker thread when server exits.

### Recommendation 3: JSON Schema Validation Using stdlib json module

**Recommendation:** Implement JSON Schema validation manually using Python's stdlib json module and dict structure checks.

**Evidence:**
- [MCP Tools Specification (2026)](https://modelcontextprotocol.io/specification/draft/server/tools) — Each tool must define an inputSchema (JSON Schema) that describes expected parameters. Servers MUST validate tool inputs.
- Python stdlib does not include JSON Schema validation library (jsonschema package is external).
- Manual validation pattern is standard practice when external dependencies are prohibited.

**Confidence:** MEDIUM — No stdlib JSON Schema validator exists; manual validation is necessary but increases code complexity.

**Implementation approach:**
```python
def validate_sync_target_params(params):
    """Validate sync_target tool parameters."""
    if not isinstance(params, dict):
        raise ValueError("Parameters must be an object")

    if "target" not in params:
        raise ValueError("Missing required parameter: target")

    target = params["target"]
    if not isinstance(target, str):
        raise ValueError("Parameter 'target' must be a string")

    if target not in ["codex", "gemini", "opencode"]:
        raise ValueError(f"Invalid target: {target}. Must be one of: codex, gemini, opencode")

    return target
```

**Caveats:** Manual validation is more error-prone than library-based validation; comprehensive test coverage required.

## Standard Stack

### Core (stdlib only)

| Module | Version | Purpose | Why Standard |
|--------|---------|---------|--------------|
| json | Python 3.x stdlib | JSON parsing/serialization | Required for JSON-RPC protocol |
| sys | Python 3.x stdlib | stdin/stdout/stderr access | Required for stdio transport |
| threading | Python 3.x stdlib | Worker thread for request queue | Standard concurrency primitive |
| queue | Python 3.x stdlib | Thread-safe request queue | Standard producer-consumer pattern |
| logging | Python 3.x stdlib | Error logging to stderr | Standard logging (cannot use stdout) |

### Supporting

| Module | Version | Purpose | When to Use |
|--------|---------|---------|-------------|
| pathlib | Python 3.x stdlib | Path manipulation | Existing project uses Path objects |
| typing | Python 3.x stdlib | Type hints for tool schemas | Better IDE support and documentation |

### Alternatives Considered

| Instead of | Could Use | Tradeoff | Reason for Rejection |
|------------|-----------|----------|---------------------|
| stdlib json | Official MCP Python SDK (mcp package) | SDK handles all protocol complexity automatically | Violates zero-dependency constraint |
| Manual validation | jsonschema package | Library provides full JSON Schema validation | External dependency not allowed |
| threading.Queue | asyncio | Native async/await support | Adds complexity; threading is simpler for this use case |

**Installation:**
```bash
# No installation required - all stdlib modules
python3 -m json.tool  # verify json module available
```

## Architecture Patterns

### Recommended Project Structure

```
src/
├── mcp/
│   ├── __init__.py
│   ├── server.py           # Main MCP server entry point
│   ├── transport.py        # Stdio transport handler
│   ├── protocol.py         # JSON-RPC 2.0 message handling
│   ├── tools.py            # Tool registration and execution
│   └── schemas.py          # Tool input/output schemas
└── orchestrator.py         # Existing sync orchestrator
```

### Pattern 1: Stdio Transport Handler

**What:** Read JSON-RPC requests from stdin, write responses to stdout, log to stderr.

**When to use:** Always for MCP stdio servers.

**Implementation:**
```python
# Source: MCP specification + Python stdlib patterns
import sys
import json
import logging

# CRITICAL: Configure logging to stderr only
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

class StdioTransport:
    """Stdio transport for MCP JSON-RPC protocol."""

    def read_request(self):
        """Read a JSON-RPC request from stdin."""
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def write_response(self, response):
        """Write a JSON-RPC response to stdout."""
        json.dump(response, sys.stdout)
        sys.stdout.write('\n')
        sys.stdout.flush()

    def write_error(self, request_id, code, message):
        """Write a JSON-RPC error response."""
        error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message
            }
        }
        self.write_response(error_response)
```

### Pattern 2: Tool Registry with Schema Validation

**What:** Register MCP tools with input/output schemas and execution handlers.

**When to use:** For all MCP tool definitions.

**Implementation:**
```python
# Source: MCP tools specification + registry pattern
class ToolRegistry:
    """Registry of MCP tools with schema validation."""

    def __init__(self):
        self.tools = {}

    def register(self, name, description, input_schema, output_schema, handler):
        """Register a tool with its schema and handler."""
        self.tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
            "outputSchema": output_schema,
            "handler": handler
        }

    def list_tools(self):
        """Return list of tool definitions (for tools/list)."""
        return [
            {
                "name": tool["name"],
                "description": tool["description"],
                "inputSchema": tool["inputSchema"]
            }
            for tool in self.tools.values()
        ]

    def call_tool(self, name, arguments):
        """Call a tool with validated arguments."""
        if name not in self.tools:
            raise ValueError(f"Unknown tool: {name}")

        tool = self.tools[name]
        # Manual schema validation here
        validated_args = self._validate_args(arguments, tool["inputSchema"])

        # Execute handler
        result = tool["handler"](validated_args)

        return result
```

### Pattern 3: Concurrent Request Handling with Queue

**What:** Serialize sync operations via queue while allowing immediate status queries.

**When to use:** When some operations must be serialized but others can run concurrently.

**Implementation:**
```python
# Source: Python threading/queue documentation + MCP concurrency patterns
import queue
import threading

class MCPServer:
    """MCP server with concurrent request handling."""

    def __init__(self, orchestrator):
        self.orchestrator = orchestrator
        self.sync_queue = queue.Queue()
        self.sync_lock = threading.Lock()
        self.sync_in_progress = False

        # Start worker thread
        self.worker = threading.Thread(target=self._sync_worker, daemon=True)
        self.worker.start()

    def _sync_worker(self):
        """Worker thread that processes sync requests from queue."""
        while True:
            request_id, tool_name, arguments = self.sync_queue.get()
            try:
                self.sync_in_progress = True

                if tool_name == "sync_all":
                    result = self.orchestrator.sync_all()
                elif tool_name == "sync_target":
                    target = arguments["target"]
                    result = self.orchestrator.sync_target(target)

                self._send_tool_result(request_id, result)
            finally:
                self.sync_in_progress = False
                self.sync_queue.task_done()

    def handle_tool_call(self, request_id, tool_name, arguments):
        """Handle a tools/call request."""
        if tool_name in ["sync_all", "sync_target"]:
            # Check if sync already in progress
            if self.sync_in_progress:
                return self._send_tool_result(request_id, {
                    "content": [{"type": "text", "text": "Sync already in progress"}],
                    "isError": False
                })

            # Queue sync request
            self.sync_queue.put((request_id, tool_name, arguments))

        elif tool_name == "get_status":
            # Status queries execute immediately (no queue)
            result = self.orchestrator.get_status()
            self._send_tool_result(request_id, result)
```

### Anti-Patterns to Avoid

- **Using print() for responses:** Never use print() — it writes to stdout and corrupts JSON-RPC protocol. Use sys.stdout.write() with explicit flush.
- **Blocking main thread on sync operations:** Sync operations can take seconds; must use worker thread to avoid blocking request processing.
- **No input validation:** MCP spec requires servers to validate all tool inputs — must implement manual validation since no stdlib schema validator exists.
- **Writing logs to stdout:** Logs must always go to stderr (use logging.basicConfig(stream=sys.stderr)) to avoid corrupting stdio transport.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON-RPC protocol parsing | Custom protocol parser | stdlib json + dict pattern | Edge cases (batch requests, notifications) are complex |
| Thread-safe queueing | Custom lock/condition variables | threading.Queue | Built-in thread safety, task completion tracking |
| JSON schema validation | Regex-based validation | Manual type checking with clear error messages | No stdlib JSON Schema validator; keep validation simple and readable |

**Key insight:** MCP protocol has many edge cases (batch requests, notifications, capability negotiation). Start with minimal implementation (single requests, tools only) rather than trying to handle all protocol features.

## Common Pitfalls

### Pitfall 1: Writing to stdout for debugging

**What goes wrong:** Adding print() statements or logging to stdout corrupts JSON-RPC messages, causing "invalid JSON" errors in MCP client.

**Why it happens:** Easy to forget that stdout is a protocol channel, not a debug channel.

**How to avoid:**
```python
# Configure logging at module level
import logging
import sys

logging.basicConfig(
    stream=sys.stderr,  # CRITICAL: stderr only
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# Use logger instead of print
logger = logging.getLogger(__name__)
logger.info("Processing request")  # Safe — goes to stderr
```

**Warning signs:** MCP client reports "Connection closed" or "Invalid JSON" immediately after server starts.

### Pitfall 2: Race conditions in concurrent sync operations

**What goes wrong:** Multiple sync requests arrive simultaneously, causing file conflicts or corrupted state.

**Why it happens:** Sync operations modify files; concurrent writes cause corruption.

**How to avoid:** Use existing sync_lock from project (src/lock.py) plus request queue:
```python
from src.lock import sync_lock

def handle_sync_request(target):
    with sync_lock():  # Existing lock from src/lock.py
        result = orchestrator.sync_all()
    return result
```

**Warning signs:** Intermittent "file already exists" errors, corrupted JSON files, broken symlinks.

### Pitfall 3: Not flushing stdout after writing response

**What goes wrong:** Responses don't appear in MCP client until buffer fills or server exits.

**Why it happens:** stdout is line-buffered by default; JSON-RPC messages may not include newlines.

**How to avoid:**
```python
import sys
import json

def write_response(response):
    json.dump(response, sys.stdout)
    sys.stdout.write('\n')
    sys.stdout.flush()  # CRITICAL: force write
```

**Warning signs:** MCP client hangs waiting for response, timeouts after 5+ seconds.

### Pitfall 4: Returning wrong error format for tool execution errors

**What goes wrong:** Confusing protocol errors (JSON-RPC level) with tool execution errors (MCP level).

**Why it happens:** MCP has two error reporting mechanisms (see MCP spec section on Error Handling).

**How to avoid:**
- **Protocol errors** (unknown tool, malformed request): Return JSON-RPC error object with `error` field
- **Tool execution errors** (invalid input, sync failure): Return successful JSON-RPC response with `isError: true` in result

```python
# Protocol error (unknown tool)
{
    "jsonrpc": "2.0",
    "id": 1,
    "error": {
        "code": -32601,
        "message": "Method not found: invalid_tool"
    }
}

# Tool execution error (sync failed)
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [{"type": "text", "text": "Sync failed: permission denied for .codex/"}],
        "isError": true
    }
}
```

**Warning signs:** MCP client shows "Server error" instead of actionable error message, LLM cannot self-correct.

## Experiment Design

### Recommended Experimental Setup

**Independent variables:** Transport type (stdio only in this phase), request concurrency level (1, 2, 5 concurrent requests)

**Dependent variables:**
- Response latency (time from request received to response sent)
- Sync correctness (files created match expected output)
- Concurrent request handling (no race conditions, queue depth)

**Controlled variables:**
- Project size (10 files: 1 rules, 3 skills, 2 agents, 2 commands, 2 MCP servers)
- Python version (3.8+)
- OS (test on macOS initially, defer Windows/Linux to integration phase)

**Baseline comparison:**
- Method: Direct SyncOrchestrator.sync_all() call (no MCP layer)
- Expected performance: <500ms for test project
- Our target: <5 seconds via MCP (success criteria requirement)

**Ablation plan:**
1. MCP server without queue (single-threaded) vs. with worker queue — tests queue benefit
2. With/without input validation — tests validation overhead
3. With/without sync_lock — tests lock necessity

**Statistical rigor:**
- Number of runs: 5 per configuration
- Confidence intervals: 95% (±2 standard deviations)
- Significance testing: Student's t-test for latency comparison

### Recommended Metrics

| Metric | Why | How to Compute | Baseline |
|--------|-----|----------------|----------|
| Tool invocation latency | Success criteria requires <5s response | Time from tools/call request to result response | <500ms (direct call) |
| Queue depth | Detect queue buildup under load | threading.Queue.qsize() before/after test | 0 (no buildup expected) |
| Concurrent request correctness | Verify no race conditions | Compare file contents after concurrent syncs | 100% match |
| Protocol conformance | Ensure valid JSON-RPC 2.0 | JSON schema validation of all responses | 100% valid |

## Verification Strategy

### Recommended Verification Tiers for This Phase

| Item | Recommended Tier | Rationale |
|------|-----------------|-----------|
| Tool schemas valid JSON | Level 1 (Sanity) | Can validate with json.loads() immediately |
| Server responds to tools/list | Level 1 (Sanity) | Basic protocol check |
| sync_target returns within 5s | Level 2 (Proxy) | Success criteria requirement |
| Concurrent requests don't corrupt state | Level 2 (Proxy) | Can test with 5 concurrent requests |
| MCP client integration (Claude Code) | Level 3 (Deferred) | Needs full Claude Code environment |

**Level 1 checks to always include:**
- Server starts without errors (python src/mcp/server.py)
- Responds to initialize request with capabilities
- tools/list returns array of 3 tools (sync_all, sync_target, get_status)
- Each tool has valid inputSchema (json.loads succeeds)

**Level 2 proxy metrics:**
- Invoke sync_target("codex") via test client, measure latency <5s
- Start 5 concurrent sync requests, verify only one executes at a time (queue serialization)
- Check files after concurrent test — no corruption, all expected files present
- get_status returns immediately even during in-progress sync

**Level 3 deferred items:**
- Integration with Claude Code via plugin.json mcp.server entry
- External agent invocation test
- OAuth authentication (if future requirement)

## Production Considerations

### Known Failure Modes

- **Sync lock timeout:** If sync operation takes >30s, MCP client may timeout
  - Prevention: Implement timeout in worker thread, return early with partial results
  - Detection: Monitor sync operation duration, log warning if >20s

- **Stdout buffer overflow:** Large sync results (>64KB) may exceed stdout buffer
  - Prevention: Chunk large responses, use TextContent with pagination
  - Detection: Monitor response size, log warning if >50KB

- **Worker thread deadlock:** If queue fills without processing, memory exhaustion
  - Prevention: Set queue maxsize, reject requests when full
  - Detection: Monitor queue.qsize(), alert if >10

### Scaling Concerns

- **At current scale (single user, <100 files):**
  - Single worker thread sufficient
  - No queue size limit needed
  - In-memory state OK

- **At production scale (teams, 1000+ files):**
  - May need multiple worker threads (one per target)
  - Queue size limit required (reject excess requests)
  - Consider persistent state (SQLite) for large projects

### Common Implementation Traps

- **Trap:** Forgetting to handle tool invocation while sync in progress
  - Correct approach: Check sync_in_progress flag, return immediate response with "sync in progress" message

- **Trap:** Not implementing graceful shutdown (worker thread keeps running)
  - Correct approach: Use daemon=True for worker thread OR implement shutdown signal handler

- **Trap:** Returning raw exception messages to MCP client (security risk)
  - Correct approach: Catch all exceptions, return sanitized error messages:
  ```python
  try:
      result = orchestrator.sync_all()
  except Exception as e:
      logger.exception("Sync failed")
      return {
          "content": [{"type": "text", "text": f"Sync failed: {type(e).__name__}"}],
          "isError": true
      }
  ```

## Code Examples

Verified patterns from official sources and stdlib documentation:

### MCP Server Main Loop (Stdio Transport)

```python
# Source: MCP specification + Python stdlib stdin/stdout patterns
import sys
import json
import logging

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

class MCPServer:
    def __init__(self):
        self.capabilities = {
            "tools": {"listChanged": False}
        }
        self.tool_registry = ToolRegistry()
        self._register_tools()

    def run(self):
        """Main server loop: read requests from stdin, write responses to stdout."""
        logger.info("MCP server started")

        for line in sys.stdin:
            try:
                request = json.loads(line)
                response = self.handle_request(request)

                if response:  # Some requests don't need response (notifications)
                    json.dump(response, sys.stdout)
                    sys.stdout.write('\n')
                    sys.stdout.flush()

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON: {e}")
                self.write_error(None, -32700, "Parse error")
            except Exception as e:
                logger.exception("Request handling failed")
                self.write_error(None, -32603, "Internal error")

    def handle_request(self, request):
        """Route request to appropriate handler."""
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        if method == "initialize":
            return self.handle_initialize(request_id, params)
        elif method == "tools/list":
            return self.handle_tools_list(request_id, params)
        elif method == "tools/call":
            return self.handle_tools_call(request_id, params)
        else:
            return self.make_error(request_id, -32601, f"Method not found: {method}")

if __name__ == "__main__":
    server = MCPServer()
    server.run()
```

### Tool Definition with Manual Schema Validation

```python
# Source: MCP tools specification + manual validation pattern
class SyncTargetTool:
    """sync_target tool: sync to a specific target (codex/gemini/opencode)."""

    @staticmethod
    def get_definition():
        """Return tool definition for tools/list."""
        return {
            "name": "sync_target",
            "description": "Sync Claude Code configuration to a specific target CLI",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "Target CLI to sync to",
                        "enum": ["codex", "gemini", "opencode"]
                    }
                },
                "required": ["target"]
            }
        }

    @staticmethod
    def validate_and_execute(arguments, orchestrator):
        """Validate arguments and execute sync."""
        # Manual schema validation
        if not isinstance(arguments, dict):
            raise ValueError("Arguments must be an object")

        if "target" not in arguments:
            raise ValueError("Missing required parameter: target")

        target = arguments["target"]
        if not isinstance(target, str):
            raise ValueError("Parameter 'target' must be a string")

        if target not in ["codex", "gemini", "opencode"]:
            raise ValueError(
                f"Invalid target: {target}. Must be one of: codex, gemini, opencode"
            )

        # Execute sync
        result = orchestrator.sync_target(target)

        # Format MCP result
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, indent=2)
                }
            ],
            "isError": False
        }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact | Source |
|--------------|------------------|--------------|--------|--------|
| SSE transport | HTTP + SSE (deprecated) | 2025-2026 | SSE now deprecated in favor of HTTP with streamable responses | [MCP Transport Docs](https://modelcontextprotocol.info/docs/concepts/transports/) |
| Synchronous tools | Tasks primitive (experimental) | 2025-11 | Enables call-now, fetch-later pattern for long-running operations | [MCP Async Tasks](https://workos.com/blog/mcp-async-tasks-ai-agent-workflows) |
| Pre-loaded tools | Tool Search (lazy loading) | 2025-late | Defers tools until needed, reduces context usage | [MCP Tool Search](https://code.claude.com/docs/en/mcp#scale-with-mcp-tool-search) |

**Deprecated/outdated:**
- SSE transport: Replaced by HTTP (streamable) for better concurrency and multiplexing
- Dynamic client registration: Some OAuth servers now require pre-configured credentials

## Open Questions

1. **Should we implement MCP Tasks primitive for long-running syncs?**
   - What we know: Tasks primitive allows async work (sync continues in background, client polls for result)
   - What's unclear: Whether <5s sync latency justifies async complexity
   - Recommendation: Defer to Phase 7 — start with synchronous tools, add Tasks if latency becomes issue

2. **How to handle MCP server in plugin.json manifest?**
   - What we know: plugin.json has `"mcp": {"server": "src/mcp/server.py", "tools": [...]}` field
   - What's unclear: Whether server.py needs special entry point format for Claude Code
   - Recommendation: Test with minimal server.py that runs via `python src/mcp/server.py`, verify Claude Code can launch it

3. **Should get_status return drift detection data?**
   - What we know: Success criteria says "get_status" tool needed, orchestrator has get_status() method
   - What's unclear: How much detail to include (per-file hashes vs. summary only)
   - Recommendation: Return full detail — MCP client can filter, but LLM benefits from specifics

## Sources

### Primary (HIGH confidence)

- [MCP Tools Specification (2026)](https://modelcontextprotocol.io/specification/draft/server/tools) — Tool definition schema, JSON-RPC protocol, error handling
- [MCP Build Server Guide (2026)](https://modelcontextprotocol.io/docs/develop/build-server) — Python server examples, stdio transport, tool implementation patterns
- [Claude Code MCP Integration (2026)](https://code.claude.com/docs/en/mcp) — Plugin MCP server configuration, plugin.json format, environment variables
- [Python threading.Queue documentation](https://docs.python.org/3/library/queue.html) — Thread-safe queue API, task_done() pattern
- [Python json module documentation](https://docs.python.org/3/library/json.html) — JSON encoding/decoding, edge cases

### Secondary (MEDIUM confidence)

- [MCP Concurrent Requests Guide (2026)](https://mcpcat.io/guides/configuring-mcp-servers-multiple-simultaneous-connections/) — Event-driven async processing pattern for concurrency
- [MCP Request Queuing (2026)](https://www.byteplus.com/en/topic/541425) — Intelligent queuing and request prioritization patterns
- [MCP Async Tasks (2025-11)](https://workos.com/blog/mcp-async-tasks-ai-agent-workflows) — Tasks primitive for long-running operations (experimental)

### Tertiary (LOW confidence)

- [jsonrpyc GitHub](https://github.com/riga/jsonrpyc) — Minimal JSON-RPC library (external dependency, cannot use)
- [FastMCP framework](https://github.com/modelcontextprotocol/python-sdk) — Official SDK (external dependency, cannot use)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All stdlib modules well-documented
- Architecture: HIGH - JSON-RPC pattern is standard, stdio transport proven
- MCP protocol requirements: HIGH - Official specification available
- Concurrent request handling: MEDIUM - Queue pattern is standard but MCP-specific testing needed
- Plugin integration: MEDIUM - plugin.json format documented but not heavily tested in wild
- Manual JSON Schema validation: LOW - No stdlib validator, custom code needed

**Research date:** 2026-02-15
**Valid until:** 2026-03-15 (30 days for stable API)

**Key constraints:**
- Python 3 stdlib only (zero dependencies)
- Must integrate with existing SyncOrchestrator
- Must handle concurrent requests gracefully
- Success criteria: <5s response time for typical project
