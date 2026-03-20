from __future__ import annotations

"""Drift enforcement: ZeroDriftGuarantee, SourceChangeWatcher, and guided merge.

This module contains the enforcement and resolution mechanisms for drift:
- ZeroDriftGuarantee: strict mode that auto-reverts external edits
- SourceChangeWatcher: monitors source files and triggers auto-sync on change
- Guided merge: interactive resolution of drift conflicts
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable

from src.state_manager import StateManager
from src.utils.hashing import hash_file_sha256
from src.utils.logger import Logger


# ---------------------------------------------------------------------------
# Zero-Drift Guarantee Mode (item 21)
# ---------------------------------------------------------------------------

class ZeroDriftGuarantee:
    """Strict mode that detects and reverts external edits to synced config files.

    When enabled, HarnessSync watches synced output files and immediately
    reverts any change made by a tool other than HarnessSync itself.  The
    revert is performed by re-writing the last-synced content stored in the
    state snapshot.

    This gives power users an iron guarantee: secondary harness configs are
    always byte-for-byte identical to the last sync output.

    Usage::

        guarantee = ZeroDriftGuarantee(project_dir=Path("."))
        guarantee.enable()   # begins watching in a background thread
        guarantee.disable()  # stops the watcher

        # Check status without starting a thread:
        violations = guarantee.scan_once()
    """

    _POLL_INTERVAL: float = 2.0
    _REVERT_LOG_MAX: int = 100

    def __init__(
        self,
        project_dir: Path | None = None,
        state_manager: StateManager | None = None,
        logger: Logger | None = None,
    ) -> None:
        self._project_dir = project_dir or Path.cwd()
        self._sm = state_manager or StateManager()
        self._logger = logger or Logger()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._revert_log: list[dict] = []

    def enable(self) -> None:
        """Start the background file watcher that reverts external edits."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="ZeroDriftGuarantee",
            daemon=True,
        )
        self._thread.start()
        self._logger.info("ZeroDriftGuarantee enabled \u2014 external edits will be reverted.")

    def disable(self) -> None:
        """Stop the background file watcher."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._logger.info("ZeroDriftGuarantee disabled.")

    @property
    def active(self) -> bool:
        """True if the background watcher is currently running."""
        return bool(self._thread and self._thread.is_alive())

    def scan_once(self) -> list[dict]:
        """Perform a single drift scan without reverting.

        Returns:
            List of violation dicts with keys:
              ``file_path``, ``expected_hash``, ``actual_hash``, ``reverted``.
        """
        return self._check_files(revert=False)

    def revert_violations(self) -> list[dict]:
        """Detect and revert all external edits to synced files.

        Returns:
            List of reverted violation dicts.
        """
        return self._check_files(revert=True)

    @property
    def revert_log(self) -> list[dict]:
        """Return the in-memory revert log (most recent first)."""
        return list(reversed(self._revert_log))

    def format_status(self) -> str:
        """Return a human-readable status string."""
        status = "active" if self.active else "inactive"
        reverts = len(self._revert_log)
        lines = [
            f"Zero-Drift Guarantee Mode: {status.upper()}",
            f"  Reverts applied this session: {reverts}",
        ]
        if self._revert_log:
            last = self._revert_log[-1]
            lines.append(f"  Last revert: {last.get('file_path', '?')} at {last.get('timestamp', '?')}")
        lines.append("")
        lines.append(
            "All synced config files are protected. External edits are reverted automatically."
            if self.active
            else "Run /sync with --zero-drift to enable protection."
        )
        return "\n".join(lines)

    def _watch_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_files(revert=True)
            except Exception as exc:
                self._logger.warning(f"ZeroDriftGuarantee scan error: {exc}")
            self._stop_event.wait(self._POLL_INTERVAL)

    def _check_files(self, revert: bool) -> list[dict]:
        """Check all tracked files for drift and optionally revert them."""
        state = self._sm.load_state()
        violations: list[dict] = []

        for target_name, target_data in state.get("targets", {}).items():
            snapshots: dict[str, str] = target_data.get("file_content_snapshots", {})
            file_hashes: dict[str, str] = target_data.get("file_hashes", {})

            for file_path_str, stored_hash in file_hashes.items():
                file_path = Path(file_path_str)
                if not file_path.exists():
                    continue

                current_hash = hash_file_sha256(file_path) or ""
                if current_hash == stored_hash:
                    continue

                violation: dict = {
                    "target": target_name,
                    "file_path": file_path_str,
                    "expected_hash": stored_hash,
                    "actual_hash": current_hash,
                    "reverted": False,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }

                if revert and file_path_str in snapshots:
                    try:
                        file_path.write_text(snapshots[file_path_str], encoding="utf-8")
                        violation["reverted"] = True
                        self._logger.warning(
                            f"ZeroDriftGuarantee: reverted external edit to {file_path_str}"
                        )
                    except OSError as exc:
                        self._logger.error(
                            f"ZeroDriftGuarantee: failed to revert {file_path_str}: {exc}"
                        )

                violations.append(violation)
                self._revert_log.append(violation)
                if len(self._revert_log) > self._REVERT_LOG_MAX:
                    self._revert_log = self._revert_log[-self._REVERT_LOG_MAX :]

        return violations


# ---------------------------------------------------------------------------
# Item 27 \u2014 Source Change Watcher (Auto-Sync on File Save)
# ---------------------------------------------------------------------------
#
# Unlike DriftWatcher which monitors target harness outputs for external edits,
# SourceChangeWatcher monitors the Claude Code *source* files (CLAUDE.md,
# .claude/) for changes and triggers an auto-sync callback when they change.
# This provides the "sync within seconds of any CLAUDE.md or .claude/ file
# change" UX described in the feature spec.


class SourceChangeWatcher:
    """Watch Claude Code source files and auto-trigger sync on change.

    Monitors ``CLAUDE.md`` and the ``.claude/`` directory (rules, skills,
    agents, commands, settings) for file content changes. When a change is
    detected the ``sync_callback`` is called so the caller can run a sync.

    Internally hashes each watched file; when a hash changes, the file is
    included in the change notification passed to the callback.

    Usage::

        def my_sync(changed_files):
            print(f"Changed: {changed_files}")
            # ... run orchestrator.sync_all() ...

        watcher = SourceChangeWatcher(project_dir, sync_callback=my_sync)
        watcher.start()          # non-blocking background thread
        watcher.watch_blocking() # or blocking until Ctrl-C
        watcher.stop()
    """

    # Source paths watched by default (relative to project_dir)
    DEFAULT_SOURCE_PATHS: list[str] = [
        "CLAUDE.md",
        ".claude/CLAUDE.md",
        ".claude/rules",
        ".claude/skills",
        ".claude/agents",
        ".claude/commands",
        ".claude/settings.json",
        ".mcp.json",
    ]

    def __init__(
        self,
        project_dir: Path,
        sync_callback: Callable[[list[str]], None],
        poll_interval: float = 2.0,
        extra_paths: list[str] | None = None,
        debounce_seconds: float = 1.0,
    ):
        """Initialise the source change watcher.

        Args:
            project_dir: Project root directory (base for relative source paths).
            sync_callback: Called with a list of changed file paths (relative to
                           project_dir) when one or more source files change.
            poll_interval: Seconds between each file check (default: 2.0).
            extra_paths: Additional paths/directories to watch.
            debounce_seconds: Minimum seconds between successive auto-sync calls.
                              Prevents rapid-fire syncs when an editor saves many
                              files at once (default: 1.0).
        """
        self.project_dir = project_dir
        self.sync_callback = sync_callback
        self.poll_interval = poll_interval
        self.debounce_seconds = debounce_seconds

        watched = list(self.DEFAULT_SOURCE_PATHS)
        if extra_paths:
            watched.extend(extra_paths)
        self._watch_paths: list[str] = watched

        # File hash snapshot: relative_path -> hash string
        self._hashes: dict[str, str] = {}
        self._last_sync_time: float = 0.0

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

        # Take initial snapshot
        self._snapshot()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start background source-change polling (non-blocking)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="harnesssync-source-watcher",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the watcher to stop and wait for its thread to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_interval + 2)
            self._thread = None

    def is_running(self) -> bool:
        """Return True if the watcher thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def watch_blocking(self) -> None:
        """Run source-change detection in the current thread until interrupted.

        Blocks until KeyboardInterrupt (Ctrl-C) or ``stop()`` is called from
        another thread.
        """
        print("HarnessSync Source Watcher \u2014 monitoring CLAUDE.md and .claude/ for changes...")
        print(f"Poll interval: {self.poll_interval}s  |  Press Ctrl-C to stop\n")
        try:
            while not self._stop_event.is_set():
                self._check_once()
                self._stop_event.wait(timeout=self.poll_interval)
        except KeyboardInterrupt:
            print("\nSource watcher stopped.")

    def check_and_sync(self) -> list[str]:
        """Run a single check and trigger sync if anything changed.

        Can be called manually (e.g. from a git hook) without starting
        the background thread.

        Returns:
            List of changed file paths that triggered the sync, or empty
            list if nothing changed.
        """
        return self._check_once()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _collect_paths(self) -> list[Path]:
        """Expand watch_paths to concrete file paths that exist."""
        paths: list[Path] = []
        for rel in self._watch_paths:
            p = self.project_dir / rel
            if p.is_file():
                paths.append(p)
            elif p.is_dir():
                # Recursively include all files in the directory
                for child in sorted(p.rglob("*")):
                    if child.is_file():
                        paths.append(child)
        return paths

    def _snapshot(self) -> None:
        """Take a fresh hash snapshot of all watched files."""
        with self._lock:
            new_hashes: dict[str, str] = {}
            for path in self._collect_paths():
                try:
                    rel = str(path.relative_to(self.project_dir))
                except ValueError:
                    rel = str(path)
                h = hash_file_sha256(path) or ""
                new_hashes[rel] = h
            self._hashes = new_hashes

    def _check_once(self) -> list[str]:
        """Check for changes and trigger sync_callback if needed.

        Returns:
            List of changed relative file paths.
        """
        changed: list[str] = []

        with self._lock:
            for path in self._collect_paths():
                try:
                    rel = str(path.relative_to(self.project_dir))
                except ValueError:
                    rel = str(path)
                current_hash = hash_file_sha256(path) or ""
                stored_hash = self._hashes.get(rel, "")
                if current_hash != stored_hash:
                    changed.append(rel)
                    self._hashes[rel] = current_hash

            # Also detect newly-created files not in previous snapshot
            for path in self._collect_paths():
                try:
                    rel = str(path.relative_to(self.project_dir))
                except ValueError:
                    rel = str(path)
                if rel not in self._hashes:
                    current_hash = hash_file_sha256(path) or ""
                    self._hashes[rel] = current_hash
                    changed.append(rel)

        if not changed:
            return []

        # Debounce: avoid rapid-fire syncs
        now = time.time()
        if now - self._last_sync_time < self.debounce_seconds:
            return changed  # Changed detected but not triggering sync yet

        self._last_sync_time = now
        try:
            self.sync_callback(changed)
        except Exception:
            pass  # Don't let sync errors crash the watcher thread

        return changed

    def _poll_loop(self) -> None:
        """Background thread loop."""
        while not self._stop_event.is_set():
            try:
                self._check_once()
            except Exception:
                pass
            self._stop_event.wait(timeout=self.poll_interval)


