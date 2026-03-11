from __future__ import annotations

"""
SessionStart hook — passive drift check at session startup.

Checks if any HarnessSync targets are out of sync relative to the last recorded
sync state and prints a one-line summary if drift is detected. Always exits 0
to never interrupt the session.

Designed to be lightweight: no subprocess spawning, no network calls.
"""

import os
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))


def main() -> None:
    """SessionStart hook entry point."""
    try:
        from src.startup_check import format_startup_message

        project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
        msg = format_startup_message(project_dir=project_dir)
        if msg:
            print(msg, file=sys.stderr)

    except Exception:
        pass  # Never block the session on startup check failure

    sys.exit(0)


if __name__ == "__main__":
    main()
