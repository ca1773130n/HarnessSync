from __future__ import annotations

"""Skill Marketplace — browse and import community skills from GitHub.

Lets users discover skills published by the community (tagged
``harnesssync-skill`` or ``claude-code-skill`` on GitHub), preview them,
and install with one command. After installation, HarnessSync auto-syncs
the new skill to all configured harnesses.

Discovery sources:
  1. GitHub topic search: ``topic:harnesssync-skill``
  2. GitHub topic search: ``topic:claude-code-skill``
  3. A curated registry embedded in this module (offline fallback)

Installation:
  - Clones or downloads the skill to ~/.claude/skills/<skill-name>/
  - Validates SKILL.md exists (or any .md file with frontmatter)
  - Optionally triggers sync immediately

Usage::

    market = SkillMarketplace()
    results = market.search("code review")
    for r in results:
        print(r.format_summary())

    result = market.install("neo/skill-code-review", dest_dir)
    print(result.summary)
"""

import json
import re
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Curated registry (offline fallback)
# ──────────────────────────────────────────────────────────────────────────────

_CURATED_REGISTRY: list[dict] = [
    {
        "name": "code-review",
        "full_name": "harnesssync-community/skill-code-review",
        "description": "Comprehensive code review with security and style checks",
        "stars": 0,
        "topics": ["harnesssync-skill", "code-review"],
        "clone_url": "",
        "html_url": "",
        "source": "curated",
    },
    {
        "name": "tdd",
        "full_name": "harnesssync-community/skill-tdd",
        "description": "Test-driven development workflow for any language",
        "stars": 0,
        "topics": ["harnesssync-skill", "tdd", "testing"],
        "clone_url": "",
        "html_url": "",
        "source": "curated",
    },
    {
        "name": "commit",
        "full_name": "harnesssync-community/skill-commit",
        "description": "Conventional commit message generator",
        "stars": 0,
        "topics": ["harnesssync-skill", "git", "commit"],
        "clone_url": "",
        "html_url": "",
        "source": "curated",
    },
    {
        "name": "debug",
        "full_name": "harnesssync-community/skill-debug",
        "description": "Systematic debugging with hypothesis tracking",
        "stars": 0,
        "topics": ["harnesssync-skill", "debugging"],
        "clone_url": "",
        "html_url": "",
        "source": "curated",
    },
]

# GitHub topics to search for community skills
_SEARCH_TOPICS = ["harnesssync-skill", "claude-code-skill"]

# GitHub API base URL
_GH_API = "https://api.github.com"

# Skill file names to look for when validating an installed skill
_SKILL_FILENAMES = ["SKILL.md", "skill.md", "README.md", "index.md"]

# Request timeout seconds
_TIMEOUT = 8


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MarketplaceEntry:
    """A single skill available in the marketplace."""

    name: str                  # Short skill name (last component of full_name)
    full_name: str             # "owner/repo" GitHub identifier
    description: str
    stars: int
    topics: list[str]
    clone_url: str
    html_url: str
    source: str = "github"    # "github" | "curated"

    def format_summary(self) -> str:
        """Return a one-line summary for display in search results."""
        stars_str = f"★{self.stars}" if self.stars else ""
        source_tag = f"[{self.source}]" if self.source != "github" else ""
        parts = [f"{self.full_name:<40}", self.description[:60]]
        if stars_str:
            parts.append(stars_str)
        if source_tag:
            parts.append(source_tag)
        return "  ".join(p for p in parts if p)

    def format_detail(self) -> str:
        """Return a multi-line detail block."""
        lines = [
            f"Skill:        {self.full_name}",
            f"Description:  {self.description}",
            f"Stars:        {self.stars}",
        ]
        if self.topics:
            lines.append(f"Topics:       {', '.join(self.topics)}")
        if self.html_url:
            lines.append(f"URL:          {self.html_url}")
        return "\n".join(lines)


@dataclass
class InstallResult:
    """Result of a skill installation."""

    skill_name: str
    dest_path: Path | None
    success: bool
    error: str = ""
    skill_file: str = ""       # SKILL.md or similar found in the install dir

    @property
    def summary(self) -> str:
        if self.success:
            return (
                f"Installed '{self.skill_name}' → {self.dest_path}\n"
                f"  Skill file: {self.skill_file or '(none found)'}\n"
                "  Run /sync to propagate to all harnesses."
            )
        return f"Install failed for '{self.skill_name}': {self.error}"


# ──────────────────────────────────────────────────────────────────────────────
# Marketplace class
# ──────────────────────────────────────────────────────────────────────────────

