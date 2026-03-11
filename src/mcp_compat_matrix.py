from __future__ import annotations

"""MCP Server Compatibility Matrix — cross-harness MCP transfer analysis.

For each MCP server in Claude Code config, shows:
- Which target harnesses support it natively
- Which require URL translation (e.g. stdio -> HTTP bridge)
- Which can't transfer at all (missing protocol support)
- Version compatibility notes per harness

Addresses the black-box problem of MCP sync: users don't know if their
tools will work in Gemini/Codex until they try and fail.

Usage:
    matrix = McpCompatMatrix(mcp_servers)
    report = matrix.analyze()
    print(matrix.format_table(report))
"""

from dataclasses import dataclass, field
from enum import Enum


class McpTransferability(str, Enum):
    """How transferable an MCP server is to a target harness."""

    NATIVE = "native"          # Same protocol, same format — copies as-is
    URL_TRANSLATE = "translate"  # Requires URL/endpoint translation
    BRIDGED = "bridged"        # Works via bridge/proxy setup
    UNSUPPORTED = "unsupported"  # Target harness doesn't support MCP at all
    MANUAL = "manual"          # Possible but requires manual config step


# Protocol support per harness
# Format: {harness: {protocol: transferability}}
_PROTOCOL_SUPPORT: dict[str, dict[str, McpTransferability]] = {
    "codex": {
        "stdio":  McpTransferability.NATIVE,
        "http":   McpTransferability.NATIVE,
        "https":  McpTransferability.NATIVE,
        "ws":     McpTransferability.BRIDGED,
        "sse":    McpTransferability.BRIDGED,
    },
    "gemini": {
        "stdio":  McpTransferability.NATIVE,
        "http":   McpTransferability.NATIVE,
        "https":  McpTransferability.NATIVE,
        "ws":     McpTransferability.BRIDGED,
        "sse":    McpTransferability.NATIVE,
    },
    "opencode": {
        "stdio":  McpTransferability.NATIVE,
        "http":   McpTransferability.NATIVE,
        "https":  McpTransferability.NATIVE,
        "ws":     McpTransferability.URL_TRANSLATE,
        "sse":    McpTransferability.NATIVE,
    },
    "cursor": {
        "stdio":  McpTransferability.NATIVE,
        "http":   McpTransferability.NATIVE,
        "https":  McpTransferability.NATIVE,
        "ws":     McpTransferability.UNSUPPORTED,
        "sse":    McpTransferability.NATIVE,
    },
    "windsurf": {
        "stdio":  McpTransferability.NATIVE,
        "http":   McpTransferability.BRIDGED,
        "https":  McpTransferability.BRIDGED,
        "ws":     McpTransferability.UNSUPPORTED,
        "sse":    McpTransferability.BRIDGED,
    },
    "aider": {
        "stdio":  McpTransferability.UNSUPPORTED,
        "http":   McpTransferability.UNSUPPORTED,
        "https":  McpTransferability.UNSUPPORTED,
        "ws":     McpTransferability.UNSUPPORTED,
        "sse":    McpTransferability.UNSUPPORTED,
    },
    "cline": {
        "stdio":  McpTransferability.NATIVE,
        "http":   McpTransferability.NATIVE,
        "https":  McpTransferability.NATIVE,
        "ws":     McpTransferability.UNSUPPORTED,
        "sse":    McpTransferability.NATIVE,
    },
    "continue": {
        "stdio":  McpTransferability.NATIVE,
        "http":   McpTransferability.NATIVE,
        "https":  McpTransferability.NATIVE,
        "ws":     McpTransferability.UNSUPPORTED,
        "sse":    McpTransferability.UNSUPPORTED,
    },
    "zed": {
        "stdio":  McpTransferability.NATIVE,
        "http":   McpTransferability.NATIVE,
        "https":  McpTransferability.NATIVE,
        "ws":     McpTransferability.UNSUPPORTED,
        "sse":    McpTransferability.UNSUPPORTED,
    },
    "neovim": {
        "stdio":  McpTransferability.MANUAL,
        "http":   McpTransferability.MANUAL,
        "https":  McpTransferability.MANUAL,
        "ws":     McpTransferability.UNSUPPORTED,
        "sse":    McpTransferability.UNSUPPORTED,
    },
}

# Well-known MCP servers and their compatibility notes per harness
# These are popular servers that have known quirks in specific harnesses
_KNOWN_SERVER_NOTES: dict[str, dict[str, str]] = {
    "filesystem": {
        "aider": "Not supported — aider manages its own file access",
    },
    "github": {
        "cursor": "Requires GITHUB_TOKEN env var in Cursor MCP config",
        "windsurf": "OAuth flow may differ from Claude Code setup",
    },
    "postgres": {
        "aider": "Not supported — aider has no MCP layer",
        "windsurf": "Needs HTTP bridge (windsurf-mcp-bridge)",
    },
    "brave-search": {
        "aider": "Not supported",
    },
    "memory": {
        "codex": "Codex uses its own memory layer — conflicts possible",
    },
    "sequential-thinking": {
        "codex": "Reasoning tool — codex has native chain-of-thought",
    },
    "puppeteer": {
        "windsurf": "Browser automation not officially supported",
        "aider": "Not supported",
    },
}

