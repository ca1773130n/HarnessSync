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
import socket
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
                lines.append("\nTeammates run:")
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

    def check_and_auto_pull(
        self,
        repo: str,
        branch: str = "team-config",
        max_age_hours: float = 24.0,
    ) -> BroadcastResult | None:
        """Pull from the team broadcast repo if the local copy is stale.

        Reads the last-pull timestamp from ``.harnesssync-broadcast-state.json``
        in the project directory. If the timestamp is older than ``max_age_hours``
        (or no timestamp exists), pulls the team config automatically.

        This method is designed to be called from session-start hooks so that
        every developer's harnesses stay current without manual intervention.

        Args:
            repo: Shared repository URL or local path.
            branch: Branch to pull from (default: "team-config").
            max_age_hours: Re-pull if last pull is older than this many hours.

        Returns:
            BroadcastResult if a pull was performed, None if still fresh.
        """
        state_path = self.project_dir / ".harnesssync-broadcast-state.json"
        now = datetime.now(timezone.utc)

        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                last_pull_str = state.get("last_pull_at", "")
                if last_pull_str:
                    last_pull = datetime.fromisoformat(last_pull_str)
                    # Ensure timezone-aware for comparison
                    if last_pull.tzinfo is None:
                        last_pull = last_pull.replace(tzinfo=timezone.utc)
                    age = now - last_pull
                    if age < timedelta(hours=max_age_hours):
                        return None  # Still fresh — skip pull
            except (OSError, ValueError, KeyError):
                pass  # Corrupt state — proceed with pull

        result = self.pull(repo, branch=branch)

        # Persist the pull timestamp regardless of success so we don't
        # hammer a broken repo on every session start.
        try:
            state_data = {
                "last_pull_at": now.isoformat(),
                "repo": repo,
                "branch": branch,
                "success": result.success,
                "files_pulled": result.files_included,
            }
            state_path.write_text(
                json.dumps(state_data, indent=2), encoding="utf-8"
            )
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# S3 Backend
# ──────────────────────────────────────────────────────────────────────────────

