from __future__ import annotations

"""User-Defined Transform Rules Engine (item 8).

Allows users to define regex or template-based replacement rules that run
during sync, translating project-specific patterns that adapters can't
handle automatically.

Common use-cases:
  - Replace ~/.claude references with target-specific config directories
  - Rewrite tool names that differ between harnesses
  - Substitute environment-specific values

Config file: .harnesssync-transforms (JSON, in project root or ~/.config)

Schema:
{
  "transforms": [
    {
      "name": "rewrite-claude-home",
      "pattern": "~/.claude",
      "replacement": "~/.codex",
      "targets": ["codex"],        // optional: only apply to these targets
      "scope": "literal"           // "literal" (default) or "regex"
    },
    {
      "name": "rename-tool",
      "pattern": "computer_use",
      "replacement": "computer-use",
      "targets": ["gemini"],
      "scope": "regex"
    }
  ]
}

Usage:
    from src.transform_engine import TransformEngine

    engine = TransformEngine.load(project_dir)
    transformed = engine.apply(content, target="codex")
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# Config file names searched in order (project root first, then user home)
_CONFIG_FILENAMES = [".harnesssync-transforms", ".harnesssync-transforms.json"]

_VALID_SCOPES = frozenset({"literal", "regex"})


@dataclass
class TransformRule:
    """A single user-defined transform rule.

    Attributes:
        name: Human-readable identifier (used in warnings/logs).
        pattern: Text to search for. Regex if scope='regex'.
        replacement: Replacement text. Supports \\1 backreferences in regex mode.
        targets: If non-empty, only apply to these harness targets.
        scope: 'literal' (plain string) or 'regex'.
        flags: Regex flags string (e.g. 'i' for case-insensitive). Ignored in literal mode.
    """

    name: str
    pattern: str
    replacement: str
    targets: list[str] = field(default_factory=list)
    scope: str = "literal"
    flags: str = ""

    def __post_init__(self) -> None:
        if self.scope not in _VALID_SCOPES:
            raise ValueError(f"Invalid scope {self.scope!r} in rule {self.name!r}. "
                             f"Must be one of: {', '.join(sorted(_VALID_SCOPES))}")

    def applies_to(self, target: str) -> bool:
        """Return True if this rule applies to the given target."""
        return not self.targets or target in self.targets

    def apply(self, content: str) -> str:
        """Apply this rule to content and return the result."""
        if self.scope == "regex":
            re_flags = 0
            for ch in self.flags.lower():
                if ch == "i":
                    re_flags |= re.IGNORECASE
                elif ch == "m":
                    re_flags |= re.MULTILINE
                elif ch == "s":
                    re_flags |= re.DOTALL
            return re.sub(self.pattern, self.replacement, content, flags=re_flags)
        else:
            return content.replace(self.pattern, self.replacement)


class TransformEngine:
    """Applies a set of user-defined transform rules to rule content.

    Load from disk via TransformEngine.load(project_dir), or construct
    directly with a list of TransformRule objects.

    The engine is intentionally lenient: malformed rules emit warnings but
    never block a sync operation.
    """

    def __init__(self, rules: list[TransformRule], config_path: Path | None = None):
        """Initialize the engine.

        Args:
            rules: List of transform rules to apply.
            config_path: Path the rules were loaded from (for error messages).
        """
        self.rules = rules
        self.config_path = config_path
        self._warnings: list[str] = []

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, project_dir: Path) -> "TransformEngine":
        """Load transform rules from disk.

        Searches for .harnesssync-transforms in project_dir, then
        ~/.config/harnesssync/transforms. Returns an engine with no rules
        (no-op) if no config file exists.

        Args:
            project_dir: Project root directory.

        Returns:
            TransformEngine instance (empty if no config found).
        """
        search_dirs = [
            project_dir,
            Path.home() / ".config" / "harnesssync",
        ]

        for directory in search_dirs:
            for filename in _CONFIG_FILENAMES:
                candidate = directory / filename
                if candidate.is_file():
                    return cls._load_from_file(candidate)

        return cls(rules=[], config_path=None)

    @classmethod
    def _load_from_file(cls, path: Path) -> "TransformEngine":
        """Parse a JSON transforms config file.

        Args:
            path: Path to the config file.

        Returns:
            TransformEngine with parsed rules.
        """
        warnings: list[str] = []
        rules: list[TransformRule] = []

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            engine = cls(rules=[], config_path=path)
            engine._warnings.append(f"Could not parse {path}: {e}")
            return engine

        raw_rules = raw.get("transforms", [])
        if not isinstance(raw_rules, list):
            engine = cls(rules=[], config_path=path)
            engine._warnings.append(f"{path}: 'transforms' must be a list")
            return engine

        for i, entry in enumerate(raw_rules):
            if not isinstance(entry, dict):
                warnings.append(f"{path} rule[{i}]: expected object, got {type(entry).__name__}")
                continue

            name = entry.get("name", f"rule-{i}")
            pattern = entry.get("pattern")
            replacement = entry.get("replacement")

            if not pattern or replacement is None:
                warnings.append(f"{path} rule {name!r}: 'pattern' and 'replacement' are required")
                continue

            try:
                rule = TransformRule(
                    name=name,
                    pattern=str(pattern),
                    replacement=str(replacement),
                    targets=list(entry.get("targets", [])),
                    scope=str(entry.get("scope", "literal")),
                    flags=str(entry.get("flags", "")),
                )
                rules.append(rule)
            except ValueError as e:
                warnings.append(f"{path} rule {name!r}: {e}")

        engine = cls(rules=rules, config_path=path)
        engine._warnings = warnings
        return engine

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    def apply(self, content: str, target: str) -> str:
        """Apply all applicable rules to content for the given target.

        Rules are applied in definition order. Each rule's output feeds
        into the next rule.

        Args:
            content: Rule/config text to transform.
            target: Harness target name (e.g. 'codex', 'gemini').

        Returns:
            Transformed content string.
        """
        for rule in self.rules:
            if not rule.applies_to(target):
                continue
            try:
                content = rule.apply(content)
            except re.error as e:
                self._warnings.append(
                    f"Rule {rule.name!r}: regex error — {e} (skipped)"
                )
        return content

    def apply_to_rules(self, rules: list[dict], target: str) -> list[dict]:
        """Apply transforms to a list of rule dicts (the format used by adapters).

        Args:
            rules: List of dicts with at least a 'content' key.
            target: Harness target name.

        Returns:
            New list with transformed 'content' values.
        """
        if not self.rules:
            return rules
        return [
            {**r, "content": self.apply(r.get("content", ""), target)}
            if isinstance(r, dict)
            else r
            for r in rules
        ]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def has_rules(self) -> bool:
        """Return True if any rules are configured."""
        return bool(self.rules)

    def warnings(self) -> list[str]:
        """Return any parse/apply warnings accumulated."""
        return list(self._warnings)

    def format_summary(self) -> str:
        """Return a human-readable summary of loaded rules."""
        if not self.rules and not self.config_path:
            return "Transform engine: no config file found (no transforms applied)"

        if not self.rules:
            return (
                f"Transform engine: config at {self.config_path} "
                f"loaded with 0 rules"
                + (f" ({len(self._warnings)} warning(s))" if self._warnings else "")
            )

        lines = [
            f"Transform engine: {len(self.rules)} rule(s) from {self.config_path}",
        ]
        for rule in self.rules:
            targets_str = f" → targets: {', '.join(rule.targets)}" if rule.targets else " → all targets"
            lines.append(
                f"  [{rule.scope}] {rule.name!r}: "
                f"{rule.pattern!r} → {rule.replacement!r}{targets_str}"
            )
        if self._warnings:
            lines.append(f"  Warnings: {len(self._warnings)}")
            for w in self._warnings:
                lines.append(f"    {w}")
        return "\n".join(lines)
