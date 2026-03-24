from __future__ import annotations

"""
/sync-score command — portability grade for your Claude Code config.

Computes a 0-100 portability score broken into four sub-scores:
  - Skill portability  (% of skills with zero harness-specific patterns)
  - MCP dependency breadth  (fraction of skills NOT blocked by unavailable MCP)
  - Path hygiene  (% of config files using relative paths)
  - Settings coverage  (% of settings keys that map to ≥1 harness target)

Each sub-score includes the top 2 specific fixes to improve it.
"""

import json
import os
import re
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path


# MCP tools that are unavailable in specific harnesses
_HARNESS_UNAVAILABLE_MCP: dict[str, set[str]] = {
    "codex": {"playwright", "github", "context7", "context-mode", "slack", "jira"},
    "gemini": {"playwright", "context-mode"},
    "cursor": set(),
    "aider": {"playwright", "github", "context7", "context-mode"},
    "windsurf": set(),
}

# Settings keys that have known harness equivalents
_SETTINGS_WITH_TARGET_SUPPORT = {
    "theme", "model", "autoApprove", "permissions", "env",
    "mcpServers", "disableNonEssentialTraffic",
}

_ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s\"'])(/(?:Users|home|root|var|opt|tmp)/\S+)")
_MCP_TOOL_RE = re.compile(r"\bmcp__(\w+)__\w+\b")


def _score_skill_portability(skills: dict, project_dir: Path) -> tuple[int, list[str]]:
    """Return (score 0-100, top fixes)."""
    if not skills:
        return 100, []

    try:
        from src.analysis.skill_linter import SkillLinter
        linter = SkillLinter()
        reports = linter.lint_all(skills)
    except Exception:
        return 100, []

    clean = len(skills) - len(reports)
    score = int(100 * clean / len(skills)) if skills else 100

    fixes: list[str] = []
    # Find top 2 most-affected skills
    by_count = sorted(reports.items(), key=lambda kv: kv[1].issue_count, reverse=True)
    for name, report in by_count[:2]:
        top_issue = report.issues[0] if report.issues else None
        if top_issue:
            fixes.append(
                f"Fix `skills/{name}`: line {top_issue.line} — {top_issue.fix}"
            )

    return score, fixes


def _score_mcp_breadth(source_data: dict) -> tuple[int, list[str]]:
    """Return (score 0-100, top fixes)."""
    skills: dict = source_data.get("skills", {})
    if not skills:
        return 100, []

    blocked: list[tuple[str, str, str]] = []  # (skill, harness, mcp_tool)
    for name, path in skills.items():
        try:
            content = Path(path).read_text(encoding="utf-8", errors="replace") if Path(path).is_file() else ""
        except OSError:
            content = ""
        for m in _MCP_TOOL_RE.finditer(content):
            tool_server = m.group(1).replace("_", "-")
            for harness, unavail in _HARNESS_UNAVAILABLE_MCP.items():
                if tool_server in unavail:
                    blocked.append((name, harness, m.group(0)))

    if not blocked:
        return 100, []

    # Score: fraction of (skill, harness) pairs that are NOT blocked
    total_pairs = len(skills) * len(_HARNESS_UNAVAILABLE_MCP)
    blocked_pairs = len({(s, h) for s, h, _ in blocked})
    score = int(100 * (total_pairs - blocked_pairs) / total_pairs)

    # Top 2 fixes
    by_skill: dict[str, list[tuple[str, str]]] = {}
    for skill, harness, tool in blocked:
        by_skill.setdefault(skill, []).append((harness, tool))
    fixes = [
        f"Wrap `{tool}` in `skills/{skill}` with availability check (blocks {harness})"
        for skill, pairs in list(by_skill.items())[:2]
        for harness, tool in [pairs[0]]
    ]
    return max(0, score), fixes


