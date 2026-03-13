from __future__ import annotations

"""MCP Server Registry Browser (item 16).

Browses a curated list of popular MCP servers, shows which ones are already
configured in Claude Code, and provides helpers to add new ones.

The registry is fetched from a remote community registry (or falls back to
a bundled offline snapshot). Users browse, search, and add servers in one
step, reducing the friction of discovering and installing useful MCP servers.

Usage:
    registry = McpRegistry(cc_home=Path("~/.claude"))
    entries = registry.list_entries()        # all known servers
    installed = registry.get_installed()     # already configured
    registry.search("github")               # filter by keyword
    registry.install("mcp-server-github")   # add to ~/.claude.json
"""

import json
import os
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# Community registry URL — falls back to built-in snapshot if unreachable
_REGISTRY_URL = "https://raw.githubusercontent.com/modelcontextprotocol/servers/main/registry.json"

# Bundled offline registry snapshot (curated popular servers)
_BUILTIN_REGISTRY: list[dict[str, Any]] = [
    {
        "id": "mcp-server-filesystem",
        "name": "Filesystem",
        "description": "File system access — read, write, list, search files",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "{allowed_dir}"],
        "category": "core",
        "tags": ["files", "read", "write"],
    },
    {
        "id": "mcp-server-github",
        "name": "GitHub",
        "description": "GitHub API — repos, issues, PRs, code search",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"},
        "category": "integration",
        "tags": ["github", "git", "repos", "prs"],
    },
    {
        "id": "mcp-server-brave-search",
        "name": "Brave Search",
        "description": "Web search via Brave Search API",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env": {"BRAVE_API_KEY": "${BRAVE_API_KEY}"},
        "category": "search",
        "tags": ["search", "web", "browse"],
    },
    {
        "id": "mcp-server-postgres",
        "name": "PostgreSQL",
        "description": "Query PostgreSQL databases",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres", "{connection_string}"],
        "category": "database",
        "tags": ["postgres", "sql", "database"],
    },
    {
        "id": "mcp-server-sqlite",
        "name": "SQLite",
        "description": "SQLite database access",
        "command": "uvx",
        "args": ["mcp-server-sqlite", "--db-path", "{db_path}"],
        "category": "database",
        "tags": ["sqlite", "sql", "database"],
    },
    {
        "id": "mcp-server-memory",
        "name": "Memory",
        "description": "Persistent key-value memory store across conversations",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-memory"],
        "category": "core",
        "tags": ["memory", "persistence"],
    },
    {
        "id": "mcp-server-fetch",
        "name": "Fetch",
        "description": "HTTP fetch — retrieve web pages and APIs",
        "command": "uvx",
        "args": ["mcp-server-fetch"],
        "category": "network",
        "tags": ["http", "fetch", "web", "api"],
    },
    {
        "id": "mcp-server-git",
        "name": "Git",
        "description": "Git repository operations — log, diff, blame, stash",
        "command": "uvx",
        "args": ["mcp-server-git", "--repository", "{repo_path}"],
        "category": "core",
        "tags": ["git", "version-control"],
    },
    {
        "id": "mcp-server-slack",
        "name": "Slack",
        "description": "Post messages and read channels via Slack API",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env": {
            "SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}",
            "SLACK_TEAM_ID": "${SLACK_TEAM_ID}",
        },
        "category": "integration",
        "tags": ["slack", "messaging"],
    },
    {
        "id": "mcp-server-puppeteer",
        "name": "Puppeteer",
        "description": "Browser automation via Puppeteer — screenshots, scraping, testing",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "category": "automation",
        "tags": ["browser", "puppeteer", "testing", "screenshot"],
    },
    {
        "id": "mcp-server-time",
        "name": "Time",
        "description": "Current time and timezone conversion",
        "command": "uvx",
        "args": ["mcp-server-time"],
        "category": "utility",
        "tags": ["time", "timezone", "datetime"],
    },
    {
        "id": "mcp-server-google-drive",
        "name": "Google Drive",
        "description": "Read and write Google Drive files",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-google-drive"],
        "category": "integration",
        "tags": ["google", "drive", "storage"],
    },
    {
        "id": "mcp-server-aws-kb",
        "name": "AWS Knowledge Base",
        "description": "Query AWS Bedrock knowledge bases",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-aws-kb-retrieval-server"],
        "env": {
            "AWS_ACCESS_KEY_ID": "${AWS_ACCESS_KEY_ID}",
            "AWS_SECRET_ACCESS_KEY": "${AWS_SECRET_ACCESS_KEY}",
            "AWS_REGION": "${AWS_REGION}",
        },
        "category": "cloud",
        "tags": ["aws", "bedrock", "knowledge-base"],
    },
    {
        "id": "mcp-context7",
        "name": "Context7",
        "description": "Up-to-date library documentation and code examples",
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp"],
        "category": "development",
        "tags": ["docs", "documentation", "libraries"],
    },
    {
        "id": "mcp-linear",
        "name": "Linear",
        "description": "Manage Linear issues and projects",
        "command": "npx",
        "args": ["-y", "linear-mcp-server"],
        "env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"},
        "category": "integration",
        "tags": ["linear", "issues", "project-management"],
    },
    {
        "id": "mcp-sentry",
        "name": "Sentry",
        "description": "Query Sentry for errors, issues, and traces",
        "command": "npx",
        "args": ["-y", "@sentry/mcp-server"],
        "env": {"SENTRY_AUTH_TOKEN": "${SENTRY_AUTH_TOKEN}"},
        "category": "monitoring",
        "tags": ["sentry", "errors", "monitoring"],
    },
]

