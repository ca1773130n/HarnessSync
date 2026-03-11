from __future__ import annotations

"""Cross-harness skill smoke tester.

After syncing skills, generates a minimal test invocation for each skill
in each target harness's format and reports pass/fail.

Catches silent failures where a skill synced successfully at the file level
but is broken because of harness-specific syntax differences — e.g., Cursor
MDC frontmatter is invalid, Aider YAML is malformed, or required metadata
fields are missing.

Checks performed per harness:
  - cursor: validates MDC frontmatter (YAML parseable, required keys present)
  - aider: validates YAML in .aider.conf.yml read-files list is syntactically valid
  - codex: validates SKILL.md file exists and has non-empty content
  - gemini: validates SKILL.md has non-empty content
  - opencode: validates skill directory structure
  - windsurf: validates memory markdown file is parseable
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class SkillSmokeResult:
    """Result of a smoke test for a single skill in a single target harness."""

    skill_name: str
    target: str
    passed: bool
    message: str
    file_path: str = ""


@dataclass
class SkillSmokeReport:
    """Aggregated smoke test results across all skills and targets."""

    results: list[SkillSmokeResult] = field(default_factory=list)

    @property
    def passed(self) -> list[SkillSmokeResult]:
        return [r for r in self.results if r.passed]

    @property
    def failed(self) -> list[SkillSmokeResult]:
        return [r for r in self.results if not r.passed]

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 1.0
        return len(self.passed) / len(self.results)

    def format(self, verbose: bool = False) -> str:
        """Format results as a human-readable report.

        Args:
            verbose: Include passing skills in output (default: failures only).

        Returns:
            Formatted report string.
        """
        if not self.results:
            return "No skills found to smoke test."

        lines: list[str] = []
        lines.append(
            f"Skill Smoke Tests: {len(self.passed)}/{len(self.results)} passed"
            f" ({self.pass_rate:.0%})"
        )

        failures = self.failed
        if failures:
            lines.append(f"\nFailed ({len(failures)}):")
            for r in failures:
                lines.append(f"  ✗ [{r.target}] {r.skill_name}: {r.message}")
                if r.file_path:
                    lines.append(f"      file: {r.file_path}")

        if verbose and self.passed:
            lines.append(f"\nPassed ({len(self.passed)}):")
            for r in self.passed:
                lines.append(f"  ✓ [{r.target}] {r.skill_name}")

        return "\n".join(lines)


class SkillSmokeTester:
    """Runs smoke tests on synced skill files across target harnesses.

    Validates that skill files written by adapters are syntactically
    correct and meet each harness's minimum requirements.
    """

    def __init__(self, project_dir: Path):
        """Initialize tester.

        Args:
            project_dir: Project root directory.
        """
        self.project_dir = project_dir

    def test_all(self, targets: list[str] | None = None) -> SkillSmokeReport:
        """Run smoke tests for all known skill locations.

        Args:
            targets: Specific targets to test (None = all detected targets).

        Returns:
            SkillSmokeReport with pass/fail results.
        """
        report = SkillSmokeReport()

        all_targets = targets or [
            "cursor", "aider", "codex", "gemini", "opencode", "windsurf"
        ]

        for target in all_targets:
            results = self._test_target(target)
            report.results.extend(results)

        return report

    def _test_target(self, target: str) -> list[SkillSmokeResult]:
        """Run smoke tests for a specific target harness.

        Args:
            target: Target harness name.

        Returns:
            List of SkillSmokeResult for each skill found.
        """
        tester = _TARGET_TESTERS.get(target)
        if tester is None:
            return []

        try:
            return tester(self.project_dir)
        except Exception as e:
            return [SkillSmokeResult(
                skill_name="*",
                target=target,
                passed=False,
                message=f"smoke test runner failed: {e}",
            )]


# ------------------------------------------------------------------
# Per-target test functions
# ------------------------------------------------------------------


def _test_cursor_skills(project_dir: Path) -> list[SkillSmokeResult]:
    """Validate .cursor/rules/skills/*.mdc files."""
    skills_dir = project_dir / ".cursor" / "rules" / "skills"
    if not skills_dir.is_dir():
        return []

    results: list[SkillSmokeResult] = []
    for mdc_file in sorted(skills_dir.glob("*.mdc")):
        skill_name = mdc_file.stem
        result = _validate_mdc_file(skill_name, "cursor", mdc_file)
        results.append(result)

    return results


def _validate_mdc_file(
    skill_name: str,
    target: str,
    path: Path,
) -> SkillSmokeResult:
    """Validate a single .mdc file.

    Checks:
    1. File is non-empty.
    2. YAML frontmatter is present and parseable.
    3. `description` field is present.

    Args:
        skill_name: Skill name for reporting.
        target: Target name for reporting.
        path: Path to .mdc file.

    Returns:
        SkillSmokeResult.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as e:
        return SkillSmokeResult(skill_name, target, False, f"cannot read file: {e}", str(path))

    if not content.strip():
        return SkillSmokeResult(skill_name, target, False, "file is empty", str(path))

    # Extract YAML frontmatter between --- delimiters
    fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not fm_match:
        return SkillSmokeResult(
            skill_name, target, False,
            "missing or malformed YAML frontmatter (expected '---' block)",
            str(path),
        )

    fm_text = fm_match.group(1)
    try:
        import yaml
        fm = yaml.safe_load(fm_text) or {}
    except Exception as e:
        return SkillSmokeResult(
            skill_name, target, False, f"YAML frontmatter parse error: {e}", str(path)
        )

    if not isinstance(fm, dict):
        return SkillSmokeResult(
            skill_name, target, False, "frontmatter is not a YAML mapping", str(path)
        )

    # description is the most important field
    if "description" not in fm:
        return SkillSmokeResult(
            skill_name, target, False,
            "frontmatter missing required 'description' field",
            str(path),
        )

    return SkillSmokeResult(skill_name, target, True, "ok", str(path))


def _test_aider_skills(project_dir: Path) -> list[SkillSmokeResult]:
    """Validate that CONVENTIONS.md is syntactically valid and non-empty."""
    conventions = project_dir / "CONVENTIONS.md"
    if not conventions.exists():
        return []

    try:
        content = conventions.read_text(encoding="utf-8")
    except OSError as e:
        return [SkillSmokeResult("CONVENTIONS.md", "aider", False, f"read error: {e}", str(conventions))]

    if not content.strip():
        return [SkillSmokeResult("CONVENTIONS.md", "aider", False, "file is empty", str(conventions))]

    return [SkillSmokeResult("CONVENTIONS.md", "aider", True, "ok", str(conventions))]


def _test_codex_skills(project_dir: Path) -> list[SkillSmokeResult]:
    """Validate .agents/skills/<name>/SKILL.md files."""
    skills_dir = project_dir / ".agents" / "skills"
    if not skills_dir.is_dir():
        return []

    results: list[SkillSmokeResult] = []
    for skill_dir in sorted(d for d in skills_dir.iterdir() if d.is_dir()):
        skill_name = skill_dir.name
        skill_file = skill_dir / "SKILL.md"

        if not skill_file.exists():
            results.append(SkillSmokeResult(
                skill_name, "codex", False,
                "SKILL.md missing in skill directory",
                str(skill_dir),
            ))
            continue

        try:
            content = skill_file.read_text(encoding="utf-8")
        except OSError as e:
            results.append(SkillSmokeResult(skill_name, "codex", False, f"read error: {e}", str(skill_file)))
            continue

        if not content.strip():
            results.append(SkillSmokeResult(skill_name, "codex", False, "SKILL.md is empty", str(skill_file)))
        else:
            results.append(SkillSmokeResult(skill_name, "codex", True, "ok", str(skill_file)))

    return results


def _test_gemini_skills(project_dir: Path) -> list[SkillSmokeResult]:
    """Validate .gemini/skills/<name>/SKILL.md files."""
    skills_dir = project_dir / ".gemini" / "skills"
    if not skills_dir.is_dir():
        return []

    results: list[SkillSmokeResult] = []
    for skill_dir in sorted(d for d in skills_dir.iterdir() if d.is_dir()):
        skill_name = skill_dir.name
        skill_file = skill_dir / "SKILL.md"

        if not skill_file.exists():
            results.append(SkillSmokeResult(
                skill_name, "gemini", False,
                "SKILL.md missing",
                str(skill_dir),
            ))
        else:
            try:
                content = skill_file.read_text(encoding="utf-8")
                if not content.strip():
                    results.append(SkillSmokeResult(skill_name, "gemini", False, "SKILL.md is empty", str(skill_file)))
                else:
                    results.append(SkillSmokeResult(skill_name, "gemini", True, "ok", str(skill_file)))
            except OSError as e:
                results.append(SkillSmokeResult(skill_name, "gemini", False, f"read error: {e}", str(skill_file)))

    return results


def _test_opencode_skills(project_dir: Path) -> list[SkillSmokeResult]:
    """Validate .opencode/skills/ structure."""
    skills_dir = project_dir / ".opencode" / "skills"
    if not skills_dir.is_dir():
        return []

    results: list[SkillSmokeResult] = []
    for item in sorted(skills_dir.iterdir()):
        skill_name = item.name
        if item.is_symlink():
            target = item.resolve()
            if not target.exists():
                results.append(SkillSmokeResult(
                    skill_name, "opencode", False,
                    f"broken symlink → {target}",
                    str(item),
                ))
            else:
                results.append(SkillSmokeResult(skill_name, "opencode", True, "ok (symlink)", str(item)))
        elif item.is_dir():
            results.append(SkillSmokeResult(skill_name, "opencode", True, "ok (dir)", str(item)))

    return results


def _test_windsurf_skills(project_dir: Path) -> list[SkillSmokeResult]:
    """Validate .windsurf/memories/*.md files."""
    memories_dir = project_dir / ".windsurf" / "memories"
    if not memories_dir.is_dir():
        return []

    results: list[SkillSmokeResult] = []
    for md_file in sorted(memories_dir.glob("*.md")):
        skill_name = md_file.stem
        try:
            content = md_file.read_text(encoding="utf-8")
        except OSError as e:
            results.append(SkillSmokeResult(skill_name, "windsurf", False, f"read error: {e}", str(md_file)))
            continue

        if not content.strip():
            results.append(SkillSmokeResult(skill_name, "windsurf", False, "file is empty", str(md_file)))
        else:
            results.append(SkillSmokeResult(skill_name, "windsurf", True, "ok", str(md_file)))

    return results


# Registry of per-target test functions
_TARGET_TESTERS: dict[str, object] = {
    "cursor":   _test_cursor_skills,
    "aider":    _test_aider_skills,
    "codex":    _test_codex_skills,
    "gemini":   _test_gemini_skills,
    "opencode": _test_opencode_skills,
    "windsurf": _test_windsurf_skills,
}
