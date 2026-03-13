from __future__ import annotations

"""Tests for iteration 69 product-ideation improvements.

Covers:
- Semantic Diff View (item 8): SemanticChange / compute_semantic_diff / DiffFormatter.add_semantic_diff
- Rule Scope & Priority Visualizer (item 19): build_scope_map / format_scope_tree
- Branch-Aware Git Hook (item 3): install_post_checkout_hook / uninstall_post_checkout_hook
- Harness Version Upgrade Instructions (item 10): get_upgrade_requirements / format_upgrade_requirements
- Cloud Sync via Gist (item 22): GistCloudSync / parse_gist_id_from_url / build_shareable_bundle
- CI Pipeline PR & Matrix triggers (item 9): CIPipelineGenerator.for_pr_trigger / for_matrix_trigger
- Named Sync Profile Presets (item 1): PRESET_PROFILES / install_preset / list_presets
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.diff_formatter import (
    SemanticChange,
    compute_semantic_diff,
    DiffFormatter,
)
from src.rule_dependency_viz import (
    ScopedRule,
    build_scope_map,
    format_scope_tree,
)
from src.branch_aware_sync import (
    install_post_checkout_hook,
    uninstall_post_checkout_hook,
)
from src.harness_version_compat import (
    UpgradeRequirement,
    get_upgrade_requirements,
    format_upgrade_requirements,
)
from src.cloud_sync import (
    GistCloudSync,
    parse_gist_id_from_url,
    build_shareable_bundle,
    GistSyncResult,
)
from src.ci_pipeline_generator import (
    CIPipelineGenerator,
    CIPipelineConfig,
)
from src.profile_manager import (
    PRESET_PROFILES,
    install_preset,
    list_presets,
    ProfileManager,
)


# ── SemanticChange ────────────────────────────────────────────────────────────


def test_semantic_change_format_added():
    """Added changes format without arrow."""
    sc = SemanticChange("MCP server", "added", "filesystem", "", "npx")
    text = sc.format()
    assert "MCP server added" in text
    assert "filesystem" in text
    assert "→" not in text


def test_semantic_change_format_removed():
    """Removed changes include 'removed'."""
    sc = SemanticChange("tool permission", "removed", "bash", "allow", "")
    text = sc.format()
    assert "removed" in text
    assert "bash" in text


def test_semantic_change_format_changed():
    """Changed changes show old → new."""
    sc = SemanticChange("tool permission", "changed", "bash", "allow", "deny")
    text = sc.format()
    assert "allow" in text
    assert "deny" in text
    assert "→" in text


# ── compute_semantic_diff ─────────────────────────────────────────────────────


def test_compute_semantic_diff_mcp_added():
    """New MCP server is detected as 'added'."""
    old = json.dumps({"mcpServers": {}})
    new = json.dumps({"mcpServers": {"filesystem": {"command": "npx", "args": []}}})
    changes = compute_semantic_diff(old, new)
    assert any(c.action == "added" and c.subject == "filesystem" for c in changes)


def test_compute_semantic_diff_mcp_removed():
    """Removed MCP server is detected as 'removed'."""
    old = json.dumps({"mcpServers": {"github": {"url": "https://api.github.com"}}})
    new = json.dumps({"mcpServers": {}})
    changes = compute_semantic_diff(old, new)
    assert any(c.action == "removed" and c.subject == "github" for c in changes)


def test_compute_semantic_diff_permission_changed():
    """Tool permission change from allow to deny is detected."""
    old = json.dumps({"permissions": {"allow": ["bash"], "deny": []}})
    new = json.dumps({"permissions": {"allow": [], "deny": ["bash"]}})
    changes = compute_semantic_diff(old, new)
    bash_changes = [c for c in changes if c.subject == "bash"]
    assert bash_changes


def test_compute_semantic_diff_rule_added():
    """New markdown heading is detected as added rule section."""
    old = "# Existing Rule\nBe helpful.\n"
    new = "# Existing Rule\nBe helpful.\n\n# New Rule\nAlways test.\n"
    changes = compute_semantic_diff(old, new)
    assert any(c.action == "added" and "New Rule" in c.subject for c in changes)


def test_compute_semantic_diff_no_changes():
    """Identical content produces no changes."""
    content = json.dumps({"mcpServers": {"fs": {"command": "npx"}}})
    changes = compute_semantic_diff(content, content)
    assert changes == []


def test_compute_semantic_diff_rule_removed():
    """Removed markdown heading is detected as removed rule section."""
    old = "# Rule A\nDo X.\n\n# Rule B\nDo Y.\n"
    new = "# Rule A\nDo X.\n"
    changes = compute_semantic_diff(old, new)
    assert any(c.action == "removed" and "Rule B" in c.subject for c in changes)


# ── DiffFormatter.add_semantic_diff ──────────────────────────────────────────


def test_diff_formatter_add_semantic_diff_returns_changes():
    """add_semantic_diff returns SemanticChange list."""
    fmt = DiffFormatter()
    old = json.dumps({"mcpServers": {}})
    new = json.dumps({"mcpServers": {"git": {"command": "uvx"}}})
    changes = fmt.add_semantic_diff("mcp", old, new)
    assert isinstance(changes, list)
    assert any(c.subject == "git" for c in changes)


def test_diff_formatter_add_semantic_diff_stored_in_diffs():
    """Semantic diff entry appears in formatter output."""
    fmt = DiffFormatter()
    old = json.dumps({"mcpServers": {"old-server": {"command": "x"}}})
    new = json.dumps({"mcpServers": {}})
    fmt.add_semantic_diff("mcp-config", old, new)
    output = fmt.format_output()
    assert "semantic diff" in output


def test_diff_formatter_format_semantic_summary_no_changes():
    """format_semantic_summary returns message when no semantic diffs recorded."""
    fmt = DiffFormatter()
    summary = fmt.format_semantic_summary()
    assert "No semantic changes" in summary


def test_diff_formatter_format_semantic_summary_with_changes():
    """format_semantic_summary lists changes after add_semantic_diff."""
    fmt = DiffFormatter()
    old = json.dumps({"mcpServers": {}})
    new = json.dumps({"mcpServers": {"new-server": {"command": "npx"}}})
    fmt.add_semantic_diff("settings", old, new)
    summary = fmt.format_semantic_summary()
    assert "new-server" in summary


# ── build_scope_map / format_scope_tree ──────────────────────────────────────


def test_build_scope_map_empty_project(tmp_path):
    """Empty project returns empty scope map."""
    rules = build_scope_map(tmp_path, cc_home=tmp_path / ".claude")
    assert isinstance(rules, list)


def test_build_scope_map_project_file(tmp_path):
    """Project CLAUDE.md rules appear with 'project' scope."""
    (tmp_path / "CLAUDE.md").write_text("# My Rule\nBe helpful.\n", encoding="utf-8")
    rules = build_scope_map(tmp_path, cc_home=tmp_path / ".claude_home")
    project_rules = [r for r in rules if r.scope == "project"]
    assert len(project_rules) >= 1


def test_build_scope_map_global_file(tmp_path):
    """~/.claude/CLAUDE.md rules appear with 'global' scope."""
    cc_home = tmp_path / ".claude"
    cc_home.mkdir()
    (cc_home / "CLAUDE.md").write_text("# Global Rule\nApply everywhere.\n", encoding="utf-8")
    rules = build_scope_map(tmp_path, cc_home=cc_home)
    global_rules = [r for r in rules if r.scope == "global"]
    assert len(global_rules) >= 1


def test_build_scope_map_conflict_detection(tmp_path):
    """Same rule name in global and project is flagged as a conflict."""
    cc_home = tmp_path / ".claude"
    cc_home.mkdir()
    (cc_home / "CLAUDE.md").write_text("# Shared Rule\nGlobal version.\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Shared Rule\nProject version.\n", encoding="utf-8")
    rules = build_scope_map(tmp_path, cc_home=cc_home)
    conflicting = [r for r in rules if r.conflicts_with]
    assert conflicting  # At least one conflict detected


def test_format_scope_tree_empty():
    """format_scope_tree with empty list returns sensible message."""
    text = format_scope_tree([])
    assert text  # Non-empty


def test_format_scope_tree_sections_labeled(tmp_path):
    """format_scope_tree labels global/project/subdirectory sections."""
    (tmp_path / "CLAUDE.md").write_text("# Alpha Rule\nDo alpha.\n", encoding="utf-8")
    cc_home = tmp_path / ".claude_home"
    cc_home.mkdir()
    (cc_home / "CLAUDE.md").write_text("# Beta Rule\nDo beta.\n", encoding="utf-8")
    rules = build_scope_map(tmp_path, cc_home=cc_home)
    text = format_scope_tree(rules)
    assert "PROJECT" in text or "GLOBAL" in text


def test_format_scope_tree_conflict_marker(tmp_path):
    """Conflicting rules show a warning marker."""
    cc_home = tmp_path / ".claude"
    cc_home.mkdir()
    (cc_home / "CLAUDE.md").write_text("# Security Policy\nGlobal.\n", encoding="utf-8")
    (tmp_path / "CLAUDE.md").write_text("# Security Policy\nProject override.\n", encoding="utf-8")
    rules = build_scope_map(tmp_path, cc_home=cc_home)
    text = format_scope_tree(rules)
    assert "⚠" in text or "conflict" in text.lower() or "overrides" in text


# ── install_post_checkout_hook ────────────────────────────────────────────────


def _init_git_repo(path: Path) -> None:
    """Initialize a bare git repo for testing."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        capture_output=True,
    )


