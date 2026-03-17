from __future__ import annotations

"""
/sync-policy slash command — Sync Policy Enforcement (item 25).

Displays the active policy, validates the current config against it, or
initialises a sample policy file.

Usage:
    /sync-policy                    Show active policy and run a check
    /sync-policy --show             Print the active policy summary only
    /sync-policy --check            Run policy check against current config
    /sync-policy --target codex     Check a specific harness only
    /sync-policy --init             Write a sample .harnesssync-policy.json
    /sync-policy --json             Output check results as JSON
    /sync-policy --project-dir PATH Project directory (default: cwd)
"""

import json
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.sync_policy import PolicyEnforcer, _PROJECT_POLICY_NAME
from src.source_reader import SourceReader
from src.adapters import AdapterRegistry

_SAMPLE_POLICY: dict = {
    "version": 1,
    "description": "HarnessSync org-level sync policy",
    "must_sync": ["rules"],
    "must_not_sync": [],
    "protected_sections": [],
    "require_review_for": ["mcp", "settings"],
    "target_overrides": {
        "aider": {
            "must_not_sync": ["mcp"]
        }
    }
}


def _run_check(
    project_dir: Path,
    target: str | None,
    as_json: bool,
) -> int:
    """Run policy check and print results. Returns exit code (0 = ok, 1 = blocked)."""
    reader = SourceReader(project_dir=project_dir)
    source_data = reader.discover_all()

    enforcer = PolicyEnforcer(project_dir=project_dir)

    if not enforcer.has_policy:
        msg = (
            "No policy file found.\n"
            f"  Run '/sync-policy --init' to create {_PROJECT_POLICY_NAME}."
        )
        if as_json:
            print(json.dumps({"ok": True, "message": msg}))
        else:
            print(msg)
        return 0

    if target:
        targets = [target]
    else:
        targets = AdapterRegistry.list_targets()

    result = enforcer.check_all(source_data, targets=targets)

    if as_json:
        out = {
            "ok": not result.any_blocked,
            "policy_file": result.policy_file,
            "total_errors": result.total_errors,
            "total_warnings": result.total_warnings,
            "reports": [
                {
                    "target": r.target,
                    "blocked": r.blocked,
                    "violations": [
                        {
                            "severity": v.severity,
                            "section": v.section,
                            "message": v.message,
                        }
                        for v in r.violations
                    ],
                    "warnings": r.warnings,
                }
                for r in result.reports
            ],
        }
        print(json.dumps(out, indent=2))
    else:
        print(result.format())

    return 1 if result.any_blocked else 0


def main() -> None:
    """Entry point for /sync-policy command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-policy",
        description="Show and enforce org-level sync policy",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Print active policy summary only (no config check)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run policy check against current config (default when no flag given)",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        metavar="HARNESS",
        help="Check a specific harness target only",
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help=f"Write a sample {_PROJECT_POLICY_NAME} to the project directory",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output results as machine-readable JSON",
    )
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()

    # --init: write sample policy
    if args.init:
        policy_path = project_dir / _PROJECT_POLICY_NAME
        if policy_path.exists():
            print(f"Policy file already exists: {policy_path}")
            print("Remove it first or edit it directly.")
            return
        policy_path.write_text(
            json.dumps(_SAMPLE_POLICY, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Sample policy written to: {policy_path}")
        print("Edit it to match your team's requirements, then run /sync-policy --check.")
        return

    enforcer = PolicyEnforcer(project_dir=project_dir)

    # --show: print policy summary only
    if args.show:
        print(enforcer.format_policy_summary())
        return

    # Default: show policy summary then run check
    if enforcer.has_policy:
        print(enforcer.format_policy_summary())
        print()

    exit_code = _run_check(project_dir, args.target, args.as_json)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
