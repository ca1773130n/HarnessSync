from __future__ import annotations

"""Model Routing Hints Sync (item 23).

Reads per-task model preferences from Claude Code's settings and translates
them into equivalent config for each target harness that supports model
selection (Gemini CLI, OpenCode, Codex, Cursor, Aider).

Problem: Users configure 'use a fast model for linting, a powerful model for
architecture' in Claude Code but lose those preferences when switching to other
harnesses. This module syncs those routing hints across harnesses.

Source format (Claude Code ~/.claude/settings.json or project settings):
    {
        "model": "claude-opus-4-6",
        "modelRouting": {
            "code_generation": "claude-opus-4-6",
            "linting":         "claude-haiku-4-5",
            "docs":            "claude-sonnet-4-6"
        }
    }

Translation targets:
    gemini:   model field in settings.json  (best-match Gemini model)
    opencode: model field in opencode.json
    codex:    model field in config.toml
    aider:    --model flag in .aider.conf.yml
    cursor:   No per-task routing; exports a comment explaining preferences.

Usage::

    from src.model_routing import ModelRoutingAdapter

    adapter = ModelRoutingAdapter()
    hints = adapter.read_from_settings(settings_dict)
    translated = adapter.translate_for_target(hints, "gemini")
    print(translated)
"""

from dataclasses import dataclass, field


# ── Model equivalence map ────────────────────────────────────────────────

# Maps Claude model IDs to best-fit equivalents in other harnesses.
# Uses prefix matching: the longest matching prefix wins.
_CLAUDE_TO_GEMINI: list[tuple[str, str]] = [
    ("claude-opus",   "gemini-1.5-pro"),
    ("claude-sonnet", "gemini-1.5-flash"),
    ("claude-haiku",  "gemini-2.0-flash"),
]

_CLAUDE_TO_GPT: list[tuple[str, str]] = [
    ("claude-opus",   "gpt-4o"),
    ("claude-sonnet", "gpt-4o-mini"),
    ("claude-haiku",  "gpt-4o-mini"),
]

_CLAUDE_TO_AIDER: list[tuple[str, str]] = [
    ("claude-opus",   "claude/claude-opus-4-6"),
    ("claude-sonnet", "claude/claude-sonnet-4-6"),
    ("claude-haiku",  "claude/claude-haiku-4-5"),
]


def _best_match(model: str, mapping: list[tuple[str, str]], fallback: str) -> str:
    """Return the translated model name using longest prefix match."""
    model_lower = model.lower()
    for prefix, target_model in mapping:
        if model_lower.startswith(prefix):
            return target_model
    return fallback


# ── Task categories ──────────────────────────────────────────────────────

# Canonical task category names recognized in modelRouting config
TASK_CATEGORIES: list[str] = [
    "code_generation",
    "linting",
    "docs",
    "refactoring",
    "debugging",
    "testing",
    "architecture",
    "review",
    "chat",
    "default",
]


# ── Data types ───────────────────────────────────────────────────────────

@dataclass
class ModelRoutingHints:
    """Parsed model routing preferences from Claude Code settings."""

    default_model: str = ""
    task_routing: dict[str, str] = field(default_factory=dict)
    # task_routing: {task_category: model_id}

    @property
    def is_empty(self) -> bool:
        return not self.default_model and not self.task_routing


@dataclass
class TranslatedModelConfig:
    """Translated model config for a target harness."""

    target: str
    default_model: str
    task_routing: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    # notes: human-readable caveats about the translation

    def as_dict(self) -> dict:
        """Return a flat dict suitable for merging into target config."""
        result: dict = {}
        if self.default_model:
            result["model"] = self.default_model
        if self.task_routing:
            result["model_routing"] = self.task_routing
        return result

    def format(self) -> str:
        """Human-readable summary of translated config."""
        lines = [f"[{self.target}] Model routing:"]
        if self.default_model:
            lines.append(f"  default: {self.default_model}")
        for task, model in sorted(self.task_routing.items()):
            lines.append(f"  {task:<20} {model}")
        for note in self.notes:
            lines.append(f"  NOTE: {note}")
        return "\n".join(lines)


# ── Adapter ──────────────────────────────────────────────────────────────

