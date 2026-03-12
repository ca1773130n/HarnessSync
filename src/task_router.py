from __future__ import annotations

"""Task-Based Harness Router (item 29).

Given a task description, recommends which harness + config profile is best
suited — based on task type, available tools, and the user's installed harnesses.

Users waste time picking the wrong harness for the job.  This router provides
data-driven recommendations so users can start productive immediately.

Routing logic:
- Classifies the task using keyword heuristics (no LLM required)
- Checks which harnesses are installed/configured
- Scores each harness against the task requirements
- Returns an ordered list of recommendations with rationale

Task categories:
  code_generation    Frontend/backend feature work
  code_review        PR/diff review, static analysis
  debugging          Error tracing, log analysis
  data_science       Notebooks, pandas, ML workflows
  infra_ops          Terraform, Docker, CI/CD
  writing_docs       READMEs, API docs, changelogs
  refactoring        Large-scale rename, extract, move
  web_search         Research tasks needing live search
  multi_agent        Orchestrated agent pipelines
  general            Catch-all

Usage:
    from src.task_router import TaskRouter

    router = TaskRouter(project_dir=Path("."))
    result = router.route("add authentication to the login endpoint")
    print(router.format_recommendation(result))

Or from the CLI:
    /sync-route "your task description here" [--json]
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Task classifier ────────────────────────────────────────────────────────

_CATEGORY_PATTERNS: dict[str, list[str]] = {
    "code_generation": [
        r"\b(add|implement|create|build|write|generate)\b.{0,40}\b(feature|endpoint|api|component|function|class|module)\b",
        r"\b(new|implement)\s+(route|handler|controller|service|model)\b",
    ],
    "code_review": [
        r"\b(review|check|analyze|audit|inspect)\b.{0,30}\b(code|pr|pull request|diff|change|commit)\b",
        r"\bcode quality\b",
        r"\bsecurity\s+(review|audit|scan)\b",
    ],
    "debugging": [
        r"\b(fix|debug|trace|investigate|diagnose|troubleshoot)\b",
        r"\b(error|exception|crash|bug|failure|broken)\b",
        r"\b(why|what).*\b(failing|broken|not working|crash)\b",
    ],
    "data_science": [
        r"\b(notebook|jupyter|pandas|numpy|sklearn|tensorflow|pytorch|keras)\b",
        r"\b(train|model|dataset|dataframe|ml|machine learning|neural)\b",
        r"\b(plot|visualiz|matplotlib|seaborn)\b",
    ],
    "infra_ops": [
        r"\b(terraform|ansible|puppet|chef|docker|kubernetes|helm|k8s)\b",
        r"\b(deploy|provision|infrastructure|ci.?cd|pipeline|workflow)\b",
        r"\b(github actions|gitlab ci|jenkins|circleci)\b",
    ],
    "writing_docs": [
        r"\b(write|update|generate)\b.{0,20}\b(readme|documentation|docs|changelog|release notes|api docs)\b",
        r"\bdocument\s+(the|this|all|api)\b",
    ],
    "refactoring": [
        r"\b(refactor|rename|extract|reorganize|restructure|clean up|move)\b",
        r"\b(large.scale|codebase.wide|project.wide)\b",
    ],
    "web_search": [
        r"\b(search|look up|find|research)\b.{0,30}\b(online|web|internet|latest|current|news)\b",
        r"\bwhat is the latest\b",
        r"\bup.?to.?date\b",
    ],
    "multi_agent": [
        r"\b(orchestrat|pipeline|multi.?agent|subagent|agent chain)\b",
        r"\b(spawn|coordinate)\b.{0,20}\b(agent|task)\b",
        r"\bparallel\b.{0,20}\b(tasks|agents|workers)\b",
    ],
}


def classify_task(description: str) -> str:
    """Classify a task description into a category string."""
    text = description.lower()
    scores: dict[str, int] = {}
    for category, patterns in _CATEGORY_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, text))
        if score > 0:
            scores[category] = score
    if not scores:
        return "general"
    return max(scores, key=lambda k: scores[k])


# ── Harness scoring matrix ─────────────────────────────────────────────────
# Score 0–10 for each (category, harness) pair.
# Higher = better fit for that task category.
_HARNESS_SCORES: dict[str, dict[str, int]] = {
    "code_generation": {
        "claude-code": 10,
        "cursor":      9,
        "opencode":    8,
        "gemini":      7,
        "aider":       8,
        "codex":       7,
        "windsurf":    7,
    },
    "code_review": {
        "claude-code": 10,
        "gemini":      8,
        "cursor":      7,
        "opencode":    7,
        "codex":       6,
        "aider":       5,
        "windsurf":    6,
    },
    "debugging": {
        "claude-code": 10,
        "cursor":      8,
        "opencode":    8,
        "gemini":      7,
        "aider":       6,
        "codex":       7,
        "windsurf":    7,
    },
    "data_science": {
        "claude-code": 8,
        "gemini":      9,   # Strong notebook/Python support
        "cursor":      7,
        "opencode":    6,
        "aider":       9,   # Excellent for notebook workflows
        "codex":       6,
        "windsurf":    6,
    },
    "infra_ops": {
        "claude-code": 9,
        "opencode":    8,
        "cursor":      7,
        "gemini":      7,
        "aider":       7,
        "codex":       8,
        "windsurf":    6,
    },
    "writing_docs": {
        "claude-code": 10,
        "gemini":      9,
        "cursor":      7,
        "opencode":    7,
        "aider":       6,
        "codex":       6,
        "windsurf":    6,
    },
    "refactoring": {
        "claude-code": 9,
        "aider":       10,  # Excellent for large-scale refactors
        "cursor":      8,
        "opencode":    8,
        "gemini":      7,
        "codex":       7,
        "windsurf":    7,
    },
    "web_search": {
        "claude-code": 8,   # MCP brave/tavily
        "gemini":      10,  # Native Google Search grounding
        "cursor":      6,
        "opencode":    6,
        "aider":       5,
        "codex":       6,
        "windsurf":    6,
    },
    "multi_agent": {
        "claude-code": 10,  # Native multi-agent SDK
        "gemini":      8,
        "opencode":    7,
        "cursor":      4,
        "aider":       3,
        "codex":       5,
        "windsurf":    4,
    },
    "general": {
        "claude-code": 9,
        "cursor":      8,
        "opencode":    8,
        "gemini":      8,
        "aider":       7,
        "codex":       7,
        "windsurf":    7,
    },
}

# Rationale snippets per (category, harness) for the top recommendation
_RATIONALE: dict[str, dict[str, str]] = {
    "code_generation": {
        "claude-code": "Best tool-use depth and project context via CLAUDE.md",
        "cursor":      "Strong inline completion and project-wide context",
        "aider":       "Excellent git-integrated generation with whole-repo context",
        "gemini":      "Fast model with good code generation for many languages",
    },
    "code_review": {
        "claude-code": "Full project context + agent pipeline for multi-file review",
        "gemini":      "Fast, capable reviewer with native search grounding",
    },
    "debugging": {
        "claude-code": "Deep tool-use for log reading, running tests, tracing errors",
        "opencode":    "Good interactive debugging flow with shell integration",
    },
    "data_science": {
        "gemini":      "Native Jupyter kernel integration and Python data analysis",
        "aider":       "Great for notebook editing with git tracking of changes",
    },
    "infra_ops": {
        "claude-code": "Full bash/shell tool-use for Terraform and Kubernetes workflows",
        "codex":       "Strong CLI integration for ops scripting tasks",
    },
    "writing_docs": {
        "claude-code": "Best long-form writing with project context from CLAUDE.md",
        "gemini":      "Fast drafting with search grounding for accuracy",
    },
    "refactoring": {
        "aider":       "Whole-repository refactoring with git-tracked incremental changes",
        "claude-code": "Multi-file refactoring with full project understanding",
    },
    "web_search": {
        "gemini":      "Native Google Search grounding — no MCP plugin required",
        "claude-code": "Use with brave-search or tavily MCP server for live search",
    },
    "multi_agent": {
        "claude-code": "Native Claude Agent SDK for subagent orchestration",
        "gemini":      "Multi-agent support via Gemini API agent framework",
    },
    "general": {
        "claude-code": "Best general-purpose harness with deepest tool integration",
    },
}


@dataclass
class HarnessRecommendation:
    """A recommendation for a specific harness."""
    harness: str
    score: int
    rank: int
    rationale: str
    is_installed: bool
    config_profile: str = ""   # e.g. "data-science branch profile"


@dataclass
class RoutingResult:
    """Result of routing a task to harnesses."""
    task_description: str
    task_category: str
    recommendations: list[HarnessRecommendation]
    top_recommendation: HarnessRecommendation | None


# ── Detection helpers ──────────────────────────────────────────────────────

def _detect_installed_harnesses(project_dir: Path, cc_home: Path) -> set[str]:
    """Detect which harnesses are installed/configured."""
    installed: set[str] = set()
    checks = {
        "claude-code": cc_home / ".claude.json",
        "cursor":      project_dir / ".cursor",
        "gemini":      project_dir / "GEMINI.md",
        "opencode":    project_dir / "opencode.json",
        "codex":       project_dir / "AGENTS.md",
        "aider":       project_dir / "CONVENTIONS.md",
        "windsurf":    project_dir / ".windsurfrules",
    }
    for name, path in checks.items():
        if path.exists():
            installed.add(name)
    # Always consider claude-code installed if we're running inside it
    installed.add("claude-code")
    return installed


class TaskRouter:
    """Route a task description to the best-suited harness.

    Args:
        project_dir: Project root.  Defaults to cwd.
        cc_home:     Claude Code home.  Defaults to ~/.claude.
    """

    def __init__(self, project_dir: Path | None = None, cc_home: Path | None = None):
        self.project_dir = project_dir or Path.cwd()
        self.cc_home = cc_home or (Path.home() / ".claude")

    def route(self, task_description: str, include_all: bool = False) -> RoutingResult:
        """Route a task description to the best harness.

        Args:
            task_description: Natural language task description.
            include_all:      If True, include harnesses not locally installed.

        Returns:
            RoutingResult with ordered recommendations.
        """
        category = classify_task(task_description)
        installed = _detect_installed_harnesses(self.project_dir, self.cc_home)
        scores = _HARNESS_SCORES.get(category, _HARNESS_SCORES["general"])
        rationale_map = _RATIONALE.get(category, {})

        recommendations: list[HarnessRecommendation] = []
        for harness, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
            is_installed = harness in installed
            if not include_all and not is_installed:
                continue
            rationale = rationale_map.get(harness, f"Suitable for {category.replace('_', ' ')} tasks")
            recommendations.append(HarnessRecommendation(
                harness=harness,
                score=score,
                rank=0,  # filled below
                rationale=rationale,
                is_installed=is_installed,
            ))

        # Assign ranks
        for i, rec in enumerate(recommendations):
            rec.rank = i + 1

        top = recommendations[0] if recommendations else None
        return RoutingResult(
            task_description=task_description,
            task_category=category,
            recommendations=recommendations,
            top_recommendation=top,
        )

    def format_recommendation(self, result: RoutingResult, top_n: int = 3) -> str:
        """Return a human-readable routing recommendation."""
        lines = [
            f"Task: {result.task_description}",
            f"Category: {result.task_category.replace('_', ' ').title()}",
            "",
            "Harness Recommendations:",
            "-" * 40,
        ]
        for rec in result.recommendations[:top_n]:
            installed_marker = "✓ installed" if rec.is_installed else "○ not found"
            lines.append(f"#{rec.rank}  {rec.harness:12s}  score={rec.score}/10  [{installed_marker}]")
            lines.append(f"    {rec.rationale}")
        if result.top_recommendation:
            lines.append(f"\nRecommendation: Use {result.top_recommendation.harness.upper()}")
        return "\n".join(lines)

    def format_json(self, result: RoutingResult) -> str:
        """Return routing result as JSON."""
        return json.dumps({
            "task": result.task_description,
            "category": result.task_category,
            "top_recommendation": result.top_recommendation.harness if result.top_recommendation else None,
            "recommendations": [
                {
                    "harness": r.harness,
                    "score": r.score,
                    "rank": r.rank,
                    "rationale": r.rationale,
                    "is_installed": r.is_installed,
                }
                for r in result.recommendations
            ],
        }, indent=2)
