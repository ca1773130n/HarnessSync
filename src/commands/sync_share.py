from __future__ import annotations

"""
/sync-share slash command implementation.

Commits a normalized, harness-agnostic config snapshot to a dedicated branch
in the current project's git repo so teammates can pull and apply it.

Unlike /sync-broadcast (which writes to an external shared repo), /sync-share
operates entirely within the project repository — no external remote required.
Teammates run:

    git pull origin harness-config
    python -m src.commands.sync

to apply the shared config to their local harnesses.

Normalized format strips:
  - Harness-specific annotations (<!-- harness:codex --> blocks)
  - Env-specific sections (<!-- env:production --> blocks)
  - Inline secrets (blocks share if secrets detected)

Usage:
    /sync-share [--branch NAME] [--message MSG] [--dry-run]
    /sync-share --status
    /sync-share --show

Options:
    --branch NAME     Branch to commit config to (default: harness-config)
    --message MSG     Custom commit message
    --dry-run         Preview what would be committed without writing
    --status          Show current share branch status
    --show            Print the normalized config that would be shared
    --project-dir DIR Project directory (default: cwd)
"""

import json
import os
import subprocess
import sys
import shlex
import argparse
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.secret_detector import SecretDetector
from src.sync_filter import filter_rules_for_target


# Default branch name for shared config
DEFAULT_SHARE_BRANCH = "harness-config"

# Relative path in the repo where the normalized config bundle is stored
_BUNDLE_FILE = ".harness-sync/shared-config.json"


