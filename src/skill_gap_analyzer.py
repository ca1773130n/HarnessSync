from __future__ import annotations

"""Skill gap analyzer for HarnessSync.

Shows which Claude Code skills have no equivalent in target harnesses and
vice versa. Highlights functionality the user is losing when switching
harnesses and motivates writing adapter approximations.

Also identifies skills that exist in target harnesses but have no source in
Claude Code (orphaned skill copies).
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


# Known skill output directories per target (relative to project_dir)
_TARGET_SKILL_DIRS: dict[str, str] = {
    "codex": ".agents/skills",
    "gemini": ".gemini/skills",
    "opencode": ".opencode/skills",
    "cursor": ".cursor/rules/skills",
    "aider": None,     # Aider doesn't sync skills to a dedicated dir
    "windsurf": ".windsurf/memories",
    "cline": ".roo/rules/skills",
    "continue": ".continue/rules/skills",
    "zed": ".zed/prompts/skills",
    "neovim": ".avante/rules/skills",
}

# Targets that don't support skill sync at all
_SKILL_UNSUPPORTED_TARGETS: set[str] = {"aider"}


@dataclass
class SkillGapItem:
    """A skill that exists in one place but not another."""
    skill_name: str
    source_exists: bool     # True if in Claude Code source
    missing_in: list[str]   # Targets where this skill is absent
    orphaned_in: list[str]  # Targets where this skill exists without a source


@dataclass
class SkillGapReport:
    """Report of skill gaps across harnesses."""

    source_skills: list[str] = field(default_factory=list)
    gaps: list[SkillGapItem] = field(default_factory=list)
    unsupported_targets: list[str] = field(default_factory=list)

    @property
    def total_gaps(self) -> int:
        return sum(len(g.missing_in) for g in self.gaps)

    @property
    def total_orphans(self) -> int:
        return sum(len(g.orphaned_in) for g in self.gaps)

    def format(self) -> str:
        """Format skill gap report as human-readable text."""
        lines = ["## Skill Gap Analysis", ""]

        if not self.source_skills:
            lines.append("No skills found in Claude Code source.")
            return "\n".join(lines)

        lines.append(f"Source skills: {len(self.source_skills)}")
        if self.unsupported_targets:
            lines.append(
                f"Targets without skill sync: {', '.join(sorted(self.unsupported_targets))}"
            )
        lines.append("")

        gaps_with_missing = [g for g in self.gaps if g.missing_in]
        if gaps_with_missing:
            lines.append("### Skills missing in some targets:")
            for gap in sorted(gaps_with_missing, key=lambda g: g.skill_name):
                lines.append(f"  {gap.skill_name}")
                lines.append(f"    Missing in: {', '.join(sorted(gap.missing_in))}")
            lines.append("")

        orphaned = [g for g in self.gaps if g.orphaned_in]
        if orphaned:
            lines.append("### Orphaned skills (exist in target but not in source):")
            for gap in sorted(orphaned, key=lambda g: g.skill_name):
                lines.append(f"  {gap.skill_name}")
                lines.append(f"    Orphaned in: {', '.join(sorted(gap.orphaned_in))}")
            lines.append("")

        if not gaps_with_missing and not orphaned:
            lines.append("All skills are in sync across all active targets.")

        if self.total_gaps > 0:
            lines.append(
                f"Total gaps: {self.total_gaps} (skill × target combinations "
                "where skill is missing)"
            )
        return "\n".join(lines)

    def format_with_suggestions(self) -> str:
        """Format skill gap report including actionable workaround suggestions.

        For each missing skill × target combination, appends a plain-English
        suggestion explaining how the user can manually fill the gap in that
        harness — making the invisible visible.

        Returns:
            Extended report string with suggestions appended after each gap.
        """
        # Import here to avoid circular dependency at module level
        from src.skill_gap_analyzer import suggest_skill_workaround

        lines = ["## Skill Gap Analysis with Suggestions", ""]

        if not self.source_skills:
            lines.append("No skills found in Claude Code source.")
            return "\n".join(lines)

        lines.append(f"Source skills: {len(self.source_skills)}")
        if self.unsupported_targets:
            lines.append(
                f"Targets without skill sync: {', '.join(sorted(self.unsupported_targets))}"
            )
        lines.append("")

        gaps_with_missing = [g for g in self.gaps if g.missing_in]
        if gaps_with_missing:
            lines.append("### Skills missing in some targets (with suggestions):")
            for gap in sorted(gaps_with_missing, key=lambda g: g.skill_name):
                lines.append(f"\n  **{gap.skill_name}**")
                for target in sorted(gap.missing_in):
                    lines.append(f"    Missing in: {target}")
                    suggestion = suggest_skill_workaround(target, gap.skill_name)
                    # Indent suggestion text
                    for sline in suggestion.split(". "):
                        sline = sline.strip()
                        if sline:
                            lines.append(f"      → {sline.rstrip('.')}.")
            lines.append("")

        orphaned = [g for g in self.gaps if g.orphaned_in]
        if orphaned:
            lines.append("### Orphaned skills (in target but not in source):")
            for gap in sorted(orphaned, key=lambda g: g.skill_name):
                lines.append(f"  {gap.skill_name}")
                lines.append(f"    Orphaned in: {', '.join(sorted(gap.orphaned_in))}")
                lines.append(
                    "    → Consider adding this skill to ~/.claude/skills/ "
                    "so it's managed by HarnessSync."
                )
            lines.append("")

        if not gaps_with_missing and not orphaned:
            lines.append("All skills are in sync across all active targets.")

        if self.total_gaps > 0:
            lines.append(
                f"Total gaps: {self.total_gaps} (skill × target combinations "
                "where skill is missing)"
            )
        return "\n".join(lines)


# Per-target suggestions for skills that can't be synced natively.
# Explains how users can manually fill the gap for unsupported harnesses.
_TARGET_SKILL_WORKAROUNDS: dict[str, str] = {
    "aider": (
        "Aider doesn't support skills natively. "
        "Embed the skill's SKILL.md content in your system prompt via "
        ".aider.conf.yml 'read' key, or add it to CONVENTIONS.md so Aider "
        "picks it up as project context."
    ),
    "codex": (
        "Codex supports skills via AGENTS.md. "
        "Add the skill instructions to your AGENTS.md under a dedicated heading, "
        "or place the skill file in .agents/skills/ so HarnessSync can sync it."
    ),
    "gemini": (
        "Gemini CLI supports skills via .gemini/skills/. "
        "Ensure the skill directory is present under ~/.claude/skills/ and run /sync."
    ),
    "opencode": (
        "OpenCode supports skills via .opencode/skills/. "
        "Ensure the skill directory is present and run /sync."
    ),
    "cursor": (
        "Cursor supports skills as .mdc rule files under .cursor/rules/skills/. "
        "Run /sync to propagate skills, or manually create a .mdc file with "
        "the skill content and alwaysApply: false."
    ),
    "windsurf": (
        "Windsurf maps skills to .windsurf/memories/ files. "
        "Run /sync to propagate, or manually create a .md file in .windsurf/memories/ "
        "with the skill content."
    ),
    "cline": (
        "Cline supports rule files under .roo/rules/skills/. "
        "Add skill content as a rule file to expose it to Cline sessions."
    ),
    "continue": (
        "Continue supports rule files under .continue/rules/skills/. "
        "Add skill content as a rule file and run /sync."
    ),
    "zed": (
        "Zed supports prompts under .zed/prompts/skills/. "
        "Add the skill as a .md prompt file for use in Zed AI sessions."
    ),
    "neovim": (
        "Neovim/Avante supports rules under .avante/rules/skills/. "
        "Add the skill content as a rule file for your Avante setup."
    ),
}


def suggest_skill_workaround(target: str, skill_name: str) -> str:
    """Return a human-readable suggestion for bridging a skill gap.

    When a skill exists in Claude Code but a target harness doesn't support
    it natively, this function explains how to manually fill the gap.

    Args:
        target: Target harness name (e.g. "aider", "codex").
        skill_name: Name of the skill that is missing.

    Returns:
        Suggestion string. Falls back to a generic message if no specific
        guidance exists for this target.
    """
    base = _TARGET_SKILL_WORKAROUNDS.get(
        target,
        f"{target} may not support skills. Check {target}'s documentation for "
        "how to inject persistent instructions or system prompt content.",
    )
    return f"Skill '{skill_name}' gap in {target}: {base}"


# ---------------------------------------------------------------------------
# Portable Skill Design Guide (item 12)
# ---------------------------------------------------------------------------

# Design tips keyed by common anti-pattern category
_PORTABLE_DESIGN_TIPS: list[tuple[str, str]] = [
    (
        "claude_tool_refs",
        "Avoid referencing Claude Code-specific tool names (e.g., 'Agent tool', "
        "'TodoWrite', 'mcp__*') inside skill descriptions. Replace with task-level "
        "descriptions so other harnesses can interpret them: "
        "'orchestrate a multi-step task' instead of 'use the Agent tool'.",
    ),
    (
        "slash_commands",
        "Don't rely on slash command names in skill descriptions. Other harnesses "
        "may not have the same commands. Describe the desired behavior instead of "
        "citing a specific command like '/sync' or '/commit'.",
    ),
    (
        "file_paths",
        "Avoid hardcoding ~/.claude/ paths in skill instructions. Use environment "
        "variables or project-relative paths so the skill works across harnesses "
        "and machines.",
    ),
    (
        "mcp_tool_names",
        "MCP tool names (mcp__plugin_*) are Claude Code-specific. For skills that "
        "use external data, describe the data source generically and let each "
        "harness use its available tool to fetch it.",
    ),
    (
        "harness_annotations",
        "Use harness annotations to include harness-specific instructions inline: "
        "<!-- harness:only=claude --> ... <!-- /harness:claude --> wraps content "
        "that only Claude Code should see. Other harnesses receive the generic version.",
    ),
    (
        "self_contained",
        "Write skills to be self-contained: include all context the AI needs "
        "without assuming access to other Claude Code features. A skill that "
        "works as a standalone system-prompt snippet will work in any harness.",
    ),
    (
        "avoid_multi_agent",
        "Multi-agent orchestration patterns (spawning sub-agents, tool chaining) "
        "are Claude Code-specific. If the skill requires orchestration, add a "
        "<!-- harness:only=claude --> section and provide a simplified single-agent "
        "fallback for other harnesses.",
    ),
]


def format_portable_design_guide(gap_report: "SkillGapReport | None" = None) -> str:
    """Return a plain-English guide for designing portable skills.

    When a SkillGapReport is provided, the guide is personalized to the
    specific gaps found (e.g., targets where skills are missing). Otherwise
    a general guide is returned.

    Args:
        gap_report: Optional SkillGapReport from SkillGapAnalyzer.analyze().

    Returns:
        Multi-line guide string with actionable tips.
    """
    lines = [
        "## Portable Skill Design Guide",
        "",
        "Skills written exclusively for Claude Code often perform poorly in other "
        "harnesses because they reference Claude-specific tools, commands, or paths.",
        "",
        "Follow these guidelines to write skills that sync cleanly to all targets:",
        "",
    ]

    for i, (_, tip) in enumerate(_PORTABLE_DESIGN_TIPS, start=1):
        lines.append(f"{i}. {tip}")
        lines.append("")

    if gap_report and gap_report.total_gaps > 0:
        lines.append("─" * 60)
        lines.append("")
        lines.append(
            f"Your skill gap report shows {gap_report.total_gaps} gap(s) across "
            f"{len([g for g in gap_report.gaps if g.missing_in])} skill(s). "
            "Applying the tips above — especially self-contained skill design and "
            "harness annotations — will reduce these gaps without requiring separate "
            "per-harness skill files."
        )

    if gap_report and gap_report.total_orphans > 0:
        lines.append("")
        lines.append(
            f"Note: {gap_report.total_orphans} orphaned skill copy(ies) were found "
            "in target harnesses without a corresponding Claude Code source. "
            "Run /sync-import to propose merging them back into a canonical skill."
        )

    return "\n".join(lines)


class SkillGapAnalyzer:
    """Analyzes skill coverage gaps across sync targets.

    Args:
        project_dir: Project root directory.
        cc_home: Claude Code home directory (defaults to ~/.claude).
    """

    def __init__(self, project_dir: Path, cc_home: Path = None):
        self.project_dir = project_dir
        self.cc_home = cc_home or Path.home() / ".claude"

    def analyze(
        self,
        source_skills: dict[str, Path] = None,
        active_targets: list[str] = None,
    ) -> SkillGapReport:
        """Run skill gap analysis.

        Args:
            source_skills: Pre-loaded skills dict (name -> path). If None,
                           auto-discovers from ~/.claude/skills/.
            active_targets: List of active targets to check. If None,
                            auto-detects from files present.

        Returns:
            SkillGapReport with per-skill gap data.
        """
        if source_skills is None:
            source_skills = self._discover_source_skills()

        if active_targets is None:
            active_targets = self._detect_active_targets()

        report = SkillGapReport(
            source_skills=sorted(source_skills.keys()),
            unsupported_targets=[t for t in active_targets if t in _SKILL_UNSUPPORTED_TARGETS],
        )

        # For each source skill, find which targets are missing it
        supported_targets = [t for t in active_targets if t not in _SKILL_UNSUPPORTED_TARGETS]

        for skill_name in source_skills:
            missing_in = []
            for target in supported_targets:
                if not self._skill_exists_in_target(skill_name, target):
                    missing_in.append(target)
            if missing_in:
                report.gaps.append(SkillGapItem(
                    skill_name=skill_name,
                    source_exists=True,
                    missing_in=missing_in,
                    orphaned_in=[],
                ))

        # Find orphaned skills in targets (exist in target but not in source)
        all_target_skills: dict[str, list[str]] = {}  # skill_name -> [targets]
        for target in supported_targets:
            target_skills = self._list_target_skills(target)
            for skill_name in target_skills:
                all_target_skills.setdefault(skill_name, []).append(target)

        for skill_name, targets_with_skill in all_target_skills.items():
            if skill_name not in source_skills:
                # Orphaned: exists in target(s) but not in source
                existing_gap = next((g for g in report.gaps if g.skill_name == skill_name), None)
                if existing_gap:
                    existing_gap.orphaned_in = targets_with_skill
                else:
                    report.gaps.append(SkillGapItem(
                        skill_name=skill_name,
                        source_exists=False,
                        missing_in=[],
                        orphaned_in=targets_with_skill,
                    ))

        return report

    def suggest_all(
        self,
        source_skills: dict[str, Path] = None,
        active_targets: list[str] = None,
    ) -> list[str]:
        """Run gap analysis and return a flat list of actionable suggestions.

        Each entry in the returned list is a plain-English suggestion for how
        to fill a specific skill × target gap.  Users don't know what they're
        missing — this makes the invisible visible.

        Args:
            source_skills: Pre-loaded skills dict (see analyze()).
            active_targets: List of active targets (see analyze()).

        Returns:
            List of suggestion strings, one per skill × target gap.
            Empty list if no gaps found.
        """
        report = self.analyze(source_skills=source_skills, active_targets=active_targets)
        suggestions: list[str] = []
        for gap in report.gaps:
            for target in gap.missing_in:
                suggestions.append(suggest_skill_workaround(target, gap.skill_name))
        return suggestions

    def _discover_source_skills(self) -> dict[str, Path]:
        """Discover skills from ~/.claude/skills/ directory."""
        skills_dir = self.cc_home / "skills"
        if not skills_dir.is_dir():
            return {}
        result = {}
        for d in skills_dir.iterdir():
            if d.is_dir() and (d / "SKILL.md").is_file():
                result[d.name] = d
        return result

    def _detect_active_targets(self) -> list[str]:
        """Auto-detect active targets by looking for known output directories/files."""
        active = []
        indicators = {
            "codex": "AGENTS.md",
            "gemini": "GEMINI.md",
            "opencode": "OPENCODE.md",
            "cursor": ".cursor/rules/claude-code-rules.mdc",
            "aider": "CONVENTIONS.md",
            "windsurf": ".windsurfrules",
            "cline": ".clinerules",
            "continue": ".continue/rules/harnesssync.md",
            "zed": ".zed/system-prompt.md",
            "neovim": ".avante/system-prompt.md",
        }
        for target, rel in indicators.items():
            if (self.project_dir / rel).is_file():
                active.append(target)
        return active

    def _skill_exists_in_target(self, skill_name: str, target: str) -> bool:
        """Return True if a skill output file exists for this target."""
        skills_rel = _TARGET_SKILL_DIRS.get(target)
        if not skills_rel:
            return False
        skills_dir = self.project_dir / skills_rel
        if not skills_dir.is_dir():
            return False
        # Check for common output file extensions
        for ext in (".md", ".mdc", ".txt", ""):
            candidate = skills_dir / f"{skill_name}{ext}"
            if candidate.is_file():
                return True
            # Also check as directory (some adapters sync skill dirs)
            candidate_dir = skills_dir / skill_name
            if candidate_dir.is_dir():
                return True
        return False

    def _list_target_skills(self, target: str) -> list[str]:
        """List skill names present in a target's skill directory."""
        skills_rel = _TARGET_SKILL_DIRS.get(target)
        if not skills_rel:
            return []
        skills_dir = self.project_dir / skills_rel
        if not skills_dir.is_dir():
            return []
        names = []
        for item in skills_dir.iterdir():
            if item.is_file():
                names.append(item.stem)
            elif item.is_dir():
                names.append(item.name)
        return names


