from __future__ import annotations

"""Re-export facade for tag-based content filtering.

This module re-exports all public symbols from their sub-modules to
maintain backward compatibility. All existing imports continue to work:

    from src.sync_filter import filter_rules_for_target
    from src.sync_filter import filter_rules_for_env, has_sync_tags
    from src.sync_filter import SyncTriggerRule, SyncTriggerMatcher
    from src.sync_filter import propagate_effectiveness_annotations

Implementation is split across:
- src/filter_rules.py   -- Tag regex patterns, frontmatter parsing, target helpers
- src/filter_engine.py  -- Core filter functions (target, env, section filtering)
- src/filter_helpers.py -- Effectiveness, compliance, section annotation helpers
- src/filter_ignore.py  -- .harnessignore support, SyncTriggerRule/SyncTriggerMatcher
"""

# --- filter_rules.py ---
from src.filter_rules import (
    KNOWN_TARGETS,
    parse_frontmatter_tags,
    is_content_allowed_for_target,
    filter_content_with_frontmatter,
)

# --- filter_engine.py ---
from src.filter_engine import (
    filter_rules_for_target,
    filter_rules_for_env,
    filter_sections_for_target,
    has_env_tags,
    has_sync_tags,
    has_compliance_pinned,
    extract_compliance_pinned,
    extract_effectiveness_annotations,
    format_effectiveness_report,
    extract_effectiveness_propagation_annotations,
    propagate_effectiveness_annotations,
    extract_section_annotations,
    format_section_annotation_report,
)

# --- filter_ignore.py ---
from src.filter_ignore import (
    load_harnessignore,
    apply_harnessignore,
    SyncTriggerRule,
    SyncTriggerMatcher,
)

__all__ = [
    # filter_rules
    "KNOWN_TARGETS",
    "parse_frontmatter_tags",
    "is_content_allowed_for_target",
    "filter_content_with_frontmatter",
    # filter_engine
    "filter_rules_for_target",
    "filter_rules_for_env",
    "filter_sections_for_target",
    "has_env_tags",
    "has_sync_tags",
    "has_compliance_pinned",
    "extract_compliance_pinned",
    "extract_effectiveness_annotations",
    "format_effectiveness_report",
    "extract_effectiveness_propagation_annotations",
    "propagate_effectiveness_annotations",
    "extract_section_annotations",
    "format_section_annotation_report",
    # filter_ignore
    "load_harnessignore",
    "apply_harnessignore",
    "SyncTriggerRule",
    "SyncTriggerMatcher",
]
