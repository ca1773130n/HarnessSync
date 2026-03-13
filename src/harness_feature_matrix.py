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
        "zed":      "native",     # → .zed/system-prompt.md
        "neovim":   "native",     # → .avante/system-prompt.md
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
        "zed":      "adapter",    # → .zed/system-prompt.md prose block
        "neovim":   "adapter",    # → .avante/system-prompt.md prose block
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
            ("skills", "zed"):      "Inline skill content in system-prompt.md manually.",
            ("skills", "neovim"):   "Add skill content to .avante/system-prompt.md.",
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
