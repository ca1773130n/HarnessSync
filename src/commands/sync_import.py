from __future__ import annotations

"""
/sync-import slash command — Pull config FROM a target harness INTO Claude Code.

HarnessSync normally pushes Claude Code config out to other harnesses. This
command reverses the flow: it reads an existing harness config (Gemini, Codex,
Cursor, etc.) and converts it to Claude Code format, staging the result under
``.claude/imported/`` for review before merging.

Each adapter exposes an ``import_to_claude(target_path) -> dict`` method that
does the actual conversion. The command writes staged files and asks for
confirmation before merging them into the live Claude Code config.

Usage:
    /sync-import gemini                     # import from Gemini (auto-detect path)
    /sync-import codex --path ~/myproject   # import from specific path
    /sync-import gemini --merge             # import and merge without staging
    /sync-import gemini --dry-run           # preview what would be imported
"""

import json
import os
import sys
import shlex
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.adapters import AdapterRegistry
from src.utils.paths import default_cc_home, ensure_dir, write_json_atomic


# Default target config paths keyed by target name
_DEFAULT_TARGET_PATHS: dict[str, str] = {
    "gemini": ".",
    "codex": ".",
    "cursor": ".",
    "aider": ".",
    "windsurf": ".",
    "opencode": ".",
    "cline": ".",
    "zed": str(Path.home() / ".config" / "zed"),
    "neovim": str(Path.home() / ".config" / "nvim"),
    "continue": str(Path.home() / ".continue"),
    "vscode": ".",
}


def _stage_imported(imported: dict, staging_dir: Path, target_name: str) -> list[Path]:
    """Write imported data to the staging area. Returns list of written paths."""
    written: list[Path] = []
    ensure_dir(staging_dir)

    rules = imported.get("rules", "")
    if rules and isinstance(rules, str) and rules.strip():
        rules_path = staging_dir / "CLAUDE.md"
        rules_path.write_text(rules, encoding="utf-8")
        written.append(rules_path)

    settings = imported.get("settings")
    if isinstance(settings, dict) and settings:
        settings_path = staging_dir / "settings.json"
        write_json_atomic(settings_path, settings)
        written.append(settings_path)

    mcp = imported.get("mcp")
    if isinstance(mcp, dict) and mcp:
        mcp_path = staging_dir / ".mcp.json"
        write_json_atomic(mcp_path, {"mcpServers": mcp})
        written.append(mcp_path)

    skills = imported.get("skills")
    if isinstance(skills, dict):
        for skill_name, skill_content in skills.items():
            if isinstance(skill_content, str) and skill_content.strip():
                skill_dir = staging_dir / "skills" / skill_name
                ensure_dir(skill_dir)
                skill_file = skill_dir / "SKILL.md"
                skill_file.write_text(skill_content, encoding="utf-8")
                written.append(skill_file)

    agents = imported.get("agents")
    if isinstance(agents, dict):
        agents_dir = staging_dir / "agents"
        ensure_dir(agents_dir)
        for agent_name, agent_content in agents.items():
            if isinstance(agent_content, str) and agent_content.strip():
                agent_file = agents_dir / f"{agent_name}.md"
                agent_file.write_text(agent_content, encoding="utf-8")
                written.append(agent_file)

    commands = imported.get("commands")
    if isinstance(commands, dict):
        commands_dir = staging_dir / "commands"
        ensure_dir(commands_dir)
        for cmd_name, cmd_content in commands.items():
            if isinstance(cmd_content, str) and cmd_content.strip():
                cmd_file = commands_dir / f"{cmd_name}.md"
                cmd_file.write_text(cmd_content, encoding="utf-8")
                written.append(cmd_file)

    return written


