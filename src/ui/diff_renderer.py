from __future__ import annotations

"""Colored unified diff renderer for interactive sync approval.

Renders a unified diff between current and proposed target file content
using ANSI escape codes. Used by the --interactive sync mode.

Usage:
    from src.ui.diff_renderer import render_diff, prompt_approval

    decision = prompt_approval("cursor", current_text, proposed_text)
    # Returns: "yes" | "no" | "skip"
"""

import difflib
import sys

# ANSI codes
_RED = "\033[31m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RESET = "\033[0m"

_NO_COLOR = not sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    """Apply ANSI color code if stdout is a TTY."""
    if _NO_COLOR:
        return text
    return f"{code}{text}{_RESET}"


def render_diff(
    current: str,
    proposed: str,
    from_label: str = "current",
    to_label: str = "proposed",
    context_lines: int = 3,
) -> str:
    """Render a colored unified diff between two strings.

    Args:
        current: Current file content.
        proposed: Proposed (new) file content.
        from_label: Label for the left (old) side.
        to_label: Label for the right (new) side.
        context_lines: Lines of surrounding context to show.

    Returns:
        String with ANSI-colored unified diff, or an empty string if identical.
    """
    if current == proposed:
        return ""

    current_lines = current.splitlines(keepends=True)
    proposed_lines = proposed.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        current_lines,
        proposed_lines,
        fromfile=from_label,
        tofile=to_label,
        n=context_lines,
    ))

    if not diff_lines:
        return ""

    colored: list[str] = []
    for line in diff_lines:
        if line.startswith("+++") or line.startswith("---"):
            colored.append(_c(_BOLD, line.rstrip("\n")))
        elif line.startswith("@@"):
            colored.append(_c(_CYAN, line.rstrip("\n")))
        elif line.startswith("+"):
            colored.append(_c(_GREEN, line.rstrip("\n")))
        elif line.startswith("-"):
            colored.append(_c(_RED, line.rstrip("\n")))
        else:
            colored.append(_c(_DIM, line.rstrip("\n")))

    return "\n".join(colored)


def prompt_approval(
    target_name: str,
    current: str,
    proposed: str,
    context_lines: int = 3,
) -> str:
    """Show a colored diff for target_name and prompt the user for approval.

    Args:
        target_name: Name of the sync target (e.g. "cursor").
        current: Current target file content (empty string if new file).
        proposed: Proposed new content.
        context_lines: Context lines around each change.

    Returns:
        One of: "yes" (write), "no" (skip this time), "skip" (skip always).
    """
    if current == proposed:
        return "yes"

    diff_text = render_diff(current, proposed, from_label=f"{target_name} (current)", to_label=f"{target_name} (proposed)", context_lines=context_lines)

    print()
    print(_c(_BOLD, f"─── {target_name} ───"))
    if diff_text:
        print(diff_text)
    else:
        print(_c(_DIM, "  (binary or whitespace-only change)"))
    print()

    while True:
        try:
            answer = input("  Write this target? [y]es / [n]o (skip once) / [s]kip always: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "no"

        if answer in ("y", "yes", ""):
            return "yes"
        if answer in ("n", "no"):
            return "no"
        if answer in ("s", "skip"):
            return "skip"
        print("  Please enter y, n, or s.")
