---
phase: 12-critical-fixes-rules-discovery
plan: 02
subsystem: source-reader
tags: [rules-discovery, frontmatter-parsing, orchestrator-integration]
dependency_graph:
  requires: []
  provides: [get_rules_files, rules_files_in_discover_all, orchestrator_rules_merge]
  affects: [src/source_reader.py, src/orchestrator.py]
tech_stack:
  added: []
  patterns: [rglob-recursive-walk, yaml-frontmatter-regex-parsing]
key_files:
  created: []
  modified: [src/source_reader.py, src/orchestrator.py]
decisions:
  - Used regex for frontmatter parsing instead of PyYAML (no new dependencies)
  - Added get_rules_files() as new method rather than modifying get_rules() return type
  - Support both paths: and globs: frontmatter keys with paths: taking precedence
metrics:
  duration: 107s
  completed: 2026-03-09T01:29:03Z
---

# Phase 12 Plan 02: Rules Directory Discovery Summary

SourceReader extended with recursive .claude/rules/ discovery and YAML frontmatter parsing for path-scoped rules, integrated into orchestrator data flow.

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Add rules directory discovery to SourceReader | 1e1e408 | src/source_reader.py |
| 2 | Integrate rules files into orchestrator data flow | 1d567f5 | src/orchestrator.py |

## Changes Made

### SourceReader (src/source_reader.py)

- Added `import re` for frontmatter regex parsing
- Added `_parse_rules_frontmatter(content)` private method that extracts `paths:` and `globs:` keys from YAML frontmatter, handling three formats: single string, YAML list, and inline `[a, b]` list
- Added `get_rules_files()` method that recursively walks `cc_home/rules/` (user scope) and `.claude/rules/` (project scope), parsing frontmatter and returning `list[dict]` with path, content, scope_patterns, scope
- Updated `discover_all()` to include `rules_files` key in returned dict
- Existing `get_rules()` method preserved unchanged for backward compatibility

### Orchestrator (src/orchestrator.py)

- After existing rules string-to-list conversion, added merge of `rules_files` into the `rules` list
- Each rules file entry includes path, content, scope_patterns, and scope metadata
- Adapters receive all rules (CLAUDE.md + .claude/rules/*.md) in the same list[dict] format

## Decisions Made

1. **New method vs modifying existing:** Added `get_rules_files()` as a separate method rather than changing `get_rules()` return type, preserving backward compatibility
2. **Regex over PyYAML:** Used regex for frontmatter parsing to avoid adding a new dependency; the frontmatter schema is simple (only paths/globs keys needed)
3. **Both paths: and globs: supported:** Per research open question #3, both keys are supported with `paths:` taking precedence when both are present

## Deviations from Plan

None - plan executed exactly as written.

## Verification Results

- `get_rules_files()` returns empty list when no rules directories exist: PASS
- `_parse_rules_frontmatter()` handles no frontmatter: PASS
- `_parse_rules_frontmatter()` handles single path string: PASS
- `_parse_rules_frontmatter()` handles inline list `[a, b, c]`: PASS
- `_parse_rules_frontmatter()` handles YAML list with `- item` entries: PASS
- `_parse_rules_frontmatter()` handles `globs:` key fallback: PASS
- `_parse_rules_frontmatter()` handles `paths:` precedence over `globs:`: PASS
- `_parse_rules_frontmatter()` handles unclosed frontmatter gracefully: PASS
- `discover_all()` includes `rules_files` key: PASS
- Orchestrator imports without error: PASS

## Self-Check: PASSED

All files exist, all commits verified.
