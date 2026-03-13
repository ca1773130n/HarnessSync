from __future__ import annotations

"""Harness Warmup Preloader — pre-initialize harnesses after sync (item 28).

After HarnessSync completes a sync operation, this module optionally pre-
warms each target harness in the background so it's ready to use instantly.
Eliminates the cold-start delay users experience when switching from Claude
Code to another harness mid-workflow.

Warmup operations per harness type:
  - Validate environment variables referenced in MCP server configs
  - Check that CLI executables are on PATH (detect stale installs)
  - Probe MCP servers if a TCP health-check URL is available
  - Index skill files on disk (stat, not read) to prime the OS page cache
  - Write a .harnesssync/warmup_cache.json with results for /sync-status

Usage::

    from src.harness_warmup import HarnessWarmupManager

    manager = HarnessWarmupManager(project_dir=Path("."))
    manager.warmup_all(targets=["codex", "gemini"])  # blocks briefly
    manager.warmup_all_async(targets=["codex"])       # background thread

    # Inspect results:
    report = manager.get_last_report()
    print(report.format())
"""

import os
import shutil
import socket
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from src.utils.logger import Logger


# Cache file written next to .harnesssync/
_WARMUP_CACHE_FILE = ".harnesssync/warmup_cache.json"

# Timeout for TCP MCP server probes
_TCP_PROBE_TIMEOUT = 2.0

# Expected CLI names per harness
_HARNESS_EXECUTABLES: dict[str, list[str]] = {
    "codex":    ["codex"],
    "gemini":   ["gemini"],
    "opencode": ["opencode", "opencode-cli"],
    "cursor":   ["cursor"],
    "aider":    ["aider"],
    "windsurf": ["windsurf"],
    "cline":    [],           # VS Code extension — no standalone CLI
    "continue": ["continue"],
    "zed":      ["zed"],
    "neovim":   ["nvim"],
    "vscode":   ["code"],
}

# Skill directory paths per harness (relative to $HOME)
_HARNESS_SKILL_DIRS: dict[str, list[str]] = {
    "codex":    [".codex/skills"],
    "gemini":   [".gemini/skills"],
    "opencode": [".opencode/skills", ".config/opencode/skills"],
    "cursor":   [".cursor/rules"],
    "aider":    [".aider/skills"],
    "windsurf": [".windsurf/rules"],
}


@dataclass
class HarnessWarmupResult:
    """Result of warming up a single harness."""

    target: str
    cli_found: bool
    cli_path: str
    env_vars_ok: list[str]          # env vars that were present
    env_vars_missing: list[str]     # env vars that were absent
    mcp_servers_probed: list[str]   # server names with TCP checks
    mcp_servers_reachable: list[str]
    mcp_servers_unreachable: list[str]
    skill_files_indexed: int        # number of skill files stat'd
    elapsed_ms: float
    error: str = ""

    @property
    def healthy(self) -> bool:
        """True if the harness is installed and env vars are present."""
        return self.cli_found and not self.env_vars_missing

    def format(self) -> str:
        lines = [f"Warmup — {self.target}"]
        lines.append(f"  CLI: {'found at ' + self.cli_path if self.cli_found else 'NOT FOUND'}")
        if self.env_vars_ok:
            lines.append(f"  Env OK:      {', '.join(self.env_vars_ok)}")
        if self.env_vars_missing:
            lines.append(f"  Env MISSING: {', '.join(self.env_vars_missing)}")
        if self.mcp_servers_probed:
            for s in self.mcp_servers_reachable:
                lines.append(f"  MCP {s}: reachable")
            for s in self.mcp_servers_unreachable:
                lines.append(f"  MCP {s}: UNREACHABLE")
        if self.skill_files_indexed:
            lines.append(f"  Skills indexed: {self.skill_files_indexed}")
        lines.append(f"  Elapsed: {self.elapsed_ms:.0f}ms")
        if self.error:
            lines.append(f"  Error: {self.error}")
        return "\n".join(lines)


@dataclass
class WarmupReport:
    """Aggregated results across all harnesses."""

    timestamp: str
    results: list[HarnessWarmupResult] = field(default_factory=list)

    @property
    def healthy_targets(self) -> list[str]:
        return [r.target for r in self.results if r.healthy]

    @property
    def unhealthy_targets(self) -> list[str]:
        return [r.target for r in self.results if not r.healthy]

    def format(self) -> str:
        lines = [
            "HarnessSync Warmup Report",
            f"  Timestamp: {self.timestamp}",
            f"  Ready:     {', '.join(self.healthy_targets) or 'none'}",
        ]
        if self.unhealthy_targets:
            lines.append(f"  Issues:    {', '.join(self.unhealthy_targets)}")
        lines.append("")
        for r in self.results:
            lines.append(r.format())
        return "\n".join(lines)

    def to_dict(self) -> dict:
        import dataclasses
        return {
            "timestamp": self.timestamp,
            "results": [dataclasses.asdict(r) for r in self.results],
        }