def _run_git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in the given directory."""
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=check,
    )


def _get_current_branch(cwd: Path) -> str | None:
    """Return the current git branch, or None if not in a git repo."""
    try:
        result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _is_git_repo(path: Path) -> bool:
    """Return True if path is inside a git repository."""
    try:
        _run_git(["rev-parse", "--git-dir"], path)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _share_branch_exists(branch: str, cwd: Path) -> bool:
    """Return True if the share branch exists locally or remotely."""
    try:
        result = _run_git(
            ["branch", "--list", "--all", f"*{branch}"], cwd, check=False
        )
        return branch in result.stdout
    except Exception:
        return False


def _normalize_rules(content: str) -> str:
    """Strip harness-specific and env-specific annotations from CLAUDE.md content.

    Removes <!-- harness:X --> blocks and <!-- env:X --> blocks so the shared
    config is harness-agnostic. Untagged content passes through unchanged.

    Args:
        content: Raw CLAUDE.md content.

    Returns:
        Normalized content with harness/env annotations removed.
    """
    # Apply filter with a neutral target ("all") to strip harness-specific blocks
    # and leave only universally applicable content
    try:
        # Use a neutral sentinel target that won't match any harness-specific block.
        # filter_rules_for_target strips blocks tagged for OTHER harnesses and keeps
        # untagged (universal) content — passing a nonexistent target name means only
        # universally applicable content survives.
        normalized = filter_rules_for_target(content, "__shared__")
    except Exception:
        # Fallback: return content as-is if filter unavailable
        normalized = content
    return normalized


def _build_share_bundle(project_dir: Path) -> dict:
    """Build the normalized config bundle for sharing.

    Reads CLAUDE.md and related config files, normalizes them, and returns
    a dict ready to be committed to the share branch.

    Args:
        project_dir: Root of the project.

    Returns:
        Bundle dict with keys: rules, metadata, timestamp.
    """
    bundle: dict = {
        "format_version": "1.0",
        "created_by": "HarnessSync /sync-share",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rules": None,
        "extra_files": {},
    }

    # Normalize CLAUDE.md
    claude_md = project_dir / "CLAUDE.md"
    if claude_md.exists():
        raw = claude_md.read_text(encoding="utf-8", errors="replace")
        bundle["rules"] = _normalize_rules(raw)

    # Include harness-sync config if present
    hs_config = project_dir / ".harnesssync"
    if hs_config.exists():
        try:
            bundle["extra_files"][".harnesssync"] = hs_config.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            pass

    return bundle


def _check_secrets(project_dir: Path) -> list[dict]:
    """Scan for secrets in the content to be shared.

    Args:
        project_dir: Project root.

    Returns:
        List of detection dicts (empty if clean).
    """
    detector = SecretDetector()
    return detector.scan_config_files(project_dir)


def _commit_bundle_to_branch(
    bundle: dict,
    branch: str,
    project_dir: Path,
    message: str,
) -> tuple[bool, str]:
    """Commit the bundle to the share branch without switching working tree.

    Uses git's low-level plumbing (hash-object, update-index, write-tree,
    commit-tree) so it never touches the user's working directory or current
    branch.

    Args:
        bundle: Normalized config bundle dict.
        branch: Target branch name.
        project_dir: Git repository root.
        message: Commit message.

    Returns:
        (success, detail_message) tuple.
    """
    bundle_json = json.dumps(bundle, indent=2, ensure_ascii=False)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(bundle_json)
        tmp_path = tmp.name

    try:
        # Write blob object
        blob = _run_git(["hash-object", "-w", tmp_path], project_dir)
        blob_sha = blob.stdout.strip()

        # Build tree from existing branch if it exists, otherwise start fresh
        parent_ref: str | None = None
        parent_sha: str | None = None
        try:
            ref_result = _run_git(
                ["rev-parse", f"refs/heads/{branch}"], project_dir, check=False
            )
            if ref_result.returncode == 0:
                parent_sha = ref_result.stdout.strip()
                # Read existing tree
                tree_result = _run_git(
                    ["ls-tree", parent_sha, "--full-tree"], project_dir, check=False
                )
                parent_ref = parent_sha
        except Exception:
            pass

        # Create new tree containing just our bundle file at the bundle path
        # We use a fresh empty tree and add our file to it
        bundle_filename = _BUNDLE_FILE.replace(".harness-sync/", "")
        dir_prefix = ".harness-sync"

        # Create a minimal tree: dir entry containing our blob
        # Tree format: "<mode> <name>\0<sha_bytes>"
        # Using update-index + write-tree approach with a temp index
        with tempfile.NamedTemporaryFile(delete=False, suffix=".idx") as idx_tmp:
            idx_path = idx_tmp.name

        try:
            env = dict(os.environ)
            env["GIT_INDEX_FILE"] = idx_path

            # Read parent tree into temp index if parent exists
            if parent_sha:
                subprocess.run(
                    ["git", "read-tree", parent_sha],
                    cwd=str(project_dir),
                    env=env,
                    capture_output=True,
                    check=False,
                )

            # Add our blob to the index
            subprocess.run(
                ["git", "update-index", "--add", "--cacheinfo",
                 f"100644,{blob_sha},{_BUNDLE_FILE}"],
                cwd=str(project_dir),
                env=env,
                capture_output=True,
                check=True,
            )

            # Write tree
            tree_result = subprocess.run(
                ["git", "write-tree"],
                cwd=str(project_dir),
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            tree_sha = tree_result.stdout.strip()
        finally:
            try:
                os.unlink(idx_path)
            except OSError:
                pass

        # Commit the tree
        commit_args = ["commit-tree", tree_sha, "-m", message]
        if parent_ref:
            commit_args += ["-p", parent_ref]
        commit_result = _run_git(commit_args, project_dir)
        commit_sha = commit_result.stdout.strip()

        # Update branch ref
        _run_git(
            ["update-ref", f"refs/heads/{branch}", commit_sha], project_dir
        )

        return True, commit_sha

    except subprocess.CalledProcessError as e:
        return False, f"git error: {e.stderr.strip()}"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _show_status(branch: str, project_dir: Path) -> None:
    """Print status of the share branch."""
    if not _is_git_repo(project_dir):
        print("ERROR: Not a git repository.")
        return

    if not _share_branch_exists(branch, project_dir):
        print(f"Share branch '{branch}' does not exist yet.")
        print(f"Run /sync-share to create it.")
        return

    # Show last commit on share branch
    try:
        log = _run_git(
            ["log", "--oneline", "-5", branch], project_dir, check=False
        )
        print(f"Share branch: {branch}")
        print(f"Last commits:")
        for line in log.stdout.strip().splitlines():
            print(f"  {line}")
    except Exception as e:
        print(f"Could not read share branch: {e}")


def _export_to_gist(
    project_dir: Path,
    public: bool = False,
    description: str = "",
    dry_run: bool = False,
) -> None:
    """Export the normalized config snapshot to a GitHub Gist.

    Wraps CloudBackupExporter.export_to_gist() with pre-export secret scanning
    and user-friendly output.  Requires GITHUB_TOKEN env var with 'gist' scope.

    Args:
        project_dir: Project root directory.
        public: If True, create a public Gist (default: secret).
        description: Gist description shown on GitHub.
        dry_run: If True, show what would be exported without calling the API.
    """
    # Secret scan before exporting
    secrets = _check_secrets(project_dir)
    if secrets:
        detector = SecretDetector()
        print("ERROR: Secrets detected — refusing to export to Gist.")
        print(detector.format_warnings(secrets))
        print("Fix the secrets above, then retry /sync-share --gist.")
        return

    import os
    github_token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not github_token:
        print("ERROR: GITHUB_TOKEN environment variable is not set.")
        print("  Set it with: export GITHUB_TOKEN=<your-token>")
        print("  The token needs the 'gist' scope.")
        print("  Create one at: https://github.com/settings/tokens")
        return

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    gist_description = description or f"HarnessSync config — {project_dir.name} — {timestamp}"

    if dry_run:
        bundle = _build_share_bundle(project_dir)
        rules_lines = len((bundle.get("rules") or "").splitlines())
        visibility = "public" if public else "secret"
        print(f"[DRY RUN] Would export to GitHub Gist ({visibility}):")
        print(f"  Description: {gist_description}")
        print(f"  Rules:       {rules_lines} lines")
        print(f"  Files:       {len(bundle.get('extra_files', {}))} extra config file(s)")
        print()
        print("Set GITHUB_TOKEN and run without --dry-run to create the Gist.")
        return

    try:
        from src.backup_manager import CloudBackupExporter
        exporter = CloudBackupExporter(project_dir=project_dir)
        result = exporter.export_to_gist(
            description=gist_description,
            public=public,
            github_token=github_token,
        )
        gist_url = result.get("gist_url") or result.get("html_url", "")
        gist_id = result.get("id", "")
        print(f"✓ Config exported to GitHub Gist")
        print(f"  URL:  {gist_url}")
        print(f"  ID:   {gist_id}")
        visibility_label = "public" if public else "secret (only visible with the URL)"
        print(f"  Visibility: {visibility_label}")
        print()
        print("Teammates import with:")
        print(f"  /sync-reverse --from-gist {gist_url}")
        print()
        print("Or fetch the raw bundle and apply manually:")
        print(f"  curl -s https://api.github.com/gists/{gist_id} | python -m src.commands.sync_import --bundle -")
    except Exception as exc:
        print(f"ERROR: Failed to export to Gist: {exc}", file=sys.stderr)
        print("Check that GITHUB_TOKEN has the 'gist' scope and try again.")


def main() -> None:
    """Entry point for /sync-share command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-share",
        description="Share normalized config to a git branch for teammates",
    )
    parser.add_argument(
        "--branch",
        default=DEFAULT_SHARE_BRANCH,
        metavar="NAME",
        help=f"Branch to commit config to (default: {DEFAULT_SHARE_BRANCH})",
    )
    parser.add_argument(
        "--message",
        default="",
        metavar="MSG",
        help="Custom commit message",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be committed without writing",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current share branch status",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print the normalized config that would be shared",
    )
    parser.add_argument(
        "--gist",
        action="store_true",
        help=(
            "Export config as a GitHub Gist instead of a git branch. "
            "Requires GITHUB_TOKEN env var with 'gist' scope. "
            "Prints the Gist URL — teammates import with: "
            "/sync-reverse --from-gist <url>"
        ),
    )
    parser.add_argument(
        "--gist-public",
        action="store_true",
        dest="gist_public",
        help="Make the Gist public (default: secret/private)",
    )
    parser.add_argument(
        "--gist-description",
        type=str,
        default="",
        metavar="DESC",
        help="Custom Gist description (default: auto-generated)",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        metavar="DIR",
        help="Project directory (default: current working directory)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()

    if args.status:
        _show_status(args.branch, project_dir)
        return

    # --gist: export config snapshot to GitHub Gist instead of a git branch
    if getattr(args, "gist", False):
        _export_to_gist(
            project_dir=project_dir,
            public=getattr(args, "gist_public", False),
            description=getattr(args, "gist_description", "") or "",
            dry_run=args.dry_run,
        )
        return

    if not _is_git_repo(project_dir):
        print("ERROR: /sync-share requires a git repository.")
        print(f"  '{project_dir}' is not inside a git repo.")
        print("  Use /sync-broadcast for non-git team sharing.")
        return

    # Build bundle
    bundle = _build_share_bundle(project_dir)

    if args.show:
        if bundle["rules"]:
            print("=== Normalized CLAUDE.md (what will be shared) ===")
            print(bundle["rules"])
        else:
            print("No CLAUDE.md found at", project_dir / "CLAUDE.md")
        return

    if bundle["rules"] is None:
        print("WARNING: No CLAUDE.md found — nothing to share.")

    # Secret scan before sharing
    secrets = _check_secrets(project_dir)
    if secrets:
        detector = SecretDetector()
        print("ERROR: Secrets detected — refusing to share config.")
        print(detector.format_warnings(secrets))
        print("Fix the secrets above, then retry /sync-share.")
        return

    # Build commit message
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    commit_message = args.message or f"harness-config: sync {timestamp}"

    if args.dry_run:
        print(f"[DRY RUN] Would commit normalized config to branch '{args.branch}'")
        print(f"  Project:  {project_dir}")
        print(f"  Message:  {commit_message}")
        print(f"  Bundle:   {_BUNDLE_FILE}")
        rules_lines = len((bundle["rules"] or "").splitlines())
        print(f"  Rules:    {rules_lines} lines")
        print()
        print("Teammates apply with:")
        print(f"  git fetch origin {args.branch}")
        print(f"  git show origin/{args.branch}:{_BUNDLE_FILE} | python -m src.commands.sync_import --bundle -")
        return

    print(f"Sharing normalized config to branch '{args.branch}'...")
    success, detail = _commit_bundle_to_branch(
        bundle, args.branch, project_dir, commit_message
    )

    if success:
        print(f"✓ Config committed to '{args.branch}' ({detail[:12]})")
        print()
        print("Teammates apply with:")
        print(f"  git fetch origin {args.branch}")
        print(f"  git show origin/{args.branch}:{_BUNDLE_FILE} | python -m src.commands.sync_import --bundle -")
        print()
        print(f"Push to remote:")
        print(f"  git push origin {args.branch}")
    else:
        print(f"ERROR: Failed to commit to '{args.branch}': {detail}")


if __name__ == "__main__":
    main()