class S3TeamBroadcast:
    """Push and pull the team broadcast bundle via AWS S3.

    Requires ``boto3`` to be installed (``pip install boto3``).  Credentials
    are resolved from the standard boto3 chain (env vars, ~/.aws/credentials,
    instance profile).

    The bundle is stored at ``s3://<bucket>/<key_prefix>/broadcast.json``.

    Args:
        project_dir: Local project root directory.
        bucket: S3 bucket name.
        key_prefix: Key prefix inside the bucket (default: "harness-sync").
    """

    def __init__(self, project_dir: Path, bucket: str, key_prefix: str = "harness-sync"):
        self.project_dir = project_dir
        self.bucket = bucket
        self.key_prefix = key_prefix.rstrip("/")
        self._broadcaster = TeamBroadcast(project_dir)

    @property
    def _bundle_key(self) -> str:
        return f"{self.key_prefix}/broadcast.json"

    def _get_s3_client(self):
        """Return a boto3 S3 client, raising ImportError if boto3 unavailable."""
        try:
            import boto3  # type: ignore[import]
            return boto3.client("s3")
        except ImportError as exc:
            raise ImportError(
                "boto3 is required for S3 broadcast. Install with: pip install boto3"
            ) from exc

    def push(self, dry_run: bool = False) -> BroadcastResult:
        """Push the current config bundle to S3.

        Args:
            dry_run: If True, build bundle without uploading.

        Returns:
            BroadcastResult with success status and details.
        """
        bundle = self._broadcaster._build_bundle()
        files_included = list(bundle["files"].keys())

        if dry_run:
            return BroadcastResult(
                success=True,
                operation="push",
                branch=self._bundle_key,
                files_included=files_included,
                errors=[],
                pull_command=f"harness-sync broadcast pull --s3 s3://{self.bucket}/{self._bundle_key}",
            )

        errors: list[str] = []
        try:
            s3 = self._get_s3_client()
            body = json.dumps(bundle, indent=2).encode("utf-8")
            s3.put_object(
                Bucket=self.bucket,
                Key=self._bundle_key,
                Body=body,
                ContentType="application/json",
            )
        except ImportError as exc:
            return BroadcastResult(
                success=False,
                operation="push",
                branch=self._bundle_key,
                files_included=[],
                errors=[str(exc)],
            )
        except Exception as exc:
            errors.append(f"S3 upload failed: {exc}")

        pull_cmd = (
            f"/sync-broadcast pull --s3 s3://{self.bucket}/{self._bundle_key}"
        )
        return BroadcastResult(
            success=not errors,
            operation="push",
            branch=self._bundle_key,
            files_included=files_included,
            errors=errors,
            pull_command=pull_cmd,
        )

    def pull(self, dry_run: bool = False) -> BroadcastResult:
        """Pull team config from S3 and apply locally.

        Args:
            dry_run: If True, preview without writing.

        Returns:
            BroadcastResult with success status and applied files.
        """
        errors: list[str] = []
        files_written: list[str] = []

        try:
            s3 = self._get_s3_client()
            response = s3.get_object(Bucket=self.bucket, Key=self._bundle_key)
            raw = response["Body"].read().decode("utf-8")
            bundle = json.loads(raw)
        except ImportError as exc:
            return BroadcastResult(
                success=False,
                operation="pull",
                branch=self._bundle_key,
                files_included=[],
                errors=[str(exc)],
            )
        except Exception as exc:
            return BroadcastResult(
                success=False,
                operation="pull",
                branch=self._bundle_key,
                files_included=[],
                errors=[f"S3 download failed: {exc}"],
            )

        files = bundle.get("files", {})
        for rel_path, content in files.items():
            abs_path = self.project_dir / rel_path
            files_written.append(rel_path)
            if not dry_run:
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    abs_path.write_text(content, encoding="utf-8")
                except OSError as exc:
                    errors.append(f"Could not write {rel_path}: {exc}")

        return BroadcastResult(
            success=not errors,
            operation="pull",
            branch=self._bundle_key,
            files_included=files_written,
            errors=errors,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Local Network Share Backend
# ──────────────────────────────────────────────────────────────────────────────

class LocalShareBroadcast:
    """Push and pull the team broadcast bundle via a mounted local/network share.

    The share must already be mounted at ``share_dir`` (e.g. /Volumes/TeamShare,
    /mnt/nas, or a UNC-mapped drive on Windows).  No extra dependencies are
    required beyond the standard library.

    The bundle is stored at ``<share_dir>/harness-sync/broadcast.json``.

    Args:
        project_dir: Local project root directory.
        share_dir: Path to the mounted share directory.
        namespace: Sub-directory inside the share (default: "harness-sync").
    """

    def __init__(
        self,
        project_dir: Path,
        share_dir: Path,
        namespace: str = "harness-sync",
    ):
        self.project_dir = project_dir
        self.share_dir = Path(share_dir)
        self.namespace = namespace
        self._broadcaster = TeamBroadcast(project_dir)

    @property
    def _bundle_path(self) -> Path:
        return self.share_dir / self.namespace / "broadcast.json"

    def push(self, dry_run: bool = False) -> BroadcastResult:
        """Write the current config bundle to the network share.

        Args:
            dry_run: If True, build bundle without writing.

        Returns:
            BroadcastResult with success status and details.
        """
        bundle = self._broadcaster._build_bundle()
        files_included = list(bundle["files"].keys())

        if dry_run:
            return BroadcastResult(
                success=True,
                operation="push",
                branch=str(self._bundle_path),
                files_included=files_included,
                errors=[],
                pull_command=f"harness-sync broadcast pull --share {self._bundle_path}",
            )

        if not self.share_dir.exists():
            return BroadcastResult(
                success=False,
                operation="push",
                branch=str(self._bundle_path),
                files_included=[],
                errors=[f"Share directory not found or not mounted: {self.share_dir}"],
            )

        errors: list[str] = []
        try:
            self._bundle_path.parent.mkdir(parents=True, exist_ok=True)
            self._bundle_path.write_text(
                json.dumps(bundle, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            errors.append(f"Could not write to share: {exc}")

        pull_cmd = f"/sync-broadcast pull --share {self._bundle_path}"
        return BroadcastResult(
            success=not errors,
            operation="push",
            branch=str(self._bundle_path),
            files_included=files_included,
            errors=errors,
            pull_command=pull_cmd,
        )

    def pull(self, dry_run: bool = False) -> BroadcastResult:
        """Read team config from the network share and apply locally.

        Args:
            dry_run: If True, preview without writing.

        Returns:
            BroadcastResult with success status and applied files.
        """
        errors: list[str] = []
        files_written: list[str] = []

        if not self._bundle_path.exists():
            return BroadcastResult(
                success=False,
                operation="pull",
                branch=str(self._bundle_path),
                files_included=[],
                errors=[
                    f"No broadcast bundle found at {self._bundle_path}. "
                    "Has the team lead run a push yet?"
                ],
            )

        try:
            bundle = json.loads(self._bundle_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return BroadcastResult(
                success=False,
                operation="pull",
                branch=str(self._bundle_path),
                files_included=[],
                errors=[f"Failed to parse bundle: {exc}"],
            )

        files = bundle.get("files", {})
        for rel_path, content in files.items():
            abs_path = self.project_dir / rel_path
            files_written.append(rel_path)
            if not dry_run:
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    abs_path.write_text(content, encoding="utf-8")
                except OSError as exc:
                    errors.append(f"Could not write {rel_path}: {exc}")

        return BroadcastResult(
            success=not errors,
            operation="pull",
            branch=str(self._bundle_path),
            files_included=files_written,
            errors=errors,
        )

    def last_push_info(self) -> dict | None:
        """Return metadata from the current bundle without applying it.

        Returns:
            Dict with 'created_at', 'creator', 'files' keys, or None if
            no bundle exists.
        """
        if not self._bundle_path.exists():
            return None
        try:
            bundle = json.loads(self._bundle_path.read_text(encoding="utf-8"))
            return {
                "created_at": bundle.get("created_at", ""),
                "creator": bundle.get("creator", ""),
                "files": list(bundle.get("files", {}).keys()),
            }
        except (OSError, json.JSONDecodeError):
            return None
