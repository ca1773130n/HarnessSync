from __future__ import annotations

"""Incremental sync engine — skip unchanged files using content fingerprinting.

Item 27: Only re-sync files that have actually changed (content hash comparison)
instead of rewriting everything on every sync. For large rule sets this
dramatically reduces churn and makes auto-sync on save feel instant.

Architecture:
- IncrementalSyncEngine wraps a StateManager to read/write content fingerprints.
- Callers pass a "content key" (e.g. "rules/CLAUDE.md") and the new content.
- is_changed() compares against the last stored hash; mark_synced() updates it.
- The fingerprint store lives inside state.json under targets[target]["content_hashes"].
  This reuses existing state infrastructure without a new file.

Usage in adapters or orchestrator::

    engine = IncrementalSyncEngine(state_manager, target="codex")
    for rule in rules:
        key = str(rule["path"])
        content = rule["content"]
        if not engine.is_changed(key, content):
            result.skipped += 1
            continue
        # ... write the file ...
        engine.mark_synced(key, content)
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _content_fingerprint(content: str) -> str:
    """SHA256 fingerprint of UTF-8 encoded content, truncated to 16 hex chars."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


@dataclass
class IncrementalStats:
    """Counters returned by IncrementalSyncEngine.filter_changed()."""

    changed: int = 0
    unchanged: int = 0
    new: int = 0  # Keys with no prior fingerprint

    @property
    def total(self) -> int:
        return self.changed + self.unchanged + self.new

    @property
    def skipped(self) -> int:
        return self.unchanged

    def summary(self) -> str:
        parts = []
        if self.new:
            parts.append(f"{self.new} new")
        if self.changed:
            parts.append(f"{self.changed} changed")
        if self.unchanged:
            parts.append(f"{self.unchanged} unchanged (skipped)")
        return ", ".join(parts) if parts else "nothing to sync"


