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
# Translation quality scoring (item 29)
# ---------------------------------------------------------------------------

def score_translation(original: str, translated: str, target_name: str) -> dict:
    """Score how faithfully a skill was translated to a target harness (0-100).

    Quality is measured along three axes:
    - content_retention: Fraction of original non-whitespace characters preserved
    - tool_refs_remaining: CC-specific tool references still present after translation
    - frontmatter: Fraction of frontmatter keys preserved

    Args:
        original: Raw skill file content before translation
        translated: Content after translate_skill_content()
        target_name: Target harness name (included in output for reference)

    Returns:
        Dict with:
            score (int 0-100), grade (str), content_retention (float),
            tool_refs_dropped (int), tool_refs_original (int),
            tool_refs_remaining (int), frontmatter_keys_kept (int),
            frontmatter_keys_dropped (int), target (str), notes (list[str])
    """
    if not original.strip():
        return {
            "score": 100, "grade": "excellent", "target": target_name,
            "notes": ["Empty skill — nothing to translate"],
        }

    notes: list[str] = []

    # Content retention
    orig_chars = max(1, len(original.replace(" ", "").replace("\n", "")))
    trans_chars = len(translated.replace(" ", "").replace("\n", ""))
    content_retention = trans_chars / orig_chars

    # Tool reference analysis
    orig_tool_refs = len(_INLINE_TOOL_RE.findall(original))
    trans_tool_refs = len(_INLINE_TOOL_RE.findall(translated))
    tool_refs_dropped = orig_tool_refs - trans_tool_refs

    if orig_tool_refs > 0:
        notes.append(f"{tool_refs_dropped}/{orig_tool_refs} CC tool reference(s) rewritten")
    if trans_tool_refs > 0:
        notes.append(f"{trans_tool_refs} CC tool reference(s) still remain — may not work in {target_name}")

    # XML tool-call blocks
    xml_orig = len(_TOOL_CALL_BLOCK_RE.findall(original))
    xml_trans = len(_TOOL_CALL_BLOCK_RE.findall(translated))
    if xml_orig > xml_trans:
        notes.append(f"{xml_orig - xml_trans} XML tool-call block(s) removed")

    # Frontmatter keys
    fm_kept = _count_frontmatter_keys(translated)
    fm_orig = _count_frontmatter_keys(original)
    fm_dropped = fm_orig - fm_kept
    if fm_dropped > 0:
        notes.append(f"{fm_dropped} CC-specific frontmatter key(s) stripped")

    # Score: 50 pts base from content retention + 30 pts from tool ref cleanup
    retention_score = min(50, int(content_retention * 50))

    if orig_tool_refs > 0:
        rewrite_bonus = int((1 - trans_tool_refs / orig_tool_refs) * 30)
    else:
        rewrite_bonus = 30

    retention_penalty = 20 if content_retention < 0.3 else 0
    if content_retention < 0.3:
        notes.append("Warning: >70% of content dropped — review manually")

    score = max(0, min(100, retention_score + rewrite_bonus - retention_penalty))

    if score >= 90:
        grade = "excellent"
    elif score >= 70:
        grade = "good"
    elif score >= 50:
        grade = "fair"
    else:
        grade = "poor"

    if not notes:
        notes.append("No CC-specific content detected — translation is a clean copy")

    return {
        "score": score,
        "grade": grade,
        "content_retention": round(content_retention, 3),
        "tool_refs_dropped": tool_refs_dropped,
        "tool_refs_original": orig_tool_refs,
        "tool_refs_remaining": trans_tool_refs,
        "frontmatter_keys_kept": fm_kept,
        "frontmatter_keys_dropped": fm_dropped,
        "target": target_name,
        "notes": notes,
    }


def _count_frontmatter_keys(content: str) -> int:
    """Count YAML frontmatter keys, or 0 if no frontmatter."""
    if not content.startswith("---"):
        return 0
    end = content.find("\n---", 3)
    if end == -1:
        return 0
    fm_text = content[3:end]
    return sum(1 for line in fm_text.splitlines() if re.match(r"^\w[\w-]*\s*:", line))


def score_skill_file(path: Path, target_name: str) -> dict:
    """Read a skill file and return its translation quality score.

    Args:
        path: Path to the skill file (.md)
        target_name: Target harness name

    Returns:
        Score dict from score_translation()
    """
    try:
        original = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"score": 0, "grade": "poor", "target": target_name,
                "notes": ["Could not read skill file"]}
    translated = translate_skill_content(original, target_name)
    return score_translation(original, translated, target_name)


# ---------------------------------------------------------------------------
# Degraded-but-functional skill variant generator (#21)
# ---------------------------------------------------------------------------

# Harnesses that can embed instructions in their agent/rules format
_PLAIN_TEXT_TARGETS = frozenset(("codex", "gemini", "opencode", "aider", "windsurf", "cursor"))

# Header inserted into generated degraded variants to make them self-documenting
_DEGRADED_HEADER_TEMPLATE = (
    "<!-- HarnessSync: auto-generated degraded variant for {target} -->\n"
    "<!-- Original Claude Code skill: {skill_name} -->\n"
    "<!-- Some CC-specific capabilities are unavailable in {target}; "
    "equivalent instructions provided below. -->\n\n"
)


