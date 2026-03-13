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

from src.utils.constants import EXTENDED_TARGETS


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

ALL_HARNESSES: list[str] = list(EXTENDED_TARGETS) + ["vscode"]


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


def portability_score(
    server_name: str,
    config: dict,
    targets: list[str] | None = None,
) -> dict[str, int]:
    """Compute a portability score (0-100) for an MCP server across all targets.

    A score of 100 means the server config works perfectly in that harness.
    Errors deduct 50 points each; warnings deduct 15 points each.
    Score is floored at 0.

    Harnesses that have no MCP transport support at all (aider, vscode) are
    assigned a score of 0 regardless of the config.

    Args:
        server_name: MCP server name (used for logging only).
        config: MCP server config dict from .mcp.json.
        targets: Subset of harnesses to score. Defaults to ALL_HARNESSES.

    Returns:
        Dict mapping target name -> integer score 0-100.
    """
    if targets is None:
        targets = ALL_HARNESSES

    scores: dict[str, int] = {}
    for target in targets:
        # Targets with no MCP execution capability score 0 unconditionally
        if not MCP_TRANSPORT_SUPPORT.get(target):
            scores[target] = 0
            continue

        issues = check_server_compat(server_name, config, target)
        score = 100
        for issue in issues:
            if issue.severity == "error":
                score -= 50
            elif issue.severity == "warning":
                score -= 15
        scores[target] = max(0, score)

    return scores


def format_portability_report(
    mcp_servers: dict[str, dict],
    targets: list[str] | None = None,
) -> str:
    """Format a per-server portability score table across all targets.

    Args:
        mcp_servers: Dict mapping server name -> config dict.
        targets: Subset of harnesses to report. Defaults to ALL_HARNESSES.

    Returns:
        Human-readable table string.
    """
    if targets is None:
        targets = ALL_HARNESSES

    if not mcp_servers:
        return "No MCP servers configured."

    # Column widths
    name_w = max(len(n) for n in mcp_servers) + 2
    col_w = 6

    header = f"{'Server':<{name_w}}"
    for t in targets:
        header += f"  {t[:col_w - 1]:<{col_w - 1}}"
    header += "  Avg"

    sep = "-" * (name_w + (col_w + 1) * len(targets) + 6)

    lines: list[str] = [
        "MCP Server Portability Scores (0-100)",
        "=" * max(len(sep), 40),
        "",
        header,
        sep,
    ]

    for server_name, config in sorted(mcp_servers.items()):
        scores = portability_score(server_name, config, targets)
        avg = int(sum(scores.values()) / len(scores)) if scores else 0
        row = f"{server_name:<{name_w}}"
        for t in targets:
            s = scores.get(t, 0)
            row += f"  {s:>{col_w - 1}}"
        row += f"  {avg:>3}"
        lines.append(row)

    lines += [
        sep,
        "",
        "100 = fully compatible  0 = no support (errors deduct 50, warnings deduct 15)",
    ]
    return "\n".join(lines)


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


