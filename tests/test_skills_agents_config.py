from __future__ import annotations

"""Tests for Slice 3: Skills, Agents, and Config Updates.

Covers:
- @include resolution: happy path, self-referential cycle, diamond dependency,
  missing file, depth=10 limit, depth=11 rejection
- Gemini @file.md native import conversion
- OpenCode instructions array (multi-source vs single-source)
- OpenCode agent config new shape
- Codex hierarchical AGENTS.md from subdirectory rules
- Skill frontmatter passthrough verification
- SourceReader include_refs in discover_all()
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.includes import resolve_includes, extract_include_refs, MAX_INCLUDE_DEPTH
from src.source_reader import SourceReader
from src.adapters.codex import CodexAdapter
from src.adapters.gemini import GeminiAdapter
from src.adapters.opencode import OpenCodeAdapter


# ---------------------------------------------------------------------------
# @include resolution tests
# ---------------------------------------------------------------------------

class TestResolveIncludes:
    """Test resolve_includes() with various scenarios."""

    def test_happy_path_single_include(self, tmp_path):
        """Single @include resolves to inlined content."""
        # Create included file
        inc = tmp_path / "extra.md"
        inc.write_text("Extra content here.", encoding="utf-8")

        content = "Before\n@include extra.md\nAfter"
        result, paths = resolve_includes(content, tmp_path)

        assert "Extra content here." in result
        assert "Before" in result
        assert "After" in result
        assert "@include" not in result
        assert inc.resolve() in paths

    def test_happy_path_multiple_includes(self, tmp_path):
        """Multiple @include directives all resolve."""
        (tmp_path / "a.md").write_text("Content A", encoding="utf-8")
        (tmp_path / "b.md").write_text("Content B", encoding="utf-8")

        content = "@include a.md\n---\n@include b.md"
        result, paths = resolve_includes(content, tmp_path)

        assert "Content A" in result
        assert "Content B" in result
        assert len(paths) == 2

    def test_nested_includes(self, tmp_path):
        """Nested @include (A includes B) resolves recursively."""
        (tmp_path / "inner.md").write_text("Inner content", encoding="utf-8")
        (tmp_path / "outer.md").write_text("Start\n@include inner.md\nEnd", encoding="utf-8")

        content = "@include outer.md"
        result, paths = resolve_includes(content, tmp_path)

        assert "Inner content" in result
        assert "Start" in result
        assert "End" in result
        assert len(paths) == 2  # outer.md and inner.md

    def test_self_referential_cycle(self, tmp_path):
        """Self-referential @include (file includes itself) is detected."""
        self_ref = tmp_path / "self.md"
        self_ref.write_text("Hello\n@include self.md\nWorld", encoding="utf-8")

        content = "@include self.md"
        result, paths = resolve_includes(content, tmp_path)

        assert "Hello" in result
        assert "circular include detected" in result
        assert "World" in result

    def test_mutual_cycle(self, tmp_path):
        """Mutual cycle (A -> B -> A) is detected."""
        (tmp_path / "a.md").write_text("A-start\n@include b.md\nA-end", encoding="utf-8")
        (tmp_path / "b.md").write_text("B-start\n@include a.md\nB-end", encoding="utf-8")

        content = "@include a.md"
        result, paths = resolve_includes(content, tmp_path)

        assert "A-start" in result
        assert "B-start" in result
        assert "circular include detected" in result

    def test_diamond_dependency(self, tmp_path):
        """Diamond: A->B, A->C, B->D, C->D. D is included twice but not a cycle."""
        (tmp_path / "d.md").write_text("Diamond content", encoding="utf-8")
        (tmp_path / "b.md").write_text("B\n@include d.md", encoding="utf-8")
        (tmp_path / "c.md").write_text("C\n@include d.md", encoding="utf-8")

        content = "@include b.md\n@include c.md"
        result, paths = resolve_includes(content, tmp_path)

        # D is included from both B and C -- not a cycle (different branches)
        assert result.count("Diamond content") == 2
        assert "circular include detected" not in result

    def test_missing_file_graceful_skip(self, tmp_path):
        """Missing included file produces a comment, not an error."""
        content = "Before\n@include nonexistent.md\nAfter"
        result, paths = resolve_includes(content, tmp_path)

        assert "file not found" in result
        assert "Before" in result
        assert "After" in result
        assert len(paths) == 0

    def test_depth_10_allowed(self, tmp_path):
        """10 levels of nesting is allowed (depth 10 is valid).

        Chain: content -> level0(depth 1) -> level1(depth 2) -> ... -> level9(depth 10)
        level9 is at depth 10, which is the maximum allowed depth.
        """
        # Create chain of exactly 10 deep: level0 -> level1 -> ... -> level9
        for i in range(MAX_INCLUDE_DEPTH):  # 0..9
            if i == MAX_INCLUDE_DEPTH - 1:
                (tmp_path / f"level{i}.md").write_text(f"Leaf at level {i}", encoding="utf-8")
            else:
                (tmp_path / f"level{i}.md").write_text(f"Level {i}\n@include level{i+1}.md", encoding="utf-8")

        content = "@include level0.md"
        result, paths = resolve_includes(content, tmp_path)

        assert f"Leaf at level {MAX_INCLUDE_DEPTH - 1}" in result
        assert "max include depth" not in result

    def test_depth_11_rejected(self, tmp_path):
        """11 levels of nesting exceeds the limit and is rejected.

        Chain: content -> level0(1) -> level1(2) -> ... -> level10(11)
        level10 is at depth 11, which exceeds the maximum.
        """
        # Create chain of 11 deep: level0 -> level1 -> ... -> level10
        for i in range(MAX_INCLUDE_DEPTH + 1):  # 0..10
            if i == MAX_INCLUDE_DEPTH:
                (tmp_path / f"level{i}.md").write_text(f"Leaf at level {i}", encoding="utf-8")
            else:
                (tmp_path / f"level{i}.md").write_text(f"Level {i}\n@include level{i+1}.md", encoding="utf-8")

        content = "@include level0.md"
        result, paths = resolve_includes(content, tmp_path)

        assert "max include depth" in result
        # The leaf at level 10 should NOT be inlined
        assert f"Leaf at level {MAX_INCLUDE_DEPTH}" not in result

    def test_include_after_whitespace(self, tmp_path):
        """@include after whitespace (indented) is recognized."""
        (tmp_path / "inc.md").write_text("Included", encoding="utf-8")

        content = "  @include inc.md"
        result, paths = resolve_includes(content, tmp_path)

        assert "Included" in result

    def test_no_includes(self, tmp_path):
        """Content without @include passes through unchanged."""
        content = "No includes here\nJust plain text"
        result, paths = resolve_includes(content, tmp_path)

        assert result == content
        assert paths == []

    def test_include_in_code_block_still_resolves(self, tmp_path):
        """@include at start of line inside text still resolves (by design)."""
        (tmp_path / "x.md").write_text("Resolved", encoding="utf-8")
        content = "```\n@include x.md\n```"
        result, paths = resolve_includes(content, tmp_path)
        # By design, we do resolve (no code-block awareness)
        assert "Resolved" in result

    def test_relative_path_resolution(self, tmp_path):
        """Relative paths resolve against base_dir."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.md").write_text("Nested file", encoding="utf-8")

        content = "@include sub/nested.md"
        result, paths = resolve_includes(content, tmp_path)

        assert "Nested file" in result


