from __future__ import annotations

"""Harness-specific inline rule annotation filter (Item 2).

Parses lightweight inline HTML comments that control per-harness rule
inclusion directly in CLAUDE.md rule text.

Supported annotation formats (HTML comments on the same line as a rule
or on its own line):

    <!-- cursor-only -->
        Include this rule only when syncing to Cursor.

    <!-- skip:aider -->
        Skip this rule when syncing to Aider.

    <!-- only:codex,gemini -->
        Include only in Codex and Gemini.

    <!-- skip:all --> or <!-- skip -->
        Skip this rule for every harness (suppress globally).

Multiple annotations on the same line are supported; first "exclude" wins.

Integration::

    from src.annotation_filter import AnnotationFilter

    # Filter a list of rule dicts (from SourceReader)
    filtered = AnnotationFilter.filter_rules_for_target(rules, "cursor")

    # Filter raw Markdown content string
    filtered_md = AnnotationFilter.filter_content_for_target(content, "cursor")

The annotations are stripped from the output so they do not appear in
the written target config files.
"""

import re
from dataclasses import dataclass, field

# Pre-compiled regex for collapsing whitespace left by annotation removal
_WHITESPACE_COLLAPSE_RE = re.compile(r"[ \t]{2,}")

# ---------------------------------------------------------------------------
# Regex: matches annotation comments in various forms
#   <!-- cursor-only -->
#   <!-- skip:aider -->
#   <!-- skip:aider,gemini -->
#   <!-- only:codex,gemini -->
#   <!-- skip --> / <!-- skip:all -->
# ---------------------------------------------------------------------------
_ANN_RE = re.compile(
    r"<!--\s*"
    r"(?:"
    r"(?P<only_single>(?P<only_harness>[a-zA-Z0-9_-]+)-only)"       # cursor-only
    r"|(?P<skip_specific>skip:(?P<skip_list>[a-zA-Z0-9_,\s-]+))"    # skip:aider[,gemini]
    r"|(?P<only_specific>only:(?P<only_list>[a-zA-Z0-9_,\s-]+))"    # only:codex[,gemini]
    r"|(?P<skip_all>skip(?::all)?)"                                   # skip / skip:all
    r")"
    r"\s*-->",
    re.IGNORECASE,
)


@dataclass
class AnnotationDirective:
    """A single parsed annotation directive."""

    mode: str              # "only" | "skip" | "skip_all"
    harnesses: list[str] = field(default_factory=list)  # empty = applies to all

    def should_include(self, target: str) -> bool:
        """Return True if the rule carrying this directive should sync to `target`."""
        t = target.lower().strip()
        if self.mode == "skip_all":
            return False
        if self.mode == "only":
            return t in [h.lower() for h in self.harnesses]
        if self.mode == "skip":
            return t not in [h.lower() for h in self.harnesses]
        return True


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_annotations(text: str) -> list[AnnotationDirective]:
    """Extract all annotation directives from a text string."""
    directives: list[AnnotationDirective] = []
    for m in _ANN_RE.finditer(text):
        if m.group("skip_all"):
            directives.append(AnnotationDirective(mode="skip_all"))
        elif m.group("only_single"):
            harness = m.group("only_harness").lower()
            directives.append(AnnotationDirective(mode="only", harnesses=[harness]))
        elif m.group("skip_specific"):
            raw = m.group("skip_list") or ""
            harnesses = [h.strip().lower() for h in raw.split(",") if h.strip()]
            directives.append(AnnotationDirective(mode="skip", harnesses=harnesses))
        elif m.group("only_specific"):
            raw = m.group("only_list") or ""
            harnesses = [h.strip().lower() for h in raw.split(",") if h.strip()]
            directives.append(AnnotationDirective(mode="only", harnesses=harnesses))
    return directives


def _should_include(rule_text: str, target: str) -> bool:
    """Return True if a rule should be included for `target`."""
    directives = _parse_annotations(rule_text)
    if not directives:
        return True
    # First directive that says "exclude" wins.
    for d in directives:
        if not d.should_include(target):
            return False
    return True


