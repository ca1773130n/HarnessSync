from __future__ import annotations

"""
/sync-resolve slash command — Interactive conflict resolver.

When HarnessSync detects that a target config file was manually edited since
the last sync, it logs a conflict warning but cannot proceed safely. This
command reads the backup snapshot (last-synced version) and the current
target file, renders a numbered hunk diff, and lets the user resolve each
hunk interactively.

Resolution choices per hunk:
  mine    — keep the current file's version (your manual edits)
  theirs  — keep the backup version (what HarnessSync wrote)
  skip    — leave this hunk unresolved and continue to the next

After resolving all hunks the merged file is written and the conflict flag is
cleared in state so the next `/sync` proceeds normally.

Usage:
    /sync-resolve              # resolve conflicts for all targets
    /sync-resolve codex        # resolve conflicts for codex only
    /sync-resolve --list       # list all targets with active conflicts
"""

import difflib
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.conflict_detector import ConflictDetector
from src.state_manager import StateManager
from src.utils.hashing import hash_file_sha256
from src.adapters import AdapterRegistry


def _find_backup_content(target_name: str, file_path: Path) -> str | None:
    """Return the most-recent backup content for file_path, or None."""
    backup_root = Path.home() / ".harnesssync" / "backups" / target_name
    if not backup_root.is_dir():
        return None

    # Each backup dir is named: {filename}_{timestamp}[_{label}]
    # Find the most recent backup that contains our file
    candidates: list[tuple[str, Path]] = []
    filename = file_path.name
    try:
        for entry in backup_root.iterdir():
            if not entry.is_dir():
                continue
            backed_up = entry / filename
            if backed_up.is_file():
                candidates.append((entry.name, backed_up))
    except OSError:
        return None

    if not candidates:
        return None

    # Sort descending by directory name (timestamp prefix makes this correct)
    candidates.sort(key=lambda x: x[0], reverse=True)
    latest = candidates[0][1]
    try:
        return latest.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _make_hunks(theirs_lines: list[str], mine_lines: list[str]) -> list[dict]:
    """Split a unified diff into numbered hunks.

    Returns a list of hunk dicts with keys:
      - index: 1-based hunk number
      - header: unified diff header line
      - lines: list of diff lines (context + +/- lines)
      - theirs_block: lines from the backup (their version)
      - mine_block: lines from the current file (my version)
    """
    hunks: list[dict] = []
    matcher = difflib.SequenceMatcher(None, theirs_lines, mine_lines, autojunk=False)
    idx = 0
    for group in matcher.get_grouped_opcodes(n=3):
        idx += 1
        theirs_block: list[str] = []
        mine_block: list[str] = []
        diff_lines: list[str] = []
        i1 = group[0][1]
        i2 = group[-1][2]
        j1 = group[0][3]
        j2 = group[-1][4]
        header = f"@@ -{i1 + 1},{i2 - i1} +{j1 + 1},{j2 - j1} @@"
        for tag, a0, a1, b0, b1 in group:
            if tag == "equal":
                for line in theirs_lines[a0:a1]:
                    diff_lines.append(f"  {line}")
                    theirs_block.append(line)
                    mine_block.append(line)
            elif tag in ("replace", "delete"):
                for line in theirs_lines[a0:a1]:
                    diff_lines.append(f"- {line}")
                    theirs_block.append(line)
                if tag == "replace":
                    for line in mine_lines[b0:b1]:
                        diff_lines.append(f"+ {line}")
                        mine_block.append(line)
            elif tag == "insert":
                for line in mine_lines[b0:b1]:
                    diff_lines.append(f"+ {line}")
                    mine_block.append(line)
        hunks.append({
            "index": idx,
            "header": header,
            "lines": diff_lines,
            "theirs_block": theirs_block,
            "mine_block": mine_block,
        })
    return hunks


def _resolve_file_interactive(
    file_path: Path,
    backup_content: str,
    current_content: str,
    target_name: str,
    no_interactive: bool = False,
) -> str | None:
    """Interactively resolve conflicts for a single file.

    Returns the resolved content string, or None if user skipped entirely.
    """
    theirs_lines = backup_content.splitlines(keepends=True)
    mine_lines = current_content.splitlines(keepends=True)

    if theirs_lines == mine_lines:
        print(f"  {file_path.name}: no differences — conflict flag will be cleared.")
        return current_content

    hunks = _make_hunks(theirs_lines, mine_lines)
    if not hunks:
        return current_content

    print(f"\nFile: {file_path}")
    print(f"  {len(hunks)} hunk(s) differ between backup (theirs) and current file (mine).")
    print()

    # Start from backup (theirs), selectively apply mine choices
    resolved_lines = list(theirs_lines)

    for hunk in hunks:
        print(f"--- Hunk {hunk['index']}/{len(hunks)}  {hunk['header']}")
        for line in hunk["lines"]:
            print(f"  {line}", end="")
            if not line.endswith("\n"):
                print()

        if no_interactive:
            choice = "mine"
            print("  → auto-selecting 'mine' (--no-interactive)")
        else:
            print()
            while True:
                raw = input("  [mine|theirs|skip] > ").strip().lower()
                if raw in ("mine", "theirs", "skip", "m", "t", "s"):
                    choice = {"m": "mine", "t": "theirs", "s": "skip"}.get(raw, raw)
                    break
                print("  Please enter: mine, theirs, or skip")

        if choice == "theirs":
            print(f"  → keeping backup version for hunk {hunk['index']}")
        elif choice == "mine":
            tb = hunk["theirs_block"]
            mb = hunk["mine_block"]
            if tb:
                for i in range(len(resolved_lines)):
                    if resolved_lines[i:i + len(tb)] == tb:
                        resolved_lines[i:i + len(tb)] = mb
                        break
            else:
                # Pure insertion: append mine_block at the appropriate position
                resolved_lines.extend(mb)
            print(f"  → keeping your version for hunk {hunk['index']}")
        else:
            print(f"  → skipping hunk {hunk['index']} (backup version retained)")

        print()

    return "".join(resolved_lines)