class TestExtractIncludeRefs:
    """Test extract_include_refs() for raw path extraction."""

    def test_extracts_paths(self):
        content = "Hello\n@include foo.md\nWorld\n@include bar/baz.md"
        refs = extract_include_refs(content)
        assert refs == ["foo.md", "bar/baz.md"]

    def test_empty_content(self):
        assert extract_include_refs("") == []

    def test_no_includes(self):
        assert extract_include_refs("Just text\nNo directives") == []


# ---------------------------------------------------------------------------
# SourceReader include_refs integration
# ---------------------------------------------------------------------------

class TestSourceReaderIncludes:
    """Test SourceReader integration with @include resolution."""

    def test_get_rules_resolves_includes(self, tmp_path):
        """get_rules() resolves @include directives in CLAUDE.md."""
        # Set up project with CLAUDE.md containing @include
        project = tmp_path / "project"
        project.mkdir()
        (project / "extra.md").write_text("Extra rules here", encoding="utf-8")
        (project / "CLAUDE.md").write_text(
            "Main rules\n@include extra.md",
            encoding="utf-8",
        )

        reader = SourceReader(scope="project", project_dir=project)
        rules = reader.get_rules()

        assert "Extra rules here" in rules
        assert "@include" not in rules

    def test_discover_all_includes_include_refs(self, tmp_path):
        """discover_all() exposes include_refs."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "extra.md").write_text("Extra", encoding="utf-8")
        (project / "CLAUDE.md").write_text(
            "Main\n@include extra.md",
            encoding="utf-8",
        )

        reader = SourceReader(scope="project", project_dir=project)
        data = reader.discover_all()

        assert "include_refs" in data
        assert "extra.md" in data["include_refs"]

    def test_discover_all_no_includes(self, tmp_path):
        """discover_all() returns empty include_refs when no @include found."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "CLAUDE.md").write_text("No includes", encoding="utf-8")

        reader = SourceReader(scope="project", project_dir=project)
        data = reader.discover_all()

        assert data["include_refs"] == []


