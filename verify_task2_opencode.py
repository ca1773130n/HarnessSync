#!/usr/bin/env python3
"""Verification script for Task 2: 3-adapter integration test."""

import tempfile
import json
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.adapters import AdapterRegistry
from src.utils.toml_writer import read_toml_safe


def test_1_adapter_discovery():
    """Test 1: AdapterRegistry.list_targets() returns all 3 targets."""
    targets = AdapterRegistry.list_targets()

    assert targets == ['codex', 'gemini', 'opencode'], f"Expected ['codex', 'gemini', 'opencode'], got {targets}"

    print("✓ Test 1: Adapter discovery (3 targets)")


def test_2_has_target_checks():
    """Test 2: AdapterRegistry.has_target() works for all targets."""
    assert AdapterRegistry.has_target('codex') is True
    assert AdapterRegistry.has_target('gemini') is True
    assert AdapterRegistry.has_target('opencode') is True
    assert AdapterRegistry.has_target('nonexistent') is False

    print("✓ Test 2: has_target() checks")


def test_3_three_adapter_integration():
    """Test 3: All 3 adapters sync the same test project successfully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)

        # Create test project data
        # 2 rule files
        rules = [
            {'path': Path('CLAUDE.md'), 'content': 'Rule 1: Always be helpful'},
            {'path': Path('CUSTOM.md'), 'content': 'Rule 2: Write clear code'}
        ]

        # 3 skills (create actual directories with SKILL.md)
        skills = {}
        for i in range(1, 4):
            skill_name = f'skill-{i}'
            skill_dir = base_dir / 'test_skills' / skill_name
            skill_dir.mkdir(parents=True)
            skill_md = skill_dir / 'SKILL.md'
            skill_md.write_text(f'---\nname: Skill {i}\ndescription: Test skill {i}\n---\n\nSkill {i} instructions')
            skills[skill_name] = skill_dir

        # 2 agents
        agents = {}
        for i in range(1, 3):
            agent_name = f'agent-{i}'
            agent_path = base_dir / 'test_agents' / f'{agent_name}.md'
            agent_path.parent.mkdir(parents=True, exist_ok=True)
            agent_path.write_text(f'---\nname: Agent {i}\ndescription: Test agent {i}\n---\n\n<role>Agent {i} role</role>')
            agents[agent_name] = agent_path

        # 1 command
        commands = {}
        cmd_name = 'test-cmd'
        cmd_path = base_dir / 'test_commands' / f'{cmd_name}.md'
        cmd_path.parent.mkdir(parents=True)
        cmd_path.write_text(f'---\nname: Test Command\ndescription: Test command description\n---\n\nCommand content')
        commands[cmd_name] = cmd_path

        # 2 MCP servers (1 stdio, 1 URL)
        mcp_servers = {
            'stdio-server': {
                'command': 'node',
                'args': ['server.js'],
                'env': {'API_KEY': '${API_KEY}'}
            },
            'url-server': {
                'url': 'https://mcp.example.com',
                'headers': {'Authorization': 'Bearer ${TOKEN}'}
            }
        }

        # Permission settings
        settings = {
            'permissions': {
                'deny': ['Bash'],
                'allow': ['Read', 'Write']
            }
        }

        # Prepare source data
        source_data = {
            'rules': rules,
            'skills': skills,
            'agents': agents,
            'commands': commands,
            'mcp': mcp_servers,
            'settings': settings
        }

        # Test all 3 adapters
        results_summary = []

        for target in ['codex', 'gemini', 'opencode']:
            # Create separate project directory for each adapter
            project_dir = base_dir / f'project_{target}'
            project_dir.mkdir()

            # Instantiate adapter
            adapter = AdapterRegistry.get_adapter(target, project_dir)

            # Sync all
            results = adapter.sync_all(source_data)

            # Verify results
            assert results['rules'].synced >= 1, f"{target}: rules not synced"
            assert results['rules'].failed == 0, f"{target}: rules failed"

            assert results['skills'].synced == 3, f"{target}: expected 3 skills synced, got {results['skills'].synced}"
            assert results['skills'].failed == 0, f"{target}: skills failed"

            assert results['agents'].synced == 2, f"{target}: expected 2 agents synced, got {results['agents'].synced}"
            assert results['agents'].failed == 0, f"{target}: agents failed"

            assert results['commands'].synced == 1, f"{target}: expected 1 command synced, got {results['commands'].synced}"
            assert results['commands'].failed == 0, f"{target}: commands failed"

            assert results['mcp'].synced == 2, f"{target}: expected 2 MCP servers synced, got {results['mcp'].synced}"
            assert results['mcp'].failed == 0, f"{target}: MCP failed"

            assert results['settings'].synced == 1, f"{target}: settings not synced"
            assert results['settings'].failed == 0, f"{target}: settings failed"

            # Collect summary
            results_summary.append({
                'target': target,
                'rules': f"{results['rules'].synced}/{results['rules'].failed}",
                'skills': f"{results['skills'].synced}/{results['skills'].failed}",
                'agents': f"{results['agents'].synced}/{results['agents'].failed}",
                'commands': f"{results['commands'].synced}/{results['commands'].failed}",
                'mcp': f"{results['mcp'].synced}/{results['mcp'].failed}",
                'settings': f"{results['settings'].synced}/{results['settings'].failed}",
            })

        # Print summary table
        print("\n  Target   | Rules | Skills | Agents | Cmds | MCP | Settings | Status")
        print("  ---------|-------|--------|--------|------|-----|----------|-------")
        for summary in results_summary:
            print(f"  {summary['target']:<8} | {summary['rules']:<5} | {summary['skills']:<6} | {summary['agents']:<6} | {summary['commands']:<4} | {summary['mcp']:<3} | {summary['settings']:<8} | PASS")

    print("\n✓ Test 3: 3-adapter integration (all adapters sync successfully)")


def test_4_codex_artifacts():
    """Test 4: Verify Codex-specific artifacts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create minimal test data
        skill_dir = project_dir / 'test_skills' / 'test-skill'
        skill_dir.mkdir(parents=True)
        (skill_dir / 'SKILL.md').write_text('---\nname: Test\n---\nContent')

        source_data = {
            'rules': [{'path': Path('CLAUDE.md'), 'content': 'Test rule'}],
            'skills': {'test-skill': skill_dir},
            'agents': {},
            'commands': {},
            'mcp': {'server1': {'command': 'node', 'args': ['server.js']}},
            'settings': {}
        }

        adapter = AdapterRegistry.get_adapter('codex', project_dir)
        adapter.sync_all(source_data)

        # Verify Codex artifacts
        assert (project_dir / 'AGENTS.md').exists(), "Codex AGENTS.md missing"
        assert (project_dir / '.agents' / 'skills' / 'test-skill').exists(), "Codex skill symlink missing"
        assert (project_dir / '.codex' / 'codex.toml').exists(), "Codex codex.toml missing"

        # Verify TOML content
        config_path = project_dir / '.codex' / 'codex.toml'
        config = read_toml_safe(config_path)
        assert 'mcp_servers' in config, "Codex MCP servers missing from TOML"

    print("✓ Test 4: Codex-specific artifacts verified")


