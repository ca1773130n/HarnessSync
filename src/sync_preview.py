from __future__ import annotations

"""Dry-run preview and current-state reading for sync operations.

Generates unified diffs showing what a sync would change without writing
any files. Also provides methods to read current target state from disk
for comparison. Extracted from SyncOrchestrator.
"""

import json
from pathlib import Path

from src.diff_formatter import DiffFormatter


class SyncPreviewGenerator:
    """Generates diff previews for dry-run sync operations.

    Reads current target files from disk to produce real unified diffs,
    showing exactly what will change. Falls back to showing new content
    if the target file doesn't exist yet.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def preview_sync(self, adapter, source_data: dict) -> dict:
        """Generate diff preview without writing files.

        Args:
            adapter: Target adapter instance
            source_data: Source configuration data

        Returns:
            Dict with 'preview' key containing formatted diff output
        """
        df = DiffFormatter()
        target = adapter.target_name

        # --- Rules diff: read existing rules file ---
        rules = source_data.get('rules', '')
        if rules:
            new_rules_str = (
                "\n\n".join(r.get('content', '') for r in rules if isinstance(r, dict))
                if isinstance(rules, list)
                else str(rules)
            )
            # Determine current rules file path per target
            rules_file = self.get_target_rules_path(adapter)
            df.add_file_diff(f"{target}/rules", rules_file, new_rules_str)

        # --- Skills diff: compare current vs new skill names ---
        skills = source_data.get('skills', {})
        if skills:
            current_skills = self.get_current_skills(adapter)
            df.add_structural_diff(
                f"{target}/skills",
                current_skills,
                {name: str(path) for name, path in skills.items()}
            )

        # --- Agents diff ---
        agents = source_data.get('agents', {})
        if agents:
            current_agents = self.get_current_agents(adapter)
            df.add_structural_diff(
                f"{target}/agents",
                current_agents,
                {name: str(path) for name, path in agents.items()}
            )

        # --- Commands diff ---
        commands = source_data.get('commands', {})
        if commands:
            current_commands = self.get_current_commands(adapter)
            df.add_structural_diff(
                f"{target}/commands",
                current_commands,
                {name: str(path) for name, path in commands.items()}
            )

        # --- MCP diff: compare current vs new MCP server keys ---
        mcp = source_data.get('mcp', {})
        if mcp:
            current_mcp = self.get_current_mcp(adapter)
            df.add_structural_diff(f"{target}/mcp", current_mcp, mcp)

        # --- Settings diff: read current settings JSON ---
        settings = source_data.get('settings', {})
        if settings:
            current_settings = self.get_current_settings(adapter)
            df.add_structural_diff(f"{target}/settings", current_settings, settings)

        return {"preview": df.format_output(), "is_preview": True}

    def get_target_rules_path(self, adapter) -> Path | None:
        """Return the path of the rules file for a given adapter, or None."""
        # Each adapter exposes a known path attribute
        for attr in ("agents_md_path", "gemini_md_path", "rules_path"):
            p = getattr(adapter, attr, None)
            if p is not None:
                return p
        # Fallback: guess from target_name
        target = adapter.target_name
        rules_filenames = {
            "codex": "AGENTS.md",
            "gemini": "GEMINI.md",
            "opencode": "OPENCODE.md",
            "cursor": ".cursor/rules/harnesssync.mdc",
            "aider": "CONVENTIONS.md",
            "windsurf": ".windsurfrules",
            "cline": ".clinerules",
            "continue": ".continue/rules/harnesssync.md",
            "zed": ".zed/system-prompt.md",
            "neovim": ".avante/system-prompt.md",
        }
        fname = rules_filenames.get(target)
        if fname:
            return self.project_dir / fname
        return None

    def get_current_skills(self, adapter) -> dict:
        """Read current skill names from adapter's skill output directory."""
        skills_dir = getattr(adapter, 'skills_dir', None)
        if skills_dir is None:
            # Guess common locations
            for candidate in (".agents/skills", ".gemini/skills", ".opencode/skills"):
                p = self.project_dir / candidate
                if p.is_dir():
                    skills_dir = p
                    break
        if not skills_dir or not Path(skills_dir).is_dir():
            return {}
        return {d.name: str(d) for d in Path(skills_dir).iterdir() if d.is_dir()}

    def get_current_agents(self, adapter) -> dict:
        """Read current agent names from adapter's agents output directory."""
        for candidate in (".gemini/agents", ".opencode/agents"):
            p = self.project_dir / candidate
            if p.is_dir():
                return {f.stem: str(f) for f in p.iterdir()
                        if f.is_file() and f.suffix == ".md"}
        return {}

    def get_current_commands(self, adapter) -> dict:
        """Read current command names from adapter's commands output directory."""
        for candidate in (".gemini/commands", ".opencode/commands"):
            p = self.project_dir / candidate
            if p.is_dir():
                return {f.stem: str(f) for f in p.iterdir()
                        if f.is_file() and f.suffix in (".md", ".toml")}
        return {}

    def get_current_mcp(self, adapter) -> dict:
        """Read current MCP config from adapter's output location."""
        # Common MCP output locations
        for candidate in (
            ".gemini/settings.json",
            ".codex/config.toml",
            ".opencode/settings.json",
        ):
            p = self.project_dir / candidate
            if p.exists() and p.suffix == ".json":
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    return data.get("mcpServers", {})
                except (OSError, json.JSONDecodeError):
                    pass
        return {}

    def get_current_settings(self, adapter) -> dict:
        """Read current settings from adapter's settings output."""
        for candidate in (
            ".gemini/settings.json",
            ".opencode/settings.json",
        ):
            p = self.project_dir / candidate
            if p.exists():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                    return {k: v for k, v in data.items() if k != "mcpServers"}
                except (OSError, json.JSONDecodeError):
                    pass
        return {}
