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
# Batch scoring (item 9 — Skill Translation Quality Score)
# ---------------------------------------------------------------------------

def score_skills_batch(
    skills: list[tuple[str, str]],
    target_name: str,
    low_score_threshold: int = 70,
) -> dict:
    """Score multiple skills for a target harness and return an aggregate report.

    Translates each skill and scores the result, then aggregates into a
    summary with per-skill breakdown and a list of low-quality translations
    that should be reviewed before syncing.

    Args:
        skills: List of (skill_name, raw_content) tuples.
        target_name: Destination harness (e.g. "codex", "gemini").
        low_score_threshold: Scores below this value trigger a warning.
                             Default: 70.

    Returns:
        Dict with:
            - target: str
            - skill_count: int
            - average_score: int (0-100)
            - min_score: int
            - max_score: int
            - low_quality: list[dict] — skills scoring below threshold
            - scores: list[dict] — full per-skill score dicts
            - summary: str — one-line human-readable summary
    """
    if not skills:
        return {
            "target": target_name,
            "skill_count": 0,
            "average_score": 100,
            "min_score": 100,
            "max_score": 100,
            "low_quality": [],
            "scores": [],
            "summary": f"{target_name}: No skills to score.",
        }

    score_dicts: list[dict] = []
    for name, content in skills:
        translated = translate_skill_content(content, target_name)
        result = score_translation(content, translated, target_name)
        result["skill_name"] = name
        score_dicts.append(result)

    score_values = [d["score"] for d in score_dicts]
    avg = int(sum(score_values) / len(score_values))
    low_quality = [d for d in score_dicts if d["score"] < low_score_threshold]

    summary_parts = [f"{target_name}: {len(skills)} skill(s), avg score {avg}/100"]
    if low_quality:
        summary_parts.append(
            f"{len(low_quality)} below {low_score_threshold} — review before syncing"
        )

    return {
        "target": target_name,
        "skill_count": len(skills),
        "average_score": avg,
        "min_score": min(score_values),
        "max_score": max(score_values),
        "low_quality": low_quality,
        "scores": score_dicts,
        "summary": ", ".join(summary_parts) + ".",
    }


def format_batch_score_report(batch_result: dict) -> str:
    """Format a batch score report from score_skills_batch() for terminal output.

    Args:
        batch_result: Output of score_skills_batch().

    Returns:
        Multi-line formatted string with per-skill breakdown and warnings.
    """
    target = batch_result.get("target", "?")
    count = batch_result.get("skill_count", 0)
    avg = batch_result.get("average_score", 0)
    min_s = batch_result.get("min_score", 0)
    max_s = batch_result.get("max_score", 0)
    low_quality = batch_result.get("low_quality", [])
    scores = batch_result.get("scores", [])

    if not scores:
        return f"Skill Translation Quality — {target}: no skills."

    lines: list[str] = [
        f"Skill Translation Quality — {target}",
        "=" * 50,
        f"  Skills scored:   {count}",
        f"  Average score:   {avg}/100",
        f"  Score range:     {min_s} – {max_s}",
        "",
    ]

    if low_quality:
        lines.append(f"  LOW QUALITY ({len(low_quality)} skill(s) need review):")
        for d in sorted(low_quality, key=lambda x: x["score"]):
            name = d.get("skill_name", "?")
            score = d["score"]
            grade = d.get("grade", "?")
            notes = d.get("notes", [])
            lines.append(f"    {score:3d}/100  [{grade}]  {name}")
            for note in notes[:2]:
                lines.append(f"             {note}")
        lines.append("")

    lines.append("  All skills:")
    for d in sorted(scores, key=lambda x: -x["score"]):
        name = d.get("skill_name", "?")
        score = d["score"]
        grade = d.get("grade", "?")
        indicator = "✓" if score >= 70 else ("~" if score >= 50 else "✗")
        lines.append(f"    {indicator} {score:3d}/100  [{grade}]  {name}")

    return "\n".join(lines)


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


# ---------------------------------------------------------------------------
# AI-Powered Rule Translation (item 4)
# ---------------------------------------------------------------------------

# Rules with no structural equivalent in the target harness need semantic
# rewriting rather than literal text copying or silently being dropped.
# This function calls the Anthropic Claude API to produce an equivalent
# rule rewrite in the target harness's idiom.

