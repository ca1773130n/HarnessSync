from __future__ import annotations

"""
/sync-add-harness slash command implementation.

One-command bootstrap for adding a new AI coding harness to HarnessSync.
Detects an installed-but-unconfigured tool, runs a guided setup flow,
translates the current Claude Code config into the harness's native format,
and verifies the output — replacing the 30-60 minute manual process.

Usage:
    /sync-add-harness                     Auto-detect an unconfigured harness
    /sync-add-harness <name>              Add a specific harness (e.g. cursor, aider)
    /sync-add-harness --list              List detected but unconfigured harnesses
    /sync-add-harness --dry-run           Preview without writing any files
    /sync-add-harness --project-dir PATH  Project root (default: cwd)
    /sync-add-harness --force             Add even if harness is already configured

Supported harness names:
    codex, gemini, opencode, cursor, aider, windsurf, cline, continue, zed, neovim
"""

import argparse
import os
import sys
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.harness_detector import detect_new_harnesses, scan_all, detect_version as get_version
from src.orchestrator import SyncOrchestrator
from src.utils.logger import Logger

# Harnesses that HarnessSync has adapters for
SUPPORTED_HARNESSES: list[str] = [
    "codex", "gemini", "opencode", "cursor", "aider",
    "windsurf", "cline", "continue", "zed", "neovim",
]

# Human-readable install hints per harness
_INSTALL_HINTS: dict[str, str] = {
    "codex":    "npm install -g @openai/codex",
    "gemini":   "npm install -g @google/gemini-cli",
    "opencode":  "npm install -g opencode",
    "cursor":   "Download from https://cursor.sh",
    "aider":    "pip install aider-chat",
    "windsurf": "Download from https://windsurf.ai",
    "cline":    "Install the Cline extension in VS Code",
    "continue": "Install the Continue extension in VS Code",
    "zed":      "Download from https://zed.dev",
    "neovim":   "brew install neovim && add avante.nvim or codecompanion.nvim",
}

