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
from dataclasses import dataclass, field
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