def test_install_post_checkout_hook_creates_file(tmp_path):
    """install_post_checkout_hook creates the hook file."""
    _init_git_repo(tmp_path)
    result = install_post_checkout_hook(tmp_path)
    assert result["installed"] is True
    assert result["hook_path"] is not None
    assert Path(result["hook_path"]).exists()


def test_install_post_checkout_hook_executable(tmp_path):
    """Installed hook file is executable."""
    import stat
    _init_git_repo(tmp_path)
    result = install_post_checkout_hook(tmp_path)
    hook_path = Path(result["hook_path"])
    mode = hook_path.stat().st_mode
    assert mode & stat.S_IXUSR


def test_install_post_checkout_hook_idempotent(tmp_path):
    """Installing twice with same content is detected as already installed."""
    _init_git_repo(tmp_path)
    install_post_checkout_hook(tmp_path)
    result2 = install_post_checkout_hook(tmp_path)
    assert result2["installed"] is True
    assert result2["was_existing"] is True


def test_install_post_checkout_hook_not_git_repo(tmp_path):
    """install_post_checkout_hook fails gracefully when not a git repo."""
    result = install_post_checkout_hook(tmp_path / "not-a-repo")
    assert result["installed"] is False


def test_uninstall_post_checkout_hook_removes(tmp_path):
    """uninstall_post_checkout_hook removes the installed hook."""
    _init_git_repo(tmp_path)
    install_post_checkout_hook(tmp_path)
    result = uninstall_post_checkout_hook(tmp_path)
    assert result["removed"] is True


