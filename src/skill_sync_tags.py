from __future__ import annotations

"""Skill Sync Tags — YAML frontmatter sync control for individual skills.

Adds a ``sync:`` frontmatter field to skill files that controls which harnesses
the skill is synced to.  Skills without a ``sync:`` field are synced everywhere
(unchanged default behaviour).

Supported frontmatter forms:

    ---
    sync: all                          # sync to all harnesses (default)
    ---

    ---
    sync: [codex, gemini]              # only these harnesses
    ---

    ---
    sync: exclude-aider                # sync everywhere EXCEPT aider
    ---

    ---
    sync:
      exclude: [aider, windsurf]       # exclude list (dict form)
    ---

    ---
    sync:
      only: [codex, gemini, cursor]    # include list (dict form)
    ---

The field is read from the YAML frontmatter block at the top of the skill's
SKILL.md (or the skill file itself if it IS a .md file).  Frontmatter is the
block between the first and second ``---`` lines.

Usage::

    from src.skill_sync_tags import parse_skill_sync_tag, skill_allowed_for_target

    allowed = parse_skill_sync_tag("/path/to/skill/SKILL.md")
    if not skill_allowed_for_target(allowed, "aider"):
        # skip syncing this skill to aider
        ...

Integration point: skill adapters and the orchestrator call
``skill_allowed_for_target()`` when iterating over skills to sync.
"""

import re
from pathlib import Path

from src.utils.constants import EXTENDED_TARGETS

try:
    import yaml as _yaml
    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

# Canonical list of all known targets
_ALL_TARGETS = frozenset(EXTENDED_TARGETS + ("vscode",))

# Regex to strip an ``exclude-TARGET`` shorthand value
_EXCLUDE_RE = re.compile(r"^exclude-([a-z0-9_-]+(?:,[a-z0-9_-]+)*)$", re.IGNORECASE)


def _parse_frontmatter_block(content: str) -> dict | None:
    """Extract the YAML frontmatter dict from a Markdown string.

    Returns the parsed dict, or None if no frontmatter block found.
    """
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        return None

    # Find closing ---
    rest = stripped[3:]
    end_idx = rest.find("\n---")
    if end_idx == -1:
        return None

    yaml_block = rest[:end_idx].strip()
    if not yaml_block:
        return {}

    if _HAS_YAML:
        try:
            parsed = _yaml.safe_load(yaml_block)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    # Fallback: minimal key: value parser (no YAML library available)
    result: dict = {}
    for line in yaml_block.splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            key, _, val = line.partition(":")
            result[key.strip()] = val.strip()
    return result


def parse_skill_sync_tag(skill_path: str | Path) -> dict:
    """Parse the ``sync:`` frontmatter field from a skill file.

    Args:
        skill_path: Path to the skill SKILL.md file (or its directory).

    Returns:
        A normalised sync-control dict with keys:
          - "mode": "all" | "only" | "exclude"
          - "targets": frozenset of target names (relevant for only/exclude modes)

        Examples:
          {"mode": "all",     "targets": frozenset()}
          {"mode": "only",    "targets": frozenset({"codex", "gemini"})}
          {"mode": "exclude", "targets": frozenset({"aider"})}
    """
    path = Path(skill_path)
    if path.is_dir():
        skill_md = path / "SKILL.md"
        if not skill_md.exists():
            # Also try index.md
            skill_md = path / "index.md"
        path = skill_md

    if not path.is_file():
        return {"mode": "all", "targets": frozenset()}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"mode": "all", "targets": frozenset()}

    frontmatter = _parse_frontmatter_block(content)
    if frontmatter is None or "sync" not in frontmatter:
        return {"mode": "all", "targets": frozenset()}

    return _normalise_sync_value(frontmatter["sync"])


