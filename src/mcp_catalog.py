from __future__ import annotations

"""MCP Server Catalog Browser.

Provides a curated registry of community MCP servers. Shows which ones you
already have configured in Claude Code, and lets you add new ones to your
.mcp.json (which then auto-syncs everywhere via HarnessSync).

The catalog is bundled as a static list of well-known MCP servers so it
works offline. An optional --refresh flag fetches the latest community list
from the official MCP registry (requires network access).
"""

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Bundled catalog — well-known community MCP servers (offline baseline)
# ---------------------------------------------------------------------------

BUNDLED_CATALOG: list[dict] = [
    {
        "name": "context7",
        "description": "Up-to-date library documentation via Context7",
        "command": "npx",
        "args": ["-y", "@upstash/context7-mcp@latest"],
        "tags": ["documentation", "libraries", "search"],
        "homepage": "https://context7.com",
    },
    {
        "name": "filesystem",
        "description": "Secure file read/write/search inside allowed directories",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "{ALLOWED_DIR}"],
        "tags": ["files", "io", "official"],
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "github",
        "description": "Search repos, read files, manage issues and PRs on GitHub",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_PERSONAL_ACCESS_TOKEN}"},
        "tags": ["github", "vcs", "official"],
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "postgres",
        "description": "Read-only SQL queries against a PostgreSQL database",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-postgres", "${POSTGRES_URL}"],
        "tags": ["database", "sql", "official"],
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "brave-search",
        "description": "Web and local search via Brave Search API",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-brave-search"],
        "env": {"BRAVE_API_KEY": "${BRAVE_API_KEY}"},
        "tags": ["search", "web", "official"],
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "puppeteer",
        "description": "Browser automation and screenshot capture via Puppeteer",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-puppeteer"],
        "tags": ["browser", "automation", "testing", "official"],
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "slack",
        "description": "Post messages and read channels on Slack",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"],
        "env": {
            "SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}",
            "SLACK_TEAM_ID": "${SLACK_TEAM_ID}",
        },
        "tags": ["slack", "messaging", "official"],
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "sentry",
        "description": "Query Sentry issues, events, and performance data",
        "command": "npx",
        "args": ["-y", "@sentry/mcp-server@latest"],
        "env": {"SENTRY_AUTH_TOKEN": "${SENTRY_AUTH_TOKEN}"},
        "tags": ["monitoring", "errors", "sentry"],
        "homepage": "https://github.com/getsentry/sentry-mcp",
    },
    {
        "name": "linear",
        "description": "Read and create Linear issues and projects",
        "command": "npx",
        "args": ["-y", "linear-mcp-server"],
        "env": {"LINEAR_API_KEY": "${LINEAR_API_KEY}"},
        "tags": ["issues", "project-management", "linear"],
        "homepage": "https://github.com/jerhadf/linear-mcp-server",
    },
    {
        "name": "playwright",
        "description": "Browser automation and E2E testing via Playwright",
        "command": "npx",
        "args": ["-y", "@executeautomation/playwright-mcp-server"],
        "tags": ["browser", "testing", "automation"],
        "homepage": "https://github.com/executeautomation/mcp-playwright",
    },
    {
        "name": "sqlite",
        "description": "Read and write SQLite databases",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite", "--db-path", "{DB_PATH}"],
        "tags": ["database", "sqlite", "official"],
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
    {
        "name": "everything",
        "description": "Demo MCP server exposing all tool, resource, and prompt types",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-everything"],
        "tags": ["testing", "demo", "official"],
        "homepage": "https://github.com/modelcontextprotocol/servers",
    },
]


# ---------------------------------------------------------------------------
# Cross-harness MCP translation table (Item 10)
# Maps Claude Code MCP server names to equivalent native capabilities in
# harnesses that don't support MCP or have built-in alternatives.
# ---------------------------------------------------------------------------

