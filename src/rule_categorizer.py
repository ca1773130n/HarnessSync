from __future__ import annotations

"""Automatic Rule Categorization & Tagging (item 9).

Analyzes CLAUDE.md rules using heuristic patterns to auto-tag each rule
as one of: 'style', 'security', 'workflow', 'tool-use', 'testing',
'documentation', 'performance', or 'general'.

Tags are used to filter sync by category — e.g., sync only 'security' rules
to all harnesses while keeping 'style' rules Claude Code-only.

Usage::

    from src.rule_categorizer import RuleCategorizer

    categorizer = RuleCategorizer()
    rules = categorizer.categorize_text(claude_md_text)
    for rule in rules:
        print(f"[{rule.category}] {rule.title}: {rule.tags}")

    # Filter rules by category
    security_rules = categorizer.filter_by_tag(rules, "security")

    # Apply tag-based sync filter: keep only rules with allowed tags
    filtered_text = categorizer.filter_content_by_tags(
        claude_md_text,
        allowed_tags={"security", "workflow"},
    )
"""

import re
from dataclasses import dataclass, field


# ── Known categories and their heuristic keyword patterns ─────────────────

CATEGORIES: dict[str, list[re.Pattern]] = {
    "security": [
        re.compile(r"\b(secret|api.?key|token|password|credential|auth|oauth|jwt|encrypt|hash|sanitiz|sql.inject|xss|csrf|cors|permission|privilege|scope|rbac|iam)\b", re.I),
        re.compile(r"\b(never (commit|store|log|expose|hardcode))\b", re.I),
        re.compile(r"\b(secret.detect|vault|keychain|env.var)\b", re.I),
    ],
    "style": [
        re.compile(r"\b(format|indent|spacing|tab|whitespace|trailing|blank.line|newline|semicolon|quote|brace|bracket|naming|camel.?case|snake.?case|kebab|pascal)\b", re.I),
        re.compile(r"\b(prettier|eslint|ruff|black|isort|flake8|pylint|rubocop|gofmt|rustfmt)\b", re.I),
        re.compile(r"\b(line.length|max.line|column.limit|80.char|120.char)\b", re.I),
        re.compile(r"\b(comment|docstring|jsdoc|pydoc|annotation|type.hint)\b", re.I),
    ],
    "testing": [
        re.compile(r"\b(test|spec|assert|mock|stub|fixture|coverage|unit.test|integration.test|e2e|tdd|bdd|pytest|jest|mocha|vitest|rspec)\b", re.I),
        re.compile(r"\b(test.file|test.suite|test.case|test.data|snapshot.test|regression.test)\b", re.I),
    ],
    "workflow": [
        re.compile(r"\b(commit|pull.request|pr|branch|merge|rebase|review|ci.?cd|pipeline|deploy|release|changelog|versioning|semver|conventional.commit)\b", re.I),
        re.compile(r"\b(git|github|gitlab|bitbucket|jira|linear|ticket|issue|milestone)\b", re.I),
        re.compile(r"\b(workflow|process|procedure|checklist|step|phase|sprint|agile|scrum)\b", re.I),
    ],
    "tool-use": [
        re.compile(r"\b(bash|grep|awk|sed|curl|wget|docker|kubectl|helm|terraform|ansible|make|npm|pip|cargo|go\s+build)\b", re.I),
        re.compile(r"\b(claude.code|gemini|codex|opencode|aider|cursor|windsurf|mcp|tool.call)\b", re.I),
        re.compile(r"\b(read.tool|write.tool|edit.tool|glob.tool|agent.tool|bash.tool)\b", re.I),
        re.compile(r"\b(use\s+(the\s+)?(bash|read|write|edit|glob|grep|agent|task|todo)\s+tool)\b", re.I),
    ],
    "performance": [
        re.compile(r"\b(performance|speed|latency|throughput|cache|optimize|efficient|fast|slow|bottleneck|profile|benchmark|lazy.load|memoize|debounce|throttle)\b", re.I),
        re.compile(r"\b(n\+1|query.optimization|index|database.performance|streaming|pagination|chunk)\b", re.I),
    ],
    "documentation": [
        re.compile(r"\b(document|readme|changelog|api.doc|javadoc|sphinx|mkdocs|docusaurus|wiki|runbook|adr|architecture.decision)\b", re.I),
        re.compile(r"\b(explain|describe|clarify|comment\s+why|self.document)\b", re.I),
    ],
    "error-handling": [
        re.compile(r"\b(error.handling|exception|try.catch|raise|throw|fallback|retry|circuit.breaker|timeout|fail.safe|graceful.degrad)\b", re.I),
        re.compile(r"\b(log.error|warn|alert|monitor|observ|sentry|datadog|prometheus)\b", re.I),
    ],
}

