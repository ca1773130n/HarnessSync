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
import subprocess
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from src.adapters.result import SyncResult
from src.utils.paths import ensure_dir


# Human-readable nouns for each config section type (used in NL summaries)
_SECTION_NOUNS: dict[str, str] = {
    "rules":    "rule",
    "skills":   "skill",
    "agents":   "agent",
    "commands": "command",
    "mcp":      "MCP server",
    "settings": "setting",
    "plugins":  "plugin",
}


def _get_git_attribution(project_dir: Path | None = None) -> dict[str, str]:
    """Return the current git author and HEAD commit for attribution (item 30).

    Calls ``git log -1`` and ``git config user.name`` / ``user.email``
    in ``project_dir`` (or cwd).  Returns empty strings for each field
    when git is unavailable or the directory is not a git repo — so the
    rest of the changelog pipeline is unaffected.

    Args:
        project_dir: Git repo root to query.  Defaults to cwd.

    Returns:
        Dict with keys: ``author``, ``email``, ``commit_sha``, ``commit_subject``
        (all strings, possibly empty).
    """
    cwd = str(project_dir) if project_dir else None
    result: dict[str, str] = {"author": "", "email": "", "commit_sha": "", "commit_subject": ""}

    try:
        name_proc = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True, text=True, cwd=cwd, timeout=3,
        )
        email_proc = subprocess.run(
            ["git", "config", "user.email"],
            capture_output=True, text=True, cwd=cwd, timeout=3,
        )
        result["author"] = name_proc.stdout.strip()
        result["email"] = email_proc.stdout.strip()

        log_proc = subprocess.run(
            ["git", "log", "-1", "--format=%h %s"],
            capture_output=True, text=True, cwd=cwd, timeout=3,
        )
        if log_proc.returncode == 0 and log_proc.stdout.strip():
            parts = log_proc.stdout.strip().split(" ", 1)
            result["commit_sha"] = parts[0]
            result["commit_subject"] = parts[1] if len(parts) > 1 else ""
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    return result


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
        """Build Markdown lines for a single sync event.

        Includes git attribution (author + HEAD commit) when available so
        every changelog entry is traceable to who changed the source config
        and what the triggering commit was (item 30 — Config Change Attribution).
        """
        now = datetime.now().isoformat(timespec="seconds")
        header_parts = [f"## {now}"]
        if account:
            header_parts.append(f"  account={account}")
        header_parts.append(f"  scope={scope}")

        lines: list[str] = [" ".join(header_parts), ""]

        # Append git attribution metadata
        attr = _get_git_attribution(self._project_dir)
        if attr["author"] or attr["commit_sha"]:
            attr_parts: list[str] = []
            if attr["author"]:
                email_suffix = f" <{attr['email']}>" if attr["email"] else ""
                attr_parts.append(f"author: {attr['author']}{email_suffix}")
            if attr["commit_sha"]:
                subject = f" — {attr['commit_subject']}" if attr["commit_subject"] else ""
                attr_parts.append(f"commit: {attr['commit_sha']}{subject}")
            lines.append(f"<!-- attribution: {' | '.join(attr_parts)} -->")
            lines.append("")

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

    def _build_plain_summary(self, results: dict, scope: str) -> str:
        """Generate a human-readable audit summary of a sync event.

        Produces natural language like:
          "Added 3 skills to codex, updated MCP server URL for gemini,
           removed deprecated rule from cursor — 2 targets synced."
        or:
          "Sync to 3 targets (codex, gemini, cursor) — no changes detected."

        The summary decomposes changes per-target and per-section so users
        have an audit trail they can explain to teammates.

        Args:
            results: Sync results dict (same as record()).
            scope: Sync scope string.

        Returns:
            Multi-sentence natural-language summary string.
        """
        target_names = [
            t for t in sorted(results.keys())
            if not t.startswith("_") and isinstance(results[t], dict)
        ]

        # Per-target per-section breakdown
        target_changes: dict[str, list[str]] = {}

        for target, target_results in results.items():
            if target.startswith("_") or not isinstance(target_results, dict):
                continue
            phrases: list[str] = []
            for config_type, r in target_results.items():
                if not isinstance(r, SyncResult):
                    continue
                synced = r.synced
                failed = r.failed
                skipped = r.skipped

                if synced > 0:
                    # Build a verb phrase: "added/updated N <type>(s)"
                    noun = _SECTION_NOUNS.get(config_type, config_type)
                    plural = f"{noun}s" if synced > 1 and not noun.endswith("s") else noun
                    verb = "synced"
                    # Heuristic: if skipped==0 and synced is small, likely a fresh add
                    if skipped == 0 and synced <= 3:
                        verb = "added"
                    elif failed > 0:
                        verb = "partially synced"
                    phrases.append(f"{verb} {synced} {plural}")

                if failed > 0:
                    noun = _SECTION_NOUNS.get(config_type, config_type)
                    phrases.append(f"{failed} {noun} error(s)")

            if phrases:
                target_changes[target] = phrases

        n_targets = len(target_names)
        targets_str = (
            ", ".join(target_names[:3])
            + (f" +{n_targets - 3} more" if n_targets > 3 else "")
        )

        if not target_changes:
            return f"Sync to {n_targets} target(s) ({targets_str}) — no changes detected."

        # Build per-target sentences
        sentences: list[str] = []
        for target in sorted(target_changes):
            detail = ", ".join(target_changes[target])
            sentences.append(f"{detail} to {target}")

        body = "; ".join(sentences)
        n_changed = len(target_changes)
        return f"{body.capitalize()} — {n_changed} target(s) updated."

    def natural_language_diff_summary(self, results: dict) -> str:
        """Generate a bullet-point changelog entry for human consumption.

        Returns a multi-line string suitable for appending to a CHANGELOG.md
        or pasting into a PR description. Each bullet describes one target's
        changes in plain language.

        Args:
            results: Sync results dict from SyncOrchestrator.sync_all().

        Returns:
            Bullet-point summary string (empty string if no changes).
        """
        bullets: list[str] = []
        for target, target_results in sorted(results.items()):
            if target.startswith("_") or not isinstance(target_results, dict):
                continue
            for config_type, r in target_results.items():
                if not isinstance(r, SyncResult) or r.synced == 0:
                    continue
                noun = _SECTION_NOUNS.get(config_type, config_type)
                plural = f"{noun}s" if r.synced > 1 and not noun.endswith("s") else noun
                bullets.append(f"- [{target}] Synced {r.synced} {plural}")
                if r.failed:
                    bullets.append(f"  ⚠ {r.failed} {noun}(s) failed to sync")
        return "\n".join(bullets)


