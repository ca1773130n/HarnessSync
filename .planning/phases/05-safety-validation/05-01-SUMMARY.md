---
phase: 05-safety-validation
plan: 01
subsystem: safety-primitives
tags: [backup, rollback, symlink-cleanup, safety, filesystem]
requires: [src/utils/paths.py, src/utils/logger.py]
provides: [src/backup_manager.py, src/symlink_cleaner.py]
affects: []
tech-stack:
  added: []
  patterns: [rollback-context, timestamped-backup, broken-symlink-detection]
key-files:
  created:
    - src/backup_manager.py
    - src/symlink_cleaner.py
  modified: []
decisions:
  - "Timestamped backup format: YYYYMMDD_HHMMSS for sortable chronological order"
  - "LIFO rollback order: restore most recent changes first for consistency"
  - "Best-effort rollback: log errors but continue processing remaining backups"
  - "Keep 10 most recent backups: balance disk space vs recovery capability"
  - "is_symlink() + not exists() pattern: correct broken symlink detection per pathlib docs"
metrics:
  duration: 128s
  tasks_completed: 2
  files_created: 2
  tests_passed: 10
  completed: 2026-02-14
---

# Phase 05 Plan 01: Backup Manager and Symlink Cleaner Summary

**One-liner:** Timestamped backup system with LIFO rollback and broken symlink cleanup achieving 100% test pass rate (10/10 verification tests).

## Objective

Implement pre-sync backup with rollback capabilities (SAF-01) and stale symlink cleanup (SAF-05) to protect target configurations from corruption during sync failures and clean up orphaned symlinks after sync operations.

## What Was Built

### 1. BackupManager (src/backup_manager.py)

**Purpose:** Timestamped backup creation and restoration with automatic rollback on failures.

**Key Features:**
- **Timestamped backups:** Creates backups under `~/.harnesssync/backups/{target_name}/{filename}_{YYYYMMDD_HHMMSS}/`
- **Symlink preservation:** Uses `shutil.copytree(symlinks=True)` to preserve symlink structure without following
- **LIFO rollback:** Restores backups in reverse order for consistency
- **Retention policy:** `cleanup_old_backups()` keeps 10 most recent, deletes older ones
- **Best-effort recovery:** Logs errors but continues processing remaining backups

**API:**
```python
bm = BackupManager(backup_root=Path.home() / '.harnesssync' / 'backups')
backup_path = bm.backup_target(target_path, 'codex')  # Create backup
bm.rollback([(backup_path, target_path)])  # Restore on failure
bm.cleanup_old_backups('codex', keep_count=10)  # Cleanup old backups
```

**BackupContext:** Context manager providing automatic rollback on exception:
```python
with BackupContext(bm) as ctx:
    bp = bm.backup_target(target, 'codex')
    ctx.register(bp, target)
    # ... sync operations ...
    # Automatic rollback if exception occurs
```

**Based on:** Rollback context pattern (Python rollback library), ISO 8601 timestamped backup best practices.

### 2. SymlinkCleaner (src/symlink_cleaner.py)

**Purpose:** Detect and remove broken symlinks from target directories.

**Key Features:**
- **Correct detection:** Uses `is_symlink() and not exists()` pattern per pathlib documentation
- **Target-aware cleanup:** Knows which directories each target uses
  - Codex: `.codex/skills/`
  - OpenCode: `.opencode/skills/`, `.opencode/agents/`, `.opencode/commands/`
  - Gemini: None (uses inline content)
- **Safe removal:** Only removes broken symlinks, preserves valid symlinks and files
- **Graceful handling:** Non-existent directories return empty list

**API:**
```python
cleaner = SymlinkCleaner(project_dir)
broken = cleaner.find_broken_symlinks(directory)  # Find broken symlinks
removed = cleaner.cleanup('opencode')  # Clean specific target
results = cleaner.cleanup_all()  # Clean all targets
```

**Based on:** Pathlib documentation's broken symlink detection pattern.

## Verification Results

### Level 1: Sanity Checks (5/5)
- ✓ S1: BackupManager class exists with backup_target, rollback, cleanup_old_backups methods
- ✓ S2: Backup directory contains timestamped subdirectory with YYYYMMDD_HHMMSS format
- ✓ S3: SymlinkCleaner class exists with find_broken_symlinks, cleanup, cleanup_all methods
- ✓ S4: Broken symlink detection uses is_symlink() and not exists() pattern
- ✓ S5: shutil.copytree called with symlinks=True

### Level 2: Proxy Tests (10/10)
**BackupManager tests (5/5):**
- ✓ P1: Backup creates timestamped directory with correct format
- ✓ P2: Backup preserves file content byte-for-byte
- ✓ P3: Rollback restores files successfully
- ✓ P4: Cleanup retains exactly 10 backups when 15 exist
- ✓ P5: BackupContext triggers rollback on exception

