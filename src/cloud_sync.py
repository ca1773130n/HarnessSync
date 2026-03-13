from __future__ import annotations

"""Multi-Machine Config Sync via GitHub Gist (item 22).

Sync your Claude Code config across machines using a GitHub Gist as the
backend. Machine A pushes; Machine B pulls. Works across home/work/cloud
dev environments.

Usage::

    syncer = GistCloudSync(token="ghp_...")
    gist_id = syncer.push(project_dir)          # First machine: publish
    syncer.pull(project_dir, gist_id=gist_id)    # Other machines: fetch

The Gist contains one file per config artifact:
  - CLAUDE.md
  - harnesssync_profile.json  (active profile)
  - mcp_servers.json          (MCP server list)
  - harness_versions.json     (version pins)

Security note: the Gist should be *secret* (not public). Secret Gists are
not indexed by search engines but are accessible to anyone with the URL.
For sensitive configs use a private GitHub repo backend instead.

Team sharing (item 2):
    Export your entire harness configuration as a shareable Gist URL.
    Teammates run one command to bootstrap their setup:
        /sync-setup --from-gist https://gist.github.com/user/abc123
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


# Files included in the Gist sync bundle
_BUNDLE_FILES = [
    "CLAUDE.md",
    "AGENTS.md",
    ".harnesssync",
]

_GIST_API = "https://api.github.com/gists"


@dataclass
class GistSyncResult:
    """Result of a Gist push or pull operation."""

    success: bool
    gist_id: str = ""
    gist_url: str = ""
    files_synced: list[str] = field(default_factory=list)
    files_skipped: list[str] = field(default_factory=list)
    error: str = ""

    def format(self) -> str:
        lines = ["Gist Cloud Sync", "=" * 40]
        lines.append(f"Status:   {'OK' if self.success else 'FAILED'}")
        if self.gist_id:
            lines.append(f"Gist ID:  {self.gist_id}")
        if self.gist_url:
            lines.append(f"URL:      {self.gist_url}")
        if self.files_synced:
            lines.append(f"Synced:   {', '.join(self.files_synced)}")
        if self.files_skipped:
            lines.append(f"Skipped:  {', '.join(self.files_skipped)}")
        if self.error:
            lines.append(f"Error:    {self.error}")
        return "\n".join(lines)


class GistCloudSync:
    """Push and pull HarnessSync configs via GitHub Gist.

    Args:
        token: GitHub personal access token with ``gist`` scope.
        description: Gist description (shown on gist.github.com).
        public: If False (default), create a secret Gist.
    """

    def __init__(
        self,
        token: str,
        description: str = "HarnessSync config bundle",
        public: bool = False,
    ):
        self.token = token
        self.description = description
        self.public = public

    # ──────────────────────────────────────────────────────────────────────────
    # Push
    # ──────────────────────────────────────────────────────────────────────────

    def push(
        self,
        project_dir: Path,
        gist_id: str | None = None,
        extra_files: dict[str, str] | None = None,
    ) -> GistSyncResult:
        """Push config files to a GitHub Gist.

        Creates a new Gist if ``gist_id`` is None; updates an existing Gist
        otherwise.

        Args:
            project_dir: Project root containing config files.
            gist_id: Existing Gist ID to update (None to create new).
            extra_files: Additional filename → content pairs to include.

        Returns:
            GistSyncResult with the Gist ID and URL.
        """
        gist_files: dict[str, dict[str, str]] = {}

        for rel in _BUNDLE_FILES:
            path = project_dir / rel
            if path.exists():
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")
                    # Gist filenames cannot contain path separators — flatten
                    filename = rel.replace("/", "_").lstrip(".")
                    if not filename:
                        filename = rel
                    gist_files[filename] = {"content": content}
                except OSError:
                    pass

        if extra_files:
            for fname, content in extra_files.items():
                gist_files[fname] = {"content": content}

        if not gist_files:
            return GistSyncResult(
                success=False,
                error="No config files found to push",
            )

        payload = {
            "description": self.description,
            "public": self.public,
            "files": gist_files,
        }

        try:
            if gist_id:
                response_data = self._api_request(
                    "PATCH", f"{_GIST_API}/{gist_id}", payload
                )
            else:
                response_data = self._api_request("POST", _GIST_API, payload)
        except Exception as exc:
            return GistSyncResult(success=False, error=str(exc))

        return GistSyncResult(
            success=True,
            gist_id=response_data.get("id", ""),
            gist_url=response_data.get("html_url", ""),
            files_synced=list(gist_files.keys()),
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Pull
    # ──────────────────────────────────────────────────────────────────────────

    def pull(
        self,
        project_dir: Path,
        gist_id: str,
        overwrite: bool = True,
    ) -> GistSyncResult:
        """Pull config files from a GitHub Gist into project_dir.

        Args:
            project_dir: Project root to write config files into.
            gist_id: Gist ID to fetch from.
            overwrite: If True (default), overwrite existing local files.

        Returns:
            GistSyncResult listing synced/skipped files.
        """
        try:
            gist_data = self._api_request("GET", f"{_GIST_API}/{gist_id}", None)
        except Exception as exc:
            return GistSyncResult(success=False, error=str(exc))

        files = gist_data.get("files", {})
        synced: list[str] = []
        skipped: list[str] = []

        for filename, file_info in files.items():
            content = file_info.get("content", "")
            # Reverse flatten: restore path separators
            dest_rel = filename.replace("_", "/") if filename.startswith(".") else filename
            # CLAUDE_md → CLAUDE.md
            if dest_rel.endswith("_md"):
                dest_rel = dest_rel[:-3] + ".md"
            dest_path = project_dir / dest_rel

            if dest_path.exists() and not overwrite:
                skipped.append(filename)
                continue

            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                dest_path.write_text(content, encoding="utf-8")
                synced.append(filename)
            except OSError as exc:
                skipped.append(f"{filename} (error: {exc})")

        return GistSyncResult(
            success=True,
            gist_id=gist_id,
            gist_url=gist_data.get("html_url", ""),
            files_synced=synced,
            files_skipped=skipped,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _api_request(
        self, method: str, url: str, payload: dict | None
    ) -> dict:
        """Make an authenticated GitHub API request.

        Args:
            method: HTTP method (GET, POST, PATCH).
            url: Full API URL.
            payload: Request body (JSON-serialised). None for GET.

        Returns:
            Parsed JSON response dict.

        Raises:
            RuntimeError: On HTTP error or JSON parse failure.
        """
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "User-Agent": "HarnessSync/1.0",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"GitHub API error {exc.code} for {method} {url}: {body[:200]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error: {exc.reason}") from exc

    def get_gist_url(self, gist_id: str) -> str:
        """Return the public URL for a Gist ID."""
        return f"https://gist.github.com/{gist_id}"


def parse_gist_id_from_url(url: str) -> str | None:
    """Extract the Gist ID from a github.com/gist URL.

    Args:
        url: e.g. "https://gist.github.com/username/abc123def456"

    Returns:
        Gist ID string, or None if not parseable.
    """
    import re

    m = re.search(r"gist\.github\.com/(?:[^/]+/)?([a-f0-9]{20,})", url)
    if m:
        return m.group(1)
    # Bare ID
    if re.match(r"^[a-f0-9]{20,}$", url):
        return url
    return None


def build_shareable_bundle(
    project_dir: Path,
    profile_name: str | None = None,
) -> dict[str, str]:
    """Build a dict of filename → content for a shareable config bundle.

    Suitable for passing to GistCloudSync.push(extra_files=...) or for
    storing in any key-value backend.

    Args:
        project_dir: Project root.
        profile_name: If provided, include the named profile from profiles.json.

    Returns:
        Dict of filename → content strings.
    """
    bundle: dict[str, str] = {}

    for rel in _BUNDLE_FILES:
        path = project_dir / rel
        if path.exists():
            try:
                bundle[rel] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

    if profile_name:
        from src.profile_manager import ProfileManager

        mgr = ProfileManager()
        profile = mgr.get_profile(profile_name)
        if profile:
            bundle["harnesssync_profile.json"] = json.dumps(
                {profile_name: profile}, indent=2
            )

    return bundle
