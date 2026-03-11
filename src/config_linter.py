from __future__ import annotations

"""Pre-sync configuration linter.

Validates CLAUDE.md and settings.json before sync and returns a list of
human-readable error/warning strings. Invalid configs are reported but
never block sync — the caller decides how to surface them.

Checks:
- CLAUDE.md: non-empty, no obviously broken markdown code fences
- settings.json: valid JSON, no unknown top-level keys that indicate corruption
- Skill/agent references that point to missing directories
- Sync tags that are unclosed (sync:exclude without sync:end)
- Portability hints: tool-specific syntax, CC-specific constructs

Auto-fix support (suggest_fixes / apply_fixes):
- Close unclosed sync tags
- Rewrite non-portable tool references into portable equivalents
- Suggest rewrites for Markdown patterns that translate poorly
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# Top-level keys we expect in Claude Code settings.json (non-exhaustive)
_KNOWN_SETTINGS_KEYS = {
    "permissions", "approval_mode", "env", "hooks", "model",
    "autoUpdaterStatus", "userID", "oauthAccount", "theme",
    "preferredNotifChannel", "verbose",
}

# Sync tag pattern (must match sync_filter.py)
_TAG_RE = re.compile(
    r"<!--\s*sync:(exclude|codex-only|gemini-only|opencode-only|end)\s*-->",
    re.IGNORECASE,
)

# Broken markdown: unclosed triple-backtick fences
_FENCE_RE = re.compile(r"^```", re.MULTILINE)

# Claude Code tool-specific syntax patterns that translate poorly
# Maps (pattern, portable_replacement, explanation)
_PORTABILITY_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"\$ARGUMENTS\b"),
        "[user-provided arguments]",
        "$ARGUMENTS placeholder is Claude Code-specific; use '[user-provided arguments]' for portability",
    ),
    (
        re.compile(r"<tool_call>.*?</tool_call>", re.DOTALL),
        "",
        "<tool_call> XML blocks are Claude Code-specific and will be stripped in other harnesses",
    ),
    (
        re.compile(r"\b(allowed-tools|tools):\s*\[.*?\]", re.DOTALL),
        "",
        "'allowed-tools' frontmatter is Claude Code-specific; other harnesses will ignore it",
    ),
    (
        re.compile(r"<!--\s*sync:(codex|gemini|opencode|cursor|aider|windsurf)-only\s*-->(?![\s\S]*?<!--\s*sync:end\s*-->)"),
        "",
        "Harness-specific sync tags without closing <!-- sync:end --> will silently include all content",
    ),
]

# Patterns indicating tool-call syntax used inline
_INLINE_TOOL_RE = re.compile(
    r"\b(?:the\s+)?(?:Read|Write|Edit|Bash|Glob|Grep|Agent|TodoWrite|TodoRead"
    r"|WebFetch|WebSearch|NotebookRead|NotebookEdit)\s+tool\b",
    re.IGNORECASE,
)


@dataclass
class LintFix:
    """A lint issue paired with its auto-fix suggestion."""

    issue: str
    suggestion: str
    auto_fixable: bool = False
    # If auto_fixable, the regex pattern and replacement for apply_fixes()
    fix_pattern: re.Pattern | None = field(default=None, repr=False)
    fix_replacement: str = ""


class ConfigLinter:
    """Validates HarnessSync source configuration before sync."""

    def lint(
        self,
        source_data: dict,
        project_dir: Path | None = None,
        cc_home: Path | None = None,
    ) -> list[str]:
        """Run all lint checks against discovered source data.

        Args:
            source_data: Output of ``SourceReader.discover_all()``.
            project_dir: Project root (used for file existence checks).
            cc_home: Claude Code config directory (used for file existence checks).

        Returns:
            List of issue strings. Empty list = no issues found.
        """
        issues: list[str] = []

        issues.extend(self._lint_rules(source_data.get("rules", "")))
        issues.extend(self._lint_settings(source_data.get("settings", {})))
        issues.extend(self._lint_skills(source_data.get("skills", {})))
        issues.extend(self._lint_agents(source_data.get("agents", {})))

        return issues

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _lint_rules(self, rules) -> list[str]:
        """Check combined rules content."""
        issues: list[str] = []

        # rules can be a string (from get_rules()) or a list of dicts
        if isinstance(rules, list):
            texts = [r.get("content", "") for r in rules if isinstance(r, dict)]
            combined = "\n".join(texts)
        else:
            combined = rules or ""

        if not combined.strip():
            # Empty rules is not an error — warn softly
            return []

        # Check for unclosed markdown code fences
        fences = _FENCE_RE.findall(combined)
        if len(fences) % 2 != 0:
            issues.append(
                "CLAUDE.md: unclosed markdown code fence (odd number of ``` markers) — "
                "target harnesses may render incorrectly"
            )

        # Check for unclosed sync tags
        tag_stack: list[str] = []
        for m in _TAG_RE.finditer(combined):
            tag = m.group(1).lower()
            if tag == "end":
                if tag_stack:
                    tag_stack.pop()
                else:
                    issues.append(
                        "CLAUDE.md: <!-- sync:end --> without matching opening tag"
                    )
            else:
                tag_stack.append(tag)

        for unclosed in tag_stack:
            issues.append(
                f"CLAUDE.md: unclosed <!-- sync:{unclosed} --> tag (missing <!-- sync:end -->)"
            )

        return issues

    def _lint_settings(self, settings: dict) -> list[str]:
        """Check settings.json content."""
        issues: list[str] = []
        if not isinstance(settings, dict):
            issues.append("settings.json: content is not a JSON object — will be skipped")
            return issues

        # Warn on keys that look like corruption artifacts
        unexpected = set(settings.keys()) - _KNOWN_SETTINGS_KEYS
        # Filter to truly suspicious keys (long random-looking strings)
        truly_suspicious = [k for k in unexpected if len(k) > 40 or not k.replace("_", "").isalnum()]
        for k in truly_suspicious[:3]:
            issues.append(
                f"settings.json: suspicious key '{k[:60]}' — possible file corruption"
            )

        return issues

    def _lint_skills(self, skills: dict) -> list[str]:
        """Check that skill directories exist."""
        issues: list[str] = []
        for name, path in (skills or {}).items():
            p = Path(path) if not isinstance(path, Path) else path
            if not p.exists():
                issues.append(f"Skill '{name}' references missing directory: {p}")
            elif not (p / "SKILL.md").exists() and not any(p.iterdir()):
                issues.append(f"Skill '{name}' directory is empty: {p}")
        return issues

    def _lint_agents(self, agents: dict) -> list[str]:
        """Check that agent files exist."""
        issues: list[str] = []
        for name, path in (agents or {}).items():
            p = Path(path) if not isinstance(path, Path) else path
            if not p.exists():
                issues.append(f"Agent '{name}' references missing file: {p}")
        return issues

    # ------------------------------------------------------------------
    # Auto-fix API
    # ------------------------------------------------------------------

    def suggest_fixes(
        self,
        source_data: dict,
        project_dir: Path | None = None,
        cc_home: Path | None = None,
    ) -> list[LintFix]:
        """Return lint issues paired with fix suggestions.

        Unlike ``lint()``, this returns structured ``LintFix`` objects that
        include a human-readable suggestion and (where possible) an
        ``auto_fixable`` flag with the regex needed to apply the fix.

        Args:
            source_data: Output of ``SourceReader.discover_all()``.
            project_dir: Project root directory.
            cc_home: Claude Code config directory.

        Returns:
            List of LintFix objects. Empty list if no issues found.
        """
        fixes: list[LintFix] = []

        rules = source_data.get("rules", "")
        if isinstance(rules, list):
            texts = [r.get("content", "") for r in rules if isinstance(r, dict)]
            combined = "\n".join(texts)
        else:
            combined = rules or ""

        if combined.strip():
            fixes.extend(self._suggest_rule_fixes(combined))

        fixes.extend(self._suggest_portability_fixes(combined))

        return fixes

    def apply_fixes(self, content: str, fixes: list[LintFix]) -> str:
        """Apply all auto-fixable fixes to the given content string.

        Only fixes where ``auto_fixable=True`` and ``fix_pattern`` is set
        are applied. Non-auto-fixable suggestions are skipped.

        Args:
            content: Raw rules content (e.g. CLAUDE.md text).
            fixes: LintFix objects from ``suggest_fixes()``.

        Returns:
            Content string with fixes applied.
        """
        for fix in fixes:
            if fix.auto_fixable and fix.fix_pattern is not None:
                content = fix.fix_pattern.sub(fix.fix_replacement, content)
        return content

    def format_fix_report(self, fixes: list[LintFix]) -> str:
        """Format LintFix list as human-readable report.

        Args:
            fixes: LintFix objects from ``suggest_fixes()``.

        Returns:
            Multi-line formatted string.
        """
        if not fixes:
            return "No lint issues found. Config looks portable!"

        lines = [f"Config Lint Report — {len(fixes)} issue(s) found", "=" * 50, ""]
        auto_count = sum(1 for f in fixes if f.auto_fixable)

        for i, fix in enumerate(fixes, 1):
            icon = "[AUTO-FIX]" if fix.auto_fixable else "[MANUAL]  "
            lines.append(f"{i}. {icon} {fix.issue}")
            lines.append(f"   → {fix.suggestion}")
            lines.append("")

        if auto_count:
            lines.append(
                f"{auto_count} issue(s) can be auto-fixed. "
                "Call apply_fixes() on your CLAUDE.md content to apply them."
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Fix suggestion helpers
    # ------------------------------------------------------------------

    def _suggest_rule_fixes(self, combined: str) -> list[LintFix]:
        """Generate fixes for unclosed tags and broken fences."""
        fixes: list[LintFix] = []

        # Unclosed markdown fences
        fences = _FENCE_RE.findall(combined)
        if len(fences) % 2 != 0:
            fixes.append(LintFix(
                issue="Unclosed markdown code fence (odd number of ``` markers)",
                suggestion="Add a closing ``` at the end of the unclosed code block. "
                           "Run: grep -n '```' CLAUDE.md to locate the unclosed fence.",
                auto_fixable=False,
            ))

        # Unclosed sync tags
        tag_stack: list[str] = []
        for m in _TAG_RE.finditer(combined):
            tag = m.group(1).lower()
            if tag == "end":
                if tag_stack:
                    tag_stack.pop()
            else:
                tag_stack.append(tag)

        for unclosed in tag_stack:
            fixes.append(LintFix(
                issue=f"Unclosed <!-- sync:{unclosed} --> tag (missing <!-- sync:end -->)",
                suggestion=f"Add <!-- sync:end --> after the last line of the '{unclosed}' section.",
                auto_fixable=True,
                fix_pattern=re.compile(
                    r"(<!--\s*sync:" + re.escape(unclosed) + r"\s*-->[\s\S]+?)(\Z|(?=<!--\s*sync:))",
                    re.IGNORECASE,
                ),
                fix_replacement=r"\1\n<!-- sync:end -->\n\2",
            ))

        return fixes

    def _suggest_portability_fixes(self, combined: str) -> list[LintFix]:
        """Detect non-portable Claude Code syntax and suggest rewrites."""
        fixes: list[LintFix] = []

        for pattern, replacement, explanation in _PORTABILITY_PATTERNS:
            if pattern.search(combined):
                auto_fixable = bool(replacement) or replacement == ""
                fix = LintFix(
                    issue=explanation,
                    suggestion=(
                        f"Replace with: '{replacement}'" if replacement
                        else "Remove this construct — it has no equivalent in other harnesses."
                    ),
                    auto_fixable=auto_fixable and replacement is not None,
                    fix_pattern=pattern if auto_fixable else None,
                    fix_replacement=replacement,
                )
                fixes.append(fix)

        # Inline tool references (not auto-fixable — context-dependent)
        tool_matches = _INLINE_TOOL_RE.findall(combined)
        if tool_matches:
            unique_tools = sorted(set(tool_matches))[:5]
            fixes.append(LintFix(
                issue=f"Claude Code-specific tool references found: {', '.join(unique_tools)}",
                suggestion="Rewrite as generic actions (e.g. 'read the file', 'run the command') "
                           "so the instruction is meaningful to non-Claude Code harnesses.",
                auto_fixable=False,
            ))

        return fixes
