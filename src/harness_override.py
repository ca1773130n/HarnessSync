from __future__ import annotations

"""Per-harness override layer — supplement synced config with harness-specific extras.

Allows users to define config that is ADDED ON TOP of the synced base for a
specific harness, without breaking the sync relationship. The override layer
never replaces synced content — it augments it.

Override files live at:
    ~/.harnesssync/overrides/<harness>.json

Format:
    {
        "rules": "# Extra rules only for this harness\\n\\n- Always use TypeScript",
        "mcp": {
            "my-internal-tool": {
                "command": "uvx my-internal-mcp",
                "args": ["--profile", "work"]
            }
        },
        "settings": {
            "approval_mode": "suggest"
        },
        "description": "Work-only Codex extras — proprietary MCP + stricter rules"
    }

The orchestrator merges overrides after writing synced content, so:
- Override rules are appended after synced rules (with a section marker)
- Override MCP servers are merged into the synced MCP config
- Override settings are shallow-merged, with overrides winning on conflict

This enables legitimate per-harness customization (different capabilities,
team-specific tools, internal services) without breaking sync purity.
"""

import json
import tempfile
from pathlib import Path


_OVERRIDE_MARKER_START = "\n\n<!-- HarnessSync per-harness override: {harness} -->\n"
_OVERRIDE_MARKER_END = "\n<!-- End HarnessSync override: {harness} -->\n"

_DEFAULT_OVERRIDES_DIR = Path.home() / ".harnesssync" / "overrides"


