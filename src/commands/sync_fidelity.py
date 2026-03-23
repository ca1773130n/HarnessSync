from __future__ import annotations

"""
/sync-fidelity slash command implementation.

Analyzes current Claude Code config and reports — without syncing — exactly
what will be preserved, approximated, or lost per target harness.

Usage:
    /sync-fidelity                  # report for all harnesses
    /sync-fidelity --target codex   # report for one harness
    /sync-fidelity --json           # machine-readable JSON output
"""

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.commands.sync_matrix import CAPABILITY_MATRIX, NATIVE, ADAPTED, PARTIAL, DROPPED, TARGETS
from src.source_reader import SourceReader


@dataclass
class FidelityReport:
    """Per-harness fidelity analysis results."""
    target: str
    preserved: list = field(default_factory=list)
    approximated: list = field(default_factory=list)
    lost: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "target": self.target,
            "preserved": self.preserved,
            "approximated": self.approximated,
            "lost": self.lost,
        }


def _has_section(source_data: dict, section: str) -> bool:
    """Return True if the source config actually has content for this section."""
    mapping = {
        "rules": lambda d: bool(d.get("rules") or d.get("claude_md")),
        "skills": lambda d: bool(d.get("skills")),
        "agents": lambda d: bool(d.get("agents")),
        "commands": lambda d: bool(d.get("commands")),
        "mcp_servers": lambda d: bool(d.get("mcp_servers")),
        "settings": lambda d: bool(d.get("settings")),
        "sync_tags": lambda d: bool(d.get("rules") or d.get("claude_md")),
        "harness_overrides": lambda d: True,
    }
    checker = mapping.get(section)
    if checker is None:
        return True
    return checker(source_data)


def build_fidelity_report(target: str, source_data: dict) -> FidelityReport:
    """Analyze capability matrix for target and return a FidelityReport."""
    report = FidelityReport(target=target)

    for row in CAPABILITY_MATRIX:
        section = row["section"]
        if not _has_section(source_data, section):
            continue

        cell = row.get(target)
        if cell is None:
            continue

        level, note = cell
        label = f"{section} — {note}"
        if level == NATIVE:
            report.preserved.append(label)
        elif level in (ADAPTED, PARTIAL):
            report.approximated.append(label)
        elif level == DROPPED:
            report.lost.append(label)

    return report


def format_fidelity_report(report: FidelityReport) -> str:
    """Render a FidelityReport as human-readable text."""
    lines = [f"  Fidelity report for: {report.target}", "  " + "-" * 50]

    if report.preserved:
        lines.append(f"  + Preserved ({len(report.preserved)}):")
        for item in report.preserved:
            lines.append(f"      {item}")

    if report.approximated:
        lines.append(f"  ~ Approximated ({len(report.approximated)}):")
        for item in report.approximated:
            lines.append(f"      {item}")

    if report.lost:
        lines.append(f"  - Lost ({len(report.lost)}):")
        for item in report.lost:
            lines.append(f"      {item}")

    if not report.preserved and not report.approximated and not report.lost:
        lines.append("  (no applicable config sections detected)")

    return "\n".join(lines)


def main() -> None:
    """Entry point for /sync-fidelity command."""
    import argparse
    import shlex

    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-fidelity",
        description="Show what config will be preserved, approximated, or lost per harness",
    )
    parser.add_argument("--target", type=str, default=None,
                        help="Restrict report to a single harness target")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Output as machine-readable JSON")

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    try:
        reader = SourceReader(scope="all", project_dir=project_dir)
        source_data = reader.discover_all()
    except Exception:
        source_data = {}

    targets = [args.target] if args.target else list(TARGETS)
    valid_targets = set(TARGETS)
    targets = [t for t in targets if t in valid_targets]

    if not targets:
        print(f"Unknown target '{args.target}'. Valid targets: {', '.join(TARGETS)}", file=sys.stderr)
        sys.exit(1)

    reports = [build_fidelity_report(t, source_data) for t in targets]

    if args.json_output:
        print(json.dumps([r.as_dict() for r in reports], indent=2))
        return

    print("Sync Translation Fidelity Report")
    print("=" * 54)
    print("(No files will be written — analysis only)\n")

    for report in reports:
        print(format_fidelity_report(report))
        print()


if __name__ == "__main__":
    main()
