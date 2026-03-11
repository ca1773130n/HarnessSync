from __future__ import annotations

"""
/sync-lint slash command implementation.

Validates the source Claude Code config before sync, reporting issues
without modifying any files.
"""

import os
import sys
import shlex

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.config_linter import ConfigLinter
from src.source_reader import SourceReader


def main() -> None:
    """Entry point for /sync-lint command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    # Simple flag: --scope
    scope = "all"
    if "--scope" in tokens:
        idx = tokens.index("--scope")
        if idx + 1 < len(tokens):
            scope = tokens[idx + 1]

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    print("HarnessSync Config Lint")
    print("=" * 50)

    try:
        reader = SourceReader(scope=scope, project_dir=project_dir)
        source_data = reader.discover_all()
    except Exception as e:
        print(f"Error reading config: {e}", file=sys.stderr)
        sys.exit(1)

    linter = ConfigLinter()
    issues = linter.lint(source_data, project_dir)

    if not issues:
        print("No issues found. Config looks good!")
        sys.exit(0)

    print(f"Found {len(issues)} issue(s):\n")
    for i, issue in enumerate(issues, 1):
        print(f"  {i}. {issue}")

    print()
    print(f"Fix these issues before syncing to prevent unexpected behavior.")
    sys.exit(1)


if __name__ == "__main__":
    main()
