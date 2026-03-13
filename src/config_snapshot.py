from __future__ import annotations

"""Shareable config snapshot — export and import Claude Code config as a bundle.

Lets users share their full Claude Code configuration (rules, MCP servers,
settings) as a single compressed JSON blob, exportable to a file, stdout,
or a GitHub Gist URL.

Recipients import with:
    /sync-snapshot import <file-or-url>
    /sync-snapshot import --gist <gist-id>

HarnessSync immediately syncs imported config to all detected harnesses.

Snapshot format (JSON, gzip-compressed + base64 for URL embedding):
    {
        "version": "1",
        "created_at": "2025-03-11T00:00:00Z",
        "creator": "optional label",
        "rules": "...",
        "mcp": {...},
        "settings": {...},
        "skills_manifest": [{"name": "...", "description": "..."}],
        "agents_manifest": [{"name": "...", "description": "..."}]
    }

Note: Skills and agents are manifested (name + description only), not
bundled, to keep snapshot size manageable and avoid bundling credentials
that might be embedded in skill content.
"""

import base64
import gzip
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


_SNAPSHOT_VERSION = "1"
_GIST_API = "https://api.github.com/gists"
_SNAPSHOT_FILENAME = "harnesssync-config.json"


class ConfigSnapshot:
    """Create and restore shareable configuration snapshots.

    Args:
        source_reader: SourceReader instance for reading current config.
                       If None, snapshot import/export works with raw dicts.
    """

    def __init__(self, source_reader=None):
        self.source_reader = source_reader

    # ──────────────────────────────────────────────────────────────────────────
    # Export
    # ──────────────────────────────────────────────────────────────────────────

    def create(self, creator: str = "") -> dict:
        """Build a snapshot dict from current Claude Code config.

        Args:
            creator: Optional label to embed (e.g. "neo@acme").

        Returns:
            Snapshot dict.
        """
        rules = ""
        mcp: dict = {}
        settings: dict = {}
        skills_manifest: list[dict] = []
        agents_manifest: list[dict] = []

        if self.source_reader:
            try:
                rules_list = self.source_reader.get_rules()
                rules = "\n\n".join(r.get("content", "") for r in rules_list)
            except Exception:
                pass

            try:
                mcp = self.source_reader.get_mcp_servers()
                # Strip scoped wrapper if present
                mcp = {
                    name: (cfg["config"] if isinstance(cfg, dict) and "config" in cfg else cfg)
                    for name, cfg in mcp.items()
                }
            except Exception:
                pass

            try:
                settings = self.source_reader.get_settings()
                # Strip sensitive keys
                settings = {
                    k: v for k, v in settings.items()
                    if k not in ("apiKey", "api_key", "token", "secret")
                }
            except Exception:
                pass

            try:
                skills = self.source_reader.get_skills()
                skills_manifest = [
                    {"name": s.get("name", ""), "description": s.get("description", "")}
                    for s in skills
                ]
            except Exception:
                pass

            try:
                agents = self.source_reader.get_agents()
                agents_manifest = [
                    {"name": a.get("name", ""), "description": a.get("description", "")}
                    for a in agents
                ]
            except Exception:
                pass

        snapshot = {
            "version": _SNAPSHOT_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "creator": creator,
            "rules": rules,
            "mcp": mcp,
            "settings": settings,
            "skills_manifest": skills_manifest,
            "agents_manifest": agents_manifest,
        }
        return snapshot

    def to_json(self, snapshot: dict) -> str:
        """Serialize snapshot to indented JSON string."""
        return json.dumps(snapshot, indent=2, ensure_ascii=False)

    def to_compressed_b64(self, snapshot: dict) -> str:
        """Compress snapshot JSON and base64-encode it for URL embedding.

        Returns:
            URL-safe base64 string of gzip-compressed JSON.
        """
        raw = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        compressed = gzip.compress(raw, compresslevel=9)
        return base64.urlsafe_b64encode(compressed).decode("ascii")

    def from_compressed_b64(self, encoded: str) -> dict:
        """Decode and decompress a base64-encoded snapshot.

        Args:
            encoded: Output of to_compressed_b64().

        Returns:
            Snapshot dict.

        Raises:
            ValueError: If decoding or decompression fails.
        """
        try:
            compressed = base64.urlsafe_b64decode(encoded + "==")
            raw = gzip.decompress(compressed)
            return json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise ValueError(f"Invalid snapshot data: {e}") from e

    def export_to_file(self, path: Path, creator: str = "") -> dict:
        """Create snapshot and write it to a file.

        Args:
            path: Output file path.
            creator: Optional creator label.

        Returns:
            The created snapshot dict.
        """
        snapshot = self.create(creator=creator)
        path.write_text(self.to_json(snapshot), encoding="utf-8")
        return snapshot

    def export_to_gist(self, github_token: str, creator: str = "", public: bool = False) -> str:
        """Create snapshot and publish it as a GitHub Gist.

        Args:
            github_token: GitHub personal access token with gist scope.
            creator: Optional creator label.
            public: Whether the gist should be public (default: secret).

        Returns:
            URL of the created Gist.

        Raises:
            RuntimeError: If Gist creation fails.
        """
        snapshot = self.create(creator=creator)
        payload = {
            "description": f"HarnessSync config snapshot — {snapshot['created_at']}",
            "public": public,
            "files": {
                _SNAPSHOT_FILENAME: {
                    "content": self.to_json(snapshot),
                }
            },
        }

        req = urllib.request.Request(
            _GIST_API,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"token {github_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "User-Agent": "HarnessSync/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("html_url", data.get("url", ""))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"GitHub API error {e.code}: {body}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}") from e

    # ──────────────────────────────────────────────────────────────────────────
    # Import
    # ──────────────────────────────────────────────────────────────────────────

    def load_from_file(self, path: Path) -> dict:
        """Load a snapshot from a JSON file.

        Args:
            path: Path to snapshot file.

        Returns:
            Snapshot dict.

        Raises:
            ValueError: If the file is not a valid snapshot.
        """
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in snapshot file: {e}") from e

        self._validate(data)
        return data

    def load_from_gist(self, gist_id_or_url: str) -> dict:
        """Fetch and load a snapshot from a GitHub Gist.

        Args:
            gist_id_or_url: Gist ID (e.g. "abc123") or full gist URL.

        Returns:
            Snapshot dict.

        Raises:
            RuntimeError: If fetching fails.
            ValueError: If the gist doesn't contain a valid snapshot.
        """
        # Extract gist ID from URL if needed
        gist_id = gist_id_or_url
        if "/" in gist_id_or_url:
            gist_id = gist_id_or_url.rstrip("/").split("/")[-1]

        api_url = f"{_GIST_API}/{gist_id}"
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "HarnessSync/1.0",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                gist_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"GitHub API error {e.code} fetching gist {gist_id}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Network error: {e.reason}") from e

        files = gist_data.get("files", {})
        # Find the snapshot file
        snapshot_file = files.get(_SNAPSHOT_FILENAME)
        if not snapshot_file:
            # Try first .json file
            for fname, fdata in files.items():
                if fname.endswith(".json"):
                    snapshot_file = fdata
                    break

        if not snapshot_file:
            raise ValueError(f"No JSON file found in gist {gist_id}")

        content = snapshot_file.get("content", "")
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in gist file: {e}") from e

        self._validate(data)
        return data

    def apply_to_claude_md(self, snapshot: dict, target_path: Path, dry_run: bool = False) -> str:
        """Apply the rules section of a snapshot to a CLAUDE.md file.

        Existing content is preserved — the snapshot rules are appended
        in a clearly-marked import block.

        Args:
            snapshot: Snapshot dict.
            target_path: Path to CLAUDE.md.
            dry_run: If True, return the new content without writing.

        Returns:
            The new CLAUDE.md content (whether written or not).
        """
        rules = snapshot.get("rules", "").strip()
        if not rules:
            current = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
            return current

        timestamp = snapshot.get("created_at", "")
        creator = snapshot.get("creator", "")
        label = f" from {creator}" if creator else ""
        header = f"\n\n<!-- Imported{label} via HarnessSync snapshot ({timestamp}) -->\n"
        footer = "\n<!-- End snapshot import -->\n"

        current = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
        new_content = current.rstrip() + header + rules + footer

        if not dry_run:
            target_path.write_text(new_content, encoding="utf-8")

        return new_content

    def format_summary(self, snapshot: dict) -> str:
        """Return a human-readable summary of a snapshot's contents."""
        lines = ["Config Snapshot Summary", "=" * 40]
        lines.append(f"Version:    {snapshot.get('version', '?')}")
        lines.append(f"Created:    {snapshot.get('created_at', 'unknown')}")
        if snapshot.get("creator"):
            lines.append(f"Creator:    {snapshot['creator']}")

        rule_lines = len(snapshot.get("rules", "").splitlines())
        lines.append(f"Rules:      {rule_lines} lines")

        mcp = snapshot.get("mcp", {})
        lines.append(f"MCP:        {len(mcp)} server(s)" + (
            f" ({', '.join(sorted(mcp.keys()))})" if mcp else ""
        ))

        settings = snapshot.get("settings", {})
        lines.append(f"Settings:   {len(settings)} key(s)")

        skills = snapshot.get("skills_manifest", [])
        if skills:
            lines.append(f"Skills:     {len(skills)} (manifest only)")

        agents = snapshot.get("agents_manifest", [])
        if agents:
            lines.append(f"Agents:     {len(agents)} (manifest only)")

        return "\n".join(lines)

    def _validate(self, data: dict) -> None:
        """Raise ValueError if the dict is not a valid snapshot."""
        if not isinstance(data, dict):
            raise ValueError("Snapshot must be a JSON object")
        if data.get("version") != _SNAPSHOT_VERSION:
            version = data.get("version", "missing")
            raise ValueError(
                f"Unsupported snapshot version {version!r} (expected {_SNAPSHOT_VERSION!r})"
            )


