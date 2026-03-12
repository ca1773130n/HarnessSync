from __future__ import annotations

"""LLM-Assisted Rule Translation (item 14).

For rules that can't be mechanically translated (Claude-specific syntax, tool
references, agent orchestration), uses Claude itself to rewrite them into the
closest equivalent for the target harness. Shows the translation with a
'best effort' label so users understand the output is approximate.

This complements the regex-based skill_translator.py:
- skill_translator.py: Fast, offline, deterministic — handles known patterns.
- llm_rule_translator.py: Slow, online, AI-powered — handles novel/complex rules.

The module is intentionally import-safe. If the anthropic package is not
installed, or no API key is available, all methods degrade gracefully by
returning the original content with a warning annotation.

Usage::

    translator = LLMRuleTranslator(target="gemini")
    result = translator.translate(rule_text)
    if result.used_llm:
        print(f"[best effort] {result.translated}")

Configuration:
    ANTHROPIC_API_KEY env var must be set for LLM translation.
    HARNESSSYNC_LLM_TRANSLATE=0 env var disables LLM translation entirely.
"""

import os
import re
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class TranslationResult:
    """Result of translating a single rule for a target harness."""

    original: str
    translated: str
    target: str
    used_llm: bool = False
    best_effort: bool = False
    skipped: bool = False  # True if content needed no translation
    annotation: str = ""   # Machine-readable translation notes
    error: str = ""        # Non-empty if translation failed

    def format(self, include_annotation: bool = True) -> str:
        """Return formatted translated content with optional annotation header."""
        if self.skipped:
            return self.translated
        lines = []
        if self.best_effort and include_annotation:
            method = "LLM (best effort)" if self.used_llm else "regex (best effort)"
            lines.append(
                f"<!-- hs:translated target='{self.target}' method='{method}' -->"
            )
            if self.annotation:
                lines.append(f"<!-- hs:notes {self.annotation} -->")
        lines.append(self.translated)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Target capability descriptions for LLM prompts
# ---------------------------------------------------------------------------

_TARGET_DESCRIPTIONS: dict[str, str] = {
    "codex": (
        "OpenAI Codex CLI. Uses AGENTS.md for instructions. "
        "Has no hooks, no skills, no tool-call XML blocks. "
        "Supports plain Markdown rules only. "
        "Tool references like 'use the Read tool' must be rewritten as generic actions."
    ),
    "gemini": (
        "Google Gemini CLI. Uses GEMINI.md for instructions. "
        "Supports Markdown rules, no agent orchestration, no tool XML. "
        "References to Claude-specific capabilities must be generalised."
    ),
    "opencode": (
        "OpenCode AI CLI. Uses AGENTS.md for instructions. "
        "Similar to Codex but allows richer Markdown. "
        "No Claude-specific tools or hooks."
    ),
    "cursor": (
        "Cursor IDE AI assistant. Uses .cursor/rules/*.mdc files. "
        "Supports Markdown rules with optional YAML frontmatter. "
        "No Claude-specific tools, skills, or hooks."
    ),
    "aider": (
        "Aider CLI coding assistant. Uses CONVENTIONS.md for instructions. "
        "Plain Markdown only. No tool-call syntax."
    ),
    "windsurf": (
        "Windsurf (Codeium) IDE assistant. Uses .windsurfrules. "
        "Markdown rules, no agent orchestration, no tool-call XML."
    ),
}

_FALLBACK_TARGET_DESCRIPTION = (
    "A generic AI coding assistant. Supports plain Markdown rules only. "
    "No Claude Code-specific features (hooks, skills, tool-call XML, agents)."
)


# ---------------------------------------------------------------------------
# Patterns that indicate a rule needs LLM translation
# ---------------------------------------------------------------------------

