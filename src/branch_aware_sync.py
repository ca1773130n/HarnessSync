from __future__ import annotations

"""Git branch-aware sync profiles for HarnessSync.

Automatically applies different sync config when the current git branch
matches a declared profile. Lets users define per-branch overrides in
.harnesssync so that feature branches can use different MCP servers,
looser rules, or different target harnesses than main.

Configuration in .harnesssync:

    {
        "branch_profiles": {
            "main": {
                "only_targets": ["codex", "gemini"],
                "skip_sections": []
            },
            "feature/*": {
                "skip_targets": ["aider"],
                "only_sections": ["rules", "mcp"]
            },
            "release/*": {
                "skip_sections": ["mcp"],
                "only_targets": ["codex"]
            }
        }
    }

Pattern matching supports:
- Exact branch name: "main", "develop"
- Glob wildcards: "feature/*", "release/v*"
- Regex (prefix "re:"): "re:hotfix-\\d+"

When multiple patterns match, the most-specific match wins (exact > glob > regex).
"""

import fnmatch
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BranchProfile:
    """Sync overrides for a specific branch pattern."""

    pattern: str                          # Branch name pattern
    skip_sections: set[str] = field(default_factory=set)
    only_sections: set[str] = field(default_factory=set)
    skip_targets: set[str] = field(default_factory=set)
    only_targets: set[str] = field(default_factory=set)
    scope: str | None = None              # Override sync scope if set
    description: str = ""                 # Human-readable label for this profile

    @property
    def is_empty(self) -> bool:
        """Return True if this profile has no actual overrides."""
        return (
            not self.skip_sections
            and not self.only_sections
            and not self.skip_targets
            and not self.only_targets
            and self.scope is None
        )