class ModelRoutingAdapter:
    """Reads Claude Code model routing hints and translates to target harnesses.

    Supported targets: gemini, opencode, codex, aider, cursor.
    """

    def read_from_settings(self, settings: dict) -> ModelRoutingHints:
        """Parse model routing hints from a Claude Code settings dict.

        Reads ``model`` (default model) and ``modelRouting`` (per-task overrides).

        Args:
            settings: Parsed Claude Code settings.json content.

        Returns:
            ModelRoutingHints with default model and per-task routing.
        """
        hints = ModelRoutingHints()
        hints.default_model = settings.get("model", "")

        raw_routing = settings.get("modelRouting", {})
        if isinstance(raw_routing, dict):
            for task, model in raw_routing.items():
                if isinstance(model, str) and model:
                    # Normalize task keys to snake_case
                    task_key = task.lower().replace("-", "_").replace(" ", "_")
                    hints.task_routing[task_key] = model

        return hints

    def translate_for_target(
        self,
        hints: ModelRoutingHints,
        target: str,
    ) -> TranslatedModelConfig | None:
        """Translate routing hints to a specific target harness's format.

        Args:
            hints: Parsed routing hints from Claude Code settings.
            target: Target harness name (gemini, opencode, codex, aider, cursor).

        Returns:
            TranslatedModelConfig or None if target doesn't support model selection.
        """
        if hints.is_empty:
            return None

        target = target.lower()

        if target == "gemini":
            return self._translate_gemini(hints)
        elif target == "opencode":
            return self._translate_opencode(hints)
        elif target == "codex":
            return self._translate_codex(hints)
        elif target == "aider":
            return self._translate_aider(hints)
        elif target == "cursor":
            return self._translate_cursor(hints)
        else:
            return None  # Target doesn't support model routing

    def translate_all(self, hints: ModelRoutingHints) -> dict[str, TranslatedModelConfig]:
        """Translate to all supported targets.

        Returns:
            Dict mapping target name to translated config (only supported targets).
        """
        result: dict[str, TranslatedModelConfig] = {}
        for target in ("gemini", "opencode", "codex", "aider", "cursor"):
            translated = self.translate_for_target(hints, target)
            if translated:
                result[target] = translated
        return result

    # ── Target-specific translators ────────────────────────────────────────

    def _translate_gemini(self, hints: ModelRoutingHints) -> TranslatedModelConfig:
        default = _best_match(
            hints.default_model or "claude-opus",
            _CLAUDE_TO_GEMINI,
            "gemini-1.5-pro",
        )
        # Gemini CLI doesn't support per-task model routing; use most capable
        # among mentioned models as the single default
        task_models = list(hints.task_routing.values())
        all_models = ([hints.default_model] if hints.default_model else []) + task_models
        # Use the most capable (longest prefix match favoring opus)
        best_claude = self._most_capable(all_models)
        if best_claude:
            default = _best_match(best_claude, _CLAUDE_TO_GEMINI, default)

        notes = []
        if hints.task_routing:
            notes.append(
                "Gemini CLI does not support per-task model routing; "
                "using most capable model as default."
            )

        return TranslatedModelConfig(
            target="gemini",
            default_model=default,
            notes=notes,
        )

    def _translate_opencode(self, hints: ModelRoutingHints) -> TranslatedModelConfig:
        # OpenCode supports a model field; per-task routing is not standard.
        default = hints.default_model or "claude-sonnet-4-6"
        notes = []
        if hints.task_routing:
            notes.append("OpenCode does not support per-task model routing.")
        return TranslatedModelConfig(
            target="opencode",
            default_model=default,
            notes=notes,
        )

    def _translate_codex(self, hints: ModelRoutingHints) -> TranslatedModelConfig:
        # Codex uses OpenAI models; translate Claude → GPT equivalents.
        default = _best_match(
            hints.default_model or "claude-sonnet",
            _CLAUDE_TO_GPT,
            "gpt-4o",
        )
        task_routing: dict[str, str] = {}
        for task, model in hints.task_routing.items():
            task_routing[task] = _best_match(model, _CLAUDE_TO_GPT, "gpt-4o")

        notes = ["Codex uses OpenAI models; Claude models mapped to GPT equivalents."]
        return TranslatedModelConfig(
            target="codex",
            default_model=default,
            task_routing=task_routing,
            notes=notes,
        )

    def _translate_aider(self, hints: ModelRoutingHints) -> TranslatedModelConfig:
        # Aider uses model: field in .aider.conf.yml with provider prefix.
        default = _best_match(
            hints.default_model or "claude-sonnet",
            _CLAUDE_TO_AIDER,
            "claude/claude-sonnet-4-6",
        )
        notes = []
        if hints.task_routing:
            notes.append(
                "Aider does not support per-task model routing via config; "
                "default model applied."
            )
        return TranslatedModelConfig(
            target="aider",
            default_model=default,
            notes=notes,
        )

    def _translate_cursor(self, hints: ModelRoutingHints) -> TranslatedModelConfig:
        # Cursor doesn't support model routing via config; produce a comment.
        notes = [
            "Cursor model selection is per-session in the UI; "
            "config-based routing is not supported.",
        ]
        if hints.default_model:
            notes.append(
                f"Preferred model: {hints.default_model} "
                "(set manually in Cursor model picker)."
            )
        return TranslatedModelConfig(
            target="cursor",
            default_model="",  # Can't set programmatically
            notes=notes,
        )

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _most_capable(models: list[str]) -> str:
        """Return the most capable Claude model from a list (by tier)."""
        tiers = ["opus", "sonnet", "haiku"]
        for tier in tiers:
            for model in models:
                if tier in model.lower():
                    return model
        return models[0] if models else ""


