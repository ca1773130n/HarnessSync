from __future__ import annotations

"""Custom Adapter Scaffold Generator.

Generates a skeleton adapter from a template given a harness name and
config file format. Lowers the contribution bar from 'read source code'
to 'fill in a template', making it easy to add support for new harnesses.

Supported config formats:
  markdown  — Single markdown file (like AGENTS.md or GEMINI.md)
  json      — JSON config file (like opencode.json)
  yaml      — YAML config file
  toml      — TOML config file
  directory — Directory of files (like .cursor/rules/*.mdc)
"""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ScaffoldResult:
    """Result of scaffold generation."""
    adapter_path: str
    command_path: str
    test_path: str
    adapter_content: str
    command_content: str
    test_content: str
    next_steps: list[str]


_ADAPTER_TEMPLATE = '''from __future__ import annotations

"""Adapter for {harness_name} harness.

Config format: {config_format}
Config path:   {config_path}
"""

import json
import re
import shutil
from pathlib import Path

from src.adapters.base import AdapterBase
from src.adapters.registry import AdapterRegistry
from src.adapters.result import SyncResult


@AdapterRegistry.register("{harness_id}")
class {class_name}(AdapterBase):
    """Sync Claude Code configuration to {harness_name}.

    Writes to: {config_path}
    """

    TARGET_NAME = "{harness_id}"
    CONFIG_PATH = "{config_path}"

    @property
    def target_name(self) -> str:
        return self.TARGET_NAME

    def sync_rules(self, rules: list[dict]) -> SyncResult:
        """Sync CLAUDE.md rules to {harness_name} config.

        TODO: Implement rules sync logic.
        - rules is a list of dicts with keys: 'content', 'scope', 'file'
        - Write to self.project_dir / self.CONFIG_PATH
        """
        result = SyncResult()
        try:
            output_path = self.project_dir / self.CONFIG_PATH
            output_path.parent.mkdir(parents=True, exist_ok=True)

            # TODO: Format rules according to {harness_name} conventions.
            content = self._format_rules(rules)
            output_path.write_text(content, encoding="utf-8")
            result.synced = len(rules)
        except OSError as e:
            result.failed = 1
            result.errors.append(str(e))
        return result

    def sync_skills(self, skills: dict[str, Path]) -> SyncResult:
        """Sync skills to {harness_name}.

        TODO: Implement skill sync logic.
        - skills is a dict mapping skill_name -> path to skill directory
        """
        result = SyncResult()
        # TODO: Add skill sync implementation.
        # For harnesses without a skill concept, skip with a note:
        # result.skipped = len(skills)
        result.skipped = len(skills)
        return result

    def sync_agents(self, agents: dict[str, Path]) -> SyncResult:
        """Sync agents to {harness_name}.

        TODO: Implement agent sync logic.
        """
        result = SyncResult()
        result.skipped = len(agents)
        return result

    def sync_commands(self, commands: dict[str, Path]) -> SyncResult:
        """Sync commands to {harness_name}.

        TODO: Implement command sync logic.
        """
        result = SyncResult()
        result.skipped = len(commands)
        return result

    def sync_mcp(self, mcp_servers: dict) -> SyncResult:
        """Sync MCP server configurations to {harness_name}.

        TODO: Implement MCP sync logic.
        - mcp_servers is a dict mapping server_name -> server config dict
        """
        result = SyncResult()
        # TODO: Add MCP sync implementation.
        result.skipped = len(mcp_servers)
        return result

    def sync_settings(self, settings: dict) -> SyncResult:
        """Sync settings to {harness_name}.

        TODO: Implement settings sync logic.
        - settings is a dict from Claude Code settings.json
        """
        result = SyncResult()
        result.skipped = 1 if settings else 0
        return result

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _format_rules(self, rules: list[dict]) -> str:
        """Format rules list into {harness_name}-compatible text.

        TODO: Implement format specific to {harness_name}.
        """
        parts = []
        for rule in rules:
            content = rule.get("content", "")
            if content:
                parts.append(content)
        return "\\n\\n".join(parts)
'''

_COMMAND_TEMPLATE = '''from __future__ import annotations

"""
/sync-{harness_id} — Sync config to {harness_name}.

Usage:
    /sync-{harness_id}
    /sync-{harness_id} --dry-run
    /sync-{harness_id} --only rules
"""

import argparse
import os
import shlex
import sys
from pathlib import Path

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from src.orchestrator import SyncOrchestrator


def main() -> None:
    """Entry point for /sync-{harness_id} command."""
    args_string = " ".join(sys.argv[1:])
    try:
        tokens = shlex.split(args_string) if args_string.strip() else []
    except ValueError:
        tokens = []

    parser = argparse.ArgumentParser(
        prog="sync-{harness_id}",
        description="Sync Claude Code config to {harness_name}",
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without writing")
    parser.add_argument("--only", default=None,
                        help="Sync only this section (rules/skills/agents/commands/mcp/settings)")
    parser.add_argument("--project-dir", default=None)

    try:
        args = parser.parse_args(tokens)
    except SystemExit:
        return

    project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()
    only_sections = {{args.only}} if args.only else None

    orch = SyncOrchestrator(
        project_dir=project_dir,
        dry_run=args.dry_run,
        only_sections=only_sections,
        cli_only_targets={{"{harness_id}"}},
    )
    results = orch.sync_all()
    target_result = results.get("{harness_id}", {{}})

    if isinstance(target_result, dict):
        total_synced = sum(
            getattr(r, "synced", 0) for r in target_result.values()
            if hasattr(r, "synced")
        )
        total_failed = sum(
            getattr(r, "failed", 0) for r in target_result.values()
            if hasattr(r, "failed")
        )
        print(f"{{\'[dry-run] \' if args.dry_run else \'\'}}Synced {{total_synced}} items to {harness_name}."
              + (f" ({{total_failed}} failed)" if total_failed else ""))
    else:
        status = "ok" if getattr(target_result, "success", True) else "failed"
        print(f"Sync to {harness_name}: {{status}}")


if __name__ == "__main__":
    main()
'''

