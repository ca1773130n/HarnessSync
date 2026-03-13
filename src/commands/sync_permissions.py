from __future__ import annotations

"""
/sync-permissions slash command implementation.

Visualizes which Claude Code tool permissions and approval-mode settings
can be translated to each target harness, which are approximated, and
which are silently dropped with no equivalent.

Helps users understand the security implications of syncing their permission
model across harnesses before running /sync.

Usage:
    /sync-permissions                   — show full boundary report
    /sync-permissions --target codex    — show only one harness
    /sync-permissions --gaps-only       — show only dropped/comment-only settings
    /sync-permissions --json            — output as JSON
"""

import json
import os
import sys
import shlex
import argparse

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path

from src.adapters import AdapterRegistry
from src.source_reader import SourceReader
from src.permission_translator import PermissionTranslator, PermissionTranslationReport


# Fidelity icons for terminal output
_FIDELITY_ICON = {
    "native":       "✓",
    "approximated": "~",
    "comment_only": "ℹ",
    "dropped":      "✗",
}

_FIDELITY_LABEL = {
    "native":       "native translation",
    "approximated": "approximated (some loss)",
    "comment_only": "comment only (intent preserved, not enforced)",
    "dropped":      "DROPPED — no equivalent in this harness",
}


def _format_boundary_report(
    report: PermissionTranslationReport,
    targets: list[str],
    gaps_only: bool = False,
) -> str:
    """Format a human-readable permission boundary report.

    Args:
        report: Translation results from PermissionTranslator.translate().
        targets: Ordered list of harness names.
        gaps_only: If True, only show dropped/comment-only translations.

    Returns:
        Multi-line formatted string.
    """
    lines: list[str] = []
    lines.append("HarnessSync Permission Boundary Visualizer")
    lines.append("=" * 60)
    lines.append("")
    lines.append("Shows how Claude Code permission settings translate to each")
    lines.append("target harness. Dropped settings are NOT enforced after sync.")
    lines.append("")

    any_output = False
    for target in targets:
        trans_list = report.for_target(target)
        if not trans_list:
            continue
        if gaps_only:
            trans_list = [t for t in trans_list if t.fidelity in ("dropped", "comment_only")]
        if not trans_list:
            continue

        any_output = True
        lines.append(f"[{target.upper()}]")
        for t in trans_list:
            icon = _FIDELITY_ICON.get(t.fidelity, "?")
            label = _FIDELITY_LABEL.get(t.fidelity, t.fidelity)
            lines.append(f"  {icon} {t.setting}")
            lines.append(f"    Status:  {label}")
            if t.translated_key:
                lines.append(f"    Maps to: {t.translated_key}")
            if t.comment:
                lines.append(f"    Note:    {t.comment}")
            if t.dropped_items:
                dropped_str = ", ".join(t.dropped_items[:5])
                if len(t.dropped_items) > 5:
                    dropped_str += f" (+{len(t.dropped_items) - 5} more)"
                lines.append(f"    Dropped: {dropped_str}")
        lines.append("")

    if not any_output:
        if gaps_only:
            lines.append("No permission gaps detected — all settings translate natively.")
        else:
            lines.append(
                "No permission settings found in Claude Code settings.\n"
                "Add allowedTools, deniedTools, or approvalMode to settings.json."
            )

    lines.append("Legend:")
    lines.append("  ✓  native       — Direct equivalent exists in target harness")
    lines.append("  ~  approximated — Partial mapping with possible fidelity loss")
    lines.append("  ℹ  comment only — Preserved as a comment; not actively enforced")
    lines.append("  ✗  dropped      — No equivalent; permission silently not applied")
    lines.append("")
    lines.append("Tip: Review dropped permissions before syncing to avoid security")
    lines.append("     surprises when switching between harnesses.")

    return "\n".join(lines)


def main() -> None:
    """Entry point for /sync-permissions command."""
    args_string = os.environ.get("ARGUMENTS", " ".join(sys.argv[1:]))
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-permissions",
        description="Visualize permission boundary translation across harnesses",
    )
    parser.add_argument(
        "--target", "-t",
        metavar="TARGET",
        help="Show only a specific target harness",
    )
    parser.add_argument(
        "--gaps-only",
        action="store_true",
        help="Show only dropped or comment-only (unenforced) settings",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Output results as JSON",
    )
    parser.add_argument(
        "--scope",
        choices=["user", "project", "all"],
        default="all",
        help="Config scope to read (default: all)",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    reader = SourceReader(scope=args.scope, project_dir=project_dir)

    # Load settings to extract permission config
    settings: dict = {}
    try:
        settings = reader.get_settings() or {}
    except Exception:
        pass

    if not settings:
        # Try reading settings.json directly from Claude home
        cc_home = Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))
        settings_path = cc_home / "settings.json"
        if settings_path.exists():
            try:
                settings = json.loads(settings_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    # Determine targets
    all_targets = AdapterRegistry.list_targets()
    if args.target:
        if args.target not in all_targets:
            print(
                f"Unknown target '{args.target}'. "
                f"Available: {', '.join(all_targets)}",
                file=sys.stderr,
            )
            sys.exit(1)
        targets = [args.target]
    else:
        targets = all_targets

    # Run translation
    translator = PermissionTranslator()
    report = translator.translate(settings, targets)

    if args.output_json:
        output = {
            "targets": targets,
            "settings_found": bool(settings),
            "translations": [
                {
                    "target": t.target,
                    "setting": t.setting,
                    "translated_key": t.translated_key,
                    "fidelity": t.fidelity,
                    "comment": t.comment,
                    "dropped_items": t.dropped_items,
                }
                for t in report.translations
            ],
        }
        print(json.dumps(output, indent=2))
        return

    print(_format_boundary_report(report, targets, gaps_only=args.gaps_only))

    # Summary line: count gaps
    gap_count = sum(
        1 for t in report.translations
        if t.fidelity in ("dropped", "comment_only")
    )
    if gap_count and not args.gaps_only:
        print(f"\n{gap_count} permission gap(s) found. Use --gaps-only to focus on them.")


if __name__ == "__main__":
    main()