def record_with_diff(
    manager: "ChangelogManager",
    results: dict,
    scope: str = "all",
    account: str | None = None,
    rule_diffs: dict[str, list[str]] | None = None,
) -> None:
    """Append a sync event with optional rule-level diff attribution.

    Extends ``ChangelogManager.record()`` by including a per-section diff
    summary in the changelog entry — showing WHICH rules/sections changed,
    not just aggregate counts.

    Args:
        manager: ChangelogManager instance.
        results: Sync results dict from SyncOrchestrator.sync_all().
        scope: Sync scope used.
        account: Account name (None for single-account).
        rule_diffs: Optional per-target diff info. Each key is a target name;
                    each value is a list of diff lines (unified diff format
                    or plain descriptions like "+Added: rule about testing").
    """
    # Use the base record method so core changelog logic stays in one place
    manager.record(results, scope=scope, account=account)

    if not rule_diffs:
        return

    # Append diff details to the last entry in the changelog
    diff_lines: list[str] = ["", "<!-- rule-level diff:"]
    for target, diff in sorted(rule_diffs.items()):
        if not diff:
            continue
        diff_lines.append(f"  {target}:")
        for line in diff[:20]:  # cap at 20 lines per target
            diff_lines.append(f"    {line}")
        if len(diff) > 20:
            diff_lines.append(f"    ... and {len(diff) - 20} more lines")
    diff_lines.append("-->")
    diff_lines.append("")

    diff_text = "\n".join(diff_lines)

    # Append to both changelog files
    try:
        with open(manager._path, "a", encoding="utf-8") as fh:
            fh.write(diff_text)
    except OSError:
        pass

    if manager._root_path is not None:
        try:
            with open(manager._root_path, "a", encoding="utf-8") as fh:
                fh.write(diff_text)
        except OSError:
            pass
