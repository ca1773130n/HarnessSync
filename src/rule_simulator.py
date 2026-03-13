from __future__ import annotations

"""Cross-harness rule simulation (item 10: Cross-Harness Rule Simulation).

Simulates how a CLAUDE.md rule or skill instruction would be interpreted
by each target harness, showing the translated output and flagging
behavioral differences between harnesses.

Answers the question: "Will 'always respond in TypeScript' mean the same
thing in Codex as it does in Claude Code?"

Usage::

    from src.rule_simulator import RuleSimulator

    sim = RuleSimulator()
    results = sim.simulate("Always respond in TypeScript, never JavaScript")
    print(sim.format_results(results))

Or from the CLI::

    /sync-test "always respond in TypeScript"
    /sync-test --file path/to/CLAUDE.md --section "Language Preferences"
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Harness rendering profiles ────────────────────────────────────────────────
# Describes how each harness interprets and applies rule text.

@dataclass
class HarnessProfile:
    """Rendering profile for a single target harness."""
    name: str
    # How the rule text is delivered to the model
    delivery: str     # "system_prompt" | "injected_context" | "file_reference"
    # Whether the harness natively supports Markdown headings in rules
    supports_headings: bool
    # Whether the harness can enforce rules programmatically (vs just context)
    enforcement: str  # "context_only" | "lint_hook" | "partial_enforcement"
    # Character limit for the entire rules file (0 = no hard limit)
    char_limit: int
    # Constructs that are stripped or ignored by this harness
    stripped_constructs: list[str] = field(default_factory=list)
    # Whether this harness has skill / command concept
    has_skills: bool = True
    # Whether MCP tools are available
    has_mcp: bool = True


_HARNESS_PROFILES: dict[str, HarnessProfile] = {
    "codex": HarnessProfile(
        name="codex",
        delivery="injected_context",
        supports_headings=True,
        enforcement="context_only",
        char_limit=0,
        stripped_constructs=["mcp__", "$CLAUDE_PLUGIN_ROOT", "PostToolUse", "PreToolUse"],
        has_skills=True,
        has_mcp=False,
    ),
    "gemini": HarnessProfile(
        name="gemini",
        delivery="system_prompt",
        supports_headings=True,
        enforcement="context_only",
        char_limit=0,
        stripped_constructs=["$CLAUDE_PLUGIN_ROOT", "PostToolUse", "PreToolUse"],
        has_skills=True,
        has_mcp=True,
    ),
    "opencode": HarnessProfile(
        name="opencode",
        delivery="system_prompt",
        supports_headings=True,
        enforcement="context_only",
        char_limit=0,
        stripped_constructs=["$CLAUDE_PLUGIN_ROOT", "PostToolUse", "PreToolUse"],
        has_skills=True,
        has_mcp=True,
    ),
    "cursor": HarnessProfile(
        name="cursor",
        delivery="injected_context",
        supports_headings=True,
        enforcement="context_only",
        char_limit=10_000,
        stripped_constructs=[
            "mcp__", "$CLAUDE_PLUGIN_ROOT", "PostToolUse", "PreToolUse",
            "SessionStart", "SessionEnd", "hooks.json",
        ],
        has_skills=False,
        has_mcp=True,
    ),
    "aider": HarnessProfile(
        name="aider",
        delivery="file_reference",
        supports_headings=True,
        enforcement="context_only",
        char_limit=5_000,
        stripped_constructs=[
            "mcp__", "$CLAUDE_PLUGIN_ROOT", "PostToolUse", "PreToolUse",
            "SessionStart", "SessionEnd", "skill", "command",
        ],
        has_skills=False,
        has_mcp=False,
    ),
    "windsurf": HarnessProfile(
        name="windsurf",
        delivery="system_prompt",
        supports_headings=True,
        enforcement="context_only",
        char_limit=0,
        stripped_constructs=["$CLAUDE_PLUGIN_ROOT", "PostToolUse", "PreToolUse"],
        has_skills=False,
        has_mcp=True,
    ),
}


# ── Behavioral difference detectors ──────────────────────────────────────────

# Patterns that might cause behavioral differences across harnesses
_BEHAVIORAL_PATTERNS: list[tuple[re.Pattern, str, list[str]]] = [
    # (pattern, description, affected_harnesses_where_behavior_differs)
    (
        re.compile(r"\b(skill|invoke skill|use skill)\b", re.IGNORECASE),
        "References 'skill' concept — not available in aider/cursor/windsurf",
        ["aider", "cursor", "windsurf"],
    ),
    (
        re.compile(r"\b(command|slash command|run /\w+)\b", re.IGNORECASE),
        "References slash commands — not available in aider/cursor/windsurf",
        ["aider", "cursor", "windsurf"],
    ),
    (
        re.compile(r"\b(mcp|mcp server|mcp tool)\b", re.IGNORECASE),
        "References MCP — not available in codex/aider",
        ["codex", "aider"],
    ),
    (
        re.compile(r"CLAUDE\.md", re.IGNORECASE),
        "References 'CLAUDE.md' by name — translated to target-specific file name",
        ["codex", "gemini", "opencode", "cursor", "aider", "windsurf"],
    ),
    (
        re.compile(r"\b(TodoWrite|WebFetch|WebSearch|EnterPlanMode|ExitPlanMode)\b"),
        "Claude Code-specific tool name — not available in other harnesses",
        ["codex", "gemini", "opencode", "cursor", "aider", "windsurf"],
    ),
    (
        re.compile(r"\b(hook|PostToolUse|PreToolUse|UserPromptSubmit|SessionStart|SessionEnd)\b"),
        "Hook event name — only available in Claude Code",
        ["codex", "gemini", "opencode", "cursor", "aider", "windsurf"],
    ),
]

# Canonical file name substitutions for CLAUDE.md references per harness
_FILE_SUBSTITUTIONS: dict[str, dict[str, str]] = {
    "codex":    {"CLAUDE.md": "AGENTS.md", "CLAUDE.local.md": "AGENTS.md"},
    "gemini":   {"CLAUDE.md": "GEMINI.md", "CLAUDE.local.md": "GEMINI.md"},
    "opencode": {"CLAUDE.md": "AGENTS.md", "CLAUDE.local.md": "AGENTS.md"},
    "cursor":   {"CLAUDE.md": ".cursor/rules/harnesssync.mdc"},
    "aider":    {"CLAUDE.md": "CONVENTIONS.md"},
    "windsurf": {"CLAUDE.md": ".windsurfrules"},
}


# ── Result types ─────────────────────────────────────────────────────────────

@dataclass
class HarnessSimulation:
    """Simulation result for a single harness."""
    harness: str
    translated_text: str         # Rule text as it would appear in this harness
    delivery_note: str           # How the harness delivers this to the model
    behavioral_diffs: list[str]  # Warnings about behavioral differences
    stripped_constructs: list[str]  # Constructs removed during translation
    char_count: int
    over_limit: bool             # True if char_limit exceeded


@dataclass
class RuleSimulationResult:
    """Full simulation result for a rule across all harnesses."""
    original_text: str
    simulations: dict[str, HarnessSimulation]  # harness -> simulation

    @property
    def has_diffs(self) -> bool:
        """True if any harness produces behavioral differences."""
        return any(s.behavioral_diffs for s in self.simulations.values())


# ── Simulator ─────────────────────────────────────────────────────────────────

class RuleSimulator:
    """Simulates how rule text translates to each target harness.

    Args:
        targets: Harness names to simulate. Defaults to all registered harnesses.
    """

    def __init__(self, targets: list[str] | None = None) -> None:
        if targets is None:
            self.targets = list(_HARNESS_PROFILES.keys())
        else:
            self.targets = [t for t in targets if t in _HARNESS_PROFILES]

    def _translate(self, text: str, profile: HarnessProfile) -> tuple[str, list[str]]:
        """Translate rule text for a specific harness profile.

        Returns:
            (translated_text, list_of_stripped_construct_descriptions)
        """
        translated = text
        stripped: list[str] = []

        # Substitute CLAUDE.md filename references
        subs = _FILE_SUBSTITUTIONS.get(profile.name, {})
        for src, dst in subs.items():
            if src in translated:
                translated = translated.replace(src, dst)

        # Strip constructs that this harness ignores
        for construct in profile.stripped_constructs:
            pattern = re.compile(re.escape(construct), re.IGNORECASE)
            if pattern.search(translated):
                # Don't remove — annotate instead so user can see the issue
                stripped.append(construct)

        return translated, stripped

    def _detect_behavioral_diffs(self, text: str, harness: str) -> list[str]:
        """Detect rule text patterns that cause behavioral differences in ``harness``."""
        diffs: list[str] = []
        for pattern, description, affected in _BEHAVIORAL_PATTERNS:
            if harness in affected and pattern.search(text):
                diffs.append(description)
        return diffs

    def simulate(self, rule_text: str) -> RuleSimulationResult:
        """Simulate how ``rule_text`` would be interpreted by each target harness.

        Args:
            rule_text: Raw rule text (e.g. a paragraph from CLAUDE.md).

        Returns:
            RuleSimulationResult with per-harness translations and diff warnings.
        """
        simulations: dict[str, HarnessSimulation] = {}

        for harness_name in self.targets:
            profile = _HARNESS_PROFILES[harness_name]
            translated, stripped = self._translate(rule_text, profile)
            diffs = self._detect_behavioral_diffs(rule_text, harness_name)

            char_count = len(translated)
            over_limit = profile.char_limit > 0 and char_count > profile.char_limit

            delivery_notes = {
                "system_prompt": "Injected into model system prompt",
                "injected_context": "Added to conversation context",
                "file_reference": "Loaded as a context file reference",
            }

            simulations[harness_name] = HarnessSimulation(
                harness=harness_name,
                translated_text=translated,
                delivery_note=delivery_notes.get(profile.delivery, profile.delivery),
                behavioral_diffs=diffs,
                stripped_constructs=stripped,
                char_count=char_count,
                over_limit=over_limit,
            )

        return RuleSimulationResult(original_text=rule_text, simulations=simulations)

    def simulate_section(self, section_text: str, section_title: str = "") -> RuleSimulationResult:
        """Simulate a complete CLAUDE.md section including its heading.

        Wraps ``simulate()`` but prepends the section title if provided.
        """
        full_text = f"## {section_title}\n\n{section_text}" if section_title else section_text
        return self.simulate(full_text)

    def format_results(self, result: RuleSimulationResult, show_translated: bool = False) -> str:
        """Format simulation results as human-readable text.

        Args:
            result:          Output of ``simulate()``.
            show_translated: If True, include the translated text for each harness.

        Returns:
            Formatted report string.
        """
        lines: list[str] = [
            "Cross-Harness Rule Simulation",
            "=" * 60,
            "",
            "Original rule text:",
            "-" * 40,
        ]
        # Truncate original if long
        preview = result.original_text.strip()
        if len(preview) > 200:
            preview = preview[:197] + "..."
        lines.append(preview)
        lines.append("")

        # Summary table
        lines.append(f"{'Harness':<12}  {'Diffs':<5}  {'Stripped':<8}  Delivery")
        lines.append("-" * 60)

        for harness, sim in result.simulations.items():
            diff_count = len(sim.behavioral_diffs)
            stripped_count = len(sim.stripped_constructs)
            diff_sym = f"! {diff_count}" if diff_count else "  0"
            stripped_sym = f"~ {stripped_count}" if stripped_count else "  0"
            lines.append(
                f"  {harness:<10}  {diff_sym:<5}  {stripped_sym:<8}  {sim.delivery_note}"
            )

        # Detail section for harnesses with diffs
        sims_with_issues = [
            (h, s) for h, s in result.simulations.items()
            if s.behavioral_diffs or s.stripped_constructs or s.over_limit
        ]
        if sims_with_issues:
            lines.append("")
            lines.append("Behavioral Differences:")
            lines.append("-" * 60)
            for harness, sim in sims_with_issues:
                lines.append(f"\n  {harness}:")
                if sim.over_limit:
                    lines.append(
                        f"    ⚠ Rule exceeds {harness} character limit"
                        f" ({sim.char_count} chars)"
                    )
                for diff in sim.behavioral_diffs:
                    lines.append(f"    ! {diff}")
                for construct in sim.stripped_constructs:
                    lines.append(f"    ~ construct not supported: {construct!r}")

        if show_translated:
            lines.append("")
            lines.append("Translated Text Per Harness:")
            lines.append("-" * 60)
            for harness, sim in result.simulations.items():
                lines.append(f"\n  [{harness}]")
                for tline in sim.translated_text.splitlines()[:10]:
                    lines.append(f"    {tline}")
                if sim.translated_text.count("\n") > 10:
                    lines.append("    ...")

        if not result.has_diffs:
            lines.append("")
            lines.append("✓ No behavioral differences detected across harnesses.")

        return "\n".join(lines)

    def compare_two(self, rule_text: str, harness_a: str, harness_b: str) -> str:
        """Compare how ``rule_text`` differs between exactly two harnesses.

        Args:
            rule_text:  Rule text to compare.
            harness_a:  First harness name.
            harness_b:  Second harness name.

        Returns:
            Formatted side-by-side comparison string.
        """
        result = self.simulate(rule_text)
        sim_a = result.simulations.get(harness_a)
        sim_b = result.simulations.get(harness_b)

        lines = [
            f"Rule Simulation: {harness_a}  vs  {harness_b}",
            "=" * 60,
            "",
        ]

        if sim_a is None:
            lines.append(f"Unknown harness: {harness_a!r}")
            return "\n".join(lines)
        if sim_b is None:
            lines.append(f"Unknown harness: {harness_b!r}")
            return "\n".join(lines)

        def _section(sim: HarnessSimulation) -> list[str]:
            out = [f"  Delivery:  {sim.delivery_note}"]
            if sim.behavioral_diffs:
                for d in sim.behavioral_diffs:
                    out.append(f"  ! {d}")
            else:
                out.append("  ✓ No behavioral differences")
            if sim.stripped_constructs:
                for c in sim.stripped_constructs:
                    out.append(f"  ~ unsupported: {c!r}")
            return out

        w = 28
        lines.append(f"  {'[' + harness_a + ']':<{w}}  {'[' + harness_b + ']'}")
        lines.append("  " + "-" * (w * 2 + 2))
        rows_a = _section(sim_a)
        rows_b = _section(sim_b)
        for i in range(max(len(rows_a), len(rows_b))):
            a = rows_a[i] if i < len(rows_a) else ""
            b = rows_b[i] if i < len(rows_b) else ""
            lines.append(f"  {a:<{w}}  {b}")

        return "\n".join(lines)
