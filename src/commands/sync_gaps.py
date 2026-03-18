from __future__ import annotations

"""
/sync-gaps slash command — Cross-Harness Feature Request Tracker (item 24)
and Harness Feature Watchlist (item 19).

When HarnessSync can't sync a feature because the target lacks support, log it
as a tracked gap with an optional link to the upstream issue tracker. Over time
this turns user frustration into an actionable log of what's missing and where
to upvote/follow.

Watchlist: subscribe to (feature, harness) pairs and get notified when support
level changes — so you find out when Aider adds MCP support instead of
discovering it by accident.

Usage:
    /sync-gaps                              # list all open gaps
    /sync-gaps --target codex               # gaps for a specific harness
    /sync-gaps log codex skills "Skills dropped — no equivalent" [--url URL]
    /sync-gaps resolve codex skills         # mark a gap resolved
    /sync-gaps --include-resolved           # show resolved gaps too
    /sync-gaps --auto                       # auto-detect gaps from last sync state
    /sync-gaps --json                       # output as JSON

    # Watchlist (item 19)
    /sync-gaps --watchlist                  # show current watchlist with support levels
    /sync-gaps --watchlist-add mcp aider    # watch for aider to add MCP support
    /sync-gaps --watchlist-remove mcp aider # stop watching
    /sync-gaps --watchlist-check            # check for support level changes
"""

import os
import sys
import shlex
import argparse
import json
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.compatibility_reporter import GapTracker

# Known upstream issue tracker URLs for common harnesses.
# Users can override by passing --url explicitly.
_DEFAULT_ISSUE_URLS: dict[str, str] = {
    "codex":    "https://github.com/openai/codex/issues",
    "gemini":   "https://github.com/google-gemini/gemini-cli/issues",
    "opencode": "https://github.com/sst/opencode/issues",
    "cursor":   "https://forum.cursor.com",
    "aider":    "https://github.com/paul-gauthier/aider/issues",
    "windsurf": "https://windsurf.com/changelog",
}

# Descriptions for well-known feature gaps — auto-populated by --auto mode.
_KNOWN_GAPS: list[tuple[str, str, str]] = [
    ("codex",    "agents",   "Codex has no native agent concept — agents are folded into skills."),
    ("codex",    "commands", "Codex command support is approximated via skills with 'cmd-' prefix."),
    ("codex",    "mcp",      "Codex supports stdio MCP only; SSE/HTTP transports are not forwarded."),
    ("aider",    "agents",   "Aider has no agent concept — agent files are dropped."),
    ("aider",    "commands", "Aider has no slash-command system — commands are dropped."),
    ("cursor",   "commands", "Cursor .mdc files have no $ARGUMENTS substitution — dynamic args are lost."),
    ("windsurf", "commands", "Windsurf workflows have no $ARGUMENTS substitution — dynamic args are lost."),
    ("gemini",   "settings", "Gemini tool permission model differs; some settings have no equivalent."),
    ("opencode", "mcp",      "OpenCode supports local/remote MCP only; tunnel/SSE proxies not supported."),
]


def _auto_detect_gaps(tracker: GapTracker) -> int:
    """Log all well-known gaps that haven't been logged yet. Returns count added."""
    added = 0
    for target, feature, description in _KNOWN_GAPS:
        existing = tracker.get_gaps(target=target)
        already_logged = any(g.feature == feature for g in existing)
        if not already_logged:
            url = _DEFAULT_ISSUE_URLS.get(target, "")
            tracker.log_gap(target=target, feature=feature,
                            description=description, upstream_url=url)
            added += 1
    return added


