from __future__ import annotations

"""Pre-sync MCP server reachability checker.

Before syncing MCP server config to targets, verify each server is actually
reachable (socket check for remote URL-based servers). Local stdio-based
servers are validated by checking the command exists on PATH.

Syncing dead MCP configs causes confusing failures in target harnesses.
A pre-sync health check catches this early.
"""

import shutil
import socket
import urllib.parse
from pathlib import Path


class McpReachabilityResult:
    """Result of a reachability check for a single MCP server."""

    def __init__(self, name: str, reachable: bool, reason: str = ""):
        self.name = name
        self.reachable = reachable
        self.reason = reason

    def __repr__(self) -> str:
        status = "ok" if self.reachable else f"unreachable ({self.reason})"
        return f"McpReachabilityResult({self.name!r}, {status})"


class McpReachabilityChecker:
    """Checks MCP server reachability before sync.

    Checks:
    - URL-based (http/https/ws): TCP socket connect to host:port
    - stdio-based (command): shutil.which() to verify command on PATH
    - Unknown configs: warn but allow through
    """

    def __init__(self, timeout: float = 3.0):
        """Initialize checker.

        Args:
            timeout: TCP connection timeout in seconds (default: 3.0)
        """
        self.timeout = timeout

    def check_all(self, mcp_servers: dict[str, dict]) -> list[McpReachabilityResult]:
        """Check reachability of all MCP servers.

        Args:
            mcp_servers: Dict mapping server name to server config dict.
                         Configs have 'command'/'cmd' (stdio) or 'url' (remote).

        Returns:
            List of McpReachabilityResult for each server.
        """
        results: list[McpReachabilityResult] = []
        for name, cfg in mcp_servers.items():
            result = self._check_server(name, cfg)
            results.append(result)
        return results

    def get_warnings(self, results: list[McpReachabilityResult]) -> list[str]:
        """Format unreachable servers as warning strings.

        Args:
            results: List of check results from check_all()

        Returns:
            List of warning strings. Empty if all servers reachable.
        """
        warnings: list[str] = []
        for r in results:
            if not r.reachable:
                warnings.append(f"MCP server '{r.name}' unreachable: {r.reason}")
        return warnings

    def has_failures(self, results: list[McpReachabilityResult]) -> bool:
        """Return True if any server is unreachable."""
        return any(not r.reachable for r in results)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _check_server(self, name: str, cfg: dict) -> McpReachabilityResult:
        """Check a single server.

        Args:
            name: Server name
            cfg: Server configuration dict

        Returns:
            McpReachabilityResult
        """
        url = cfg.get("url") or cfg.get("serverUrl")
        command = cfg.get("command") or cfg.get("cmd")

        if url:
            return self._check_url(name, url)
        elif command:
            return self._check_command(name, command)
        else:
            # Can't determine type — pass through with warning
            return McpReachabilityResult(
                name=name,
                reachable=True,
                reason="unknown server type, skipped",
            )

    def _check_url(self, name: str, url: str) -> McpReachabilityResult:
        """Check a URL-based MCP server via TCP socket connect.

        Args:
            name: Server name
            url: Server URL (http/https/ws/wss)

        Returns:
            McpReachabilityResult
        """
        try:
            parsed = urllib.parse.urlparse(url)
            host = parsed.hostname
            if not host:
                return McpReachabilityResult(name, False, f"invalid URL: {url}")

            # Determine port
            port = parsed.port
            if port is None:
                scheme = parsed.scheme.lower()
                port = 443 if scheme in ("https", "wss") else 80

            sock = socket.create_connection((host, port), timeout=self.timeout)
            sock.close()
            return McpReachabilityResult(name, True)
        except socket.timeout:
            return McpReachabilityResult(name, False, f"connection timed out ({self.timeout}s)")
        except (socket.error, OSError) as e:
            return McpReachabilityResult(name, False, str(e))
        except Exception as e:
            return McpReachabilityResult(name, False, f"check error: {e}")

    def _check_command(self, name: str, command: str) -> McpReachabilityResult:
        """Check a stdio-based MCP server by verifying the command exists on PATH.

        Args:
            name: Server name
            command: Command string (may be absolute path or bare executable name)

        Returns:
            McpReachabilityResult
        """
        # If absolute path, check directly
        cmd_path = Path(command)
        if cmd_path.is_absolute():
            if cmd_path.exists() and cmd_path.is_file():
                return McpReachabilityResult(name, True)
            else:
                return McpReachabilityResult(
                    name, False, f"command not found: {command}"
                )

        # Otherwise check PATH
        found = shutil.which(command)
        if found:
            return McpReachabilityResult(name, True)
        else:
            return McpReachabilityResult(
                name, False, f"command '{command}' not found on PATH"
            )
