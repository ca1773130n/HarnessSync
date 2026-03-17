from __future__ import annotations

"""
/sync-merge slash command — interactive 3-way merge conflict resolution.

When a sync target has been manually edited since the last sync, this command
presents a 3-way merge UI: source (what HarnessSync would write), base
(the last-synced version — the common ancestor), and current (what is in the
target file right now). Showing all three versions makes it clear which
changes came from HarnessSync and which were made manually.

Usage:
    /sync-merge [TARGET] [--auto-ours] [--auto-theirs] [--dry-run] [--3way] [--project-dir PATH]

Options:
    TARGET            Target to check and merge (codex, gemini, opencode, ...).
                      If omitted, checks all targets with conflicts.
    --auto-ours       Automatically keep the HarnessSync (source) version for all conflicts
    --auto-theirs     Automatically keep the manually-edited (target) version for all conflicts
    --3way            Show the full 3-way diff (source / base / current) for each conflict.
                      Default when on a TTY.
    --dry-run         Show conflicts without writing any resolution
    --project-dir PATH  Project directory (default: cwd)
"""

import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.conflict_detector import ConflictDetector
from src.state_manager import StateManager


def _format_conflict_block(conflict: dict, index: int, show_three_way: bool = False) -> str:
    """Format a single conflict for display.

    When show_three_way=True, shows the full 3-way diff (source / base / current)
    using ConflictDetector.three_way_diff().  When False, falls back to the
    simpler side-by-side view (source vs current).
    """
    lines = [
        f"\n{'─' * 60}",
        f"Conflict #{index + 1}: {conflict.get('file_path', '(unknown)')}",
        f"{'─' * 60}",
    ]

    if show_three_way:
        source = conflict.get("source_content", "")
        try:
            detector = ConflictDetector(state_manager=StateManager())
            three_way = detector.three_way_diff(
                source_content=source,
                conflict=conflict,
                base_content=conflict.get("base_content") or conflict.get("stored_content"),
            )
            has_base = bool(three_way.get("base_lines"))
            lines.append("")
            if has_base:
                lines.append("  [ 3-Way diff — base: last-synced, ours: sync source, theirs: manual edits ]")
                lines.append("")
                lines.append("  Changes: last-synced -> manual edits (YOUR changes):")
                udiff_btc = three_way.get("unified_base_vs_current", "")
                if udiff_btc.strip():
                    for dl in udiff_btc.splitlines()[:30]:
                        lines.append(f"    {dl}")
                    if len(udiff_btc.splitlines()) > 30:
                        lines.append(f"    ... ({len(udiff_btc.splitlines()) - 30} more lines)")
                else:
                    lines.append("    (no changes from base)")
                lines.append("")
                lines.append("  Changes: last-synced -> sync source (HARNESSSYNC changes):")
                udiff_bts = three_way.get("unified_base_vs_source", "")
                if udiff_bts.strip():
                    for dl in udiff_bts.splitlines()[:30]:
                        lines.append(f"    {dl}")
                    if len(udiff_bts.splitlines()) > 30:
                        lines.append(f"    ... ({len(udiff_bts.splitlines()) - 30} more lines)")
                else:
                    lines.append("    (no changes from base)")
            else:
                lines.append("  [ 2-Way diff — no prior baseline available ]")
                lines.append("")
                udiff_stc = three_way.get("unified_source_vs_current", "")
                if udiff_stc.strip():
                    for dl in udiff_stc.splitlines()[:40]:
                        lines.append(f"    {dl}")
                    if len(udiff_stc.splitlines()) > 40:
                        lines.append(f"    ... ({len(udiff_stc.splitlines()) - 40} more lines)")
                else:
                    lines.append("    (files are identical)")
            return "\n".join(lines)
        except Exception:
            pass  # Fall through to simple display on error

    # Simple 2-way display (fallback)
    source = conflict.get("source_content", "")
    current = conflict.get("current_content", "")
    if source and current:
        src_lines = source.splitlines()
        cur_lines = current.splitlines()
        lines.append(f"\n{'<<< SYNC SOURCE (HarnessSync would write this)':60s}")
        for line in src_lines[:20]:
            lines.append(f"  {line}")
        if len(src_lines) > 20:
            lines.append(f"  ... ({len(src_lines) - 20} more lines)")
        lines.append(f"\n{'>>> CURRENT (manually edited)':60s}")
        for line in cur_lines[:20]:
            lines.append(f"  {line}")
        if len(cur_lines) > 20:
            lines.append(f"  ... ({len(cur_lines) - 20} more lines)")
    elif conflict.get("note") == "deleted":
        lines.append("  File was deleted manually -- HarnessSync would recreate it.")
    else:
        lines.append(f"  Stored hash: {conflict.get('stored_hash', '')[:16]}")
        lines.append(f"  Current hash: {conflict.get('current_hash', '')[:16]}")
    return "\n".join(lines)


