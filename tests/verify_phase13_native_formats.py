#!/usr/bin/env python3
"""End-to-end verification script for Phase 13: Gemini Native Format Migration.

Verifies all 5 Phase 13 requirements:
- GMN-07: Skills written as native .gemini/skills/<name>/SKILL.md files
- GMN-08: Agents written as native .gemini/agents/<name>.md files
- GMN-09: Commands written as native .gemini/commands/<name>.toml files
- GMN-11: MCP field passthrough (trust, includeTools, excludeTools, cwd)
- GMN-12: Stale GEMINI.md subsection cleanup after migration
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.adapters.gemini import GeminiAdapter


# --- Test helpers ---

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = ""):
    """Record a PASS/FAIL check."""
    global passed, failed
    status = "PASS" if condition else "FAIL"
    suffix = f" -- {detail}" if detail and not condition else ""
    print(f"  [{status}] {label}{suffix}")
    if condition:
        passed += 1
    else:
        failed += 1


# --- Setup ---

def create_test_environment(tmpdir: Path):
    """Create isolated test environment with all source fixtures."""
    project_dir = tmpdir / "project"
    project_dir.mkdir(parents=True)

    # --- Skill fixture ---
    skill_dir = tmpdir / "source" / "skills" / "code-review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: Code Review\n"
        "description: Reviews code for quality and correctness\n"
        "---\n"
        "\n"
        "Review the provided code for:\n"
        "- Logic errors\n"
        "- Style issues\n"
        "- Security vulnerabilities\n",
        encoding="utf-8",
    )

    # --- Agent fixture (with color field to verify it's dropped) ---
    agent_dir = tmpdir / "source" / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "reviewer.md").write_text(
        "---\n"
        "name: Reviewer\n"
        "description: Code review specialist\n"
        "tools: eslint, ruff\n"
        "color: blue\n"
        "---\n"
        "\n"
        "<role>\n"
        "You are an expert code reviewer.\n"
        "Focus on correctness and maintainability.\n"
        "</role>\n",
        encoding="utf-8",
    )

    # --- Command fixture (with $ARGUMENTS) ---
    cmd_dir = tmpdir / "source" / "commands"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "lint.md").write_text(
        "---\n"
        "name: lint\n"
        "description: Run linter on files\n"
        "---\n"
        "\n"
        "Run the linter on $ARGUMENTS and report issues.\n",
        encoding="utf-8",
    )

    # --- Namespaced command fixture ---
    (cmd_dir / "test-sub.md").write_text(
        "---\n"
        "name: test:sub\n"
        "description: Run subset of tests\n"
        "---\n"
        "\n"
        "Run only the tests matching $ARGUMENTS.\n",
        encoding="utf-8",
    )

    # --- GEMINI.md with rules + stale subsections ---
    (project_dir / "GEMINI.md").write_text(
        "<!-- Managed by HarnessSync -->\n"
        "# Rules synced from Claude Code\n"
        "\n"
        "Always write tests.\n"
        "\n"
        "<!-- HarnessSync:Skills -->\n"
        "## Skill: Old Skill\n"
        "Old inlined skill content\n"
        "<!-- End HarnessSync:Skills -->\n"
        "\n"
        "<!-- HarnessSync:Agents -->\n"
        "## Agent: Old Agent\n"
        "Old inlined agent content\n"
        "<!-- End HarnessSync:Agents -->\n"
        "\n"
        "<!-- HarnessSync:Commands -->\n"
        "## Available Commands\n"
        "- /old-cmd: Old command\n"
        "<!-- End HarnessSync:Commands -->\n"
        "\n"
        "---\n"
        "*Last synced by HarnessSync: 2026-01-01*\n"
        "<!-- End HarnessSync managed content -->\n",
        encoding="utf-8",
    )

    # --- MCP server configs ---
    mcp_servers = {
        "my-server": {
            "command": "npx",
            "args": ["-y", "my-mcp-server"],
            "trust": True,
            "includeTools": ["tool_a", "tool_b"],
            "excludeTools": ["tool_c"],
            "cwd": "/home/user/project",
        }
    }

    return project_dir, skill_dir, agent_dir, cmd_dir, mcp_servers


# --- GMN-07: Skills ---

def verify_gmn07_skills(adapter: GeminiAdapter, skill_dir: Path, project_dir: Path):
    """Verify skills are written as native .gemini/skills/<name>/SKILL.md."""
    print("\n[GMN-07] Skills -> native .gemini/skills/<name>/SKILL.md")

    # Read GEMINI.md content before sync_skills
    gemini_before = (project_dir / "GEMINI.md").read_text(encoding="utf-8")

    skills = {"code-review": skill_dir}
    result = adapter.sync_skills(skills)

    # Check file exists
    target = project_dir / ".gemini" / "skills" / "code-review" / "SKILL.md"
    check("Native SKILL.md file exists", target.exists())

    if target.exists():
        content = target.read_text(encoding="utf-8")
        # Frontmatter preserved
        check("Frontmatter contains name", "name: Code Review" in content)
        check("Frontmatter contains description", "description:" in content)
        # Body preserved
        check("Body content preserved", "Review the provided code for:" in content)
        check("List items preserved", "- Logic errors" in content)

    # GEMINI.md NOT modified by sync_skills
    gemini_after = (project_dir / "GEMINI.md").read_text(encoding="utf-8")
    check("GEMINI.md not modified by sync_skills", gemini_before == gemini_after)

    # SyncResult correctness
    check("SyncResult synced=1", result.synced == 1)


# --- GMN-08: Agents ---

def verify_gmn08_agents(adapter: GeminiAdapter, agent_dir: Path, project_dir: Path):
    """Verify agents are written as native .gemini/agents/<name>.md."""
    print("\n[GMN-08] Agents -> native .gemini/agents/<name>.md")

    agents = {"reviewer": agent_dir / "reviewer.md"}
    result = adapter.sync_agents(agents)

    target = project_dir / ".gemini" / "agents" / "reviewer.md"
    check("Native agent .md file exists", target.exists())

    if target.exists():
        content = target.read_text(encoding="utf-8")
        # Frontmatter has required fields
        check("Frontmatter has name", "name:" in content and "Reviewer" in content)
        check("Frontmatter has description", "description:" in content)
        # Tools passed through
        check("Frontmatter has tools", "tools:" in content)
        check("Tool eslint present", "eslint" in content)
        check("Tool ruff present", "ruff" in content)
        # Color dropped
        check("Color field NOT in output", "color" not in content.lower() or "color:" not in content)
        # Body from <role> tags (stripped)
        check("Role body present", "expert code reviewer" in content)
        check("<role> tags stripped", "<role>" not in content)

    check("SyncResult synced=1", result.synced == 1)


# --- GMN-09: Commands ---

def verify_gmn09_commands(adapter: GeminiAdapter, cmd_dir: Path, project_dir: Path):
    """Verify commands are written as native .gemini/commands/<name>.toml."""
    print("\n[GMN-09] Commands -> native .gemini/commands/<name>.toml")

    commands = {
        "lint": cmd_dir / "lint.md",
        "test-sub": cmd_dir / "test-sub.md",
    }
    result = adapter.sync_commands(commands)

    # Simple command
    lint_toml = project_dir / ".gemini" / "commands" / "lint.toml"
    check("lint.toml exists", lint_toml.exists())

    if lint_toml.exists():
        content = lint_toml.read_text(encoding="utf-8")
        check("Has description field", 'description = "' in content)
        check("Has prompt field with triple-quote", 'prompt = """' in content)
        check("$ARGUMENTS replaced with {{args}}", "{{args}}" in content)
        check("$ARGUMENTS not present", "$ARGUMENTS" not in content)

    # Namespaced command: test:sub -> test/sub.toml
    sub_toml = project_dir / ".gemini" / "commands" / "test" / "sub.toml"
    check("Namespaced test/sub.toml exists", sub_toml.exists())

    if sub_toml.exists():
        content = sub_toml.read_text(encoding="utf-8")
        check("Namespaced command has prompt", 'prompt = """' in content)
        check("Namespaced command has {{args}}", "{{args}}" in content)

    check("SyncResult synced=2", result.synced == 2)


