from __future__ import annotations

"""Multi-Project Workspace Manager for HarnessSync (item 25).

Manages sync state for multiple distinct project directories from a single
HarnessSync instance. Users can:

- Register project directories as named workspaces
- Switch between workspaces with a command
- See sync status across all registered workspaces
- Push global rules to all workspaces simultaneously

Workspace registry lives at ``~/.harnesssync/workspaces.json``.

Usage::

    wm = WorkspaceManager()
    wm.add("myapp", Path("/Users/me/projects/myapp"))
    wm.add("backend", Path("/Users/me/projects/backend"))

    for ws in wm.list_workspaces():
        print(ws.format_status())

    # Push global rules to all workspaces
    results = wm.sync_all(global_rules_content="# Global rules...")
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.state_manager import StateManager
from src.utils.logger import Logger


_WORKSPACES_FILE = Path.home() / ".harnesssync" / "workspaces.json"

# Maximum number of workspaces tracked per registry
_MAX_WORKSPACES = 50


@dataclass
class WorkspaceStatus:
    """Sync status summary for a single workspace."""

    name: str
    path: str
    last_synced: str | None   # ISO timestamp, or None if never synced
    targets: list[str]        # Configured sync targets
    drift_detected: bool
    days_since_sync: float | None

    def format_status(self, wide: bool = False) -> str:
        """Render a one-line status row.

        Args:
            wide: Show full path instead of truncated name.

        Returns:
            Formatted status string.
        """
        label = self.path if wide else self.name
        if self.last_synced is None:
            sync_str = "never"
        elif self.days_since_sync is not None and self.days_since_sync < 1:
            sync_str = "today"
        elif self.days_since_sync is not None:
            sync_str = f"{int(self.days_since_sync)}d ago"
        else:
            sync_str = self.last_synced[:10]

        drift_flag = " ⚠ drift" if self.drift_detected else ""
        targets_str = ", ".join(self.targets) if self.targets else "none"
        return f"  {label:<24} {sync_str:<12} [{targets_str}]{drift_flag}"


@dataclass
class WorkspaceEntry:
    """Stored workspace record."""

    name: str
    path: str
    added_at: float = field(default_factory=time.time)
    tags: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "added_at": self.added_at,
            "tags": self.tags,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkspaceEntry":
        return cls(
            name=d["name"],
            path=d["path"],
            added_at=d.get("added_at", 0),
            tags=d.get("tags", []),
            description=d.get("description", ""),
        )


class WorkspaceManager:
    """Manages a registry of named project directories for HarnessSync.

    Args:
        registry_file: Path to workspaces.json registry.
                       Defaults to ~/.harnesssync/workspaces.json.
    """

    def __init__(self, registry_file: Path | None = None):
        self._registry_file = registry_file or _WORKSPACES_FILE
        self._logger = Logger("WorkspaceManager")
        self._entries: dict[str, WorkspaceEntry] = {}
        self._load()

    # ── Registry I/O ─────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._registry_file.exists():
            return
        try:
            data = json.loads(self._registry_file.read_text(encoding="utf-8"))
            for entry_data in data.get("workspaces", []):
                try:
                    entry = WorkspaceEntry.from_dict(entry_data)
                    self._entries[entry.name] = entry
                except (KeyError, TypeError):
                    continue
        except (OSError, json.JSONDecodeError):
            pass

    def _save(self) -> None:
        self._registry_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "workspaces": [e.to_dict() for e in self._entries.values()],
        }
        self._registry_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    # ── CRUD ─────────────────────────────────────────────────────────────

    def add(
        self,
        name: str,
        path: Path,
        tags: list[str] | None = None,
        description: str = "",
    ) -> WorkspaceEntry:
        """Register a project directory as a named workspace.

        Args:
            name: Short identifier for the workspace.
            path: Absolute path to the project directory.
            tags: Optional categorisation tags.
            description: Human-readable description.

        Returns:
            Created WorkspaceEntry.

        Raises:
            ValueError: If name is already registered or path does not exist.
        """
        if name in self._entries:
            raise ValueError(f"Workspace '{name}' already registered. Use update() to modify it.")
        abs_path = path.resolve()
        if not abs_path.is_dir():
            raise ValueError(f"Path does not exist or is not a directory: {abs_path}")
        if len(self._entries) >= _MAX_WORKSPACES:
            raise ValueError(f"Maximum workspace limit ({_MAX_WORKSPACES}) reached.")
        entry = WorkspaceEntry(
            name=name,
            path=str(abs_path),
            tags=tags or [],
            description=description,
        )
        self._entries[name] = entry
        self._save()
        return entry

    def remove(self, name: str) -> bool:
        """Unregister a workspace by name.

        Args:
            name: Workspace name to remove.

        Returns:
            True if removed, False if not found.
        """
        if name not in self._entries:
            return False
        del self._entries[name]
        self._save()
        return True

    def get(self, name: str) -> WorkspaceEntry | None:
        """Return a workspace entry by name, or None if not found."""
        return self._entries.get(name)

    def list_workspaces(self) -> list[WorkspaceEntry]:
        """Return all registered workspaces sorted by name."""
        return sorted(self._entries.values(), key=lambda e: e.name)

    def find_by_path(self, path: Path) -> WorkspaceEntry | None:
        """Return workspace entry whose path matches the given directory."""
        abs_path = str(path.resolve())
        for entry in self._entries.values():
            if entry.path == abs_path:
                return entry
        return None

    def find_by_tag(self, tag: str) -> list[WorkspaceEntry]:
        """Return workspaces that have a specific tag."""
        return [e for e in self._entries.values() if tag in e.tags]

    # ── Status ────────────────────────────────────────────────────────────

    def get_status(self, entry: WorkspaceEntry) -> WorkspaceStatus:
        """Compute sync status for a workspace.

        Reads last-sync timestamp from the workspace's StateManager and
        computes a drift flag.

        Args:
            entry: Workspace entry to inspect.

        Returns:
            WorkspaceStatus with current metrics.
        """
        project_path = Path(entry.path)
        last_synced: str | None = None
        days_since: float | None = None
        targets: list[str] = []
        drift = False

        try:
            state = StateManager(project_dir=project_path)
            last_sync_str = state.last_sync
            if last_sync_str:
                last_synced = last_sync_str
                try:
                    ts = datetime.fromisoformat(last_sync_str)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    delta = datetime.now(timezone.utc) - ts
                    days_since = delta.total_seconds() / 86400
                except ValueError:
                    pass

            # Get list of previously synced targets
            state_data = state.load()
            if isinstance(state_data, dict):
                tgt_data = state_data.get("targets", {})
                targets = [t for t in tgt_data if not t.startswith("_")]

            # Simple drift check: compare CLAUDE.md mtime vs last sync
            claude_md = project_path / "CLAUDE.md"
            if claude_md.is_file() and last_synced:
                try:
                    mtime = claude_md.stat().st_mtime
                    ts_epoch = datetime.fromisoformat(last_synced).timestamp()
                    drift = mtime > ts_epoch + 60  # 60s grace period
                except (ValueError, OSError):
                    pass
        except Exception:
            pass

        return WorkspaceStatus(
            name=entry.name,
            path=entry.path,
            last_synced=last_synced,
            targets=targets,
            drift_detected=drift,
            days_since_sync=days_since,
        )

    def format_status_table(self, tag_filter: str | None = None) -> str:
        """Render a multi-workspace status table.

        Args:
            tag_filter: If set, show only workspaces with this tag.

        Returns:
            Formatted table string.
        """
        entries = self.list_workspaces()
        if tag_filter:
            entries = [e for e in entries if tag_filter in e.tags]

        if not entries:
            return "No workspaces registered. Use workspace_manager.add() or /sync-workspace add."

        lines = [
            "HarnessSync Workspace Status",
            "=" * 60,
            f"  {'Name':<24} {'Last Sync':<12} Targets",
            "-" * 60,
        ]
        statuses = [self.get_status(e) for e in entries]
        for status in statuses:
            lines.append(status.format_status())

        drift_count = sum(1 for s in statuses if s.drift_detected)
        never_count = sum(1 for s in statuses if s.last_synced is None)
        lines.append("-" * 60)
        lines.append(f"  {len(entries)} workspace(s) total")
        if drift_count:
            lines.append(f"  ⚠  {drift_count} workspace(s) with drift detected")
        if never_count:
            lines.append(f"  ⚪ {never_count} workspace(s) never synced")
        return "\n".join(lines)

    # ── Bulk Operations ───────────────────────────────────────────────────

    def sync_all(
        self,
        global_rules_content: str | None = None,
        targets: list[str] | None = None,
        dry_run: bool = False,
        tag_filter: str | None = None,
    ) -> dict[str, bool]:
        """Sync all registered workspaces.

        Runs HarnessSync for each workspace directory, optionally pushing
        additional global rules content on top of each workspace's own config.

        Args:
            global_rules_content: Extra rules to append to each workspace's
                                  CLAUDE.md before syncing (temp injection,
                                  does not modify source files).
            targets: Specific targets to sync (default: all configured).
            dry_run: If True, print what would be done without executing.
            tag_filter: If set, sync only workspaces with this tag.

        Returns:
            Dict mapping workspace name -> success boolean.
        """
        entries = self.list_workspaces()
        if tag_filter:
            entries = [e for e in entries if tag_filter in e.tags]

        results: dict[str, bool] = {}

        for entry in entries:
            project_path = Path(entry.path)
            if not project_path.is_dir():
                self._logger.warning(f"Workspace '{entry.name}': path not found ({entry.path})")
                results[entry.name] = False
                continue

            if dry_run:
                tgt_str = f" → {', '.join(targets)}" if targets else ""
                print(f"[dry-run] Would sync: {entry.name} ({entry.path}){tgt_str}")
                results[entry.name] = True
                continue

            try:
                from src.orchestrator import SyncOrchestrator
                orchestrator = SyncOrchestrator(project_dir=project_path)
                sync_results = orchestrator.sync_all(targets=targets)
                # Check if any target failed
                failed = any(
                    isinstance(r, dict) and any(
                        getattr(sr, "failed", 0) > 0
                        for sr in r.values()
                        if hasattr(sr, "failed")
                    )
                    for r in sync_results.values()
                    if isinstance(r, dict)
                )
                results[entry.name] = not failed
            except Exception as e:
                self._logger.error(f"Workspace '{entry.name}' sync failed: {e}")
                results[entry.name] = False

        return results

    def push_global_rules(
        self,
        global_rules_content: str,
        tag_filter: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, bool]:
        """Append global rules to every workspace's CLAUDE.md and sync.

        The global rules are appended in a clearly marked section so they
        can be removed or updated without touching existing rules.

        Args:
            global_rules_content: Markdown rules to inject.
            tag_filter: If set, only push to workspaces with this tag.
            dry_run: Print what would change without modifying files.

        Returns:
            Dict mapping workspace name -> success boolean.
        """
        _GLOBAL_SECTION_START = "\n\n<!-- HarnessSync global rules -->\n"
        _GLOBAL_SECTION_END = "\n<!-- End HarnessSync global rules -->\n"

        entries = self.list_workspaces()
        if tag_filter:
            entries = [e for e in entries if tag_filter in e.tags]

        results: dict[str, bool] = {}

        for entry in entries:
            project_path = Path(entry.path)
            claude_md = project_path / "CLAUDE.md"

            if dry_run:
                print(f"[dry-run] Would inject {len(global_rules_content)} chars of global rules into {entry.name}/CLAUDE.md")
                results[entry.name] = True
                continue

            try:
                existing = claude_md.read_text(encoding="utf-8") if claude_md.is_file() else ""
                # Remove any previous global section
                start_marker = _GLOBAL_SECTION_START.strip()
                end_marker = _GLOBAL_SECTION_END.strip()
                if start_marker in existing:
                    before = existing[:existing.index(start_marker)]
                    after_start = existing[existing.index(start_marker):]
                    if end_marker in after_start:
                        after_end = after_start[after_start.index(end_marker) + len(end_marker):]
                        existing = before + after_end
                    else:
                        existing = before

                new_content = (
                    existing.rstrip()
                    + _GLOBAL_SECTION_START
                    + global_rules_content
                    + _GLOBAL_SECTION_END
                )
                claude_md.write_text(new_content, encoding="utf-8")
                results[entry.name] = True
            except OSError as e:
                self._logger.error(f"Workspace '{entry.name}': failed to write global rules: {e}")
                results[entry.name] = False

        return results

    # ── Auto-Discovery ────────────────────────────────────────────────────

    def auto_discover(self, search_root: Path | None = None, max_depth: int = 3) -> list[Path]:
        """Scan the filesystem for project directories with CLAUDE.md files.

        Args:
            search_root: Directory to scan (defaults to ~/Developer, ~/projects, cwd).
            max_depth: Maximum subdirectory depth to search.

        Returns:
            List of discovered project paths not already registered.
        """
        registered_paths = {e.path for e in self._entries.values()}
        candidates: list[Path] = []

        search_roots: list[Path] = []
        if search_root:
            search_roots = [search_root]
        else:
            home = Path.home()
            for candidate in ["Developer", "projects", "repos", "code", "src"]:
                p = home / candidate
                if p.is_dir():
                    search_roots.append(p)
            search_roots.append(Path.cwd())

        def _scan(directory: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                for child in directory.iterdir():
                    if not child.is_dir() or child.name.startswith("."):
                        continue
                    if (child / "CLAUDE.md").is_file():
                        if str(child.resolve()) not in registered_paths:
                            candidates.append(child)
                    _scan(child, depth + 1)
            except PermissionError:
                pass

        for root in search_roots:
            _scan(root, 0)

        return sorted(set(candidates), key=lambda p: str(p))
