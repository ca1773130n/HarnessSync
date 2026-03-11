from __future__ import annotations

"""Harness Hot-Swap Mode — sync and immediately open another harness.

Ensures the target harness is fully synced, then launches it in a new terminal
window pre-configured with the same project context. One command to go from
Claude Code to Gemini CLI (or Codex, OpenCode, etc.) without manual setup.

Usage:
    /sync-hotswap --to gemini
    /sync-hotswap --to codex [--no-sync]
    /sync-hotswap --to opencode [--project-dir PATH]

Options:
    --to HARNESS      Target harness to open (gemini | codex | opencode | cursor | aider)
    --no-sync         Skip sync step; just launch the harness
    --project-dir     Project directory (default: cwd)
    --dry-run         Show what would be launched without opening terminal
"""

import os
import platform
import shlex
import shutil
import subprocess
import sys
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)


# Harness CLI executables and default launch arguments
_HARNESS_LAUNCH: dict[str, dict] = {
    "gemini": {
        "executables": ["gemini"],
        "launch_args": [],
        "description": "Gemini CLI",
    },
    "codex": {
        "executables": ["codex"],
        "launch_args": [],
        "description": "Codex CLI",
    },
    "opencode": {
        "executables": ["opencode", "opencode-cli"],
        "launch_args": [],
        "description": "OpenCode",
    },
    "cursor": {
        "executables": ["cursor"],
        "launch_args": ["."],
        "description": "Cursor IDE",
    },
    "aider": {
        "executables": ["aider"],
        "launch_args": [],
        "description": "Aider",
    },
    "windsurf": {
        "executables": ["windsurf"],
        "launch_args": ["."],
        "description": "Windsurf IDE",
    },
}


def _find_executable(harness: str) -> str | None:
    """Find the CLI executable for a harness."""
    info = _HARNESS_LAUNCH.get(harness, {})
    for exe in info.get("executables", [harness]):
        path = shutil.which(exe)
        if path:
            return path
    return None


def _build_launch_command(exe: str, harness: str, project_dir: Path) -> list[str]:
    """Build the launch command list for a harness."""
    info = _HARNESS_LAUNCH.get(harness, {})
    extra_args = info.get("launch_args", [])
    cmd = [exe] + extra_args
    return cmd


def _open_new_terminal(cmd: list[str], project_dir: Path) -> bool:
    """Open a new terminal window running cmd in project_dir.

    Supports macOS (Terminal.app / iTerm2) and Linux (gnome-terminal,
    xterm, x-terminal-emulator). Returns True on success.
    """
    system = platform.system()
    cmd_str = " ".join(shlex.quote(c) for c in cmd)
    cwd_str = str(project_dir)

    if system == "Darwin":
        # Try iTerm2 first, fall back to Terminal.app
        iterm_script = f'''
            tell application "iTerm2"
                set newWindow to (create window with default profile)
                tell current session of newWindow
                    write text "cd {shlex.quote(cwd_str)} && {cmd_str}"
                end tell
            end tell
        '''
        terminal_script = f'''
            tell application "Terminal"
                do script "cd {shlex.quote(cwd_str)} && {cmd_str}"
                activate
            end tell
        '''
        # Try iTerm2
        result = subprocess.run(
            ["osascript", "-e", iterm_script],
            capture_output=True,
        )
        if result.returncode == 0:
            return True
        # Fall back to Terminal.app
        result = subprocess.run(
            ["osascript", "-e", terminal_script],
            capture_output=True,
        )
        return result.returncode == 0

    elif system == "Linux":
        # Try common Linux terminal emulators
        for term in ["gnome-terminal", "x-terminal-emulator", "xterm", "konsole", "xfce4-terminal"]:
            term_path = shutil.which(term)
            if not term_path:
                continue

            if term == "gnome-terminal":
                term_cmd = [term_path, "--", "bash", "-c",
                            f"cd {shlex.quote(cwd_str)} && {cmd_str}; exec bash"]
            elif term == "konsole":
                term_cmd = [term_path, "-e", "bash", "-c",
                            f"cd {shlex.quote(cwd_str)} && {cmd_str}; exec bash"]
            else:
                term_cmd = [term_path, "-e",
                            f"bash -c 'cd {shlex.quote(cwd_str)} && {cmd_str}; exec bash'"]

            result = subprocess.Popen(term_cmd)
            return True

    return False


