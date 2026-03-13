from __future__ import annotations

"""Named sync profile manager.

Profiles are named sets of sync options stored at ~/.harnesssync/profiles.json.
Activate with /sync --profile <name>. Each profile can specify:
- scope: "user" | "project" | "all"
- only_sections: list of section names to sync
- skip_sections: list of section names to skip
- targets: list of specific targets to sync (empty = all)
- description: human-readable description

Example profile:
    {
        "work": {
            "description": "Work machine — stable skills only, no experimental MCPs",
            "scope": "all",
            "skip_sections": ["mcp"],
            "targets": ["codex", "gemini"]
        },
        "minimal": {
            "description": "Minimal sync — rules only",
            "scope": "all",
            "only_sections": ["rules"]
        }
    }

Team Sync via Git (item 2):
Teams can commit a shared profile to their repository under
``.harness-sync/team-profile.json``. When teammates clone or pull,
``ProfileManager.load_from_repo()`` imports the shared profile so that
org-wide harness standards apply automatically without manual config.

Export:
    manager.export_to_repo(project_dir, profile_name="team")

Import (run after git pull):
    imported = manager.load_from_repo(project_dir)
"""

import json
import os
import tempfile
from pathlib import Path


# Repo-committed shared profile path (relative to project root)
_REPO_PROFILE_PATH = ".harness-sync/team-profile.json"


