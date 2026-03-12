from __future__ import annotations

"""
/sync-ab slash command implementation.

Manages A/B config experiments: assigns two rule variants to different
harnesses, runs the split sync, collects preference annotations, and
surfaces a comparison after the trial period.

Usage:
    /sync-ab setup --name EXPERIMENT [--a TARGETS] [--b TARGETS] [--notes TEXT]
    /sync-ab list
    /sync-ab run --name EXPERIMENT [--dry-run] [--project-dir PATH]
    /sync-ab annotate --name EXPERIMENT --prefer A|B [--reason TEXT]
    /sync-ab compare --name EXPERIMENT
    /sync-ab delete --name EXPERIMENT

Example:
    /sync-ab setup --name ts-strictness --a codex,gemini --b cursor,aider
    /sync-ab run --name ts-strictness
    # ... use the harnesses for a week ...
    /sync-ab annotate --name ts-strictness --prefer A --reason "fewer type errors"
    /sync-ab compare --name ts-strictness
"""

import argparse
import os
import shlex
import sys
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.ab_config_tester import ABConfigTester
from src.orchestrator import SyncOrchestrator
from src.source_reader import SourceReader


def _parse_targets(raw: str) -> list[str]:
    """Parse comma-separated target list."""
    return [t.strip().lower() for t in raw.split(",") if t.strip()]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sync-ab", description="Manage A/B config experiments")
    sub = parser.add_subparsers(dest="subcommand")

    # setup
    setup_p = sub.add_parser("setup", help="Create a new A/B experiment")
    setup_p.add_argument("--name", required=True, help="Experiment name (used in CLAUDE.md markers)")
    setup_p.add_argument("--a", dest="variant_a", default="", help="Comma-separated targets for variant A")
    setup_p.add_argument("--b", dest="variant_b", default="", help="Comma-separated targets for variant B")
    setup_p.add_argument("--notes", default="", help="Optional description")

    # list
    sub.add_parser("list", help="List all experiments")

    # run
    run_p = sub.add_parser("run", help="Apply variant rules to assigned harnesses")
    run_p.add_argument("--name", required=True, help="Experiment name")
    run_p.add_argument("--dry-run", action="store_true", help="Preview without writing")
    run_p.add_argument("--project-dir", default=None, help="Project root (default: cwd)")

    # annotate
    ann_p = sub.add_parser("annotate", help="Record which variant you preferred")
    ann_p.add_argument("--name", required=True, help="Experiment name")
    ann_p.add_argument("--prefer", required=True, choices=["A", "B", "a", "b"], help="Preferred variant")
    ann_p.add_argument("--reason", default="", help="Why this variant felt better")

    # compare
    cmp_p = sub.add_parser("compare", help="Show comparison results")
    cmp_p.add_argument("--name", required=True, help="Experiment name")

    # delete
    del_p = sub.add_parser("delete", help="Delete an experiment")
    del_p.add_argument("--name", required=True, help="Experiment name")

    if not argv:
        parser.print_help()
        sys.exit(0)

    return parser.parse_args(argv)


