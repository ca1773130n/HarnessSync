from __future__ import annotations

"""Context window budget synchronization (item 26: Context Window Budget Sync).

Reads context/token budget settings from CLAUDE.md (via a structured
``## Context Budget`` section) and translates them into the equivalent
config keys for each target harness.

Users who carefully tune Claude Code's context window behavior currently
get inconsistent results in other harnesses because each harness uses
different key names and units.

This module:
1. Parses budget directives from CLAUDE.md front matter or a dedicated section.
2. Translates the unified budget config to each harness's native format.
3. Generates harness-specific config snippets that can be merged into
   the adapter output.

Budget directive format in CLAUDE.md (inline comments after ## Context Budget)::

    ## Context Budget
    max_tokens: 8192
    context_limit: 200000
    thinking_budget: 5000
    output_limit: 4096

Harness-specific translations:
  - Codex (config.toml):     max_tokens = <value>
  - Gemini (settings.json):  "maxOutputTokens": <value>
  - OpenCode (opencode.json): "model": { "maxTokens": <value> }
  - Cursor (.cursorrules):   No direct equivalent — annotated as comment
  - Aider (.aider.conf.yml): --max-tokens <value>
  - Windsurf:               No direct equivalent — annotated as comment
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Budget field names ────────────────────────────────────────────────────────

# Canonical budget fields (unified across harnesses)
BUDGET_FIELDS = [
    "max_tokens",          # Maximum tokens per response
    "context_limit",       # Maximum total context window tokens
    "thinking_budget",     # Tokens reserved for extended thinking (Claude)
    "output_limit",        # Alias for max_tokens (used by some harnesses)
]

# Default values when not specified
_DEFAULTS: dict[str, int] = {
    "max_tokens": 8192,
    "context_limit": 200_000,
    "thinking_budget": 0,   # 0 = disabled
    "output_limit": 8192,
}


@dataclass
class ContextBudget:
    """Parsed context budget settings."""
    max_tokens: int = 8192
    context_limit: int = 200_000
    thinking_budget: int = 0
    output_limit: int = 8192

    # Source information
    source: str = ""        # "claude_md", "defaults", "explicit"

    def effective_output_tokens(self) -> int:
        """Return the effective output token limit (max of max_tokens and output_limit)."""
        return max(self.max_tokens, self.output_limit)


@dataclass
class HarnessBudgetConfig:
    """Budget configuration translated to a specific harness's format."""
    harness: str
    config_snippet: str          # Harness-native config text/JSON to merge
    config_format: str           # "toml" | "json" | "yaml" | "comment_only"
    field_mappings: dict[str, str] = field(default_factory=dict)
    # field_mappings: canonical_name -> harness_native_key
    notes: list[str] = field(default_factory=list)


# ── CLAUDE.md budget parser ────────────────────────────────────────────────────

_BUDGET_SECTION_RE = re.compile(
    r"^#+\s+Context\s+Budget\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BUDGET_KV_RE = re.compile(
    r"^[ \t]*([a-z_]+)\s*[:=]\s*(\d+)",
    re.IGNORECASE | re.MULTILINE,
)


def parse_budget_from_claude_md(content: str) -> ContextBudget | None:
    """Parse a ``## Context Budget`` section from CLAUDE.md content.

    Returns a ContextBudget if the section exists, or None if not found.

    Args:
        content: Full text content of CLAUDE.md.

    Returns:
        ContextBudget with parsed values, or None if no budget section.
    """
    # Find the Context Budget section
    match = _BUDGET_SECTION_RE.search(content)
    if not match:
        return None

    # Extract text from section start to next ## heading
    section_start = match.end()
    next_heading = re.search(r"^#+ ", content[section_start:], re.MULTILINE)
    if next_heading:
        section_text = content[section_start:section_start + next_heading.start()]
    else:
        section_text = content[section_start:]

    # Parse key: value pairs
    budget_dict: dict[str, int] = {}
    for kv_match in _BUDGET_KV_RE.finditer(section_text):
        key = kv_match.group(1).lower()
        value = int(kv_match.group(2))
        if key in BUDGET_FIELDS:
            budget_dict[key] = value

    if not budget_dict:
        return None

    return ContextBudget(
        max_tokens=budget_dict.get("max_tokens", _DEFAULTS["max_tokens"]),
        context_limit=budget_dict.get("context_limit", _DEFAULTS["context_limit"]),
        thinking_budget=budget_dict.get("thinking_budget", _DEFAULTS["thinking_budget"]),
        output_limit=budget_dict.get("output_limit", budget_dict.get("max_tokens", _DEFAULTS["output_limit"])),
        source="claude_md",
    )