MCP_EQUIVALENTS: dict[str, dict[str, str]] = {
    "filesystem": {
        "cursor":    "Built-in: Cursor has native file read/write via @workspace. No MCP needed.",
        "aider":     "Built-in: Aider reads/writes files natively. Pass file paths as CLI args.",
        "windsurf":  "Built-in: Windsurf Cascade has native filesystem access.",
        "continue":  "Built-in: Continue reads files from workspace context automatically.",
    },
    "github": {
        "cursor":    "Extension: Install 'GitHub Pull Requests' VSCode extension for PR/issue access.",
        "aider":     "CLI: Use `gh` CLI alongside Aider for GitHub operations.",
        "windsurf":  "Built-in: Windsurf has GitHub integration via source control panel.",
    },
    "brave-search": {
        "cursor":    "Extension: Use Perplexity or web-search VSCode extensions.",
        "gemini":    "Built-in: Gemini CLI has @google-search grounding (no MCP needed).",
        "aider":     "Workaround: Pipe search results into context manually.",
    },
    "postgres": {
        "cursor":    "Extension: Install 'SQLTools' VSCode extension with PostgreSQL driver.",
        "aider":     "Workaround: Run SQL queries in a terminal and pipe results to Aider.",
    },
    "sqlite": {
        "cursor":    "Extension: Install 'SQLite Viewer' VSCode extension.",
        "aider":     "Workaround: Run sqlite3 CLI queries and paste output into context.",
    },
    "context7": {
        "cursor":    "Built-in: Cursor has @docs context provider. Add library URLs in settings.",
        "gemini":    "Workaround: Use /add-context with documentation URLs in Gemini CLI.",
        "aider":     "Workaround: Pass documentation files as read-only context with --read.",
    },
    "slack": {
        "cursor":    "Extension: Use the Slack VSCode extension for notifications.",
        "aider":     "Workaround: No native equivalent. Use slack-cli for notifications.",
    },
    "puppeteer": {
        "cursor":    "Extension: Use Playwright VSCode extension for browser automation.",
        "aider":     "Workaround: Run Puppeteer/Playwright scripts externally and share output.",
    },
    "playwright": {
        "cursor":    "Built-in: Cursor supports Playwright via MCP or VSCode test extension.",
        "aider":     "Workaround: Run Playwright tests externally; share results with Aider.",
    },
    "sentry": {
        "cursor":    "Extension: Install 'Sentry' VSCode extension for issue browsing.",
        "aider":     "Workaround: Fetch Sentry issues via curl/sentry-cli and paste into context.",
    },
    "linear": {
        "cursor":    "Extension: Install 'Linear' VSCode extension for issue management.",
        "aider":     "Workaround: Use linear-cli to fetch issues and pipe into context.",
    },
}


@dataclass
class HarnessEquivalent:
    """A harness-native equivalent for an MCP server."""
    harness: str
    mcp_server: str
    description: str  # Human-readable explanation of the alternative


@dataclass
class CatalogEntry:
    """A single MCP server entry from the catalog."""
    name: str
    description: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    homepage: str = ""
    installed: bool = False  # True if already in user's .mcp.json

    def to_mcp_config(self) -> dict:
        """Return the MCP server config dict suitable for .mcp.json."""
        cfg: dict = {"command": self.command, "args": self.args}
        if self.env:
            cfg["env"] = self.env
        return cfg


