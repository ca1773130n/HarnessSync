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

import shlex
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