class SkillMarketplace:
    """Browse and install community skills.

    Args:
        skills_dir: Directory where skills are installed.
                    Defaults to ~/.claude/skills/.
        github_token: Optional GitHub personal access token for higher rate limits.
    """

    def __init__(
        self,
        skills_dir: Path | None = None,
        github_token: str = "",
    ):
        self.skills_dir = skills_dir or (Path.home() / ".claude" / "skills")
        self._token = github_token

    # ──────────────────────────────────────────────────────────────────────────
    # Search
    # ──────────────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str = "",
        max_results: int = 20,
        use_github: bool = True,
    ) -> list[MarketplaceEntry]:
        """Search for community skills.

        Args:
            query: Free-text query to filter results (name / description).
            max_results: Maximum entries to return.
            use_github: Whether to query GitHub API (requires network).
                        Falls back to curated registry when False or on error.

        Returns:
            List of MarketplaceEntry sorted by relevance (stars desc).
        """
        entries: list[MarketplaceEntry] = []

        if use_github:
            for topic in _SEARCH_TOPICS:
                try:
                    topic_results = self._search_github_topic(topic, per_page=50)
                    entries.extend(topic_results)
                except Exception:
                    pass  # network unavailable — fall back to curated

        # Deduplicate by full_name
        seen: set[str] = set()
        deduped: list[MarketplaceEntry] = []
        for e in entries:
            if e.full_name not in seen:
                seen.add(e.full_name)
                deduped.append(e)

        # Always include curated entries that aren't already present
        for raw in _CURATED_REGISTRY:
            if raw["full_name"] not in seen:
                deduped.append(_raw_to_entry(raw))

        # Filter by query
        if query:
            q_lower = query.lower()
            deduped = [
                e for e in deduped
                if q_lower in e.name.lower()
                or q_lower in e.description.lower()
                or any(q_lower in t for t in e.topics)
            ]

        # Sort: github entries by stars desc, curated last
        deduped.sort(key=lambda e: (e.source == "curated", -e.stars))

        return deduped[:max_results]

    def list_installed(self) -> list[str]:
        """Return names of skills currently installed in skills_dir.

        Returns:
            Sorted list of skill directory names.
        """
        if not self.skills_dir.is_dir():
            return []
        return sorted(
            p.name for p in self.skills_dir.iterdir()
            if p.is_dir() and not p.name.startswith(".")
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Install
    # ──────────────────────────────────────────────────────────────────────────

    def install(
        self,
        repo: str,
        skill_name: str | None = None,
        overwrite: bool = False,
    ) -> InstallResult:
        """Install a skill from a GitHub repository.

        Args:
            repo: GitHub "owner/repo" identifier or a full HTTPS clone URL.
            skill_name: Local directory name for the skill.
                        Defaults to the last path component of repo.
            overwrite: Replace an existing installation if True.

        Returns:
            InstallResult with success status and destination path.
        """
        # Normalise repo → clone URL
        clone_url = _repo_to_clone_url(repo)
        if skill_name is None:
            skill_name = _repo_to_name(repo)

        dest = self.skills_dir / skill_name

        if dest.exists():
            if not overwrite:
                return InstallResult(
                    skill_name=skill_name,
                    dest_path=dest,
                    success=False,
                    error=(
                        f"Skill '{skill_name}' is already installed at {dest}. "
                        "Pass overwrite=True to replace."
                    ),
                )
            shutil.rmtree(dest)

        # Attempt git clone
        result = self._git_clone(clone_url, dest)
        if not result.success:
            return result

        # Validate skill file exists
        skill_file = _find_skill_file(dest)
        return InstallResult(
            skill_name=skill_name,
            dest_path=dest,
            success=True,
            skill_file=skill_file,
        )

    def uninstall(self, skill_name: str) -> bool:
        """Remove an installed skill directory.

        Args:
            skill_name: Name of the skill directory to remove.

        Returns:
            True if removed, False if it didn't exist.
        """
        dest = self.skills_dir / skill_name
        if not dest.exists():
            return False
        shutil.rmtree(dest)
        return True

    def format_search_results(self, results: list[MarketplaceEntry]) -> str:
        """Format a list of search results for terminal display.

        Args:
            results: List from search().

        Returns:
            Formatted string ready to print.
        """
        if not results:
            return "No skills found."
        lines = [f"Found {len(results)} skill(s):\n"]
        for i, entry in enumerate(results, 1):
            lines.append(f"  {i:2}. {entry.format_summary()}")
        lines.append(
            "\nInstall with: /sync-marketplace install <owner/repo>"
        )
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _search_github_topic(
        self, topic: str, per_page: int = 30
    ) -> list[MarketplaceEntry]:
        """Query GitHub Search API for repos with a given topic."""
        params = urllib.parse.urlencode({
            "q": f"topic:{topic}",
            "per_page": per_page,
            "sort": "stars",
            "order": "desc",
        })
        url = f"{_GH_API}/search/repositories?{params}"
        data = self._gh_get(url)
        entries: list[MarketplaceEntry] = []
        for item in data.get("items", []):
            entries.append(MarketplaceEntry(
                name=item.get("name", ""),
                full_name=item.get("full_name", ""),
                description=item.get("description", "") or "",
                stars=item.get("stargazers_count", 0),
                topics=item.get("topics", []),
                clone_url=item.get("clone_url", ""),
                html_url=item.get("html_url", ""),
                source="github",
            ))
        return entries

    def _gh_get(self, url: str) -> dict:
        """Perform a GitHub API GET request and return parsed JSON."""
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError):
            return {}

    def _git_clone(self, clone_url: str, dest: Path) -> InstallResult:
        """Clone a git repository to dest.

        Returns InstallResult with success=True on success.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            result = subprocess.run(
                ["git", "clone", "--depth=1", "--quiet", clone_url, str(dest)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
            return InstallResult(
                skill_name=dest.name,
                dest_path=None,
                success=False,
                error=f"git clone failed: {exc}",
            )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "unknown error"
            return InstallResult(
                skill_name=dest.name,
                dest_path=None,
                success=False,
                error=f"git clone exited {result.returncode}: {error_msg}",
            )

        return InstallResult(
            skill_name=dest.name,
            dest_path=dest,
            success=True,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Free helpers
# ──────────────────────────────────────────────────────────────────────────────

def _raw_to_entry(raw: dict) -> MarketplaceEntry:
    """Convert a raw registry dict to MarketplaceEntry."""
    return MarketplaceEntry(
        name=raw.get("name", ""),
        full_name=raw.get("full_name", ""),
        description=raw.get("description", ""),
        stars=raw.get("stars", 0),
        topics=raw.get("topics", []),
        clone_url=raw.get("clone_url", ""),
        html_url=raw.get("html_url", ""),
        source=raw.get("source", "github"),
    )


def _repo_to_clone_url(repo: str) -> str:
    """Convert 'owner/repo' or a full URL to a clone URL."""
    if repo.startswith("https://") or repo.startswith("git@"):
        return repo
    return f"https://github.com/{repo}.git"


def _repo_to_name(repo: str) -> str:
    """Derive a skill directory name from a repo identifier."""
    # Strip trailing .git
    repo = re.sub(r"\.git$", "", repo)
    # Take last path component
    name = repo.rstrip("/").split("/")[-1]
    # Strip common prefixes: skill-, harnesssync-skill-, claude-skill-
    name = re.sub(r"^(harnesssync-skill-|claude-skill-|skill-)", "", name)
    return name or repo


def _find_skill_file(skill_dir: Path) -> str:
    """Return the first skill description file found in skill_dir."""
    for fname in _SKILL_FILENAMES:
        candidate = skill_dir / fname
        if candidate.is_file():
            return fname
    # Try any .md file
    for p in skill_dir.glob("*.md"):
        return p.name
    return ""


# ---------------------------------------------------------------------------
# Item 22 — Community Adapter Registry
# ---------------------------------------------------------------------------
# Lets users publish and install adapters for harnesses not officially
# supported by HarnessSync. Someone builds a Continue.dev adapter, publishes
# it tagged "harnesssync-adapter", and everyone benefits.

_ADAPTER_TOPIC = "harnesssync-adapter"
_ADAPTER_SEARCH_URL = (
    "https://api.github.com/search/repositories"
    f"?q=topic:{_ADAPTER_TOPIC}&sort=stars&order=desc&per_page=30"
)

# Curated offline fallback for community adapters
_CURATED_ADAPTERS: list[dict] = [
    {
        "name": "continue-adapter",
        "full_name": "harnesssync-community/adapter-continue",
        "description": "HarnessSync adapter for Continue.dev — syncs rules and skills to .continue/",
        "harness": "continue",
        "stars": 0,
        "topics": [_ADAPTER_TOPIC, "continue-dev"],
        "clone_url": "",
        "html_url": "",
        "source": "curated",
    },
    {
        "name": "zed-adapter",
        "full_name": "harnesssync-community/adapter-zed",
        "description": "HarnessSync adapter for Zed editor AI — syncs rules to .rules",
        "harness": "zed",
        "stars": 0,
        "topics": [_ADAPTER_TOPIC, "zed-editor"],
        "clone_url": "",
        "html_url": "",
        "source": "curated",
    },
]


@dataclass
class AdapterEntry:
    """A community adapter listed in the registry."""

    name: str
    full_name: str
    description: str
    harness: str        # Target harness this adapter supports
    stars: int = 0
    topics: list[str] = None
    clone_url: str = ""
    html_url: str = ""
    source: str = "github"

    def __post_init__(self) -> None:
        if self.topics is None:
            self.topics = []

    def format_summary(self) -> str:
        """Return a one-line summary for display."""
        return (
            f"{self.name:<30}  harness={self.harness:<12}  ★{self.stars:<5}  "
            f"{self.description[:60]}"
        )


@dataclass
class AdapterInstallResult:
    """Result of installing a community adapter."""

    adapter_name: str
    harness: str
    success: bool
    adapter_dir: Path | None = None
    error: str = ""
    summary: str = ""


class CommunityAdapterRegistry:
    """Browse and install community-published HarnessSync adapters.

    Community members publish adapters by creating a GitHub repo tagged with
    ``harnesssync-adapter``. Each adapter repo contains:
    - ``adapter.py``: The adapter class implementing AdapterBase.
    - ``adapter.json``: Metadata (harness name, version, description).
    - ``README.md``: Usage instructions.

    Once installed, the adapter is registered with the AdapterRegistry and
    becomes available as a sync target.

    Args:
        adapters_dir: Directory to install community adapters into.
                      Defaults to ~/.harnesssync/community-adapters/
        github_token: Optional GitHub API token for higher rate limits.
    """

    def __init__(
        self,
        adapters_dir: Path | None = None,
        github_token: str | None = None,
    ) -> None:
        self._adapters_dir = adapters_dir or (
            Path.home() / ".harnesssync" / "community-adapters"
        )
        self._github_token = github_token or os.environ.get("GITHUB_TOKEN", "")

    def search(self, query: str = "", harness: str = "") -> list[AdapterEntry]:
        """Search the community adapter registry.

        Queries GitHub for repos tagged ``harnesssync-adapter``, then filters
        by ``query`` (keyword in name/description) and/or ``harness`` name.
        Falls back to the curated built-in list when GitHub is unreachable.

        Args:
            query: Keyword to filter by (matched against name and description).
            harness: Target harness name to filter by (e.g. "continue").

        Returns:
            List of AdapterEntry results sorted by stars descending.
        """
        entries = self._fetch_from_github() or self._curated_entries()

        if query:
            q = query.lower()
            entries = [
                e for e in entries
                if q in e.name.lower() or q in e.description.lower()
            ]
        if harness:
            entries = [e for e in entries if e.harness == harness]

        return sorted(entries, key=lambda e: e.stars, reverse=True)

    def _fetch_from_github(self) -> list[AdapterEntry] | None:
        """Fetch adapter entries from GitHub topic search. Returns None on failure."""
        headers = {"Accept": "application/vnd.github.v3+json"}
        if self._github_token:
            headers["Authorization"] = f"token {self._github_token}"
        try:
            req = urllib.request.Request(_ADAPTER_SEARCH_URL, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

        entries: list[AdapterEntry] = []
        for item in data.get("items", []):
            # Infer harness from topics or description
            topics = item.get("topics", [])
            harness = ""
            for t in topics:
                if t.startswith("adapter-") and t != _ADAPTER_TOPIC:
                    harness = t[len("adapter-"):]
                    break
            if not harness:
                # Try to infer from description
                desc = (item.get("description") or "").lower()
                for h in ("codex", "gemini", "cursor", "windsurf", "aider",
                          "continue", "zed", "neovim", "cline", "opencode"):
                    if h in desc:
                        harness = h
                        break

            entries.append(AdapterEntry(
                name=_repo_to_name(item.get("full_name", "")),
                full_name=item.get("full_name", ""),
                description=item.get("description") or "",
                harness=harness,
                stars=item.get("stargazers_count", 0),
                topics=topics,
                clone_url=item.get("clone_url", ""),
                html_url=item.get("html_url", ""),
                source="github",
            ))
        return entries

    def _curated_entries(self) -> list[AdapterEntry]:
        """Return the built-in curated adapter list."""
        return [
            AdapterEntry(**{k: v for k, v in a.items()})
            for a in _CURATED_ADAPTERS
        ]

    def install(self, repo: str, harness: str = "") -> AdapterInstallResult:
        """Install a community adapter from GitHub.

        Clones the adapter repository into the community adapters directory
        and validates that it contains an ``adapter.py`` module. The adapter
        is NOT automatically registered — users must call ``/sync-registry add``
        to activate it, giving them a chance to review the code first.

        Args:
            repo: GitHub repo in ``owner/name`` format, or a full HTTPS/SSH URL.
            harness: Target harness name (used for the install directory name).
                     Inferred from adapter.json if empty.

        Returns:
            AdapterInstallResult with success status and install path.
        """
        clone_url = _repo_to_clone_url(repo)
        adapter_name = _repo_to_name(repo)
        dest = self._adapters_dir / adapter_name

        if dest.exists():
            return AdapterInstallResult(
                adapter_name=adapter_name,
                harness=harness,
                success=False,
                error=f"Adapter already installed at {dest}. Remove it first to reinstall.",
            )

        try:
            self._adapters_dir.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["git", "clone", "--depth=1", clone_url, str(dest)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return AdapterInstallResult(
                    adapter_name=adapter_name,
                    harness=harness,
                    success=False,
                    error=f"git clone failed: {result.stderr.strip()[:200]}",
                )
        except FileNotFoundError:
            return AdapterInstallResult(
                adapter_name=adapter_name,
                harness=harness,
                success=False,
                error="git not found on PATH. Install git to use the adapter registry.",
            )
        except Exception as exc:
            return AdapterInstallResult(
                adapter_name=adapter_name,
                harness=harness,
                success=False,
                error=str(exc),
            )

        # Validate adapter.py exists
        if not (dest / "adapter.py").exists():
            return AdapterInstallResult(
                adapter_name=adapter_name,
                harness=harness,
                success=False,
                adapter_dir=dest,
                error=(
                    f"Repository cloned to {dest} but adapter.py was not found. "
                    "This may not be a valid HarnessSync adapter."
                ),
            )

        # Read metadata from adapter.json if present
        meta_path = dest / "adapter.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                harness = harness or meta.get("harness", adapter_name)
            except (json.JSONDecodeError, OSError):
                pass

        return AdapterInstallResult(
            adapter_name=adapter_name,
            harness=harness,
            success=True,
            adapter_dir=dest,
            summary=(
                f"Adapter '{adapter_name}' installed to {dest}.\n"
                "Review adapter.py before activating. "
                "Run /sync-registry add {adapter_name} to register it."
            ),
        )

    def list_installed(self) -> list[dict]:
        """List locally installed community adapters.

        Returns:
            List of dicts with keys: name, harness, path, has_adapter_py,
            has_metadata.
        """
        if not self._adapters_dir.is_dir():
            return []
        result: list[dict] = []
        for d in self._adapters_dir.iterdir():
            if not d.is_dir():
                continue
            meta: dict = {"harness": "unknown", "description": ""}
            meta_path = d / "adapter.json"
            if meta_path.exists():
                try:
                    loaded = json.loads(meta_path.read_text(encoding="utf-8"))
                    meta.update(loaded)
                except (json.JSONDecodeError, OSError):
                    pass
            result.append({
                "name": d.name,
                "harness": meta.get("harness", "unknown"),
                "description": meta.get("description", ""),
                "path": str(d),
                "has_adapter_py": (d / "adapter.py").is_file(),
                "has_metadata": meta_path.exists(),
            })
        return sorted(result, key=lambda x: x["name"])

    def format_search_results(self, entries: list[AdapterEntry]) -> str:
        """Format adapter search results for display.

        Args:
            entries: List of AdapterEntry from search().

        Returns:
            Formatted multi-line results string.
        """
        if not entries:
            return (
                "No community adapters found.\n"
                f"Publish your own by tagging a GitHub repo with '{_ADAPTER_TOPIC}'."
            )
        lines = [f"Community Adapters ({len(entries)} found)", "=" * 60]
        for entry in entries:
            lines.append(f"\n  {entry.format_summary()}")
            if entry.html_url:
                lines.append(f"  {entry.html_url}")
        lines.append("")
        lines.append(
            f"Install: /sync-registry install <owner/repo>\n"
            f"Publish: tag your adapter repo with '{_ADAPTER_TOPIC}' on GitHub"
        )
        return "\n".join(lines)
