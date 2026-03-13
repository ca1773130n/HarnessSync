from __future__ import annotations

"""
/sync-diff slash command implementation.

Shows a side-by-side comparison of what Claude Code has vs what's currently
written to each target harness. Makes drift visible at a glance.

Answers: "what exactly is different between my Claude Code config and
what Gemini/Codex currently has?"
"""

import os
import sys
import shlex
import argparse
import difflib

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.diff_formatter import compute_semantic_diff


# Map from target name to their primary config file(s) (relative to project root)
_TARGET_PRIMARY_FILES: dict[str, list[str]] = {
    "codex":    ["AGENTS.md"],
    "gemini":   ["GEMINI.md"],
    "opencode": ["AGENTS.md", "opencode.json"],
    "cursor":   [".cursor/rules/harnesssync.mdc"],
    "aider":    ["CONVENTIONS.md"],
    "windsurf": [".windsurfrules"],
}


def _read_file_safe(path: Path) -> str | None:
    """Read file content, return None if missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _unified_diff(source_text: str, target_text: str, source_label: str, target_label: str) -> str:
    """Generate unified diff between source and target text."""
    source_lines = source_text.splitlines(keepends=True)
    target_lines = target_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        source_lines,
        target_lines,
        fromfile=source_label,
        tofile=target_label,
        lineterm="",
    )
    return "".join(diff)


def _side_by_side_diff(source_text: str, target_text: str, width: int = 80) -> str:
    """Generate side-by-side diff between source and target.

    Args:
        source_text: Left-side content (Claude Code source).
        target_text: Right-side content (current target file).
        width: Total terminal width for the combined view.

    Returns:
        Side-by-side diff string.
    """
    col = width // 2 - 2
    source_lines = source_text.splitlines()
    target_lines = target_text.splitlines()

    sm = difflib.SequenceMatcher(None, source_lines, target_lines)
    lines: list[str] = []

    sep = " | "

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for sl, tl in zip(source_lines[i1:i2], target_lines[j1:j2]):
                lines.append(f"  {sl[:col]:<{col}}{sep}{tl[:col]}")
        elif tag == "replace":
            src_block = source_lines[i1:i2]
            tgt_block = target_lines[j1:j2]
            max_len = max(len(src_block), len(tgt_block))
            src_block += [""] * (max_len - len(src_block))
            tgt_block += [""] * (max_len - len(tgt_block))
            for sl, tl in zip(src_block, tgt_block):
                lines.append(f"~ {sl[:col]:<{col}}{sep}{tl[:col]}")
        elif tag == "delete":
            for sl in source_lines[i1:i2]:
                lines.append(f"- {sl[:col]:<{col}}{sep}")
        elif tag == "insert":
            for tl in target_lines[j1:j2]:
                lines.append(f"+ {'':>{col}}{sep}{tl[:col]}")

    return "\n".join(lines)


def _diff_target(
    target: str,
    project_dir: Path,
    source_text: str,
    mode: str = "unified",
    semantic: bool = False,
) -> str:
    """Generate diff output for a specific target.

    Args:
        target: Target harness name.
        project_dir: Project root directory.
        source_text: Claude Code source rules content.
        mode: "unified" | "side-by-side".
        semantic: If True, append a semantic change summary.

    Returns:
        Formatted diff string.
    """
    file_paths = _TARGET_PRIMARY_FILES.get(target, [])
    if not file_paths:
        return f"  [{target}] — no primary config file known\n"

    sections: list[str] = []
    for rel_path in file_paths:
        target_path = project_dir / rel_path
        target_text = _read_file_safe(target_path)

        if target_text is None:
            sections.append(f"  {rel_path}: not found (target not synced yet)\n")
            continue

        if source_text == target_text:
            sections.append(f"  {rel_path}: identical — no drift\n")
            continue

        source_lines = source_text.splitlines()
        target_lines = target_text.splitlines()
        source_set = set(source_lines)
        target_set = set(target_lines)
        added = sum(1 for l in target_lines if l not in source_set)
        removed = sum(1 for l in source_lines if l not in target_set)

        sections.append(f"  {rel_path}: +{added} lines, -{removed} lines differ\n")

        if mode == "unified":
            diff = _unified_diff(source_text, target_text, "claude-source", rel_path)
            if diff:
                sections.append(diff[:4000])
                if len(diff) > 4000:
                    sections.append("\n  ... (diff truncated, use --no-truncate to see full diff)\n")
        elif mode == "side-by-side":
            header_line = f"{'CLAUDE SOURCE':<38} | {'TARGET: ' + rel_path}"
            sections.append(header_line)
            sections.append("-" * 78)
            sections.append(_side_by_side_diff(source_text, target_text))

        if semantic:
            changes = compute_semantic_diff(source_text, target_text)
            if changes:
                sections.append(f"\n  Semantic Changes ({rel_path}):")
                for change in changes:
                    sections.append(f"    {change.format()}")
            else:
                sections.append(f"\n  Semantic Changes ({rel_path}): none")

    return "\n".join(sections)


def main() -> None:
    """Entry point for /sync-diff command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-diff",
        description="Show diff between Claude Code source and current target harness files",
    )
    parser.add_argument(
        "--target",
        type=str,
        default=None,
        help="Diff only this target (codex, gemini, opencode, cursor, aider, windsurf)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["unified", "side-by-side"],
        default="unified",
        help="Diff display mode (default: unified)",
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        default=False,
        help="Show semantic summary of config changes (MCP servers, permissions, rule sections)",
    )
    parser.add_argument("--project-dir", type=str, default=None)
    parser.add_argument("--account", type=str, default=None, help="Account name")

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))

    # Load source rules text
    try:
        from src.source_reader import SourceReader
        cc_home = None
        if args.account:
            try:
                from src.account_manager import AccountManager
                am = AccountManager()
                acc = am.get_account(args.account)
                if acc:
                    cc_home = Path(acc["source"]["path"])
            except Exception:
                pass
        reader = SourceReader(project_dir=project_dir, cc_home=cc_home)
        source_text = reader.get_rules() or ""
    except Exception as e:
        print(f"Error reading source: {e}", file=sys.stderr)
        return

    targets = list(_TARGET_PRIMARY_FILES.keys())
    if args.target:
        if args.target not in _TARGET_PRIMARY_FILES:
            print(f"Unknown target '{args.target}'. Known: {', '.join(targets)}")
            return
        targets = [args.target]

    print("HarnessSync Config Diff")
    print("=" * 60)
    print(f"Source: CLAUDE.md ({len(source_text.splitlines())} lines)")
    print(f"Mode: {args.mode}")
    if args.semantic:
        print("Semantic: enabled")
    print()

    any_drift = False
    for target in targets:
        print(f"--- {target.upper()} ---")
        diff_out = _diff_target(target, project_dir, source_text, mode=args.mode, semantic=args.semantic)
        print(diff_out)
        if "differ" in diff_out or "unified" in diff_out:
            any_drift = True

    if not any_drift:
        print("All targets are in sync with source. No drift detected.")
    else:
        print("\nRun /sync to bring drifted targets back in sync.")


if __name__ == "__main__":
    main()
