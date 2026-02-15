#!/usr/bin/env python3
"""Verification script for Task 1: GeminiAdapter rules, skills, agents, commands + write_json_atomic."""

import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.adapters.gemini import GeminiAdapter
from src.utils.paths import write_json_atomic


def test_write_json_atomic():
    """Test write_json_atomic creates valid JSON file atomically."""
    print("TEST 1: write_json_atomic creates valid JSON...")

    with tempfile.TemporaryDirectory() as tmpdir:
        json_path = Path(tmpdir) / "test.json"
        test_data = {"key": "value", "number": 42, "list": [1, 2, 3]}

        # Write atomically
        write_json_atomic(json_path, test_data)

        # Verify file exists
        assert json_path.exists(), "JSON file not created"

        # Verify content is valid JSON
        import json
        with open(json_path, 'r') as f:
            loaded = json.load(f)

        assert loaded == test_data, "JSON content mismatch"

    print("  ✓ write_json_atomic works correctly")


def test_write_json_atomic_import():
    """Test that write_json_atomic is importable from src.utils.paths."""
    print("TEST 2: write_json_atomic is importable...")

    from src.utils.paths import write_json_atomic as imported_func
    assert callable(imported_func), "write_json_atomic is not callable"

    print("  ✓ write_json_atomic is importable and callable")


