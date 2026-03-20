from __future__ import annotations

"""Inline harness annotation parsing for per-harness rule overrides.

Supported annotation forms in CLAUDE.md:

  <!-- harness:codex -->
  This rule is only for Codex.
  <!-- /harness:codex -->

  <!-- harness:codex,cursor -->
  This rule is for Codex and Cursor only.
  <!-- /harness:codex,cursor -->

  <!-- harness:!gemini -->
  This rule is synced everywhere EXCEPT Gemini.
  <!-- /harness:!gemini -->

  <!-- sync:only:cursor,gemini -->
  Power-user form: only land in cursor and gemini.
  <!-- /sync:only -->

  <!-- sync:skip:codex -->
  Power-user form: sync everywhere EXCEPT codex.
  <!-- /sync:skip -->

Blocks without any annotation are included for all harnesses (default).
Opening and closing tags are consumed; only the block body is kept.
"""

import re

_HARNESS_ANNO_RE = re.compile(
    r"<!--\s*harness:(!?)([a-zA-Z0-9_,\s-]+?)\s*-->(.*?)<!--\s*/harness:[^>]+-->",
    re.DOTALL | re.IGNORECASE,
)

# sync:only:target1,target2 ... /sync:only  (include-list form)
_SYNC_ONLY_RE = re.compile(
    r"<!--\s*sync:only:([a-zA-Z0-9_,\s-]+?)\s*-->(.*?)<!--\s*/sync:only\s*-->",
    re.DOTALL | re.IGNORECASE,
)

# sync:skip:target1,target2 ... /sync:skip  (exclude-list form)
_SYNC_SKIP_RE = re.compile(
    r"<!--\s*sync:skip:([a-zA-Z0-9_,\s-]+?)\s*-->(.*?)<!--\s*/sync:skip\s*-->",
    re.DOTALL | re.IGNORECASE,
)


def filter_rules_for_harness(content: str, target: str) -> str:
    """Filter CLAUDE.md content, keeping only rules relevant to *target*.

    Inline harness annotations scope rule blocks to specific targets.
    Three equivalent syntaxes are supported:

    * ``<!-- harness:codex --> ... <!-- /harness:codex -->``
      Keep only when syncing to codex.
    * ``<!-- harness:codex,cursor --> ... <!-- /harness:codex,cursor -->``
      Keep only when syncing to codex or cursor.
    * ``<!-- harness:!gemini --> ... <!-- /harness:!gemini -->``
      Exclude when syncing to gemini.
    * ``<!-- sync:only:cursor,gemini --> ... <!-- /sync:only -->``
      Power-user alias: include only in cursor and gemini.
    * ``<!-- sync:skip:codex --> ... <!-- /sync:skip -->``
      Power-user alias: include everywhere except codex.

    Content outside annotation blocks is passed through unchanged.

    Args:
        content: Raw CLAUDE.md text.
        target: Target harness name (e.g. ``"codex"``).

    Returns:
        Filtered content with annotation markers removed.
    """
    target_lower = target.lower().strip()

    # ── Pass 1: resolve sync:only blocks ─────────────────────────────────────
    def _apply_sync_only(m: re.Match) -> str:
        targets = [t.strip().lower() for t in m.group(1).replace(" ", "").split(",") if t.strip()]
        return m.group(2) if target_lower in targets else ""

    content = _SYNC_ONLY_RE.sub(_apply_sync_only, content)

    # ── Pass 2: resolve sync:skip blocks ─────────────────────────────────────
    def _apply_sync_skip(m: re.Match) -> str:
        targets = [t.strip().lower() for t in m.group(1).replace(" ", "").split(",") if t.strip()]
        return m.group(2) if target_lower not in targets else ""

    content = _SYNC_SKIP_RE.sub(_apply_sync_skip, content)

    # ── Pass 3: resolve harness: blocks ──────────────────────────────────────
    result_parts: list[str] = []
    last_end = 0

    for m in _HARNESS_ANNO_RE.finditer(content):
        result_parts.append(content[last_end:m.start()])
        last_end = m.end()

        negate = m.group(1) == "!"
        raw_targets = [t.strip().lower() for t in m.group(2).replace(" ", "").split(",") if t.strip()]
        body = m.group(3)

        in_list = target_lower in raw_targets
        include = (not negate and in_list) or (negate and not in_list)
        if include:
            result_parts.append(body)

    result_parts.append(content[last_end:])
    return "".join(result_parts)
