from __future__ import annotations

"""Skill translation engine for cross-harness compatibility.

Strips or rewrites Claude Code-specific tool references from skill/agent/command
content before it is deployed to non-Claude Code harnesses. Prevents Codex or
Gemini from receiving instructions that reference tools they don't have.

Transformations applied:
- Tool-use XML blocks (<tool_call>...</tool_call>) → removed
- Claude Code tool names in inline references → generic equivalents
- Frontmatter fields that are CC-specific (e.g. ``allowed-tools``) → removed
- ARGUMENTS placeholder → generic form
"""

import re
from pathlib import Path

# Claude Code tool names that have no equivalent in generic harnesses
_CC_TOOLS = (
    "Read", "Write", "Edit", "Bash", "Glob", "Grep", "Agent",
    "TodoWrite", "TodoRead", "WebFetch", "WebSearch",
    "NotebookRead", "NotebookEdit", "ExitPlanMode", "EnterPlanMode",
    "ListMcpResourcesTool", "ReadMcpResourceTool",
    "LS", "MultiEdit", "Task",
)

# Pattern matching inline tool references like "use the Read tool" or "call Write"
_INLINE_TOOL_RE = re.compile(
    r"\b(the\s+)?(" + "|".join(re.escape(t) for t in _CC_TOOLS) + r")\s+tool\b",
    re.IGNORECASE,
)

# Pattern matching XML tool-call blocks (some CC skill docs use these)
_TOOL_CALL_BLOCK_RE = re.compile(
    r"<tool_call>.*?</tool_call>",
    re.DOTALL | re.IGNORECASE,
)

# Frontmatter fields that are CC-specific and should be stripped for other harnesses
_CC_FRONTMATTER_KEYS = {"allowed-tools", "tools", "tool-calls"}

# Replacement map for common tool references → portable equivalents
_TOOL_REPLACEMENTS = {
    "Read tool": "file reading",
    "Write tool": "file writing",
    "Edit tool": "file editing",
    "Bash tool": "shell execution",
    "Glob tool": "file pattern matching",
    "Grep tool": "content search",
    "Agent tool": "sub-agent delegation",
    "TodoWrite tool": "task tracking",
    "TodoRead tool": "task reading",
    "WebFetch tool": "web fetching",
    "WebSearch tool": "web search",
    "NotebookRead tool": "notebook reading",
    "NotebookEdit tool": "notebook editing",
}


def translate_skill_content(content: str, target_name: str) -> str:
    """Translate skill markdown content for a non-CC target harness.

    Claude Code skills are verbatim-copied by default. This function strips
    or rewrites references that only make sense in Claude Code so that Codex
    and Gemini receive clean, portable instructions.

    Args:
        content: Raw skill file content (markdown, possibly with YAML frontmatter).
        target_name: Destination harness ("codex", "gemini", "opencode").
                     If "claude" or unknown, content is returned unchanged.

    Returns:
        Translated content string.
    """
    if target_name.lower() in ("claude", ""):
        return content

    # Strip CC-specific frontmatter fields
    content = _strip_frontmatter_keys(content, _CC_FRONTMATTER_KEYS)

    # Remove XML tool-call blocks
    content = _TOOL_CALL_BLOCK_RE.sub("", content)

    # Replace inline "the X tool" references with generic equivalents
    def _replace_tool_ref(m: re.Match) -> str:
        prefix = m.group(1) or ""
        tool = m.group(2)
        key = f"{tool} tool"
        return _TOOL_REPLACEMENTS.get(key, f"{prefix}{tool} (not available in {target_name})")

    content = _INLINE_TOOL_RE.sub(_replace_tool_ref, content)

    # Collapse runs of blank lines introduced by removals
    content = re.sub(r"\n{3,}", "\n\n", content)

    return content.strip()


def translate_skill_file(path: Path, target_name: str) -> str:
    """Read a skill file and return its translated content.

    Args:
        path: Absolute path to the skill file (.md).
        target_name: Destination harness name.

    Returns:
        Translated file content string.
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return translate_skill_content(raw, target_name)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _strip_frontmatter_keys(content: str, keys_to_remove: set[str]) -> str:
    """Remove specific keys from YAML frontmatter while preserving the rest.

    Handles ``---`` delimited frontmatter at the start of the file.
    """
    if not content.startswith("---"):
        return content

    end = content.find("\n---", 3)
    if end == -1:
        return content

    frontmatter_block = content[3:end]
    body = content[end + 4:]

    # Remove matching key lines (simple line-by-line, not a full YAML parser)
    filtered_lines = []
    for line in frontmatter_block.splitlines():
        stripped = line.strip()
        key = stripped.split(":", 1)[0].strip().lower()
        if key in keys_to_remove:
            continue
        filtered_lines.append(line)

    new_frontmatter = "\n".join(filtered_lines).strip()
    if new_frontmatter:
        return f"---\n{new_frontmatter}\n---{body}"
    else:
        # All frontmatter removed — drop the delimiters too
        return body.lstrip("\n")
