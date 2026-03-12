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