_COMPLEX_PATTERNS = [
    re.compile(r"<tool_call>", re.IGNORECASE),
    re.compile(r"\bAgent\s+tool\b", re.IGNORECASE),
    re.compile(r"\bTodoWrite\b|\bTodoRead\b", re.IGNORECASE),
    re.compile(r"<!-- harness:.*?-->", re.IGNORECASE),
    re.compile(r"\bSubagent\b", re.IGNORECASE),
    re.compile(r"\bEnterPlanMode\b|\bExitPlanMode\b", re.IGNORECASE),
    re.compile(r"\bNotebookEdit\b|\bNotebookRead\b", re.IGNORECASE),
    re.compile(r"\bMCP server\b.*\btool\b", re.IGNORECASE),
]


def _needs_llm_translation(content: str) -> bool:
    """Return True if content contains patterns that regex can't handle well."""
    return any(p.search(content) for p in _COMPLEX_PATTERNS)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LLMRuleTranslator:
    """Translates Claude Code rules to target-harness equivalents using Claude.

    Falls back to the original content (with a warning annotation) when:
    - The anthropic package is not installed.
    - No API key is configured.
    - LLM translation is disabled via HARNESSSYNC_LLM_TRANSLATE=0.
    - A network or API error occurs.

    Args:
        target: Target harness name (e.g. "codex", "gemini").
        model: Claude model to use (default: claude-haiku-4-5-20251001 for cost).
        max_tokens: Max response tokens (default: 1024).
        enabled: Override enabled check (default: auto-detect from env).
    """

    DEFAULT_MODEL = "claude-haiku-4-5-20251001"
    DEFAULT_MAX_TOKENS = 1024

    def __init__(
        self,
        target: str = "codex",
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        enabled: bool | None = None,
    ) -> None:
        self.target = target
        self.model = model or self.DEFAULT_MODEL
        self.max_tokens = max_tokens

        # Determine if LLM translation is enabled
        if enabled is not None:
            self._enabled = enabled
        else:
            env_flag = os.environ.get("HARNESSSYNC_LLM_TRANSLATE", "1")
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            self._enabled = env_flag != "0" and bool(api_key)

        self._client: Any = None  # Lazy-initialized anthropic.Anthropic client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def translate(self, content: str, force_llm: bool = False) -> TranslationResult:
        """Translate a rule/skill block for the target harness.

        First applies cheap regex-based cleanup (via skill_translator). If the
        result still contains patterns that regex cannot handle (tool XML, agent
        orchestration), and LLM translation is enabled, sends a structured
        prompt to Claude for a best-effort rewrite.

        Args:
            content: Raw rule or skill content from CLAUDE.md / skills dir.
            force_llm: Skip regex step and go straight to LLM (useful for testing).

        Returns:
            TranslationResult with translated content and metadata.
        """
        if not content or not content.strip():
            return TranslationResult(
                original=content,
                translated=content,
                target=self.target,
                skipped=True,
            )

        # Step 1: Regex translation (fast, offline)
        regex_translated = content
        if not force_llm:
            try:
                from src.skill_translator import translate_skill_content
                regex_translated = translate_skill_content(content)
            except Exception:
                regex_translated = content

        # Step 2: Check if LLM translation is needed and available
        if not force_llm and not _needs_llm_translation(regex_translated):
            changed = regex_translated != content
            return TranslationResult(
                original=content,
                translated=regex_translated,
                target=self.target,
                skipped=not changed,
                best_effort=changed,
                used_llm=False,
            )

        if not self._enabled:
            # Return regex result with annotation that LLM was not available
            note = "LLM translation unavailable (no API key or disabled)"
            return TranslationResult(
                original=content,
                translated=regex_translated,
                target=self.target,
                best_effort=True,
                used_llm=False,
                annotation=note,
            )

        # Step 3: LLM translation
        return self._translate_with_llm(content, regex_translated)

    def translate_batch(
        self,
        items: list[dict],
        content_key: str = "content",
        force_llm: bool = False,
    ) -> list[TranslationResult]:
        """Translate a list of rule/skill dicts.

        Args:
            items: List of dicts containing the content to translate.
            content_key: Key in each dict holding the content string.
            force_llm: Bypass regex and go straight to LLM for all items.

        Returns:
            List of TranslationResult, one per input item.
        """
        return [
            self.translate(item.get(content_key, ""), force_llm=force_llm)
            for item in items
        ]

    def is_available(self) -> bool:
        """Return True if LLM translation is enabled and the client can be init'd."""
        if not self._enabled:
            return False
        try:
            self._get_client()
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> Any:
        """Lazily initialize and return the Anthropic client.

        Raises:
            ImportError: If the anthropic package is not installed.
            ValueError: If ANTHROPIC_API_KEY is not set.
        """
        if self._client is not None:
            return self._client

        try:
            import anthropic  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "LLM translation requires 'anthropic' package. "
                "Install it with: pip install anthropic"
            ) from exc

        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Set it to enable LLM-assisted rule translation."
            )

        self._client = anthropic.Anthropic(api_key=api_key)
        return self._client

    def _build_prompt(self, content: str) -> str:
        """Build the system prompt for rule translation."""
        target_desc = _TARGET_DESCRIPTIONS.get(self.target, _FALLBACK_TARGET_DESCRIPTION)
        return (
            f"You are a configuration translator for AI coding assistant tools.\n\n"
            f"Target harness: {self.target}\n"
            f"Target description: {target_desc}\n\n"
            f"Translate the following Claude Code rule/instruction into the best possible "
            f"equivalent for the target harness. Rules:\n"
            f"1. Preserve the intent and behavior guidance as closely as possible.\n"
            f"2. Remove Claude Code-specific syntax (tool XML blocks, hook references, "
            f"   skill invocations, agent orchestration).\n"
            f"3. Rewrite tool-specific instructions into generic equivalents.\n"
            f"4. Keep the output as Markdown text only.\n"
            f"5. If a concept has no equivalent, note it briefly in a <!-- NOTE: ... --> "
            f"   comment but still produce the best possible translation.\n"
            f"6. Output ONLY the translated rule text. No preamble, no explanation.\n\n"
            f"Rule to translate:\n---\n{content}\n---"
        )

    def _translate_with_llm(
        self,
        original: str,
        regex_translated: str,
    ) -> TranslationResult:
        """Send content to Claude for LLM-assisted translation.

        Args:
            original: Original content before any translation.
            regex_translated: Content after regex pre-processing (sent to LLM).

        Returns:
            TranslationResult with LLM output.
        """
        try:
            client = self._get_client()
        except (ImportError, ValueError) as exc:
            return TranslationResult(
                original=original,
                translated=regex_translated,
                target=self.target,
                best_effort=True,
                used_llm=False,
                error=str(exc),
            )

        prompt = self._build_prompt(regex_translated)
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            translated = response.content[0].text.strip()

            return TranslationResult(
                original=original,
                translated=translated,
                target=self.target,
                used_llm=True,
                best_effort=True,
                annotation=f"translated by {self.model}",
            )

        except Exception as exc:
            # Network error, rate limit, etc. — fall back to regex result
            return TranslationResult(
                original=original,
                translated=regex_translated,
                target=self.target,
                best_effort=True,
                used_llm=False,
                error=f"LLM call failed: {exc}",
            )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

