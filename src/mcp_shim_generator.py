from __future__ import annotations

"""MCP Transport Auto-Shim Generator (item 30).

Automatically generates thin proxy wrapper scripts for MCP servers that use
a transport protocol unsupported by a target harness. For example, wraps an
SSE server to look like a stdio server for Codex, so users get MCP tool
parity without manually writing bridge scripts.

Supported shim types:
  - sse-to-stdio:  Wraps an SSE server as a stdio-transport server
  - http-to-stdio: Wraps an HTTP MCP server as stdio

The shim is a Python script that can be run as a child process (stdio
transport) while forwarding calls to the real server.

Usage:
    from src.mcp_shim_generator import ShimGenerator

    gen = ShimGenerator(project_dir)
    plan = gen.build_shim_plan(mcp_servers, target="codex")
    for shim in plan.shims_needed:
        path = gen.write_shim(shim)
        print(f"Shim written: {path}")
    print(plan.format_report())
"""

import json
import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Shim types
# ---------------------------------------------------------------------------

SHIM_DIR = ".harnesssync/shims"


class ShimType:
    SSE_TO_STDIO = "sse-to-stdio"
    HTTP_TO_STDIO = "http-to-stdio"
    UNSUPPORTED = "unsupported"


@dataclass
class ShimSpec:
    """Specification for a single shim to generate.

    Attributes:
        server_name: MCP server name (from config).
        shim_type: One of ShimType constants.
        source_url: URL of the real server (e.g. 'http://localhost:3000/sse').
        target: Harness target this shim is intended for.
        shim_filename: Suggested output filename for the shim script.
        description: Human-readable explanation of why the shim is needed.
    """

    server_name: str
    shim_type: str
    source_url: str
    target: str
    shim_filename: str
    description: str = ""

    @property
    def is_generatable(self) -> bool:
        """Return True if we know how to generate this shim type."""
        return self.shim_type in (ShimType.SSE_TO_STDIO, ShimType.HTTP_TO_STDIO)


