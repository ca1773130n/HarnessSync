from __future__ import annotations

"""
/sync-all-projects slash command implementation.

Iterates over all known Claude Code projects (from Claude Code's global
project list in ~/.claude.json) and runs HarnessSync for each project,
with a final summary of successes and failures.

This solves the multi-project problem: when you update a global rule in
CLAUDE.md or push a change to a shared skill, you can propagate it to
all your active projects in one command.

Usage:
    /sync-all-projects [--scope SCOPE] [--dry-run] [--concurrency N]
                       [--filter GLOB] [--exclude GLOB]
"""

import json
import os
import sys
import shlex
import argparse
import concurrent.futures
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.orchestrator import SyncOrchestrator
from src.adapters.result import SyncResult


@dataclass
class ProjectSyncResult:
    """Outcome of syncing a single project."""

    project_path: str
    success: bool
    total_synced: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    error: str | None = None
    targets_synced: list[str] = field(default_factory=list)


def _discover_projects(cc_home: Path) -> list[Path]:
    """Read Claude Code's known project list from ~/.claude.json.

    Claude Code records every project it has opened in the global
    .claude.json file under the `projects` key (an object whose keys
    are absolute project paths).

    Args:
        cc_home: Claude Code config home directory (default: ~/.claude).

    Returns:
        List of project directory paths that exist on disk.
    """
    global_config = cc_home / ".claude.json"
    if not global_config.exists():
        # Fall back to parent of cc_home if .claude.json isn't in cc_home itself
        global_config = cc_home.parent / ".claude.json"

    projects: list[Path] = []

    if global_config.exists():
        try:
            data = json.loads(global_config.read_text(encoding="utf-8"))
            for path_str in data.get("projects", {}).keys():
                p = Path(path_str)
                if p.is_dir():
                    projects.append(p)
        except (json.JSONDecodeError, OSError):
            pass

    return projects


def _sync_project(
    project_path: Path,
    scope: str,
    dry_run: bool,
    cc_home: Path | None,
) -> ProjectSyncResult:
    """Sync a single project and return the result.

    Args:
        project_path: Project directory to sync.
        scope: Sync scope (user/project/all).
        dry_run: If True, preview without writing.
        cc_home: Claude Code config home.

    Returns:
        ProjectSyncResult with outcome details.
    """
    try:
        orch = SyncOrchestrator(
            project_dir=project_path,
            scope=scope,
            dry_run=dry_run,
            cc_home=cc_home,
        )
        results = orch.sync_all()

        total_synced = 0
        total_skipped = 0
        total_failed = 0
        targets_synced: list[str] = []

        for target_name, target_results in results.items():
            if target_name.startswith("_"):
                continue
            if isinstance(target_results, dict):
                for config_type, result in target_results.items():
                    if isinstance(result, SyncResult):
                        total_synced += result.synced
                        total_skipped += result.skipped
                        total_failed += result.failed
                if any(
                    isinstance(r, SyncResult) and r.synced > 0
                    for r in target_results.values()
                ):
                    targets_synced.append(target_name)

        return ProjectSyncResult(
            project_path=str(project_path),
            success=total_failed == 0,
            total_synced=total_synced,
            total_skipped=total_skipped,
            total_failed=total_failed,
            targets_synced=targets_synced,
        )

    except Exception as exc:
        return ProjectSyncResult(
            project_path=str(project_path),
            success=False,
            error=str(exc),
        )


def _matches_glob(path: Path, pattern: str) -> bool:
    """Return True if path matches the glob pattern."""
    import fnmatch
    return fnmatch.fnmatch(str(path), pattern) or fnmatch.fnmatch(path.name, pattern)


