from __future__ import annotations

"""Feature Gap Issue Creator — auto-draft GitHub issues for harness feature gaps.

Also includes GapUpvoteTracker (item 29): a local store that lets users
"upvote" capability gaps they care about. The tracker periodically checks
whether a target harness has added support for previously-tracked gaps.

Usage::

    tracker = GapUpvoteTracker()
    tracker.upvote("codex", "skills")        # Express interest in this gap
    tracker.upvote("codex", "skills")        # Subsequent upvote increments count
    open_gaps = tracker.list_gaps()          # List all tracked gaps with vote counts
    resolved = tracker.check_resolved()      # Returns gaps that may be resolved


When HarnessSync detects a Claude Code feature with no equivalent in a target
harness, this module drafts a GitHub issue in that harness's upstream repo
requesting the feature. Turns passive gap detection into upstream pressure
that benefits the whole ecosystem.

Two modes:
  - draft_only: Generate the issue body as text (no API call). Safe default.
  - submit:     POST to GitHub Issues API (requires token + explicit opt-in).

Usage::

    creator = FeatureGapIssueCreator(github_token="ghp_...")
    gap = FeatureGap(
        harness="codex",
        feature="skills",
        description="Claude Code skills (slash-command prompts) have no equivalent in Codex CLI.",
        impact="high",
    )
    draft = creator.draft(gap)
    print(draft.body)

    # To actually open the issue (requires token):
    result = creator.submit(gap, repo="openai/openai-codex")
    print(result.url)
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field


# ──────────────────────────────────────────────────────────────────────────────
# Known upstream repositories per harness
# ──────────────────────────────────────────────────────────────────────────────

_HARNESS_REPOS: dict[str, str] = {
    "codex":    "openai/openai-codex",
    "gemini":   "google-gemini/gemini-cli",
    "opencode": "opencode-ai/opencode",
    "cursor":   "getcursor/cursor",
    "aider":    "paul-gauthier/aider",
    "windsurf": "codeium/windsurf",
    "cline":    "cline/cline",
    "continue": "continuedev/continue",
    "zed":      "zed-industries/zed",
}

# GitHub API endpoint
_GH_API = "https://api.github.com"

# Issue labels to apply when available
_DEFAULT_LABELS = ["feature request", "enhancement"]

# Request timeout seconds
_TIMEOUT = 10


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class FeatureGap:
    """A Claude Code feature that is missing from a target harness.

    Attributes:
        harness: Target harness name (e.g. "codex").
        feature: Short feature category (e.g. "skills", "mcp", "agents").
        description: Human-readable description of the gap.
        impact: "high" | "medium" | "low" — how much users are affected.
        workaround: Optional workaround text included in the issue body.
        harnesssync_version: HarnessSync version string for context.
    """

    harness: str
    feature: str
    description: str
    impact: str = "medium"
    workaround: str = ""
    harnesssync_version: str = ""


@dataclass
class IssueDraft:
    """A drafted GitHub issue ready for review or submission.

    Attributes:
        gap: The FeatureGap this draft addresses.
        title: Suggested issue title.
        body: Full Markdown issue body.
        repo: Upstream GitHub repo ("owner/repo").
        labels: Suggested labels.
    """

    gap: FeatureGap
    title: str
    body: str
    repo: str
    labels: list[str] = field(default_factory=list)

    def format(self) -> str:
        """Return a formatted preview for terminal display."""
        lines = [
            f"Issue Draft — {self.repo}",
            "=" * 60,
            f"Title:  {self.title}",
            f"Labels: {', '.join(self.labels) or '(none)'}",
            "",
            "Body:",
            "-" * 40,
            self.body,
            "-" * 40,
        ]
        return "\n".join(lines)


@dataclass
class SubmitResult:
    """Result of submitting a GitHub issue."""

    success: bool
    url: str = ""
    issue_number: int = 0
    error: str = ""

    def format(self) -> str:
        if self.success:
            return f"Issue #{self.issue_number} opened: {self.url}"
        return f"Submit failed: {self.error}"


# ──────────────────────────────────────────────────────────────────────────────
# Creator
# ──────────────────────────────────────────────────────────────────────────────

class FeatureGapIssueCreator:
    """Draft and optionally submit GitHub issues for harness feature gaps.

    Args:
        github_token: GitHub personal access token with repo scope.
                      Required only for submit(); draft() works without it.
    """

    def __init__(self, github_token: str = ""):
        self._token = github_token

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def draft(self, gap: FeatureGap, repo: str | None = None) -> IssueDraft:
        """Build an IssueDraft for a FeatureGap without making any API calls.

        Args:
            gap: The feature gap to document.
            repo: Override the default upstream repo for the harness.

        Returns:
            IssueDraft ready for review.
        """
        target_repo = repo or _HARNESS_REPOS.get(gap.harness, "")
        title = _build_title(gap)
        body = _build_body(gap)
        labels = _suggest_labels(gap)
        return IssueDraft(gap=gap, title=title, body=body, repo=target_repo, labels=labels)

    def draft_from_comparison_report(
        self,
        report_data: dict,
        min_impact: str = "medium",
    ) -> list[IssueDraft]:
        """Generate issue drafts from a HarnessConfigComparison report dict.

        Iterates over the per-feature support matrix and creates a draft for
        every (harness, feature) pair where support is "none".

        Args:
            report_data: Dict from HarnessConfigComparison.compare() containing
                         a "feature_rows" list with target support levels.
            min_impact: Minimum impact level to include ("high" | "medium" | "low").

        Returns:
            List of IssueDraft objects.
        """
        _IMPACT_ORDER = {"high": 3, "medium": 2, "low": 1}
        min_order = _IMPACT_ORDER.get(min_impact, 2)

        drafts: list[IssueDraft] = []
        feature_rows = report_data.get("feature_rows", [])
        for row in feature_rows:
            feature = row.get("feature", "")
            impact = _feature_impact(feature)
            if _IMPACT_ORDER.get(impact, 0) < min_order:
                continue
            for target, support in row.get("target_support", {}).items():
                if support == "none":
                    gap = FeatureGap(
                        harness=target,
                        feature=feature,
                        description=_default_description(feature, target),
                        impact=impact,
                    )
                    drafts.append(self.draft(gap))
        return drafts

    def submit(
        self,
        gap_or_draft: "FeatureGap | IssueDraft",
        repo: str | None = None,
    ) -> SubmitResult:
        """Submit a GitHub issue for a feature gap.

        Requires a valid GitHub token (set at construction time).

        Args:
            gap_or_draft: FeatureGap or pre-built IssueDraft to submit.
            repo: GitHub "owner/repo". Uses harness default if not provided.
                  Required when gap_or_draft is a FeatureGap with an unknown harness.

        Returns:
            SubmitResult with issue URL on success.
        """
        if not self._token:
            return SubmitResult(
                success=False,
                error="No GitHub token configured. Pass github_token= to FeatureGapIssueCreator.",
            )

        if isinstance(gap_or_draft, IssueDraft):
            draft = gap_or_draft
            if repo:
                draft = IssueDraft(
                    gap=draft.gap,
                    title=draft.title,
                    body=draft.body,
                    repo=repo,
                    labels=draft.labels,
                )
        else:
            draft = self.draft(gap_or_draft, repo=repo)

        if not draft.repo:
            return SubmitResult(
                success=False,
                error=f"No upstream repo known for harness '{draft.gap.harness}'. Pass repo= explicitly.",
            )

        return self._post_issue(draft)

    def format_drafts_report(self, drafts: list[IssueDraft]) -> str:
        """Format a list of drafts as a summary table.

        Args:
            drafts: List from draft_from_comparison_report().

        Returns:
            Multi-line summary string.
        """
        if not drafts:
            return "No feature gaps found that warrant upstream issues."
        lines = [f"Feature Gap Issues ({len(drafts)} drafts)\n{'=' * 50}"]
        for d in drafts:
            impact_tag = f"[{d.gap.impact.upper()}]"
            lines.append(
                f"  {impact_tag:<8} {d.gap.harness:<12} {d.gap.feature:<14} → {d.repo}"
            )
        lines += [
            "",
            "Review each draft with creator.draft(gap).format() before submitting.",
            "Submit with creator.submit(draft) (requires GitHub token).",
        ]
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _post_issue(self, draft: IssueDraft) -> SubmitResult:
        """POST the draft to GitHub Issues API."""
        url = f"{_GH_API}/repos/{draft.repo}/issues"
        payload: dict = {"title": draft.title, "body": draft.body}
        if draft.labels:
            payload["labels"] = draft.labels

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                return SubmitResult(
                    success=True,
                    url=resp_data.get("html_url", ""),
                    issue_number=resp_data.get("number", 0),
                )
        except urllib.error.HTTPError as exc:
            try:
                msg = json.loads(exc.read().decode("utf-8")).get("message", str(exc))
            except Exception:
                msg = str(exc)
            return SubmitResult(success=False, error=f"HTTP {exc.code}: {msg}")
        except Exception as exc:
            return SubmitResult(success=False, error=str(exc))


# ──────────────────────────────────────────────────────────────────────────────
# Issue content builders
# ──────────────────────────────────────────────────────────────────────────────

def _build_title(gap: FeatureGap) -> str:
    """Build a concise issue title."""
    feature_label = gap.feature.replace("_", " ").title()
    return f"Feature request: Support for {feature_label} (HarnessSync compatibility)"


def _build_body(gap: FeatureGap) -> str:
    """Build a complete Markdown issue body."""
    sections: list[str] = []

    sections.append("## Summary\n")
    sections.append(gap.description.strip())
    sections.append("")

    sections.append("## Context\n")
    sections.append(
        f"[HarnessSync](https://github.com/harnesssync/harnesssync) synchronises "
        f"Claude Code configurations to multiple AI coding harnesses. When syncing "
        f"to **{gap.harness}**, the `{gap.feature}` feature cannot be represented "
        f"because no equivalent mechanism exists in this harness.\n"
    )
    if gap.harnesssync_version:
        sections.append(f"Detected with HarnessSync v{gap.harnesssync_version}.\n")

    sections.append("## Impact\n")
    impact_descriptions = {
        "high":   "Many users are affected. This gap causes meaningful behavior differences when switching from Claude Code.",
        "medium": "Some users are affected. Users who rely on this feature see degraded behavior in this harness.",
        "low":    "Niche impact. Affects users who heavily rely on this specific Claude Code feature.",
    }
    sections.append(f"**{gap.impact.upper()}** — {impact_descriptions.get(gap.impact, '')}\n")

    if gap.workaround:
        sections.append("## Workaround\n")
        sections.append(gap.workaround.strip())
        sections.append("")

    sections.append("## Proposed Solution\n")
    sections.append(
        f"Implement a native `{gap.feature}` mechanism in {gap.harness} that "
        f"HarnessSync (and users directly) can target. "
        f"See the [HarnessSync capability matrix](https://github.com/harnesssync/harnesssync#capability-matrix) "
        f"for the full feature set that would benefit from parity.\n"
    )

    sections.append("---")
    sections.append(
        "*This issue was drafted by [HarnessSync](https://github.com/harnesssync/harnesssync), "
        "a tool that syncs Claude Code configurations across AI coding harnesses.*"
    )

    return "\n".join(sections)


def _suggest_labels(gap: FeatureGap) -> list[str]:
    """Suggest GitHub issue labels based on the gap."""
    labels = ["feature request"]
    if gap.impact == "high":
        labels.append("enhancement")
    feature_label_map = {
        "skills":   "skills",
        "agents":   "agents",
        "mcp":      "mcp",
        "commands": "commands",
        "settings": "settings",
    }
    if gap.feature in feature_label_map:
        labels.append(feature_label_map[gap.feature])
    return labels


def _feature_impact(feature: str) -> str:
    """Return default impact level for a feature category."""
    high_impact = {"rules", "mcp", "settings"}
    medium_impact = {"skills", "agents", "commands"}
    if feature in high_impact:
        return "high"
    if feature in medium_impact:
        return "medium"
    return "low"


def _default_description(feature: str, harness: str) -> str:
    """Return a default gap description for a known feature."""
    descriptions = {
        "skills": (
            f"Claude Code skills (slash-command SKILL.md prompts) have no native equivalent in {harness}. "
            "HarnessSync can approximate them by embedding skill content in the rules file, "
            "but this loses slot-based invocation and skill-level sync control."
        ),
        "agents": (
            f"Claude Code sub-agent configurations (AGENT.md files) cannot be represented in {harness}. "
            "Users lose structured multi-agent workflows when switching to this harness."
        ),
        "commands": (
            f"Claude Code custom slash commands (.claude/commands/) have no equivalent in {harness}. "
            "Command shortcuts and structured invocation patterns are lost on sync."
        ),
        "mcp": (
            f"{harness} does not support MCP (Model Context Protocol) natively. "
            "Users lose all MCP-powered tool capabilities when switching to this harness."
        ),
        "settings": (
            f"Claude Code permission settings (allowedTools, approvalMode) cannot be "
            f"mapped to native controls in {harness} and are silently dropped on sync."
        ),
    }
    return descriptions.get(
        feature,
        f"Claude Code's '{feature}' feature has no equivalent in {harness} and is lost during sync.",
    )


# ---------------------------------------------------------------------------
# Item 29 — Capability Gap Upvote Tracker
# ---------------------------------------------------------------------------

_UPVOTE_STORE_PATH = (
    __import__("pathlib").Path.home() / ".harnesssync" / "gap_upvotes.json"
)

# Known support levels per (harness, feature) pair.
# Updated when new harness versions add features.
# "supported" means the gap may now be resolved; None = unknown.
_KNOWN_SUPPORT: dict[tuple[str, str], bool] = {
    ("gemini", "skills"):   True,   # Gemini CLI added native skill support
    ("gemini", "commands"): True,   # Gemini CLI added native command support
    ("codex", "mcp"):       True,   # Codex added MCP support
    ("cursor", "skills"):   False,  # No native skill concept yet
    ("aider", "skills"):    False,  # No native skill concept in Aider
    ("aider", "agents"):    False,  # No agent concept in Aider
    ("windsurf", "agents"): False,  # No agent concept in Windsurf
}


class GapUpvoteTracker:
    """Track user upvotes for capability gaps and detect when gaps are resolved.

    Stores upvote counts in ``~/.harnesssync/gap_upvotes.json``. Each gap
    is keyed by ``<harness>:<feature>``. Upvotes express user interest and
    help prioritize which gaps matter most.

    ``check_resolved()`` compares tracked gaps against a known-support
    database and returns gaps that appear to now be supported in the
    target harness.

    Args:
        store_path: Override the default JSON store path (useful for testing).
    """

    def __init__(self, store_path: __import__("pathlib").Path | None = None) -> None:
        from pathlib import Path
        self._store_path: Path = store_path or _UPVOTE_STORE_PATH

    # ── Storage helpers ───────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not self._store_path.exists():
            return {}
        try:
            import json
            data = json.loads(self._store_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        self._store_path.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def upvote(self, harness: str, feature: str) -> int:
        """Register one upvote for a (harness, feature) capability gap.

        Args:
            harness: Target harness name (e.g. "codex").
            feature: Feature name (e.g. "skills").

        Returns:
            New total upvote count for this gap.
        """
        from datetime import datetime, timezone
        key = f"{harness}:{feature}"
        data = self._load()
        entry = data.get(key, {"harness": harness, "feature": feature, "votes": 0, "first_upvoted": "", "last_upvoted": ""})
        entry["votes"] = entry.get("votes", 0) + 1
        now = datetime.now(tz=timezone.utc).isoformat()
        if not entry.get("first_upvoted"):
            entry["first_upvoted"] = now
        entry["last_upvoted"] = now
        data[key] = entry
        self._save(data)
        return entry["votes"]

    def list_gaps(self, min_votes: int = 0) -> list[dict]:
        """Return all tracked gaps sorted by vote count descending.

        Args:
            min_votes: Filter to gaps with at least this many votes.

        Returns:
            List of dicts with keys: ``harness``, ``feature``, ``votes``,
            ``first_upvoted``, ``last_upvoted``, ``resolved``.
        """
        data = self._load()
        entries = []
        for key, entry in data.items():
            if entry.get("votes", 0) < min_votes:
                continue
            h, f = entry.get("harness", ""), entry.get("feature", "")
            resolved = _KNOWN_SUPPORT.get((h, f), None)
            entries.append({
                "harness": h,
                "feature": f,
                "votes": entry.get("votes", 0),
                "first_upvoted": entry.get("first_upvoted", ""),
                "last_upvoted": entry.get("last_upvoted", ""),
                "resolved": resolved,
            })
        entries.sort(key=lambda e: e["votes"], reverse=True)
        return entries

    def check_resolved(self) -> list[dict]:
        """Return gaps that are now supported in the target harness.

        Compares tracked gaps against the known-support database and
        returns entries where support has been confirmed.

        Returns:
            List of gap dicts (same format as list_gaps()) where
            ``resolved`` is True.
        """
        return [g for g in self.list_gaps() if g["resolved"] is True]

    def format_report(self) -> str:
        """Return a human-readable report of all tracked gaps.

        Returns:
            Multi-line formatted string.
        """
        gaps = self.list_gaps()
        if not gaps:
            return "No capability gaps tracked. Use /sync-gaps to find and upvote gaps."

        lines = [
            "Capability Gap Upvote Tracker",
            "=" * 50,
            "",
            f"  {'Harness':<12} {'Feature':<14} {'Votes':>5}  Status",
            "  " + "-" * 46,
        ]
        for g in gaps:
            resolved = g["resolved"]
            status = "✓ now supported!" if resolved else ("✗ still open" if resolved is False else "? unknown")
            lines.append(
                f"  {g['harness']:<12} {g['feature']:<14} {g['votes']:>5}  {status}"
            )

        resolved_gaps = self.check_resolved()
        if resolved_gaps:
            lines.append("")
            lines.append(
                f"  {len(resolved_gaps)} gap(s) appear resolved — "
                "re-sync to take advantage of new harness support."
            )

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Feature Gap Advisor — actionable workarounds per capability gap (Item 5)
# ---------------------------------------------------------------------------

# Per-(harness, feature) workarounds: specific, actionable steps users can take
# to partially recover missing capabilities.  Goes beyond just listing gaps.
_WORKAROUNDS: dict[tuple[str, str], list[str]] = {
    ("aider", "skills"): [
        "Create a skills/ directory with .md files alongside your project.",
        "Pass skill files as read-only context: `aider --read skills/my-skill.md`.",
        "Alias frequent skill invocations in a Makefile: `make fix-types` → `aider --read skills/fix-types.md`.",
    ],
    ("aider", "mcp"): [
        "Run MCP tools as standalone CLI processes and pipe their output to Aider.",
        "Use aider's `--exec` flag to run a helper script before each session.",
        "Store MCP output in a temp file and add it via `--read` at session start.",
    ],
    ("aider", "agents"): [
        "Use Aider's `--architect` mode as a lightweight two-agent pattern.",
        "Chain multiple aider invocations in a shell script to simulate agent handoffs.",
    ],
    ("aider", "commands"): [
        "Define shell aliases or Makefile targets for each common slash command.",
        "Add a `scripts/` directory with one script per command (e.g., `scripts/fix-types.sh`).",
    ],
    ("codex", "skills"): [
        "Embed skill content directly in AGENTS.md under a '## Skills' heading.",
        "Use Codex's `--profile` flag to load project-specific rule subsets.",
    ],
    ("codex", "agents"): [
        "Use Codex's built-in multi-turn conversation to simulate agent handoffs manually.",
        "Split complex tasks into separate AGENTS.md sections gated by task context.",
    ],
    ("cursor", "agents"): [
        "Use Cursor's Composer in 'Long Context' mode as an approximation.",
        "Create separate .cursor/rules/*.mdc files scoped to different workflows.",
    ],
    ("windsurf", "agents"): [
        "Use Windsurf Cascade's multi-step mode for sequential task pipelines.",
        "Create separate workspace flows for different agent roles.",
    ],
    ("windsurf", "mcp"): [
        "Use Windsurf's built-in tool integrations (file system, terminal) as MCP alternatives.",
        "For custom MCP tools: run them as background processes and read their output via context.",
    ],
    ("gemini", "commands"): [
        "Use Gemini CLI's `@file` context injection as an approximation of slash commands.",
        "Create shell aliases: `alias /fix-types='gemini --context skills/fix-types.md'`.",
    ],
    ("cline", "agents"): [
        "Use Cline's task chaining feature in VS Code to approximate multi-agent flows.",
    ],
}

# Generic fallback workarounds by feature category
_GENERIC_WORKAROUNDS: dict[str, list[str]] = {
    "skills": [
        "Embed skill instructions directly in CLAUDE.md/AGENTS.md under a '## Skills' section.",
        "Create a dedicated rules file per skill and load it as additional context.",
    ],
    "agents": [
        "Split agent responsibilities across CLAUDE.md sections with clear headings.",
        "Use sequential task files to hand off context between conceptual agents.",
    ],
    "commands": [
        "Map each command to a shell alias or Makefile target.",
        "Document command invocations in CLAUDE.md so the AI can approximate them.",
    ],
    "mcp": [
        "Run MCP servers as standalone background processes and use their CLI output.",
        "Check if the harness has native equivalents for your specific MCP tools.",
    ],
    "settings": [
        "Document your desired permission model in CLAUDE.md comments for reference.",
        "Use harness-specific config files (.cursorrules, GEMINI.md) for settings approximation.",
    ],
}


@dataclass
class GapAdvice:
    """Actionable advice for a single capability gap."""
    harness: str
    feature: str
    workarounds: list[str]
    # True if specific workarounds exist; False if only generic advice available
    has_specific_advice: bool = False


class FeatureGapAdvisor:
    """Provide actionable workarounds for Claude Code → harness capability gaps.

    Goes beyond gap detection to give users specific, copyable steps to
    recover missing capabilities.  Each piece of advice targets the exact
    (harness, feature) combination rather than generic guidance.

    Usage::

        advisor = FeatureGapAdvisor()
        advice_list = advisor.advise("aider", ["skills", "mcp", "agents"])
        print(advisor.format_advice(advice_list))
    """

    def advise(
        self,
        harness: str,
        features: list[str],
    ) -> list[GapAdvice]:
        """Return workarounds for each (harness, feature) capability gap.

        Args:
            harness: Target harness name (e.g. "aider").
            features: List of feature categories that are missing
                      (e.g. ["skills", "mcp", "agents"]).

        Returns:
            List of GapAdvice objects, one per feature with at least one step.
        """
        result: list[GapAdvice] = []
        h = harness.lower().strip()
        for feature in features:
            f = feature.lower().strip()
            key = (h, f)
            specific = _WORKAROUNDS.get(key)
            if specific:
                result.append(GapAdvice(
                    harness=h,
                    feature=f,
                    workarounds=specific,
                    has_specific_advice=True,
                ))
            else:
                generic = _GENERIC_WORKAROUNDS.get(f, [
                    f"No direct equivalent exists for '{f}' in {h}. "
                    "Consider documenting the capability in your project's CLAUDE.md "
                    "so it remains accessible as human reference even without tool support.",
                ])
                result.append(GapAdvice(
                    harness=h,
                    feature=f,
                    workarounds=generic,
                    has_specific_advice=False,
                ))
        return result

    def format_advice(self, advice_list: list[GapAdvice]) -> str:
        """Render advice as a human-readable report.

        Args:
            advice_list: Output from :meth:`advise`.

        Returns:
            Formatted multi-line string with per-gap workaround steps.
        """
        if not advice_list:
            return "No capability gaps provided. All features appear to be supported."

        lines: list[str] = []
        lines.append("Feature Gap Advisor — Actionable Workarounds")
        lines.append("=" * 55)

        for adv in advice_list:
            qualifier = "specific" if adv.has_specific_advice else "generic"
            lines.append(f"\n  [{adv.harness.upper()}] {adv.feature}  ({qualifier} advice)")
            for i, step in enumerate(adv.workarounds, 1):
                lines.append(f"    {i}. {step}")

        lines.append("")
        lines.append(
            "Use /sync-gaps to see the full gap list or /sync-compare for a matrix view."
        )
        return "\n".join(lines)
