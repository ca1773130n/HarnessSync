from __future__ import annotations

"""
Declarative harnesssync.toml config loader.

A single ``harnesssync.toml`` at the project root captures all sync policy
in one reviewable, version-controllable file.  This complements the existing
``.harnesssync`` JSON format — both are supported and merged at load time,
with TOML taking precedence on any key it defines.

TOML schema::

    [sync]
    targets = ["codex", "gemini", "cursor"]     # which harnesses to sync to
    sections = ["rules", "skills", "mcp"]        # which sections to include
    exclude_sections = ["settings"]              # sections to skip
    dry_run = false                              # default dry-run mode

    [targets.codex]
    enabled = true
    only_sections = ["rules", "mcp"]

    [targets.cursor]
    enabled = true
    exclude_sections = ["settings"]

    [profile]
    active = "work"                              # active named profile

    [ignore]
    rules = ["experimental-*", "wip-*"]         # rule name patterns to exclude
    skills = ["draft-*"]                         # skill name patterns to exclude

Merging with existing .harnesssync JSON:
    loader = HarnessSyncToml.load(project_dir)
    policy = loader.to_policy_dict()

Usage::

    from src.harnesssync_toml import HarnessSyncToml

    cfg = HarnessSyncToml.load(project_dir)
    if cfg.has_toml:
        policy = cfg.to_policy_dict()
        targets = policy.get("only_targets", [])
"""

import json
import re
from pathlib import Path
from typing import Any


TOML_FILE = "harnesssync.toml"
JSON_FILE = ".harnesssync"


