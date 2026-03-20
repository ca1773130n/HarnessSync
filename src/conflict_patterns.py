from __future__ import annotations

"""
Semantic rule conflict detection patterns and detector.

Contains regex-based contradiction patterns for detecting conflicting
instructions within CLAUDE.md (or similar rules files), plus the
SemanticConflictDetector class that scans for contradictions.
"""

import re
from dataclasses import dataclass
from pathlib import Path


# ---------------------------------------------------------------------------
# Semantic Rule Conflict Detection (item 25)
# ---------------------------------------------------------------------------

@dataclass
class SemanticConflict:
    """A pair of rules that appear to contradict each other."""

    rule_a: str          # Excerpt of first rule (<=120 chars)
    line_a: int          # Line number in source file
    rule_b: str          # Excerpt of contradicting rule
    line_b: int          # Line number in source file
    conflict_type: str   # Short category label
    explanation: str     # Human-readable explanation


# Contradiction pattern pairs: (pattern_a, pattern_b, conflict_type, explanation)
# Each pattern is a compiled regex that triggers when matched in DIFFERENT lines.
_CONTRADICTION_PATTERNS: list[tuple[re.Pattern, re.Pattern, str, str]] = [
    (
        re.compile(r"\b(always|never skip|always add|add)\b.{0,40}\bcomment", re.I),
        re.compile(r"\b(avoid|don.t add|no|minimal|sparse|concise)\b.{0,40}\bcomment", re.I),
        "comment_policy",
        "One rule requires comments; another discourages them.",
    ),
    (
        re.compile(r"\buse\b.{0,30}\bTypeScript\b", re.I),
        re.compile(r"\buse\b.{0,30}\bJavaScript\b(?! with TypeScript)", re.I),
        "language_choice",
        "Conflicting language directives: TypeScript vs JavaScript.",
    ),
    (
        re.compile(r"\b(always|prefer|use)\b.{0,30}\bsingle.quot", re.I),
        re.compile(r"\b(always|prefer|use)\b.{0,30}\bdouble.quot", re.I),
        "quote_style",
        "Conflicting quote-style directives.",
    ),
    (
        re.compile(r"\b(always|write|add|include)\b.{0,30}\b(test|tests|unit test)\b", re.I),
        re.compile(r"\b(skip|no|don.t write|avoid)\b.{0,30}\b(test|tests|unit test)\b", re.I),
        "test_policy",
        "Conflicting testing directives: one requires tests, another discourages them.",
    ),
    (
        re.compile(r"\b(never|don.t|avoid)\b.{0,30}\b(console\.log|print|debug)\b", re.I),
        re.compile(r"\b(always|add|use)\b.{0,30}\b(console\.log|print|debug log)\b", re.I),
        "logging_policy",
        "Conflicting log/debug directives.",
    ),
    (
        re.compile(r"\buse\b.{0,30}\b(tabs|tab indent)\b", re.I),
        re.compile(r"\buse\b.{0,30}\b(spaces|space indent)\b", re.I),
        "indentation",
        "Conflicting indentation directives: tabs vs spaces.",
    ),
    (
        re.compile(r"\b(always|prefer)\b.{0,30}\bfunctional\b", re.I),
        re.compile(r"\b(always|prefer)\b.{0,30}\bclass.based\b", re.I),
        "oop_vs_functional",
        "Conflicting paradigm preference: functional vs class-based.",
    ),
    (
        re.compile(r"\b(never|avoid|don.t use)\b.{0,20}\bvar\b", re.I),
        re.compile(r"\buse\b.{0,20}\bvar\b", re.I),
        "var_usage",
        "Conflicting 'var' usage directives.",
    ),
    (
        re.compile(r"\b(verbose|detailed|comprehensive)\b.{0,30}\bresponse", re.I),
        re.compile(r"\b(concise|brief|short|terse)\b.{0,30}\bresponse", re.I),
        "response_style",
        "Conflicting response verbosity: one asks for verbose answers, another for concise.",
    ),
    (
        re.compile(r"\b(never|don.t|avoid)\b.{0,30}\bemoji", re.I),
        re.compile(r"\b(use|add|include)\b.{0,30}\bemoji", re.I),
        "emoji_policy",
        "Conflicting emoji usage directives.",
    ),
]


def _extract_rule_lines(content: str) -> list[tuple[int, str]]:
    """Extract non-empty, non-heading, non-comment lines with their line numbers."""
    lines = []
    for i, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("<!--"):
            continue
        lines.append((i, stripped))
    return lines