def main() -> None:
    """Entry point for /sync-ab command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    args = _parse_args(tokens)
    tester = ABConfigTester()

    if args.subcommand == "setup":
        a_targets = _parse_targets(args.variant_a) if args.variant_a else []
        b_targets = _parse_targets(args.variant_b) if args.variant_b else []

        if not a_targets and not b_targets:
            print("Error: Specify at least one target with --a or --b", file=sys.stderr)
            sys.exit(1)

        overlap = set(a_targets) & set(b_targets)
        if overlap:
            print(f"Error: Targets cannot be in both variants: {', '.join(overlap)}", file=sys.stderr)
            sys.exit(1)

        try:
            exp = tester.create(
                name=args.name,
                variant_a_targets=a_targets,
                variant_b_targets=b_targets,
                notes=args.notes,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)

        print(f"A/B experiment '{exp.name}' created.")
        print(f"  Variant A targets: {', '.join(exp.variant_a_targets) or '(none)'}")
        print(f"  Variant B targets: {', '.join(exp.variant_b_targets) or '(none)'}")
        print()
        print("Add variant blocks to CLAUDE.md:")
        print(f"  <!-- @ab:experiment={exp.name}:A -->")
        print("  - Your variant A rule here")
        print("  <!-- @ab:end -->")
        print()
        print(f"  <!-- @ab:experiment={exp.name}:B -->")
        print("  - Your variant B rule here")
        print("  <!-- @ab:end -->")
        print()
        print(f"Run the experiment with: /sync-ab run --name {exp.name}")

    elif args.subcommand == "list":
        print(tester.format_list())

    elif args.subcommand == "run":
        project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()
        exp = tester.load(args.name)
        if exp is None:
            print(f"Error: Experiment '{args.name}' not found. Create it with /sync-ab setup.", file=sys.stderr)
            sys.exit(1)

        # Read CLAUDE.md content
        claude_md = project_dir / "CLAUDE.md"
        if not claude_md.exists():
            print(f"Error: CLAUDE.md not found in {project_dir}", file=sys.stderr)
            sys.exit(1)

        content = claude_md.read_text(encoding="utf-8")
        variants = tester.extract_variant_rules(content, args.name)

        if not variants["A"] and not variants["B"]:
            print(f"Warning: No variant blocks found for experiment '{args.name}' in CLAUDE.md.")
            print(f"Add <!-- @ab:experiment={args.name}:A --> ... <!-- @ab:end --> blocks.")
        else:
            a_preview = variants["A"][:60] + "..." if len(variants["A"]) > 60 else variants["A"]
            b_preview = variants["B"][:60] + "..." if len(variants["B"]) > 60 else variants["B"]
            print(f"Experiment '{args.name}' variant preview:")
            print(f"  A: {a_preview!r}")
            print(f"  B: {b_preview!r}")

        mode = " [DRY RUN]" if args.dry_run else ""
        print(f"\nRunning A/B sync{mode}...")

        all_targets = exp.variant_a_targets + exp.variant_b_targets
        print(f"  Targets in experiment: {', '.join(all_targets)}")
        if args.dry_run:
            for target in exp.variant_a_targets:
                variant_content = tester.apply_variant_to_content(content, args.name, target, exp)
                print(f"  [DRY RUN] {target} would receive variant A rules")
            for target in exp.variant_b_targets:
                variant_content = tester.apply_variant_to_content(content, args.name, target, exp)
                print(f"  [DRY RUN] {target} would receive variant B rules")
        else:
            # Run sync using SyncOrchestrator for each variant group
            for target in exp.variant_a_targets:
                orch = SyncOrchestrator(
                    project_dir=project_dir,
                    dry_run=False,
                    cli_only_targets={target},
                )
                results = orch.sync_all()
                status = "✓" if not results.get("_blocked") else "✗"
                print(f"  {status} {target} synced (variant A)")

            for target in exp.variant_b_targets:
                orch = SyncOrchestrator(
                    project_dir=project_dir,
                    dry_run=False,
                    cli_only_targets={target},
                )
                results = orch.sync_all()
                status = "✓" if not results.get("_blocked") else "✗"
                print(f"  {status} {target} synced (variant B)")

        print(f"\nRecord your preference with: /sync-ab annotate --name {args.name} --prefer A|B")

    elif args.subcommand == "annotate":
        preferred = args.prefer.upper()
        ok = tester.add_annotation(args.name, preferred_variant=preferred, reason=args.reason)
        if not ok:
            print(f"Error: Experiment '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        reason_suffix = f" ({args.reason})" if args.reason else ""
        print(f"Preference recorded: variant {preferred}{reason_suffix}")
        print(f"Run /sync-ab compare --name {args.name} to see results.")

    elif args.subcommand == "compare":
        result = tester.compare(args.name)
        if "error" in result:
            print(f"Error: {result['error']}", file=sys.stderr)
            sys.exit(1)
        print(result["summary"])

    elif args.subcommand == "delete":
        deleted = tester.delete(args.name)
        if deleted:
            print(f"Experiment '{args.name}' deleted.")
        else:
            print(f"Experiment '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)

    else:
        print("Usage: /sync-ab <setup|list|run|annotate|compare|delete> [options]")
        print("Run /sync-ab --help for details.")


if __name__ == "__main__":
    main()
