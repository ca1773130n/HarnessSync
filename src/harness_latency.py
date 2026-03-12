from __future__ import annotations

"""Harness Latency Comparison — benchmark response latency across harnesses.

Runs a standard one-shot prompt against each configured harness CLI and
reports response latency ranked from fastest to slowest. Helps users choose
the right harness for time-sensitive vs. quality-sensitive tasks.

Usage:
    benchmarker = HarnessLatencyBenchmarker(project_dir)
    results = benchmarker.run(targets=["gemini", "codex"])
    print(benchmarker.format_results(results))
"""

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from src.utils.logger import Logger


# Default benchmark prompt — short, unambiguous, forces a response
DEFAULT_BENCHMARK_PROMPT = "Reply with exactly: OK"

# Timeout per harness invocation (seconds)
_TIMEOUT_SECONDS = 30

# Harness CLI invocation patterns
_HARNESS_CLI: dict[str, dict] = {
    "gemini": {
        "executables": ["gemini"],
        "prompt_arg": None,    # uses stdin or first positional
        "prompt_flag": "-p",
        "extra_flags": ["--no-interactive"] if False else [],
    },
    "codex": {
        "executables": ["codex"],
        "prompt_flag": None,
        "extra_flags": ["-q"],  # quiet mode for codex
    },
    "opencode": {
        "executables": ["opencode", "opencode-cli"],
        "prompt_flag": None,
        "extra_flags": [],
    },
    "aider": {
        "executables": ["aider"],
        "prompt_flag": "--message",
        "extra_flags": ["--no-git", "--yes"],
    },
}


@dataclass
class LatencyResult:
    """Benchmark result for a single harness."""

    target: str
    latency_ms: float        # Wall-clock latency in milliseconds
    response_preview: str    # First 120 chars of response
    error: str               # Non-empty if measurement failed
    executable: str          # Path to the CLI that was run

    @property
    def success(self) -> bool:
        return not self.error

    def format_row(self, rank: int) -> str:
        if self.error:
            return f"  #{rank}  {self.target:<12}  ERROR: {self.error[:60]}"
        bar_len = min(int(self.latency_ms / 100), 30)
        bar = "█" * bar_len
        return (
            f"  #{rank}  {self.target:<12}  {self.latency_ms:>7.0f} ms  {bar}"
        )