class SemanticConflictDetector:
    """Detect contradictory instructions within a CLAUDE.md (or similar rules file).

    Unlike ConflictDetector (which detects hash-based sync conflicts between
    target files), this class scans a SINGLE source file for internally
    contradictory rules -- e.g. "always add comments" in one section and
    "avoid verbose comments" in another.

    Usage::

        detector = SemanticConflictDetector()
        conflicts = detector.scan(content)
        print(detector.format_report(conflicts))
    """

    def scan(self, content: str) -> list[SemanticConflict]:
        """Scan rules content for semantic contradictions.

        Args:
            content: Full text of a rules/config file (e.g. CLAUDE.md).

        Returns:
            List of SemanticConflict entries, deduplicated by conflict_type.
        """
        rule_lines = _extract_rule_lines(content)
        found: list[SemanticConflict] = []
        seen_types: set[str] = set()

        for pat_a, pat_b, ctype, explanation in _CONTRADICTION_PATTERNS:
            if ctype in seen_types:
                continue

            matches_a: list[tuple[int, str]] = [
                (ln, text) for ln, text in rule_lines if pat_a.search(text)
            ]
            matches_b: list[tuple[int, str]] = [
                (ln, text) for ln, text in rule_lines if pat_b.search(text)
            ]

            if matches_a and matches_b:
                # Report the first pair found -- skip if both patterns hit the same line
                ln_a, text_a = matches_a[0]
                ln_b, text_b = matches_b[0]
                if ln_a == ln_b:
                    # Try to find a different line for the second pattern
                    alt = [(ln, t) for ln, t in matches_b if ln != ln_a]
                    if not alt:
                        continue
                    ln_b, text_b = alt[0]
                found.append(SemanticConflict(
                    rule_a=text_a[:120],
                    line_a=ln_a,
                    rule_b=text_b[:120],
                    line_b=ln_b,
                    conflict_type=ctype,
                    explanation=explanation,
                ))
                seen_types.add(ctype)

        return found

    def scan_file(self, path: Path) -> list[SemanticConflict]:
        """Scan a rules file for semantic contradictions.

        Args:
            path: Path to rules file (CLAUDE.md, AGENTS.md, etc.)

        Returns:
            List of SemanticConflict entries.
        """
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return []
        return self.scan(content)

    def check_temporal_drift(
        self,
        current_content: str,
        snapshot_content: str,
    ) -> list[SemanticConflict]:
        """Detect semantic drift between current rules and a previously-synced snapshot.

        Identifies rules added to ``current_content`` since the snapshot was
        taken that now logically contradict rules present in the snapshot.
        This catches the "rule #47 contradicts rule #12" problem where rules
        accumulate over time without the user noticing the contradiction.

        Algorithm:
          1. Extract lines present in current but NOT in snapshot (new rules).
          2. For each new rule line, check if it contradicts any snapshot rule
             using the same ``_CONTRADICTION_PATTERNS`` as ``scan()``.
          3. Return conflicts where one side is new (post-snapshot) and the
             other is from the snapshot.

        Args:
            current_content: Current CLAUDE.md content.
            snapshot_content: Previously-synced content (baseline).

        Returns:
            List of SemanticConflict where rule_a is from the snapshot and
            rule_b is the newly-added contradicting rule.
        """
        snapshot_lines = set(l.strip() for l in snapshot_content.splitlines() if l.strip())
        current_rule_lines = _extract_rule_lines(current_content)
        snapshot_rule_lines = _extract_rule_lines(snapshot_content)

        # New rules are lines in current but not in snapshot (by content)
        new_rules = [(ln, text) for ln, text in current_rule_lines
                     if text not in snapshot_lines]

        if not new_rules:
            return []

        conflicts: list[SemanticConflict] = []
        seen_types: set[str] = set()

        for pat_a, pat_b, ctype, explanation in _CONTRADICTION_PATTERNS:
            if ctype in seen_types:
                continue

            # Find snapshot lines matching pattern A
            snap_matches_a = [(ln, t) for ln, t in snapshot_rule_lines if pat_a.search(t)]
            snap_matches_b = [(ln, t) for ln, t in snapshot_rule_lines if pat_b.search(t)]

            # Check if any NEW rule contradicts existing snapshot rules
            new_matches_b = [(ln, t) for ln, t in new_rules if pat_b.search(t)]
            new_matches_a = [(ln, t) for ln, t in new_rules if pat_a.search(t)]

            if snap_matches_a and new_matches_b:
                ln_a, text_a = snap_matches_a[0]
                ln_b, text_b = new_matches_b[0]
                if ln_a != ln_b:
                    conflicts.append(SemanticConflict(
                        rule_a=text_a[:120],
                        line_a=ln_a,
                        rule_b=text_b[:120],
                        line_b=ln_b,
                        conflict_type=f"drift:{ctype}",
                        explanation=f"[TEMPORAL DRIFT] {explanation} "
                                    f"The existing rule (line {ln_a}) was synced weeks ago; "
                                    f"the contradicting rule (line {ln_b}) was added recently.",
                    ))
                    seen_types.add(ctype)

            elif snap_matches_b and new_matches_a:
                ln_a, text_a = new_matches_a[0]
                ln_b, text_b = snap_matches_b[0]
                if ln_a != ln_b:
                    conflicts.append(SemanticConflict(
                        rule_a=text_a[:120],
                        line_a=ln_a,
                        rule_b=text_b[:120],
                        line_b=ln_b,
                        conflict_type=f"drift:{ctype}",
                        explanation=f"[TEMPORAL DRIFT] {explanation} "
                                    f"The new rule (line {ln_a}) contradicts an older "
                                    f"rule (line {ln_b}) that was already synced.",
                    ))
                    seen_types.add(ctype)

        return conflicts

    def format_report(self, conflicts: list[SemanticConflict]) -> str:
        """Format detected conflicts for terminal output.

        Args:
            conflicts: Output of scan() or scan_file().

        Returns:
            Human-readable conflict report.
        """
        if not conflicts:
            return "No semantic rule conflicts detected."

        lines = [
            f"Semantic Rule Conflicts: {len(conflicts)} found",
            "=" * 50,
            "",
        ]
        for c in conflicts:
            lines.append(f"  [{c.conflict_type}] {c.explanation}")
            lines.append(f"    Line {c.line_a}: {c.rule_a!r}")
            lines.append(f"    Line {c.line_b}: {c.rule_b!r}")
            lines.append("")
        lines.append(
            "Fix: review conflicting rules above and consolidate into a single directive."
        )
        return "\n".join(lines)
