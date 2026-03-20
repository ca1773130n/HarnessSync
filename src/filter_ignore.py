from __future__ import annotations

"""Harnessignore file support and context-aware sync triggers.

Provides:
- .harnessignore file parsing and application for excluding specific
  rules, skills, MCPs, and agents from specific targets
- SyncTriggerRule and SyncTriggerMatcher for context-aware sync triggers
  that fire only when specific files or sections change
"""

import fnmatch
import re
from dataclasses import dataclass, field as dc_field


# ---------------------------------------------------------------------------
# .harnessignore file support (item 27)
# ---------------------------------------------------------------------------
#
# A .harnessignore file in the project root (or ~/.harnesssync/.harnessignore
# for global rules) lets users exclude specific rules, skills, MCPs, and
# agents from specific targets without polluting CLAUDE.md with tags.
#
# File format -- one directive per line, blank lines and # comments ignored:
#
#   # Exclude the work-slack MCP from all targets except codex
#   mcp:work-slack-server  skip=gemini,cursor,aider,windsurf
#
#   # Exclude a skill from a target that doesn't support it well
#   skill:experimental-debugger  skip=aider,windsurf
#
#   # Exclude a CLAUDE.md section heading from a specific target
#   rule:## Database Guidelines  skip=codex
#
#   # Exclude an agent definition from all targets
#   agent:code-reviewer  skip=all
#
# Supported item types: rule, skill, agent, command, mcp
# Supported modifiers:  skip=<comma-separated targets or "all">
#                       only=<comma-separated targets>
#
# ---------------------------------------------------------------------------

_IGNORE_COMMENT_RE = re.compile(r"\s*#.*$")


def _parse_harnessignore_line(line: str) -> dict | None:
    """Parse a single .harnessignore directive.

    Returns a dict with keys: item_type, item_name, mode ("skip"|"only"),
    targets (frozenset of target names, or frozenset() meaning "all targets").
    Returns None for blank/comment lines or unrecognised formats.
    """
    line = _IGNORE_COMMENT_RE.sub("", line).strip()
    if not line:
        return None

    parts = line.split(None, 1)
    if len(parts) < 2:
        return None

    type_name_part = parts[0]
    modifier_part = parts[1].strip()

    if ":" not in type_name_part:
        return None

    item_type, _, item_name = type_name_part.partition(":")
    item_type = item_type.lower()
    if item_type not in ("rule", "skill", "agent", "command", "mcp"):
        return None

    mode = "skip"
    targets_raw = ""

    if modifier_part.lower().startswith("skip="):
        mode = "skip"
        targets_raw = modifier_part[5:].strip()
    elif modifier_part.lower().startswith("only="):
        mode = "only"
        targets_raw = modifier_part[5:].strip()
    else:
        return None

    if targets_raw.lower() == "all":
        targets: frozenset[str] = frozenset()  # empty = all targets
    else:
        targets = frozenset(t.strip() for t in targets_raw.split(",") if t.strip())

    return {
        "item_type": item_type,
        "item_name": item_name,
        "mode": mode,
        "targets": targets,
    }


def load_harnessignore(project_dir: "Path | None" = None) -> list[dict]:
    """Load .harnessignore rules from project and global config.

    Searches in order:
    1. ~/.harnesssync/.harnessignore  (global)
    2. <project_dir>/.harnessignore   (project, takes precedence)

    Args:
        project_dir: Project root directory. None means global rules only.

    Returns:
        List of parsed ignore rule dicts (see _parse_harnessignore_line).
    """
    import pathlib

    rules: list[dict] = []
    candidates: list[pathlib.Path] = []

    global_path = pathlib.Path.home() / ".harnesssync" / ".harnessignore"
    if global_path.is_file():
        candidates.append(global_path)

    if project_dir is not None:
        project_path = pathlib.Path(project_dir) / ".harnessignore"
        if project_path.is_file():
            candidates.append(project_path)

    for path in candidates:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw_line in text.splitlines():
            parsed = _parse_harnessignore_line(raw_line)
            if parsed is not None:
                rules.append(parsed)

    return rules