# Categories for display grouping
_CATEGORIES = ["core", "development", "database", "search", "network",
                "integration", "automation", "cloud", "monitoring", "utility"]

# Portability level constants
PORTABILITY_UNIVERSAL = "universal"      # Works in all MCP-capable harnesses via stdio
PORTABILITY_NODE_REQUIRED = "node"       # Requires Node.js (npx); not all sandboxes allow it
PORTABILITY_PYTHON_REQUIRED = "python"   # Requires Python/uvx; broader but not universal
PORTABILITY_CLAUDE_ONLY = "claude-only"  # Plugin-style, Claude Code only
PORTABILITY_PARTIAL = "partial"          # Works in some harnesses, not all

# Harnesses that fully support stdio MCP servers
_MCP_CAPABLE_HARNESSES = {
    "codex", "gemini", "opencode", "cursor", "cline", "continue", "windsurf", "zed", "neovim"
}

# Per-server portability overrides.  Key = server ID, value = portability level.
# Default (not listed here) is inferred from command type.
_PORTABILITY_OVERRIDES: dict[str, str] = {
    # Claude Code-specific plugins that use cc:// or plugin: scheme
    "mcp-hookify": PORTABILITY_CLAUDE_ONLY,
    "mcp-superpowers": PORTABILITY_CLAUDE_ONLY,
    "mcp-claude-code-skills": PORTABILITY_CLAUDE_ONLY,
    # Servers with known compatibility issues in non-Node harnesses
    "mcp-server-puppeteer": PORTABILITY_NODE_REQUIRED,
    "mcp-server-google-drive": PORTABILITY_NODE_REQUIRED,
    "mcp-server-slack": PORTABILITY_NODE_REQUIRED,
}


def _infer_portability(command: str, server_id: str) -> str:
    """Infer portability level from command launcher.

    Args:
        command: The command used to launch the server (e.g. 'npx', 'uvx').
        server_id: Server ID for override lookup.

    Returns:
        Portability level string.
    """
    if server_id in _PORTABILITY_OVERRIDES:
        return _PORTABILITY_OVERRIDES[server_id]
    if command in ("npx", "node"):
        return PORTABILITY_NODE_REQUIRED
    if command in ("uvx", "python", "python3", "uv"):
        return PORTABILITY_PYTHON_REQUIRED
    # Binary or unknown — assume broadly portable
    return PORTABILITY_UNIVERSAL