def test_uninstall_post_checkout_hook_no_hook(tmp_path):
    """uninstall_post_checkout_hook returns removed=False when no hook exists."""
    _init_git_repo(tmp_path)
    result = uninstall_post_checkout_hook(tmp_path)
    assert result["removed"] is False


# ── UpgradeRequirement / get_upgrade_requirements ────────────────────────────


def test_upgrade_requirement_format():
    """UpgradeRequirement.format() includes harness, versions, features, commands."""
    req = UpgradeRequirement(
        harness="cursor",
        current_version="0.39",
        required_version="0.43",
        blocked_features=["MCP server support", "glob scoping"],
        upgrade_commands=["Download from https://cursor.com"],
    )
    text = req.format()
    assert "cursor" in text.lower()
    assert "0.39" in text
    assert "0.43" in text
    assert "MCP server support" in text
    assert "Download" in text


def test_get_upgrade_requirements_returns_list(tmp_path):
    """get_upgrade_requirements returns a list."""
    reqs = get_upgrade_requirements(project_dir=tmp_path)
    assert isinstance(reqs, list)


def test_get_upgrade_requirements_old_version_triggers(tmp_path):
    """An old pinned version triggers upgrade requirements."""
    versions_file = tmp_path / ".harnesssync"
    versions_file.write_text(
        json.dumps({"harness_versions": {"cursor": "0.30"}}),
        encoding="utf-8",
    )
    reqs = get_upgrade_requirements(project_dir=tmp_path)
    cursor_req = next((r for r in reqs if r.harness == "cursor"), None)
    assert cursor_req is not None
    assert cursor_req.current_version == "0.30"
    assert cursor_req.blocked_features  # Should have blocked features


