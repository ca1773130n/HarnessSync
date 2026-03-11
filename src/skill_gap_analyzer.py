from __future__ import annotations

"""Skill gap analyzer for HarnessSync.

Shows which Claude Code skills have no equivalent in target harnesses and
vice versa. Highlights functionality the user is losing when switching
harnesses and motivates writing adapter approximations.

Also identifies skills that exist in target harnesses but have no source in
Claude Code (orphaned skill copies).
"""

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