# --- GMN-11: MCP field passthrough ---

def verify_gmn11_mcp_fields(adapter: GeminiAdapter, mcp_servers: dict, project_dir: Path):
    """Verify MCP field passthrough (trust, includeTools, excludeTools, cwd)."""
    print("\n[GMN-11] MCP field passthrough")

    result = adapter.sync_mcp(mcp_servers)

    settings_path = project_dir / ".gemini" / "settings.json"
    check("settings.json exists", settings_path.exists())

    if settings_path.exists():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        server = settings.get("mcpServers", {}).get("my-server", {})

        check("trust field present", "trust" in server, f"keys: {list(server.keys())}")
        check("trust value is True", server.get("trust") is True)
        check("includeTools field present", "includeTools" in server)
        check("includeTools value correct", server.get("includeTools") == ["tool_a", "tool_b"])
        check("excludeTools field present", "excludeTools" in server)
        check("excludeTools value correct", server.get("excludeTools") == ["tool_c"])
        check("cwd field present", "cwd" in server)
        check("cwd value correct", server.get("cwd") == "/home/user/project")
        # Standard fields also present
        check("command field present", server.get("command") == "npx")
        check("args field present", server.get("args") == ["-y", "my-mcp-server"])

    check("SyncResult synced=1", result.synced == 1)


# --- GMN-12: Stale subsection cleanup ---

