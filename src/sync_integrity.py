from __future__ import annotations

"""Sync integrity verification — cryptographic signing of synced configs.

Signs synced harness configs with HMAC-SHA256 at write time and verifies
signatures before reads, flagging tampering or external modification.

Provides an audit trail for team environments where synced AGENTS.md or
GEMINI.md could be modified by malicious or accidental out-of-band edits.

How it works:
1. When a target file is written by HarnessSync, sign_file() computes
   HMAC-SHA256 over the file content using a local machine secret and
   stores the signature in .harness-sync/signatures.json.

2. Before reading or comparing synced configs, verify_file() recomputes
   the HMAC and checks it against the stored signature. A mismatch means
   the file was modified after HarnessSync last wrote it.

3. The HMAC key is stored in ~/.harnesssync/integrity.key (created on first
   use, never transmitted). Teams can opt in to a shared key via env var
   HARNESSSYNC_INTEGRITY_KEY for cross-machine consistency.

Security properties:
- Detects out-of-band modifications to synced config files.
- Does NOT prevent modifications — only surfaces them.
- The key is a local secret; signatures are per-machine by default.
- Signatures are stored separately from content so they survive re-sync.
"""

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# Signatures database location
_SIGS_FILENAME = "signatures.json"

# Local HMAC key file (generated on first use)
_KEY_FILE = Path.home() / ".harnesssync" / "integrity.key"


def _load_or_create_key() -> bytes:
    """Load the local HMAC signing key, creating it if it doesn't exist.

    Key priority:
    1. HARNESSSYNC_INTEGRITY_KEY env var (hex-encoded, enables team sharing)
    2. ~/.harnesssync/integrity.key file (machine-local, auto-generated)

    Returns:
        32-byte HMAC key.
    """
    env_key = os.environ.get("HARNESSSYNC_INTEGRITY_KEY", "").strip()
    if env_key:
        try:
            return bytes.fromhex(env_key)[:32].ljust(32, b"\x00")
        except ValueError:
            pass  # Invalid hex — fall through to file key

    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if _KEY_FILE.exists():
        try:
            return bytes.fromhex(_KEY_FILE.read_text().strip())
        except (ValueError, OSError):
            pass

    # Generate and persist a new random key
    key = secrets.token_bytes(32)
    try:
        _KEY_FILE.write_text(key.hex())
        _KEY_FILE.chmod(0o600)
    except OSError:
        pass
    return key


def _compute_signature(content: bytes, key: bytes) -> str:
    """Compute HMAC-SHA256 signature for file content.

    Args:
        content: Raw file bytes to sign.
        key: 32-byte HMAC key.

    Returns:
        Hex-encoded HMAC-SHA256 signature string.
    """
    return hmac.new(key, content, hashlib.sha256).hexdigest()


@dataclass
class SignatureRecord:
    """Stored signature record for a single file."""
    path: str          # Absolute path (resolved)
    signature: str     # Hex HMAC-SHA256
    size: int          # File size in bytes at signing time
    signed_at: str     # ISO timestamp

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "signature": self.signature,
            "size": self.size,
            "signed_at": self.signed_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SignatureRecord:
        return cls(
            path=d["path"],
            signature=d["signature"],
            size=d.get("size", 0),
            signed_at=d.get("signed_at", ""),
        )


@dataclass
class VerificationResult:
    """Result of verifying one or more file signatures."""
    verified: list[str] = field(default_factory=list)    # Paths that verified OK
    tampered: list[str] = field(default_factory=list)    # Paths with bad signature
    unsigned: list[str] = field(default_factory=list)    # Paths with no stored sig
    missing: list[str] = field(default_factory=list)     # Paths that no longer exist

    @property
    def all_ok(self) -> bool:
        return not self.tampered and not self.missing

    @property
    def has_issues(self) -> bool:
        return bool(self.tampered or self.missing)

    def format(self) -> str:
        lines = ["Sync Integrity Report"]
        lines.append("=" * 40)
        if self.verified:
            lines.append(f"✓ Verified:  {len(self.verified)} file(s)")
        if self.unsigned:
            lines.append(f"? Unsigned:  {len(self.unsigned)} file(s) (no signature on record)")
        if self.tampered:
            lines.append(f"⚠ TAMPERED:  {len(self.tampered)} file(s) — out-of-band modification detected")
            for path in self.tampered:
                lines.append(f"    {path}")
        if self.missing:
            lines.append(f"✗ Missing:   {len(self.missing)} file(s) — signed files no longer exist")
            for path in self.missing:
                lines.append(f"    {path}")
        if self.all_ok and not self.unsigned:
            lines.append("All synced configs verified.")
        return "\n".join(lines)


