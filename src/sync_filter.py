from __future__ import annotations

"""Tag-based content filtering for selective sync.

Allows users to annotate CLAUDE.md sections with sync control tags:

  Classic tags (backward compatible):
    <!-- sync:exclude -->          — exclude from all targets
    <!-- sync:codex-only -->       — include only in codex
    <!-- sync:gemini-only -->      — include only in gemini
    <!-- sync:opencode-only -->    — include only in opencode
    <!-- sync:end -->              — end a tagged region

  New multi-target inclusion (item 13):
    <!-- no-sync -->               — exclude from all targets (alias for sync:exclude)
    <!-- sync:codex,gemini -->     — include only in listed targets (comma-separated)

  Per-harness content overrides (item 2):
    <!-- harness:codex -->         — content visible only to codex (override block)
    <!-- /harness:codex -->        — close harness override block

  Inline skip annotations (item 9 — Smart Section Tagging):
    <!-- harness:skip=gemini -->          — skip THIS LINE for gemini only
    <!-- harness:skip=gemini,aider -->    — skip THIS LINE for gemini and aider
    <!-- harness:only=codex -->           — include THIS LINE only in codex
    <!-- harness:only=codex,opencode --> — include THIS LINE only in listed targets

  @harness shorthand annotations (item 28 — inline declarative style):
    <!-- @harness:codex-only -->    — include THIS LINE only in codex
    <!-- @harness:skip-gemini -->   — skip THIS LINE for gemini
    <!-- @harness:cursor,aider -->  — include THIS LINE only in cursor and aider
    <!-- @harness:skip-gemini,aider --> — skip THIS LINE for gemini and aider

  These are semantic aliases for the harness:only= / harness:skip= forms but
  use a more CSS-like @harness: prefix that some users find more readable.

  Environment-specific overrides (item 18):
    @env:production                — section only included when --env=production
    @env:dev                       — section only included when --env=dev
    <!-- env:production -->        — HTML-comment form of same annotation
    <!-- /env:production -->       — close an env block

  Unlike block-style harness: tags, inline skip/only annotations apply only
  to the line they appear on (or the section heading line if placed after ##).

Untagged content is included in all targets (default passthrough).
"""

import re

# Supported target names
KNOWN_TARGETS = ("codex", "gemini", "opencode", "cursor", "aider", "windsurf")

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
#   @harness:TARGET-only            — include this line only in TARGET
#   @harness:T1,T2                  — include this line only in T1, T2
#   @harness:skip-TARGET            — skip this line for TARGET
#   @harness:skip-T1,T2             — skip this line for T1 and T2
#
# Examples:
#   <!-- @harness:codex-only -->             → only in codex
#   <!-- @harness:cursor,aider -->           → only in cursor and aider
#   <!-- @harness:skip-gemini -->            → skip for gemini
#   <!-- @harness:skip-gemini,aider -->      → skip for gemini and aider
#
# These are normalised to the same semantics as harness:only= / harness:skip=.

# skip-TARGET(,TARGET)* form
_AT_HARNESS_SKIP_RE = re.compile(
    r"<!--\s*@harness:skip-([a-z0-9,\s_-]+)\s*-->",
    re.IGNORECASE,
)

# TARGET-only  OR  T1,T2  (inclusion) form  — NOTE: must be checked after skip
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


# Block-level exclude tag (item 30 — Harness-Specific Section Tagging):
#   <!-- harness:exclude:gemini -->   — open; section dropped for gemini only
#   <!-- /harness:exclude:gemini -->  — close
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
#   <!-- compliance:pinned -->   — open block; content is ALWAYS included in all targets
#   <!-- /compliance:pinned -->  — close block
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
#   @env:production  or  <!-- env:production -->  — open block for named env
#   <!-- /env:production -->                       — close env block
# The @env: shorthand on a standalone line is the friendlier form.
_ENV_OPEN_AT_RE = re.compile(r"^\s*@env:([a-z0-9_-]+)\s*$", re.IGNORECASE)
_ENV_OPEN_COMMENT_RE = re.compile(r"<!--\s*env:([a-z0-9_-]+)\s*-->", re.IGNORECASE)
_ENV_CLOSE_COMMENT_RE = re.compile(r"<!--\s*/env:([a-z0-9_-]+)\s*-->", re.IGNORECASE)


def _parse_target_list(targets_str: str) -> set[str]:
    """Parse a comma-separated target list string into a normalised set."""
    return {t.strip().lower() for t in targets_str.split(",") if t.strip()}


