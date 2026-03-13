from __future__ import annotations

"""Token count and context cost estimator for synced harness configs.

Shows an estimate of how many tokens each synced rules file will consume
in each harness's context window, flagging configurations that may degrade
LLM performance due to bloated system prompts.

Helps users understand the cost tradeoff of syncing verbose Claude Code
rules to token-constrained harnesses.

Token counting method:
  Uses the ~4 characters/token heuristic (GPT-3.5/4 and most models).
  For precise Anthropic tokenization we would need the tokenizer library,
  but the heuristic is within ±15% for typical rule files.

Context window limits per harness (conservative estimates, 2025):
  codex:    ~8,192 tokens (Codex CLI default context)
  gemini:   ~32,768 tokens (Gemini 1.5 Flash/Pro)
  opencode: ~32,768 tokens
  cursor:   ~8,192 tokens (Cursor chat context limit for rules)
  aider:    ~8,192 tokens (conservative; depends on model)
  windsurf: ~8,192 tokens
"""

from dataclasses import dataclass, field
from pathlib import Path


# Approximate characters per token (GPT/Claude heuristic)
CHARS_PER_TOKEN = 4.0

# Cost per 1M input tokens (USD) per harness's typical model, 2025 estimates
# These are approximate — actual costs depend on the model selected by the user
INPUT_COST_PER_MTK: dict[str, float] = {
    "codex":    0.50,   # GPT-4o mini tier (Codex CLI default)
    "gemini":   0.075,  # Gemini 1.5 Flash
    "opencode": 3.00,   # GPT-4o or Claude tier (configurable)
    "cursor":   3.00,   # Claude/GPT-4o (Cursor default)
    "aider":    3.00,   # Claude/GPT-4o (model-dependent)
    "windsurf": 3.00,   # Claude/GPT-4o tier
    "cline":    3.00,   # Claude/GPT-4o (VS Code extension, model-dependent)
    "continue": 1.00,   # Continue.dev — varies widely by model choice
    "zed":      3.00,   # Zed AI — Claude/GPT-4o tier
    "neovim":   3.00,   # avante.nvim/codecompanion — model-dependent
}

# Context window sizes per harness (in tokens)
CONTEXT_WINDOWS: dict[str, int] = {
    "codex":    8_192,
    "gemini":   32_768,
    "opencode": 32_768,
    "cursor":   8_192,
    "aider":    8_192,
    "windsurf": 8_192,
    "cline":    16_384,   # Cline injects rules into each conversation context
    "continue": 32_768,   # Continue.dev injects rules into context
    "zed":      16_384,   # Zed AI system prompt context
    "neovim":   16_384,   # avante.nvim/codecompanion context
}

# Warning thresholds (fraction of context window)
WARN_THRESHOLD = 0.25   # Warn at 25% usage
CRITICAL_THRESHOLD = 0.50  # Critical at 50% usage


def _estimate_session_cost_usd(tokens: int, target: str) -> float:
    """Estimate per-session USD cost to load a config into a harness context.

    Args:
        tokens: Estimated token count of the config.
        target: Target harness name.

    Returns:
        USD cost as float (e.g. 0.0032).
    """
    cost_per_m = INPUT_COST_PER_MTK.get(target, 3.00)
    return (tokens / 1_000_000) * cost_per_m


@dataclass
class FileTokenEstimate:
    """Token estimate for a single file in a target harness."""

    file_path: str
    char_count: int
    token_estimate: int
    context_window: int
    fraction_used: float           # 0.0 – 1.0+
    level: str                     # "ok" | "warn" | "critical"

    @property
    def percent_used(self) -> float:
        return self.fraction_used * 100.0