**SymlinkCleaner tests (5/5):**
- ✓ P6: Detects broken symlinks correctly (1 broken, 1 valid)
- ✓ P7: Cleanup removes only broken symlinks, preserves valid
- ✓ P8: OpenCode cleanup covers all 3 directories (skills, agents, commands)
- ✓ P9: Gemini returns empty list (no symlinks)
- ✓ P10: Non-existent directory handled gracefully

### Level 3: Deferred Validations
- **DEFER-05-01:** Windows junction detection in SymlinkCleaner (requires Windows environment)
- **DEFER-05-02:** Large directory backup performance (requires >1GB test data)

## Deviations from Plan

None - plan executed exactly as written. All tasks completed with 100% test pass rate.

## Integration Points

### Upstream Dependencies
- `src/utils/paths.py` - Path resolution and directory creation
- `src/utils/logger.py` - Colored logging and operation tracking

### Downstream Usage (Future)
- **SyncOrchestrator** (Plan 04-01) - Will use BackupManager for pre-sync backup
- **SyncOrchestrator** (Plan 04-01) - Will use SymlinkCleaner for post-sync cleanup
- **PostToolUse hook** (Plan 04-03) - Will invoke backup/cleanup during auto-sync

### Provides to Codebase
- `BackupManager` class with backup/rollback/cleanup API
- `BackupContext` context manager for automatic rollback
- `SymlinkCleaner` class for broken symlink detection and removal

## Key Decisions

1. **Timestamped backup format (YYYYMMDD_HHMMSS):** Sortable chronological order, human-readable, avoids filesystem special characters.

2. **LIFO rollback order:** Process backups in reverse order (most recent first) for consistency with transactional rollback semantics.

3. **Best-effort rollback:** Log errors but continue processing remaining backups instead of failing fast. Rationale: partial recovery is better than no recovery.

4. **Keep 10 most recent backups:** Balance between disk space usage and recovery capability. Configurable via `keep_count` parameter.

5. **Symlink preservation with symlinks=True:** Critical for avoiding duplicate content and preserving skill directory references. Following symlinks would violate single-source-of-truth principle.

6. **is_symlink() + not exists() pattern:** Correct broken symlink detection per pathlib documentation. Using `lexists()` would incorrectly return True for broken links.

## Technical Insights

### Pattern: Rollback Context Manager

The BackupContext pattern provides automatic cleanup on exception:
```python
with BackupContext(bm) as ctx:
    bp = bm.backup_target(target, 'codex')
    ctx.register(bp, target)
    # ... operations that might fail ...
# __exit__ triggers rollback if exception occurred
```

This ensures rollback happens even on unexpected exceptions, following the RAII (Resource Acquisition Is Initialization) pattern.

### Pattern: Broken Symlink Detection

The correct way to detect broken symlinks:
```python
# CORRECT: is_symlink() first, then exists()
if item.is_symlink() and not item.exists():
    # item is a broken symlink

# WRONG: Using lexists() alone
if not item.exists():  # False for both broken links AND missing files
```

The `exists()` method follows symlinks, so broken symlinks return False. Combined with `is_symlink()`, this reliably identifies broken links.

### Pattern: Timestamped Backup Storage

Directory structure:
```
~/.harnesssync/backups/
  codex/
    config.toml_20260214_142900/
      config.toml
    config.toml_20260214_150500/
      config.toml
  opencode/
    config.yaml_20260214_143000/
      config.yaml
```

Benefits:
- Chronologically sortable by modification time
- Human-readable timestamps
- Isolated by target name for cleanup efficiency
- Preserves original filename for restoration

## Files Created

1. **src/backup_manager.py** (214 lines)
   - BackupManager class
   - BackupContext context manager
   - Timestamped backup creation
   - LIFO rollback restoration
   - Retention policy cleanup

2. **src/symlink_cleaner.py** (142 lines)
   - SymlinkCleaner class
   - Broken symlink detection
   - Target-aware cleanup
   - Graceful error handling

## Commits

| Hash    | Message                                                                 |
|---------|-------------------------------------------------------------------------|
| 9b89d24 | feat(05-01): implement BackupManager with timestamped backup and rollback |
| 81ca0b9 | feat(05-01): implement SymlinkCleaner for broken symlink removal        |

## Next Steps

1. **Plan 05-02:** Implement ConflictDetector for hash-based drift detection and SecretDetector for environment variable scanning
2. **Integration testing:** Add backup/rollback integration to SyncOrchestrator
3. **Performance testing:** Defer large directory backup performance validation (DEFER-05-02)
4. **Windows testing:** Defer Windows junction detection validation (DEFER-05-01)

## Self-Check: PASSED

✓ src/backup_manager.py exists
✓ src/symlink_cleaner.py exists
✓ Commit 9b89d24 exists
✓ Commit 81ca0b9 exists
✓ All 10 verification tests passed
✓ No deviations from plan