def apply_harnessignore(
    items: dict,
    item_type: str,
    target: str,
    rules: list[dict],
) -> dict:
    """Filter an items dict using .harnessignore rules.

    Args:
        items: Dict mapping item name -> item data (skills, agents, MCPs, etc.)
        item_type: One of "skill", "agent", "command", "mcp", "rule".
        target: The target harness being synced (e.g. "codex").
        rules: List of parsed ignore rules from load_harnessignore().

    Returns:
        Filtered dict with excluded items removed.
    """
    if not rules:
        return items

    result = {}
    for name, data in items.items():
        excluded = False
        for rule in rules:
            if rule["item_type"] != item_type:
                continue
            rule_name = rule["item_name"]
            # Match by exact name or prefix
            if rule_name != name and not name.startswith(rule_name):
                continue

            rule_targets = rule["targets"]
            all_targets = len(rule_targets) == 0  # empty frozenset means "all"

            if rule["mode"] == "skip":
                if all_targets or target in rule_targets:
                    excluded = True
                    break
            elif rule["mode"] == "only":
                if not all_targets and target not in rule_targets:
                    excluded = True
                    break

        if not excluded:
            result[name] = data

    return result


# ---------------------------------------------------------------------------
# Item 7 -- Context-Aware Sync Triggers
# ---------------------------------------------------------------------------
#
# Trigger rules let users define WHAT causes a sync to a specific target.
# Instead of syncing everything on every config change, triggers fire only
# when specific files or sections change.
#
# Trigger rule format (stored in .harness-sync/sync-triggers.json):
#
#   [
#     {
#       "target": "codex",
#       "watch_paths": ["CLAUDE.md"],
#       "watch_sections": [],
#       "description": "Only sync to Codex when CLAUDE.md changes"
#     },
#     {
#       "target": "all",
#       "watch_paths": [".claude/skills/"],
#       "watch_sections": [],
#       "description": "Sync all targets when any skill changes"
#     }
#   ]
#
# ``watch_paths`` uses glob patterns relative to the project root.
# ``watch_sections`` matches section names from CLAUDE.md (e.g. "rules").
# ``target`` can be a harness name or "all" to match all targets.


@dataclass
class SyncTriggerRule:
    """A trigger rule that activates sync for specific targets when files change.

    Attributes:
        target: Harness name to sync, or "all" for all targets.
        watch_paths: Glob patterns (relative to project root) to watch.
        watch_sections: Section names (e.g. "rules", "skills") that trigger sync.
        description: Human-readable description of the trigger.
    """

    target: str
    watch_paths: list[str] = dc_field(default_factory=list)
    watch_sections: list[str] = dc_field(default_factory=list)
    description: str = ""