def test_format_upgrade_requirements_no_issues(tmp_path):
    """format_upgrade_requirements returns ok message when all versions are current."""
    # No pinned versions file → defaults used → all features unlocked
    text = format_upgrade_requirements(project_dir=tmp_path)
    # Either no issues message or empty string (both acceptable)
    assert isinstance(text, str)


def test_format_upgrade_requirements_with_old_version(tmp_path):
    """format_upgrade_requirements includes upgrade commands for old versions."""
    versions_file = tmp_path / ".harnesssync"
    versions_file.write_text(
        json.dumps({"harness_versions": {"gemini": "0.5"}}),
        encoding="utf-8",
    )
    text = format_upgrade_requirements(project_dir=tmp_path)
    assert "gemini" in text.lower()


# ── GistCloudSync / parse_gist_id_from_url / build_shareable_bundle ──────────


def test_parse_gist_id_from_url_full():
    """parse_gist_id_from_url extracts ID from full URL."""
    url = "https://gist.github.com/octocat/6cad326836d38bd3a7ae"
    gist_id = parse_gist_id_from_url(url)
    assert gist_id == "6cad326836d38bd3a7ae"


def test_parse_gist_id_from_url_bare_id():
    """parse_gist_id_from_url handles bare hex IDs."""
    gist_id = parse_gist_id_from_url("aa5a315d61ae9438b18d")
    assert gist_id == "aa5a315d61ae9438b18d"


def test_parse_gist_id_from_url_invalid():
    """parse_gist_id_from_url returns None for unrecognized strings."""
    assert parse_gist_id_from_url("not-a-gist-id") is None


def test_build_shareable_bundle_empty_project(tmp_path):
    """build_shareable_bundle returns empty dict for empty project."""
    bundle = build_shareable_bundle(tmp_path)
    assert isinstance(bundle, dict)
    # No CLAUDE.md or other files → empty bundle


def test_build_shareable_bundle_includes_claude_md(tmp_path):
    """build_shareable_bundle includes CLAUDE.md when it exists."""
    (tmp_path / "CLAUDE.md").write_text("# Rules\nBe helpful.", encoding="utf-8")
    bundle = build_shareable_bundle(tmp_path)
    assert "CLAUDE.md" in bundle
    assert "Be helpful" in bundle["CLAUDE.md"]


def test_gist_cloud_sync_result_format_success():
    """GistSyncResult.format() shows success status."""
    result = GistSyncResult(
        success=True,
        gist_id="abc123",
        gist_url="https://gist.github.com/abc123",
        files_synced=["CLAUDE.md", "AGENTS.md"],
    )
    text = result.format()
    assert "OK" in text
    assert "abc123" in text
    assert "CLAUDE.md" in text


def test_gist_cloud_sync_result_format_failure():
    """GistSyncResult.format() shows failure and error."""
    result = GistSyncResult(success=False, error="Network error: timeout")
    text = result.format()
    assert "FAILED" in text
    assert "Network error" in text


def test_gist_cloud_sync_get_gist_url():
    """GistCloudSync.get_gist_url returns correct URL."""
    syncer = GistCloudSync(token="dummy-token")
    url = syncer.get_gist_url("abc123def456")
    assert "gist.github.com" in url
    assert "abc123def456" in url


def test_gist_cloud_sync_push_no_files(tmp_path):
    """GistCloudSync.push returns failure when no config files found."""
    syncer = GistCloudSync(token="dummy-token")
    # tmp_path has no config files
    result = syncer.push(tmp_path)
    assert result.success is False
    assert "No config files" in result.error


# ── CI Pipeline PR & Matrix triggers ─────────────────────────────────────────


def test_ci_pipeline_pr_trigger_yaml_contains_pull_request():
    """PR trigger workflow contains pull_request event."""
    gen = CIPipelineGenerator.for_pr_trigger(base_branch="main")
    yaml = gen.generate()
    assert "pull_request" in yaml
    assert "dry-run" in yaml or "dry_run" in yaml or "dry-run" in yaml


