"""JSON-RPC 2.0 protocol handler for MCP message routing.

Routes MCP methods (initialize, tools/list, tools/call) to handlers
and constructs proper JSON-RPC 2.0 responses and errors.
"""

import logging

logger = logging.getLogger(__name__)

# JSON-RPC 2.0 error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


class ProtocolHandler:
    """JSON-RPC 2.0 message router for MCP protocol."""

    def __init__(self, transport):
        """Initialize protocol handler.

        Args:
            transport: StdioTransport instance for I/O (may be None for testing).
        """
        self.transport = transport

    def handle_message(self, raw: dict):
        """Route a JSON-RPC message to the appropriate handler.

        Args:
            raw: Parsed JSON-RPC message dict.

        Returns:
            Response dict to send, or None for notifications.
        """
        method = raw.get("method")
        request_id = raw.get("id")
        params = raw.get("params", {})

        if method is None:
            return make_error(request_id, INVALID_REQUEST, "Invalid Request: missing method")

        if method == "initialize":
            return self._handle_initialize(request_id, params)
        elif method == "initialized":
            return None  # Notification, no response
        elif method == "tools/list":
            return self._handle_tools_list(request_id, params)
        elif method == "tools/call":
            return self._handle_tools_call(request_id, params)
        elif method == "notifications/cancelled":
            return None  # Notification, no response
        else:
            return make_error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")

    def _handle_initialize(self, request_id, params):
        """Handle MCP initialize request.

        Returns server capabilities and protocol version.
        """
        return make_success(request_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {},
            },
            "serverInfo": {
                "name": "harnesssync",
                "version": "1.0.0",
            },
        })

    def _handle_tools_list(self, request_id, params):
        """Handle MCP tools/list request.

        Returns list of available tool definitions.
        """
        from src.mcp.schemas import TOOLS
        return make_success(request_id, {"tools": TOOLS})

    def _handle_tools_call(self, request_id, params):
        """Handle MCP tools/call request.

        Returns the raw message dict for the caller (server) to dispatch
        to the appropriate tool handler. This is the hook point for
        Plan 06-02's server implementation.
        """
        return {"_tools_call": True, "id": request_id, "params": params}


def make_success(request_id, result: dict) -> dict:
    """Construct a JSON-RPC 2.0 success response.

    Args:
        request_id: The request ID.
        result: The result payload.

    Returns:
        JSON-RPC 2.0 success response dict.
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def make_error(request_id, code: int, message: str) -> dict:
    """Construct a JSON-RPC 2.0 error response.

    Args:
        request_id: The request ID (may be None).
        code: JSON-RPC error code.
        message: Human-readable error message.

    Returns:
        JSON-RPC 2.0 error response dict.
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def make_tool_result(content_text: str, is_error: bool = False) -> dict:
    """Construct an MCP tool result.

    Args:
        content_text: Text content of the result.
        is_error: Whether the result represents an error.

    Returns:
        MCP tool result dict with content array and isError flag.
    """
    return {
        "content": [{"type": "text", "text": content_text}],
        "isError": is_error,
    }