class SyncTriggerMatcher:
    """Determines which targets should sync based on which files changed.

    Reads trigger rules from ``.harness-sync/sync-triggers.json`` and
    matches them against the set of changed files or sections.

    Usage::

        matcher = SyncTriggerMatcher(project_dir)
        targets_to_sync = matcher.targets_for_changes(
            changed_files=["CLAUDE.md", ".claude/skills/my-skill/SKILL.md"],
            changed_sections=["rules"],
            all_targets=["codex", "gemini", "opencode"],
        )
    """

    _TRIGGERS_FILE = ".harness-sync/sync-triggers.json"

    def __init__(self, project_dir=None) -> None:
        import pathlib
        self.project_dir = project_dir or pathlib.Path.cwd()
        self._triggers_path = self.project_dir / self._TRIGGERS_FILE

    def load_rules(self) -> list[SyncTriggerRule]:
        """Load trigger rules from the project's triggers config file.

        Returns:
            List of SyncTriggerRule. Empty list if no config file exists.
        """
        import json
        if not self._triggers_path.exists():
            return []
        try:
            data = json.loads(self._triggers_path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return []
            rules = []
            for item in data:
                if not isinstance(item, dict):
                    continue
                rules.append(SyncTriggerRule(
                    target=item.get("target", "all"),
                    watch_paths=item.get("watch_paths", []),
                    watch_sections=item.get("watch_sections", []),
                    description=item.get("description", ""),
                ))
            return rules
        except (OSError, ValueError):
            return []

    def save_rules(self, rules: list[SyncTriggerRule]) -> None:
        """Persist trigger rules to the project config file.

        Args:
            rules: Rules to save.
        """
        import json
        self._triggers_path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "target": r.target,
                "watch_paths": r.watch_paths,
                "watch_sections": r.watch_sections,
                "description": r.description,
            }
            for r in rules
        ]
        self._triggers_path.write_text(
            json.dumps(data, indent=2), encoding="utf-8"
        )

    def _matches_file(self, pattern: str, changed_files: list[str]) -> bool:
        """Return True if any changed file matches the pattern."""
        import os
        for changed in changed_files:
            if fnmatch.fnmatch(changed, pattern):
                return True
            # Also match if pattern is a directory prefix
            if pattern.endswith("/") and changed.startswith(pattern):
                return True
            # Match basename
            if fnmatch.fnmatch(os.path.basename(changed), pattern):
                return True
        return False

    def targets_for_changes(
        self,
        changed_files: list[str],
        changed_sections: list[str],
        all_targets: list[str],
    ) -> list[str]:
        """Return which targets should receive a sync given the changed items.

        If no trigger rules are configured, returns *all_targets* (default
        behaviour: sync everything on every change).

        If trigger rules ARE configured, returns only the targets that have
        a matching rule for the changed files/sections.

        Args:
            changed_files: List of changed file paths (relative to project root).
            changed_sections: List of changed section names (e.g. ["rules"]).
            all_targets: All configured sync targets.

        Returns:
            List of target names that should receive sync updates.
        """
        rules = self.load_rules()
        if not rules:
            return list(all_targets)

        triggered: set[str] = set()

        for rule in rules:
            file_match = any(
                self._matches_file(pat, changed_files)
                for pat in rule.watch_paths
            )
            section_match = any(
                sec in changed_sections
                for sec in rule.watch_sections
            )

            if file_match or section_match:
                if rule.target == "all":
                    triggered.update(all_targets)
                elif rule.target in all_targets:
                    triggered.add(rule.target)

        return [t for t in all_targets if t in triggered]

    def explain(
        self,
        changed_files: list[str],
        changed_sections: list[str],
        all_targets: list[str],
    ) -> str:
        """Return a human-readable explanation of which rules fired.

        Args:
            changed_files: Changed file paths.
            changed_sections: Changed section names.
            all_targets: All configured targets.

        Returns:
            Multi-line explanation string.
        """
        rules = self.load_rules()
        if not rules:
            return (
                "No trigger rules configured — syncing all targets by default.\n"
                "Add rules to .harness-sync/sync-triggers.json to control per-target sync."
            )

        lines = [
            "Sync Trigger Analysis",
            "=" * 50,
            f"Changed files:    {', '.join(changed_files) or '(none)'}",
            f"Changed sections: {', '.join(changed_sections) or '(none)'}",
            "",
            f"Rules evaluated ({len(rules)}):",
        ]

        for i, rule in enumerate(rules, 1):
            file_match = any(
                self._matches_file(pat, changed_files)
                for pat in rule.watch_paths
            )
            section_match = any(
                sec in changed_sections
                for sec in rule.watch_sections
            )
            fired = file_match or section_match
            status = "FIRED" if fired else "skipped"
            target_label = rule.target if rule.target != "all" else "all targets"
            lines.append(
                f"  {i}. {status}  -> {target_label}  "
                f"({rule.description or 'no description'})"
            )
            if fired:
                if file_match:
                    lines.append(f"     File match: {rule.watch_paths}")
                if section_match:
                    lines.append(f"     Section match: {rule.watch_sections}")

        triggered = self.targets_for_changes(changed_files, changed_sections, all_targets)
        lines.append("")
        if triggered:
            lines.append(f"Targets that will sync: {', '.join(triggered)}")
            skipped = [t for t in all_targets if t not in triggered]
            if skipped:
                lines.append(f"Targets skipped:        {', '.join(skipped)}")
        else:
            lines.append("No triggers fired — no targets will sync.")

        return "\n".join(lines)