@dataclass
class RegistryEntry:
    """A single MCP server registry entry."""
    id: str
    name: str
    description: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    category: str = "utility"
    tags: list[str] = field(default_factory=list)
    installed: bool = False
    portability: str = PORTABILITY_UNIVERSAL  # portability level

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RegistryEntry":
        server_id = d.get("id", "")
        command = d.get("command", "")
        portability = d.get("portability") or _infer_portability(command, server_id)
        return cls(
            id=server_id,
            name=d.get("name", server_id),
            description=d.get("description", ""),
            command=command,
            args=d.get("args", []),
            env=d.get("env", {}),
            category=d.get("category", "utility"),
            tags=d.get("tags", []),
            portability=portability,
        )

    @property
    def portability_label(self) -> str:
        """Human-readable portability label."""
        labels = {
            PORTABILITY_UNIVERSAL: "universal",
            PORTABILITY_NODE_REQUIRED: "requires Node.js",
            PORTABILITY_PYTHON_REQUIRED: "requires Python/uvx",
            PORTABILITY_CLAUDE_ONLY: "Claude Code only",
            PORTABILITY_PARTIAL: "partial",
        }
        return labels.get(self.portability, self.portability)

    @property
    def is_portable(self) -> bool:
        """True if this server can be used in non-Claude-Code harnesses."""
        return self.portability != PORTABILITY_CLAUDE_ONLY

    def to_mcp_config(self) -> dict[str, Any]:
        """Convert to Claude Code MCP server config format."""
        config: dict[str, Any] = {
            "type": "stdio",
            "command": self.command,
            "args": self.args,
        }
        if self.env:
            config["env"] = self.env
        return config


