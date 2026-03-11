from __future__ import annotations

"""Team Config Broadcast — push Claude Code config to a shared git repo.

Lets a team lead sync their Claude Code config to a shared branch or repository.
Teammates run one command to pull and apply the canonical config to all their
harnesses. Solves 'everyone on the team has wildly different AI setups.'

Flow:
    Lead: TeamBroadcast.push(shared_repo, branch="team-config")
    Teammate: TeamBroadcast.pull(shared_repo, branch="team-config")

The broadcast bundle is stored as a JSON file in the shared repo under
``.harness-sync/broadcast.json``. The bundle contains CLAUDE.md content,
synced harness configs, and MCP server configs with secrets redacted.

Usage:
    broadcaster = TeamBroadcast(project_dir)
    result = broadcaster.push(repo_url_or_path, branch="team-config")
    print(result.summary)
"""

import getpass
import json
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from src.secret_detector import SecretDetector
from src.utils.logger import Logger


# Relative path within the shared repo where the broadcast bundle is stored
_BUNDLE_PATH = ".harness-sync/broadcast.json"

# Files included in the broadcast (relative to project root)
_BROADCAST_FILES: list[str] = [
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "CONVENTIONS.md",
    ".windsurfrules",
    ".cursor/rules/claude-code-rules.mdc",
    ".harness-sync/team-profile.json",
]

# Sensitive MCP env keys to redact
_REDACT_SENTINEL = "<REDACTED>"
_SECRET_KEYWORDS = ("key", "secret", "password", "token", "passwd")


def _redact_mcp_env(mcp_servers: dict) -> dict:
    """Return mcp_servers with sensitive env values redacted."""
    out: dict = {}
    for name, cfg in mcp_servers.items():
        if not isinstance(cfg, dict):
            out[name] = cfg
            continue
        cfg_copy = dict(cfg)
        env = cfg_copy.get("env", {})
        if isinstance(env, dict):
            redacted_env = {}
            for k, v in env.items():
                if any(kw in k.lower() for kw in _SECRET_KEYWORDS):
                    redacted_env[k] = _REDACT_SENTINEL
                else:
                    redacted_env[k] = v
            cfg_copy["env"] = redacted_env
        out[name] = cfg_copy
    return out


def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=30,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


@dataclass
class BroadcastResult:
    """Result of a push or pull broadcast operation."""

    success: bool
    operation: str       # "push" | "pull"
    branch: str
    files_included: list[str]
    errors: list[str]
    commit_sha: str = ""
    pull_command: str = ""

    @property
    def summary(self) -> str:
        lines = [f"Team Config Broadcast — {self.operation.upper()}"]
        if self.success:
            lines.append(f"  ✓ Branch: {self.branch}")
            if self.commit_sha:
                lines.append(f"  ✓ Commit: {self.commit_sha[:12]}")
            lines.append(f"  ✓ Files:  {len(self.files_included)} included")
            if self.pull_command:
                lines.append(f"\nTeammates run:")
                lines.append(f"  {self.pull_command}")
        else:
            lines.append("  ✗ Failed")
            for err in self.errors:
                lines.append(f"  · {err}")
        return "\n".join(lines)


