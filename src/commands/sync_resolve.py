from __future__ import annotations

"""
/sync-resolve slash command — Interactive conflict resolver.

When a target file was manually edited since last sync, HarnessSync warns
and skips it. This command loads the conflict list from state, renders a
side-by-side diff, and prompts the user to choose how to resolve each one.

Usage:
    /sync-resolve                  # resolve all pending conflicts interactively
    /sync-resolve --target cursor  # resolve only cursor conflicts
    /sync-resolve --auto-overwrite # overwrite all without prompting
    /sync-resolve --list           # list conflicts without resolving
"""

import os
import sys
import shlex
import argparse
import difflib

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.state_manager import StateManager
from src.orchestrator import SyncOrchestrator


def _render_side_by_side_diff(stored: str, current: str, width: int = 80) -> str:
    """Return a unified diff string comparing stored (sync) vs current (theirs)."""
    stored_lines = stored.splitlines(keepends=True)
    current_lines = current.splitlines(keepends=True)
    diff = difflib.unified_diff(
        stored_lines,
        current_lines,
        fromfile="sync-version",
        tofile="their-edits",
        lineterm="",
    )
    return "".join(diff)


def _load_conflicts(project_dir: Path, target_filter: str | None) -> list[dict]:
    """Load pending conflicts from state.json.

    Returns list of dicts with keys: target, path, stored_hash, current_hash.
    """
    sm = StateManager()
    state = sm.load_state()
    conflicts: list[dict] = []

    targets_data = state.get("targets", {})
    # Also check v2 schema under accounts
    for account_data in state.get("accounts", {}).values():
        for t, td in account_data.get("targets", {}).items():
            targets_data.setdefault(t, td)

    for target, tdata in targets_data.items():
        if target_filter and target != target_filter:
            continue
        for conflict in tdata.get("conflicts", []):
            conflicts.append({
                "target": target,
                "path": conflict.get("path", ""),
                "stored_hash": conflict.get("stored_hash", ""),
                "current_hash": conflict.get("current_hash", ""),
            })
    return conflicts


def _prompt_choice(prompt: str, choices: list[str]) -> str:
    """Prompt user for a choice, returning the chosen option."""
    choices_str = "/".join(choices)
    while True:
        try:
            answer = input(f"{prompt} [{choices_str}]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "skip"
        if answer in [c.lower() for c in choices]:
            return answer
        print(f"  Please enter one of: {choices_str}")


def _resolve_conflict(conflict: dict, project_dir: Path, auto_overwrite: bool) -> str:
    """Interactively resolve a single conflict. Returns action taken."""
    target = conflict["target"]
    rel_path = conflict["path"]
    full_path = project_dir / rel_path

    print(f"\nConflict: {target} → {rel_path}")
    print("-" * 60)

    if not full_path.exists():
        print("  File no longer exists — marking as resolved (deleted).")
        return "deleted"

    current_content = full_path.read_text(encoding="utf-8", errors="replace")

    if auto_overwrite:
        # Re-sync will write the canonical version; just clear the conflict flag
        print("  Auto-overwrite: conflict will be resolved on next /sync.")
        return "overwrite"

    # Show diff
    stored_preview = f"[sync version — hash {conflict['stored_hash'][:8]}]"
    print(f"  Theirs: {full_path} (manually edited)")
    print(f"  Ours:   {stored_preview}")
    print()

    diff = _render_side_by_side_diff(stored_preview, current_content)
    # Show first 40 lines of diff to avoid flooding output
    diff_lines = diff.splitlines()
    if len(diff_lines) > 40:
        for line in diff_lines[:40]:
            print(f"  {line}")
        print(f"  ... ({len(diff_lines) - 40} more lines)")
    else:
        for line in diff_lines:
            print(f"  {line}")

    print()
    choice = _prompt_choice(
        "  Action",
        ["overwrite", "keep", "skip"],
    )
    return choice


def main() -> None:
    """Entry point for /sync-resolve command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-resolve",
        description="Interactively resolve conflicts between synced and manually edited target files.",
    )
    parser.add_argument(
        "--target", type=str, default=None,
        help="Resolve only conflicts for this harness target",
    )
    parser.add_argument(
        "--auto-overwrite", action="store_true",
        help="Clear all conflicts and overwrite with sync version on next /sync",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List conflicts without resolving",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path.cwd()
    conflicts = _load_conflicts(project_dir, args.target)

    if not conflicts:
        target_msg = f" for '{args.target}'" if args.target else ""
        print(f"No conflicts detected{target_msg}. All targets are in sync.")
        return

    if args.list:
        print(f"Pending conflicts ({len(conflicts)}):")
        for c in conflicts:
            print(f"  {c['target']:<15} {c['path']}")
        return

    print(f"HarnessSync Conflict Resolver — {len(conflicts)} conflict(s) found")
    print("=" * 60)

    sm = StateManager()
    resolved_overwrite: list[dict] = []
    skipped: list[dict] = []

    for conflict in conflicts:
        action = _resolve_conflict(conflict, project_dir, args.auto_overwrite)

        if action in ("overwrite", "deleted"):
            resolved_overwrite.append(conflict)
        elif action == "keep":
            # Mark as acknowledged so HarnessSync stops warning
            skipped.append(conflict)
        else:
            skipped.append(conflict)

    # Clear conflict flags for overwrite-resolved items
    if resolved_overwrite:
        state = sm.load_state()
        for conflict in resolved_overwrite:
            target = conflict["target"]
            for branch in [state.get("targets", {})] + [
                a.get("targets", {}) for a in state.get("accounts", {}).values()
            ]:
                if target in branch:
                    branch[target]["conflicts"] = [
                        c for c in branch[target].get("conflicts", [])
                        if c.get("path") != conflict["path"]
                    ]
        sm.save_state(state)

    print()
    print(f"Done. {len(resolved_overwrite)} resolved, {len(skipped)} skipped.")
    if resolved_overwrite:
        print("Run /sync to apply the canonical versions to overwritten targets.")


if __name__ == "__main__":
    main()
