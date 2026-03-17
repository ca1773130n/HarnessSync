from __future__ import annotations

"""Rule Tagging — filter which rules sync where based on category tags.

Users tag rules in CLAUDE.md with inline category markers:

    <!-- #security -->
    - Never commit secrets or API keys.
    - Always validate user input before SQL queries.

    <!-- #style -->
    - Use 4-space indentation in Python, 2-space in JS/TS.

    <!-- #workflow -->
    - Run tests before committing.
    - Use conventional commits format.

    <!-- /#security -->
    <!-- /#style -->

Per-harness tag config in ``.harnesssync/rule_tags.json`` controls which
categories each harness receives:

    {
        "cursor":  {"include_tags": ["security", "style", "workflow"]},
        "aider":   {"include_tags": ["security"]},
        "codex":   {"exclude_tags": ["style"]},
        "gemini":  {}
    }

Omitting a harness (or providing an empty dict) means "pass all tags".
``include_tags`` is an allow-list; ``exclude_tags`` is a deny-list.
If both are set, ``include_tags`` takes precedence.

Rules outside any tag block are always included (untagged = universal).

Usage::

    tagger = RuleTagger(project_dir=Path.cwd())

    # Filter rules content for a specific target
    filtered = tagger.filter_content(rules_content, target="aider")

    # Check if content has any tag markers
    if tagger.has_tags(rules_content):
        ...

    # Get a summary of tags used in content
    tags = tagger.extract_tags(rules_content)
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_CONFIG_FILENAME = "rule_tags.json"
_CONFIG_DIR = ".harnesssync"

# Matches <!-- #tagname --> and <!-- /#tagname -->
_TAG_OPEN_RE = re.compile(
    r"<!--\s*#([a-zA-Z][a-zA-Z0-9_-]*)\s*-->",
    re.IGNORECASE,
)
_TAG_CLOSE_RE = re.compile(
    r"<!--\s*/#([a-zA-Z][a-zA-Z0-9_-]*)\s*-->",
    re.IGNORECASE,
)

# Inline tag on a single line: <!-- tag:#security -->
_INLINE_TAG_RE = re.compile(
    r"<!--\s*tag:#([a-zA-Z][a-zA-Z0-9_-]*)\s*-->",
    re.IGNORECASE,
)


@dataclass
class HarnessTagPolicy:
    """Tag filtering policy for a single harness."""

    include_tags: list[str] = field(default_factory=list)  # allow-list (empty = all)
    exclude_tags: list[str] = field(default_factory=list)  # deny-list

    def allows(self, tag: str) -> bool:
        """Return True if *tag* should be included for this harness."""
        tag_lower = tag.lower()
        if self.include_tags:
            return tag_lower in [t.lower() for t in self.include_tags]
        if self.exclude_tags:
            return tag_lower not in [t.lower() for t in self.exclude_tags]
        return True  # no restrictions

    def is_empty(self) -> bool:
        return not self.include_tags and not self.exclude_tags


@dataclass
class TaggingConfig:
    """Per-harness tag policies parsed from rule_tags.json."""

    policies: dict[str, HarnessTagPolicy] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not self.policies or all(p.is_empty() for p in self.policies.values())

    def policy_for(self, target: str) -> HarnessTagPolicy:
        return self.policies.get(target.lower(), HarnessTagPolicy())


def _load_tagging_config(project_dir: Path) -> TaggingConfig:
    """Load rule_tags.json.  Returns empty config if file absent/invalid."""
    path = project_dir / _CONFIG_DIR / _CONFIG_FILENAME
    if not path.exists():
        return TaggingConfig()

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return TaggingConfig()

    if not isinstance(data, dict):
        return TaggingConfig()

    policies: dict[str, HarnessTagPolicy] = {}
    for harness, raw in data.items():
        if not isinstance(raw, dict):
            continue
        policies[harness.lower()] = HarnessTagPolicy(
            include_tags=[str(t) for t in raw.get("include_tags", [])],
            exclude_tags=[str(t) for t in raw.get("exclude_tags", [])],
        )

    return TaggingConfig(policies=policies)


def extract_tags(content: str) -> set[str]:
    """Return all tag names used in *content* (open block tags + inline tags)."""
    tags: set[str] = set()
    for m in _TAG_OPEN_RE.finditer(content):
        tags.add(m.group(1).lower())
    for m in _INLINE_TAG_RE.finditer(content):
        tags.add(m.group(1).lower())
    return tags


def has_tags(content: str) -> bool:
    """Return True if *content* contains any rule tag markers."""
    return bool(_TAG_OPEN_RE.search(content) or _INLINE_TAG_RE.search(content))


def filter_content_for_tags(
    content: str,
    policy: HarnessTagPolicy,
) -> str:
    """Filter *content* based on *policy*, returning only permitted tagged blocks.

    Algorithm:
    - Lines outside any tag block are always included.
    - Lines inside a ``<!-- #tag -->`` ... ``<!-- /#tag -->`` block are included
      only if *policy* allows that tag.
    - Inline-tagged lines (``<!-- tag:#security --> ...``) obey the same policy.
    - Tag marker lines themselves are stripped from output.

    Args:
        content: Raw rules text (CLAUDE.md or similar).
        policy:  HarnessTagPolicy for the target harness.

    Returns:
        Filtered content with tag markers removed.
    """
    if policy.is_empty():
        # No restrictions — strip markers but keep all content
        result = _TAG_OPEN_RE.sub("", content)
        result = _TAG_CLOSE_RE.sub("", result)
        result = _INLINE_TAG_RE.sub("", result)
        return result

    lines = content.splitlines(keepends=True)
    output: list[str] = []

    # Stack of currently active tags and their allow status
    active_tags: list[tuple[str, bool]] = []  # (tag_name, allowed)

    for line in lines:
        # Check for inline tag annotation
        inline_match = _INLINE_TAG_RE.search(line)
        if inline_match:
            tag = inline_match.group(1).lower()
            if policy.allows(tag):
                # Strip the inline marker and emit the line
                output.append(_INLINE_TAG_RE.sub("", line))
            # else: drop the line
            continue

        # Check for open tag
        open_match = _TAG_OPEN_RE.match(line.strip())
        if open_match:
            tag = open_match.group(1).lower()
            active_tags.append((tag, policy.allows(tag)))
            # Don't emit the tag marker line itself
            continue

        # Check for close tag
        close_match = _TAG_CLOSE_RE.match(line.strip())
        if close_match:
            tag = close_match.group(1).lower()
            # Pop the matching open tag (search from end for proper nesting)
            for i in range(len(active_tags) - 1, -1, -1):
                if active_tags[i][0] == tag:
                    active_tags.pop(i)
                    break
            # Don't emit the close marker line
            continue

        # Regular content line
        if not active_tags:
            # Outside any tagged block — always include
            output.append(line)
        else:
            # Inside one or more tagged blocks — include only if ALL active tags allow
            if all(allowed for _, allowed in active_tags):
                output.append(line)

    return "".join(output)


class RuleTagger:
    """Apply per-harness tag filtering to rules content.

    Args:
        project_dir: Project root (used to locate .harnesssync/rule_tags.json).
    """

    def __init__(self, project_dir: Path | None = None) -> None:
        self._project_dir = project_dir or Path.cwd()
        self._config = _load_tagging_config(self._project_dir)

    @property
    def is_configured(self) -> bool:
        """Return True if a non-trivial tag config is loaded."""
        return not self._config.is_empty()

    def filter_content(self, content: str, target: str) -> str:
        """Return *content* filtered by the tag policy for *target*.

        If no policy is defined for *target*, content passes through with
        tag markers stripped.

        Args:
            content: Rules markdown text.
            target:  Harness name.

        Returns:
            Filtered markdown text with tag markers removed.
        """
        if not has_tags(content):
            return content

        policy = self._config.policy_for(target)
        return filter_content_for_tags(content, policy)

    def filter_rules_list(self, rules: list[dict], target: str) -> list[dict]:
        """Filter a list of rules dicts (as used internally in the orchestrator).

        Each dict has at least a ``'content'`` key with the rules text.

        Args:
            rules:   List of rule dicts from SourceReader.
            target:  Harness name.

        Returns:
            New list with 'content' values filtered.
        """
        if not any(has_tags(r.get("content", "")) for r in rules):
            return rules

        policy = self._config.policy_for(target)
        if policy.is_empty():
            return rules

        result: list[dict] = []
        for rule in rules:
            content = rule.get("content", "")
            if has_tags(content):
                filtered = filter_content_for_tags(content, policy)
                result.append({**rule, "content": filtered})
            else:
                result.append(rule)
        return result

    def extract_tags(self, content: str) -> set[str]:
        """Return all tag names found in *content*."""
        return extract_tags(content)

    def format_policy_summary(self, target: str) -> str:
        """Return a human-readable description of the tag policy for *target*."""
        policy = self._config.policy_for(target)
        if policy.is_empty():
            return f"{target}: all rule tags included (no restrictions)"
        if policy.include_tags:
            return f"{target}: only tags {policy.include_tags} will be synced"
        if policy.exclude_tags:
            return f"{target}: tags {policy.exclude_tags} will be excluded"
        return f"{target}: no tag restrictions"

    def format_all_policies(self) -> str:
        """Return a summary of all configured harness tag policies."""
        if self._config.is_empty():
            return "Rule tagging: no per-harness tag filters configured."
        lines = ["Rule Tag Policies", "=" * 40]
        for target, policy in sorted(self._config.policies.items()):
            lines.append(f"  {self.format_policy_summary(target)}")
        return "\n".join(lines)


def create_default_tag_config(project_dir: Path) -> Path:
    """Write a starter rule_tags.json with example policies.

    Args:
        project_dir: Project root (.harnesssync/ written inside it).

    Returns:
        Path to the written config file.
    """
    config_dir = project_dir / _CONFIG_DIR
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / _CONFIG_FILENAME

    data = {
        "_comment": (
            "Rule Tag Policies — control which tagged rule categories sync to each harness. "
            "Tag blocks in CLAUDE.md: <!-- #security --> ... <!-- /#security -->. "
            "include_tags: allow-list. exclude_tags: deny-list. "
            "See: https://github.com/harnesssync/harnesssync#rule-tagging"
        ),
        "cursor": {
            "include_tags": ["security", "style", "workflow"]
        },
        "aider": {
            "include_tags": ["security", "workflow"]
        },
        "codex": {
            "exclude_tags": []
        },
        "gemini": {}
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path
