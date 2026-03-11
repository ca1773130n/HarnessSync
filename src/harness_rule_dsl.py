from __future__ import annotations

"""Harness-Agnostic Rule DSL — write once, compile to any harness format.

Defines a canonical rule format with semantic metadata (intent, scope, priority)
that compiles to target-specific Markdown, TOML, or JSON with higher fidelity
than plain text translation. Intent metadata enables better cross-harness
translation because the system knows *why* a rule exists.

Rule DSL format (YAML/JSON inside CLAUDE.md fenced block):
    ```harness-rule
    id: no-hardcoded-paths
    intent: prevent_hardcoding
    scope: [codex, gemini, opencode, cursor, aider]
    priority: high
    text: Never hardcode absolute paths; use project-relative paths or env vars.
    applies_to: [rules]
    ```

Intent values:
    prevent_hardcoding | security | style | workflow | tool_restriction |
    quality | documentation | testing | performance | safety

Usage:
    parser = RuleDSLParser()
    rules = parser.parse(claude_md_content)
    compiler = RuleDSLCompiler()
    codex_rules = compiler.compile(rules, target="codex")
    gemini_rules = compiler.compile(rules, target="gemini")
"""

import re
from dataclasses import dataclass, field
from typing import Any

try:
    import yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False


# Fenced block pattern for harness-rule DSL
_DSL_BLOCK_RE = re.compile(
    r"```harness-rule\s*\n(.*?)```",
    re.DOTALL,
)

# Valid intent values and their human-readable descriptions
VALID_INTENTS: dict[str, str] = {
    "prevent_hardcoding": "Prevent hardcoded values (paths, credentials, IDs)",
    "security": "Security and credential protection",
    "style": "Code style and formatting",
    "workflow": "Development workflow and process",
    "tool_restriction": "Restrict or allow specific tools",
    "quality": "Code quality and review",
    "documentation": "Documentation and comments",
    "testing": "Testing practices",
    "performance": "Performance and efficiency",
    "safety": "Safety nets and guardrails",
}

# Priority order for rendering (higher priority rules listed first)
_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Target-specific preambles for compiled output
_TARGET_PREAMBLES: dict[str, str] = {
    "codex":    "# Rules (compiled from HarnessSync Rule DSL)\n",
    "gemini":   "# Rules (compiled from HarnessSync Rule DSL)\n",
    "opencode": "# Rules (compiled from HarnessSync Rule DSL)\n",
    "cursor":   "---\ndescription: HarnessSync compiled rules\n---\n\n",
    "aider":    "# Conventions (compiled from HarnessSync Rule DSL)\n",
    "windsurf": "# Rules (compiled from HarnessSync Rule DSL)\n",
}


@dataclass
class HarnessRule:
    """A single rule with semantic metadata."""

    id: str
    text: str
    intent: str = "style"
    scope: list[str] = field(default_factory=list)   # empty = all targets
    priority: str = "medium"
    applies_to: list[str] = field(default_factory=lambda: ["rules"])
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def priority_order(self) -> int:
        return _PRIORITY_ORDER.get(self.priority, 2)

    def applies_to_target(self, target: str) -> bool:
        """Return True if this rule should be included for target."""
        if not self.scope:
            return True  # no scope restriction = all targets
        return target in self.scope

    def format_for_target(self, target: str) -> str:
        """Format the rule text for a specific target."""
        # All targets currently use Markdown bullet
        # Future: could return TOML for codex, JSON for opencode, etc.
        return f"- {self.text}"


class RuleDSLParser:
    """Parse harness-rule DSL blocks from CLAUDE.md content."""

    def parse(self, content: str) -> list[HarnessRule]:
        """Extract all harness-rule blocks from content.

        Args:
            content: Full CLAUDE.md file content.

        Returns:
            List of HarnessRule objects parsed from DSL blocks.
        """
        rules: list[HarnessRule] = []
        for m in _DSL_BLOCK_RE.finditer(content):
            block_text = m.group(1).strip()
            rule = self._parse_block(block_text)
            if rule:
                rules.append(rule)
        return rules

    def _parse_block(self, block: str) -> HarnessRule | None:
        """Parse a single DSL block into a HarnessRule."""
        data: dict[str, Any] = {}

        if _HAS_YAML:
            try:
                data = yaml.safe_load(block) or {}
            except Exception:
                data = self._parse_simple_kv(block)
        else:
            data = self._parse_simple_kv(block)

        if not isinstance(data, dict):
            return None

        rule_id = str(data.get("id", "")).strip()
        text = str(data.get("text", "")).strip()
        if not rule_id or not text:
            return None

        # Normalise scope to list
        scope_raw = data.get("scope", [])
        if isinstance(scope_raw, str):
            scope = [s.strip() for s in scope_raw.split(",") if s.strip()]
        else:
            scope = list(scope_raw)

        # Normalise applies_to
        applies_raw = data.get("applies_to", ["rules"])
        if isinstance(applies_raw, str):
            applies_to = [a.strip() for a in applies_raw.split(",") if a.strip()]
        else:
            applies_to = list(applies_raw)

        intent = str(data.get("intent", "style")).strip()
        priority = str(data.get("priority", "medium")).strip()

        return HarnessRule(
            id=rule_id,
            text=text,
            intent=intent,
            scope=scope,
            priority=priority,
            applies_to=applies_to,
            raw=data,
        )

    @staticmethod
    def _parse_simple_kv(block: str) -> dict:
        """Parse simple key: value format without yaml dependency."""
        result: dict = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()
            # Handle list values like [a, b, c]
            if value.startswith("[") and value.endswith("]"):
                inner = value[1:-1]
                result[key] = [v.strip() for v in inner.split(",") if v.strip()]
            else:
                result[key] = value
        return result


class RuleDSLCompiler:
    """Compile HarnessRule objects to target-specific config text."""

    def compile(
        self,
        rules: list[HarnessRule],
        target: str,
        section_heading: str = "Rules",
    ) -> str:
        """Compile rules to the format expected by a specific target.

        Args:
            rules: List of HarnessRule objects.
            target: Target harness name.
            section_heading: Markdown section heading for the rules block.

        Returns:
            Formatted string ready to be written to the target config file.
        """
        applicable = [r for r in rules if r.applies_to_target(target)]
        if not applicable:
            return ""

        # Sort by priority (critical first, then high, medium, low)
        applicable.sort(key=lambda r: r.priority_order)

        preamble = _TARGET_PREAMBLES.get(target, "")
        lines = [preamble, f"## {section_heading}", ""]

        # Group by intent for readability
        by_intent: dict[str, list[HarnessRule]] = {}
        for rule in applicable:
            by_intent.setdefault(rule.intent, []).append(rule)

        for intent, intent_rules in by_intent.items():
            intent_label = VALID_INTENTS.get(intent, intent.replace("_", " ").title())
            lines.append(f"### {intent_label}")
            lines.append("")
            for rule in intent_rules:
                lines.append(rule.format_for_target(target))
            lines.append("")

        return "\n".join(lines)

    def compile_metadata_summary(self, rules: list[HarnessRule]) -> str:
        """Generate a human-readable summary of DSL rule metadata."""
        if not rules:
            return "No harness-rule DSL blocks found."
        lines = [f"Harness Rule DSL — {len(rules)} rule(s) defined:", ""]
        for rule in rules:
            scope_str = ", ".join(rule.scope) if rule.scope else "all targets"
            lines.append(
                f"  [{rule.priority.upper()}] {rule.id}  "
                f"intent={rule.intent}  scope={scope_str}"
            )
        return "\n".join(lines)
