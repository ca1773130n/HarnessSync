from __future__ import annotations

"""
/sync-schedule slash command implementation.

Schedule periodic background syncs via cron (macOS/Linux) or Task Scheduler
stub (Windows). Independent of any Claude Code session — syncs happen even
when the editor is closed.

Usage:
    /sync-schedule --every 1h [--scope all] [--project-dir PATH]
    /sync-schedule --list
    /sync-schedule --remove

Options:
    --every INTERVAL    Sync interval: 30m, 1h, 6h, 12h, 1d, etc.
    --scope SCOPE       Sync scope: user | project | all (default: all)
    --project-dir PATH  Project directory (default: cwd)
    --list              Show all HarnessSync cron jobs
    --remove            Remove the cron job for this project
    --dry-run           Print cron line without installing it
"""

import os
import re
import sys
import shlex
import shutil
import argparse
import subprocess
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

# Cron comment marker so we can identify and remove our entries
_CRON_MARKER = "# HarnessSync scheduled sync"
_CRON_PROJECT_MARKER_PREFIX = "# hs-project:"


def _parse_interval(interval: str) -> tuple[int, int, str]:
    """Parse a human-friendly interval into (minute, hour, cron_expr).

    Supports: 30m, 1h, 2h, 6h, 12h, 1d, 2d
    Returns (minute, hour, cron_expression).

    Raises ValueError for unrecognised formats.
    """
    interval = interval.strip().lower()
    m = re.match(r"^(\d+)(m|h|d)$", interval)
    if not m:
        raise ValueError(
            f"Unrecognised interval {interval!r}. Use 30m, 1h, 6h, 12h, 1d, etc."
        )

    value = int(m.group(1))
    unit = m.group(2)

    if unit == "m":
        if value < 5:
            raise ValueError("Minimum interval is 5m to avoid excessive syncing.")
        if value >= 60:
            raise ValueError("Use 1h instead of 60m.")
        return (0, 0, f"*/{value} * * * *")
    elif unit == "h":
        if value == 1:
            return (0, 0, "0 * * * *")
        if value > 23:
            raise ValueError("Use 1d instead of 24h.")
        return (0, 0, f"0 */{value} * * *")
    else:  # days
        if value == 1:
            return (0, 9, "0 9 * * *")  # daily at 09:00
        return (0, 9, f"0 9 */{value} * *")


def _python_path() -> str:
    """Return the best available Python 3 executable path."""
    for candidate in [sys.executable, shutil.which("python3"), shutil.which("python")]:
        if candidate:
            return candidate
    return "python3"


def _build_cron_line(project_dir: Path, cron_expr: str, scope: str) -> str:
    """Build the full cron line for a scheduled sync."""
    py = _python_path()
    sync_script = Path(PLUGIN_ROOT) / "src" / "commands" / "sync.py"
    log_path = project_dir / ".harness-sync" / "schedule.log"

    cmd = (
        f'cd "{project_dir}" && '
        f'"{py}" "{sync_script}" --scope {scope} '
        f'>> "{log_path}" 2>&1'
    )
    return (
        f"{_CRON_MARKER}\n"
        f"{_CRON_PROJECT_MARKER_PREFIX}{project_dir}\n"
        f"{cron_expr} {cmd}"
    )