class IncrementalSyncEngine:
    """Per-target incremental sync state using content fingerprints.

    Maintains a ``content_hashes`` dict inside the existing state.json target
    entry so no additional files are needed. Fingerprints are 16-char SHA256
    hex digests of UTF-8 content.

    Args:
        state_manager: StateManager instance to read/write state.
        target: Target adapter name (e.g. "codex", "gemini").
        account: Account name for multi-account state (default: "default").
    """

    _HASH_KEY = "content_hashes"

    def __init__(
        self,
        state_manager: Any,
        target: str,
        account: str = "default",
    ) -> None:
        self._sm = state_manager
        self._target = target
        self._account = account
        self._pending: dict[str, str] = {}  # key → new fingerprint, committed on flush()

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def is_changed(self, key: str, content: str) -> bool:
        """Return True if content differs from the last stored fingerprint.

        A key with no stored fingerprint is always considered changed (new).

        Args:
            key: Stable identifier for this content unit (e.g. file path string).
            content: Current UTF-8 content to test.

        Returns:
            True if content has changed or is new, False if identical.
        """
        stored = self._get_stored_hashes().get(key)
        if stored is None:
            return True  # New entry — always sync
        return _content_fingerprint(content) != stored

    def filter_changed(
        self,
        items: list[dict],
        content_key: str = "content",
        id_key: str = "path",
    ) -> tuple[list[dict], IncrementalStats]:
        """Filter a list of items to only those with changed content.

        Typical usage with rules::

            changed, stats = engine.filter_changed(rules)
            result.skipped += stats.skipped

        Args:
            items: List of dicts, each with at minimum ``id_key`` and ``content_key``.
            content_key: Dict key for the content string (default: "content").
            id_key: Dict key for the stable identifier (default: "path").

        Returns:
            Tuple of (filtered_items, IncrementalStats).
        """
        stats = IncrementalStats()
        changed_items: list[dict] = []
        stored = self._get_stored_hashes()

        for item in items:
            key = str(item.get(id_key, ""))
            content = item.get(content_key, "") or ""
            fp = _content_fingerprint(content)

            if key not in stored:
                stats.new += 1
                changed_items.append(item)
                self._pending[key] = fp
            elif stored[key] != fp:
                stats.changed += 1
                changed_items.append(item)
                self._pending[key] = fp
            else:
                stats.unchanged += 1

        return changed_items, stats

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def mark_synced(self, key: str, content: str) -> None:
        """Record a successful sync of content for the given key.

        Call this after writing a file so future runs can skip it if unchanged.

        Args:
            key: Stable identifier (same value used in is_changed / filter_changed).
            content: The content that was synced.
        """
        self._pending[key] = _content_fingerprint(content)

    def flush(self) -> None:
        """Persist pending fingerprint updates to state.json.

        Call once after all sync operations complete. Batching writes avoids
        writing state on every individual file during large syncs.
        """
        if not self._pending:
            return

        state = self._sm.load_state()
        targets = self._get_targets_dict(state)
        target_entry = targets.setdefault(self._target, {})
        hashes = target_entry.setdefault(self._HASH_KEY, {})
        hashes.update(self._pending)
        self._pending.clear()

        # Write back to state — use set_target_data if available, else direct write
        if hasattr(self._sm, "set_target_data"):
            self._sm.set_target_data(self._target, target_entry, account=self._account)
        else:
            # Fall back to writing the modified state dict directly
            try:
                self._sm._state = state
                self._sm.save_state(state)
            except AttributeError:
                pass  # Best-effort: state persists in memory if save not available

    def invalidate(self, key: str) -> None:
        """Remove a key's fingerprint so it will be re-synced next time.

        Useful when a file is known to have been overwritten or deleted.

        Args:
            key: Key to invalidate.
        """
        state = self._sm.load_state()
        targets = self._get_targets_dict(state)
        hashes = targets.get(self._target, {}).get(self._HASH_KEY, {})
        if key in hashes:
            del hashes[key]
            try:
                self._sm.save_state(state)
            except AttributeError:
                pass

    def invalidate_all(self) -> None:
        """Remove ALL fingerprints for this target, forcing a full re-sync."""
        state = self._sm.load_state()
        targets = self._get_targets_dict(state)
        if self._target in targets:
            targets[self._target].pop(self._HASH_KEY, None)
            try:
                self._sm.save_state(state)
            except AttributeError:
                pass

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_all_fingerprints(self) -> dict[str, str]:
        """Return a copy of all stored fingerprints for this target.

        Useful for debugging and /sync-status display.
        """
        return dict(self._get_stored_hashes())

    def format_status(self) -> str:
        """Return a human-readable summary of stored fingerprints."""
        hashes = self._get_stored_hashes()
        if not hashes:
            return f"[{self._target}] No incremental fingerprints (full sync on next run)"
        lines = [f"[{self._target}] {len(hashes)} content fingerprint(s):"]
        for key, fp in sorted(hashes.items()):
            short_key = key if len(key) <= 60 else "…" + key[-57:]
            lines.append(f"  {short_key:<60} {fp}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_stored_hashes(self) -> dict[str, str]:
        """Load current content hashes from state for this target."""
        state = self._sm.load_state()
        targets = self._get_targets_dict(state)
        return targets.get(self._target, {}).get(self._HASH_KEY, {})

    def _get_targets_dict(self, state: dict) -> dict:
        """Navigate to the correct targets dict, accounting for v1/v2 schema."""
        accounts = state.get("accounts", {})
        if accounts:
            account_data = accounts.get(self._account, {})
            return account_data.setdefault("targets", {})
        return state.setdefault("targets", {})


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------

def fingerprint_files(paths: list[Path]) -> dict[str, str]:
    """Compute SHA256 fingerprints for a list of file paths.

    Files that don't exist return an empty string fingerprint.

    Args:
        paths: File paths to fingerprint.

    Returns:
        Dict mapping str(path) → 16-char hex fingerprint.
    """
    from src.utils.hashing import hash_file_sha256

    return {str(p): hash_file_sha256(p) for p in paths}


def changed_files(
    current_fingerprints: dict[str, str],
    stored_fingerprints: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    """Compare current vs. stored fingerprints to identify changed files.

    Args:
        current_fingerprints: Dict of str(path) → current fingerprint.
        stored_fingerprints: Dict of str(path) → previously stored fingerprint.

    Returns:
        Tuple of (new_paths, modified_paths, deleted_paths) — all as str lists.
    """
    new: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []

    all_keys = set(current_fingerprints) | set(stored_fingerprints)
    for key in sorted(all_keys):
        current = current_fingerprints.get(key, "")
        stored = stored_fingerprints.get(key, "")
        if stored == "" and current != "":
            new.append(key)
        elif stored != "" and current == "":
            deleted.append(key)
        elif current != stored:
            modified.append(key)

    return new, modified, deleted