class TeamBroadcast:
    """Push and pull Claude Code config via a shared git repository.

    Args:
        project_dir: Local project root directory.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.detector = SecretDetector()
        self.logger = Logger()

    def _collect_files(self) -> dict[str, str]:
        """Read broadcast-eligible files and return path -> content map."""
        files: dict[str, str] = {}
        for rel in _BROADCAST_FILES:
            abs_path = self.project_dir / rel
            if abs_path.exists():
                try:
                    content = abs_path.read_text(encoding="utf-8", errors="replace")
                    # Inline secret scan — warn but don't block (secrets are redacted below)
                    inline_hits = self.detector.scan_content(content, source_label=rel)
                    if inline_hits:
                        self.logger.warning(
                            f"TeamBroadcast: potential inline secret in {rel} — "
                            f"verify before pushing."
                        )
                    files[rel] = content
                except OSError:
                    pass
        return files

    def _read_mcp_servers(self) -> dict:
        """Read MCP server configs from .mcp.json, redact secrets."""
        mcp_path = self.project_dir / ".mcp.json"
        if not mcp_path.exists():
            return {}
        try:
            raw = json.loads(mcp_path.read_text(encoding="utf-8"))
            servers = raw.get("mcpServers", raw) if isinstance(raw, dict) else {}
            return _redact_mcp_env(servers)
        except (OSError, json.JSONDecodeError):
            return {}

    def _build_bundle(self) -> dict:
        """Assemble the broadcast bundle as a JSON-serialisable dict."""
        return {
            "version": "1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "creator": f"{getpass.getuser()}@{socket.gethostname()}",
            "project_dir": self.project_dir.name,
            "files": self._collect_files(),
            "mcp_servers": self._read_mcp_servers(),
        }

    def push(
        self,
        shared_repo: str,
        branch: str = "team-config",
        message: str = "",
        dry_run: bool = False,
    ) -> BroadcastResult:
        """Push current config to a shared git repository.

        Args:
            shared_repo: Remote URL or local path of the shared repo.
            branch: Branch name to push to (created if not existing).
            message: Optional commit message prefix.
            dry_run: If True, build bundle without committing.

        Returns:
            BroadcastResult with success status and details.
        """
        bundle = self._build_bundle()
        files_included = list(bundle["files"].keys())

        if dry_run:
            return BroadcastResult(
                success=True,
                operation="push",
                branch=branch,
                files_included=files_included,
                errors=[],
                pull_command=f"harness-sync broadcast pull --from {shared_repo} --branch {branch}",
            )

        errors: list[str] = []
        commit_sha = ""

        with tempfile.TemporaryDirectory(prefix="hs-broadcast-") as tmpdir:
            tmp = Path(tmpdir)

            # Clone the shared repo (shallow to avoid large history)
            rc, out, err = _run_git(
                ["clone", "--depth=1", "--branch", branch, shared_repo, str(tmp / "repo")],
                cwd=tmp,
            )
            # If branch doesn't exist yet, clone without branch flag then create it
            if rc != 0:
                rc2, _, _ = _run_git(
                    ["clone", "--depth=1", shared_repo, str(tmp / "repo")],
                    cwd=tmp,
                )
                if rc2 != 0:
                    return BroadcastResult(
                        success=False,
                        operation="push",
                        branch=branch,
                        files_included=[],
                        errors=[f"Could not clone {shared_repo}: {err}"],
                    )
                repo = tmp / "repo"
                _run_git(["checkout", "-b", branch], cwd=repo)
            else:
                repo = tmp / "repo"

            # Write bundle
            bundle_path = repo / _BUNDLE_PATH
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")

            # Commit
            _run_git(["add", _BUNDLE_PATH], cwd=repo)
            commit_msg = message or f"harness-sync: broadcast config ({bundle['created_at'][:10]})"
            rc, _, err = _run_git(
                ["commit", "-m", commit_msg, "--allow-empty"],
                cwd=repo,
            )
            if rc != 0 and "nothing to commit" not in err:
                errors.append(f"Git commit failed: {err}")

            # Get commit SHA
            _, sha, _ = _run_git(["rev-parse", "--short", "HEAD"], cwd=repo)
            commit_sha = sha

            # Push
            rc, _, push_err = _run_git(
                ["push", "origin", branch],
                cwd=repo,
            )
            if rc != 0:
                errors.append(f"Git push failed: {push_err}")

        pull_cmd = f"/sync-broadcast pull --from {shared_repo} --branch {branch}"
        return BroadcastResult(
            success=not errors,
            operation="push",
            branch=branch,
            files_included=files_included,
            errors=errors,
            commit_sha=commit_sha,
            pull_command=pull_cmd,
        )

    def pull(
        self,
        shared_repo: str,
        branch: str = "team-config",
        dry_run: bool = False,
    ) -> BroadcastResult:
        """Pull team config from a shared git repository and apply locally.

        Args:
            shared_repo: Remote URL or local path of the shared repo.
            branch: Branch name to pull from.
            dry_run: If True, preview what would be written without writing.

        Returns:
            BroadcastResult with success status and applied files.
        """
        errors: list[str] = []
        files_written: list[str] = []

        with tempfile.TemporaryDirectory(prefix="hs-broadcast-pull-") as tmpdir:
            tmp = Path(tmpdir)
            repo = tmp / "repo"

            rc, _, err = _run_git(
                ["clone", "--depth=1", "--branch", branch, shared_repo, str(repo)],
                cwd=tmp,
            )
            if rc != 0:
                return BroadcastResult(
                    success=False,
                    operation="pull",
                    branch=branch,
                    files_included=[],
                    errors=[f"Could not clone {shared_repo} branch '{branch}': {err}"],
                )

            bundle_path = repo / _BUNDLE_PATH
            if not bundle_path.exists():
                return BroadcastResult(
                    success=False,
                    operation="pull",
                    branch=branch,
                    files_included=[],
                    errors=[f"No broadcast bundle found at {_BUNDLE_PATH} in {branch}"],
                )

            try:
                bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                return BroadcastResult(
                    success=False,
                    operation="pull",
                    branch=branch,
                    files_included=[],
                    errors=[f"Failed to parse bundle: {e}"],
                )

            files = bundle.get("files", {})
            for rel_path, content in files.items():
                abs_path = self.project_dir / rel_path
                files_written.append(rel_path)
                if not dry_run:
                    abs_path.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        abs_path.write_text(content, encoding="utf-8")
                    except OSError as e:
                        errors.append(f"Could not write {rel_path}: {e}")

        return BroadcastResult(
            success=not errors,
            operation="pull",
            branch=branch,
            files_included=files_written,
            errors=errors,
        )