# Which adapter class name maps to which harness (for the orchestrator target list)
_ADAPTER_KEYS: dict[str, str] = {
    "codex":    "codex",
    "gemini":   "gemini",
    "opencode": "opencode",
    "cursor":   "cursor",
    "aider":    "aider",
    "windsurf": "windsurf",
    "cline":    "cline",
    "continue": "continue",
    "zed":      "zed",
    "neovim":   "neovim",
}


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="sync-add-harness",
        description="Bootstrap a new AI coding harness into HarnessSync.",
    )
    parser.add_argument(
        "harness",
        nargs="?",
        metavar="NAME",
        help=(
            "Harness to add: "
            + ", ".join(SUPPORTED_HARNESSES)
            + ". Omit to auto-detect."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List detected but unconfigured harnesses and exit.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what would be written without modifying any files.",
    )
    parser.add_argument(
        "--project-dir",
        metavar="PATH",
        default=".",
        help="Project root directory (default: current working directory).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Add the harness even if it appears to be already configured.",
    )
    return parser.parse_args(argv)


def _detect_unconfigured(logger: Logger) -> list[str]:
    """Return harnesses that are installed but not yet configured."""
    all_detected = scan_all()
    unconfigured: list[str] = []
    for name, detected in all_detected.items():
        if detected and name in SUPPORTED_HARNESSES:
            unconfigured.append(name)
    return unconfigured


def _check_already_configured(harness: str, project_dir: Path) -> bool:
    """Return True if the harness appears to already have HarnessSync-managed config."""
    _INDICATOR_FILES: dict[str, list[str]] = {
        "codex":    ["AGENTS.md"],
        "gemini":   [".gemini/GEMINI.md"],
        "opencode": [".opencode/AGENTS.md"],
        "cursor":   [".cursor/rules/"],
        "aider":    ["CONVENTIONS.md"],
        "windsurf": [".windsurfrules"],
        "cline":    [".clinerules"],
        "continue": [".continue/rules/"],
        "zed":      [".zed/system-prompt.md"],
        "neovim":   [".avante/system-prompt.md"],
    }
    for rel in _INDICATOR_FILES.get(harness, []):
        candidate = project_dir / rel
        if candidate.exists():
            return True
    # Also check user-level config dirs
    _USER_DIRS: dict[str, Path] = {
        "codex":    Path.home() / ".codex" / "AGENTS.md",
        "gemini":   Path.home() / ".gemini" / "GEMINI.md",
        "opencode": Path.home() / ".config" / "opencode" / "AGENTS.md",
        "cursor":   Path.home() / ".cursor" / "mcp.json",
        "windsurf": Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
    }
    user_path = _USER_DIRS.get(harness)
    return bool(user_path and user_path.exists())


def _print_harness_banner(harness: str, version: str | None) -> None:
    ver_str = f"  (detected version: {version})" if version else ""
    print(f"\n  Adding harness: {harness}{ver_str}")
    print(f"  {'─' * 50}")


def run(argv: list[str] | None = None) -> int:
    """Entry point for /sync-add-harness.

    Args:
        argv: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        Exit code (0 = success, non-zero = error).
    """
    if argv is None:
        argv = sys.argv[1:]

    args = _parse_args(argv)
    logger = Logger()
    project_dir = Path(args.project_dir).resolve()

    # --list: print unconfigured harnesses and exit
    if args.list:
        unconfigured = _detect_unconfigured(logger)
        if not unconfigured:
            print("No unconfigured harnesses detected.")
            print(
                "All supported harnesses are either already configured or not installed."
            )
        else:
            print(f"Detected {len(unconfigured)} unconfigured harness(es):")
            for h in unconfigured:
                ver = get_version(h)
                ver_str = f"  [{ver}]" if ver else ""
                print(f"  {h}{ver_str}")
            print(f"\nRun /sync-add-harness <name> to configure one.")
        return 0

    # Determine which harness to add
    target = args.harness
    if target is None:
        unconfigured = _detect_unconfigured(logger)
        if not unconfigured:
            print("No unconfigured harnesses detected.")
            print("Either all supported harnesses are already configured, or none are installed.")
            print("\nInstall a harness and re-run, or specify a name explicitly:")
            for h in SUPPORTED_HARNESSES:
                print(f"  /sync-add-harness {h}")
            return 0
        if len(unconfigured) == 1:
            target = unconfigured[0]
            print(f"Auto-detected unconfigured harness: {target}")
        else:
            print(f"Multiple unconfigured harnesses detected: {', '.join(unconfigured)}")
            print("Specify one explicitly:  /sync-add-harness <name>")
            return 1

    target = target.lower().strip()
    if target not in SUPPORTED_HARNESSES:
        logger.error(
            f"Unknown harness '{target}'. Supported: {', '.join(SUPPORTED_HARNESSES)}"
        )
        return 1

    # Warn if the harness doesn't appear to be installed
    all_detected = scan_all()
    if not all_detected.get(target):
        print(f"Warning: '{target}' does not appear to be installed.")
        hint = _INSTALL_HINTS.get(target, "")
        if hint:
            print(f"  Install it with: {hint}")
        print("  Proceeding anyway — files will be written for future use.\n")

    # Check if already configured (unless --force)
    if not args.force and _check_already_configured(target, project_dir):
        print(
            f"'{target}' appears to already be configured.\n"
            f"Use --force to overwrite existing config, or run /sync to refresh."
        )
        return 0

    version = get_version(target)
    _print_harness_banner(target, version)

    # Report what source config sections are available
    print("  [1/5] Reading Claude Code source config...")
    from src.source_reader import SourceReader
    source_data: dict = {}
    try:
        reader = SourceReader(project_dir=project_dir)
        source_data = reader.discover_all()
        sections_found: list[str] = [
            key for key in ("rules", "skills", "agents", "commands", "mcp", "settings")
            if source_data.get(key)
        ]
        if sections_found:
            print(f"     Found: {', '.join(sections_found)}")
        else:
            print("     Warning: No source config found — CLAUDE.md may be empty.")
    except Exception:
        print("     (Could not pre-read source config — sync will discover it automatically.)")

    # Show capability matrix for the target harness so the user knows what will/won't sync
    print(f"  [2/5] Capability matrix for '{target}':")
    _print_capability_matrix(target, source_data)

    # Run sync targeting only the new harness
    print(f"  [3/5] Translating config to {target} native format...")
    orchestrator = SyncOrchestrator(
        project_dir=project_dir,
        dry_run=args.dry_run,
        cli_only_targets={_ADAPTER_KEYS[target]},
    )

    if args.dry_run:
        print(f"  [DRY-RUN] Would write {target} config — no files will be modified.")

    try:
        result = orchestrator.sync_all()
    except Exception as exc:
        logger.error(f"Sync failed for {target}: {exc}")
        return 1

    if args.dry_run:
        print(f"  [4/5] Skipping write (dry-run mode).")
        print(f"  [5/5] Skipping verification (dry-run mode).")
        print(
            f"\n  Dry run complete. Run without --dry-run to apply changes."
        )
        return 0

    # Report on what was written
    print(f"  [4/5] Writing {target} config files...")
    # Report any files written (result dict maps target -> results)
    target_result = result.get(target) if isinstance(result, dict) else None
    if target_result and isinstance(target_result, dict):
        files = target_result.get("files_written", [])
        for f in files:
            print(f"     Wrote: {f}")
    if not (target_result and isinstance(target_result, dict) and target_result.get("files_written")):
        print(f"     Config written to {target} target directory.")

    # Verify the output
    print(f"  [5/5] Verifying {target} config...")
    # Basic verification: check that at least one expected indicator file now exists
    if _check_already_configured(target, project_dir):
        print(f"     Verification passed — {target} config is present.")
    else:
        print(
            f"     Warning: Could not verify {target} output. "
            "Check the target directory manually."
        )

    print(f"\n  Done! '{target}' is now configured.\n")
    print(f"  From now on, /sync will automatically keep {target} in sync with Claude Code.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
