from __future__ import annotations

"""
/sync-report slash command implementation.

Shows analytics about the current HarnessSync configuration:
- How many rules/skills/agents/commands/MCP servers are synced
- What percentage of the Claude Code config is reflected in each target
- Which sections are systematically losing fidelity (adapted/skipped)
- Historical sync activity summary

Usage:
    /sync-report [--scope SCOPE] [--project-dir PATH] [--json]

Options:
    --scope SCOPE       Sync scope: user | project | all (default: all)
    --project-dir PATH  Project directory (default: cwd)
    --json              Output raw JSON instead of formatted report
"""

import json
import os
import sys
import shlex
import argparse
from datetime import datetime
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.adapters import AdapterRegistry
from src.source_reader import SourceReader
from src.state_manager import StateManager


def _count_source_items(reader: SourceReader) -> dict[str, int]:
    """Count all available source items by section."""
    counts: dict[str, int] = {
        "rules": 0,
        "skills": 0,
        "agents": 0,
        "commands": 0,
        "mcp": 0,
        "settings": 0,
    }

    try:
        rules = reader.get_rules()
        counts["rules"] = len(rules)
    except Exception:
        pass

    try:
        skills = reader.get_skills()
        counts["skills"] = len(skills)
    except Exception:
        pass

    try:
        agents = reader.get_agents()
        counts["agents"] = len(agents)
    except Exception:
        pass

    try:
        commands = reader.get_commands()
        counts["commands"] = len(commands)
    except Exception:
        pass

    try:
        mcp = reader.get_mcp_servers()
        counts["mcp"] = len(mcp)
    except Exception:
        pass

    try:
        settings = reader.get_settings()
        counts["settings"] = 1 if settings else 0
    except Exception:
        pass

    return counts


def _compute_fidelity(target_state: dict, source_counts: dict[str, int]) -> dict:
    """Compute per-section fidelity percentage for a target.

    Returns a dict with section -> {synced, source_total, pct, status}
    where status is "full" | "partial" | "none" | "unknown".
    """
    fidelity: dict[str, dict] = {}

    sync_method = target_state.get("sync_method", {})
    items_synced = target_state.get("items_synced", 0)
    items_skipped = target_state.get("items_skipped", 0)
    items_failed = target_state.get("items_failed", 0)

    for section, source_total in source_counts.items():
        if source_total == 0:
            fidelity[section] = {
                "synced": 0,
                "source_total": 0,
                "pct": 100,
                "status": "full",
                "note": "nothing to sync",
            }
            continue

        section_method = sync_method.get(section, "unknown")
        if section_method == "unknown":
            fidelity[section] = {
                "synced": 0,
                "source_total": source_total,
                "pct": 0,
                "status": "unknown",
                "note": "no sync record",
            }
        elif section_method in ("synced", "adapted"):
            fidelity[section] = {
                "synced": source_total,
                "source_total": source_total,
                "pct": 100 if section_method == "synced" else 85,
                "status": "full" if section_method == "synced" else "partial",
                "note": "translated to target format" if section_method == "adapted" else "",
            }
        elif section_method == "skipped":
            fidelity[section] = {
                "synced": 0,
                "source_total": source_total,
                "pct": 0,
                "status": "none",
                "note": "not supported by target",
            }
        else:
            fidelity[section] = {
                "synced": 0,
                "source_total": source_total,
                "pct": 0,
                "status": "unknown",
                "note": section_method,
            }

    return fidelity


def _format_bar(pct: float, width: int = 20) -> str:
    """Render a simple ASCII progress bar."""
    filled = round(pct / 100 * width)
    return "[" + "█" * filled + "░" * (width - filled) + f"] {pct:3.0f}%"


