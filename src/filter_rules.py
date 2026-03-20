from __future__ import annotations

"""Tag-based content filtering rule definitions and patterns.

Defines all regex patterns for sync control tags and provides
frontmatter-based @target:/@skip: directive parsing.

Tag families supported:
  Classic:     <!-- sync:exclude --> / <!-- sync:codex-only --> / <!-- sync:end -->
  Multi:       <!-- sync:codex,gemini --> / <!-- no-sync -->
  Harness:     <!-- harness:X --> / <!-- /harness:X -->
  Inline skip: <!-- harness:skip=X,Y --> / <!-- harness:only=X,Y -->
  @harness:    <!-- @harness:codex-only --> / <!-- @harness:skip-gemini -->
  Exclude:     <!-- harness:exclude:X --> / <!-- /harness:exclude:X -->
  Compliance:  <!-- compliance:pinned --> / <!-- /compliance:pinned -->
  Env:         @env:production / <!-- env:X --> / <!-- /env:X -->
  Python/shell: # @codex: skip / # @gemini: replace with <text>
"""

import re

from src.utils.constants import CORE_TARGETS

# Supported target names
KNOWN_TARGETS = CORE_TARGETS

# Classic tag pattern (backward compat)
_CLASSIC_TAG_RE = re.compile(
    r"<!--\s*sync:(exclude|codex-only|gemini-only|opencode-only|cursor-only|aider-only|windsurf-only|end)\s*-->",
    re.IGNORECASE,
)

# New multi-target tag: <!-- sync:codex,gemini --> or <!-- no-sync -->
_MULTI_TARGET_TAG_RE = re.compile(
    r"<!--\s*(?:sync:([a-z0-9,\s]+)|no-sync)\s*-->",
    re.IGNORECASE,
)

# Harness override open/close: <!-- harness:codex --> / <!-- /harness:codex -->
# NOTE: These must be checked AFTER skip/only inline tags to avoid false matches.
_HARNESS_OPEN_RE = re.compile(
    r"<!--\s*harness:([a-z0-9_-]+)\s*-->",
    re.IGNORECASE,
)
_HARNESS_CLOSE_RE = re.compile(
    r"<!--\s*/harness:([a-z0-9_-]+)\s*-->",
    re.IGNORECASE,
)

# Inline skip annotation: <!-- harness:skip=gemini,aider --> on a single line
# Skips (drops) the line for any target in the list.
_HARNESS_SKIP_RE = re.compile(
    r"<!--\s*harness:skip=([a-z0-9,\s_-]+)\s*-->",
    re.IGNORECASE,
)

# Inline only annotation: <!-- harness:only=codex,opencode --> on a single line
# Includes the line ONLY for targets in the list; drops it for all others.
_HARNESS_ONLY_RE = re.compile(
    r"<!--\s*harness:only=([a-z0-9,\s_-]+)\s*-->",
    re.IGNORECASE,
)

# @harness shorthand annotations (item 28):
#
# Two sub-forms exist:
#
#   @harness:TARGET-only            -- include this line only in TARGET
#   @harness:T1,T2                  -- include this line only in T1, T2
#   @harness:skip-TARGET            -- skip this line for TARGET
#   @harness:skip-T1,T2             -- skip this line for T1 and T2
#
# Examples:
#   <!-- @harness:codex-only -->             -> only in codex
#   <!-- @harness:cursor,aider -->           -> only in cursor and aider
#   <!-- @harness:skip-gemini -->            -> skip for gemini
#   <!-- @harness:skip-gemini,aider -->      -> skip for gemini and aider
#
# These are normalised to the same semantics as harness:only= / harness:skip=.

# skip-TARGET(,TARGET)* form
_AT_HARNESS_SKIP_RE = re.compile(
    r"<!--\s*@harness:skip-([a-z0-9,\s_-]+)\s*-->",
    re.IGNORECASE,
)

# TARGET-only  OR  T1,T2  (inclusion) form  -- NOTE: must be checked after skip
# Matches "@harness:codex-only" or "@harness:cursor,aider"
# The pattern requires no "skip-" prefix.
_AT_HARNESS_ONLY_RE = re.compile(
    r"<!--\s*@harness:((?!skip-)([a-z0-9][-a-z0-9]*(?:,\s*[a-z0-9][-a-z0-9]*)*)(?:-only)?)\s*-->",
    re.IGNORECASE,
)


