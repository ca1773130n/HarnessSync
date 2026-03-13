from __future__ import annotations

"""Dead config detector for HarnessSync.

Analyzes Claude Code config and flags:
1. Rules, skills, agents, commands, and MCP servers in Claude Code that have
   no active sync target (i.e., all targets skip or don't support them).
2. Config artifacts in target harnesses that have no corresponding source in
   Claude Code (orphaned files left from previous syncs).
3. Skills, agents, and commands that haven't been invoked in N days across
   any harness (usage-based dead config detection).

Helps users clean up config debt they didn't know they had.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


# Usage log stored at ~/.harnesssync/usage_log.json
# Format: {item_key: {"last_used": float_timestamp, "use_count": int, "harness": str}}
# item_key: "skill:<name>", "agent:<name>", "command:<name>", "rule:<path>"
_USAGE_LOG_PATH = Path.home() / ".harnesssync" / "usage_log.json"

# Default staleness threshold in days
_DEFAULT_STALE_DAYS = 30


class UsageTracker:
    """Track and query invocation history for skills, agents, and commands.

    Usage data is persisted to ~/.harnesssync/usage_log.json.
    Each record stores the last-used UNIX timestamp, total use count,
    and which harness last invoked the item.

    Usage::

        tracker = UsageTracker()
        tracker.record("skill", "commit", harness="gemini")
        stale = tracker.find_stale(days=30)
    """

    def __init__(self, log_path: Path | None = None):
        self._path = log_path or _USAGE_LOG_PATH

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict[str, dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _key(self, category: str, name: str) -> str:
        return f"{category}:{name}"

    def record(self, category: str, name: str, harness: str = "") -> None:
        """Record an invocation of a skill, agent, command, or rule.

        Args:
            category: "skill" | "agent" | "command" | "rule"
            name:     Item name (e.g. skill directory name, agent stem).
            harness:  Which harness invoked it (e.g. "gemini", "cursor").
        """
        data = self._load()
        key = self._key(category, name)
        existing = data.get(key, {"use_count": 0})
        data[key] = {
            "last_used": time.time(),
            "use_count": existing.get("use_count", 0) + 1,
            "harness": harness,
        }
        self._save(data)

    def last_used(self, category: str, name: str) -> float | None:
        """Return the last-used timestamp for an item, or None if never used.

        Args:
            category: "skill" | "agent" | "command" | "rule"
            name:     Item name.

        Returns:
            UNIX timestamp float or None.
        """
        data = self._load()
        entry = data.get(self._key(category, name))
        return entry["last_used"] if entry else None

    def use_count(self, category: str, name: str) -> int:
        """Return how many times an item has been invoked (0 if never)."""
        data = self._load()
        entry = data.get(self._key(category, name))
        return entry.get("use_count", 0) if entry else 0

    def find_stale(
        self,
        names: dict[str, list[str]],
        days: int = _DEFAULT_STALE_DAYS,
    ) -> list[dict]:
        """Find items that haven't been used in the last N days.

        Args:
            names: Dict mapping category -> list of item names.
                   E.g. {"skill": ["commit", "debug"], "agent": ["reviewer"]}
            days:  Staleness threshold in days (default 30).

        Returns:
            List of dicts with keys: category, name, last_used_days_ago (None=never),
            use_count, harness.
        """
        data = self._load()
        cutoff = time.time() - days * 86400
        stale = []

        for category, item_names in names.items():
            for name in item_names:
                key = self._key(category, name)
                entry = data.get(key)
                if entry is None:
                    # Never used
                    stale.append({
                        "category": category,
                        "name": name,
                        "last_used_days_ago": None,
                        "use_count": 0,
                        "harness": "",
                    })
                elif entry.get("last_used", 0) < cutoff:
                    days_ago = int((time.time() - entry["last_used"]) / 86400)
                    stale.append({
                        "category": category,
                        "name": name,
                        "last_used_days_ago": days_ago,
                        "use_count": entry.get("use_count", 0),
                        "harness": entry.get("harness", ""),
                    })

        return stale

    def format_stale_report(
        self,
        stale_items: list[dict],
        days: int = _DEFAULT_STALE_DAYS,
    ) -> str:
        """Format stale items as a human-readable report.

        Args:
            stale_items: Output from find_stale().
            days:        Threshold used (for report header).

        Returns:
            Formatted multi-line string.
        """
        if not stale_items:
            return f"No unused config items found (threshold: {days} days)."

        lines = [
            f"Unused Config Items (not invoked in {days}+ days)",
            "=" * 50,
            "",
        ]
        by_cat: dict[str, list[dict]] = {}
        for item in stale_items:
            by_cat.setdefault(item["category"], []).append(item)

        for cat, items in sorted(by_cat.items()):
            lines.append(f"  {cat.upper()}S ({len(items)}):")
            for it in sorted(items, key=lambda x: (x["last_used_days_ago"] is None, x["name"])):
                if it["last_used_days_ago"] is None:
                    age_str = "never used"
                else:
                    age_str = f"last used {it['last_used_days_ago']}d ago"
                count_str = f", {it['use_count']} total uses" if it["use_count"] else ""
                lines.append(f"    {it['name']:<30} {age_str}{count_str}")
            lines.append("")

        lines.append(
            f"Tip: Remove unused items from ~/.claude/ to reduce config bloat,\n"
            f"     or tag them with <!-- sync:skip --> if intentionally kept."
        )
        return "\n".join(lines)


# Known synced output file patterns per target (relative to project_dir)
_TARGET_OUTPUT_FILES: dict[str, list[str]] = {
    "codex": ["AGENTS.md", ".codex/config.toml"],
    "gemini": ["GEMINI.md", ".gemini/settings.json"],
    "opencode": ["OPENCODE.md", ".opencode/settings.json"],
    "cursor": [".cursor/rules/claude-code-rules.mdc", ".cursor/mcp.json"],
    "aider": ["CONVENTIONS.md", ".aider.conf.yml"],
    "windsurf": [".windsurfrules", ".codeium/windsurf/mcp_config.json"],
    "cline": [".clinerules", ".roo/mcp.json"],
    "continue": [".continue/rules/harnesssync.md", ".continue/config.json"],
    "zed": [".zed/system-prompt.md", ".zed/settings.json"],
    "neovim": [".avante/system-prompt.md", ".codecompanion/system-prompt.md", ".avante/mcp.json"],
}

# HarnessSync managed section markers — files with these markers are managed
_HARNESSSYNC_MARKER = "<!-- Managed by HarnessSync -->"


@dataclass
class DeadConfigItem:
    """A config item that is dead (orphaned or unmapped)."""
    kind: str       # "source_no_target" | "target_orphan"
    category: str   # "rules" | "mcp" | "skill" | "agent" | "command" | "file"
    name: str       # Item name or file path
    detail: str     # Human-readable explanation


@dataclass
class DeadConfigReport:
    """Report of dead/orphaned configuration items."""

    source_no_target: list[DeadConfigItem] = field(default_factory=list)
    target_orphans: list[DeadConfigItem] = field(default_factory=list)

    @property
    def total_issues(self) -> int:
        return len(self.source_no_target) + len(self.target_orphans)

    def is_clean(self) -> bool:
        return self.total_issues == 0

    def format(self) -> str:
        """Format the dead config report as human-readable text."""
        if self.is_clean():
            return "Dead Config Detector: No issues found. Config is clean."

        lines = ["## Dead Config Report", ""]

        if self.source_no_target:
            lines.append("### Source items with no active sync target:")
            for item in self.source_no_target:
                lines.append(f"  [{item.category.upper()}] {item.name}")
                lines.append(f"    {item.detail}")
            lines.append("")

        if self.target_orphans:
            lines.append("### Orphaned files in targets (no source in Claude Code):")
            for item in self.target_orphans:
                lines.append(f"  [{item.category.upper()}] {item.name}")
                lines.append(f"    {item.detail}")
            lines.append("")

        lines.append(f"Total issues: {self.total_issues}")
        return "\n".join(lines)


class DeadConfigDetector:
    """Detects dead/orphaned configuration between Claude Code source and sync targets.

    Args:
        project_dir: Project root directory.
        cc_home: Claude Code home directory (defaults to ~/.claude).
    """

    def __init__(self, project_dir: Path, cc_home: Path = None):
        self.project_dir = project_dir
        self.cc_home = cc_home or Path.home() / ".claude"

    def detect(
        self,
        source_data: dict = None,
        active_targets: list[str] = None,
        stale_days: int = _DEFAULT_STALE_DAYS,
    ) -> DeadConfigReport:
        """Run dead config detection.

        Args:
            source_data: Pre-loaded source data dict (from SourceReader.discover_all()).
                         If None, a minimal scan of the project dir is used.
            active_targets: List of active sync targets. If None, all known targets
                            with output files present in project_dir are checked.
            stale_days: Number of days without invocation before an item is
                        considered unused (default: 30). Pass 0 to skip usage check.

        Returns:
            DeadConfigReport with categorized issues.
        """
        report = DeadConfigReport()

        if source_data is None:
            source_data = self._minimal_source_scan()

        if active_targets is None:
            active_targets = self._detect_active_targets()

        # Check 1: Source items with no active target support
        self._check_source_no_target(source_data, active_targets, report)

        # Check 2: Orphaned files in targets
        self._check_target_orphans(active_targets, source_data, report)

        # Check 3: Usage-based stale detection (skills/agents/commands unused for N days)
        if stale_days > 0:
            self._check_stale_by_usage(source_data, stale_days, report)

        return report

    def _check_stale_by_usage(
        self, source_data: dict, stale_days: int, report: "DeadConfigReport"
    ) -> None:
        """Flag skills, agents, and commands that haven't been invoked in stale_days days.

        Uses the HarnessSync usage log (~/.harnesssync/usage_log.json) which is
        updated whenever a skill/agent/command is invoked via any synced harness.
        Items that have never been logged are also reported as unused.

        Args:
            source_data:  Discovered source data dict.
            stale_days:   Days threshold for staleness.
            report:       Report to append items to.
        """
        tracker = UsageTracker()
        to_check: dict[str, list[str]] = {
            "skill": list(source_data.get("skills", {}).keys()),
            "agent": list(source_data.get("agents", {}).keys()),
            "command": list(source_data.get("commands", {}).keys()),
        }

        stale_items = tracker.find_stale(to_check, days=stale_days)
        for item in stale_items:
            if item["last_used_days_ago"] is None:
                detail = (
                    f"{item['category'].capitalize()} '{item['name']}' has never been "
                    f"invoked across any harness (consider removing or tagging <!-- sync:skip -->)"
                )
            else:
                detail = (
                    f"{item['category'].capitalize()} '{item['name']}' last used "
                    f"{item['last_used_days_ago']} days ago (threshold: {stale_days}d). "
                    f"Total uses: {item['use_count']}"
                )
            report.source_no_target.append(DeadConfigItem(
                kind="source_no_target",
                category=item["category"],
                name=item["name"],
                detail=detail,
            ))

    def _minimal_source_scan(self) -> dict:
        """Perform a minimal scan for source data without importing SourceReader."""
        data: dict = {
            "rules": [],
            "skills": {},
            "agents": {},
            "commands": {},
            "mcp_servers": {},
        }

        # Check CLAUDE.md
        claude_md = self.project_dir / "CLAUDE.md"
        if claude_md.is_file() and claude_md.stat().st_size > 0:
            data["rules"] = [{"path": "CLAUDE.md", "content": claude_md.read_text(encoding="utf-8")}]

        # Check .claude/skills/
        skills_dir = self.cc_home / "skills"
        if skills_dir.is_dir():
            for d in skills_dir.iterdir():
                if d.is_dir() and (d / "SKILL.md").is_file():
                    data["skills"][d.name] = d

        # Check .claude/agents/
        agents_dir = self.cc_home / "agents"
        if agents_dir.is_dir():
            for f in agents_dir.iterdir():
                if f.is_file() and f.suffix == ".md":
                    data["agents"][f.stem] = f

        # Check .claude/commands/
        commands_dir = self.cc_home / "commands"
        if commands_dir.is_dir():
            for f in commands_dir.iterdir():
                if f.is_file() and f.suffix == ".md":
                    data["commands"][f.stem] = f

        return data

    def _detect_active_targets(self) -> list[str]:
        """Return targets that appear to have been synced (output files exist)."""
        active = []
        for target, output_files in _TARGET_OUTPUT_FILES.items():
            for rel in output_files:
                p = self.project_dir / rel
                if p.is_file():
                    active.append(target)
                    break
        return active

    def _check_source_no_target(
        self, source_data: dict, active_targets: list[str], report: DeadConfigReport
    ) -> None:
        """Flag source items that have no mapping in any active target."""
        # MCP servers: check if any active target writes MCP config
        mcp_servers = source_data.get("mcp_servers", source_data.get("mcp", {}))
        if mcp_servers and active_targets:
            # Targets that support MCP output
            mcp_capable = {"codex", "gemini", "opencode", "cursor", "cline", "continue", "zed", "neovim"}
            if not any(t in mcp_capable for t in active_targets):
                for server_name in mcp_servers:
                    report.source_no_target.append(DeadConfigItem(
                        kind="source_no_target",
                        category="mcp",
                        name=server_name,
                        detail="MCP server has no active target that supports MCP sync",
                    ))

        # Skills: check if any active target syncs skills
        skills = source_data.get("skills", {})
        if skills and active_targets:
            skill_capable = {"codex", "gemini", "opencode", "cursor", "cline", "continue", "zed", "neovim"}
            if not any(t in skill_capable for t in active_targets):
                for skill_name in skills:
                    report.source_no_target.append(DeadConfigItem(
                        kind="source_no_target",
                        category="skill",
                        name=skill_name,
                        detail="Skill has no active target that syncs skills",
                    ))

        # Rules: warn if no active targets at all
        rules = source_data.get("rules", [])
        if rules and not active_targets:
            report.source_no_target.append(DeadConfigItem(
                kind="source_no_target",
                category="rules",
                name="CLAUDE.md",
                detail="Rules exist but no sync targets have been configured",
            ))

    def _check_target_orphans(
        self, active_targets: list[str], source_data: dict, report: DeadConfigReport
    ) -> None:
        """Flag target output files that are managed by HarnessSync but have no source."""
        has_rules = bool(source_data.get("rules", []))

        for target in active_targets:
            output_files = _TARGET_OUTPUT_FILES.get(target, [])
            for rel in output_files:
                p = self.project_dir / rel
                if not p.is_file():
                    continue
                try:
                    content = p.read_text(encoding="utf-8")
                except OSError:
                    continue

                # Only flag files that HarnessSync manages
                if _HARNESSSYNC_MARKER not in content:
                    continue

                # If no source rules, any managed rules file is an orphan
                if not has_rules and ("rules" in rel.lower() or rel.endswith(".md")):
                    report.target_orphans.append(DeadConfigItem(
                        kind="target_orphan",
                        category="file",
                        name=f"{target}:{rel}",
                        detail=(
                            f"HarnessSync-managed file at {rel} has no source "
                            f"CLAUDE.md or rules in Claude Code"
                        ),
                    ))
