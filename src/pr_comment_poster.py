from __future__ import annotations

"""GitHub PR comment poster for HarnessSync config diff reports.

When a PR modifies CLAUDE.md or any synced config file, post a formatted
comment showing what each target harness would look like after sync.
Gives code reviewers visibility into the downstream impact of AI config
changes without requiring them to run HarnessSync locally.

Usage (from CI or /sync-pr-comment command):
    poster = PrCommentPoster(token=os.environ["GITHUB_TOKEN"], repo="org/repo")
    diff_summary = poster.build_diff_summary(project_dir, scope="all")
    poster.post(pr_number=42, diff_summary=diff_summary)

The posted comment is idempotent: if a HarnessSync comment already exists
on the PR, it is updated in place rather than posting a duplicate.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.logger import Logger

# Marker embedded in the comment body to identify HarnessSync-managed comments
_COMMENT_MARKER = "<!-- harnesssync-pr-diff -->"

# GitHub API base URL (overridable for GitHub Enterprise)
_GITHUB_API_BASE = "https://api.github.com"


@dataclass
class HarnessDiff:
    """Diff summary for a single target harness."""

    target: str
    files_changed: list[str] = field(default_factory=list)
    files_added: list[str] = field(default_factory=list)
    files_removed: list[str] = field(default_factory=list)
    sections_changed: list[str] = field(default_factory=list)
    # Human-readable description of what changed per section
    change_notes: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.files_changed or self.files_added or self.files_removed)

    @property
    def total_changes(self) -> int:
        return len(self.files_changed) + len(self.files_added) + len(self.files_removed)


class PrCommentPoster:
    """Post harness config diff comments on GitHub pull requests.

    Args:
        token: GitHub personal access token or GITHUB_TOKEN (Actions secret).
        repo: Repository in "owner/name" format (e.g. "acme/myproject").
        api_base: GitHub API base URL (override for GitHub Enterprise).
        logger: Optional Logger instance.
    """

    def __init__(
        self,
        token: str,
        repo: str,
        api_base: str = _GITHUB_API_BASE,
        logger: Logger | None = None,
    ) -> None:
        self.token = token
        self.repo = repo
        self.api_base = api_base.rstrip("/")
        self.logger = logger or Logger()

    # ──────────────────────────────────────────────────────────────────────────
    # Diff computation
    # ──────────────────────────────────────────────────────────────────────────

    def build_diff_summary(
        self,
        project_dir: Path,
        scope: str = "all",
    ) -> list[HarnessDiff]:
        """Compute what each harness config would look like after sync.

        Runs a dry-run sync internally and collects per-target diffs.
        Does NOT write any files.

        Args:
            project_dir: Project root directory.
            scope: Sync scope ('user' | 'project' | 'all').

        Returns:
            List of HarnessDiff, one per registered target.
        """
        try:
            from src.orchestrator import SyncOrchestrator
        except ImportError:
            self.logger.warn("SyncOrchestrator not available; returning empty diff")
            return []

        diffs: list[HarnessDiff] = []

        try:
            orchestrator = SyncOrchestrator(
                project_dir=project_dir,
                scope=scope,
                dry_run=True,
            )
            results = orchestrator.sync_all()
        except Exception as exc:
            self.logger.warn(f"Dry-run sync failed: {exc}")
            return []

        for target_name, target_results in results.items():
            if target_name.startswith("_") or not isinstance(target_results, dict):
                continue

            diff = HarnessDiff(target=target_name)
            for section, result in target_results.items():
                if not hasattr(result, "status"):
                    continue
                if result.status in ("synced", "updated"):
                    diff.sections_changed.append(section)
                    diff.files_changed.extend(getattr(result, "files", []))
                    note = f"{section}: {getattr(result, 'message', 'updated')}"
                    diff.change_notes.append(note)
                elif result.status == "created":
                    diff.sections_changed.append(section)
                    diff.files_added.extend(getattr(result, "files", []))
                    diff.change_notes.append(f"{section}: new file(s) would be created")

            diffs.append(diff)

        return diffs

    # ──────────────────────────────────────────────────────────────────────────
    # Comment formatting
    # ──────────────────────────────────────────────────────────────────────────

    def format_comment(self, diffs: list[HarnessDiff]) -> str:
        """Build the markdown body for the PR comment.

        Args:
            diffs: Per-target diff summaries from build_diff_summary().

        Returns:
            Markdown string suitable for a GitHub PR comment body.
        """
        changed = [d for d in diffs if d.has_changes]
        unchanged = [d for d in diffs if not d.has_changes]

        lines = [
            _COMMENT_MARKER,
            "## 🔄 HarnessSync — Config Diff Preview",
            "",
            "This PR modifies AI config files. Here's what each target harness "
            "would look like after running `/sync`:",
            "",
        ]

        if not diffs:
            lines += [
                "_No harness targets registered or dry-run produced no results._",
                "",
            ]
        elif not changed:
            lines += [
                "✅ **All harness configs are already in sync** — no changes would be applied.",
                "",
            ]
        else:
            lines += [
                f"**{len(changed)} target(s) would change** after sync:",
                "",
            ]
            for diff in changed:
                lines.append(f"### `{diff.target}` — {diff.total_changes} file(s) affected")
                if diff.change_notes:
                    for note in diff.change_notes:
                        lines.append(f"- {note}")
                if diff.files_added:
                    for f in diff.files_added:
                        lines.append(f"- ➕ `{f}` (new)")
                if diff.files_changed:
                    for f in diff.files_changed:
                        lines.append(f"- ✏️  `{f}` (modified)")
                if diff.files_removed:
                    for f in diff.files_removed:
                        lines.append(f"- 🗑️  `{f}` (removed)")
                lines.append("")

            if unchanged:
                in_sync = ", ".join(f"`{d.target}`" for d in unchanged)
                lines.append(f"✅ Already in sync: {in_sync}")
                lines.append("")

        lines += [
            "---",
            "_Run `/sync` in Claude Code to apply these changes, then commit the updated files._  ",
            "_[HarnessSync](https://github.com/your-org/harnesssync) · "
            "[Docs](https://github.com/your-org/harnesssync#readme)_",
        ]

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # GitHub API calls
    # ──────────────────────────────────────────────────────────────────────────

    def _api_request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
    ) -> dict | list | None:
        """Make an authenticated GitHub API request.

        Args:
            method: HTTP method ('GET', 'POST', 'PATCH').
            path: API path starting with '/' (e.g. '/repos/owner/name/issues/1/comments').
            body: Optional request body (will be JSON-encoded).

        Returns:
            Parsed JSON response, or None on error.
        """
        url = f"{self.api_base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            self.logger.warn(f"GitHub API {method} {path} → HTTP {exc.code}: {exc.reason}")
        except Exception as exc:
            self.logger.warn(f"GitHub API request failed: {exc}")
        return None

    def _find_existing_comment(self, pr_number: int) -> int | None:
        """Return the comment ID of an existing HarnessSync comment on the PR, or None.

        Args:
            pr_number: Pull request number.

        Returns:
            Existing comment ID, or None if not found.
        """
        path = f"/repos/{self.repo}/issues/{pr_number}/comments"
        response = self._api_request("GET", path)
        if not isinstance(response, list):
            return None
        for comment in response:
            body = comment.get("body", "")
            if _COMMENT_MARKER in body:
                return comment.get("id")
        return None

    def post(self, pr_number: int, diffs: list[HarnessDiff] | None = None, body: str | None = None) -> bool:
        """Post or update the diff comment on a PR.

        Idempotent: if a HarnessSync comment already exists, it is updated
        in place rather than creating a duplicate.

        Args:
            pr_number: Pull request number.
            diffs: Pre-computed diffs (from build_diff_summary()). If None,
                   ``body`` must be provided.
            body: Raw comment body (overrides diffs if provided).

        Returns:
            True if the comment was successfully posted or updated.
        """
        if body is None:
            if diffs is None:
                raise ValueError("Either diffs or body must be provided")
            body = self.format_comment(diffs)

        existing_id = self._find_existing_comment(pr_number)

        if existing_id is not None:
            # Update existing comment
            path = f"/repos/{self.repo}/issues/comments/{existing_id}"
            result = self._api_request("PATCH", path, {"body": body})
            if result:
                self.logger.info(f"Updated HarnessSync comment #{existing_id} on PR #{pr_number}")
                return True
        else:
            # Create new comment
            path = f"/repos/{self.repo}/issues/{pr_number}/comments"
            result = self._api_request("POST", path, {"body": body})
            if result:
                comment_id = result.get("id", "?")
                self.logger.info(f"Posted HarnessSync comment #{comment_id} on PR #{pr_number}")
                return True

        return False