def _parse_at_harness_targets(raw: str) -> set[str]:
    """Parse the target list from an @harness annotation.

    Handles "codex-only" (strip "-only" suffix), "codex,aider",
    and "codex, aider" forms.

    Args:
        raw: Captured group from _AT_HARNESS_SKIP_RE or _AT_HARNESS_ONLY_RE.

    Returns:
        Normalised set of target name strings.
    """
    cleaned = raw.lower().removesuffix("-only")
    return {t.strip().rstrip("-") for t in cleaned.split(",") if t.strip()}


# Block-level exclude tag (item 30 -- Harness-Specific Section Tagging):
#   <!-- harness:exclude:gemini -->   -- open; section dropped for gemini only
#   <!-- /harness:exclude:gemini -->  -- close
# This is a semantic alias for the <!-- harness:skip=gemini --> inline form but
# works as a block-level open/close pair for multi-line exclusions.
# Unlike harness:skip (which drops just one line), this drops everything between
# the open and close tags for the named target while keeping it for all others.
_HARNESS_EXCLUDE_OPEN_RE = re.compile(
    r"<!--\s*harness:exclude:([a-z0-9_-]+)\s*-->",
    re.IGNORECASE,
)
_HARNESS_EXCLUDE_CLOSE_RE = re.compile(
    r"<!--\s*/harness:exclude:([a-z0-9_-]+)\s*-->",
    re.IGNORECASE,
)

# Compliance-pinned block tags (item 16):
#   <!-- compliance:pinned -->   -- open block; content is ALWAYS included in all targets
#   <!-- /compliance:pinned -->  -- close block
# Content inside compliance-pinned blocks bypasses all sync filters so that
# security/legal requirements cannot be accidentally excluded.
_COMPLIANCE_OPEN_RE = re.compile(
    r"<!--\s*compliance:pinned\s*-->",
    re.IGNORECASE,
)
_COMPLIANCE_CLOSE_RE = re.compile(
    r"<!--\s*/compliance:pinned\s*-->",
    re.IGNORECASE,
)

# Environment-specific section tags (item 18):
#   @env:production  or  <!-- env:production -->  -- open block for named env
#   <!-- /env:production -->                       -- close env block
# The @env: shorthand on a standalone line is the friendlier form.
_ENV_OPEN_AT_RE = re.compile(r"^\s*@env:([a-z0-9_-]+)\s*$", re.IGNORECASE)
_ENV_OPEN_COMMENT_RE = re.compile(r"<!--\s*env:([a-z0-9_-]+)\s*-->", re.IGNORECASE)
_ENV_CLOSE_COMMENT_RE = re.compile(r"<!--\s*/env:([a-z0-9_-]+)\s*-->", re.IGNORECASE)

# Python/shell comment-style inline harness annotations (item 1 -- per-harness override layer):
#
#   <content>  # @codex: skip
#   <content>  # @gemini,aider: skip
#   <content>  # @gemini: replace with <replacement text>
#   <content>  # @codex,cursor: replace with <replacement text>
#
# The annotation must appear at the END of the line (after the content).
# For non-matching targets the annotation is stripped and the original content
# is emitted.  Both patterns are anchored to end-of-line so they don't
# accidentally match inside content.
_PY_HARNESS_SKIP_RE = re.compile(
    r"\s+#\s*@([a-z0-9][a-z0-9,\s_-]*):\s*skip\s*$",
    re.IGNORECASE,
)
_PY_HARNESS_REPLACE_RE = re.compile(
    r"\s+#\s*@([a-z0-9][a-z0-9,\s_-]*):\s*replace\s+with\s+(.*?)\s*$",
    re.IGNORECASE,
)


def _parse_target_list(targets_str: str) -> set[str]:
    """Parse a comma-separated target list string into a normalised set."""
    return {t.strip().lower() for t in targets_str.split(",") if t.strip()}


# --------------------------------------------------------------------------- #
# Frontmatter-based @target: / @skip: directive support (item 3)              #
# --------------------------------------------------------------------------- #
# Users can place directive lines at the top of a CLAUDE.md rule block:
#
#   @target:codex,gemini   -- include this block ONLY in codex and gemini
#   @skip:cursor,aider     -- exclude this block from cursor and aider
#
# These are standalone lines (not HTML comments) making them easy to type.
# They apply to the entire content block (not just a single line).
# Multiple directives are AND-combined: content must satisfy all of them.

