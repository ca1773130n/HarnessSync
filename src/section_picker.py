from __future__ import annotations

"""Interactive section picker for selective sync.

Presents a conversational multi-select checklist letting users choose which
sections of their Claude Code config to include in each sync.

Designed for TTY sessions. Falls back gracefully when stdin is not a terminal.

Usage (library):
    from src.section_picker import pick_sections_interactive

    only, skip = pick_sections_interactive(preselected={"rules", "mcp"})

Usage (command-line / --pick-sections flag):
    Invoked automatically by sync.py when --pick-sections is passed without --only.
"""

import sys

ALL_SECTIONS = ["rules", "skills", "agents", "commands", "mcp", "settings"]

_SECTION_DESCRIPTIONS = {
    "rules": "CLAUDE.md rules and instructions",
    "skills": "Skill directories (SKILL.md + assets)",
    "agents": "Agent .md configuration files",
    "commands": "Slash command .md files",
    "mcp": "MCP server configurations",
    "settings": "Settings and permission maps",
}


def pick_sections_interactive(
    preselected: set[str] | None = None,
    prompt: str = "Select sections to sync",
) -> tuple[set[str], set[str]]:
    """Present an interactive multi-select checklist for section selection.

    Returns (only_sections, skip_sections) where:
    - only_sections: non-empty set of selected sections (or empty to mean all)
    - skip_sections: sections explicitly deselected

    Args:
        preselected: Sections checked by default (default: all sections).
        prompt: Header text to show above the checklist.

    Returns:
        Tuple of (only_sections, skip_sections).
        If the user selects all sections, returns (set(), set()) so the
        caller can omit --only entirely and sync everything.
    """
    if not sys.stdin.isatty():
        # Non-interactive environment — return defaults
        return (set(), set())

    selected = set(preselected) if preselected is not None else set(ALL_SECTIONS)

    def _render(cursor: int) -> None:
        """Redraw the checklist."""
        print(f"\n{prompt}")
        print("─" * 50)
        for i, section in enumerate(ALL_SECTIONS):
            check = "✓" if section in selected else " "
            arrow = "▶" if i == cursor else " "
            desc = _SECTION_DESCRIPTIONS.get(section, "")
            print(f"  {arrow} [{check}] {section:<12}  {desc}")
        print("─" * 50)
        print("  ↑/↓: navigate  SPACE: toggle  ENTER: confirm  q: cancel")

    # Use simple numbered menu when we can't do cursor control
    if not _has_tty_control():
        return _pick_sections_numbered(selected, prompt)

    try:
        import termios
        import tty
    except ImportError:
        return _pick_sections_numbered(selected, prompt)

    cursor = 0
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        tty.setraw(fd)
        _render(cursor)

        while True:
            ch = sys.stdin.read(1)

            if ch == "\r" or ch == "\n":
                # Confirm
                break
            elif ch == "q" or ch == "\x03":  # q or Ctrl+C
                # Cancel — return defaults (no filtering)
                print("\n\nSection selection cancelled. Syncing all sections.")
                return (set(), set())
            elif ch == " ":
                # Toggle current section
                section = ALL_SECTIONS[cursor]
                if section in selected:
                    selected.discard(section)
                else:
                    selected.add(section)
                _render(cursor)
            elif ch == "\x1b":
                # Escape sequence — read two more chars for arrow keys
                seq = sys.stdin.read(2)
                if seq == "[A" and cursor > 0:  # Up arrow
                    cursor -= 1
                elif seq == "[B" and cursor < len(ALL_SECTIONS) - 1:  # Down arrow
                    cursor += 1
                _render(cursor)
            elif ch in "123456":
                # Shortcut: press number to toggle that section
                idx = int(ch) - 1
                if 0 <= idx < len(ALL_SECTIONS):
                    section = ALL_SECTIONS[idx]
                    if section in selected:
                        selected.discard(section)
                    else:
                        selected.add(section)
                    _render(cursor)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        print()  # Move past the menu

    return _selection_to_filters(selected)


def _has_tty_control() -> bool:
    """Check if we can use raw terminal control."""
    try:
        import termios
        import tty
        return True
    except ImportError:
        return False


def _pick_sections_numbered(
    preselected: set[str], prompt: str
) -> tuple[set[str], set[str]]:
    """Fallback numbered-list picker when cursor control is unavailable."""
    print(f"\n{prompt}")
    print("─" * 50)
    print("Currently selected (enter number to toggle, ENTER to confirm):")
    print()

    while True:
        for i, section in enumerate(ALL_SECTIONS, 1):
            check = "✓" if section in preselected else " "
            desc = _SECTION_DESCRIPTIONS.get(section, "")
            print(f"  [{check}] {i}. {section:<12}  {desc}")
        print()
        print("  Enter number(s) to toggle (e.g. '1 3'), or ENTER to confirm, 'q' to cancel:")

        try:
            line = input("  > ").strip()
        except EOFError:
            return (set(), set())

        if not line:
            break
        if line.lower() == "q":
            print("Section selection cancelled. Syncing all sections.")
            return (set(), set())

        for token in line.split():
            try:
                idx = int(token) - 1
                if 0 <= idx < len(ALL_SECTIONS):
                    section = ALL_SECTIONS[idx]
                    if section in preselected:
                        preselected.discard(section)
                    else:
                        preselected.add(section)
            except ValueError:
                pass
        print()

    return _selection_to_filters(preselected)


def _selection_to_filters(selected: set[str]) -> tuple[set[str], set[str]]:
    """Convert a selected set into (only_sections, skip_sections).

    If everything is selected, return (set(), set()) so the caller can
    simply omit section filters and sync everything.
    """
    all_set = set(ALL_SECTIONS)
    if selected == all_set or not selected:
        return (set(), set())

    skip = all_set - selected
    return (set(selected), skip)


def format_section_selection(only: set[str], skip: set[str]) -> str:
    """Return a human-readable summary of the section selection."""
    if not only and not skip:
        return "All sections selected."
    if only:
        return f"Syncing only: {', '.join(sorted(only))}"
    return f"Skipping: {', '.join(sorted(skip))}"
