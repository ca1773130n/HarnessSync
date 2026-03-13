from __future__ import annotations

"""
/sync-analytics slash command implementation.

Displays a sync analytics dashboard: sync frequency, drift rate per harness,
most-changed config sections, and conflict frequency over time.

Gives team leads visibility into config health and helps identify which
harnesses are most out of sync in practice.
"""

import os
import sys
import shlex
import argparse
import json

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.sync_metrics import SyncMetricsExporter


def _bar(value: int, max_value: int, width: int = 20) -> str:
    """Render a simple ASCII progress bar."""
    if max_value == 0:
        filled = 0
    else:
        filled = round(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


def _format_dashboard(summary: dict) -> str:
    """Render a human-readable analytics dashboard from a metrics summary dict."""
    lines: list[str] = []

    lines.append("╔══════════════════════════════════════════════════════╗")
    lines.append("║         HarnessSync Analytics Dashboard              ║")
    lines.append("╚══════════════════════════════════════════════════════╝")
    lines.append("")

    # ── Sync Totals ────────────────────────────────────────────────────
    sync_totals: dict[str, dict] = summary.get("sync_totals", {})
    if sync_totals:
        lines.append("  Sync Operations")
        lines.append("  " + "─" * 50)
        max_syncs = max(
            (d.get("success", 0) + d.get("error", 0)) for d in sync_totals.values()
        ) if sync_totals else 1
        for target, counts in sorted(sync_totals.items()):
            total = counts.get("success", 0) + counts.get("error", 0)
            success = counts.get("success", 0)
            rate = f"{success}/{total}" if total else "0/0"
            bar = _bar(total, max(max_syncs, 1))
            lines.append(f"  {target:<12} {bar}  {rate} syncs")
        lines.append("")

    # ── Drift Events ───────────────────────────────────────────────────
    drift_totals: dict[str, int] = summary.get("drift_totals", {})
    if drift_totals:
        lines.append("  Drift Events (external config modifications detected)")
        lines.append("  " + "─" * 50)
        max_drift = max(drift_totals.values()) if drift_totals else 1
        for target, count in sorted(drift_totals.items(), key=lambda x: -x[1]):
            bar = _bar(count, max(max_drift, 1))
            lines.append(f"  {target:<12} {bar}  {count} event(s)")
        lines.append("")

    # ── Health Scores ──────────────────────────────────────────────────
    health_scores: dict[str, int] = summary.get("health_scores", {})
    if health_scores:
        lines.append("  Harness Health Scores  (0 = unhealthy, 100 = perfect)")
        lines.append("  " + "─" * 50)
        for target, score in sorted(health_scores.items()):
            bar = _bar(score, 100)
            status = "✓" if score >= 70 else ("⚠" if score >= 40 else "✗")
            lines.append(f"  {target:<12} {bar}  {score:3d}/100  {status}")
        lines.append("")

    if not sync_totals and not drift_totals and not health_scores:
        lines.append("  No analytics data yet.")
        lines.append("  Run /sync to record your first sync events.")
        lines.append("")

    return "\n".join(lines)


def main() -> None:
    """Entry point for /sync-analytics command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-analytics",
        description="Display sync analytics dashboard",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output raw metrics as JSON",
    )
    parser.add_argument(
        "--prometheus",
        action="store_true",
        help="Output Prometheus text-format metrics",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear all accumulated analytics data",
    )
    args = parser.parse_args(tokens)

    exporter = SyncMetricsExporter(backend="prometheus", persist=True)

    if args.reset:
        exporter.reset()
        print("Analytics data cleared.")
        return

    if args.prometheus:
        print(exporter.render())
        return

    summary = exporter.get_summary()

    if args.output_json:
        print(json.dumps(summary, indent=2))
        return

    print(_format_dashboard(summary))


if __name__ == "__main__":
    main()
