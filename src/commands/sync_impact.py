from __future__ import annotations

"""
/sync-impact slash command implementation.

Before running /sync, analyze pending config changes and predict the behavioral
impact on each target harness. Shows what rules will conflict with harness
built-in preferences, what MCP servers are being added/removed, and what
permission changes are coming.

Usage:
    /sync-impact                   Predict impact of pending changes
    /sync-impact --target cursor   Only show impact for a specific target
    /sync-impact --detailed        Show all info items, not just warnings
    /sync-impact --json            Output raw JSON
"""

import json
import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path


def main() -> None:
    """Entry point for /sync-impact command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-impact",
        description="Predict behavioral impact of pending config changes before sync",
    )
    parser.add_argument(
        "--target", "-t",
        default=None,
        help="Filter predictions to a specific target harness",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Include informational items, not just warnings",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_out",
        help="Output raw JSON instead of formatted text",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project root directory (default: current directory)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()

    try:
        from src.source_reader import SourceReader
        from src.sync_impact_predictor import SyncImpactPredictor

        reader = SourceReader(project_dir=project_dir)
        current_data = reader.discover_all()

        # Load last-synced state snapshot if one exists on disk
        previous_data: dict = {}
        snapshot_path = project_dir / ".harnesssync-last-source.json"
        if snapshot_path.exists():
            try:
                import json as _json
                previous_data = _json.loads(snapshot_path.read_text(encoding="utf-8"))
            except Exception:
                previous_data = {}

        predictor = SyncImpactPredictor(project_dir=project_dir)
        report = predictor.predict(current_data, previous_data)

    except ImportError as e:
        print(f"[sync-impact] Error loading modules: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[sync-impact] Error reading config: {e}", file=sys.stderr)
        sys.exit(1)

    # Filter by target if requested
    items = report.items
    if args.target:
        items = [
            item for item in items
            if item.target in (args.target, "all")
        ]

    # Filter by severity
    if not args.detailed:
        items = [item for item in items if item.severity in ("warning", "error")]

    if args.json_out:
        output = {
            "project_dir": str(project_dir),
            "target_filter": args.target,
            "items": [
                {
                    "severity": item.severity,
                    "target": item.target,
                    "category": item.category,
                    "message": item.message,
                }
                for item in items
            ],
        }
        print(json.dumps(output, indent=2))
        return

    # Formatted text output
    print("Sync Impact Prediction")
    print("=" * 60)
    if args.target:
        print(f"Target filter: {args.target}")
    print()

    if not items:
        if args.detailed:
            print("No impact items detected — sync looks clean.")
        else:
            print("No warnings detected. Run with --detailed for all info items.")
        return

    severity_order = {"error": 0, "warning": 1, "info": 2, "note": 3}
    items = sorted(items, key=lambda i: severity_order.get(i.severity, 99))

    icons = {"error": "[ERR]", "warning": "[WARN]", "info": "[INFO]", "note": "[NOTE]"}
    current_severity = None
    for item in items:
        if item.severity != current_severity:
            current_severity = item.severity
            label = item.severity.upper() + "S"
            print(f"--- {label} ---")
        icon = icons.get(item.severity, "[?]")
        target_label = f"[{item.target}]" if item.target != "all" else "[ALL]"
        print(f"  {icon} {target_label} {item.message}")

    warnings = sum(1 for i in items if i.severity in ("error", "warning"))
    print()
    print(f"{warnings} warning(s) found. Review before running /sync.")


if __name__ == "__main__":
    main()
