from __future__ import annotations

"""Dotfile manager integration for HarnessSync.

Generates HarnessSync-aware stanzas for popular dotfile managers so that
synced harness configurations are tracked in the user's dotfile repository.

Supported dotfile managers:
- chezmoi: Generates chezmoi source path entries for each synced target file
- yadm: Lists files as tracked paths for yadm add
- dotbot: Generates a link block for dotbot config (install.conf.yaml)
- bare git repo: Generic list of paths to git add

Also provides DotfilesAutoCommitter: after each successful sync, optionally
commit the changed target configs to a designated dotfiles git repo with a
structured commit message (item 2).
"""

import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# Known synced output files per target (relative to project_dir)
# Grouped by those that are project-specific vs user-global
_TARGET_PROJECT_FILES: dict[str, list[str]] = {
    "codex": ["AGENTS.md", ".codex/config.toml"],
    "gemini": ["GEMINI.md", ".gemini/settings.json"],
    "opencode": ["OPENCODE.md", ".opencode/settings.json"],
    "cursor": [".cursor/rules/claude-code-rules.mdc", ".cursor/mcp.json"],
    "aider": ["CONVENTIONS.md", ".aider.conf.yml"],
    "windsurf": [".windsurfrules"],
    "cline": [".clinerules", ".roo/mcp.json"],
    "continue": [".continue/rules/harnesssync.md", ".continue/config.json"],
    "zed": [".zed/system-prompt.md", ".zed/settings.json"],
    "neovim": [".avante/system-prompt.md", ".codecompanion/system-prompt.md", ".avante/mcp.json"],
}

# Files that are user-global (in $HOME, not project-specific)
# chezmoi/yadm track these differently
_USER_GLOBAL_FILE_PATTERNS: list[str] = [
    ".codex/config.toml",
    ".aider.conf.yml",
]


@dataclass
class DotfileStanza:
    """A generated dotfile manager stanza."""
    manager: str        # "chezmoi" | "yadm" | "dotbot" | "bare-git"
    content: str        # The stanza text to add to dotfile config
    instructions: str   # Human-readable usage instructions


@dataclass
class DotfileIntegrationReport:
    """Report containing stanzas for all requested dotfile managers."""
    stanzas: list[DotfileStanza] = field(default_factory=list)
    tracked_files: list[str] = field(default_factory=list)

    def format(self) -> str:
        """Format all stanzas as a human-readable guide."""
        lines = ["## HarnessSync Dotfile Manager Integration", ""]
        lines.append(
            "Add these stanzas to your dotfile manager to track synced "
            "HarnessSync configs on new machines.\n"
        )
        lines.append(f"Tracked files ({len(self.tracked_files)}):")
        for f in self.tracked_files:
            lines.append(f"  {f}")
        lines.append("")

        for stanza in self.stanzas:
            lines.append(f"### {stanza.manager.upper()}")
            lines.append("")
            lines.append(stanza.instructions)
            lines.append("")
            lines.append("```")
            lines.append(stanza.content)
            lines.append("```")
            lines.append("")

        return "\n".join(lines)


