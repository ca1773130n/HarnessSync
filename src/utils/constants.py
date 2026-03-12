from __future__ import annotations

# Canonical target lists - import these instead of hardcoding
CORE_TARGETS: tuple[str, ...] = ("codex", "gemini", "opencode", "cursor", "aider", "windsurf")
EXTENDED_TARGETS: tuple[str, ...] = CORE_TARGETS + ("cline", "continue", "zed", "neovim")
ALL_TARGETS: tuple[str, ...] = EXTENDED_TARGETS

# Section names used throughout the codebase
ALL_SECTIONS: tuple[str, ...] = ("rules", "skills", "agents", "commands", "mcp", "settings")

# Support level constants
SUPPORT_FULL = "full"
SUPPORT_PARTIAL = "partial"
SUPPORT_NONE = "none"
