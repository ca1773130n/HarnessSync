from __future__ import annotations

"""
/sync-git-hook slash command implementation.

Install or uninstall git hooks that auto-sync config when CLAUDE.md,
.claude/, or .mcp.json changes.

Post-commit hook:   syncs in background after commit (non-blocking)
Pre-commit hook:    syncs synchronously and stages updated target files
                    (AGENTS.md, GEMINI.md, etc.) in the same commit
Gate hook:          blocks commits when harness configs are stale
                    (Claude Code config changed but targets not synced yet)
Post-checkout hook: auto-syncs when switching branches or pulling team
                    config changes (removes need to remember /sync after
                    git checkout or git pull)
Post-merge hook:    auto-syncs after git merge / git pull when team config
                    files (CLAUDE.md, .mcp.json, etc.) changed in the merge
                    (item 3 — Team Config Broadcast via Git)
Pre-push hook:      blocks git push when harness configs are out of sync
                    with CLAUDE.md, preventing teams from pushing config
                    debt (item 4 — Pre-Push Sync Enforcement)

Usage:
    /sync-git-hook                            # show status
    /sync-git-hook install                    # install post-commit hook
    /sync-git-hook install --pre-commit       # install pre-commit sync + auto-stage
    /sync-git-hook install --gate             # install pre-commit gate (blocking)
    /sync-git-hook install --post-checkout    # install post-checkout branch-sync hook
    /sync-git-hook install --post-merge       # install post-merge team-config hook
    /sync-git-hook install --pre-push         # install pre-push sync enforcement hook
    /sync-git-hook uninstall                  # remove post-commit hook
    /sync-git-hook uninstall --pre-commit     # remove pre-commit hook
    /sync-git-hook uninstall --gate           # remove gate hook
    /sync-git-hook uninstall --post-checkout  # remove post-checkout hook
    /sync-git-hook uninstall --post-merge     # remove post-merge hook
    /sync-git-hook uninstall --pre-push       # remove pre-push hook
"""

import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.git_hook_installer import (
    install_hook,
    uninstall_hook,
    is_hook_installed,
    install_pre_commit_hook,
    uninstall_pre_commit_hook,
    is_pre_commit_hook_installed,
    install_gate_hook,
    uninstall_gate_hook,
    is_gate_hook_installed,
    install_post_checkout_hook,
    uninstall_post_checkout_hook,
    is_post_checkout_hook_installed,
    install_post_merge_hook,
    uninstall_post_merge_hook,
    is_post_merge_hook_installed,
    install_pre_push_hook,
    uninstall_pre_push_hook,
    is_pre_push_hook_installed,
)


def _generate_lazy_wrapper(harness: str, cli_executable: str, plugin_root: str) -> str:
    """Generate a shell function that syncs a single harness before running its CLI.

    The generated function is a drop-in replacement for the real CLI executable:
    it syncs only the target harness (fast, single-target), then execs the real
    binary with the original arguments.  If the sync fails, the CLI still runs —
    lazy sync is best-effort and never blocks the user's workflow.

    Args:
        harness:        Harness name (e.g. "aider", "gemini").
        cli_executable: Absolute path to the real CLI (from shutil.which).
        plugin_root:    Absolute path to the HarnessSync plugin root.

    Returns:
        Shell function definition string suitable for .zshrc / .bashrc.
    """
    py_detect = "$(command -v python3 || command -v python)"
    return f"""\
# Lazy on-demand HarnessSync wrapper for {harness}
# Paste into ~/.zshrc or ~/.bashrc, then reload your shell.
{harness}() {{
  _hs_py={py_detect}
  if [ -n "$_hs_py" ]; then
    "$_hs_py" -m src.commands.sync --targets {harness} --project-dir "${{CLAUDE_PROJECT_DIR:-$PWD}}" \\
      2>/dev/null &  # background, non-blocking
    wait $!         # wait for sync before starting CLI
  fi
  command {cli_executable} "$@"
}}"""