def translate_rule_for_target(
    content: str,
    target: str,
    model: str | None = None,
) -> TranslationResult:
    """Translate a single rule for the given target harness.

    Convenience wrapper around LLMRuleTranslator for one-off translations.

    Args:
        content: Rule content to translate.
        target: Target harness name.
        model: Optional Claude model override.

    Returns:
        TranslationResult.
    """
    return LLMRuleTranslator(target=target, model=model).translate(content)


# ---------------------------------------------------------------------------
# Offline Phrasing Normalizer (item 21)
# ---------------------------------------------------------------------------
#
# Different harnesses respond differently to imperative vs declarative phrasing:
#   - Claude Code: imperative works best ("Always use named exports")
#   - Codex/AGENTS.md: slightly more declarative ("The agent should use named exports")
#   - Gemini: declarative/explanatory ("Named exports are preferred because …")
#   - Cursor .mdc: short imperative fragments ("Use named exports")
#   - Aider CONVENTIONS.md: imperative or descriptive ("Prefer named exports")
#
# This normalizer applies regex-based phrasing transforms without an LLM,
# making it fast, offline, and deterministic.  It complements LLMRuleTranslator:
#   - RulePhrasingNormalizer: instant, offline, style-only transforms
#   - LLMRuleTranslator:      slow, online, semantic + style transforms

