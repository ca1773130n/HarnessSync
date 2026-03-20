from __future__ import annotations

"""Filter engine applying sync control tags to content.

Core filtering functions that process CLAUDE.md content line by line,
applying classic tags, multi-target tags, harness blocks, inline skip/only
annotations, compliance-pinned blocks, environment filters, and
section-level annotations.
"""

import re

from src.filter_rules import (
    _CLASSIC_TAG_RE,
    _HARNESS_OPEN_RE,
    _HARNESS_CLOSE_RE,
    _HARNESS_SKIP_RE,
    _HARNESS_ONLY_RE,
    _AT_HARNESS_SKIP_RE,
    _AT_HARNESS_ONLY_RE,
    _HARNESS_EXCLUDE_OPEN_RE,
    _HARNESS_EXCLUDE_CLOSE_RE,
    _COMPLIANCE_OPEN_RE,
    _COMPLIANCE_CLOSE_RE,
    _ENV_OPEN_AT_RE,
    _ENV_OPEN_COMMENT_RE,
    _ENV_CLOSE_COMMENT_RE,
    _PY_HARNESS_SKIP_RE,
    _PY_HARNESS_REPLACE_RE,
    _SECTION_ANNOTATION_RE,
    _parse_target_list,
    _parse_at_harness_targets,
)

# Re-export helpers so that imports from filter_engine still work
from src.filter_helpers import (
    extract_effectiveness_annotations,
    format_effectiveness_report,
    has_compliance_pinned,
    extract_compliance_pinned,
    extract_effectiveness_propagation_annotations,
    propagate_effectiveness_annotations,
    extract_section_annotations,
    format_section_annotation_report,
)