# ──────────────────────────────────────────────────────────────────────────────
# Named Checkpoint Store
# ──────────────────────────────────────────────────────────────────────────────

import os
import tempfile


_CHECKPOINTS_DIR = Path.home() / ".harnesssync" / "checkpoints"


class NamedCheckpointStore:
    """Store and restore named configuration checkpoints.

    Allows users to tag the current synced state with a meaningful name
    (e.g. 'before-big-refactor', 'v2.1-release-setup') and restore any
    checkpoint later. Goes beyond ephemeral rollback to provide permanent,
    human-readable snapshots.

    Checkpoints are stored as JSON files under
    ``~/.harnesssync/checkpoints/<tag>.json``.

    Usage::

        store = NamedCheckpointStore()
        store.save("before-big-refactor", snapshot_dict)
        store.save("v2.1-release", snapshot_dict, notes="Release candidate config")

        tags = store.list_tags()
        snap = store.load("before-big-refactor")
        store.delete("old-tag")
    """

    def __init__(self, checkpoints_dir: Path | None = None):
        self.checkpoints_dir = checkpoints_dir or _CHECKPOINTS_DIR

    def _path(self, tag: str) -> Path:
        return self.checkpoints_dir / f"{tag}.json"

    @staticmethod
    def _validate_tag(tag: str) -> None:
        """Raise ValueError if tag contains unsafe characters."""
        # Allow alphanumeric, hyphens, underscores, dots — no slashes or spaces
        import re
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", tag):
            raise ValueError(
                f"Invalid checkpoint tag {tag!r}. "
                "Use alphanumeric characters, hyphens, underscores, or dots (max 64 chars)."
            )

    def list_tags(self) -> list[dict]:
        """Return checkpoint metadata sorted by creation time (newest first).

        Returns:
            List of dicts, each with keys: ``tag``, ``created_at``, ``notes``.
        """
        if not self.checkpoints_dir.exists():
            return []

        entries: list[dict] = []
        for path in self.checkpoints_dir.glob("*.json"):
            tag = path.stem
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entries.append({
                    "tag": tag,
                    "created_at": data.get("_checkpoint_created_at", ""),
                    "notes": data.get("_checkpoint_notes", ""),
                })
            except (json.JSONDecodeError, OSError):
                entries.append({"tag": tag, "created_at": "", "notes": ""})

        entries.sort(key=lambda e: e["created_at"], reverse=True)
        return entries

    def save(
        self,
        tag: str,
        snapshot: dict,
        notes: str = "",
        overwrite: bool = True,
    ) -> Path:
        """Save a named checkpoint.

        Args:
            tag: Unique checkpoint name (e.g. 'before-big-refactor').
            snapshot: Snapshot dict (from ConfigSnapshot.create()).
            notes: Optional human-readable note about this checkpoint.
            overwrite: If False, raise FileExistsError if tag already exists.

        Returns:
            Path to the saved checkpoint file.

        Raises:
            ValueError: If tag is invalid.
            FileExistsError: If tag exists and overwrite=False.
        """
        self._validate_tag(tag)
        dest = self._path(tag)

        if dest.exists() and not overwrite:
            raise FileExistsError(
                f"Checkpoint {tag!r} already exists. Pass overwrite=True to replace it."
            )

        # Embed checkpoint metadata into the snapshot dict (non-destructive copy)
        data = dict(snapshot)
        data["_checkpoint_tag"] = tag
        data["_checkpoint_created_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if notes:
            data["_checkpoint_notes"] = notes

        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

        # Atomic write
        tmp_fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.checkpoints_dir,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(data, tmp_fd, indent=2, ensure_ascii=False)
            tmp_fd.write("\n")
            tmp_fd.flush()
            os.fsync(tmp_fd.fileno())
            tmp_fd.close()
            os.replace(tmp_fd.name, str(dest))
        except Exception:
            tmp_fd.close()
            try:
                os.unlink(tmp_fd.name)
            except OSError:
                pass
            raise

        return dest

    def load(self, tag: str) -> dict:
        """Load a named checkpoint.

        Args:
            tag: Checkpoint name to load.

        Returns:
            Snapshot dict (with checkpoint metadata keys prefixed with ``_``).

        Raises:
            KeyError: If tag does not exist.
            ValueError: If the checkpoint file is not valid JSON.
        """
        self._validate_tag(tag)
        path = self._path(tag)
        if not path.exists():
            available = ", ".join(e["tag"] for e in self.list_tags()) or "none"
            raise KeyError(
                f"Checkpoint {tag!r} not found. Available: {available}"
            )
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"Checkpoint {tag!r} contains invalid JSON: {e}") from e

    def delete(self, tag: str) -> bool:
        """Delete a named checkpoint.

        Args:
            tag: Checkpoint name to delete.

        Returns:
            True if deleted, False if not found.
        """
        self._validate_tag(tag)
        path = self._path(tag)
        if not path.exists():
            return False
        path.unlink()
        return True

    def format_list(self) -> str:
        """Return a human-readable list of all checkpoints."""
        tags = self.list_tags()
        if not tags:
            return (
                "No named checkpoints. Create one with:\n"
                "  /sync-snapshot save <tag> [--notes 'description']"
            )

        lines = [f"Named Checkpoints ({len(tags)})", "=" * 40]
        for entry in tags:
            tag = entry["tag"]
            created = entry["created_at"][:19].replace("T", " ") if entry["created_at"] else "unknown"
            notes = f"  — {entry['notes']}" if entry["notes"] else ""
            lines.append(f"  {tag:<30} {created}{notes}")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Sync Audit Log