def pre_sync_check(
    mcp_servers: dict[str, dict],
    targets: list[str] | None = None,
) -> dict:
    """Run pre-sync compatibility checks on all MCP servers.

    Validates the full MCP config before writing to target harnesses and
    returns a structured report with error counts, per-harness summaries,
    and a go/no-go recommendation.

    Args:
        mcp_servers: Dict mapping server name -> config dict (from .mcp.json).
        targets: Subset of harnesses to validate. Defaults to ALL_HARNESSES.

    Returns:
        Dict with keys:
          - ``ok``: bool  — True if no errors (warnings are acceptable)
          - ``error_count``: int
          - ``warning_count``: int
          - ``blocking``: list[str]  — error messages that will break sync
          - ``cautions``: list[str]  — warning messages to review
          - ``harness_summary``: dict[str, dict]  — per-harness {"errors": int, "warnings": int}
          - ``recommendation``: str  — human-readable go/no-go message
    """
    if targets is None:
        targets = ALL_HARNESSES

    blocking: list[str] = []
    cautions: list[str] = []
    harness_error_count: dict[str, int] = {t: 0 for t in targets}
    harness_warn_count: dict[str, int] = {t: 0 for t in targets}

    for server_name, config in mcp_servers.items():
        for target in targets:
            for issue in check_server_compat(server_name, config, target):
                msg = f"[{target}] {server_name}: {issue.message}"
                if issue.severity == "error":
                    blocking.append(msg)
                    harness_error_count[target] = harness_error_count.get(target, 0) + 1
                elif issue.severity == "warning":
                    cautions.append(msg)
                    harness_warn_count[target] = harness_warn_count.get(target, 0) + 1

    total_errors = len(blocking)
    total_warnings = len(cautions)
    ok = total_errors == 0

    harness_summary = {
        t: {"errors": harness_error_count.get(t, 0), "warnings": harness_warn_count.get(t, 0)}
        for t in targets
    }

    if ok and total_warnings == 0:
        recommendation = "All MCP servers are compatible — safe to sync."
    elif ok:
        recommendation = (
            f"No blocking errors — sync will proceed. "
            f"Review {total_warnings} warning(s) for potential runtime issues."
        )
    else:
        recommendation = (
            f"Sync blocked: {total_errors} error(s) detected. "
            f"Fix the listed issues before syncing."
        )

    return {
        "ok": ok,
        "error_count": total_errors,
        "warning_count": total_warnings,
        "blocking": blocking,
        "cautions": cautions,
        "harness_summary": harness_summary,
        "recommendation": recommendation,
    }


def format_pre_sync_report(check_result: dict) -> str:
    """Format the output of pre_sync_check() as a human-readable terminal string.

    Args:
        check_result: Output dict from pre_sync_check().

    Returns:
        Multi-line formatted string ready for CLI display.
    """
    lines = [
        "MCP Pre-Sync Check",
        "=" * 60,
        "",
    ]

    ok = check_result.get("ok", True)
    status = "PASS" if ok else "FAIL"
    lines.append(f"Status: {status}")
    lines.append(
        f"  {check_result.get('error_count', 0)} error(s), "
        f"{check_result.get('warning_count', 0)} warning(s)"
    )
    lines.append("")

    blocking = check_result.get("blocking", [])
    if blocking:
        lines.append("Blocking Errors:")
        for msg in blocking:
            lines.append(f"  ✗ {msg}")
        lines.append("")

    cautions = check_result.get("cautions", [])
    if cautions:
        lines.append("Warnings:")
        for msg in cautions:
            lines.append(f"  ⚠ {msg}")
        lines.append("")

    lines.append(check_result.get("recommendation", ""))
    return "\n".join(lines)


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


# ---------------------------------------------------------------------------
# MCP Server Portability Advisor (item 3)
# ---------------------------------------------------------------------------

# Known MCP server → harness-native equivalents database
# Maps server name patterns to per-harness alternatives
_MCP_EQUIVALENTS: dict[str, dict[str, str]] = {
    "github": {
        "cursor":   "GitHub Copilot (built-in) — provides file, PR, and issue context natively",
        "windsurf": "GitHub Copilot extension for Windsurf",
        "cline":    "github MCP server (same package, cline supports stdio)",
        "codex":    "codex has native GitHub context via AGENTS.md; MCP adds extra tools",
    },
    "filesystem": {
        "aider":    "Aider natively reads/writes files — MCP filesystem server not needed",
        "cursor":   "Cursor has native file access — MCP filesystem server adds little value",
        "zed":      "Zed has built-in file system access; MCP server is redundant",
    },
    "playwright": {
        "cursor":   "Install Playwright MCP extension from Cursor Extensions marketplace",
        "cline":    "Playwright MCP (same package) works natively with cline stdio support",
        "continue": "No direct Continue.dev equivalent; use a browser-testing CI step instead",
    },
    "context7": {
        "cursor":   "No direct Cursor equivalent; copy context7 prompts into .cursor/rules/",
        "gemini":   "No Gemini CLI equivalent; add library docs to GEMINI.md manually",
        "codex":    "No Codex equivalent; embed relevant docs snippets in AGENTS.md",
    },
    "sqlite": {
        "cursor":   "DB queries supported via Cursor's built-in terminal; MCP adds structure",
        "aider":    "Aider cannot execute DB queries; use CLI tools and pipe output as context",
    },
    "brave-search": {
        "gemini":   "Gemini 2.0 has native web search via Google Search grounding",
        "cursor":   "Cursor has no built-in web search; keep MCP server if available",
        "codex":    "Codex has no built-in web search; keep MCP server",
    },
    "memory": {
        "windsurf": "Windsurf Memories (native) — use .windsurf/memories/ directory instead",
        "cursor":   "Cursor has no native memory; consider using a persistent .mdc always-apply rule",
        "gemini":   "Use GEMINI.md as static memory — no dynamic memory MCP equivalent",
    },
}

