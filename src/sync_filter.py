from __future__ import annotations

"""Tag-based content filtering for selective sync.

Allows users to annotate CLAUDE.md sections with sync control tags:
  <!-- sync:exclude -->          — exclude from all targets
  <!-- sync:codex-only -->       — include only in codex
  <!-- sync:gemini-only -->      — include only in gemini
  <!-- sync:opencode-only -->    — include only in opencode
  <!-- sync:end -->              — end a tagged region

Untagged content is included in all targets (default passthrough).
"""

import re

# Supported target names
KNOWN_TARGETS = ("codex", "gemini", "opencode")

# Tag patterns
_TAG_RE = re.compile(
    r"<!--\s*sync:(exclude|codex-only|gemini-only|opencode-only|end)\s*-->",
    re.IGNORECASE
)


def filter_rules_for_target(content: str, target_name: str) -> str:
    """Filter rules content for a specific target based on sync tags.

    Parses the content line by line, tracking active sync tags.
    Regions between a tag and the next ``<!-- sync:end -->`` are included
    or excluded based on whether the tag matches ``target_name``.

    Args:
        content: Raw rules text (e.g. CLAUDE.md contents).
        target_name: Target identifier ("codex", "gemini", "opencode").

    Returns:
        Filtered content with excluded sections removed. Tag comment lines
        themselves are stripped from the output.
    """
    if not content:
        return content

    # Build a set of accepted "only" tags for this target
    # e.g. "codex" accepts regions tagged "codex-only"
    target_only_tag = f"{target_name}-only"

    lines = content.splitlines(keepends=True)
    output: list[str] = []

    # State: None = default (include), "exclude" = drop, "only:<target>" = conditional
    active_tag: str | None = None

    for line in lines:
        m = _TAG_RE.search(line)
        if m:
            tag = m.group(1).lower()
            if tag == "end":
                active_tag = None
            elif tag == "exclude":
                active_tag = "exclude"
            else:
                # e.g. "codex-only"
                active_tag = tag
            # Don't emit tag lines themselves
            continue

        if active_tag is None:
            # Default region — include for all targets
            output.append(line)
        elif active_tag == "exclude":
            # Excluded from all targets
            pass
        elif active_tag == target_only_tag:
            # Matches this target — include
            output.append(line)
        else:
            # Some other target's exclusive region — skip
            pass

    result = "".join(output)
    # Collapse runs of 3+ blank lines down to 2 (clean up gaps left by removed sections)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def has_sync_tags(content: str) -> bool:
    """Return True if content contains any sync control tags."""
    return bool(_TAG_RE.search(content or ""))
