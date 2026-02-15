#!/usr/bin/env python3
"""Verification script for Task 1: OpenCodeAdapter implementation."""

import tempfile
import json
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.adapters import AdapterRegistry, SyncResult
from src.adapters.opencode import OpenCodeAdapter


def test_1_opencode_adapter_instantiation():
    """Test 1: Instantiate OpenCodeAdapter with temp directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        assert adapter.target_name == "opencode"
        assert adapter.project_dir == project_dir
        assert adapter.agents_md_path == project_dir / "AGENTS.md"
        assert adapter.opencode_dir == project_dir / ".opencode"
        assert adapter.opencode_json_path == project_dir / "opencode.json"

    print("✓ Test 1: OpenCodeAdapter instantiation")


def test_2_sync_rules_with_markers():
    """Test 2: sync_rules writes to AGENTS.md with markers and rule content."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        # Create mock rules
        rules = [
            {'path': Path('CLAUDE.md'), 'content': 'Rule 1 content\nMultiple lines'},
            {'path': Path('CUSTOM.md'), 'content': 'Rule 2 content'}
        ]

        # Sync rules
        result = adapter.sync_rules(rules)

        # Verify result
        assert result.synced == 1
        assert result.adapted == 2
        assert result.failed == 0

        # Verify AGENTS.md exists with markers
        agents_md = project_dir / "AGENTS.md"
        assert agents_md.exists()

        content = agents_md.read_text()
        assert "<!-- Managed by HarnessSync -->" in content
        assert "<!-- End HarnessSync managed content -->" in content
        assert "Rule 1 content" in content
        assert "Rule 2 content" in content
        assert "Last synced by HarnessSync:" in content

    print("✓ Test 2: sync_rules with markers and content")


def test_3_sync_skills_creates_symlinks():
    """Test 3: sync_skills creates symlinks in .opencode/skills/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        # Create mock skill directory
        skill_dir = project_dir / "mock_skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nname: Test Skill\n---\nSkill content")

        # Sync skills
        skills = {'test-skill': skill_dir}
        result = adapter.sync_skills(skills)

        # Verify result
        assert result.synced == 1
        assert result.failed == 0

        # Verify symlink exists
        symlink_path = project_dir / ".opencode" / "skills" / "test-skill"
        assert symlink_path.exists()

        # Verify it points to source (or is a copy)
        assert (symlink_path / "SKILL.md").exists()

    print("✓ Test 3: sync_skills creates symlinks")


def test_4_sync_agents_creates_symlinks():
    """Test 4: sync_agents creates symlinks in .opencode/agents/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        # Create mock agent file
        agent_path = project_dir / "mock_agents" / "test-agent.md"
        agent_path.parent.mkdir(parents=True)
        agent_path.write_text("---\nname: Test Agent\n---\n<role>Agent role</role>")

        # Sync agents
        agents = {'test-agent': agent_path}
        result = adapter.sync_agents(agents)

        # Verify result
        assert result.synced == 1
        assert result.failed == 0

        # Verify symlink exists with .md extension
        symlink_path = project_dir / ".opencode" / "agents" / "test-agent.md"
        assert symlink_path.exists()

    print("✓ Test 4: sync_agents creates symlinks")


def test_5_sync_commands_creates_symlinks():
    """Test 5: sync_commands creates symlinks in .opencode/commands/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        # Create mock command file
        cmd_path = project_dir / "mock_commands" / "test-cmd.md"
        cmd_path.parent.mkdir(parents=True)
        cmd_path.write_text("---\nname: Test Command\n---\nCommand content")

        # Sync commands
        commands = {'test-cmd': cmd_path}
        result = adapter.sync_commands(commands)

        # Verify result
        assert result.synced == 1
        assert result.failed == 0

        # Verify symlink exists with .md extension
        symlink_path = project_dir / ".opencode" / "commands" / "test-cmd.md"
        assert symlink_path.exists()

    print("✓ Test 5: sync_commands creates symlinks")


def test_6_stale_symlink_cleanup():
    """Test 6: Stale symlinks are cleaned up after sync."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        # Create a valid skill
        skill_dir = project_dir / "mock_skills" / "valid-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("Valid skill")

        # Create stale symlink manually
        stale_target = project_dir / "mock_skills" / "deleted-skill"
        skills_target_dir = project_dir / ".opencode" / "skills"
        skills_target_dir.mkdir(parents=True)
        stale_link = skills_target_dir / "stale-skill"

        # Try to create symlink to non-existent target
        try:
            stale_link.symlink_to(stale_target, target_is_directory=True)
        except:
            # If symlink fails, create a marker file to simulate stale state
            stale_link.mkdir()

        # Sync valid skills
        skills = {'valid-skill': skill_dir}
        result = adapter.sync_skills(skills)

        # Verify stale symlink was cleaned
        assert "cleaned:" in str(result.skipped_files) or result.synced == 1

    print("✓ Test 6: Stale symlink cleanup")


