from __future__ import annotations

"""Shareable config snapshot — export and import Claude Code config as a bundle.

Lets users share their full Claude Code configuration (rules, MCP servers,
settings) as a single compressed JSON blob, exportable to a file, stdout,
or a GitHub Gist URL.

Recipients import with:
    /sync-snapshot import <file-or-url>
    /sync-snapshot import --gist <gist-id>

HarnessSync immediately syncs imported config to all detected harnesses.

Snapshot format (JSON, gzip-compressed + base64 for URL embedding):
    {
        "version": "1",
        "created_at": "2025-03-11T00:00:00Z",
        "creator": "optional label",
        "rules": "...",
        "mcp": {...},
        "settings": {...},
        "skills_manifest": [{"name": "...", "description": "..."}],
        "agents_manifest": [{"name": "...", "description": "..."}]
    }

Note: Skills and agents are manifested (name + description only), not
bundled, to keep snapshot size manageable and avoid bundling credentials
that might be embedded in skill content.
"""

import base64
import gzip
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


_SNAPSHOT_VERSION = "1"
_GIST_API = "https://api.github.com/gists"
_SNAPSHOT_FILENAME = "harnesssync-config.json"


class ConfigSnapshot:
    """Create and restore shareable configuration snapshots.

    Args:
        source_reader: SourceReader instance for reading current config.
                       If None, snapshot import/export works with raw dicts.
    """

    def __init__(self, source_reader=None):
        self.source_reader = source_reader

    # ──────────────────────────────────────────────────────────────────────────
    # Export
    # ──────────────────────────────────────────────────────────────────────────

    def create(self, creator: str = "") -> dict:
        """Build a snapshot dict from current Claude Code config.

        Args:
            creator: Optional label to embed (e.g. "neo@acme").

        Returns:
            Snapshot dict.
        """
        rules = ""
        mcp: dict = {}
        settings: dict = {}
        skills_manifest: list[dict] = []
        agents_manifest: list[dict] = []

        if self.source_reader:
            try:
                rules_list = self.source_reader.get_rules()
                rules = "\n\n".join(r.get("content", "") for r in rules_list)
            except Exception:
                pass

            try:
                mcp = self.source_reader.get_mcp_servers()
                # Strip scoped wrapper if present
                mcp = {
                    name: (cfg["config"] if isinstance(cfg, dict) and "config" in cfg else cfg)
                    for name, cfg in mcp.items()
                }
            except Exception:
                pass

            try:
                settings = self.source_reader.get_settings()
                # Strip sensitive keys
                settings = {
                    k: v for k, v in settings.items()
                    if k not in ("apiKey", "api_key", "token", "secret")
                }
            except Exception:
                pass

            try:
                skills = self.source_reader.get_skills()
                skills_manifest = [
                    {"name": s.get("name", ""), "description": s.get("description", "")}
                    for s in skills
                ]
            except Exception:
                pass

            try:
                agents = self.source_reader.get_agents()
                agents_manifest = [
                    {"name": a.get("name", ""), "description": a.get("description", "")}
                    for a in agents
                ]
            except Exception:
                pass

        snapshot = {
            "version": _SNAPSHOT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "creator": creator,
            "rules": rules,
            "mcp": mcp,
            "settings": settings,
            "skills_manifest": skills_manifest,
            "agents_manifest": agents_manifest,
        }
        return snapshot

    def to_json(self, snapshot: dict) -> str:
        """Serialize snapshot to indented JSON string."""
        return json.dumps(snapshot, indent=2, ensure_ascii=False)

    def to_compressed_b64(self, snapshot: dict) -> str:
        """Compress snapshot JSON and base64-encode it for URL embedding.

        Returns:
            URL-safe base64 string of gzip-compressed JSON.
        """
        raw = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        compressed = gzip.compress(raw, compresslevel=9)
        return base64.urlsafe_b64encode(compressed).decode("ascii")

    def from_compressed_b64(self, encoded: str) -> dict:
        """Decode and decompress a base64-encoded snapshot.

        Args:
            encoded: Output of to_compressed_b64().

        Returns:
            Snapshot dict.

        Raises:
            ValueError: If decoding or decompression fails.
        """
        try:
            compressed = base64.urlsafe_b64decode(encoded + "==")
            raw = gzip.decompress(compressed)
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Invalid snapshot data: {e}") from e

    def export_to_file(self, path: Path, creator: str = "") -> dict:
        """Create snapshot and write it to a file.

        Args:
            path: Output file path.
            creator: Optional creator label.

        Returns:
            The created snapshot dict.
        """
        snapshot = self.create(creator=creator)
        path.write_text(self.to_json(snapshot), encoding="utf-8")
        return snapshot

    def export_to_gist(self, github_token: str, creator: str = "", public: bool = False) -> str:
        """Create snapshot and publish it as a GitHub Gist.

        Args:
            github_token: GitHub personal access token with gist scope.
            creator: Optional creator label.
            public: Whether the gist should be public (default: secret).

        Returns:
            URL of the created Gist.

        Raises:
            RuntimeError: If Gist creation fails.
        """
        snapshot = self.create(creator=creator)
        payload = {
            "description": f"HarnessSync config snapshot — {snapshot['created_at']}",
            "public": public,
            "files": {
                _SNAPSHOT_FILENAME: {
                    "content": self.to_json(snapshot),
                }
            },
        }

        req = urllib.request.Request(
            _GIST_API,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "HarnessSync/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("html_url", data.get("url", ""))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API error {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}") from e

    # ──────────────────────────────────────────────────────────────────────────
    # Import
    # ──────────────────────────────────────────────────────────────────────────

    def load_from_file(self, path: Path) -> dict:
        """Load a snapshot from a JSON file.

        Args:
            path: Path to snapshot file.

        Returns:
            Snapshot dict.

        Raises:
            ValueError: If the file is not a valid snapshot.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in snapshot file: {e}") from e

        self._validate(data)
        return data

    def load_from_gist(self, gist_id_or_url: str) -> dict:
        """Fetch and load a snapshot from a GitHub Gist.

        Args:
            gist_id_or_url: Gist ID (e.g. "abc123") or full gist URL.

        Returns:
            Snapshot dict.

        Raises:
            RuntimeError: If fetching fails.
            ValueError: If the gist doesn't contain a valid snapshot.
        """
        # Extract gist ID from URL if needed
        gist_id = gist_id_or_url
        if "/" in gist_id_or_url:
            gist_id = gist_id_or_url.rstrip("/").split("/")[-1]

        api_url = f"{_GIST_API}/{gist_id}"
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "HarnessSync/1.0",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                gist_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"GitHub API error {e.code} fetching gist {gist_id}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}") from e

        files = gist_data.get("files", {})
        # Find the snapshot file
        snapshot_file = files.get(_SNAPSHOT_FILENAME)
        if not snapshot_file:
            # Try first .json file
            for fname, fdata in files.items():
                if fname.endswith(".json"):
                    snapshot_file = fdata
                    break

        if not snapshot_file:
            raise ValueError(f"No JSON file found in gist {gist_id}")

        content = snapshot_file.get("content", "")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in gist file: {e}") from e

        self._validate(data)
        return data

    def apply_to_claude_md(self, snapshot: dict, target_path: Path, dry_run: bool = False) -> str:
        """Apply the rules section of a snapshot to a CLAUDE.md file.

        Existing content is preserved — the snapshot rules are appended
        in a clearly-marked import block.

        Args:
            snapshot: Snapshot dict.
            target_path: Path to CLAUDE.md.
            dry_run: If True, return the new content without writing.

        Returns:
            The new CLAUDE.md content (whether written or not).
        """
        rules = snapshot.get("rules", "").strip()
        if not rules:
            current = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
            return current

        timestamp = snapshot.get("created_at", "")
        creator = snapshot.get("creator", "")
        label = f" from {creator}" if creator else ""
        header = f"\n\n<!-- Imported{label} via HarnessSync snapshot ({timestamp}) -->\n"
        footer = "\n<!-- End snapshot import -->\n"

        current = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
        new_content = current.rstrip() + header + rules + footer

        if not dry_run:
            target_path.write_text(new_content, encoding="utf-8")

        return new_content

    def format_summary(self, snapshot: dict) -> str:
        """Return a human-readable summary of a snapshot's contents."""
        lines = ["Config Snapshot Summary", "=" * 40]
        lines.append(f"Version:    {snapshot.get('version', '?')}")
        lines.append(f"Created:    {snapshot.get('created_at', 'unknown')}")
        if snapshot.get("creator"):
            lines.append(f"Creator:    {snapshot['creator']}")

        rule_lines = len(snapshot.get("rules", "").splitlines())
        lines.append(f"Rules:      {rule_lines} lines")

        mcp = snapshot.get("mcp", {})
        lines.append(f"MCP:        {len(mcp)} server(s)" + (
            f" ({', '.join(sorted(mcp.keys()))})" if mcp else ""
        ))

        settings = snapshot.get("settings", {})
        lines.append(f"Settings:   {len(settings)} key(s)")

        skills = snapshot.get("skills_manifest", [])
        if skills:
            lines.append(f"Skills:     {len(skills)} (manifest only)")

        agents = snapshot.get("agents_manifest", [])
        if agents:
            lines.append(f"Agents:     {len(agents)} (manifest only)")

        return "\n".join(lines)

    def _validate(self, data: dict) -> None:
        """Raise ValueError if the dict is not a valid snapshot."""
        if not isinstance(data, dict):
            raise ValueError("Snapshot must be a JSON object")
        if data.get("version") != _SNAPSHOT_VERSION:
            version = data.get("version", "missing")
            raise ValueError(
                f"Unsupported snapshot version {version!r} (expected {_SNAPSHOT_VERSION!r})"
            )
