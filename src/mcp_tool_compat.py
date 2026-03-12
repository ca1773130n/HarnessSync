from __future__ import annotations

"""MCP Tool Compatibility Matrix.

Shows which MCP capabilities (tools, resources, prompts, sampling),
transport types, and config features work in each target harness.
Flags MCP server configs that will silently fail when synced to harnesses
that don't support their transport or feature requirements.

Usage::

    from src.mcp_tool_compat import (
        check_server_compat,
        check_all_targets,
        check_servers_batch,
        format_mcp_tool_matrix,
        format_server_warnings,
    )

    # Check a specific server config
    issues = check_server_compat("my-server", {"url": "https://x/sse"}, "codex")
    # -> [CompatIssue(severity="error", message="SSE transport not supported...")]

    # Format the full matrix table
    print(format_mcp_tool_matrix())
"""

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Support level constants
# ---------------------------------------------------------------------------

SUPPORTED = "yes"
PARTIAL = "partial"
UNSUPPORTED = "no"
UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# All known harnesses (display order matches sync_matrix.py)
# ---------------------------------------------------------------------------

ALL_HARNESSES: list[str] = [
    "codex", "gemini", "opencode", "cursor", "aider",
    "windsurf", "cline", "continue", "zed", "neovim", "vscode",
]


# ---------------------------------------------------------------------------
# Transport support matrix
# Maps harness -> frozenset of supported MCP transport types.
# An empty frozenset means the harness writes config but never executes servers.
# ---------------------------------------------------------------------------

MCP_TRANSPORT_SUPPORT: dict[str, frozenset[str]] = {
    # Codex: config.toml; stdio + http only (SSE support was removed)
    "codex":    frozenset({"stdio", "http"}),
    # Gemini CLI: settings.json; full transport support including SSE
    "gemini":   frozenset({"stdio", "http", "sse"}),
    # OpenCode: opencode.json type-discriminated; stdio + http only (no SSE)
    "opencode": frozenset({"stdio", "http"}),
    # Cursor: .cursor/mcp.json; standard MCP JSON; all transports
    "cursor":   frozenset({"stdio", "http", "sse"}),
    # Aider: server name only in .aider.conf.yml; no MCP tool execution
    "aider":    frozenset(),
    # Windsurf: .codeium/windsurf/mcp_config.json; all transports
    "windsurf": frozenset({"stdio", "http", "sse"}),
    # Cline/Roo-Code: .roo/mcp.json; full MCP native support
    "cline":    frozenset({"stdio", "http", "sse"}),
    # Continue.dev: .continue/config.json; stdio + http only
    "continue": frozenset({"stdio", "http"}),
    # Zed: context_servers in settings.json; stdio + http only
    "zed":      frozenset({"stdio", "http"}),
    # Neovim (avante/codecompanion): .avante/mcp.json; all transports
    "neovim":   frozenset({"stdio", "http", "sse"}),
    # VS Code AI extensions (Copilot, Codeium): no MCP support at all
    "vscode":   frozenset(),
}


# ---------------------------------------------------------------------------
# MCP capability type support
# Whether each harness invokes each MCP capability type on connected servers.
# Capability types defined by the MCP spec: tools, resources, prompts, sampling.
# ---------------------------------------------------------------------------

