from __future__ import annotations

"""Dead config detector for HarnessSync.

Analyzes Claude Code config and flags:
1. Rules, skills, agents, commands, and MCP servers in Claude Code that have
   no active sync target (i.e., all targets skip or don't support them).
2. Config artifacts in target harnesses that have no corresponding source in
   Claude Code (orphaned files left from previous syncs).

Helps users clean up config debt they didn't know they had.
"""

from dataclasses import dataclass, field
from pathlib import Path


# Known synced output file patterns per target (relative to project_dir)
_TARGET_OUTPUT_FILES: dict[str, list[str]] = {
    "codex": ["AGENTS.md", ".codex/config.toml"],
    "gemini": ["GEMINI.md", ".gemini/settings.json"],
    "opencode": ["OPENCODE.md", ".opencode/settings.json"],
    "cursor": [".cursor/rules/claude-code-rules.mdc", ".cursor/mcp.json"],
    "aider": ["CONVENTIONS.md", ".aider.conf.yml"],
    "windsurf": [".windsurfrules", ".codeium/windsurf/mcp_config.json"],
    "cline": [".clinerules", ".roo/mcp.json"],
    "continue": [".continue/rules/harnesssync.md", ".continue/config.json"],
    "zed": [".zed/system-prompt.md", ".zed/settings.json"],
    "neovim": [".avante/system-prompt.md", ".codecompanion/system-prompt.md", ".avante/mcp.json"],
}

# HarnessSync managed section markers — files with these markers are managed
_HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"


@dataclass
class DeadConfigItem:
    """A config item that is dead (orphaned or unmapped)."""
    kind: str       # "source_no_target" | "target_orphan"
    category: str   # "rules" | "mcp" | "skill" | "agent" | "command" | "file"
    name: str       # Item name or file path
    detail: str     # Human-readable explanation


@dataclass
class DeadConfigReport:
    """Report of dead/orphaned configuration items."""

    source_no_target: list[DeadConfigItem] = field(default_factory=list)
    target_orphans: list[DeadConfigItem] = field(default_factory=list)

    @property
    def total_issues(self) -> int:
        return len(self.source_no_target) + len(self.target_orphans)

    def is_clean(self) -> bool:
        return self.total_issues == 0

    def format(self) -> str:
        """Format the dead config report as human-readable text."""
        if self.is_clean():
            return "Dead Config Detector: No issues found. Config is clean."

        lines = ["## Dead Config Report", ""]

        if self.source_no_target:
            lines.append("### Source items with no active sync target:")
            for item in self.source_no_target:
                lines.append(f"  [{item.category.upper()}] {item.name}")
                lines.append(f"    {item.detail}")
            lines.append("")

        if self.target_orphans:
            lines.append("### Orphaned files in targets (no source in Claude Code):")
            for item in self.target_orphans:
                lines.append(f"  [{item.category.upper()}] {item.name}")
                lines.append(f"    {item.detail}")
            lines.append("")

        lines.append(f"Total issues: {self.total_issues}")
        return "\n".join(lines)