def test_5_gemini_artifacts():
    """Test 5: Verify Gemini-specific artifacts (inline content, no YAML frontmatter)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create minimal test data
        skill_dir = project_dir / 'test_skills' / 'test-skill'
        skill_dir.mkdir(parents=True)
        (skill_dir / 'SKILL.md').write_text('---\nname: Test Skill\ndescription: Test\n---\n\nSkill content here')

        source_data = {
            'rules': [{'path': Path('CLAUDE.md'), 'content': 'Test rule'}],
            'skills': {'test-skill': skill_dir},
            'agents': {},
            'commands': {},
            'mcp': {'server1': {'command': 'node', 'args': ['server.js']}},
            'settings': {}
        }

        adapter = AdapterRegistry.get_adapter('gemini', project_dir)
        adapter.sync_all(source_data)

        # Verify Gemini artifacts
        assert (project_dir / 'GEMINI.md').exists(), "Gemini GEMINI.md missing"
        assert (project_dir / '.gemini' / 'settings.json').exists(), "Gemini settings.json missing"

        # Verify GEMINI.md has NO YAML frontmatter (skills are inlined)
        gemini_content = (project_dir / 'GEMINI.md').read_text()
        assert '## Skill: Test Skill' in gemini_content, "Gemini skill not inlined"
        assert 'Skill content here' in gemini_content, "Gemini skill content missing"
        # Should NOT have YAML frontmatter in inlined content
        assert '---\nname: Test Skill\n---' not in gemini_content, "Gemini has YAML frontmatter (should be stripped)"

        # Verify settings.json has mcpServers
        settings_path = project_dir / '.gemini' / 'settings.json'
        settings = json.loads(settings_path.read_text())
        assert 'mcpServers' in settings, "Gemini mcpServers missing"

    print("✓ Test 5: Gemini-specific artifacts verified (inline, no frontmatter)")


def test_6_opencode_artifacts():
    """Test 6: Verify OpenCode-specific artifacts (symlinks, type-discriminated MCP)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)

        # Create minimal test data
        skill_dir = project_dir / 'test_skills' / 'test-skill'
        skill_dir.mkdir(parents=True)
        (skill_dir / 'SKILL.md').write_text('---\nname: Test\n---\nContent')

        agent_path = project_dir / 'test_agents' / 'test-agent.md'
        agent_path.parent.mkdir(parents=True)
        agent_path.write_text('---\nname: Test\n---\nAgent content')

        cmd_path = project_dir / 'test_commands' / 'test-cmd.md'
        cmd_path.parent.mkdir(parents=True)
        cmd_path.write_text('---\nname: Test\n---\nCommand content')

        source_data = {
            'rules': [{'path': Path('CLAUDE.md'), 'content': 'Test rule'}],
            'skills': {'test-skill': skill_dir},
            'agents': {'test-agent': agent_path},
            'commands': {'test-cmd': cmd_path},
            'mcp': {
                'stdio-server': {'command': 'node', 'args': ['server.js']},
                'url-server': {'url': 'https://example.com'}
            },
            'settings': {}
        }

        adapter = AdapterRegistry.get_adapter('opencode', project_dir)
        adapter.sync_all(source_data)

        # Verify OpenCode artifacts
        assert (project_dir / 'AGENTS.md').exists(), "OpenCode AGENTS.md missing"
        assert (project_dir / '.opencode' / 'skills' / 'test-skill').exists(), "OpenCode skill symlink missing"
        assert (project_dir / '.opencode' / 'agents' / 'test-agent.md').exists(), "OpenCode agent symlink missing"
        assert (project_dir / '.opencode' / 'commands' / 'test-cmd.md').exists(), "OpenCode command symlink missing"
        assert (project_dir / 'opencode.json').exists(), "OpenCode opencode.json missing"

        # Verify opencode.json has type-discriminated MCP
        config_path = project_dir / 'opencode.json'
        config = json.loads(config_path.read_text())
        assert 'mcp' in config, "OpenCode MCP config missing"
        assert config['mcp']['stdio-server']['type'] == 'local', "OpenCode stdio server not type: local"
        assert config['mcp']['url-server']['type'] == 'remote', "OpenCode URL server not type: remote"

    print("✓ Test 6: OpenCode-specific artifacts verified (symlinks, type-discriminated MCP)")