_AI_TRANSLATION_SYSTEM_PROMPT = """You are an expert in AI coding assistant configuration.
Your task is to translate a rule or instruction written for Claude Code (claude.ai)
into a semantically equivalent version suitable for {target_harness}.

Key constraints:
- Preserve the intent and semantics of the original rule exactly
- Rewrite any Claude Code-specific syntax or tool references into the target's idiom
- If the target has no equivalent concept, produce a plain-text instruction that
  guides the AI model to approximate the behavior manually
- Do not add commentary or explanation — output only the translated rule text
- Keep the same heading level and markdown structure where possible
- Target harness: {target_harness}

Target harness characteristics:
{target_characteristics}"""

_TARGET_CHARACTERISTICS: dict[str, str] = {
    "codex": "OpenAI Codex CLI. Uses AGENTS.md for rules. No tool-call XML. Plain markdown instructions only.",
    "gemini": "Google Gemini CLI. Uses GEMINI.md. No Claude-specific tool names. Plain markdown instructions.",
    "opencode": "OpenCode CLI. Uses opencode.json + markdown rule files. No Claude-specific constructs.",
    "cursor": "Cursor IDE AI. Uses .cursor/rules/*.mdc files with YAML frontmatter. No Claude tool names.",
    "aider": "Aider (command-line AI). Uses CONVENTIONS.md. Plain text instructions, no frontmatter.",
    "windsurf": "Windsurf IDE AI. Uses .windsurfrules. Plain markdown, no Claude-specific tool names.",
    "cline": "Cline VS Code AI. Uses .clinerules. Plain markdown instructions.",
}


def ai_translate_rule(
    rule_content: str,
    target_name: str,
    api_key: str | None = None,
    model: str = "claude-haiku-4-5-20251001",
    timeout: float = 15.0,
) -> str | None:
    """Use Claude API to semantically translate a rule to a target harness.

    Falls back to None (caller should use regular translation) if:
    - anthropic package is not installed
    - API key is not available
    - The API call fails

    Args:
        rule_content: Original rule text (markdown, possibly with frontmatter).
        target_name: Target harness name (codex, gemini, etc.)
        api_key: Anthropic API key. Reads ANTHROPIC_API_KEY env var if not provided.
        model: Claude model ID to use for translation.
        timeout: HTTP request timeout in seconds.

    Returns:
        Translated rule content string, or None if unavailable/failed.
    """
    import os

    resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not resolved_key:
        return None

    characteristics = _TARGET_CHARACTERISTICS.get(
        target_name,
        f"{target_name} AI coding assistant. No Claude Code-specific constructs.",
    )

    system = _AI_TRANSLATION_SYSTEM_PROMPT.format(
        target_harness=target_name,
        target_characteristics=characteristics,
    )

    user_message = (
        f"Translate the following Claude Code rule for {target_name}:\n\n"
        f"```\n{rule_content}\n```\n\n"
        f"Output only the translated rule text, no explanation."
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=resolved_key)
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        translated = response.content[0].text.strip()
        # Strip wrapping ``` if the model added code fences around the result
        if translated.startswith("```") and translated.endswith("```"):
            inner = translated[3:]
            first_newline = inner.find("\n")
            if first_newline != -1:
                translated = inner[first_newline + 1:-3].strip()
        return translated
    except ImportError:
        pass  # anthropic not installed
    except Exception:
        pass  # API error — fall back to regex translation

    return None


def translate_rule_with_ai_fallback(
    content: str,
    target_name: str,
    api_key: str | None = None,
    use_ai: bool = True,
) -> tuple[str, bool]:
    """Translate rule content, using AI for semantically complex rules.

    For rules that still contain Claude Code-specific constructs after
    regex translation, attempts an AI-powered semantic rewrite via the
    Claude API. Falls back to regex translation if AI is unavailable.

    Args:
        content: Raw rule content.
        target_name: Target harness name.
        api_key: Optional Anthropic API key.
        use_ai: If True, attempt AI translation for complex rules.

    Returns:
        Tuple of (translated_content, used_ai) where used_ai indicates
        whether the AI path was actually used.
    """
    # First pass: regex-based translation
    regex_translated = translate_skill_content(content, target_name)

    # Check if CC-specific constructs remain after regex translation
    _CC_TOOL_PATTERN = re.compile(
        r"\b(" + "|".join(re.escape(t) for t in _CC_TOOLS) + r")\b",
        re.IGNORECASE,
    )
    _HOOK_PATTERN = re.compile(
        r"\b(PreToolUse|PostToolUse|UserPromptSubmit|SessionStart|SessionEnd|mcp__\w+__\w+)\b"
    )

    has_cc_constructs = bool(
        _CC_TOOL_PATTERN.search(regex_translated)
        or _HOOK_PATTERN.search(regex_translated)
        or "$CLAUDE_PLUGIN_ROOT" in regex_translated
    )

    if not (use_ai and has_cc_constructs):
        return regex_translated, False

    # Attempt AI-powered translation
    ai_result = ai_translate_rule(regex_translated, target_name, api_key=api_key)
    if ai_result:
        return ai_result, True

    return regex_translated, False


