from __future__ import annotations

"""
Rule annotation auto-suggester.

Analyzes each rule's content and suggests ``@only:`` or ``@skip:`` tags
based on harness-specific terminology or references it detects.

Users write harness-specific rules without realizing it — this module catches
those cases and surfaces a suggestion so the right ``<!-- @harness:... -->``
annotation can be added to avoid polluting other harnesses with irrelevant
instructions.

Detection strategy:
- Keyword scanning: look for harness-specific CLI names, file patterns, or
  concepts that only apply to one harness family.
- Path references: detect paths like ``.cursor/``, ``.aider.conf.yml``,
  ``AGENTS.md``, etc. as strong signals.
- Capability references: flags like ``--yes``, ``/sync``, slash commands that
  only exist in specific harnesses.

Usage::

    from src.rule_annotation_suggester import RuleAnnotationSuggester

    suggester = RuleAnnotationSuggester()
    suggestions = suggester.analyze_rules(rules)
    for s in suggestions:
        print(s.format())
"""

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Harness-specific signal patterns
# ---------------------------------------------------------------------------

# Maps harness name -> list of (regex, description) pairs.
# A match is a strong signal that the rule content is harness-specific.
_HARNESS_SIGNALS: dict[str, list[tuple[re.Pattern, str]]] = {
    "codex": [
        (re.compile(r"\bcodex\b", re.I), "mentions Codex"),
        (re.compile(r"\bAGENTS\.md\b"), "references AGENTS.md (Codex format)"),
        (re.compile(r"\bcodex\.toml\b", re.I), "references codex.toml"),
        (re.compile(r"\\.codex[\\/]", re.I), "references .codex/ directory"),
        (re.compile(r"\bapproval_policy\b", re.I), "uses Codex approval_policy setting"),
    ],
    "gemini": [
        (re.compile(r"\bgemini\b(?!\s+api)", re.I), "mentions Gemini CLI"),
        (re.compile(r"\bGEMINI\.md\b"), "references GEMINI.md"),
        (re.compile(r"\\.gemini[\\/]", re.I), "references .gemini/ directory"),
        (re.compile(r"\bgemini\s+cli\b", re.I), "references Gemini CLI"),
    ],
    "cursor": [
        (re.compile(r"\bcursor\b(?!\s+position)", re.I), "mentions Cursor IDE"),
        (re.compile(r"\\.cursor[\\/]", re.I), "references .cursor/ directory"),
        (re.compile(r"\\.cursorrules\b"), "references .cursorrules file"),
        (re.compile(r"\\.mdc\b"), "references .mdc rule files (Cursor format)"),
        (re.compile(r"\balwaysApply\b"), "uses Cursor alwaysApply frontmatter"),
        (re.compile(r"\bcursor\s+rules\b", re.I), "references Cursor rules concept"),
    ],
    "aider": [
        (re.compile(r"\baider\b", re.I), "mentions Aider"),
        (re.compile(r"\\.aider\.conf\.yml\b"), "references .aider.conf.yml"),
        (re.compile(r"\baider\s+--yes\b", re.I), "references Aider --yes flag"),
        (re.compile(r"\bCONVENTIONS\.md\b"), "references CONVENTIONS.md (Aider style)"),
        (re.compile(r"\baider\s+chat\b", re.I), "references Aider chat mode"),
    ],
    "windsurf": [
        (re.compile(r"\bwindsurf\b", re.I), "mentions Windsurf IDE"),
        (re.compile(r"\\.windsurfrules\b"), "references .windsurfrules file"),
        (re.compile(r"\\.windsurf[\\/]", re.I), "references .windsurf/ directory"),
        (re.compile(r"\bcodeium\b", re.I), "mentions Codeium (Windsurf maker)"),
        (re.compile(r"\bcascade\s+rules?\b", re.I), "references Windsurf cascade rules"),
    ],
    "opencode": [
        (re.compile(r"\bopencode\b", re.I), "mentions OpenCode"),
        (re.compile(r"\bopencode\.json\b", re.I), "references opencode.json"),
        (re.compile(r"\\.opencode[\\/]", re.I), "references .opencode/ directory"),
    ],
    "cline": [
        (re.compile(r"\bcline\b", re.I), "mentions Cline"),
        (re.compile(r"\\.clinerules\b"), "references .clinerules"),
        (re.compile(r"\\.roo[\\/]", re.I), "references .roo/ directory (Cline)"),
    ],
    "continue": [
        (re.compile(r"\bcontinue\b(?!\s+to|\s+reading)", re.I), "mentions Continue.dev"),
        (re.compile(r"\\.continue[\\/]", re.I), "references .continue/ directory"),
    ],
    "zed": [
        (re.compile(r"\bzed\b(?!\s+editor|\s+out)", re.I), "mentions Zed editor"),
        (re.compile(r"\\.zed[\\/]", re.I), "references .zed/ directory"),
    ],
    "neovim": [
        (re.compile(r"\bneovim\b|\bavante\b", re.I), "mentions Neovim/Avante"),
        (re.compile(r"\\.avante[\\/]", re.I), "references .avante/ directory"),
    ],
}

# Claude Code-specific signals (only makes sense in Claude Code context)
_CLAUDE_CODE_SIGNALS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bCLAUDE\.md\b"), "references CLAUDE.md"),
    (re.compile(r"\b/sync\b"), "references /sync slash command"),
    (re.compile(r"\bMCP\b"), "references MCP servers"),
    (re.compile(r"\b\.claude[\\/]", re.I), "references .claude/ directory"),
    (re.compile(r"\bclaude\s+code\b", re.I), "references Claude Code"),
    (re.compile(r"\bskills?\s+dir", re.I), "references skills directory"),
]