# ──────────────────────────────────────────────────────────────────────────────


_AUDIT_LOG_PATH = Path.home() / ".harnesssync" / "sync-audit.jsonl"
_AUDIT_LOG_MAX_ENTRIES = 1000  # Rolling window — oldest entries pruned


class SyncAuditLog:
    """Append-only audit log recording every sync operation.

    Solves the 'when did this rule change and who/what triggered it?' problem.
    Every call to ``record()`` appends a JSON line to the audit log file so
    there is a complete history of all sync operations.  Unlike named
    checkpoints (which users create manually), the audit log is written
    automatically by the orchestrator on every sync.

    Each log entry contains:
    - ``timestamp``: ISO-8601 UTC timestamp
    - ``trigger``: What initiated the sync (e.g. "command", "hook", "ci")
    - ``targets``: List of harness targets synced
    - ``sections``: Sections synced (empty = all)
    - ``dry_run``: Whether this was a dry-run
    - ``totals``: Dict with synced/skipped/failed counts
    - ``source_hash``: SHA-256 of CLAUDE.md at sync time (for diff detection)
    - ``project``: Project directory basename

    Args:
        log_path: Path to the JSONL audit log file.
                  Default: ``~/.harnesssync/sync-audit.jsonl``.
        max_entries: Maximum entries to keep before pruning oldest.
    """

    def __init__(
        self,
        log_path: Path | None = None,
        max_entries: int = _AUDIT_LOG_MAX_ENTRIES,
    ):
        self.log_path = log_path or _AUDIT_LOG_PATH
        self.max_entries = max_entries

    def record(
        self,
        targets: list[str],
        totals: dict,
        project: str = "",
        trigger: str = "command",
        sections: list[str] | None = None,
        dry_run: bool = False,
        source_hash: str = "",
    ) -> dict:
        """Append a sync operation to the audit log.

        Args:
            targets: Harness targets that were synced.
            totals: Dict with 'synced', 'skipped', 'failed' counts.
            project: Project directory basename (for multi-project users).
            trigger: What triggered the sync: "command", "hook", "ci", "schedule".
            sections: Sections synced (None/empty = all sections).
            dry_run: True if this was a preview-only sync.
            source_hash: SHA-256 of CLAUDE.md (first 12 chars is enough).

        Returns:
            The log entry dict that was written.
        """
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "trigger": trigger,
            "targets": list(targets),
            "sections": list(sections) if sections else [],
            "dry_run": dry_run,
            "totals": {
                "synced": totals.get("synced", 0),
                "skipped": totals.get("skipped", 0),
                "failed": totals.get("failed", 0),
            },
            "source_hash": source_hash[:12] if source_hash else "",
            "project": project,
        }

        self.log_path.parent.mkdir(parents=True, exist_ok=True)

        # Append new entry
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError:
            pass

        # Prune if over limit
        self._maybe_prune()

        return entry

    def tail(self, n: int = 20) -> list[dict]:
        """Return the last *n* audit log entries (most recent last).

        Args:
            n: Number of entries to return (default: 20).

        Returns:
            List of entry dicts, ordered oldest→newest.
        """
        return self._read_all()[-n:]

    def full_log(self) -> list[dict]:
        """Return all audit log entries, oldest first."""
        return self._read_all()

    def since(self, iso_timestamp: str) -> list[dict]:
        """Return entries with timestamps >= *iso_timestamp*.

        Args:
            iso_timestamp: ISO-8601 timestamp string (e.g. "2025-01-01T00:00:00Z").

        Returns:
            Filtered list of entry dicts.
        """
        return [e for e in self._read_all() if e.get("timestamp", "") >= iso_timestamp]

    def format_tail(self, n: int = 20) -> str:
        """Format the last *n* entries as a human-readable table.

        Args:
            n: Number of entries to display.

        Returns:
            Formatted string suitable for terminal output.
        """
        entries = self.tail(n)
        if not entries:
            return "No sync history found."

        lines = [f"Sync Audit Log — last {min(n, len(entries))} entries", "=" * 60]
        for e in entries:
            ts = e.get("timestamp", "")[:19].replace("T", " ")
            targets = ", ".join(e.get("targets", [])[:4]) or "all"
            if len(e.get("targets", [])) > 4:
                targets += f" +{len(e['targets']) - 4}"
            totals = e.get("totals", {})
            synced = totals.get("synced", 0)
            skipped = totals.get("skipped", 0)
            failed = totals.get("failed", 0)
            trigger = e.get("trigger", "?")
            dry_note = " [dry-run]" if e.get("dry_run") else ""
            fail_note = f" ✗{failed}" if failed else ""
            lines.append(
                f"  {ts}  {trigger:<8}  {targets:<30}  "
                f"+{synced} ~{skipped}{fail_note}{dry_note}"
            )
        return "\n".join(lines)

    def stats(self) -> dict:
        """Return aggregate statistics over the full log.

        Returns:
            Dict with keys:
            - total_syncs: int
            - total_synced: int
            - total_skipped: int
            - total_failed: int
            - targets_seen: sorted list of unique target names
            - first_sync: ISO timestamp or ""
            - last_sync: ISO timestamp or ""
        """
        entries = self._read_all()
        if not entries:
            return {
                "total_syncs": 0,
                "total_synced": 0,
                "total_skipped": 0,
                "total_failed": 0,
                "targets_seen": [],
                "first_sync": "",
                "last_sync": "",
            }
        total_synced = sum(e.get("totals", {}).get("synced", 0) for e in entries)
        total_skipped = sum(e.get("totals", {}).get("skipped", 0) for e in entries)
        total_failed = sum(e.get("totals", {}).get("failed", 0) for e in entries)
        all_targets: set[str] = set()
        for e in entries:
            all_targets.update(e.get("targets", []))
        return {
            "total_syncs": len(entries),
            "total_synced": total_synced,
            "total_skipped": total_skipped,
            "total_failed": total_failed,
            "targets_seen": sorted(all_targets),
            "first_sync": entries[0].get("timestamp", ""),
            "last_sync": entries[-1].get("timestamp", ""),
        }

    def clear(self) -> None:
        """Delete the audit log file (destructive — use with care)."""
        if self.log_path.exists():
            self.log_path.unlink()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _read_all(self) -> list[dict]:
        """Read and parse all JSONL entries from the log file."""
        if not self.log_path.exists():
            return []
        entries: list[dict] = []
        try:
            with open(self.log_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass  # Skip corrupt lines
        except OSError:
            pass
        return entries

    def _maybe_prune(self) -> None:
        """Remove oldest entries if the log exceeds max_entries."""
        entries = self._read_all()
        if len(entries) <= self.max_entries:
            return
        keep = entries[-self.max_entries:]
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                for entry in keep:
                    f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# Target Config Version History
# ──────────────────────────────────────────────────────────────────────────────


_TARGET_HISTORY_DIR = Path.home() / ".harnesssync" / "target-history"
_TARGET_HISTORY_KEEP = 20  # Number of versions to retain per target file


class TargetConfigHistory:
    """Automatic timestamped version history for synced target harness config files.

    After each sync, call ``snapshot_file()`` for every file written.  The
    history stores the last N versions with timestamps so users can answer
    "what did my Gemini config look like last Tuesday?" and restore any version.

    Storage layout::

        ~/.harnesssync/target-history/
            gemini/GEMINI.md/
                2026-03-13T12:00:00Z.txt
                2026-03-12T09:15:00Z.txt
                ...
            codex/AGENTS.md/
                ...

    Usage::

        history = TargetConfigHistory()
        history.snapshot_file("gemini", Path("/project/GEMINI.md"))
        versions = history.list_versions("gemini", "GEMINI.md")
        content = history.get_version("gemini", "GEMINI.md", versions[0]["timestamp"])
        history.restore_version("gemini", "GEMINI.md", versions[1]["timestamp"])
    """

    def __init__(
        self,
        history_dir: Path | None = None,
        keep: int = _TARGET_HISTORY_KEEP,
    ):
        self.history_dir = history_dir or _TARGET_HISTORY_DIR
        self.keep = keep

    def _version_dir(self, target: str, file_path: str | Path) -> Path:
        """Return the directory for version history of a specific file."""
        name = Path(file_path).name
        return self.history_dir / target / name

    def snapshot_file(
        self,
        target: str,
        file_path: Path,
        timestamp: str | None = None,
    ) -> Path | None:
        """Capture a version snapshot of a target harness config file.

        Called automatically after each sync to maintain version history.
        No-ops silently if the file doesn't exist.

        Args:
            target: Harness target name (e.g. "gemini", "codex").
            file_path: Absolute path to the target config file.
            timestamp: ISO-8601 UTC timestamp. Defaults to now.

        Returns:
            Path to the saved version file, or None if file didn't exist.
        """
        if not file_path.exists():
            return None

        ts = timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        # Sanitize timestamp for use as filename
        safe_ts = ts.replace(":", "-").replace("+", "Z")

        version_dir = self._version_dir(target, file_path)
        version_dir.mkdir(parents=True, exist_ok=True)

        dest = version_dir / f"{safe_ts}.txt"
        try:
            content = file_path.read_text(encoding="utf-8")
            dest.write_text(content, encoding="utf-8")
        except OSError:
            return None

        self._prune(version_dir)
        return dest

    def list_versions(self, target: str, filename: str) -> list[dict]:
        """List available versions for a target config file.

        Args:
            target: Harness target name.
            filename: Config file basename (e.g. "GEMINI.md").

        Returns:
            List of dicts with ``timestamp`` and ``size_bytes`` keys,
            sorted newest first.
        """
        vdir = self.history_dir / target / filename
        if not vdir.exists():
            return []

        versions: list[dict] = []
        for f in sorted(vdir.glob("*.txt"), reverse=True):
            # Recover timestamp from filename
            ts = f.stem.replace("Z-", "Z:").replace("-", ":", 2)
            # Normalize: 2026-03-13T12-00-00Z.txt → 2026-03-13T12:00:00Z
            ts = f.stem
            for i, sep in enumerate(["-", "-", "T", "-", "-"]):
                if i < 3:
                    continue  # Preserve date hyphens
            # Simple approach: replace only the time portion separators
            raw = f.stem  # e.g. 2026-03-13T12-00-00Z
            parts = raw.split("T")
            if len(parts) == 2:
                date_part, time_part = parts
                time_part = time_part.replace("-", ":")
                ts = f"{date_part}T{time_part}"
            else:
                ts = raw

            versions.append({
                "timestamp": ts,
                "filename": f.name,
                "size_bytes": f.stat().st_size,
            })

        return versions

    def get_version(self, target: str, filename: str, timestamp: str) -> str | None:
        """Retrieve the content of a specific version.

        Args:
            target: Harness target name.
            filename: Config file basename.
            timestamp: Timestamp string from ``list_versions()``.

        Returns:
            File content string, or None if not found.
        """
        # Try both with colons and hyphens in timestamp
        safe_ts = timestamp.replace(":", "-").replace("+", "Z")
        vdir = self.history_dir / target / filename
        candidate = vdir / f"{safe_ts}.txt"
        if not candidate.exists():
            return None
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            return None

    def restore_version(
        self,
        target: str,
        filename: str,
        timestamp: str,
        dest_path: Path,
    ) -> bool:
        """Restore a historical version of a target config file.

        Overwrites *dest_path* with the historical content.

        Args:
            target: Harness target name.
            filename: Config file basename.
            timestamp: Timestamp string from ``list_versions()``.
            dest_path: Path to write the restored content to.

        Returns:
            True if restored successfully, False if version not found.
        """
        content = self.get_version(target, filename, timestamp)
        if content is None:
            return False
        try:
            dest_path.write_text(content, encoding="utf-8")
            return True
        except OSError:
            return False

    def format_versions(self, target: str, filename: str) -> str:
        """Format a human-readable list of versions for a file.

        Args:
            target: Harness target name.
            filename: Config file basename.

        Returns:
            Formatted string.
        """
        versions = self.list_versions(target, filename)
        if not versions:
            return f"No version history for {target}/{filename}."

        lines = [
            f"Version History: {target}/{filename}  ({len(versions)} versions)",
            "=" * 55,
        ]
        for i, v in enumerate(versions):
            ts = v["timestamp"][:19].replace("T", " ")
            size = v["size_bytes"]
            marker = " (latest)" if i == 0 else ""
            lines.append(f"  [{i}] {ts}  {size:>7,} bytes{marker}")

        lines.append(
            f"\nRestore with: /sync-snapshot restore {target} {filename} <index>"
        )
        return "\n".join(lines)

    def _prune(self, version_dir: Path) -> None:
        """Remove oldest versions beyond the keep limit."""
        files = sorted(version_dir.glob("*.txt"))
        excess = len(files) - self.keep
        for f in files[:excess]:
            try:
                f.unlink()
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Named Config Snapshots (item 22)
# ---------------------------------------------------------------------------

class NamedSnapshotStore:
    """Save and restore named snapshots of the full HarnessSync config state.

    Named snapshots are stored as JSON files under
    ``~/.harnesssync/named-snapshots/<name>.json``.  They capture the full
    source config (rules, MCP servers, settings, skills manifest) at a point
    in time so users can restore a known-good state by name.

    This is complementary to ``ConfigSnapshot`` (which focuses on shareable
    bundles / GitHub Gists).  Named snapshots are private, local, and designed
    for quick save/restore during local experiments.

    Usage::

        store = NamedSnapshotStore()
        store.save("pre-migration", snapshot_dict)

        names = store.list_names()
        snap = store.load("pre-migration")
        store.delete("pre-migration")

    """

    def __init__(self, store_dir: Path | None = None) -> None:
        self._dir = store_dir or (Path.home() / ".harnesssync" / "named-snapshots")

    # ── Internal helpers ────────────────────────────────────────────────────

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.json"

    @staticmethod
    def _validate_name(name: str) -> None:
        if not name or not name.replace("-", "").replace("_", "").replace(".", "").isalnum():
            raise ValueError(
                f"Invalid snapshot name {name!r}. "
                "Use alphanumeric characters, hyphens, underscores, or dots only."
            )

    # ── Public API ───────────────────────────────────────────────────────────

    def save(self, name: str, snapshot: dict) -> Path:
        """Save a snapshot under the given name.

        Overwrites any existing snapshot with the same name.

        Args:
            name: Human-readable snapshot label (e.g. "pre-migration").
            snapshot: Snapshot dict (e.g. from ``ConfigSnapshot.create()``).

        Returns:
            Path to the saved snapshot file.

        Raises:
            ValueError: If ``name`` contains invalid characters.
            OSError: If the file cannot be written.
        """
        self._validate_name(name)
        self._dir.mkdir(parents=True, exist_ok=True)

        import os as _os
        import tempfile as _tempfile

        target_path = self._path(name)
        tmp = _tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(self._dir),
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            payload = {
                "name": name,
                "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "snapshot": snapshot,
            }
            json.dump(payload, tmp, indent=2, ensure_ascii=False)
            tmp.write("\n")
            tmp.flush()
            _os.fsync(tmp.fileno())
            tmp.close()
            _os.replace(tmp.name, str(target_path))
        except Exception:
            tmp.close()
            try:
                _os.unlink(tmp.name)
            except OSError:
                pass
            raise

        return target_path

    def load(self, name: str) -> dict | None:
        """Load a named snapshot.

        Args:
            name: Snapshot label previously passed to :meth:`save`.

        Returns:
            The snapshot dict (the ``"snapshot"`` key from the stored payload),
            or ``None`` if not found or unreadable.
        """
        self._validate_name(name)
        path = self._path(name)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload.get("snapshot") if isinstance(payload, dict) else None
        except (json.JSONDecodeError, OSError):
            return None

    def load_metadata(self, name: str) -> dict | None:
        """Load metadata (name, saved_at) for a snapshot without the full payload.

        Args:
            name: Snapshot label.

        Returns:
            Dict with ``name`` and ``saved_at`` keys, or ``None`` if not found.
        """
        self._validate_name(name)
        path = self._path(name)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return None
            return {"name": payload.get("name", name), "saved_at": payload.get("saved_at", "")}
        except (json.JSONDecodeError, OSError):
            return None

    def list_names(self) -> list[str]:
        """Return a sorted list of saved snapshot names.

        Returns:
            List of snapshot name strings (without ``.json`` extension).
        """
        if not self._dir.exists():
            return []
        return sorted(
            p.stem for p in self._dir.glob("*.json")
            if p.is_file() and not p.stem.startswith(".")
        )

    def delete(self, name: str) -> bool:
        """Delete a named snapshot.

        Args:
            name: Snapshot label to delete.

        Returns:
            ``True`` if deleted, ``False`` if not found.
        """
        self._validate_name(name)
        path = self._path(name)
        if not path.exists():
            return False
        try:
            path.unlink()
            return True
        except OSError:
            return False

    def format_listing(self) -> str:
        """Return a human-readable listing of all stored snapshots.

        Returns:
            Multi-line string, or a message if no snapshots exist.
        """
        names = self.list_names()
        if not names:
            return "No named snapshots saved. Use /sync-snapshot save <name> to create one."

        lines = [f"Named Snapshots  ({len(names)} stored):", "─" * 45]
        for name in names:
            meta = self.load_metadata(name)
            ts = (meta.get("saved_at", "")[:19].replace("T", " ") if meta else "?")
            lines.append(f"  {name:<30} {ts}")
        lines.append("")
        lines.append("Restore with: /sync-snapshot restore <name>")
        return "\n".join(lines)