# MCP server name normalization: strip common package prefixes/suffixes
_NAME_NORMALIZERS = [
    (r"^@modelcontextprotocol/server-", ""),
    (r"^mcp-server-", ""),
    (r"^mcp-", ""),
    (r"-mcp$", ""),
]


def _normalize_server_name(raw_name: str) -> str:
    """Strip common prefixes/suffixes from an MCP server name for lookup."""
    import re as _re
    name = raw_name.lower()
    for pattern, repl in _NAME_NORMALIZERS:
        name = _re.sub(pattern, repl, name)
    return name


def suggest_alternatives(
    server_name: str,
    config: dict,
    targets: list[str] | None = None,
) -> dict[str, str]:
    """Return harness-native alternatives for an MCP server that can't be synced.

    Looks up the server name in a curated equivalents database and returns
    per-harness suggestions.  Only returns entries for ``targets`` where the
    server has portability issues (score < 70).

    Args:
        server_name: Logical MCP server name (e.g. "github", "playwright").
        config: Server config dict (used to compute portability scores).
        targets: Harnesses to consider. Defaults to ALL_HARNESSES.

    Returns:
        Dict mapping harness name → alternative/workaround description.
        Empty dict if the server is fully portable or has no known alternatives.
    """
    target_list = targets or ALL_HARNESSES
    scores = portability_score(server_name, config, target_list)

    # Find targets where this server has portability problems
    problem_targets = {t for t, s in scores.items() if s < 70}
    if not problem_targets:
        return {}

    # Normalize the server name for lookup
    canonical = _normalize_server_name(server_name)

    # Also try the full name in case of an exact match
    equivalents = _MCP_EQUIVALENTS.get(canonical, _MCP_EQUIVALENTS.get(server_name, {}))

    return {
        t: equivalents[t]
        for t in problem_targets
        if t in equivalents
    }


def format_portability_advice(
    mcp_servers: dict[str, dict],
    targets: list[str] | None = None,
) -> str:
    """Format portability advice for a set of MCP servers.

    Shows which servers have portability issues across which harnesses,
    with per-harness alternative suggestions from the equivalents database.

    Args:
        mcp_servers: Dict mapping server name -> config dict.
        targets: Harnesses to check. Defaults to ALL_HARNESSES.

    Returns:
        Multi-line advice string, or empty string if all servers are portable.
    """
    if not mcp_servers:
        return "No MCP servers configured."

    target_list = targets or ALL_HARNESSES
    advice_lines: list[str] = []

    for server_name, config in sorted(mcp_servers.items()):
        scores = portability_score(server_name, config, target_list)
        alts = suggest_alternatives(server_name, config, target_list)

        problem_targets = sorted(t for t, s in scores.items() if s < 70)
        if not problem_targets:
            continue

        advice_lines.append(f"\n{server_name}:")
        for target in problem_targets:
            score = scores.get(target, 0)
            alt = alts.get(target, "No known equivalent — manual workaround required.")
            sym = "✗" if score == 0 else "⚠"
            advice_lines.append(f"  {sym} [{target}]  score={score}  →  {alt}")

    if not advice_lines:
        return "All configured MCP servers are portable across all target harnesses."

    header = [
        "MCP Server Portability Advice",
        "=" * 60,
        "Servers listed below have portability issues in some harnesses.",
        "Scores: 100=fully compatible  0=completely unsupported",
    ]
    return "\n".join(header + advice_lines + [""])