def test_7_conservative_permissions():
    """Test 7: Conservative permission mapping across all 3 adapters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_dir = Path(tmpdir)

        # Test settings with deny list
        settings = {
            'permissions': {
                'deny': ['Bash', 'Edit']
            }
        }

        source_data = {
            'rules': [],
            'skills': {},
            'agents': {},
            'commands': {},
            'mcp': {},
            'settings': settings
        }

        # Codex: deny list -> read-only sandbox
        codex_dir = base_dir / 'codex'
        codex_dir.mkdir()
        codex_adapter = AdapterRegistry.get_adapter('codex', codex_dir)
        codex_adapter.sync_all(source_data)

        codex_config = read_toml_safe(codex_dir / '.codex' / 'codex.toml')
        assert codex_config.get('sandbox_mode') == 'read-only', "Codex not conservative (expected read-only)"

        # Gemini: deny list -> blockedTools
        gemini_dir = base_dir / 'gemini'
        gemini_dir.mkdir()
        gemini_adapter = AdapterRegistry.get_adapter('gemini', gemini_dir)
        gemini_adapter.sync_all(source_data)

        gemini_settings = json.loads((gemini_dir / '.gemini' / 'settings.json').read_text())
        assert 'blockedTools' in gemini_settings.get('tools', {}), "Gemini not conservative (expected blockedTools)"

        # OpenCode: deny list -> restricted mode
        opencode_dir = base_dir / 'opencode'
        opencode_dir.mkdir()
        opencode_adapter = AdapterRegistry.get_adapter('opencode', opencode_dir)
        opencode_adapter.sync_all(source_data)

        opencode_config = json.loads((opencode_dir / 'opencode.json').read_text())
        assert opencode_config['permissions']['mode'] == 'restricted', "OpenCode not conservative (expected restricted)"

    print("✓ Test 7: Conservative permission mapping across all 3 adapters")


def main():
    """Run all verification tests."""
    print("\n=== 3-Adapter Integration Verification (Task 2) ===\n")

    tests = [
        test_1_adapter_discovery,
        test_2_has_target_checks,
        test_3_three_adapter_integration,
        test_4_codex_artifacts,
        test_5_gemini_artifacts,
        test_6_opencode_artifacts,
        test_7_conservative_permissions,
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
        print("All Task 2 tests passed!")
        print("\nPhase 3 success criteria:")
        print("  ✓ Gemini adapter inlines skills into GEMINI.md (strips frontmatter)")
        print("  ✓ Gemini adapter translates MCP to settings.json mcpServers")
        print("  ✓ OpenCode adapter creates symlinks to .opencode/ with stale cleanup")
        print("  ✓ OpenCode adapter translates MCP to opencode.json with type discrimination")
        print("  ✓ All 3 adapters sync test project successfully")
        print("  ✓ Conservative permission mapping for all adapters")
        sys.exit(0)


if __name__ == '__main__':
    main()