def _show_lazy_wrappers(harness_list: list[str] | None, plugin_root: str) -> None:
    """Print lazy on-demand sync shell wrappers for the given harnesses.

    Detects which harnesses are installed (by checking shutil.which) and prints
    shell function snippets for each one.

    Args:
        harness_list: Harnesses to generate wrappers for (None = auto-detect).
        plugin_root:  HarnessSync plugin root path.
    """
    import shutil

    # Known CLI executables per harness
    _CLI_MAP: dict[str, list[str]] = {
        "aider":    ["aider"],
        "gemini":   ["gemini"],
        "codex":    ["codex"],
        "opencode": ["opencode", "opencode-cli"],
        "cursor":   ["cursor"],
        "windsurf": ["windsurf"],
        "cline":    [],   # VS Code extension — no CLI to wrap
        "continue": [],   # VS Code extension — no CLI to wrap
        "zed":      ["zed"],
        "neovim":   ["nvim"],
    }

    targets = harness_list or list(_CLI_MAP.keys())
    wrappers_generated: list[str] = []

    for harness in targets:
        executables = _CLI_MAP.get(harness, [harness])
        if not executables:
            print(f"  # {harness}: VS Code extension — no CLI wrapper needed")
            continue
        found_exe = None
        for exe in executables:
            path = shutil.which(exe)
            if path:
                found_exe = path
                break
        if not found_exe:
            print(f"  # {harness}: not found on PATH — skipping")
            continue
        snippet = _generate_lazy_wrapper(harness, found_exe, plugin_root)
        print(snippet)
        print()
        wrappers_generated.append(harness)

    if wrappers_generated:
        print("# ── How to use ──────────────────────────────────────────────")
        print("# 1. Paste the functions above into ~/.zshrc (or ~/.bashrc)")
        print("# 2. Run: source ~/.zshrc")
        print("# 3. Now calling 'aider', 'gemini', etc. will sync first.")
        print()
        print("# To disable, remove the function from your shell config.")
        print("# Lazy sync is best-effort — the CLI runs even if sync fails.")
    else:
        print("No supported harness CLIs found on PATH.")
        print("Install a harness (aider, gemini, codex, opencode, cursor, windsurf)")
        print("and re-run /sync-git-hook --lazy-wrapper.")