class McpCatalog:
    """Browse and add community MCP servers to Claude Code config.

    Args:
        project_dir: Project root (used to find .mcp.json / .claude/ dirs).
        cc_home: Claude Code config home (default: ~/.claude).
    """

    _REGISTRY_URL = "https://registry.jsonplaceholder.typicode.com"  # placeholder

    def __init__(
        self,
        project_dir: Path | None = None,
        cc_home: Path | None = None,
    ):
        self.project_dir = project_dir or Path.cwd()
        self.cc_home = cc_home or (Path.home() / ".claude")

    def load_catalog(self, refresh: bool = False) -> list[CatalogEntry]:
        """Return catalog entries, marking installed ones.

        Args:
            refresh: If True, attempt to fetch updated list from network.
                     Falls back to bundled catalog on network failure.
        """
        raw_entries: list[dict] = list(BUNDLED_CATALOG)

        if refresh:
            fetched = self._fetch_remote_catalog()
            if fetched:
                # Merge: remote entries override bundled ones by name
                by_name = {e["name"]: e for e in raw_entries}
                for entry in fetched:
                    if isinstance(entry, dict) and "name" in entry:
                        by_name[entry["name"]] = entry
                raw_entries = list(by_name.values())

        installed_names = self._get_installed_names()

        entries: list[CatalogEntry] = []
        for raw in raw_entries:
            entries.append(CatalogEntry(
                name=raw["name"],
                description=raw.get("description", ""),
                command=raw.get("command", "npx"),
                args=raw.get("args", []),
                env=raw.get("env", {}),
                tags=raw.get("tags", []),
                homepage=raw.get("homepage", ""),
                installed=(raw["name"] in installed_names),
            ))

        # Sort: uninstalled first, then alphabetical
        entries.sort(key=lambda e: (e.installed, e.name))
        return entries

    def search(
        self,
        query: str,
        entries: list[CatalogEntry] | None = None,
    ) -> list[CatalogEntry]:
        """Filter catalog entries by name, description, or tag.

        Args:
            query: Search query (case-insensitive substring match).
            entries: Pre-loaded entries (fetches if None).

        Returns:
            Matching entries.
        """
        if entries is None:
            entries = self.load_catalog()
        q = query.lower()
        return [
            e for e in entries
            if q in e.name.lower()
            or q in e.description.lower()
            or any(q in tag for tag in e.tags)
        ]

    def add_server(
        self,
        name: str,
        entries: list[CatalogEntry] | None = None,
        scope: str = "project",
    ) -> tuple[bool, str]:
        """Add a catalog server to the user's .mcp.json.

        Args:
            name: Server name as listed in the catalog.
            entries: Pre-loaded catalog entries.
            scope: 'project' writes to .mcp.json in project_dir,
                   'user' writes to cc_home/.mcp.json.

        Returns:
            (success, message)
        """
        if entries is None:
            entries = self.load_catalog()

        entry = next((e for e in entries if e.name == name), None)
        if entry is None:
            return False, f"Server '{name}' not found in catalog."

        if scope == "user":
            mcp_file = self.cc_home / ".mcp.json"
        else:
            mcp_file = self.project_dir / ".mcp.json"

        mcp_data: dict = {}
        if mcp_file.exists():
            try:
                mcp_data = json.loads(mcp_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                mcp_data = {}

        servers: dict = mcp_data.setdefault("mcpServers", {})
        if name in servers:
            return False, f"Server '{name}' is already configured in {mcp_file}."

        servers[name] = entry.to_mcp_config()
        mcp_file.parent.mkdir(parents=True, exist_ok=True)
        mcp_file.write_text(json.dumps(mcp_data, indent=2), encoding="utf-8")
        return True, f"Added '{name}' to {mcp_file}. Run /sync to propagate to all harnesses."

    def _get_installed_names(self) -> set[str]:
        """Return set of already-configured MCP server names."""
        names: set[str] = set()
        for mcp_file in [
            self.project_dir / ".mcp.json",
            self.cc_home / ".mcp.json",
        ]:
            if mcp_file.exists():
                try:
                    data = json.loads(mcp_file.read_text(encoding="utf-8"))
                    names.update(data.get("mcpServers", {}).keys())
                except (json.JSONDecodeError, OSError):
                    pass
        return names

    def suggest_equivalents(
        self,
        server_names: list[str] | None = None,
        harness: str | None = None,
    ) -> list[HarnessEquivalent]:
        """Return harness-native alternatives for MCP servers.

        For harnesses that lack MCP support (or have built-in equivalents),
        shows what native capability substitutes for each configured server.

        Args:
            server_names: MCP server names to look up. Defaults to all installed.
            harness: Filter to a specific target (None = all harnesses with entries).

        Returns:
            List of HarnessEquivalent suggestions.
        """
        if server_names is None:
            server_names = sorted(self._get_installed_names())

        results: list[HarnessEquivalent] = []
        for name in server_names:
            equiv_map = MCP_EQUIVALENTS.get(name, {})
            for h, description in equiv_map.items():
                if harness is None or h == harness.lower():
                    results.append(HarnessEquivalent(
                        harness=h,
                        mcp_server=name,
                        description=description,
                    ))
        return results

    def _fetch_remote_catalog(self) -> list[dict] | None:
        """Attempt to fetch a remote catalog JSON. Returns None on failure."""
        try:
            req = urllib.request.Request(
                self._REGISTRY_URL,
                headers={"User-Agent": "HarnessSync/1.0"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return data
        except (urllib.error.URLError, json.JSONDecodeError, OSError):
            pass
        return None


def format_catalog(
    entries: list[CatalogEntry],
    show_installed: bool = True,
    verbose: bool = False,
) -> str:
    """Render catalog entries as a human-readable list.

    Args:
        entries: Catalog entries to display.
        show_installed: If False, hide already-installed entries.
        verbose: If True, include tags, homepage, and env vars.

    Returns:
        Formatted string.
    """
    if not show_installed:
        entries = [e for e in entries if not e.installed]

    if not entries:
        return "No catalog entries to show. All available servers may already be installed."

    lines: list[str] = []
    lines.append(f"MCP Server Catalog ({len(entries)} entries)")
    lines.append("=" * 50)

    for entry in entries:
        status = "✓ installed" if entry.installed else "  available"
        lines.append(f"  {status}  {entry.name:<20}  {entry.description}")
        if verbose:
            lines.append(f"             command: {entry.command} {' '.join(entry.args[:3])}")
            if entry.tags:
                lines.append(f"             tags:    {', '.join(entry.tags)}")
            if entry.homepage:
                lines.append(f"             info:    {entry.homepage}")

    lines.append("")
    lines.append("  To add a server: /sync-catalog --add <name>")
    lines.append("  To search:       /sync-catalog --search <query>")
    return "\n".join(lines)


def format_translation_report(equivalents: list[HarnessEquivalent]) -> str:
    """Render a table of harness-native alternatives for configured MCP servers.

    Args:
        equivalents: Suggestions from McpCatalog.suggest_equivalents().

    Returns:
        Formatted string showing each MCP server and its harness-native substitute.
    """
    if not equivalents:
        return (
            "No cross-harness equivalents found for configured MCP servers.\n"
            "All servers are MCP-native with no known built-in alternatives."
        )

    lines: list[str] = []
    lines.append("MCP Server Translation Report")
    lines.append("=" * 60)
    lines.append(
        "For harnesses without MCP support, use these built-in alternatives:"
    )
    lines.append("")

    # Group by harness
    by_harness: dict[str, list[HarnessEquivalent]] = {}
    for eq in equivalents:
        by_harness.setdefault(eq.harness, []).append(eq)

    for harness in sorted(by_harness):
        lines.append(f"  [{harness.upper()}]")
        for eq in by_harness[harness]:
            lines.append(f"    mcp:{eq.mcp_server}")
            lines.append(f"      → {eq.description}")
        lines.append("")

    return "\n".join(lines)