MCP_CAPABILITY_SUPPORT: dict[str, dict[str, str]] = {
    "codex": {
        "tools":     SUPPORTED,
        "resources": UNKNOWN,    # Not documented
        "prompts":   UNKNOWN,    # Not documented
        "sampling":  UNSUPPORTED,
    },
    "gemini": {
        "tools":     SUPPORTED,
        "resources": PARTIAL,    # Limited — read-only resource URIs
        "prompts":   UNKNOWN,    # Not documented
        "sampling":  UNSUPPORTED,
    },
    "opencode": {
        "tools":     SUPPORTED,
        "resources": UNKNOWN,
        "prompts":   UNKNOWN,
        "sampling":  UNSUPPORTED,
    },
    "cursor": {
        "tools":     SUPPORTED,
        "resources": PARTIAL,    # Some resource types supported
        "prompts":   UNSUPPORTED,
        "sampling":  UNSUPPORTED,
    },
    "aider": {
        # Aider does not invoke MCP tools — config is decorative only
        "tools":     UNSUPPORTED,
        "resources": UNSUPPORTED,
        "prompts":   UNSUPPORTED,
        "sampling":  UNSUPPORTED,
    },
    "windsurf": {
        "tools":     SUPPORTED,
        "resources": UNKNOWN,
        "prompts":   UNKNOWN,
        "sampling":  UNSUPPORTED,
    },
    "cline": {
        # Roo-Code has the most complete MCP implementation among harnesses
        "tools":     SUPPORTED,
        "resources": SUPPORTED,
        "prompts":   SUPPORTED,
        "sampling":  UNSUPPORTED,
    },
    "continue": {
        "tools":     SUPPORTED,
        "resources": PARTIAL,    # Injected as context items
        "prompts":   UNSUPPORTED,
        "sampling":  UNSUPPORTED,
    },
    "zed": {
        # context_servers is a reduced MCP subset focused on context provision
        "tools":     PARTIAL,
        "resources": PARTIAL,
        "prompts":   UNSUPPORTED,
        "sampling":  UNSUPPORTED,
    },
    "neovim": {
        "tools":     SUPPORTED,
        "resources": UNKNOWN,
        "prompts":   UNKNOWN,
        "sampling":  UNSUPPORTED,
    },
    "vscode": {
        "tools":     UNSUPPORTED,
        "resources": UNSUPPORTED,
        "prompts":   UNSUPPORTED,
        "sampling":  UNSUPPORTED,
    },
}


# ---------------------------------------------------------------------------
# MCP feature support
# Per-harness flags for config features that affect whether servers work.
# ---------------------------------------------------------------------------

MCP_FEATURE_SUPPORT: dict[str, dict[str, str]] = {
    "codex": {
        # Codex TOML does not support ${VAR} at runtime; must be expanded at sync time
        "env_interpolation": UNSUPPORTED,
        "tool_filtering":    UNKNOWN,
        "per_server_trust":  UNKNOWN,
        # HTTP auth headers only apply to http transport (no SSE)
        "header_auth":       PARTIAL,
    },
    "gemini": {
        # ${VAR} works natively in settings.json
        "env_interpolation": SUPPORTED,
        # includeTools / excludeTools fields per server
        "tool_filtering":    SUPPORTED,
        # trust field per server entry
        "per_server_trust":  SUPPORTED,
        "header_auth":       SUPPORTED,
    },
    "opencode": {
        # ${VAR} in env fields; {env:VAR} syntax required in headers
        "env_interpolation": PARTIAL,
        "tool_filtering":    UNKNOWN,
        # Type-discriminated local/remote config implies basic scoping
        "per_server_trust":  PARTIAL,
        "header_auth":       SUPPORTED,
    },
    "cursor": {
        "env_interpolation": SUPPORTED,
        "tool_filtering":    PARTIAL,
        "per_server_trust":  UNKNOWN,
        "header_auth":       SUPPORTED,
    },
    "aider": {
        "env_interpolation": UNSUPPORTED,
        "tool_filtering":    UNSUPPORTED,
        "per_server_trust":  UNSUPPORTED,
        "header_auth":       UNSUPPORTED,
    },
    "windsurf": {
        "env_interpolation": SUPPORTED,
        "tool_filtering":    UNKNOWN,
        "per_server_trust":  UNKNOWN,
        "header_auth":       UNKNOWN,
    },
    "cline": {
        "env_interpolation": SUPPORTED,
        # allowedTools per server entry
        "tool_filtering":    SUPPORTED,
        # alwaysAllow field per server
        "per_server_trust":  SUPPORTED,
        "header_auth":       SUPPORTED,
    },
    "continue": {
        # Continue uses plain env map — no ${VAR} interpolation in values
        "env_interpolation": PARTIAL,
        "tool_filtering":    UNKNOWN,
        "per_server_trust":  UNKNOWN,
        # requestOptions.headers for HTTP servers
        "header_auth":       PARTIAL,
    },
    "zed": {
        # context_servers uses plain initializationOptions — no ${VAR}
        "env_interpolation": UNSUPPORTED,
        "tool_filtering":    UNSUPPORTED,
        "per_server_trust":  UNSUPPORTED,
        "header_auth":       PARTIAL,
    },
    "neovim": {
        "env_interpolation": SUPPORTED,
        "tool_filtering":    UNKNOWN,
        "per_server_trust":  UNKNOWN,
        "header_auth":       UNKNOWN,
    },
    "vscode": {
        "env_interpolation": UNSUPPORTED,
        "tool_filtering":    UNSUPPORTED,
        "per_server_trust":  UNSUPPORTED,
        "header_auth":       UNSUPPORTED,
    },
}


