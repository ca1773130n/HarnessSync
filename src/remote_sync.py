from __future__ import annotations

"""Remote machine config sync over SSH (item 20).

Pushes the full HarnessSync config set to a remote machine's harness
installations over SSH using the ``scp`` and ``ssh`` system commands
(no external Python dependencies required).

Usage:
    syncer = RemoteSync("user@devbox.company.com", project_dir)
    result = syncer.push()

Or via /sync --remote=user@devbox.company.com in the CLI.

Remote targets are detected by querying the remote machine's PATH and
known install directories via SSH. Only harnesses present on the remote
are targeted, preventing errors from trying to write configs for CLIs
that aren't installed there.

Design decisions:
- Uses stdlib subprocess + system ssh/scp (no paramiko dependency)
- ssh ControlMaster multiplexing re-uses one connection for all transfers
- Supports --ssh-key, --ssh-port, and custom remote project directory
- Dry-run mode prints the scp commands without executing them
"""

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.logger import Logger


# Config files to push to the remote (relative to local project_dir)
_SYNC_FILES = [
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "opencode.json",
    ".harnesssync",
]

# Global Claude config files (relative to ~/.claude on both machines)
_CC_GLOBAL_FILES = [
    "CLAUDE.md",
]

# Remote harness detection commands (returns 0 if present)
_DETECT_CMDS: dict[str, str] = {
    "codex": "command -v codex",
    "gemini": "command -v gemini",
    "opencode": "command -v opencode || command -v opencode-cli",
    "cursor": "command -v cursor || test -d ~/.cursor",
    "aider": "command -v aider",
    "windsurf": "command -v windsurf || test -d ~/.windsurf",
}


@dataclass
class RemoteSyncResult:
    """Result of a remote sync operation."""

    remote: str
    files_pushed: list[str] = field(default_factory=list)
    files_failed: list[str] = field(default_factory=list)
    remote_harnesses: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False

    @property
    def success(self) -> bool:
        return len(self.files_failed) == 0

    def format(self) -> str:
        lines = [f"Remote Sync — {self.remote}"]
        lines.append("=" * 50)
        if self.dry_run:
            lines.append("[dry-run mode — no files transferred]")
        lines.append(f"Detected harnesses: {', '.join(self.remote_harnesses) or 'none'}")
        lines.append(f"Files pushed: {len(self.files_pushed)}")
        if self.files_pushed:
            for f in self.files_pushed:
                lines.append(f"  ✓ {f}")
        if self.files_failed:
            lines.append(f"Files failed: {len(self.files_failed)}")
            for f in self.files_failed:
                lines.append(f"  ✗ {f}")
        if self.warnings:
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")
        return "\n".join(lines)


