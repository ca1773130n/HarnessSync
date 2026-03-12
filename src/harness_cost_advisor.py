from __future__ import annotations

"""Cross-Harness Cost Optimization Advisor (item 27).

Analyzes harness configuration and usage patterns across Claude Code, Gemini,
OpenCode, Codex, Aider, Cursor, and Windsurf to surface config changes that
could reduce API costs.

Examples of advice generated:
- "Your Gemini config is using Opus-class models for simple tasks; switching to
  Flash would save ~40% cost."
- "Cursor is set to auto-trigger on every keystroke; switching to manual trigger
  reduces API calls by ~60%."
- "3 MCP servers are configured globally but only used in 1 project; scoping
  them reduces cold-start token overhead."

Usage:
    from src.harness_cost_advisor import HarnessCostAdvisor

    advisor = HarnessCostAdvisor(project_dir=Path("."))
    report = advisor.analyze()
    print(advisor.format_report(report))

Or from the CLI:
    /sync-cost [--project-dir PATH] [--json]
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Model pricing (USD per 1M tokens, input/output) ───────────────────────
# Approximate public prices as of early 2025 — used for relative estimates.
_MODEL_PRICES: dict[str, tuple[float, float]] = {
    # Claude
    "claude-opus-4":                   (15.0,  75.0),
    "claude-opus-4-5":                 (15.0,  75.0),
    "claude-opus-4-6":                 (15.0,  75.0),
    "claude-sonnet-4":                 (3.0,   15.0),
    "claude-sonnet-4-5":               (3.0,   15.0),
    "claude-sonnet-4-6":               (3.0,   15.0),
    "claude-3-5-sonnet-20241022":      (3.0,   15.0),
    "claude-3-5-haiku-20241022":       (0.8,   4.0),
    "claude-haiku-4-5":                (0.8,   4.0),
    # Gemini
    "gemini-1.5-pro":                  (3.5,   10.5),
    "gemini-1.5-flash":                (0.075, 0.3),
    "gemini-2.0-flash":                (0.075, 0.3),
    "gemini-exp-1206":                 (0.0,   0.0),  # Free tier
    # OpenAI (Codex backend)
    "gpt-4o":                          (2.5,   10.0),
    "gpt-4o-mini":                     (0.15,  0.6),
    "o1":                              (15.0,  60.0),
    "o3-mini":                         (1.1,   4.4),
}

# Model tier classification
def _model_tier(model: str) -> str:
    model_lower = model.lower()
    if any(k in model_lower for k in ("opus", "gpt-4o\b", "o1", "1.5-pro", "gemini-exp")):
        return "expensive"
    if any(k in model_lower for k in ("sonnet", "gpt-4o-mini", "flash", "haiku")):
        return "mid"
    return "unknown"


@dataclass
class CostAdvisory:
    """A single cost optimization recommendation."""
    harness: str
    severity: str               # "high", "medium", "low"
    category: str               # "model", "trigger", "context", "mcp", "caching"
    issue: str
    recommendation: str
    estimated_savings: str      # Human-readable e.g. "~30–50% API cost"
    current_value: str = ""


@dataclass
class CostReport:
    """Complete cost optimization report across all harnesses."""
    advisories: list[CostAdvisory]
    detected_harnesses: list[str]
    total_high: int = 0
    total_medium: int = 0
    total_low: int = 0


class HarnessCostAdvisor:
    """Analyze harness configurations for cost optimization opportunities.

    Args:
        project_dir: Project root.  Defaults to cwd.
        cc_home:     Claude Code home.  Defaults to ~/.claude.
    """

    def __init__(self, project_dir: Path | None = None, cc_home: Path | None = None):
        self.project_dir = project_dir or Path.cwd()
        self.cc_home = cc_home or (Path.home() / ".claude")

    def analyze(self) -> CostReport:
        """Scan all harness configs and return cost advisories."""
        advisories: list[CostAdvisory] = []
        detected: list[str] = []

        # Claude Code / source
        cc_items, cc_found = self._analyze_claude_code()
        advisories.extend(cc_items)
        if cc_found:
            detected.append("claude-code")

        # Gemini
        g_items, g_found = self._analyze_gemini()
        advisories.extend(g_items)
        if g_found:
            detected.append("gemini")

        # OpenCode
        oc_items, oc_found = self._analyze_opencode()
        advisories.extend(oc_items)
        if oc_found:
            detected.append("opencode")

        # Codex
        cx_items, cx_found = self._analyze_codex()
        advisories.extend(cx_items)
        if cx_found:
            detected.append("codex")

        # Cursor
        cur_items, cur_found = self._analyze_cursor()
        advisories.extend(cur_items)
        if cur_found:
            detected.append("cursor")

        # MCP overhead analysis
        mcp_items = self._analyze_mcp_overhead()
        advisories.extend(mcp_items)

        # CLAUDE.md context budget analysis
        ctx_items = self._analyze_context_budget()
        advisories.extend(ctx_items)

        # Sort: high > medium > low
        severity_order = {"high": 0, "medium": 1, "low": 2}
        advisories.sort(key=lambda a: severity_order.get(a.severity, 3))

        report = CostReport(
            advisories=advisories,
            detected_harnesses=detected,
        )
        report.total_high = sum(1 for a in advisories if a.severity == "high")
        report.total_medium = sum(1 for a in advisories if a.severity == "medium")
        report.total_low = sum(1 for a in advisories if a.severity == "low")
        return report

    # ── Per-harness analyzers ──────────────────────────────────────────────

    def _analyze_claude_code(self) -> tuple[list[CostAdvisory], bool]:
        items: list[CostAdvisory] = []
        claude_json = self.cc_home / ".claude.json"
        if not claude_json.exists():
            return items, False
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return items, False

        # Check for expensive model in settings
        model = data.get("model", "") or ""
        if _model_tier(model) == "expensive":
            alt = self._suggest_cheaper_model(model)
            items.append(CostAdvisory(
                harness="claude-code",
                severity="medium",
                category="model",
                issue=f"Global model set to expensive tier: {model}",
                recommendation=f"Consider {alt} for routine tasks; reserve {model} for complex work",
                estimated_savings="~50–80% per-request API cost",
                current_value=model,
            ))

        # Large number of global MCP servers
        mcp_servers = data.get("mcpServers", {})
        if len(mcp_servers) > 8:
            items.append(CostAdvisory(
                harness="claude-code",
                severity="low",
                category="mcp",
                issue=f"{len(mcp_servers)} MCP servers loaded globally",
                recommendation="Move rarely-used servers to per-project config to reduce context token overhead",
                estimated_savings="~5–15% context token reduction per session",
                current_value=f"{len(mcp_servers)} servers",
            ))
        return items, True

    def _analyze_gemini(self) -> tuple[list[CostAdvisory], bool]:
        items: list[CostAdvisory] = []
        # Check GEMINI.md for model hints and gemini.json
        gemini_md = self.project_dir / "GEMINI.md"
        gemini_json = self.project_dir / "gemini.json"
        found = gemini_md.exists() or gemini_json.exists()
        if not found:
            return items, False

        # Read gemini.json if present
        if gemini_json.exists():
            try:
                data = json.loads(gemini_json.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            model = data.get("model", "") or ""
            if model and _model_tier(model) == "expensive":
                items.append(CostAdvisory(
                    harness="gemini",
                    severity="high",
                    category="model",
                    issue=f"Gemini configured with expensive model: {model}",
                    recommendation="Use gemini-2.0-flash or gemini-1.5-flash for routine tasks (~97% cheaper per token)",
                    estimated_savings="~90–97% API cost for routine tasks",
                    current_value=model,
                ))

        return items, True

    def _analyze_opencode(self) -> tuple[list[CostAdvisory], bool]:
        items: list[CostAdvisory] = []
        oc_json = self.project_dir / "opencode.json"
        if not oc_json.exists():
            return items, False
        try:
            data = json.loads(oc_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return items, False

        model = data.get("model", "") or ""
        if model and _model_tier(model) == "expensive":
            alt = self._suggest_cheaper_model(model)
            items.append(CostAdvisory(
                harness="opencode",
                severity="medium",
                category="model",
                issue=f"OpenCode model set to expensive tier: {model}",
                recommendation=f"Switch to {alt} for the majority of tasks",
                estimated_savings="~50–80% per-request cost",
                current_value=model,
            ))
        return items, True

    def _analyze_codex(self) -> tuple[list[CostAdvisory], bool]:
        items: list[CostAdvisory] = []
        config = self.project_dir / ".codex" / "config.toml"
        if not config.exists():
            return items, False
        try:
            content = config.read_text(encoding="utf-8")
        except OSError:
            return items, False

        model_match = re.search(r'model\s*=\s*"([^"]+)"', content)
        if model_match:
            model = model_match.group(1)
            if _model_tier(model) == "expensive":
                alt = self._suggest_cheaper_model(model)
                items.append(CostAdvisory(
                    harness="codex",
                    severity="medium",
                    category="model",
                    issue=f"Codex model configured to expensive tier: {model}",
                    recommendation=f"Switch to {alt} for routine code tasks",
                    estimated_savings="~50–75% per-request cost",
                    current_value=model,
                ))

        # Check approval policy — 'on-failure' triggers more requests than 'on-request'
        if "on-failure" in content:
            items.append(CostAdvisory(
                harness="codex",
                severity="low",
                category="trigger",
                issue="approval_policy=on-failure causes extra API calls on each failure",
                recommendation="Consider 'on-request' approval to reduce automatic retries",
                estimated_savings="~10–25% fewer API calls in error-heavy sessions",
                current_value="on-failure",
            ))
        return items, True

    def _analyze_cursor(self) -> tuple[list[CostAdvisory], bool]:
        items: list[CostAdvisory] = []
        cursor_dir = self.project_dir / ".cursor"
        if not cursor_dir.is_dir():
            return items, False

        # Count total rule size — large rules files increase context cost per request
        total_rule_bytes = 0
        rule_files = list(cursor_dir.glob("rules/*.mdc"))
        for mdc in rule_files:
            try:
                total_rule_bytes += mdc.stat().st_size
            except OSError:
                pass

        if total_rule_bytes > 20_000:
            items.append(CostAdvisory(
                harness="cursor",
                severity="medium",
                category="context",
                issue=f"Cursor rules total {total_rule_bytes // 1024}KB — injected into every request context",
                recommendation="Split large rules into scoped .mdc files with glob filters to reduce per-request context",
                estimated_savings="~20–40% context token reduction per request",
                current_value=f"{total_rule_bytes // 1024}KB in {len(rule_files)} files",
            ))
        return items, True

    def _analyze_mcp_overhead(self) -> list[CostAdvisory]:
        """Flag MCP servers that add schema tokens without being widely used."""
        items: list[CostAdvisory] = []
        claude_json = self.cc_home / ".claude.json"
        if not claude_json.exists():
            return items
        try:
            data = json.loads(claude_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return items

        # Global MCP servers vs per-project — global ones add tokens to every session
        global_mcp = data.get("mcpServers", {})
        if len(global_mcp) > 5:
            large_schemas = [
                name for name, cfg in global_mcp.items()
                if isinstance(cfg, dict) and len(cfg.get("args", [])) > 3
            ]
            if large_schemas:
                items.append(CostAdvisory(
                    harness="claude-code",
                    severity="low",
                    category="mcp",
                    issue=f"MCP servers with large argument lists loaded globally: {', '.join(large_schemas[:3])}",
                    recommendation="Move project-specific MCP servers to per-project config in .claude.json",
                    estimated_savings="~3–8% context token reduction per session",
                    current_value=f"{len(large_schemas)} servers with large schemas",
                ))
        return items

    def _analyze_context_budget(self) -> list[CostAdvisory]:
        """Check CLAUDE.md size for context budget issues."""
        items: list[CostAdvisory] = []
        claude_md = self.project_dir / "CLAUDE.md"
        if not claude_md.exists():
            return items
        try:
            size = claude_md.stat().st_size
        except OSError:
            return items

        if size > 50_000:
            items.append(CostAdvisory(
                harness="claude-code",
                severity="high",
                category="context",
                issue=f"CLAUDE.md is {size // 1024}KB — injects large context into every session",
                recommendation="Use /sync-lint to find redundant rules; /sync-token-estimate to see per-harness cost",
                estimated_savings="~15–40% context cost depending on rule pruning",
                current_value=f"{size // 1024}KB",
            ))
        elif size > 20_000:
            items.append(CostAdvisory(
                harness="claude-code",
                severity="medium",
                category="context",
                issue=f"CLAUDE.md is {size // 1024}KB — moderately large context file",
                recommendation="Review for redundant rules with /sync-lint; consider splitting into scoped sections",
                estimated_savings="~5–20% context cost reduction",
                current_value=f"{size // 1024}KB",
            ))
        return items

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _suggest_cheaper_model(model: str) -> str:
        """Suggest a cheaper model in the same family."""
        model_lower = model.lower()
        if "opus" in model_lower:
            return "claude-sonnet-4-6 (5x cheaper, ~90% capability)"
        if "gemini-1.5-pro" in model_lower or "gemini-exp" in model_lower:
            return "gemini-2.0-flash (~97% cheaper per token)"
        if "gpt-4o\b" in model_lower or model_lower in ("gpt-4o", "o1"):
            return "gpt-4o-mini (~16x cheaper per input token)"
        return "a mid-tier model variant"

    # ── Report formatting ──────────────────────────────────────────────────

    def format_report(self, report: CostReport) -> str:
        """Return a human-readable cost optimization report."""
        lines = [
            "Cross-Harness Cost Optimization Report",
            "=" * 45,
            f"Detected harnesses: {', '.join(report.detected_harnesses) or 'none'}",
            f"Advisories: {report.total_high} high  {report.total_medium} medium  {report.total_low} low",
            "",
        ]

        severity_labels = {"high": "🔴 HIGH", "medium": "🟡 MEDIUM", "low": "🟢 LOW"}
        for adv in report.advisories:
            label = severity_labels.get(adv.severity, adv.severity.upper())
            lines.append(f"{label}  [{adv.harness}] {adv.issue}")
            lines.append(f"  → {adv.recommendation}")
            lines.append(f"  Estimated savings: {adv.estimated_savings}")
            if adv.current_value:
                lines.append(f"  Current value: {adv.current_value}")
            lines.append("")

        if not report.advisories:
            lines.append("No cost optimization opportunities found. Configuration looks efficient!")

        return "\n".join(lines)

    def format_json(self, report: CostReport) -> str:
        """Return report as JSON for programmatic use."""
        return json.dumps({
            "detected_harnesses": report.detected_harnesses,
            "summary": {
                "high": report.total_high,
                "medium": report.total_medium,
                "low": report.total_low,
            },
            "advisories": [
                {
                    "harness": a.harness,
                    "severity": a.severity,
                    "category": a.category,
                    "issue": a.issue,
                    "recommendation": a.recommendation,
                    "estimated_savings": a.estimated_savings,
                    "current_value": a.current_value,
                }
                for a in report.advisories
            ],
        }, indent=2)
