from __future__ import annotations

"""Tests for rule_annotator integration into the sync pipeline.

Covers:
- annotate() wraps content with harness-sync provenance markers
- strip_annotations() removes markers without losing content
- extract_annotated_blocks() parses annotated content
- RuleAttributionStore persists and retrieves attribution
- PreSyncPipeline.annotate_rules() applies annotation during sync
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rule_annotator import annotate, strip_annotations, extract_annotated_blocks, RuleAttributionStore


# ---------------------------------------------------------------------------
# Unit tests: annotate / strip / extract
# ---------------------------------------------------------------------------

class TestAnnotate:
    def test_basic_annotation(self):
        content = "Do not use unsafe patterns"
        result = annotate(content, source_path="CLAUDE.md", line_range="5-10")
        assert "<!-- [harness-sync:start source=CLAUDE.md line=5-10] -->" in result
        assert "<!-- [harness-sync:end] -->" in result
        assert "Do not use unsafe patterns" in result

    def test_annotation_without_line_range(self):
        result = annotate("rule text", source_path="rules/safety.md")
        assert "source=rules/safety.md" in result
        assert "line=" not in result

    def test_strip_removes_markers(self):
        content = "rule text"
        annotated = annotate(content, source_path="CLAUDE.md", line_range="1")
        stripped = strip_annotations(annotated)
        assert "harness-sync" not in stripped
        assert "rule text" in stripped

    def test_strip_idempotent_on_clean_content(self):
        content = "no markers here"
        assert strip_annotations(content) == content

    def test_extract_blocks(self):
        annotated = annotate("block one", source_path="a.md", line_range="1-5")
        annotated += "\n" + annotate("block two", source_path="b.md", line_range="10-20")
        blocks = extract_annotated_blocks(annotated)
        assert len(blocks) == 2
        assert blocks[0]["source"] == "a.md"
        assert blocks[0]["line_range"] == "1-5"
        assert "block one" in blocks[0]["content"]
        assert blocks[1]["source"] == "b.md"


# ---------------------------------------------------------------------------
# RuleAttributionStore
# ---------------------------------------------------------------------------

class TestRuleAttributionStore:
    def test_record_and_retrieve(self, tmp_path):
        store = RuleAttributionStore(tmp_path)
        store.record("cursor/.cursorrules", "CLAUDE.md", "1-42")
        result = store.get_source("cursor/.cursorrules")
        assert result is not None
        assert result["source"] == "CLAUDE.md"
        assert result["line_range"] == "1-42"

    def test_missing_key_returns_none(self, tmp_path):
        store = RuleAttributionStore(tmp_path)
        assert store.get_source("nonexistent") is None

    def test_all_attributions(self, tmp_path):
        store = RuleAttributionStore(tmp_path)
        store.record("a", "CLAUDE.md", "1")
        store.record("b", "rules/x.md", "5-10")
        all_attr = store.all_attributions()
        assert len(all_attr) == 2


# ---------------------------------------------------------------------------
# Integration: PreSyncPipeline.annotate_rules()
# ---------------------------------------------------------------------------

class TestAnnotateRulesInPipeline:
    """Verify that annotate_rules() in PreSyncPipeline annotates rule content."""

    def test_annotate_rules_adds_markers(self, tmp_path):
        from src.sync_pipeline import PreSyncPipeline
        from src.utils.logger import Logger

        pipeline = PreSyncPipeline(
            project_dir=tmp_path,
            cc_home=None,
            scope="all",
            dry_run=False,
            allow_secrets=False,
            scrub_secrets=False,
            minimal=False,
            logger=Logger(),
        )

        source_data = {
            'rules': [
                {'path': 'CLAUDE.md', 'content': 'Always use type hints'},
                {'path': '.claude/rules/safety.md', 'content': 'Never run untrusted input'},
            ],
        }

        pipeline.annotate_rules(source_data)

        for rule in source_data['rules']:
            assert "<!-- [harness-sync:start" in rule['content']
            assert "<!-- [harness-sync:end] -->" in rule['content']

        # Check source paths are preserved in markers
        assert "source=CLAUDE.md" in source_data['rules'][0]['content']
        assert "source=.claude/rules/safety.md" in source_data['rules'][1]['content']

    def test_annotate_rules_no_double_wrap(self, tmp_path):
        """Re-running annotate_rules should not double-wrap."""
        from src.sync_pipeline import PreSyncPipeline
        from src.utils.logger import Logger

        pipeline = PreSyncPipeline(
            project_dir=tmp_path,
            cc_home=None,
            scope="all",
            dry_run=False,
            allow_secrets=False,
            scrub_secrets=False,
            minimal=False,
            logger=Logger(),
        )

        source_data = {
            'rules': [
                {'path': 'CLAUDE.md', 'content': 'Use pytest for tests'},
            ],
        }

        pipeline.annotate_rules(source_data)
        pipeline.annotate_rules(source_data)

        second_pass = source_data['rules'][0]['content']

        # Count markers -- should be exactly one start and one end
        assert second_pass.count("harness-sync:start") == 1
        assert second_pass.count("harness-sync:end") == 1

    def test_annotate_rules_persists_attribution(self, tmp_path):
        """Attribution store should be written when not in dry-run."""
        from src.sync_pipeline import PreSyncPipeline
        from src.utils.logger import Logger

        pipeline = PreSyncPipeline(
            project_dir=tmp_path,
            cc_home=None,
            scope="all",
            dry_run=False,
            allow_secrets=False,
            scrub_secrets=False,
            minimal=False,
            logger=Logger(),
        )

        source_data = {
            'rules': [
                {'path': 'CLAUDE.md', 'content': 'Be helpful'},
            ],
        }

        pipeline.annotate_rules(source_data)

        attr_path = tmp_path / ".harness-sync" / "rule-attribution.json"
        assert attr_path.exists()
        data = json.loads(attr_path.read_text())
        assert "CLAUDE.md" in data

    def test_annotate_rules_skipped_in_dry_run(self, tmp_path):
        """In dry-run mode, attribution store should NOT be written."""
        from src.sync_pipeline import PreSyncPipeline
        from src.utils.logger import Logger

        pipeline = PreSyncPipeline(
            project_dir=tmp_path,
            cc_home=None,
            scope="all",
            dry_run=True,
            allow_secrets=False,
            scrub_secrets=False,
            minimal=False,
            logger=Logger(),
        )

        source_data = {
            'rules': [
                {'path': 'CLAUDE.md', 'content': 'Be helpful'},
            ],
        }

        pipeline.annotate_rules(source_data)

        # Annotations should still be applied to content
        assert "harness-sync:start" in source_data['rules'][0]['content']
        # But attribution file should NOT be persisted
        attr_path = tmp_path / ".harness-sync" / "rule-attribution.json"
        assert not attr_path.exists()
