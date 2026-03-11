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
        """Return profile config dict or None if not found."""
        return self._load().get(name)

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

        return result

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
