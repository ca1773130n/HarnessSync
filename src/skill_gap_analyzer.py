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
