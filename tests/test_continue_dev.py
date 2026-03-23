from __future__ import annotations

"""Tests for Continue.dev adapter.

Covers:
- Rules sync with YAML frontmatter (name, alwaysApply, description)
- Skills sync with YAML frontmatter
- MCP sync to config.yaml (primary, list format)
- MCP sync fallback to config.json (legacy dict format)
- YAML section removal helper
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.adapters.continue_dev import ContinueDevAdapter


# ---------------------------------------------------------------------------
# Rules sync tests
# ---------------------------------------------------------------------------

class TestContinueDevRulesSync:
    """Test sync_rules writes YAML frontmatter."""

    def test_rules_have_yaml_frontmatter(self, tmp_path):
        """Rules file should start with YAML frontmatter block."""
        adapter = ContinueDevAdapter(tmp_path)
        rules = [{"content": "Do not use unsafe functions."}]
        result = adapter.sync_rules(rules)

        assert result.synced == 1
        rules_path = tmp_path / ".continue" / "rules" / "harnesssync.md"
        assert rules_path.exists()

        content = rules_path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "name: HarnessSync Rules" in content
        assert "alwaysApply: true" in content
        assert "description: Rules synced from Claude Code by HarnessSync" in content
        # Frontmatter closes before managed marker
        assert "---\n\n<!-- Managed by HarnessSync -->" in content

    def test_rules_empty_skipped(self, tmp_path):
        """Empty rules list should be skipped."""
        adapter = ContinueDevAdapter(tmp_path)
        result = adapter.sync_rules([])
        assert result.skipped == 1

    def test_rules_content_preserved(self, tmp_path):
        """Rule content appears after frontmatter."""
        adapter = ContinueDevAdapter(tmp_path)
        rules = [{"content": "Rule one"}, {"content": "Rule two"}]
        result = adapter.sync_rules(rules)

        content = (tmp_path / ".continue" / "rules" / "harnesssync.md").read_text()
        assert "Rule one" in content
        assert "Rule two" in content
        assert result.synced == 1


# ---------------------------------------------------------------------------
# Skills sync tests
# ---------------------------------------------------------------------------

class TestContinueDevSkillsSync:
    """Test sync_skills writes YAML frontmatter."""

    def test_skills_have_yaml_frontmatter(self, tmp_path):
        """Skill files should have YAML frontmatter with name and alwaysApply."""
        skill_dir = tmp_path / "skills" / "debugging"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("Debug instructions here.", encoding="utf-8")

        adapter = ContinueDevAdapter(tmp_path)
        result = adapter.sync_skills({"debugging": skill_dir})

        assert result.synced == 1
        out_path = tmp_path / ".continue" / "rules" / "skills" / "debugging.md"
        assert out_path.exists()

        content = out_path.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "name: debugging" in content
        assert "alwaysApply: true" in content
        assert "Skill 'debugging' synced from Claude Code" in content
        assert "Debug instructions here." in content

    def test_skills_empty_skipped(self, tmp_path):
        """Empty skills dict should be skipped."""
        adapter = ContinueDevAdapter(tmp_path)
        result = adapter.sync_skills({})
        assert result.skipped == 1


# ---------------------------------------------------------------------------
# MCP sync tests - YAML primary
# ---------------------------------------------------------------------------

class TestContinueDevMcpYaml:
    """Test MCP sync writes config.yaml by default."""

    def test_mcp_writes_yaml_when_no_config_exists(self, tmp_path):
        """With no existing config, MCP should write config.yaml."""
        adapter = ContinueDevAdapter(tmp_path)
        servers = {
            "myserver": {
                "command": "node",
                "args": ["server.js"],
                "env": {"PORT": "3000"},
            }
        }
        result = adapter.sync_mcp(servers)

        assert result.synced == 1
        yaml_path = tmp_path / ".continue" / "config.yaml"
        assert yaml_path.exists()
        assert not (tmp_path / ".continue" / "config.json").exists()

        content = yaml_path.read_text(encoding="utf-8")
        assert "mcpServers:" in content
        assert "  - name: myserver" in content
        assert "    command: node" in content
        assert "      - server.js" in content
        assert "      PORT:" in content

    def test_mcp_writes_yaml_when_yaml_exists(self, tmp_path):
        """If config.yaml already exists, keep using it."""
        continue_dir = tmp_path / ".continue"
        continue_dir.mkdir(parents=True)
        (continue_dir / "config.yaml").write_text("models:\n  - name: gpt-4\n", encoding="utf-8")

        adapter = ContinueDevAdapter(tmp_path)
        servers = {"srv": {"command": "python", "args": ["-m", "srv"]}}
        result = adapter.sync_mcp(servers)

        assert result.synced == 1
        content = (continue_dir / "config.yaml").read_text(encoding="utf-8")
        # Preserved existing models section
        assert "models:" in content
        assert "  - name: gpt-4" in content
        # Has new mcpServers
        assert "mcpServers:" in content
        assert "  - name: srv" in content

    def test_mcp_yaml_with_cwd(self, tmp_path):
        """cwd field should be written to YAML output."""
        adapter = ContinueDevAdapter(tmp_path)
        servers = {"s": {"command": "node", "cwd": "/home/user/proj"}}
        adapter.sync_mcp(servers)

        content = (tmp_path / ".continue" / "config.yaml").read_text()
        assert "cwd: /home/user/proj" in content

    def test_mcp_yaml_with_url_transport(self, tmp_path):
        """URL-based servers should get transport: sse."""
        adapter = ContinueDevAdapter(tmp_path)
        servers = {"remote": {"url": "http://localhost:8080"}}
        adapter.sync_mcp(servers)

        content = (tmp_path / ".continue" / "config.yaml").read_text()
        assert "url:" in content
        assert "transport: sse" in content


# ---------------------------------------------------------------------------
# MCP sync tests - JSON fallback
# ---------------------------------------------------------------------------

class TestContinueDevMcpJsonFallback:
    """Test MCP falls back to config.json when appropriate."""

    def test_mcp_writes_json_when_only_json_exists(self, tmp_path):
        """If config.json exists but config.yaml doesn't, use JSON."""
        continue_dir = tmp_path / ".continue"
        continue_dir.mkdir(parents=True)
        (continue_dir / "config.json").write_text('{"models": []}', encoding="utf-8")

        adapter = ContinueDevAdapter(tmp_path)
        servers = {"srv": {"command": "node", "args": ["index.js"]}}
        result = adapter.sync_mcp(servers)

        assert result.synced == 1
        json_path = continue_dir / "config.json"
        data = json.loads(json_path.read_text(encoding="utf-8"))
        # Preserved existing models
        assert "models" in data
        # MCP as dict keyed by name (legacy format)
        assert "srv" in data["mcpServers"]
        assert data["mcpServers"]["srv"]["command"] == "node"

    def test_mcp_empty_skipped(self, tmp_path):
        """Empty MCP servers should be skipped."""
        adapter = ContinueDevAdapter(tmp_path)
        result = adapter.sync_mcp({})
        assert result.skipped == 1


# ---------------------------------------------------------------------------
# YAML section removal helper
# ---------------------------------------------------------------------------

class TestRemoveYamlSection:
    """Test _remove_yaml_section static helper."""

    def test_removes_section(self):
        raw = "models:\n  - name: gpt-4\nmcpServers:\n  - name: srv\n    command: node\nother: value\n"
        result = ContinueDevAdapter._remove_yaml_section(raw, "mcpServers")
        assert "mcpServers:" not in "\n".join(result)
        assert "models:" in "\n".join(result)
        assert "other: value" in "\n".join(result)

    def test_no_section_noop(self):
        raw = "models:\n  - name: gpt-4\n"
        result = ContinueDevAdapter._remove_yaml_section(raw, "mcpServers")
        assert len(result) == 2
        assert "models:" in result[0]
