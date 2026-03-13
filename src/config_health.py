from __future__ import annotations

"""Config health score and recommendations.

Analyzes the current Claude Code config and scores it across dimensions:
- completeness: MCP servers configured? Rules present?
- portability: How much syncs cleanly vs gets dropped?
- security: Any secrets in rules or settings?
- size: CLAUDE.md too large for some targets?

Outputs actionable recommendations.
"""

import re
from pathlib import Path


# Target portability weights (fraction of sections supported natively)
# Based on sync_matrix.py CAPABILITY_MATRIX
_TARGET_NATIVE_FRACTIONS: dict[str, float] = {
    "codex": 0.70,
    "gemini": 0.90,
    "opencode": 0.90,
    "cursor": 0.75,
    "aider": 0.35,
    "windsurf": 0.70,
    "cline": 0.65,      # Rules + MCP native; agents/skills partial; commands dropped
    "continue": 0.70,   # Rules + MCP native; agents/commands via prompts
    "zed": 0.65,        # Rules native; MCP via context_servers; others partial
    "neovim": 0.65,     # Rules native; MCP native; others partial
}

# Size thresholds (bytes)
RULES_SIZE_WARN = 50_000     # 50KB warning
RULES_SIZE_CRITICAL = 100_000  # 100KB critical

# Secret patterns (same as SecretDetector uses)
_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE),           # OpenAI key
    re.compile(r"AKIA[A-Z0-9]{16}", re.IGNORECASE),              # AWS access key
    re.compile(r"ghp_[A-Za-z0-9]{36}", re.IGNORECASE),           # GitHub PAT
    re.compile(r"xoxb-[A-Za-z0-9-]{24,}", re.IGNORECASE),        # Slack bot token
    re.compile(r"(?i)(password|passwd|secret|api[_-]?key)\s*[:=]\s*\S{8,}"),
]


class HealthDimension:
    """Score and details for one health dimension."""

    def __init__(self, name: str, score: int, label: str, recommendations: list[str]):
        self.name = name
        self.score = score          # 0-100
        self.label = label          # e.g. "good" / "fair" / "poor"
        self.recommendations = recommendations


class ConfigHealthReport:
    """Overall config health report."""

    def __init__(self):
        self.dimensions: list[HealthDimension] = []

    def add(self, dimension: HealthDimension) -> None:
        self.dimensions.append(dimension)

    @property
    def overall_score(self) -> int:
        if not self.dimensions:
            return 0
        return int(sum(d.score for d in self.dimensions) / len(self.dimensions))

    @property
    def overall_label(self) -> str:
        score = self.overall_score
        if score >= 80:
            return "good"
        elif score >= 60:
            return "fair"
        elif score >= 40:
            return "poor"
        return "critical"


