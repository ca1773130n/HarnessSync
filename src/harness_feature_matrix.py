from __future__ import annotations

"""Live Harness Feature Support Matrix (item 31).

A comprehensive, queryable matrix of which Claude Code features each supported
harness handles, annotated with support levels and version requirements.

Support levels:
  "native"      — Feature maps directly to a first-class harness construct.
  "partial"     — Feature syncs with some loss or conversion required.
  "adapter"     — Feature is emulated via workaround (e.g. rules → .mdc bodies).
  "unsupported" — Feature cannot be represented in this harness at all.

Features tracked:
  rules         CLAUDE.md rule content
  skills        .claude/skills/ skill files
  agents        .claude/agents/ sub-agent definitions
  commands      .claude/commands/ slash commands
  mcp           MCP server configurations
  hooks         .claude/settings.json hook definitions
  settings      Permission / model / env settings
  env_vars      Environment variable forwarding
  plugins       Claude Code plugin definitions

Covered harnesses (matching HarnessSync adapter targets):
  codex, gemini, opencode, cursor, aider, windsurf, cline, continue, zed, neovim

Usage:
    from src.harness_feature_matrix import HarnessFeatureMatrix

    matrix = HarnessFeatureMatrix()
    print(matrix.format_matrix_table())

    # Query a single feature across all harnesses:
    print(matrix.query_feature("mcp"))

    # Query a single harness across all features:
    print(matrix.query_harness("cursor"))

    # Get unsupported features for a harness:
    print(matrix.get_support_gaps("aider"))
"""

from dataclasses import dataclass, field
from pathlib import Path


# ── Support level type alias ────────────────────────────────────────────────

SupportLevel = str   # "native" | "partial" | "adapter" | "unsupported"

_VALID_LEVELS: frozenset[str] = frozenset(
    {"native", "partial", "adapter", "unsupported"}
)

# ── All features and harnesses ──────────────────────────────────────────────

ALL_FEATURES: list[str] = [
    "rules",
    "skills",
    "agents",
    "commands",
    "mcp",
    "hooks",
    "settings",
    "env_vars",
    "plugins",
]

ALL_HARNESSES: list[str] = [
    "codex",
    "gemini",
    "opencode",
    "cursor",
    "aider",
    "windsurf",
    "cline",
    "continue",
    "zed",
    "neovim",
]

# ── Feature matrix ──────────────────────────────────────────────────────────
# Structure: {feature: {harness: SupportLevel}}
#
# Rationale for each entry is documented inline.  The data is derived from:
# - config_health.py _TARGET_NATIVE_FRACTIONS
# - skill_compatibility.py TARGET_LIMITATIONS
# - harness_version_compat.py VERSIONED_FEATURES
# - sync_matrix.py CAPABILITY_MATRIX (where it exists in the project)