class DotfileIntegrationGenerator:
    """Generates dotfile manager integration stanzas for HarnessSync.

    Args:
        project_dir: Project root directory.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def generate(
        self,
        managers: list[str] = None,
        targets: list[str] = None,
    ) -> DotfileIntegrationReport:
        """Generate dotfile manager stanzas.

        Args:
            managers: Dotfile managers to generate for. Defaults to all known:
                      ["chezmoi", "yadm", "dotbot", "bare-git"].
            targets: Targets to include files for (None = auto-detect from disk).

        Returns:
            DotfileIntegrationReport with stanzas and tracked file list.
        """
        if managers is None:
            managers = ["chezmoi", "yadm", "dotbot", "bare-git"]

        if targets is None:
            targets = self._detect_active_targets()

        # Collect all tracked files
        tracked_files = self._collect_tracked_files(targets)

        report = DotfileIntegrationReport(tracked_files=tracked_files)

        for manager in managers:
            stanza = self._generate_stanza(manager, tracked_files)
            if stanza:
                report.stanzas.append(stanza)

        return report

    def _detect_active_targets(self) -> list[str]:
        """Detect targets that have been synced by checking for output files."""
        active = []
        for target, files in _TARGET_PROJECT_FILES.items():
            for rel in files:
                if (self.project_dir / rel).is_file():
                    active.append(target)
                    break
        return active

    def _collect_tracked_files(self, targets: list[str]) -> list[str]:
        """Collect all synced output file paths that exist on disk."""
        files = []
        seen = set()
        for target in targets:
            for rel in _TARGET_PROJECT_FILES.get(target, []):
                if rel in seen:
                    continue
                p = self.project_dir / rel
                if p.is_file():
                    files.append(rel)
                    seen.add(rel)
        return sorted(files)

    def _generate_stanza(self, manager: str, tracked_files: list[str]) -> DotfileStanza | None:
        """Generate a stanza for a specific dotfile manager."""
        if manager == "chezmoi":
            return self._chezmoi_stanza(tracked_files)
        if manager == "yadm":
            return self._yadm_stanza(tracked_files)
        if manager == "dotbot":
            return self._dotbot_stanza(tracked_files)
        if manager == "bare-git":
            return self._bare_git_stanza(tracked_files)
        return None

    def _chezmoi_stanza(self, tracked_files: list[str]) -> DotfileStanza:
        """Generate chezmoi add commands."""
        commands = []
        for rel in tracked_files:
            commands.append(f"chezmoi add ~/{rel}")

        content = "\n".join(commands) if commands else "# No tracked files found"
        return DotfileStanza(
            manager="chezmoi",
            content=content,
            instructions=(
                "Run these commands to add HarnessSync output files to chezmoi. "
                "After syncing on a new machine, run: chezmoi apply"
            ),
        )

    def _yadm_stanza(self, tracked_files: list[str]) -> DotfileStanza:
        """Generate yadm add commands."""
        commands = ["# Add HarnessSync tracked files to yadm"]
        for rel in tracked_files:
            commands.append(f"yadm add ~/{rel}")
        commands.append("yadm commit -m 'Track HarnessSync config files'")

        return DotfileStanza(
            manager="yadm",
            content="\n".join(commands),
            instructions=(
                "Run these commands to add HarnessSync output files to yadm. "
                "After cloning on a new machine, run: yadm checkout"
            ),
        )

    def _dotbot_stanza(self, tracked_files: list[str]) -> DotfileStanza:
        """Generate a dotbot link block."""
        lines = [
            "# HarnessSync config files — add to install.conf.yaml",
            "- link:",
        ]
        for rel in tracked_files:
            # dotbot: target (home): source (dotfiles dir)
            lines.append(f"    ~/{rel}:")
            lines.append(f"      path: {rel}")
            lines.append(f"      create: true")

        return DotfileStanza(
            manager="dotbot",
            content="\n".join(lines),
            instructions=(
                "Add this block to your install.conf.yaml dotbot configuration. "
                "Dotbot will create symlinks from your dotfiles repo to these paths."
            ),
        )

    def _bare_git_stanza(self, tracked_files: list[str]) -> DotfileStanza:
        """Generate bare git repo add commands."""
        alias = "config"  # Common alias for bare git dotfile repos
        commands = [
            f"# Add to bare git dotfile repo (assuming alias: {alias}='git --git-dir=$HOME/.cfg --work-tree=$HOME')",
        ]
        for rel in tracked_files:
            commands.append(f"{alias} add ~/{rel}")
        commands.append(f"{alias} commit -m 'Track HarnessSync config files'")
        commands.append(f"{alias} push")

        return DotfileStanza(
            manager="bare-git",
            content="\n".join(commands),
            instructions=(
                "If you use a bare git repo for dotfiles (the atlassian method), "
                "run these commands to track HarnessSync output files."
            ),
        )


# ---------------------------------------------------------------------------
# Dotfiles Repo Auto-Committer (item 2)
# ---------------------------------------------------------------------------

@dataclass
class AutoCommitResult:
    """Result of an auto-commit operation."""

    repo_path: str
    committed: bool
    commit_sha: str = ""
    files_staged: list[str] = field(default_factory=list)
    message: str = ""
    error: str = ""

    def format(self) -> str:
        if self.error:
            return f"dotfiles auto-commit failed: {self.error}"
        if not self.committed:
            return f"dotfiles repo {self.repo_path}: nothing to commit"
        return (
            f"dotfiles auto-commit: {self.commit_sha[:8] if self.commit_sha else 'ok'} "
            f"({len(self.files_staged)} file(s)) — {self.message}"
        )


class DotfilesAutoCommitter:
    """Auto-commit changed harness configs into a dotfiles git repository.

    After a successful HarnessSync sync, call ``commit()`` to stage all
    tracked harness config files that have changed and create a structured
    git commit in the specified dotfiles repo.

    The dotfiles repo can be:
    - A normal git repo at the given path (files copied/symlinked there)
    - The user's home directory if it is itself a git repo (bare-git style)

    Args:
        dotfiles_repo: Path to the dotfiles git repository root.
        project_dir: HarnessSync project directory (used to find tracked files).
        targets: Optional list of target harnesses to include. Defaults to all.
        push_after_commit: If True, run ``git push`` after committing.
        commit_message_prefix: Prefix for auto-generated commit messages.
    """

    _GIT = "git"

    def __init__(
        self,
        dotfiles_repo: Path,
        project_dir: Path,
        targets: list[str] | None = None,
        push_after_commit: bool = False,
        commit_message_prefix: str = "harnesssync",
    ):
        self.dotfiles_repo = dotfiles_repo
        self.project_dir = project_dir
        self.targets = targets
        self.push_after_commit = push_after_commit
        self.commit_message_prefix = commit_message_prefix

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Return True if git is on PATH and dotfiles_repo is a git repo."""
        if not shutil.which(self._GIT):
            return False
        git_dir = self.dotfiles_repo / ".git"
        return git_dir.exists() or self._is_bare_git_root(self.dotfiles_repo)

    def commit(
        self,
        changed_targets: list[str] | None = None,
        dry_run: bool = False,
    ) -> AutoCommitResult:
        """Stage changed harness config files and commit them.

        Discovers which tracked files have been modified (git status),
        stages them, and creates a commit with a structured message listing
        which targets changed.

        Args:
            changed_targets: Names of targets that were updated in this sync
                             (used in the commit message). If None, all targets.
            dry_run: If True, show what would be committed without writing.

        Returns:
            AutoCommitResult describing what happened.
        """
        if not self.is_available():
            return AutoCommitResult(
                repo_path=str(self.dotfiles_repo),
                committed=False,
                error="git not available or dotfiles_repo is not a git repository",
            )

        # Collect tracked files that exist on disk
        targets = changed_targets or self.targets or list(_TARGET_PROJECT_FILES.keys())
        tracked = self._collect_tracked_files(targets)
        if not tracked:
            return AutoCommitResult(
                repo_path=str(self.dotfiles_repo),
                committed=False,
                message="no tracked files found",
            )

        # Determine which files are actually modified vs repo
        staged = self._find_modified_files(tracked)
        if not staged:
            return AutoCommitResult(
                repo_path=str(self.dotfiles_repo),
                committed=False,
                message="no changes detected",
            )

        if dry_run:
            return AutoCommitResult(
                repo_path=str(self.dotfiles_repo),
                committed=False,
                files_staged=staged,
                message=f"[dry-run] would commit {len(staged)} file(s)",
            )

        # Stage files
        stage_err = self._stage_files(staged)
        if stage_err:
            return AutoCommitResult(
                repo_path=str(self.dotfiles_repo),
                committed=False,
                files_staged=staged,
                error=f"git add failed: {stage_err}",
            )

        # Build commit message
        msg = self._build_commit_message(targets, staged)

        # Commit
        sha, commit_err = self._create_commit(msg)
        if commit_err:
            return AutoCommitResult(
                repo_path=str(self.dotfiles_repo),
                committed=False,
                files_staged=staged,
                message=msg,
                error=f"git commit failed: {commit_err}",
            )

        result = AutoCommitResult(
            repo_path=str(self.dotfiles_repo),
            committed=True,
            commit_sha=sha,
            files_staged=staged,
            message=msg,
        )

        if self.push_after_commit:
            push_err = self._push()
            if push_err:
                result.error = f"commit ok but git push failed: {push_err}"

        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_tracked_files(self, targets: list[str]) -> list[str]:
        """Return relative paths of tracked files that exist in dotfiles_repo."""
        files: list[str] = []
        seen: set[str] = set()
        for target in targets:
            for rel in _TARGET_PROJECT_FILES.get(target, []):
                if rel in seen:
                    continue
                # File could live in dotfiles_repo directly or be sourced from project_dir
                candidate = self.dotfiles_repo / rel
                if candidate.is_file():
                    files.append(rel)
                    seen.add(rel)
        return sorted(files)

    def _find_modified_files(self, tracked: list[str]) -> list[str]:
        """Return which tracked files show as modified/untracked in git status."""
        try:
            result = subprocess.run(
                [self._GIT, "-C", str(self.dotfiles_repo), "status", "--porcelain", "--"] + tracked,
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return tracked  # Assume all changed on git error

            modified = []
            for line in result.stdout.splitlines():
                if len(line) >= 3:
                    path = line[3:].strip().strip('"')
                    if path in tracked:
                        modified.append(path)
            return modified
        except Exception:
            return tracked  # Fail open: stage everything

    def _stage_files(self, files: list[str]) -> str:
        """Stage files for commit. Returns error string or empty string."""
        try:
            result = subprocess.run(
                [self._GIT, "-C", str(self.dotfiles_repo), "add", "--"] + files,
                capture_output=True, text=True, timeout=15,
            )
            return result.stderr.strip() if result.returncode != 0 else ""
        except Exception as e:
            return str(e)

    def _create_commit(self, message: str) -> tuple[str, str]:
        """Create git commit. Returns (sha, error_str)."""
        try:
            result = subprocess.run(
                [self._GIT, "-C", str(self.dotfiles_repo), "commit", "-m", message],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return "", result.stderr.strip()
            # Parse commit SHA from output like "[main abc1234] ..."
            sha = ""
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 2 and "]" in parts[0]:
                    sha = parts[1].rstrip("]")
                    break
            return sha, ""
        except Exception as e:
            return "", str(e)

    def _push(self) -> str:
        """Push to remote. Returns error string or empty string."""
        try:
            result = subprocess.run(
                [self._GIT, "-C", str(self.dotfiles_repo), "push"],
                capture_output=True, text=True, timeout=30,
            )
            return result.stderr.strip() if result.returncode != 0 else ""
        except Exception as e:
            return str(e)

    def _build_commit_message(self, targets: list[str], staged_files: list[str]) -> str:
        """Build a structured commit message for the auto-commit."""
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        target_list = ", ".join(sorted(set(targets))) if targets else "all"
        prefix = self.commit_message_prefix
        return (
            f"{prefix}: sync harness configs [{target_list}]\n\n"
            f"Auto-committed by HarnessSync at {now}\n"
            f"Files updated ({len(staged_files)}):\n"
            + "\n".join(f"  {f}" for f in sorted(staged_files))
        )

    @staticmethod
    def _is_bare_git_root(path: Path) -> bool:
        """Check if path is the working tree of a bare git repo."""
        try:
            result = subprocess.run(
                ["git", "-C", str(path), "rev-parse", "--git-dir"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False