# ---------------------------------------------------------------------------
# Translation Annotation Comments (Item 29)
# ---------------------------------------------------------------------------
#
# When syncing skills and agents to target harnesses, optionally inject
# comments explaining *what* was translated and *why*, so users who open
# AGENTS.md or Codex config directly understand why it looks the way it does.
# This turns the synced output from a black box into self-documenting config.


def generate_translation_annotation(
    original: str,
    translated: str,
    skill_name: str,
    target_name: str,
) -> str:
    """Generate a comment block documenting the translation decisions applied.

    The annotation is designed to be prepended to the translated skill content
    in a target harness file. It explains:
    - The source skill name
    - What CC-specific constructs were rewritten
    - Any limitations (capabilities dropped entirely)

    Args:
        original: Raw source skill content (from Claude Code).
        translated: Content after translate_skill_content().
        skill_name: Name of the skill (for the comment header).
        target_name: Target harness name.

    Returns:
        A multi-line comment string ready to be prepended to translated content.
        Returns empty string if there is nothing worth documenting (clean copy).
    """
    changes: list[str] = []

    # Detect tool reference rewrites
    orig_tool_refs = _INLINE_TOOL_RE.findall(original)
    trans_tool_refs = _INLINE_TOOL_RE.findall(translated)
    dropped_tools = len(orig_tool_refs) - len(trans_tool_refs)
    if dropped_tools > 0:
        tool_names = list(dict.fromkeys(m[1] for m in orig_tool_refs))  # unique, ordered
        changes.append(
            f"Rewrote {dropped_tools} Claude Code tool reference(s): "
            + ", ".join(tool_names[:5])
            + (" ..." if len(tool_names) > 5 else "")
        )

    # Detect XML tool-call block removal
    xml_orig = _TOOL_CALL_BLOCK_RE.findall(original)
    if xml_orig:
        changes.append(f"Removed {len(xml_orig)} XML tool-call block(s) (CC-only syntax)")

    # Detect frontmatter key stripping
    fm_orig = _count_frontmatter_keys(original)
    fm_trans = _count_frontmatter_keys(translated)
    if fm_orig > fm_trans:
        changes.append(
            f"Stripped {fm_orig - fm_trans} CC-specific frontmatter key(s) "
            f"(e.g. 'allowed-tools')"
        )

    # Detect MCP references still present in translated content
    mcp_pattern = re.compile(r"mcp__\w+__\w+")
    if mcp_pattern.search(translated):
        changes.append(
            "MCP tool references remain — ensure these servers are configured "
            f"in {target_name}"
        )

    # If nothing changed, no annotation is needed
    if not changes:
        return ""

    lines = [
        f"<!-- Translated from Claude Code skill: {skill_name}",
        f"     Target: {target_name}",
        "     Translation decisions:",
    ]
    for change in changes:
        lines.append(f"     - {change}")
    lines.append("-->")

    return "\n".join(lines) + "\n"


def annotate_translated_content(
    original: str,
    translated: str,
    skill_name: str,
    target_name: str,
) -> str:
    """Return translated content with a translation annotation comment prepended.

    Convenience wrapper: if no annotation is needed (clean copy), returns
    translated content unchanged. Otherwise, prepends the annotation block.

    Args:
        original: Raw source content.
        translated: Content after translation.
        skill_name: Skill/agent name for the annotation header.
        target_name: Target harness name.

    Returns:
        Annotated content string.
    """
    annotation = generate_translation_annotation(
        original, translated, skill_name, target_name
    )
    if not annotation:
        return translated
    return annotation + "\n" + translated


# ---------------------------------------------------------------------------
# Skill translation quality report (item 13)
# ---------------------------------------------------------------------------