@dataclass
class ShimPlan:
    """Result of shim planning for a set of MCP servers against a target.

    Attributes:
        target: Harness target name.
        shims_needed: List of shims to generate.
        unsupported_servers: Servers whose transport can't be shimmed.
        already_compatible: Servers that work natively (no shim needed).
    """

    target: str
    shims_needed: list[ShimSpec] = field(default_factory=list)
    unsupported_servers: list[str] = field(default_factory=list)
    already_compatible: list[str] = field(default_factory=list)

    def format_report(self) -> str:
        """Return human-readable shim plan report."""
        lines = [
            f"MCP Transport Shim Plan — target: {self.target}",
            "=" * 50,
        ]
        if self.already_compatible:
            lines.append(f"\nNative (no shim needed): {len(self.already_compatible)}")
            for name in self.already_compatible:
                lines.append(f"  ✓ {name}")

        if self.shims_needed:
            generatable = [s for s in self.shims_needed if s.is_generatable]
            not_generatable = [s for s in self.shims_needed if not s.is_generatable]
            lines.append(f"\nShims to generate: {len(generatable)}")
            for shim in generatable:
                lines.append(f"  ~ {shim.server_name} ({shim.shim_type})")
                lines.append(f"      → {SHIM_DIR}/{shim.shim_filename}")
                if shim.description:
                    lines.append(f"      {shim.description}")
            if not_generatable:
                lines.append(f"\nRequire manual shim ({len(not_generatable)}):")
                for shim in not_generatable:
                    lines.append(f"  ✗ {shim.server_name}: {shim.description or 'no auto-shim available'}")

        if self.unsupported_servers:
            lines.append(f"\nUnsupported (MCP not supported by {self.target}): {len(self.unsupported_servers)}")
            for name in self.unsupported_servers:
                lines.append(f"  ✗ {name}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Protocol detection
# ---------------------------------------------------------------------------

def _detect_transport(server_cfg: dict) -> tuple[str, str]:
    """Detect transport type and endpoint URL from a server config.

    Args:
        server_cfg: MCP server config dict.

    Returns:
        (transport_type, endpoint_url) tuple.
        transport_type: 'stdio' | 'sse' | 'http' | 'https' | 'ws' | 'unknown'
    """
    # Explicit transport field
    transport = server_cfg.get("transport", "")
    if transport:
        url = server_cfg.get("url", server_cfg.get("endpoint", ""))
        return transport.lower(), url

    # Infer from command (stdio)
    if server_cfg.get("command"):
        return "stdio", ""

    # Infer from URL
    url = server_cfg.get("url", server_cfg.get("endpoint", ""))
    if not url:
        return "unknown", ""

    if url.startswith("wss://") or url.startswith("ws://"):
        return "ws", url
    if "/sse" in url or url.endswith("/events"):
        return "sse", url
    if url.startswith("https://"):
        return "https", url
    if url.startswith("http://"):
        return "http", url

    return "unknown", url


# Harnesses that support stdio natively but NOT sse/http directly
_STDIO_ONLY_HARNESSES = frozenset({"codex", "aider"})


def _needs_shim(transport: str, target: str) -> str:
    """Return shim type needed, or empty string if no shim required."""
    if transport == "stdio":
        return ""  # All harnesses support stdio

    if target in _STDIO_ONLY_HARNESSES:
        if transport == "sse":
            return ShimType.SSE_TO_STDIO
        if transport in ("http", "https"):
            return ShimType.HTTP_TO_STDIO

    return ""  # Other targets can handle it natively


# ---------------------------------------------------------------------------
# Shim script templates
# ---------------------------------------------------------------------------

def _sse_to_stdio_script(server_name: str, sse_url: str) -> str:
    """Generate a Python SSE→stdio bridge script.

    The script connects to the SSE server and proxies MCP messages over
    stdin/stdout, making the remote SSE server appear as a local stdio server.
    """
    return textwrap.dedent(f"""\
        #!/usr/bin/env python3
        \"\"\"
        HarnessSync auto-generated SSE→stdio shim for MCP server: {server_name}
        Source SSE URL: {sse_url}

        This script acts as a stdio-transport MCP server that proxies all
        requests to the real SSE server at the URL above. It is auto-generated
        by HarnessSync and can be regenerated by running:
            /sync --rebuild-shims
        \"\"\"
        import json
        import sys
        import threading
        import urllib.request
        import urllib.error


        SSE_URL = {json.dumps(sse_url)}
        TIMEOUT = 30


        def _post_message(url: str, payload: dict) -> dict:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                url,
                data=data,
                headers={{"Content-Type": "application/json"}},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    body = resp.read().decode()
                    return json.loads(body) if body.strip() else {{}}
            except urllib.error.HTTPError as e:
                return {{"error": {{"code": e.code, "message": str(e)}}}}
            except Exception as e:
                return {{"error": {{"code": -32000, "message": str(e)}}}}


        def main():
            # Determine the RPC endpoint (strip /sse suffix if present)
            rpc_url = SSE_URL
            if rpc_url.endswith("/sse") or rpc_url.endswith("/events"):
                rpc_url = rpc_url.rsplit("/", 1)[0]

            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    continue

                response = _post_message(rpc_url, request)
                sys.stdout.write(json.dumps(response) + "\\n")
                sys.stdout.flush()


        if __name__ == "__main__":
            main()
        """)


def _http_to_stdio_script(server_name: str, http_url: str) -> str:
    """Generate a Python HTTP→stdio bridge script."""
    return textwrap.dedent(f"""\
        #!/usr/bin/env python3
        \"\"\"
        HarnessSync auto-generated HTTP→stdio shim for MCP server: {server_name}
        Source HTTP URL: {http_url}

        This script acts as a stdio-transport MCP server that proxies all
        requests to the real HTTP server at the URL above. It is auto-generated
        by HarnessSync and can be regenerated by running:
            /sync --rebuild-shims
        \"\"\"
        import json
        import sys
        import urllib.request
        import urllib.error


        HTTP_URL = {json.dumps(http_url)}
        TIMEOUT = 30


        def _post_message(payload: dict) -> dict:
            data = json.dumps(payload).encode()
            req = urllib.request.Request(
                HTTP_URL,
                data=data,
                headers={{"Content-Type": "application/json"}},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                    body = resp.read().decode()
                    return json.loads(body) if body.strip() else {{}}
            except urllib.error.HTTPError as e:
                return {{"error": {{"code": e.code, "message": str(e)}}}}
            except Exception as e:
                return {{"error": {{"code": -32000, "message": str(e)}}}}


        def main():
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    continue

                response = _post_message(request)
                sys.stdout.write(json.dumps(response) + "\\n")
                sys.stdout.flush()


        if __name__ == "__main__":
            main()
        """)


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

class ShimGenerator:
    """Generates MCP transport shim scripts for target harnesses.

    Args:
        project_dir: Project root directory. Shims are written to
                     <project_dir>/.harnesssync/shims/.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def build_shim_plan(
        self,
        mcp_servers: dict[str, dict],
        target: str,
    ) -> ShimPlan:
        """Determine which shims are needed for a target.

        Args:
            mcp_servers: Dict of server name → config (from SourceReader).
            target: Harness target to plan shims for.

        Returns:
            ShimPlan describing what to generate.
        """
        plan = ShimPlan(target=target)

        for server_name, raw_cfg in mcp_servers.items():
            # Unwrap scoped format from SourceReader
            cfg = raw_cfg.get("config", raw_cfg) if isinstance(raw_cfg, dict) else {}

            transport, url = _detect_transport(cfg)
            shim_type = _needs_shim(transport, target)

            if not shim_type:
                if transport != "unknown":
                    plan.already_compatible.append(server_name)
                continue

            safe_name = re.sub(r"[^a-z0-9_-]", "_", server_name.lower())
            filename = f"shim_{safe_name}_{target}.py"

            plan.shims_needed.append(ShimSpec(
                server_name=server_name,
                shim_type=shim_type,
                source_url=url,
                target=target,
                shim_filename=filename,
                description=(
                    f"{transport} transport not supported by {target}; "
                    f"auto-shimmed to stdio"
                ),
            ))

        return plan

    def write_shim(self, shim: ShimSpec) -> Path:
        """Write a shim script to disk.

        Args:
            shim: ShimSpec from build_shim_plan().

        Returns:
            Path to the written shim file.

        Raises:
            ValueError: If shim type is not generatable.
        """
        if not shim.is_generatable:
            raise ValueError(
                f"Cannot auto-generate shim of type {shim.shim_type!r} "
                f"for server {shim.server_name!r}"
            )

        shim_dir = self.project_dir / SHIM_DIR
        shim_dir.mkdir(parents=True, exist_ok=True)
        out = shim_dir / shim.shim_filename

        if shim.shim_type == ShimType.SSE_TO_STDIO:
            script = _sse_to_stdio_script(shim.server_name, shim.source_url)
        elif shim.shim_type == ShimType.HTTP_TO_STDIO:
            script = _http_to_stdio_script(shim.server_name, shim.source_url)
        else:
            raise ValueError(f"Unknown shim type: {shim.shim_type!r}")

        out.write_text(script, encoding="utf-8")
        out.chmod(0o755)
        return out

    def write_all_shims(
        self,
        mcp_servers: dict[str, dict],
        target: str,
    ) -> tuple[ShimPlan, dict[str, Path]]:
        """Plan and write all shims for a target.

        Args:
            mcp_servers: MCP server configs.
            target: Target harness name.

        Returns:
            (plan, written_paths) where written_paths maps server_name -> shim path.
        """
        plan = self.build_shim_plan(mcp_servers, target)
        written: dict[str, Path] = {}
        for shim in plan.shims_needed:
            if shim.is_generatable:
                try:
                    path = self.write_shim(shim)
                    written[shim.server_name] = path
                except Exception:
                    pass  # Non-blocking; report via plan
        return plan, written

    def build_shimmed_server_config(
        self,
        server_name: str,
        shim: ShimSpec,
        shim_path: Path,
    ) -> dict:
        """Return a stdio MCP server config pointing to the generated shim.

        This config can replace the original server entry when syncing to
        the target harness.

        Args:
            server_name: Original server name.
            shim: The generated shim spec.
            shim_path: Path to the written shim script.

        Returns:
            MCP server config dict with stdio transport.
        """
        import sys
        python = sys.executable or "python3"
        return {
            "command": python,
            "args": [str(shim_path)],
            "_shim": True,
            "_shim_type": shim.shim_type,
            "_original_url": shim.source_url,
        }

