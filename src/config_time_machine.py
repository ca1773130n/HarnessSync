from __future__ import annotations

"""Config Time Machine — browse and restore CLAUDE.md from git history.

Integrates with git to show how CLAUDE.md has evolved over time and lets
users restore any target harness to the config state from any past commit.

Answers 'what was my Gemini config set to two weeks ago when things were
working?' without manually reading git history.

Operations:
    timeline()      — list commits that touched CLAUDE.md with summaries
    show_at()       — show CLAUDE.md content at a specific commit
    diff_between()  — diff CLAUDE.md between two commits
    restore_to()    — re-sync target harnesses from a past CLAUDE.md state
"""

import subprocess
from dataclasses import dataclass
from datetime import datetime
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


def _run_git(args: list[str], cwd: Path) -> tuple[str, int]:
    """Run a git command in cwd and return (stdout, returncode).

    Args:
        args: Git arguments (without the 'git' binary name).
        cwd: Working directory.

    Returns:
        (stdout_text, returncode) tuple. stdout is empty string on error.
    """
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

        # Build file filter for git log
        format_str = "%H%x1f%h%x1f%an%x1f%as%x1f%s"  # full_sha, short_sha, author, date, subject
        args = [
            "log",
            f"--max-count={max_commits}",
            f"--format={format_str}",
            "--name-only",  # Include changed filenames
            "--",
            *_TRACKED_FILES,
        ]

        out, rc = _run_git(args, self.project_dir)
        if rc != 0 or not out.strip():
            return []

        commits: list[ConfigCommit] = []
        # Git log with --name-only outputs: header block, blank line, filenames, blank line, ...
        blocks = out.strip().split("\n\n")

        for block in blocks:
            block = block.strip()
            if not block:
                continue
            block_lines = block.splitlines()
            if not block_lines:
                continue

            # First line is the formatted header (split by \x1f)
            header_parts = block_lines[0].split("\x1f")
            if len(header_parts) < 5:
                continue

            full_sha, short_sha, author, date, *subject_parts = header_parts
            subject = "\x1f".join(subject_parts)  # Rejoin in case subject had \x1f
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

    def format_timeline(self, commits: list[ConfigCommit]) -> str:
        """Format a timeline of commits for terminal display.

        Args:
            commits: Output of timeline().

        Returns:
            Formatted string.
        """
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
