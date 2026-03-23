from __future__ import annotations

"""Per-harness config override manager.

Loads target-specific override files from .harness-sync/overrides/ and merges
them into the base content before each adapter writes.

Override layout:
    .harness-sync/overrides/<target>.md    — appended to Markdown rule content
    .harness-sync/overrides/<target>.json  — deep-merged into JSON settings/MCP

Usage (from orchestrator):
    om = OverrideManager(project_dir)
    merged_rules = om.merge_overrides("cursor", base_rules_text, "md")
    merged_mcp   = om.merge_overrides("cursor", base_mcp_dict, "json")
"""

import json
from pathlib import Path


_OVERRIDE_DIR = ".harness-sync/overrides"
# Secondary lookup: .claude/overrides/<target>.md (Claude Code conventional path)
_OVERRIDE_DIR_CLAUDE = ".claude/overrides"


class OverrideManager:
    """Loads and applies per-harness config overrides.

    Searches two locations in priority order:
      1. .harness-sync/overrides/<target>.{md,json}  (HarnessSync-native)
      2. .claude/overrides/<target>.{md,json}          (Claude Code conventional)
    """

    def __init__(self, project_dir: Path):
        self.overrides_dir = project_dir / _OVERRIDE_DIR
        self._claude_overrides_dir = project_dir / _OVERRIDE_DIR_CLAUDE

    def _locate(self, target: str, suffix: str) -> Path | None:
        """Return the first existing override file for target+suffix, or None."""
        for base in (self.overrides_dir, self._claude_overrides_dir):
            candidate = base / f"{target}{suffix}"
            if candidate.exists():
                return candidate
        return None

    def has_overrides(self, target: str) -> bool:
        """Return True if any override file exists for target."""
        return (
            self._locate(target, ".md") is not None
            or self._locate(target, ".json") is not None
        )

    def load_overrides(self, target: str) -> dict:
        """Return a dict with 'md' and/or 'json' override content for target.

        Keys present only when the corresponding file exists:
            'md'   -> str  (raw Markdown text)
            'json' -> dict (parsed JSON object)
        """
        result: dict = {}
        md_path = self._locate(target, ".md")
        json_path = self._locate(target, ".json")

        if md_path is not None:
            try:
                result["md"] = md_path.read_text(encoding="utf-8")
            except OSError:
                pass

        if json_path is not None:
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    result["json"] = data
            except (OSError, json.JSONDecodeError):
                pass

        return result

    def merge_overrides(self, target: str, base_content, content_type: str = "md"):
        """Merge override content for target into base_content.

        Args:
            target: Harness target name (e.g. 'cursor', 'gemini').
            base_content: str for Markdown, dict for JSON.
            content_type: 'md' or 'json'.

        Returns:
            Merged content of the same type as base_content.
            Returns base_content unchanged if no override exists.
        """
        overrides = self.load_overrides(target)

        if content_type == "md":
            override_text = overrides.get("md", "")
            if not override_text:
                return base_content
            base_str = base_content if isinstance(base_content, str) else ""
            separator = "\n\n" if base_str and not base_str.endswith("\n\n") else ""
            return base_str + separator + override_text

        if content_type == "json":
            override_dict = overrides.get("json", {})
            if not override_dict:
                return base_content
            base_dict = dict(base_content) if isinstance(base_content, dict) else {}
            # Deep merge: override keys win at top level; nested dicts are merged
            for key, value in override_dict.items():
                if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
                    base_dict[key] = {**base_dict[key], **value}
                else:
                    base_dict[key] = value
            return base_dict

        return base_content

    def list_targets_with_overrides(self) -> list[str]:
        """Return sorted list of targets that have override files in either override directory."""
        targets: set[str] = set()
        for base in (self.overrides_dir, self._claude_overrides_dir):
            if not base.exists():
                continue
            for path in base.iterdir():
                if path.suffix in (".md", ".json"):
                    targets.add(path.stem)
        return sorted(targets)

    def show_overrides_summary(self) -> str:
        """Return a human-readable summary of all configured overrides."""
        targets = self.list_targets_with_overrides()
        if not targets:
            return (
                "No per-harness overrides configured.\n"
                "Add files to .claude/overrides/<target>.md or "
                ".harness-sync/overrides/<target>.md to get started."
            )

        lines = ["Per-Harness Overrides", "=" * 40]
        for target in targets:
            overrides = self.load_overrides(target)
            parts = []
            if "md" in overrides:
                line_count = overrides["md"].count("\n") + 1
                parts.append(f"rules ({line_count} lines)")
            if "json" in overrides:
                key_count = len(overrides["json"])
                parts.append(f"settings ({key_count} keys)")
            lines.append(f"  {target:<15} {', '.join(parts)}")
        return "\n".join(lines)
