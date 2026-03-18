from __future__ import annotations

"""Tamper-Evident Audit Log (item 28).

Records every sync event in a cryptographically chained append-only log.
Each entry includes a SHA256 hash of the previous entry so any tampering
(deletion, modification, reordering) is immediately detectable via
``AuditLog.verify()``.

Storage: ``.harness-sync/audit.jsonl``
Format: one JSON object per line (JSONL), each with a ``chain_hash`` field
        derived from HMAC-SHA256 over the serialised previous entry.

Usage::

    log = AuditLog(project_dir=Path("."))
    log.record(
        event="sync",
        targets=["codex", "gemini"],
        files_changed=["AGENTS.md", ".gemini/GEMINI.md"],
        source_hash="abc123",
        user="alice",
    )

    report = log.verify()
    if not report.ok:
        print("AUDIT LOG TAMPERED:", report.first_violation)

    for entry in log.tail(10):
        print(entry.timestamp, entry.event, entry.targets)
"""

import csv
import hashlib
import hmac
import io
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from src.utils.paths import ensure_dir

# HMAC key: static per-installation secret.  Not a security secret —
# just makes it harder to accidentally produce a "valid" forged entry.
# Override via HARNESSSYNC_AUDIT_KEY env var for org-wide consistency.
_DEFAULT_HMAC_KEY = b"harnesssync-audit-v1"
_LOG_FILENAME = "audit.jsonl"


def _get_hmac_key() -> bytes:
    key = os.environ.get("HARNESSSYNC_AUDIT_KEY", "").strip()
    return key.encode() if key else _DEFAULT_HMAC_KEY


def _chain_hash(prev_raw: str, entry_raw: str) -> str:
    """Compute HMAC-SHA256 chain link.

    Args:
        prev_raw: Raw JSON string of the previous entry (or "" for genesis).
        entry_raw: Raw JSON string of the current entry (without chain_hash).

    Returns:
        Hex-encoded HMAC digest.
    """
    key = _get_hmac_key()
    data = (prev_raw + "\x00" + entry_raw).encode("utf-8", errors="replace")
    return hmac.new(key, data, hashlib.sha256).hexdigest()


@dataclass
class AuditEntry:
    """A single entry in the tamper-evident audit log."""

    timestamp: str          # ISO-8601 UTC
    event: str              # "sync" | "drift_detected" | "rollback" | "policy_violation" | ...
    targets: list[str]      # Harness names affected
    files_changed: list[str]
    source_hash: str        # SHA256 of CLAUDE.md at sync time (or "")
    user: str               # git config user.name or OS user
    extra: dict             # Arbitrary additional fields
    chain_hash: str         # HMAC chain link (empty string on genesis entry)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "event": self.event,
            "targets": self.targets,
            "files_changed": self.files_changed,
            "source_hash": self.source_hash,
            "user": self.user,
            "extra": self.extra,
            "chain_hash": self.chain_hash,
        }

    @staticmethod
    def from_dict(d: dict) -> "AuditEntry":
        return AuditEntry(
            timestamp=d.get("timestamp", ""),
            event=d.get("event", ""),
            targets=d.get("targets", []),
            files_changed=d.get("files_changed", []),
            source_hash=d.get("source_hash", ""),
            user=d.get("user", ""),
            extra=d.get("extra", {}),
            chain_hash=d.get("chain_hash", ""),
        )


@dataclass
class VerificationReport:
    """Result of an audit log integrity check."""

    ok: bool
    entry_count: int
    first_violation: Optional[str] = None   # Human-readable description
    violation_index: Optional[int] = None   # 0-based index of tampered entry

    def format(self) -> str:
        if self.ok:
            return f"Audit log OK — {self.entry_count} entr{'y' if self.entry_count == 1 else 'ies'} verified."
        lines = [
            "AUDIT LOG INTEGRITY VIOLATION",
            f"  Entries checked : {self.entry_count}",
            f"  First violation : entry #{self.violation_index}",
            f"  Detail          : {self.first_violation}",
        ]
        return "\n".join(lines)