def _merge_staged(staging_dir: Path, project_dir: Path, cc_home: Path) -> list[str]:
    """Merge staged files into live Claude Code config. Returns list of actions."""
    import shutil
    actions: list[str] = []

    staged_rules = staging_dir / "CLAUDE.md"
    if staged_rules.is_file():
        live_claude = project_dir / "CLAUDE.md"
        imported_text = staged_rules.read_text(encoding="utf-8")
        if live_claude.is_file():
            existing = live_claude.read_text(encoding="utf-8")
            merged = existing.rstrip("\n") + "\n\n" + imported_text
            live_claude.write_text(merged, encoding="utf-8")
            actions.append(f"Appended imported rules to {live_claude}")
        else:
            live_claude.write_text(imported_text, encoding="utf-8")
            actions.append(f"Created {live_claude} from imported rules")

    staged_settings = staging_dir / "settings.json"
    if staged_settings.is_file():
        live_settings = project_dir / ".claude" / "settings.json"
        try:
            imported_settings = json.loads(staged_settings.read_text(encoding="utf-8"))
            existing_settings: dict = {}
            if live_settings.is_file():
                try:
                    existing_settings = json.loads(live_settings.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    pass
            merged_settings = {**existing_settings, **imported_settings}
            ensure_dir(live_settings.parent)
            write_json_atomic(live_settings, merged_settings)
            actions.append(f"Merged settings into {live_settings}")
        except (json.JSONDecodeError, OSError) as e:
            actions.append(f"Warning: could not merge settings: {e}")

    staged_skills = staging_dir / "skills"
    if staged_skills.is_dir():
        live_skills = cc_home / "skills"
        ensure_dir(live_skills)
        for skill_dir in staged_skills.iterdir():
            if skill_dir.is_dir():
                dest = live_skills / skill_dir.name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(skill_dir, dest)
                actions.append(f"Imported skill '{skill_dir.name}' to {dest}")

    staged_agents = staging_dir / "agents"
    if staged_agents.is_dir():
        live_agents = cc_home / "agents"
        ensure_dir(live_agents)
        for agent_file in staged_agents.iterdir():
            if agent_file.is_file():
                dest = live_agents / agent_file.name
                shutil.copy2(agent_file, dest)
                actions.append(f"Imported agent '{agent_file.stem}' to {dest}")

    return actions


def main() -> None:
    """Entry point for /sync-import command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-import",
        description="Import config FROM a target harness INTO Claude Code format.",
    )
    parser.add_argument(
        "target",
        help="Target harness to import from (e.g. gemini, codex, cursor)",
    )
    parser.add_argument(
        "--path",
        default=None,
        dest="target_path",
        help="Path to target harness config root (default: auto-detect for current project)",
    )
    parser.add_argument(
        "--project-dir",
        default=None,
        help="Project directory (default: current directory)",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="After staging, immediately merge into live Claude Code config without prompting",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Preview what would be imported without writing any files",
    )

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir or os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    cc_home = default_cc_home()

    if args.target_path:
        target_path = Path(args.target_path).expanduser().resolve()
    else:
        default_rel = _DEFAULT_TARGET_PATHS.get(args.target.lower(), ".")
        target_path = (project_dir / default_rel).resolve()

    try:
        adapter = AdapterRegistry.get_adapter(args.target.lower(), project_dir)
    except Exception:
        print(f"Error: unknown target '{args.target}'.", file=sys.stderr)
        print(f"Known targets: {', '.join(sorted(AdapterRegistry.list_targets()))}")
        sys.exit(1)

    print(f"Importing from {args.target} at {target_path} ...")

    try:
        imported = adapter.import_to_claude(target_path)
    except Exception as e:
        print(f"Error during import: {e}", file=sys.stderr)
        sys.exit(1)

    if not imported:
        print(f"Nothing to import — the {args.target} adapter returned no data.")
        print("(The adapter may not yet implement import_to_claude() for this harness.)")
        return

    summary_parts = []
    if imported.get("rules"):
        summary_parts.append("rules")
    if imported.get("settings"):
        summary_parts.append(f"{len(imported['settings'])} setting(s)")
    if imported.get("mcp"):
        summary_parts.append(f"{len(imported['mcp'])} MCP server(s)")
    if imported.get("skills"):
        summary_parts.append(f"{len(imported['skills'])} skill(s)")
    if imported.get("agents"):
        summary_parts.append(f"{len(imported['agents'])} agent(s)")
    if imported.get("commands"):
        summary_parts.append(f"{len(imported['commands'])} command(s)")

    print(f"Found: {', '.join(summary_parts) or 'nothing'}")

    if args.dry_run:
        print("[dry-run] No files written.")
        if imported.get("rules"):
            print("\n--- Imported rules preview ---")
            preview = imported["rules"][:500]
            print(preview)
            if len(imported["rules"]) > 500:
                print(f"  ... ({len(imported['rules'])} chars total)")
        return

    staging_dir = project_dir / ".claude" / "imported" / args.target.lower()
    written = _stage_imported(imported, staging_dir, args.target.lower())

    print(f"\nStaged {len(written)} file(s) under {staging_dir}:")
    for p in written:
        try:
            print(f"  {p.relative_to(project_dir)}")
        except ValueError:
            print(f"  {p}")

    if args.merge:
        print("\nMerging into live Claude Code config ...")
        actions = _merge_staged(staging_dir, project_dir, cc_home)
        for action in actions:
            print(f"  {action}")
        print("\nMerge complete. Run /sync to push changes to all targets.")
    else:
        print(f"\nReview staged files, then run:")
        print(f"  /sync-import {args.target} --merge   # merge staged files into live config")
        print(f"Or to discard: rm -rf \"{staging_dir}\"")


if __name__ == "__main__":
    main()
