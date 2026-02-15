"""Stdio transport for MCP JSON-RPC 2.0 protocol.

Reads JSON-RPC requests from stdin, writes responses to stdout.
CRITICAL: stdout is the protocol channel — logging uses stderr only.
"""

import json
import logging
import sys

# Configure logging to stderr — stdout is reserved for JSON-RPC
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)


class StdioTransport:
    """Stdio transport handler for MCP JSON-RPC communication."""

    def read_message(self):
        """Read one JSON-RPC message from stdin.

        Returns:
            Parsed dict on success, None on EOF.

        Raises:
            json.JSONDecodeError: If input is not valid JSON.
        """
        line = sys.stdin.readline()
        if not line:
            return None
        return json.loads(line)

    def write_response(self, response: dict):
        """Write a JSON-RPC response to stdout.

        Args:
            response: JSON-RPC response dict to serialize and write.
        """
        sys.stdout.write(json.dumps(response))
        sys.stdout.write("\n")
        sys.stdout.flush()

    def write_error(self, request_id, code: int, message: str):
        """Write a JSON-RPC 2.0 error response.

        Args:
            request_id: The request ID (may be None for parse errors).
            code: JSON-RPC error code.
            message: Human-readable error message.
        """
        error_response = {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": code,
                "message": message,
            },
        }
        self.write_response(error_response)