# ---------------------------------------------------------------------------
# Item 1 — Real-Time Capability Gap Alerts
# ---------------------------------------------------------------------------

# MCP features that some targets cannot replicate at all
_MCP_UNSUPPORTED_TARGETS: dict[str, str] = {
    "aider": "Aider has no native MCP support; servers must be invoked manually",
    "cline": "Cline supports MCP but requires manual wiring in VS Code settings",
    "zed": "Zed AI does not yet support MCP servers",
    "neovim": "Avante/Neovim has no MCP server support",
}

# Skill features that some targets cannot replicate
_SKILL_UNSUPPORTED_REASONS: dict[str, str] = {
    "aider": "Aider does not support skill files; embed skill content in CONVENTIONS.md",
    "zed": "Zed has no concept of skills; use .zed/prompts/ as an approximation",
    "neovim": "Avante does not support skill files natively",
}


@dataclass
class CapabilityGapAlert:
    """A single capability gap alert for a newly-added skill or MCP server."""

    item_type: str       # "skill" or "mcp_server"
    item_name: str       # Name of the skill or MCP server key
    affected_targets: list[str]   # Targets that can't fully replicate this item
    reasons: dict[str, str]       # target -> why it can't be replicated

    def format(self) -> str:
        """Return a human-readable alert string."""
        lines = [
            f"Capability gap: new {self.item_type} '{self.item_name}' "
            f"cannot fully sync to {len(self.affected_targets)} target(s):"
        ]
        for target in sorted(self.affected_targets):
            reason = self.reasons.get(target, "limited support")
            lines.append(f"  {target}: {reason}")
        return "\n".join(lines)

    def format_short(self) -> str:
        """Return a single-line summary suitable for desktop notifications."""
        targets_str = ", ".join(sorted(self.affected_targets[:3]))
        suffix = f" +{len(self.affected_targets) - 3} more" if len(self.affected_targets) > 3 else ""
        return (
            f"New {self.item_type} '{self.item_name}' won't fully sync to: "
            f"{targets_str}{suffix}"
        )