def parse_budget_from_file(claude_md_path: Path) -> ContextBudget | None:
    """Read CLAUDE.md from disk and parse its budget section."""
    if not claude_md_path.exists():
        return None
    try:
        content = claude_md_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return parse_budget_from_claude_md(content)


# ── Harness translators ────────────────────────────────────────────────────────

def _translate_codex(budget: ContextBudget) -> HarnessBudgetConfig:
    """Translate budget to Codex config.toml format."""
    lines = ["# Context budget (synced from CLAUDE.md by HarnessSync)"]
    lines.append(f"max_tokens = {budget.effective_output_tokens()}")
    if budget.context_limit != _DEFAULTS["context_limit"]:
        lines.append(f"# context_limit = {budget.context_limit}  # informational only")
    return HarnessBudgetConfig(
        harness="codex",
        config_snippet="\n".join(lines),
        config_format="toml",
        field_mappings={"max_tokens": "max_tokens"},
    )


def _translate_gemini(budget: ContextBudget) -> HarnessBudgetConfig:
    """Translate budget to Gemini settings.json format."""
    import json
    obj: dict = {"maxOutputTokens": budget.effective_output_tokens()}
    if budget.thinking_budget > 0:
        obj["thinkingConfig"] = {"thinkingBudget": budget.thinking_budget}
    snippet = json.dumps(obj, indent=2)
    return HarnessBudgetConfig(
        harness="gemini",
        config_snippet=snippet,
        config_format="json",
        field_mappings={
            "max_tokens": "maxOutputTokens",
            "thinking_budget": "thinkingConfig.thinkingBudget",
        },
    )


def _translate_opencode(budget: ContextBudget) -> HarnessBudgetConfig:
    """Translate budget to opencode.json format."""
    import json
    obj = {
        "model": {
            "maxTokens": budget.effective_output_tokens(),
        }
    }
    snippet = json.dumps(obj, indent=2)
    return HarnessBudgetConfig(
        harness="opencode",
        config_snippet=snippet,
        config_format="json",
        field_mappings={"max_tokens": "model.maxTokens"},
    )


def _translate_cursor(budget: ContextBudget) -> HarnessBudgetConfig:
    """Translate budget to Cursor comment annotation."""
    lines = [
        "# Context Budget (from HarnessSync — Cursor has no direct token budget config)",
        f"# Recommended max tokens: {budget.effective_output_tokens()}",
        f"# Context limit: {budget.context_limit}",
        "# Configure via Cursor Settings > AI > Max Tokens if available.",
    ]
    return HarnessBudgetConfig(
        harness="cursor",
        config_snippet="\n".join(lines),
        config_format="comment_only",
        notes=["Cursor manages token budgets via IDE settings, not rule files."],
    )


def _translate_aider(budget: ContextBudget) -> HarnessBudgetConfig:
    """Translate budget to Aider .aider.conf.yml format."""
    lines = [
        "# Context budget (synced from CLAUDE.md by HarnessSync)",
        f"max-tokens: {budget.effective_output_tokens()}",
    ]
    if budget.context_limit != _DEFAULTS["context_limit"]:
        lines.append(f"# context-limit: {budget.context_limit}  # informational only")
    return HarnessBudgetConfig(
        harness="aider",
        config_snippet="\n".join(lines),
        config_format="yaml",
        field_mappings={"max_tokens": "max-tokens"},
    )