class HarnessSyncToml:
    """Load and merge harnesssync.toml + .harnesssync JSON into a unified policy dict.

    Attributes:
        has_toml: True if a harnesssync.toml file was found and loaded.
        has_json: True if a .harnesssync JSON file was found and loaded.
    """

    def __init__(
        self,
        toml_data: dict,
        json_data: dict,
        toml_path: Path | None = None,
        json_path: Path | None = None,
    ):
        self._toml = toml_data
        self._json = json_data
        self.toml_path = toml_path
        self.json_path = json_path
        self.has_toml = bool(toml_data)
        self.has_json = bool(json_data)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, project_dir: Path) -> "HarnessSyncToml":
        """Load harnesssync.toml and .harnesssync from project_dir.

        Both files are optional.  If neither exists, returns an instance with
        empty data.  If both exist, TOML settings take precedence.

        Args:
            project_dir: Project root directory.

        Returns:
            HarnessSyncToml instance.
        """
        project_dir = Path(project_dir)
        toml_path = project_dir / TOML_FILE
        json_path = project_dir / JSON_FILE

        toml_data = cls._load_toml(toml_path)
        json_data = cls._load_json(json_path)

        return cls(
            toml_data=toml_data,
            json_data=json_data,
            toml_path=toml_path if toml_path.exists() else None,
            json_path=json_path if json_path.exists() else None,
        )

    @classmethod
    def _load_toml(cls, path: Path) -> dict:
        """Load TOML file using stdlib tomllib (Python 3.11+) or fallback parser."""
        if not path.is_file():
            return {}
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return {}

        # Try stdlib tomllib (Python 3.11+)
        try:
            import tomllib  # type: ignore[import]
            return tomllib.loads(text)
        except ImportError:
            pass

        # Try tomli backport
        try:
            import tomli  # type: ignore[import]
            return tomli.loads(text)
        except ImportError:
            pass

        # Fallback: minimal TOML parser for simple key=value and [section] syntax
        return cls._minimal_toml_parse(text)

    @classmethod
    def _load_json(cls, path: Path) -> dict:
        """Load .harnesssync JSON file."""
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @classmethod
    def _minimal_toml_parse(cls, text: str) -> dict:
        """Minimal TOML parser for simple cases (no stdlib tomllib available).

        Handles:
        - [section] and [section.subsection] headers
        - key = "string" / key = ["list", "items"] / key = true/false/integer
        - # comments
        - Inline arrays of strings

        Does NOT handle: multi-line strings, inline tables, datetime, nested arrays.
        """
        result: dict[str, Any] = {}
        current_section: list[str] = []

        string_re = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_-]*)\s*=\s*"([^"]*)"')
        bool_re = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_-]*)\s*=\s*(true|false)\s*$')
        int_re = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_-]*)\s*=\s*(-?\d+)\s*$')
        array_re = re.compile(r'^([a-zA-Z_][a-zA-Z0-9_-]*)\s*=\s*\[([^\]]*)\]')
        section_re = re.compile(r'^\[([^\]]+)\]')

        def _set_nested(d: dict, keys: list[str], value: Any) -> None:
            for k in keys[:-1]:
                d = d.setdefault(k, {})
            d[keys[-1]] = value

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Section header
            sec_m = section_re.match(line)
            if sec_m:
                current_section = [s.strip() for s in sec_m.group(1).split(".")]
                # Ensure the section path exists in result
                d = result
                for k in current_section:
                    d = d.setdefault(k, {})
                continue

            # Key = value
            m: re.Match | None
            if m := string_re.match(line):
                _set_nested(result, current_section + [m.group(1)], m.group(2))
            elif m := bool_re.match(line):
                _set_nested(result, current_section + [m.group(1)], m.group(2) == "true")
            elif m := int_re.match(line):
                _set_nested(result, current_section + [m.group(1)], int(m.group(2)))
            elif m := array_re.match(line):
                raw_items = m.group(2)
                # Parse list of quoted strings
                items = re.findall(r'"([^"]*)"', raw_items)
                _set_nested(result, current_section + [m.group(1)], items)

        return result

    # ------------------------------------------------------------------
    # Policy extraction
    # ------------------------------------------------------------------

    def to_policy_dict(self) -> dict:
        """Merge TOML and JSON config into a unified sync policy dict.

        Returns a dict compatible with the existing .harnesssync JSON format,
        suitable for passing to SyncOrchestrator or other consumers.

        TOML values take precedence over JSON values for overlapping keys.

        Returns:
            Dict with policy keys:
              - only_targets: list of harness names to sync to (or [] for all)
              - exclude_targets: list of harnesses to skip
              - only_sections: list of section names to include (or [] for all)
              - exclude_sections: list of sections to skip
              - dry_run: bool
              - profile: str | None
              - ignore_rules: list of rule name glob patterns
              - ignore_skills: list of skill name glob patterns
              - target_overrides: per-target config overrides (from [targets.*])
        """
        policy: dict = {}

        # Start with JSON data (lower priority)
        policy.update({k: v for k, v in self._json.items() if not k.startswith("_")})

        # Apply TOML [sync] section
        sync_section = self._toml.get("sync", {})
        if isinstance(sync_section, dict):
            if "targets" in sync_section:
                policy["only_targets"] = sync_section["targets"]
            if "sections" in sync_section:
                policy["only_sections"] = sync_section["sections"]
            if "exclude_sections" in sync_section:
                policy["exclude_sections"] = sync_section["exclude_sections"]
            if "dry_run" in sync_section:
                policy["dry_run"] = sync_section["dry_run"]

        # Apply TOML [profile] section
        profile_section = self._toml.get("profile", {})
        if isinstance(profile_section, dict) and "active" in profile_section:
            policy["profile"] = profile_section["active"]

        # Apply TOML [ignore] section
        ignore_section = self._toml.get("ignore", {})
        if isinstance(ignore_section, dict):
            if "rules" in ignore_section:
                policy["ignore_rules"] = ignore_section["rules"]
            if "skills" in ignore_section:
                policy["ignore_skills"] = ignore_section["skills"]

        # Apply TOML [targets.*] per-target overrides
        targets_section = self._toml.get("targets", {})
        if isinstance(targets_section, dict):
            overrides: dict[str, dict] = {}
            for target_name, target_cfg in targets_section.items():
                if isinstance(target_cfg, dict):
                    overrides[target_name] = target_cfg
            if overrides:
                policy["target_overrides"] = overrides

        return policy

    def describe(self) -> str:
        """Return a human-readable summary of the loaded config."""
        parts: list[str] = []
        if self.has_toml:
            parts.append(f"harnesssync.toml loaded from {self.toml_path}")
        if self.has_json:
            parts.append(f".harnesssync JSON loaded from {self.json_path}")
        if not parts:
            parts.append("No harnesssync config files found (using defaults)")

        policy = self.to_policy_dict()
        if policy.get("only_targets"):
            parts.append(f"  Targets: {', '.join(policy['only_targets'])}")
        if policy.get("only_sections"):
            parts.append(f"  Sections: {', '.join(policy['only_sections'])}")
        if policy.get("exclude_sections"):
            parts.append(f"  Excluded sections: {', '.join(policy['exclude_sections'])}")
        if policy.get("profile"):
            parts.append(f"  Active profile: {policy['profile']}")
        return "\n".join(parts)

    @staticmethod
    def write_template(project_dir: Path, targets: list[str] | None = None) -> Path:
        """Write a commented harnesssync.toml template to project_dir.

        Args:
            project_dir: Project root where the file will be written.
            targets: List of active target names to pre-populate, or None for all.

        Returns:
            Path to the written file.

        Raises:
            OSError: If the file cannot be written.
        """
        targets_line = (
            f'targets = {json.dumps(targets)}'
            if targets
            else '# targets = ["codex", "gemini", "cursor"]  # omit to sync all'
        )

        template = f"""\
# harnesssync.toml — HarnessSync declarative configuration
# Version-control this file to share sync policy with your team.
# See: https://github.com/your-org/harnesssync for full schema.

[sync]
# Which harnesses to sync to (comment out to sync all detected harnesses)
{targets_line}

# Which config sections to include (comment out to sync all sections)
# sections = ["rules", "skills", "mcp"]

# Sections to exclude from sync
# exclude_sections = ["settings"]

# Enable dry-run by default (show diffs without writing)
# dry_run = false

[profile]
# Active named sync profile (defined via /sync-setup --profile)
# active = "work"

[ignore]
# Rule name glob patterns to exclude from sync (like .gitignore)
# rules = ["experimental-*", "wip-*", "*.draft"]

# Skill name glob patterns to exclude from sync
# skills = ["draft-*"]

# Per-target overrides (optional — customize sync per harness)
# [targets.codex]
# enabled = true
# only_sections = ["rules", "mcp"]

# [targets.cursor]
# enabled = true
# exclude_sections = ["settings"]
"""
        path = Path(project_dir) / TOML_FILE
        path.write_text(template, encoding="utf-8")
        return path
