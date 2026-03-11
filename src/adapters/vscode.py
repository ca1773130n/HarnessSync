from __future__ import annotations

"""VS Code AI Extension adapter for HarnessSync.

Syncs Claude Code configuration to VS Code AI extension formats:
- Rules (CLAUDE.md) → .github/copilot-instructions.md (GitHub Copilot)
                    → .codeium/instructions.md (Codeium/Windsurf extension)
- Skills → Appended to copilot-instructions.md as reference sections
- Agents → Appended to copilot-instructions.md as assistant personas
- Commands → Not supported (no slash command model in Copilot)
- MCP servers → Not supported (no MCP in VS Code AI extensions)
- Settings → .github/copilot-instructions.md preference section

Targets VS Code users who rely on GitHub Copilot or Codeium extensions
rather than standalone CLI harnesses, enabling centralized rule management.

Copilot instructions reference:
  https://docs.github.com/en/copilot/customizing-copilot/adding-repository-custom-instructions-for-github-copilot
"""

import re
from datetime import datetime, timezone
from pathlib import Path

from .base import AdapterBase
from .registry import AdapterRegistry
from .result import SyncResult
from src.utils.paths import ensure_dir


HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"
HARNESSSYNC_MARKER_END = "<!-- End HarnessSync managed content -->"

# Copilot instructions file (GitHub standard path)
COPILOT_INSTRUCTIONS = ".github/copilot-instructions.md"

# Codeium instructions file
CODEIUM_INSTRUCTIONS = ".codeium/instructions.md"


def _build_managed_block(content: str, timestamp: str) -> str:
    """Build a managed content block with markers."""
    return (
        f"{HARNESSSYNC_MARKER}\n"
        f"<!-- Last synced: {timestamp} -->\n"
        f"{content.strip()}\n"
        f"{HARNESSSYNC_MARKER_END}\n"
    )


def _inject_managed_block(existing: str, new_block: str) -> str:
    """Replace managed block in existing content, or append if absent."""
    pattern = re.compile(
        re.escape(HARNESSSYNC_MARKER) + r".*?" + re.escape(HARNESSSYNC_MARKER_END) + r"\n?",
        re.DOTALL,
    )
    if pattern.search(existing):
        return pattern.sub(new_block, existing)
    # No existing block — append after any user content
    prefix = existing.rstrip()
    if prefix:
        return prefix + "\n\n" + new_block
    return new_block