class ConfigHealthChecker:
    """Analyzes Claude Code config and produces a health report."""

    def check(
        self,
        source_data: dict,
        project_dir: Path | None = None,
        cc_home: Path | None = None,
    ) -> ConfigHealthReport:
        """Run all health checks.

        Args:
            source_data: Output of SourceReader.discover_all()
            project_dir: Project root (optional, for file size checks)
            cc_home: Claude Code home directory (optional, for freshness checks).
                     Defaults to Path.home() / ".claude".

        Returns:
            ConfigHealthReport
        """
        report = ConfigHealthReport()
        report.add(self._check_completeness(source_data))
        report.add(self._check_portability(source_data))
        report.add(self._check_security(source_data))
        report.add(self._check_size(source_data, project_dir))
        report.add(self._check_freshness(project_dir, cc_home))
        return report

    def format_report(self, report: ConfigHealthReport) -> str:
        """Format health report as human-readable text."""
        lines: list[str] = []
        lines.append("Config Health Score")
        lines.append("=" * 50)
        lines.append(f"\nOverall: {report.overall_score}/100  [{report.overall_label.upper()}]")
        lines.append("")

        for dim in report.dimensions:
            bar = _score_bar(dim.score)
            lines.append(f"{dim.name:<15}  {bar}  {dim.score:>3}/100  [{dim.label}]")

        recommendations = [
            rec for dim in report.dimensions for rec in dim.recommendations
        ]
        if recommendations:
            lines.append("")
            lines.append("Recommendations:")
            for rec in recommendations:
                lines.append(f"  • {rec}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private checks
    # ------------------------------------------------------------------

    def _check_completeness(self, data: dict) -> HealthDimension:
        """Check if key config sections are populated."""
        score = 100
        recs: list[str] = []

        has_rules = bool(data.get("rules") or data.get("rules_files"))
        has_mcp = bool(data.get("mcp_servers"))
        has_skills = bool(data.get("skills"))

        if not has_rules:
            score -= 30
            recs.append("No CLAUDE.md rules found — add rules to guide AI behavior across harnesses")
        if not has_mcp:
            score -= 20
            recs.append("No MCP servers configured — MCP servers extend harness capabilities significantly")
        if not has_skills:
            score -= 10
            recs.append("No skills found — skills allow reusable workflows across harnesses")

        label = _label(score)
        return HealthDimension("completeness", score, label, recs)

    def _check_portability(self, data: dict) -> HealthDimension:
        """Check how much of the config syncs cleanly to all targets."""
        from src.adapters import AdapterRegistry
        targets = AdapterRegistry.list_targets()
        if not targets:
            return HealthDimension("portability", 100, "good", [])

        avg_fraction = sum(_TARGET_NATIVE_FRACTIONS.get(t, 0.5) for t in targets) / len(targets)
        score = int(avg_fraction * 100)
        recs: list[str] = []

        low_targets = [t for t in targets if _TARGET_NATIVE_FRACTIONS.get(t, 0.5) < 0.5]
        if low_targets:
            recs.append(
                f"Targets {', '.join(low_targets)} have limited compatibility — "
                f"run /sync-matrix for details on what gets dropped"
            )

        label = _label(score)
        return HealthDimension("portability", score, label, recs)

    def _check_security(self, data: dict) -> HealthDimension:
        """Scan rules and settings for potential secrets."""
        score = 100
        recs: list[str] = []

        # Scan rules content
        rules_texts: list[str] = []
        raw_rules = data.get("rules", "")
        if isinstance(raw_rules, str):
            rules_texts.append(raw_rules)
        elif isinstance(raw_rules, list):
            rules_texts.extend(r.get("content", "") for r in raw_rules if isinstance(r, dict))

        found_secrets = False
        for text in rules_texts:
            for pattern in _SECRET_PATTERNS:
                if pattern.search(text):
                    found_secrets = True
                    break

        if found_secrets:
            score -= 50
            recs.append(
                "Potential secrets detected in CLAUDE.md — run /sync-lint for details. "
                "Remove secrets before syncing to prevent credential leakage"
            )

        label = _label(score)
        return HealthDimension("security", score, label, recs)

    def _check_size(self, data: dict, project_dir: Path | None) -> HealthDimension:
        """Check for oversized config files that may cause issues."""
        score = 100
        recs: list[str] = []

        if project_dir:
            claude_md = project_dir / "CLAUDE.md"
            if claude_md.is_file():
                size = claude_md.stat().st_size
                if size > RULES_SIZE_CRITICAL:
                    score -= 40
                    recs.append(
                        f"CLAUDE.md is very large ({size // 1024}KB) — "
                        "consider splitting into focused rule files in .claude/rules/ "
                        "for better Codex/Aider compatibility"
                    )
                elif size > RULES_SIZE_WARN:
                    score -= 20
                    recs.append(
                        f"CLAUDE.md is large ({size // 1024}KB) — "
                        "consider splitting into smaller rule files"
                    )

        label = _label(score)
        return HealthDimension("size", score, label, recs)

    def _check_freshness(
        self,
        project_dir: Path | None,
        cc_home: Path | None = None,
    ) -> HealthDimension:
        """Score config freshness — how recently were target harness files updated.

        Checks the modification times of known target harness config files
        relative to the source CLAUDE.md. A score of 100 means all detected
        target configs are at least as recent as the source. Scores drop when
        target configs are significantly older than the source, indicating drift.

        A missing source CLAUDE.md or no target harness files means we can't
        assess freshness, so we return 100 (no evidence of staleness).

        Args:
            project_dir: Project root directory.
            cc_home: Claude Code home dir (defaults to ~/.claude).

        Returns:
            HealthDimension with score, label, and recommendations.
        """
        import time as _time

        score = 100
        recs: list[str] = []

        if not project_dir:
            return HealthDimension("freshness", score, "good", recs)

        # Determine source CLAUDE.md mtime
        source_mtime: float | None = None
        for source_candidate in [
            project_dir / "CLAUDE.md",
            (cc_home or Path.home() / ".claude") / "CLAUDE.md",
        ]:
            if source_candidate.is_file():
                source_mtime = source_candidate.stat().st_mtime
                break

        if source_mtime is None:
            return HealthDimension("freshness", score, "good", recs)

        # Known target harness config files relative to project dir
        _HARNESS_CONFIG_PATHS = [
            project_dir / "AGENTS.md",                       # Codex
            project_dir / ".gemini" / "GEMINI.md",           # Gemini
            project_dir / ".opencode" / "instructions.md",   # OpenCode
            project_dir / ".cursor" / "rules",               # Cursor rules dir
            project_dir / "CONVENTIONS.md",                  # Aider
            project_dir / ".windsurfrules",                  # Windsurf
        ]

        stale_targets: list[str] = []
        now = _time.time()

        # Threshold: target config is "stale" if it's more than 1 hour older than source
        STALE_THRESHOLD_SECS = 3600

        for path in _HARNESS_CONFIG_PATHS:
            if not path.exists():
                continue
            target_mtime = path.stat().st_mtime
            age_vs_source = source_mtime - target_mtime
            if age_vs_source > STALE_THRESHOLD_SECS:
                stale_targets.append(path.name)

        # Score: -15 per stale target, floor at 40
        if stale_targets:
            penalty = min(60, len(stale_targets) * 15)
            score = max(40, 100 - penalty)
            recs.append(
                f"{len(stale_targets)} target config file(s) appear stale "
                f"({', '.join(stale_targets)}) — run /sync to bring them up to date"
            )

        # Additionally check source mtime age (is CLAUDE.md itself very old?)
        source_age_days = (now - source_mtime) / 86400
        if source_age_days > 90:
            score = min(score, 70)
            recs.append(
                f"CLAUDE.md hasn't been modified in {int(source_age_days)} days — "
                "consider reviewing rules for relevance"
            )

        label = _label(score)
        return HealthDimension("freshness", score, label, recs)


def _label(score: int) -> str:
    if score >= 80:
        return "good"
    elif score >= 60:
        return "fair"
    elif score >= 40:
        return "poor"
    return "critical"


def _score_bar(score: int, width: int = 20) -> str:
    """Generate an ASCII progress bar for a score 0-100."""
    filled = int(score / 100 * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


def suggest_rule_improvements(rules_content: str) -> list[dict]:
    """Analyze rule content and suggest improvements for quality and clarity.

    Detects common config quality issues:
    - Duplicate or near-duplicate rules that can be consolidated
    - Overly long rules that should be split
    - Rules with vague language that lack actionable specifics
    - Rules that reference external tools/versions that may be outdated
    - Empty or placeholder rules

    Args:
        rules_content: Full text of CLAUDE.md or combined rules content.

    Returns:
        List of suggestion dicts, each with:
            - type: "duplicate" | "vague" | "too-long" | "outdated-ref" | "empty"
            - severity: "info" | "warn"
            - line: int | None — approximate source line (1-indexed)
            - message: str — human-readable suggestion
            - excerpt: str — snippet of the rule in question (≤120 chars)
    """
    suggestions: list[dict] = []
    lines = rules_content.splitlines()

    _BULLET_RE = re.compile(r"^[-*•]\s+(.+)$")
    bullet_rules: list[tuple[int, str]] = []
    for i, line in enumerate(lines, 1):
        m = _BULLET_RE.match(line.strip())
        if m:
            bullet_rules.append((i, m.group(1).strip()))

    # Duplicate / near-duplicate detection via Jaccard similarity on word tokens
    _STOP_WORDS = {"the", "a", "an", "and", "or", "in", "to", "of", "for",
                   "is", "are", "be", "use", "when", "with", "this", "that"}

    def _tokens(text: str) -> frozenset[str]:
        words = re.findall(r"\b\w+\b", text.lower())
        return frozenset(w for w in words if w not in _STOP_WORDS and len(w) > 2)

    seen: list[tuple[frozenset, int]] = []
    for line_num, rule_text in bullet_rules:
        toks = _tokens(rule_text)
        if len(toks) >= 3:
            for prev_toks, prev_line in seen:
                if len(prev_toks) >= 3:
                    overlap = len(toks & prev_toks)
                    union = len(toks | prev_toks)
                    if union and overlap / union >= 0.7:
                        suggestions.append({
                            "type": "duplicate",
                            "severity": "warn",
                            "line": line_num,
                            "message": (
                                f"Rule on line {line_num} is very similar to rule on line {prev_line} "
                                f"({int(overlap / union * 100)}% overlap) — consider consolidating"
                            ),
                            "excerpt": rule_text[:120],
                        })
                        break
        seen.append((toks, line_num))

    # Vague language patterns
    _VAGUE: list[tuple[re.Pattern, str]] = [
        (re.compile(r"\bmake sure\b", re.I),
         "'Make sure' is vague — rephrase as a specific action or constraint"),
        (re.compile(r"\bif (possible|applicable|needed)\b", re.I),
         "Conditional 'if possible/needed' rules are often skipped — make them specific or remove"),
        (re.compile(r"\b(various|some|several)\b.{0,30}\b(files?|places?|cases?)\b", re.I),
         "Vague quantifiers ('various', 'some', 'several') should be replaced with specifics"),
    ]
    for line_num, rule_text in bullet_rules:
        for pattern, message in _VAGUE:
            if pattern.search(rule_text):
                suggestions.append({
                    "type": "vague",
                    "severity": "info",
                    "line": line_num,
                    "message": message,
                    "excerpt": rule_text[:120],
                })
                break

    # Overly long rules
    for line_num, rule_text in bullet_rules:
        if len(rule_text) > 300:
            suggestions.append({
                "type": "too-long",
                "severity": "info",
                "line": line_num,
                "message": (
                    f"Rule on line {line_num} is {len(rule_text)} chars — "
                    "consider splitting into multiple focused rules for better portability"
                ),
                "excerpt": rule_text[:120] + "...",
            })

    # Outdated hard-coded references
    _OUTDATED: list[tuple[re.Pattern, str]] = [
        (re.compile(r"\bgpt-3\.5\b|\bgpt-4\b(?!o)", re.I),
         "Hard-coded model version may become outdated — use abstract capability names"),
        (re.compile(r"\b(node|python|go)\s+\d+\.\d+\b", re.I),
         "Hard-coded language version may go stale — remove or add a review note"),
    ]
    for line_num, rule_text in bullet_rules:
        for pattern, message in _OUTDATED:
            if pattern.search(rule_text):
                suggestions.append({
                    "type": "outdated-ref",
                    "severity": "info",
                    "line": line_num,
                    "message": message,
                    "excerpt": rule_text[:120],
                })
                break

    # Empty / placeholder rules
    _PLACEHOLDER_RE = re.compile(
        r"^(TODO|FIXME|TBD|placeholder|fill in|your rule here)[\s:]*$", re.I
    )
    for line_num, rule_text in bullet_rules:
        if _PLACEHOLDER_RE.match(rule_text) or len(rule_text.strip()) < 10:
            suggestions.append({
                "type": "empty",
                "severity": "warn",
                "line": line_num,
                "message": f"Empty or placeholder rule on line {line_num} — remove or complete it",
                "excerpt": rule_text[:120],
            })

    return suggestions


def format_rule_improvement_suggestions(suggestions: list[dict]) -> str:
    """Format rule improvement suggestions as human-readable text.

    Args:
        suggestions: Output of suggest_rule_improvements().

    Returns:
        Formatted string, or empty string if no suggestions.
    """
    if not suggestions:
        return ""

    by_type: dict[str, list[dict]] = {}
    for s in suggestions:
        by_type.setdefault(s["type"], []).append(s)

    lines = ["Rule Improvement Suggestions", "=" * 50, ""]
    type_labels = {
        "duplicate":    ("⚠", "Potential Duplicate Rules"),
        "vague":        ("ℹ", "Vague Language"),
        "too-long":     ("ℹ", "Overly Long Rules"),
        "outdated-ref": ("ℹ", "Outdated References"),
        "empty":        ("⚠", "Empty / Placeholder Rules"),
    }
    for stype, (icon, label) in type_labels.items():
        items = by_type.get(stype, [])
        if not items:
            continue
        lines.append(f"{icon} {label} ({len(items)}):")
        for s in items:
            line_ref = f"line {s['line']}: " if s.get("line") else ""
            lines.append(f"  {line_ref}{s['message']}")
            if s.get("excerpt"):
                lines.append(f"    \"{s['excerpt'][:80]}\"")
        lines.append("")

    total_warn = sum(1 for s in suggestions if s["severity"] == "warn")
    total_info = sum(1 for s in suggestions if s["severity"] == "info")
    parts = []
    if total_warn:
        parts.append(f"{total_warn} warning(s)")
    if total_info:
        parts.append(f"{total_info} suggestion(s)")
    lines.append("Summary: " + ", ".join(parts))
    return "\n".join(lines)


def pre_sync_gap_warnings(
    source_data: dict,
    targets: list[str] | None = None,
) -> list[dict]:
    """Warn about source settings that have no equivalent in target harnesses.

    Call this BEFORE syncing to give users a chance to decide how to handle
    settings that will be silently dropped or approximated. Unlike the health
    score (post-hoc aggregate), each warning here is actionable and specific.

    Args:
        source_data: Output of SourceReader.discover_all()
        targets: Target harness names to check (default: all registered).

    Returns:
        List of warning dicts, each with:
            - target: str — which harness this affects
            - setting: str — the setting/field that has no equivalent
            - severity: "info" | "warn" | "error"
            - message: str — human-readable explanation
            - suggestion: str — closest approximation or workaround
    """
    if targets is None:
        try:
            from src.adapters import AdapterRegistry
            targets = AdapterRegistry.list_targets()
        except Exception:
            targets = list(_TARGET_NATIVE_FRACTIONS.keys())

    warnings: list[dict] = []
    settings = source_data.get("settings", {})
    mcp_servers = source_data.get("mcp_servers", {})
    has_agents = bool(source_data.get("agents"))
    has_commands = bool(source_data.get("commands"))

    # Per-target gap matrix: setting_key -> {target: (severity, message, suggestion)}
    _GAPS: dict[str, dict[str, tuple[str, str, str]]] = {
        "allowedTools": {
            "gemini": (
                "warn",
                "Claude Code tool allowlist has no direct Gemini equivalent",
                "Add '<!-- sync:gemini-only --> Use caution with tool execution' to GEMINI.md",
            ),
            "aider": (
                "warn",
                "Claude Code tool allowlist has no Aider equivalent",
                "Consider adding tool guidance to CONVENTIONS.md instead",
            ),
        },
        "deniedTools": {
            "gemini": (
                "error",
                "Claude Code tool denylist has no Gemini equivalent — denied tools will not be blocked",
                "Add explicit instructions in GEMINI.md: '<!-- sync:gemini-only --> Do not use: <tool>'",
            ),
            "aider": (
                "error",
                "Claude Code tool denylist has no Aider equivalent",
                "Add explicit tool restrictions to CONVENTIONS.md for Aider",
            ),
            "cursor": (
                "warn",
                "Claude Code tool denylist maps partially to Cursor rules",
                "Check .cursor/rules/ for any injected deny guidance after sync",
            ),
        },
        "approvalMode": {
            "aider": (
                "info",
                "Claude Code approvalMode has no Aider equivalent (Aider always requires per-change approval)",
                "No action needed — Aider's default behavior is to confirm each edit",
            ),
        },
        "env": {
            "gemini": (
                "warn",
                "Environment variables in settings.json are not forwarded to Gemini CLI",
                "Add required env vars to ~/.gemini/.env manually or via /sync-setup",
            ),
        },
    }

    for setting_key, target_map in _GAPS.items():
        if not settings.get(setting_key):
            continue
        for target in targets:
            if target not in target_map:
                continue
            severity, message, suggestion = target_map[target]
            warnings.append({
                "target": target,
                "setting": setting_key,
                "severity": severity,
                "message": message,
                "suggestion": suggestion,
            })

    # Warn about agents for harnesses that convert rather than support them natively
    _NO_AGENT_SUPPORT = {"aider", "windsurf", "cursor"}
    if has_agents:
        for target in targets:
            if target in _NO_AGENT_SUPPORT:
                warnings.append({
                    "target": target,
                    "setting": "agents",
                    "severity": "info",
                    "message": f"{target} has no native agent system — agents will be converted to rules",
                    "suggestion": "Agent content will be inlined as instructions; review after sync",
                })

    # Warn about slash commands for harnesses that don't support them
    _NO_COMMAND_SUPPORT = {"aider", "gemini"}
    if has_commands:
        for target in targets:
            if target in _NO_COMMAND_SUPPORT:
                warnings.append({
                    "target": target,
                    "setting": "commands",
                    "severity": "info",
                    "message": f"{target} has no slash command system — commands will be summarized or dropped",
                    "suggestion": "Key commands will be documented as instructions in the target's rules file",
                })

    # Warn about URL-based MCP servers for targets that only support stdio
    url_mcp_servers = {
        k: v for k, v in mcp_servers.items()
        if v.get("type") == "url" or v.get("url")
    }
    if url_mcp_servers:
        _NO_URL_MCP = {"aider", "cursor"}
        for target in targets:
            if target in _NO_URL_MCP:
                names = ", ".join(list(url_mcp_servers.keys())[:3])
                if len(url_mcp_servers) > 3:
                    names += f" (+{len(url_mcp_servers) - 3} more)"
                warnings.append({
                    "target": target,
                    "setting": "mcp_url_servers",
                    "severity": "warn",
                    "message": f"{target} does not support remote/URL MCP servers ({names})",
                    "suggestion": "These MCP servers will be skipped for this target — use stdio-based servers instead",
                })

    return warnings


def format_pre_sync_warnings(warnings: list[dict]) -> str:
    """Format pre-sync gap warnings as human-readable text.

    Args:
        warnings: Output of pre_sync_gap_warnings().

    Returns:
        Formatted string, or empty string if no warnings.
    """
    if not warnings:
        return ""

    errors = [w for w in warnings if w["severity"] == "error"]
    warns = [w for w in warnings if w["severity"] == "warn"]
    infos = [w for w in warnings if w["severity"] == "info"]

    lines = ["Pre-Sync Capability Gap Warnings", "=" * 50, ""]

    for w in errors:
        lines.append(f"  ✗ [{w['target'].upper()}] {w['setting']}: {w['message']}")
        lines.append(f"    → {w['suggestion']}")
        lines.append("")

    for w in warns:
        lines.append(f"  ⚠ [{w['target'].upper()}] {w['setting']}: {w['message']}")
        lines.append(f"    → {w['suggestion']}")
        lines.append("")

    for w in infos:
        lines.append(f"  ℹ [{w['target'].upper()}] {w['setting']}: {w['message']}")
        lines.append(f"    → {w['suggestion']}")
        lines.append("")

    summary_parts = []
    if errors:
        summary_parts.append(f"{len(errors)} error(s)")
    if warns:
        summary_parts.append(f"{len(warns)} warning(s)")
    if infos:
        summary_parts.append(f"{len(infos)} info(s)")

    lines.append("Summary: " + ", ".join(summary_parts))
    if errors:
        lines.append("Errors indicate settings that will be silently dropped — review before syncing.")

    return "\n".join(lines)


def get_drift_analytics(state_manager, targets: list[str] | None = None) -> dict:
    """Compute drift frequency and age analytics for all configured targets.

    Tracks how often each target drifts from source and how long between syncs.
    Surfaces insights like "Your Codex config is 3 weeks out of date."

    Args:
        state_manager: StateManager instance for reading last-sync data.
        targets: List of targets to check. If None, checks all known targets.

    Returns:
        Dict with:
            per_target: {target -> {days_since_sync, drift_level, is_stale}}
            stale_targets: list of targets with significant drift
            insights: list of human-readable insight strings
    """
    import time as _time

    if targets is None:
        targets = [
            "codex", "gemini", "opencode", "cursor", "aider", "windsurf",
        ]

    now = _time.time()
    STALE_DAYS = 14  # 2 weeks without sync = stale
    WARN_DAYS = 7    # 1 week = worth a mention

    per_target: dict[str, dict] = {}
    stale_targets: list[str] = []
    insights: list[str] = []

    for target in targets:
        status = state_manager.get_target_status(target) or {}
        last_sync_ts = status.get("last_sync_time")

        if last_sync_ts is None:
            days = None
            drift_level = "unknown"
            is_stale = False  # Never synced — not "stale", just "not started"
        else:
            days = (now - last_sync_ts) / 86400
            if days > STALE_DAYS:
                drift_level = "high"
                is_stale = True
                stale_targets.append(target)
            elif days > WARN_DAYS:
                drift_level = "medium"
                is_stale = False
            else:
                drift_level = "low"
                is_stale = False

        per_target[target] = {
            "days_since_sync": round(days, 1) if days is not None else None,
            "drift_level": drift_level,
            "is_stale": is_stale,
            "last_sync_time": last_sync_ts,
        }

    # Build human-readable insights
    if stale_targets:
        for t in stale_targets:
            days = per_target[t]["days_since_sync"]
            if days is not None:
                insights.append(
                    f"Your {t} config is {int(days)} day(s) out of date. "
                    f"Run /sync --target {t} to update it."
                )

    never_synced = [t for t in targets if per_target[t]["days_since_sync"] is None]
    if never_synced:
        insights.append(
            f"{len(never_synced)} target(s) have never been synced: "
            + ", ".join(never_synced)
            + ". Run /sync to initialize them."
        )

    warn_targets = [
        t for t in targets
        if per_target[t]["drift_level"] == "medium"
    ]
    if warn_targets:
        insights.append(
            f"{len(warn_targets)} target(s) are approaching staleness (> {WARN_DAYS} days): "
            + ", ".join(warn_targets)
        )

    if not insights:
        active = [t for t in targets if per_target[t]["days_since_sync"] is not None]
        if active:
            insights.append(
                f"All {len(active)} active target(s) synced within the last {WARN_DAYS} days."
            )

    return {
        "per_target": per_target,
        "stale_targets": stale_targets,
        "insights": insights,
    }
