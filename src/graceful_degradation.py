from __future__ import annotations

"""Graceful degradation profiles for cross-harness feature gaps.

When syncing a feature that isn't supported in a target harness, instead of
silently dropping it, GracefulDegradation injects a human-readable fallback:
- A text description of what the feature does
- A manual workaround suggestion
- A placeholder config comment explaining the gap

Example: if MCP server X is unavailable in Codex, inject a text block
into AGENTS.md describing what it would do and suggesting alternatives.

Degradation profiles are defined per (feature_type, target) pair. Each profile
specifies:
- fallback_type: "comment" | "text_block" | "skip"
- template: string template for the injected fallback content
- condition: optional callable returning bool to apply this profile
"""

from dataclasses import dataclass, field
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DegradationProfile:
    """How to handle a specific feature gap for a specific target."""

    feature_type: str      # e.g. "mcp_server", "hook", "agent", "command", "skill"
    target: str            # e.g. "aider", "codex"
    fallback_type: str     # "comment" | "text_block" | "skip"
    template: str          # Template string; use {name}, {description}, {workaround}
    workaround: str = ""   # Human-readable manual workaround suggestion


@dataclass
class DegradationResult:
    """Output of applying a degradation profile to a specific feature."""

    feature_name: str
    target: str
    fallback_type: str
    injected_content: str
    applied_profile: str   # Profile identifier for audit


# ──────────────────────────────────────────────────────────────────────────────
# Built-in degradation profiles
# ──────────────────────────────────────────────────────────────────────────────