class DeadConfigDetector:
    """Detects dead/orphaned configuration between Claude Code source and sync targets.

    Args:
        project_dir: Project root directory.
        cc_home: Claude Code home directory (defaults to ~/.claude).
    """

    def __init__(self, project_dir: Path, cc_home: Path = None):
        self.project_dir = project_dir
        self.cc_home = cc_home or Path.home() / ".claude"

    def detect(self, source_data: dict = None, active_targets: list[str] = None) -> DeadConfigReport:
        """Run dead config detection.

        Args:
            source_data: Pre-loaded source data dict (from SourceReader.discover_all()).
                         If None, a minimal scan of the project dir is used.
            active_targets: List of active sync targets. If None, all known targets
                            with output files present in project_dir are checked.

        Returns:
            DeadConfigReport with categorized issues.
        """
        report = DeadConfigReport()

        if source_data is None:
            source_data = self._minimal_source_scan()

        if active_targets is None:
            active_targets = self._detect_active_targets()

        # Check 1: Source items with no active target support
        self._check_source_no_target(source_data, active_targets, report)

        # Check 2: Orphaned files in targets
        self._check_target_orphans(active_targets, source_data, report)

        return report

    def _minimal_source_scan(self) -> dict:
        """Perform a minimal scan for source data without importing SourceReader."""
        data: dict = {
            "rules": [],
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp_servers": {},
        }

        # Check CLAUDE.md
        claude_md = self.project_dir / "CLAUDE.md"
        if claude_md.is_file() and claude_md.stat().st_size > 0:
            data["rules"] = [{"path": "CLAUDE.md", "content": claude_md.read_text(encoding="utf-8")}]

        # Check .claude/skills/
        skills_dir = self.cc_home / "skills"
        if skills_dir.is_dir():
            for d in skills_dir.iterdir():
                if d.is_dir() and (d / "SKILL.md").is_file():
                    data["skills"][d.name] = d

        # Check .claude/agents/
        agents_dir = self.cc_home / "agents"
        if agents_dir.is_dir():
            for f in agents_dir.iterdir():
                if f.is_file() and f.suffix == ".md":
                    data["agents"][f.stem] = f

        # Check .claude/commands/
        commands_dir = self.cc_home / "commands"
        if commands_dir.is_dir():
            for f in commands_dir.iterdir():
                if f.is_file() and f.suffix == ".md":
                    data["commands"][f.stem] = f

        return data

    def _detect_active_targets(self) -> list[str]:
        """Return targets that appear to have been synced (output files exist)."""
        active = []
        for target, output_files in _TARGET_OUTPUT_FILES.items():
            for rel in output_files:
                p = self.project_dir / rel
                if p.is_file():
                    active.append(target)
                    break
        return active

    def _check_source_no_target(
        self, source_data: dict, active_targets: list[str], report: DeadConfigReport
    ) -> None:
        """Flag source items that have no mapping in any active target."""
        # MCP servers: check if any active target writes MCP config
        mcp_servers = source_data.get("mcp_servers", source_data.get("mcp", {}))
        if mcp_servers and active_targets:
            # Targets that support MCP output
            mcp_capable = {"codex", "gemini", "opencode", "cursor", "cline", "continue", "zed", "neovim"}
            if not any(t in mcp_capable for t in active_targets):
                for server_name in mcp_servers:
                    report.source_no_target.append(DeadConfigItem(
                        kind="source_no_target",
                        category="mcp",
                        name=server_name,
                        detail="MCP server has no active target that supports MCP sync",
                    ))

        # Skills: check if any active target syncs skills
        skills = source_data.get("skills", {})
        if skills and active_targets:
            skill_capable = {"codex", "gemini", "opencode", "cursor", "cline", "continue", "zed", "neovim"}
            if not any(t in skill_capable for t in active_targets):
                for skill_name in skills:
                    report.source_no_target.append(DeadConfigItem(
                        kind="source_no_target",
                        category="skill",
                        name=skill_name,
                        detail="Skill has no active target that syncs skills",
                    ))

        # Rules: warn if no active targets at all
        rules = source_data.get("rules", [])
        if rules and not active_targets:
            report.source_no_target.append(DeadConfigItem(
                kind="source_no_target",
                category="rules",
                name="CLAUDE.md",
                detail="Rules exist but no sync targets have been configured",
            ))

    def _check_target_orphans(
        self, active_targets: list[str], source_data: dict, report: DeadConfigReport
    ) -> None:
        """Flag target output files that are managed by HarnessSync but have no source."""
        has_rules = bool(source_data.get("rules", []))

        for target in active_targets:
            output_files = _TARGET_OUTPUT_FILES.get(target, [])
            for rel in output_files:
                p = self.project_dir / rel
                if not p.is_file():
                    continue
                try:
                    content = p.read_text(encoding="utf-8")
                except OSError:
                    continue

                # Only flag files that HarnessSync manages
                if _HARNESSSYNC_MARKER not in content:
                    continue

                # If no source rules, any managed rules file is an orphan
                if not has_rules and ("rules" in rel.lower() or rel.endswith(".md")):
                    report.target_orphans.append(DeadConfigItem(
                        kind="target_orphan",
                        category="file",
                        name=f"{target}:{rel}",
                        detail=(
                            f"HarnessSync-managed file at {rel} has no source "
                            f"CLAUDE.md or rules in Claude Code"
                        ),
                    ))
