from __future__ import annotations

"""Team config sharing via GitHub (item 8 — team sync).

Publish your HarnessSync config set (CLAUDE.md, harness translations, etc.) to
a GitHub repository so teammates can subscribe with a single URL and keep in
sync automatically.

Design decisions:
- Uses stdlib subprocess + system ``git`` binary (no external Python deps,
  no GitHub API tokens required for public repos; uses SSH or HTTPS git auth).
- A "team config repo" is just a standard git repository: CLAUDE.md at root,
  optionally a ``harness-sync/`` sub-folder for translated harness configs.
- Subscription metadata (repo URL, branch, last-pull timestamp) is stored in
  ~/.harnesssync/team-subscriptions.json for lightweight bookkeeping.
- Dry-run support throughout: pass dry_run=True to print git commands without
  executing them.

Typical workflow:

    # Team lead — publish configs
    sync = TeamGitHubSync(project_dir=Path("."))
    result = sync.publish("https://github.com/myorg/team-claude-config.git")
    print(result)

    # Teammate — subscribe
    sync = TeamGitHubSync(project_dir=Path("."))
    result = sync.subscribe("https://github.com/myorg/team-claude-config.git")
    print(result)

    # CI / cron — check for upstream updates
    info = sync.check_updates("https://github.com/myorg/team-claude-config.git")
    if info["has_updates"]:
        sync.subscribe(...)
"""

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.utils.logger import Logger


# ---------------------------------------------------------------------------
# Files copied into / out of the team config repo
# ---------------------------------------------------------------------------

# Relative to project_dir — files that are published and subscribed
_PUBLISH_FILES: list[str] = [
    "CLAUDE.md",
    "CLAUDE.local.md",
    "AGENTS.md",
    "GEMINI.md",
    "CONVENTIONS.md",
    ".windsurfrules",
    ".cursor/rules/claude-code-rules.mdc",
    ".harness-sync/team-profile.json",
    ".harnesssync",
]

# Sub-directory within the team repo where harness-specific overrides live
_HARNESS_SYNC_SUBDIR = "harness-sync"

# Default location for local clones of subscribed team repos
_DEFAULT_CACHE_DIR = Path.home() / ".harnesssync" / "team-repos"

# Subscription index file
_SUBSCRIPTIONS_FILE = Path.home() / ".harnesssync" / "team-subscriptions.json"

# Timeout for git network operations (seconds)
_GIT_NETWORK_TIMEOUT = 60


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TeamConfigRepo:
    """Metadata for a subscribed (or published) team config repository."""

    url: str                        # GitHub repo URL or any git remote URL
    branch: str = "main"
    last_pulled: str | None = None  # ISO 8601 timestamp of last successful pull
    local_cache: str | None = None  # Absolute path to the local clone


@dataclass
class PublishResult:
    """Result of a publish operation."""

    success: bool
    url: str
    files_pushed: list[str] = field(default_factory=list)
    commit_sha: str | None = None
    error: str | None = None

    def format(self) -> str:
        lines = [f"Team Config Publish — {self.url}"]
        lines.append("=" * 60)
        if not self.success:
            lines.append(f"FAILED: {self.error}")
            return "\n".join(lines)
        lines.append(f"Commit: {self.commit_sha or '(dry-run)'}")
        lines.append(f"Files pushed: {len(self.files_pushed)}")
        for f in self.files_pushed:
            lines.append(f"  + {f}")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.format()