# Default profiles — covers the most common cross-harness gaps.
# Keyed by (feature_type, target). Use ("*", target) as wildcard feature type.
_DEFAULT_PROFILES: list[DegradationProfile] = [
    # MCP servers not supported in Aider
    DegradationProfile(
        feature_type="mcp_server",
        target="aider",
        fallback_type="text_block",
        template=(
            "<!-- MCP Server: {name} (not supported in Aider) -->\n"
            "# [{name}] is not available in Aider.\n"
            "# What it does: {description}\n"
            "# Workaround: {workaround}\n"
        ),
        workaround="Use the equivalent CLI tool or API directly from your shell before/after Aider.",
    ),
    # MCP servers degraded in cursor (need separate mcp.json setup)
    DegradationProfile(
        feature_type="mcp_server",
        target="cursor",
        fallback_type="comment",
        template=(
            "<!-- MCP Server '{name}' requires manual Cursor MCP setup. "
            "Add it to .cursor/mcp.json. Description: {description} -->\n"
        ),
        workaround="Add the server manually to .cursor/mcp.json using Cursor's MCP configuration format.",
    ),
    # Hooks not supported anywhere except Claude Code
    DegradationProfile(
        feature_type="hook",
        target="codex",
        fallback_type="text_block",
        template=(
            "<!-- Hook '{name}' ({hook_event}) cannot be replicated in Codex. -->\n"
            "# Note: The '{name}' hook (triggered on {hook_event}) is Claude Code-specific.\n"
            "# Workaround: {workaround}\n"
        ),
        workaround="Replicate this behavior using a shell wrapper script or git hook instead.",
    ),
    DegradationProfile(
        feature_type="hook",
        target="gemini",
        fallback_type="text_block",
        template=(
            "<!-- Hook '{name}' ({hook_event}) has no Gemini equivalent. -->\n"
            "# Note: '{name}' ({hook_event}) is Claude Code-specific and was not synced.\n"
            "# Workaround: {workaround}\n"
        ),
        workaround="Use a git hook or shell alias to approximate this behavior.",
    ),
    DegradationProfile(
        feature_type="hook",
        target="opencode",
        fallback_type="comment",
        template=(
            "<!-- Hook '{name}' ({hook_event}) skipped — opencode has no hook system. "
            "Workaround: {workaround} -->\n"
        ),
        workaround="Use a shell wrapper script.",
    ),
    DegradationProfile(
        feature_type="hook",
        target="cursor",
        fallback_type="comment",
        template=(
            "<!-- Hook '{name}' ({hook_event}) skipped — Cursor has no hook system. "
            "Workaround: {workaround} -->\n"
        ),
        workaround="Use VS Code extension events or a shell wrapper.",
    ),
    DegradationProfile(
        feature_type="hook",
        target="aider",
        fallback_type="comment",
        template=(
            "<!-- Hook '{name}' ({hook_event}) skipped — Aider has no hook system. "
            "Workaround: {workaround} -->\n"
        ),
        workaround="Use aider's --auto-commits flag or a git hook for lifecycle events.",
    ),
    DegradationProfile(
        feature_type="hook",
        target="windsurf",
        fallback_type="comment",
        template=(
            "<!-- Hook '{name}' ({hook_event}) skipped — Windsurf has no hook system. "
            "Workaround: {workaround} -->\n"
        ),
        workaround="Use a git hook or shell alias to approximate this behavior.",
    ),
    # Slash commands not supported anywhere except Claude Code
    DegradationProfile(
        feature_type="command",
        target="codex",
        fallback_type="text_block",
        template=(
            "# [UNSUPPORTED COMMAND] /{name}\n"
            "# This Claude Code slash command cannot be synced to Codex.\n"
            "# What it does: {description}\n"
            "# Workaround: {workaround}\n"
        ),
        workaround="Run this action manually from the shell or create a shell alias.",
    ),
    DegradationProfile(
        feature_type="command",
        target="gemini",
        fallback_type="text_block",
        template=(
            "# [UNSUPPORTED COMMAND] /{name}\n"
            "# Gemini CLI does not support slash commands.\n"
            "# Description: {description}\n"
            "# Workaround: {workaround}\n"
        ),
        workaround="Create an equivalent shell script or alias.",
    ),
    # Agents partially supported
    DegradationProfile(
        feature_type="agent",
        target="aider",
        fallback_type="text_block",
        template=(
            "# [AGENT: {name}] — converted to instruction context\n"
            "# Aider does not support named agents. The agent description has been\n"
            "# included as a context hint below:\n"
            "#\n"
            "# {description}\n"
            "#\n"
            "# Note: Aider will not dispatch to this agent automatically.\n"
        ),
        workaround="Reference the agent context manually by including the file with --read.",
    ),
    DegradationProfile(
        feature_type="agent",
        target="cursor",
        fallback_type="comment",
        template=(
            "<!-- Agent '{name}' converted to .mdc rule. "
            "Note: Cursor does not support subagent dispatch. {description} -->\n"
        ),
        workaround="Use Cursor's Composer mode and reference the agent rules manually.",
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# Custom profile storage
# ──────────────────────────────────────────────────────────────────────────────

_CUSTOM_PROFILE_FILE = Path.home() / ".harnesssync" / "degradation_profiles.json"


def _load_custom_profiles() -> list[DegradationProfile]:
    """Load user-defined degradation profiles from disk."""
    if not _CUSTOM_PROFILE_FILE.exists():
        return []
    try:
        import json
        raw = json.loads(_CUSTOM_PROFILE_FILE.read_text(encoding="utf-8"))
        profiles = []
        for entry in raw.get("profiles", []):
            profiles.append(DegradationProfile(
                feature_type=entry["feature_type"],
                target=entry["target"],
                fallback_type=entry.get("fallback_type", "comment"),
                template=entry["template"],
                workaround=entry.get("workaround", ""),
            ))
        return profiles
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Core engine
# ──────────────────────────────────────────────────────────────────────────────

class GracefulDegradation:
    """Apply graceful degradation profiles to unsupported features.

    Profiles are matched by (feature_type, target) with custom profiles
    taking precedence over built-in ones.
    """

    def __init__(self, custom_profiles: list[DegradationProfile] | None = None):
        """Initialize with optional custom profiles (overrides built-ins)."""
        self._custom = custom_profiles if custom_profiles is not None else _load_custom_profiles()
        # Build lookup: (feature_type, target) -> profile (custom wins over default)
        self._profiles: dict[tuple[str, str], DegradationProfile] = {}
        for p in _DEFAULT_PROFILES:
            self._profiles[(p.feature_type, p.target)] = p
        for p in self._custom:
            self._profiles[(p.feature_type, p.target)] = p

    def apply(
        self,
        feature_type: str,
        feature_name: str,
        target: str,
        description: str = "",
        workaround: str = "",
        extra: dict | None = None,
    ) -> DegradationResult | None:
        """Apply a degradation profile for an unsupported feature.

        Args:
            feature_type: "mcp_server" | "hook" | "agent" | "command" | "skill"
            feature_name: The feature's identifier (e.g. MCP server name, hook name).
            target: Target harness name.
            description: Human-readable description of what the feature does.
            workaround: Override the profile's built-in workaround hint.
            extra: Additional template variables (e.g. {"hook_event": "PreToolUse"}).

        Returns:
            DegradationResult if a profile applies, None if this feature is unknown.
        """
        profile = self._profiles.get((feature_type, target))
        if profile is None:
            return None

        # Build template context
        ctx: dict[str, str] = {
            "name": feature_name,
            "description": description or f"No description provided for '{feature_name}'.",
            "workaround": workaround or profile.workaround or "No automatic workaround available.",
        }
        if extra:
            ctx.update(extra)

        try:
            content = profile.template.format(**ctx)
        except KeyError as e:
            content = (
                f"<!-- Degradation profile error for '{feature_name}': "
                f"missing template key {e} -->\n"
            )

        return DegradationResult(
            feature_name=feature_name,
            target=target,
            fallback_type=profile.fallback_type,
            injected_content=content,
            applied_profile=f"{feature_type}:{target}",
        )

    def apply_all(
        self,
        features: list[dict],
        target: str,
    ) -> list[DegradationResult]:
        """Apply degradation to a list of features for a target.

        Args:
            features: List of feature dicts with keys:
                  type, name, description, workaround (optional), extra (optional)
            target: Target harness name.

        Returns:
            List of DegradationResult for each feature that has a matching profile.
        """
        results: list[DegradationResult] = []
        for feat in features:
            result = self.apply(
                feature_type=feat.get("type", ""),
                feature_name=feat.get("name", ""),
                target=target,
                description=feat.get("description", ""),
                workaround=feat.get("workaround", ""),
                extra=feat.get("extra"),
            )
            if result is not None:
                results.append(result)
        return results

    def format_report(self, results: list[DegradationResult]) -> str:
        """Format degradation results as a human-readable summary."""
        if not results:
            return "No degradation applied — all features supported."

        lines = [
            f"Graceful Degradation Report ({len(results)} feature(s) substituted)",
            "=" * 60,
        ]
        by_target: dict[str, list[DegradationResult]] = {}
        for r in results:
            by_target.setdefault(r.target, []).append(r)

        for target, target_results in sorted(by_target.items()):
            lines.append(f"\n  {target}:")
            for r in target_results:
                lines.append(
                    f"    [{r.fallback_type}] {r.feature_name} — profile: {r.applied_profile}"
                )

        return "\n".join(lines)

    def get_known_targets(self) -> set[str]:
        """Return all target names that have at least one profile."""
        return {t for (_, t) in self._profiles}

    def get_known_feature_types(self) -> set[str]:
        """Return all feature types that have at least one profile."""
        return {ft for (ft, _) in self._profiles}
