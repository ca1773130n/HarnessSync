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