_FEATURE_MATRIX: dict[str, dict[str, SupportLevel]] = {

    "rules": {
        # Rules (CLAUDE.md content) translate to every harness's system-prompt
        # or rules file.  All support it; quality of fidelity varies.
        "codex":    "native",     # → AGENTS.md, fully inlined
        "gemini":   "native",     # → GEMINI.md, fully inlined
        "opencode": "native",     # → OPENCODE.md / opencode.json system field
        "cursor":   "native",     # → .cursor/rules/*.mdc, glob-scoped
        "aider":    "native",     # → CONVENTIONS.md, fully inlined
        "windsurf": "native",     # → .windsurfrules, fully inlined
        "cline":    "native",     # → .clinerules, fully inlined
        "continue": "native",     # → .continue/rules/harnesssync.md
        "zed":      "native",     # → .rules
        "neovim":   "native",     # → .avante/rules/system-prompt.avanterules
    },

    "skills": {
        # Skills are reusable workflow descriptions.  Most harnesses can receive
        # them as additional context files; a few have no skill concept at all.
        "codex":    "native",     # → .agents/skills/
        "gemini":   "native",     # → .gemini/skills/
        "opencode": "native",     # → .opencode/skills/
        "cursor":   "partial",    # → .cursor/rules/skills/ as .mdc (format converted)
        "aider":    "adapter",    # → read_files list in .aider.conf.yml (context only)
        "windsurf": "adapter",    # → .windsurf/memories/ (memory format)
        "cline":    "partial",    # → .roo/rules/skills/ (minor format adaptation)
        "continue": "partial",    # → .continue/rules/skills/ (prompt format)
        "zed":      "unsupported",# Zed has no skill / reusable prompt concept
        "neovim":   "unsupported",# avante.nvim has no native skill system
    },

    "agents": {
        # Sub-agent definitions (.claude/agents/).  Only a few harnesses have a
        # native agent system; others convert to inlined instructions.
        "codex":    "partial",    # → AGENTS.md agent sections (no separate files)
        "gemini":   "partial",    # → GEMINI.md agent sections
        "opencode": "partial",    # → OPENCODE.md agent sections
        "cursor":   "adapter",    # → flattened into .cursor/rules/ bodies
        "aider":    "adapter",    # → flattened into CONVENTIONS.md
        "windsurf": "adapter",    # → flattened into .windsurfrules
        "cline":    "partial",    # → .clinerules agent section
        "continue": "adapter",    # → .continue/rules/ prompt blocks
        "zed":      "adapter",    # → .rules prose block
        "neovim":   "adapter",    # → .avante/rules/ .avanterules files
    },

    "commands": {
        # Slash commands (.claude/commands/).  Very few harnesses have an
        # equivalent command palette concept.
        "codex":    "partial",    # → documented in AGENTS.md (not executable)
        "gemini":   "unsupported",# Gemini CLI has no slash command system
        "opencode": "partial",    # → opencode.json keybinding section (limited)
        "cursor":   "partial",    # → .cursor/rules/ as inline usage instructions
        "aider":    "unsupported",# Aider has no slash command forwarding
        "windsurf": "adapter",    # → .windsurfrules command reference block
        "cline":    "partial",    # → .clinerules command documentation
        "continue": "partial",    # → .continue/rules/ slash command stubs
        "zed":      "unsupported",# Zed assistant has no command forwarding
        "neovim":   "unsupported",# avante.nvim has no command forwarding
    },

    "mcp": {
        # MCP server configuration.  Harnesses vary widely in support.
        "codex":    "native",     # → .codex/config.toml [mcp.servers.*]
        "gemini":   "native",     # → .gemini/settings.json mcpServers
        "opencode": "native",     # → .opencode/settings.json mcpServers
        "cursor":   "native",     # → .cursor/mcp.json (Cursor ≥ 0.43)
        "aider":    "unsupported",# Aider has no MCP server concept
        "windsurf": "native",     # → .codeium/windsurf/mcp_config.json (Windsurf ≥ 1.0)
        "cline":    "native",     # → .roo/mcp.json
        "continue": "native",     # → .continue/config.json mcpServers
        "zed":      "native",     # → .zed/settings.json context_servers
        "neovim":   "native",     # → .avante/mcp.json
    },

    "hooks": {
        # Claude Code lifecycle hooks (PostToolUse, PreToolUse, etc.).
        # No harness has an equivalent hook system; hooks are either dropped
        # or partially documented as instructions.
        "codex":    "unsupported",
        "gemini":   "unsupported",
        "opencode": "unsupported",
        "cursor":   "unsupported",
        "aider":    "unsupported",
        "windsurf": "unsupported",
        "cline":    "unsupported",
        "continue": "unsupported",
        "zed":      "unsupported",
        "neovim":   "unsupported",
    },

    "settings": {
        # Permission / model / env settings from claude settings.json.
        # Most harnesses have some form of settings but the fields differ.
        "codex":    "partial",    # → approval_policy, sandbox_mode in config.toml
        "gemini":   "partial",    # → tools.exclude / tools.allowed in settings.json
        "opencode": "partial",    # → model/provider in opencode.json
        "cursor":   "partial",    # → frontmatter in .mdc files (limited fields)
        "aider":    "partial",    # → .aider.conf.yml model / auto-commit flags
        "windsurf": "partial",    # → .windsurfrules preamble settings
        "cline":    "partial",    # → .roo/config.json (model settings)
        "continue": "partial",    # → .continue/config.json model selection
        "zed":      "partial",    # → .zed/settings.json assistant section
        "neovim":   "partial",    # → .avante/config.lua model config
    },

    "env_vars": {
        # Environment variable forwarding (settings.json env section).
        "codex":    "partial",    # → env block in config.toml
        "gemini":   "unsupported",# Gemini CLI does not read env from config
        "opencode": "native",     # → opencode.json env section
        "cursor":   "unsupported",# Cursor does not expose env var forwarding
        "aider":    "partial",    # → .env file (referenced via .aider.conf.yml)
        "windsurf": "unsupported",# Windsurf has no env forwarding
        "cline":    "partial",    # → .roo/config.json environment section
        "continue": "unsupported",# Continue has no env forwarding mechanism
        "zed":      "unsupported",# Zed assistant has no env forwarding
        "neovim":   "unsupported",# avante.nvim does not forward env vars
    },

    "plugins": {
        # Claude Code plugin definitions ($CLAUDE_PLUGIN_ROOT).
        # No other harness has a plugin system equivalent.
        "codex":    "unsupported",
        "gemini":   "unsupported",
        "opencode": "unsupported",
        "cursor":   "unsupported",
        "aider":    "unsupported",
        "windsurf": "unsupported",
        "cline":    "unsupported",
        "continue": "unsupported",
        "zed":      "unsupported",
        "neovim":   "unsupported",
    },
}

# ── Minimum version requirements per (harness, feature) ─────────────────────
# Only populated where a minimum harness version gate applies.
# Format: {harness: {feature: (min_version, note)}}

VERSION_REQUIREMENTS: dict[str, dict[str, tuple[str, str]]] = {
    "cursor": {
        "mcp":    ("0.43", ".cursor/mcp.json introduced in Cursor 0.43"),
        "skills": ("0.42", "glob-scoped .mdc rules required for skill files"),
    },
    "windsurf": {
        "mcp":    ("1.0", "mcp_config.json introduced in Windsurf 1.0"),
        "skills": ("1.2", "memory files for skills introduced in Windsurf 1.2"),
    },
    "codex": {
        "settings": ("1.2", "approval_policy / sandbox_mode require Codex 1.2+"),
    },
    "gemini": {
        "settings": ("1.5", "tools.exclude requires Gemini CLI 1.5+"),
    },
    "aider": {
        "skills": ("0.50", "read_files list for skill context requires Aider 0.50+"),
    },
}

# ── Support level ordering for display / comparison ─────────────────────────

_LEVEL_ORDER: dict[str, int] = {
    "native":      0,
    "partial":     1,
    "adapter":     2,
    "unsupported": 3,
}

# Short display labels for each level
_LEVEL_LABELS: dict[str, str] = {
    "native":      "native   ",
    "partial":     "partial  ",
    "adapter":     "adapter  ",
    "unsupported": "---      ",
}

# ── Result dataclasses ──────────────────────────────────────────────────────

@dataclass
class FeatureSupportEntry:
    """Describes one harness's support for one feature.

    Attributes:
        harness:         Canonical harness name.
        feature:         Feature name.
        level:           One of "native", "partial", "adapter", "unsupported".
        min_version:     Minimum harness version required (empty string = any).
        version_note:    Human-readable note about version requirements.
    """
    harness: str
    feature: str
    level: SupportLevel
    min_version: str = ""
    version_note: str = ""