# One-line notes explaining the key MCP limitation(s) per harness
HARNESS_MCP_NOTES: dict[str, str] = {
    "codex":    "config.toml; no SSE; ${VAR} must be expanded at sync time",
    "gemini":   "settings.json; full support; native ${VAR}; trust + tool filtering",
    "opencode": "opencode.json type-discriminated; no SSE; {env:VAR} in headers",
    "cursor":   ".cursor/mcp.json; standard mcpServers JSON; all transports",
    "aider":    "Name written to .aider.conf.yml only — no MCP tool invocation",
    "windsurf": ".codeium/windsurf/mcp_config.json; standard format; all transports",
    "cline":    ".roo/mcp.json; richest support: resources+prompts+tool allowlist",
    "continue": ".continue/config.json; stdio+http only; no SSE; limited env support",
    "zed":      "context_servers in settings.json; stdio+http only; reduced feature set",
    "neovim":   ".avante/mcp.json; standard mcpServers JSON; all transports",
    "vscode":   "No MCP support in VS Code AI extensions — config silently dropped",
}


# ---------------------------------------------------------------------------
# Compatibility checking
# ---------------------------------------------------------------------------

# Pattern for bash-style ${VAR} references in config strings
_VAR_PATTERN = re.compile(r'\$\{[A-Z_][A-Z0-9_]*')


def _detect_transport(config: dict) -> str:
    """Detect MCP server transport type from config dict.

    Returns:
        "stdio", "sse", "http", or "unknown"
    """
    if "command" in config:
        return "stdio"
    url = config.get("url", "")
    if isinstance(url, str) and url:
        if url.endswith("/sse") or "/sse" in url or "sse" in url.lower():
            return "sse"
        return "http"
    return "unknown"


def _config_uses_var_syntax(config: dict) -> bool:
    """Return True if any config value contains ${VAR} syntax."""
    return bool(_VAR_PATTERN.search(str(config)))


@dataclass
class CompatIssue:
    """A single compatibility issue for an MCP server on a target harness."""

    server: str
    target: str
    severity: str   # "error" | "warning" | "info"
    message: str


def check_server_compat(
    server_name: str,
    config: dict,
    target: str,
) -> list[CompatIssue]:
    """Check a single MCP server config against a target harness.

    Args:
        server_name: Name of the MCP server (used in issue messages).
        config: MCP server config dict (command/url/args/env/headers).
        target: Target harness name (e.g. "codex", "gemini").

    Returns:
        List of CompatIssue objects. Empty list means fully compatible.
    """
    issues: list[CompatIssue] = []
    supported_transports = MCP_TRANSPORT_SUPPORT.get(target, frozenset())

    # --- No MCP execution at all ---
    if not supported_transports:
        issues.append(CompatIssue(
            server=server_name,
            target=target,
            severity="error",
            message=(
                f"No MCP execution support in {target} — "
                f"server config will be synced but silently ignored"
            ),
        ))
        # No point checking further; nothing will run
        return issues

    # --- Transport compatibility ---
    transport = _detect_transport(config)
    if transport == "unknown":
        issues.append(CompatIssue(
            server=server_name,
            target=target,
            severity="warning",
            message=(
                "Unknown transport (no command or url field) — "
                "server may fail to start"
            ),
        ))
    elif transport not in supported_transports:
        issues.append(CompatIssue(
            server=server_name,
            target=target,
            severity="error",
            message=(
                f"{transport.upper()} transport not supported by {target} "
                f"(supported: {', '.join(sorted(supported_transports))})"
                f" — server will be synced but silently fail to connect"
            ),
        ))

    # --- Env var interpolation ---
    feature_support = MCP_FEATURE_SUPPORT.get(target, {})
    env_interp = feature_support.get("env_interpolation", UNKNOWN)
    if _config_uses_var_syntax(config) and env_interp == UNSUPPORTED:
        issues.append(CompatIssue(
            server=server_name,
            target=target,
            severity="warning",
            message=(
                f"Config uses ${{VAR}} syntax but {target} does not support "
                f"runtime env var interpolation — values will be empty strings"
            ),
        ))

    # --- Header auth ---
    if "headers" in config and feature_support.get("header_auth", UNKNOWN) == UNSUPPORTED:
        issues.append(CompatIssue(
            server=server_name,
            target=target,
            severity="warning",
            message=(
                f"Config has HTTP headers but {target} does not support "
                f"header auth — headers will be silently dropped"
            ),
        ))

    return issues


