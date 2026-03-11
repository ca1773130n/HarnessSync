from __future__ import annotations

"""
/sync-bootstrap slash command implementation.

One-command setup for a new machine: detects installed harnesses, restores
configs from a backup archive or GitHub Gist, runs a dry-run sync, and
validates output — all in a single guided flow.

Usage:
    /sync-bootstrap                          Interactive guided setup
    /sync-bootstrap --from-archive PATH      Restore from local zip archive
    /sync-bootstrap --from-gist GIST_ID      Restore from GitHub Gist
    /sync-bootstrap --dry-run                Preview what would be synced
    /sync-bootstrap --project-dir PATH       Project root (default: cwd)

This is item 8 from the product roadmap: "New Machine Bootstrap Command".
It solves the painful new-machine setup problem by combining:
  1. Harness auto-detection (which CLIs are installed?)
  2. Config restoration (from archive or Gist)
  3. Dry-run sync preview (what will be written?)
  4. Target validation (did the sync produce valid configs?)
"""

import argparse
import os
import shlex
import sys
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.backup_manager import CloudBackupExporter
from src.harness_detector import scan_all
from src.orchestrator import SyncOrchestrator
from src.utils.logger import Logger


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sync-bootstrap",
        description="Bootstrap HarnessSync on a new machine from a backup",
    )
    parser.add_argument(
        "--from-archive",
        metavar="PATH",
        help="Restore config from a local zip archive (created by /sync-bootstrap --export)",
    )
    parser.add_argument(
        "--from-gist",
        metavar="GIST_ID",
        help="Restore config from a GitHub Gist ID (requires GITHUB_TOKEN env var)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview sync output without writing any files",
    )
    parser.add_argument(
        "--project-dir",
        metavar="PATH",
        default=os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()),
        help="Project root directory (default: $CLAUDE_PROJECT_DIR or cwd)",
    )
    parser.add_argument(
        "--export",
        action="store_true",
        help="Export current config to archive (inverse of --from-archive)",
    )
    parser.add_argument(
        "--export-path",
        metavar="PATH",
        help="Destination path for exported archive (used with --export)",
    )
    try:
        args_string = " ".join(sys.argv[1:])
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []
    try:
        return parser.parse_args(tokens)
    except SystemExit:
        return parser.parse_args([])


def _detect_harnesses(logger: Logger) -> list[str]:
    """Detect installed harnesses and report findings."""
    print("\n[1/4] Detecting installed AI coding harnesses...")
    try:
        detected = scan_all()
        installed = [name for name, info in detected.items() if info.get("found")]
    except Exception as exc:
        logger.warn(f"Harness detection failed: {exc}")
        installed = []

    if installed:
        print(f"  Found {len(installed)} harness(es): {', '.join(installed)}")
    else:
        print("  No harnesses detected in PATH or common install locations.")
        print("  Install Codex, Gemini CLI, or another supported harness, then re-run.")
    return installed


def _restore_from_archive(archive_path: Path, project_dir: Path, logger: Logger) -> bool:
    """Restore config files from a local archive."""
    print(f"\n[2/4] Restoring config from archive: {archive_path}")
    if not archive_path.exists():
        print(f"  ERROR: Archive not found: {archive_path}")
        return False
    try:
        restored = CloudBackupExporter.restore_from_archive(archive_path, project_dir)
        print(f"  Restored {len(restored)} file(s):")
        for fname in restored:
            print(f"    · {fname}")
        return True
    except Exception as exc:
        print(f"  ERROR restoring archive: {exc}")
        logger.error(f"Archive restoration failed: {exc}")
        return False