def generate_degraded_variant(content: str, skill_name: str, target_name: str) -> str:
    """Generate a degraded-but-functional skill variant for an unsupported target.

    When a skill uses MCP tools, Agent sub-tasks, or other CC-only capabilities
    that don't translate literally, this function produces a plain-text version
    with equivalent instructions so the user can still invoke analogous behavior
    in the target harness.

    Strategy:
    1. Translate CC tool references to descriptive equivalents (reuse existing logic)
    2. Replace MCP tool_call blocks with explanatory text
    3. Strip CC-only frontmatter but keep name/description
    4. Prepend a self-documenting header noting this is a degraded variant
    5. Append a "Limitations" section listing what was unavailable

    Args:
        content: Raw skill file content.
        skill_name: Name of the skill (for the header).
        target_name: Destination harness name.

    Returns:
        Degraded-but-functional content string.
    """
    if not content.strip():
        return content

    # Step 1: Standard translation pass
    translated = translate_skill_content(content, target_name)

    # Step 2: Replace remaining MCP tool invocations with explanatory text
    # Pattern: lines that contain tool invocations like `use_mcp_tool(...)` or
    # XML-style `<mcp_call>...</mcp_call>` that survived standard translation
    mcp_call_re = re.compile(
        r"(?:<mcp_call>.*?</mcp_call>|use_mcp_tool\([^)]+\))",
        re.DOTALL | re.IGNORECASE,
    )
    translated = mcp_call_re.sub(
        f"[Note: This step requires a tool available in Claude Code but not in {target_name}. "
        "Perform this step manually or via the harness's native tools.]",
        translated,
    )

    # Step 3: Collect limitations for the footer
    limitations: list[str] = []
    orig_tool_refs = len(_INLINE_TOOL_RE.findall(content))
    if orig_tool_refs > 0:
        limitations.append(f"Claude Code tool references rewritten ({orig_tool_refs} found)")
    if _TOOL_CALL_BLOCK_RE.search(content):
        limitations.append("XML tool-call blocks removed (CC-only syntax)")
    if mcp_call_re.search(content):
        limitations.append("MCP tool calls replaced with manual-step instructions")

    # Step 4: Build the degraded variant
    header = _DEGRADED_HEADER_TEMPLATE.format(
        target=target_name, skill_name=skill_name
    )

    footer = ""
    if limitations:
        footer = (
            "\n\n---\n**Limitations in this degraded variant:**\n"
            + "\n".join(f"- {lim}" for lim in limitations)
        )

    return header + translated + footer


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def inject_agent_translation_hints(
    agent_content: str,
    agent_name: str,
    target_name: str,
) -> str:
    """Inject comment blocks explaining Claude Code capability gaps into agent content.

    When an agent uses CC-specific tools or APIs that don't exist in the target
    harness, this function prepends a structured hint block explaining what's
    missing and suggesting manual workarounds. Silent missing features are worse
    than documented ones.

    Args:
        agent_content: The agent's markdown content.
        agent_name: Name of the agent (for the hint header).
        target_name: Target harness name.

    Returns:
        Agent content with translation hints prepended (if any gaps detected).
    """
    if not agent_content.strip():
        return agent_content

    gaps: list[str] = []

    # Detect MCP tool call references
    mcp_matches = re.findall(r"mcp__(\w+)__(\w+)", agent_content)
    for server, tool in mcp_matches:
        gaps.append(
            f"MCP tool `mcp__{server}__{tool}` — requires '{server}' MCP server "
            f"(not available in {target_name}). "
            f"Workaround: invoke the equivalent API manually or via a shell command."
        )

    # Detect Agent tool sub-dispatch
    if re.search(r"\bAgent\b.*\btool\b|\bsub.?agent\b|\bdispatch.*agent\b", agent_content, re.I):
        gaps.append(
            f"Sub-agent dispatch — Claude Code's Agent tool is not available in {target_name}. "
            f"Workaround: break the task into sequential prompts or use separate harness sessions."
        )

    # Detect hook event references
    hook_events = re.findall(
        r"\b(PreToolUse|PostToolUse|UserPromptSubmit|SessionStart|SessionEnd|SubagentStop)\b",
        agent_content,
    )
    if hook_events:
        unique_hooks = sorted(set(hook_events))
        gaps.append(
            f"Hook events ({', '.join(unique_hooks)}) — {target_name} has no hook system. "
            f"Workaround: replicate lifecycle behavior using git hooks or shell wrappers."
        )

    # Detect TodoWrite / TodoRead references
    if re.search(r"\bTodoWrite\b|\bTodoRead\b", agent_content):
        gaps.append(
            f"TodoWrite/TodoRead — Claude Code task tracking is not available in {target_name}. "
            f"Workaround: use a plain text TODO file or issue tracker."
        )

    # Detect CLAUDE_PLUGIN_ROOT or plugin path references
    if re.search(r"CLAUDE_PLUGIN_ROOT|\$CLAUDE_\w+", agent_content):
        gaps.append(
            f"Claude Code plugin environment variables — not available in {target_name}. "
            f"Workaround: use hardcoded paths or standard environment variables instead."
        )

    if not gaps:
        return agent_content

    # Build the hint block
    hint_lines = [
        f"<!-- HarnessSync: Agent Translation Hints for '{agent_name}' in {target_name} -->",
        f"<!-- This agent uses {len(gaps)} Claude Code feature(s) not available in {target_name}. -->",
        "<!--",
    ]
    for i, gap in enumerate(gaps, 1):
        hint_lines.append(f"  {i}. {gap}")
    hint_lines.append("-->")
    hint_lines.append("")

    return "\n".join(hint_lines) + agent_content


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