_FRONTMATTER_TARGET_RE = re.compile(
    r"^[ \t]*@target:([a-z0-9, _-]+)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)
_FRONTMATTER_SKIP_RE = re.compile(
    r"^[ \t]*@skip:([a-z0-9, _-]+)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_frontmatter_tags(content: str) -> dict:
    """Extract @target: and @skip: directives from content.

    Scans every line of ``content`` for standalone ``@target:`` and ``@skip:``
    directive annotations. Returns a summary dict describing the targeting rules
    found and the cleaned content with the directive lines removed.

    Args:
        content: Raw CLAUDE.md text, possibly containing @target:/@skip: lines.

    Returns:
        Dict with keys:
          - target_targets: set[str] -- if non-empty, content targets only these
          - skip_targets:   set[str] -- content must be excluded from these
          - cleaned:        str      -- content with directive lines stripped out
    """
    target_targets: set[str] = set()
    skip_targets: set[str] = set()

    for m in _FRONTMATTER_TARGET_RE.finditer(content):
        target_targets.update(_parse_target_list(m.group(1)))

    for m in _FRONTMATTER_SKIP_RE.finditer(content):
        skip_targets.update(_parse_target_list(m.group(1)))

    # Strip directive lines from the content
    cleaned = _FRONTMATTER_TARGET_RE.sub("", content)
    cleaned = _FRONTMATTER_SKIP_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return {
        "target_targets": target_targets,
        "skip_targets": skip_targets,
        "cleaned": cleaned,
    }


def is_content_allowed_for_target(content: str, target_name: str) -> bool:
    """Return True if the content block is allowed to reach ``target_name``.

    Checks @target: and @skip: frontmatter directives embedded in ``content``.
    If neither directive is present, returns True (default passthrough).

    Args:
        content: Raw content that may contain @target:/@skip: directives.
        target_name: Target harness identifier (e.g. "codex", "gemini").

    Returns:
        True if the content should be included for this target, False otherwise.
    """
    target_lower = target_name.lower()
    tags = parse_frontmatter_tags(content)

    # @skip: takes precedence
    if target_lower in tags["skip_targets"]:
        return False

    # @target: restricts inclusion to a specific set
    if tags["target_targets"] and target_lower not in tags["target_targets"]:
        return False

    return True


def filter_content_with_frontmatter(content: str, target_name: str) -> str:
    """Apply @target:/@skip: frontmatter directives and strip them from output.

    If frontmatter directives indicate the content should be excluded from
    ``target_name``, returns an empty string.  Otherwise returns the content
    with the directive lines stripped (so they don't pollute the target file).

    This should be called BEFORE ``filter_rules_for_target`` so that the
    cleaned content flows into the per-line filter pipeline.

    Args:
        content: Raw CLAUDE.md rule block text.
        target_name: Target harness identifier.

    Returns:
        Cleaned content (directive lines removed) if allowed, or "" if excluded.
    """
    tags = parse_frontmatter_tags(content)
    target_lower = target_name.lower()

    if target_lower in tags["skip_targets"]:
        return ""
    if tags["target_targets"] and target_lower not in tags["target_targets"]:
        return ""

    return tags["cleaned"] if (tags["target_targets"] or tags["skip_targets"]) else content


# Section-level harness annotation parser (item 2 -- per-harness config overrides)
#
# Matches a Markdown heading line (H1-H4) that is IMMEDIATELY followed on the
# same line by a harness annotation comment:
#   ## My Section <!-- harness:codex-only -->
#   ### Rules <!-- skip:gemini -->
#   # Context <!-- harness:only=codex,cursor -->
_SECTION_ANNOTATION_RE = re.compile(
    r"^(#{1,4}\s+.+?)\s+"
    r"<!--\s*"
    r"(?:"
    r"harness:(?P<only_a>[a-z0-9,_-]+-only)"       # harness:codex-only
    r"|harness:only=(?P<only_b>[a-z0-9,_-]+)"       # harness:only=codex,cursor
    r"|harness:skip=(?P<skip_a>[a-z0-9,_-]+)"       # harness:skip=gemini
    r"|skip:(?P<skip_b>[a-z0-9,_-]+)"               # skip:gemini
    r")"
    r"\s*-->",
    re.IGNORECASE | re.MULTILINE,
)