def _normalise_sync_value(value) -> dict:
    """Normalise a raw ``sync:`` frontmatter value into a canonical dict.

    Handles all supported forms:
      - "all"                    → mode=all
      - "none" / "exclude-all"  → mode=exclude, targets=all
      - "exclude-aider"         → mode=exclude, targets={aider}
      - "exclude-a,b"           → mode=exclude, targets={a,b}
      - ["codex","gemini"]       → mode=only
      - {"only": [...]}          → mode=only
      - {"exclude": [...]}       → mode=exclude
    """
    if value is None or value == "all":
        return {"mode": "all", "targets": frozenset()}

    # String shorthand: "exclude-TARGET[,TARGET]"
    if isinstance(value, str):
        val_lower = value.lower().strip()
        if val_lower in ("none", "exclude-all"):
            return {"mode": "exclude", "targets": frozenset(_ALL_TARGETS)}
        m = _EXCLUDE_RE.match(val_lower)
        if m:
            excluded = frozenset(t.strip() for t in m.group(1).split(",") if t.strip())
            return {"mode": "exclude", "targets": excluded}
        # Single target name: treated as only:[target]
        if val_lower in _ALL_TARGETS:
            return {"mode": "only", "targets": frozenset({val_lower})}
        return {"mode": "all", "targets": frozenset()}

    # List of target names: sync: [codex, gemini]
    if isinstance(value, list):
        targets = frozenset(str(t).lower().strip() for t in value if t)
        return {"mode": "only", "targets": targets}

    # Dict form: sync: {only: [...]} or sync: {exclude: [...]}
    if isinstance(value, dict):
        if "only" in value:
            only_raw = value["only"]
            if isinstance(only_raw, list):
                targets = frozenset(str(t).lower().strip() for t in only_raw if t)
            else:
                targets = frozenset({str(only_raw).lower().strip()})
            return {"mode": "only", "targets": targets}
        if "exclude" in value:
            excl_raw = value["exclude"]
            if isinstance(excl_raw, list):
                targets = frozenset(str(t).lower().strip() for t in excl_raw if t)
            else:
                targets = frozenset({str(excl_raw).lower().strip()})
            return {"mode": "exclude", "targets": targets}

    return {"mode": "all", "targets": frozenset()}


def skill_allowed_for_target(sync_tag: dict, target: str) -> bool:
    """Return True if a skill with the given sync tag should be synced to target.

    Args:
        sync_tag: Normalised sync tag dict from :func:`parse_skill_sync_tag`.
        target:   Canonical target name (e.g. "codex", "aider").

    Returns:
        True if the skill should be synced to this target.
    """
    mode = sync_tag.get("mode", "all")
    targets = sync_tag.get("targets", frozenset())
    target_lower = target.lower()

    if mode == "all":
        return True
    if mode == "only":
        return target_lower in targets
    if mode == "exclude":
        return target_lower not in targets
    return True


def filter_skills_for_target(
    skills: dict[str, Path],
    target: str,
) -> dict[str, Path]:
    """Filter a skills dict to only those allowed for a specific target.

    Args:
        skills: Dict mapping skill_name -> skill directory/file path.
        target: Canonical target name (e.g. "gemini").

    Returns:
        Filtered dict containing only skills that should be synced to target.
    """
    result: dict[str, Path] = {}
    for name, path in skills.items():
        sync_tag = parse_skill_sync_tag(path)
        if skill_allowed_for_target(sync_tag, target):
            result[name] = path
    return result


def parse_agent_sync_tag(agent_path: str | Path) -> dict:
    """Parse the ``sync:`` frontmatter field from an agent .md file.

    Args:
        agent_path: Path to the agent .md file.

    Returns:
        Normalised sync-control dict identical to :func:`parse_skill_sync_tag`.
    """
    path = Path(agent_path)
    if not path.is_file():
        return {"mode": "all", "targets": frozenset()}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"mode": "all", "targets": frozenset()}

    frontmatter = _parse_frontmatter_block(content)
    if frontmatter is None or "sync" not in frontmatter:
        return {"mode": "all", "targets": frozenset()}

    return _normalise_sync_value(frontmatter["sync"])


def filter_agents_for_target(
    agents: dict[str, Path],
    target: str,
) -> dict[str, Path]:
    """Filter an agents dict to only those allowed for a specific target.

    Reads the ``sync:`` YAML frontmatter from each agent .md file and
    returns only agents whose sync tag permits ``target``.

    Args:
        agents: Dict mapping agent_name -> path to agent .md file.
        target: Canonical target name (e.g. "gemini").

    Returns:
        Filtered dict containing only agents that should be synced to target.
    """
    result: dict[str, Path] = {}
    for name, path in agents.items():
        sync_tag = parse_agent_sync_tag(path)
        if skill_allowed_for_target(sync_tag, target):
            result[name] = path
    return result


def describe_skill_sync_tag(sync_tag: dict) -> str:
    """Return a human-readable description of a skill's sync tag.

    Args:
        sync_tag: Normalised sync tag dict.

    Returns:
        Short description string.
    """
    mode = sync_tag.get("mode", "all")
    targets = sync_tag.get("targets", frozenset())

    if mode == "all":
        return "syncs to all harnesses"
    if mode == "only":
        if not targets:
            return "syncs to no harnesses (empty only list)"
        return f"syncs only to: {', '.join(sorted(targets))}"
    if mode == "exclude":
        if not targets:
            return "syncs to all harnesses (empty exclude list)"
        if targets >= _ALL_TARGETS:
            return "excluded from all harnesses"
        return f"excluded from: {', '.join(sorted(targets))}"
    return "syncs to all harnesses"
