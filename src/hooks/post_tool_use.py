"""
PostToolUse hook for auto-sync on config file edits.

Reads JSON from stdin (tool_name, tool_input), checks if the edited
file is a Claude Code config file, and triggers sync if debounce/lock
conditions are met. Always exits 0 to never block Claude Code.
"""

import json
import os
import sys
from pathlib import Path

# Resolve project root for imports
PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

CONFIG_PATTERNS = [
    "CLAUDE.md",
    ".mcp.json",
    "/skills/",
    "/agents/",
    "/commands/",
    "settings.json",
    "settings.local.json",
]


def is_config_file(file_path: str) -> bool:
    """Check if file path matches a Claude Code config pattern.

    Args:
        file_path: Absolute or relative file path

    Returns:
        True if the file is a config file that should trigger sync
    """
    if not file_path:
        return False
    return any(pattern in file_path for pattern in CONFIG_PATTERNS)


def main():
    """PostToolUse hook entry point."""
    try:
        # Read hook event data from stdin
        try:
            hook_data = json.load(sys.stdin)
        except (json.JSONDecodeError, ValueError):
            sys.exit(0)  # Invalid input, allow action

        # Extract file path
        file_path = hook_data.get("tool_input", {}).get("file_path", "")

        # Check if edited file is a config file
        if not is_config_file(file_path):
            sys.exit(0)  # Not a config file, skip

        print(f"HarnessSync: config change detected: {file_path}", file=sys.stderr)

        # Import sync components (deferred to avoid loading on non-config edits)
        from src.lock import sync_lock, should_debounce, LOCK_FILE_DEFAULT
        from src.state_manager import StateManager
        from src.orchestrator import SyncOrchestrator

        # Debounce check
        state_manager = StateManager()
        if should_debounce(state_manager):
            print("HarnessSync: sync skipped (debounce)", file=sys.stderr)
            sys.exit(0)

        # Lock and sync
        try:
            with sync_lock(LOCK_FILE_DEFAULT):
                project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
                orchestrator = SyncOrchestrator(
                    project_dir=project_dir,
                    scope="all",
                    dry_run=False
                )
                results = orchestrator.sync_all()
                target_count = len(results)
                print(f"HarnessSync: synced {target_count} targets", file=sys.stderr)

        except BlockingIOError:
            print("HarnessSync: sync in progress, skipping", file=sys.stderr)

    except Exception as e:
        print(f"HarnessSync: sync error: {e}", file=sys.stderr)

    # Always exit 0 - never block Claude Code tool execution
    sys.exit(0)


if __name__ == "__main__":
    main()
