from __future__ import annotations

"""Tests for Python/shell comment-style harness annotations (iteration 44, item 1).

Covers the new # @targets: skip and # @targets: replace with <text> inline
annotations added to sync_filter.filter_rules_for_target().
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sync_filter import filter_rules_for_target


# ---------------------------------------------------------------------------
# # @targets: skip
# ---------------------------------------------------------------------------


def test_py_skip_drops_line_for_matching_target():
    content = "- Use /debug skill  # @aider: skip\n- Another rule"
    result = filter_rules_for_target(content, "aider")
    assert "Use /debug skill" not in result
    assert "Another rule" in result


def test_py_skip_preserves_line_for_non_matching_target():
    content = "- Use /debug skill  # @aider: skip\n- Another rule"
    result = filter_rules_for_target(content, "codex")
    assert "Use /debug skill" in result
    # Annotation itself stripped for non-matching targets
    assert "# @aider: skip" not in result
    assert "Another rule" in result


def test_py_skip_multi_target_drops_for_each():
    content = "- Prefer TypeScript  # @aider,windsurf: skip"
    for target in ("aider", "windsurf"):
        result = filter_rules_for_target(content, target)
        assert "Prefer TypeScript" not in result, f"Should be dropped for {target}"


def test_py_skip_multi_target_preserves_others():
    content = "- Prefer TypeScript  # @aider,windsurf: skip"
    result = filter_rules_for_target(content, "codex")
    assert "Prefer TypeScript" in result
    assert "# @aider,windsurf: skip" not in result


def test_py_skip_case_insensitive_target():
    content = "- Some rule  # @Codex: skip"
    result = filter_rules_for_target(content, "codex")
    assert "Some rule" not in result


def test_py_skip_annotation_not_stripped_when_no_target():
    # Lines without annotations pass through unchanged
    content = "- Plain rule\n- Another plain rule"
    result = filter_rules_for_target(content, "codex")
    assert "Plain rule" in result
    assert "Another plain rule" in result


# ---------------------------------------------------------------------------
# # @targets: replace with <text>
# ---------------------------------------------------------------------------


def test_py_replace_substitutes_for_matching_target():
    content = "- Use /debug skill  # @aider: replace with See debug-task.md"
    result = filter_rules_for_target(content, "aider")
    assert "See debug-task.md" in result
    assert "/debug skill" not in result


def test_py_replace_emits_original_for_non_matching_target():
    content = "- Use /debug skill  # @aider: replace with See debug-task.md"
    result = filter_rules_for_target(content, "codex")
    assert "Use /debug skill" in result
    assert "See debug-task.md" not in result
    assert "# @aider: replace with" not in result


def test_py_replace_multi_target():
    content = "- Run /sync  # @codex,cursor: replace with Run harnesssync"
    for target in ("codex", "cursor"):
        result = filter_rules_for_target(content, target)
        assert "Run harnesssync" in result, f"Replacement missing for {target}"
        assert "/sync" not in result, f"Original should be replaced for {target}"


def test_py_replace_other_targets_get_original():
    content = "- Run /sync  # @codex,cursor: replace with Run harnesssync"
    result = filter_rules_for_target(content, "gemini")
    assert "Run /sync" in result
    assert "Run harnesssync" not in result


def test_py_replace_preserves_leading_whitespace():
    # In a multi-line block, the leading whitespace of the replaced line is
    # preserved relative to surrounding content.  filter_rules_for_target
    # strips the overall result, so we need surrounding context to verify
    # intra-block indentation is intact.
    content = "## Section\n\n  - Plain rule\n  - Indented rule  # @aider: replace with Indented replacement\n  - Last rule"
    result = filter_rules_for_target(content, "aider")
    # Replacement should appear with its own leading whitespace preserved in context
    assert "Indented replacement" in result
    # The replacement line should be indented relative to the heading
    lines = result.splitlines()
    replacement_line = next((l for l in lines if "Indented replacement" in l), "")
    assert replacement_line.startswith("  "), f"Expected leading spaces in: {replacement_line!r}"


def test_py_replace_empty_replacement_drops_line():
    # If replacement text is empty, line is silently dropped for that target
    content = "- Some rule  # @codex: replace with "
    result = filter_rules_for_target(content, "codex")
    assert "Some rule" not in result


# ---------------------------------------------------------------------------
# Interaction with existing annotations (no interference)
# ---------------------------------------------------------------------------


def test_html_comment_annotations_unaffected():
    """HTML comment annotations still work alongside new Python-style ones."""
    content = (
        "- HTML skip line  <!-- harness:skip=gemini -->\n"
        "- Python skip line  # @aider: skip\n"
        "- Normal line"
    )
    gemini_result = filter_rules_for_target(content, "gemini")
    assert "HTML skip line" not in gemini_result
    assert "Python skip line" in gemini_result
    assert "Normal line" in gemini_result

    aider_result = filter_rules_for_target(content, "aider")
    assert "HTML skip line" in aider_result
    assert "Python skip line" not in aider_result
    assert "Normal line" in aider_result


def test_py_annotation_inside_compliance_pinned_block():
    """Python-style annotations inside compliance:pinned blocks are bypassed."""
    content = (
        "<!-- compliance:pinned -->\n"
        "- Pinned rule  # @codex: skip\n"
        "<!-- /compliance:pinned -->"
    )
    result = filter_rules_for_target(content, "codex")
    # compliance:pinned overrides everything — line must be included
    assert "Pinned rule" in result