class CapabilityGapNotifier:
    """Detects new skills/MCP servers and surfaces capability gap alerts.

    Maintains a snapshot of known skills and MCP servers in a state file.
    On each call to ``check()``, compares the current state against the
    snapshot and returns alerts for newly-added items that can't fully
    replicate to all active targets.

    This solves the "why doesn't this work in Codex?" confusion hours after
    syncing a new skill or MCP server.

    Args:
        project_dir: Project root directory.
        cc_home: Claude Code home directory (defaults to ~/.claude).
        state_file: Path to the JSON state file for tracking known items.
                    Defaults to project_dir/.harness-sync/gap-notifier-state.json
    """

    def __init__(
        self,
        project_dir: Path,
        cc_home: Path | None = None,
        state_file: Path | None = None,
    ) -> None:
        self.project_dir = project_dir
        self.cc_home = cc_home or Path.home() / ".claude"
        self._state_file = (
            state_file
            or project_dir / ".harness-sync" / "gap-notifier-state.json"
        )

    def _load_state(self) -> dict:
        """Load previous known-items state from the JSON state file."""
        if not self._state_file.exists():
            return {"skills": [], "mcp_servers": []}
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            return {
                "skills": list(data.get("skills", [])),
                "mcp_servers": list(data.get("mcp_servers", [])),
            }
        except (json.JSONDecodeError, OSError):
            return {"skills": [], "mcp_servers": []}

    def _save_state(self, state: dict) -> None:
        """Persist the current known-items state to the JSON state file."""
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(
                json.dumps(state, indent=2), encoding="utf-8"
            )
        except OSError:
            pass  # Non-fatal — next check will re-detect the same items

    def _current_skills(self) -> set[str]:
        """Discover current skill names from ~/.claude/skills/."""
        skills_dir = self.cc_home / "skills"
        if not skills_dir.is_dir():
            return set()
        return {
            d.name
            for d in skills_dir.iterdir()
            if d.is_dir() and (d / "SKILL.md").is_file()
        }

    def _current_mcp_servers(self) -> set[str]:
        """Discover current MCP server names from ~/.claude.json."""
        claude_json = self.cc_home.parent / ".claude.json"
        if not claude_json.exists():
            claude_json = Path.home() / ".claude.json"
        if not claude_json.exists():
            return set()
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
            servers = data.get("mcpServers", {})
            if isinstance(servers, dict):
                return set(servers.keys())
        except (json.JSONDecodeError, OSError):
            pass
        return set()

    def _active_targets(self) -> list[str]:
        """Detect active sync targets from known output files."""
        analyzer = SkillGapAnalyzer(self.project_dir, self.cc_home)
        return analyzer._detect_active_targets()

    def _skill_alerts_for(
        self, new_skills: set[str], active_targets: list[str]
    ) -> list[CapabilityGapAlert]:
        """Return gap alerts for newly-added skills."""
        alerts: list[CapabilityGapAlert] = []
        for skill_name in sorted(new_skills):
            affected: list[str] = []
            reasons: dict[str, str] = {}
            for target in active_targets:
                if target in _SKILL_UNSUPPORTED_TARGETS:
                    affected.append(target)
                    reasons[target] = _SKILL_UNSUPPORTED_REASONS.get(
                        target, f"{target} does not support skill sync"
                    )
            if affected:
                alerts.append(CapabilityGapAlert(
                    item_type="skill",
                    item_name=skill_name,
                    affected_targets=affected,
                    reasons=reasons,
                ))
        return alerts

    def _mcp_alerts_for(
        self, new_servers: set[str], active_targets: list[str]
    ) -> list[CapabilityGapAlert]:
        """Return gap alerts for newly-added MCP servers."""
        alerts: list[CapabilityGapAlert] = []
        for server_name in sorted(new_servers):
            affected: list[str] = []
            reasons: dict[str, str] = {}
            for target in active_targets:
                if target in _MCP_UNSUPPORTED_TARGETS:
                    affected.append(target)
                    reasons[target] = _MCP_UNSUPPORTED_TARGETS[target]
            if affected:
                alerts.append(CapabilityGapAlert(
                    item_type="mcp_server",
                    item_name=server_name,
                    affected_targets=affected,
                    reasons=reasons,
                ))
        return alerts

    def check(
        self,
        notify: bool = False,
        update_state: bool = True,
    ) -> list[CapabilityGapAlert]:
        """Check for new skills/MCP servers and return capability gap alerts.

        Compares current skills and MCP servers against the last-known state.
        Newly-added items that can't fully replicate to all active targets
        generate CapabilityGapAlert entries.

        Args:
            notify: If True, fire desktop notifications for each alert
                    (requires HARNESSSYNC_NOTIFY=1 env var).
            update_state: If True, save the current state after checking so
                          the same items don't alert again next call.

        Returns:
            List of CapabilityGapAlert entries for newly-detected items.
            Empty if nothing new was added or no gaps exist.
        """
        state = self._load_state()
        known_skills = set(state["skills"])
        known_mcp = set(state["mcp_servers"])

        current_skills = self._current_skills()
        current_mcp = self._current_mcp_servers()
        active_targets = self._active_targets()

        new_skills = current_skills - known_skills
        new_mcp = current_mcp - known_mcp

        alerts: list[CapabilityGapAlert] = []
        if active_targets:
            alerts.extend(self._skill_alerts_for(new_skills, active_targets))
            alerts.extend(self._mcp_alerts_for(new_mcp, active_targets))

        if notify and alerts:
            self._fire_notifications(alerts)

        if update_state:
            self._save_state({
                "skills": sorted(current_skills),
                "mcp_servers": sorted(current_mcp),
            })

        return alerts

    def _fire_notifications(self, alerts: list[CapabilityGapAlert]) -> None:
        """Send desktop notifications for capability gap alerts."""
        try:
            from src.desktop_notifier import DesktopNotifier
            notifier = DesktopNotifier()
            for alert in alerts:
                notifier._send(
                    f"HarnessSync: Capability Gap — {alert.item_name}",
                    alert.format_short(),
                    urgency="normal",
                )
        except Exception:
            pass  # Notifications are best-effort

    def format_alerts(self, alerts: list[CapabilityGapAlert]) -> str:
        """Format a list of capability gap alerts as human-readable text.

        Args:
            alerts: List of CapabilityGapAlert from check().

        Returns:
            Formatted multi-line string, or empty string if no alerts.
        """
        if not alerts:
            return ""
        lines = ["## Capability Gap Alerts", ""]
        for alert in alerts:
            lines.append(alert.format())
            lines.append("")
        lines.append(
            "Run /sync-gaps for a full capability gap analysis, "
            "or /sync-status to see current drift."
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Agent Capability Gap Report (item 20)
# ---------------------------------------------------------------------------

# Agent capabilities tracked across harnesses
_AGENT_CAPABILITIES: list[str] = [
    "tool_access",       # Can the agent call tools/functions?
    "memory",            # Does the agent have persistent memory?
    "context_window",    # How much context does the agent have?
    "multi_turn",        # Can the agent maintain multi-turn conversation?
    "sub_agents",        # Can the agent spawn sub-agents?
    "file_access",       # Can the agent read/write files?
    "web_search",        # Can the agent search the web?
    "code_execution",    # Can the agent execute code?
    "mcp_tools",         # Can the agent call MCP-served tools?
    "streaming",         # Does the harness support streaming responses?
]

# Per-harness capability support: True/False/None (unknown)
_HARNESS_AGENT_CAPABILITIES: dict[str, dict[str, bool | None]] = {
    "codex": {
        "tool_access": True,
        "memory": False,
        "context_window": True,
        "multi_turn": True,
        "sub_agents": True,
        "file_access": True,
        "web_search": False,
        "code_execution": True,
        "mcp_tools": True,
        "streaming": True,
    },
    "gemini": {
        "tool_access": True,
        "memory": False,
        "context_window": True,
        "multi_turn": True,
        "sub_agents": False,
        "file_access": True,
        "web_search": True,
        "code_execution": False,
        "mcp_tools": True,
        "streaming": True,
    },
    "opencode": {
        "tool_access": True,
        "memory": False,
        "context_window": True,
        "multi_turn": True,
        "sub_agents": False,
        "file_access": True,
        "web_search": False,
        "code_execution": False,
        "mcp_tools": True,
        "streaming": True,
    },
    "cursor": {
        "tool_access": True,
        "memory": False,
        "context_window": True,
        "multi_turn": True,
        "sub_agents": False,
        "file_access": True,
        "web_search": True,
        "code_execution": True,
        "mcp_tools": True,
        "streaming": True,
    },
    "aider": {
        "tool_access": False,
        "memory": False,
        "context_window": True,
        "multi_turn": True,
        "sub_agents": False,
        "file_access": True,
        "web_search": False,
        "code_execution": False,
        "mcp_tools": False,
        "streaming": True,
    },
    "windsurf": {
        "tool_access": True,
        "memory": True,
        "context_window": True,
        "multi_turn": True,
        "sub_agents": False,
        "file_access": True,
        "web_search": True,
        "code_execution": True,
        "mcp_tools": True,
        "streaming": True,
    },
    "cline": {
        "tool_access": True,
        "memory": False,
        "context_window": True,
        "multi_turn": True,
        "sub_agents": False,
        "file_access": True,
        "web_search": True,
        "code_execution": True,
        "mcp_tools": True,
        "streaming": True,
    },
    "continue": {
        "tool_access": True,
        "memory": False,
        "context_window": True,
        "multi_turn": True,
        "sub_agents": False,
        "file_access": True,
        "web_search": False,
        "code_execution": False,
        "mcp_tools": True,
        "streaming": True,
    },
    "zed": {
        "tool_access": True,
        "memory": False,
        "context_window": True,
        "multi_turn": True,
        "sub_agents": False,
        "file_access": True,
        "web_search": False,
        "code_execution": False,
        "mcp_tools": True,
        "streaming": True,
    },
    "neovim": {
        "tool_access": True,
        "memory": False,
        "context_window": True,
        "multi_turn": True,
        "sub_agents": False,
        "file_access": True,
        "web_search": False,
        "code_execution": False,
        "mcp_tools": True,
        "streaming": True,
    },
}

# Claude Code (source harness) capabilities — the gold standard
_CLAUDE_CODE_CAPABILITIES: dict[str, bool] = {
    "tool_access": True,
    "memory": True,
    "context_window": True,
    "multi_turn": True,
    "sub_agents": True,
    "file_access": True,
    "web_search": True,
    "code_execution": True,
    "mcp_tools": True,
    "streaming": True,
}

# Workaround suggestions for capabilities not available in a harness
_WORKAROUNDS: dict[str, str] = {
    "memory": "Use CLAUDE.md/AGENTS.md to embed persistent context as static rules.",
    "sub_agents": "Break multi-agent workflows into sequential prompts or use a script.",
    "web_search": "Pre-fetch search results and pass as context in your initial prompt.",
    "code_execution": "Use the harness's built-in terminal integration if available.",
    "mcp_tools": "Replace MCP tool calls with equivalent inline instructions.",
    "tool_access": "Describe required tool behavior in rules as manual instructions.",
}


@dataclass
class AgentCapabilityGap:
    """A single capability that is lost when syncing agents to a target harness."""
    capability: str
    available_in_source: bool
    available_in_target: bool | None
    workaround: str


@dataclass
class AgentCapabilityGapReport:
    """Report showing which agent capabilities are lost per target harness.

    Attributes:
        target: Target harness name.
        gaps: List of capability gaps (capabilities present in Claude Code but
              absent or unknown in the target).
        coverage_score: Percentage of Claude Code capabilities available (0–100).
    """
    target: str
    gaps: list[AgentCapabilityGap]
    coverage_score: int

    def format(self) -> str:
        """Format the gap report for terminal display."""
        lines = [
            f"Agent Capability Gap Report — {self.target}",
            "=" * 50,
            f"Coverage score: {self.coverage_score}/100",
            "",
        ]
        if not self.gaps:
            lines.append("All Claude Code agent capabilities are available in this harness.")
            return "\n".join(lines)

        lines.append("Missing capabilities:")
        for gap in self.gaps:
            avail_str = "unavailable" if gap.available_in_target is False else "unknown"
            lines.append(f"  ✗ {gap.capability:<22} ({avail_str})")
            if gap.workaround:
                lines.append(f"    Workaround: {gap.workaround}")
        return "\n".join(lines)


def build_agent_gap_report(target: str) -> AgentCapabilityGapReport:
    """Build an agent capability gap report for a single target harness.

    Args:
        target: Target harness name (e.g. "codex", "gemini").

    Returns:
        AgentCapabilityGapReport for the given target.
    """
    target_caps = _HARNESS_AGENT_CAPABILITIES.get(target, {})
    gaps: list[AgentCapabilityGap] = []

    for cap in _AGENT_CAPABILITIES:
        source_has = _CLAUDE_CODE_CAPABILITIES.get(cap, False)
        target_has = target_caps.get(cap)
        if source_has and not target_has:
            gaps.append(AgentCapabilityGap(
                capability=cap,
                available_in_source=source_has,
                available_in_target=target_has,
                workaround=_WORKAROUNDS.get(cap, ""),
            ))

    total = len(_AGENT_CAPABILITIES)
    missing = len(gaps)
    score = int(((total - missing) / total) * 100) if total else 100

    return AgentCapabilityGapReport(target=target, gaps=gaps, coverage_score=score)


def build_all_agent_gap_reports(
    targets: list[str] | None = None,
) -> list[AgentCapabilityGapReport]:
    """Build agent capability gap reports for all (or specified) target harnesses.

    Args:
        targets: Harness names to report. Defaults to all known harnesses.

    Returns:
        List of AgentCapabilityGapReport sorted by coverage_score descending.
    """
    target_list = targets or list(_HARNESS_AGENT_CAPABILITIES.keys())
    reports = [build_agent_gap_report(t) for t in target_list]
    return sorted(reports, key=lambda r: r.coverage_score, reverse=True)


def format_agent_gap_summary(reports: list[AgentCapabilityGapReport]) -> str:
    """Format all agent gap reports as a compact summary table.

    Args:
        reports: List of AgentCapabilityGapReport from build_all_agent_gap_reports().

    Returns:
        Multi-line table string.
    """
    if not reports:
        return "No agent capability gap data available."

    col_w = 10
    cap_w = 24
    header = f"{'Capability':<{cap_w}}" + "".join(f"  {t[:col_w - 1]:<{col_w - 1}}" for t in [r.target for r in reports])
    sep = "-" * len(header)

    lines = ["Agent Capability Gap Summary", "=" * max(len(sep), 40), "", header, sep]

    for cap in _AGENT_CAPABILITIES:
        row = f"{cap:<{cap_w}}"
        for report in reports:
            target_has = _HARNESS_AGENT_CAPABILITIES.get(report.target, {}).get(cap)
            cell = "✓" if target_has else ("✗" if target_has is False else "?")
            row += f"  {cell:>{col_w - 1}}"
        lines.append(row)

    lines += [sep, "", "Coverage scores:"]
    for report in reports:
        lines.append(f"  {report.target:<20} {report.coverage_score:>3}/100")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Item 21 — Skill Coverage Report (per-target percentage)
# ---------------------------------------------------------------------------


@dataclass
class SkillCoverageEntry:
    """Coverage data for one (skill, target) pair."""

    skill_name: str
    target: str
    present: bool           # True if skill file exists in target location
    translation_score: int  # 0–100 (from score_skill_file, 0 if not present)


@dataclass
class SkillCoverageReport:
    """Coverage percentages for all skills across all active targets.

    Args:
        entries: All (skill, target) coverage pairs.
        source_skills: List of skill names from Claude Code.
        targets: Active sync targets checked.
    """

    entries: list[SkillCoverageEntry]
    source_skills: list[str]
    targets: list[str]

    def coverage_pct(self, target: str) -> float:
        """Return the percentage of skills present in *target* (0.0–100.0)."""
        target_entries = [e for e in self.entries if e.target == target]
        if not target_entries:
            return 0.0
        present = sum(1 for e in target_entries if e.present)
        return (present / len(target_entries)) * 100.0

    def avg_translation_score(self, target: str) -> float:
        """Return average translation quality score for *target* (0.0–100.0)."""
        target_entries = [e for e in self.entries if e.target == target and e.present]
        if not target_entries:
            return 0.0
        return sum(e.translation_score for e in target_entries) / len(target_entries)

    def format(self) -> str:
        """Return a formatted coverage report table."""
        if not self.source_skills or not self.targets:
            return "No skills or targets to report."

        col_skill = max(14, max(len(s) for s in self.source_skills) + 2)
        col_target = 14
        header = f"  {'Skill':<{col_skill}}" + "".join(f"{t:^{col_target}}" for t in self.targets)
        sep = "  " + "-" * (col_skill + col_target * len(self.targets))

        lines = [
            "Skill Coverage Report",
            "=" * (col_skill + col_target * len(self.targets) + 4),
            "",
            "Coverage = skill file present in target location",
            "Score    = translation quality (0–100, higher = more faithful)",
            "",
            header,
            sep,
        ]

        for skill in self.source_skills:
            row = f"  {skill:<{col_skill}}"
            for target in self.targets:
                matching = [e for e in self.entries if e.skill_name == skill and e.target == target]
                if not matching:
                    row += f"{'—':^{col_target}}"
                    continue
                entry = matching[0]
                if entry.present:
                    row += f"{'✓ ' + str(entry.translation_score):^{col_target}}"
                else:
                    row += f"{'✗':^{col_target}}"
            lines.append(row)

        lines.append(sep)

        # Summary row with coverage percentages
        pct_row = f"  {'Coverage %':<{col_skill}}"
        for target in self.targets:
            pct = self.coverage_pct(target)
            cell = f"{pct:.0f}%"
            pct_row += f"{cell:^{col_target}}"
        lines.append(pct_row)

        avg_row = f"  {'Avg score':<{col_skill}}"
        for target in self.targets:
            avg = self.avg_translation_score(target)
            cell = f"{avg:.0f}"
            avg_row += f"{cell:^{col_target}}"
        lines.append(avg_row)

        lines.append("")
        lines.append("  ✓ = present, ✗ = missing/not synced, number = translation score")
        return "\n".join(lines)


def build_skill_coverage_report(
    skills_dir: Path,
    project_dir: Path,
    targets: list[str] | None = None,
) -> SkillCoverageReport:
    """Build a skill coverage report for all skills across active targets.

    Args:
        skills_dir: Claude Code skills directory (e.g. ~/.claude/skills/).
        project_dir: Project root for detecting active target configs.
        targets: Targets to check. Auto-detects if None.

    Returns:
        SkillCoverageReport with per-skill, per-target coverage data.
    """
    from src.skill_translator import score_skill_file

    # Discover source skills
    source_skills: dict[str, Path] = {}
    if skills_dir.is_dir():
        for item in sorted(skills_dir.iterdir()):
            if item.is_file() and item.suffix == ".md":
                source_skills[item.stem] = item
            elif item.is_dir():
                candidate = item / "SKILL.md"
                if candidate.is_file():
                    source_skills[item.name] = candidate

    # Determine targets
    if targets is None:
        analyzer = SkillGapAnalyzer(project_dir)
        targets = analyzer._detect_active_targets()

    entries: list[SkillCoverageEntry] = []
    for skill_name, skill_path in source_skills.items():
        for target in targets:
            # Check if a translated version exists in the target location
            present = _check_skill_in_target(skill_name, target, project_dir)
            score = 0
            if present:
                try:
                    result = score_skill_file(skill_path, target)
                    score = result.get("score", 0)
                except Exception:
                    score = 50  # default when scoring fails

            entries.append(SkillCoverageEntry(
                skill_name=skill_name,
                target=target,
                present=present,
                translation_score=score,
            ))

    return SkillCoverageReport(
        entries=entries,
        source_skills=list(source_skills.keys()),
        targets=targets,
    )


def post_sync_capability_report(
    synced_targets: list[str],
    project_dir: Path | None = None,
) -> str:
    """Generate a compact capability gap summary to display after a sync.

    Surfaces which Claude Code capabilities are unavailable in each target
    that was just synced, with suggested workarounds.  Returns an empty
    string when all targets support all capabilities (nothing to warn about).

    This is the *post-sync alert* described in product-ideation item 5:
    "After each sync, report which Claude Code capabilities have no
    equivalent in each target and suggest workarounds."

    Args:
        synced_targets: List of harness names that were synced in this run.
        project_dir: Project root (unused currently, reserved for future
                     per-project capability overrides).

    Returns:
        Human-readable capability gap summary, or empty string if no gaps.
    """
    if not synced_targets:
        return ""

    reports = [build_agent_gap_report(t) for t in synced_targets]
    gapped = [r for r in reports if r.gaps]
    if not gapped:
        return ""

    lines = ["", "## Post-Sync Capability Alerts", ""]
    for report in gapped:
        cap_names = ", ".join(g.capability for g in report.gaps)
        lines.append(
            f"  {report.target} ({report.coverage_score}/100): "
            f"missing — {cap_names}"
        )
        for gap in report.gaps:
            if gap.workaround:
                lines.append(f"    → {gap.capability}: {gap.workaround}")
    lines += [
        "",
        "  Run /sync-gaps for a full capability analysis.",
    ]
    return "\n".join(lines)


def _check_skill_in_target(skill_name: str, target: str, project_dir: Path) -> bool:
    """Check if a skill has been synced to the target harness location.

    Args:
        skill_name: Name of the skill.
        target: Target harness name.
        project_dir: Project root.

    Returns:
        True if the skill file exists in the target's expected location.
    """
    target_paths: dict[str, list[Path]] = {
        "codex":    [project_dir / ".agents" / "skills" / skill_name / "SKILL.md"],
        "gemini":   [project_dir / ".gemini" / "skills" / skill_name / "SKILL.md"],
        "opencode": [project_dir / ".opencode" / "skills" / skill_name / "SKILL.md"],
        "cursor":   [project_dir / ".cursor" / "rules" / "skills" / f"{skill_name}.mdc"],
        "aider":    [],  # Aider embeds skills in CONVENTIONS.md — not a discrete file
        "windsurf": [project_dir / ".windsurf" / "memories" / f"{skill_name}.md"],
        "cline":    [project_dir / ".roo" / "rules" / "skills" / f"{skill_name}.md"],
        "continue": [project_dir / ".continue" / "rules" / "skills" / f"{skill_name}.md"],
    }
    candidates = target_paths.get(target, [])
    return any(p.exists() for p in candidates)
