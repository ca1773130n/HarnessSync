from __future__ import annotations

"""Pre-sync configuration linter with custom rule support.

Validates CLAUDE.md and settings.json before sync and returns a list of
human-readable error/warning strings. Invalid configs are reported but
never block sync — the caller decides how to surface them.

Built-in checks:
- CLAUDE.md: non-empty, no obviously broken markdown code fences
- settings.json: valid JSON, no unknown top-level keys that indicate corruption
- Skill/agent references that point to missing directories
- Sync tags that are unclosed (sync:exclude without sync:end)
- Portability hints: tool-specific syntax, CC-specific constructs

Auto-fix support (suggest_fixes / apply_fixes):
- Close unclosed sync tags
- Rewrite non-portable tool references into portable equivalents
- Suggest rewrites for Markdown patterns that translate poorly

Custom lint rules (item 18):
Users and teams can define custom lint rules in
``.harness-sync/lint-rules.json``. Each rule specifies a pattern to
check and a message to show when the check fails. Rules are loaded by
``ConfigLinter.lint()`` and run alongside built-in checks.

Custom rule schema:
    [
        {
            "id": "require-testing-section",
            "description": "CLAUDE.md must include a ## Testing section",
            "type": "require_heading",
            "value": "Testing",
            "severity": "error"
        },
        {
            "id": "require-rule-rationale",
            "description": "Each rule bullet must have a rationale (ends with '— <reason>')",
            "type": "pattern_must_not_match",
            "pattern": "^- (?!.*—).*\\.",
            "severity": "warning"
        },
        {
            "id": "mcp-must-specify-tools",
            "description": "MCP server entries should specify allowed tools",
            "type": "mcp_field_required",
            "field": "tools",
            "severity": "warning"
        }
    ]

Supported rule types:
    require_heading:          CLAUDE.md must contain a heading with 'value'
    pattern_must_match:       rules content must match 'pattern'
    pattern_must_not_match:   rules content must NOT match 'pattern'
    max_lines:                rules content must be <= 'value' lines
    min_section_count:        CLAUDE.md must have >= 'value' ## headings
    mcp_field_required:       each MCP server must have key 'field'
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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

# @harness shorthand annotation recognition (item 28)
# <!-- @harness:codex-only --> / <!-- @harness:skip-gemini --> / <!-- @harness:cursor,aider -->
_AT_HARNESS_ANNOTATION_RE = re.compile(
    r"<!--\s*@harness:(?:skip-)?[a-z0-9][-a-z0-9,\s]*(?:-only)?\s*-->",
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
    # Auto-fixable: strip trailing whitespace on each line (common portability issue
    # causing inconsistent rendering in Cursor/Codex rule files)
    (
        re.compile(r"[ \t]+$", re.MULTILINE),
        "",
        "Trailing whitespace on rule lines can cause rendering issues in some harnesses",
    ),
    # Auto-fixable: Windows-style CRLF line endings (\\r\\n) → LF (\\n)
    (
        re.compile(r"\r\n"),
        "\n",
        "Windows CRLF line endings (\\r\\n) detected; normalize to LF for cross-platform harness compatibility",
    ),
    # Auto-fixable: more than 2 consecutive blank lines → 2 blank lines
    (
        re.compile(r"\n{4,}"),
        "\n\n\n",
        "More than 3 consecutive blank lines reduce readability; collapse to at most 2",
    ),
    # Auto-fixable: Claude-specific /slash-command references in rule text
    # Replace with a generic description to avoid confusing other harnesses
    (
        re.compile(r"\b/sync(?:-[a-z]+)?\b"),
        "[HarnessSync command]",
        "/sync* slash-command references are Claude Code-specific; use a generic description for portability",
    ),
    # Auto-fixable: strip <!-- sync:end --> tag lines that appear without an opening tag
    # (orphaned close tags confuse some harnesses that pass the content through literally)
    (
        re.compile(r"^<!--\s*sync:end\s*-->\s*\n", re.MULTILINE),
        "",
        "Orphaned <!-- sync:end --> without a matching opening tag — safe to remove",
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
    """Validates HarnessSync source configuration before sync.

    Custom rules are loaded from ``.harness-sync/lint-rules.json`` in the
    project directory. Use ``load_custom_rules()`` to inspect what's loaded,
    or ``add_custom_rule()`` to register rules programmatically.
    """

    # Default path for custom rules file (relative to project_dir)
    CUSTOM_RULES_FILE = ".harness-sync/lint-rules.json"

    def __init__(self) -> None:
        self._custom_rules: list[dict[str, Any]] = []

    def load_custom_rules(self, project_dir: Path) -> list[dict]:
        """Load custom lint rules from .harness-sync/lint-rules.json.

        Args:
            project_dir: Project root directory.

        Returns:
            List of loaded rule dicts. Empty if file missing or invalid.
        """
        rules_path = project_dir / self.CUSTOM_RULES_FILE
        if not rules_path.is_file():
            return []
        try:
            data = json.loads(rules_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._custom_rules = [r for r in data if isinstance(r, dict)]
            else:
                self._custom_rules = []
        except (json.JSONDecodeError, OSError):
            self._custom_rules = []
        return self._custom_rules

    def add_custom_rule(self, rule: dict[str, Any]) -> None:
        """Register a custom lint rule programmatically.

        Args:
            rule: Rule dict with at minimum 'id', 'description', 'type' keys.
        """
        self._custom_rules.append(rule)

    def lint(
        self,
        source_data: dict,
        project_dir: Path | None = None,
        cc_home: Path | None = None,
    ) -> list[str]:
        """Run all lint checks against discovered source data.

        Loads custom rules from ``<project_dir>/.harness-sync/lint-rules.json``
        (if project_dir is provided) and runs them alongside built-in checks.

        Args:
            source_data: Output of ``SourceReader.discover_all()``.
            project_dir: Project root (used for file existence checks and custom rules).
            cc_home: Claude Code config directory (used for file existence checks).

        Returns:
            List of issue strings. Empty list = no issues found.
        """
        issues: list[str] = []

        issues.extend(self._lint_rules(source_data.get("rules", "")))
        issues.extend(self._lint_settings(source_data.get("settings", {})))
        issues.extend(self._lint_skills(source_data.get("skills", {})))
        issues.extend(self._lint_agents(source_data.get("agents", {})))

        # Run custom lint rules if project_dir provided
        if project_dir:
            self.load_custom_rules(project_dir)
        if self._custom_rules:
            issues.extend(self._run_custom_rules(source_data))

        # Check for cross-harness rule duplicates (item 30)
        # Surface deduplication opportunities so --fix can consolidate them.
        if project_dir:
            issues.extend(self._lint_duplicates(project_dir))

        return issues

    def _lint_duplicates(self, project_dir: Path) -> list[str]:
        """Detect near-duplicate rules across harness config files.

        Uses RuleDeduplicator to find clusters of similar rules in CLAUDE.md,
        AGENTS.md, GEMINI.md, and other harness config files. Cross-harness
        duplicates indicate rules that should be consolidated in CLAUDE.md as
        the single source of truth.

        Args:
            project_dir: Project root directory.

        Returns:
            List of lint warning strings, one per cross-harness duplicate cluster.
        """
        try:
            from src.rule_deduplicator import RuleDeduplicator
            dedup = RuleDeduplicator(project_dir=project_dir)
            clusters = dedup.scan()
            cross_harness = [c for c in clusters if c.is_cross_harness]
            if not cross_harness:
                return []
            sources_summary = ", ".join(
                "/".join(sorted(c.sources)) for c in cross_harness[:3]
            )
            suffix = f" (e.g. {sources_summary})" if sources_summary else ""
            return [
                f"Found {len(cross_harness)} near-duplicate rule cluster(s) across harness "
                f"config files{suffix}. Consider consolidating in CLAUDE.md as the single "
                "source of truth. Run /sync to let HarnessSync propagate from there."
            ]
        except Exception:
            return []  # Deduplication check is best-effort

    def _run_custom_rules(self, source_data: dict) -> list[str]:
        """Execute all registered custom rules against source_data.

        Args:
            source_data: Output of SourceReader.discover_all().

        Returns:
            List of violation messages. Empty list if all rules pass.
        """
        issues: list[str] = []

        # Build combined rules text for content checks
        rules_raw = source_data.get("rules", "")
        if isinstance(rules_raw, list):
            combined = "\n".join(r.get("content", "") for r in rules_raw if isinstance(r, dict))
        else:
            combined = rules_raw or ""

        mcp_servers = source_data.get("mcp_servers", {})

        for rule in self._custom_rules:
            rule_id = rule.get("id", "custom")
            description = rule.get("description", rule_id)
            severity = rule.get("severity", "warning").upper()
            rule_type = rule.get("type", "")

            try:
                violation = self._evaluate_custom_rule(
                    rule_type, rule, combined, mcp_servers, source_data
                )
            except Exception as exc:
                issues.append(f"[custom:{rule_id}] Rule evaluation error: {exc}")
                continue

            if violation:
                issues.append(f"[{severity}][custom:{rule_id}] {description}")

        return issues

    def _evaluate_custom_rule(
        self,
        rule_type: str,
        rule: dict,
        combined_rules: str,
        mcp_servers: dict,
        source_data: dict,
    ) -> bool:
        """Evaluate a single custom rule. Returns True if there is a violation.

        Args:
            rule_type: The rule type string.
            rule: Full rule definition dict.
            combined_rules: All CLAUDE.md rules text concatenated.
            mcp_servers: MCP server config dict.
            source_data: Full source data from SourceReader.

        Returns:
            True if the rule is violated (an issue should be reported).
        """
        if rule_type == "require_heading":
            heading = rule.get("value", "")
            heading_re = re.compile(
                r"^#{1,4}\s+" + re.escape(heading), re.MULTILINE | re.IGNORECASE
            )
            return not heading_re.search(combined_rules)

        if rule_type == "pattern_must_match":
            pattern = rule.get("pattern", "")
            if not pattern:
                return False
            return not re.search(pattern, combined_rules, re.MULTILINE)

        if rule_type == "pattern_must_not_match":
            pattern = rule.get("pattern", "")
            if not pattern:
                return False
            return bool(re.search(pattern, combined_rules, re.MULTILINE))

        if rule_type == "max_lines":
            limit = int(rule.get("value", 500))
            return len(combined_rules.splitlines()) > limit

        if rule_type == "min_section_count":
            minimum = int(rule.get("value", 1))
            heading_count = len(re.findall(r"^#{1,4}\s+\S", combined_rules, re.MULTILINE))
            return heading_count < minimum

        if rule_type == "mcp_field_required":
            field_name = rule.get("field", "")
            if not field_name or not mcp_servers:
                return False
            return any(
                isinstance(cfg, dict) and field_name not in cfg
                for cfg in mcp_servers.values()
            )

        # Unknown rule type — skip silently
        return False

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

        # Secret-like patterns (auto-fixable: redact inline key values)
        # Catches obvious patterns: sk-..., ghp_..., xoxb-... embedded in rule text
        _SECRET_INLINE_RE = re.compile(
            r"\b(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{36,}|xoxb-[A-Za-z0-9\-]{40,}"
            r"|Bearer [A-Za-z0-9\-_.]{20,}|AIza[A-Za-z0-9\-_]{35,})\b"
        )
        if _SECRET_INLINE_RE.search(combined):
            fixes.append(LintFix(
                issue="Potential API key or secret token embedded in rules content",
                suggestion="Replace inline secret values with environment variable references "
                           "(e.g. $MY_API_KEY) or remove them entirely before syncing.",
                auto_fixable=True,
                fix_pattern=_SECRET_INLINE_RE,
                fix_replacement="[REDACTED]",
            ))

        return fixes

    # ─────────────────────────────────────────────────────────────────────────
    # Config Quality Score (item 10)
    # ─────────────────────────────────────────────────────────────────────────

    def quality_score(
        self,
        source_data: dict,
        project_dir: Path | None = None,
        cc_home: Path | None = None,
    ) -> dict:
        """Compute a 0–100 quality score for the current configuration.

        Runs the full lint suite and suggest_fixes pipeline, then converts the
        result into a numeric score with a tier label and a prioritised list of
        actionable suggestions.

        Scoring model
        ~~~~~~~~~~~~~
        * Base score: 100.
        * Each lint *error* (broken fence, unclosed tag, missing rules, …) deducts
          **10 points**.
        * Each portability *fix* (non-portable construct, CC-only tool reference,
          embedded secret) deducts **5 points**.
        * Cross-harness duplicate warnings deduct **3 points** each (capped at 15).
        * Score is clamped to [0, 100].

        Tier labels
        ~~~~~~~~~~~
        * 90–100  Excellent — config is clean and portable
        * 70–89   Good — minor portability issues
        * 50–69   Fair — several issues worth addressing
        * 0–49    Poor — significant problems present

        Args:
            source_data: Output of ``SourceReader.discover_all()``.
            project_dir: Project root (enables custom rules + duplicate checks).
            cc_home: Claude Code config directory.

        Returns:
            Dict with keys:

            * ``score`` (int 0–100)
            * ``tier`` (str: "Excellent" | "Good" | "Fair" | "Poor")
            * ``issues`` (list[str]) — all lint issue strings
            * ``suggestions`` (list[str]) — human-readable improvement hints
            * ``breakdown`` (dict) — per-category deduction totals
        """
        issues = self.lint(source_data, project_dir=project_dir, cc_home=cc_home)

        # Gather portability / fix suggestions from rules content
        rules_text = source_data.get("rules", "") or ""
        portability_fixes = self._suggest_portability_fixes(rules_text)
        rule_fixes = self._suggest_rule_fixes(rules_text)
        all_fixes = portability_fixes + rule_fixes

        # Categorise issues
        duplicate_issues = [i for i in issues if "duplicate" in i.lower() or "similar" in i.lower()]
        structural_issues = [i for i in issues if i not in duplicate_issues]

        # Compute deductions
        structural_deduction = min(len(structural_issues) * 10, 60)
        portability_deduction = min(len(portability_fixes) * 5, 30)
        duplicate_deduction = min(len(duplicate_issues) * 3, 15)

        score = max(0, 100 - structural_deduction - portability_deduction - duplicate_deduction)

        if score >= 90:
            tier = "Excellent"
        elif score >= 70:
            tier = "Good"
        elif score >= 50:
            tier = "Fair"
        else:
            tier = "Poor"

        # Build actionable suggestions (deduplicated, capped for readability)
        suggestions: list[str] = []
        seen: set[str] = set()
        for fix in all_fixes:
            hint = fix.suggestion
            if hint and hint not in seen:
                suggestions.append(hint)
                seen.add(hint)
        for issue in structural_issues:
            if issue not in seen:
                suggestions.append(f"Fix: {issue}")
                seen.add(issue)

        return {
            "score": score,
            "tier": tier,
            "issues": issues,
            "suggestions": suggestions[:10],
            "breakdown": {
                "structural_deduction": structural_deduction,
                "portability_deduction": portability_deduction,
                "duplicate_deduction": duplicate_deduction,
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Skill Portability Linter (Item 30)
    # ─────────────────────────────────────────────────────────────────────────

    # Patterns in skill files that won't translate to other harnesses
    _SKILL_PORTABILITY_CHECKS: list[tuple[re.Pattern, str, str]] = [
        # Claude Code-specific tool references
        (
            re.compile(
                r"\b(?:use\s+the\s+)?(?:Read|Write|Edit|Bash|Glob|Grep|Agent|TodoWrite"
                r"|TodoRead|WebFetch|WebSearch|NotebookRead|NotebookEdit)\s+tool\b",
                re.IGNORECASE,
            ),
            "CC_TOOL_REF",
            "References Claude Code tool names directly (e.g. 'Read tool', 'Bash tool'). "
            "Rewrite as generic actions ('read the file', 'run the command') so other harnesses understand.",
        ),
        # $ARGUMENTS placeholder
        (
            re.compile(r"\$ARGUMENTS\b"),
            "CC_ARGUMENTS",
            "$ARGUMENTS is Claude Code-specific. Replace with '[user arguments]' or describe "
            "expected input in a generic way.",
        ),
        # /slash-command references in skill body
        (
            re.compile(r"(?<!\w)/[a-z][a-z0-9-]*\b"),
            "CC_SLASH_CMD",
            "Slash-command references (e.g. /sync, /commit) are Claude Code-specific. "
            "Describe the action in plain language for portability.",
        ),
        # Hardcoded absolute paths
        (
            re.compile(r"(?<!\$)\b(/Users/|/home/|C:\\\\Users\\\\)[^\s\"']+"),
            "HARDCODED_PATH",
            "Hardcoded absolute path detected. Use ${HOME} or a relative path so the skill "
            "works across different machines and harnesses.",
        ),
        # YAML frontmatter keys used by Claude Code agent system but not others
        (
            re.compile(r"^subagent_type\s*:", re.MULTILINE),
            "CC_SUBAGENT_TYPE",
            "'subagent_type' frontmatter is Claude Code-specific and will be ignored by "
            "other harnesses. Document the agent role in the description instead.",
        ),
        # XML-style tool_call blocks
        (
            re.compile(r"<tool_call>", re.IGNORECASE),
            "CC_TOOL_CALL_XML",
            "<tool_call> XML syntax is Claude Code-specific. Remove these blocks or replace "
            "with plain-language instructions.",
        ),
        # Claude Code MCP tool references (mcp__*)
        (
            re.compile(r"\bmcp__[a-z][a-z0-9_]*__[a-z][a-z0-9_]*\b", re.IGNORECASE),
            "CC_MCP_TOOL_REF",
            "MCP tool reference (mcp__server__tool) is Claude Code-specific. "
            "Describe what the tool does generically.",
        ),
    ]

    def lint_skill_portability(
        self, skill_name: str, skill_path: Path
    ) -> list[dict]:
        """Lint a single skill file for cross-harness portability issues.

        Scans the SKILL.md (or the skill file directly if skill_path is a
        file) for patterns that are Claude Code-specific and won't translate
        to other harnesses (Cursor, Gemini, Aider, etc.).

        Args:
            skill_name: Human-readable skill name (for issue messages).
            skill_path: Path to skill directory (with SKILL.md) or .md file.

        Returns:
            List of issue dicts with keys:
              - ``code``:    Short identifier (e.g. "CC_TOOL_REF")
              - ``message``: Human-readable description of the issue
              - ``fix``:     Suggested fix description
              - ``line``:    1-based line number of first match (or 0 if unknown)
        """
        skill_md = (
            skill_path / "SKILL.md"
            if skill_path.is_dir() and (skill_path / "SKILL.md").is_file()
            else skill_path
        )
        if not skill_md.is_file():
            return [{
                "code": "MISSING_SKILL_MD",
                "message": f"Skill '{skill_name}': SKILL.md not found at {skill_md}",
                "fix": "Create a SKILL.md file in the skill directory.",
                "line": 0,
            }]

        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError as e:
            return [{
                "code": "READ_ERROR",
                "message": f"Skill '{skill_name}': cannot read {skill_md}: {e}",
                "fix": "Check file permissions.",
                "line": 0,
            }]

        issues: list[dict] = []
        lines = content.splitlines()

        for pattern, code, fix_description in self._SKILL_PORTABILITY_CHECKS:
            for lineno, line in enumerate(lines, start=1):
                if pattern.search(line):
                    issues.append({
                        "code": code,
                        "message": (
                            f"Skill '{skill_name}' line {lineno}: "
                            f"{fix_description.split('.')[0]}."
                        ),
                        "fix": fix_description,
                        "line": lineno,
                    })
                    break  # One issue per check type per skill

        return issues

    def lint_all_skills_portability(
        self, skills: dict[str, Path]
    ) -> dict[str, list[dict]]:
        """Lint all skills for portability issues.

        Args:
            skills: Dict mapping skill name -> skill path (from SourceReader).

        Returns:
            Dict mapping skill_name -> list of issue dicts.
            Only skills with issues are included.
        """
        results: dict[str, list[dict]] = {}
        for name, path in (skills or {}).items():
            issues = self.lint_skill_portability(name, Path(path) if not isinstance(path, Path) else path)
            if issues:
                results[name] = issues
        return results

    def format_skill_portability_report(
        self, issues_by_skill: dict[str, list[dict]]
    ) -> str:
        """Format the skill portability report as human-readable text.

        Args:
            issues_by_skill: Output from lint_all_skills_portability().

        Returns:
            Formatted report string.
        """
        if not issues_by_skill:
            return "Skill Portability Linter: All skills are portable across harnesses."

        total = sum(len(v) for v in issues_by_skill.values())
        lines = [
            f"Skill Portability Report — {total} issue(s) in {len(issues_by_skill)} skill(s)",
            "=" * 60,
            "",
            "Flagged patterns won't translate well to Cursor, Gemini, Aider, or other harnesses.",
            "",
        ]

        for skill_name, skill_issues in sorted(issues_by_skill.items()):
            lines.append(f"  [{skill_name}]  ({len(skill_issues)} issue(s))")
            for issue in skill_issues:
                line_ref = f" (line {issue['line']})" if issue.get("line") else ""
                lines.append(f"    [{issue['code']}]{line_ref}: {issue['message']}")
                lines.append(f"      Fix: {issue['fix']}")
            lines.append("")

        lines.append(
            "Tip: Tag Claude-Code-only skill sections with <!-- sync:skip --> to exclude\n"
            "     them from non-CC harnesses, or rewrite in harness-agnostic language."
        )
        return "\n".join(lines)

    # Pre-flight adapter-constraint checks (item: pre-flight mode)
    # Maps adapter name -> list of (check_fn, warning_message) tuples
    _PRE_FLIGHT_CHECKS: dict[str, list[tuple]] = {}

    def pre_flight_check(self, source_data: dict) -> list[dict]:
        """Validate source config against known adapter constraints before sync.

        Returns a list of warning dicts with keys: adapter, message, remediation.
        """
        warnings: list[dict] = []
        mcp_servers = source_data.get("mcp") or {}
        settings = source_data.get("settings") or {}
        env_vars = settings.get("env") or {}
        permissions = settings.get("permissions") or {}

        # Check MCP server transport compatibility
        for server_name, server_cfg in mcp_servers.items():
            if not isinstance(server_cfg, dict):
                continue
            transport = server_cfg.get("type") or server_cfg.get("transport", "stdio")
            if transport == "stdio":
                # Codex requires MCP servers to be reachable; stdio may not work in some envs
                pass  # stdio is widely supported
            elif transport in ("sse", "http"):
                for adapter in ("aider", "neovim"):
                    warnings.append({
                        "adapter": adapter,
                        "message": f"MCP server '{server_name}' uses '{transport}' transport which is not supported by {adapter}.",
                        "remediation": f"Use stdio transport for '{server_name}' or exclude it from {adapter} with --skip mcp.",
                    })

        # Check env var names for secret-like patterns
        _SECRET_PATTERNS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "PASS", "CREDENTIAL", "PRIVATE")
        for var_name in env_vars:
            upper = var_name.upper()
            if any(pat in upper for pat in _SECRET_PATTERNS):
                warnings.append({
                    "adapter": "all",
                    "message": f"Env var '{var_name}' matches a secret-like pattern and may be blocked by secret detection.",
                    "remediation": f"Remove '{var_name}' from env config or set allow_secrets=true if intentional.",
                })

        # Check deny permissions are not inadvertently included
        denied = permissions.get("deny") or []
        if denied:
            for adapter in ("codex", "gemini", "cursor"):
                warnings.append({
                    "adapter": adapter,
                    "message": f"{len(denied)} 'deny' permission(s) in source config — verify {adapter} honours Claude Code deny semantics.",
                    "remediation": "Review deny permissions in settings.json; not all harnesses enforce Claude Code permission syntax.",
                })
                break  # one warning per adapter group is enough

        # Check for agents used by harnesses that don't support them
        agents = source_data.get("agents") or {}
        if agents:
            for adapter in ("opencode", "aider", "zed", "neovim", "cline", "continue"):
                warnings.append({
                    "adapter": adapter,
                    "message": f"{len(agents)} agent(s) found but {adapter} does not support agent definitions — they will be dropped.",
                    "remediation": "Use --skip agents when syncing to these targets, or accept that agents won't transfer.",
                })

        return warnings
