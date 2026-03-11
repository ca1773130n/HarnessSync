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


def _parse_target_list(targets_str: str) -> set[str]:
    """Parse a comma-separated target list string into a normalised set."""
    return {t.strip().lower() for t in targets_str.split(",") if t.strip()}


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

    for line in lines:
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