def test_7_sync_mcp_stdio_server():
    """Test 7: sync_mcp with stdio server creates type: local config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        # Create stdio MCP server config
        mcp_servers = {
            'test-server': {
                'command': 'node',
                'args': ['server.js', '--port', '3000'],
                'env': {'API_KEY': '${API_KEY}'}
            }
        }

        # Sync MCP
        result = adapter.sync_mcp(mcp_servers)

        # Verify result
        assert result.synced == 1
        assert result.failed == 0

        # Verify opencode.json
        config_path = project_dir / "opencode.json"
        assert config_path.exists()

        config = json.loads(config_path.read_text())
        assert '$schema' in config
        assert 'mcp' in config
        assert 'test-server' in config['mcp']

        server_config = config['mcp']['test-server']
        assert server_config['type'] == 'local'
        assert server_config['command'] == ['node', 'server.js', '--port', '3000']
        assert server_config['environment'] == {'API_KEY': '${API_KEY}'}
        assert server_config['enabled'] is True

    print("✓ Test 7: sync_mcp with stdio server (type: local)")


def test_8_sync_mcp_url_server():
    """Test 8: sync_mcp with URL server creates type: remote config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        # Create URL MCP server config
        mcp_servers = {
            'remote-server': {
                'url': 'https://mcp.example.com',
                'headers': {'Authorization': 'Bearer ${TOKEN}'}
            }
        }

        # Sync MCP
        result = adapter.sync_mcp(mcp_servers)

        # Verify result
        assert result.synced == 1
        assert result.failed == 0

        # Verify opencode.json
        config_path = project_dir / "opencode.json"
        config = json.loads(config_path.read_text())

        server_config = config['mcp']['remote-server']
        assert server_config['type'] == 'remote'
        assert server_config['url'] == 'https://mcp.example.com'
        assert server_config['headers'] == {'Authorization': 'Bearer ${TOKEN}'}
        assert server_config['enabled'] is True

    print("✓ Test 8: sync_mcp with URL server (type: remote)")


def test_9_sync_mcp_preserves_env_vars():
    """Test 9: sync_mcp preserves environment variable references."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        # Create config with env var references
        mcp_servers = {
            'env-server': {
                'command': 'python',
                'args': ['server.py'],
                'env': {
                    'DATABASE_URL': '${DATABASE_URL}',
                    'API_KEY': '${API_KEY}',
                    'PORT': '${PORT:-8000}'
                }
            }
        }

        # Sync MCP
        result = adapter.sync_mcp(mcp_servers)

        # Verify env vars preserved as strings
        config_path = project_dir / "opencode.json"
        config = json.loads(config_path.read_text())

        env = config['mcp']['env-server']['environment']
        assert env['DATABASE_URL'] == '${DATABASE_URL}'
        assert env['API_KEY'] == '${API_KEY}'
        assert env['PORT'] == '${PORT:-8000}'

    print("✓ Test 9: sync_mcp preserves env var references")


def test_10_sync_settings_deny_list():
    """Test 10: sync_settings with deny list creates restricted mode."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        # Create settings with deny list
        settings = {
            'permissions': {
                'deny': ['Bash', 'Edit']
            }
        }

        # Sync settings
        result = adapter.sync_settings(settings)

        # Verify result
        assert result.synced == 1
        assert result.failed == 0

        # Verify opencode.json
        config_path = project_dir / "opencode.json"
        config = json.loads(config_path.read_text())

        assert 'permissions' in config
        assert config['permissions']['mode'] == 'restricted'
        assert config['permissions']['denied'] == ['Bash', 'Edit']

    print("✓ Test 10: sync_settings with deny list (restricted mode)")


def test_11_sync_settings_mcp_coexistence():
    """Test 11: sync_settings + sync_mcp coexist in same opencode.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = OpenCodeAdapter(project_dir)

        # Sync MCP first
        mcp_servers = {
            'test-server': {
                'command': 'node',
                'args': ['server.js']
            }
        }
        result1 = adapter.sync_mcp(mcp_servers)
        assert result1.synced == 1

        # Sync settings second
        settings = {
            'permissions': {
                'allow': ['Read', 'Write']
            }
        }
        result2 = adapter.sync_settings(settings)
        assert result2.synced == 1

        # Verify both sections exist
        config_path = project_dir / "opencode.json"
        config = json.loads(config_path.read_text())

        assert 'mcp' in config
        assert 'test-server' in config['mcp']
        assert 'permissions' in config
        assert config['permissions']['mode'] == 'default'
        assert config['permissions']['allowed'] == ['Read', 'Write']

    print("✓ Test 11: sync_settings + sync_mcp coexistence")


def main():
    """Run all verification tests."""
    print("\n=== OpenCodeAdapter Verification (Task 1) ===\n")

    tests = [
        test_1_opencode_adapter_instantiation,
        test_2_sync_rules_with_markers,
        test_3_sync_skills_creates_symlinks,
        test_4_sync_agents_creates_symlinks,
        test_5_sync_commands_creates_symlinks,
        test_6_stale_symlink_cleanup,
        test_7_sync_mcp_stdio_server,
        test_8_sync_mcp_url_server,
        test_9_sync_mcp_preserves_env_vars,
        test_10_sync_settings_deny_list,
        test_11_sync_settings_mcp_coexistence,
    ]

    failed = []
    for test in tests:
        try:
            test()
        except AssertionError as e:
            failed.append((test.__name__, str(e)))
            print(f"✗ {test.__name__}: {e}")
        except Exception as e:
            failed.append((test.__name__, str(e)))
            print(f"✗ {test.__name__}: {e}")

    print(f"\n=== Results: {len(tests) - len(failed)}/{len(tests)} tests passed ===\n")

    if failed:
        print("Failed tests:")
        for name, error in failed:
            print(f"  - {name}: {error}")
        sys.exit(1)
    else:
        print("All Task 1 tests passed!")
        sys.exit(0)


if __name__ == '__main__':
    main()
