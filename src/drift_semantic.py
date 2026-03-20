from __future__ import annotations

"""Semantic drift analysis: intent-level comparison between source and target configs.

Rather than comparing bytes or hashes, this module looks at capability mentions
(e.g. "bash", "mcp") and classifies whether each harness config allows or blocks
them. When the source (CLAUDE.md) and a target config disagree on intent,
a SemanticDriftAlert is raised.
"""

from dataclasses import dataclass
from pathlib import Path

from src.state_manager import StateManager


# Rule-level permission keywords whose presence/absence signals semantic drift.
_ALLOW_KEYWORDS = frozenset(["allow", "always", "enable", "permitted", "can use", "allowed"])
_BLOCK_KEYWORDS = frozenset(["block", "deny", "disable", "never", "not allowed", "forbidden", "reject"])

# Tool/capability names to check across harness configs
_CAPABILITY_TOKENS = frozenset([
    "bash", "edit", "read", "write", "glob", "grep", "agent", "webfetch", "websearch",
    "mcp", "tool_use", "computer_use", "code_execution",
])


@dataclass
class SemanticDriftAlert:
    """Alert for a rule whose meaning has shifted between Claude Code and a target harness."""

    target: str
    capability: str          # e.g. "bash", "mcp"
    source_intent: str       # "allow" | "block" | "neutral"
    target_intent: str       # "allow" | "block" | "neutral" | "absent"
    source_snippet: str      # relevant line from CLAUDE.md
    target_snippet: str      # relevant line from target config (empty if absent)
    suggested_fix: str

    def format(self) -> str:
        lines = [
            f"[SEMANTIC DRIFT] {self.target} \u2014 capability '{self.capability}'",
            f"  Claude Code intent : {self.source_intent}",
            f"  {self.target:16s} intent: {self.target_intent}",
        ]
        if self.source_snippet:
            lines.append(f"  Source rule  : {self.source_snippet.strip()}")
        if self.target_snippet:
            lines.append(f"  Target rule  : {self.target_snippet.strip()}")
        lines.append(f"  Suggested fix: {self.suggested_fix}")
        return "\n".join(lines)


def _classify_intent(text: str) -> str:
    """Return 'allow', 'block', or 'neutral' based on keyword presence."""
    lower = text.lower()
    has_allow = any(kw in lower for kw in _ALLOW_KEYWORDS)
    has_block = any(kw in lower for kw in _BLOCK_KEYWORDS)
    if has_block and not has_allow:
        return "block"
    if has_allow and not has_block:
        return "allow"
    return "neutral"


def _find_capability_line(text: str, capability: str) -> str:
    """Return the first line in text that mentions the capability, or ''."""
    for line in text.splitlines():
        if capability.lower() in line.lower():
            return line
    return ""


def analyze_semantic_drift(
    source_content: str,
    target_content: str,
    target: str,
) -> list[SemanticDriftAlert]:
    """Compare rule semantics between Claude Code config and a target harness config.

    Rather than comparing bytes, this looks for capability mentions whose
    allow/block intent differs between the source (CLAUDE.md) and the synced
    target config. For example, if CLAUDE.md permits 'bash' but the Codex
    target config now has a line that blocks it, a SemanticDriftAlert is
    returned.

    Args:
        source_content: Text of the Claude Code rules (CLAUDE.md content).
        target_content: Text of the target harness config as currently on disk.
        target: Harness name (e.g. "codex").

    Returns:
        List of SemanticDriftAlerts \u2014 empty if no semantic conflicts found.
    """
    alerts: list[SemanticDriftAlert] = []

    for cap in _CAPABILITY_TOKENS:
        source_line = _find_capability_line(source_content, cap)
        target_line = _find_capability_line(target_content, cap)

        if not source_line and not target_line:
            continue  # capability not mentioned in either \u2014 no drift

        source_intent = _classify_intent(source_line) if source_line else "neutral"
        target_intent = _classify_intent(target_line) if target_line else "absent"

        # Only surface when intents conflict meaningfully
        conflict = (
            (source_intent == "allow" and target_intent == "block")
            or (source_intent == "block" and target_intent == "allow")
            or (source_intent == "allow" and target_intent == "absent" and not target_line)
        )
        if not conflict:
            continue

        if source_intent == "allow" and target_intent == "block":
            suggested_fix = (
                f"Remove or relax the '{cap}' restriction in the {target} config, "
                f"or add '# @{target}: skip' to the source rule."
            )
        elif source_intent == "block" and target_intent == "allow":
            suggested_fix = (
                f"Add a '{cap}' restriction to the {target} config to match "
                f"the Claude Code rule, or run /sync to re-apply it."
            )
        else:
            suggested_fix = (
                f"The '{cap}' capability is allowed in Claude Code but missing "
                f"from the {target} config. Run /sync to propagate the rule."
            )

        alerts.append(SemanticDriftAlert(
            target=target,
            capability=cap,
            source_intent=source_intent,
            target_intent=target_intent,
            source_snippet=source_line,
            target_snippet=target_line,
            suggested_fix=suggested_fix,
        ))

    return alerts


def semantic_drift_summary(
    project_dir: Path,
    state_manager: StateManager | None = None,
) -> dict[str, list[SemanticDriftAlert]]:
    """Run semantic drift analysis across all synced targets.

    Reads the Claude Code rules source and compares them against each target's
    current on-disk config to detect meaning-level conflicts.

    Args:
        project_dir: Root directory of the project.
        state_manager: Optional StateManager (created from project_dir if None).

    Returns:
        Dict mapping target name \u2192 list of SemanticDriftAlerts.
        Targets with no semantic conflicts map to an empty list.
    """
    sm = state_manager or StateManager()

    # Read Claude Code source rules
    source_path = project_dir / "CLAUDE.md"
    if not source_path.exists():
        return {}
    source_content = source_path.read_text(encoding="utf-8", errors="replace")

    # Target config file paths (primary rules file per harness)
    _TARGET_RULES_FILES: dict[str, str] = {
        "codex": "AGENTS.md",
        "gemini": "GEMINI.md",
        "opencode": "AGENTS.md",
        "cursor": ".cursor/rules/harnesssync.mdc",
        "aider": "CONVENTIONS.md",
        "windsurf": ".windsurfrules",
        "cline": ".clinerules",
        "continue": ".continue/rules/harnesssync.md",
        "zed": ".zed/system-prompt.md",
        "neovim": ".avante/system-prompt.md",
    }

    state = sm.load_state()
    configured_targets = list(state.get("targets", {}).keys())
    if not configured_targets:
        configured_targets = list(_TARGET_RULES_FILES.keys())

    result: dict[str, list[SemanticDriftAlert]] = {}
    for target in configured_targets:
        rules_file = _TARGET_RULES_FILES.get(target)
        if not rules_file:
            result[target] = []
            continue
        target_path = project_dir / rules_file
        if not target_path.exists():
            result[target] = []
            continue
        target_content = target_path.read_text(encoding="utf-8", errors="replace")
        result[target] = analyze_semantic_drift(source_content, target_content, target)

    return result