def sync_all_projects(
    scope: str = "all",
    dry_run: bool = False,
    concurrency: int = 4,
    filter_glob: str | None = None,
    exclude_glob: str | None = None,
    cc_home: Path | None = None,
) -> tuple[list[ProjectSyncResult], str]:
    """Sync all discovered Claude Code projects.

    Args:
        scope: Sync scope (user/project/all).
        dry_run: Preview without writing.
        concurrency: Max parallel syncs.
        filter_glob: Only sync projects matching this glob.
        exclude_glob: Skip projects matching this glob.
        cc_home: Claude Code config home (default: ~/.claude).

    Returns:
        Tuple of (list of results, formatted summary string).
    """
    cc_home = cc_home or Path.home() / ".claude"
    projects = _discover_projects(cc_home)

    if not projects:
        return [], "No Claude Code projects found. Open a project in Claude Code first."

    # Apply filters
    if filter_glob:
        projects = [p for p in projects if _matches_glob(p, filter_glob)]
    if exclude_glob:
        projects = [p for p in projects if not _matches_glob(p, exclude_glob)]

    if not projects:
        return [], "No projects match the specified filter criteria."

    # Run syncs (parallel up to concurrency limit)
    results: list[ProjectSyncResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(concurrency, len(projects))) as executor:
        futures = {
            executor.submit(_sync_project, p, scope, dry_run, cc_home): p
            for p in projects
        }
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    # Sort by project path for consistent output
    results.sort(key=lambda r: r.project_path)

    summary = _format_summary(results, dry_run=dry_run)
    return results, summary


def _format_summary(results: list[ProjectSyncResult], dry_run: bool = False) -> str:
    """Format multi-project sync results as a summary table.

    Args:
        results: List of ProjectSyncResult objects.
        dry_run: True if this was a preview run.

    Returns:
        Formatted multi-line string.
    """
    mode = "[DRY RUN] " if dry_run else ""
    lines = [
        f"{mode}HarnessSync — All Projects",
        "=" * 60,
        f"{'Project':<35} {'Synced':>6} {'Skip':>5} {'Fail':>5} {'Status':<8}",
        "-" * 60,
    ]

    total_synced = total_skipped = total_failed = 0
    success_count = failure_count = 0

    for r in results:
        label = Path(r.project_path).name
        if len(label) > 33:
            label = "..." + label[-30:]

        if r.error:
            status = "ERROR"
            failure_count += 1
        elif r.success:
            status = "ok"
            success_count += 1
        else:
            status = "partial"
            failure_count += 1

        total_synced += r.total_synced
        total_skipped += r.total_skipped
        total_failed += r.total_failed

        lines.append(
            f"{label:<35} {r.total_synced:>6} {r.total_skipped:>5} {r.total_failed:>5} {status:<8}"
        )
        if r.error:
            lines.append(f"  {'':33}  └─ {r.error[:50]}")

    lines.append("-" * 60)
    lines.append(
        f"{'TOTAL':<35} {total_synced:>6} {total_skipped:>5} {total_failed:>5}"
    )
    lines.append("")
    lines.append(f"Projects: {len(results)} total, {success_count} succeeded, {failure_count} failed")

    return "\n".join(lines)


def main(args: list[str] | None = None) -> int:
    """Entry point for /sync-all-projects command.

    Args:
        args: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 = success, 1 = some failures).
    """
    parser = argparse.ArgumentParser(
        prog="sync-all-projects",
        description="Sync all Claude Code projects to registered harnesses",
    )
    parser.add_argument(
        "--scope",
        default="all",
        choices=["user", "project", "all"],
        help="Sync scope for each project (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Max parallel syncs (default: 4)",
    )
    parser.add_argument(
        "--filter",
        dest="filter_glob",
        metavar="GLOB",
        help="Only sync projects matching this glob pattern",
    )
    parser.add_argument(
        "--exclude",
        dest="exclude_glob",
        metavar="GLOB",
        help="Skip projects matching this glob pattern",
    )

    parsed = parser.parse_args(args if args is not None else sys.argv[1:])

    results, summary = sync_all_projects(
        scope=parsed.scope,
        dry_run=parsed.dry_run,
        concurrency=parsed.concurrency,
        filter_glob=parsed.filter_glob,
        exclude_glob=parsed.exclude_glob,
    )

    print(summary)

    failed = [r for r in results if not r.success]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