@dataclass
class HarnessTokenReport:
    """Token usage report for a single target harness."""

    target: str
    files: list[FileTokenEstimate] = field(default_factory=list)
    context_window: int = 0

    @property
    def total_tokens(self) -> int:
        return sum(f.token_estimate for f in self.files)

    @property
    def total_fraction(self) -> float:
        if not self.context_window:
            return 0.0
        return self.total_tokens / self.context_window

    @property
    def level(self) -> str:
        if self.total_fraction >= CRITICAL_THRESHOLD:
            return "critical"
        if self.total_fraction >= WARN_THRESHOLD:
            return "warn"
        return "ok"

    @property
    def session_cost_usd(self) -> float:
        """Estimated per-session USD cost to load this config into context."""
        return _estimate_session_cost_usd(self.total_tokens, self.target)

    def format_summary(self) -> str:
        pct = self.total_fraction * 100
        cost = self.session_cost_usd
        symbol = "⚠" if self.level == "warn" else ("✗" if self.level == "critical" else "✓")
        cost_str = f"~${cost:.4f}/session" if cost >= 0.0001 else f"~${cost:.6f}/session"
        return (
            f"{symbol} {self.target}: ~{self.total_tokens:,} tokens "
            f"({pct:.1f}% of {self.context_window:,}-token context, {cost_str})"
        )


@dataclass
class TokenEstimateReport:
    """Aggregated token report across all harnesses."""

    harnesses: list[HarnessTokenReport] = field(default_factory=list)

    def format(self, verbose: bool = False) -> str:
        """Format human-readable report.

        Args:
            verbose: Include per-file breakdown (default: harness totals only).

        Returns:
            Formatted string.
        """
        if not self.harnesses:
            return "No synced rule files found to estimate."

        lines: list[str] = ["## Token & Context Cost Estimate", ""]
        lines.append(
            "Estimates use the ~4 chars/token heuristic (±15% accuracy).\n"
        )

        warnings = [h for h in self.harnesses if h.level in ("warn", "critical")]
        if warnings:
            lines.append("**Warnings:**")
            for h in warnings:
                lines.append(
                    f"  {'⚠' if h.level == 'warn' else '✗'} {h.target}: "
                    f"{h.total_fraction * 100:.0f}% of context window consumed by synced rules. "
                    f"Consider using <!-- sync:exclude --> to reduce rule verbosity."
                )
            lines.append("")

        lines.append("**Per-harness totals:**")
        for h in sorted(self.harnesses, key=lambda x: x.target):
            lines.append(f"  {h.format_summary()}")
            if verbose:
                for fe in h.files:
                    lines.append(
                        f"    - {Path(fe.file_path).name}: "
                        f"~{fe.token_estimate:,} tokens ({fe.percent_used:.1f}%)"
                        + (f" [{fe.level.upper()}]" if fe.level != "ok" else "")
                    )

        return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    """Estimate token count from character count.

    Args:
        text: Input text.

    Returns:
        Estimated token count.
    """
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def _classify_level(fraction: float) -> str:
    """Classify token usage level.

    Args:
        fraction: Fraction of context window used.

    Returns:
        "ok" | "warn" | "critical"
    """
    if fraction >= CRITICAL_THRESHOLD:
        return "critical"
    if fraction >= WARN_THRESHOLD:
        return "warn"
    return "ok"


