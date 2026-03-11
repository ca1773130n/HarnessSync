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
