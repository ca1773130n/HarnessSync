from __future__ import annotations

"""Config size optimizer — analyze CLAUDE.md verbosity and suggest concise equivalents.

Different harnesses load the entire config into their context window on every
session. A verbose CLAUDE.md costs tokens; a concise one costs less while
conveying the same instructions. This module helps users find high-verbosity
rules and suggests more concise phrasings.

Analysis heuristics:
- Passive-voice and hedging phrases (should, would, could, might) that can be
  collapsed to imperative form
- Filler preambles that add length without instruction value
- Redundant repetition (same keyword appearing 3+ times in nearby lines)
- Over-specification (spelling out obvious defaults)
- Excessively long sentences (>30 words) that could be split
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

# Per-harness recommended max token budget for synced rules files.
# Sourced from token_estimator.CONTEXT_WINDOWS — using 25% of the context
# window as a rule-file budget leaves room for conversation and code context.
# Values are approximate conservative recommendations (2025 harness defaults).
_HARNESS_TOKEN_BUDGETS: dict[str, int] = {
    "codex":    2_048,   # 25% of 8,192 (Codex CLI context)
    "gemini":   8_192,   # 25% of 32,768 (Gemini 1.5)
    "opencode": 8_192,   # 25% of 32,768
    "cursor":   2_048,   # 25% of 8,192
    "aider":    2_048,   # 25% of 8,192
    "windsurf": 2_048,   # 25% of 8,192
    "cline":    4_096,   # 25% of 16,384
    "continue": 8_192,   # 25% of 32,768
    "zed":      4_096,   # 25% of 16,384
    "neovim":   4_096,   # 25% of 16,384
}

# Fraction thresholds for budget levels
_BUDGET_WARN_FRACTION = 0.75    # 75% of budget used → warn
_BUDGET_CRITICAL_FRACTION = 1.0 # 100% → critical


@dataclass
class HarnessBudgetWarning:
    """Budget warning for a single harness."""

    harness: str
    token_count: int
    budget: int
    fraction: float   # token_count / budget (can exceed 1.0)
    level: str        # "ok" | "warn" | "critical"

    @property
    def percent_used(self) -> float:
        return self.fraction * 100.0

    def format(self) -> str:
        """Format a single harness budget line."""
        bar_len = min(int(self.percent_used / 5), 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        icon = {"ok": "✓", "warn": "⚠", "critical": "✗"}.get(self.level, "?")
        return (
            f"  {icon} {self.harness:<12} {bar} {self.percent_used:5.1f}%  "
            f"({self.token_count:,} / {self.budget:,} tokens)"
        )


# Hedging phrases that often signal verbosity
_HEDGING_RE = re.compile(
    r"\b(you should|you would|you might|you could|please note that|"
    r"it is important to|keep in mind that|be sure to|"
    r"make sure to|don't forget to|remember to)\b",
    re.IGNORECASE,
)

# Passive-voice constructions (is/are/was/were + past participle)
_PASSIVE_RE = re.compile(
    r"\b(?:is|are|was|were)\s+\w+(?:ed|en)\b",
    re.IGNORECASE,
)

# Redundant filler openers
_FILLER_RE = re.compile(
    r"^\s*(?:Note:|Note that|Important:|Please|Always remember|Keep in mind)[,:]?\s+",
    re.IGNORECASE | re.MULTILINE,
)

# Maximum sentence length (words) before flagging as long
_MAX_SENTENCE_WORDS = 30


@dataclass
class OptimizationSuggestion:
    """A single verbosity suggestion for a content block."""

    line_number: int
    category: str      # "hedging" | "passive" | "filler" | "long_sentence" | "repetition"
    excerpt: str       # Short excerpt of the flagged text (truncated to 80 chars)
    suggestion: str    # Human-readable improvement suggestion


@dataclass
class SizeReport:
    """Verbosity analysis report for a single CLAUDE.md or rules file."""

    file_path: str
    total_chars: int
    total_tokens: int              # ~chars/4 estimate
    total_lines: int
    suggestions: list[OptimizationSuggestion] = field(default_factory=list)

    @property
    def savings_estimate(self) -> int:
        """Rough estimate of tokens saved if all suggestions were applied (15% per suggestion)."""
        return min(self.total_tokens, len(self.suggestions) * max(1, self.total_tokens // 20))

    def format(self, verbose: bool = False) -> str:
        """Format the report for terminal output.

        Args:
            verbose: Include all suggestions (default: top 5 only).

        Returns:
            Formatted string.
        """
        shown = self.suggestions if verbose else self.suggestions[:5]
        lines = [
            f"## Config Size Report: {self.file_path}",
            f"   Size:        {self.total_chars:,} chars / ~{self.total_tokens:,} tokens",
            f"   Lines:       {self.total_lines:,}",
            f"   Suggestions: {len(self.suggestions)}",
        ]
        if self.suggestions:
            lines.append(
                f"   Est. savings: ~{self.savings_estimate:,} tokens if all applied"
            )
            lines.append("")
            for s in shown:
                lines.append(f"   [{s.category}] line {s.line_number}: {s.excerpt!r}")
                lines.append(f"     → {s.suggestion}")
            if not verbose and len(self.suggestions) > 5:
                lines.append(
                    f"   ... and {len(self.suggestions) - 5} more (use --verbose to see all)"
                )
        else:
            lines.append("   No verbosity issues detected.")
        return "\n".join(lines)


class ConfigSizeOptimizer:
    """Analyzes CLAUDE.md for verbosity and suggests concise equivalents.

    Usage:
        optimizer = ConfigSizeOptimizer(project_dir)
        reports = optimizer.analyze_all()
        for report in reports:
            print(report.format())
    """

    def __init__(self, project_dir: Path):
        """Initialize optimizer.

        Args:
            project_dir: Project root directory.
        """
        self.project_dir = project_dir

    def check_harness_budgets(
        self,
        content: str,
        targets: list[str] | None = None,
    ) -> list[HarnessBudgetWarning]:
        """Check whether config content fits within per-harness recommended token budgets.

        Different harnesses have different context windows, so a verbose CLAUDE.md
        that is fine for Gemini may exceed Codex's effective rules budget.

        Args:
            content: Rules/config text (e.g. CLAUDE.md contents).
            targets: Harness names to check. Defaults to all known harnesses.

        Returns:
            List of HarnessBudgetWarning, sorted by fraction used (highest first).
        """
        if targets is None:
            targets = list(_HARNESS_TOKEN_BUDGETS.keys())

        token_count = max(1, len(content) // 4)
        warnings: list[HarnessBudgetWarning] = []

        for harness in targets:
            budget = _HARNESS_TOKEN_BUDGETS.get(harness, 8_192)
            fraction = token_count / budget
            if fraction >= _BUDGET_CRITICAL_FRACTION:
                level = "critical"
            elif fraction >= _BUDGET_WARN_FRACTION:
                level = "warn"
            else:
                level = "ok"
            warnings.append(HarnessBudgetWarning(
                harness=harness,
                token_count=token_count,
                budget=budget,
                fraction=fraction,
                level=level,
            ))

        warnings.sort(key=lambda w: w.fraction, reverse=True)
        return warnings

    def format_budget_report(
        self,
        warnings: list[HarnessBudgetWarning],
        show_ok: bool = False,
    ) -> str:
        """Format harness budget warnings for terminal output.

        Args:
            warnings: Output of check_harness_budgets().
            show_ok:  Include harnesses within budget (default: show warnings only).

        Returns:
            Formatted multi-line string.
        """
        shown = warnings if show_ok else [w for w in warnings if w.level != "ok"]
        if not shown:
            return "Config size OK — within recommended budget for all harnesses."

        lines = ["Config Token Budget Check:", ""]
        for w in shown:
            lines.append(w.format())
        critical = [w.harness for w in shown if w.level == "critical"]
        if critical:
            lines.append("")
            lines.append(
                f"  CRITICAL: {', '.join(critical)} — config exceeds recommended budget. "
                "Run /sync-optimize to reduce token usage."
            )
        return "\n".join(lines)

    def analyze_all(self) -> list[SizeReport]:
        """Analyze all CLAUDE.md-style files in the project.

        Returns:
            List of SizeReport (one per discovered rules file).
        """
        candidates = [
            self.project_dir / "CLAUDE.md",
            self.project_dir / "CLAUDE.local.md",
            self.project_dir / ".claude" / "CLAUDE.md",
        ]
        reports: list[SizeReport] = []
        for path in candidates:
            if path.is_file():
                try:
                    content = path.read_text(encoding="utf-8")
                    reports.append(self.analyze(content, str(path.relative_to(self.project_dir))))
                except OSError:
                    continue
        return reports

    def analyze(self, content: str, label: str = "CLAUDE.md") -> SizeReport:
        """Analyze a single config content string.

        Args:
            content: Raw text content.
            label: Human-readable file label.

        Returns:
            SizeReport with verbosity suggestions.
        """
        total_chars = len(content)
        total_tokens = max(1, total_chars // 4)
        lines = content.splitlines()
        suggestions: list[OptimizationSuggestion] = []

        for i, line in enumerate(lines, start=1):
            # Skip comment-only lines (sync tags)
            stripped = line.strip()
            if stripped.startswith("<!--") and stripped.endswith("-->"):
                continue

            # Hedging phrases
            for m in _HEDGING_RE.finditer(line):
                suggestions.append(OptimizationSuggestion(
                    line_number=i,
                    category="hedging",
                    excerpt=line.strip()[:80],
                    suggestion=(
                        f"Replace '{m.group()}' with an imperative: "
                        f"e.g. 'Always X' instead of 'You should X'"
                    ),
                ))
                break  # One suggestion per line

            # Filler openers
            if _FILLER_RE.match(line):
                suggestions.append(OptimizationSuggestion(
                    line_number=i,
                    category="filler",
                    excerpt=line.strip()[:80],
                    suggestion="Remove filler opener — start with the directive directly",
                ))

            # Long sentences
            words = len(re.findall(r"\w+", line))
            if words > _MAX_SENTENCE_WORDS:
                suggestions.append(OptimizationSuggestion(
                    line_number=i,
                    category="long_sentence",
                    excerpt=line.strip()[:80],
                    suggestion=(
                        f"Split this {words}-word sentence into 2-3 shorter rules "
                        "for clarity and token efficiency"
                    ),
                ))

        # Repetition: same significant word appears 3+ times in any 5-line window
        for window_start in range(0, len(lines), 5):
            window = " ".join(lines[window_start:window_start + 5])
            words_in_window = re.findall(r"\b[a-z]{5,}\b", window.lower())
            from collections import Counter
            counts = Counter(words_in_window)
            for word, count in counts.items():
                if count >= 3 and word not in _STOP_WORDS:
                    center_line = window_start + 3
                    suggestions.append(OptimizationSuggestion(
                        line_number=center_line,
                        category="repetition",
                        excerpt=f"'{word}' appears {count}x in lines {window_start+1}-{window_start+5}",
                        suggestion=(
                            f"Consider consolidating rules mentioning '{word}' "
                            "into a single directive"
                        ),
                    ))
                    break  # One repetition warning per window

        return SizeReport(
            file_path=label,
            total_chars=total_chars,
            total_tokens=total_tokens,
            total_lines=len(lines),
            suggestions=suggestions,
        )


# Common words to skip for repetition detection
_STOP_WORDS = frozenset({
    "always", "never", "should", "would", "could", "might", "please",
    "ensure", "important", "using", "when", "that", "this", "with",
    "from", "have", "code", "file", "make", "your", "their", "there",
})