# Default category when no pattern matches
DEFAULT_CATEGORY = "general"

# Minimum score to accept a category (patterns matched)
_MIN_SCORE = 1


@dataclass
class CategorizedRule:
    """A single rule extracted from CLAUDE.md with category tags."""

    title: str                            # Heading text (without # prefix)
    content: str                          # Full rule body including heading
    category: str                         # Primary category
    tags: list[str] = field(default_factory=list)  # All matched categories
    line_start: int = 0                   # 1-based line number of heading
    confidence: str = "medium"           # "high" | "medium" | "low"


@dataclass
class CategorizationResult:
    """Result of categorizing all rules in a CLAUDE.md file."""

    rules: list[CategorizedRule] = field(default_factory=list)
    tag_counts: dict[str, int] = field(default_factory=dict)

    def filter_by_tag(self, tag: str) -> list[CategorizedRule]:
        """Return rules that include the given tag."""
        return [r for r in self.rules if tag in r.tags]

    def format_summary(self) -> str:
        """Return a human-readable summary of categorized rules."""
        if not self.rules:
            return "No rules found."
        lines = [f"Rule Categorization ({len(self.rules)} rules):"]
        for tag, count in sorted(self.tag_counts.items(), key=lambda x: -x[1]):
            lines.append(f"  {tag:<20} {count:>3} rule(s)")
        return "\n".join(lines)

    def format_detail(self) -> str:
        """Return detailed listing per rule."""
        if not self.rules:
            return "No rules found."
        lines = []
        for rule in self.rules:
            tags_str = ", ".join(rule.tags) if rule.tags else rule.category
            lines.append(f"  [{rule.category}] {rule.title} ({tags_str})")
        return "\n".join(lines)


# ── Heading extraction ─────────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def _split_into_sections(text: str) -> list[tuple[int, int, str, str]]:
    """Split text into sections by headings.

    Returns list of (line_start, level, title, full_section_text).
    Only captures H2 and H3 sections (## and ###) as rule blocks.
    """
    matches = list(_HEADING_RE.finditer(text))
    sections = []

    for i, match in enumerate(matches):
        level = len(match.group(1))
        if level > 3:
            continue  # Skip deep headings — they're subsections, not rules

        title = match.group(2).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end]

        # Calculate 1-based line number
        line_start = text[:start].count("\n") + 1
        sections.append((line_start, level, title, section_text))

    return sections


# ── Category scoring ────────────────────────────────────────────────────────

def _score_text(text: str) -> dict[str, int]:
    """Score text against all category patterns, returning match counts."""
    scores: dict[str, int] = {}
    for category, patterns in CATEGORIES.items():
        count = sum(len(p.findall(text)) for p in patterns)
        if count >= _MIN_SCORE:
            scores[category] = count
    return scores


def _pick_primary(scores: dict[str, int]) -> tuple[str, str]:
    """Pick primary category and confidence from score map."""
    if not scores:
        return DEFAULT_CATEGORY, "low"

    best = max(scores, key=scores.get)
    top_score = scores[best]

    if top_score >= 3:
        confidence = "high"
    elif top_score >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return best, confidence


# ── Public API ──────────────────────────────────────────────────────────────

