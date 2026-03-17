from __future__ import annotations

"""Config Time Machine — browse and restore CLAUDE.md from git history.

Integrates with git to show how CLAUDE.md has evolved over time and lets
users restore any target harness to the config state from any past commit.

Answers 'what was my Gemini config set to two weeks ago when things were
working?' without manually reading git history.

Operations:
    timeline()       — list commits that touched CLAUDE.md with summaries
    show_at()        — show CLAUDE.md content at a specific commit
    diff_between()   — diff CLAUDE.md between two commits
    restore_to()     — re-sync target harnesses from a past CLAUDE.md state
    take_snapshot()  — save a named snapshot of config files (non-git fallback)
    list_snapshots() — list named snapshots
    restore_snapshot() — restore a named snapshot to a temp dir for diffing
"""

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ConfigCommit:
    """A git commit that touched a config file."""

    sha: str           # Short SHA (7 chars)
    full_sha: str      # Full 40-char SHA
    author: str        # Author name
    date: str          # ISO date string (e.g. "2025-03-11")
    subject: str       # Commit subject line
    files_changed: list[str]  # Changed config-related filenames


@dataclass
class RestoreResult:
    """Result of a restore_to() operation."""

    sha: str
    filename: str
    targets_synced: list[str] = field(default_factory=list)
    targets_skipped: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.errors

    def format(self) -> str:
        mode = " [DRY RUN]" if self.dry_run else ""
        lines = [f"Config Time Machine — Restore{mode}", "=" * 50, ""]
        lines.append(f"  Source commit: {self.sha}")
        lines.append(f"  Config file:   {self.filename}")
        lines.append("")
        if self.targets_synced:
            lines.append(f"  Synced ({len(self.targets_synced)}):")
            for t in self.targets_synced:
                prefix = "  (would sync)" if self.dry_run else "  ✓"
                lines.append(f"    {prefix} {t}")
        if self.targets_skipped:
            lines.append(f"  Skipped ({len(self.targets_skipped)}):")
            for t in self.targets_skipped:
                lines.append(f"    - {t}")
        if self.errors:
            lines.append(f"  Errors ({len(self.errors)}):")
            for e in self.errors:
                lines.append(f"    ✗ {e}")
        return "\n".join(lines)


@dataclass
class SnapshotEntry:
    """A named snapshot of config files (non-git fallback)."""
    name: str
    timestamp: str
    files: dict[str, str]   # absolute_path -> content


