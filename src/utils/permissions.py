from __future__ import annotations

"""Permission extraction and parsing utilities for HarnessSync.

Provides stateless functions for extracting and parsing Claude Code permission
settings into a structured format that adapters can consume for target-specific
permission mapping.

Permission string format examples:
    "Bash(npm *)"   -> tool="Bash", args="npm *"
    "Read"          -> tool="Read", args=""
    "Bash(git push *)" -> tool="Bash", args="git push *"
    "WebFetch(https://api.example.com/*)" -> tool="WebFetch", args="https://api.example.com/*"
"""


def extract_permissions(settings: dict) -> dict:
    """Extract permission lists from Claude Code settings dict.

    Pulls from ``settings["permissions"]["allow"]``,
    ``settings["permissions"]["deny"]``, and
    ``settings["permissions"]["ask"]`` keys. Missing keys default
    to empty lists.

    Args:
        settings: Claude Code settings dict (from SourceReader.get_settings()).
                  May be empty, missing the "permissions" key, or have
                  partial permission sub-keys.

    Returns:
        Dict with keys "allow", "deny", "ask", each mapping to a list
        of permission strings. Always returns all three keys.
    """
    if not isinstance(settings, dict):
        return {"allow": [], "deny": [], "ask": []}

    permissions = settings.get("permissions", {})
    if not isinstance(permissions, dict):
        return {"allow": [], "deny": [], "ask": []}

    result = {}
    for key in ("allow", "deny", "ask"):
        val = permissions.get(key, [])
        if isinstance(val, list):
            result[key] = list(val)  # defensive copy
        else:
            result[key] = []

    return result


def parse_permission_string(perm: str) -> tuple[str, str]:
    """Parse a Claude Code permission string into (tool_name, args).

    Handles several formats:
        "Read"                      -> ("Read", "")
        "Bash(npm *)"               -> ("Bash", "npm *")
        "Bash(git push *)"          -> ("Bash", "git push *")
        "WebFetch(https://x.com/*)" -> ("WebFetch", "https://x.com/*)")
                                       Note: nested parens preserved.
        ""                          -> ("", "")

    The parser finds the first ``(`` and the **last** ``)`` to handle
    nested parentheses in arguments (e.g. URL patterns containing parens).

    Args:
        perm: Raw permission string from Claude Code settings.

    Returns:
        Tuple of (tool_name, args_string). tool_name is the portion
        before the first ``(``, args_string is everything between
        the first ``(`` and the last ``)``. If no parens, args is "".
    """
    if not perm or not isinstance(perm, str):
        return ("", "")

    perm = perm.strip()
    if not perm:
        return ("", "")

    # Find first opening paren
    open_idx = perm.find("(")
    if open_idx == -1:
        # No parens — bare tool name like "Read"
        return (perm, "")

    tool_name = perm[:open_idx].strip()

    # Find last closing paren (handles nested parens)
    close_idx = perm.rfind(")")
    if close_idx == -1 or close_idx <= open_idx:
        # Malformed: opening paren but no closing — treat remainder as args
        args = perm[open_idx + 1:].strip()
        return (tool_name, args)

    args = perm[open_idx + 1:close_idx].strip()
    return (tool_name, args)