# ---------------------------------------------------------------------------
# Guided merge \u2014 item 10 (Drift Detection with Guided Merge)
# ---------------------------------------------------------------------------


class MergeChoice(Enum):
    """User's resolution choice from guided_merge_prompt()."""
    SYNC_WINS = "sync"       # Overwrite with HarnessSync content
    KEEP_MANUAL = "keep"     # Keep the manual edits as a harness-specific override
    SKIP = "skip"            # Do nothing for now


@dataclass
class GuidedMergeResult:
    """Result of a guided merge interaction."""
    target: str
    file_path: str
    choice: MergeChoice
    override_saved: bool = False  # True if manual edit was saved as an override
    override_path: str = ""       # Path to saved override file (if kept)


def _show_drift_diff(
    source_content: str,
    current_content: str,
    file_label: str,
    max_lines: int = 30,
) -> None:
    """Print a compact unified diff showing what the user manually changed."""
    import difflib as _difflib

    source_lines = source_content.splitlines(keepends=True)
    current_lines = current_content.splitlines(keepends=True)
    diff = list(_difflib.unified_diff(
        source_lines,
        current_lines,
        fromfile=f"harnesssync/{file_label}",
        tofile=f"manual/{file_label}",
        lineterm="",
        n=2,
    ))
    if not diff:
        print(f"  (no text differences detected in {file_label})")
        return

    printed = 0
    for line in diff:
        if printed >= max_lines:
            remaining = len(diff) - max_lines
            print(f"  ... ({remaining} more diff lines)")
            break
        if line.startswith("+") and not line.startswith("+++"):
            print(f"  \033[32m{line}\033[0m")  # green
        elif line.startswith("-") and not line.startswith("---"):
            print(f"  \033[31m{line}\033[0m")  # red
        else:
            print(f"  {line}")
        printed += 1


