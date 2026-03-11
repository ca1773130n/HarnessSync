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

# Context window sizes per harness (in tokens)
CONTEXT_WINDOWS: dict[str, int] = {
    "codex":    8_192,
    "gemini":   32_768,
    "opencode": 32_768,
    "cursor":   8_192,
    "aider":    8_192,
    "windsurf": 8_192,
}

# Warning thresholds (fraction of context window)
WARN_THRESHOLD = 0.25   # Warn at 25% usage
CRITICAL_THRESHOLD = 0.50  # Critical at 50% usage


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

    def format_summary(self) -> str:
        pct = self.total_fraction * 100
        symbol = "⚠" if self.level == "warn" else ("✗" if self.level == "critical" else "✓")
        return (
            f"{symbol} {self.target}: ~{self.total_tokens:,} tokens "
            f"({pct:.1f}% of {self.context_window:,}-token context)"
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
    }

    results: list[Path] = []
    for rel in patterns.get(target, []):
        p = project_dir / rel
        if p.is_file():
            results.append(p)

    return results