@dataclass
class MatrixQueryResult:
    """Result of a matrix query (by feature or by harness).

    Attributes:
        key:          The queried feature name or harness name.
        query_type:   "feature" or "harness".
        entries:      One entry per row in the result.
    """
    key: str
    query_type: str   # "feature" | "harness"
    entries: list[FeatureSupportEntry] = field(default_factory=list)

    def as_dict(self) -> dict[str, str]:
        """Return a flat {counterpart: level} dict for easy consumption."""
        return {e.harness if self.query_type == "feature" else e.feature: e.level
                for e in self.entries}


# ── Per-cell hover notes for the HTML report ────────────────────────────────
# Keyed by (feature, harness). Displayed as tooltip in export_html_report().

_FEATURE_NOTES: dict[tuple[str, str], str] = {
    ("skills", "gemini"):   "Inlined into GEMINI.md — no dedicated skill runtime",
    ("skills", "aider"):    "No skill system — content appended to CONVENTIONS.md",
    ("agents", "gemini"):   "Inlined into GEMINI.md — no sub-agent dispatch",
    ("commands", "gemini"): "Summarized as prose in GEMINI.md — not executable",
    ("commands", "aider"):  "Translated to shell aliases in CONVENTIONS.md",
    ("hooks", "codex"):     "Mapped to closest Codex lifecycle hooks — subset only",
    ("hooks", "cursor"):    "No hook runtime — converted to .mdc guardrails",
    ("hooks", "aider"):     "No hook system — converted to --before/after-apply flags",
    ("plugins", "codex"):   "No plugin API — rules inlined into AGENTS.md",
    ("plugins", "gemini"):  "No plugin API — rules inlined into GEMINI.md",
    ("plugins", "aider"):   "No plugin system — rules added to CONVENTIONS.md",
    ("mcp", "aider"):       "Aider cannot execute MCP servers — tools unavailable",
    ("env_vars", "codex"):  "Forwarded via config.toml [env] section",
    ("env_vars", "cursor"): "No env forwarding — must set in OS/shell manually",
}


# ── HarnessFeatureMatrix ────────────────────────────────────────────────────