def _run_sync(target: str, project_dir: Path) -> bool:
    """Run /sync for the given target. Returns True on success."""
    # Try to import and run the orchestrator directly
    try:
        from src.orchestrator import Orchestrator
        from src.source_reader import SourceReader

        reader = SourceReader(scope="all", project_dir=project_dir)
        config = reader.read_all()

        orchestrator = Orchestrator(project_dir=project_dir)
        results = orchestrator.sync(config, targets=[target])
        return True
    except Exception as e:
        print(f"Sync error: {e}", file=sys.stderr)
        return False


def hotswap(
    target: str,
    project_dir: Path,
    skip_sync: bool = False,
    dry_run: bool = False,
) -> list[str]:
    """Sync target harness and open it in a new terminal.

    Args:
        target: Target harness to open.
        project_dir: Project root directory.
        skip_sync: If True, skip the sync step.
        dry_run: If True, print what would happen without launching.

    Returns:
        List of status messages for the user.
    """
    messages: list[str] = []
    info = _HARNESS_LAUNCH.get(target)
    if not info:
        return [f"Error: unknown harness '{target}'. Choose from: {', '.join(_HARNESS_LAUNCH)}"]

    exe = _find_executable(target)
    if not exe:
        return [
            f"Error: {info['description']} not found on PATH.",
            f"Install {info['description']} and try again.",
        ]

    # Step 1: Sync
    if not skip_sync:
        messages.append(f"Syncing {target} config from Claude Code...")
        if dry_run:
            messages.append(f"[dry-run] Would sync: harness={target}, project={project_dir}")
        else:
            ok = _run_sync(target, project_dir)
            if ok:
                messages.append(f"✓ Sync complete for {target}")
            else:
                messages.append(f"⚠ Sync encountered errors — launching anyway.")
    else:
        messages.append(f"Skipping sync (--no-sync).")

    # Step 2: Build launch command
    cmd = _build_launch_command(exe, target, project_dir)

    if dry_run:
        messages.append(f"[dry-run] Would launch: {' '.join(cmd)}")
        messages.append(f"[dry-run] Working directory: {project_dir}")
        return messages

    # Step 3: Open new terminal
    messages.append(f"Opening {info['description']} in new terminal window...")
    success = _open_new_terminal(cmd, project_dir)
    if success:
        messages.append(f"✓ {info['description']} launched in new terminal at {project_dir}")
    else:
        # Fallback: print the command for the user to run manually
        cmd_str = " ".join(shlex.quote(c) for c in cmd)
        messages.append(
            f"Could not open terminal automatically. Run manually:\n"
            f"  cd {project_dir} && {cmd_str}"
        )

    return messages


def main() -> None:
    """Entry point for /sync-hotswap command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-hotswap",
        description="Sync and open a harness in a new terminal window",
    )
    parser.add_argument(
        "--to",
        dest="target",
        choices=list(_HARNESS_LAUNCH.keys()),
        required=True,
        help="Target harness to open",
    )
    parser.add_argument(
        "--no-sync",
        dest="skip_sync",
        action="store_true",
        help="Skip sync step; just launch the harness",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be launched without opening terminal",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        help="Project directory (default: cwd)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    results = hotswap(
        target=args.target,
        project_dir=project_dir,
        skip_sync=args.skip_sync,
        dry_run=args.dry_run,
    )
    for line in results:
        print(line)


if __name__ == "__main__":
    main()
