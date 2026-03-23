from __future__ import annotations

"""Cross-Harness Prompt Benchmarking (item 30).

Run the same prompt/task description against multiple harnesses' configurations
and compare compatibility/coverage scores side-by-side.

No LLM calls are made.  Instead this module statically analyzes the synced
config files on disk (AGENTS.md, GEMINI.md, .cursor/rules/, etc.) and scores
how well each harness is set up to handle a given prompt or task description.

Scoring dimensions (total: 100 points):
  - rule_coverage  (40 pts): Rules in the synced config that match task keywords
  - tool_coverage  (30 pts): MCP tools relevant to the task are configured
  - skill_coverage (20 pts): Skills present that match the task type
  - capability_fit (10 pts): Harness-native capability alignment with task type

Usage:
    from src.prompt_benchmark import PromptBenchmark

    bench = PromptBenchmark(project_dir=Path("."))
    report = bench.run("add oauth2 authentication to the login endpoint")
    print(report.format_comparison_table())

Or from the CLI:
    /sync-bench "your task description here" [--targets codex,gemini] [--json]
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Task classification ─────────────────────────────────────────────────────
# Reuses the category keyword patterns from task_router.py (kept in sync).

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


def _classify_prompt(prompt: str) -> str:
    """Classify a prompt into a task category string using keyword heuristics."""
    text = prompt.lower()
    scores: dict[str, int] = {}
    for category, patterns in _CATEGORY_PATTERNS.items():
        score = sum(1 for p in patterns if re.search(p, text))
        if score > 0:
            scores[category] = score
    if not scores:
        return "general"
    return max(scores, key=lambda k: scores[k])


def _extract_keywords(prompt: str) -> list[str]:
    """Extract significant keywords from the prompt for rule matching.

    Strips stop-words and short tokens; returns lowercase unique terms.
    """
    _STOP_WORDS = {
        "a", "an", "the", "and", "or", "but", "for", "in", "on", "at", "to",
        "of", "with", "that", "this", "is", "are", "was", "be", "by", "it",
        "as", "do", "from", "not", "can", "has", "have", "will", "i", "my",
        "our", "we", "they", "he", "she", "its",
    }
    tokens = re.findall(r"[a-z][a-z0-9_-]{2,}", prompt.lower())
    return list({t for t in tokens if t not in _STOP_WORDS})


# ── MCP tool relevance map ──────────────────────────────────────────────────
# Maps task category → list of MCP server name substrings that are useful.

_TASK_RELEVANT_MCP: dict[str, list[str]] = {
    "code_generation":  ["filesystem", "github", "git", "sqlite", "postgres"],
    "code_review":      ["github", "git", "filesystem"],
    "debugging":        ["filesystem", "bash", "shell", "sequential-thinking"],
    "data_science":     ["filesystem", "sqlite", "postgres", "jupyter"],
    "infra_ops":        ["bash", "shell", "filesystem", "github", "docker"],
    "writing_docs":     ["filesystem", "github", "brave-search", "tavily", "fetch"],
    "refactoring":      ["filesystem", "github", "git"],
    "web_search":       ["brave-search", "tavily", "fetch", "puppeteer", "playwright"],
    "multi_agent":      ["filesystem", "github", "sequential-thinking"],
    "general":          ["filesystem"],
}

# ── Skill type relevance map ────────────────────────────────────────────────
# Maps task category → skill name substrings that indicate relevance.

_TASK_RELEVANT_SKILLS: dict[str, list[str]] = {
    "code_generation":  ["generate", "create", "scaffold", "template", "boilerplate", "api", "crud"],
    "code_review":      ["review", "lint", "check", "audit", "security", "quality"],
    "debugging":        ["debug", "trace", "diagnose", "fix", "analyze", "log"],
    "data_science":     ["data", "notebook", "model", "analysis", "plot", "ml", "pandas"],
    "infra_ops":        ["deploy", "infra", "terraform", "docker", "k8s", "ci", "devops"],
    "writing_docs":     ["doc", "readme", "changelog", "comment", "wiki"],
    "refactoring":      ["refactor", "rename", "clean", "restructure", "organize"],
    "web_search":       ["search", "research", "fetch", "browse", "lookup"],
    "multi_agent":      ["agent", "orchestrat", "pipeline", "parallel", "spawn"],
    "general":          [],
}

# ── Harness-native capability alignment per task category ───────────────────
# How inherently well-suited each harness is to each task category (0-10).

_CAPABILITY_FIT: dict[str, dict[str, int]] = {
    "code_generation": {
        "codex": 7, "gemini": 7, "opencode": 8, "cursor": 9, "aider": 8,
        "windsurf": 7, "cline": 7, "continue": 7, "zed": 7, "neovim": 6,
    },
    "code_review": {
        "codex": 6, "gemini": 8, "opencode": 7, "cursor": 7, "aider": 5,
        "windsurf": 6, "cline": 6, "continue": 6, "zed": 7, "neovim": 5,
    },
    "debugging": {
        "codex": 7, "gemini": 7, "opencode": 8, "cursor": 8, "aider": 6,
        "windsurf": 7, "cline": 7, "continue": 7, "zed": 7, "neovim": 6,
    },
    "data_science": {
        "codex": 6, "gemini": 9, "opencode": 6, "cursor": 7, "aider": 9,
        "windsurf": 6, "cline": 5, "continue": 6, "zed": 5, "neovim": 5,
    },
    "infra_ops": {
        "codex": 8, "gemini": 7, "opencode": 8, "cursor": 7, "aider": 7,
        "windsurf": 6, "cline": 7, "continue": 7, "zed": 6, "neovim": 6,
    },
    "writing_docs": {
        "codex": 6, "gemini": 9, "opencode": 7, "cursor": 7, "aider": 6,
        "windsurf": 6, "cline": 6, "continue": 6, "zed": 7, "neovim": 5,
    },
    "refactoring": {
        "codex": 7, "gemini": 7, "opencode": 8, "cursor": 8, "aider": 10,
        "windsurf": 7, "cline": 7, "continue": 7, "zed": 7, "neovim": 7,
    },
    "web_search": {
        "codex": 6, "gemini": 10, "opencode": 6, "cursor": 6, "aider": 5,
        "windsurf": 6, "cline": 5, "continue": 5, "zed": 5, "neovim": 4,
    },
    "multi_agent": {
        "codex": 5, "gemini": 8, "opencode": 7, "cursor": 4, "aider": 3,
        "windsurf": 4, "cline": 5, "continue": 5, "zed": 4, "neovim": 3,
    },
    "general": {
        "codex": 7, "gemini": 8, "opencode": 8, "cursor": 8, "aider": 7,
        "windsurf": 7, "cline": 7, "continue": 7, "zed": 7, "neovim": 6,
    },
}

# ── Known harness capability limitations (affects missing_capabilities) ─────

_HARNESS_CAPABILITY_LIMITS: dict[str, list[str]] = {
    "codex":    ["No native hook events", "MCP limited to stdio servers"],
    "gemini":   ["No native hook events"],
    "opencode": ["No native hook events"],
    "cursor":   ["Skills converted to .mdc", "No native hook events",
                 "MCP requires separate Cursor setup"],
    "aider":    ["Skills mapped to context files (no execution)",
                 "No MCP server support", "No slash commands",
                 "No hook events"],
    "windsurf": ["Skills mapped to memory files", "No native hook events",
                 "MCP requires separate Windsurf setup"],
    "cline":    ["No native hook events", "Commands not supported"],
    "continue": ["No native hook events", "Agents converted to prompts"],
    "zed":      ["Skills not supported natively", "No native hook events",
                 "Agents converted to prompts"],
    "neovim":   ["Skills not supported natively", "No native hook events",
                 "Agents converted to prompts"],
}

# ── Task-required capabilities (what the task category typically needs) ─────

_TASK_REQUIRED_CAPS: dict[str, list[str]] = {
    "code_generation":  ["rules", "skills", "mcp"],
    "code_review":      ["rules", "mcp"],
    "debugging":        ["rules", "mcp", "skills"],
    "data_science":     ["rules", "skills"],
    "infra_ops":        ["rules", "mcp", "commands"],
    "writing_docs":     ["rules"],
    "refactoring":      ["rules", "skills"],
    "web_search":       ["mcp"],
    "multi_agent":      ["agents", "mcp"],
    "general":          ["rules"],
}


# ── Synced config file paths per harness ────────────────────────────────────

_RULES_FILES: dict[str, list[str]] = {
    "codex":    ["AGENTS.md"],
    "gemini":   ["GEMINI.md"],
    "opencode": ["OPENCODE.md"],
    "cursor":   [".cursor/rules/claude-code-rules.mdc"],
    "aider":    ["CONVENTIONS.md"],
    "windsurf": [".windsurfrules"],
    "cline":    [".clinerules"],
    "continue": [".continue/rules/harnesssync.md"],
    "zed":      [".rules"],
    "neovim":   [".avante/rules/system-prompt.avanterules"],
}

_SKILLS_DIRS: dict[str, str] = {
    "codex":    ".agents/skills",
    "gemini":   ".gemini/skills",
    "opencode": ".opencode/skills",
    "cursor":   ".cursor/rules/skills",
    "cline":    ".roo/rules/skills",
    "continue": ".continue/rules/skills",
    "zed":      ".zed/prompts/skills",
    "neovim":   ".avante/rules/skills",
}

_MCP_FILES: dict[str, str] = {
    "codex":    ".codex/config.toml",
    "gemini":   ".gemini/settings.json",
    "opencode": ".opencode/settings.json",
    "cursor":   ".cursor/mcp.json",
    "cline":    ".roo/mcp.json",
    "continue": ".continue/config.json",
    "zed":      ".zed/settings.json",
    "neovim":   ".avante/mcp.json",
}

_ALL_TARGETS: list[str] = [
    "codex", "gemini", "opencode", "cursor", "aider",
    "windsurf", "cline", "continue", "zed", "neovim",
]


# ── Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class HarnessBenchmarkResult:
    """Benchmark result for a single harness against a prompt.

    Attributes:
        harness:              Canonical harness name.
        score:                Aggregate score 0-100.
        rule_matches:         Rules in the synced config that match task keywords.
        available_tools:      MCP tool server names available for this harness.
        skill_matches:        Skill names that match the task type.
        missing_capabilities: Capabilities the task needs but the harness lacks.
        notes:                Human-readable summary of the result.
    """
    harness: str
    score: int
    rule_matches: list[str] = field(default_factory=list)
    available_tools: list[str] = field(default_factory=list)
    skill_matches: list[str] = field(default_factory=list)
    missing_capabilities: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class BenchmarkReport:
    """Aggregate benchmark report across all scored harnesses.

    Attributes:
        prompt:  The original task description that was benchmarked.
        results: Per-harness results, sorted by score descending.
        winner:  Harness name with the highest score.
    """
    prompt: str
    results: list[HarnessBenchmarkResult]
    winner: str

    def format_comparison_table(self) -> str:
        """Return a terminal-friendly comparison table.

        Columns: harness, score, rules matched, tools, skills, missing caps.
        """
        if not self.results:
            return "No benchmark results available."

        col_widths = {
            "harness": 10,
            "score":    6,
            "rules":    7,
            "tools":    7,
            "skills":   7,
            "missing": 30,
        }

        sep = "-" * (sum(col_widths.values()) + len(col_widths) * 3 - 1)

        header = (
            f"{'Harness':<{col_widths['harness']}}"
            f"  {'Score':>{col_widths['score']}}"
            f"  {'Rules':>{col_widths['rules']}}"
            f"  {'Tools':>{col_widths['tools']}}"
            f"  {'Skills':>{col_widths['skills']}}"
            f"  {'Missing capabilities':<{col_widths['missing']}}"
        )

        lines: list[str] = [
            f"Cross-Harness Benchmark: {self.prompt[:72]}",
            "=" * max(len(sep), 60),
            "",
            header,
            sep,
        ]

        for r in self.results:
            # Compact bar for score
            bar_len = r.score // 10
            bar = "#" * bar_len + "." * (10 - bar_len)
            score_str = f"{r.score:>3}/100"

            missing_str = (
                "; ".join(r.missing_capabilities)[:col_widths["missing"] - 1]
                if r.missing_capabilities else "-"
            )

            winner_marker = " *" if r.harness == self.winner else "  "
            lines.append(
                f"{r.harness:<{col_widths['harness']}}"
                f"  {score_str:>{col_widths['score']}}"
                f"  {len(r.rule_matches):>{col_widths['rules']}}"
                f"  {len(r.available_tools):>{col_widths['tools']}}"
                f"  {len(r.skill_matches):>{col_widths['skills']}}"
                f"  {missing_str:<{col_widths['missing']}}"
                f"{winner_marker}"
            )

        lines += [
            sep,
            f"* Winner: {self.winner}",
            "",
            "Score breakdown: rules=40pts  tools=30pts  skills=20pts  capability=10pts",
        ]

        # Detail section for top 3 results
        lines += ["", "Top match details:"]
        for r in self.results[:3]:
            lines.append(f"  {r.harness}: {r.notes}")
            if r.rule_matches:
                sample = ", ".join(r.rule_matches[:4])
                if len(r.rule_matches) > 4:
                    sample += f" (+{len(r.rule_matches) - 4} more)"
                lines.append(f"    rules : {sample}")
            if r.available_tools:
                lines.append(f"    tools : {', '.join(r.available_tools)}")
            if r.skill_matches:
                lines.append(f"    skills: {', '.join(r.skill_matches)}")

        return "\n".join(lines)

    def format_json(self) -> str:
        """Return benchmark report as a JSON string."""
        return json.dumps(
            {
                "prompt": self.prompt,
                "winner": self.winner,
                "results": [
                    {
                        "harness": r.harness,
                        "score": r.score,
                        "rule_matches": r.rule_matches,
                        "available_tools": r.available_tools,
                        "skill_matches": r.skill_matches,
                        "missing_capabilities": r.missing_capabilities,
                        "notes": r.notes,
                    }
                    for r in self.results
                ],
            },
            indent=2,
        )

    def format_side_by_side(self, width: int = 120) -> str:
        """Format benchmark results as a side-by-side column comparison.

        Renders up to 3 harnesses in adjacent columns so users can compare
        rule coverage, tool availability, and capability gaps at a glance —
        verifying that synced rules produce consistent harness setups.

        Args:
            width: Total terminal width to fill. Defaults to 120.

        Returns:
            Multi-line string with harness columns laid out side by side.
        """
        if not self.results:
            return "No benchmark results available."

        # Limit to top 3 harnesses for readability
        cols = self.results[:3]
        n = len(cols)
        col_w = max(30, (width - (n - 1) * 3) // n)

        def _pad(text: str, w: int) -> str:
            return text[:w].ljust(w)

        # Build per-harness content blocks as lists of lines
        def _harness_lines(r: HarnessBenchmarkResult) -> list[str]:
            bar_len = r.score // 10
            score_bar = "#" * bar_len + "." * (10 - bar_len)
            block = [
                f"{r.harness.upper()}  score={r.score}/100",
                f"[{score_bar}]",
                "",
                f"Rules matched: {len(r.rule_matches)}",
            ]
            for rule in r.rule_matches[:4]:
                block.append(f"  • {rule[:col_w - 6]}")
            if len(r.rule_matches) > 4:
                block.append(f"  … +{len(r.rule_matches) - 4} more")
            block += [
                "",
                f"Tools available: {len(r.available_tools)}",
            ]
            for tool in r.available_tools[:4]:
                block.append(f"  • {tool[:col_w - 6]}")
            if len(r.available_tools) > 4:
                block.append(f"  … +{len(r.available_tools) - 4} more")
            block += ["", f"Skills: {len(r.skill_matches)}"]
            for skill in r.skill_matches[:3]:
                block.append(f"  • {skill[:col_w - 6]}")
            block += ["", "Missing:"]
            if r.missing_capabilities:
                for cap in r.missing_capabilities:
                    block.append(f"  ✗ {cap[:col_w - 6]}")
            else:
                block.append("  (none)")
            block += ["", r.notes[:col_w] if r.notes else ""]
            return block

        col_blocks = [_harness_lines(r) for r in cols]
        max_rows = max(len(b) for b in col_blocks)
        for b in col_blocks:
            b += [""] * (max_rows - len(b))

        sep_line = (" | ".join("─" * col_w for _ in range(n)))
        title = f"Side-by-Side Benchmark: {self.prompt[:width - 25]}"
        lines: list[str] = [title, "=" * len(title), "", sep_line]
        for row_idx in range(max_rows):
            row = " | ".join(_pad(col_blocks[i][row_idx], col_w) for i in range(n))
            lines.append(row)
        lines.append(sep_line)
        lines.append(f"\nWinner: {self.winner}  |  Run /sync to align configs.")
        return "\n".join(lines)


# ── PromptBenchmark main class ──────────────────────────────────────────────

class PromptBenchmark:
    """Benchmark a task prompt against multiple harnesses' synced configs.

    Reads config files that were previously written by HarnessSync adapters
    and scores each harness on rule coverage, MCP tool availability, skill
    presence, and native capability fit.

    Args:
        project_dir: Project root directory.  Defaults to cwd.
    """

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir or Path.cwd()

    def run(
        self,
        prompt: str,
        targets: list[str] | None = None,
    ) -> BenchmarkReport:
        """Benchmark the prompt against all requested harnesses.

        Args:
            prompt:  Natural language task/prompt description.
            targets: Harness names to score (default: all installed/synced).

        Returns:
            BenchmarkReport with per-harness results, sorted by score desc.
        """
        category = _classify_prompt(prompt)
        keywords = _extract_keywords(prompt)

        if targets is None:
            targets = self._detect_synced_targets()

        results: list[HarnessBenchmarkResult] = []
        for harness in targets:
            result = self._score_harness(harness, prompt, category, keywords)
            results.append(result)

        results.sort(key=lambda r: r.score, reverse=True)
        winner = results[0].harness if results else ""

        return BenchmarkReport(prompt=prompt, results=results, winner=winner)

    # ── Private helpers ──────────────────────────────────────────────────────

    def _detect_synced_targets(self) -> list[str]:
        """Return the subset of _ALL_TARGETS that have synced files on disk."""
        found: list[str] = []
        for target in _ALL_TARGETS:
            for rel in _RULES_FILES.get(target, []):
                if (self.project_dir / rel).is_file():
                    found.append(target)
                    break
        return found

    def _score_harness(
        self,
        harness: str,
        prompt: str,
        category: str,
        keywords: list[str],
    ) -> HarnessBenchmarkResult:
        """Compute a HarnessBenchmarkResult for one harness.

        Scoring (max 100):
          40 pts  rule_coverage  — rules matching task keywords
          30 pts  tool_coverage  — relevant MCP tools configured
          20 pts  skill_coverage — skills matching the task type
          10 pts  capability_fit — harness-native alignment score
        """
        # ── 1. Rule coverage (40 pts) ─────────────────────────────────────
        rule_matches = self._match_rules(harness, keywords, category)
        rule_score = min(40, len(rule_matches) * 8)  # 5 matches = full 40 pts

        # ── 2. Tool coverage (30 pts) ─────────────────────────────────────
        available_tools = self._detect_mcp_tools(harness)
        relevant_tools = _TASK_RELEVANT_MCP.get(category, [])
        tool_matches = [
            t for t in available_tools
            if any(kw in t.lower() for kw in relevant_tools)
        ]
        tool_score = min(30, len(tool_matches) * 10)  # 3 matches = full 30 pts

        # ── 3. Skill coverage (20 pts) ────────────────────────────────────
        skill_matches = self._match_skills(harness, category, keywords)
        skill_score = min(20, len(skill_matches) * 7)  # 3 matches ≈ full 20 pts

        # ── 4. Capability fit (10 pts) ────────────────────────────────────
        native_fit = _CAPABILITY_FIT.get(category, {}).get(harness, 7)
        capability_score = native_fit  # already 0-10

        total = rule_score + tool_score + skill_score + capability_score

        # ── 5. Missing capabilities ────────────────────────────────────────
        missing = self._find_missing_capabilities(harness, category, available_tools)

        # ── 6. Notes ─────────────────────────────────────────────────────
        notes = _build_notes(
            harness, total, rule_matches, tool_matches, skill_matches, category,
        )

        return HarnessBenchmarkResult(
            harness=harness,
            score=min(100, max(0, total)),
            rule_matches=rule_matches,
            available_tools=available_tools,
            skill_matches=skill_matches,
            missing_capabilities=missing,
            notes=notes,
        )

    def _match_rules(
        self,
        harness: str,
        keywords: list[str],
        category: str,
    ) -> list[str]:
        """Return excerpts from the synced rules file that match task keywords.

        Each match is the first 80 characters of the matching line/bullet,
        de-duplicated and capped at 10 matches.
        """
        matches: list[str] = []
        for rel in _RULES_FILES.get(harness, []):
            path = self.project_dir / rel
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Also add category-specific terms to the search
            category_terms = _CATEGORY_KEYWORD_EXTRAS.get(category, [])
            all_terms = list(set(keywords + category_terms))

            for line in content.splitlines():
                line_lower = line.lower()
                # Only consider rule-like lines (bullets, headings, non-empty prose)
                stripped = line.strip()
                if not stripped or len(stripped) < 8:
                    continue
                for kw in all_terms:
                    if kw in line_lower:
                        excerpt = stripped[:80]
                        if excerpt not in matches:
                            matches.append(excerpt)
                        break  # one match per line
                if len(matches) >= 10:
                    break
            if len(matches) >= 10:
                break

        return matches

    def _detect_mcp_tools(self, harness: str) -> list[str]:
        """Return the list of MCP server names configured for this harness."""
        mcp_rel = _MCP_FILES.get(harness)
        if not mcp_rel:
            return []

        mcp_path = self.project_dir / mcp_rel
        if not mcp_path.is_file():
            return []

        try:
            content = mcp_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        servers: list[str] = []

        # Try JSON first (most harnesses use JSON for MCP config)
        if mcp_path.suffix == ".json":
            try:
                data = json.loads(content)
                # Handle common shapes: {mcpServers: {...}}, {context_servers: {...}}
                for key in ("mcpServers", "context_servers", "mcp_servers"):
                    if isinstance(data.get(key), dict):
                        servers.extend(data[key].keys())
                        break
                # .continue/config.json uses a different structure
                if not servers and "models" in data:
                    for item in data.get("mcpServers", {}).keys():
                        servers.append(item)
            except (json.JSONDecodeError, AttributeError):
                pass

        # TOML fallback for codex
        elif mcp_path.suffix == ".toml":
            for m in re.finditer(r'\[mcp\.servers\.([^\]]+)\]', content):
                servers.append(m.group(1).strip())
            if not servers:
                for m in re.finditer(r'"([^"]+)"\s*=\s*\{', content):
                    servers.append(m.group(1))

        return servers

    def _match_skills(
        self,
        harness: str,
        category: str,
        keywords: list[str],
    ) -> list[str]:
        """Return skill names that match the task category or keywords."""
        skills_rel = _SKILLS_DIRS.get(harness)
        if not skills_rel:
            return []

        skills_dir = self.project_dir / skills_rel
        if not skills_dir.is_dir():
            return []

        relevant_terms = _TASK_RELEVANT_SKILLS.get(category, []) + keywords
        matches: list[str] = []

        for entry in skills_dir.iterdir():
            skill_name = entry.name.lower()
            for term in relevant_terms:
                if term in skill_name:
                    matches.append(entry.name)
                    break

        return sorted(set(matches))[:8]

    def _find_missing_capabilities(
        self,
        harness: str,
        category: str,
        available_tools: list[str],
    ) -> list[str]:
        """Identify capabilities the task requires that this harness lacks."""
        missing: list[str] = []
        required = _TASK_REQUIRED_CAPS.get(category, [])
        limitations = _HARNESS_CAPABILITY_LIMITS.get(harness, [])

        # Check required capabilities against known harness limitations
        if "mcp" in required:
            relevant_mcp = _TASK_RELEVANT_MCP.get(category, [])
            has_relevant = any(
                any(kw in t.lower() for kw in relevant_mcp)
                for t in available_tools
            )
            if not has_relevant and available_tools == []:
                missing.append(f"No MCP tools configured (needs: {', '.join(relevant_mcp[:2])})")

        if "agents" in required:
            no_agent_targets = {"aider", "windsurf", "cursor"}
            if harness in no_agent_targets:
                missing.append("No native agent support (agents converted to rules)")

        if "commands" in required:
            no_cmd_targets = {"aider", "gemini"}
            if harness in no_cmd_targets:
                missing.append("Slash commands not available")

        if "skills" in required:
            skill_limited = {"zed", "neovim"}
            if harness in skill_limited:
                missing.append("Skills not natively supported")

        # Add harness-specific limitations relevant to this task
        for limitation in limitations:
            limit_lower = limitation.lower()
            if "mcp" in limit_lower and "mcp" in required:
                if limitation not in missing:
                    missing.append(limitation)
            elif "hook" in limit_lower:
                pass  # Hooks are CC-specific; don't surface as a benchmark gap

        return missing[:5]


# ── Category extra search terms ─────────────────────────────────────────────
# Additional domain-specific terms to broaden rule matching beyond raw keywords.

_CATEGORY_KEYWORD_EXTRAS: dict[str, list[str]] = {
    "code_generation": ["implement", "function", "class", "endpoint", "module", "api"],
    "code_review":     ["review", "quality", "lint", "security", "audit"],
    "debugging":       ["error", "fix", "debug", "trace", "exception", "test"],
    "data_science":    ["data", "analysis", "model", "notebook", "visualization"],
    "infra_ops":       ["deploy", "docker", "terraform", "pipeline", "ci", "cd"],
    "writing_docs":    ["documentation", "readme", "comment", "describe"],
    "refactoring":     ["refactor", "clean", "rename", "extract", "restructure"],
    "web_search":      ["search", "fetch", "browse", "research"],
    "multi_agent":     ["agent", "orchestrate", "pipeline", "parallel"],
    "general":         [],
}


def _build_notes(
    harness: str,
    score: int,
    rule_matches: list[str],
    tool_matches: list[str],
    skill_matches: list[str],
    category: str,
) -> str:
    """Build a one-line summary note for a harness benchmark result."""
    parts: list[str] = []
    if rule_matches:
        parts.append(f"{len(rule_matches)} rule match(es)")
    else:
        parts.append("no rule matches (config may not be synced)")
    if tool_matches:
        parts.append(f"{len(tool_matches)} relevant MCP tool(s)")
    if skill_matches:
        parts.append(f"{len(skill_matches)} skill match(es)")

    grade = "excellent" if score >= 75 else "good" if score >= 55 else "fair" if score >= 35 else "weak"
    return f"{grade} fit for {category.replace('_', ' ')} — " + "; ".join(parts)