class HarnessFeatureMatrix:
    """Queryable feature support matrix for all HarnessSync targets.

    Exposes the static ``_FEATURE_MATRIX`` with convenience accessors and
    terminal-friendly formatting.  No I/O is performed — all data is static.

    Usage:
        matrix = HarnessFeatureMatrix()
        matrix.format_matrix_table()
        matrix.query_feature("mcp")
        matrix.query_harness("aider")
        matrix.get_support_gaps("aider")
    """

    def __init__(self) -> None:
        # Validate the static data at construction time so callers get early
        # errors if a future edit introduces invalid levels.
        for feature, harness_map in _FEATURE_MATRIX.items():
            for harness, level in harness_map.items():
                if level not in _VALID_LEVELS:
                    raise ValueError(
                        f"Invalid support level '{level}' for "
                        f"feature='{feature}' harness='{harness}'"
                    )

    # ── Queries ──────────────────────────────────────────────────────────────

    def query_feature(
        self,
        feature_name: str,
        targets: list[str] | None = None,
    ) -> dict[str, SupportLevel]:
        """Return a {harness: support_level} dict for one feature.

        Args:
            feature_name: Feature to query (e.g. "mcp").
            targets:      Subset of harnesses to include (default: all).

        Returns:
            Dict mapping harness name → support level.

        Raises:
            KeyError: If feature_name is not in the matrix.
        """
        if feature_name not in _FEATURE_MATRIX:
            raise KeyError(
                f"Unknown feature '{feature_name}'. "
                f"Available: {', '.join(ALL_FEATURES)}"
            )
        row = _FEATURE_MATRIX[feature_name]
        if targets:
            return {h: row[h] for h in targets if h in row}
        return dict(row)

    def query_harness(
        self,
        harness_name: str,
        features: list[str] | None = None,
    ) -> dict[str, SupportLevel]:
        """Return a {feature: support_level} dict for one harness.

        Args:
            harness_name: Harness to query (e.g. "cursor").
            features:     Subset of features to include (default: all).

        Returns:
            Dict mapping feature name → support level.

        Raises:
            KeyError: If harness_name is not in the matrix.
        """
        if harness_name not in ALL_HARNESSES:
            raise KeyError(
                f"Unknown harness '{harness_name}'. "
                f"Available: {', '.join(ALL_HARNESSES)}"
            )
        feature_list = features or ALL_FEATURES
        return {
            feat: _FEATURE_MATRIX[feat][harness_name]
            for feat in feature_list
            if feat in _FEATURE_MATRIX and harness_name in _FEATURE_MATRIX[feat]
        }

    def get_support_gaps(self, harness_name: str) -> list[str]:
        """Return the list of features that are unsupported by a harness.

        Args:
            harness_name: Canonical harness name.

        Returns:
            Sorted list of feature names with level "unsupported".
        """
        if harness_name not in ALL_HARNESSES:
            raise KeyError(
                f"Unknown harness '{harness_name}'. "
                f"Available: {', '.join(ALL_HARNESSES)}"
            )
        return sorted(
            feat
            for feat, harness_map in _FEATURE_MATRIX.items()
            if harness_map.get(harness_name) == "unsupported"
        )

    def get_native_features(self, harness_name: str) -> list[str]:
        """Return the list of features natively supported by a harness.

        Args:
            harness_name: Canonical harness name.

        Returns:
            Sorted list of feature names with level "native".
        """
        if harness_name not in ALL_HARNESSES:
            raise KeyError(
                f"Unknown harness '{harness_name}'. "
                f"Available: {', '.join(ALL_HARNESSES)}"
            )
        return sorted(
            feat
            for feat, harness_map in _FEATURE_MATRIX.items()
            if harness_map.get(harness_name) == "native"
        )

    def get_entry(
        self,
        feature: str,
        harness: str,
    ) -> FeatureSupportEntry:
        """Return a FeatureSupportEntry for a specific (feature, harness) pair.

        Args:
            feature: Feature name.
            harness: Harness name.

        Returns:
            FeatureSupportEntry with level and version information.
        """
        level = _FEATURE_MATRIX.get(feature, {}).get(harness, "unsupported")
        version_info = VERSION_REQUIREMENTS.get(harness, {}).get(feature, ("", ""))
        min_version, version_note = version_info if version_info else ("", "")
        return FeatureSupportEntry(
            harness=harness,
            feature=feature,
            level=level,
            min_version=min_version,
            version_note=version_note,
        )

    # ── Coverage stats ───────────────────────────────────────────────────────

    def native_fraction(self, harness_name: str) -> float:
        """Return the fraction of features that are natively supported (0.0-1.0).

        Mirrors the ``_TARGET_NATIVE_FRACTIONS`` values in config_health.py,
        but computed dynamically from the live matrix.

        Args:
            harness_name: Canonical harness name.

        Returns:
            Float between 0.0 and 1.0.
        """
        total = len(ALL_FEATURES)
        if total == 0:
            return 0.0
        native = sum(
            1 for feat in ALL_FEATURES
            if _FEATURE_MATRIX.get(feat, {}).get(harness_name) == "native"
        )
        return native / total

    def coverage_score(self, harness_name: str) -> int:
        """Return an integer coverage score 0-100 for a harness.

        Weights:
          native      = 1.0 credit
          partial     = 0.6 credit
          adapter     = 0.3 credit
          unsupported = 0.0 credit
        """
        _WEIGHTS: dict[str, float] = {
            "native":      1.0,
            "partial":     0.6,
            "adapter":     0.3,
            "unsupported": 0.0,
        }
        total = len(ALL_FEATURES)
        if total == 0:
            return 0
        credit = sum(
            _WEIGHTS.get(_FEATURE_MATRIX.get(feat, {}).get(harness_name, "unsupported"), 0.0)
            for feat in ALL_FEATURES
        )
        return round((credit / total) * 100)

    # ── Formatting ───────────────────────────────────────────────────────────

    def format_matrix_table(
        self,
        features: list[str] | None = None,
        targets: list[str] | None = None,
    ) -> str:
        """Return a terminal-friendly feature support matrix table.

        Args:
            features: Subset of features to include (default: all).
            targets:  Subset of harnesses to include (default: all).

        Returns:
            Multi-line formatted string.
        """
        feat_list = features or ALL_FEATURES
        tgt_list = targets or ALL_HARNESSES

        # Column widths
        feat_col = max(len(f) for f in feat_list) + 2  # feature name col

        # Harness column width = max(harness_name, "native   ") = 10
        tgt_col = 10

        # Build header
        header = f"{'Feature':<{feat_col}}"
        for tgt in tgt_list:
            header += f"  {tgt:<{tgt_col}}"
        header += "  Notes"

        sep = "-" * (feat_col + (tgt_col + 2) * len(tgt_list) + 8)

        lines: list[str] = [
            "Harness Feature Support Matrix",
            "=" * max(len(sep), 40),
            "",
            "Support levels:  native = full  partial = some loss  adapter = workaround  --- = unsupported",
            "",
            header,
            sep,
        ]

        for feat in feat_list:
            row = f"{feat:<{feat_col}}"
            version_notes: list[str] = []
            for tgt in tgt_list:
                level = _FEATURE_MATRIX.get(feat, {}).get(tgt, "unsupported")
                label = _LEVEL_LABELS.get(level, "         ")
                row += f"  {label:<{tgt_col}}"
                # Collect version requirements
                ver_info = VERSION_REQUIREMENTS.get(tgt, {}).get(feat)
                if ver_info:
                    version_notes.append(f"{tgt}≥{ver_info[0]}")
            if version_notes:
                row += f"  requires {', '.join(version_notes)}"
            lines.append(row)

        lines.append(sep)

        # Coverage summary row
        summary = f"{'Coverage %':<{feat_col}}"
        for tgt in tgt_list:
            score = self.coverage_score(tgt)
            summary += f"  {score:>3}%      "
        lines.append(summary)

        lines += [
            "",
            "Coverage % = weighted score (native=100%, partial=60%, adapter=30%, unsupported=0%)",
        ]

        return "\n".join(lines)

    def format_harness_summary(self, harness_name: str) -> str:
        """Return a per-harness feature support summary.

        Args:
            harness_name: Canonical harness name.

        Returns:
            Multi-line formatted string.
        """
        if harness_name not in ALL_HARNESSES:
            return f"Unknown harness '{harness_name}'."

        level_map = self.query_harness(harness_name)
        score = self.coverage_score(harness_name)
        native = self.get_native_features(harness_name)
        gaps = self.get_support_gaps(harness_name)

        lines: list[str] = [
            f"Feature Support: {harness_name}",
            "=" * 40,
            f"  Coverage score: {score}/100",
            f"  Native features ({len(native)}):  {', '.join(native) or 'none'}",
            f"  Unsupported ({len(gaps)}):  {', '.join(gaps) or 'none'}",
            "",
            "  Feature breakdown:",
        ]

        for feat in ALL_FEATURES:
            level = level_map.get(feat, "unsupported")
            label = level.capitalize()
            ver_info = VERSION_REQUIREMENTS.get(harness_name, {}).get(feat)
            ver_str = f"  (requires {harness_name} ≥ {ver_info[0]})" if ver_info else ""
            lines.append(f"    {feat:<12} {label}{ver_str}")

        return "\n".join(lines)

    def format_feature_summary(self, feature_name: str) -> str:
        """Return a per-feature support summary across all harnesses.

        Args:
            feature_name: Feature name.

        Returns:
            Multi-line formatted string.
        """
        if feature_name not in _FEATURE_MATRIX:
            return f"Unknown feature '{feature_name}'."

        harness_map = _FEATURE_MATRIX[feature_name]

        # Group by level
        by_level: dict[str, list[str]] = {
            lvl: [] for lvl in ("native", "partial", "adapter", "unsupported")
        }
        for harness in ALL_HARNESSES:
            lvl = harness_map.get(harness, "unsupported")
            by_level[lvl].append(harness)

        lines: list[str] = [
            f"Feature: {feature_name}",
            "=" * 40,
        ]
        for lvl in ("native", "partial", "adapter", "unsupported"):
            harnesses = by_level[lvl]
            if harnesses:
                lines.append(f"  {lvl.capitalize():<12}: {', '.join(harnesses)}")

        # Version requirements for this feature
        ver_lines: list[str] = []
        for harness in ALL_HARNESSES:
            ver_info = VERSION_REQUIREMENTS.get(harness, {}).get(feature_name)
            if ver_info:
                ver_lines.append(f"    {harness}: requires v{ver_info[0]}+ — {ver_info[1]}")
        if ver_lines:
            lines.append("")
            lines.append("  Version requirements:")
            lines.extend(ver_lines)

        return "\n".join(lines)

    def compare_harnesses(
        self,
        harness_a: str,
        harness_b: str,
    ) -> str:
        """Return a side-by-side comparison of two harnesses.

        Args:
            harness_a: First harness name.
            harness_b: Second harness name.

        Returns:
            Multi-line formatted comparison string.
        """
        for h in (harness_a, harness_b):
            if h not in ALL_HARNESSES:
                return f"Unknown harness '{h}'."

        col = 14
        header = (
            f"{'Feature':<12}  {harness_a:<{col}}  {harness_b:<{col}}  Delta"
        )
        sep = "-" * (12 + (col + 2) * 2 + 8)

        lines: list[str] = [
            f"Harness Comparison: {harness_a} vs {harness_b}",
            "=" * max(len(sep), 40),
            "",
            header,
            sep,
        ]

        score_a = self.coverage_score(harness_a)
        score_b = self.coverage_score(harness_b)

        for feat in ALL_FEATURES:
            lvl_a = _FEATURE_MATRIX.get(feat, {}).get(harness_a, "unsupported")
            lvl_b = _FEATURE_MATRIX.get(feat, {}).get(harness_b, "unsupported")
            ord_a = _LEVEL_ORDER[lvl_a]
            ord_b = _LEVEL_ORDER[lvl_b]

            if ord_a < ord_b:
                delta = f"+ {harness_a} better"
            elif ord_b < ord_a:
                delta = f"+ {harness_b} better"
            else:
                delta = "equal"

            lines.append(
                f"{feat:<12}  {lvl_a:<{col}}  {lvl_b:<{col}}  {delta}"
            )

        lines += [
            sep,
            f"{'Coverage':<12}  {score_a}%{'':<{col - 2}}  {score_b}%",
        ]

        return "\n".join(lines)

    def format_capability_gap_dashboard(
        self,
        harnesses: list[str] | None = None,
        include_workarounds: bool = True,
    ) -> str:
        """Return a real-time capability gap dashboard for all (or specified) harnesses.

        For each harness, lists features that are missing or degraded compared
        to Claude Code, classified as either **blocking** (unsupported — the
        feature cannot be represented at all) or **advisory** (partial/adapter —
        the feature syncs with caveats).

        Each blocking gap includes a suggested workaround where one exists.

        Args:
            harnesses: Harnesses to include. Defaults to ALL_HARNESSES.
            include_workarounds: Whether to show workaround suggestions.

        Returns:
            Multi-line formatted string suitable for terminal output.
        """
        target_list = harnesses or ALL_HARNESSES

        # Workaround suggestions keyed by (feature, harness)
        _WORKAROUNDS: dict[tuple[str, str], str] = {
            ("skills", "zed"):      "Inline skill content in .rules manually.",
            ("skills", "neovim"):   "Add skill content to .avante/rules/ as .avanterules files.",
            ("commands", "gemini"): "Document commands as GEMINI.md workflow steps instead.",
            ("commands", "aider"):  "Use aider /ask prefix or shell aliases as command proxies.",
            ("commands", "zed"):    "Zed has no command forwarding — document as prose notes.",
            ("commands", "neovim"): "avante.nvim has no command system — use Neovim keymaps.",
            ("hooks", "aider"):     "Use aider --before-apply / --after-apply shell hooks instead.",
            ("hooks", "cursor"):    "Cursor has no hook system — use .cursorrules for guardrails.",
            ("plugins", "gemini"):  "Gemini CLI has no plugin API — replicate plugin rules inline.",
            ("plugins", "aider"):   "Aider has no plugin system — apply plugin rules to CONVENTIONS.md.",
            ("plugins", "cursor"):  "Replicate plugin behavior as .mdc rule files in .cursor/rules/.",
            ("plugins", "cline"):   "Cline has no plugin API — add plugin guidance to .clinerules.",
            ("plugins", "continue"):"Continue.dev has no plugins — add to .continue/rules/.",
            ("plugins", "zed"):     "Zed has no plugin extension API for AI assistants.",
            ("plugins", "neovim"):  "Use Neovim Lua config to replicate plugin behavior.",
            ("mcp", "aider"):       "Aider does not execute MCP servers — share tool context via read_files.",
            ("mcp", "vscode"):      "VS Code AI extensions lack MCP support — no workaround available.",
        }

        lines: list[str] = [
            "Capability Gap Dashboard",
            "=" * 60,
            "",
            "BLOCKING = feature has no equivalent in this harness",
            "ADVISORY = feature syncs with caveats or partial support",
            "",
        ]

        for harness in target_list:
            if harness not in ALL_HARNESSES:
                continue

            blocking: list[str] = []
            advisory: list[str] = []

            for feat in ALL_FEATURES:
                level = _FEATURE_MATRIX.get(feat, {}).get(harness, "unsupported")
                if level == "unsupported":
                    blocking.append(feat)
                elif level in ("partial", "adapter"):
                    advisory.append(feat)

            score = self.coverage_score(harness)
            header_line = f"  {harness:<12}  coverage={score}/100"
            lines.append(header_line)

            if not blocking and not advisory:
                lines.append("    All features supported natively.")
            else:
                if blocking:
                    lines.append(f"    [BLOCKING x{len(blocking)}]")
                    for feat in sorted(blocking):
                        lines.append(f"      - {feat}")
                        if include_workarounds:
                            hint = _WORKAROUNDS.get((feat, harness), "")
                            if hint:
                                lines.append(f"        Workaround: {hint}")
                if advisory:
                    lines.append(f"    [ADVISORY x{len(advisory)}]")
                    for feat in sorted(advisory):
                        lines.append(f"      ~ {feat}")

            lines.append("")

        lines.append(
            "Run /sync-gaps <harness> for full details on a specific target."
        )
        return "\n".join(lines)

    def get_features_missing_everywhere(self) -> list[str]:
        """Return features that are unsupported by every harness.

        Useful for identifying features that exist in Claude Code but have
        zero harness ecosystem support — worth flagging prominently.

        Returns:
            Sorted list of feature names with level "unsupported" in ALL harnesses.
        """
        return sorted(
            feat
            for feat in ALL_FEATURES
            if all(
                _FEATURE_MATRIX.get(feat, {}).get(h) == "unsupported"
                for h in ALL_HARNESSES
            )
        )

    def format_report_card(self, target_list: list[str] | None = None) -> str:
        """Render a visual capability gap report card for each harness.

        Shows a letter grade (A-F) and coverage score per harness, listing
        which Claude Code features have no equivalent and which are only
        partially supported.  Helps users understand what they lose when
        switching harnesses and motivates keeping Claude Code as primary.

        Item 2 — Capability Gap Report Card.

        Args:
            target_list: Harnesses to include (default: all).

        Returns:
            Multi-line formatted report card string.
        """
        targets = [t for t in (target_list or ALL_HARNESSES) if t in ALL_HARNESSES]
        if not targets:
            return "No known harnesses to report on."

        def _letter_grade(score: int) -> str:
            if score >= 90:
                return "A"
            if score >= 75:
                return "B"
            if score >= 60:
                return "C"
            if score >= 45:
                return "D"
            return "F"

        lines: list[str] = [
            "Capability Gap Report Card",
            "=" * 50,
            f"{'Harness':<12}  {'Score':>5}  {'Grade'}  {'Gaps (unsupported features)'}",
            "-" * 50,
        ]

        for harness in sorted(targets):
            score = self.coverage_score(harness)
            grade = _letter_grade(score)
            gaps = self.get_support_gaps(harness)
            partial = [
                f for f in ALL_FEATURES
                if _FEATURE_MATRIX.get(f, {}).get(harness) in ("partial", "adapter")
            ]
            gap_str = ", ".join(gaps) if gaps else "none"
            lines.append(f"{harness:<12}  {score:>4}%  [{grade}]    {gap_str}")
            if partial:
                partial_str = ", ".join(partial)
                lines.append(f"{'':12}  {'':>5}         Degraded: {partial_str}")

        lines += [
            "-" * 50,
            "",
            "Grades: A=90%+  B=75%+  C=60%+  D=45%+  F=<45%",
            "Run /sync-gaps <harness> for per-harness remediation steps.",
        ]
        return "\n".join(lines)

    def get_cross_harness_gaps(
        self,
        min_support_level: str = "partial",
    ) -> dict[str, list[str]]:
        """Return features that fall below the minimum support level per harness.

        Unlike ``get_support_gaps()`` (which only returns "unsupported"),
        this method accepts any minimum level so callers can find features that
        are at most "partial" or "adapter" across the harness fleet.

        Args:
            min_support_level: Minimum acceptable level. Features with a level
                *worse* than this are included in the result.
                Accepted values: "native", "partial", "adapter", "unsupported".
                Default: "partial" (returns features that are only adapter or worse).

        Returns:
            Dict mapping harness_name -> list of feature names below the threshold.
        """
        threshold = _LEVEL_ORDER.get(min_support_level, 1)
        result: dict[str, list[str]] = {}
        for harness in ALL_HARNESSES:
            below = sorted(
                feat
                for feat in ALL_FEATURES
                if _LEVEL_ORDER.get(
                    _FEATURE_MATRIX.get(feat, {}).get(harness, "unsupported"), 3
                ) > threshold
            )
            if below:
                result[harness] = below
        return result

    def format_feature_adoption_report(self) -> str:
        """Return a feature adoption report sorted by cross-harness support rate.

        For each feature, shows how many harnesses support it at each level,
        sorted from most-adopted to least-adopted. Helps users understand which
        features to use confidently and which to avoid in multi-harness setups.

        Returns:
            Multi-line formatted string.
        """
        lines: list[str] = [
            "Feature Adoption Report",
            "=" * 60,
            "",
            "Features sorted by native support rate (most portable first):",
            "",
        ]

        # Compute adoption score per feature
        scored: list[tuple[float, str]] = []
        for feat in ALL_FEATURES:
            native_count = sum(
                1 for h in ALL_HARNESSES
                if _FEATURE_MATRIX.get(feat, {}).get(h) == "native"
            )
            partial_count = sum(
                1 for h in ALL_HARNESSES
                if _FEATURE_MATRIX.get(feat, {}).get(h) in ("partial", "adapter")
            )
            total = len(ALL_HARNESSES)
            score = (native_count + 0.5 * partial_count) / total
            scored.append((score, feat))

        scored.sort(reverse=True)

        for score, feat in scored:
            harness_map = _FEATURE_MATRIX.get(feat, {})
            native_list = [h for h in ALL_HARNESSES if harness_map.get(h) == "native"]
            partial_list = [h for h in ALL_HARNESSES if harness_map.get(h) in ("partial", "adapter")]
            unsup_list = [h for h in ALL_HARNESSES if harness_map.get(h) == "unsupported"]

            pct = int(score * 100)
            bar_len = int(pct / 5)
            bar = "█" * bar_len + "░" * (20 - bar_len)

            lines.append(f"  {feat:<12}  {bar}  {pct:3d}%")
            if native_list:
                lines.append(f"    native   : {', '.join(native_list)}")
            if partial_list:
                lines.append(f"    partial  : {', '.join(partial_list)}")
            if unsup_list:
                lines.append(f"    missing  : {', '.join(unsup_list)}")
            lines.append("")

        missing_everywhere = self.get_features_missing_everywhere()
        if missing_everywhere:
            lines.append(
                f"  NOTE: {', '.join(missing_everywhere)} "
                f"ha{'ve' if len(missing_everywhere) > 1 else 's'} 0% support across all harnesses."
            )

        return "\n".join(lines)

    def export_html_report(self, output_path: "Path | str | None" = None) -> str:
        """Generate a self-contained HTML capability gap matrix report.

        Produces a single HTML file with embedded CSS and an interactive table
        showing support levels per (feature, harness) cell with color coding:
          - native      → green
          - partial     → yellow
          - adapter     → orange
          - unsupported → red

        Args:
            output_path: If provided, write the HTML to this file path.
                         Returns the HTML string in both cases.

        Returns:
            HTML string of the full report.
        """
        import html as _html
        from datetime import datetime as _dt

        def _esc(t: str) -> str:
            return _html.escape(str(t))

        level_styles = {
            "native":      "background:#2ea043;color:#fff;",
            "partial":     "background:#d29922;color:#fff;",
            "adapter":     "background:#e0823d;color:#fff;",
            "unsupported": "background:#cf2222;color:#fff;",
        }
        level_labels = {
            "native":      "Native",
            "partial":     "Partial",
            "adapter":     "Adapter",
            "unsupported": "None",
        }

        # Build table header
        header_cells = "".join(f"<th>{_esc(h)}</th>" for h in ALL_HARNESSES)
        header = f"<tr><th>Feature</th>{header_cells}</tr>"

        # Build table rows
        rows_html = []
        for feat in ALL_FEATURES:
            cells = ""
            for harness in ALL_HARNESSES:
                level = _FEATURE_MATRIX.get(feat, {}).get(harness, "unsupported")
                style = level_styles.get(level, "")
                label = level_labels.get(level, level)
                note = _FEATURE_NOTES.get((feat, harness), "")
                title_attr = f' title="{_esc(note)}"' if note else ""
                cells += f'<td style="{style}"{title_attr}>{_esc(label)}</td>'
            rows_html.append(f"<tr><td><strong>{_esc(feat)}</strong></td>{cells}</tr>")

        # Build coverage score row
        score_cells = "".join(
            f"<td><strong>{self.coverage_score(h)}</strong></td>"
            for h in ALL_HARNESSES
        )
        score_row = f"<tr style='background:#161b22'><td><em>Coverage</em></td>{score_cells}</tr>"

        rows_str = "\n".join(rows_html) + "\n" + score_row
        generated_at = _dt.now().strftime("%Y-%m-%d %H:%M")

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>HarnessSync — Capability Gap Matrix</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', monospace;
           background:#0d1117; color:#c9d1d9; margin:0; padding:20px; }}
    h1 {{ color:#58a6ff; border-bottom:1px solid #30363d; padding-bottom:10px; }}
    p.subtitle {{ color:#8b949e; font-size:0.9em; }}
    table {{ border-collapse:collapse; width:100%; margin-top:20px; font-size:0.85em; }}
    th {{ background:#1f2937; color:#79c0ff; padding:8px 12px; text-align:center;
          border:1px solid #30363d; white-space:nowrap; }}
    td {{ padding:6px 10px; text-align:center; border:1px solid #30363d; }}
    tr:hover td {{ filter:brightness(1.15); }}
    .legend {{ display:flex; gap:16px; margin:12px 0; flex-wrap:wrap; }}
    .legend-item {{ display:flex; align-items:center; gap:6px; font-size:0.85em; }}
    .legend-swatch {{ width:14px; height:14px; border-radius:3px; }}
  </style>
</head>
<body>
  <h1>HarnessSync — Live Capability Gap Matrix</h1>
  <p class="subtitle">Generated: {_esc(generated_at)} &nbsp;|&nbsp;
     Hover cells for notes &nbsp;|&nbsp;
     Coverage score = native×100 + partial×50 (out of 100)</p>
  <div class="legend">
    <div class="legend-item">
      <div class="legend-swatch" style="background:#2ea043"></div> Native
    </div>
    <div class="legend-item">
      <div class="legend-swatch" style="background:#d29922"></div> Partial
    </div>
    <div class="legend-item">
      <div class="legend-swatch" style="background:#e0823d"></div> Adapter
    </div>
    <div class="legend-item">
      <div class="legend-swatch" style="background:#cf2222"></div> Unsupported
    </div>
  </div>
  <table>
    <thead>{header}</thead>
    <tbody>{rows_str}</tbody>
  </table>
</body>
</html>
"""

        if output_path is not None:
            from pathlib import Path as _Path
            _Path(output_path).write_text(html_content, encoding="utf-8")

        return html_content

    # ── Pre-sync capability check (item 1 — Live Capability Matrix Dashboard) ──

    def check_before_sync(
        self,
        target: str,
        features: list[str] | None = None,
    ) -> dict[str, object]:
        """Answer 'will this work in <target>?' before running sync.

        Returns a structured result showing which features will work natively,
        which will be adapted, and which will be silently dropped.  Call this
        from the orchestrator or /sync command to surface capability warnings
        at sync time rather than after.

        Args:
            target:   Harness name (e.g. "codex", "aider").
            features: Feature names to check. Defaults to ALL_FEATURES.

        Returns:
            Dict with keys:
              - "target":    harness name
              - "ready":     features with "native" support
              - "degraded":  features with "partial" or "adapter" support
              - "blocked":   features with "unsupported" support
              - "score":     coverage score (0-100)
              - "verdict":   "ok" | "warnings" | "blocked"
              - "summary":   one-line human-readable verdict string
        """
        check_features = features or ALL_FEATURES
        ready: list[str] = []
        degraded: list[str] = []
        blocked: list[str] = []

        for feat in check_features:
            level = _FEATURE_MATRIX.get(feat, {}).get(target, "unsupported")
            if level == "native":
                ready.append(feat)
            elif level in ("partial", "adapter"):
                degraded.append(feat)
            else:
                blocked.append(feat)

        score = self.coverage_score(target)

        if blocked:
            verdict = "blocked"
            summary = (
                f"{target}: {len(blocked)} feature(s) unsupported — "
                f"{', '.join(blocked[:3])}{'…' if len(blocked) > 3 else ''}"
            )
        elif degraded:
            verdict = "warnings"
            summary = (
                f"{target}: {len(degraded)} feature(s) with degraded support — "
                f"{', '.join(degraded[:3])}{'…' if len(degraded) > 3 else ''}"
            )
        else:
            verdict = "ok"
            summary = f"{target}: all features supported natively (score={score})"

        return {
            "target": target,
            "ready": ready,
            "degraded": degraded,
            "blocked": blocked,
            "score": score,
            "verdict": verdict,
            "summary": summary,
        }

    def check_all_targets_before_sync(
        self,
        features: list[str] | None = None,
        targets: list[str] | None = None,
    ) -> list[dict[str, object]]:
        """Run :meth:`check_before_sync` for all (or specified) targets.

        Returns results sorted by score descending (best-supported harnesses first),
        making it easy to spot which targets will have the most sync degradation.

        Args:
            features: Features to check (default: ALL_FEATURES).
            targets:  Targets to check (default: ALL_HARNESSES).

        Returns:
            List of check result dicts, sorted best-first.
        """
        target_list = targets or ALL_HARNESSES
        results = [self.check_before_sync(t, features) for t in target_list]
        return sorted(results, key=lambda r: r["score"], reverse=True)  # type: ignore[return-value]

    def format_pre_sync_warnings(
        self,
        features: list[str] | None = None,
        targets: list[str] | None = None,
    ) -> str:
        """Return a concise pre-sync warning block for terminal display.

        Shows only targets with degraded or blocked features, with one-line
        summaries.  Targets where everything works natively are omitted to
        reduce noise.

        Args:
            features: Features to check (default: ALL_FEATURES).
            targets:  Targets to check (default: ALL_HARNESSES).

        Returns:
            Warning block string, or empty string if no warnings.
        """
        results = self.check_all_targets_before_sync(features, targets)
        warnings: list[str] = []

        for r in results:
            if r["verdict"] == "blocked":
                warnings.append(f"  [BLOCKED]  {r['summary']}")
            elif r["verdict"] == "warnings":
                warnings.append(f"  [ADVISORY] {r['summary']}")

        if not warnings:
            return ""

        header = ["Pre-sync capability warnings:", "─" * 50]
        footer = ["", "Run /sync-matrix for full capability details."]
        return "\n".join(header + warnings + footer)

    # ── Coverage Heatmap (item 3) ────────────────────────────────────────────

    def render_coverage_heatmap(
        self,
        features: list[str] | None = None,
        targets: list[str] | None = None,
        use_color: bool = False,
    ) -> str:
        """Render an ASCII heatmap showing feature coverage across harnesses.

        Each cell contains a single glyph:
        - ``■`` native support (best)
        - ``◑`` partial support
        - ``○`` adapter/emulation
        - ``✗`` unsupported (gap)

        Args:
            features: Feature subset to show (default: ALL_FEATURES).
            targets:  Harness subset to show (default: ALL_HARNESSES).
            use_color: Emit ANSI color codes for terminal color output.

        Returns:
            Multi-line heatmap string.
        """
        feat_list = features or ALL_FEATURES
        targ_list = targets or ALL_HARNESSES

        # ANSI colors (reset at end of each cell)
        _ANSI = {
            "native":      "\033[32m",   # green
            "partial":     "\033[33m",   # yellow
            "adapter":     "\033[34m",   # blue
            "unsupported": "\033[31m",   # red
            "reset":       "\033[0m",
        } if use_color else {k: "" for k in ("native", "partial", "adapter", "unsupported", "reset")}

        _GLYPH: dict[str, str] = {
            "native":      "■",
            "partial":     "◑",
            "adapter":     "○",
            "unsupported": "✗",
        }

        def _cell(level: str) -> str:
            col = _ANSI.get(level, "")
            reset = _ANSI["reset"]
            glyph = _GLYPH.get(level, "?")
            return f"{col}{glyph}{reset}"

        # Compute column widths
        targ_col = max(len(t) for t in targ_list)
        feat_col = 3  # each feature column: glyph + 2 spaces

        # Header row
        feat_header = "  ".join(f[:4].ljust(4) for f in feat_list)
        header = f"{'harness':<{targ_col}}  {feat_header}"
        sep = "─" * len(header)

        lines = [
            "Feature Coverage Heatmap",
            "  ■ native  ◑ partial  ○ adapter  ✗ unsupported",
            sep,
            header,
            sep,
        ]

        for target in targ_list:
            cells = []
            for feat in feat_list:
                level = _FEATURE_MATRIX.get(feat, {}).get(target, "unsupported")
                cells.append(_cell(level).ljust(4 + len(_ANSI.get("reset", ""))))
            row = f"{target:<{targ_col}}  {'  '.join(c.strip() for c in cells)}"
            lines.append(row)

        lines.append(sep)

        # Compact legend counts
        native_count = sum(
            1 for f in feat_list for t in targ_list
            if _FEATURE_MATRIX.get(f, {}).get(t) == "native"
        )
        total_cells = len(feat_list) * len(targ_list)
        pct = int(native_count / total_cells * 100) if total_cells else 0
        lines.append(f"Native coverage: {native_count}/{total_cells} cells ({pct}%)")

        return "\n".join(lines)