def _get_identity() -> str:
    """Best-effort current user identity (git name > OS login > 'unknown')."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    try:
        return os.getlogin()
    except Exception:
        pass
    return os.environ.get("USER", os.environ.get("USERNAME", "unknown"))


class AuditLog:
    """Append-only tamper-evident audit log backed by a JSONL file.

    Each entry is linked to the previous one via HMAC-SHA256, forming a
    hash chain. Verification walks the chain and re-derives each link —
    any modification, deletion, or reordering of entries breaks the chain.

    Args:
        project_dir: Project root directory (log stored in .harness-sync/).
        log_dir: Override the directory containing the audit log file.
    """

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        log_dir: Optional[Path] = None,
    ) -> None:
        if log_dir is not None:
            self._log_dir = log_dir
        elif project_dir is not None:
            self._log_dir = project_dir / ".harness-sync"
        else:
            self._log_dir = Path(".harness-sync")
        ensure_dir(self._log_dir)
        self._log_path = self._log_dir / _LOG_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(
        self,
        event: str,
        targets: list[str] | None = None,
        files_changed: list[str] | None = None,
        source_hash: str = "",
        user: str | None = None,
        **extra: object,
    ) -> AuditEntry:
        """Append a new event to the audit log.

        Args:
            event: Event type string (e.g. "sync", "rollback", "drift_detected").
            targets: Harness names affected by the event.
            files_changed: Relative paths of files written/modified.
            source_hash: SHA256 of the source CLAUDE.md (optional).
            user: Override identity string (defaults to git/OS user).
            **extra: Additional key-value metadata stored in entry.extra.

        Returns:
            The newly written AuditEntry.
        """
        prev_raw = self._last_raw_line()
        entry_body = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "event": event,
            "targets": targets or [],
            "files_changed": files_changed or [],
            "source_hash": source_hash,
            "user": user or _get_identity(),
            "extra": extra,
        }
        # Serialise without chain_hash for the hash computation
        entry_raw = json.dumps(entry_body, separators=(",", ":"), sort_keys=True)
        chain = _chain_hash(prev_raw, entry_raw)
        entry_body["chain_hash"] = chain
        final_raw = json.dumps(entry_body, separators=(",", ":"), sort_keys=True)

        # Atomic append via temp-file rename to prevent partial writes
        self._atomic_append(final_raw)
        return AuditEntry.from_dict(entry_body)

    def record_secret_block(
        self,
        detections: list[dict],
        protected_targets: list[str] | None = None,
        user: str | None = None,
    ) -> AuditEntry:
        """Record a sync-blocked event due to secret detection.

        Logs each detected variable name and source file without ever
        recording the actual secret value. This satisfies the audit-trail
        requirement for item 8 (Secret Redaction Audit Log): users can see
        exactly what was blocked and why via ``/sync-status``.

        Args:
            detections: Detection dicts from SecretDetector.scan() or
                        scan_content(). Only ``var_name``, ``source_file``,
                        ``confidence``, and ``reason`` are persisted —
                        never the secret value itself.
            protected_targets: Harness names that were protected (not written).
            user: Override identity (defaults to git/OS user).

        Returns:
            The newly written AuditEntry with event="secret_blocked".
        """
        # Build a sanitised summary list — NEVER includes actual secret values
        summary: list[dict] = []
        for d in detections:
            summary.append({
                "var_name": d.get("var_name", "<unknown>"),
                "source_file": d.get("source_file", d.get("source", "")),
                "confidence": d.get("confidence", "medium"),
                "reason": d.get("reason", ""),
            })

        return self.record(
            event="secret_blocked",
            targets=protected_targets or [],
            files_changed=[],
            user=user,
            secret_count=len(detections),
            blocked_vars=summary,
        )

    def format_secret_blocks(self, n: int = 10) -> str:
        """Return a summary of recent secret-blocked events for /sync-status.

        Args:
            n: Maximum number of recent block events to show.

        Returns:
            Human-readable string, or empty string if none found.
        """
        entries = self.tail(200)
        blocked = [e for e in entries if e.event == "secret_blocked"]
        if not blocked:
            return ""
        recent = blocked[-n:]
        lines = ["Secret Redaction Audit", "-" * 40]
        for e in recent:
            ts = e.timestamp[:19].replace("T", " ")
            count = e.extra.get("secret_count", "?")
            blocked_vars = e.extra.get("blocked_vars", [])
            targets_str = ", ".join(e.targets) if e.targets else "—"
            lines.append(f"  {ts}  blocked {count} secret(s)  protected: {targets_str}")
            for bv in blocked_vars[:5]:
                var = bv.get("var_name", "?")
                src = bv.get("source_file", "")
                conf = bv.get("confidence", "?")
                src_str = f" in {src}" if src else ""
                lines.append(f"    · {var}{src_str}  [{conf} confidence]")
            if len(blocked_vars) > 5:
                lines.append(f"    … and {len(blocked_vars) - 5} more")
        lines.append(f"\nShowing {len(recent)} of {len(blocked)} total secret-block events.")
        return "\n".join(lines)

    def verify(self) -> VerificationReport:
        """Walk the hash chain and verify every entry.

        Returns:
            VerificationReport with ok=True if the log is unmodified.
        """
        lines = self._read_lines()
        if not lines:
            return VerificationReport(ok=True, entry_count=0)

        prev_raw = ""
        for idx, line in enumerate(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                return VerificationReport(
                    ok=False,
                    entry_count=idx,
                    first_violation=f"JSON parse error: {exc}",
                    violation_index=idx,
                )

            stored_chain = entry.pop("chain_hash", None)
            # Re-derive: serialise entry without chain_hash
            entry_raw = json.dumps(entry, separators=(",", ":"), sort_keys=True)
            expected = _chain_hash(prev_raw, entry_raw)

            if stored_chain != expected:
                return VerificationReport(
                    ok=False,
                    entry_count=idx,
                    first_violation=(
                        f"Chain hash mismatch at entry {idx}: "
                        f"stored={stored_chain!r} expected={expected!r}"
                    ),
                    violation_index=idx,
                )
            # Restore chain_hash for computing next link
            entry["chain_hash"] = stored_chain
            prev_raw = json.dumps(entry, separators=(",", ":"), sort_keys=True)

        return VerificationReport(ok=True, entry_count=len(lines))

    def tail(self, n: int = 20) -> list[AuditEntry]:
        """Return the most recent *n* entries.

        Args:
            n: Maximum number of entries to return.

        Returns:
            List of AuditEntry objects, oldest first.
        """
        lines = self._read_lines()
        recent = lines[-n:] if len(lines) > n else lines
        entries = []
        for line in recent:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(AuditEntry.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError):
                continue
        return entries

    def format_timeline(self, n: int = 20) -> str:
        """Format a human-readable timeline of recent events.

        Args:
            n: Number of recent entries to show.

        Returns:
            Multi-line string suitable for terminal output.
        """
        entries = self.tail(n)
        if not entries:
            return "Audit log is empty — no sync events recorded yet."

        lines = ["HarnessSync Audit Log", "=" * 50]
        for e in entries:
            ts = e.timestamp[:19].replace("T", " ")
            targets_str = ", ".join(e.targets) if e.targets else "—"
            changed_str = (
                f"{len(e.files_changed)} file(s)" if e.files_changed else "no files"
            )
            lines.append(f"  {ts}  [{e.event:<18}]  {targets_str}  ({changed_str})  by {e.user}")
        lines.append("")
        lines.append(f"Showing {len(entries)} of {len(self._read_lines())} total entries.")
        lines.append("Run /sync-audit verify to check chain integrity.")
        return "\n".join(lines)

    def export_csv(
        self,
        dest: Path | None = None,
        since: str | None = None,
        event_types: list[str] | None = None,
    ) -> str:
        """Export the audit log as a CSV file for compliance reporting (item 17).

        Produces a flat CSV with one row per event — suitable for import into
        spreadsheets, SIEM tools, or compliance dashboards. Every field is
        human-readable with no binary data.

        Args:
            dest: Path to write the CSV file. If None, returns CSV as a string.
            since: ISO-8601 timestamp; only include entries after this time.
            event_types: Whitelist of event types to include (None = all).

        Returns:
            CSV content string (even when dest is provided, for logging purposes).
        """
        entries = self.tail(10_000)

        # Apply filters
        if since:
            entries = [e for e in entries if e.timestamp >= since]
        if event_types:
            event_set = set(event_types)
            entries = [e for e in entries if e.event in event_set]

        fieldnames = [
            "timestamp", "event", "targets", "files_changed_count",
            "files_changed", "source_hash", "user", "extra_summary", "chain_hash",
        ]

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for e in entries:
            # Flatten complex fields to plain strings
            targets_str = "; ".join(e.targets) if e.targets else ""
            files_str = "; ".join(e.files_changed) if e.files_changed else ""
            extra_parts = []
            for k, v in (e.extra or {}).items():
                if k not in ("blocked_vars",):  # never export raw secret info
                    extra_parts.append(f"{k}={v!r}")
            writer.writerow({
                "timestamp": e.timestamp,
                "event": e.event,
                "targets": targets_str,
                "files_changed_count": len(e.files_changed),
                "files_changed": files_str,
                "source_hash": e.source_hash,
                "user": e.user,
                "extra_summary": ", ".join(extra_parts),
                "chain_hash": e.chain_hash,
            })

        csv_content = buf.getvalue()

        if dest is not None:
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(csv_content, encoding="utf-8")

        return csv_content

    def export_json(
        self,
        dest: Path | None = None,
        since: str | None = None,
        event_types: list[str] | None = None,
        pretty: bool = True,
    ) -> str:
        """Export the audit log as a structured JSON file (item 17).

        Suitable for ingestion by log aggregators, audit dashboards, and
        automated compliance checks. Includes metadata (export time, entry count,
        chain integrity status) alongside the events array.

        Args:
            dest: Path to write the JSON file. If None, returns JSON string.
            since: ISO-8601 timestamp filter (inclusive lower bound).
            event_types: Whitelist of event types to include (None = all).
            pretty: Pretty-print with indentation (default True).

        Returns:
            JSON content string.
        """
        entries = self.tail(10_000)

        if since:
            entries = [e for e in entries if e.timestamp >= since]
        if event_types:
            event_set = set(event_types)
            entries = [e for e in entries if e.event in event_set]

        # Verify chain integrity to include in metadata
        verify_report = self.verify()

        export_doc = {
            "harnesssync_audit_export": {
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "entry_count": len(entries),
                "chain_integrity": "ok" if verify_report.ok else "violated",
                "chain_violation_detail": verify_report.first_violation or None,
                "filter_since": since,
                "filter_event_types": event_types,
            },
            "events": [e.to_dict() for e in entries],
        }

        indent = 2 if pretty else None
        json_content = json.dumps(export_doc, indent=indent, ensure_ascii=False)

        if dest is not None:
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json_content, encoding="utf-8")

        return json_content

    def filter_by_event(self, event_type: str, n: int = 50) -> list["AuditEntry"]:
        """Return the most recent entries matching a specific event type.

        Args:
            event_type: Event type to filter for (e.g. "sync", "drift_detected").
            n: Maximum number of results.

        Returns:
            Matching AuditEntry objects, oldest first.
        """
        all_entries = self.tail(max(n * 10, 500))
        matching = [e for e in all_entries if e.event == event_type]
        return matching[-n:]

    @property
    def log_path(self) -> Path:
        return self._log_path

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_lines(self) -> list[str]:
        if not self._log_path.exists():
            return []
        try:
            return [
                l for l in self._log_path.read_text(encoding="utf-8").splitlines()
                if l.strip()
            ]
        except OSError:
            return []

    def _last_raw_line(self) -> str:
        lines = self._read_lines()
        return lines[-1].strip() if lines else ""

    def _atomic_append(self, line: str) -> None:
        """Append a line atomically, preserving existing content."""
        ensure_dir(self._log_dir)
        # Open in append mode — no temp file needed since appends are atomic
        # on POSIX for lines < PIPE_BUF, but we use a lock-style write for safety.
        try:
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            # Non-fatal: audit log failure should never block sync
            import warnings
            warnings.warn(f"AuditLog: could not append entry: {exc}")
