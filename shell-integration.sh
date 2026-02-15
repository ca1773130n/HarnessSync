#!/usr/bin/env bash
# ─────────────────────────────────────────────
# HarnessSync shell integration
# Source this from ~/.bashrc or ~/.zshrc:
#   source /path/to/HarnessSync/shell-integration.sh
#
# This wraps codex, gemini, opencode commands to
# auto-sync from Claude Code before launch.
# Claude Code itself is untouched — it's the master.
# ─────────────────────────────────────────────

HARNESSSYNC_HOME="${HARNESSSYNC_HOME:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"
HARNESSSYNC_COOLDOWN="${HARNESSSYNC_COOLDOWN:-300}"  # 5 minutes between auto-syncs
HARNESSSYNC_STAMP="$HOME/.harnesssync/.last-sync"

_harnesssync_should_sync() {
    # Check if enough time has passed since last sync
    if [[ ! -f "$HARNESSSYNC_STAMP" ]]; then
        return 0  # never synced
    fi
    local last now diff
    last=$(cat "$HARNESSSYNC_STAMP" 2>/dev/null || echo 0)
    now=$(date +%s)
    diff=$((now - last))
    [[ $diff -ge $HARNESSSYNC_COOLDOWN ]]
}

_harnesssync_auto_sync() {
    local scope="${1:-all}"
    if _harnesssync_should_sync; then
        if [[ "${HARNESSSYNC_VERBOSE:-0}" == "1" ]]; then
            python3 -c "
import sys; sys.path.insert(0, '$HARNESSSYNC_HOME')
from src.orchestrator import SyncOrchestrator
o = SyncOrchestrator()
o.sync_all()
" 2>&1
        else
            python3 -c "
import sys; sys.path.insert(0, '$HARNESSSYNC_HOME')
from src.orchestrator import SyncOrchestrator
o = SyncOrchestrator()
o.sync_all()
" >/dev/null 2>&1
        fi
        mkdir -p "$(dirname "$HARNESSSYNC_STAMP")"
        date +%s > "$HARNESSSYNC_STAMP"
    fi
}

# ─── Wrapper: codex ───
if command -v codex &>/dev/null; then
    _harnesssync_original_codex="$(command -v codex)"
    codex() {
        _harnesssync_auto_sync all &
        "$_harnesssync_original_codex" "$@"
    }
fi

# ─── Wrapper: gemini ───
if command -v gemini &>/dev/null; then
    _harnesssync_original_gemini="$(command -v gemini)"
    gemini() {
        _harnesssync_auto_sync all &
        "$_harnesssync_original_gemini" "$@"
    }
fi

# ─── Wrapper: opencode ───
if command -v opencode &>/dev/null; then
    _harnesssync_original_opencode="$(command -v opencode)"
    opencode() {
        _harnesssync_auto_sync all &
        "$_harnesssync_original_opencode" "$@"
    }
fi

# ─── Manual commands ───

harnesssync() {
    case "${1:-sync}" in
        sync)
            shift 2>/dev/null || true
            python3 -c "
import sys; sys.path.insert(0, '$HARNESSSYNC_HOME')
from src.orchestrator import SyncOrchestrator
o = SyncOrchestrator()
o.sync_all()
" 2>&1
            ;;
        status)
            echo "HarnessSync status:"
            if [[ -f "$HARNESSSYNC_STAMP" ]]; then
                local last now ago
                last=$(cat "$HARNESSSYNC_STAMP")
                now=$(date +%s)
                ago=$((now - last))
                echo "  Last sync: ${ago}s ago"
            else
                echo "  Last sync: never"
            fi
            echo "  Cooldown: ${HARNESSSYNC_COOLDOWN}s"
            echo "  Home: $HARNESSSYNC_HOME"
            echo ""
            echo "  Targets:"
            _harnesssync_check_target "Codex"    "${CODEX_HOME:-$HOME/.codex}/AGENTS.md"
            _harnesssync_check_target "Gemini"   "$HOME/.gemini/GEMINI.md"
            _harnesssync_check_target "OpenCode" "$HOME/.config/opencode/AGENTS.md"
            ;;
        force)
            shift 2>/dev/null || true
            rm -f "$HARNESSSYNC_STAMP"
            python3 -c "
import sys; sys.path.insert(0, '$HARNESSSYNC_HOME')
from src.orchestrator import SyncOrchestrator
o = SyncOrchestrator()
o.sync_all()
" 2>&1
            ;;
        help|--help|-h)
            cat <<'EOF'
HarnessSync — Claude Code → All Harnesses Sync

Commands:
  harnesssync [sync]       Sync now
  harnesssync force        Force sync (ignore cooldown)
  harnesssync status       Show sync status
  harnesssync help         Show this help

Options:
  HARNESSSYNC_COOLDOWN=300  Seconds between auto-syncs (default: 300)
  HARNESSSYNC_VERBOSE=1     Show sync output on auto-sync

Auto-sync happens transparently when you run:
  codex, gemini, opencode
EOF
            ;;
        *)
            echo "Unknown command: $1 (try: harnesssync help)"
            ;;
    esac
}

_harnesssync_check_target() {
    local name="$1" path="$2"
    if [[ -f "$path" ]]; then
        echo "    ✓ $name: $path ($(wc -l < "$path") lines)"
    else
        echo "    · $name: not synced yet"
    fi
}
