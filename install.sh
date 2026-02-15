#!/usr/bin/env bash
# ─────────────────────────────────────────────
# HarnessSync installer
# Supports: macOS, Linux, Windows (WSL2/Git Bash)
# ─────────────────────────────────────────────

set -euo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
BLUE="\033[34m"
YELLOW="\033[33m"
RED="\033[31m"
NC="\033[0m"

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --dry-run)
            DRY_RUN=true
            ;;
    esac
done

echo -e "\n${BOLD}${BLUE}╔═══════════════════════════════════════╗${NC}"
echo -e "${BOLD}${BLUE}║  HarnessSync Installation             ║${NC}"
echo -e "${BOLD}${BLUE}║  Claude Code → Codex + Gemini + OC    ║${NC}"
echo -e "${BOLD}${BLUE}╚═══════════════════════════════════════╝${NC}\n"

if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}[DRY RUN] No changes will be made${NC}\n"
fi

# ── Step 1/4: Platform detection ──
echo -e "${BLUE}[1/4] Detecting platform${NC}"

OS_TYPE="unknown"
if [[ "${OSTYPE:-}" == "darwin"* ]]; then
    OS_TYPE="macos"
elif command -v wslpath >/dev/null 2>&1; then
    OS_TYPE="wsl"
elif [[ "${OSTYPE:-}" == "linux-gnu"* ]]; then
    OS_TYPE="linux"
elif [[ "${OSTYPE:-}" == "msys" || "${OSTYPE:-}" == "win32" ]]; then
    OS_TYPE="windows"
fi

echo -e "  Platform: ${BOLD}${OS_TYPE}${NC}"

# Python version check
if command -v python3 >/dev/null 2>&1; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "unknown")
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [[ "$PY_MAJOR" -ge 3 && "$PY_MINOR" -ge 10 ]] 2>/dev/null; then
        echo -e "  Python:   ${GREEN}${PY_VER}${NC}"
    else
        echo -e "  Python:   ${YELLOW}${PY_VER} (3.10+ recommended)${NC}"
    fi
else
    echo -e "  Python:   ${RED}not found${NC}"
    echo -e "  ${YELLOW}HarnessSync requires Python 3.10+${NC}"
fi

# ── Step 2/4: Create target directories ──
echo -e "\n${BLUE}[2/4] Creating target directories${NC}"

if [[ "$DRY_RUN" == true ]]; then
    echo -e "  [DRY RUN] Would create \${CODEX_HOME:-~/.codex}/skills/"
    echo -e "  [DRY RUN] Would create ~/.gemini/"
    echo -e "  [DRY RUN] Would create ~/.config/opencode/{skills,agents,commands}/"
else
    mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
    mkdir -p "$HOME/.gemini"
    mkdir -p "$HOME/.config/opencode/skills"
    mkdir -p "$HOME/.config/opencode/agents"
    mkdir -p "$HOME/.config/opencode/commands"
    echo -e "  ${GREEN}✓${NC} \${CODEX_HOME:-~/.codex}/skills/"
    echo -e "  ${GREEN}✓${NC} ~/.gemini/"
    echo -e "  ${GREEN}✓${NC} ~/.config/opencode/{skills,agents,commands}/"
fi

# ── Step 3/4: Shell integration ──
echo -e "\n${BLUE}[3/4] Shell integration${NC}"

SHELL_RC=""
if [[ -n "${ZSH_VERSION:-}" ]] || [[ "${SHELL:-}" == *"zsh"* ]]; then
    SHELL_RC="$HOME/.zshrc"
elif [[ -n "${BASH_VERSION:-}" ]] || [[ "${SHELL:-}" == *"bash"* ]]; then
    SHELL_RC="$HOME/.bashrc"
fi

if [[ -z "$SHELL_RC" ]]; then
    echo -e "  ${YELLOW}Could not detect shell (bash/zsh)${NC}"
    echo -e "  Add manually to your shell profile:"
    echo -e "    source \"$PLUGIN_ROOT/shell-integration.sh\""
elif [[ "$DRY_RUN" == true ]]; then
    echo -e "  [DRY RUN] Would add HarnessSync to $SHELL_RC"
else
    if grep -q "HarnessSync" "$SHELL_RC" 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} Already in $SHELL_RC"
    else
        echo "" >> "$SHELL_RC"
        echo "# HarnessSync: Claude Code → All Harnesses auto-sync" >> "$SHELL_RC"
        echo "source \"$PLUGIN_ROOT/shell-integration.sh\"" >> "$SHELL_RC"
        echo -e "  ${GREEN}✓${NC} Added to $SHELL_RC"
    fi
fi

# ── Step 4/4: Platform info ──
echo -e "\n${BLUE}[4/4] Platform notes${NC}"

case $OS_TYPE in
    macos)
        echo -e "  ${GREEN}✓${NC} macOS: native symlinks supported"
        ;;
    linux)
        echo -e "  ${GREEN}✓${NC} Linux: native symlinks supported"
        ;;
    windows)
        echo -e "  ${YELLOW}!${NC} Windows native: junction points for directories, copy for files"
        echo -e "    (no admin privileges required)"
        ;;
    wsl)
        echo -e "  ${GREEN}✓${NC} WSL2: native symlinks supported in Linux filesystem"
        ;;
    *)
        echo -e "  ${YELLOW}!${NC} Unknown platform: symlinks may require manual setup"
        ;;
esac

# ── Done ──
echo -e "\n${BOLD}${GREEN}═══════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  HarnessSync installation complete!${NC}"
echo -e "${BOLD}${GREEN}═══════════════════════════════════════${NC}"

if [[ "$DRY_RUN" == false ]]; then
    echo ""
    echo -e "  ${BOLD}Next steps:${NC}"
    if [[ -n "$SHELL_RC" ]]; then
        echo -e "  1. Restart your shell:  ${BLUE}source $SHELL_RC${NC}"
    fi
    echo -e "  2. Check status:        ${BLUE}/sync-status${NC}"
    echo -e "  3. Run first sync:      ${BLUE}/sync${NC}"
    echo ""
fi
