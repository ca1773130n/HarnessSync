from __future__ import annotations

"""
/sync-team slash command — Team Config Broadcast.

Reads a shared team CLAUDE.md from a git repo URL (or local path) instead
of the local one, then syncs to all personal harnesses. Makes the team lead
the source of truth for shared AI config — teammates run /sync-team and
instantly get the canonical MCP servers, rules, and skills.

Usage:
    /sync-team --from URL_OR_PATH [--file CLAUDE.md] [--scope all]
    /sync-team --from URL_OR_PATH --dry-run
    /sync-team --status

Options:
    --from URL_OR_PATH  Git repo URL or local path to the team config
    --file PATH         Config file inside the repo (default: CLAUDE.md)
    --scope SCOPE       Sync scope: rules|skills|agents|commands|mcp|settings|all
    --branch BRANCH     Branch to checkout (default: main/master)
    --dry-run           Preview without writing
    --status            Show currently configured team source
    --clear             Remove the stored team source config
    --save              Save --from as the default team source for future runs
"""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.utils.logger import Logger

# Path where team source is persisted between runs.
_TEAM_CONFIG_FILE = Path.home() / ".harnesssync" / "team-source.json"


def _load_team_config() -> dict:
    if _TEAM_CONFIG_FILE.exists():
        try:
            return json.loads(_TEAM_CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_team_config(cfg: dict) -> None:
    _TEAM_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _TEAM_CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _is_git_url(source: str) -> bool:
    return source.startswith(("https://", "http://", "git@", "git://", "ssh://"))


def _clone_repo(url: str, branch: str | None, clone_dir: Path, logger: Logger) -> str | None:
    """Clone or shallow-clone the given URL into clone_dir.

    Returns None on success, or an error message on failure.
    """
    cmd = ["git", "clone", "--depth=1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, str(clone_dir)]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return result.stderr.strip() or f"git clone failed (exit {result.returncode})"
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return str(exc)
    return None


def _resolve_source(
    source: str,
    branch: str | None,
    file_path: str,
    logger: Logger,
) -> tuple[Path | None, str | None, str | None]:
    """Resolve the team source to a local file path.

    Returns:
        (local_file, temp_dir_to_cleanup, error_message)
        temp_dir_to_cleanup is set when a clone was made and must be removed.
    """
    if _is_git_url(source):
        tmp = tempfile.mkdtemp(prefix="harnesssync-team-")
        clone_dir = Path(tmp) / "repo"
        err = _clone_repo(source, branch, clone_dir, logger)
        if err:
            shutil.rmtree(tmp, ignore_errors=True)
            return None, None, f"Failed to clone team repo: {err}"
        local_file = clone_dir / file_path
        if not local_file.exists():
            shutil.rmtree(tmp, ignore_errors=True)
            return None, None, f"File '{file_path}' not found in cloned repo"
        return local_file, tmp, None
    else:
        local_path = Path(source).expanduser()
        if local_path.is_dir():
            local_file = local_path / file_path
        else:
            local_file = local_path
        if not local_file.exists():
            return None, None, f"Team config file not found: {local_file}"
        return local_file, None, None


def _sync_from_file(
    team_file: Path,
    scope: str,
    project_dir: Path,
    dry_run: bool,
    logger: Logger,
) -> None:
    """Run HarnessSync using the team config file as the source."""
    from src.orchestrator import SyncOrchestrator
    from src.source_reader import SourceReader

    # Read team rules
    team_content = team_file.read_text(encoding="utf-8")
    logger.info(f"Team config: {len(team_content.splitlines())} lines from {team_file}")

    if dry_run:
        print(f"[dry-run] Would sync team config from: {team_file}")
        print(f"[dry-run] Rules preview ({min(10, len(team_content.splitlines()))} lines):")
        for line in team_content.splitlines()[:10]:
            print(f"  {line}")
        if len(team_content.splitlines()) > 10:
            print(f"  ... ({len(team_content.splitlines()) - 10} more lines)")
        return

    # Write team content to a temp CLAUDE.md, then sync
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(team_content)
        tmp_path = Path(tmp.name)

    try:
        # Override CLAUDE.md in project_dir for this sync
        original_claude_md = project_dir / "CLAUDE.md"
        backup_content: str | None = None
        if original_claude_md.exists():
            backup_content = original_claude_md.read_text(encoding="utf-8")

        # Merge: prepend team content with a clear header
        merged = (
            "<!-- HarnessSync: team config merged from shared source -->\n\n"
            + team_content
            + (
                "\n\n<!-- HarnessSync: local overrides below -->\n\n" + backup_content
                if backup_content
                else ""
            )
        )
        original_claude_md.write_text(merged, encoding="utf-8")

        try:
            only_sections: set[str] | None = None
            if scope and scope != "all":
                only_sections = {scope}

            orch = SyncOrchestrator(
                project_dir=project_dir,
                scope="all",
                dry_run=dry_run,
                only_sections=only_sections,
            )
            results = orch.sync_all()

            success_count = sum(
                1 for t, r in results.items()
                if not t.startswith("_") and (
                    getattr(r, "success", True) if hasattr(r, "success") else
                    all(getattr(v, "success", True) for v in (r.values() if isinstance(r, dict) else [r]))
                )
            )
            print(f"Team sync complete: {success_count} targets updated.")

        finally:
            # Restore original CLAUDE.md
            if backup_content is not None:
                original_claude_md.write_text(backup_content, encoding="utf-8")
            elif original_claude_md.exists():
                original_claude_md.unlink()

    finally:
        tmp_path.unlink(missing_ok=True)


def main() -> None:
    """Entry point for /sync-team command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-team",
        description="Sync from a shared team CLAUDE.md to all personal harnesses",
    )
    parser.add_argument("--from", dest="source", default=None,
                        help="Git repo URL or local path to team config")
    parser.add_argument("--file", default="CLAUDE.md",
                        help="Config file inside the repo (default: CLAUDE.md)")
    parser.add_argument("--branch", default=None,
                        help="Git branch to use (default: main/master)")
    parser.add_argument("--scope", default="all",
                        help="Sync scope: rules|skills|agents|commands|mcp|settings|all")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true",
                        help="Show currently configured team source")
    parser.add_argument("--clear", action="store_true",
                        help="Remove stored team source config")
    parser.add_argument("--save", action="store_true",
                        help="Save --from as the default team source")
    parser.add_argument("--project-dir", default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    logger = Logger()
    project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()

    if args.status:
        cfg = _load_team_config()
        if cfg:
            print(f"Team source: {cfg.get('source', '(none)')}")
            print(f"  file:   {cfg.get('file', 'CLAUDE.md')}")
            print(f"  branch: {cfg.get('branch', 'default')}")
        else:
            print("No team source configured. Use /sync-team --from <URL> --save to set one.")
        return

    if args.clear:
        if _TEAM_CONFIG_FILE.exists():
            _TEAM_CONFIG_FILE.unlink()
        print("Team source config cleared.")
        return

    source = args.source
    if not source:
        # Try saved config
        cfg = _load_team_config()
        source = cfg.get("source")
        if not source:
            print(
                "Error: --from is required (or save a default with /sync-team --from URL --save).",
                file=sys.stderr,
            )
            sys.exit(1)
        file_path = args.file or cfg.get("file", "CLAUDE.md")
        branch = args.branch or cfg.get("branch")
    else:
        file_path = args.file
        branch = args.branch

    if args.save and args.source:
        _save_team_config({"source": args.source, "file": file_path, "branch": branch})
        print(f"Saved team source: {args.source}")

    local_file, tmp_dir, err = _resolve_source(source, branch, file_path, logger)
    if err:
        print(f"Error: {err}", file=sys.stderr)
        sys.exit(1)

    try:
        _sync_from_file(local_file, args.scope, project_dir, args.dry_run, logger)
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    main()