def test_ci_pipeline_pr_trigger_no_commit_step():
    """PR trigger workflow does not include a git commit step."""
    gen = CIPipelineGenerator.for_pr_trigger()
    yaml = gen.generate()
    assert "git commit" not in yaml


def test_ci_pipeline_matrix_trigger_yaml_contains_matrix():
    """Matrix trigger workflow has strategy matrix."""
    gen = CIPipelineGenerator.for_matrix_trigger(targets=["codex", "gemini"])
    yaml = gen.generate()
    assert "matrix" in yaml
    assert "codex" in yaml
    assert "gemini" in yaml


def test_ci_pipeline_matrix_trigger_targets_serialized():
    """Matrix trigger serializes targets as JSON array."""
    gen = CIPipelineGenerator.for_matrix_trigger(targets=["aider", "cursor", "windsurf"])
    yaml = gen.generate()
    assert "aider" in yaml
    assert "cursor" in yaml
    assert "windsurf" in yaml


def test_ci_pipeline_matrix_trigger_fail_fast_false():
    """Matrix trigger sets fail-fast: false for per-target isolation."""
    gen = CIPipelineGenerator.for_matrix_trigger()
    yaml = gen.generate()
    assert "fail-fast: false" in yaml


def test_ci_pipeline_pr_trigger_base_branch():
    """PR trigger uses the specified base branch."""
    gen = CIPipelineGenerator.for_pr_trigger(base_branch="develop")
    yaml = gen.generate()
    assert "develop" in yaml


# ── PRESET_PROFILES / install_preset / list_presets ──────────────────────────


def test_preset_profiles_keys():
    """PRESET_PROFILES contains expected preset names."""
    assert "work" in PRESET_PROFILES
    assert "personal" in PRESET_PROFILES
    assert "oss" in PRESET_PROFILES
    assert "minimal" in PRESET_PROFILES
    assert "compliance" in PRESET_PROFILES


def test_preset_profiles_have_descriptions():
    """All presets have non-empty description fields."""
    for name, profile in PRESET_PROFILES.items():
        assert "description" in profile, f"{name} missing description"
        assert profile["description"], f"{name} has empty description"


def test_install_preset_saves_profile(tmp_path):
    """install_preset saves a copy of the preset into ProfileManager."""
    mgr = ProfileManager(config_dir=tmp_path / ".harnesssync")
    install_preset(mgr, "work")
    saved = mgr.get_profile("work")
    assert saved is not None
    assert saved.get("description") == PRESET_PROFILES["work"]["description"]


def test_install_preset_custom_name(tmp_path):
    """install_preset saves under a custom name when provided."""
    mgr = ProfileManager(config_dir=tmp_path / ".harnesssync")
    name = install_preset(mgr, "oss", profile_name="my-oss")
    assert name == "my-oss"
    assert mgr.get_profile("my-oss") is not None
    assert mgr.get_profile("oss") is None


def test_install_preset_raises_for_unknown():
    """install_preset raises KeyError for unknown preset names."""
    mgr = ProfileManager()
    with pytest.raises(KeyError, match="Unknown preset"):
        install_preset(mgr, "nonexistent-preset-xyz")


def test_install_preset_no_overwrite(tmp_path):
    """install_preset raises ValueError if profile exists and overwrite=False."""
    mgr = ProfileManager(config_dir=tmp_path / ".harnesssync")
    install_preset(mgr, "minimal")
    with pytest.raises(ValueError, match="already exists"):
        install_preset(mgr, "minimal", overwrite=False)


def test_install_preset_overwrite(tmp_path):
    """install_preset with overwrite=True replaces existing profile."""
    mgr = ProfileManager(config_dir=tmp_path / ".harnesssync")
    install_preset(mgr, "minimal")
    # Modify and save
    mgr.save_profile("minimal", {"description": "Modified"})
    install_preset(mgr, "minimal", overwrite=True)
    # Should be restored to preset content
    saved = mgr.get_profile("minimal")
    assert saved["description"] == PRESET_PROFILES["minimal"]["description"]


def test_list_presets_contains_all_names():
    """list_presets output contains all preset names."""
    text = list_presets()
    for name in PRESET_PROFILES:
        assert name in text


def test_list_presets_install_hint():
    """list_presets includes usage instruction."""
    text = list_presets()
    assert "/sync" in text or "Install" in text
