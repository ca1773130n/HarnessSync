# Plan 07-02 Summary: Installation Scripts

**Status:** Complete
**Duration:** ~1 min
**Files modified:** install.sh (rewritten), shell-integration.sh (rewritten)

## What Was Done

1. **Rewrote install.sh** with:
   - HarnessSync branding (all cc2all references removed)
   - `--dry-run` flag support (prints what would be done, skips mutations)
   - Platform detection (macOS/Linux/Windows/WSL via $OSTYPE and wslpath)
   - Python version check (warns if < 3.10)
   - 4-step flow: platform detect → dir creation → shell integration → platform notes
   - Idempotent shell RC modification (grep -q "HarnessSync" before appending)
   - Removed: cc2all references, file copying to ~/.cc2all/, hook setup, initial sync, CLI checks

2. **Rewrote shell-integration.sh** with:
   - All cc2all variables → HARNESSSYNC_* (HARNESSSYNC_HOME, HARNESSSYNC_COOLDOWN, etc.)
   - All cc2all functions → _harnesssync_*
   - `cc2all()` → `harnesssync()` manual command
   - Sync invocation via Python one-liner importing SyncOrchestrator
   - Removed `_cc2all_register_hook` (handled by plugin system)
   - Preserved wrapper pattern for codex/gemini/opencode

## Key Decisions

- **Decision #57:** Shell-integration invokes sync via `python3 -c "from src.orchestrator import SyncOrchestrator; ..."` instead of standalone script
- **Decision #58:** HARNESSSYNC_HOME defaults to directory containing shell-integration.sh (not fixed path)
- **Decision #59:** Stamp file at `$HOME/.harnesssync/.last-sync` (not ~/.cc2all/)

## Verification Results

| Check | Status |
|-------|--------|
| install.sh executable | PASS |
| install.sh syntax (bash -n) | PASS |
| shell-integration.sh syntax (bash -n) | PASS |
| install.sh --dry-run completes | PASS |
| No cc2all references (install.sh) | PASS |
| No cc2all references (shell-integration.sh) | PASS |
| HarnessSync branding present | PASS |
| Wrapper functions (codex/gemini/opencode) present | PASS |