def main() -> None:
    """Entry point for /sync-gaps command."""
    raw_args = sys.argv[1:] if len(sys.argv) > 1 else []
    if len(raw_args) == 1 and " " in raw_args[0]:
        raw_args = shlex.split(raw_args[0])

    parser = argparse.ArgumentParser(
        prog="sync-gaps",
        description="Track and view cross-harness capability gaps.",
    )
    subparsers = parser.add_subparsers(dest="subcommand")

    # log subcommand
    log_p = subparsers.add_parser("log", help="Log a new capability gap")
    log_p.add_argument("target", help="Target harness (e.g. codex)")
    log_p.add_argument("feature", help="Feature category (e.g. skills, mcp, agents)")
    log_p.add_argument("description", help="Human-readable description of the gap")
    log_p.add_argument("--url", default="", help="Upstream issue tracker URL")

    # resolve subcommand
    res_p = subparsers.add_parser("resolve", help="Mark a gap as resolved")
    res_p.add_argument("target", help="Target harness")
    res_p.add_argument("feature", help="Feature category")

    # Top-level list flags
    parser.add_argument("--target", default=None,
                        help="Filter by harness name")
    parser.add_argument("--include-resolved", action="store_true",
                        help="Include resolved gaps in output")
    parser.add_argument("--auto", action="store_true",
                        help="Auto-detect and log well-known gaps")
    parser.add_argument("--json", dest="output_json", action="store_true",
                        help="Output as JSON")

    # Watchlist flags (item 19)
    parser.add_argument(
        "--watchlist",
        action="store_true",
        help="Show the current feature watchlist with live support levels",
    )
    parser.add_argument(
        "--watchlist-add",
        nargs=2,
        metavar=("FEATURE", "HARNESS"),
        dest="watchlist_add",
        help="Add a (feature, harness) pair to the watchlist. E.g. --watchlist-add mcp aider",
    )
    parser.add_argument(
        "--watchlist-remove",
        nargs=2,
        metavar=("FEATURE", "HARNESS"),
        dest="watchlist_remove",
        help="Remove a (feature, harness) pair from the watchlist.",
    )
    parser.add_argument(
        "--watchlist-check",
        action="store_true",
        dest="watchlist_check",
        help=(
            "Check current support levels against stored levels and report changes. "
            "Updates stored levels so next check only reports new changes."
        ),
    )

    args = parser.parse_args(raw_args)
    tracker = GapTracker()

    # ── Watchlist commands (item 19) ──────────────────────────────────────────
    if getattr(args, "watchlist_add", None):
        from src.feature_watchlist import FeatureWatchlist
        feature, harness = args.watchlist_add
        wl = FeatureWatchlist()
        ok, msg = wl.add(feature, harness)
        print(("OK: " if ok else "Error: ") + msg)
        return

    if getattr(args, "watchlist_remove", None):
        from src.feature_watchlist import FeatureWatchlist
        feature, harness = args.watchlist_remove
        wl = FeatureWatchlist()
        ok, msg = wl.remove(feature, harness)
        print(("OK: " if ok else "Error: ") + msg)
        return

    if getattr(args, "watchlist", False):
        from src.feature_watchlist import FeatureWatchlist
        wl = FeatureWatchlist()
        print(wl.format_status())
        return

    if getattr(args, "watchlist_check", False):
        from src.feature_watchlist import FeatureWatchlist
        wl = FeatureWatchlist()
        hits = wl.check(update=True)
        if hits:
            print(wl.format_hits(hits))
        else:
            watches = wl.list_watches()
            if watches:
                print(f"No changes detected across {len(watches)} watched feature/harness pair(s).")
            else:
                print("Watchlist is empty. Add entries with --watchlist-add <feature> <harness>.")
        return
    # ── End watchlist ─────────────────────────────────────────────────────────

    if args.subcommand == "log":
        gap = tracker.log_gap(
            target=args.target.lower(),
            feature=args.feature.lower(),
            description=args.description,
            upstream_url=args.url,
        )
        print(f"Logged gap: [{gap.target}] {gap.feature}")
        if gap.upstream_url:
            print(f"  Issue tracker: {gap.upstream_url}")
        return

    if args.subcommand == "resolve":
        found = tracker.resolve_gap(args.target.lower(), args.feature.lower())
        if found:
            print(f"Resolved gap: [{args.target}] {args.feature}")
        else:
            print(f"No open gap found for [{args.target}] {args.feature}", file=sys.stderr)
            sys.exit(1)
        return

    if args.auto:
        added = _auto_detect_gaps(tracker)
        if added:
            print(f"Auto-logged {added} well-known capability gap(s).")
        else:
            print("All well-known gaps already logged.")

    # Default: list gaps
    include_resolved = getattr(args, "include_resolved", False)
    target_filter = getattr(args, "target", None)
    gaps = tracker.get_gaps(target=target_filter, include_resolved=include_resolved)

    if args.output_json:
        print(json.dumps([g.to_dict() for g in gaps], indent=2))
        return

    if not gaps:
        label = f" for {target_filter}" if target_filter else ""
        print(f"No open capability gaps tracked{label}.")
        print("  Run with --auto to seed well-known gaps, or use:")
        print("  sync-gaps log <harness> <feature> '<description>' [--url URL]")
        return

    print(tracker.format_gap_report(
        target=target_filter,
        include_resolved=include_resolved,
    ))
    print()
    print("  Use 'sync-gaps resolve <harness> <feature>' to mark a gap resolved.")
    print("  Use 'sync-gaps --auto' to seed all well-known gaps.")


if __name__ == "__main__":
    main()
