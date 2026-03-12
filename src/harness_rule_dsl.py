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

Compliance-pinned rules (item 16):
    Add ``compliance: true`` to mark a rule as always-synced regardless of
    ``--skip-sections`` or other filters. Compliance rules appear first in
    the compiled output and carry a [COMPLIANCE] marker so target harnesses
    can visually distinguish them. Useful for security/legal requirements
    that must be present in every harness config.

    ```harness-rule
    id: never-commit-secrets
    intent: security
    priority: critical
    compliance: true
    text: Never commit API keys, tokens, or passwords to version control.
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
    compliance: bool = False   # If True, rule cannot be skipped by --skip-sections
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
        """Format the rule text for a specific target.

        Compliance-pinned rules are prefixed with [COMPLIANCE] so they are
        visually distinct in every target harness config.
        """
        prefix = "[COMPLIANCE] " if self.compliance else ""
        return f"- {prefix}{self.text}"


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
        # Compliance flag: accept bool True, or string "true"/"yes"/"1"
        compliance_raw = data.get("compliance", False)
        if isinstance(compliance_raw, bool):
            compliance = compliance_raw
        else:
            compliance = str(compliance_raw).strip().lower() in ("true", "yes", "1")
        # Rules with priority "critical" are implicitly compliance-pinned
        if priority == "critical":
            compliance = True

        return HarnessRule(
            id=rule_id,
            text=text,
            intent=intent,
            scope=scope,
            priority=priority,
            applies_to=applies_to,
            compliance=compliance,
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


def get_compliance_rules(rules: list[HarnessRule]) -> list[HarnessRule]:
    """Return only compliance-pinned rules from a list.

    Compliance rules are those with ``compliance=True`` (set explicitly or
    implied by ``priority=critical``). These must always be synced to every
    target regardless of section filters.

    Args:
        rules: Full list of HarnessRule objects.

    Returns:
        Filtered list containing only compliance-pinned rules.
    """
    return [r for r in rules if r.compliance]


class RuleDSLCompiler:
    """Compile HarnessRule objects to target-specific config text."""

    def compile(
        self,
        rules: list[HarnessRule],
        target: str,
        section_heading: str = "Rules",
        compliance_only: bool = False,
    ) -> str:
        """Compile rules to the format expected by a specific target.

        Compliance-pinned rules always appear first under a dedicated
        "Compliance Requirements" subsection, clearly separated from
        regular rules so they are not accidentally removed.

        Args:
            rules: List of HarnessRule objects.
            target: Target harness name.
            section_heading: Markdown section heading for the rules block.
            compliance_only: If True, emit only compliance-pinned rules.
                             Used by the orchestrator to inject compliance
                             content when a section is otherwise skipped.

        Returns:
            Formatted string ready to be written to the target config file.
        """
        applicable = [r for r in rules if r.applies_to_target(target)]
        if compliance_only:
            applicable = [r for r in applicable if r.compliance]
        if not applicable:
            return ""

        # Sort by priority (critical first, then high, medium, low)
        applicable.sort(key=lambda r: r.priority_order)

        preamble = _TARGET_PREAMBLES.get(target, "")
        lines = [preamble, f"## {section_heading}", ""]

        # Emit compliance-pinned rules first under their own subsection
        compliance_rules = [r for r in applicable if r.compliance]
        regular_rules = [r for r in applicable if not r.compliance]

        if compliance_rules:
            lines.append("### Compliance Requirements")
            lines.append("")
            for rule in compliance_rules:
                lines.append(rule.format_for_target(target))
            lines.append("")

        if regular_rules and not compliance_only:
            # Group non-compliance rules by intent for readability
            by_intent: dict[str, list[HarnessRule]] = {}
            for rule in regular_rules:
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
        compliance_count = sum(1 for r in rules if r.compliance)
        lines = [
            f"Harness Rule DSL — {len(rules)} rule(s) defined "
            f"({compliance_count} compliance-pinned):",
            "",
        ]
        for rule in rules:
            scope_str = ", ".join(rule.scope) if rule.scope else "all targets"
            compliance_flag = " 🔒COMPLIANCE" if rule.compliance else ""
            lines.append(
                f"  [{rule.priority.upper()}] {rule.id}{compliance_flag}  "
                f"intent={rule.intent}  scope={scope_str}"
            )
        return "\n".join(lines)
