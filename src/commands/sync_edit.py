from __future__ import annotations

"""
/sync-edit slash command — natural language config editing via Claude API.

Interprets plain-English instructions to modify Claude Code config, then
immediately syncs to all registered harnesses.

Examples:
    /sync-edit "add a rule that always use TypeScript for new files"
    /sync-edit "remove MCP server named postgres"
    /sync-edit "set approval mode to suggest for all targets"
    /sync-edit "add rule: never commit secrets to git" --dry-run
    /sync-edit "move the security rules section before the style rules"

The command:
1. Reads current CLAUDE.md + settings
2. Sends both + the user instruction to Claude API
3. Receives a structured edit plan (JSON)
4. Applies the edit to CLAUDE.md or settings.json
5. Runs sync to propagate changes to all harnesses
6. Reports what changed

The Claude API call uses a compact schema to get reliable structured output:
    {
        "action": "add_rule" | "remove_rule" | "modify_rule" |
                  "add_mcp" | "remove_mcp" | "set_setting",
        "target_file": "CLAUDE.md" | "settings.json",
        "content": "<new text or config>",
        "placement": "append" | "prepend" | "replace",
        "find_text": "<text to find for replace ops>",
        "explanation": "<brief human-readable description of change>"
    }
"""

import json
import os
import re
import shlex
import sys
import urllib.error
import urllib.request
import argparse
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.utils.logger import Logger


# ──────────────────────────────────────────────────────────────────────────────
# Claude API integration
# ──────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are HarnessSync's config editor. Your job is to interpret natural language
editing instructions and produce a precise, minimal edit to Claude Code config.

You output ONLY valid JSON matching this schema — no prose, no markdown:
{
  "action": one of ["add_rule","remove_rule","modify_rule","add_mcp","remove_mcp","set_setting"],
  "target_file": one of ["CLAUDE.md", "settings.json"],
  "content": "the new text or JSON to insert/replace with",
  "placement": one of ["append","prepend","replace","after_section"],
  "find_text": "exact text to find when action is modify_rule or remove_rule (omit otherwise)",
  "section": "CLAUDE.md section heading to place content under (optional)",
  "explanation": "one sentence describing what changed and why"
}

