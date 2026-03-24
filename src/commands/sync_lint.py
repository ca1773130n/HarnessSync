from __future__ import annotations

"""
/sync-lint slash command implementation.

Validates the source Claude Code config before sync, reporting issues
without modifying any files.

Flags:
  --scope user|project|all   Scope to lint (default: all)
  --ci                       Machine-readable JSON output; exit 0=ok, 1=warnings, 2=errors
  --fix                      Apply safe auto-fixes to CLAUDE.md and report changes
  --format text|json         Output format (--ci implies json)
  --dead                     Detect dead/orphaned config items (unused rules, skills, etc.)
  --dead-days N              Staleness threshold for --dead (default: 30 days)
  --quality                  Run semantic quality analysis: vague instructions, contradictions,
                             security risks, duplicate rules, overly-broad permissions
"""

import json
import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.config_linter import ConfigLinter
from src.source_reader import SourceReader
from src.dead_config_detector import DeadConfigDetector, UsageTracker


def _find_claude_md(project_dir: Path) -> Path | None:
    """Return path to project CLAUDE.md if it exists."""
    p = project_dir / "CLAUDE.md"
    return p if p.exists() else None


def main() -> None:
    """Entry point for /sync-lint command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-lint",
        description="Validate Claude Code config before sync",
    )
    parser.add_argument("--scope", default="all", choices=["user", "project", "all"])
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: emit machine-readable JSON; exit 0=ok, 1=warnings, 2=errors",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply safe auto-fixes to CLAUDE.md and show what changed",
    )
    parser.add_argument(
        "--format",
        default="text",
        choices=["text", "json"],
        help="Output format (--ci implies json)",
    )
    parser.add_argument(
        "--skills",
        action="store_true",
        help=(
            "Run skill portability linter: flag Claude Code-specific patterns in "
            "SKILL.md files that won't translate to Cursor, Gemini, Aider, etc."
        ),
    )
    parser.add_argument("--project-dir", type=str, default=None)
    parser.add_argument(
        "--pre-flight",
        action="store_true",
        dest="pre_flight",
        help=(
            "Validate source config against known adapter constraints before sync. "
            "Checks MCP transport compatibility, secret-like env vars, and unsupported features."
        ),
    )
    parser.add_argument(
        "--dead",
        action="store_true",
        help=(
            "Detect dead/orphaned config items: skills, rules, agents, and commands "
            "that are unused or have no active sync target."
        ),
    )
    parser.add_argument(
        "--dead-days",
        type=int,
        default=30,
        dest="dead_days",
        metavar="N",
        help="Staleness threshold in days for usage-based dead detection (default: 30)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    ci_mode: bool = args.ci
    output_json: bool = ci_mode or args.format == "json"
    apply_fixes: bool = args.fix
    scope: str = args.scope
    check_skills: bool = getattr(args, "skills", False)
    check_dead: bool = getattr(args, "dead", False)
    dead_days: int = getattr(args, "dead_days", 30)
    check_pre_flight: bool = getattr(args, "pre_flight", False)
    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    if not ci_mode:
        print("HarnessSync Config Lint")
        print("=" * 50)

    try:
        reader = SourceReader(scope=scope, project_dir=project_dir)
        source_data = reader.discover_all()
    except Exception as e:
        if output_json:
            print(json.dumps({"error": str(e), "issues": [], "fixes_applied": []}))
        else:
            print(f"Error reading config: {e}", file=sys.stderr)
        sys.exit(2)

    linter = ConfigLinter()
    linter.load_custom_rules(project_dir)

    issues = linter.lint(source_data, project_dir)
    fixes_applied: list[str] = []

    # Apply auto-fixes if requested
    if apply_fixes:
        claude_md = _find_claude_md(project_dir)
        if claude_md:
            content = claude_md.read_text(encoding="utf-8")
            fix_suggestions = linter.suggest_fixes(source_data, project_dir)
            auto_fixable = [f for f in fix_suggestions if f.auto_fixable]
            if auto_fixable:
                new_content = linter.apply_fixes(content, auto_fixable)
                if new_content != content:
                    claude_md.write_text(new_content, encoding="utf-8")
                    fixes_applied = [f.issue for f in auto_fixable]
                    if not ci_mode:
                        print(f"Applied {len(fixes_applied)} auto-fix(es) to {claude_md}:")
                        for fix_desc in fixes_applied:
                            print(f"  - {fix_desc}")
                        print()
                else:
                    if not ci_mode:
                        print("No auto-fixable issues found in CLAUDE.md.")
            else:
                if not ci_mode:
                    print("No auto-fixable issues found.")
        else:
            if not ci_mode:
                print("CLAUDE.md not found; no fixes to apply.")

    # Determine severity of each issue
    def _issue_severity(issue: str) -> str:
        low = issue.lower()
        if "error" in low or "invalid" in low or "missing" in low:
            return "error"
        return "warning"

    has_errors = any(_issue_severity(i) == "error" for i in issues)
    has_issues = bool(issues)

    # Skill portability check (--skills flag)
    skill_portability_issues: dict = {}
    skill_linter_reports: dict = {}
    if check_skills:
        skills = source_data.get("skills", {})
        if skills:
            skill_portability_issues = linter.lint_all_skills_portability(skills)
            # Also run the focused per-harness linter for inline fix suggestions
            try:
                from src.analysis.skill_linter import SkillLinter
                _sl = SkillLinter()
                skill_linter_reports = _sl.lint_all(skills)
            except Exception:
                pass

    if output_json:
        payload = {
            "ok": not issues and not skill_portability_issues,
            "issue_count": len(issues),
            "issues": [
                {"message": issue, "severity": _issue_severity(issue)}
                for issue in issues
            ],
            "fixes_applied": fixes_applied,
            "skill_portability": skill_portability_issues,
        }
        print(json.dumps(payload, indent=2))
        if has_errors:
            sys.exit(2)
        elif has_issues or skill_portability_issues:
            sys.exit(1)
        sys.exit(0)

    # Human-readable text output
    if not issues:
        if not apply_fixes or not fixes_applied:
            print("No issues found. Config looks good!")
        else:
            print("No issues remain after fixes.")
    else:
        print(f"Found {len(issues)} issue(s):\n")
        for i, issue in enumerate(issues, 1):
            print(f"  {i}. {issue}")
        print()
        if not apply_fixes:
            fix_suggestions = linter.suggest_fixes(source_data, project_dir)
            auto_fixable_count = sum(1 for f in fix_suggestions if f.auto_fixable)
            if auto_fixable_count:
                print(f"  {auto_fixable_count} issue(s) can be auto-fixed. Run /sync-lint --fix to apply.")
        print("Fix these issues before syncing to prevent unexpected behavior.")

    # Skill portability report
    if check_skills:
        if skill_linter_reports:
            print()
            from src.analysis.skill_linter import SkillLinter
            print(SkillLinter().format_all_reports(skill_linter_reports))
        elif skill_portability_issues:
            print()
            print(linter.format_skill_portability_report(skill_portability_issues))
        elif source_data.get("skills"):
            print("\nSkill portability: All skills look portable.")
        else:
            print("\nSkill portability: No skills found to check.")

    # Dead config detection (--dead flag)
    dead_report = None
    stale_items: list[dict] = []
    if check_dead:
        try:
            detector = DeadConfigDetector(project_dir=project_dir)
            dead_report = detector.detect(source_data=source_data, stale_days=dead_days)

            # Usage-based staleness via UsageTracker
            tracker = UsageTracker()
            names: dict[str, list[str]] = {}
            for cat in ("skill", "agent", "command"):
                items = source_data.get(cat + "s", {})
                if items:
                    names[cat] = list(items.keys())
            if names:
                stale_items = tracker.find_stale(names, days=dead_days)
        except Exception as exc:
            if not ci_mode:
                print(f"\nDead config detection error: {exc}", file=sys.stderr)

        if output_json:
            dead_payload: dict = {
                "dead_config": {
                    "total_issues": dead_report.total_issues if dead_report else 0,
                    "source_no_target": [
                        {"category": i.category, "name": i.name, "detail": i.detail}
                        for i in (dead_report.source_no_target if dead_report else [])
                    ],
                    "target_orphans": [
                        {"category": i.category, "name": i.name, "detail": i.detail}
                        for i in (dead_report.target_orphans if dead_report else [])
                    ],
                    "stale_items": stale_items,
                }
            }
            # Merge into existing payload or print separately
            print(json.dumps(dead_payload, indent=2))
        else:
            print()
            if dead_report:
                print(dead_report.format())
            if stale_items:
                print(f"\nUsage-stale items (not used in {dead_days}+ days):")
                for item in stale_items:
                    ago = item.get("last_used_days_ago")
                    age_str = f"{ago:.0f}d ago" if ago is not None else "never used"
                    print(f"  [{item['category']}] {item['name']}  ({age_str})")
                print(
                    "\nRemove unused items or run /sync to reset the usage counter.\n"
                    "Re-run with --dead-days N to adjust the staleness threshold."
                )
            elif dead_report and dead_report.is_clean() and not stale_items:
                pass  # already printed clean message from dead_report.format()

    # Pre-flight adapter constraint check (--pre-flight flag)
    pre_flight_warnings: list[dict] = []
    if check_pre_flight:
        try:
            pre_flight_warnings = linter.pre_flight_check(source_data)
        except Exception as exc:
            if not ci_mode:
                print(f"\nPre-flight check error: {exc}", file=sys.stderr)

        if output_json:
            print(json.dumps({"pre_flight_warnings": pre_flight_warnings}, indent=2))
        elif pre_flight_warnings:
            print()
            print(f"Pre-Flight Warnings ({len(pre_flight_warnings)}):")
            print("-" * 50)
            for w in pre_flight_warnings:
                adapter_label = f"[{w['adapter']}]"
                print(f"  {adapter_label:<12} {w['message']}")
                print(f"               Remediation: {w['remediation']}")
            print()
        else:
            if not ci_mode:
                print("\nPre-flight: No adapter compatibility issues found.")

    if has_errors:
        sys.exit(2)
    if has_issues or skill_portability_issues:
        sys.exit(1)
    if dead_report and not dead_report.is_clean():
        sys.exit(1)
    if pre_flight_warnings:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