class HarnessLatencyBenchmarker:
    """Benchmark response latency across multiple harnesses.

    Args:
        project_dir: Project root (used as working directory for CLIs).
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.logger = Logger()

    def _find_executable(self, target: str) -> str | None:
        info = _HARNESS_CLI.get(target, {})
        for exe in info.get("executables", [target]):
            path = shutil.which(exe)
            if path:
                return path
        return None

    def _measure(self, target: str, prompt: str) -> LatencyResult:
        """Invoke the harness CLI with the prompt and measure wall-clock latency."""
        exe = self._find_executable(target)
        if not exe:
            return LatencyResult(
                target=target,
                latency_ms=0.0,
                response_preview="",
                error=f"executable not found on PATH",
                executable="",
            )

        info = _HARNESS_CLI[target]
        prompt_flag = info.get("prompt_flag")
        extra_flags = info.get("extra_flags", [])

        if prompt_flag:
            cmd = [exe] + extra_flags + [prompt_flag, prompt]
        else:
            cmd = [exe] + extra_flags + [prompt]

        start = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_dir),
                timeout=_TIMEOUT_SECONDS,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            output = (result.stdout or result.stderr or "").strip()
            if result.returncode != 0 and not output:
                return LatencyResult(
                    target=target,
                    latency_ms=elapsed_ms,
                    response_preview="",
                    error=f"exit code {result.returncode}",
                    executable=exe,
                )
            return LatencyResult(
                target=target,
                latency_ms=elapsed_ms,
                response_preview=output[:120],
                error="",
                executable=exe,
            )
        except subprocess.TimeoutExpired:
            elapsed_ms = _TIMEOUT_SECONDS * 1000.0
            return LatencyResult(
                target=target,
                latency_ms=elapsed_ms,
                response_preview="",
                error=f"timed out after {_TIMEOUT_SECONDS}s",
                executable=exe,
            )
        except Exception as e:
            return LatencyResult(
                target=target,
                latency_ms=0.0,
                response_preview="",
                error=str(e),
                executable=exe,
            )

    def run(
        self,
        targets: list[str] | None = None,
        prompt: str = DEFAULT_BENCHMARK_PROMPT,
        runs: int = 1,
    ) -> list[LatencyResult]:
        """Benchmark each target harness and return results ranked by latency.

        Args:
            targets: Harnesses to benchmark. Defaults to all known targets.
            prompt: Benchmark prompt to send.
            runs: Number of runs to average (default: 1 for quick check).

        Returns:
            List of LatencyResult sorted fastest → slowest.
        """
        if targets is None:
            targets = list(_HARNESS_CLI.keys())

        results: list[LatencyResult] = []
        for target in targets:
            if runs > 1:
                # Average multiple runs
                measurements: list[float] = []
                last_result: LatencyResult | None = None
                for _ in range(runs):
                    r = self._measure(target, prompt)
                    last_result = r
                    if r.success:
                        measurements.append(r.latency_ms)
                if measurements and last_result:
                    last_result.latency_ms = sum(measurements) / len(measurements)
                if last_result:
                    results.append(last_result)
            else:
                results.append(self._measure(target, prompt))

        # Sort: successful results by latency, then errors at the end
        results.sort(key=lambda r: (not r.success, r.latency_ms))
        return results

    def format_results(self, results: list[LatencyResult], prompt: str = DEFAULT_BENCHMARK_PROMPT) -> str:
        """Format benchmark results as a ranked comparison table."""
        if not results:
            return "No harness results to display."

        lines = [
            "\nHarness Latency Comparison",
            "=" * 50,
            f"Prompt: {prompt!r}",
            "",
            f"  {'Rank':<4}  {'Harness':<12}  {'Latency':>10}  {'Speed'}",
            "  " + "-" * 46,
        ]

        for i, result in enumerate(results, start=1):
            lines.append(result.format_row(i))

        # Add fastest/slowest summary
        successful = [r for r in results if r.success]
        if len(successful) >= 2:
            fastest = successful[0]
            slowest = successful[-1]
            ratio = slowest.latency_ms / fastest.latency_ms if fastest.latency_ms > 0 else 1.0
            lines.append("")
            lines.append(
                f"  {fastest.target} is {ratio:.1f}x faster than {slowest.target}"
            )

        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cross-Harness Response Quality Benchmarker (item 16)
# ---------------------------------------------------------------------------

@dataclass
class QualityResult:
    """Response quality capture for a single harness."""

    target: str
    prompt: str
    response: str        # Full response text
    latency_ms: float    # Wall-clock response time
    error: str           # Non-empty if invocation failed
    executable: str      # CLI path used

    @property
    def success(self) -> bool:
        return not self.error

    @property
    def word_count(self) -> int:
        return len(self.response.split())

    @property
    def line_count(self) -> int:
        return len(self.response.splitlines())


class HarnessQualityBenchmarker:
    """Run the same prompt across multiple harnesses and compare response quality.

    Unlike ``HarnessLatencyBenchmarker`` (which ranks by response time),
    this class captures the full response text so users can evaluate whether
    synced rules produce consistent behaviour across harnesses.

    The comparison shows responses side-by-side in the terminal, with basic
    quality signals: response length, structure (bullet vs prose), and keyword
    hit-rate for expected terms.

    Usage::

        bm = HarnessQualityBenchmarker(project_dir)
        results = bm.run("Explain what you do in one sentence.", targets=["gemini", "codex"])
        print(bm.format_comparison(results))
        divergences = bm.divergence_report(results)
    """

    # Maximum response characters to capture (prevents runaway output)
    MAX_RESPONSE_CHARS = 4000

    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir
        self.logger = Logger()
        self._latency_benchmarker = HarnessLatencyBenchmarker(project_dir)

    def _capture(self, target: str, prompt: str) -> QualityResult:
        """Invoke harness CLI and capture the full response.

        Args:
            target: Harness name (e.g. "gemini").
            prompt: Prompt to send.

        Returns:
            QualityResult with full response text.
        """
        exe = self._latency_benchmarker._find_executable(target)
        if not exe:
            return QualityResult(
                target=target,
                prompt=prompt,
                response="",
                latency_ms=0.0,
                error="executable not found on PATH",
                executable="",
            )

        info = _HARNESS_CLI.get(target, {})
        prompt_flag = info.get("prompt_flag")
        extra_flags = info.get("extra_flags", [])

        if prompt_flag:
            cmd = [exe] + extra_flags + [prompt_flag, prompt]
        else:
            cmd = [exe] + extra_flags + [prompt]

        start = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.project_dir),
                timeout=_TIMEOUT_SECONDS,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            output = (result.stdout or result.stderr or "").strip()
            output = output[: self.MAX_RESPONSE_CHARS]
            if result.returncode != 0 and not output:
                return QualityResult(
                    target=target,
                    prompt=prompt,
                    response="",
                    latency_ms=elapsed_ms,
                    error=f"exit code {result.returncode}",
                    executable=exe,
                )
            return QualityResult(
                target=target,
                prompt=prompt,
                response=output,
                latency_ms=elapsed_ms,
                error="",
                executable=exe,
            )
        except subprocess.TimeoutExpired:
            return QualityResult(
                target=target,
                prompt=prompt,
                response="",
                latency_ms=_TIMEOUT_SECONDS * 1000.0,
                error=f"timed out after {_TIMEOUT_SECONDS}s",
                executable=exe,
            )
        except Exception as e:
            return QualityResult(
                target=target,
                prompt=prompt,
                response="",
                latency_ms=0.0,
                error=str(e),
                executable=exe,
            )

    def run(
        self,
        prompt: str,
        targets: list[str] | None = None,
    ) -> list[QualityResult]:
        """Run the prompt on all (or specified) harnesses and collect responses.

        Args:
            prompt: The prompt to run against every harness.
            targets: Harnesses to query. Defaults to all known CLI targets.

        Returns:
            List of QualityResult, one per target (including errors).
        """
        if targets is None:
            targets = list(_HARNESS_CLI.keys())
        return [self._capture(t, prompt) for t in targets]

    def format_comparison(self, results: list[QualityResult], column_width: int = 60) -> str:
        """Format responses side-by-side in a readable comparison view.

        Each harness gets a column block. Responses are shown in full (up to
        MAX_RESPONSE_CHARS). Quality signals (word count, line count, latency)
        are shown in a summary header above each response.

        Args:
            results: Output of ``run()``.
            column_width: Width of each harness column in characters.

        Returns:
            Human-readable comparison string.
        """
        if not results:
            return "No quality results to display."

        prompt = results[0].prompt if results else ""
        lines: list[str] = [
            "\nCross-Harness Response Comparison",
            "=" * (column_width * min(len(results), 3)),
            f"Prompt: {prompt!r}",
            "",
        ]

        for r in results:
            sep = "─" * column_width
            lines.append(sep)
            if r.error:
                lines.append(f"[ {r.target.upper()} — ERROR: {r.error} ]")
            else:
                lines.append(
                    f"[ {r.target.upper()} ]  "
                    f"{r.latency_ms:.0f}ms  |  "
                    f"{r.word_count} words  |  "
                    f"{r.line_count} lines"
                )
                lines.append(sep)
                # Wrap long lines at column_width
                for text_line in r.response.splitlines():
                    if len(text_line) <= column_width:
                        lines.append(text_line)
                    else:
                        # Simple word-wrap
                        words = text_line.split()
                        current = ""
                        for word in words:
                            if len(current) + len(word) + 1 > column_width:
                                lines.append(current)
                                current = word
                            else:
                                current = (current + " " + word).lstrip()
                        if current:
                            lines.append(current)
            lines.append("")

        lines.append("=" * (column_width * min(len(results), 3)))
        return "\n".join(lines)

    def divergence_report(
        self,
        results: list[QualityResult],
        keyword_checks: list[str] | None = None,
    ) -> list[str]:
        """Identify harnesses whose responses diverge significantly.

        Checks two signals:
          1. **Length divergence**: response word count differs by >3x from median.
          2. **Keyword miss**: expected keywords (if provided) are absent from response.

        Args:
            results: Output of ``run()``.
            keyword_checks: Optional list of words that should appear in all responses.

        Returns:
            List of divergence notice strings. Empty = all responses consistent.
        """
        successful = [r for r in results if r.success]
        if len(successful) < 2:
            return []

        notices: list[str] = []

        # Length divergence
        word_counts = [r.word_count for r in successful]
        sorted_counts = sorted(word_counts)
        median = sorted_counts[len(sorted_counts) // 2]
        if median > 0:
            for r in successful:
                ratio = r.word_count / median
                if ratio > 3.0 or ratio < 0.33:
                    notices.append(
                        f"{r.target}: response length diverges "
                        f"({r.word_count} words vs median {median}) — "
                        "rules may not be translating consistently"
                    )

        # Keyword checks
        if keyword_checks:
            for r in successful:
                response_lower = r.response.lower()
                missing = [kw for kw in keyword_checks if kw.lower() not in response_lower]
                if missing:
                    notices.append(
                        f"{r.target}: missing expected keyword(s): {', '.join(missing)}"
                    )

        return notices