def guided_merge_prompt(
    target: str,
    file_path: str,
    source_content: str,
    current_content: str,
    project_dir: Path | None = None,
    non_interactive: bool = False,
) -> GuidedMergeResult:
    """Interactively resolve a drift conflict between HarnessSync and manual edits.

    Shows the user exactly what they changed in the target config (diff),
    then offers three choices:
      1. Let sync win  \u2014 overwrite manual edits on next sync
      2. Keep changes  \u2014 save manual edits as a harness-specific override
                         in .harnesssync-overrides/<target>/ so they survive
                         future syncs
      3. Skip for now  \u2014 do nothing (drift remains)

    Args:
        target: Canonical harness name (e.g. "codex").
        file_path: Absolute path to the drifted config file.
        source_content: Last-synced content (the HarnessSync version).
        current_content: Current on-disk content (with manual edits).
        project_dir: Project root (for saving overrides). Defaults to cwd.
        non_interactive: If True, skip the prompt and default to SKIP.

    Returns:
        GuidedMergeResult describing what was chosen and what was done.
    """
    import sys as _sys

    result = GuidedMergeResult(
        target=target,
        file_path=file_path,
        choice=MergeChoice.SKIP,
    )

    separator = "\u2500" * 60
    print(f"\n{separator}")
    print(f"Drift detected in {target}: {file_path}")
    print(separator)
    print("Your manual changes vs. the last HarnessSync version:\n")
    _show_drift_diff(source_content, current_content, file_path)
    print()

    if non_interactive or not _sys.stdin.isatty():
        print(f"[non-interactive] Defaulting to SKIP for {target}.")
        return result

    print("How would you like to resolve this?")
    print("  [1] Let sync win     \u2014 overwrite on next /sync (manual edits lost)")
    print("  [2] Keep my changes  \u2014 save as a harness-specific override")
    print("  [3] Skip for now     \u2014 leave as-is (drift remains)")
    print()

    try:
        answer = input("Choice [1/2/3, default=3]: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted \u2014 defaulting to skip.")
        return result

    if answer == "1":
        result.choice = MergeChoice.SYNC_WINS
        print(f"\u2713 Marked: sync will overwrite {target} config on next /sync.")

    elif answer == "2":
        result.choice = MergeChoice.KEEP_MANUAL
        # Save the manual edits as a harness-specific override
        proj = Path(project_dir) if project_dir else Path.cwd()
        override_dir = proj / ".harnesssync-overrides" / target
        override_dir.mkdir(parents=True, exist_ok=True)
        override_file = override_dir / Path(file_path).name
        try:
            override_file.write_text(current_content, encoding="utf-8")
            result.override_saved = True
            result.override_path = str(override_file)
            print(f"\u2713 Manual edits saved to: {override_file}")
            print(
                f"  HarnessSync will merge this override on future syncs.\n"
                f"  Commit .harnesssync-overrides/ to share with your team."
            )
        except OSError as e:
            print(f"  Warning: could not save override: {e}")

    else:
        print(f"  Skipping \u2014 drift in {target} remains. Run /sync to overwrite.")

    return result
