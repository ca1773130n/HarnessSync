"""MCP server entry point for HarnessSync.

Launched via `python src/mcp/server.py`. Communicates with MCP clients
over stdio using JSON-RPC 2.0 protocol. Serializes sync operations
via worker thread with request queue.

CRITICAL: stdout is the JSON-RPC protocol channel.
All logging goes to stderr only.
"""

import json
import logging
import os
import queue
import sys
import threading
from pathlib import Path

# Configure ALL logging to stderr BEFORE any other imports
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("harnesssync.mcp")

# Path setup (same pattern as src/commands/sync.py)
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.mcp.transport import StdioTransport
from src.mcp.protocol import ProtocolHandler, make_success, make_error, INVALID_PARAMS
from src.mcp.tools import ToolHandlers, TOOL_HANDLERS
from src.mcp.schemas import VALIDATORS


class MCPServer:
    """MCP server with worker-thread concurrency for sync operations."""

    def __init__(self):
        self.transport = StdioTransport()
        self.protocol = ProtocolHandler(self.transport)
        self.tool_handlers = ToolHandlers()
        self.sync_queue = queue.Queue(maxsize=1)
        self.sync_in_progress = False

        # Start worker thread for serialized sync operations
        self.worker = threading.Thread(target=self._sync_worker, daemon=True)
        self.worker.start()

    def _sync_worker(self):
        """Worker thread: process sync requests from queue one at a time."""
        while True:
            request_id, tool_name, arguments = self.sync_queue.get()
            self.sync_in_progress = True
            try:
                from src.lock import sync_lock

                with sync_lock():
                    handler_method = getattr(self.tool_handlers, TOOL_HANDLERS[tool_name])
                    result = handler_method(arguments)
            except BlockingIOError:
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": "Another sync operation is in progress (file lock held by /sync command or hook)",
                        }
                    ],
                    "isError": True,
                }
            except Exception as e:
                logger.exception("Sync worker error")
                result = {
                    "content": [{"type": "text", "text": f"Internal error: {type(e).__name__}"}],
                    "isError": True,
                }
            finally:
                self.sync_in_progress = False

            # Send response from worker thread (safe: only sync ops use worker)
            response = make_success(request_id, result)
            self.transport.write_response(response)
            self.sync_queue.task_done()

    def _handle_tools_call(self, request_id, params: dict):
        """Dispatch tools/call to appropriate handler.

        Args:
            request_id: JSON-RPC request ID.
            params: Tool call params with 'name' and 'arguments'.

        Returns:
            Response dict if immediate, None if queued for worker thread.
        """
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in TOOL_HANDLERS:
            return make_error(request_id, INVALID_PARAMS, f"Unknown tool: {tool_name}")

        # Validate arguments early (before queueing)
        try:
            VALIDATORS[tool_name](arguments)
        except ValueError as e:
            return make_success(
                request_id,
                {
                    "content": [{"type": "text", "text": str(e)}],
                    "isError": True,
                },
            )

        # get_status executes immediately (no queue, no sync lock)
        if tool_name == "get_status":
            result = self.tool_handlers.handle_get_status(arguments)
            return make_success(request_id, result)

        # sync_all/sync_target: queue for worker thread
        if self.sync_in_progress:
            return make_success(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "status": "busy",
                                    "message": "Sync operation already in progress. Use get_status to check current state.",
                                }
                            ),
                        }
                    ],
                    "isError": False,
                },
            )

        try:
            self.sync_queue.put_nowait((request_id, tool_name, arguments))
        except queue.Full:
            return make_success(
                request_id,
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "status": "busy",
                                    "message": "Sync queue full. Try again shortly.",
                                }
                            ),
                        }
                    ],
                    "isError": False,
                },
            )

        # Response will be sent by worker thread
        return None

    def run(self):
        """Main server loop: read requests, route, respond."""
        logger.info("HarnessSync MCP server started")

        while True:
            try:
                message = self.transport.read_message()
            except json.JSONDecodeError as e:
                logger.error(f"Parse error: {e}")
                self.transport.write_error(None, -32700, "Parse error")
                continue

            if message is None:
                break  # EOF, client disconnected

            method = message.get("method")
            request_id = message.get("id")

            # Special handling for tools/call (dispatched to our handler)
            if method == "tools/call":
                params = message.get("params", {})
                response = self._handle_tools_call(request_id, params)
                if response is not None:
                    self.transport.write_response(response)
                continue

            # All other methods go through protocol handler
            response = self.protocol.handle_message(message)
            if response is not None:
                self.transport.write_response(response)

        logger.info("HarnessSync MCP server stopped")


if __name__ == "__main__":
    server = MCPServer()
    try:
        server.run()
    except KeyboardInterrupt:
        logger.info("Server interrupted")
    except Exception as e:
        logger.exception("Server fatal error")
        sys.exit(1)