class SyncIntegrityStore:
    """Manages HMAC signatures for synced harness config files.

    Signatures are stored in <project_dir>/.harness-sync/signatures.json.
    Each entry maps the resolved absolute file path to its HMAC-SHA256
    signature, file size, and signing timestamp.

    Usage:
        store = SyncIntegrityStore(project_dir=Path("."))
        store.sign_file(Path("AGENTS.md"))      # Called after writing
        result = store.verify_file(Path("AGENTS.md"))   # Called before reading
    """

    def __init__(self, project_dir: Path | None = None):
        """Initialize the integrity store.

        Args:
            project_dir: Project root directory. Signatures stored in
                         <project_dir>/.harness-sync/signatures.json.
        """
        self._project_dir = project_dir or Path.cwd()
        self._sigs_dir = self._project_dir / ".harness-sync"
        self._sigs_path = self._sigs_dir / _SIGS_FILENAME
        self._key = _load_or_create_key()
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        """Load signatures database from disk."""
        if not self._sigs_path.exists():
            return {}
        try:
            return json.loads(self._sigs_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        """Persist signatures database to disk."""
        self._sigs_dir.mkdir(parents=True, exist_ok=True)
        self._sigs_path.write_text(
            json.dumps(self._data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def sign_file(self, file_path: Path) -> SignatureRecord | None:
        """Compute and store the HMAC signature for a file.

        Should be called immediately after HarnessSync writes a target file.

        Args:
            file_path: Path to the file to sign (need not be inside project_dir).

        Returns:
            SignatureRecord if signing succeeded, None if file unreadable.
        """
        from datetime import datetime, timezone

        resolved = file_path.resolve()
        try:
            content = resolved.read_bytes()
        except OSError:
            return None

        sig = _compute_signature(content, self._key)
        record = SignatureRecord(
            path=str(resolved),
            signature=sig,
            size=len(content),
            signed_at=datetime.now(tz=timezone.utc).isoformat(),
        )
        self._data[str(resolved)] = record.to_dict()
        self._save()
        return record

    def verify_file(self, file_path: Path) -> str:
        """Verify the integrity of a single synced file.

        Args:
            file_path: Path to verify.

        Returns:
            One of: "ok" | "tampered" | "unsigned" | "missing"
        """
        resolved = file_path.resolve()
        key = str(resolved)

        if key not in self._data:
            return "unsigned"

        if not resolved.exists():
            return "missing"

        try:
            content = resolved.read_bytes()
        except OSError:
            return "missing"

        stored_sig = self._data[key]["signature"]
        actual_sig = _compute_signature(content, self._key)

        if hmac.compare_digest(actual_sig, stored_sig):
            return "ok"
        return "tampered"

    def verify_all(self) -> VerificationResult:
        """Verify all signed files in the database.

        Returns:
            VerificationResult summarizing the verification status of all files.
        """
        result = VerificationResult()
        for path_str in self._data:
            status = self.verify_file(Path(path_str))
            if status == "ok":
                result.verified.append(path_str)
            elif status == "tampered":
                result.tampered.append(path_str)
            elif status == "missing":
                result.missing.append(path_str)
            else:
                result.unsigned.append(path_str)
        return result

    def sign_target_files(self, target_files: list[Path]) -> int:
        """Sign multiple target files in bulk.

        Convenience method for signing all files written in a sync operation.

        Args:
            target_files: List of file paths to sign.

        Returns:
            Number of files successfully signed.
        """
        signed = 0
        for f in target_files:
            if self.sign_file(f) is not None:
                signed += 1
        return signed

    def revoke(self, file_path: Path) -> bool:
        """Remove the stored signature for a file (e.g. when deleting it).

        Args:
            file_path: Path to revoke signature for.

        Returns:
            True if a signature was removed, False if not found.
        """
        key = str(file_path.resolve())
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False

    def summary(self) -> dict:
        """Return a summary dict of signing coverage.

        Returns:
            Dict with counts of total, verified, tampered, unsigned, and missing.
        """
        result = self.verify_all()
        return {
            "total_signed": len(self._data),
            "verified": len(result.verified),
            "tampered": len(result.tampered),
            "unsigned": len(result.unsigned),
            "missing": len(result.missing),
        }


# ---------------------------------------------------------------------------
# Immutable Sync Audit Trail (Item 24)
# ---------------------------------------------------------------------------
#
# Maintains a tamper-evident append-only log of every sync operation with:
#   - ISO timestamp
#   - trigger (manual / hook / ci)
#   - targets affected
#   - per-file before/after SHA-256 hashes
#   - HMAC-SHA256 chain signature linking entries (detects tampering of log)
#
# Log is stored at <project_dir>/.harness-sync/audit.log (JSONL format).
# Each line is a JSON object.  The chain signature is computed as
# HMAC(prev_chain_sig + entry_json, key) so any edit to a prior entry
# invalidates all subsequent signatures.


_AUDIT_LOG_FILENAME = "audit.log"


@dataclass
class AuditEntry:
    """One sync audit log entry."""
    timestamp: str          # ISO-8601 timestamp
    trigger: str            # "manual" | "hook" | "ci" | "unknown"
    targets: list[str]      # Harnesses synced in this operation
    file_changes: list[dict]  # [{file, before_hash, after_hash, action}]
    chain_sig: str          # HMAC chain signature (hex)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "trigger": self.trigger,
            "targets": self.targets,
            "file_changes": self.file_changes,
            "chain_sig": self.chain_sig,
        }


class SyncAuditLog:
    """Append-only audit log for sync operations.

    Args:
        project_dir: Project root. Log written to
                     <project_dir>/.harness-sync/audit.log.
    """

    def __init__(self, project_dir: Path | None = None):
        self._project_dir = project_dir or Path.cwd()
        self._log_dir = self._project_dir / ".harness-sync"
        self._log_path = self._log_dir / _AUDIT_LOG_FILENAME
        self._key = _load_or_create_key()

    def _last_chain_sig(self) -> str:
        """Return the chain signature of the last entry, or 'GENESIS'."""
        if not self._log_path.exists():
            return "GENESIS"
        try:
            lines = self._log_path.read_text(encoding="utf-8").splitlines()
            for line in reversed(lines):
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    return entry.get("chain_sig", "GENESIS")
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        return "GENESIS"

    def append(
        self,
        targets: list[str],
        file_changes: list[dict],
        trigger: str = "manual",
    ) -> AuditEntry:
        """Append a sync operation to the audit log.

        Args:
            targets: List of harness names that were synced.
            file_changes: List of per-file change dicts, each with keys:
                          ``file`` (path str), ``action`` ("created" |
                          "modified" | "deleted"), ``before_hash`` (hex or ""),
                          ``after_hash`` (hex or "").
            trigger: What triggered this sync ("manual", "hook", "ci").

        Returns:
            The appended AuditEntry.
        """
        timestamp = datetime.now(timezone.utc).isoformat()
        prev_sig = self._last_chain_sig()

        # Build the entry dict (without chain_sig) for signing
        entry_core = {
            "timestamp": timestamp,
            "trigger": trigger,
            "targets": sorted(targets),
            "file_changes": file_changes,
        }
        core_json = json.dumps(entry_core, sort_keys=True, ensure_ascii=False)
        chain_input = (prev_sig + core_json).encode("utf-8")
        chain_sig = hmac.new(self._key, chain_input, hashlib.sha256).hexdigest()

        entry = AuditEntry(
            timestamp=timestamp,
            trigger=trigger,
            targets=sorted(targets),
            file_changes=file_changes,
            chain_sig=chain_sig,
        )

        self._log_dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
        with open(self._log_path, "a", encoding="utf-8") as fh:
            fh.write(line)

        return entry

    def read_all(self) -> list[AuditEntry]:
        """Read all audit log entries (chronological order).

        Returns:
            List of AuditEntry objects. Empty if log does not exist.
        """
        if not self._log_path.exists():
            return []
        entries: list[AuditEntry] = []
        try:
            for line in self._log_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    entries.append(AuditEntry(
                        timestamp=d.get("timestamp", ""),
                        trigger=d.get("trigger", "unknown"),
                        targets=d.get("targets", []),
                        file_changes=d.get("file_changes", []),
                        chain_sig=d.get("chain_sig", ""),
                    ))
                except (json.JSONDecodeError, KeyError):
                    continue
        except OSError:
            pass
        return entries

    def verify_chain(self) -> tuple[bool, int]:
        """Verify the HMAC chain across all audit log entries.

        Recomputes chain signatures from scratch and confirms each entry's
        stored ``chain_sig`` matches. A mismatch means the log was tampered
        with after the fact.

        Returns:
            Tuple of (chain_intact: bool, first_bad_index: int).
            If intact, first_bad_index is -1.
        """
        entries = self.read_all()
        prev_sig = "GENESIS"

        for i, entry in enumerate(entries):
            core = {
                "timestamp": entry.timestamp,
                "trigger": entry.trigger,
                "targets": entry.targets,
                "file_changes": entry.file_changes,
            }
            core_json = json.dumps(core, sort_keys=True, ensure_ascii=False)
            chain_input = (prev_sig + core_json).encode("utf-8")
            expected = hmac.new(self._key, chain_input, hashlib.sha256).hexdigest()

            if not hmac.compare_digest(expected, entry.chain_sig):
                return False, i

            prev_sig = entry.chain_sig

        return True, -1

    def format_recent(self, n: int = 10) -> str:
        """Format the N most recent audit log entries as a human-readable string.

        Args:
            n: Number of most-recent entries to show (default 10).

        Returns:
            Formatted string, or message if log is empty.
        """
        entries = self.read_all()
        if not entries:
            return "Audit log is empty — no syncs recorded yet."

        recent = entries[-n:]
        lines = [f"Sync Audit Log (last {len(recent)} of {len(entries)} entries)", "=" * 60]

        for entry in reversed(recent):
            ts = entry.timestamp[:19].replace("T", " ")
            targets = ", ".join(entry.targets) or "none"
            changes = len(entry.file_changes)
            lines.append(f"  {ts}  [{entry.trigger}]  targets: {targets}  files: {changes}")
            for fc in entry.file_changes:
                action = fc.get("action", "?")
                fpath = fc.get("file", "?")
                before = (fc.get("before_hash") or "")[:8]
                after = (fc.get("after_hash") or "")[:8]
                hash_part = f"  {before or 'new'}→{after or 'del'}" if (before or after) else ""
                lines.append(f"      {action:<9} {fpath}{hash_part}")

        return "\n".join(lines)