def _score_path_hygiene(source_data: dict, project_dir: Path) -> tuple[int, list[str]]:
    """Return (score 0-100, top fixes)."""
    rules = source_data.get("rules", "")
    if isinstance(rules, list):
        rules = "\n\n".join(r.get("content", "") if isinstance(r, dict) else str(r) for r in rules)

    # Also scan skills
    skill_texts: list[str] = []
    for path in (source_data.get("skills") or {}).values():
        try:
            p = Path(path)
            if p.is_file():
                skill_texts.append(p.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass

    all_text = rules + "\n".join(skill_texts)
    absolute_paths = _ABSOLUTE_PATH_RE.findall(all_text)

    if not absolute_paths:
        return 100, []

    unique = list(dict.fromkeys(absolute_paths))
    # Score: 100 - min(10 * count, 100)
    score = max(0, 100 - 10 * len(unique))
    fixes = [
        f"Replace absolute path `{p}` with a relative path or $HOME variable"
        for p in unique[:2]
    ]
    return score, fixes


def _score_settings_coverage(source_data: dict) -> tuple[int, list[str]]:
    """Return (score 0-100, top fixes)."""
    settings: dict = source_data.get("settings", {})
    if not settings:
        return 100, []

    covered = [k for k in settings if k in _SETTINGS_WITH_TARGET_SUPPORT]
    score = int(100 * len(covered) / len(settings)) if settings else 100

    uncovered = [k for k in settings if k not in _SETTINGS_WITH_TARGET_SUPPORT]
    fixes = [
        f"Setting `{k}` has no known harness equivalent — document a fallback or remove it"
        for k in uncovered[:2]
    ]
    return score, fixes


def _compute_total(sub_scores: dict[str, int]) -> int:
    """Weighted average of sub-scores."""
    weights = {"skill_portability": 35, "mcp_breadth": 25, "path_hygiene": 20, "settings_coverage": 20}
    total = sum(sub_scores[k] * weights[k] for k in weights if k in sub_scores)
    return total // 100


def main() -> None:
    """Entry point for /sync-score command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-score",
        description="Compute portability score for Claude Code config (0-100)",
    )
    parser.add_argument("--format", default="text", choices=["text", "json"])
    parser.add_argument("--project-dir", default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    output_json = args.format == "json"

    try:
        from src.source_reader import SourceReader
        reader = SourceReader(scope="all", project_dir=project_dir)
        source_data = reader.discover_all()
    except Exception as e:
        if output_json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Error reading config: {e}", file=sys.stderr)
        sys.exit(2)

    skill_score, skill_fixes = _score_skill_portability(source_data.get("skills", {}), project_dir)
    mcp_score, mcp_fixes = _score_mcp_breadth(source_data)
    path_score, path_fixes = _score_path_hygiene(source_data, project_dir)
    settings_score, settings_fixes = _score_settings_coverage(source_data)

    sub_scores = {
        "skill_portability": skill_score,
        "mcp_breadth": mcp_score,
        "path_hygiene": path_score,
        "settings_coverage": settings_score,
    }
    total = _compute_total(sub_scores)

    if output_json:
        print(json.dumps({
            "total": total,
            "sub_scores": sub_scores,
            "fixes": {
                "skill_portability": skill_fixes,
                "mcp_breadth": mcp_fixes,
                "path_hygiene": path_fixes,
                "settings_coverage": settings_fixes,
            },
        }, indent=2))
        return

    # Human-readable output
    def _grade(score: int) -> str:
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"

    print("HarnessSync Portability Score")
    print("=" * 40)
    print(f"  Total score: {total}/100  ({_grade(total)})")
    print()
    rows = [
        ("Skill portability", skill_score, skill_fixes),
        ("MCP dependency breadth", mcp_score, mcp_fixes),
        ("Path hygiene", path_score, path_fixes),
        ("Settings coverage", settings_score, settings_fixes),
    ]
    for label, score, fixes in rows:
        print(f"  {label:<25} {score:>3}/100  ({_grade(score)})")
        for fix in fixes:
            print(f"    → {fix}")
        if fixes:
            print()

    if total >= 90:
        print("\nExcellent portability — your config translates well across harnesses.")
    elif total >= 70:
        print("\nGood portability. Address the fixes above to reach 90+.")
    else:
        print("\nPortability needs work. Focus on the highest-weight sub-scores first.")


if __name__ == "__main__":
    main()