# ---------------------------------------------------------------------------
# Gemini @file.md native import conversion
# ---------------------------------------------------------------------------

class TestGeminiNativeImports:
    """Test Gemini adapter @include -> @file.md conversion."""

    def test_convert_includes_to_native(self):
        """@include foo.md -> @foo.md"""
        content = "Some rules\n@include foo.md\nMore rules"
        result = GeminiAdapter.convert_includes_to_native(content)

        assert "@foo.md" in result
        assert "@include" not in result
        assert "Some rules" in result
        assert "More rules" in result

    def test_convert_multiple_includes(self):
        """Multiple @include directives all convert."""
        content = "@include a.md\n@include path/to/b.md"
        result = GeminiAdapter.convert_includes_to_native(content)

        assert "@a.md" in result
        assert "@path/to/b.md" in result
        assert "@include" not in result

    def test_no_includes_passthrough(self):
        """Content without @include passes through unchanged."""
        content = "Plain text rules\nNo directives"
        result = GeminiAdapter.convert_includes_to_native(content)
        assert result == content

    def test_sync_rules_with_include_refs(self, tmp_path):
        """sync_rules uses native conversion when include_refs provided."""
        adapter = GeminiAdapter(tmp_path)
        rules = [{"path": tmp_path / "test.md", "content": "Rules\n@include extra.md"}]
        result = adapter.sync_rules(rules, include_refs=["extra.md"])

        assert result.synced == 1
        # Read the written GEMINI.md
        gemini_md = tmp_path / "GEMINI.md"
        assert gemini_md.exists()
        content = gemini_md.read_text(encoding="utf-8")
        assert "@extra.md" in content
        assert "@include" not in content

    def test_sync_rules_without_include_refs(self, tmp_path):
        """sync_rules without include_refs does not convert."""
        adapter = GeminiAdapter(tmp_path)
        rules = [{"path": tmp_path / "test.md", "content": "Rules\n@include extra.md"}]
        result = adapter.sync_rules(rules)

        assert result.synced == 1
        content = (tmp_path / "GEMINI.md").read_text(encoding="utf-8")
        # Without include_refs, @include is left as-is (already resolved by SourceReader)
        assert "@include extra.md" in content


# ---------------------------------------------------------------------------
# OpenCode instructions array (multi-source vs single-source)
# ---------------------------------------------------------------------------

