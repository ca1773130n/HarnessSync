from __future__ import annotations

"""
Conflict detection and resolution for HarnessSync.

This module is the public API surface -- all classes and functions are
re-exported from their implementation sub-modules for backward compatibility.

Sub-modules:
  - src.conflict_patterns: SemanticConflict, SemanticConflictDetector, pattern data
  - src.conflict_scanner:  ConflictDetector (hash-based detection, diffs, formatting)
  - src.conflict_resolver: ConflictResolutionWizard, SyncConflictWizard, TuiConflictWizard
"""

# --- Semantic conflict patterns and detector ---
from src.conflict_patterns import (  # noqa: F401
    SemanticConflict,
    SemanticConflictDetector,
    _CONTRADICTION_PATTERNS,
    _extract_rule_lines,
)

# --- Hash-based conflict scanner ---
from src.conflict_scanner import (  # noqa: F401
    ConflictDetector,
    _build_merge_template,
)

# --- Conflict resolution wizards ---
from src.conflict_resolver import (  # noqa: F401
    ConflictResolutionWizard,
    SyncConflictWizard,
    TuiConflictWizard,
    _explain_conflict_in_plain_english,
)

__all__ = [
    "ConflictDetector",
    "ConflictResolutionWizard",
    "SemanticConflict",
    "SemanticConflictDetector",
    "SyncConflictWizard",
    "TuiConflictWizard",
    "_CONTRADICTION_PATTERNS",
    "_build_merge_template",
    "_explain_conflict_in_plain_english",
    "_extract_rule_lines",
]