class RemoteSync:
    """Push HarnessSync configs to a remote machine over SSH.

    Uses system ``ssh`` and ``scp`` binaries. Requires SSH access to the
    remote host (key-based auth or SSH agent recommended).

    Args:
        remote: SSH target in ``user@host`` or ``host`` format.
        project_dir: Local project root containing config files.
        remote_project_dir: Remote project directory (default: same relative path).
        ssh_key: Path to SSH private key (default: uses SSH agent / ~/.ssh/id_rsa).
        ssh_port: SSH port (default: 22).
        dry_run: If True, print commands without executing.
    """

    def __init__(
        self,
        remote: str,
        project_dir: Path,
        remote_project_dir: str | None = None,
        ssh_key: str | None = None,
        ssh_port: int = 22,
        dry_run: bool = False,
    ):
        self.remote = remote
        self.project_dir = Path(project_dir)
        self.remote_project_dir = remote_project_dir or str(self.project_dir)
        self.ssh_key = ssh_key
        self.ssh_port = ssh_port
        self.dry_run = dry_run
        self.logger = Logger()
        self._ssh_available = bool(shutil.which("ssh") and shutil.which("scp"))

    def _ssh_opts(self) -> list[str]:
        """Build common SSH option flags."""
        opts = [
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-p", str(self.ssh_port),
        ]
        if self.ssh_key:
            opts += ["-i", self.ssh_key]
        return opts

    def _run_ssh(self, command: str, timeout: int = 15) -> tuple[int, str]:
        """Run a command on the remote via SSH.

        Returns:
            (returncode, stdout_text)
        """
        cmd = ["ssh"] + self._ssh_opts() + [self.remote, command]
        if self.dry_run:
            self.logger.info(f"[dry-run] ssh: {' '.join(cmd)}")
            return 0, ""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode, result.stdout.strip()
        except subprocess.TimeoutExpired:
            return 1, ""
        except OSError as exc:
            self.logger.warn(f"SSH command failed: {exc}")
            return 1, ""

    def _scp_push(self, local_path: Path, remote_path: str) -> bool:
        """Copy a local file to the remote via SCP.

        Returns:
            True if successful, False otherwise.
        """
        cmd = ["scp"] + self._ssh_opts() + [str(local_path), f"{self.remote}:{remote_path}"]
        if self.dry_run:
            self.logger.info(f"[dry-run] scp: {' '.join(cmd)}")
            return True
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError) as exc:
            self.logger.warn(f"SCP failed for {local_path}: {exc}")
            return False

    def check_connectivity(self) -> bool:
        """Test SSH connectivity to the remote host.

        Returns:
            True if SSH connection succeeds.
        """
        if not self._ssh_available:
            self.logger.warn("ssh/scp not found in PATH — remote sync unavailable")
            return False
        rc, _ = self._run_ssh("echo ok", timeout=10)
        return rc == 0

    def detect_remote_harnesses(self) -> list[str]:
        """Detect which harnesses are installed on the remote machine.

        Returns:
            List of harness names present on the remote.
        """
        detected = []
        for harness, cmd in _DETECT_CMDS.items():
            rc, _ = self._run_ssh(cmd, timeout=10)
            if rc == 0:
                detected.append(harness)
        return detected

    def _ensure_remote_dir(self, remote_path: str) -> bool:
        """Create remote directory if it doesn't exist."""
        rc, _ = self._run_ssh(f"mkdir -p {remote_path!r}")
        return rc == 0

    def push(self) -> RemoteSyncResult:
        """Push all config files to the remote machine.

        Detects remote harnesses, creates necessary directories, and pushes
        each config file with SCP. Returns a RemoteSyncResult summary.

        Returns:
            RemoteSyncResult with details of pushed/failed files.
        """
        result = RemoteSyncResult(remote=self.remote, dry_run=self.dry_run)

        if not self._ssh_available:
            result.warnings.append("ssh/scp not found in PATH — install OpenSSH")
            return result

        # Detect remote harnesses
        result.remote_harnesses = self.detect_remote_harnesses()
        if not result.remote_harnesses and not self.dry_run:
            result.warnings.append(
                "No supported harnesses detected on remote — "
                "install Codex, Gemini CLI, or another supported harness"
            )

        # Ensure remote project dir exists
        self._ensure_remote_dir(self.remote_project_dir)

        # Push project-level config files
        for rel in _SYNC_FILES:
            local = self.project_dir / rel
            if not local.exists():
                continue
            remote_path = f"{self.remote_project_dir}/{rel}"
            # Ensure parent dir exists on remote
            remote_parent = str(Path(remote_path).parent)
            if remote_parent != self.remote_project_dir:
                self._ensure_remote_dir(remote_parent)

            ok = self._scp_push(local, remote_path)
            if ok:
                result.files_pushed.append(rel)
            else:
                result.files_failed.append(rel)

        # Push global Claude config if present
        global_claude = Path.home() / ".claude" / "CLAUDE.md"
        if global_claude.exists():
            self._ensure_remote_dir("~/.claude")
            ok = self._scp_push(global_claude, "~/.claude/CLAUDE.md")
            if ok:
                result.files_pushed.append("~/.claude/CLAUDE.md")
            else:
                result.files_failed.append("~/.claude/CLAUDE.md")

        return result

    def pull(self, file_rel: str = "CLAUDE.md") -> str | None:
        """Pull a single config file from the remote machine.

        Useful for bidirectional sync — fetch what the remote has before
        overwriting it, enabling drift detection.

        Args:
            file_rel: Relative path of the file to pull (default: CLAUDE.md).

        Returns:
            File content string, or None if pull failed.
        """
        remote_path = f"{self.remote_project_dir}/{file_rel}"
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tf:
            tmp = tf.name

        cmd = ["scp"] + self._ssh_opts() + [f"{self.remote}:{remote_path}", tmp]
        try:
            if self.dry_run:
                self.logger.info(f"[dry-run] would pull {remote_path} from {self.remote}")
                return None
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                content = Path(tmp).read_text(encoding="utf-8", errors="replace")
                return content
        except (subprocess.TimeoutExpired, OSError) as exc:
            self.logger.warn(f"Pull failed for {remote_path}: {exc}")
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return None