def format_skill_translation_report(
    skills_dir: Path,
    targets: list[str] | None = None,
) -> str:
    """Report translation quality for all skills in a directory across targets.

    Scans *skills_dir* for ``.md`` skill files, translates each for every
    requested target, and returns a formatted summary table with per-skill
    grades and an overall fidelity assessment.

    Helps users understand which skills translate well and which need
    harness-portable rewrites before syncing (item 13: Skill Translation
    Quality Report).

    Args:
        skills_dir: Path to the skills directory (e.g. ``~/.claude/skills/``).
        targets: Target harness names to report on. Defaults to
                 ``["codex", "gemini", "cursor", "aider"]``.

    Returns:
        Formatted multi-line report string.
    """
    if targets is None:
        targets = ["codex", "gemini", "cursor", "aider"]

    # Collect skill files (top-level .md or SKILL.md inside sub-dirs)
    skill_paths: list[tuple[str, Path]] = []
    if skills_dir.is_dir():
        for item in sorted(skills_dir.iterdir()):
            if item.is_file() and item.suffix == ".md":
                skill_paths.append((item.stem, item))
            elif item.is_dir():
                candidate = item / "SKILL.md"
                if candidate.is_file():
                    skill_paths.append((item.name, candidate))

    if not skill_paths:
        return f"Skill Translation Report: No skills found in {skills_dir}"

    # Grade symbols
    grade_sym = {"excellent": "A", "good": "B", "fair": "C", "poor": "D"}

    # Header
    col_skill = max(14, max(len(name) for name, _ in skill_paths) + 2)
    col_target = 8
    header_targets = "".join(f"{t:^{col_target}}" for t in targets)
    lines = [
        "Skill Translation Quality Report",
        "=" * (col_skill + col_target * len(targets) + 4),
        "",
        f"  {'Skill':<{col_skill}}{header_targets}",
        "  " + "-" * (col_skill + col_target * len(targets)),
    ]

    # Per-skill rows
    skill_scores: list[dict] = []
    for skill_name, skill_path in skill_paths:
        row = f"  {skill_name:<{col_skill}}"
        scores_for_skill: list[int] = []
        for target in targets:
            result = score_skill_file(skill_path, target)
            grade = grade_sym.get(result.get("grade", "poor"), "D")
            score = result.get("score", 0)
            scores_for_skill.append(score)
            row += f"{grade}({score:>3})".center(col_target)
        lines.append(row)
        skill_scores.append({
            "name": skill_name,
            "path": str(skill_path),
            "avg_score": sum(scores_for_skill) / max(1, len(scores_for_skill)),
        })

    lines.append("")
    lines.append("  Grade: A=excellent(90+)  B=good(70+)  C=fair(50+)  D=poor(<50)")
    lines.append("")

    # Highlight skills that need attention
    poor_skills = [s for s in skill_scores if s["avg_score"] < 50]
    if poor_skills:
        lines.append("Skills needing attention (avg score < 50):")
        for s in poor_skills:
            lines.append(f"  - {s['name']}  (avg {s['avg_score']:.0f}/100) — "
                         f"consider rewriting for harness portability")
        lines.append("")

    overall_avg = sum(s["avg_score"] for s in skill_scores) / max(1, len(skill_scores))
    lines.append(f"Overall translation fidelity: {overall_avg:.0f}/100  "
                 f"({len(skill_paths)} skill(s) across {len(targets)} target(s))")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Item 4 — Skill Translation Quality Improvement Hints
# ---------------------------------------------------------------------------
#
# After translation, annotate the output with inline comments explaining
# what was approximated and HOW to manually improve it. Unlike the basic
# annotation which just documents what changed, improvement hints give
# actionable rewrite suggestions.

# Target-specific skill idioms: what the harness natively supports
_TARGET_NATIVE_IDIOMS: dict[str, list[str]] = {
    "gemini": [
        "Use tool_code blocks for shell commands (Gemini natively executes these)",
        "Replace 'use the Bash tool' with direct shell command examples",
        "Gemini supports structured output — prefer JSON response schemas over prose",
    ],
    "codex": [
        "Use markdown code fences with language hints (Codex parses these for diffs)",
        "Replace skill invocations with plain instructions (no slash commands in Codex)",
        "Add explicit 'do not ask for confirmation' instructions if needed",
    ],
    "cursor": [
        "Cursor .mdc rules use alwaysApply + globs — add file pattern metadata if applicable",
        "Replace tool references with plain prose (Cursor reads these as editor context)",
        "Use imperative voice ('Create', 'Update') — Cursor responds well to directives",
    ],
    "aider": [
        "Aider reads CONVENTIONS.md sequentially — put most important rules first",
        "Add explicit commit message format instructions (Aider auto-commits)",
        "Replace skill invocations with inline instructions (Aider has no slash commands)",
    ],
    "windsurf": [
        "Windsurf memory files are limited in size — keep skill content concise (<500 words)",
        "Use declarative style ('Files should...') over imperative ('You must...')",
        "Windsurf has no tool system — replace all tool references with behavior descriptions",
    ],
}