class HarnessOverride:
    """Per-harness config override manager.

    Args:
        overrides_dir: Directory containing <harness>.json override files.
                       Defaults to ~/.harnesssync/overrides/
    """

    def __init__(self, overrides_dir: Path | None = None):
        self.overrides_dir = overrides_dir or _DEFAULT_OVERRIDES_DIR

    def _override_path(self, harness: str) -> Path:
        return self.overrides_dir / f"{harness}.json"

    def load(self, harness: str) -> dict:
        """Load override config for a harness.

        Args:
            harness: Target harness name (e.g. "codex", "gemini").

        Returns:
            Override dict, or empty dict if no override file exists.
        """
        path = self._override_path(harness)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, harness: str, override: dict) -> None:
        """Save override config for a harness.

        Args:
            harness: Target harness name.
            override: Override dict to persist.
        """
        self.overrides_dir.mkdir(parents=True, exist_ok=True)
        path = self._override_path(harness)

        # Atomic write via temp file
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.overrides_dir,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(override, tmp, indent=2, ensure_ascii=False)
            tmp.write("\n")
            tmp.flush()
            tmp.close()
            Path(tmp.name).replace(path)
        except Exception:
            tmp.close()
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def delete(self, harness: str) -> bool:
        """Remove the override file for a harness.

        Returns:
            True if a file was deleted, False if none existed.
        """
        path = self._override_path(harness)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_overrides(self) -> dict[str, dict]:
        """Return all configured harness overrides as {harness: override_dict}.

        Returns:
            Dict mapping harness name to its override config.
            Empty dict if no overrides directory or no files.
        """
        if not self.overrides_dir.exists():
            return {}
        result = {}
        for path in sorted(self.overrides_dir.glob("*.json")):
            harness = path.stem
            override = self.load(harness)
            if override:
                result[harness] = override
        return result

    def apply_rules_override(self, synced_content: str, harness: str) -> str:
        """Append harness-specific rules to already-synced rules content.

        The override rules are appended in a clearly-marked section so they
        can be identified and removed/replaced on the next sync without
        disturbing the synced base content.

        Args:
            synced_content: The rules content already written by sync.
            harness: Target harness name.

        Returns:
            Content with override rules appended, or original if no override.
        """
        override = self.load(harness)
        extra_rules = override.get("rules", "")
        if not extra_rules or not extra_rules.strip():
            return synced_content

        marker_start = _OVERRIDE_MARKER_START.format(harness=harness)
        marker_end = _OVERRIDE_MARKER_END.format(harness=harness)

        return synced_content + marker_start + extra_rules.strip() + marker_end

    def strip_rules_override(self, content: str, harness: str) -> str:
        """Remove previously-applied override section from rules content.

        Safe to call on content that has no override section.

        Args:
            content: Rules content possibly containing an override section.
            harness: Target harness name.

        Returns:
            Content with the override section removed.
        """
        marker_start = _OVERRIDE_MARKER_START.format(harness=harness)
        marker_end = _OVERRIDE_MARKER_END.format(harness=harness)

        start_idx = content.find(marker_start)
        if start_idx == -1:
            return content

        end_idx = content.find(marker_end, start_idx)
        if end_idx == -1:
            # Malformed — just strip from marker_start to end
            return content[:start_idx].rstrip()

        # Remove from marker_start through the end of marker_end
        return content[:start_idx].rstrip() + content[end_idx + len(marker_end):]

    def apply_mcp_override(self, synced_mcp: dict, harness: str) -> dict:
        """Merge harness-specific MCP servers into synced MCP config.

        Override servers are merged in (override wins on key collision),
        preserving all synced servers not overridden.

        Args:
            synced_mcp: MCP server dict from sync (may be empty).
            harness: Target harness name.

        Returns:
            Merged MCP servers dict.
        """
        override = self.load(harness)
        extra_mcp = override.get("mcp", {})
        if not extra_mcp:
            return synced_mcp

        merged = dict(synced_mcp)
        merged.update(extra_mcp)
        return merged

    def apply_settings_override(self, synced_settings: dict, harness: str) -> dict:
        """Shallow-merge harness-specific settings over synced settings.

        Override values win on conflict. Synced keys not in override are
        preserved unchanged.

        Args:
            synced_settings: Settings dict from sync.
            harness: Target harness name.

        Returns:
            Merged settings dict.
        """
        override = self.load(harness)
        extra_settings = override.get("settings", {})
        if not extra_settings:
            return synced_settings

        merged = dict(synced_settings)
        merged.update(extra_settings)
        return merged

    def set_rules(self, harness: str, rules: str) -> None:
        """Set or replace the rules override for a harness.

        Args:
            harness: Target harness name.
            rules: Markdown rules string to use as override.
        """
        override = self.load(harness)
        override["rules"] = rules
        self.save(harness, override)

    def set_mcp(self, harness: str, server_name: str, config: dict) -> None:
        """Add or update an MCP server in the harness override.

        Args:
            harness: Target harness name.
            server_name: MCP server identifier.
            config: Server config dict.
        """
        override = self.load(harness)
        if "mcp" not in override:
            override["mcp"] = {}
        override["mcp"][server_name] = config
        self.save(harness, override)

    def remove_mcp(self, harness: str, server_name: str) -> bool:
        """Remove a specific MCP server from the harness override.

        Returns:
            True if server was found and removed.
        """
        override = self.load(harness)
        mcp = override.get("mcp", {})
        if server_name not in mcp:
            return False
        del mcp[server_name]
        override["mcp"] = mcp
        self.save(harness, override)
        return True

    def set_description(self, harness: str, description: str) -> None:
        """Set a human-readable description for this override."""
        override = self.load(harness)
        override["description"] = description
        self.save(harness, override)

    def format_summary(self) -> str:
        """Return a formatted summary of all active overrides."""
        overrides = self.list_overrides()
        if not overrides:
            return "No per-harness overrides configured.\n" \
                   f"Override files go in: {self.overrides_dir}/<harness>.json"

        lines = ["Per-Harness Override Summary", "=" * 40]
        for harness, cfg in overrides.items():
            description = cfg.get("description", "")
            lines.append(f"\n{harness}:" + (f" — {description}" if description else ""))

            if "rules" in cfg and cfg["rules"]:
                rule_lines = cfg["rules"].strip().split("\n")
                lines.append(f"  rules: {len(rule_lines)} line(s)")

            mcp = cfg.get("mcp", {})
            if mcp:
                lines.append(f"  mcp: {', '.join(sorted(mcp.keys()))}")

            settings = cfg.get("settings", {})
            if settings:
                lines.append(f"  settings: {', '.join(sorted(settings.keys()))}")

        return "\n".join(lines)