def _restore_from_gist(gist_id: str, project_dir: Path, logger: Logger) -> bool:
    """Restore config files from a GitHub Gist."""
    import json
    import urllib.request

    print(f"\n[2/4] Restoring config from GitHub Gist: {gist_id}")
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "HarnessSync/1.0",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    try:
        req = urllib.request.Request(
            f"https://api.github.com/gists/{gist_id}",
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"  ERROR fetching Gist: {exc}")
        logger.error(f"Gist fetch failed: {exc}")
        return False

    gist_files = data.get("files", {})
    restored: list[str] = []
    for _fname, file_info in gist_files.items():
        orig_name = file_info.get("filename", "")
        content = file_info.get("content", "")
        if orig_name == "harnesssync-manifest.json" or not content:
            continue
        # Reverse the safe-name transformation used during export
        rel_path = orig_name.replace("home_", "~/").replace("_", "/", 1) if orig_name.startswith("home_") else orig_name
        dest = project_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        restored.append(rel_path)

    if restored:
        print(f"  Restored {len(restored)} file(s):")
        for fname in restored:
            print(f"    · {fname}")
        return True
    else:
        print("  No config files found in Gist.")
        return False


def _run_dry_sync(project_dir: Path, logger: Logger) -> dict:
    """Run a dry-run sync and return results."""
    print("\n[3/4] Running dry-run sync to preview output...")
    try:
        orchestrator = SyncOrchestrator(
            project_dir=project_dir,
            scope="all",
            dry_run=True,
        )
        results = orchestrator.sync_all()
        return results
    except Exception as exc:
        print(f"  WARNING: Dry-run failed: {exc}")
        logger.warn(f"Bootstrap dry-run failed: {exc}")
        return {}


def _validate_results(results: dict) -> bool:
    """Validate sync results and print summary."""
    print("\n[4/4] Validating sync output...")
    if not results:
        print("  No results to validate (dry-run may have failed or no targets configured).")
        return False

    all_ok = True
    for target, target_results in sorted(results.items()):
        if target.startswith("_"):
            continue
        failed = 0
        synced = 0
        if isinstance(target_results, dict):
            for _ct, result in target_results.items():
                try:
                    synced += result.synced
                    failed += result.failed
                except AttributeError:
                    pass
        status = "OK" if failed == 0 else "WARN"
        if failed > 0:
            all_ok = False
        print(f"  {target:<12} {status}  (synced={synced}, failed={failed})")

    return all_ok


def _export_config(project_dir: Path, export_path: str | None, logger: Logger) -> None:
    """Export current config to local archive."""
    exporter = CloudBackupExporter(project_dir)
    dest = Path(export_path) if export_path else None
    try:
        archive = exporter.export_to_archive(dest)
        print(f"\nConfig exported to: {archive}")
        print("Share this file or use --from-archive on a new machine to restore.")
    except Exception as exc:
        print(f"\nERROR: Export failed: {exc}")
        logger.error(f"Bootstrap export failed: {exc}")


def main() -> None:
    """Entry point for /sync-bootstrap command."""
    logger = Logger()
    args = _parse_args(sys.argv[1:])
    project_dir = Path(args.project_dir).resolve()

    print("HarnessSync Bootstrap")
    print("=" * 50)

    # Export mode: create archive for use on a new machine
    if args.export:
        _export_config(project_dir, args.export_path, logger)
        return

    # Step 1: Detect harnesses
    installed = _detect_harnesses(logger)

    # Step 2: Restore config (if source provided)
    restored = False
    if args.from_archive:
        restored = _restore_from_archive(Path(args.from_archive), project_dir, logger)
    elif args.from_gist:
        restored = _restore_from_gist(args.from_gist, project_dir, logger)
    else:
        print("\n[2/4] No backup source specified.")
        print("  Use --from-archive PATH or --from-gist GIST_ID to restore from backup.")
        print("  Or use --export to create a backup archive for use on a new machine.")
        restored = True  # Proceed with existing config

    if not restored and (args.from_archive or args.from_gist):
        print("\nBootstrap aborted: config restoration failed.")
        return

    # Step 3: Dry-run sync
    results = _run_dry_sync(project_dir, logger)

    # Step 4: Validate
    ok = _validate_results(results)

    print("\n" + "=" * 50)
    if not installed:
        print("RESULT: No harnesses installed. Install a supported CLI and re-run.")
    elif ok:
        print("RESULT: Bootstrap complete.")
        if args.dry_run:
            print("  (dry-run mode — no files written)")
        else:
            print("  Run /sync to apply the configuration to all detected harnesses.")
    else:
        print("RESULT: Bootstrap completed with warnings. Check output above.")


if __name__ == "__main__":
    main()
