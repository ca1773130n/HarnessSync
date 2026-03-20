from __future__ import annotations

"""Compliance, effectiveness, and section annotation helpers for sync filtering.

Provides inspection and transformation functions that work with sync filter
tags but are not part of the core filtering pipeline:
- Rule effectiveness annotations (<!-- effective: ... -->)
- Compliance-pinned block extraction (<!-- compliance:pinned -->)
- @effectiveness propagation annotations
- Section-level harness annotation extraction and reporting
"""

import re

from src.filter_rules import (
    _COMPLIANCE_OPEN_RE,
    _COMPLIANCE_CLOSE_RE,
    _SECTION_ANNOTATION_RE,
)


# ---------------------------------------------------------------------------
# Rule Effectiveness Annotations (#25)
# ---------------------------------------------------------------------------

# Pattern: <!-- effective: helped | confused | neutral -->
# Optionally followed by a note: <!-- effective: confused in codex -- too verbose -->
_EFFECTIVENESS_RE = re.compile(
    r"<!--\s*effective:\s*(helped|confused|neutral)(?:[^\-]+-+\s*([^>]+))?\s*-->",
    re.IGNORECASE,
)


def extract_effectiveness_annotations(content: str) -> list[dict]:
    """Extract rule effectiveness annotations from content.

    Users tag rules with <!-- effective: helped --> or
    <!-- effective: confused in codex -- rule caused bad output -->
    annotations to build a personal knowledge base of config choices.

    Args:
        content: Raw CLAUDE.md text.

    Returns:
        List of annotation dicts with keys:
            - rating: "helped" | "confused" | "neutral"
            - note: Optional note text (may be empty string)
            - line_number: 1-based line number of the annotation
    """
    annotations: list[dict] = []
    for i, line in enumerate(content.splitlines(), start=1):
        m = _EFFECTIVENESS_RE.search(line)
        if m:
            annotations.append({
                "rating": m.group(1).lower(),
                "note": (m.group(2) or "").strip(),
                "line_number": i,
            })
    return annotations


