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
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


# Known MCP server commands and how to install them.
# Keyed by the command name (first segment of the "command" field).
_MCP_INSTALL_HINTS: dict[str, str] = {
    "npx": "npm install -g npm  (npx comes with npm)",
    "uvx": "pip install uv  or  curl -LsSf https://astral.sh/uv/install.sh | sh",
    # Specific npx-based servers (matched by checking args[0])
    "@modelcontextprotocol/server-filesystem": "npx -y @modelcontextprotocol/server-filesystem",
    "@modelcontextprotocol/server-github": "npx -y @modelcontextprotocol/server-github",
    "@modelcontextprotocol/server-brave-search": "npx -y @modelcontextprotocol/server-brave-search",
    "@modelcontextprotocol/server-postgres": "npx -y @modelcontextprotocol/server-postgres",
    "@modelcontextprotocol/server-memory": "npx -y @modelcontextprotocol/server-memory",
    "@modelcontextprotocol/server-puppeteer": "npx -y @modelcontextprotocol/server-puppeteer",
    "@modelcontextprotocol/server-slack": "npx -y @modelcontextprotocol/server-slack",
    "@modelcontextprotocol/server-google-drive": "npx -y @modelcontextprotocol/server-google-drive",
    # uvx-based servers
    "mcp-server-sqlite": "uvx mcp-server-sqlite  or  pip install mcp-server-sqlite",
    "mcp-server-fetch": "uvx mcp-server-fetch  or  pip install mcp-server-fetch",
    "mcp-server-git": "uvx mcp-server-git  or  pip install mcp-server-git",
    "mcp-server-time": "uvx mcp-server-time  or  pip install mcp-server-time",
    # Common standalone tools
    "docker": "Install Docker Desktop from https://docker.com",
    "node": "Install Node.js from https://nodejs.org",
    "python3": "Install Python 3 from https://python.org",
    "python": "Install Python 3 from https://python.org",
    "deno": "Install Deno: curl -fsSL https://deno.land/install.sh | sh",
    "bun": "Install Bun: curl -fsSL https://bun.sh/install | bash",
}


def _get_install_hint(command: str) -> str:
    """Return an installation hint for a missing MCP server command.

    Args:
        command: The bare command name (e.g. "npx", "uvx", "mcp-server-fetch").

    Returns:
        Install hint string, or empty string if unknown.
    """
    # Exact match first
    if command in _MCP_INSTALL_HINTS:
        return _MCP_INSTALL_HINTS[command]
    # Prefix match for package-style names
    for key, hint in _MCP_INSTALL_HINTS.items():
        if command.startswith(key):
            return hint
    return ""


class McpReachabilityResult:
    """Result of a reachability check for a single MCP server."""

    def __init__(self, name: str, reachable: bool, reason: str = "",
                 response_ms: float | None = None):
        self.name = name
        self.reachable = reachable
        self.reason = reason
        self.response_ms = response_ms  # TCP connect time in ms (None for stdio/unknown)

    def __repr__(self) -> str:
        status = "ok" if self.reachable else f"unreachable ({self.reason})"
        if self.response_ms is not None:
            status += f" ({self.response_ms:.0f}ms)"
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
        if not mcp_servers:
            return []

        results: list[McpReachabilityResult] = []
        with ThreadPoolExecutor(max_workers=min(len(mcp_servers), 8)) as pool:
            futures = {
                pool.submit(self._check_server, name, cfg): name
                for name, cfg in mcp_servers.items()
            }
            for fut in as_completed(futures):
                name = futures[fut]
                try:
                    results.append(fut.result())
                except Exception:
                    results.append(McpReachabilityResult(
                        name=name,
                        reachable=False,
                        reason=str(fut.exception()),
                    ))
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

    def get_install_suggestions(
        self, mcp_servers: dict[str, dict]
    ) -> list[str]:
        """For missing stdio servers, suggest install commands.

        Checks which servers are missing and returns actionable install hints
        for each. Useful for syncing MCP configs to new machines where the
        underlying binaries aren't installed yet.

        Args:
            mcp_servers: Dict of server configs (same as check_all input).

        Returns:
            List of install suggestion strings (empty if all present).
        """
        suggestions: list[str] = []
        for name, cfg in mcp_servers.items():
            command = cfg.get("command") or cfg.get("cmd")
            if not command:
                continue
            if shutil.which(command):
                continue  # Already installed
            # Check if it's an absolute path that exists
            cmd_path = Path(command)
            if cmd_path.is_absolute() and cmd_path.exists():
                continue

            hint = _get_install_hint(command)
            # Also check args for npx package names
            args = cfg.get("args", [])
            if command in ("npx",) and args:
                pkg = args[0] if not args[0].startswith("-") else (args[1] if len(args) > 1 else "")
                pkg_hint = _get_install_hint(pkg)
                if pkg_hint:
                    hint = pkg_hint
            elif command in ("uvx",) and args:
                pkg = args[0]
                pkg_hint = _get_install_hint(pkg)
                if pkg_hint:
                    hint = pkg_hint

            if hint:
                suggestions.append(f"  MCP server '{name}': {hint}")
            else:
                suggestions.append(
                    f"  MCP server '{name}': install '{command}' (no automated hint available)"
                )

        return suggestions

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

        Measures connection latency (TCP connect time in ms) for the
        health dashboard response-time column.

        Args:
            name: Server name
            url: Server URL (http/https/ws/wss)

        Returns:
            McpReachabilityResult with response_ms populated on success
        """
        import time as _time
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

            t0 = _time.monotonic()
            sock = socket.create_connection((host, port), timeout=self.timeout)
            elapsed_ms = (_time.monotonic() - t0) * 1000
            sock.close()
            return McpReachabilityResult(name, True, response_ms=elapsed_ms)
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
            install_hint = _get_install_hint(command)
            reason = f"command '{command}' not found on PATH"
            if install_hint:
                reason += f". To install: {install_hint}"
            return McpReachabilityResult(name, False, reason)


def filter_unreachable_servers(
    mcp_servers: dict[str, dict],
    timeout: float = 3.0,
) -> tuple[dict[str, dict], list[McpReachabilityResult]]:
    """Filter out unreachable MCP servers before syncing to targets.

    Returns only the servers that are reachable, along with a list of
    results for the unreachable ones so callers can emit warnings.

    This implements the MCP Watchdog behaviour (item 5): syncing a dead
    MCP server config to a target harness causes confusing startup errors
    on the target machine. Filtering here prevents those errors at the
    source before the config is written anywhere.

    Args:
        mcp_servers: Dict mapping server name -> server config dict.
                     Same format accepted by McpReachabilityChecker.check_all().
        timeout: TCP connection timeout in seconds (default: 3.0).

    Returns:
        Tuple of:
        - reachable_servers: Dict of only the servers that passed the check.
        - skipped: List of McpReachabilityResult for unreachable servers.

    Example::

        reachable, skipped = filter_unreachable_servers(all_servers)
        for r in skipped:
            print(f"Skipping MCP server '{r.name}': {r.reason}")
        # sync only `reachable` to targets
    """
    checker = McpReachabilityChecker(timeout=timeout)
    results = checker.check_all(mcp_servers)

    reachable: dict[str, dict] = {}
    skipped: list[McpReachabilityResult] = []

    for result in results:
        if result.reachable:
            reachable[result.name] = mcp_servers[result.name]
        else:
            skipped.append(result)

    return reachable, skipped
