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
"""

import json
import os
import tempfile
from pathlib import Path


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
