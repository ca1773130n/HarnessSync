from __future__ import annotations

"""Tests for adapter updates: VSCode commands/MCP, Cursor globs/legacy, Codex override/size warnings."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# VSCode adapter: sync_commands writes .github/prompts/<name>.prompt.md
# ---------------------------------------------------------------------------

class TestVSCodeCommands:
    def test_sync_commands_writes_prompt_files(self, tmp_path):
        from src.adapters.vscode import VSCodeAdapter

        adapter = VSCodeAdapter(tmp_path)

        # Create a command file
        cmd_dir = tmp_path / "commands"
        cmd_dir.mkdir()
        cmd_file = cmd_dir / "review.md"
        cmd_file.write_text("Review the code for bugs and style issues.", encoding="utf-8")

        result = adapter.sync_commands({"review": cmd_file})
        assert result.synced >= 1
        prompt_path = tmp_path / ".github" / "prompts" / "review.prompt.md"
        assert prompt_path.exists()
        content = prompt_path.read_text(encoding="utf-8")
        assert "Review the code" in content

    def test_sync_commands_empty(self, tmp_path):
        from src.adapters.vscode import VSCodeAdapter

        adapter = VSCodeAdapter(tmp_path)
        result = adapter.sync_commands({})
        assert result.skipped >= 1

    def test_sync_commands_missing_file(self, tmp_path):
        from src.adapters.vscode import VSCodeAdapter

        adapter = VSCodeAdapter(tmp_path)
        result = adapter.sync_commands({"ghost": tmp_path / "nonexistent.md"})
        assert result.failed >= 1


# ---------------------------------------------------------------------------
# VSCode adapter: sync_mcp writes .vscode/mcp.json
# ---------------------------------------------------------------------------

class TestVSCodeMCP:
    def test_sync_mcp_writes_vscode_mcp_json(self, tmp_path):
        from src.adapters.vscode import VSCodeAdapter

        adapter = VSCodeAdapter(tmp_path)
        servers = {
            "myserver": {
                "command": "node",
                "args": ["server.js"],
                "env": {"PORT": "3000"},
            }
        }
        result = adapter.sync_mcp(servers)
        assert result.synced >= 1

        mcp_path = tmp_path / ".vscode" / "mcp.json"
        assert mcp_path.exists()
        data = json.loads(mcp_path.read_text(encoding="utf-8"))
        assert "servers" in data
        assert "myserver" in data["servers"]
        assert data["servers"]["myserver"]["command"] == "node"
        assert data["servers"]["myserver"]["args"] == ["server.js"]
        assert data["servers"]["myserver"]["env"] == {"PORT": "3000"}

    def test_sync_mcp_empty(self, tmp_path):
        from src.adapters.vscode import VSCodeAdapter

        adapter = VSCodeAdapter(tmp_path)
        result = adapter.sync_mcp({})
        assert result.skipped >= 1

    def test_sync_mcp_no_url_passthrough(self, tmp_path):
        """Only command/args/env are written, not url fields."""
        from src.adapters.vscode import VSCodeAdapter

        adapter = VSCodeAdapter(tmp_path)
        result = adapter.sync_mcp({"srv": {"command": "python3", "args": ["-m", "srv"]}})
        assert result.synced >= 1
        data = json.loads((tmp_path / ".vscode" / "mcp.json").read_text())
        assert "url" not in data["servers"]["srv"]


# ---------------------------------------------------------------------------
# Cursor adapter: globs in frontmatter
# ---------------------------------------------------------------------------

class TestCursorGlobs:
    def test_globs_string_in_frontmatter(self, tmp_path):
        from src.adapters.cursor import CursorAdapter

        adapter = CursorAdapter(tmp_path)
        rules = [{"path": "api-rules.md", "content": "API rules here", "globs": "src/api/**/*.ts"}]
        result = adapter.sync_rules(rules)
        assert result.synced >= 1

        mdc_path = tmp_path / ".cursor" / "rules" / "api-rules.mdc"
        content = mdc_path.read_text(encoding="utf-8")
        assert "globs: src/api/**/*.ts" in content

    def test_globs_list_in_frontmatter(self, tmp_path):
        from src.adapters.cursor import CursorAdapter

        adapter = CursorAdapter(tmp_path)
        rules = [{"path": "multi.md", "content": "Multi rules", "globs": ["*.py", "*.ts"]}]
        result = adapter.sync_rules(rules)
        assert result.synced >= 1

        mdc_path = tmp_path / ".cursor" / "rules" / "multi.mdc"
        content = mdc_path.read_text(encoding="utf-8")
        assert "globs: *.py, *.ts" in content

    def test_scope_patterns_as_globs(self, tmp_path):
        from src.adapters.cursor import CursorAdapter

        adapter = CursorAdapter(tmp_path)
        rules = [{"path": "scoped.md", "content": "Scoped rules", "scope_patterns": ["docs/**"]}]
        result = adapter.sync_rules(rules)
        assert result.synced >= 1

        mdc_path = tmp_path / ".cursor" / "rules" / "scoped.mdc"
        content = mdc_path.read_text(encoding="utf-8")
        assert "globs: docs/**" in content

    def test_no_globs_when_absent(self, tmp_path):
        from src.adapters.cursor import CursorAdapter

        adapter = CursorAdapter(tmp_path)
        rules = [{"path": "plain.md", "content": "Plain rules"}]
        result = adapter.sync_rules(rules)
        assert result.synced >= 1

        mdc_path = tmp_path / ".cursor" / "rules" / "plain.mdc"
        content = mdc_path.read_text(encoding="utf-8")
        assert "globs:" not in content


# ---------------------------------------------------------------------------
# Cursor adapter: legacy .cursorrules warning
# ---------------------------------------------------------------------------

class TestCursorLegacyWarning:
    def test_warns_on_legacy_cursorrules(self, tmp_path, capsys):
        from src.adapters.cursor import CursorAdapter

        # Create legacy file
        (tmp_path / ".cursorrules").write_text("old rules", encoding="utf-8")

        adapter = CursorAdapter(tmp_path)
        adapter.sync_rules([{"path": "CLAUDE.md", "content": "New rules"}])

        captured = capsys.readouterr()
        assert ".cursorrules" in captured.err
        assert "migrating" in captured.err or "migration" in captured.err or "Consider" in captured.err

    def test_no_warning_without_legacy(self, tmp_path, capsys):
        from src.adapters.cursor import CursorAdapter

        adapter = CursorAdapter(tmp_path)
        adapter.sync_rules([{"path": "CLAUDE.md", "content": "New rules"}])

        captured = capsys.readouterr()
        assert ".cursorrules" not in captured.err


# ---------------------------------------------------------------------------
# Codex adapter: AGENTS.override.md warning
# ---------------------------------------------------------------------------

class TestCodexOverrideWarning:
    def test_warns_on_agents_override(self, tmp_path, capsys):
        from src.adapters.codex import CodexAdapter

        # Create override file
        (tmp_path / "AGENTS.override.md").write_text("override content", encoding="utf-8")

        adapter = CodexAdapter(tmp_path)
        adapter.sync_rules([{"path": "CLAUDE.md", "content": "Some rules"}])

        captured = capsys.readouterr()
        assert "AGENTS.override.md" in captured.err
        assert "precedence" in captured.err

    def test_no_warning_without_override(self, tmp_path, capsys):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_path)
        adapter.sync_rules([{"path": "CLAUDE.md", "content": "Some rules"}])

        captured = capsys.readouterr()
        assert "AGENTS.override.md" not in captured.err


# ---------------------------------------------------------------------------
# Codex adapter: 32KB size limit warning
# ---------------------------------------------------------------------------

class TestCodexSizeLimit:
    def test_warns_on_large_agents_md(self, tmp_path, capsys):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_path)
        # Create content exceeding 32KB
        large_content = "x" * 40000
        adapter.sync_rules([{"path": "CLAUDE.md", "content": large_content}])

        captured = capsys.readouterr()
        assert "32KB" in captured.err or "32768" in captured.err

    def test_no_warning_on_small_agents_md(self, tmp_path, capsys):
        from src.adapters.codex import CodexAdapter

        adapter = CodexAdapter(tmp_path)
        adapter.sync_rules([{"path": "CLAUDE.md", "content": "Small content"}])

        captured = capsys.readouterr()
        assert "32KB" not in captured.err
        assert "truncat" not in captured.err