def format_effectiveness_report(annotations: list[dict]) -> str:
    """Format effectiveness annotations as a lint report section.

    Args:
        annotations: Output of extract_effectiveness_annotations().

    Returns:
        Formatted string, empty if no annotations found.
    """
    if not annotations:
        return ""

    counts: dict[str, int] = {"helped": 0, "confused": 0, "neutral": 0}
    for a in annotations:
        counts[a["rating"]] = counts.get(a["rating"], 0) + 1

    lines = [
        "Rule Effectiveness Annotations",
        "-" * 40,
        f"  helped: {counts['helped']}  confused: {counts['confused']}  neutral: {counts['neutral']}",
    ]
    confused = [a for a in annotations if a["rating"] == "confused"]
    if confused:
        lines.append("")
        lines.append("Rules flagged as 'confused' (review these):")
        for a in confused:
            note = f" — {a['note']}" if a["note"] else ""
            lines.append(f"  line {a['line_number']}: confused{note}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Compliance-Pinned Helpers (item 16)
# ---------------------------------------------------------------------------


def has_compliance_pinned(content: str) -> bool:
    """Return True if content contains any compliance:pinned blocks.

    Args:
        content: Raw CLAUDE.md text.

    Returns:
        True if at least one ``<!-- compliance:pinned -->`` tag is present.
    """
    return bool(_COMPLIANCE_OPEN_RE.search(content))


def extract_compliance_pinned(content: str) -> str:
    """Extract all compliance-pinned content from a CLAUDE.md string.

    Collects all text inside ``<!-- compliance:pinned --> ... <!-- /compliance:pinned -->``
    blocks into a single string. Used by the orchestrator to inject compliance
    content into targets that would otherwise have the rules section skipped.

    Args:
        content: Raw CLAUDE.md text.

    Returns:
        Concatenated compliance-pinned content, or empty string if none.
    """
    if not content:
        return ""

    collected: list[str] = []
    in_block = False

    for line in content.splitlines(keepends=True):
        if _COMPLIANCE_OPEN_RE.search(line):
            in_block = True
            continue
        if _COMPLIANCE_CLOSE_RE.search(line):
            in_block = False
            continue
        if in_block:
            collected.append(line)

    return "".join(collected).strip()


# -- Rule Effectiveness Annotations (item 18) ---------------------------------
#
# Authors annotate rules with effectiveness notes that propagate to all target
# configs as comments. This lets teams share institutional knowledge about
# WHY rules exist without polluting the rule text itself.
#
# Syntax in CLAUDE.md:
#
#   - Always use TypeScript <!-- @effectiveness: reduced type errors by ~40% in Go services -->
#
#   <!-- @effectiveness: this rule prevented 3 CI failures per week -->
#   - Never import lodash directly; use specific submodule imports
#
# The annotation is stripped from the active rule text when writing to targets
# that don't support HTML comments (Aider CONVENTIONS.md), and preserved as
# a regular comment for targets that do (Cursor .mdc, GEMINI.md, AGENTS.md).

_EFFECTIVENESS_PROPAGATE_RE = re.compile(
    r"<!--\s*@effectiveness:\s*(.*?)\s*-->",
    re.IGNORECASE,
)


def extract_effectiveness_propagation_annotations(content: str) -> list[dict]:
    """Extract all @effectiveness annotations from CLAUDE.md content.

    Args:
        content: Full CLAUDE.md text.

    Returns:
        List of dicts with keys:
            line_number: 1-based line number of the annotation
            annotation: Raw annotation text (stripped)
            context: The line containing the annotation (for display)
    """
    results = []
    for i, line in enumerate(content.splitlines(), start=1):
        m = _EFFECTIVENESS_PROPAGATE_RE.search(line)
        if m:
            results.append({
                "line_number": i,
                "annotation": m.group(1).strip(),
                "context": line.strip(),
            })
    return results


def propagate_effectiveness_annotations(
    content: str,
    target: str,
    strip_comments: bool = False,
) -> str:
    """Transform effectiveness annotations for a target harness.

    For targets that support HTML comments (Cursor, Gemini, Codex, OpenCode,
    Windsurf) the annotations are kept as-is.  For plain-text targets (Aider)
    the annotations are rewritten as ``> Effectiveness note: ...`` blockquotes
    so the information is still visible.  When ``strip_comments=True`` the
    annotations are removed entirely (useful for display-only modes).

    Args:
        content: CLAUDE.md text.
        target: Target harness name.
        strip_comments: If True, remove annotations completely.

    Returns:
        Transformed content string.
    """
    # Targets that render HTML comments as invisible metadata
    html_comment_targets = {"cursor", "gemini", "opencode", "codex", "windsurf", "vscode", "cline"}
    # Plain-text targets that should see annotations as readable text
    plain_text_targets = {"aider", "neovim", "zed"}

    target_lower = target.lower()

    if strip_comments:
        return _EFFECTIVENESS_PROPAGATE_RE.sub("", content)

    if target_lower in plain_text_targets:
        # Convert to blockquote-style readable notes
        def _to_blockquote(m: re.Match) -> str:
            return f"> Effectiveness note: {m.group(1).strip()}"
        return _EFFECTIVENESS_PROPAGATE_RE.sub(_to_blockquote, content)

    # All other targets: keep as HTML comments (default passthrough)
    return content


# ---------------------------------------------------------------------------
# Section-level annotation extraction and reporting
# ---------------------------------------------------------------------------


def extract_section_annotations(content: str) -> list[dict]:
    """Parse CLAUDE.md and extract per-section harness annotation metadata.

    Returns a list of sections annotated with harness targeting info.
    Useful for auditing which sections are restricted to specific harnesses.

    Supported heading-line annotation forms:
      ## Section Name <!-- harness:codex-only -->
      ## Section Name <!-- harness:only=codex,cursor -->
      ## Section Name <!-- harness:skip=gemini -->
      ## Section Name <!-- skip:gemini -->

    Args:
        content: Raw CLAUDE.md (or other Markdown) text.

    Returns:
        List of dicts with keys:
          - heading: Full heading text (e.g. "## My Section")
          - annotation_type: "only" | "skip"
          - targets: Set of harness names the annotation applies to
          - line_number: 1-based line number of the heading
    """
    results: list[dict] = []
    for m in _SECTION_ANNOTATION_RE.finditer(content):
        heading = m.group(1).strip()

        # Determine line number
        line_number = content[: m.start()].count("\n") + 1

        only_a = m.group("only_a")
        only_b = m.group("only_b")
        skip_a = m.group("skip_a")
        skip_b = m.group("skip_b")

        if only_a:
            # "codex-only" -> target is "codex"
            raw = only_a.replace("-only", "")
            targets = {t.strip() for t in raw.split(",") if t.strip()}
            ann_type = "only"
        elif only_b:
            targets = {t.strip() for t in only_b.split(",") if t.strip()}
            ann_type = "only"
        elif skip_a:
            targets = {t.strip() for t in skip_a.split(",") if t.strip()}
            ann_type = "skip"
        else:
            targets = {t.strip() for t in skip_b.split(",") if t.strip()}
            ann_type = "skip"

        results.append({
            "heading":         heading,
            "annotation_type": ann_type,
            "targets":         targets,
            "line_number":     line_number,
        })

    return results


def format_section_annotation_report(content: str, targets: list[str] | None = None) -> str:
    """Report all section-level harness annotations found in CLAUDE.md.

    Args:
        content: Raw CLAUDE.md content.
        targets: Optional list of known harness names for validation.

    Returns:
        Formatted report string listing annotated sections.
    """
    annotations = extract_section_annotations(content)
    if not annotations:
        return "No section-level harness annotations found."

    lines = [f"Found {len(annotations)} section-level harness annotation(s):\n"]
    for ann in annotations:
        heading = ann["heading"]
        ann_type = ann["annotation_type"]
        targets_str = ", ".join(sorted(ann["targets"]))
        line_num = ann["line_number"]

        if ann_type == "only":
            desc = f"only-for: {targets_str}"
        else:
            desc = f"skip-for: {targets_str}"

        lines.append(f"  Line {line_num:4d}: {heading} — {desc}")

        # Warn about unknown targets
        if targets:
            known_set = set(targets)
            unknown = ann["targets"] - known_set
            if unknown:
                lines.append(f"           ⚠ Unknown harness(es): {', '.join(sorted(unknown))}")

    return "\n".join(lines)
