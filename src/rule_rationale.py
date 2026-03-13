from __future__ import annotations

"""Rule Rationale Annotations for HarnessSync.

Attaches a 'why' comment to each rule/skill in CLAUDE.md that is preserved
through sync and appears in target harness configs in the appropriate format.

Annotation syntax in CLAUDE.md (immediately after the heading)::

    ## Conventional Commits
    <!-- why: Our CI/CD pipeline parses commit messages for changelogs -->

    Always use conventional commits: feat:, fix:, chore:, docs: prefixes.

The ``<!-- why: ... -->`` annotation survives a round-trip through every
supported adapter format:

* **Markdown** targets (AGENTS.md, GEMINI.md, CONVENTIONS.md, .mdc):
  The annotation is preserved verbatim as an HTML comment.
* **TOML** targets (Codex ``config.toml``):
  Translated to ``# Why: ...`` line comments above the relevant entry.
* **YAML** targets (Aider ``.aider.conf.yml``):
  Translated to ``# why: ...`` line comments.
* **Strip** mode:
  All ``<!-- why: ... -->`` annotations are removed from the output, useful
  for harnesses that cannot render or ignore HTML comments.
"""

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Matches a Markdown ATX heading of any level (# through ######).
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Matches a <!-- why: ... --> annotation (single or multi-line).
# Captures everything between "why:" and the closing "-->".
_WHY_ANNOTATION_RE = re.compile(
    r"<!--\s*why:\s*(.*?)\s*-->",
    re.DOTALL | re.IGNORECASE,
)

# Matches a standalone <!-- why: ... --> annotation line (used for stripping).
_WHY_ANNOTATION_LINE_RE = re.compile(
    r"[ \t]*<!--\s*why:[^>]*-->\s*\n?",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RuleWithRationale:
    """A rule extracted from CLAUDE.md, with its optional rationale annotation.

    Attributes:
        title:       The heading text of the rule section (e.g. ``"Conventional Commits"``).
        content:     The body text of the rule, excluding the heading and annotation comment.
        rationale:   The text from the ``<!-- why: ... -->`` annotation, or ``None`` if absent.
        line_number: 1-based line number of the heading within the source document.
    """

    title: str
    content: str
    rationale: str | None
    line_number: int


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

def extract_rationale_annotations(claude_md_text: str) -> list[RuleWithRationale]:
    """Parse CLAUDE.md and extract rules together with their rationale annotations.

    Each Markdown ATX heading (``# Title``, ``## Title``, etc.) starts a new
    rule section.  A ``<!-- why: ... -->`` comment appearing anywhere within
    the rule body (typically immediately after the heading) is captured as the
    rationale.

    The annotation comment is stripped from the ``content`` field — the returned
    content contains only the substantive rule text.

    Args:
        claude_md_text: Full text of a CLAUDE.md file.

    Returns:
        List of :class:`RuleWithRationale` objects in document order.
        An empty list is returned when no headings are found.
    """
    if not claude_md_text:
        return []

    lines = claude_md_text.splitlines(keepends=True)
    # Build a line-number index for each heading match so we can report 1-based
    # line numbers accurately even though re searches on the raw string.
    heading_matches = list(_HEADING_RE.finditer(claude_md_text))

    if not heading_matches:
        return []

    # Compute 1-based line number for a character offset in the source text.
    def _line_number_for_offset(offset: int) -> int:
        return claude_md_text.count("\n", 0, offset) + 1

    rules: list[RuleWithRationale] = []

    for i, match in enumerate(heading_matches):
        title = match.group(2).strip()
        heading_start = match.start()
        heading_lineno = _line_number_for_offset(heading_start)

        # Body runs from the character after this heading to the start of the next.
        body_start = match.end()
        body_end = heading_matches[i + 1].start() if i + 1 < len(heading_matches) else len(claude_md_text)
        body_raw = claude_md_text[body_start:body_end]

        # Extract the first <!-- why: ... --> annotation found in the body.
        rationale: str | None = None
        why_match = _WHY_ANNOTATION_RE.search(body_raw)
        if why_match:
            raw_why = why_match.group(1)
            # Collapse internal whitespace / newlines to a single space.
            rationale = " ".join(raw_why.split())

        # Strip annotation comments from the body content.
        content = _WHY_ANNOTATION_LINE_RE.sub("", body_raw)
        # Tidy leading/trailing blank lines.
        content = content.strip()

        rules.append(
            RuleWithRationale(
                title=title,
                content=content,
                rationale=rationale,
                line_number=heading_lineno,
            )
        )

    return rules


# ---------------------------------------------------------------------------
# Injection helpers (per target format)
# ---------------------------------------------------------------------------

def inject_rationale_for_markdown(content: str, rationale: str, title: str) -> str:
    """Inject a ``<!-- why: ... -->`` annotation into Markdown content.

    The annotation is inserted immediately after the first heading that matches
    *title*.  If no matching heading is found the annotation is prepended to
    the content.  If a ``<!-- why: ... -->`` annotation already exists it is
    replaced.

    Args:
        content:   The Markdown text to annotate.
        rationale: The rationale text (without the HTML comment wrapper).
        title:     The exact heading text to annotate.

    Returns:
        Modified Markdown string with the annotation injected.
    """
    if not rationale:
        return content

    annotation = f"<!-- why: {rationale} -->"

    # Remove any pre-existing why annotation to avoid duplication.
    content = _WHY_ANNOTATION_LINE_RE.sub("", content)

    # Find the heading matching 'title'.
    heading_pattern = re.compile(
        r"^(#{1,6}\s+" + re.escape(title) + r"\s*)$",
        re.MULTILINE,
    )
    m = heading_pattern.search(content)
    if m:
        insert_pos = m.end()
        # Ensure there is a newline between the heading and the annotation.
        if insert_pos < len(content) and content[insert_pos] != "\n":
            annotation_block = f"\n{annotation}\n"
        else:
            annotation_block = f"\n{annotation}"
        return content[:insert_pos] + annotation_block + content[insert_pos:]

    # Fallback: prepend annotation.
    return annotation + "\n\n" + content


def inject_rationale_for_toml(content: str, rationale: str) -> str:
    """Inject a ``# Why: ...`` comment into TOML content.

    The comment is inserted at the top of the TOML text (before any existing
    content) so it acts as a file-level annotation.  If a ``# Why:`` comment
    already exists on the first non-blank line it is replaced.

    Args:
        content:   The TOML text to annotate.
        rationale: The rationale text (without the comment prefix).

    Returns:
        Modified TOML string with the comment injected.
    """
    if not rationale:
        return content

    comment_line = f"# Why: {rationale}"

    lines = content.splitlines(keepends=True)

    # Remove any pre-existing "# Why:" comment lines.
    filtered: list[str] = [
        line for line in lines
        if not re.match(r"^\s*#\s*Why:", line, re.IGNORECASE)
    ]

    return comment_line + "\n" + "".join(filtered)


def inject_rationale_for_yaml(content: str, rationale: str) -> str:
    """Inject a ``# why: ...`` comment into YAML content.

    Mirrors :func:`inject_rationale_for_toml` but uses lowercase ``why:``
    to follow YAML convention.

    Args:
        content:   The YAML text to annotate.
        rationale: The rationale text (without the comment prefix).

    Returns:
        Modified YAML string with the comment injected.
    """
    if not rationale:
        return content

    comment_line = f"# why: {rationale}"

    lines = content.splitlines(keepends=True)

    # Remove any pre-existing "# why:" comment lines.
    filtered: list[str] = [
        line for line in lines
        if not re.match(r"^\s*#\s*why:", line, re.IGNORECASE)
    ]

    return comment_line + "\n" + "".join(filtered)


def strip_rationale_annotations(content: str) -> str:
    """Remove all ``<!-- why: ... -->`` annotations from *content*.

    Used for harnesses that do not support HTML comments and where the
    annotation text would appear as literal characters in the rendered output.

    Args:
        content: Source text potentially containing ``<!-- why: ... -->`` blocks.

    Returns:
        Content with all rationale annotations removed.  Surrounding whitespace
        is preserved; only the annotation lines themselves are deleted.
    """
    return _WHY_ANNOTATION_LINE_RE.sub("", content)


# ---------------------------------------------------------------------------
# RationalePreserver — pipeline integration
# ---------------------------------------------------------------------------

class RationalePreserver:
    """Preserves rationale annotations through the HarnessSync pipeline.

    Extracts ``<!-- why: ... -->`` annotations from rules text and re-injects
    them in the appropriate format for the target harness.

    Usage::

        preserver = RationalePreserver()

        # Transform rules text bound for a Markdown target (AGENTS.md, etc.)
        output = preserver.apply_to_rules_text(rules_text, target_format="markdown")

        # Transform rules text bound for Codex config.toml
        output = preserver.apply_to_rules_text(rules_text, target_format="toml")

        # Remove annotations for harnesses that cannot render HTML comments
        output = preserver.apply_to_rules_text(rules_text, target_format="strip")
    """

    # Format values accepted by apply_to_rules_text.
    SUPPORTED_FORMATS = frozenset({"markdown", "toml", "yaml", "strip"})

    def __init__(self) -> None:
        """Initialise with no persistent state."""

    def apply_to_rules_text(self, rules_text: str, target_format: str) -> str:
        """Transform *rules_text* so that rationale annotations appear in *target_format*.

        For ``"markdown"`` format the annotations are preserved as-is (the
        ``<!-- why: ... -->`` HTML comments pass through unchanged).  For
        ``"toml"`` and ``"yaml"`` formats the annotations are removed from the
        Markdown and the resulting text is prefixed with a format-appropriate
        comment.  For ``"strip"`` format all annotations are removed.

        Because TOML and YAML targets typically receive the *entire* rules text
        as a single block (rather than individual rule entries), this method
        inserts a single top-level rationale comment aggregating all rationales
        found in the rules text when there is more than one.  When exactly one
        rationale is found it is used directly.

        Args:
            rules_text:   The raw rules text (may contain ``<!-- why: ... -->``
                          annotations).
            target_format: One of ``"markdown"``, ``"toml"``, ``"yaml"``, or
                           ``"strip"``.

        Returns:
            Transformed rules text.

        Raises:
            ValueError: If *target_format* is not a recognised format string.
        """
        if target_format not in self.SUPPORTED_FORMATS:
            raise ValueError(
                f"Unsupported target_format '{target_format}'. "
                f"Choose from: {sorted(self.SUPPORTED_FORMATS)}"
            )

        if target_format == "markdown":
            # Markdown targets can render HTML comments — pass through unchanged.
            return rules_text

        if target_format == "strip":
            return strip_rationale_annotations(rules_text)

        # For TOML and YAML: collect all rationales and inject as file header.
        rules = extract_rationale_annotations(rules_text)
        rationales = [r.rationale for r in rules if r.rationale]

        # Strip the HTML-comment annotations from the output text first.
        clean_text = strip_rationale_annotations(rules_text)

        if not rationales:
            return clean_text

        if len(rationales) == 1:
            combined_rationale = rationales[0]
        else:
            # Join multiple rationales with a semicolon separator.
            combined_rationale = "; ".join(rationales)

        if target_format == "toml":
            return inject_rationale_for_toml(clean_text, combined_rationale)

        # target_format == "yaml"
        return inject_rationale_for_yaml(clean_text, combined_rationale)

    def get_rationale_map(self, rules_text: str) -> dict[str, str]:
        """Return a mapping of rule title -> rationale text.

        Useful for callers that need to inject rationales rule-by-rule rather
        than operating on the whole text block at once.

        Args:
            rules_text: Raw rules text (may contain ``<!-- why: ... -->`` blocks).

        Returns:
            Dict mapping rule title (str) -> rationale text (str).
            Rules without a ``<!-- why: ... -->`` annotation are excluded.
        """
        return {
            rule.title: rule.rationale
            for rule in extract_rationale_annotations(rules_text)
            if rule.rationale is not None
        }