def extract_routing_hints_from_settings_file(settings_path: "Path") -> ModelRoutingHints:
    """Convenience function: read and parse a Claude Code settings.json file.

    Args:
        settings_path: Path to settings.json (user or project scope).

    Returns:
        Parsed ModelRoutingHints.
    """
    import json
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    adapter = ModelRoutingAdapter()
    return adapter.read_from_settings(data)


# ---------------------------------------------------------------------------
# Model-Specific Instruction Tuning (item 28)
# ---------------------------------------------------------------------------

import re as _re


# Markers used inside CLAUDE.md rule text to embed model-specific variants.
# Format:
#   <!-- model:gemini-2.0-flash -->
#   <shorter variant of the rule>
#   <!-- /model:gemini-2.0-flash -->
_MODEL_BLOCK_RE = _re.compile(
    r"<!--\s*model:(?P<model>[^\s>]+)\s*-->(?P<content>.*?)<!--\s*/model:[^\s>]+\s*-->",
    _re.DOTALL | _re.IGNORECASE,
)

# Maps target harness → primary model identifier (used to select the right variant)
_HARNESS_PRIMARY_MODEL: dict[str, str] = {
    "gemini":   "gemini-2.0-flash",
    "codex":    "claude-sonnet-4-6",
    "opencode": "claude-sonnet-4-6",
    "cursor":   "claude-sonnet-4-6",
    "aider":    "gpt-4o",
    "windsurf": "claude-sonnet-4-6",
    "cline":    "claude-sonnet-4-6",
    "continue": "claude-sonnet-4-6",
    "zed":      "claude-sonnet-4-6",
    "neovim":   "claude-sonnet-4-6",
}


def extract_model_variant(rule_text: str, target: str) -> str:
    """Extract the model-specific variant of a rule for a given target harness.

    Scans ``rule_text`` for ``<!-- model:X --> ... <!-- /model:X -->`` blocks.
    If a block exists for the target harness's primary model, returns the
    block's content instead of the full rule text — giving that harness a
    tailored, often shorter instruction that better fits its capabilities.

    If no matching block is found, returns the original ``rule_text`` unchanged
    (with model blocks stripped so other harnesses don't see the markup).

    Args:
        rule_text: Rule content potentially containing model-specific blocks.
        target: Target harness name (e.g. "gemini", "codex").

    Returns:
        Rule text with the best-matching model variant selected.
    """
    primary_model = _HARNESS_PRIMARY_MODEL.get(target, "")
    if not primary_model or not _MODEL_BLOCK_RE.search(rule_text):
        return rule_text

    # First pass: look for an exact match on the target's primary model
    for match in _MODEL_BLOCK_RE.finditer(rule_text):
        model_tag = match.group("model").strip().lower()
        if primary_model.lower().startswith(model_tag) or model_tag in primary_model.lower():
            # Return the variant content surrounded by the non-model text
            variant_content = match.group("content").strip()
            outer = _MODEL_BLOCK_RE.sub("", rule_text).strip()
            if outer:
                return outer + "\n\n" + variant_content
            return variant_content

    # No exact variant found — strip all model blocks and return base text
    return _MODEL_BLOCK_RE.sub("", rule_text).strip()


def inject_model_variant(
    rule_text: str,
    model_id: str,
    variant_text: str,
) -> str:
    """Insert a model-specific variant block into a rule.

    Appends a ``<!-- model:X --> ... <!-- /model:X -->`` block to the rule,
    allowing HarnessSync to select the right variant when syncing to a harness
    that primarily uses that model.

    Args:
        rule_text: Original rule content.
        model_id: Model identifier for the variant (e.g. "gemini-2.0-flash").
        variant_text: Shorter or adapted instruction text for this model.

    Returns:
        Updated rule text with the model variant appended.
    """
    variant_block = (
        f"\n\n<!-- model:{model_id} -->\n"
        f"{variant_text.strip()}\n"
        f"<!-- /model:{model_id} -->"
    )
    return rule_text.rstrip() + variant_block


def list_model_variants(rule_text: str) -> list[dict]:
    """List all model-specific variants embedded in a rule.

    Args:
        rule_text: Rule content potentially containing model variant blocks.

    Returns:
        List of dicts with keys ``model`` and ``content`` for each variant found.
    """
    return [
        {"model": m.group("model"), "content": m.group("content").strip()}
        for m in _MODEL_BLOCK_RE.finditer(rule_text)
    ]