def _translate_windsurf(budget: ContextBudget) -> HarnessBudgetConfig:
    """Translate budget to Windsurf comment annotation."""
    lines = [
        "# Context Budget (from HarnessSync — Windsurf has no direct token budget config)",
        f"# Recommended max tokens: {budget.effective_output_tokens()}",
        f"# Context limit: {budget.context_limit}",
    ]
    return HarnessBudgetConfig(
        harness="windsurf",
        config_snippet="\n".join(lines),
        config_format="comment_only",
        notes=["Windsurf manages token budgets via Cascade settings."],
    )


_TRANSLATORS = {
    "codex": _translate_codex,
    "gemini": _translate_gemini,
    "opencode": _translate_opencode,
    "cursor": _translate_cursor,
    "aider": _translate_aider,
    "windsurf": _translate_windsurf,
}


# ── Main sync class ────────────────────────────────────────────────────────────

class ContextBudgetSync:
    """Synchronizes context budget settings across target harnesses.

    Reads the ``## Context Budget`` section from CLAUDE.md and generates
    harness-specific config snippets for each registered target.

    Args:
        targets: Harness names to generate config for. Defaults to all known.
    """

    def __init__(self, targets: list[str] | None = None) -> None:
        self.targets = targets or list(_TRANSLATORS.keys())

    def translate_budget(self, budget: ContextBudget) -> dict[str, HarnessBudgetConfig]:
        """Translate a budget to all configured targets.

        Args:
            budget: Parsed ContextBudget (e.g. from parse_budget_from_claude_md).

        Returns:
            Dict mapping harness name -> HarnessBudgetConfig.
        """
        configs: dict[str, HarnessBudgetConfig] = {}
        for target in self.targets:
            translator = _TRANSLATORS.get(target)
            if translator:
                configs[target] = translator(budget)
        return configs

    def sync_from_claude_md(
        self,
        claude_md_content: str,
    ) -> tuple[ContextBudget | None, dict[str, HarnessBudgetConfig]]:
        """Parse CLAUDE.md and translate its budget section to all targets.

        Args:
            claude_md_content: Raw text of CLAUDE.md.

        Returns:
            (budget, configs) where budget is the parsed ContextBudget (or None
             if no budget section) and configs is the per-harness translation dict.
        """
        budget = parse_budget_from_claude_md(claude_md_content)
        if budget is None:
            return None, {}
        return budget, self.translate_budget(budget)

    def format_report(
        self,
        budget: ContextBudget,
        configs: dict[str, HarnessBudgetConfig],
    ) -> str:
        """Format a human-readable report of the budget sync.

        Args:
            budget:  The parsed canonical budget.
            configs: Output of ``translate_budget()``.

        Returns:
            Formatted report string.
        """
        lines = [
            "Context Budget Sync",
            "=" * 50,
            "",
            "Canonical budget (from CLAUDE.md):",
            f"  max_tokens:       {budget.max_tokens:,}",
            f"  context_limit:    {budget.context_limit:,}",
            f"  thinking_budget:  {budget.thinking_budget:,}",
            f"  output_limit:     {budget.output_limit:,}",
            "",
            "Per-harness translation:",
            "-" * 50,
        ]
        for harness, config in configs.items():
            lines.append(f"\n  [{harness}]  ({config.config_format})")
            for snippet_line in config.config_snippet.splitlines():
                lines.append(f"    {snippet_line}")
            if config.notes:
                for note in config.notes:
                    lines.append(f"    ℹ {note}")
        return "\n".join(lines)

    def generate_claude_md_section(self, budget: ContextBudget) -> str:
        """Generate a ``## Context Budget`` CLAUDE.md section for the given budget.

        Useful when the user wants to add a budget section to CLAUDE.md
        that HarnessSync will then sync to all targets.

        Args:
            budget: Budget to encode as CLAUDE.md section.

        Returns:
            Formatted CLAUDE.md section string.
        """
        lines = [
            "## Context Budget",
            "",
            "<!-- HarnessSync: token budget settings synced to all harnesses -->",
            f"max_tokens: {budget.max_tokens}",
            f"context_limit: {budget.context_limit}",
        ]
        if budget.thinking_budget > 0:
            lines.append(f"thinking_budget: {budget.thinking_budget}")
        if budget.output_limit != budget.max_tokens:
            lines.append(f"output_limit: {budget.output_limit}")
        lines.append("")
        return "\n".join(lines)