# Version requirements for MCP support per harness
_MCP_VERSION_REQUIREMENTS: dict[str, str] = {
    "codex":    ">= 1.0",
    "gemini":   ">= 1.0",
    "opencode": ">= 0.1",
    "cursor":   ">= 0.43",
    "windsurf": ">= 1.0 (bridge required for non-stdio)",
    "aider":    "not supported",
    "cline":    ">= 2.0",
    "continue": ">= 0.8",
    "zed":      ">= 0.1 (context_servers API)",
    "neovim":   "manual plugin config required",
}


@dataclass
class McpServerAnalysis:
    """Per-server compatibility analysis result."""

    server_name: str
    protocol: str          # detected protocol: stdio | http | https | ws | sse | unknown
    command: str           # command (stdio) or url (remote)
    per_harness: dict[str, dict]  # {harness: {transferability, notes}}

    def transferable_targets(self) -> list[str]:
        """Return targets where this server can be transferred (any non-unsupported status)."""
        return [
            h for h, info in self.per_harness.items()
            if info["transferability"] != McpTransferability.UNSUPPORTED
        ]

    def blocked_targets(self) -> list[str]:
        """Return targets where this server cannot transfer."""
        return [
            h for h, info in self.per_harness.items()
            if info["transferability"] == McpTransferability.UNSUPPORTED
        ]


@dataclass
class McpCompatReport:
    """Full MCP compatibility report across all servers and harnesses."""

    servers: list[McpServerAnalysis] = field(default_factory=list)
    harnesses: list[str] = field(default_factory=list)

    @property
    def fully_compatible_count(self) -> int:
        """Count servers that transfer natively to ALL harnesses (excl. aider)."""
        check_harnesses = [h for h in self.harnesses if h != "aider"]
        count = 0
        for server in self.servers:
            if all(
                server.per_harness.get(h, {}).get("transferability")
                == McpTransferability.NATIVE
                for h in check_harnesses
            ):
                count += 1
        return count

    @property
    def blocked_server_count(self) -> int:
        """Count servers that can't transfer to at least one non-aider harness."""
        check_harnesses = [h for h in self.harnesses if h != "aider"]
        count = 0
        for server in self.servers:
            if any(
                server.per_harness.get(h, {}).get("transferability")
                == McpTransferability.UNSUPPORTED
                for h in check_harnesses
            ):
                count += 1
        return count


def _detect_protocol(cfg: dict) -> tuple[str, str]:
    """Detect MCP server protocol and primary endpoint from its config dict.

    Returns:
        (protocol, endpoint) — e.g. ("stdio", "uvx mcp-server-github")
        or ("https", "https://api.example.com/mcp")
    """
    # stdio-based: has 'command' or 'cmd' key
    if "command" in cfg or "cmd" in cfg:
        cmd = cfg.get("command") or cfg.get("cmd", "")
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        return "stdio", str(cmd)

    # URL-based: has 'url' key
    url = cfg.get("url", "")
    if url:
        if url.startswith("wss://") or url.startswith("ws://"):
            return "ws", url
        if url.startswith("https://"):
            return "https", url
        if url.startswith("http://"):
            return "http", url
        # SSE streams often identified by path
        if "sse" in url or "stream" in url:
            return "sse", url
        return "http", url

    # type field may say "sse"
    if cfg.get("type") == "sse":
        return "sse", cfg.get("url", "")

    return "unknown", ""