def test_sync_rules():
    """Test sync_rules writes rules to GEMINI.md with markers."""
    print("TEST 3: sync_rules writes to GEMINI.md with markers...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Create mock rules
        rules = [
            {'path': Path('rule1.md'), 'content': 'Rule 1 content'},
            {'path': Path('rule2.md'), 'content': 'Rule 2 content'},
        ]

        # Sync rules
        result = adapter.sync_rules(rules)

        # Verify result
        assert result.synced == 1, f"Expected synced=1, got {result.synced}"
        assert result.adapted == 2, f"Expected adapted=2, got {result.adapted}"

        # Verify GEMINI.md exists and contains expected content
        gemini_md = project_dir / "GEMINI.md"
        assert gemini_md.exists(), "GEMINI.md not created"

        content = gemini_md.read_text()
        assert "<!-- Managed by HarnessSync -->" in content, "Missing start marker"
        assert "<!-- End HarnessSync managed content -->" in content, "Missing end marker"
        assert "Rule 1 content" in content, "Rule 1 content not found"
        assert "Rule 2 content" in content, "Rule 2 content not found"

    print("  ✓ sync_rules works correctly")


def test_sync_skills():
    """Test sync_skills strips frontmatter and inlines to GEMINI.md."""
    print("TEST 4: sync_skills strips frontmatter and inlines...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Create mock skill directory with SKILL.md
        skill_dir = Path(tmpdir) / "skills" / "test-skill"
        skill_dir.mkdir(parents=True)

        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("""---
name: Test Skill
description: A test skill
---

This is the skill body content.

## Additional Section

More content here.""")

        # Sync skills
        skills = {"test-skill": skill_dir}
        result = adapter.sync_skills(skills)

        # Verify result
        assert result.synced == 1, f"Expected synced=1, got {result.synced}"
        assert result.adapted == 1, f"Expected adapted=1, got {result.adapted}"

        # Verify GEMINI.md contains inlined skill without frontmatter
        gemini_md = project_dir / "GEMINI.md"
        assert gemini_md.exists(), "GEMINI.md not created"

        content = gemini_md.read_text()
        assert "<!-- HarnessSync:Skills -->" in content, "Missing skills marker"
        assert "## Skill: Test Skill" in content, "Skill header not found"
        assert "**Purpose:** A test skill" in content, "Purpose not found"
        assert "This is the skill body content." in content, "Skill body not found"
        assert "---\nname: Test Skill" not in content, "YAML frontmatter not stripped"

    print("  ✓ sync_skills works correctly")


def test_sync_agents():
    """Test sync_agents extracts role section and inlines to GEMINI.md."""
    print("TEST 5: sync_agents extracts role and inlines...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Create mock agent file
        agents_dir = Path(tmpdir) / "agents"
        agents_dir.mkdir()

        agent_md = agents_dir / "test-agent.md"
        agent_md.write_text("""---
name: Test Agent
description: An agent for testing
---

Some preamble text.

<role>
Agent role instructions go here.
This is what the agent should do.
</role>

Some additional content.""")

        # Sync agents
        agents = {"test-agent": agent_md}
        result = adapter.sync_agents(agents)

        # Verify result
        assert result.synced == 1, f"Expected synced=1, got {result.synced}"
        assert result.adapted == 1, f"Expected adapted=1, got {result.adapted}"

        # Verify GEMINI.md contains agent section
        gemini_md = project_dir / "GEMINI.md"
        assert gemini_md.exists(), "GEMINI.md not created"

        content = gemini_md.read_text()
        assert "<!-- HarnessSync:Agents -->" in content, "Missing agents marker"
        assert "## Agent: Test Agent" in content, "Agent header not found"
        assert "**Description:** An agent for testing" in content, "Description not found"
        assert "Agent role instructions go here." in content, "Role content not found"
        assert "<role>" not in content, "Role tags not stripped"

    print("  ✓ sync_agents works correctly")


def test_sync_commands():
    """Test sync_commands creates brief descriptions in GEMINI.md."""
    print("TEST 6: sync_commands creates brief descriptions...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Create mock command files
        commands_dir = Path(tmpdir) / "commands"
        commands_dir.mkdir()

        cmd1 = commands_dir / "cmd1.md"
        cmd1.write_text("""---
name: test-cmd
description: A test command
---

Full command content here.""")

        cmd2 = commands_dir / "cmd2.md"
        cmd2.write_text("""---
name: another-cmd
description: Another command
---

More content.""")

        # Sync commands
        commands = {"cmd1": cmd1, "cmd2": cmd2}
        result = adapter.sync_commands(commands)

        # Verify result
        assert result.synced == 2, f"Expected synced=2, got {result.synced}"
        assert result.adapted == 2, f"Expected adapted=2, got {result.adapted}"

        # Verify GEMINI.md contains command summaries
        gemini_md = project_dir / "GEMINI.md"
        assert gemini_md.exists(), "GEMINI.md not created"

        content = gemini_md.read_text()
        assert "<!-- HarnessSync:Commands -->" in content, "Missing commands marker"
        assert "## Available Commands" in content, "Commands header not found"
        assert "- **/test-cmd**: A test command" in content, "Command 1 not found"
        assert "- **/another-cmd**: Another command" in content, "Command 2 not found"
        assert "Full command content here." not in content, "Full content should not be included"

    print("  ✓ sync_commands works correctly")


def test_idempotency():
    """Test that re-syncing rules replaces markers without duplication."""
    print("TEST 7: Idempotency - re-sync replaces markers...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # First sync
        rules = [{'path': Path('rule1.md'), 'content': 'Original content'}]
        adapter.sync_rules(rules)

        # Second sync with different content
        rules = [{'path': Path('rule1.md'), 'content': 'Updated content'}]
        adapter.sync_rules(rules)

        # Verify only one managed section exists
        gemini_md = project_dir / "GEMINI.md"
        content = gemini_md.read_text()

        marker_count = content.count("<!-- Managed by HarnessSync -->")
        assert marker_count == 1, f"Expected 1 marker, found {marker_count} (duplication detected)"

        assert "Updated content" in content, "Updated content not found"
        assert "Original content" not in content, "Old content not replaced"

    print("  ✓ Idempotency works correctly")


def test_user_content_preservation():
    """Test that user content outside markers is preserved."""
    print("TEST 8: User content outside markers is preserved...")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        adapter = GeminiAdapter(project_dir)

        # Create GEMINI.md with user content
        gemini_md = project_dir / "GEMINI.md"
        gemini_md.write_text("""# My Custom Header

User content before HarnessSync section.

This should be preserved.""")

        # Sync rules
        rules = [{'path': Path('rule1.md'), 'content': 'Rule content'}]
        adapter.sync_rules(rules)

        # Verify user content is still present
        content = gemini_md.read_text()

        assert "# My Custom Header" in content, "User header not preserved"
        assert "User content before HarnessSync section." in content, "User content not preserved"
        assert "Rule content" in content, "Rule content not added"

    print("  ✓ User content preservation works correctly")


def run_all_tests():
    """Run all verification tests."""
    print("=" * 60)
    print("TASK 1 VERIFICATION: GeminiAdapter + write_json_atomic")
    print("=" * 60)
    print()

    tests = [
        test_write_json_atomic,
        test_write_json_atomic_import,
        test_sync_rules,
        test_sync_skills,
        test_sync_agents,
        test_sync_commands,
        test_idempotency,
        test_user_content_preservation,
    ]

    failed = 0
    for test in tests:
        try:
            test()
        except AssertionError as e:
            print(f"  ✗ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {e}")
            failed += 1

    print()
    print("=" * 60)
    if failed == 0:
        print("ALL TESTS PASSED ✓")
        print("=" * 60)
        return 0
    else:
        print(f"FAILED: {failed}/{len(tests)} tests")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