def _strip_annotations(text: str) -> str:
    """Remove annotation comments from text."""
    cleaned = _ANN_RE.sub("", text).strip()
    # Collapse multiple spaces left by removal (but keep newlines)
    cleaned = _WHITESPACE_COLLAPSE_RE.sub(" ", cleaned)
    return cleaned


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class AnnotationFilter:
    """Filter rule content based on inline harness annotations.

    This class provides static methods only; no state is held.

    Usage::

        from src.annotation_filter import AnnotationFilter

        # Filter list-of-dicts rules (SourceReader format)
        filtered = AnnotationFilter.filter_rules_for_target(rules, "cursor")

        # Filter a raw Markdown string
        filtered_md = AnnotationFilter.filter_content_for_target(content, "cursor")

        # Check whether annotations are present at all (for performance)
        if AnnotationFilter.has_annotations(content):
            ...
    """

    @staticmethod
    def filter_rules_for_target(
        rules: list[dict] | str,
        target: str,
    ) -> list[dict] | str:
        """Filter rules for a specific harness, stripping annotation comments.

        Accepts both list-of-dicts (structured SourceReader output) and raw
        string formats.  Returns the same type as the input.

        Args:
            rules: Either a list of rule dicts with a ``'content'`` key, or a
                   raw Markdown string.
            target: Target harness name (e.g. ``"cursor"``, ``"aider"``).

        Returns:
            Filtered rules in the same format as the input, with annotation
            comments stripped from the content of included rules.
        """
        if isinstance(rules, str):
            return AnnotationFilter.filter_content_for_target(rules, target)

        filtered: list[dict] = []
        for rule in rules:
            if isinstance(rule, dict):
                content = rule.get("content", "")
                if _should_include(content, target):
                    filtered.append({**rule, "content": _strip_annotations(content)})
            else:
                text = str(rule)
                if _should_include(text, target):
                    filtered.append(_strip_annotations(text))  # type: ignore[arg-type]
        return filtered

    @staticmethod
    def filter_content_for_target(content: str, target: str) -> str:
        """Filter raw Markdown content, removing lines annotated for exclusion.

        Lines that carry an annotation excluding ``target`` are dropped.
        Annotation comments are stripped from included lines.

        Args:
            content: Raw Markdown string (e.g. a CLAUDE.md rules section).
            target: Target harness name.

        Returns:
            Filtered Markdown with excluded lines removed and annotation
            comments stripped from included lines.
        """
        output: list[str] = []
        for line in content.splitlines(keepends=True):
            if _should_include(line, target):
                stripped = _strip_annotations(line.rstrip())
                output.append(stripped + "\n" if line.endswith("\n") else stripped)
        return "".join(output)

    @staticmethod
    def has_annotations(content: str) -> bool:
        """Return True if ``content`` contains any harness annotation comments."""
        return bool(_ANN_RE.search(content))

    @staticmethod
    def extract_annotation_summary(content: str) -> dict[str, list[str]]:
        """Return a summary mapping harness → annotation types found.

        Useful for pre-sync reporting: which harnesses have targeted rules?

        Args:
            content: Raw Markdown string to scan.

        Returns:
            Dict ``{harness_name: [annotation_type, ...]}``.
            ``"all"`` is used as key for ``skip:all`` directives.

        Example::

            {"cursor": ["only"], "aider": ["skip"], "all": ["skip_all"]}
        """
        summary: dict[str, list[str]] = {}
        for m in _ANN_RE.finditer(content):
            if m.group("skip_all"):
                summary.setdefault("all", []).append("skip_all")
            elif m.group("only_single"):
                h = m.group("only_harness").lower()
                summary.setdefault(h, []).append("only")
            elif m.group("skip_specific"):
                raw = m.group("skip_list") or ""
                for h in raw.split(","):
                    h = h.strip().lower()
                    if h:
                        summary.setdefault(h, []).append("skip")
            elif m.group("only_specific"):
                raw = m.group("only_list") or ""
                for h in raw.split(","):
                    h = h.strip().lower()
                    if h:
                        summary.setdefault(h, []).append("only")
        return summary

    @staticmethod
    def list_annotations(content: str) -> list[dict]:
        """Return a list of all annotation occurrences with their positions.

        Args:
            content: Raw Markdown string to scan.

        Returns:
            List of dicts: ``{start, end, mode, harnesses, raw}``.
        """
        results = []
        for m in _ANN_RE.finditer(content):
            directives = _parse_annotations(m.group(0))
            for d in directives:
                results.append({
                    "start": m.start(),
                    "end": m.end(),
                    "mode": d.mode,
                    "harnesses": d.harnesses,
                    "raw": m.group(0),
                })
        return results