@dataclass
class SubscribeResult:
    """Result of a subscribe (pull + apply) operation."""

    success: bool
    files_applied: list[str] = field(default_factory=list)
    updated: bool = False   # True if there were upstream changes
    error: str | None = None

    def format(self) -> str:
        lines = ["Team Config Subscribe"]
        lines.append("=" * 60)
        if not self.success:
            lines.append(f"FAILED: {self.error}")
            return "\n".join(lines)
        status = "updated" if self.updated else "already up to date"
        lines.append(f"Status: {status}")
        if self.files_applied:
            lines.append(f"Files applied: {len(self.files_applied)}")
            for f in self.files_applied:
                lines.append(f"  ✓ {f}")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.format()


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class TeamGitHubSync:
    """Publish and subscribe to team HarnessSync configs via a git repository.

    Args:
        project_dir: Local project root containing CLAUDE.md and harness configs.
        cache_dir: Directory where team repo clones are stored.
                   Defaults to ~/.harnesssync/team-repos/.
    """

    def __init__(
        self,
        project_dir: Path,
        cache_dir: Path | None = None,
    ) -> None:
        self.project_dir = Path(project_dir).resolve()
        self.cache_dir = Path(cache_dir).resolve() if cache_dir else _DEFAULT_CACHE_DIR
        self.logger = Logger()
        self._git = shutil.which("git")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def publish(
        self,
        repo_url: str,
        branch: str = "main",
        message: str | None = None,
        dry_run: bool = False,
    ) -> PublishResult:
        """Push current configs to a team GitHub repository.

        Creates or updates a local staging clone of ``repo_url``, copies the
        current CLAUDE.md and harness config files into it, commits, and pushes
        to the remote.

        Args:
            repo_url: Git remote URL (HTTPS or SSH) of the team config repo.
            branch: Branch to push to (default: "main").
            message: Commit message. Defaults to a timestamped message.
            dry_run: If True, print git commands without executing them.

        Returns:
            PublishResult with success status, pushed files list, and commit SHA.
        """
        if not self._git:
            return PublishResult(
                success=False,
                url=repo_url,
                error="git not found in PATH — install Git to use team sync",
            )

        stage_dir = self._stage_dir(repo_url)

        # Clone or update the staging repo
        ok, err = self._ensure_clone(repo_url, branch, stage_dir, dry_run=dry_run)
        if not ok:
            return PublishResult(success=False, url=repo_url, error=err)

        # Copy config files from project_dir → staging clone
        files_copied: list[str] = []
        copy_errors: list[str] = []

        for rel in _PUBLISH_FILES:
            src = self.project_dir / rel
            if not src.exists():
                continue
            dst = stage_dir / rel
            try:
                if dry_run:
                    self.logger.info(f"[dry-run] would copy {rel} → {dst}")
                    files_copied.append(rel)
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                files_copied.append(rel)
            except OSError as exc:
                copy_errors.append(f"{rel}: {exc}")
                self.logger.warn(f"publish: copy failed for {rel}: {exc}")

        # Also copy per-target override files (CLAUDE.<target>.md)
        for target in ("codex", "gemini", "opencode", "cursor", "aider", "windsurf"):
            override_rel = f"CLAUDE.{target}.md"
            src = self.project_dir / override_rel
            if not src.exists():
                continue
            dst = stage_dir / override_rel
            try:
                if dry_run:
                    self.logger.info(f"[dry-run] would copy {override_rel} → {dst}")
                    files_copied.append(override_rel)
                    continue
                shutil.copy2(str(src), str(dst))
                files_copied.append(override_rel)
            except OSError as exc:
                copy_errors.append(f"{override_rel}: {exc}")

        if not files_copied and not dry_run:
            return PublishResult(
                success=False,
                url=repo_url,
                error="No config files found to publish in project_dir",
            )

        if dry_run:
            commit_msg = message or self._default_commit_message()
            self.logger.info(f"[dry-run] would commit: {commit_msg}")
            self.logger.info(f"[dry-run] would push to {repo_url} branch {branch}")
            return PublishResult(
                success=True,
                url=repo_url,
                files_pushed=files_copied,
                commit_sha=None,
            )

        # git add -A
        rc, out, err_text = self._git_run(["add", "-A"], cwd=stage_dir)
        if rc != 0:
            return PublishResult(
                success=False, url=repo_url,
                error=f"git add failed: {err_text.strip()}",
            )

        # Check if there's anything to commit
        rc_status, status_out, _ = self._git_run(
            ["status", "--porcelain"], cwd=stage_dir
        )
        if rc_status == 0 and not status_out.strip():
            # Nothing changed — still succeed with the current HEAD SHA
            sha = self._current_sha(stage_dir)
            return PublishResult(
                success=True,
                url=repo_url,
                files_pushed=files_copied,
                commit_sha=sha,
            )

        # git commit
        commit_msg = message or self._default_commit_message()
        rc, _, err_text = self._git_run(
            ["commit", "-m", commit_msg, "--allow-empty"], cwd=stage_dir
        )
        if rc != 0:
            return PublishResult(
                success=False, url=repo_url,
                error=f"git commit failed: {err_text.strip()}",
            )

        sha = self._current_sha(stage_dir)

        # git push
        rc, _, err_text = self._git_run(
            ["push", "origin", branch],
            cwd=stage_dir,
            timeout=_GIT_NETWORK_TIMEOUT,
        )
        if rc != 0:
            return PublishResult(
                success=False, url=repo_url,
                error=f"git push failed: {err_text.strip()}",
            )

        return PublishResult(
            success=True,
            url=repo_url,
            files_pushed=files_copied,
            commit_sha=sha,
        )

    def subscribe(
        self,
        repo_url: str,
        branch: str = "main",
        dry_run: bool = False,
    ) -> SubscribeResult:
        """Pull a team config repo and apply its files to project_dir.

        Clones the repo (or pulls if already cloned), then copies CLAUDE.md and
        harness config files into project_dir. Saves subscription metadata to
        ~/.harnesssync/team-subscriptions.json.

        Args:
            repo_url: Git remote URL of the team config repo.
            branch: Branch to track (default: "main").
            dry_run: If True, report what would be applied without writing files.

        Returns:
            SubscribeResult with applied files and whether there were updates.
        """
        if not self._git:
            return SubscribeResult(
                success=False,
                error="git not found in PATH — install Git to use team sync",
            )

        cache = self._stage_dir(repo_url)
        had_existing_clone = cache.exists() and (cache / ".git").exists()

        # Remember HEAD before pull so we can detect updates
        sha_before = self._current_sha(cache) if had_existing_clone else None

        ok, err = self._ensure_clone(repo_url, branch, cache, dry_run=dry_run)
        if not ok:
            return SubscribeResult(success=False, error=err)

        sha_after = self._current_sha(cache) if not dry_run else None
        updated = (sha_before != sha_after) and sha_before is not None

        if dry_run:
            # Report what would be applied
            files_to_apply = self._list_applicable_files(cache)
            self.logger.info(f"[dry-run] would apply {len(files_to_apply)} files from {repo_url}")
            for rel in files_to_apply:
                self.logger.info(f"[dry-run]   {rel} → {self.project_dir / rel}")
            return SubscribeResult(
                success=True,
                files_applied=files_to_apply,
                updated=True,  # dry-run assumes there would be updates
            )

        # Apply files from the cloned repo to project_dir
        files_applied: list[str] = []
        apply_errors: list[str] = []

        for rel in self._list_applicable_files(cache):
            src = cache / rel
            dst = self.project_dir / rel
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                files_applied.append(rel)
            except OSError as exc:
                apply_errors.append(f"{rel}: {exc}")
                self.logger.warn(f"subscribe: apply failed for {rel}: {exc}")

        if apply_errors and not files_applied:
            return SubscribeResult(
                success=False,
                error=f"Failed to apply any files: {'; '.join(apply_errors)}",
            )

        # Save subscription metadata
        self._save_subscription(
            TeamConfigRepo(
                url=repo_url,
                branch=branch,
                last_pulled=datetime.now(timezone.utc).isoformat(),
                local_cache=str(cache),
            )
        )

        return SubscribeResult(
            success=True,
            files_applied=files_applied,
            updated=updated or (not had_existing_clone),
        )

    def check_updates(self, repo_url: str, branch: str = "main") -> dict:
        """Check whether the remote team config repo has updates.

        Fetches from the remote (no merge) and compares the remote branch HEAD
        against the local clone HEAD to determine if there are new commits.

        Args:
            repo_url: Git remote URL of the team config repo.
            branch: Branch to check (default: "main").

        Returns:
            Dict with keys:
                - has_updates: bool — True if remote is ahead of local
                - remote_commit: str — remote HEAD SHA (or "" if unavailable)
                - local_commit: str — local HEAD SHA (or "" if no local clone)
                - files_changed: list[str] — files changed between local and remote
        """
        if not self._git:
            return {
                "has_updates": False,
                "remote_commit": "",
                "local_commit": "",
                "files_changed": [],
            }

        cache = self._stage_dir(repo_url)

        # If no local clone exists, any remote content is "new"
        if not cache.exists() or not (cache / ".git").exists():
            return {
                "has_updates": True,
                "remote_commit": "",
                "local_commit": "",
                "files_changed": [],
            }

        local_sha = self._current_sha(cache) or ""

        # Fetch remote without merging
        self._git_run(
            ["fetch", "origin", branch],
            cwd=cache,
            timeout=_GIT_NETWORK_TIMEOUT,
        )

        # Get remote HEAD
        rc, remote_sha, _ = self._git_run(
            ["rev-parse", f"origin/{branch}"],
            cwd=cache,
        )
        remote_sha = remote_sha.strip() if rc == 0 else ""

        if not remote_sha or remote_sha == local_sha:
            return {
                "has_updates": False,
                "remote_commit": remote_sha,
                "local_commit": local_sha,
                "files_changed": [],
            }

        # List changed files between local and remote
        rc, diff_out, _ = self._git_run(
            ["diff", "--name-only", local_sha, remote_sha],
            cwd=cache,
        )
        files_changed: list[str] = []
        if rc == 0 and diff_out.strip():
            files_changed = [f for f in diff_out.strip().splitlines() if f]

        return {
            "has_updates": True,
            "remote_commit": remote_sha,
            "local_commit": local_sha,
            "files_changed": files_changed,
        }

    def list_subscriptions(self) -> list[TeamConfigRepo]:
        """Return all saved team config subscriptions.

        Returns:
            List of TeamConfigRepo entries from the subscriptions index.
        """
        data = self._load_subscriptions()
        result = []
        for entry in data.values():
            result.append(
                TeamConfigRepo(
                    url=entry.get("url", ""),
                    branch=entry.get("branch", "main"),
                    last_pulled=entry.get("last_pulled"),
                    local_cache=entry.get("local_cache"),
                )
            )
        return sorted(result, key=lambda r: r.url)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _stage_dir(self, repo_url: str) -> Path:
        """Return the local clone path for a given repo URL.

        The directory name is derived from the URL's path component so that
        different repos get separate clone directories.
        """
        # Use the last component of the URL path (strip .git suffix)
        url_slug = repo_url.rstrip("/").rsplit("/", 1)[-1]
        if url_slug.endswith(".git"):
            url_slug = url_slug[:-4]
        if not url_slug:
            url_slug = "team-config"
        # Include a short hash of the full URL to disambiguate forks
        import hashlib
        url_hash = hashlib.sha1(repo_url.encode()).hexdigest()[:8]
        return self.cache_dir / f"{url_slug}-{url_hash}"

    def _ensure_clone(
        self,
        repo_url: str,
        branch: str,
        dest: Path,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Clone repo_url into dest, or pull if already cloned.

        Returns:
            (success: bool, error_message: str)
        """
        if dry_run:
            if not dest.exists():
                self.logger.info(f"[dry-run] would clone {repo_url} → {dest}")
            else:
                self.logger.info(f"[dry-run] would pull {repo_url} branch {branch}")
            return True, ""

        if not dest.exists() or not (dest / ".git").exists():
            # Fresh clone
            dest.parent.mkdir(parents=True, exist_ok=True)
            rc, _, err = self._git_run(
                ["clone", "--depth", "1", "--branch", branch, repo_url, str(dest)],
                cwd=None,
                timeout=_GIT_NETWORK_TIMEOUT,
            )
            if rc != 0:
                # Try without --branch (repo may use "main" or "master")
                if dest.exists():
                    shutil.rmtree(str(dest), ignore_errors=True)
                rc2, _, err2 = self._git_run(
                    ["clone", "--depth", "1", repo_url, str(dest)],
                    cwd=None,
                    timeout=_GIT_NETWORK_TIMEOUT,
                )
                if rc2 != 0:
                    return False, f"git clone failed: {err2.strip() or err.strip()}"
                # Checkout requested branch if it differs from default
                self._git_run(["checkout", branch], cwd=dest)
        else:
            # Pull existing clone
            self._git_run(["fetch", "origin"], cwd=dest, timeout=_GIT_NETWORK_TIMEOUT)
            rc, _, err = self._git_run(
                ["reset", "--hard", f"origin/{branch}"],
                cwd=dest,
            )
            if rc != 0:
                return False, f"git pull failed: {err.strip()}"

        return True, ""

    def _list_applicable_files(self, repo_dir: Path) -> list[str]:
        """List files in repo_dir that should be applied to project_dir.

        Only includes files that match known HarnessSync config file names.
        Filters out git internals, README, and other non-config files.
        """
        applicable: list[str] = []
        for rel in _PUBLISH_FILES:
            if (repo_dir / rel).exists():
                applicable.append(rel)

        # Also include per-target override files present in the repo
        for target in ("codex", "gemini", "opencode", "cursor", "aider", "windsurf"):
            override_rel = f"CLAUDE.{target}.md"
            if (repo_dir / override_rel).exists():
                applicable.append(override_rel)

        return applicable

    def _git_run(
        self,
        args: list[str],
        cwd: Path | None = None,
        timeout: int = 30,
    ) -> tuple[int, str, str]:
        """Run a git subcommand.

        Args:
            args: git arguments (without the "git" prefix).
            cwd: Working directory for the command.
            timeout: Timeout in seconds.

        Returns:
            (returncode, stdout, stderr)
        """
        cmd = [self._git or "git"] + args
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(cwd) if cwd else None,
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            self.logger.warn(f"git {' '.join(args[:2])} timed out after {timeout}s")
            return 1, "", "timeout"
        except OSError as exc:
            self.logger.warn(f"git command failed: {exc}")
            return 1, "", str(exc)

    def _current_sha(self, repo_dir: Path) -> str | None:
        """Return the current HEAD commit SHA for a local repo, or None."""
        if not repo_dir.exists():
            return None
        rc, out, _ = self._git_run(["rev-parse", "HEAD"], cwd=repo_dir)
        if rc == 0 and out.strip():
            return out.strip()
        return None

    def _default_commit_message(self) -> str:
        """Generate a default commit message with timestamp."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        project_name = self.project_dir.name
        return f"harnesssync: publish config from {project_name} at {ts}"

    # ------------------------------------------------------------------
    # Subscription persistence
    # ------------------------------------------------------------------

    def _load_subscriptions(self) -> dict:
        """Load subscriptions index from disk."""
        if not _SUBSCRIPTIONS_FILE.exists():
            return {}
        try:
            return json.loads(_SUBSCRIPTIONS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_subscription(self, repo: TeamConfigRepo) -> None:
        """Upsert a TeamConfigRepo into the subscriptions index."""
        data = self._load_subscriptions()
        data[repo.url] = {
            "url": repo.url,
            "branch": repo.branch,
            "last_pulled": repo.last_pulled,
            "local_cache": repo.local_cache,
        }
        _SUBSCRIPTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SUBSCRIPTIONS_FILE.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


def publish_config(
    repo_url: str,
    project_dir: Path,
    branch: str = "main",
    message: str | None = None,
    dry_run: bool = False,
) -> PublishResult:
    """Convenience wrapper: publish project configs to a team GitHub repo.

    Args:
        repo_url: Git remote URL of the team config repo.
        project_dir: Local project root containing CLAUDE.md and harness configs.
        branch: Branch to push to (default: "main").
        message: Commit message. Auto-generated if not provided.
        dry_run: If True, print commands without executing.

    Returns:
        PublishResult describing what was pushed.
    """
    return TeamGitHubSync(project_dir).publish(
        repo_url, branch=branch, message=message, dry_run=dry_run
    )


def subscribe_config(
    repo_url: str,
    project_dir: Path,
    branch: str = "main",
    dry_run: bool = False,
) -> SubscribeResult:
    """Convenience wrapper: subscribe to a team GitHub config repo.

    Clones or updates the repo and applies config files to project_dir.

    Args:
        repo_url: Git remote URL of the team config repo.
        project_dir: Local project root where configs will be written.
        branch: Branch to track (default: "main").
        dry_run: If True, report what would be applied without writing.

    Returns:
        SubscribeResult describing what was applied.
    """
    return TeamGitHubSync(project_dir).subscribe(repo_url, branch=branch, dry_run=dry_run)


def check_upstream_updates(
    repo_url: str,
    project_dir: Path,
    branch: str = "main",
) -> dict:
    """Convenience wrapper: check if the remote team config has updates.

    Args:
        repo_url: Git remote URL of the team config repo.
        project_dir: Local project root (used to locate the cache dir).
        branch: Branch to check (default: "main").

    Returns:
        Dict with has_updates, remote_commit, local_commit, files_changed.
    """
    return TeamGitHubSync(project_dir).check_updates(repo_url, branch=branch)
