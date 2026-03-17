from __future__ import annotations

"""AI Rule Quality Scorer.

Analyzes rules in CLAUDE.md for clarity, specificity, and actionability,
scoring each rule and suggesting improvements before sync. Vague rules like
'write good code' waste context in every harness — this scorer helps users
write rules that actually change AI behavior.

Scoring dimensions (each 0-10):
  clarity      — Is the rule easy to understand without ambiguity?
  specificity  — Does it name concrete actions/patterns rather than abstractions?
  actionability — Can an AI agent act on it immediately without interpretation?
  conciseness  — Is it as short as possible without losing meaning?

Overall score = weighted average (clarity 30%, specificity 30%, actionability 30%, conciseness 10%)

No external dependencies — all analysis is regex/heuristic-based so it works
offline without any API calls.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


# ---------------------------------------------------------------------------
# Heuristic patterns
# ---------------------------------------------------------------------------

# Vague words that signal low specificity
_VAGUE_WORDS = re.compile(
    r"\b(good|bad|proper|nice|clean|appropriate|correctly|correctly|well|better|best|"
    r"effective|efficient|quality|improve|enhance|ensure|make sure|try to|consider|"
    r"whenever possible|as needed|if applicable|might|could|should probably)\b",
    re.IGNORECASE,
)

# Concrete action verbs that signal high actionability
_ACTION_VERBS = re.compile(
    r"\b(use|prefer|always|never|avoid|require|write|add|remove|include|exclude|"
    r"format|indent|name|import|export|return|throw|catch|log|test|comment|document|"
    r"run|check|validate|assert|define|declare|call|invoke)\b",
    re.IGNORECASE,
)

# Negations that can reduce actionability (double negatives, unclear prohibitions)
_AMBIGUOUS_NEGATION = re.compile(
    r"\b(do not not|should not never|avoid not)\b", re.IGNORECASE
)

# Long rules (>200 chars) that likely need splitting
_MAX_CLEAR_LENGTH = 200

# Patterns that indicate concrete examples (good)
_HAS_EXAMPLE = re.compile(
    r"(e\.g\.|for example|such as|like:|e\.g:|``|```|\bfor instance\b|→|->|:$)",
    re.IGNORECASE,
)

# Patterns for absolute directives — highly actionable
_ABSOLUTE_DIRECTIVE = re.compile(
    r"^[-*•]?\s*(always|never|do not|don't|must|use|prefer|avoid|require|write)\b",
    re.IGNORECASE | re.MULTILINE,
)

# Too-generic rules that add nothing
_GENERIC_RULES = [
    re.compile(r"\bwrite (good|clean|quality|high.quality) code\b", re.I),
    re.compile(r"\bfollow best practices\b", re.I),
    re.compile(r"\bkeep (it|the code) simple\b", re.I),
    re.compile(r"\bbe (consistent|clear|concise)\b", re.I),
    re.compile(r"\bmaintain (code quality|standards)\b", re.I),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RuleScore:
    """Scores and suggestions for a single rule."""
    text: str
    line_number: int
    clarity: float          # 0-10
    specificity: float      # 0-10
    actionability: float    # 0-10
    conciseness: float      # 0-10
    overall: float          # 0-10
    suggestions: list[str] = field(default_factory=list)
    is_generic: bool = False

    @property
    def grade(self) -> str:
        if self.overall >= 8.0:
            return "A"
        if self.overall >= 6.0:
            return "B"
        if self.overall >= 4.0:
            return "C"
        return "D"


@dataclass
class QualityReport:
    """Quality report for a full CLAUDE.md or rules string."""
    scores: list[RuleScore] = field(default_factory=list)
    mean_overall: float = 0.0
    low_quality_rules: list[RuleScore] = field(default_factory=list)

    def format(self, show_all: bool = False) -> str:
        """Render the report as a human-readable string."""
        if not self.scores:
            return "No rules found to analyze."

        lines: list[str] = []
        lines.append(f"Rule Quality Report — {len(self.scores)} rules analyzed")
        lines.append(f"Average score: {self.mean_overall:.1f}/10")
        lines.append("=" * 50)

        to_show = self.scores if show_all else self.low_quality_rules
        if not to_show and not show_all:
            lines.append("✓ All rules passed quality thresholds.")
            return "\n".join(lines)

        for rs in to_show:
            lines.append(
                f"\n  Line {rs.line_number:>3}: [{rs.grade}] {rs.overall:.1f}/10"
                f"{'  ⚠ generic' if rs.is_generic else ''}"
            )
            preview = rs.text[:100] + ("..." if len(rs.text) > 100 else "")
            lines.append(f"  '{preview}'")
            lines.append(
                f"  clarity={rs.clarity:.0f}  specificity={rs.specificity:.0f}"
                f"  actionability={rs.actionability:.0f}  conciseness={rs.conciseness:.0f}"
            )
            for suggestion in rs.suggestions:
                lines.append(f"  → {suggestion}")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------

class RuleQualityScorer:
    """Score rules in a CLAUDE.md file for clarity, specificity, actionability.

    Args:
        min_rule_length: Minimum character count to consider a line a rule.
        low_quality_threshold: Rules with overall score below this are flagged.
    """

    def __init__(
        self,
        min_rule_length: int = 15,
        low_quality_threshold: float = 5.0,
    ):
        self.min_rule_length = min_rule_length
        self.low_quality_threshold = low_quality_threshold

    def score_text(self, content: str) -> QualityReport:
        """Score all rules extracted from a string.

        Args:
            content: CLAUDE.md content to analyze.

        Returns:
            QualityReport with per-rule scores and suggestions.
        """
        rules = _extract_rule_items(content)
        if not rules:
            return QualityReport()

        scores: list[RuleScore] = [self._score_rule(text, lineno) for text, lineno in rules]

        if scores:
            mean_overall = sum(s.overall for s in scores) / len(scores)
        else:
            mean_overall = 0.0

        low_quality = [s for s in scores if s.overall < self.low_quality_threshold]

        return QualityReport(
            scores=scores,
            mean_overall=round(mean_overall, 2),
            low_quality_rules=low_quality,
        )

    def score_file(self, path: Path) -> QualityReport:
        """Score rules in a CLAUDE.md file."""
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            report = QualityReport()
            report.mean_overall = 0.0
            return report
        return self.score_text(content)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _score_rule(self, text: str, lineno: int) -> RuleScore:
        """Compute dimension scores for a single rule text."""
        clarity = self._score_clarity(text)
        specificity = self._score_specificity(text)
        actionability = self._score_actionability(text)
        conciseness = self._score_conciseness(text)
        is_generic = any(p.search(text) for p in _GENERIC_RULES)

        # Weighted average
        overall = (
            0.30 * clarity
            + 0.30 * specificity
            + 0.30 * actionability
            + 0.10 * conciseness
        )
        if is_generic:
            overall = min(overall, 3.0)

        suggestions = self._build_suggestions(text, clarity, specificity, actionability, conciseness, is_generic)

        return RuleScore(
            text=text,
            line_number=lineno,
            clarity=round(clarity, 1),
            specificity=round(specificity, 1),
            actionability=round(actionability, 1),
            conciseness=round(conciseness, 1),
            overall=round(overall, 1),
            suggestions=suggestions,
            is_generic=is_generic,
        )

    def _score_clarity(self, text: str) -> float:
        score = 8.0
        # Penalise ambiguous negations
        if _AMBIGUOUS_NEGATION.search(text):
            score -= 3.0
        # Penalise extremely long rules (hard to parse)
        if len(text) > _MAX_CLEAR_LENGTH:
            score -= 2.0
        elif len(text) > 120:
            score -= 1.0
        # Reward examples
        if _HAS_EXAMPLE.search(text):
            score += 1.5
        # Penalise vague words (up to -3)
        vague_hits = len(_VAGUE_WORDS.findall(text))
        score -= min(vague_hits * 0.8, 3.0)
        return max(0.0, min(10.0, score))

    def _score_specificity(self, text: str) -> float:
        score = 5.0
        vague_hits = len(_VAGUE_WORDS.findall(text))
        score -= min(vague_hits * 1.2, 4.0)
        # Reward named technologies, file extensions, concrete nouns
        if re.search(r"\.(py|ts|js|json|yaml|toml|md|css|html)\b", text, re.I):
            score += 1.5
        if re.search(r"\b\d+\b", text):  # Contains a number (e.g. "2-space indent")
            score += 1.5
        if _HAS_EXAMPLE.search(text):
            score += 2.0
        if re.search(r"`[^`]+`", text):  # Inline code
            score += 1.5
        if is_generic := any(p.search(text) for p in _GENERIC_RULES):
            score = min(score, 2.0)
        return max(0.0, min(10.0, score))

    def _score_actionability(self, text: str) -> float:
        score = 4.0
        if _ABSOLUTE_DIRECTIVE.search(text):
            score += 3.5
        action_count = len(_ACTION_VERBS.findall(text))
        score += min(action_count * 0.8, 3.0)
        if any(p.search(text) for p in _GENERIC_RULES):
            score = min(score, 2.0)
        # Penalise hedge words that reduce actionability
        hedges = re.findall(
            r"\b(might|could|consider|try|whenever possible|if applicable|as needed)\b",
            text, re.I
        )
        score -= min(len(hedges) * 1.0, 3.0)
        return max(0.0, min(10.0, score))

    def _score_conciseness(self, text: str) -> float:
        length = len(text)
        if length <= 60:
            return 10.0
        if length <= 100:
            return 8.0
        if length <= 150:
            return 6.0
        if length <= 200:
            return 4.0
        if length <= 300:
            return 2.0
        return 1.0

    def _build_suggestions(
        self,
        text: str,
        clarity: float,
        specificity: float,
        actionability: float,
        conciseness: float,
        is_generic: bool,
    ) -> list[str]:
        suggestions: list[str] = []

        if is_generic:
            suggestions.append(
                "Replace with a specific, actionable rule. "
                "e.g. 'Use 2-space indentation in all Python files.' instead of 'write clean code.'"
            )
            return suggestions  # No more suggestions needed for fully generic rules

        vague_hits = _VAGUE_WORDS.findall(text)
        if vague_hits:
            unique_vague = list(dict.fromkeys(v.lower() for v in vague_hits))[:3]
            suggestions.append(
                f"Replace vague words ({', '.join(unique_vague)}) with concrete equivalents. "
                "e.g. 'properly formatted' → 'formatted with Black (line length 88).'"
            )

        if actionability < 5.0 and not _ABSOLUTE_DIRECTIVE.search(text):
            suggestions.append(
                "Start with a directive verb: 'Always', 'Never', 'Use', 'Prefer', 'Avoid'. "
                "e.g. 'Code should be tested' → 'Always write unit tests for public functions.'"
            )

        if specificity < 5.0 and not _HAS_EXAMPLE.search(text):
            suggestions.append(
                "Add a concrete example or name a specific tool/pattern. "
                "e.g. 'Use type hints (e.g. def foo(x: int) -> str:).'"
            )

        if conciseness < 5.0:
            suggestions.append(
                "This rule is long — consider splitting into multiple focused rules "
                "or trimming to the essential directive."
            )

        return suggestions


# ---------------------------------------------------------------------------
# Helper: extract rule items from CLAUDE.md content
# ---------------------------------------------------------------------------

def _extract_rule_items(content: str) -> list[tuple[str, int]]:
    """Extract individual rule items from markdown content.

    Returns list of (rule_text, line_number) tuples.
    Focuses on list items and short paragraphs that look like rules.
    """
    results: list[tuple[str, int]] = []
    lines = content.splitlines()

    # Collect list items (- rule text / * rule text / 1. rule text)
    _LIST_ITEM = re.compile(r"^\s*[-*•]\s+(.+)$")
    _NUMBERED_ITEM = re.compile(r"^\s*\d+[.)]\s+(.+)$")

    for lineno, line in enumerate(lines, start=1):
        m = _LIST_ITEM.match(line) or _NUMBERED_ITEM.match(line)
        if m:
            text = m.group(1).strip()
            if len(text) >= 15:  # Skip trivial items
                results.append((text, lineno))

    # Also include short non-heading paragraphs (1-2 lines)
    in_code_block = False
    para_buf: list[str] = []
    para_start = 0

    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if stripped.startswith("#"):
            para_buf = []
            continue
        if stripped.startswith(("- ", "* ", "• ")) or re.match(r"^\d+[.)]\s", stripped):
            para_buf = []
            continue

        if stripped:
            if not para_buf:
                para_start = lineno
            para_buf.append(stripped)
        else:
            if para_buf:
                text = " ".join(para_buf)
                if 15 <= len(text) <= 400 and not text.startswith("<!--"):
                    # Only include if not already captured as a list item
                    results.append((text, para_start))
            para_buf = []

    # Flush last paragraph
    if para_buf:
        text = " ".join(para_buf)
        if 15 <= len(text) <= 400 and not text.startswith("<!--"):
            results.append((text, para_start))

    # Deduplicate by text (keep first occurrence)
    seen: set[str] = set()
    deduped: list[tuple[str, int]] = []
    for text, lineno in results:
        if text not in seen:
            seen.add(text)
            deduped.append((text, lineno))

    return deduped