class TestOpenCodeInstructionsArray:
    """Test OpenCode instructions array for multi-source rules."""

    def test_single_source_writes_agents_md(self, tmp_path):
        """Single rule source writes AGENTS.md (backward compat)."""
        adapter = OpenCodeAdapter(tmp_path)
        rules = [{"path": tmp_path / "rules.md", "content": "Single rule"}]
        result = adapter.sync_rules(rules)

        assert result.synced == 1
        agents_md = tmp_path / "AGENTS.md"
        assert agents_md.exists()
        assert "Single rule" in agents_md.read_text()
        # opencode.json should NOT have instructions array
        oc_json = tmp_path / "opencode.json"
        if oc_json.exists():
            data = json.loads(oc_json.read_text())
            assert "instructions" not in data

    def test_multi_source_writes_instructions_array(self, tmp_path):
        """Multiple rule sources write .opencode/rules/ + instructions array."""
        adapter = OpenCodeAdapter(tmp_path)
        rules = [
            {"path": tmp_path / "user.md", "content": "User rules", "scope": "user"},
            {"path": tmp_path / "project.md", "content": "Project rules", "scope": "project"},
        ]
        result = adapter.sync_rules(rules)

        # Should have written individual rule files
        rules_dir = tmp_path / ".opencode" / "rules"
        assert rules_dir.is_dir()
        rule_files = list(rules_dir.glob("*.md"))
        assert len(rule_files) == 2

        # Should have instructions array in opencode.json
        oc_json = tmp_path / "opencode.json"
        assert oc_json.exists()
        data = json.loads(oc_json.read_text())
        assert "instructions" in data
        assert len(data["instructions"]) == 2
        assert all(p.startswith(".opencode/rules/") for p in data["instructions"])

    def test_multi_source_rule_file_contents(self, tmp_path):
        """Individual rule files contain the correct content."""
        adapter = OpenCodeAdapter(tmp_path)
        rules = [
            {"path": tmp_path / "user.md", "content": "User rules content", "scope": "user"},
            {"path": tmp_path / "project.md", "content": "Project rules content", "scope": "project"},
        ]
        adapter.sync_rules(rules)

        rules_dir = tmp_path / ".opencode" / "rules"
        contents = {f.name: f.read_text() for f in rules_dir.glob("*.md")}

        # Verify contents match
        user_file = [v for k, v in contents.items() if "user" in k]
        project_file = [v for k, v in contents.items() if "project" in k]
        assert user_file and "User rules content" in user_file[0]
        assert project_file and "Project rules content" in project_file[0]


# ---------------------------------------------------------------------------
# OpenCode agent config new shape
# ---------------------------------------------------------------------------

class TestOpenCodeAgentConfig:
    """Test OpenCode new agent config shape (replacing deprecated 'mode')."""

    def test_agent_config_shape(self, tmp_path):
        """sync_agents writes new agent config shape to opencode.json."""
        adapter = OpenCodeAdapter(tmp_path)

        # Create agent files
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        dev_agent = agents_dir / "developer.md"
        dev_agent.write_text(
            "---\nname: developer\ndescription: Dev agent\n---\n\nYou are a developer.",
            encoding="utf-8",
        )
        explorer_agent = agents_dir / "explorer.md"
        explorer_agent.write_text(
            "---\nname: explorer\ndescription: Explorer agent\n---\n\nYou explore code.",
            encoding="utf-8",
        )

        agents = {"developer": dev_agent, "explorer": explorer_agent}
        result = adapter.sync_agents(agents)

        # Verify opencode.json has new agent shape
        oc_json = tmp_path / "opencode.json"
        assert oc_json.exists()
        data = json.loads(oc_json.read_text())

        assert "agent" in data
        assert "mode" not in data  # deprecated key removed
        assert "primary" in data["agent"]
        assert "agents" in data["agent"]
        assert "developer" in data["agent"]["agents"]
        assert "explorer" in data["agent"]["agents"]
        assert "instructions" in data["agent"]["agents"]["developer"]
        assert "You are a developer." in data["agent"]["agents"]["developer"]["instructions"]

    def test_agent_config_removes_deprecated_mode(self, tmp_path):
        """sync_agents removes deprecated 'mode' key from opencode.json."""
        # Pre-populate with deprecated mode key
        oc_json = tmp_path / "opencode.json"
        oc_json.write_text(json.dumps({"mode": "old-mode"}), encoding="utf-8")

        adapter = OpenCodeAdapter(tmp_path)
        agent_file = tmp_path / "dev.md"
        agent_file.write_text("---\nname: dev\n---\n\nDev instructions.", encoding="utf-8")

        adapter.sync_agents({"dev": agent_file})

        data = json.loads(oc_json.read_text())
        assert "mode" not in data
        assert "agent" in data

    def test_agent_config_primary_deterministic(self, tmp_path):
        """Primary agent is first in sorted order (deterministic)."""
        adapter = OpenCodeAdapter(tmp_path)
        for name in ["zephyr", "alpha", "beta"]:
            f = tmp_path / f"{name}.md"
            f.write_text(f"Instructions for {name}", encoding="utf-8")

        agents = {name: tmp_path / f"{name}.md" for name in ["zephyr", "alpha", "beta"]}
        adapter.sync_agents(agents)

        data = json.loads((tmp_path / "opencode.json").read_text())
        assert data["agent"]["primary"] == "alpha"

    def test_extract_agent_instructions_with_frontmatter(self):
        """_extract_agent_instructions strips frontmatter."""
        content = "---\nname: test\ndescription: Test\n---\n\nThe instructions."
        result = OpenCodeAdapter._extract_agent_instructions(content)
        assert result == "The instructions."

    def test_extract_agent_instructions_without_frontmatter(self):
        """_extract_agent_instructions returns full content when no frontmatter."""
        content = "Just instructions, no frontmatter."
        result = OpenCodeAdapter._extract_agent_instructions(content)
        assert result == "Just instructions, no frontmatter."