def _resolve_auto(conflicts: list[dict], keep: str, dry_run: bool) -> int:
    """Auto-resolve all conflicts by keeping 'ours' (sync source) or 'theirs' (manual edits)."""
    resolved = 0
    for conflict in conflicts:
        file_path = Path(conflict.get("file_path", ""))
        if not file_path.exists():
            continue
        if keep == "ours":
            source_content = conflict.get("source_content", "")
            if source_content and not dry_run:
                file_path.write_text(source_content, encoding="utf-8")
                print(f"  ✓ {file_path} — kept sync source version")
            elif dry_run:
                print(f"  [dry-run] {file_path} — would keep sync source version")
        else:  # theirs
            print(f"  ✓ {file_path} — kept manually-edited version (no write needed)")
        resolved += 1
    return resolved


def main():
    """Entry point for /sync-merge command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-merge",
        description="Interactive merge conflict resolution for manually-edited sync targets.",
    )
    parser.add_argument(
        "target", nargs="?", default=None,
        help="Specific target to check (e.g. codex, gemini). Default: check all.",
    )
    parser.add_argument("--auto-ours", action="store_true",
                        help="Auto-keep HarnessSync (source) version for all conflicts")
    parser.add_argument("--auto-theirs", action="store_true",
                        help="Auto-keep manually-edited version for all conflicts")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show conflicts without writing any resolution")
    parser.add_argument(
        "--3way", dest="three_way", action="store_true",
        help=(
            "Show the full 3-way diff (source / last-synced baseline / current) for "
            "each conflict. Makes it clear which changes came from HarnessSync vs. "
            "your manual edits. Enabled by default on a TTY."
        ),
    )
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--json", dest="output_json", action="store_true")

    args = parser.parse_args(raw_args)

    if args.auto_ours and args.auto_theirs:
        print("Error: --auto-ours and --auto-theirs are mutually exclusive.", file=sys.stderr)
        sys.exit(1)

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()
    state_manager = StateManager(project_dir=project_dir)
    detector = ConflictDetector(state_manager=state_manager)

    # Determine targets to check
    if args.target:
        targets_to_check = [args.target]
    else:
        # Check all known targets
        targets_to_check = ["codex", "gemini", "opencode", "cursor", "aider", "windsurf"]

    all_conflicts: dict[str, list[dict]] = {}
    for target in targets_to_check:
        try:
            conflicts = detector.check(target)
            if conflicts:
                all_conflicts[target] = conflicts
        except Exception:
            pass  # Target not configured; skip silently

    if not all_conflicts:
        print("✓ No conflicts detected — all sync targets match their last-synced state.")
        return

    total = sum(len(v) for v in all_conflicts.values())
    print(f"Found {total} conflict(s) across {len(all_conflicts)} target(s):\n")

    # Enable 3-way diff by default on TTY; also when explicitly requested.
    use_three_way = getattr(args, "three_way", False) or sys.stdout.isatty()

    for target, conflicts in all_conflicts.items():
        print(f"\n[{target.upper()}] {len(conflicts)} conflict(s)")
        for i, conflict in enumerate(conflicts):
            print(_format_conflict_block(conflict, i, show_three_way=use_three_way))

    if args.dry_run:
        print("\n[dry-run] No changes written.")
        return

    if args.auto_ours:
        print("\nAuto-resolving: keeping HarnessSync (source) versions…")
        for target, conflicts in all_conflicts.items():
            resolved = _resolve_auto(conflicts, "ours", dry_run=False)
            print(f"  {target}: {resolved} conflict(s) resolved (kept source)")
        print("\nDone. Run /sync to re-sync and update stored hashes.")
        return

    if args.auto_theirs:
        print("\nAuto-resolving: keeping manually-edited versions…")
        for target, conflicts in all_conflicts.items():
            resolved = _resolve_auto(conflicts, "theirs", dry_run=False)
            print(f"  {target}: {resolved} conflict(s) resolved (kept manual edits)")
        print("\nDone. Note: manual edits will be overwritten on next sync unless you re-sync from Claude Code.")
        return

    # Interactive mode (default for TTY)
    if sys.stdout.isatty():
        print("\nInteractive resolution:")
        print("  For each conflict, choose: [s]ource (sync) / [m]anual (keep edits) / [e]dit manually")
        for target, conflicts in all_conflicts.items():
            for conflict in conflicts:
                file_path = Path(conflict.get("file_path", ""))
                print(f"\nFile: {file_path}")
                choice = input("Keep: [s]ource / [m]anual (default: manual) > ").strip().lower()
                if choice == "s":
                    source_content = conflict.get("source_content", "")
                    if source_content and file_path.exists():
                        file_path.write_text(source_content, encoding="utf-8")
                        print(f"  ✓ Applied source version")
                else:
                    print(f"  ✓ Kept manual edits")
        print("\nDone. Run /sync to re-sync.")
    else:
        # Non-TTY: print summary and suggest flags
        print("\nRun with --auto-ours or --auto-theirs to resolve automatically.")
        print("Or run interactively in a terminal session.")


if __name__ == "__main__":
    main()
