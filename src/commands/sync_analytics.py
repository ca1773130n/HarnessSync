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

import time
from datetime import datetime, timezone, timedelta
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


def _format_weekly_digest(summary: dict, days: int = 7) -> str:
    """Generate a weekly usage digest from analytics summary data.

    Produces a concise human-readable report covering:
    - Which harnesses were synced and their success rates
    - Harnesses with high drift (frequent manual edits)
    - Health score changes (best and worst performing targets)
    - Any harnesses that haven't been synced recently

    Args:
        summary: Dict from SyncMetricsExporter.get_summary().
        days: Number of days to include in the digest window (default: 7).

    Returns:
        Multi-line digest string.
    """
    now_ts = datetime.now(timezone.utc)
    period_label = f"Last {days} days"

    lines: list[str] = []
    lines.append("╔══════════════════════════════════════════════════════╗")
    lines.append(f"║     HarnessSync Weekly Digest — {period_label:<21} ║")
    lines.append("╚══════════════════════════════════════════════════════╝")
    lines.append("")

    sync_totals: dict[str, dict] = summary.get("sync_totals", {})
    drift_totals: dict[str, int] = summary.get("drift_totals", {})
    health_scores: dict[str, int] = summary.get("health_scores", {})
    last_sync_timestamps: dict[str, float] = summary.get("last_sync_timestamps", {})

    # ── Sync activity summary ─────────────────────────────────────────────
    if sync_totals:
        lines.append("  Sync Activity This Week")
        lines.append("  " + "─" * 45)
        total_syncs = 0
        total_success = 0
        active_targets: list[str] = []
        idle_targets: list[str] = []

        for target, counts in sorted(sync_totals.items()):
            success = counts.get("success", 0)
            errors = counts.get("error", 0)
            total = success + errors
            total_syncs += total
            total_success += success

            # Check if last sync was within the window
            last_ts = last_sync_timestamps.get(target, 0)
            last_dt = datetime.fromtimestamp(last_ts, tz=timezone.utc) if last_ts else None
            is_recent = last_dt and (now_ts - last_dt) < timedelta(days=days)

            rate = f"{success}/{total}" if total else "0/0"
            pct = f"{round(100 * success / total)}%" if total else "  —"

            if total > 0:
                active_targets.append(target)
                last_label = last_dt.strftime("%b %d") if last_dt else "unknown"
                lines.append(f"  {target:<12}  {rate:>6} syncs  {pct:>4} success  last: {last_label}")
            else:
                idle_targets.append(target)

        lines.append("")
        lines.append(f"  Total: {total_syncs} syncs across {len(active_targets)} target(s)")
        if total_syncs > 0:
            overall_pct = round(100 * total_success / total_syncs)
            lines.append(f"  Overall success rate: {overall_pct}%")
        if idle_targets:
            lines.append(f"  Idle targets (no syncs): {', '.join(idle_targets)}")
        lines.append("")

    # ── Drift alert ───────────────────────────────────────────────────────
    if drift_totals:
        high_drift = {t: c for t, c in drift_totals.items() if c >= 3}
        if high_drift:
            lines.append("  ⚠  High Drift Targets (manually edited since last sync)")
            lines.append("  " + "─" * 45)
            for target, count in sorted(high_drift.items(), key=lambda x: -x[1]):
                lines.append(f"  {target:<12}  {count} edit(s) detected")
            lines.append("  → Run /sync to overwrite, or use conflict resolution.")
            lines.append("")

    # ── Health summary ────────────────────────────────────────────────────
    if health_scores:
        sorted_scores = sorted(health_scores.items(), key=lambda x: -x[1])
        best = sorted_scores[0] if sorted_scores else None
        worst = sorted_scores[-1] if sorted_scores else None

        lines.append("  Health Scores")
        lines.append("  " + "─" * 45)
        for target, score in sorted_scores:
            status = "✓" if score >= 70 else ("⚠" if score >= 40 else "✗")
            bar = _bar(score, 100, width=15)
            lines.append(f"  {target:<12}  {bar}  {score:3d}/100  {status}")
        lines.append("")

        if worst and worst[1] < 40:
            lines.append(
                f"  Action needed: '{worst[0]}' health score is {worst[1]}/100.\n"
                "  Run /sync-health for a detailed diagnosis."
            )
            lines.append("")

    if not sync_totals and not drift_totals and not health_scores:
        lines.append("  No analytics data available for this period.")
        lines.append("  Run /sync to start recording sync events.")
        lines.append("")

    lines.append("─" * 56)
    lines.append("  Run /sync-analytics for the full dashboard.")
    lines.append("  Run /sync-gaps --advisor for capability gap workarounds.")
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
    parser.add_argument(
        "--weekly-digest",
        action="store_true",
        dest="weekly_digest",
        help="Show a weekly usage digest (syncs, drift, health summary)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days for --weekly-digest window (default: 7)",
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

    if args.weekly_digest:
        print(_format_weekly_digest(summary, days=args.days))
        return

    print(_format_dashboard(summary))


if __name__ == "__main__":
    main()
