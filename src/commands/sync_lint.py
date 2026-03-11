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
    parser.add_argument("--project-dir", type=str, default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    ci_mode: bool = args.ci
    output_json: bool = ci_mode or args.format == "json"
    apply_fixes: bool = args.fix
    scope: str = args.scope
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

    if output_json:
        payload = {
            "ok": not issues,
            "issue_count": len(issues),
            "issues": [
                {"message": issue, "severity": _issue_severity(issue)}
                for issue in issues
            ],
            "fixes_applied": fixes_applied,
        }
        print(json.dumps(payload, indent=2))
        if has_errors:
            sys.exit(2)
        elif has_issues:
            sys.exit(1)
        sys.exit(0)

    # Human-readable text output
    if not issues:
        if not apply_fixes or not fixes_applied:
            print("No issues found. Config looks good!")
        else:
            print("No issues remain after fixes.")
        sys.exit(0)

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

    if has_errors:
        sys.exit(2)
    sys.exit(1)


if __name__ == "__main__":
    main()