# Harness phrasing style: imperative | declarative | fragment | descriptive
_HARNESS_PHRASING_STYLE: dict[str, str] = {
    "codex":    "declarative",
    "gemini":   "declarative",
    "cursor":   "fragment",
    "aider":    "imperative",
    "opencode": "imperative",
    "windsurf": "imperative",
}

# Sentence-level transforms: (pattern, imperative_repl, declarative_repl, fragment_repl)
# Each row is a rule transform.  We try each pattern against the full sentence.
# Patterns are case-insensitive and applied to each sentence independently.
_PHRASING_TRANSFORMS: list[tuple[re.Pattern, str, str, str]] = [
    # "Always X" → "The assistant should X" / "Always X" / "X"
    (
        re.compile(r"^Always\s+(.+)$", re.IGNORECASE),
        r"Always \1",
        r"The assistant should always \1",
        r"\1",
    ),
    # "Never X" → "The assistant must never X" / "Never X" / "avoid X"
    (
        re.compile(r"^Never\s+(.+)$", re.IGNORECASE),
        r"Never \1",
        r"The assistant must never \1",
        r"avoid \1",
    ),
    # "Prefer X" → "The assistant prefers X" / "prefer X" / "X preferred"
    (
        re.compile(r"^Prefer\s+(.+)$", re.IGNORECASE),
        r"Prefer \1",
        r"The assistant prefers \1",
        r"\1 preferred",
    ),
    # "Use X" → "The assistant uses X" / "use X" / "X"
    (
        re.compile(r"^Use\s+(.+)$", re.IGNORECASE),
        r"Use \1",
        r"The assistant uses \1",
        r"\1",
    ),
    # "Do not X" → "The assistant does not X" / "do not X" / "no X"
    (
        re.compile(r"^Do not\s+(.+)$", re.IGNORECASE),
        r"Do not \1",
        r"The assistant does not \1",
        r"no \1",
    ),
    # "Avoid X" → "The assistant avoids X" / "avoid X" / "no X"
    (
        re.compile(r"^Avoid\s+(.+)$", re.IGNORECASE),
        r"Avoid \1",
        r"The assistant avoids \1",
        r"no \1",
    ),
    # "Ensure X" → "The assistant ensures X" / "ensure X" / "X"
    (
        re.compile(r"^Ensure\s+(.+)$", re.IGNORECASE),
        r"Ensure \1",
        r"The assistant ensures \1",
        r"\1",
    ),
    # "Make sure X" → "The assistant should make sure X" / "make sure X" / "X"
    (
        re.compile(r"^Make sure\s+(.+)$", re.IGNORECASE),
        r"Make sure \1",
        r"The assistant should make sure \1",
        r"\1",
    ),
]


def _transform_sentence(sentence: str, style: str) -> str:
    """Apply one phrasing transform to a single sentence.

    Args:
        sentence: One rule sentence (no leading/trailing whitespace).
        style: Target phrasing style: "imperative" | "declarative" | "fragment".

    Returns:
        Transformed sentence, or original if no pattern matches.
    """
    for pattern, imp_repl, dec_repl, frag_repl in _PHRASING_TRANSFORMS:
        if pattern.match(sentence):
            if style == "declarative":
                result = pattern.sub(dec_repl, sentence, count=1)
            elif style == "fragment":
                result = pattern.sub(frag_repl, sentence, count=1)
            else:  # imperative (default)
                result = pattern.sub(imp_repl, sentence, count=1)
            # Capitalise first letter
            return result[:1].upper() + result[1:] if result else sentence
    return sentence