def filter_rules_for_target(content: str, target_name: str) -> str:
    """Filter rules content for a specific target based on sync tags.

    Processes content line by line, supporting:
    1. Classic sync:exclude / sync:X-only / sync:end tags
    2. New <!-- no-sync --> shorthand (excludes from all)
    3. New <!-- sync:codex,gemini --> multi-target include lists
    4. New <!-- harness:X -->...<!-- /harness:X --> override blocks
       (content only visible to target X)
    5. Inline <!-- harness:skip=X,Y --> -- drops THIS line for listed targets
    6. Inline <!-- harness:only=X,Y --> -- keeps THIS line only for listed targets
    7. Inline <!-- @harness:skip-X,Y --> -- @harness shorthand skip (item 28)
    8. Inline <!-- @harness:X-only --> or <!-- @harness:X,Y --> -- @harness only (item 28)
    9. Python/shell # @targets: skip -- drops THIS line for listed targets
   10. Python/shell # @targets: replace with <text> -- replaces THIS line for listed targets

    Args:
        content: Raw rules text (e.g. CLAUDE.md contents).
        target_name: Target identifier ("codex", "gemini", "opencode", ...).

    Returns:
        Filtered content with excluded sections removed. Tag comment lines
        themselves are stripped from the output.
    """
    if not content:
        return content

    # Apply section-level heading annotations first (whole-section include/exclude)
    # before the line-by-line inline tag processing below.
    content = filter_sections_for_target(content, target_name)

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

        # --- @harness:skip-X shorthand (item 28) -- applies to this line only ---
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
            continue  # Always consumed -- other targets don't see this line

        # --- Inline harness:skip=X annotation -- applies to this line only ---
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

        # --- Inline harness:only=X annotation -- applies to this line only ---
        only_m = _HARNESS_ONLY_RE.search(line)
        if only_m:
            only_targets = _parse_target_list(only_m.group(1))
            if target_lower in only_targets:
                # Emit line with annotation stripped
                cleaned = _HARNESS_ONLY_RE.sub("", line).rstrip()
                if cleaned.strip():
                    output.append(cleaned + ("\n" if line.endswith("\n") else ""))
            continue  # Always consumed -- other targets don't see this line

        # --- Python/shell comment-style: # @targets: skip ---
        # Example: "- Use /debug skill  # @aider: skip"
        # For matching targets: drop the line entirely.
        # For non-matching targets: emit the content without the annotation.
        py_skip_m = _PY_HARNESS_SKIP_RE.search(line)
        if py_skip_m:
            skip_targets = _parse_target_list(py_skip_m.group(1))
            if target_lower in skip_targets:
                continue  # Drop for listed targets
            # Strip annotation, preserve leading whitespace + content
            cleaned = line[: py_skip_m.start()].rstrip()
            if cleaned.strip():
                output.append(cleaned + ("\n" if line.endswith("\n") else ""))
            continue

        # --- Python/shell comment-style: # @targets: replace with <text> ---
        # Example: "- Use /debug skill  # @aider: replace with See debug-task.md"
        # For matching targets: emit the replacement text (preserving leading indent).
        # For non-matching targets: emit original content without the annotation.
        py_replace_m = _PY_HARNESS_REPLACE_RE.search(line)
        if py_replace_m:
            replace_targets = _parse_target_list(py_replace_m.group(1))
            replacement = py_replace_m.group(2).strip()
            leading = line[: len(line) - len(line.lstrip())]
            if target_lower in replace_targets:
                if replacement:
                    output.append(leading + replacement + ("\n" if line.endswith("\n") else ""))
            else:
                cleaned = line[: py_replace_m.start()].rstrip()
                if cleaned.strip():
                    output.append(cleaned + ("\n" if line.endswith("\n") else ""))
            continue

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

    1. **Inline heading annotation** -- ``@env:X`` appended to a Markdown heading
       marks that section as env-specific. The section runs until the next heading
       at the same or higher level::

           ## Strict CI Rules @env:production
           - No debug logging

           ## Regular Rules
           - These always appear

    2. **Explicit block tags** -- ``<!-- env:X --> ... <!-- /env:X -->``::

           <!-- env:production -->
           Only in production.
           <!-- /env:production -->
           Regular content again.

    Sections tagged for a specific env are dropped when syncing to a different env.
    Untagged sections and content are always included.

    Args:
        content: Raw CLAUDE.md text.
        env: Active environment name (e.g. "production", "dev"). If None or empty,
             all content is included (passthrough -- strips tags only).

    Returns:
        Filtered content with non-matching env sections removed.
    """
    _HEADING_LINE_RE = re.compile(
        r"^(#{1,6})\s+(.+?)(?:\s+@env:([a-z0-9_-]+))?\s*$",
        re.IGNORECASE,
    )

    if not env:
        # No env filter -- strip annotations/tags but keep all content
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
            output.append(line)  # Untagged -- always include

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


def filter_sections_for_target(content: str, target_name: str) -> str:
    """Remove or retain whole Markdown sections based on heading-level annotations.

    When a heading line carries a ``<!-- harness:codex-only -->`` or similar
    annotation, the entire section (heading + body, up to the next same-level
    or higher heading) is either kept or dropped for the given target.

    This is complementary to ``filter_rules_for_target()``, which handles
    inline and block-level tags. This function handles coarser, section-level
    targeting.

    Sections without annotations pass through unchanged.

    Args:
        content: Raw CLAUDE.md Markdown text.
        target_name: Target harness name (e.g. "codex", "gemini").

    Returns:
        Filtered content with excluded sections removed.
    """
    target_lower = target_name.lower()

    # Parse all annotated sections first
    annotated: dict[int, dict] = {}  # start_pos -> annotation
    for m in _SECTION_ANNOTATION_RE.finditer(content):
        annotated[m.start()] = {
            "match": m,
            "annotation_type": None,
            "targets": set(),
        }
        only_a = m.group("only_a")
        only_b = m.group("only_b")
        skip_a = m.group("skip_a")
        skip_b = m.group("skip_b")
        if only_a:
            raw = only_a.replace("-only", "")
            annotated[m.start()]["targets"] = {t.strip() for t in raw.split(",") if t.strip()}
            annotated[m.start()]["annotation_type"] = "only"
        elif only_b:
            annotated[m.start()]["targets"] = {t.strip() for t in only_b.split(",") if t.strip()}
            annotated[m.start()]["annotation_type"] = "only"
        elif skip_a:
            annotated[m.start()]["targets"] = {t.strip() for t in skip_a.split(",") if t.strip()}
            annotated[m.start()]["annotation_type"] = "skip"
        else:
            annotated[m.start()]["targets"] = {t.strip() for t in skip_b.split(",") if t.strip()}
            annotated[m.start()]["annotation_type"] = "skip"

    if not annotated:
        return content

    # Split content into lines with character positions
    lines = content.splitlines(keepends=True)
    line_starts = []
    pos = 0
    for line in lines:
        line_starts.append(pos)
        pos += len(line)

    # Build a set of line indices to drop
    heading_re = re.compile(r"^(#{1,4})\s", re.MULTILINE)
    heading_matches = list(heading_re.finditer(content))

    # For each annotated heading, determine section extent and decide to keep/drop
    drop_ranges: list[tuple[int, int]] = []  # (start_line_idx, end_line_idx) exclusive

    for start_pos, ann_info in annotated.items():
        ann_type = ann_info["annotation_type"]
        targets = ann_info["targets"]

        # Should this section be excluded for the target?
        if ann_type == "only":
            exclude = target_lower not in targets
        else:  # "skip"
            exclude = target_lower in targets

        if not exclude:
            continue

        # Find which heading_match corresponds to this annotation
        match_obj = ann_info["match"]
        ann_heading_start = match_obj.start()

        # Find index of this heading in heading_matches
        hm_idx = next(
            (i for i, hm in enumerate(heading_matches) if hm.start() == ann_heading_start),
            None,
        )
        if hm_idx is None:
            continue

        current_level = len(heading_matches[hm_idx].group(1))

        # Section ends at next heading of same or higher level
        section_start = ann_heading_start
        section_end = len(content)
        for hm in heading_matches[hm_idx + 1:]:
            level = len(hm.group(1))
            if level <= current_level:
                section_end = hm.start()
                break

        drop_ranges.append((section_start, section_end))

    if not drop_ranges:
        return content

    # Build output by excluding dropped character ranges
    result_parts: list[str] = []
    cursor = 0
    for start, end in sorted(drop_ranges):
        if cursor < start:
            result_parts.append(content[cursor:start])
        cursor = max(cursor, end)
    if cursor < len(content):
        result_parts.append(content[cursor:])

    return "".join(result_parts)
