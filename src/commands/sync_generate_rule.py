from __future__ import annotations

"""
/sync-generate-rule slash command implementation.

Accepts a plain-English description of a desired AI assistant behavior
and generates the correct CLAUDE.md rule block — ready to review and
append to your config, then sync to all harnesses.

Usage:
    /sync-generate-rule "always run tests before committing"
    /sync-generate-rule "never modify migration files directly" --dry-run
    /sync-generate-rule "use TypeScript strict mode" --append
    /sync-generate-rule --list-categories

The rule generation is fully offline and deterministic (no LLM required).
Use --show-harness-notes to see how the rule translates to each harness.
"""

import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.nl_config_generator import NLConfigGenerator
import src.nl_config_generator as _nlcg_module
from src.utils.logger import Logger


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync-generate-rule",
        description=(
            "Generate CLAUDE.md rule blocks from plain-English descriptions. "
            "Rules are formatted for HarnessSync compatibility and include "
            "harness-specific annotations where behaviour differs."
        ),
    )
    parser.add_argument(
        "description",
        nargs="?",
        default="",
        help="Plain-English description of the desired rule (e.g. 'always run tests before committing')",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        default=False,
        help="Append generated rule block to CLAUDE.md (prompts for confirmation).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Preview the generated rule without writing anything.",
    )
    parser.add_argument(
        "--show-harness-notes",
        action="store_true",
        default=False,
        help="Show per-harness translation notes alongside the generated rule.",
    )
    parser.add_argument(
        "--list-categories",
        action="store_true",
        default=False,
        help="List all available behavior categories and example phrases.",
    )
    parser.add_argument(
        "--project-dir",
        metavar="DIR",
        default="",
        help="Project directory containing CLAUDE.md (default: current directory).",
    )
    return parser


def _list_categories(gen: NLConfigGenerator) -> None:
    """Print the available behavior categories with example phrases."""
    print("Available Behavior Categories")
    print("=" * 60)
    seen: set[str] = set()
    patterns = getattr(_nlcg_module, "_PATTERNS", [])
    all_rules = [rule for _pat, rule in patterns]
    for rule in all_rules:
        if rule.category not in seen:
            seen.add(rule.category)
            print(f"\n  [{rule.category}]")
            print(f"    Example: {rule.title}")
            snippet = rule.rule_text.strip().splitlines()[0][:70]
            print(f"    Rule:    {snippet}{'...' if len(rule.rule_text) > 70 else ''}")
    print()
    print(f"Total: {len(seen)} categorie(s)  |  {len(all_rules)} rule template(s)")
    print()
    print("Tip: combine multiple phrases in one description:")
    print("  /sync-generate-rule \"avoid console.log and use parameterized SQL\"")


def _format_with_harness_notes(result) -> str:
    """Format result with per-harness translation annotations."""
    lines: list[str] = []
    lines.append(result.claude_md_block)

    all_notes: dict[str, list[str]] = {}
    for rule in result.matched_rules:
        for harness, note in rule.harness_notes.items():
            all_notes.setdefault(harness, []).append(note)

    if all_notes:
        lines.append("")
        lines.append("# Harness-specific translation notes:")
        for harness in sorted(all_notes):
            for note in all_notes[harness]:
                lines.append(f"#   [{harness}] {note}")

    return "\n".join(lines)


def _append_to_claude_md(project_dir: Path, block: str, dry_run: bool) -> bool:
    """Append a rule block to CLAUDE.md.

    Returns True if the block was written (or would be in dry-run mode).
    """
    claude_md = project_dir / "CLAUDE.md"
    if not claude_md.exists():
        # Try common parent directories
        for candidate in [project_dir.parent, Path.cwd()]:
            candidate_md = candidate / "CLAUDE.md"
            if candidate_md.exists():
                claude_md = candidate_md
                break

    if dry_run:
        print(f"\n[dry-run] Would append to: {claude_md}")
        return True

    if not claude_md.parent.exists():
        print(f"Error: directory does not exist: {claude_md.parent}", file=sys.stderr)
        return False

    # Prompt for confirmation
    try:
        answer = input(f"\nAppend rule to {claude_md}? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return False

    if answer not in ("y", "yes"):
        print("Aborted.")
        return False

    try:
        existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
        separator = "\n\n" if existing and not existing.endswith("\n\n") else ""
        claude_md.write_text(existing + separator + block + "\n", encoding="utf-8")
        print(f"Rule appended to {claude_md}")
        print("Run /sync to propagate changes to all harnesses.")
        return True
    except OSError as e:
        print(f"Error writing {claude_md}: {e}", file=sys.stderr)
        return False


def main() -> None:
    """Entry point for /sync-generate-rule command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = _build_parser()
    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    gen = NLConfigGenerator()

    if args.list_categories:
        _list_categories(gen)
        return

    description = args.description.strip()
    if not description:
        parser.print_help()
        print("\nExample: /sync-generate-rule \"always run tests before committing\"")
        return

    # Generate the rule
    result = gen.generate(description)

    # Print generation summary
    print(result.format_summary())

    if not result.matched_rules:
        print("\nNo rule templates matched your description.")
        print("Try /sync-generate-rule --list-categories to see available patterns.")
        print("Or be more specific: e.g. 'avoid console.log' instead of 'better logging'.")
        return

    print()
    print("Generated Rule Block")
    print("=" * 60)

    if args.show_harness_notes and any(r.harness_notes for r in result.matched_rules):
        block_text = _format_with_harness_notes(result)
    else:
        block_text = result.claude_md_block

    print(block_text)

    if result.unmatched_phrases:
        print()
        print("Tip: Run with --show-harness-notes to see per-harness translation details.")

    if args.append:
        _append_to_claude_md(project_dir, block_text, dry_run=args.dry_run)
    elif not args.dry_run:
        print()
        print("To add this rule to CLAUDE.md, re-run with --append:")
        print(f'  /sync-generate-rule "{description}" --append')
        print()
        print("To preview harness-specific translation differences:")
        print(f'  /sync-generate-rule "{description}" --show-harness-notes')


if __name__ == "__main__":
    main()