class HarnessWarmupManager:
    """Pre-warms target harnesses after sync to eliminate cold-start delays.

    Args:
        project_dir: Project directory (used to find MCP config files).
        logger: Optional Logger instance.
    """

    def __init__(self, project_dir: Path, logger: Logger | None = None):
        self.project_dir = project_dir
        self._logger = logger or Logger()
        self._last_report: WarmupReport | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def warmup_all(self, targets: list[str] | None = None) -> WarmupReport:
        """Warm up all targets synchronously and return the report.

        Args:
            targets: Harness names to warm up. Defaults to all known harnesses.

        Returns:
            WarmupReport with per-harness results.
        """
        target_list = targets or list(_HARNESS_EXECUTABLES.keys())
        mcp_servers = self._load_mcp_servers()
        results = [self._warmup_target(t, mcp_servers) for t in target_list]
        report = WarmupReport(
            timestamp=datetime.now().isoformat(timespec="seconds"),
            results=results,
        )
        with self._lock:
            self._last_report = report
        self._write_cache(report)
        return report

    def warmup_all_async(
        self,
        targets: list[str] | None = None,
        on_complete: "Callable[[WarmupReport], None] | None" = None,
    ) -> threading.Thread:
        """Warm up all targets in a background thread.

        Args:
            targets: Harness names to warm up.
            on_complete: Optional callback called with the WarmupReport on completion.

        Returns:
            The started daemon thread (for join() if needed).
        """
        def _run() -> None:
            report = self.warmup_all(targets)
            if on_complete:
                try:
                    on_complete(report)
                except Exception:
                    pass

        thread = threading.Thread(
            target=_run,
            name="harnesssync-warmup",
            daemon=True,
        )
        thread.start()
        return thread

    def get_last_report(self) -> WarmupReport | None:
        """Return the most recent warmup report, or None if never run."""
        with self._lock:
            return self._last_report

    def load_cached_report(self) -> WarmupReport | None:
        """Load a previously persisted warmup report from disk.

        Returns:
            WarmupReport if cache exists and is readable, else None.
        """
        cache_path = self.project_dir / _WARMUP_CACHE_FILE
        if not cache_path.exists():
            return None
        try:
            import json
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            results = [
                HarnessWarmupResult(**r)
                for r in data.get("results", [])
                if isinstance(r, dict)
            ]
            return WarmupReport(
                timestamp=data.get("timestamp", ""),
                results=results,
            )
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _warmup_target(self, target: str, mcp_servers: dict) -> HarnessWarmupResult:
        """Warm up a single harness and return its result."""
        start = time.monotonic()
        cli_found = False
        cli_path = ""
        env_ok: list[str] = []
        env_missing: list[str] = []
        mcp_probed: list[str] = []
        mcp_reachable: list[str] = []
        mcp_unreachable: list[str] = []
        skill_count = 0
        error = ""

        try:
            # 1. Check CLI is on PATH
            executables = _HARNESS_EXECUTABLES.get(target, [])
            for exe in executables:
                found = shutil.which(exe)
                if found:
                    cli_found = True
                    cli_path = found
                    break

            # 2. Check env vars for MCP servers targeting this harness
            for server_name, server_cfg in mcp_servers.items():
                if not isinstance(server_cfg, dict):
                    continue
                env_section = server_cfg.get("env", {})
                if not isinstance(env_section, dict):
                    continue
                for var_name in env_section:
                    if os.environ.get(var_name):
                        if var_name not in env_ok:
                            env_ok.append(var_name)
                    else:
                        if var_name not in env_missing:
                            env_missing.append(var_name)

            # 3. TCP probe for HTTP/SSE MCP servers
            for server_name, server_cfg in mcp_servers.items():
                if not isinstance(server_cfg, dict):
                    continue
                url = server_cfg.get("url") or server_cfg.get("baseUrl", "")
                if not url or not url.startswith("http"):
                    continue
                mcp_probed.append(server_name)
                if _tcp_probe(url):
                    mcp_reachable.append(server_name)
                else:
                    mcp_unreachable.append(server_name)

            # 4. Index skill files (stat to prime OS cache)
            skill_count = self._index_skill_files(target)

        except Exception as exc:
            error = str(exc)

        elapsed_ms = (time.monotonic() - start) * 1000

        return HarnessWarmupResult(
            target=target,
            cli_found=cli_found,
            cli_path=cli_path,
            env_vars_ok=env_ok,
            env_vars_missing=env_missing,
            mcp_servers_probed=mcp_probed,
            mcp_servers_reachable=mcp_reachable,
            mcp_servers_unreachable=mcp_unreachable,
            skill_files_indexed=skill_count,
            elapsed_ms=elapsed_ms,
            error=error,
        )

    def _load_mcp_servers(self) -> dict:
        """Load MCP server configs from .mcp.json or project dir."""
        import json

        candidates = [
            self.project_dir / ".mcp.json",
            Path.home() / ".claude" / "mcp.json",
            Path.home() / ".mcp.json",
        ]
        for path in candidates:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return data.get("mcpServers", data) if isinstance(data, dict) else {}
                except Exception:
                    pass
        return {}

    def _index_skill_files(self, target: str) -> int:
        """Stat skill files for the given target to prime the OS file cache."""
        count = 0
        home = Path.home()
        for rel_dir in _HARNESS_SKILL_DIRS.get(target, []):
            skill_dir = home / rel_dir
            if not skill_dir.is_dir():
                continue
            try:
                for entry in skill_dir.rglob("*"):
                    if entry.is_file():
                        try:
                            entry.stat()
                            count += 1
                        except OSError:
                            pass
            except OSError:
                pass
        return count

    def _write_cache(self, report: WarmupReport) -> None:
        """Persist warmup results to .harnesssync/warmup_cache.json."""
        import json
        cache_path = self.project_dir / _WARMUP_CACHE_FILE
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except OSError:
            pass


def _tcp_probe(url: str, timeout: float = _TCP_PROBE_TIMEOUT) -> bool:
    """Check if a TCP connection to the given URL's host:port succeeds.

    Args:
        url: HTTP or HTTPS URL to probe.
        timeout: Connection timeout in seconds.

    Returns:
        True if the connection was accepted, False otherwise.
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            return False
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False