def _run_git(args: list[str], cwd: Path) -> tuple[str, int]:
    """Run a git command in cwd and return (stdout, returncode)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=10,
        )
        return result.stdout, result.returncode
    except (OSError, subprocess.TimeoutExpired):
        return "", 1


# Config-related filenames to track in git history
_TRACKED_FILES = (
    "CLAUDE.md",
    "CLAUDE.local.md",
    ".claude/CLAUDE.md",
    "SYNC-CHANGELOG.md",
)

# Snapshot store location
_SNAPSHOT_DIR = Path.home() / ".harnesssync" / "snapshots"


class ConfigTimeMachine:
    """Browse and restore CLAUDE.md states from git history.

    Args:
        project_dir: Project root directory (must be a git repository).
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def is_git_repo(self) -> bool:
        """Return True if project_dir is inside a git repository."""
        _, rc = _run_git(["rev-parse", "--git-dir"], self.project_dir)
        return rc == 0

    def timeline(self, max_commits: int = 20) -> list[ConfigCommit]:
        """Return a list of commits that touched CLAUDE.md-related files.

        Args:
            max_commits: Maximum number of commits to return.

        Returns:
            List of ConfigCommit ordered newest-first.
        """
        if not self.is_git_repo():
            return []

        format_str = "%H%x1f%h%x1f%an%x1f%as%x1f%s"
        args = [
            "log",
            f"--max-count={max_commits}",
            f"--format={format_str}",
            "--name-only",
            "--",
            *_TRACKED_FILES,
        ]

        out, rc = _run_git(args, self.project_dir)
        if rc != 0 or not out.strip():
            return []

        commits: list[ConfigCommit] = []
        blocks = out.strip().split("\n\n")

        for block in blocks:
            block = block.strip()
            if not block:
                continue
            block_lines = block.splitlines()
            if not block_lines:
                continue

            header_parts = block_lines[0].split("\x1f")
            if len(header_parts) < 5:
                continue

            full_sha, short_sha, author, date, *subject_parts = header_parts
            subject = "\x1f".join(subject_parts)
            files_changed = [ln.strip() for ln in block_lines[1:] if ln.strip()]

            commits.append(ConfigCommit(
                sha=short_sha.strip(),
                full_sha=full_sha.strip(),
                author=author.strip(),
                date=date.strip(),
                subject=subject.strip(),
                files_changed=files_changed,
            ))

        return commits

    def show_at(self, sha: str, filename: str = "CLAUDE.md") -> str:
        """Return the content of a config file at a specific commit.

        Args:
            sha: Git commit SHA (full or short).
            filename: File path relative to project root.

        Returns:
            File content string, or empty string if not found.
        """
        out, rc = _run_git(["show", f"{sha}:{filename}"], self.project_dir)
        if rc != 0:
            return ""
        return out

    def diff_between(
        self, sha_old: str, sha_new: str = "HEAD", filename: str = "CLAUDE.md"
    ) -> str:
        """Return a unified diff of a config file between two commits.

        Args:
            sha_old: Older commit SHA.
            sha_new: Newer commit SHA (default: HEAD).
            filename: File path relative to project root.

        Returns:
            Unified diff string, or empty string on error.
        """
        out, rc = _run_git(
            ["diff", sha_old, sha_new, "--", filename],
            self.project_dir,
        )
        if rc != 0:
            return ""
        return out

    def restore_to(
        self,
        sha: str,
        filename: str = "CLAUDE.md",
        targets: list[str] | None = None,
        dry_run: bool = False,
        scope: str = "all",
    ) -> RestoreResult:
        """Re-sync all target harnesses from a past CLAUDE.md state.

        Retrieves the file content from git at the given commit SHA, writes it
        to a temporary directory, and runs SyncOrchestrator against it so all
        target harnesses receive the historical config.

        Args:
            sha: Git commit SHA to restore from (short or full).
            filename: Config file to restore (default: "CLAUDE.md").
            targets: Specific targets to restore (None = all configured).
            dry_run: If True, report what would change without writing files.
            scope: Sync scope — "all" | "user" | "project".

        Returns:
            RestoreResult with per-target sync outcomes.
        """
        result = RestoreResult(sha=sha, filename=filename, dry_run=dry_run)

        # Retrieve historical content from git
        historical_content = self.show_at(sha, filename)
        if not historical_content:
            result.errors.append(
                f"Could not retrieve '{filename}' at commit {sha}. "
                "Check that the SHA is valid and the file existed at that commit."
            )
            return result

        with tempfile.TemporaryDirectory(prefix="harnesssync_restore_") as tmpdir:
            tmp_path = Path(tmpdir)

            # Write historical content so SyncOrchestrator can read it
            tmp_claude = tmp_path / Path(filename).name
            tmp_claude.parent.mkdir(parents=True, exist_ok=True)
            tmp_claude.write_text(historical_content, encoding="utf-8")

            if dry_run:
                # List what would be affected without running the sync
                try:
                    from src.adapters import AdapterRegistry
                    reg = AdapterRegistry(project_dir=self.project_dir)
                    all_targets = list(reg.list_targets())
                    sync_targets = [t for t in all_targets if not targets or t in targets]
                    result.targets_synced = sync_targets
                    result.targets_skipped = [t for t in all_targets if t not in sync_targets]
                except Exception as e:
                    result.errors.append(f"Could not enumerate targets: {e}")
                return result

            # Run the orchestrator against the historical content
            try:
                from src.orchestrator import SyncOrchestrator

                orch = SyncOrchestrator(
                    project_dir=self.project_dir,
                    scope=scope,
                    dry_run=False,
                    cc_home=tmp_path,
                    cli_only_targets=set(targets) if targets else set(),
                )

                sync_results = orch.sync_all()

                for target_name, target_result in (sync_results or {}).items():
                    if targets and target_name not in targets:
                        result.targets_skipped.append(target_name)
                        continue
                    success = getattr(target_result, "success", False)
                    if success:
                        result.targets_synced.append(target_name)
                    else:
                        err = getattr(target_result, "error", "unknown error")
                        result.errors.append(f"{target_name}: {err}")

            except Exception as e:
                result.errors.append(f"Sync failed: {e}")

        return result

    def take_snapshot(self, name: str, cc_home: Path | None = None) -> SnapshotEntry:
        """Save a named snapshot of current config files (non-git fallback).

        Captures all tracked config files from project_dir and cc_home and
        stores them in ~/.harnesssync/snapshots/<name>.json. Enables rollback
        even when the project isn't in a git repository.

        Args:
            name: Human-readable snapshot name (e.g. "before-big-change").
            cc_home: Claude Code config directory (default: ~/.claude).

        Returns:
            SnapshotEntry with the saved content.
        """
        cc_home = cc_home or (Path.home() / ".claude")
        files: dict[str, str] = {}

        for base in (self.project_dir, cc_home):
            for tracked in _TRACKED_FILES:
                candidate = base / tracked
                if candidate.is_file():
                    try:
                        content = candidate.read_text(encoding="utf-8", errors="replace")
                        files[str(candidate)] = content
                    except OSError:
                        pass

        timestamp = datetime.now(timezone.utc).isoformat()
        entry = SnapshotEntry(name=name, timestamp=timestamp, files=files)

        _SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        snapshot_file = _SNAPSHOT_DIR / f"{name}.json"
        snapshot_file.write_text(
            json.dumps({"name": name, "timestamp": timestamp, "files": files}, indent=2),
            encoding="utf-8",
        )

        return entry

    def list_snapshots(self) -> list[SnapshotEntry]:
        """List all named snapshots stored on disk.

        Returns:
            List of SnapshotEntry ordered by timestamp (newest first).
        """
        if not _SNAPSHOT_DIR.exists():
            return []

        entries: list[SnapshotEntry] = []
        for f in sorted(_SNAPSHOT_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                entries.append(SnapshotEntry(
                    name=data.get("name", f.stem),
                    timestamp=data.get("timestamp", ""),
                    files=data.get("files", {}),
                ))
            except (json.JSONDecodeError, OSError):
                pass

        return entries

    def restore_snapshot(self, name: str, dest_dir: Path | None = None) -> dict[str, Path]:
        """Restore a named snapshot to a directory for inspection or re-sync.

        Args:
            name: Snapshot name as returned by list_snapshots().
            dest_dir: Destination directory. If None, creates a temp dir (caller
                      is responsible for cleanup).

        Returns:
            Dict mapping original file path -> restored path in dest_dir.
            Empty dict if snapshot not found.
        """
        snapshot_file = _SNAPSHOT_DIR / f"{name}.json"
        if not snapshot_file.exists():
            return {}

        try:
            data = json.loads(snapshot_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

        files = data.get("files", {})
        if not files:
            return {}

        if dest_dir is None:
            dest_dir = Path(tempfile.mkdtemp(prefix=f"harnesssync_snap_{name}_"))

        restored: dict[str, Path] = {}
        for orig_path, content in files.items():
            filename = Path(orig_path).name
            dest_file = dest_dir / filename
            dest_file.write_text(content, encoding="utf-8")
            restored[orig_path] = dest_file

        return restored

    def format_timeline(self, commits: list[ConfigCommit]) -> str:
        """Format a timeline of commits for terminal display."""
        if not commits:
            return (
                "No config-related commits found in git history.\n"
                "Make sure CLAUDE.md is tracked by git."
            )

        lines = [
            "Config Time Machine — CLAUDE.md History",
            "=" * 50,
            "",
            "  SHA      Date        Author           Subject",
            "  " + "-" * 60,
        ]
        for c in commits:
            author = c.author[:14].ljust(15)
            subject = c.subject[:40]
            files = ", ".join(c.files_changed[:3])
            if len(c.files_changed) > 3:
                files += f" (+{len(c.files_changed) - 3})"
            lines.append(f"  {c.sha}  {c.date}  {author}  {subject}")
            if files:
                lines.append(f"           Files: {files}")

        lines.append("")
        lines.append(
            "Tip: Use /sync-restore --from-commit <SHA> to re-apply\n"
            "a past CLAUDE.md state to all harnesses."
        )
        return "\n".join(lines)

    def format_snapshots(self, snapshots: list[SnapshotEntry]) -> str:
        """Format snapshot list for terminal display."""
        if not snapshots:
            return (
                "No snapshots found.\n"
                "Use /sync-restore --take-snapshot <name> to create one."
            )

        lines = [
            "Config Time Machine — Saved Snapshots",
            "=" * 50,
            "",
            f"  {'Name':<30} {'Timestamp':<30} Files",
            "  " + "-" * 70,
        ]
        for s in snapshots:
            ts = s.timestamp[:19].replace("T", " ") if s.timestamp else "unknown"
            file_count = len(s.files)
            lines.append(f"  {s.name:<30} {ts:<30} {file_count}")

        lines.append("")
        lines.append("Tip: Use /sync-restore --from-snapshot <name> to restore.")
        return "\n".join(lines)

    def auto_snapshot_before_sync(
        self,
        cc_home: Path | None = None,
        max_auto_snapshots: int = 50,
    ) -> SnapshotEntry:
        """Take an automatic timestamped snapshot immediately before a sync run.

        Called by the orchestrator at the start of every sync so users can
        roll back to any previous state with a single command, not just the
        most recent one. Old auto-snapshots are pruned once the count exceeds
        ``max_auto_snapshots`` to avoid unbounded disk growth.

        Args:
            cc_home: Claude Code config directory (default: ~/.claude).
            max_auto_snapshots: Maximum number of auto-snapshots to retain.
                                Oldest are deleted when the limit is exceeded.

        Returns:
            SnapshotEntry for the snapshot that was just saved.
        """
        timestamp = datetime.now(timezone.utc)
        # Build a sortable, filesystem-safe name: auto-YYYYMMDD-HHMMSS
        name = "auto-" + timestamp.strftime("%Y%m%d-%H%M%S")
        entry = self.take_snapshot(name, cc_home=cc_home)
        self._prune_auto_snapshots(max_auto_snapshots)
        return entry

    def _prune_auto_snapshots(self, keep: int) -> None:
        """Delete oldest auto-* snapshots beyond the keep limit."""
        if not _SNAPSHOT_DIR.exists():
            return
        auto_files = sorted(
            [f for f in _SNAPSHOT_DIR.glob("auto-*.json")],
            key=lambda p: p.stat().st_mtime,
        )
        excess = auto_files[: max(0, len(auto_files) - keep)]
        for f in excess:
            try:
                f.unlink()
            except OSError:
                pass

    def restore_auto_snapshot(
        self,
        index: int = 0,
        dest_dir: Path | None = None,
    ) -> dict[str, Path]:
        """Restore a specific auto-snapshot by reverse-chronological index.

        Unlike ``restore_snapshot()`` which requires an exact name, this lets
        users say "go back 3 syncs" without knowing the exact timestamp.

        Args:
            index: 0 = most recent auto-snapshot, 1 = second most recent, etc.
            dest_dir: Destination directory. If None, creates a temp dir.

        Returns:
            Dict mapping original file path -> restored path.
            Empty dict if no auto-snapshots exist or index is out of range.
        """
        if not _SNAPSHOT_DIR.exists():
            return {}
        auto_files = sorted(
            [f for f in _SNAPSHOT_DIR.glob("auto-*.json")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if index >= len(auto_files):
            return {}
        snap_name = auto_files[index].stem
        return self.restore_snapshot(snap_name, dest_dir=dest_dir)

    def list_auto_snapshots(self) -> list[SnapshotEntry]:
        """Return all auto-* snapshots ordered newest first."""
        all_snaps = self.list_snapshots()
        return [s for s in all_snaps if s.name.startswith("auto-")]

    def format_visual_timeline(
        self,
        commits: list[ConfigCommit],
        max_width: int = 80,
        show_files: bool = False,
    ) -> str:
        """Render a visual ASCII timeline of config history.

        Produces a branch-style ASCII art timeline showing the chronological
        sequence of commits that touched CLAUDE.md.  Newest commits are at
        the top (most recent first) so the user can see the latest changes
        immediately.

        Example output::

            Config Timeline — CLAUDE.md
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━
            ◉  abc1234  2026-03-13  Add TypeScript rules
            │
            ◉  def5678  2026-03-10  Update MCP server config
            │
            ◉  ghi9012  2026-03-07  Initial CLAUDE.md
            ╵
            3 commit(s) shown

        Args:
            commits:    List from ``timeline()``, newest first.
            max_width:  Maximum terminal width for wrapping subject lines.
            show_files: If True, show changed files below each commit node.

        Returns:
            Formatted ASCII timeline string.
        """
        if not commits:
            return (
                "Config Timeline\n"
                "═══════════════\n\n"
                "  No config-related commits found.\n"
                "  Make sure CLAUDE.md is tracked by git.\n"
            )

        title = "Config Timeline — CLAUDE.md"
        lines: list[str] = [title, "═" * len(title), ""]

        max_subject = max(20, max_width - 35)

        for i, commit in enumerate(commits):
            is_last = i == len(commits) - 1
            node = "◉"
            subject = commit.subject
            if len(subject) > max_subject:
                subject = subject[: max_subject - 1] + "…"

            # Commit node line
            lines.append(f"{node}  {commit.sha}  {commit.date}  {subject}")

            # Optional author
            lines.append(f"│      by {commit.author}")

            # Optional changed files
            if show_files and commit.files_changed:
                for fname in commit.files_changed[:3]:
                    lines.append(f"│      ├─ {fname}")
                if len(commit.files_changed) > 3:
                    lines.append(f"│      └─ … ({len(commit.files_changed) - 3} more)")

            # Connector to next commit (or bottom cap)
            if is_last:
                lines.append("╵")
            else:
                lines.append("│")

        lines.append("")
        noun = "commit" if len(commits) == 1 else "commits"
        lines.append(f"{len(commits)} {noun} shown")
        lines.append("")
        lines.append("Tip: /sync-restore --from-commit <SHA> to roll back a harness.")
        return "\n".join(lines)

    def search_timeline(
        self,
        query: str | None = None,
        since: str | None = None,
        until: str | None = None,
        author: str | None = None,
        file_filter: str | None = None,
        max_commits: int = 50,
    ) -> list[ConfigCommit]:
        """Search the config history by text, date range, author, or file.

        Fetches the full timeline and applies filters client-side so that
        searches work even without a git ``--grep`` flag.

        Args:
            query:       Case-insensitive substring to match against commit
                         subjects.  Matches any part of the subject line.
            since:       ISO date string — include only commits on or after this
                         date (e.g. "2025-01-01").
            until:       ISO date string — include only commits on or before
                         this date (e.g. "2025-06-30").
            author:      Case-insensitive substring to match against author name.
            file_filter: Case-insensitive substring to match against changed
                         filenames (e.g. "skills/" to find skill-related commits).
            max_commits: Maximum commits to fetch from git history before
                         applying filters.

        Returns:
            List of ConfigCommit matching all supplied filters, newest first.

        Example::

            tm = ConfigTimeMachine(Path("."))
            # Find all commits that changed skills in 2026
            results = tm.search_timeline(
                file_filter="skills/",
                since="2026-01-01",
                until="2026-12-31",
            )
        """
        commits = self.timeline(max_commits=max_commits)
        results: list[ConfigCommit] = []

        for c in commits:
            if query and query.lower() not in c.subject.lower():
                continue
            if author and author.lower() not in c.author.lower():
                continue
            if since and c.date < since:
                continue
            if until and c.date > until:
                continue
            if file_filter:
                if not any(file_filter.lower() in f.lower() for f in c.files_changed):
                    continue
            results.append(c)

        return results

    def format_search_results(
        self,
        results: list[ConfigCommit],
        query: str | None = None,
    ) -> str:
        """Format search results as a human-readable summary.

        Args:
            results: Output from :meth:`search_timeline`.
            query:   The search query string (included in header for context).

        Returns:
            Formatted string suitable for terminal display.
        """
        header = "Config Timeline Search"
        if query:
            header += f" — '{query}'"
        lines = [header, "=" * len(header), ""]

        if not results:
            lines.append(
                "  No commits matched your search.\n"
                "  Try a different query, date range, or broaden the file filter."
            )
            return "\n".join(lines)

        for c in results:
            lines.append(f"  {c.sha}  {c.date}  {c.subject}")
            lines.append(f"         by {c.author}")
            if c.files_changed:
                files_str = ", ".join(c.files_changed[:4])
                if len(c.files_changed) > 4:
                    files_str += f" (+{len(c.files_changed) - 4})"
                lines.append(f"         files: {files_str}")
            lines.append("")

        lines.append(f"{len(results)} match(es) found.")
        lines.append("Tip: /sync-restore --from-commit <SHA> to restore any version.")
        return "\n".join(lines)