_TEST_TEMPLATE = '''from __future__ import annotations

"""Tests for {harness_name} adapter."""

import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.adapters.{harness_id} import {class_name}
from src.adapters.registry import AdapterRegistry


class Test{class_name}:
    def _adapter(self, tmp_path: Path) -> {class_name}:
        return {class_name}(project_dir=tmp_path)

    def test_registered(self):
        assert "{harness_id}" in AdapterRegistry.list_targets()

    def test_target_name(self, tmp_path):
        adapter = self._adapter(tmp_path)
        assert adapter.target_name == "{harness_id}"

    def test_sync_rules_empty(self, tmp_path):
        adapter = self._adapter(tmp_path)
        result = adapter.sync_rules([])
        assert result.failed == 0

    def test_sync_rules_basic(self, tmp_path):
        adapter = self._adapter(tmp_path)
        rules = [{{"content": "Use 2-space indentation.", "scope": "project"}}]
        result = adapter.sync_rules(rules)
        # At least one rule should be synced or result should not error
        assert result.failed == 0

    def test_sync_mcp_returns_result(self, tmp_path):
        adapter = self._adapter(tmp_path)
        result = adapter.sync_mcp({{"my-server": {{"command": "npx", "args": ["-y", "my-server"]}}}})
        # Should not raise
        assert result is not None

    def test_sync_skills_skips(self, tmp_path):
        adapter = self._adapter(tmp_path)
        result = adapter.sync_skills({{"my-skill": tmp_path}})
        assert result is not None
'''


def _harness_id_to_class_name(harness_id: str) -> str:
    """Convert 'my-harness' → 'MyHarnessAdapter'."""
    parts = re.split(r"[-_]", harness_id)
    return "".join(p.capitalize() for p in parts) + "Adapter"


def _infer_config_path(harness_id: str, config_format: str) -> str:
    """Infer a sensible default config path for the harness."""
    defaults: dict[str, str] = {
        "markdown":  f"{harness_id.upper()}.md",
        "json":      f".{harness_id}/{harness_id}.json",
        "yaml":      f".{harness_id}/{harness_id}.yaml",
        "toml":      f".{harness_id}/{harness_id}.toml",
        "directory": f".{harness_id}/rules/",
    }
    return defaults.get(config_format, f".{harness_id}/config")


def generate_adapter_scaffold(
    harness_id: str,
    harness_name: str | None = None,
    config_format: str = "markdown",
    config_path: str | None = None,
    output_dir: Path | None = None,
    dry_run: bool = False,
) -> ScaffoldResult:
    """Generate a skeleton adapter for a new harness.

    Args:
        harness_id: Short identifier used in file names and registry (e.g. 'myrule').
        harness_name: Human-readable name (default: title-case of harness_id).
        config_format: 'markdown' | 'json' | 'yaml' | 'toml' | 'directory'.
        config_path: Override the default config file path.
        output_dir: Directory to write generated files (default: current project).
        dry_run: If True, return content without writing files.

    Returns:
        ScaffoldResult with file paths and content.
    """
    harness_id = harness_id.lower().replace(" ", "-")
    harness_name = harness_name or harness_id.replace("-", " ").replace("_", " ").title()
    class_name = _harness_id_to_class_name(harness_id)
    config_path = config_path or _infer_config_path(harness_id, config_format)

    adapter_content = _ADAPTER_TEMPLATE.format(
        harness_id=harness_id,
        harness_name=harness_name,
        class_name=class_name,
        config_format=config_format,
        config_path=config_path,
    )
    command_content = _COMMAND_TEMPLATE.format(
        harness_id=harness_id,
        harness_name=harness_name,
    )
    test_content = _TEST_TEMPLATE.format(
        harness_id=harness_id,
        harness_name=harness_name,
        class_name=class_name,
    )

    adapter_path = f"src/adapters/{harness_id}.py"
    command_path = f"src/commands/sync_{harness_id.replace('-', '_')}.py"
    test_path = f"tests/test_adapter_{harness_id.replace('-', '_')}.py"

    next_steps = [
        f"1. Review and complete {adapter_path}",
        f"   - Implement sync_rules() to write {config_path}",
        f"   - Implement sync_mcp() if {harness_name} supports MCP",
        f"2. Import the adapter in src/adapters/__init__.py",
        f"   Add: from src.adapters.{harness_id.replace('-', '_')} import {class_name}",
        f"3. Run: python3 -m pytest {test_path}",
        f"4. Add '{harness_id}' to CORE_TARGETS or EXTENDED_TARGETS in src/utils/constants.py",
        f"5. Submit a pull request to harnesssync/harnesssync",
    ]

    if not dry_run and output_dir is not None:
        (output_dir / adapter_path).parent.mkdir(parents=True, exist_ok=True)
        (output_dir / adapter_path).write_text(adapter_content, encoding="utf-8")

        (output_dir / command_path).parent.mkdir(parents=True, exist_ok=True)
        (output_dir / command_path).write_text(command_content, encoding="utf-8")

        (output_dir / test_path).parent.mkdir(parents=True, exist_ok=True)
        (output_dir / test_path).write_text(test_content, encoding="utf-8")

    return ScaffoldResult(
        adapter_path=adapter_path,
        command_path=command_path,
        test_path=test_path,
        adapter_content=adapter_content,
        command_content=command_content,
        test_content=test_content,
        next_steps=next_steps,
    )