class RulePhrasingNormalizer:
    """Offline phrasing normalizer for CLAUDE.md rules.

    Transforms rule sentences to match each harness's expected phrasing style
    (imperative / declarative / fragment) without requiring an LLM call.

    This normalizer works at the sentence level within each rule block.
    It is fast enough to run on every sync without noticeable delay.

    Usage::

        normalizer = RulePhrasingNormalizer()
        normalized = normalizer.normalize("Always use named exports.", "gemini")
        # → "The assistant should always use named exports."

        block = normalizer.normalize_block(rule_text, "cursor")
        # → sentence-by-sentence fragment style

    """

    def normalize(self, sentence: str, target: str) -> str:
        """Normalize a single rule sentence for the target harness.

        Args:
            sentence: One rule sentence (may have trailing punctuation).
            target: Harness name (e.g. "gemini", "cursor").

        Returns:
            Phrasing-adjusted sentence.
        """
        style = _HARNESS_PHRASING_STYLE.get(target, "imperative")
        stripped = sentence.strip().rstrip(".")
        transformed = _transform_sentence(stripped, style)
        # Re-attach period if original had one and result doesn't
        if sentence.rstrip().endswith(".") and not transformed.endswith("."):
            transformed += "."
        return transformed

    def normalize_block(self, rule_text: str, target: str) -> str:
        """Normalize all sentences in a rule block for the target harness.

        Splits on sentence boundaries (. at line end or before uppercase),
        transforms each sentence, then reassembles preserving blank lines
        and non-sentence lines (e.g. code blocks, bullet lists).

        Args:
            rule_text: Multi-sentence rule block text.
            target: Target harness name.

        Returns:
            Phrasing-adjusted rule block.
        """
        lines = rule_text.splitlines(keepends=True)
        output: list[str] = []
        in_code_block = False

        for line in lines:
            stripped = line.strip()
            # Skip code blocks
            if stripped.startswith("```"):
                in_code_block = not in_code_block
                output.append(line)
                continue
            if in_code_block:
                output.append(line)
                continue
            # Skip bullet/numbered list markers — only transform the text after the marker
            list_match = re.match(r"^(\s*[-*+]|\s*\d+[.)]\s+)(.+)$", line)
            if list_match:
                prefix = list_match.group(1)
                text = list_match.group(2).rstrip("\n")
                normalized = self.normalize(text, target)
                eol = "\n" if line.endswith("\n") else ""
                output.append(f"{prefix}{normalized}{eol}")
                continue
            # Plain sentence lines
            if stripped and not stripped.startswith("#"):
                normalized = self.normalize(stripped, target)
                indent = len(line) - len(line.lstrip())
                eol = "\n" if line.endswith("\n") else ""
                output.append(" " * indent + normalized + eol)
            else:
                output.append(line)

        return "".join(output)

    def normalize_all_targets(self, rule_text: str) -> dict[str, str]:
        """Normalize a rule block for all known harnesses.

        Args:
            rule_text: Rule block text.

        Returns:
            Dict mapping harness name → normalized rule text.
        """
        return {t: self.normalize_block(rule_text, t) for t in _HARNESS_PHRASING_STYLE}


def normalize_rule_phrasing(rule_text: str, target: str) -> str:
    """Convenience function: normalize a rule block's phrasing for a target.

    Args:
        rule_text: Rule text to normalize.
        target: Target harness name.

    Returns:
        Phrasing-adjusted rule text.
    """
    return RulePhrasingNormalizer().normalize_block(rule_text, target)