@AdapterRegistry.register("vscode")
class VSCodeAdapter(AdapterBase):
    """Adapter for VS Code AI extension configuration sync.

    Writes to .github/copilot-instructions.md for GitHub Copilot and
    optionally to .codeium/instructions.md for Codeium. Both files use
    the same managed-marker pattern as other adapters.
    """

    def __init__(self, project_dir: Path):
        super().__init__(project_dir)
        self.copilot_path = project_dir / COPILOT_INSTRUCTIONS
        self.codeium_path = project_dir / CODEIUM_INSTRUCTIONS

    @property
    def target_name(self) -> str:
        return "vscode"

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync rules to .github/copilot-instructions.md.

        Copilot reads a single markdown file for repository instructions.
        All rules are concatenated into a HarnessSync-managed block.
        Also writes a copy to .codeium/instructions.md if Codeium config
        directory is detected.

        Args:
            rules: List of rule dicts with 'content' key.

        Returns:
            SyncResult with synced=1 on success, skipped=1 if no rules.
        """
        if not rules:
            return SyncResult(skipped=1, skipped_files=[COPILOT_INSTRUCTIONS])

        combined = "\n\n".join(
            r.get("content", "").strip() for r in rules if r.get("content", "").strip()
        )
        if not combined:
            return SyncResult(skipped=1, skipped_files=[COPILOT_INSTRUCTIONS])

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        managed_block = _build_managed_block(combined, timestamp)

        synced_files: list[str] = []
        failed_files: list[str] = []

        # Write Copilot instructions
        try:
            ensure_dir(self.copilot_path.parent)
            existing = self.copilot_path.read_text(encoding="utf-8") if self.copilot_path.exists() else ""
            new_content = _inject_managed_block(existing, managed_block)
            self.copilot_path.write_text(new_content, encoding="utf-8")
            synced_files.append(COPILOT_INSTRUCTIONS)
        except OSError as e:
            failed_files.append(f"{COPILOT_INSTRUCTIONS}: {e}")

        # Write Codeium instructions if .codeium dir exists or we can create it
        codeium_dir = self.project_dir / ".codeium"
        if codeium_dir.exists() or (self.project_dir / ".codeium").parent.exists():
            try:
                ensure_dir(self.codeium_path.parent)
                existing_c = self.codeium_path.read_text(encoding="utf-8") if self.codeium_path.exists() else ""
                new_content_c = _inject_managed_block(existing_c, managed_block)
                self.codeium_path.write_text(new_content_c, encoding="utf-8")
                synced_files.append(CODEIUM_INSTRUCTIONS)
            except OSError:
                pass  # Codeium sync is best-effort

        if failed_files:
            return SyncResult(failed=1, failed_files=failed_files)
        return SyncResult(synced=len(synced_files), synced_files=synced_files)

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Append skill summaries to copilot-instructions.md.

        VS Code AI extensions don't have a skills concept. We append a
        'Available Behaviors' section referencing each skill by name and
        its description (first non-empty line of SKILL.md if present).

        Args:
            skills: Dict mapping skill name to skill directory path.

        Returns:
            SyncResult with synced count.
        """
        if not skills:
            return SyncResult(skipped=1, skipped_files=["skills: none to sync"])

        skill_lines: list[str] = ["## Available Skill Behaviors\n"]
        for name, skill_dir in sorted(skills.items()):
            skill_md = skill_dir / "SKILL.md" if skill_dir.is_dir() else skill_dir
            description = _extract_first_description(skill_md)
            skill_lines.append(f"- **{name}**: {description}")

        section = "\n".join(skill_lines)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Append skills section after managed rules block
        try:
            ensure_dir(self.copilot_path.parent)
            existing = self.copilot_path.read_text(encoding="utf-8") if self.copilot_path.exists() else ""
            # Skills go after the main managed block as a separate section
            if "## Available Skill Behaviors" in existing:
                existing = re.sub(
                    r"## Available Skill Behaviors\n(?:.*\n)*?(?=\n##|\Z)",
                    section + "\n\n",
                    existing,
                )
            else:
                existing = existing.rstrip() + "\n\n" + section + "\n"
            self.copilot_path.write_text(existing, encoding="utf-8")
            return SyncResult(synced=len(skills), synced_files=[COPILOT_INSTRUCTIONS])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"skills section: {e}"])

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Append agent personas to copilot-instructions.md.

        Agents are exposed as named assistant persona descriptions so
        Copilot can be directed to emulate specific behavior patterns.

        Args:
            agents: Dict mapping agent name to agent .md file path.

        Returns:
            SyncResult with synced count.
        """
        if not agents:
            return SyncResult(skipped=1, skipped_files=["agents: none to sync"])

        agent_lines: list[str] = ["## Assistant Personas\n"]
        for name, agent_path in sorted(agents.items()):
            description = _extract_first_description(agent_path)
            agent_lines.append(f"- **{name}**: {description}")

        section = "\n".join(agent_lines)

        try:
            ensure_dir(self.copilot_path.parent)
            existing = self.copilot_path.read_text(encoding="utf-8") if self.copilot_path.exists() else ""
            if "## Assistant Personas" in existing:
                existing = re.sub(
                    r"## Assistant Personas\n(?:.*\n)*?(?=\n##|\Z)",
                    section + "\n\n",
                    existing,
                )
            else:
                existing = existing.rstrip() + "\n\n" + section + "\n"
            self.copilot_path.write_text(existing, encoding="utf-8")
            return SyncResult(synced=len(agents), synced_files=[COPILOT_INSTRUCTIONS])
        except OSError as e:
            return SyncResult(failed=1, failed_files=[f"agents section: {e}"])

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Commands not supported in VS Code AI extensions.

        GitHub Copilot and Codeium don't have a slash command model
        that accepts arbitrary user-defined commands. Skip silently.

        Returns:
            SyncResult with skipped count equal to command count.
        """
        count = len(commands)
        return SyncResult(
            skipped=count if count > 0 else 1,
            skipped_files=[f"{name}: no command model in VS Code extensions" for name in commands]
            or ["commands: no command model in VS Code extensions"],
        )

    def sync_mcp(self, mcp_servers: dict[str, dict]) -> SyncResult:
        """MCP not supported in VS Code AI extensions.

        GitHub Copilot and Codeium extensions don't support MCP server
        configuration at the project level. Skip.

        Returns:
            SyncResult with skipped count.
        """
        count = len(mcp_servers)
        return SyncResult(
            skipped=count if count > 0 else 1,
            skipped_files=["mcp: not supported in VS Code AI extensions"],
        )

    def sync_settings(self, settings: dict) -> SyncResult:
        """Translate relevant settings to copilot-instructions hints.

        Some settings (like preferred language or style preferences) can
        be encoded as natural language instructions in the Copilot file.
        Settings without a meaningful translation are skipped.

        Args:
            settings: Settings dict from Claude Code configuration.

        Returns:
            SyncResult with synced or skipped.
        """
        if not settings:
            return SyncResult(skipped=1, skipped_files=["settings: none to translate"])

        hints: list[str] = []

        model = settings.get("model")
        if model:
            hints.append(f"Preferred AI model context: {model}")

        if hints:
            section = "## Configuration Hints\n\n" + "\n".join(f"- {h}" for h in hints)
            try:
                ensure_dir(self.copilot_path.parent)
                existing = self.copilot_path.read_text(encoding="utf-8") if self.copilot_path.exists() else ""
                if "## Configuration Hints" in existing:
                    existing = re.sub(
                        r"## Configuration Hints\n(?:.*\n)*?(?=\n##|\Z)",
                        section + "\n\n",
                        existing,
                    )
                else:
                    existing = existing.rstrip() + "\n\n" + section + "\n"
                self.copilot_path.write_text(existing, encoding="utf-8")
                return SyncResult(synced=1, synced_files=[COPILOT_INSTRUCTIONS])
            except OSError as e:
                return SyncResult(failed=1, failed_files=[f"settings section: {e}"])

        return SyncResult(skipped=1, skipped_files=["settings: no translatable settings"])


def _extract_first_description(path: Path) -> str:
    """Extract first non-empty, non-frontmatter, non-heading line as description."""
    if not path or not path.exists():
        return "(no description)"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no description)"

    # Skip YAML frontmatter
    lines = text.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() == "---":
                start = i + 1
                break

    for line in lines[start:]:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("<!--"):
            return stripped[:120]

    return "(no description)"
