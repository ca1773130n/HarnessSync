from __future__ import annotations

"""Sync changelog feed with analytics.

Maintains a human-readable ``.harness-sync/changelog.md`` file that logs
every sync event with timestamps, what changed, and which targets were
updated. Provides an audit trail for teams.

Analytics (item 17):
``analytics()`` parses the changelog to surface patterns: most-changed
files, sync frequency per harness, error rates, and harness activity
trends — helping users audit and optimize their multi-harness setup.
"""

import re
from collections import defaultdict
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

    def analytics(self) -> dict:
        """Parse the changelog and return sync analytics insights.

        Scans the changelog for patterns: sync frequency per harness,
        success/fail rates, most-changed files, and harness activity trends.

        Returns:
            Dict with keys:
                total_syncs: int
                targets: {target -> {syncs, failures, success_rate}}
                most_synced_target: str | None
                least_synced_active: str | None  (active = at least 1 sync)
                file_change_counts: {filename -> count}  (top 10)
                insights: list[str]  human-readable observations
        """
        content = self.read()
        if not content:
            return {
                "total_syncs": 0,
                "targets": {},
                "most_synced_target": None,
                "least_synced_active": None,
                "file_change_counts": {},
                "insights": ["No sync history found. Run /sync to start tracking."],
            }

        # Parse sync entries
        # Entry format: ## <timestamp>  scope=<scope>  [account=<acct>]
        # Target lines: - **<target>** ✓/✗  synced=N skipped=N failed=N
        target_re = re.compile(
            r"^- \*\*(\w+)\*\*\s+[✓✗]\s+synced=(\d+)\s+skipped=(\d+)\s+failed=(\d+)",
            re.MULTILINE,
        )
        file_re = re.compile(r"^\s+- `([^`]+)`", re.MULTILINE)
        entry_re = re.compile(r"^## \d{4}-\d{2}-\d{2}", re.MULTILINE)

        total_syncs = len(entry_re.findall(content))
        target_stats: dict[str, dict] = defaultdict(
            lambda: {"syncs": 0, "failures": 0, "total_synced": 0}
        )
        file_counts: dict[str, int] = defaultdict(int)

        for m in target_re.finditer(content):
            target = m.group(1)
            synced = int(m.group(2))
            failed = int(m.group(4))
            target_stats[target]["syncs"] += 1
            target_stats[target]["total_synced"] += synced
            if failed > 0:
                target_stats[target]["failures"] += 1

        for m in file_re.finditer(content):
            fname = m.group(1).strip()
            if fname:
                file_counts[fname] += 1

        # Compute success rates
        for target, stats in target_stats.items():
            n = stats["syncs"]
            stats["success_rate"] = round(
                (n - stats["failures"]) / n * 100, 1
            ) if n > 0 else 100.0

        # Top 10 most changed files
        top_files = dict(
            sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        )

        # Identify most/least active
        active = {t: s for t, s in target_stats.items() if s["syncs"] > 0}
        most_synced = max(active, key=lambda t: active[t]["syncs"], default=None)
        least_synced = min(active, key=lambda t: active[t]["syncs"], default=None)

        # Build insights
        insights: list[str] = []
        if total_syncs == 0:
            insights.append("No sync history. Run /sync to begin tracking.")
        else:
            insights.append(f"Total syncs recorded: {total_syncs}")
            if most_synced and active[most_synced]["syncs"] > 3:
                share = active[most_synced]["syncs"] / total_syncs * 100
                insights.append(
                    f"Most synced target: {most_synced} "
                    f"({active[most_synced]['syncs']} syncs, {share:.0f}% of all syncs)"
                )
            # Flag high error rate targets
            for t, s in active.items():
                if s["failures"] > 0 and s["success_rate"] < 80:
                    insights.append(
                        f"⚠ {t} has {s['failures']} failure(s) "
                        f"({s['success_rate']:.0f}% success rate) — investigate sync errors"
                    )
            # Flag rarely synced targets (low engagement)
            if least_synced and least_synced != most_synced:
                least_syncs = active[least_synced]["syncs"]
                most_syncs = active[most_synced]["syncs"] if most_synced else 1
                if least_syncs * 5 < most_syncs:
                    insights.append(
                        f"Low activity: {least_synced} synced only {least_syncs}x "
                        f"vs {most_synced}'s {most_syncs}x — is {least_synced} still needed?"
                    )

        return {
            "total_syncs": total_syncs,
            "targets": dict(target_stats),
            "most_synced_target": most_synced,
            "least_synced_active": least_synced,
            "file_change_counts": top_files,
            "insights": insights,
        }

    def format_analytics(self) -> str:
        """Return a formatted analytics summary string for display."""
        data = self.analytics()
        lines = ["Sync Analytics & Insights", "=" * 45, ""]
        for insight in data["insights"]:
            lines.append(f"  {insight}")

        if data["targets"]:
            lines.append("\nPer-target sync stats:")
            for target, stats in sorted(
                data["targets"].items(),
                key=lambda kv: kv[1]["syncs"],
                reverse=True,
            ):
                lines.append(
                    f"  {target:<12} {stats['syncs']:>3} syncs  "
                    f"{stats['success_rate']:.0f}% success  "
                    f"{stats['total_synced']} items synced"
                )

        if data["file_change_counts"]:
            lines.append("\nMost frequently synced files (top 10):")
            for fname, count in data["file_change_counts"].items():
                lines.append(f"  {count:>3}x  {fname}")

        return "\n".join(lines)

    def export_json(self, output_path: Path | None = None) -> str:
        """Export sync history as machine-queryable JSON.

        Each entry in the output array represents one sync run with fields:
          timestamp, scope, account, targets (list of target summaries).

        Args:
            output_path: If provided, write JSON to this file in addition to returning it.

        Returns:
            JSON string of the full sync history.
        """
        import json as _json

        content = self.read()
        entries: list[dict] = []

        if content:
            # Parse entries from Markdown
            entry_pattern = re.compile(
                r"^## (\S+)\s*(?:account=(\S+))?\s*scope=(\S+)", re.MULTILINE
            )
            target_pattern = re.compile(
                r"^- \*\*(\w+)\*\*\s+([✓✗])\s+synced=(\d+)\s+skipped=(\d+)\s+failed=(\d+)",
                re.MULTILINE,
            )
            blocked_pattern = re.compile(r"^- \*\*BLOCKED\*\*: (.+)$", re.MULTILINE)

            # Split into per-entry blocks
            sections = re.split(r"(?=^## \d{4}-\d{2}-\d{2})", content, flags=re.MULTILINE)
            for section in sections:
                section = section.strip()
                if not section:
                    continue
                header_m = entry_pattern.search(section)
                if not header_m:
                    continue

                entry: dict = {
                    "timestamp": header_m.group(1),
                    "account": header_m.group(2),
                    "scope": header_m.group(3),
                    "blocked": False,
                    "targets": [],
                }

                blocked_m = blocked_pattern.search(section)
                if blocked_m:
                    entry["blocked"] = True
                    entry["block_reason"] = blocked_m.group(1)
                else:
                    for tm in target_pattern.finditer(section):
                        entry["targets"].append(
                            {
                                "target": tm.group(1),
                                "status": "success" if tm.group(2) == "✓" else "failed",
                                "synced": int(tm.group(3)),
                                "skipped": int(tm.group(4)),
                                "failed": int(tm.group(5)),
                            }
                        )

                entries.append(entry)

        result = _json.dumps({"sync_history": entries}, indent=2, ensure_ascii=False)

        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result, encoding="utf-8")

        return result

    def export_csv(self, output_path: Path | None = None) -> str:
        """Export sync history as CSV for spreadsheet analysis.

        Columns: timestamp, account, scope, target, status, synced, skipped, failed

        Args:
            output_path: If provided, write CSV to this file in addition to returning it.

        Returns:
            CSV string of the full sync history.
        """
        import csv as _csv
        import io as _io

        buf = _io.StringIO()
        writer = _csv.writer(buf)
        writer.writerow(["timestamp", "account", "scope", "target", "status", "synced", "skipped", "failed"])

        import json as _json
        raw = self.export_json()
        data = _json.loads(raw)

        for entry in data.get("sync_history", []):
            ts = entry.get("timestamp", "")
            account = entry.get("account") or ""
            scope = entry.get("scope", "")
            if entry.get("blocked"):
                writer.writerow([ts, account, scope, "BLOCKED", "blocked", 0, 0, 0])
            else:
                for t in entry.get("targets", []):
                    writer.writerow([
                        ts, account, scope,
                        t["target"], t["status"],
                        t["synced"], t["skipped"], t["failed"],
                    ])

        result = buf.getvalue()

        if output_path is not None:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result, encoding="utf-8")

        return result

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