def generate_improvement_hints(
    original: str,
    translated: str,
    skill_name: str,
    target_name: str,
) -> list[str]:
    """Generate actionable improvement hints for a translated skill file.

    Analyzes the gap between original and translated content and returns
    concrete suggestions for how to manually improve the translation for
    the specific target harness.

    Args:
        original: Raw source skill content (from Claude Code).
        translated: Content after translate_skill_content().
        skill_name: Name of the skill (for context).
        target_name: Target harness name.

    Returns:
        List of hint strings (may be empty if no improvements suggested).
    """
    hints: list[str] = []

    # Check for remaining tool references in translated content
    remaining_tools = _INLINE_TOOL_RE.findall(translated)
    if remaining_tools:
        tool_names = list(dict.fromkeys(m[1] for m in remaining_tools))
        hints.append(
            f"Replace remaining tool references ({', '.join(tool_names[:3])}) "
            f"with {target_name}-native equivalents or plain prose descriptions"
        )

    # Check for MCP references that won't work
    mcp_refs = re.findall(r"mcp__(\w+)__(\w+)", translated)
    if mcp_refs:
        server_names = list(dict.fromkeys(s for s, _ in mcp_refs))
        hints.append(
            f"MCP tool calls ({', '.join(server_names)}) may not work in {target_name} "
            "— replace with equivalent instructions or verify MCP config is synced"
        )

    # Check for skill invocations (slash command references)
    skill_invoke_re = re.compile(r"/[a-z][\w-]+\b")
    slash_refs = skill_invoke_re.findall(translated)
    if slash_refs:
        unique_refs = list(dict.fromkeys(slash_refs[:3]))
        hints.append(
            f"Slash command references ({', '.join(unique_refs)}) are Claude Code-specific "
            f"— expand their logic inline or remove from {target_name} variant"
        )

    # Add target-native idiom suggestions when content is non-trivial
    if len(original) > 200:
        native_idioms = _TARGET_NATIVE_IDIOMS.get(target_name, [])
        hints.extend(native_idioms[:2])  # Add up to 2 idiom hints

    # Check for XML tool-call blocks that may have been awkwardly removed
    if _TOOL_CALL_BLOCK_RE.search(original) and not _TOOL_CALL_BLOCK_RE.search(translated):
        hints.append(
            "XML tool-call blocks were removed — verify surrounding prose still makes "
            "sense without the structured tool invocation context"
        )

    return hints


def annotate_with_improvement_hints(
    original: str,
    translated: str,
    skill_name: str,
    target_name: str,
) -> str:
    """Return translated content with improvement hints appended as a comment block.

    Unlike annotate_translated_content() which documents what changed,
    this function adds forward-looking improvement hints explaining how
    to manually make the translation better.

    Args:
        original: Raw source content.
        translated: Content after translation.
        skill_name: Skill/agent name.
        target_name: Target harness name.

    Returns:
        Translated content with improvement hints comment appended, or
        the original translated content if no hints are generated.
    """
    hints = generate_improvement_hints(original, translated, skill_name, target_name)
    if not hints:
        return translated

    hint_lines = [
        "",
        f"<!-- HarnessSync: Manual improvement hints for {target_name}",
        f"     Skill: {skill_name}",
        "     The following changes would improve this translation:",
    ]
    for i, hint in enumerate(hints, 1):
        hint_lines.append(f"     {i}. {hint}")
    hint_lines.append("-->")

    return translated + "\n".join(hint_lines) + "\n"


# ---------------------------------------------------------------------------
# Item 10 — Harness-Specific Skill Variants (fallback versions)
# ---------------------------------------------------------------------------
#
# A skill can define harness-specific fallback variants by placing additional
# files alongside SKILL.md in the skill directory:
#
#     ~/.claude/skills/my-skill/
#         SKILL.md               ← canonical Claude Code version
#         SKILL.codex.md         ← fallback for Codex
#         SKILL.gemini.md        ← fallback for Gemini
#         SKILL.fallback.md      ← fallback for ALL other harnesses
#
# If a harness-specific variant file exists it is used verbatim (no
# translation applied). If only the generic SKILL.fallback.md exists it is
# used for any target without a dedicated variant. Otherwise the normal
# translate_skill_content() pipeline runs.
#
# This mirrors "responsive design but for AI config" — the author
# explicitly controls the degraded experience instead of accepting silent
# auto-translation.