Rules:
- Keep changes minimal — only touch what the instruction asks about
- For add_rule: content is the new rule text (Markdown bullet or paragraph)
- For remove_rule: find_text must uniquely identify the text to remove
- For modify_rule: find_text is what to find, content is what replaces it
- For add_mcp: content is a JSON object with the MCP server config
- For remove_mcp: find_text is the MCP server name
- For set_setting: content is a JSON object with the key-value to set
- Never output anything except the JSON object
"""


def _call_claude_api(instruction: str, claude_md: str, api_key: str) -> dict | None:
    """Call Claude API to get an edit plan for the instruction.

    Args:
        instruction: Natural language instruction from user.
        claude_md: Current CLAUDE.md content.
        api_key: Anthropic API key.

    Returns:
        Edit plan dict, or None on failure.
    """
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1024,
        "system": _SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Current CLAUDE.md content:\n```\n{claude_md[:6000]}\n```\n\n"
                    f"Instruction: {instruction}"
                ),
            }
        ],
    }

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            text = data["content"][0]["text"].strip()
            # Strip markdown code fences if present
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            return json.loads(text)
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, IndexError) as e:
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Edit application
# ──────────────────────────────────────────────────────────────────────────────

def _apply_edit_to_claude_md(path: Path, plan: dict) -> tuple[bool, str]:
    """Apply a parsed edit plan to CLAUDE.md.

    Args:
        path: Path to CLAUDE.md.
        plan: Edit plan dict from Claude API.

    Returns:
        (success, message) tuple.
    """
    action = plan.get("action", "")
    content = plan.get("content", "")
    placement = plan.get("placement", "append")
    find_text = plan.get("find_text", "")
    section = plan.get("section", "")

    current = path.read_text(encoding="utf-8") if path.exists() else ""

    if action == "add_rule":
        if placement == "prepend":
            new_content = content.strip() + "\n\n" + current
        elif placement == "after_section" and section:
            # Insert after the named section heading
            section_pattern = re.compile(
                rf"(#{1,4}\s+{re.escape(section)}.*?\n)", re.IGNORECASE
            )
            m = section_pattern.search(current)
            if m:
                insert_at = m.end()
                new_content = current[:insert_at] + "\n" + content.strip() + "\n" + current[insert_at:]
            else:
                new_content = current + "\n\n" + content.strip()
        else:
            # append
            new_content = current.rstrip() + "\n\n" + content.strip() + "\n"

    elif action == "remove_rule":
        if not find_text:
            return False, "remove_rule requires find_text"
        if find_text not in current:
            return False, f"Could not find text to remove: {find_text[:60]!r}"
        new_content = current.replace(find_text, "", 1).rstrip() + "\n"

    elif action == "modify_rule":
        if not find_text:
            return False, "modify_rule requires find_text"
        if find_text not in current:
            return False, f"Could not find text to modify: {find_text[:60]!r}"
        new_content = current.replace(find_text, content, 1)

    else:
        return False, f"Unsupported action for CLAUDE.md: {action}"

    path.write_text(new_content, encoding="utf-8")
    return True, plan.get("explanation", "Edit applied.")


def _apply_edit_to_settings(path: Path, plan: dict) -> tuple[bool, str]:
    """Apply a parsed edit plan to settings.json.

    Args:
        path: Path to settings.json.
        plan: Edit plan dict.

    Returns:
        (success, message) tuple.
    """
    action = plan.get("action", "")
    content = plan.get("content", "")
    find_text = plan.get("find_text", "")

    settings: dict = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            settings = {}

    if action == "set_setting":
        updates = content if isinstance(content, dict) else json.loads(content)
        settings.update(updates)

    elif action == "add_mcp":
        server_name = find_text or "new-server"
        mcp_config = content if isinstance(content, dict) else json.loads(content)
        if "mcpServers" not in settings:
            settings["mcpServers"] = {}
        settings["mcpServers"][server_name] = mcp_config

    elif action == "remove_mcp":
        server_name = find_text
        mcp = settings.get("mcpServers", {})
        if server_name not in mcp:
            return False, f"MCP server {server_name!r} not found in settings.json"
        del mcp[server_name]
        settings["mcpServers"] = mcp

    else:
        return False, f"Unsupported action for settings.json: {action}"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True, plan.get("explanation", "Settings updated.")


# ──────────────────────────────────────────────────────────────────────────────
# Command entry point
# ──────────────────────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync-edit",
        description="Edit Claude Code config using natural language, then sync.",
    )
    parser.add_argument(
        "instruction",
        nargs="?",
        help="Natural language instruction (e.g. 'add a rule: always use TypeScript')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the proposed edit without applying it",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Apply the edit to CLAUDE.md but skip sync to targets",
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Project directory (default: cwd)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Anthropic API key (default: ANTHROPIC_API_KEY env var)",
    )

    args = parser.parse_args(argv if argv is not None else shlex.split(
        os.environ.get("CLAUDE_ARGS", "")
    ))

    logger = Logger()
    project_dir = args.project_dir or Path.cwd()
    cc_home = Path(os.environ.get("CLAUDE_HOME", Path.home() / ".claude"))

    # Get instruction from args or stdin
    instruction = args.instruction
    if not instruction:
        if sys.stdin.isatty():
            print("Usage: /sync-edit '<instruction>'")
            print("Example: /sync-edit 'add a rule that always uses TypeScript'")
            return 1
        instruction = sys.stdin.read().strip()

    if not instruction:
        print("Error: No instruction provided.", file=sys.stderr)
        return 1

    # Locate CLAUDE.md
    claude_md_path = project_dir / "CLAUDE.md"
    if not claude_md_path.exists():
        claude_md_path = cc_home / "CLAUDE.md"

    claude_md_content = ""
    if claude_md_path.exists():
        claude_md_content = claude_md_path.read_text(encoding="utf-8")

    # Get API key
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print(
            "Error: No Anthropic API key found.\n"
            "Set ANTHROPIC_API_KEY environment variable or pass --api-key.",
            file=sys.stderr,
        )
        return 1

    print(f"Analyzing instruction: {instruction!r}")
    print("Calling Claude API to generate edit plan...")

    edit_plan = _call_claude_api(instruction, claude_md_content, api_key)
    if not edit_plan:
        print(
            "Error: Failed to generate edit plan from Claude API.\n"
            "Check your API key and network connection.",
            file=sys.stderr,
        )
        return 1

    # Show the plan
    print("\nProposed edit:")
    print(f"  Action: {edit_plan.get('action')}")
    print(f"  Target: {edit_plan.get('target_file')}")
    print(f"  Explanation: {edit_plan.get('explanation')}")
    if edit_plan.get("content"):
        content_preview = str(edit_plan["content"])[:100]
        if len(str(edit_plan["content"])) > 100:
            content_preview += "..."
        print(f"  Content: {content_preview}")

    if args.dry_run:
        print("\n[Dry run — no changes applied]")
        return 0

    # Apply edit
    target_file = edit_plan.get("target_file", "CLAUDE.md")
    if target_file == "CLAUDE.md":
        success, message = _apply_edit_to_claude_md(claude_md_path, edit_plan)
        if not success:
            print(f"Error applying edit: {message}", file=sys.stderr)
            return 1
        print(f"\nApplied to {claude_md_path}: {message}")
    elif target_file == "settings.json":
        settings_path = project_dir / ".claude" / "settings.json"
        if not settings_path.exists():
            settings_path = cc_home / "settings.json"
        success, message = _apply_edit_to_settings(settings_path, edit_plan)
        if not success:
            print(f"Error applying edit: {message}", file=sys.stderr)
            return 1
        print(f"\nApplied to {settings_path}: {message}")
    else:
        print(f"Error: Unknown target file {target_file!r}", file=sys.stderr)
        return 1

    # Run sync
    if not args.no_sync:
        print("\nSyncing changes to all harnesses...")
        try:
            from src.orchestrator import SyncOrchestrator
            orchestrator = SyncOrchestrator(project_dir=project_dir)
            results = orchestrator.sync_all()

            total_synced = sum(
                sum(r.synced for r in target_results.values() if hasattr(r, "synced"))
                for target_results in results.values()
                if isinstance(target_results, dict)
            )
            print(f"Sync complete: {total_synced} items propagated to targets.")
        except Exception as e:
            print(f"Warning: Sync failed: {e}", file=sys.stderr)
            print("Edit was applied to CLAUDE.md — run /sync to sync manually.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
