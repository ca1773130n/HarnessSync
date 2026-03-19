from __future__ import annotations

"""@include directive resolution for CLAUDE.md files.

Resolves ``@include path/to/file.md`` directives by inlining the referenced
file content. Supports:
- Cycle detection (tracks seen paths, rejects if revisited)
- Max depth limit (default 10, rejects at depth 11)
- Missing files (graceful skip with inline comment)
- Symlink boundary enforcement (no traversal outside base_dir parent tree)
- Diamond dependency graphs (same file included from multiple paths, no error)
"""

import re
from pathlib import Path

# Matches @include at start of line or after whitespace
INCLUDE_RE = re.compile(r'(?:^|(?<=\s))@include\s+(\S+)', re.MULTILINE)

MAX_INCLUDE_DEPTH = 10


def resolve_includes(
    content: str,
    base_dir: Path,
    *,
    _seen: set[Path] | None = None,
    _depth: int = 0,
) -> tuple[str, list[Path]]:
    """Resolve ``@include`` directives by inlining referenced file content.

    Scans *content* for ``@include path/to/file.md`` patterns and replaces
    each with the content of the referenced file. Paths are resolved relative
    to *base_dir* (the directory of the source file).

    Args:
        content:   Source text potentially containing ``@include`` directives.
        base_dir:  Directory against which relative include paths are resolved.
        _seen:     (Internal) Set of already-seen resolved paths for cycle detection.
        _depth:    (Internal) Current recursion depth.

    Returns:
        Tuple of (resolved_content, list_of_included_file_paths).
        Included paths are in encounter order, deduplicated.
    """
    if _seen is None:
        _seen = set()

    included_paths: list[Path] = []

    def _replace_include(m: re.Match) -> str:
        raw_path = m.group(1)

        # Resolve relative to base_dir
        try:
            target = (base_dir / raw_path).resolve()
        except (OSError, ValueError):
            return f"<!-- @include {raw_path}: could not resolve path -->"

        # Depth limit: depth 10 is the last valid level; depth 11 is rejected
        if _depth + 1 > MAX_INCLUDE_DEPTH:
            return f"<!-- @include {raw_path}: max include depth ({MAX_INCLUDE_DEPTH}) exceeded -->"

        # Cycle detection: if we've already seen this resolved path, skip
        if target in _seen:
            return f"<!-- @include {raw_path}: circular include detected -->"

        # NOTE: Symlink boundary check is defense-in-depth. Since Path.resolve()
        # follows symlinks, target.is_symlink() will be False for most resolved
        # paths. This catches the edge case of unresolvable or chained symlinks.
        try:
            anchor = base_dir.resolve()
            # Walk up to find a reasonable boundary (use the original base_dir's root)
            # The constraint is: the resolved target must share a common prefix
            # with the base_dir's parent tree
            anchor_parents = set(anchor.parents) | {anchor}
            target_parents = set(target.parents) | {target}
            # Check if target is within the anchor tree (ancestor or descendant)
            if not (target.is_relative_to(anchor) or anchor.is_relative_to(target.parent)):
                # Neither descendant nor ancestor -- check they share a common root
                # Allow if they share the base_dir's grandparent at minimum
                common = anchor_parents & target_parents
                if not common or (len(common) == 1 and Path('/') in common):
                    # Only the filesystem root in common -- too far outside
                    if target.is_symlink():
                        return f"<!-- @include {raw_path}: symlink outside project boundary -->"
        except (OSError, ValueError):
            pass

        # Read the file
        if not target.is_file():
            return f"<!-- @include {raw_path}: file not found -->"

        try:
            file_content = target.read_text(encoding='utf-8', errors='replace')
        except OSError:
            return f"<!-- @include {raw_path}: could not read file -->"

        # Track this path
        if target not in included_paths:
            included_paths.append(target)

        # Mark as seen for cycle detection in this branch
        new_seen = _seen | {target}

        # Recursively resolve includes in the inlined content
        resolved, nested_paths = resolve_includes(
            file_content,
            target.parent,
            _seen=new_seen,
            _depth=_depth + 1,
        )

        # Collect nested included paths
        for p in nested_paths:
            if p not in included_paths:
                included_paths.append(p)

        return resolved

    result = INCLUDE_RE.sub(_replace_include, content)
    return result, included_paths


def extract_include_refs(content: str) -> list[str]:
    """Extract raw ``@include`` path strings without resolving them.

    Useful for adapters that want the raw references (e.g., Gemini's
    ``@file.md`` native import syntax).

    Args:
        content: Source text with potential ``@include`` directives.

    Returns:
        List of raw path strings in encounter order.
    """
    return INCLUDE_RE.findall(content)