def _format_report(report: dict) -> str:
    """Format the analytics report as human-readable text."""
    lines: list[str] = []
    lines.append("HarnessSync Analytics Report")
    lines.append("=" * 60)

    generated = report.get("generated_at", "unknown")
    lines.append(f"Generated: {generated}")
    lines.append("")

    # Source summary
    source = report["source"]
    lines.append("Source Config (Claude Code)")
    lines.append("-" * 40)
    total_source = sum(source.values())
    for section, count in source.items():
        lines.append(f"  {section:<12} {count:>4} item(s)")
    lines.append(f"  {'TOTAL':<12} {total_source:>4} item(s)")
    lines.append("")

    # Per-target breakdown
    targets = report.get("targets", {})
    if not targets:
        lines.append("No sync history found. Run /sync first.")
        return "\n".join(lines)

    lines.append("Per-Target Fidelity")
    lines.append("-" * 40)
    for target_name, target_data in targets.items():
        last_sync = target_data.get("last_sync", "never")
        status = target_data.get("status", "unknown")
        overall_pct = target_data.get("overall_pct", 0)

        lines.append(f"\n  {target_name.upper()}")
        lines.append(f"  Last sync: {last_sync}  Status: {status}")
        lines.append(f"  Overall:   {_format_bar(overall_pct)}")

        fidelity = target_data.get("fidelity", {})
        for section, fd in fidelity.items():
            pct = fd["pct"]
            note = fd.get("note", "")
            bar = _format_bar(pct, width=10)
            note_str = f"  ({note})" if note else ""
            lines.append(f"    {section:<10} {bar}{note_str}")

    # Sections with systematic fidelity loss
    lines.append("")
    lines.append("Sections with Fidelity Loss")
    lines.append("-" * 40)
    problem_sections = report.get("problem_sections", [])
    if problem_sections:
        for ps in problem_sections:
            lines.append(f"  {ps['section']:<12} avg {ps['avg_pct']:3.0f}%  "
                         f"({ps['targets_affected']} target(s) affected)")
        lines.append("")
        lines.append("  Tip: Use --only to skip sections that don't translate well,")
        lines.append("  or check adapter docs for format-specific workarounds.")
    else:
        lines.append("  None detected — all sections syncing at high fidelity.")

    lines.append("")
    return "\n".join(lines)


def _build_report(project_dir: Path, scope: str) -> dict:
    """Build the analytics report data structure."""
    reader = SourceReader(scope=scope, project_dir=project_dir)
    source_counts = _count_source_items(reader)

    state_manager = StateManager()
    all_status = state_manager.get_all_status()
    targets_state = all_status.get("targets", {})

    registered_targets = AdapterRegistry.list_targets()

    targets_report: dict[str, dict] = {}
    for target_name in registered_targets:
        target_state = targets_state.get(target_name)
        if not target_state:
            continue

        fidelity = _compute_fidelity(target_state, source_counts)

        # Compute overall percentage (weighted average across non-zero sections)
        pct_values = [
            fd["pct"] for fd in fidelity.values()
            if fd["source_total"] > 0
        ]
        overall_pct = sum(pct_values) / len(pct_values) if pct_values else 100.0

        targets_report[target_name] = {
            "last_sync": target_state.get("last_sync", "never"),
            "status": target_state.get("status", "unknown"),
            "items_synced": target_state.get("items_synced", 0),
            "items_skipped": target_state.get("items_skipped", 0),
            "items_failed": target_state.get("items_failed", 0),
            "fidelity": fidelity,
            "overall_pct": round(overall_pct, 1),
        }

    # Find sections with systematic fidelity loss (avg < 80% across targets)
    section_pcts: dict[str, list[float]] = {s: [] for s in source_counts}
    for td in targets_report.values():
        for section, fd in td["fidelity"].items():
            if fd["source_total"] > 0 and fd["status"] != "unknown":
                section_pcts[section].append(fd["pct"])

    problem_sections = []
    for section, pcts in section_pcts.items():
        if pcts:
            avg = sum(pcts) / len(pcts)
            affected = sum(1 for p in pcts if p < 80)
            if avg < 80:
                problem_sections.append({
                    "section": section,
                    "avg_pct": round(avg, 1),
                    "targets_affected": affected,
                })
    problem_sections.sort(key=lambda x: x["avg_pct"])

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source_counts,
        "targets": targets_report,
        "problem_sections": problem_sections,
    }


def main():
    """Entry point for /sync-report command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []

    # Handle shell-quoted args from Claude Code command invocation
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-report",
        description="Show HarnessSync analytics: coverage, fidelity, and problem sections.",
    )
    parser.add_argument("--scope", default="all", choices=["user", "project", "all"])
    parser.add_argument("--project-dir", default=None, help="Project directory (default: cwd)")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Output raw JSON")

    args = parser.parse_args(raw_args)

    project_dir = Path(args.project_dir).resolve() if args.project_dir else Path.cwd()

    try:
        report = _build_report(project_dir, args.scope)
    except Exception as e:
        print(f"Error building report: {e}", file=sys.stderr)
        sys.exit(1)

    if args.output_json:
        print(json.dumps(report, indent=2))
    else:
        print(_format_report(report))


if __name__ == "__main__":
    main()