# ---------------------------------------------------------------------------
# Codex hierarchical AGENTS.md from subdirectory rules
# ---------------------------------------------------------------------------

class TestCodexHierarchicalAgentsMd:
    """Test Codex adapter writing subdirectory AGENTS.md from rules_files."""

    def test_subdirectory_agents_md_from_scoped_rules(self, tmp_path):
        """rules_files with scope_patterns create subdirectory AGENTS.md."""
        # Create the subdirectory that the pattern references
        src_api = tmp_path / "src" / "api"
        src_api.mkdir(parents=True)

        adapter = CodexAdapter(tmp_path)
        rules = [{"path": tmp_path / "main.md", "content": "Main rules"}]
        rules_files = [
            {
                "path": tmp_path / ".claude" / "rules" / "api-rules.md",
                "content": "API-specific rules here",
                "scope_patterns": ["src/api/**/*.ts"],
                "scope": "project",
            }
        ]

        result = adapter.sync_rules(rules, rules_files=rules_files)

        # Main AGENTS.md should exist
        assert (tmp_path / "AGENTS.md").exists()

        # Subdirectory AGENTS.md should exist
        sub_agents = src_api / "AGENTS.md"
        assert sub_agents.exists()
        content = sub_agents.read_text()
        assert "API-specific rules here" in content
        assert "Managed by HarnessSync" in content

    def test_no_subdirectory_when_dir_missing(self, tmp_path):
        """If referenced directory doesn't exist, no subdirectory AGENTS.md created."""
        adapter = CodexAdapter(tmp_path)
        rules = [{"path": tmp_path / "main.md", "content": "Main rules"}]
        rules_files = [
            {
                "path": tmp_path / "rules.md",
                "content": "Rules for nonexistent dir",
                "scope_patterns": ["nonexistent/dir/**"],
                "scope": "project",
            }
        ]

        result = adapter.sync_rules(rules, rules_files=rules_files)

        # Only root AGENTS.md, no subdirectory one
        assert (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / "nonexistent" / "dir" / "AGENTS.md").exists()

    def test_no_subdirectory_for_rules_without_patterns(self, tmp_path):
        """rules_files without scope_patterns don't create subdirectory AGENTS.md."""
        adapter = CodexAdapter(tmp_path)
        rules = [{"path": tmp_path / "main.md", "content": "Main rules"}]
        rules_files = [
            {
                "path": tmp_path / "rules.md",
                "content": "General rules",
                "scope_patterns": [],
                "scope": "project",
            }
        ]

        result = adapter.sync_rules(rules, rules_files=rules_files)
        # Only root AGENTS.md
        assert (tmp_path / "AGENTS.md").exists()

    def test_extract_subdir_from_pattern(self):
        """_extract_subdir_from_pattern extracts directory prefix correctly."""
        assert CodexAdapter._extract_subdir_from_pattern("src/api/**/*.ts") == "src/api"
        assert CodexAdapter._extract_subdir_from_pattern("src/components/*") == "src/components"
        assert CodexAdapter._extract_subdir_from_pattern("**/*.py") == ""
        assert CodexAdapter._extract_subdir_from_pattern("docs/") == "docs"
        assert CodexAdapter._extract_subdir_from_pattern("*.md") == ""
        assert CodexAdapter._extract_subdir_from_pattern("src/") == "src"

    def test_sync_all_passes_rules_files(self, tmp_path):
        """Codex sync_all passes rules_files from source_data to sync_rules."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()

        adapter = CodexAdapter(tmp_path)
        source_data = {
            "rules": [{"path": tmp_path / "main.md", "content": "Main rules"}],
            "rules_files": [
                {
                    "path": tmp_path / "scoped.md",
                    "content": "Scoped rules",
                    "scope_patterns": ["src/**"],
                    "scope": "project",
                }
            ],
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp": {},
            "settings": {},
        }

        results = adapter.sync_all(source_data)

        assert results["rules"].synced >= 1
        # Subdirectory AGENTS.md should exist
        assert (tmp_path / "src" / "AGENTS.md").exists()


# ---------------------------------------------------------------------------
# Skill frontmatter passthrough
# ---------------------------------------------------------------------------

class TestSkillFrontmatterPassthrough:
    """Verify skill frontmatter (including new fields) passes through."""

    def test_gemini_preserves_frontmatter(self, tmp_path):
        """Gemini adapter copies SKILL.md content including frontmatter."""
        adapter = GeminiAdapter(tmp_path)

        # Create skill directory with SKILL.md containing new frontmatter fields
        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\n"
            "name: my-skill\n"
            "description: A test skill\n"
            "context: fork\n"
            "agent: developer\n"
            "---\n\n"
            "Skill instructions here.\n",
            encoding="utf-8",
        )

        skills = {"my-skill": skill_dir}
        result = adapter.sync_skills(skills)

        assert result.synced == 1
        target_skill = tmp_path / ".gemini" / "skills" / "my-skill" / "SKILL.md"
        assert target_skill.exists()
        content = target_skill.read_text()
        # New frontmatter fields preserved
        assert "context: fork" in content
        assert "agent: developer" in content

    def test_codex_preserves_frontmatter_via_symlink(self, tmp_path):
        """Codex adapter symlinks skill dirs, preserving all content including frontmatter."""
        adapter = CodexAdapter(tmp_path)

        skill_dir = tmp_path / "skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\n"
            "name: my-skill\n"
            "description: A test skill\n"
            "context: fork\n"
            "agent: developer\n"
            "---\n\n"
            "Skill body.\n",
            encoding="utf-8",
        )

        skills = {"my-skill": skill_dir}
        result = adapter.sync_skills(skills)

        assert result.synced == 1
        # Symlink target should point to original (all content preserved)
        target = tmp_path / ".agents" / "skills" / "my-skill"
        assert target.exists()
        skill_content = (target / "SKILL.md").read_text()
        assert "context: fork" in skill_content
        assert "agent: developer" in skill_content

    def test_opencode_preserves_frontmatter_via_symlink(self, tmp_path):
        """OpenCode adapter symlinks skill dirs, preserving all content."""
        adapter = OpenCodeAdapter(tmp_path)

        # Create skill outside .claude/skills/ to avoid native-discovery skip
        skill_dir = tmp_path / "ext-skills" / "my-skill"
        skill_dir.mkdir(parents=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(
            "---\n"
            "name: my-skill\n"
            "description: A test skill\n"
            "context: fork\n"
            "agent: developer\n"
            "---\n\n"
            "Skill body.\n",
            encoding="utf-8",
        )

        skills = {"my-skill": skill_dir}
        result = adapter.sync_skills(skills)

        assert result.synced == 1
        target = tmp_path / ".opencode" / "skills" / "my-skill"
        assert target.exists()
        skill_content = (target / "SKILL.md").read_text()
        assert "context: fork" in skill_content
        assert "agent: developer" in skill_content