class RuleCategorizer:
    """Categorizes CLAUDE.md rules using heuristic keyword patterns.

    No external dependencies or API calls required — fully offline.
    """

    def categorize_text(self, text: str) -> CategorizationResult:
        """Parse and categorize all rules found in *text*.

        Args:
            text: Full CLAUDE.md content.

        Returns:
            CategorizationResult with per-rule tags and a tag-count summary.
        """
        sections = _split_into_sections(text)
        result = CategorizationResult()

        for line_start, _level, title, section_text in sections:
            scores = _score_text(section_text)
            primary, confidence = _pick_primary(scores)
            # All categories that scored above threshold become tags
            tags = sorted(scores.keys(), key=lambda c: -scores[c])
            if not tags:
                tags = [DEFAULT_CATEGORY]

            rule = CategorizedRule(
                title=title,
                content=section_text,
                category=primary,
                tags=tags,
                line_start=line_start,
                confidence=confidence,
            )
            result.rules.append(rule)

            for tag in tags:
                result.tag_counts[tag] = result.tag_counts.get(tag, 0) + 1

        return result

    def filter_content_by_tags(
        self,
        text: str,
        allowed_tags: set[str],
        *,
        include_untagged: bool = True,
    ) -> str:
        """Return *text* with only sections matching *allowed_tags* preserved.

        Sections that match none of the allowed tags are removed.  Sections
        that categorize as 'general' (no heuristic match) are preserved when
        *include_untagged* is True (default).

        Args:
            text: Full CLAUDE.md content.
            allowed_tags: Set of category names to keep (e.g. {"security", "workflow"}).
            include_untagged: Whether to preserve rules with no category match.

        Returns:
            Filtered content string.
        """
        sections = _split_into_sections(text)
        if not sections:
            return text

        # Build a set of sections to keep
        keep_ranges: list[tuple[int, int]] = []  # (start_char, end_char) in text

        matches = list(_HEADING_RE.finditer(text))
        for i, match in enumerate(matches):
            level = len(match.group(1))
            if level > 3:
                # Always keep deep headings (they're part of a parent section)
                keep_ranges.append((match.start(), matches[i + 1].start() if i + 1 < len(matches) else len(text)))
                continue

            start = match.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            section_text = text[start:end]

            scores = _score_text(section_text)
            tags = set(scores.keys()) if scores else {DEFAULT_CATEGORY}

            should_keep = bool(tags & allowed_tags)
            if not should_keep and include_untagged and not scores:
                should_keep = True  # no heuristic match → keep as untagged

            if should_keep:
                keep_ranges.append((start, end))

        if not keep_ranges:
            return ""

        # Merge overlapping ranges and reconstruct text
        keep_ranges.sort()
        merged: list[tuple[int, int]] = []
        for start, end in keep_ranges:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        # Preserve any preamble before first heading
        first_heading_start = matches[0].start() if matches else len(text)
        preamble = text[:first_heading_start]

        parts = [preamble] + [text[s:e] for s, e in merged]
        return "".join(parts)


# ---------------------------------------------------------------------------
# Rule Portability Triage (item 11)
# ---------------------------------------------------------------------------

# Patterns that indicate a rule uses Claude Code-specific syntax or features
# that will NOT be understood by other harnesses.
_CC_ONLY_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(allowed-tools|tool-calls|agent-tool|task-tool)\b", re.I),
    re.compile(r"<tool_call>|</tool_call>", re.I),
    re.compile(r"\b(EnterPlanMode|ExitPlanMode|TodoWrite|TodoRead|NotebookEdit|NotebookRead)\b"),
    re.compile(r"\b(MultiEdit|ExitWorktree|EnterWorktree)\b"),
    re.compile(r"\.claude/(skills|agents|commands|hooks)/"),
    re.compile(r"\$CLAUDE_PLUGIN_ROOT|\bclaudeCode\b|\bclaude-code\b", re.I),
    re.compile(r"\bclaude settings\.json\b", re.I),
    re.compile(r"\b(claude code plugin|harness.sync skill)\b", re.I),
]