# --------------------------------------------------------------------------- #
# Frontmatter-based @target: / @skip: directive support (item 3)              #
# --------------------------------------------------------------------------- #
# Users can place directive lines at the top of a CLAUDE.md rule block:
#
#   @target:codex,gemini   — include this block ONLY in codex and gemini
#   @skip:cursor,aider     — exclude this block from cursor and aider
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
          - target_targets: set[str] — if non-empty, content targets only these
          - skip_targets:   set[str] — content must be excluded from these
          - cleaned:        str      — content with directive lines stripped out
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


def filter_rules_for_target(content: str, target_name: str) -> str:
    """Filter rules content for a specific target based on sync tags.

    Processes content line by line, supporting:
    1. Classic sync:exclude / sync:X-only / sync:end tags
    2. New <!-- no-sync --> shorthand (excludes from all)
    3. New <!-- sync:codex,gemini --> multi-target include lists
    4. New <!-- harness:X -->...<!-- /harness:X --> override blocks
       (content only visible to target X)
    5. Inline <!-- harness:skip=X,Y --> — drops THIS line for listed targets
    6. Inline <!-- harness:only=X,Y --> — keeps THIS line only for listed targets
    7. Inline <!-- @harness:skip-X,Y --> — @harness shorthand skip (item 28)
    8. Inline <!-- @harness:X-only --> or <!-- @harness:X,Y --> — @harness only (item 28)

    Args:
        content: Raw rules text (e.g. CLAUDE.md contents).
        target_name: Target identifier ("codex", "gemini", "opencode", ...).

    Returns:
        Filtered content with excluded sections removed. Tag comment lines
        themselves are stripped from the output.
    """
    if not content:
        return content

    target_lower = target_name.lower()

    lines = content.splitlines(keepends=True)
    output: list[str] = []

    # State machine
    # active_tag: None = include all, "exclude" = drop, "only:<targets>" = target list
    active_tag: str | None = None
    # harness_only: set of targets for current harness block; None = not in a harness block
    harness_target: str | None = None
    # compliance_pinned: True when inside <!-- compliance:pinned --> block.
    # Content in this block bypasses ALL other filter logic.
    compliance_pinned: bool = False
    # harness_exclude_target: set of targets currently in an exclude block.
    # Content inside <!-- harness:exclude:X --> ... <!-- /harness:exclude:X -->
    # is dropped for target X and included for all other targets.
    harness_exclude_targets: set[str] = set()

    for line in lines:
        # --- Check for compliance:pinned open/close tags ---
        if _COMPLIANCE_OPEN_RE.search(line):
            compliance_pinned = True
            continue  # Don't emit the tag line itself
        if _COMPLIANCE_CLOSE_RE.search(line):
            compliance_pinned = False
            continue  # Don't emit the tag line itself
        # Inside a compliance-pinned block: always include, skip all other logic
        if compliance_pinned:
            output.append(line)
            continue

        # --- Check for harness close tag first ---
        hc_match = _HARNESS_CLOSE_RE.search(line)
        if hc_match:
            # Closing a harness block
            harness_target = None
            continue  # Don't emit the tag line

        # --- Check for harness open tag ---
        ho_match = _HARNESS_OPEN_RE.search(line)
        if ho_match:
            harness_target = ho_match.group(1).lower()
            continue  # Don't emit the tag line

        # --- If inside a harness block, only emit for the matching target ---
        if harness_target is not None:
            if harness_target == target_lower:
                output.append(line)
            continue

        # --- Check for harness:exclude:X open/close block tags ---
        exc_close_m = _HARNESS_EXCLUDE_CLOSE_RE.search(line)
        if exc_close_m:
            harness_exclude_targets.discard(exc_close_m.group(1).lower())
            continue  # Don't emit the tag line

        exc_open_m = _HARNESS_EXCLUDE_OPEN_RE.search(line)
        if exc_open_m:
            harness_exclude_targets.add(exc_open_m.group(1).lower())
            continue  # Don't emit the tag line

        # --- If inside a harness:exclude block for this target, drop the line ---
        if target_lower in harness_exclude_targets:
            continue

        # --- Check for no-sync / sync:skip shorthands ---
        if re.search(r"<!--\s*(?:no-sync|sync:skip)\s*-->", line, re.IGNORECASE):
            active_tag = "exclude"
            continue

        # --- Check for classic sync tags ---
        cm = _CLASSIC_TAG_RE.search(line)
        if cm:
            tag = cm.group(1).lower()
            if tag == "end":
                active_tag = None
            elif tag == "exclude":
                active_tag = "exclude"
            else:
                # e.g. "codex-only"
                active_tag = tag
            continue

        # --- Check for multi-target sync tag: <!-- sync:codex,gemini --> ---
        mm = re.search(r"<!--\s*sync:([a-z0-9,\s]+)\s*-->", line, re.IGNORECASE)
        if mm:
            targets_str = mm.group(1)
            # Check if this looks like a target list (has comma or matches known targets)
            targets = {t.strip().lower() for t in targets_str.split(",") if t.strip()}
            # Only treat as multi-target if it doesn't match the old "-only" pattern
            # (classic tags already handled above)
            if targets and not any(t.endswith("-only") or t in ("exclude", "end") for t in targets):
                active_tag = f"targets:{','.join(sorted(targets))}"
                continue

        # --- @harness:skip-X shorthand (item 28) — applies to this line only ---
        # <!-- @harness:skip-gemini --> or <!-- @harness:skip-gemini,aider -->
        # Semantically equivalent to <!-- harness:skip=gemini --> but uses the
        # @harness: prefix style.  Checked before the plain harness:skip form.
        at_skip_m = _AT_HARNESS_SKIP_RE.search(line)
        if at_skip_m:
            skip_targets = _parse_at_harness_targets(at_skip_m.group(1))
            if target_lower in skip_targets:
                continue  # Drop this line for listed targets
            cleaned = _AT_HARNESS_SKIP_RE.sub("", line).rstrip()
            if cleaned.strip():
                output.append(cleaned + ("\n" if line.endswith("\n") else ""))
            continue

        # --- @harness:TARGET-only / @harness:T1,T2 shorthand (item 28) ---
        # <!-- @harness:codex-only --> or <!-- @harness:cursor,aider -->
        # Semantically equivalent to <!-- harness:only=codex --> forms.
        at_only_m = _AT_HARNESS_ONLY_RE.search(line)
        if at_only_m:
            only_targets = _parse_at_harness_targets(at_only_m.group(1))
            if target_lower in only_targets:
                cleaned = _AT_HARNESS_ONLY_RE.sub("", line).rstrip()
                if cleaned.strip():
                    output.append(cleaned + ("\n" if line.endswith("\n") else ""))
            continue  # Always consumed — other targets don't see this line

        # --- Inline harness:skip=X annotation — applies to this line only ---
        # Must be checked BEFORE harness_open so "harness:skip=gemini" doesn't
        # get confused with the block-opening "harness:gemini".
        skip_m = _HARNESS_SKIP_RE.search(line)
        if skip_m:
            skip_targets = _parse_target_list(skip_m.group(1))
            if target_lower in skip_targets:
                continue  # Drop this line for the listed targets
            # Strip the annotation tag itself from the emitted line
            cleaned = _HARNESS_SKIP_RE.sub("", line).rstrip()
            if cleaned.strip():
                output.append(cleaned + ("\n" if line.endswith("\n") else ""))
            continue

        # --- Inline harness:only=X annotation — applies to this line only ---
        only_m = _HARNESS_ONLY_RE.search(line)
        if only_m:
            only_targets = _parse_target_list(only_m.group(1))
            if target_lower in only_targets:
                # Emit line with annotation stripped
                cleaned = _HARNESS_ONLY_RE.sub("", line).rstrip()
                if cleaned.strip():
                    output.append(cleaned + ("\n" if line.endswith("\n") else ""))
            continue  # Always consumed — other targets don't see this line

        # --- Emit based on active_tag ---
        if active_tag is None:
            output.append(line)
        elif active_tag == "exclude":
            pass  # Drop
        elif active_tag.endswith("-only"):
            # Classic format: "codex-only" matches target "codex"
            expected = active_tag[:-5]  # strip "-only"
            if expected == target_lower:
                output.append(line)
        elif active_tag.startswith("targets:"):
            # New multi-target format
            allowed = set(active_tag[len("targets:"):].split(","))
            if target_lower in allowed:
                output.append(line)

    result = "".join(output)
    # Collapse runs of 3+ blank lines down to 2
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def filter_rules_for_env(content: str, env: str | None) -> str:
    """Filter CLAUDE.md content for a specific deployment environment (item 18).

    Supports two tag forms:

    1. **Inline heading annotation** — ``@env:X`` appended to a Markdown heading
       marks that section as env-specific. The section runs until the next heading
       at the same or higher level::

           ## Strict CI Rules @env:production
           - No debug logging

           ## Regular Rules
           - These always appear

    2. **Explicit block tags** — ``<!-- env:X --> ... <!-- /env:X -->``::

           <!-- env:production -->
           Only in production.
           <!-- /env:production -->
           Regular content again.

    Sections tagged for a specific env are dropped when syncing to a different env.
    Untagged sections and content are always included.

    Args:
        content: Raw CLAUDE.md text.
        env: Active environment name (e.g. "production", "dev"). If None or empty,
             all content is included (passthrough — strips tags only).

    Returns:
        Filtered content with non-matching env sections removed.
    """
    _HEADING_LINE_RE = re.compile(
        r"^(#{1,6})\s+(.+?)(?:\s+@env:([a-z0-9_-]+))?\s*$",
        re.IGNORECASE,
    )

    if not env:
        # No env filter — strip annotations/tags but keep all content
        def _strip_at_env(ln: str) -> str:
            return re.sub(r"\s*@env:[a-z0-9_-]+", "", ln, flags=re.IGNORECASE)

        cleaned = "\n".join(_strip_at_env(ln) for ln in content.splitlines())
        cleaned = _ENV_OPEN_COMMENT_RE.sub("", cleaned)
        cleaned = _ENV_CLOSE_COMMENT_RE.sub("", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    env_lower = env.lower()
    lines = content.splitlines(keepends=True)
    output: list[str] = []

    # State for explicit HTML-comment blocks
    comment_env: str | None = None  # current <!-- env:X --> block, or None

    # State for heading-annotated sections: (env_name, heading_level) or None
    heading_env: tuple[str, int] | None = None

    for line in lines:
        stripped = line.rstrip("\n")

        # --- HTML-comment close: <!-- /env:X --> ---
        close_m = _ENV_CLOSE_COMMENT_RE.search(stripped)
        if close_m and comment_env and close_m.group(1).lower() == comment_env:
            comment_env = None
            continue  # Don't emit the tag line

        # --- HTML-comment open: <!-- env:X --> ---
        open_m = _ENV_OPEN_COMMENT_RE.search(stripped)
        if open_m:
            comment_env = open_m.group(1).lower()
            continue  # Don't emit the tag line

        # --- Check for @env:X-annotated heading ---
        heading_m = _HEADING_LINE_RE.match(stripped)
        if heading_m:
            level = len(heading_m.group(1))
            section_env = (heading_m.group(3) or "").lower() or None

            # A heading at same/higher level closes the current heading-env block
            if heading_env is not None and level <= heading_env[1]:
                heading_env = None

            if section_env is not None:
                heading_env = (section_env, level)
                if section_env != env_lower:
                    continue  # Drop heading (and its body) for other envs
                # Emit heading with @env annotation stripped
                clean = re.sub(r"\s+@env:[a-z0-9_-]+", "", stripped, flags=re.IGNORECASE)
                output.append(clean + ("\n" if line.endswith("\n") else ""))
                continue
            # Untagged heading: also closes any heading-env block
            # (already handled above by level check)

        # --- Emit or drop based on active block state ---
        if comment_env is not None:
            if comment_env == env_lower:
                output.append(line)
            # else: drop (inside a different-env comment block)
        elif heading_env is not None:
            if heading_env[0] == env_lower:
                output.append(line)
            # else: drop (inside a different-env heading section)
        else:
            output.append(line)  # Untagged — always include

    result = "".join(output)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def has_env_tags(content: str) -> bool:
    """Return True if content contains any environment filter tags."""
    if not content:
        return False
    return bool(
        _ENV_OPEN_AT_RE.search(content)
        or _ENV_OPEN_COMMENT_RE.search(content)
        or _ENV_CLOSE_COMMENT_RE.search(content)
    )


def has_sync_tags(content: str) -> bool:
    """Return True if content contains any sync control tags."""
    if not content:
        return False
    # Classic tags
    if _CLASSIC_TAG_RE.search(content):
        return True
    # no-sync / sync:skip
    if re.search(r"<!--\s*(?:no-sync|sync:skip)\s*-->", content, re.IGNORECASE):
        return True
    # harness open/close
    if _HARNESS_OPEN_RE.search(content) or _HARNESS_CLOSE_RE.search(content):
        return True
    # Multi-target sync tags (<!-- sync:codex,gemini -->)
    mm = re.search(r"<!--\s*sync:([a-z0-9,\s]+)\s*-->", content, re.IGNORECASE)
    if mm:
        targets_str = mm.group(1)
        targets = {t.strip().lower() for t in targets_str.split(",") if t.strip()}
        if targets and not any(t.endswith("-only") or t in ("exclude", "end") for t in targets):
            return True
    # Inline harness:skip / harness:only annotations
    if _HARNESS_SKIP_RE.search(content) or _HARNESS_ONLY_RE.search(content):
        return True
    return False


# ---------------------------------------------------------------------------
# Rule Effectiveness Annotations (#25)
# ---------------------------------------------------------------------------

# Pattern: <!-- effective: helped | confused | neutral -->
# Optionally followed by a note: <!-- effective: confused in codex — too verbose -->
_EFFECTIVENESS_RE = re.compile(
    r"<!--\s*effective:\s*(helped|confused|neutral)(?:[^\-]+-+\s*([^>]+))?\s*-->",
    re.IGNORECASE,
)


def extract_effectiveness_annotations(content: str) -> list[dict]:
    """Extract rule effectiveness annotations from content.

    Users tag rules with <!-- effective: helped --> or
    <!-- effective: confused in codex — rule caused bad output -->
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
