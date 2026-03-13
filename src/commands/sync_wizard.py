from __future__ import annotations

"""
/sync-wizard slash command implementation.

Guided first-time onboarding flow that:
1. Detects installed harnesses via PATH and config-dir scanning
2. Shows users what was found and lets them pick sync targets
3. Runs an initial sync with sensible defaults for the selected targets
4. Prints a next-steps summary

Solves the cold-start problem where new users don't know which adapters to
enable or what settings matter most.
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.harness_detector import detect_new_harnesses, detect_version, scan_all


def _prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt user for yes/no, returning *default* when stdin is not a TTY."""
    if not sys.stdin.isatty():
        return default
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        answer = input(question + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if answer in ("y", "yes"):
        return True
    if answer in ("n", "no"):
        return False
    return default


def _prompt_choice(prompt: str, options: list[str]) -> list[str]:
    """Let the user select from a numbered list, returning selected items.

    Pressing Enter with no input selects all options (opt-in default).
    """
    if not sys.stdin.isatty():
        return options
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    print("  (press Enter to select all, or enter comma-separated numbers)")
    try:
        raw = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return options
    if not raw:
        return options
    selected = []
    for part in raw.split(","):
        part = part.strip()
        try:
            idx = int(part) - 1
            if 0 <= idx < len(options):
                selected.append(options[idx])
        except ValueError:
            pass
    return selected if selected else options


def _run_initial_sync(targets: list[str], project_dir: Path) -> bool:
    """Invoke the sync orchestrator for the selected targets.

    Returns True on success, False on any adapter failure.
    """
    try:
        from src.orchestrator import SyncOrchestrator
        orchestrator = SyncOrchestrator(project_dir=project_dir)
        results = orchestrator.sync_all(targets=targets)
        # Detect failures: adapter results with failed > 0
        any_failed = False
        for target, adapter_results in results.items():
            if target.startswith("_"):
                continue
            if isinstance(adapter_results, dict):
                for section, res in adapter_results.items():
                    if getattr(res, "failed", 0) > 0:
                        any_failed = True
                        print(f"  [warn] {target}/{section}: {res.failed} file(s) failed")
        return not any_failed
    except Exception as exc:  # pragma: no cover
        print(f"  [error] Sync failed: {exc}", file=sys.stderr)
        return False


def main() -> None:
    """Entry point for /sync-wizard command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-wizard",
        description="Guided HarnessSync onboarding wizard",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        help="Project directory (default: current directory)",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Non-interactive mode: select all detected harnesses automatically",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Detect harnesses and show selection but do not sync",
    )
    args = parser.parse_args(tokens)

    project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()

    print("=" * 60)
    print("  HarnessSync — First-Time Setup Wizard")
    print("=" * 60)
    print()

    # ── Step 1: detect installed harnesses ──────────────────────────────
    print("Step 1/3  Detecting installed harnesses…")
    all_detected = scan_all()  # {canonical: {in_path, config_dir, executable, via_pkg_mgr}}
    detected = sorted(
        name for name, info in all_detected.items()
        if info.get("in_path") or info.get("config_dir") or info.get("via_pkg_mgr")
    )
    if not detected:
        print("  No supported harnesses found on this machine.")
        print("  Install one of: codex, gemini, opencode, cursor, aider, windsurf")
        print("  Then re-run /sync-wizard.")
        return

    print(f"  Found {len(detected)} harness(es):")
    for name in detected:
        exe = all_detected[name].get("executable")
        ver = detect_version(name, exe) if exe else None
        ver_str = f" (v{ver})" if ver else ""
        print(f"    ✓ {name}{ver_str}")
    print()

    # ── Step 2: pick sync targets ────────────────────────────────────────
    print("Step 2/3  Choose which harnesses to sync:")
    if args.auto or not sys.stdin.isatty():
        selected_targets = detected
        print(f"  Auto-selected all {len(selected_targets)} harness(es).")
    else:
        selected_targets = _prompt_choice("", detected)
        if not selected_targets:
            print("  No harnesses selected — exiting wizard.")
            return
    print()

    if args.dry_run:
        print("Step 3/3  Dry run — would sync to:", ", ".join(selected_targets))
        print()
        print("  Re-run without --dry-run to apply.")
        return

    # ── Step 3: initial sync ─────────────────────────────────────────────
    print(f"Step 3/3  Running initial sync to: {', '.join(selected_targets)}…")
    success = _run_initial_sync(selected_targets, project_dir)
    print()

    if success:
        print("  Sync complete!")
    else:
        print("  Sync completed with warnings — check output above.")

    print()
    print("─" * 60)
    print("Next steps:")
    print("  /sync-status        — check sync state at any time")
    print("  /sync-matrix        — view per-harness feature support")
    print("  /sync-health        — verify harness configurations")
    print("  /sync-wizard --auto — re-run wizard non-interactively")
    print("─" * 60)


if __name__ == "__main__":
    main()