# Patterns that indicate the rule will need approximation / translation
_APPROX_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(skill|skills|slash command|/[a-z][-a-z]+)\b", re.I),
    re.compile(r"\b(mcp server|mcp tool|mcp_server)\b", re.I),
    re.compile(r"\b(agent|sub.?agent)\b", re.I),
    re.compile(r"\b(hook|post.?tool|pre.?tool|on.?tool)\b", re.I),
    re.compile(r"\b(context window|token limit|max.?token)\b", re.I),
    re.compile(r"\b(keybinding|keyboard shortcut|hotkey)\b", re.I),
]


@dataclass
class RulePortability:
    """Portability classification for a single CLAUDE.md rule section.

    Attributes:
        title:       Section heading text.
        portability: One of ``"universal"``, ``"claude-code-only"``, ``"approximable"``.
        reason:      Short explanation of the classification.
        suggestion:  Recommendation to improve portability (empty if already universal).
        line_start:  1-based line number of the section heading.
    """

    title: str
    portability: str       # "universal" | "claude-code-only" | "approximable"
    reason: str
    suggestion: str
    line_start: int = 0


def triage_by_portability(text: str) -> list[RulePortability]:
    """Classify each rule section in *text* by its portability across harnesses.

    Portability levels:
    - ``"universal"``        — works the same in all harnesses.
    - ``"approximable"``     — contains features that other harnesses can emulate
                               with translation (e.g., skills become context files).
    - ``"claude-code-only"`` — contains CC-specific syntax that will silently fail
                               or be ignored in other harnesses.

    Args:
        text: Full CLAUDE.md content (or any rules document).

    Returns:
        List of :class:`RulePortability` entries, one per H2/H3 section.
    """
    sections = _split_into_sections(text)
    results: list[RulePortability] = []

    for line_start, _level, title, section_text in sections:
        # Check for CC-only patterns first (stronger signal)
        cc_matches = [p.pattern for p in _CC_ONLY_PATTERNS if p.search(section_text)]
        if cc_matches:
            results.append(RulePortability(
                title=title,
                portability="claude-code-only",
                reason=f"Uses Claude Code-specific feature(s): {cc_matches[0]}",
                suggestion=(
                    "Rewrite using portable language (e.g., 'use a reusable workflow' "
                    "instead of 'invoke a skill'). Remove CC tool names and XML blocks."
                ),
                line_start=line_start,
            ))
            continue

        # Check for approximable patterns
        approx_matches = [p.pattern for p in _APPROX_PATTERNS if p.search(section_text)]
        if approx_matches:
            results.append(RulePortability(
                title=title,
                portability="approximable",
                reason=f"References feature that requires translation: {approx_matches[0]}",
                suggestion=(
                    "Consider providing a portable fallback description so harnesses "
                    "without this feature can still apply the intent of the rule."
                ),
                line_start=line_start,
            ))
            continue

        results.append(RulePortability(
            title=title,
            portability="universal",
            reason="No harness-specific syntax detected.",
            suggestion="",
            line_start=line_start,
        ))

    return results


def format_portability_triage(entries: list[RulePortability]) -> str:
    """Return a terminal-friendly summary of portability triage results.

    Args:
        entries: Output of :func:`triage_by_portability`.

    Returns:
        Formatted multi-line string.
    """
    if not entries:
        return "No rule sections found to triage."

    counts = {"universal": 0, "approximable": 0, "claude-code-only": 0}
    for e in entries:
        counts[e.portability] = counts.get(e.portability, 0) + 1

    lines = [
        f"Rule Portability Triage  ({len(entries)} sections)",
        "=" * 55,
        f"  Universal      : {counts['universal']:>3}",
        f"  Approximable   : {counts['approximable']:>3}",
        f"  Claude Code Only: {counts['claude-code-only']:>3}",
        "",
    ]
    for e in entries:
        badge = {
            "universal":        "[UNIVERSAL  ]",
            "approximable":     "[APPROXIMABLE]",
            "claude-code-only": "[CC ONLY     ]",
        }.get(e.portability, "[?]")
        lines.append(f"  {badge} L{e.line_start:<4} {e.title}")
        if e.suggestion:
            lines.append(f"             → {e.suggestion[:80]}")
    return "\n".join(lines)