def verify_gmn12_cleanup(adapter: GeminiAdapter, project_dir: Path):
    """Verify stale subsection cleanup from GEMINI.md."""
    print("\n[GMN-12] Stale GEMINI.md subsection cleanup")

    removed = adapter.cleanup_legacy_inline_sections()

    check("Cleanup returned count=3", removed == 3, f"got {removed}")

    content = (project_dir / "GEMINI.md").read_text(encoding="utf-8")

    # Subsection markers removed
    check("Skills marker removed", "<!-- HarnessSync:Skills -->" not in content)
    check("Agents marker removed", "<!-- HarnessSync:Agents -->" not in content)
    check("Commands marker removed", "<!-- HarnessSync:Commands -->" not in content)
    check("End Skills marker removed", "<!-- End HarnessSync:Skills -->" not in content)
    check("End Agents marker removed", "<!-- End HarnessSync:Agents -->" not in content)
    check("End Commands marker removed", "<!-- End HarnessSync:Commands -->" not in content)

    # Inlined content removed
    check("Old skill content removed", "Old inlined skill content" not in content)
    check("Old agent content removed", "Old inlined agent content" not in content)
    check("Old command content removed", "/old-cmd" not in content)

    # Rules managed section preserved
    check("Managed marker preserved", "<!-- Managed by HarnessSync -->" in content)
    check("End managed marker preserved", "<!-- End HarnessSync managed content -->" in content)
    check("Rules content preserved", "Always write tests." in content)

    # Idempotency
    removed2 = adapter.cleanup_legacy_inline_sections()
    check("Idempotent (second run returns 0)", removed2 == 0, f"got {removed2}")


# --- Full sync_all integration ---

def verify_sync_all_integration(tmpdir: Path):
    """Verify full sync_all produces native files AND clean GEMINI.md."""
    print("\n[INTEGRATION] sync_all produces native files + clean GEMINI.md")

    project_dir, skill_dir, agent_dir, cmd_dir, mcp_servers = create_test_environment(tmpdir / "integration")

    adapter = GeminiAdapter(project_dir)

    source_data = {
        "rules": [{"path": Path("rule.md"), "content": "Always write tests."}],
        "skills": {"code-review": skill_dir},
        "agents": {"reviewer": agent_dir / "reviewer.md"},
        "commands": {"lint": cmd_dir / "lint.md"},
        "mcp": mcp_servers,
        "settings": {},
    }

    results = adapter.sync_all(source_data)

    # Native files exist
    check("Skills native file created", (project_dir / ".gemini" / "skills" / "code-review" / "SKILL.md").exists())
    check("Agents native file created", (project_dir / ".gemini" / "agents" / "reviewer.md").exists())
    check("Commands native file created", (project_dir / ".gemini" / "commands" / "lint.toml").exists())
    check("MCP settings.json created", (project_dir / ".gemini" / "settings.json").exists())

    # GEMINI.md cleaned
    content = (project_dir / "GEMINI.md").read_text(encoding="utf-8")
    check("GEMINI.md has no Skills subsection", "<!-- HarnessSync:Skills -->" not in content)
    check("GEMINI.md has no Agents subsection", "<!-- HarnessSync:Agents -->" not in content)
    check("GEMINI.md has no Commands subsection", "<!-- HarnessSync:Commands -->" not in content)
    check("GEMINI.md still has rules", "Always write tests." in content)
    check("GEMINI.md still has managed markers", "<!-- Managed by HarnessSync -->" in content)

    # All sync results succeeded
    for key in ("rules", "skills", "agents", "commands", "mcp"):
        r = results.get(key)
        check(f"sync_{key} had 0 failures", r is not None and r.failed == 0, f"result: {r}")


# --- Main ---

def run_all():
    """Run all Phase 13 verification checks."""
    print("=" * 65)
    print("PHASE 13 VERIFICATION: Gemini Native Format Migration")
    print("=" * 65)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)

        # Create shared test environment for individual checks
        project_dir, skill_dir, agent_dir, cmd_dir, mcp_servers = create_test_environment(tmpdir / "unit")
        adapter = GeminiAdapter(project_dir)

        # Individual requirement checks
        verify_gmn07_skills(adapter, skill_dir, project_dir)
        verify_gmn08_agents(adapter, agent_dir, project_dir)
        verify_gmn09_commands(adapter, cmd_dir, project_dir)
        verify_gmn11_mcp_fields(adapter, mcp_servers, project_dir)
        verify_gmn12_cleanup(adapter, project_dir)

        # Full integration check
        verify_sync_all_integration(tmpdir)

    print()
    print("=" * 65)
    global passed, failed
    total = passed + failed
    if failed == 0:
        print(f"ALL {total} CHECKS PASSED")
    else:
        print(f"FAILED: {failed}/{total} checks")
    print("=" * 65)
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(run_all())