class McpRegistry:
    """Browse and manage the MCP server registry.

    Fetches registry data from a remote source (with fallback to the
    bundled offline snapshot) and cross-references against the currently
    installed MCP servers in Claude Code.
    """

    def __init__(
        self,
        cc_home: Path | None = None,
        project_dir: Path | None = None,
        fetch_remote: bool = True,
        timeout: float = 5.0,
    ):
        self._cc_home = cc_home or Path.home() / ".claude"
        self._project_dir = project_dir or Path.cwd()
        self._fetch_remote = fetch_remote
        self._timeout = timeout
        self._entries: list[RegistryEntry] | None = None

    # ------------------------------------------------------------------
    # Registry loading
    # ------------------------------------------------------------------

    def load(self, force_refresh: bool = False) -> list[RegistryEntry]:
        """Load registry entries (cached after first call).

        Args:
            force_refresh: If True, discard cache and reload.

        Returns:
            List of RegistryEntry objects with installed flag set.
        """
        if self._entries is not None and not force_refresh:
            return self._entries

        raw: list[dict[str, Any]] = []
        if self._fetch_remote:
            raw = self._fetch_remote_registry()
        if not raw:
            raw = list(_BUILTIN_REGISTRY)

        installed = self._get_installed_ids()
        entries = []
        for item in raw:
            entry = RegistryEntry.from_dict(item)
            entry.installed = entry.id in installed
            entries.append(entry)

        self._entries = entries
        return entries

    def _fetch_remote_registry(self) -> list[dict[str, Any]]:
        """Try to fetch the remote registry; return empty list on failure."""
        try:
            req = urllib.request.Request(
                _REGISTRY_URL,
                headers={"User-Agent": "HarnessSync/1.0"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
            data = json.loads(body)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "servers" in data:
                return data["servers"]
        except Exception:
            pass
        return []

    def _get_installed_ids(self) -> set[str]:
        """Return set of installed MCP server IDs from Claude Code config."""
        installed: set[str] = set()
        # Check ~/.claude.json (user-scope MCP servers)
        claude_json = self._cc_home / ".claude.json"
        if not claude_json.exists():
            claude_json = self._cc_home / "claude.json"
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
            mcp_servers = data.get("mcpServers", {})
            for name in mcp_servers:
                installed.add(name)
        except Exception:
            pass

        # Also check project-local .mcp.json
        mcp_json = self._project_dir / ".mcp.json"
        try:
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
            mcp_servers = data.get("mcpServers", {})
            for name in mcp_servers:
                installed.add(name)
        except Exception:
            pass

        return installed

    # ------------------------------------------------------------------
    # Query API
    # ------------------------------------------------------------------

    def list_entries(self, category: str | None = None) -> list[RegistryEntry]:
        """Return all registry entries, optionally filtered by category."""
        entries = self.load()
        if category:
            entries = [e for e in entries if e.category == category]
        return entries

    def get_installed(self) -> list[RegistryEntry]:
        """Return only installed entries."""
        return [e for e in self.load() if e.installed]

    def get_uninstalled(self) -> list[RegistryEntry]:
        """Return entries not yet installed."""
        return [e for e in self.load() if not e.installed]

    def search(self, query: str) -> list[RegistryEntry]:
        """Full-text search entries by name, description, id, or tags.

        Args:
            query: Search string (case-insensitive).

        Returns:
            Matching entries sorted by relevance (exact id/name matches first).
        """
        q = query.lower().strip()
        if not q:
            return self.load()

        exact: list[RegistryEntry] = []
        partial: list[RegistryEntry] = []

        for entry in self.load():
            score = 0
            if q in entry.id.lower():
                score += 10
            if q in entry.name.lower():
                score += 8
            for tag in entry.tags:
                if q in tag.lower():
                    score += 5
            if q in entry.description.lower():
                score += 2
            if score >= 10:
                exact.append(entry)
            elif score > 0:
                partial.append(entry)

        return exact + partial

    def get_by_id(self, server_id: str) -> RegistryEntry | None:
        """Return a registry entry by ID, or None if not found."""
        for entry in self.load():
            if entry.id == server_id:
                return entry
        return None

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------

    def install(self, server_id: str, scope: str = "user") -> tuple[bool, str]:
        """Add an MCP server to Claude Code config.

        Args:
            server_id: Registry entry ID to install.
            scope: "user" (add to ~/.claude.json) or "project" (add to .mcp.json).

        Returns:
            (success, message) tuple.
        """
        entry = self.get_by_id(server_id)
        if entry is None:
            return False, f"Server '{server_id}' not found in registry"

        if scope == "project":
            return self._install_to_project(entry)
        return self._install_to_user(entry)

    def _install_to_user(self, entry: RegistryEntry) -> tuple[bool, str]:
        """Add MCP server to ~/.claude.json user-scope mcpServers."""
        claude_json_path = self._cc_home / ".claude.json"
        if not claude_json_path.exists():
            claude_json_path = self._cc_home / "claude.json"

        try:
            if claude_json_path.exists():
                data = json.loads(claude_json_path.read_text(encoding="utf-8"))
            else:
                data = {}

            if "mcpServers" not in data:
                data["mcpServers"] = {}

            if entry.id in data["mcpServers"]:
                return True, f"'{entry.id}' is already configured in Claude Code"

            data["mcpServers"][entry.id] = entry.to_mcp_config()

            self._cc_home.mkdir(parents=True, exist_ok=True)
            claude_json_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            # Invalidate cached entries
            self._entries = None

            return True, f"Added '{entry.name}' to Claude Code MCP servers"
        except Exception as e:
            return False, f"Failed to install '{entry.id}': {e}"

    def _install_to_project(self, entry: RegistryEntry) -> tuple[bool, str]:
        """Add MCP server to project-local .mcp.json."""
        mcp_json_path = self._project_dir / ".mcp.json"
        try:
            if mcp_json_path.exists():
                data = json.loads(mcp_json_path.read_text(encoding="utf-8"))
            else:
                data = {}

            if "mcpServers" not in data:
                data["mcpServers"] = {}

            if entry.id in data["mcpServers"]:
                return True, f"'{entry.id}' is already configured in .mcp.json"

            data["mcpServers"][entry.id] = entry.to_mcp_config()
            mcp_json_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

            self._entries = None
            return True, f"Added '{entry.name}' to project .mcp.json"
        except Exception as e:
            return False, f"Failed to install '{entry.id}' to project: {e}"

    # ------------------------------------------------------------------
    # Formatting
    # ------------------------------------------------------------------

    def format_list(
        self,
        entries: list[RegistryEntry] | None = None,
        group_by_category: bool = True,
        show_installed: bool = True,
    ) -> str:
        """Format registry entries as a human-readable table."""
        if entries is None:
            entries = self.load()

        if not entries:
            return "No MCP servers found in registry."

        lines = ["MCP Server Registry", "=" * 60]

        if show_installed:
            installed_count = sum(1 for e in entries if e.installed)
            lines.append(f"{len(entries)} servers  |  {installed_count} installed\n")

        if group_by_category:
            by_cat: dict[str, list[RegistryEntry]] = {}
            for entry in entries:
                by_cat.setdefault(entry.category, []).append(entry)

            for cat in _CATEGORIES:
                cat_entries = by_cat.get(cat, [])
                if not cat_entries:
                    continue
                lines.append(f"\n[{cat.upper()}]")
                for e in cat_entries:
                    marker = "✓" if e.installed else " "
                    lines.append(f"  [{marker}] {e.id:<40} {e.name}")
                    lines.append(f"       {e.description}")

            # Anything in an unknown category
            known_cats = set(_CATEGORIES)
            for cat, cat_entries in by_cat.items():
                if cat not in known_cats:
                    lines.append(f"\n[{cat.upper()}]")
                    for e in cat_entries:
                        marker = "✓" if e.installed else " "
                        lines.append(f"  [{marker}] {e.id:<40} {e.name}")
                        lines.append(f"       {e.description}")
        else:
            for e in entries:
                marker = "✓" if e.installed else " "
                lines.append(f"  [{marker}] {e.id:<40} {e.name}")
                lines.append(f"       {e.description}")

        lines.append("\nLegend: [✓] installed  [ ] not installed")
        lines.append("Install with: /sync-registry install <server-id>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Portability analysis
    # ------------------------------------------------------------------

    def analyze_portability(
        self,
        configured_servers: dict[str, Any] | None = None,
    ) -> "PortabilityReport":
        """Analyze portability of configured MCP servers.

        For each configured MCP server, determines whether it will work
        in non-Claude-Code harnesses and flags harness-specific servers
        that need stubs or workarounds.

        Args:
            configured_servers: Dict of {server_name: config} as read from
                .mcp.json or ~/.claude.json. If None, reads from Claude Code config.

        Returns:
            PortabilityReport with per-server classifications.
        """
        if configured_servers is None:
            configured_servers = self._load_configured_servers()

        entries_by_id = {e.id: e for e in self.load()}
        results: list[PortabilityResult] = []

        for name, config in (configured_servers or {}).items():
            # Try to look up in registry
            entry = entries_by_id.get(name)
            if entry:
                portability = entry.portability
                description = entry.description
            else:
                # Infer from config
                command = ""
                if isinstance(config, dict):
                    command = config.get("command", "")
                portability = _infer_portability(command, name)
                description = f"custom server ({command or 'unknown command'})"

            results.append(PortabilityResult(
                server_name=name,
                portability=portability,
                description=description,
                config=config if isinstance(config, dict) else {},
            ))

        return PortabilityReport(results=results)

    def _load_configured_servers(self) -> dict[str, Any]:
        """Load all configured MCP servers from Claude Code config files."""
        servers: dict[str, Any] = {}

        # User-scope
        for fname in (".claude.json", "claude.json"):
            p = self._cc_home / fname
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                servers.update(data.get("mcpServers", {}))
                break
            except Exception:
                pass

        # Project-scope
        try:
            data = json.loads((self._project_dir / ".mcp.json").read_text(encoding="utf-8"))
            servers.update(data.get("mcpServers", {}))
        except Exception:
            pass

        return servers


@dataclass
class PortabilityResult:
    """Portability classification for a single configured MCP server."""
    server_name: str
    portability: str
    description: str
    config: dict[str, Any] = field(default_factory=dict)

    @property
    def is_portable(self) -> bool:
        return self.portability != PORTABILITY_CLAUDE_ONLY

    @property
    def portability_label(self) -> str:
        labels = {
            PORTABILITY_UNIVERSAL: "universal",
            PORTABILITY_NODE_REQUIRED: "requires Node.js",
            PORTABILITY_PYTHON_REQUIRED: "requires Python/uvx",
            PORTABILITY_CLAUDE_ONLY: "Claude Code only",
            PORTABILITY_PARTIAL: "partial",
        }
        return labels.get(self.portability, self.portability)


@dataclass
class PortabilityReport:
    """Portability analysis for all configured MCP servers."""
    results: list[PortabilityResult] = field(default_factory=list)

    @property
    def portable(self) -> list[PortabilityResult]:
        return [r for r in self.results if r.is_portable]

    @property
    def claude_only(self) -> list[PortabilityResult]:
        return [r for r in self.results if r.portability == PORTABILITY_CLAUDE_ONLY]

    @property
    def node_required(self) -> list[PortabilityResult]:
        return [r for r in self.results if r.portability == PORTABILITY_NODE_REQUIRED]

    @property
    def python_required(self) -> list[PortabilityResult]:
        return [r for r in self.results if r.portability == PORTABILITY_PYTHON_REQUIRED]

    def format(self) -> str:
        """Format portability report as a human-readable summary."""
        if not self.results:
            return "No MCP servers configured — nothing to analyze."

        lines = [
            "MCP Server Portability Analysis",
            "=" * 55,
            f"{len(self.results)} server(s) configured | "
            f"{len(self.portable)} portable | "
            f"{len(self.claude_only)} Claude Code only",
            "",
        ]

        groups = [
            (PORTABILITY_UNIVERSAL,       "✓ Universal (all MCP-capable harnesses)",   self.results),
            (PORTABILITY_PYTHON_REQUIRED, "~ Requires Python/uvx",                     []),
            (PORTABILITY_NODE_REQUIRED,   "~ Requires Node.js (npx)",                  []),
            (PORTABILITY_CLAUDE_ONLY,     "✗ Claude Code only (not portable)",          self.claude_only),
            (PORTABILITY_PARTIAL,         "? Partial support",                          []),
        ]

        # Populate groups from results
        by_level: dict[str, list[PortabilityResult]] = {}
        for r in self.results:
            by_level.setdefault(r.portability, []).append(r)

        for level, label, _ in groups:
            items = by_level.get(level, [])
            if not items:
                continue
            lines.append(label)
            for r in items:
                lines.append(f"  {r.server_name:<35} {r.portability_label}")
                if r.description:
                    lines.append(f"    {r.description[:70]}")
            lines.append("")

        if self.claude_only:
            lines.append("Note: Claude Code-only servers will be silently skipped when syncing")
            lines.append("  to other harnesses. Consider whether you need equivalent tools in")
            lines.append("  Gemini, Cursor, etc. or if those features are harness-specific.")

        if self.node_required:
            lines.append("")
            lines.append("Note: Node.js-based servers (npx) work in most harnesses but may")
            lines.append("  fail in sandboxed environments that block subprocess execution.")

        return "\n".join(lines)
