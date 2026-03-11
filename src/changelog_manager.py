from __future__ import annotations

"""Sync changelog feed.

Maintains a human-readable ``.harness-sync/changelog.md`` file that logs
every sync event with timestamps, what changed, and which targets were
updated. Provides an audit trail for teams.
"""

from datetime import datetime
from pathlib import Path

from src.adapters.result import SyncResult
from src.utils.paths import ensure_dir


class ChangelogManager:
    """Appends sync events to a Markdown changelog file."""

    def __init__(self, project_dir: Path | None = None, changelog_dir: Path | None = None,
                 write_root_changelog: bool = True):
        """Initialize ChangelogManager.

        Args:
            project_dir: Project root. If None, uses cwd.
            changelog_dir: Override directory for the changelog file.
                           Default: ``<project_dir>/.harness-sync/``.
            write_root_changelog: If True, also maintain SYNC-CHANGELOG.md at
                                  project root for easy access (default: True).
        """
        self._project_dir = project_dir or Path.cwd()
        if changelog_dir is not None:
            self._dir = changelog_dir
        else:
            self._dir = self._project_dir / ".harness-sync"
        self._path = self._dir / "changelog.md"
        self._root_path = self._project_dir / "SYNC-CHANGELOG.md" if write_root_changelog else None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, results: dict, scope: str = "all", account: str | None = None) -> None:
        """Append a sync event to the changelog.

        Args:
            results: Sync results dict from ``SyncOrchestrator.sync_all()``.
            scope: Sync scope used ("user", "project", "all").
            account: Account name (None for v1 single-account).
        """
        ensure_dir(self._dir)

        lines = self._build_entry(results, scope=scope, account=account)
        entry_text = "\n".join(lines) + "\n\n"

        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(entry_text)

        # Also maintain SYNC-CHANGELOG.md at project root for easy discoverability
        if self._root_path is not None:
            try:
                with open(self._root_path, "a", encoding="utf-8") as fh:
                    fh.write(entry_text)
            except OSError:
                pass  # Root changelog is best-effort

    def read(self) -> str:
        """Return full changelog content, or empty string if not yet created."""
        if not self._path.exists():
            return ""
        return self._path.read_text(encoding="utf-8")

    def read_root(self) -> str:
        """Return content of SYNC-CHANGELOG.md at project root, if it exists."""
        if self._root_path is None or not self._root_path.exists():
            return ""
        return self._root_path.read_text(encoding="utf-8")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_entry(self, results: dict, scope: str, account: str | None) -> list[str]:
        """Build Markdown lines for a single sync event."""
        now = datetime.now().isoformat(timespec="seconds")
        header_parts = [f"## {now}"]
        if account:
            header_parts.append(f"  account={account}")
        header_parts.append(f"  scope={scope}")

        lines: list[str] = [" ".join(header_parts), ""]

        blocked = results.get("_blocked", False)
        if blocked:
            lines.append(f"- **BLOCKED**: {results.get('_reason', 'unknown')}")
            return lines

        for target, target_results in sorted(results.items()):
            if target.startswith("_") or not isinstance(target_results, dict):
                continue

            synced = skipped = failed = 0
            changed_files: list[str] = []

            for config_type, r in target_results.items():
                if isinstance(r, SyncResult):
                    synced += r.synced
                    skipped += r.skipped
                    failed += r.failed
                    changed_files.extend(r.synced_files if hasattr(r, "synced_files") else [])

            status = "✓" if failed == 0 else "✗"
            lines.append(
                f"- **{target}** {status}  synced={synced} skipped={skipped} failed={failed}"
            )
            for f in changed_files[:10]:
                lines.append(f"  - `{f}`")
            if len(changed_files) > 10:
                lines.append(f"  - … and {len(changed_files) - 10} more")

        return lines