def _show_conflict_diff(file_path: Path, target_name: str) -> None:
    """Print a unified diff between the pre-sync backup and the current target file."""
    backup_content = _find_backup_content(target_name, file_path)
    if backup_content is None:
        print("    (no backup snapshot — cannot show diff)")
        return
    if not file_path.is_file():
        print("    (file deleted since last sync)")
        return
    current_content = file_path.read_text(encoding="utf-8", errors="replace")
    diff = difflib.unified_diff(
        backup_content.splitlines(keepends=True),
        current_content.splitlines(keepends=True),
        fromfile=f"last-synced/{file_path.name}",
        tofile=f"current/{file_path.name}",
        lineterm="",
    )
    diff_lines = list(diff)
    if not diff_lines:
        print("    (files are identical — stale conflict flag)")
        return
    for line in diff_lines[:40]:
        print(f"    {line}")
    if len(diff_lines) > 40:
        print(f"    ... ({len(diff_lines) - 40} more lines)")


def _list_conflicts(targets: list[str], show_diff: bool = False) -> None:
    """Print a summary of all targets with active conflicts."""
    detector = ConflictDetector()
    found_any = False
    for target in targets:
        conflicts = detector.check(target)
        if conflicts:
            found_any = True
            print(f"  {target}: {len(conflicts)} conflicted file(s)")
            for c in conflicts:
                note = f"  [{c.get('note', 'modified')}]"
                print(f"    {c['file_path']}{note}")
                if show_diff:
                    _show_conflict_diff(Path(c["file_path"]), target)
    if not found_any:
        print("  No conflicts detected across all targets.")


def _clear_conflict(state_manager: StateManager, target_name: str, file_path: Path) -> None:
    """Update state hash for file_path so the conflict flag is cleared."""
    new_hash = hash_file_sha256(file_path)
    if not new_hash:
        return
    try:
        state_manager.update_file_hash(target_name, str(file_path), new_hash)
    except Exception:
        try:
            target_status = state_manager.get_target_status(target_name) or {}
            file_hashes = target_status.get("file_hashes", {})
            file_hashes[str(file_path)] = new_hash
            target_status["file_hashes"] = file_hashes
            state_manager.update_target_status(target_name, target_status)
        except Exception:
            pass


def main() -> None:
    """Entry point for /sync-resolve command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-resolve",
        description="Interactively resolve HarnessSync conflict flags.",
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="Target harness to resolve (default: all conflicted targets)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all targets with active conflicts and exit",
    )
    parser.add_argument(
        "--show-diff",
        action="store_true",
        dest="show_diff",
        help="With --list: show unified diff of each conflicted file vs its last-sync snapshot",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        dest="no_interactive",
        help="Non-interactive mode: automatically choose 'mine' for every hunk",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Override project directory (default: current directory)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    all_targets = AdapterRegistry.list_targets()
    targets = [args.target] if args.target else list(all_targets)

    if args.list:
        print("Targets with conflicts:")
        _list_conflicts(targets)
        return

    detector = ConflictDetector()
    state_manager = StateManager()
    resolved_count = 0
    skipped_count = 0

    for target in targets:
        conflicts = detector.check(target)
        if not conflicts:
            continue

        print(f"\n{'=' * 60}")
        print(f"Target: {target}  ({len(conflicts)} conflict(s))")
        print(f"{'=' * 60}")

        for conflict in conflicts:
            file_path = Path(conflict["file_path"])

            if conflict.get("note") == "deleted":
                print(f"\n  {file_path.name}: file was deleted.")
                if args.no_interactive:
                    choice = "yes"
                else:
                    choice = input("  Restore from backup? [yes/no] > ").strip().lower()
                if choice in ("yes", "y"):
                    backup_content = _find_backup_content(target, file_path)
                    if backup_content:
                        try:
                            file_path.parent.mkdir(parents=True, exist_ok=True)
                            file_path.write_text(backup_content, encoding="utf-8")
                            _clear_conflict(state_manager, target, file_path)
                            print(f"  Restored {file_path.name} from backup.")
                            resolved_count += 1
                        except OSError as e:
                            print(f"  Error restoring: {e}")
                    else:
                        print(f"  No backup found for {file_path.name}.")
                continue

            if not file_path.is_file():
                print(f"\n  {file_path}: file not found, skipping.")
                skipped_count += 1
                continue

            current_content = file_path.read_text(encoding="utf-8", errors="replace")
            backup_content = _find_backup_content(target, file_path)

            if backup_content is None:
                print(f"\n  {file_path.name}: no backup snapshot found.")
                print("  Clearing conflict flag to unblock sync.")
                _clear_conflict(state_manager, target, file_path)
                resolved_count += 1
                continue

            resolved = _resolve_file_interactive(
                file_path=file_path,
                backup_content=backup_content,
                current_content=current_content,
                target_name=target,
                no_interactive=args.no_interactive,
            )

            if resolved is not None:
                try:
                    file_path.write_text(resolved, encoding="utf-8")
                    _clear_conflict(state_manager, target, file_path)
                    print(f"  Written: {file_path}")
                    resolved_count += 1
                except OSError as e:
                    print(f"  Error writing {file_path}: {e}")
                    skipped_count += 1
            else:
                skipped_count += 1

    print()
    print(f"Done. {resolved_count} conflict(s) resolved, {skipped_count} skipped.")
    if resolved_count > 0:
        print("Run /sync to push changes to all targets.")


if __name__ == "__main__":
    main()
