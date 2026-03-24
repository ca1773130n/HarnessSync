from __future__ import annotations

"""Skill portability linter with per-harness incompatibility analysis.

Scans skill .md files for patterns that are Claude Code-specific and
won't work in Codex, Gemini, Cursor, Aider, or other harnesses.

Each issue includes:
- The affected harnesses (e.g. "Gemini, Codex")
- The line number
- An inline fix suggestion

Usage:
    from src.analysis.skill_linter import SkillLinter
    linter = SkillLinter()
    report = linter.lint_file(Path("skills/playwright.md"))
    print(linter.format_report(report))
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillIssue:
    """A single portability issue found in a skill file."""
    line: int
    code: str
    description: str
    # Harnesses where this issue causes incompatibility
    affected_harnesses: list[str]
    fix: str
    raw_text: str = ""


@dataclass
class SkillReport:
    """Linting report for a single skill file."""
    skill_name: str
    skill_path: Path
    issues: list[SkillIssue] = field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def is_clean(self) -> bool:
        return len(self.issues) == 0


# --- Pattern registry ---
# Each entry: (regex, code, description_template, affected_harnesses, fix_template)
_CHECKS: list[tuple[re.Pattern, str, str, list[str], str]] = [
    (
        re.compile(r"\bmcp__\w+__\w+\b"),
        "MCP_TOOL_CALL",
        "MCP tool call `{match}` is Claude Code-specific",
        ["Gemini", "Codex", "Cursor", "Aider", "Windsurf"],
        "wrap in an availability check or provide a non-MCP fallback",
    ),
    (
        re.compile(r"(?<!\w)/(commit|review-pr|sync|hookify|grd:|harness-sync:)\S*"),
        "CC_SLASH_CMD",
        "Claude Code slash command `{match}` is not available in other harnesses",
        ["Gemini", "Codex", "Cursor", "Aider"],
        "replace with plain-text instruction or make the step conditional on harness",
    ),
    (
        re.compile(r"\.claude/"),
        "CLAUDE_DIR_REF",
        "Reference to `.claude/` directory is Claude Code-specific",
        ["Gemini", "Codex", "Cursor", "Aider", "Windsurf"],
        "use a relative path or a harness-agnostic config variable instead",
    ),
    (
        re.compile(r"(?:^|[^a-zA-Z0-9_/])(/(?:Users|home|root)/[^\s\"']+)"),
        "ABSOLUTE_PATH",
        "Absolute file path `{match}` is not portable across machines",
        ["Gemini", "Codex", "Cursor", "Aider", "Windsurf"],
        "replace with a relative path or an environment variable like $HOME",
    ),
    (
        re.compile(r"\bTodoWrite\b|\bWebFetch\b|\bWebSearch\b|\bAgent\b|\bBash\b|\bGlob\b|\bGrep\b|\bRead\b|\bEdit\b|\bWrite\b"),
        "CC_TOOL_NAME",
        "Claude Code internal tool name `{match}` referenced directly",
        ["Gemini", "Codex"],
        "describe the action in natural language instead of using the tool name",
    ),
    (
        re.compile(r"CLAUDE\.md", re.IGNORECASE),
        "CLAUDE_MD_REF",
        "Reference to `CLAUDE.md` — Gemini uses `GEMINI.md`, Codex uses `AGENTS.md`",
        ["Gemini", "Codex"],
        "use a harness-agnostic term like 'project instructions file' or check at runtime",
    ),
    (
        re.compile(r"settings\.(?:local\.)?json"),
        "CC_SETTINGS_FILE",
        "Reference to Claude Code `settings.json` is harness-specific",
        ["Gemini", "Codex", "Cursor", "Aider"],
        "abstract behind a configuration variable or document the harness-specific equivalent",
    ),
]


class SkillLinter:
    """Lints skill markdown files for cross-harness portability issues."""

    def lint_file(self, path: Path, skill_name: str | None = None) -> SkillReport:
        """Lint a single skill markdown file.

        Args:
            path: Path to the .md skill file (or skill directory with SKILL.md).
            skill_name: Optional display name; defaults to path stem.

        Returns:
            SkillReport with all discovered issues.
        """
        if path.is_dir():
            candidate = path / "SKILL.md"
            if candidate.is_file():
                path = candidate
            else:
                # Try any .md file in the directory
                mds = list(path.glob("*.md"))
                if mds:
                    path = mds[0]

        name = skill_name or path.stem
        report = SkillReport(skill_name=name, skill_path=path)

        if not path.is_file():
            report.issues.append(SkillIssue(
                line=0,
                code="MISSING_FILE",
                description=f"Skill file not found: {path}",
                affected_harnesses=[],
                fix="Create the skill file.",
            ))
            return report

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            report.issues.append(SkillIssue(
                line=0,
                code="READ_ERROR",
                description=f"Cannot read skill file: {e}",
                affected_harnesses=[],
                fix="Check file permissions.",
            ))
            return report

        lines = content.splitlines()
        for lineno, line in enumerate(lines, start=1):
            for pattern, code, description_tmpl, harnesses, fix_tmpl in _CHECKS:
                m = pattern.search(line)
                if m:
                    match_text = m.group(0).strip()
                    description = description_tmpl.format(match=match_text)
                    report.issues.append(SkillIssue(
                        line=lineno,
                        code=code,
                        description=description,
                        affected_harnesses=harnesses,
                        fix=fix_tmpl,
                        raw_text=line.strip(),
                    ))

        return report

    def lint_all(self, skills: dict[str, Path]) -> dict[str, SkillReport]:
        """Lint all skills in a skills dict.

        Args:
            skills: Mapping of skill_name -> path (from SourceReader).

        Returns:
            Mapping of skill_name -> SkillReport (only skills with issues).
        """
        results: dict[str, SkillReport] = {}
        for name, path in (skills or {}).items():
            report = self.lint_file(Path(path) if not isinstance(path, Path) else path, skill_name=name)
            if not report.is_clean:
                results[name] = report
        return results

    def format_report(self, report: SkillReport) -> str:
        """Format a single SkillReport as human-readable text with inline fixes."""
        if report.is_clean:
            return f"{report.skill_path}: no portability issues"

        lines: list[str] = [
            f"{report.skill_path}: {report.issue_count} issue(s)",
        ]
        for issue in report.issues:
            harness_str = ", ".join(issue.affected_harnesses) if issue.affected_harnesses else "all harnesses"
            lines.append(
                f"  line {issue.line}: [{issue.code}] {issue.description} "
                f"(not available in: {harness_str})"
            )
            lines.append(f"    fix: {issue.fix}")
        return "\n".join(lines)

    def format_all_reports(self, reports: dict[str, SkillReport]) -> str:
        """Format multiple skill reports as a combined portability report."""
        if not reports:
            return "Skill portability linter: all skills are portable across harnesses."

        total_issues = sum(r.issue_count for r in reports.values())
        out: list[str] = [
            f"Skill Portability Linter — {total_issues} issue(s) in {len(reports)} skill(s)",
            "=" * 60,
            "",
        ]
        for name, report in sorted(reports.items()):
            out.append(self.format_report(report))
            out.append("")
        return "\n".join(out).rstrip()
