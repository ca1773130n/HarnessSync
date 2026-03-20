from __future__ import annotations

"""Watch mode and monorepo sync mode for the /sync command.

Extracted from sync.py to keep the main command file focused on CLI parsing
and standard sync orchestration.
"""

from pathlib import Path

from src.orchestrator import SyncOrchestrator
from src.desktop_notifier import DesktopNotifier


def run_monorepo_sync(project_dir: Path, args) -> None:
    """Run per-package sync for a monorepo project.

    Discovers sub-packages with .harnesssync-package.json or CLAUDE.md files
    inside well-known package directories (packages/, apps/, libs/, etc.) and
    syncs each one with its own target/section overrides.
    """
    from src.monorepo_sync import MonorepoPackageDiscoverer, run_monorepo_sync as _run, format_monorepo_results

    print("HarnessSync — Monorepo Mode")
    print("=" * 50)

    discoverer = MonorepoPackageDiscoverer(project_dir)
    packages = discoverer.discover()

    if not packages:
        print("No monorepo sub-packages found.")
        print(
            "Add a .harnesssync-package.json to any subdirectory, or place a CLAUDE.md "
            "inside packages/, apps/, libs/, or services/."
        )
        return

    print(discoverer.format_report(packages))
    print()

    results = _run(
        project_dir=project_dir,
        packages=packages,
        dry_run=args.dry_run,
        scope=args.scope,
        allow_secrets=getattr(args, "allow_secrets", False),
    )

    print(format_monorepo_results(results))


def run_watch_mode(project_dir: Path, args, only_sections, skip_sections,
                   cc_home: Path = None) -> None:
    """Watch Claude Code config files and sync on change.

    Uses polling (stat mtime) since fswatch/inotify may not be available.
    Triggers incremental sync whenever a watched file changes.

    Args:
        project_dir: Project root directory
        args: Parsed sync arguments
        only_sections: Section filter from --only
        skip_sections: Section filter from --skip
        cc_home: Claude Code config directory (default: ~/.claude)
    """
    import time as _time

    if cc_home is None:
        cc_home = Path.home() / ".claude"

    # Files and dirs to watch
    watch_targets = [
        project_dir / "CLAUDE.md",
        project_dir / ".claude",
        project_dir / ".mcp.json",
        project_dir / ".harness-sync",
        cc_home / "settings.json",
        cc_home.parent / ".mcp.json",
    ]

    def _collect_mtimes() -> dict:
        mtimes: dict[str, float] = {}
        for target in watch_targets:
            if target.is_file():
                mtimes[str(target)] = target.stat().st_mtime
            elif target.is_dir():
                for f in target.rglob("*"):
                    if f.is_file():
                        mtimes[str(f)] = f.stat().st_mtime
        return mtimes

    print("HarnessSync Watch Mode")
    print("=" * 50)
    print("Watching Claude Code config files for changes...")
    print("Press Ctrl+C to stop.\n")

    _notifier = DesktopNotifier()

    last_mtimes = _collect_mtimes()

    try:
        while True:
            _time.sleep(1)
            current_mtimes = _collect_mtimes()

            changed = set()
            for path, mtime in current_mtimes.items():
                if last_mtimes.get(path) != mtime:
                    changed.add(path)
            for path in last_mtimes:
                if path not in current_mtimes:
                    changed.add(path)

            if changed:
                import datetime
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                print(f"[{ts}] Changes detected ({len(changed)} file(s)), syncing...")
                for p in sorted(changed)[:5]:
                    print(f"  {p}")

                try:
                    orchestrator = SyncOrchestrator(
                        project_dir=project_dir,
                        scope=args.scope,
                        dry_run=args.dry_run,
                        allow_secrets=args.allow_secrets,
                        only_sections=only_sections,
                        skip_sections=skip_sections,
                        incremental=True,  # Always incremental in watch mode
                    )
                    results = orchestrator.sync_all()
                    # Brief summary
                    synced_total = sum(
                        sum(getattr(r, 'synced', 0) for r in tr.values() if hasattr(r, 'synced'))
                        for tr in results.values()
                        if isinstance(tr, dict) and not str(tr).startswith('_')
                    )
                    print(f"[{ts}] Sync complete.\n")
                    _notifier.notify_sync_complete(
                        targets_updated=[k for k in results if not k.startswith("_")],
                        targets_skipped=[],
                        errors=[],
                    )
                except Exception as e:
                    print(f"[{ts}] Sync error: {e}\n")
                    _notifier.notify_sync_error("watch", str(e))

                last_mtimes = current_mtimes
    except KeyboardInterrupt:
        print("\nWatch mode stopped.")