def _read_crontab() -> str:
    """Read the current crontab. Returns empty string if none exists."""
    try:
        result = subprocess.run(
            ["crontab", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
        # exit code 1 with "no crontab" message is normal
        return ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _write_crontab(content: str) -> bool:
    """Write content to crontab. Returns True on success."""
    try:
        proc = subprocess.run(
            ["crontab", "-"],
            input=content,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _install_cron_job(project_dir: Path, cron_expr: str, scope: str) -> bool:
    """Install or replace the cron job for this project.

    Returns True on success.
    """
    # Remove existing entries for this project first
    existing = _read_crontab()
    cleaned = _remove_project_from_crontab(existing, project_dir)

    new_entry = _build_cron_line(project_dir, cron_expr, scope)
    new_crontab = cleaned.rstrip() + "\n" + new_entry + "\n"

    # Ensure log directory exists
    log_dir = project_dir / ".harness-sync"
    log_dir.mkdir(parents=True, exist_ok=True)

    return _write_crontab(new_crontab)


def _remove_project_from_crontab(crontab: str, project_dir: Path) -> str:
    """Remove all HarnessSync entries for the given project from a crontab string."""
    lines = crontab.splitlines(keepends=True)
    result: list[str] = []
    skip_next = 0

    for line in lines:
        if _CRON_MARKER in line:
            skip_next = 2  # skip the marker and project marker line
            continue
        if skip_next > 0 and line.startswith(_CRON_PROJECT_MARKER_PREFIX):
            project_in_line = line[len(_CRON_PROJECT_MARKER_PREFIX):].strip()
            if str(project_dir) == project_in_line:
                skip_next = 1  # skip the actual cron command line too
                continue
            else:
                # Different project — keep it but reset skip counter
                result.append(f"{_CRON_MARKER}\n")
                result.append(line)
                skip_next = 0
                continue
        if skip_next > 0:
            skip_next -= 1
            continue
        result.append(line)

    return "".join(result)


def _list_harnesssync_cron_jobs(crontab: str) -> list[dict]:
    """Extract all HarnessSync cron entries from a crontab string."""
    lines = crontab.splitlines()
    jobs: list[dict] = []
    i = 0
    while i < len(lines):
        if _CRON_MARKER in lines[i]:
            project = ""
            cron_line = ""
            if i + 1 < len(lines) and lines[i + 1].startswith(_CRON_PROJECT_MARKER_PREFIX):
                project = lines[i + 1][len(_CRON_PROJECT_MARKER_PREFIX):].strip()
                i += 1
            if i + 1 < len(lines):
                cron_line = lines[i + 1].strip()
                i += 1
            jobs.append({"project": project, "cron_line": cron_line})
        i += 1
    return jobs


def _format_jobs(jobs: list[dict]) -> str:
    if not jobs:
        return "No HarnessSync scheduled syncs found."
    lines = ["HarnessSync Scheduled Syncs", "─" * 50]
    for job in jobs:
        lines.append(f"  Project: {job['project'] or '(unknown)'}")
        lines.append(f"  Cron:    {job['cron_line']}")
        lines.append("")
    return "\n".join(lines)


def _windows_stub(project_dir: Path, interval: str, scope: str) -> str:
    """Return Windows Task Scheduler instructions since we can't automate it here."""
    py = _python_path()
    sync_script = Path(PLUGIN_ROOT) / "src" / "commands" / "sync.py"
    return (
        "Windows Task Scheduler is not automated by this command.\n"
        "To schedule syncs manually, run:\n\n"
        "  schtasks /create /tn \"HarnessSync\" /sc HOURLY /tr "
        f'"{py} {sync_script} --scope {scope}" /f\n\n'
        "Or use the Windows Task Scheduler GUI to create a task that runs:\n"
        f'  "{py}" "{sync_script}" --scope {scope}\n'
        f"  Working directory: {project_dir}\n"
    )


def main():
    """Entry point for /sync-schedule command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-schedule",
        description="Schedule periodic background syncs via cron.",
    )
    parser.add_argument("--every", default=None, metavar="INTERVAL",
                        help="Sync interval: 30m, 1h, 6h, 12h, 1d, etc.")
    parser.add_argument("--scope", default="all", choices=["user", "project", "all"])
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--list", dest="list_jobs", action="store_true",
                        help="List all HarnessSync scheduled syncs")
    parser.add_argument("--remove", action="store_true",
                        help="Remove the cron job for this project")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the cron line without installing it")

    args = parser.parse_args(raw_args)
    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()

    # Windows: unsupported (provide instructions)
    if sys.platform == "win32":
        if args.every:
            print(_windows_stub(project_dir, args.every, args.scope))
        else:
            print("Scheduled sync is not supported on Windows via this command.")
            print("See --help for manual Task Scheduler instructions.")
        return

    # Check crontab availability
    if not shutil.which("crontab"):
        print("Error: 'crontab' not found. Scheduled sync requires cron to be installed.",
              file=sys.stderr)
        sys.exit(1)

    crontab = _read_crontab()

    if args.list_jobs:
        jobs = _list_harnesssync_cron_jobs(crontab)
        print(_format_jobs(jobs))
        return

    if args.remove:
        cleaned = _remove_project_from_crontab(crontab, project_dir)
        if cleaned == crontab:
            print(f"No HarnessSync cron job found for {project_dir}")
            return
        if _write_crontab(cleaned):
            print(f"Removed HarnessSync cron job for {project_dir}")
        else:
            print("Error: could not update crontab.", file=sys.stderr)
            sys.exit(1)
        return

    if not args.every:
        parser.print_help()
        print("\nExamples:")
        print("  /sync-schedule --every 1h")
        print("  /sync-schedule --every 30m --scope project")
        print("  /sync-schedule --list")
        print("  /sync-schedule --remove")
        return

    try:
        _, _, cron_expr = _parse_interval(args.every)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    cron_line = _build_cron_line(project_dir, cron_expr, args.scope)

    if args.dry_run:
        print("Cron entry that would be installed:")
        print(cron_line)
        return

    if _install_cron_job(project_dir, cron_expr, args.scope):
        print(f"Scheduled HarnessSync every {args.every} for:")
        print(f"  Project: {project_dir}")
        print(f"  Scope:   {args.scope}")
        print(f"  Cron:    {cron_expr}")
        print(f"  Log:     {project_dir / '.harness-sync' / 'schedule.log'}")
        print()
        print("To remove: /sync-schedule --remove")
        print("To list:   /sync-schedule --list")
    else:
        print("Error: could not install cron job. Check crontab permissions.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