# Minimum number of signal matches to trigger a suggestion
_MIN_SIGNAL_STRENGTH = 1


@dataclass
class AnnotationSuggestion:
    """A suggestion to add a harness-scoping annotation to a rule."""

    rule_path: str             # Source path of the rule file
    rule_excerpt: str          # First 100 chars of the matching content
    suggested_annotation: str  # The annotation to add, e.g. "@harness:cursor-only"
    harness: str               # The detected harness name
    signals: list[str] = field(default_factory=list)  # What triggered detection
    confidence: str = "low"    # "low" | "medium" | "high"

    def format(self) -> str:
        """Return a formatted suggestion string for display."""
        lines = [
            f"  Rule: {self.rule_path}",
            f"  Detected: {self.harness} ({self.confidence} confidence)",
        ]
        for sig in self.signals[:3]:
            lines.append(f"    · {sig}")
        lines.append(
            f"  Suggestion: Add  <!-- {self.suggested_annotation} -->  "
            f"to the relevant line or section header"
        )
        excerpt = self.rule_excerpt.replace("\n", " ").strip()
        if len(excerpt) > 100:
            excerpt = excerpt[:97] + "..."
        lines.append(f"  Context: \"{excerpt}\"")
        return "\n".join(lines)


class RuleAnnotationSuggester:
    """Analyzes rule content and suggests harness-scoping annotations.

    For each rule, checks whether its content contains harness-specific
    terminology — file paths, CLI names, concepts that only apply to one
    harness.  When detected, it suggests the appropriate ``@harness:``
    annotation so that polluting other harnesses is avoided.
    """

    def analyze_rules(self, rules: list[dict]) -> list[AnnotationSuggestion]:
        """Scan rules for harness-specific content and return suggestions.

        Args:
            rules: List of rule dicts with at minimum ``path`` and ``content`` keys.

        Returns:
            List of AnnotationSuggestion instances.  Empty if no harness-specific
            content is detected.
        """
        suggestions: list[AnnotationSuggestion] = []
        for rule in rules:
            path = rule.get("path", "<unknown>")
            content = rule.get("content", "")
            if not content.strip():
                continue
            found = self._analyze_content(content, path)
            suggestions.extend(found)
        return suggestions

    def analyze_content(self, content: str, path: str = "<unknown>") -> list[AnnotationSuggestion]:
        """Analyze a single content string for harness-specific signals.

        Args:
            content: Raw rule text.
            path: Source path label for the suggestions.

        Returns:
            List of AnnotationSuggestion instances.
        """
        return self._analyze_content(content, path)

    def _analyze_content(self, content: str, path: str) -> list[AnnotationSuggestion]:
        suggestions: list[AnnotationSuggestion] = []

        for harness, signal_list in _HARNESS_SIGNALS.items():
            matched_signals: list[str] = []
            first_match_pos = len(content)
            for pattern, description in signal_list:
                m = pattern.search(content)
                if m:
                    matched_signals.append(description)
                    first_match_pos = min(first_match_pos, m.start())

            if len(matched_signals) < _MIN_SIGNAL_STRENGTH:
                continue

            # Determine confidence by signal count
            confidence = "low"
            if len(matched_signals) >= 3:
                confidence = "high"
            elif len(matched_signals) >= 2:
                confidence = "medium"

            # Extract excerpt around first match
            excerpt_start = max(0, first_match_pos - 20)
            excerpt_end = min(len(content), first_match_pos + 80)
            excerpt = content[excerpt_start:excerpt_end]

            # Determine appropriate annotation
            annotation = f"@harness:{harness}-only"

            suggestions.append(AnnotationSuggestion(
                rule_path=path,
                rule_excerpt=excerpt,
                suggested_annotation=annotation,
                harness=harness,
                signals=matched_signals,
                confidence=confidence,
            ))

        return suggestions

    def format_report(self, suggestions: list[AnnotationSuggestion]) -> str:
        """Format a list of suggestions into a human-readable report.

        Args:
            suggestions: List from analyze_rules().

        Returns:
            Formatted string, or a "no suggestions" message if list is empty.
        """
        if not suggestions:
            return (
                "Rule Annotation Analysis: no harness-specific content detected.\n"
                "All rules appear safe to sync to all active targets."
            )

        lines = [
            f"Rule Annotation Suggestions ({len(suggestions)} found)",
            "=" * 55,
            "",
            "The following rules contain harness-specific content and may",
            "benefit from @harness: annotations to prevent them from being",
            "synced to targets where they don't apply.",
            "",
        ]

        # Group by harness
        by_harness: dict[str, list[AnnotationSuggestion]] = {}
        for s in suggestions:
            by_harness.setdefault(s.harness, []).append(s)

        for harness in sorted(by_harness):
            harness_suggestions = by_harness[harness]
            lines.append(f"### {harness} ({len(harness_suggestions)} rule(s))")
            for s in harness_suggestions:
                lines.append(s.format())
                lines.append("")

        lines.append(
            "Tip: Add the suggested annotation as an HTML comment on the relevant "
            "line. See /sync-diff --annotate for an interactive annotation workflow."
        )
        return "\n".join(lines)