class McpCompatMatrix:
    """Analyze MCP server transferability across target harnesses.

    Args:
        mcp_servers: Dict mapping server name -> server config dict.
                     Same format as SourceReader.get_mcp_servers() output.
        target_harnesses: Which harnesses to include in the matrix.
                          Defaults to all known harnesses.
    """

    ALL_HARNESSES = [
        "codex", "gemini", "opencode", "cursor",
        "windsurf", "aider", "cline", "continue", "zed", "neovim",
    ]

    def __init__(
        self,
        mcp_servers: dict[str, dict],
        target_harnesses: list[str] | None = None,
    ):
        self.mcp_servers = mcp_servers
        self.harnesses = target_harnesses or self.ALL_HARNESSES

    def analyze(self) -> McpCompatReport:
        """Run full compatibility analysis.

        Returns:
            McpCompatReport with per-server, per-harness analysis.
        """
        report = McpCompatReport(harnesses=self.harnesses)

        for server_name, cfg in self.mcp_servers.items():
            # Support scoped config format from SourceReader
            if isinstance(cfg, dict) and "config" in cfg:
                server_cfg = cfg["config"]
            else:
                server_cfg = cfg

            protocol, endpoint = _detect_protocol(server_cfg)
            per_harness: dict[str, dict] = {}

            for harness in self.harnesses:
                harness_protocols = _PROTOCOL_SUPPORT.get(harness, {})
                transferability = harness_protocols.get(
                    protocol, McpTransferability.UNSUPPORTED
                )

                notes: list[str] = []

                # Check known server-specific notes
                server_key = server_name.lower().replace("-", "_")
                for known_key, harness_notes in _KNOWN_SERVER_NOTES.items():
                    if known_key in server_key or server_key in known_key:
                        if harness in harness_notes:
                            notes.append(harness_notes[harness])

                # Add translation notes
                if transferability == McpTransferability.URL_TRANSLATE:
                    notes.append("Endpoint URL may need updating for this harness")
                elif transferability == McpTransferability.BRIDGED:
                    notes.append("Requires MCP bridge setup")
                elif transferability == McpTransferability.MANUAL:
                    notes.append("Requires manual plugin/extension config")

                per_harness[harness] = {
                    "transferability": transferability,
                    "notes": notes,
                    "version_req": _MCP_VERSION_REQUIREMENTS.get(harness, "unknown"),
                }

            analysis = McpServerAnalysis(
                server_name=server_name,
                protocol=protocol,
                command=endpoint,
                per_harness=per_harness,
            )
            report.servers.append(analysis)

        return report

    def format_table(self, report: McpCompatReport | None = None) -> str:
        """Render the compatibility matrix as an ASCII table.

        Args:
            report: Pre-computed report (runs analyze() if None).

        Returns:
            Multi-line ASCII table string.
        """
        if report is None:
            report = self.analyze()

        if not report.servers:
            return "No MCP servers found in Claude Code config."

        # Symbol legend
        symbols = {
            McpTransferability.NATIVE:      "✓",
            McpTransferability.URL_TRANSLATE: "~",
            McpTransferability.BRIDGED:     "B",
            McpTransferability.UNSUPPORTED: "✗",
            McpTransferability.MANUAL:      "M",
        }

        harness_abbrev = {
            "codex": "CDX", "gemini": "GEM", "opencode": "OPC",
            "cursor": "CRS", "windsurf": "WND", "aider": "ADR",
            "cline": "CLN", "continue": "CNT", "zed": "ZED", "neovim": "NVM",
        }

        col_headers = [harness_abbrev.get(h, h[:3].upper()) for h in report.harnesses]
        name_col_w = max(len(s.server_name) for s in report.servers) + 2
        proto_col_w = 7  # "proto  "
        harness_col_w = 4

        lines: list[str] = []
        lines.append("MCP Server Compatibility Matrix")
        lines.append("=" * (name_col_w + proto_col_w + len(col_headers) * harness_col_w))

        # Legend
        lines.append("Legend: ✓=native  ~=translate  B=bridge  M=manual  ✗=unsupported")
        lines.append("")

        # Header row
        header = f"{'Server':<{name_col_w}}{'Proto':<{proto_col_w}}"
        for abbr in col_headers:
            header += f"{abbr:>{harness_col_w}}"
        lines.append(header)
        lines.append("-" * len(header))

        # Server rows
        for server in report.servers:
            row = f"{server.server_name:<{name_col_w}}{server.protocol:<{proto_col_w}}"
            for harness in report.harnesses:
                info = server.per_harness.get(harness, {})
                sym = symbols.get(
                    info.get("transferability", McpTransferability.UNSUPPORTED), "?"
                )
                row += f"{sym:>{harness_col_w}}"
            lines.append(row)

        lines.append("-" * len(header))
        lines.append("")

        # Summary
        lines.append(
            f"Servers: {len(report.servers)} total  "
            f"| {report.fully_compatible_count} fully portable  "
            f"| {report.blocked_server_count} have transfer issues"
        )

        # Version requirements
        lines.append("")
        lines.append("Harness MCP version requirements:")
        for harness in report.harnesses:
            req = _MCP_VERSION_REQUIREMENTS.get(harness, "unknown")
            abbr = harness_abbrev.get(harness, harness[:3].upper())
            lines.append(f"  {abbr} ({harness}): {req}")

        # Per-server notes
        server_notes = []
        for server in report.servers:
            all_notes: list[str] = []
            for harness, info in server.per_harness.items():
                for note in info.get("notes", []):
                    all_notes.append(f"  [{harness}] {note}")
            if all_notes:
                server_notes.append(f"\n{server.server_name}:")
                server_notes.extend(all_notes)

        if server_notes:
            lines.append("")
            lines.append("Notes:")
            lines.extend(server_notes)

        return "\n".join(lines)

    def get_blocked_servers(self, target: str) -> list[str]:
        """Return names of MCP servers that cannot transfer to a specific target.

        Args:
            target: Target harness name (e.g. "aider").

        Returns:
            Sorted list of server names that are unsupported by the target.
        """
        report = self.analyze()
        blocked = []
        for server in report.servers:
            info = server.per_harness.get(target, {})
            if info.get("transferability") == McpTransferability.UNSUPPORTED:
                blocked.append(server.server_name)
        return sorted(blocked)

    def get_native_servers(self, target: str) -> list[str]:
        """Return names of MCP servers that transfer natively to a specific target.

        Args:
            target: Target harness name.

        Returns:
            Sorted list of server names with native support.
        """
        report = self.analyze()
        native = []
        for server in report.servers:
            info = server.per_harness.get(target, {})
            if info.get("transferability") == McpTransferability.NATIVE:
                native.append(server.server_name)
        return sorted(native)