class TokenEstimator:
    """Estimates token usage for synced harness config files.

    Scans known harness config file locations and estimates how much of
    each harness's context window is consumed by synced rules.
    """

    def __init__(self, project_dir: Path):
        """Initialize estimator.

        Args:
            project_dir: Project root directory.
        """
        self.project_dir = project_dir

    def estimate_all(self, targets: list[str] | None = None) -> TokenEstimateReport:
        """Estimate token usage for all target harnesses.

        Args:
            targets: Specific targets to check (None = all known).

        Returns:
            TokenEstimateReport with per-harness breakdowns.
        """
        all_targets = targets or list(CONTEXT_WINDOWS.keys())
        report = TokenEstimateReport()

        for target in all_targets:
            harness_report = self._estimate_target(target)
            if harness_report.files:  # Skip targets with no synced files
                report.harnesses.append(harness_report)

        return report

    def _estimate_target(self, target: str) -> HarnessTokenReport:
        """Estimate token usage for a single harness.

        Args:
            target: Target harness name.

        Returns:
            HarnessTokenReport.
        """
        context_window = CONTEXT_WINDOWS.get(target, 8_192)
        harness_report = HarnessTokenReport(target=target, context_window=context_window)

        for file_path in _get_rules_files(target, self.project_dir):
            try:
                content = file_path.read_text(encoding="utf-8")
            except OSError:
                continue

            char_count = len(content)
            token_estimate = _estimate_tokens(content)
            fraction = token_estimate / context_window

            harness_report.files.append(FileTokenEstimate(
                file_path=str(file_path),
                char_count=char_count,
                token_estimate=token_estimate,
                context_window=context_window,
                fraction_used=fraction,
                level=_classify_level(fraction),
            ))

        return harness_report


def suggest_size_optimizations(
    report: "TokenEstimateReport",
    *,
    target_fraction: float = 0.20,
) -> list[str]:
    """Suggest token-reduction actions for harnesses over their context budget.

    For each harness where the synced config consumes more than ``target_fraction``
    of the context window, produces actionable suggestions: which files to trim,
    how many tokens could be saved, and what to do.

    Args:
        report: TokenBudgetReport from TokenBudgetEstimator.estimate_all() or similar.
        target_fraction: Fraction of the context window to target (default 0.20 = 20%).

    Returns:
        List of human-readable suggestion strings, one per over-budget harness.
        Empty if all harnesses are within budget.
    """
    suggestions: list[str] = []

    for harness_report in report.harnesses:
        if harness_report.total_fraction <= target_fraction:
            continue

        current_tokens = harness_report.total_tokens
        window = harness_report.context_window
        target_tokens = int(window * target_fraction)
        excess = current_tokens - target_tokens

        # Find the largest file — that's the best trimming candidate
        if not harness_report.files:
            continue
        largest = max(harness_report.files, key=lambda f: f.token_estimate)

        trim_pct = min(100, int((excess / largest.token_estimate) * 100)) if largest.token_estimate else 0
        cost_now = harness_report.session_cost_usd
        cost_target = _estimate_session_cost_usd(target_tokens, harness_report.target)
        savings = cost_now - cost_target

        suggestion = (
            f"{harness_report.target}: {current_tokens:,} tokens "
            f"({harness_report.total_fraction * 100:.0f}% of {window:,}-token context). "
            f"Trim ~{trim_pct}% from {largest.file_path} to reach {target_fraction * 100:.0f}% target "
            f"(saves ~{excess:,} tokens, ~${savings:.5f}/session)."
        )
        suggestions.append(suggestion)

    return suggestions


def _get_rules_files(target: str, project_dir: Path) -> list[Path]:
    """Return paths of synced rules files for the given target harness.

    Args:
        target: Target harness name.
        project_dir: Project root directory.

    Returns:
        List of existing file paths.
    """
    patterns: dict[str, list[str]] = {
        "codex":    ["AGENTS.md"],
        "gemini":   ["GEMINI.md"],
        "opencode": ["AGENTS.md"],
        "cursor":   [".cursor/rules/claude-code-rules.mdc"],
        "aider":    ["CONVENTIONS.md"],
        "windsurf": [".windsurfrules"],
        "cline":    [".clinerules", ".roo/rules/harnesssync.md"],
        "continue": [".continue/rules/harnesssync.md"],
        "zed":      [".zed/system-prompt.md"],
        "neovim":   [".avante/system-prompt.md", ".codecompanion/system-prompt.md"],
    }

    results: list[Path] = []
    for rel in patterns.get(target, []):
        p = project_dir / rel
        if p.is_file():
            results.append(p)

    return results