_VARIANT_CANDIDATES = [
    # Most specific → least specific
    "SKILL.{target}.md",
    "SKILL.fallback.md",
]


def get_skill_variant_path(skill_dir: Path, target: str) -> Path | None:
    """Return the path to a harness-specific skill variant file, if one exists.

    Checks for ``SKILL.<target>.md`` first, then the generic
    ``SKILL.fallback.md``. Returns None if neither variant is present,
    indicating that the normal translation pipeline should be used.

    Args:
        skill_dir: Directory containing the skill (e.g. ~/.claude/skills/my-skill).
        target: Target harness name (e.g. "codex", "gemini").

    Returns:
        Path to the variant file, or None if no variant is defined.
    """
    for pattern in _VARIANT_CANDIDATES:
        candidate = skill_dir / pattern.format(target=target)
        if candidate.is_file():
            return candidate
    return None


def translate_skill_with_variant(
    skill_dir: Path,
    target: str,
    skill_file: str = "SKILL.md",
) -> tuple[str, str]:
    """Translate a skill for a target harness, using fallback variants when available.

    Resolution order:
    1. Harness-specific variant: ``SKILL.<target>.md`` → returned verbatim.
    2. Generic fallback variant: ``SKILL.fallback.md`` → returned verbatim.
    3. Canonical skill file: ``SKILL.md`` → passed through translate_skill_content().

    Args:
        skill_dir: Skill directory (e.g. ~/.claude/skills/my-skill/).
        target: Target harness name.
        skill_file: Name of the canonical skill file (default: SKILL.md).

    Returns:
        Tuple of (content, variant_used) where:
          - content: Translated/variant content string (empty if skill unreadable).
          - variant_used: One of "harness-specific", "generic-fallback", or "translated".
    """
    variant_path = get_skill_variant_path(skill_dir, target)
    if variant_path is not None:
        try:
            content = variant_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        variant_type = (
            "harness-specific"
            if variant_path.name != "SKILL.fallback.md"
            else "generic-fallback"
        )
        return content, variant_type

    # Fall through to normal translation
    canonical = skill_dir / skill_file
    content = translate_skill_file(canonical, target)
    return content, "translated"


def list_skill_variants(skill_dir: Path) -> dict[str, str]:
    """List all harness-specific variant files present in a skill directory.

    Args:
        skill_dir: Skill root directory (e.g. ~/.claude/skills/my-skill/).

    Returns:
        Dict mapping target name (or "fallback") to the variant filename.
        E.g. {"codex": "SKILL.codex.md", "fallback": "SKILL.fallback.md"}
    """
    variants: dict[str, str] = {}
    if not skill_dir.is_dir():
        return variants
    for f in skill_dir.iterdir():
        if not f.is_file():
            continue
        name = f.name
        if name == "SKILL.fallback.md":
            variants["fallback"] = name
        elif name.startswith("SKILL.") and name.endswith(".md"):
            target = name[len("SKILL."):-len(".md")]
            if target and target not in ("fallback",):
                variants[target] = name
    return variants


def format_variant_summary(skill_dir: Path) -> str:
    """Format a human-readable summary of variant coverage for a skill.

    Args:
        skill_dir: Skill root directory.

    Returns:
        Multi-line summary string.
    """
    variants = list_skill_variants(skill_dir)
    skill_name = skill_dir.name
    lines = [f"Skill variants for '{skill_name}':"]
    if not variants:
        lines.append("  No harness-specific variants defined.")
        lines.append("  All targets use auto-translation from SKILL.md.")
        lines.append(
            "  Tip: Add SKILL.fallback.md to control the experience in "
            "harnesses that translate poorly."
        )
    else:
        for key, filename in sorted(variants.items()):
            label = "all other harnesses" if key == "fallback" else key
            lines.append(f"  {label}: {filename} (verbatim — no auto-translation)")
        has_fallback = "fallback" in variants
        if not has_fallback:
            lines.append("")
            lines.append(
                "  Tip: Add SKILL.fallback.md to catch harnesses without a dedicated variant."
            )
    return "\n".join(lines)
