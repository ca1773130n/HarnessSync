from __future__ import annotations

"""MCP server auto-discovery for HarnessSync.

Scans the local system for installed MCP servers by checking:
1. npm global packages (npx -y @modelcontextprotocol/*)
2. Python packages (uvx mcp-server-*)
3. Common well-known MCP server executables on PATH
4. Existing ~/.claude.json and .mcp.json configs (avoid duplicates)

Suggests adding discovered servers to the Claude Code config so they
can be synced to all harnesses via HarnessSync.
"""

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path


# Well-known MCP server executables and their config templates
_KNOWN_MCP_SERVERS: dict[str, dict] = {
    "mcp-server-filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "${HOME}"],
        "description": "MCP filesystem server (file read/write/search)",
    },
    "mcp-server-github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": ""},
        "description": "MCP GitHub server (repos, PRs, issues)",
    },
    "mcp-server-brave-search": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env": {"BRAVE_API_KEY": ""},
        "description": "MCP Brave Search server (web search)",
    },
    "mcp-server-postgres": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres", "${DATABASE_URL}"],
        "description": "MCP PostgreSQL server (database queries)",
    },
    "mcp-server-sqlite": {
        "command": "uvx",
        "args": ["mcp-server-sqlite", "--db-path", "${HOME}/mcp.db"],
        "description": "MCP SQLite server (local database)",
    },
    "mcp-server-fetch": {
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "description": "MCP fetch server (HTTP requests, web content)",
    },
    "mcp-server-memory": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "description": "MCP memory server (persistent key-value store)",
    },
    "mcp-server-puppeteer": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "description": "MCP Puppeteer server (browser automation)",
    },
    "mcp-server-git": {
        "command": "uvx",
        "args": ["mcp-server-git"],
        "description": "MCP git server (repository operations)",
    },
    "mcp-server-aws-kb-retrieval": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-aws-kb-retrieval"],
        "env": {
            "AWS_ACCESS_KEY_ID": "",
            "AWS_SECRET_ACCESS_KEY": "",
            "AWS_REGION": "us-east-1",
        },
        "description": "MCP AWS Knowledge Base server",
    },
}

# npm package prefix for MCP servers
_NPM_MCP_PREFIX = "@modelcontextprotocol/server-"

# Python package prefix for MCP servers
_PYTHON_MCP_PREFIX = "mcp-server-"