def check_all_targets(
    server_name: str,
    config: dict,
    targets: list[str] | None = None,
) -> dict[str, list[CompatIssue]]:
    """Check a server config against all (or specified) target harnesses.

    Args:
        server_name: MCP server name.
        config: MCP server config dict.
        targets: Subset of harnesses to check. Defaults to ALL_HARNESSES.

    Returns:
        Dict mapping target name -> list of CompatIssue.
        Targets with no issues are excluded from the result.
    """
    if targets is None:
        targets = ALL_HARNESSES
    return {
        t: issues
        for t in targets
        if (issues := check_server_compat(server_name, config, t))
    }


def check_servers_batch(
    mcp_servers: dict[str, dict],
    targets: list[str] | None = None,
) -> dict[str, dict[str, list[CompatIssue]]]:
    """Check all MCP servers in a config batch against all targets.

    Args:
        mcp_servers: Dict mapping server name -> config dict.
        targets: Subset of harnesses to check. Defaults to ALL_HARNESSES.

    Returns:
        Nested dict: {server_name: {target: [CompatIssue, ...]}}
        Only servers/targets with issues are included.
    """
    return {
        name: by_target
        for name, config in mcp_servers.items()
        if (by_target := check_all_targets(name, config, targets))
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

_LEVEL_SYMBOLS: dict[str, str] = {
    SUPPORTED:   "✓",
    PARTIAL:     "~",
    UNSUPPORTED: "✗",
    UNKNOWN:     "?",
}

_SEVERITY_SYMBOLS: dict[str, str] = {
    "error":   "✗",
    "warning": "⚠",
    "info":    "i",
}


def format_mcp_tool_matrix(section: str = "all") -> str:
    """Format the MCP tool compatibility matrix as a text table.

    Args:
        section: Which sub-table to show.
            "transport"    — transport type support per harness
            "capabilities" — MCP capability types (tools/resources/prompts/sampling)
            "features"     — config features (env vars, tool filtering, etc.)
            "all"          — all three sections (default)

    Returns:
        Formatted multi-section string ready to print.
    """
    lines: list[str] = []
    lines.append("MCP Tool Compatibility Matrix")
    lines.append("=" * 72)
    lines.append("Legend:  ✓ yes  ~ partial  ✗ no  ? unknown")
    lines.append("")

    if section in ("transport", "all"):
        lines.extend(_format_transport_section())

    if section in ("capabilities", "all"):
        lines.extend(_format_capabilities_section())

    if section in ("features", "all"):
        lines.extend(_format_features_section())

    lines.append("")
    lines.append(
        "Tip: Run /sync-mcp-health to check live reachability of your servers."
    )
    lines.append(
        "     Use /sync-matrix --notes for full config section support details."
    )

    return "\n".join(lines)


def _col_header_row(harnesses: list[str], label_w: int, col_w: int) -> str:
    hdr = " " * label_w
    for h in harnesses:
        hdr += f"  {h[:col_w - 2]:<{col_w - 2}}"
    return hdr


def _format_transport_section() -> list[str]:
    lines: list[str] = [
        "── Transport Support ──────────────────────────────────────────────────",
        "",
    ]
    label_w, col_w = 7, 9
    lines.append(_col_header_row(ALL_HARNESSES, label_w, col_w))
    lines.append("-" * (label_w + len(ALL_HARNESSES) * col_w))

    for transport in ("stdio", "http", "sse"):
        row = f"{transport:>{label_w}}"
        for h in ALL_HARNESSES:
            sym = "✓" if transport in MCP_TRANSPORT_SUPPORT.get(h, frozenset()) else "✗"
            row += f"  {sym:<{col_w - 2}}"
        lines.append(row)

    lines.append("")
    return lines


def _format_capabilities_section() -> list[str]:
    lines: list[str] = [
        "── MCP Capability Types ───────────────────────────────────────────────",
        "",
    ]
    label_w, col_w = 10, 9
    lines.append(_col_header_row(ALL_HARNESSES, label_w, col_w))
    lines.append("-" * (label_w + len(ALL_HARNESSES) * col_w))

    for cap in ("tools", "resources", "prompts", "sampling"):
        row = f"{cap:>{label_w}}"
        for h in ALL_HARNESSES:
            level = MCP_CAPABILITY_SUPPORT.get(h, {}).get(cap, UNKNOWN)
            row += f"  {_LEVEL_SYMBOLS.get(level, '?'):<{col_w - 2}}"
        lines.append(row)

    lines.append("")
    return lines


def _format_features_section() -> list[str]:
    lines: list[str] = [
        "── Config Features ────────────────────────────────────────────────────",
        "",
    ]
    label_w, col_w = 16, 9
    lines.append(_col_header_row(ALL_HARNESSES, label_w, col_w))
    lines.append("-" * (label_w + len(ALL_HARNESSES) * col_w))

    feature_labels = [
        ("env_interpolation", "env-interpolation"),
        ("tool_filtering",    "tool-filtering"),
        ("per_server_trust",  "per-server-trust"),
        ("header_auth",       "header-auth"),
    ]
    for feat, label in feature_labels:
        row = f"{label:>{label_w}}"
        for h in ALL_HARNESSES:
            level = MCP_FEATURE_SUPPORT.get(h, {}).get(feat, UNKNOWN)
            row += f"  {_LEVEL_SYMBOLS.get(level, '?'):<{col_w - 2}}"
        lines.append(row)

    lines.append("")
    lines.append("Notes:")
    for h in ALL_HARNESSES:
        note = HARNESS_MCP_NOTES.get(h, "")
        if note:
            lines.append(f"  {h:<10}  {note}")
    lines.append("")
    return lines


def format_server_warnings(
    mcp_servers: dict[str, dict],
    targets: list[str] | None = None,
) -> str:
    """Format compatibility warnings for a batch of MCP servers.

    Returns an empty string if all servers are compatible with all targets.

    Args:
        mcp_servers: Dict mapping server name -> config dict.
        targets: Subset of harnesses to check. Defaults to ALL_HARNESSES.

    Returns:
        Human-readable warning block, or "" if nothing to report.
    """
    issues_by_server = check_servers_batch(mcp_servers, targets)
    if not issues_by_server:
        return ""

    lines: list[str] = [
        "MCP Server Compatibility Warnings",
        "=" * 60,
    ]

    for server, targets_issues in sorted(issues_by_server.items()):
        errors = [
            issue
            for issue_list in targets_issues.values()
            for issue in issue_list
            if issue.severity == "error"
        ]
        warnings = [
            issue
            for issue_list in targets_issues.values()
            for issue in issue_list
            if issue.severity == "warning"
        ]
        parts = []
        if errors:
            parts.append(f"✗ {len(errors)} error(s)")
        if warnings:
            parts.append(f"⚠ {len(warnings)} warning(s)")
        lines.append(f"\n  {server}  ({', '.join(parts)})")
        for target, issue_list in sorted(targets_issues.items()):
            for issue in issue_list:
                sym = _SEVERITY_SYMBOLS.get(issue.severity, "!")
                lines.append(f"    {sym} [{target}]  {issue.message}")

    lines.append("")
    return "\n".join(lines)