def main() -> None:
    """Entry point for /sync-git-hook command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-git-hook",
        description="Install/uninstall git hooks for auto-sync",
    )
    parser.add_argument(
        "action",
        choices=["install", "uninstall", "status"],
        nargs="?",
        default="status",
        help="Action to perform (default: status)",
    )
    parser.add_argument(
        "--pre-commit",
        action="store_true",
        help="Target pre-commit hook (syncs synchronously, stages updated files)",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Install/remove pre-commit gate that blocks commits when sync is stale",
    )
    parser.add_argument(
        "--post-checkout",
        action="store_true",
        dest="post_checkout",
        help=(
            "Install/remove post-checkout hook that auto-syncs when switching branches "
            "or pulling team config changes (non-blocking, background sync)"
        ),
    )
    parser.add_argument(
        "--post-merge",
        action="store_true",
        dest="post_merge",
        help=(
            "Install/remove post-merge hook that auto-syncs after git merge/pull when "
            "team config files (CLAUDE.md, .mcp.json, settings.json) changed "
            "(item 3: Team Config Broadcast via Git)"
        ),
    )
    parser.add_argument(
        "--pre-push",
        action="store_true",
        dest="pre_push",
        help=(
            "Install/remove pre-push enforcement hook that blocks push when harness "
            "configs are out of sync with CLAUDE.md. Prevents teams from pushing "
            "CLAUDE.md changes without also committing the synced harness files."
        ),
    )
    parser.add_argument(
        "--lazy-wrapper",
        action="store_true",
        dest="lazy_wrapper",
        help=(
            "Generate lazy on-demand sync shell wrappers for each installed harness CLI "
            "(aider, gemini, codex, opencode, cursor, windsurf). "
            "When a harness CLI is invoked through the wrapper, HarnessSync syncs "
            "only that harness first, then runs the real CLI. "
            "Paste the printed shell snippet into your ~/.zshrc or ~/.bashrc."
        ),
    )
    parser.add_argument(
        "--lazy-harnesses",
        type=str,
        default=None,
        dest="lazy_harnesses",
        metavar="LIST",
        help=(
            "Comma-separated harnesses to generate lazy wrappers for "
            "(default: all that are installed on PATH). "
            "Example: --lazy-harnesses aider,gemini"
        ),
    )
    parser.add_argument("--project-dir", type=str, default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    pre_commit = args.pre_commit
    gate = getattr(args, 'gate', False)
    post_checkout = getattr(args, 'post_checkout', False)
    post_merge = getattr(args, 'post_merge', False)
    pre_push = getattr(args, 'pre_push', False)

    # --lazy-wrapper: generate on-demand sync shell functions
    if getattr(args, "lazy_wrapper", False):
        harness_list: list[str] | None = None
        raw_harnesses = getattr(args, "lazy_harnesses", None)
        if raw_harnesses:
            harness_list = [h.strip() for h in raw_harnesses.split(",") if h.strip()]
        print("# HarnessSync Lazy On-Demand Sync Wrappers")
        print("# =========================================")
        print("# Each function syncs only that harness before launching the CLI.")
        print()
        _show_lazy_wrappers(harness_list, PLUGIN_ROOT)
        return

    if args.action == "status":
        post_installed = is_hook_installed(project_dir)
        pre_installed = is_pre_commit_hook_installed(project_dir)
        gate_installed = is_gate_hook_installed(project_dir)
        post_checkout_installed = is_post_checkout_hook_installed(project_dir)
        post_merge_installed = is_post_merge_hook_installed(project_dir)
        pre_push_installed = is_pre_push_hook_installed(project_dir)

        print("HarnessSync Git Hook Status")
        print("=" * 40)
        print(f"  post-commit:      {'installed' if post_installed else 'not installed'}")
        print(f"  pre-commit:       {'installed' if pre_installed else 'not installed'}")
        print(f"  pre-commit gate:  {'installed' if gate_installed else 'not installed'}")
        print(f"  post-checkout:    {'installed' if post_checkout_installed else 'not installed'}")
        print(f"  post-merge:       {'installed' if post_merge_installed else 'not installed'}")
        print(f"  pre-push:         {'installed' if pre_push_installed else 'not installed'}")
        print()
        if post_installed:
            print("Post-commit:    auto-syncs in background after each commit.")
        if pre_installed:
            print("Pre-commit:     syncs and stages target files before each commit.")
        if gate_installed:
            print("Gate:           blocks commits when harness configs are stale.")
        if post_checkout_installed:
            print("Post-checkout:  auto-syncs when switching branches or pulling team changes.")
        if post_merge_installed:
            print("Post-merge:     auto-syncs after git pull/merge when team config files change.")
        if pre_push_installed:
            print("Pre-push:       blocks push when harness configs are out of sync with CLAUDE.md.")
        if not any([post_installed, pre_installed, gate_installed, post_checkout_installed,
                    post_merge_installed, pre_push_installed]):
            print("Run /sync-git-hook install to enable post-commit auto-sync.")
            print("Run /sync-git-hook install --pre-commit to enable pre-commit sync + auto-stage.")
            print("Run /sync-git-hook install --gate to enable the stale-sync commit gate.")
            print("Run /sync-git-hook install --post-checkout to enable branch-switch auto-sync.")
            print("Run /sync-git-hook install --post-merge to enable team config broadcast.")
            print("Run /sync-git-hook install --pre-push to enforce sync before push.")

    elif args.action == "install":
        if gate:
            success, message = install_gate_hook(project_dir)
            if success:
                print(f"OK: {message}")
                print()
                print("HarnessSync gate is active: commits that include CLAUDE.md changes")
                print("will be blocked if the harness target files are out of sync.")
                print("Run /sync to unblock, then commit again.")
            else:
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)
        elif pre_commit:
            success, message = install_pre_commit_hook(project_dir)
            if success:
                print(f"OK: {message}")
                print()
                print("HarnessSync will now sync harness configs and stage updated")
                print("target files (AGENTS.md, GEMINI.md, etc.) before each commit")
                print("when CLAUDE.md, .claude/, or .mcp.json is staged.")
            else:
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)
        elif post_checkout:
            success, message = install_post_checkout_hook(project_dir)
            if success:
                print(f"OK: {message}")
                print()
                print("HarnessSync will now auto-sync in the background whenever you")
                print("switch branches (git checkout / git switch), but only when")
                print("CLAUDE.md, .claude/, or .mcp.json differs between branches.")
                print("This eliminates 'forgot to /sync after git pull' config drift.")
            else:
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)
        elif post_merge:
            success, message = install_post_merge_hook(project_dir)
            if success:
                print(f"OK: {message}")
                print()
                print("HarnessSync will now auto-sync after git pull/merge when")
                print("CLAUDE.md, .mcp.json, or other team config files changed.")
                print("This ensures everyone's harnesses stay in sync after pulling team changes.")
            else:
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)
        elif pre_push:
            success, message = install_pre_push_hook(project_dir)
            if success:
                print(f"OK: {message}")
                print()
                print("HarnessSync will now block git push when harness configs are out")
                print("of sync with CLAUDE.md. Run /sync and commit the updated harness")
                print("files before pushing to prevent config debt in shared repos.")
            else:
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)
        else:
            success, message = install_hook(project_dir)
            if success:
                print(f"OK: {message}")
                print()
                print("HarnessSync will now auto-sync in the background whenever you commit")
                print("changes to CLAUDE.md, .claude/, or .mcp.json.")
            else:
                print(f"Error: {message}", file=sys.stderr)
                sys.exit(1)

    elif args.action == "uninstall":
        if gate:
            success, message = uninstall_gate_hook(project_dir)
        elif pre_commit:
            success, message = uninstall_pre_commit_hook(project_dir)
        elif post_checkout:
            success, message = uninstall_post_checkout_hook(project_dir)
        elif post_merge:
            success, message = uninstall_post_merge_hook(project_dir)
        elif pre_push:
            success, message = uninstall_pre_push_hook(project_dir)
        else:
            success, message = uninstall_hook(project_dir)

        if success:
            print(f"OK: {message}")
        else:
            print(f"Error: {message}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