def _get_current_branch(repo_dir: Path) -> str | None:
    """Return the current git branch name, or None if not in a git repo.

    Args:
        repo_dir: Directory to check git branch in.

    Returns:
        Branch name string, or None if git not available / not in repo.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=str(repo_dir),
            timeout=3,
        )
        if result.returncode == 0:
            branch = result.stdout.strip()
            # "HEAD" means detached HEAD state
            return branch if branch and branch != "HEAD" else None
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _pattern_matches(pattern: str, branch: str) -> bool:
    """Return True if a branch profile pattern matches the given branch name.

    Supports:
    - Exact match: "main"
    - Glob wildcard: "feature/*"
    - Regex (prefix "re:"): "re:hotfix-\\d+"

    Args:
        pattern: The profile key from branch_profiles config.
        branch: The current git branch name.

    Returns:
        True if the pattern matches the branch.
    """
    if pattern.startswith("re:"):
        try:
            return bool(re.fullmatch(pattern[3:], branch))
        except re.error:
            return False
    # Glob matching (fnmatch uses shell-style wildcards: *, ?, [...])
    return fnmatch.fnmatch(branch, pattern)


def _pattern_specificity(pattern: str) -> int:
    """Score a pattern's specificity for tiebreaking.

    Higher score = more specific = wins when multiple patterns match.

    Exact match > glob with no wildcard chars > glob with wildcards > regex.

    Args:
        pattern: Branch profile pattern string.

    Returns:
        Integer specificity score (higher = more specific).
    """
    if pattern.startswith("re:"):
        return 0
    if "*" in pattern or "?" in pattern or "[" in pattern:
        # Fewer wildcard chars → more specific
        wildcard_count = sum(1 for c in pattern if c in "*?[")
        return 10 - wildcard_count
    # Exact match
    return 100


def load_branch_profiles(project_config: dict) -> dict[str, BranchProfile]:
    """Parse branch_profiles from .harnesssync project config dict.

    Args:
        project_config: Parsed dict from the .harnesssync file.

    Returns:
        Dict mapping pattern -> BranchProfile.
    """
    raw = project_config.get("branch_profiles", {})
    if not isinstance(raw, dict):
        return {}

    profiles: dict[str, BranchProfile] = {}
    for pattern, overrides in raw.items():
        if not isinstance(overrides, dict):
            continue
        profiles[pattern] = BranchProfile(
            pattern=pattern,
            skip_sections=set(overrides.get("skip_sections", [])),
            only_sections=set(overrides.get("only_sections", [])),
            skip_targets=set(overrides.get("skip_targets", [])),
            only_targets=set(overrides.get("only_targets", [])),
            scope=overrides.get("scope"),
            description=overrides.get("description", ""),
        )
    return profiles


def resolve_branch_profile(
    project_dir: Path,
    project_config: dict,
) -> BranchProfile | None:
    """Find the best-matching branch profile for the current git branch.

    Detects the current git branch in project_dir, then matches it against
    all defined branch_profiles using specificity-ordered matching.

    Args:
        project_dir: Repository root directory.
        project_config: Parsed dict from .harnesssync file.

    Returns:
        The best-matching BranchProfile, or None if no profiles defined
        or no branch matches.
    """
    profiles = load_branch_profiles(project_config)
    if not profiles:
        return None

    branch = _get_current_branch(project_dir)
    if not branch:
        return None

    matches: list[tuple[int, BranchProfile]] = []
    for pattern, profile in profiles.items():
        if _pattern_matches(pattern, branch):
            matches.append((_pattern_specificity(pattern), profile))

    if not matches:
        return None

    # Return the most specific match
    matches.sort(key=lambda x: x[0], reverse=True)
    return matches[0][1]


def apply_branch_profile(
    profile: BranchProfile,
    current_skip_sections: set,
    current_only_sections: set,
    current_skip_targets: set,
    current_only_targets: set,
    current_scope: str,
) -> tuple[set, set, set, set, str]:
    """Merge a branch profile's overrides into the current sync settings.

    Branch profiles are additive for skip sets and restrictive for only sets,
    matching the same semantics as _apply_project_config() in the orchestrator.

    Args:
        profile: BranchProfile to apply.
        current_skip_sections: Current set of sections to skip.
        current_only_sections: Current set of sections to include exclusively.
        current_skip_targets: Current set of targets to skip.
        current_only_targets: Current set of targets to include exclusively.
        current_scope: Current sync scope string.

    Returns:
        Tuple of (skip_sections, only_sections, skip_targets, only_targets, scope)
        after merging the branch profile.
    """
    # Skip sets are additive
    new_skip_sections = current_skip_sections | profile.skip_sections
    new_skip_targets = current_skip_targets | profile.skip_targets

    # Only sets are intersective (most restrictive wins)
    if profile.only_sections:
        new_only_sections = (
            current_only_sections & profile.only_sections
            if current_only_sections
            else profile.only_sections
        )
    else:
        new_only_sections = current_only_sections

    if profile.only_targets:
        new_only_targets = (
            current_only_targets & profile.only_targets
            if current_only_targets
            else profile.only_targets
        )
    else:
        new_only_targets = current_only_targets

    new_scope = profile.scope if profile.scope else current_scope

    return new_skip_sections, new_only_sections, new_skip_targets, new_only_targets, new_scope


def describe_active_profile(profile: BranchProfile, branch: str) -> str:
    """Format a human-readable description of an active branch profile.

    Args:
        profile: The active BranchProfile.
        branch: Current branch name.

    Returns:
        Multi-line string describing the profile and its effects.
    """
    lines = [f"Branch profile active: '{profile.pattern}' (branch: {branch!r})"]
    if profile.description:
        lines.append(f"  {profile.description}")
    if profile.skip_sections:
        lines.append(f"  Skipping sections: {', '.join(sorted(profile.skip_sections))}")
    if profile.only_sections:
        lines.append(f"  Only syncing sections: {', '.join(sorted(profile.only_sections))}")
    if profile.skip_targets:
        lines.append(f"  Skipping targets: {', '.join(sorted(profile.skip_targets))}")
    if profile.only_targets:
        lines.append(f"  Only syncing to: {', '.join(sorted(profile.only_targets))}")
    if profile.scope:
        lines.append(f"  Scope override: {profile.scope}")
    return "\n".join(lines)