class ProfileManager:
    """Manage named sync profiles stored as JSON.

    Profiles are stored at ~/.harnesssync/profiles.json and can be
    activated with /sync --profile <name>.
    """

    VALID_SECTIONS = {"rules", "skills", "agents", "commands", "mcp", "settings"}

    # Top-level profile fields recognized by apply_to_kwargs()
    VALID_PROFILE_KEYS = {
        "description", "scope", "only_sections", "skip_sections", "targets",
        "mcp_servers", "account", "harness_env", "extends",
    }

    def __init__(self, config_dir: Path = None):
        self.config_dir = config_dir or (Path.home() / ".harnesssync")
        self._profiles_path = self.config_dir / "profiles.json"

    def _load(self) -> dict:
        if not self._profiles_path.exists():
            return {}
        try:
            data = json.loads(self._profiles_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, profiles: dict) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temp_fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.config_dir,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(profiles, temp_fd, indent=2, ensure_ascii=False)
            temp_fd.write("\n")
            temp_fd.flush()
            os.fsync(temp_fd.fileno())
            temp_fd.close()
            os.replace(temp_fd.name, str(self._profiles_path))
        except Exception:
            temp_fd.close()
            try:
                os.unlink(temp_fd.name)
            except OSError:
                pass
            raise

    def list_profiles(self) -> list[str]:
        """Return sorted list of profile names."""
        return sorted(self._load().keys())

    def get_profile(self, name: str) -> dict | None:
        """Return profile config dict or None if not found.

        Supports profile inheritance via the ``extends`` key.  A profile with
        ``"extends": "base-profile"`` inherits all keys from the named base
        profile, with the child's keys taking precedence.  Inheritance is
        resolved recursively up to a depth of 5 to prevent cycles.

        Example::

            {
              "base": {"scope": "all", "targets": ["codex", "gemini"]},
              "work": {"extends": "base", "skip_sections": ["mcp"]}
            }

        ``work`` inherits ``scope`` and ``targets`` from ``base`` and adds
        its own ``skip_sections`` override.
        """
        profiles = self._load()
        return self._resolve_profile(name, profiles, depth=0)

    def _resolve_profile(
        self,
        name: str,
        profiles: dict,
        depth: int,
    ) -> dict | None:
        """Recursively resolve profile inheritance.

        Args:
            name: Profile name to resolve.
            profiles: Full profiles dict (from _load()).
            depth: Current recursion depth (guard against cycles).

        Returns:
            Merged profile dict, or None if the name is not found.
        """
        raw = profiles.get(name)
        if raw is None or not isinstance(raw, dict):
            return None

        parent_name = raw.get("extends")
        if not parent_name or depth >= 5:
            # No parent or cycle guard hit — return as-is (strip meta key)
            result = {k: v for k, v in raw.items() if k != "extends"}
            return result

        parent = self._resolve_profile(parent_name, profiles, depth + 1)
        if parent is None:
            # Parent doesn't exist — return child as-is
            return {k: v for k, v in raw.items() if k != "extends"}

        # Merge: parent provides defaults, child overrides
        merged = dict(parent)
        for k, v in raw.items():
            if k == "extends":
                continue
            merged[k] = v

        return merged

    def save_profile(self, name: str, config: dict) -> None:
        """Create or update a named profile.

        Args:
            name: Profile name (alphanumeric + hyphens/underscores)
            config: Profile config dict with keys: description, scope,
                    only_sections, skip_sections, targets
        """
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"Invalid profile name: {name!r}. Use alphanumeric/hyphen/underscore.")
        profiles = self._load()
        profiles[name] = config
        self._save(profiles)

    def delete_profile(self, name: str) -> bool:
        """Delete a profile. Returns True if deleted, False if not found."""
        profiles = self._load()
        if name not in profiles:
            return False
        del profiles[name]
        self._save(profiles)
        return True

    def apply_to_kwargs(self, name: str, base_kwargs: dict) -> dict:
        """Merge profile settings into orchestrator keyword arguments.

        Args:
            name: Profile name to load
            base_kwargs: Base keyword arguments dict (modified in-place copy)

        Returns:
            Updated kwargs dict with profile settings applied.

        Raises:
            KeyError: If profile not found
        """
        profile = self.get_profile(name)
        if profile is None:
            raise KeyError(f"Profile {name!r} not found. Run /sync --profile-list to see available profiles.")

        result = dict(base_kwargs)

        if "scope" in profile:
            result["scope"] = profile["scope"]

        only = profile.get("only_sections", [])
        if only:
            result["only_sections"] = set(only) & self.VALID_SECTIONS

        skip = profile.get("skip_sections", [])
        if skip:
            result["skip_sections"] = set(skip) & self.VALID_SECTIONS

        # targets filtering is communicated via special key; orchestrator
        # reads it to restrict which adapters run
        if "targets" in profile and profile["targets"]:
            result["profile_targets"] = list(profile["targets"])

        # MCP server subset: only sync specific named MCP servers.
        # Allows profiles to define "work" (only internal tools) vs "oss"
        # (only public servers) without requiring separate CLAUDE.md files.
        if "mcp_servers" in profile and profile["mcp_servers"]:
            result["profile_mcp_servers"] = list(profile["mcp_servers"])

        # Credential account: use a named Claude Code account (multi-account setup).
        # Allows consultants/developers with work/personal separation to switch accounts
        # per project by activating the appropriate named profile.
        if "account" in profile and profile["account"]:
            result["account"] = profile["account"]

        # Harness environment override: select which env-tagged rules to include.
        # Profiles can pin rules to a specific environment (e.g., "production", "dev").
        if "harness_env" in profile and profile["harness_env"]:
            result["harness_env"] = profile["harness_env"]

        return result

    def filter_mcp_servers(self, mcp_servers: dict, name: str) -> dict:
        """Filter an MCP servers dict to only include servers listed in a profile.

        If the profile has no ``mcp_servers`` key (or an empty list), the full
        dict is returned unchanged — this is an opt-in filter.

        Args:
            mcp_servers: Dict mapping server name → server config.
            name: Profile name to read the ``mcp_servers`` allowlist from.

        Returns:
            Filtered dict (subset of mcp_servers), or original if no filter.
        """
        profile = self.get_profile(name)
        if profile is None:
            return mcp_servers

        allowlist = profile.get("mcp_servers", [])
        if not allowlist:
            return mcp_servers

        allowed_set = set(allowlist)
        return {k: v for k, v in mcp_servers.items() if k in allowed_set}

    # ------------------------------------------------------------------
    # Team Sync via Git
    # ------------------------------------------------------------------

    def export_to_repo(
        self,
        project_dir: Path,
        profile_name: str = "team",
        overwrite: bool = True,
    ) -> Path:
        """Export a named profile to the repository for team sharing.

        Writes the profile to ``.harness-sync/team-profile.json`` in the
        project root. Teams commit this file so teammates automatically
        inherit org-wide HarnessSync standards on clone/pull.

        Args:
            project_dir: Project root directory.
            profile_name: Name of the local profile to export (default: "team").
            overwrite: If False, raise if the repo profile already exists.

        Returns:
            Path to the exported file.

        Raises:
            KeyError: If profile_name is not found.
            FileExistsError: If file exists and overwrite=False.
        """
        profile = self.get_profile(profile_name)
        if profile is None:
            raise KeyError(
                f"Profile {profile_name!r} not found. "
                f"Available: {', '.join(self.list_profiles()) or 'none'}"
            )

        dest = project_dir / _REPO_PROFILE_PATH
        if dest.exists() and not overwrite:
            raise FileExistsError(
                f"{dest} already exists. Pass overwrite=True to replace it."
            )

        dest.parent.mkdir(parents=True, exist_ok=True)

        export_data = {
            "_harnesssync_team_profile": True,
            "_exported_from": profile_name,
            "_export_note": (
                "This file is managed by HarnessSync. "
                "Import with: /sync --import-team-profile or ProfileManager.load_from_repo()"
            ),
            **profile,
        }

        dest.write_text(
            json.dumps(export_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return dest

    def load_from_repo(
        self,
        project_dir: Path,
        import_as: str = "team",
        overwrite: bool = True,
    ) -> dict | None:
        """Import the team profile from the repository into local profiles.

        Reads ``.harness-sync/team-profile.json`` and saves it as a local
        profile so it can be activated with /sync --profile team.

        Call this after ``git clone`` or ``git pull`` to pick up org-wide
        HarnessSync standards automatically.

        Args:
            project_dir: Project root directory.
            import_as: Local profile name to save the imported profile as.
            overwrite: If False, skip import if a local profile with import_as exists.

        Returns:
            Imported profile dict, or None if no repo profile found.
        """
        repo_file = project_dir / _REPO_PROFILE_PATH
        if not repo_file.exists():
            return None

        try:
            data = json.loads(repo_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        if not isinstance(data, dict):
            return None

        if not overwrite and self.get_profile(import_as) is not None:
            return None

        # Strip internal metadata keys before saving
        profile = {k: v for k, v in data.items() if not k.startswith("_")}
        if not profile:
            return None

        # Ensure description notes the team origin
        if "description" not in profile:
            profile["description"] = f"Team profile (imported from {_REPO_PROFILE_PATH})"

        self.save_profile(import_as, profile)
        return profile

    def fetch_from_url(
        self,
        url: str,
        import_as: str = "team",
        overwrite: bool = True,
        timeout: float = 10.0,
    ) -> dict | None:
        """Fetch a team profile from a URL (git raw, S3, internal server).

        Allows teams to publish a canonical HarnessSync profile to a shared
        git repo or URL. Team members run this to pull the org profile so
        their local harnesses stay aligned with team standards.

        Supports:
          - https://raw.githubusercontent.com/org/repo/main/.harness-sync/team-profile.json
          - Any URL returning a valid profile JSON

        Args:
            url: URL returning a HarnessSync profile JSON.
            import_as: Local profile name to save the fetched profile as.
            overwrite: If False, skip import if a local profile with import_as exists.
            timeout: HTTP request timeout in seconds.

        Returns:
            Imported profile dict, or None on failure.

        Raises:
            ValueError: If URL response is not valid JSON or not a valid profile.
        """
        import urllib.request
        import urllib.error

        if not overwrite and self.get_profile(import_as) is not None:
            return None

        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "HarnessSync/1.0"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.URLError as e:
            raise ValueError(f"Failed to fetch profile from {url}: {e}") from e

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise ValueError(f"URL did not return valid JSON: {e}") from e

        if not isinstance(data, dict):
            raise ValueError("Fetched profile must be a JSON object")

        # Strip internal metadata keys
        profile = {k: v for k, v in data.items() if not k.startswith("_")}
        if not profile:
            raise ValueError("Fetched JSON has no profile keys")

        if "description" not in profile:
            profile["description"] = f"Team profile (fetched from {url})"

        self.save_profile(import_as, profile)
        return profile

    # ------------------------------------------------------------------
    # Built-in Project-Type Templates
    # ------------------------------------------------------------------

    # Pre-built sync profiles for common project archetypes.
    # Reduces the blank-page problem for new users.
    _BUILTIN_TEMPLATES: dict[str, dict] = {
        "python-api": {
            "description": "Python API project — rules + MCP, skip heavy agents",
            "scope": "all",
            "only_sections": ["rules", "mcp", "settings"],
            "targets": ["codex", "cursor", "cline"],
        },
        "react-spa": {
            "description": "React SPA — rules + skills for frontend work",
            "scope": "all",
            "only_sections": ["rules", "skills"],
            "targets": ["cursor", "windsurf", "cline"],
        },
        "go-cli": {
            "description": "Go CLI project — minimal rules sync, no MCP overhead",
            "scope": "all",
            "only_sections": ["rules"],
            "targets": ["codex", "aider", "cursor"],
        },
        "rust-crate": {
            "description": "Rust crate — rules only, no MCP (cargo handles deps)",
            "scope": "all",
            "only_sections": ["rules"],
            "targets": ["cursor", "zed", "neovim"],
        },
        "minimal": {
            "description": "Minimal sync — rules only, all targets",
            "scope": "all",
            "only_sections": ["rules"],
        },
        "full": {
            "description": "Full sync — all sections, all targets",
            "scope": "all",
        },
        "team-shared": {
            "description": "Team-standard sync — rules + MCP, skip personal skills",
            "scope": "all",
            "only_sections": ["rules", "mcp"],
        },
        "work-mcp-only": {
            "description": "Work context — sync only internal/work MCP servers",
            "scope": "all",
            "only_sections": ["rules", "mcp"],
            # mcp_servers is intentionally empty here (template — fill in your servers)
            # Example: "mcp_servers": ["internal-jira", "company-github"]
            # Set "account": "work" to use a dedicated work Claude Code account
        },
        "oss-mcp-only": {
            "description": "OSS context — sync only public/open-source MCP servers",
            "scope": "all",
            "only_sections": ["rules", "mcp"],
            # Example: "mcp_servers": ["context7", "github-public", "brave-search"]
            # Set "account": "personal" to use a personal Claude Code account
        },
        "consultant-client": {
            "description": "Client project — dedicated account + rules only, no personal MCPs",
            "scope": "project",
            "only_sections": ["rules"],
            # Set "account": "<client-account-name>" and "targets" to client-approved harnesses
        },
        "data-science": {
            "description": "Data science / ML project — Jupyter-aware MCP, Python tools, skip frontend skills",
            "scope": "all",
            "only_sections": ["rules", "mcp", "settings"],
            "targets": ["cursor", "continue", "cline"],
            # MCP suggestion: jupyter, pandas-mcp, filesystem for notebook access
            # Note: skip codex/aider (no notebook support)
        },
        "backend": {
            "description": "Backend service — rules + MCP (DB, APIs), skip frontend-specific skills",
            "scope": "all",
            "only_sections": ["rules", "mcp", "settings"],
            "targets": ["codex", "cursor", "opencode", "cline"],
        },
        "frontend": {
            "description": "Frontend / UI project — rules + skills for component/CSS workflows, skip DB MCPs",
            "scope": "all",
            "only_sections": ["rules", "skills"],
            "targets": ["cursor", "windsurf", "cline", "continue"],
        },
        "devops": {
            "description": "DevOps / infra project — rules + MCP for cloud/docker/k8s, minimal skills",
            "scope": "all",
            "only_sections": ["rules", "mcp"],
            "targets": ["codex", "cursor", "opencode"],
        },
    }

    def list_templates(self) -> list[str]:
        """Return sorted list of built-in template names."""
        return sorted(self._BUILTIN_TEMPLATES.keys())

    def get_template(self, name: str) -> dict | None:
        """Return a built-in template config dict, or None if not found."""
        return self._BUILTIN_TEMPLATES.get(name)

    def apply_template(self, name: str, save_as: str = None) -> dict:
        """Apply a built-in template (optionally saving it as a profile).

        Args:
            name: Template name (from list_templates()).
            save_as: If provided, save the template as a local profile with this name.

        Returns:
            Template config dict.

        Raises:
            KeyError: If template not found.
        """
        template = self.get_template(name)
        if template is None:
            available = ", ".join(self.list_templates())
            raise KeyError(
                f"Template {name!r} not found. Available: {available}"
            )
        if save_as:
            self.save_profile(save_as, dict(template))
        return dict(template)

    def format_templates(self) -> str:
        """Return a human-readable list of built-in templates."""
        lines = ["Built-in Sync Templates", "=" * 40]
        lines.append("Use with: /sync --profile <name> (after applying template)\n")
        for name, cfg in sorted(self._BUILTIN_TEMPLATES.items()):
            desc = cfg.get("description", "")
            only = cfg.get("only_sections", [])
            targets = cfg.get("targets", [])
            lines.append(f"  {name}")
            if desc:
                lines.append(f"    {desc}")
            if only:
                lines.append(f"    sections: {', '.join(only)}")
            if targets:
                lines.append(f"    targets: {', '.join(targets)}")
            lines.append("")
        return "\n".join(lines)

    def format_list(self) -> str:
        """Return a human-readable profile list for display."""
        profiles = self._load()
        if not profiles:
            return "No profiles configured. Create one with /sync --profile-save <name>."

        lines = ["Sync Profiles", "=" * 40]
        for name, cfg in sorted(profiles.items()):
            desc = cfg.get("description", "")
            scope = cfg.get("scope", "all")
            only = cfg.get("only_sections", [])
            skip = cfg.get("skip_sections", [])
            targets = cfg.get("targets", [])

            lines.append(f"\n  {name}")
            if desc:
                lines.append(f"    {desc}")
            lines.append(f"    scope: {scope}")
            if only:
                lines.append(f"    only: {', '.join(only)}")
            if skip:
                lines.append(f"    skip: {', '.join(skip)}")
            if targets:
                lines.append(f"    targets: {', '.join(targets)}")
            mcp_servers = cfg.get("mcp_servers", [])
            if mcp_servers:
                lines.append(f"    mcp-servers: {', '.join(mcp_servers)}")
            account = cfg.get("account", "")
            if account:
                lines.append(f"    account: {account}")
            harness_env = cfg.get("harness_env", "")
            if harness_env:
                lines.append(f"    harness-env: {harness_env}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # GitHub Gist Export / Import
    # ------------------------------------------------------------------

    def export_to_gist(
        self,
        profile_name: str = "team",
        description: str = "HarnessSync team profile",
        public: bool = False,
        github_token: str | None = None,
    ) -> str:
        """Export a named profile to a GitHub Gist and return the Gist URL.

        Enables one-command team config sharing: export a profile once, then
        teammates run ``ProfileManager().import_from_gist(url)`` to pull it.

        Args:
            profile_name: Local profile name to export.
            description: Gist description shown on GitHub.
            public: If True, create a public Gist (default: secret Gist).
            github_token: GitHub personal access token with ``gist`` scope.
                          Reads from the GITHUB_TOKEN env var if not provided.

        Returns:
            HTTPS URL of the created Gist.

        Raises:
            ValueError: If the profile doesn't exist or the token is missing.
            RuntimeError: If the Gist API call fails.
        """
        import urllib.request
        import urllib.error

        profile = self.get_profile(profile_name)
        if profile is None:
            available = ", ".join(self.list_profiles())
            raise ValueError(
                f"Profile {profile_name!r} not found. Available: {available or 'none'}"
            )

        token = github_token or os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise ValueError(
                "GitHub token required. Set GITHUB_TOKEN env var or pass github_token."
            )

        export_data = {
            "_harnesssync_version": 1,
            "_exported_profile": profile_name,
            **profile,
        }
        file_content = json.dumps(export_data, indent=2, ensure_ascii=False) + "\n"

        payload = json.dumps({
            "description": description,
            "public": public,
            "files": {
                "harnesssync-profile.json": {"content": file_content},
            },
        }).encode("utf-8")

        req = urllib.request.Request(
            "https://api.github.com/gists",
            data=payload,
            headers={
                "Authorization": f"token {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "User-Agent": "HarnessSync/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API error {e.code}: {err_body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error creating Gist: {e}") from e

        html_url: str = body.get("html_url", "")
        raw_url: str = ""
        files = body.get("files", {})
        if "harnesssync-profile.json" in files:
            raw_url = files["harnesssync-profile.json"].get("raw_url", "")

        # Store the raw URL in the profile metadata for easy re-import
        profile["_gist_url"] = raw_url or html_url
        self.save_profile(profile_name, profile)

        return html_url

    def import_from_gist(
        self,
        gist_url: str,
        import_as: str = "team",
        overwrite: bool = True,
        github_token: str | None = None,
    ) -> dict:
        """Import a HarnessSync profile from a GitHub Gist URL.

        Accepts both the Gist HTML URL (https://gist.github.com/user/ID) and
        a raw file URL. The profile is saved locally under ``import_as``.

        Args:
            gist_url: GitHub Gist URL or raw file URL.
            import_as: Local profile name to save the fetched profile as.
            overwrite: If False, raise ValueError if profile already exists.
            github_token: Optional GitHub token (increases rate limit for private Gists).

        Returns:
            Imported profile dict.

        Raises:
            ValueError: If the URL format is invalid or profile already exists (when not overwriting).
            RuntimeError: If fetching fails.
        """
        import urllib.request
        import urllib.error
        import re

        if not overwrite and self.get_profile(import_as) is not None:
            raise ValueError(
                f"Profile {import_as!r} already exists. Pass overwrite=True to replace it."
            )

        # Convert Gist HTML URL → raw API URL
        # https://gist.github.com/USER/GIST_ID → https://api.github.com/gists/GIST_ID
        api_url = gist_url
        gist_id_match = re.search(r"gist\.github\.com/[^/]+/([a-f0-9]+)", gist_url)
        if gist_id_match:
            gist_id = gist_id_match.group(1)
            api_url = f"https://api.github.com/gists/{gist_id}"

        headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "HarnessSync/1.0",
        }
        token = github_token or os.environ.get("GITHUB_TOKEN", "")
        if token:
            headers["Authorization"] = f"token {token}"

        req = urllib.request.Request(api_url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API error {e.code}: {err_body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error fetching Gist: {e}") from e

        # If we got an API response, extract the file content
        if isinstance(body, dict) and "files" in body:
            files = body["files"]
            profile_file = files.get("harnesssync-profile.json")
            if not profile_file:
                # Fallback: grab the first JSON file
                for fname, fdata in files.items():
                    if fname.endswith(".json"):
                        profile_file = fdata
                        break
            if not profile_file:
                raise ValueError("Gist has no harnesssync-profile.json file")

            content = profile_file.get("content") or ""
            if not content:
                # Need to fetch raw_url
                raw_url = profile_file.get("raw_url", "")
                if raw_url:
                    raw_req = urllib.request.Request(raw_url, headers=headers, method="GET")
                    with urllib.request.urlopen(raw_req, timeout=15) as raw_resp:
                        content = raw_resp.read().decode("utf-8")
        else:
            # Assume body IS the profile JSON (raw URL was given)
            content = json.dumps(body)

        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Gist content is not valid JSON: {e}") from e

        # Strip internal metadata keys
        profile = {k: v for k, v in data.items() if not k.startswith("_")}
        if not profile:
            raise ValueError("Gist profile has no usable keys")

        if "description" not in profile:
            profile["description"] = f"Imported from Gist: {gist_url}"

        self.save_profile(import_as, profile)
        return profile

    # ------------------------------------------------------------------
    # CWD-based auto-activation (Item 26 — Project-Scoped Sync Profiles)
    # ------------------------------------------------------------------

    def auto_activate_from_cwd(
        self,
        cwd: Path | None = None,
    ) -> str | None:
        """Return the profile name that should activate for the given directory.

        Users can attach a profile to one or more path prefixes in a special
        ``__cwd_rules__`` entry inside ``profiles.json``::

            {
              "__cwd_rules__": [
                {"path_prefix": "/work/acme", "profile": "work"},
                {"path_prefix": "/home/user/personal", "profile": "minimal"}
              ],
              "work": { ... },
              "minimal": { ... }
            }

        The *longest matching* prefix wins, so
        ``/work/acme/projectA`` matches the ``work`` rule even if a shorter
        ``/work`` rule also exists.

        Args:
            cwd: Directory to test (defaults to current working directory).

        Returns:
            Profile name to activate, or ``None`` if no rule matches.
        """
        resolve_cwd = (cwd or Path.cwd()).resolve()
        profiles = self._load()
        rules = profiles.get("__cwd_rules__", [])
        if not isinstance(rules, list):
            return None

        best_match: str | None = None
        best_len = -1

        for rule in rules:
            if not isinstance(rule, dict):
                continue
            prefix_str = rule.get("path_prefix", "")
            profile_name = rule.get("profile", "")
            if not prefix_str or not profile_name:
                continue
            try:
                prefix = Path(prefix_str).expanduser().resolve()
            except (OSError, ValueError):
                continue

            # Check if cwd is inside this prefix
            try:
                resolve_cwd.relative_to(prefix)
            except ValueError:
                continue  # Not a match

            prefix_len = len(str(prefix))
            if prefix_len > best_len:
                best_len = prefix_len
                best_match = profile_name

        return best_match

    def add_cwd_rule(self, path_prefix: str, profile_name: str) -> None:
        """Associate a directory prefix with a profile for auto-activation.

        Args:
            path_prefix: Absolute directory path (or prefix) to match.
                         Tilde (~) is supported.
            profile_name: Profile to activate when CWD is inside this prefix.

        Raises:
            ValueError: If profile_name does not exist in the profiles store.
        """
        profiles = self._load()
        if profile_name not in profiles and profile_name != "__cwd_rules__":
            raise ValueError(f"Profile {profile_name!r} does not exist")

        rules: list[dict] = []
        existing = profiles.get("__cwd_rules__", [])
        if isinstance(existing, list):
            rules = list(existing)

        # Remove any existing rule for this prefix before re-adding
        rules = [
            r for r in rules
            if not (isinstance(r, dict) and r.get("path_prefix") == path_prefix)
        ]
        rules.append({"path_prefix": path_prefix, "profile": profile_name})
        profiles["__cwd_rules__"] = rules
        self._save(profiles)

    def remove_cwd_rule(self, path_prefix: str) -> bool:
        """Remove the CWD rule for a given path prefix.

        Args:
            path_prefix: The path prefix to remove.

        Returns:
            True if a rule was removed, False if no matching rule was found.
        """
        profiles = self._load()
        rules = profiles.get("__cwd_rules__", [])
        if not isinstance(rules, list):
            return False

        new_rules = [
            r for r in rules
            if not (isinstance(r, dict) and r.get("path_prefix") == path_prefix)
        ]
        if len(new_rules) == len(rules):
            return False  # Nothing removed

        profiles["__cwd_rules__"] = new_rules
        self._save(profiles)
        return True


# ---------------------------------------------------------------------------
# Per-project sync profiles (item 4)
# ---------------------------------------------------------------------------

_PROJECT_PROFILE_FILE = ".harnesssync.json"


def load_project_profile(project_dir: "Path") -> dict | None:
    """Load a per-project sync profile from ``<project_dir>/.harnesssync.json``.

    Teams can commit a ``.harnesssync.json`` at the repo root to enforce
    org-wide sync settings (e.g., skip MCP servers, restrict to certain
    targets) for everyone who clones the repo.

    The file supports the same keys as a named profile::

        {
            "description": "Work repo — no experimental MCPs",
            "skip_sections": ["mcp"],
            "targets": ["codex", "gemini"],
            "extends": "base"
        }

    Args:
        project_dir: Root directory of the project (where ``.harnesssync.json``
                     lives).

    Returns:
        Profile dict, or ``None`` if the file does not exist or is invalid JSON.
    """
    from pathlib import Path as _Path

    profile_path = _Path(project_dir) / _PROJECT_PROFILE_FILE
    if not profile_path.exists():
        return None
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def save_project_profile(project_dir: "Path", profile: dict) -> None:
    """Write a per-project sync profile to ``<project_dir>/.harnesssync.json``.

    Overwrites any existing ``.harnesssync.json`` in the project directory.

    Args:
        project_dir: Root directory of the project.
        profile: Profile dict (same schema as named profiles in ``ProfileManager``).

    Raises:
        OSError: If the file cannot be written.
        ValueError: If ``profile`` is not a dict.
    """
    import os as _os
    import tempfile as _tempfile
    from pathlib import Path as _Path

    if not isinstance(profile, dict):
        raise ValueError("profile must be a dict")

    profile_path = _Path(project_dir) / _PROJECT_PROFILE_FILE
    tmp_fd = _tempfile.NamedTemporaryFile(
        mode="w",
        dir=str(profile_path.parent),
        suffix=".tmp",
        delete=False,
        encoding="utf-8",
    )
    try:
        json.dump(profile, tmp_fd, indent=2, ensure_ascii=False)
        tmp_fd.write("\n")
        tmp_fd.flush()
        _os.fsync(tmp_fd.fileno())
        tmp_fd.close()
        _os.replace(tmp_fd.name, str(profile_path))
    except Exception:
        tmp_fd.close()
        try:
            _os.unlink(tmp_fd.name)
        except OSError:
            pass
        raise


def merge_project_profile(
    named_profile: dict | None,
    project_profile: dict | None,
) -> dict:
    """Merge a named profile with a per-project profile override.

    Project profile keys take precedence over named profile keys.
    Both may be ``None``; an empty dict is returned when both are absent.

    Args:
        named_profile: Profile from ``ProfileManager.get_profile()`` (or None).
        project_profile: Profile from ``load_project_profile()`` (or None).

    Returns:
        Merged profile dict.
    """
    result: dict = {}
    if named_profile:
        result.update(named_profile)
    if project_profile:
        result.update(project_profile)
    return result
