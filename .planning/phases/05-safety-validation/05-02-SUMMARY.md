---
phase: 05-safety-validation
plan: 02
subsystem: safety-validation
tags: [conflict-detection, secret-scanning, security, pre-sync-validation]
dependency_graph:
  requires: [state-manager, hashing, logger]
  provides: [conflict-detector, secret-detector]
  affects: [sync-orchestrator]
tech_stack:
  added: [hmac-compare-digest, regex-secret-patterns]
  patterns: [secure-comparison, keyword-whitelist-filtering]
key_files:
  created:
    - src/conflict_detector.py
    - src/secret_detector.py
  modified: []
decisions:
  - Use hmac.compare_digest() for hash comparison to prevent timing attacks
  - Keyword+regex approach for secret detection (15-20% false positive rate vs 60% regex-only)
  - Whitelist TEST_/EXAMPLE_/DEMO_ prefixes to reduce false positives
  - Require 16+ char complex values to filter out simple values
  - Block sync by default with allow_secrets override
  - Never expose secret values in logs or output
metrics:
  duration_minutes: 1.9
  completed_date: 2026-02-14
---

# Phase 5 Plan 02: Conflict Detection & Secret Scanning Summary

**One-liner:** Hash-based conflict detection and keyword+regex secret scanning implementing SAF-02 and SAF-03 with secure comparison and value masking.

## What Was Built

Implemented two pre-sync validation modules:

1. **ConflictDetector** (SAF-02) — Hash-based drift detection via SHA256 comparison
   - Detects manual config edits that would be overwritten
   - Uses `hmac.compare_digest()` for secure comparison (prevents timing attacks)
   - Detects both file modifications and deletions
   - Provides formatted warnings with override hints

2. **SecretDetector** (SAF-03) — Environment variable secret scanning
   - Keyword+regex approach (15-20% false positive rate)
   - Whitelist filtering for TEST_/EXAMPLE_/DEMO_ prefixes
   - Complexity check (16+ chars) to reduce false positives
   - Blocks sync by default with `allow_secrets` override
   - Never exposes secret values in output

## Deviations from Plan

None - plan executed exactly as written.

## Requirements Delivered

- **SAF-02:** Conflict detection via hash comparison
- **SAF-03:** Secret detection in environment variables

Both requirements implemented as specified in plan with all verification tests passing.

## Technical Details

### ConflictDetector Implementation

**Core algorithm:**
```python
# Secure hash comparison (prevents timing attacks)
if not hmac.compare_digest(stored_hash, current_hash):
    conflicts.append({...})
```

**Key features:**
- Read-only operation (does not modify state)
- Per-target and all-target scanning modes
- Deletion detection (missing file = conflict with current_hash="")
- Formatted warnings with modified/deleted indicators

**Verification:** 5/5 tests passed
- No conflicts when files unchanged
- Detects file modification
- Detects file deletion
- check_all() returns dict for all targets
- format_warnings() produces string output

### SecretDetector Implementation

**Detection strategy:**
1. Skip safe prefixes (TEST_, EXAMPLE_, DEMO_, MOCK_, FAKE_, DUMMY_)
2. Check for secret keywords in var name (API_KEY, SECRET, PASSWORD, TOKEN variants)
3. Match value against complexity pattern (16+ alphanumeric/special chars)
4. All checks pass → flag as potential secret

**Keywords matched:**
- API_KEY, APIKEY, API-KEY
- SECRET, SECRET_KEY
- PASSWORD, PASSWD, PWD
- TOKEN, ACCESS_TOKEN, AUTH_TOKEN
- PRIVATE_KEY

**Verification:** 6/6 tests passed
- Detects API key pattern
- Skips TEST_/EXAMPLE_ prefixes
- Skips short/simple values
- should_block() respects allow_secrets override
- format_warnings() masks values
- scan_mcp_env() extracts from MCP configs

## Integration Points

**ConflictDetector:**
- Depends on: StateManager (read stored hashes), hash_file_sha256 (compute current hashes)
- Used by: SyncOrchestrator (pre-sync validation), /sync-status command (drift display)

**SecretDetector:**
- Depends on: Logger (warning output)
- Used by: SyncOrchestrator (pre-sync validation), adapters (MCP env scanning)

## Testing

**Verification Level:** Proxy (Level 2)

**Sanity checks (5):**
- S1: ConflictDetector class with check, check_all, format_warnings methods ✓
- S2: hmac.compare_digest used for hash comparison ✓
- S3: SecretDetector class with scan, scan_mcp_env, should_block, format_warnings ✓
- S4: SECRET_KEYWORDS contains API_KEY, SECRET, PASSWORD, TOKEN ✓
- S5: SAFE_PREFIXES contains TEST_, EXAMPLE_, DEMO_ ✓

**Proxy checks (6):**
- P1: ConflictDetector detects modification via hash mismatch ✓
- P2: ConflictDetector detects file deletion ✓
- P3: SecretDetector detects API key pattern ✓
- P4: SecretDetector skips whitelisted prefixes and short values ✓
- P5: should_block respects allow_secrets override ✓
- P6: format_warnings never contains actual secret values ✓

**Overall:** 11/11 tests passed (100%)

**Deferred to Level 3:**
- DEFER-05-03: Secret detection on production .env files (requires sanitized test data)
- DEFER-05-04: Entropy-based detection (deferred per research - start with keyword+regex)

## Commits

| Task | Commit | Files |
|------|--------|-------|
| 1 | 6d18353 | src/conflict_detector.py (created) |
| 2 | 2e51ed3 | src/secret_detector.py (created) |

## Self-Check: PASSED

**Files created:**
- src/conflict_detector.py ✓
- src/secret_detector.py ✓

**Commits exist:**
- 6d18353 ✓
- 2e51ed3 ✓

**Verification tests:**
- ConflictDetector: 5/5 passed ✓
- SecretDetector: 6/6 passed ✓

All claims verified.