@dataclass
class DiscoveredMcpServer:
    """A discovered MCP server candidate."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    description: str = ""
    source: str = ""    # "path" | "npm-global" | "python-package" | "known-pattern"
    already_configured: bool = False


@dataclass
class McpDiscoveryReport:
    """Report of discovered MCP servers."""
    discovered: list[DiscoveredMcpServer] = field(default_factory=list)
    already_configured: list[str] = field(default_factory=list)
    scan_errors: list[str] = field(default_factory=list)

    @property
    def new_servers(self) -> list[DiscoveredMcpServer]:
        return [s for s in self.discovered if not s.already_configured]

    def format(self) -> str:
        """Format the discovery report as human-readable text."""
        lines = ["## MCP Server Auto-Discovery Report", ""]

        if not self.discovered and not self.scan_errors:
            lines.append("No new MCP servers discovered on this system.")
            return "\n".join(lines)

        if self.already_configured:
            lines.append(
                f"Already configured: {', '.join(sorted(self.already_configured))}\n"
            )

        new = self.new_servers
        if new:
            lines.append(f"Discovered {len(new)} new MCP server(s) not yet in your config:\n")
            for server in new:
                lines.append(f"  [{server.source}] {server.name}")
                lines.append(f"    {server.description}")
                cmd_str = " ".join([server.command] + server.args)
                lines.append(f"    Command: {cmd_str}")
                if server.env:
                    lines.append(f"    Env vars required: {', '.join(server.env.keys())}")
                lines.append("")

            lines.append(
                "To add these to your Claude Code config, run:\n"
                "  /sync-setup\n"
                "or manually add them to ~/.claude/settings.json mcpServers."
            )
        else:
            lines.append("All discovered servers are already configured.")

        if self.scan_errors:
            lines.append("\nScan warnings:")
            for err in self.scan_errors:
                lines.append(f"  - {err}")

        return "\n".join(lines)

    def as_mcp_config(self) -> dict[str, dict]:
        """Return discovered new servers as mcpServers config dict.

        Returns:
            Dict suitable for merging into mcpServers configuration.
        """
        result = {}
        for server in self.new_servers:
            entry: dict = {"command": server.command}
            if server.args:
                entry["args"] = server.args
            if server.env:
                entry["env"] = server.env
            result[server.name] = entry
        return result


class McpAutoDiscovery:
    """Discovers MCP servers installed on the local system.

    Args:
        cc_home: Claude Code home directory (defaults to ~/.claude).
        project_dir: Optional project root for checking .mcp.json.
    """

    def __init__(self, cc_home: Path = None, project_dir: Path = None):
        self.cc_home = cc_home or Path.home() / ".claude"
        self.project_dir = project_dir

    def discover(self) -> McpDiscoveryReport:
        """Run full MCP server discovery scan.

        Returns:
            McpDiscoveryReport with all findings.
        """
        report = McpDiscoveryReport()

        # Load already-configured servers to avoid duplicate suggestions
        configured = self._load_configured_servers()
        report.already_configured = sorted(configured.keys())

        # Scan for new servers
        candidates: list[DiscoveredMcpServer] = []

        candidates.extend(self._scan_path_executables(configured))
        candidates.extend(self._scan_npm_global(configured, report))
        candidates.extend(self._scan_python_packages(configured, report))
        candidates.extend(self._check_known_patterns(configured))
        candidates.extend(self._scan_mcp_home_directory(configured, report))

        # Deduplicate by name
        seen_names: set[str] = set()
        for candidate in candidates:
            if candidate.name not in seen_names:
                seen_names.add(candidate.name)
                report.discovered.append(candidate)

        return report

    def _load_configured_servers(self) -> dict[str, dict]:
        """Load currently configured MCP servers from Claude Code config."""
        configured: dict[str, dict] = {}

        # Load from ~/.claude/settings.json
        settings_path = self.cc_home / "settings.json"
        if settings_path.is_file():
            try:
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                configured.update(data.get("mcpServers", {}))
            except (OSError, ValueError):
                pass

        # Load from ~/.claude.json (user-level)
        claude_json = Path.home() / ".claude.json"
        if claude_json.is_file():
            try:
                data = json.loads(claude_json.read_text(encoding="utf-8"))
                for project_data in data.get("projects", {}).values():
                    configured.update(project_data.get("mcpServers", {}))
            except (OSError, ValueError):
                pass

        # Load from project .mcp.json
        if self.project_dir:
            mcp_json = self.project_dir / ".mcp.json"
            if mcp_json.is_file():
                try:
                    data = json.loads(mcp_json.read_text(encoding="utf-8"))
                    configured.update(data.get("mcpServers", {}))
                except (OSError, ValueError):
                    pass

        return configured

    def _scan_path_executables(self, configured: dict) -> list[DiscoveredMcpServer]:
        """Scan PATH for known MCP server executables."""
        found = []
        for name, template in _KNOWN_MCP_SERVERS.items():
            cmd = template.get("command", "")
            if not shutil.which(cmd):
                continue
            # Check if the specific server is likely installed
            args = template.get("args", [])
            pkg = next((a for a in args if "@modelcontextprotocol" in a or "mcp-server" in a), None)
            if pkg:
                # Can't easily verify npm/uvx packages without running them
                continue
            # Direct executable check
            if shutil.which(name):
                already = name in configured
                found.append(DiscoveredMcpServer(
                    name=name,
                    command=cmd,
                    args=list(args),
                    env=dict(template.get("env", {})),
                    description=template.get("description", ""),
                    source="path",
                    already_configured=already,
                ))
        return found

    def _scan_npm_global(
        self, configured: dict, report: McpDiscoveryReport
    ) -> list[DiscoveredMcpServer]:
        """Scan npm global packages for MCP servers."""
        import subprocess
        found = []

        if not shutil.which("npm"):
            return found

        try:
            result = subprocess.run(
                ["npm", "list", "-g", "--depth=0", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0 and not result.stdout:
                return found

            data = json.loads(result.stdout or "{}")
            dependencies = data.get("dependencies", {})

            for pkg_name in dependencies:
                if not pkg_name.startswith(_NPM_MCP_PREFIX):
                    continue
                server_suffix = pkg_name[len(_NPM_MCP_PREFIX):]
                server_name = f"mcp-server-{server_suffix}"
                already = server_name in configured

                # Look up known template or create generic one
                template = _KNOWN_MCP_SERVERS.get(server_name, {})
                found.append(DiscoveredMcpServer(
                    name=server_name,
                    command="npx",
                    args=list(template.get("args", ["-y", pkg_name])),
                    env=dict(template.get("env", {})),
                    description=template.get("description", f"MCP server: {pkg_name}"),
                    source="npm-global",
                    already_configured=already,
                ))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
            report.scan_errors.append(f"npm global scan: {e}")

        return found

    def _scan_python_packages(
        self, configured: dict, report: McpDiscoveryReport
    ) -> list[DiscoveredMcpServer]:
        """Scan Python packages for MCP servers."""
        import subprocess
        found = []

        pip_cmd = shutil.which("pip3") or shutil.which("pip")
        if not pip_cmd:
            return found

        try:
            result = subprocess.run(
                [pip_cmd, "list", "--format=json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return found

            packages = json.loads(result.stdout or "[]")
            for pkg in packages:
                pkg_name = pkg.get("name", "")
                if not pkg_name.startswith(_PYTHON_MCP_PREFIX):
                    continue
                server_name = pkg_name.replace("-", "-")  # normalize
                already = server_name in configured

                template = _KNOWN_MCP_SERVERS.get(server_name, {})
                found.append(DiscoveredMcpServer(
                    name=server_name,
                    command="uvx",
                    args=list(template.get("args", [server_name])),
                    env=dict(template.get("env", {})),
                    description=template.get("description", f"MCP server: {pkg_name}"),
                    source="python-package",
                    already_configured=already,
                ))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, Exception) as e:
            report.scan_errors.append(f"pip package scan: {e}")

        return found

    def _scan_mcp_home_directory(
        self, configured: dict, report: McpDiscoveryReport
    ) -> list[DiscoveredMcpServer]:
        """Scan ~/.mcp/ directory for locally installed MCP server scripts.

        The ~/.mcp/ convention is used by developers who install MCP servers as
        local scripts rather than via npm/pip. Each entry is either an executable
        script (treated as a direct command) or a directory containing a
        package.json (treated as an npx-runnable package).

        Args:
            configured: Already-configured server names to skip.
            report: Discovery report for recording scan errors.

        Returns:
            List of discovered MCP server candidates.
        """
        mcp_home = Path.home() / ".mcp"
        found: list[DiscoveredMcpServer] = []

        if not mcp_home.is_dir():
            return found

        try:
            for entry in sorted(mcp_home.iterdir()):
                name = entry.name
                # Skip hidden files and non-server files
                if name.startswith(".") or name.startswith("_"):
                    continue

                # Normalize name to mcp-server-<name> convention if needed
                server_name = name if name.startswith("mcp-") else f"mcp-{name}"
                already = server_name in configured or name in configured

                if entry.is_file() and entry.stat().st_mode & 0o111:
                    # Executable script — invoke directly
                    found.append(DiscoveredMcpServer(
                        name=server_name,
                        command=str(entry),
                        args=[],
                        description=f"Local MCP server script: {entry}",
                        source="mcp-home",
                        already_configured=already,
                    ))

                elif entry.is_dir():
                    # Check for package.json (Node.js server)
                    pkg_json = entry / "package.json"
                    if pkg_json.is_file():
                        try:
                            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
                            description = pkg.get("description", f"Local MCP server: {name}")
                            main_script = pkg.get("main", "index.js")
                            found.append(DiscoveredMcpServer(
                                name=server_name,
                                command="node",
                                args=[str(entry / main_script)],
                                description=description,
                                source="mcp-home",
                                already_configured=already,
                            ))
                        except (OSError, ValueError) as e:
                            report.scan_errors.append(f"~/.mcp/{name}/package.json: {e}")

                    # Check for pyproject.toml / setup.py (Python server)
                    elif (entry / "pyproject.toml").is_file() or (entry / "setup.py").is_file():
                        found.append(DiscoveredMcpServer(
                            name=server_name,
                            command="python",
                            args=["-m", name.replace("-", "_")],
                            description=f"Local Python MCP server: {name}",
                            source="mcp-home",
                            already_configured=already,
                        ))

        except OSError as e:
            report.scan_errors.append(f"~/.mcp/ scan error: {e}")

        return found

    def _check_known_patterns(self, configured: dict) -> list[DiscoveredMcpServer]:
        """Check known MCP server patterns without actually running them.

        For well-known servers with npm/uvx launchers, suggest them if the
        launcher (npx/uvx) is available — users can install the package later.
        """
        found = []
        has_npx = shutil.which("npx") is not None
        has_uvx = shutil.which("uvx") is not None

        for name, template in _KNOWN_MCP_SERVERS.items():
            if name in configured:
                continue
            cmd = template.get("command", "")
            if cmd == "npx" and not has_npx:
                continue
            if cmd == "uvx" and not has_uvx:
                continue
            # Suggest it as a known pattern
            found.append(DiscoveredMcpServer(
                name=name,
                command=cmd,
                args=list(template.get("args", [])),
                env=dict(template.get("env", {})),
                description=template.get("description", ""),
                source="known-pattern",
                already_configured=False,
            ))

        return found
