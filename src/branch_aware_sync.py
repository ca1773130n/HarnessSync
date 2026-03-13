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


# ---------------------------------------------------------------------------
# Git Activity-Based Smart Sync Scheduling (item 28)
# ---------------------------------------------------------------------------


def get_git_commit_frequency(
    repo_dir: Path,
    lookback_days: int = 7,
) -> float:
    """Measure recent git commit frequency in commits per day.

    Args:
        repo_dir: Git repository root directory.
        lookback_days: How many days of history to analyze.

    Returns:
        Average commits per day over the lookback window.
        Returns 0.0 if git is unavailable or no commits found.
    """
    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--since={lookback_days} days ago",
                "--oneline",
                "--no-merges",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo_dir),
            timeout=5,
        )
        if result.returncode != 0:
            return 0.0
        commit_lines = [l for l in result.stdout.strip().splitlines() if l.strip()]
        return len(commit_lines) / max(1, lookback_days)
    except (OSError, subprocess.TimeoutExpired):
        return 0.0


def recommend_sync_interval_seconds(
    repo_dir: Path,
    base_cooldown: int = 300,
    active_cooldown: int = 60,
    quiet_cooldown: int = 1800,
    active_threshold: float = 5.0,
    quiet_threshold: float = 0.5,
) -> int:
    """Recommend a sync cooldown interval based on git commit activity.

    During active dev sprints (many commits), sync more aggressively so
    config changes propagate quickly. During quiet periods, back off to
    reduce unnecessary syncs.

    Activity levels:
        active:  >= active_threshold commits/day → active_cooldown seconds
        normal:  between thresholds              → base_cooldown seconds
        quiet:   <= quiet_threshold commits/day  → quiet_cooldown seconds

    Args:
        repo_dir: Git repository root.
        base_cooldown: Normal sync interval in seconds (default 300 = 5 min).
        active_cooldown: Fast sync interval during active sprints (default 60s).
        quiet_cooldown: Slow sync interval during quiet periods (default 30 min).
        active_threshold: Commits/day to be considered "active" (default 5).
        quiet_threshold: Commits/day to be considered "quiet" (default 0.5).

    Returns:
        Recommended sync cooldown in seconds.
    """
    freq = get_git_commit_frequency(repo_dir)

    if freq >= active_threshold:
        return active_cooldown
    elif freq <= quiet_threshold:
        return quiet_cooldown
    else:
        return base_cooldown


def get_activity_label(repo_dir: Path) -> str:
    """Return a human-readable activity label for the current repository.

    Args:
        repo_dir: Git repository root.

    Returns:
        One of: "active sprint", "normal", "quiet"
    """
    freq = get_git_commit_frequency(repo_dir)
    if freq >= 5.0:
        return "active sprint"
    elif freq <= 0.5:
        return "quiet"
    else:
        return "normal"


def adaptive_cooldown(
    repo_dir: Path,
    env_override: str | None = None,
) -> int:
    """Return the recommended sync cooldown, respecting env var overrides.

    Checks HARNESSSYNC_COOLDOWN env var first; falls back to the git
    activity-based recommendation.

    Args:
        repo_dir: Git repository root for activity measurement.
        env_override: Override value string (from HARNESSSYNC_COOLDOWN env var).
                      If None, reads from environment automatically.

    Returns:
        Cooldown interval in seconds.
    """
    import os

    if env_override is None:
        env_override = os.environ.get("HARNESSSYNC_COOLDOWN", "")

    if env_override:
        try:
            return max(0, int(env_override))
        except ValueError:
            pass

    return recommend_sync_interval_seconds(repo_dir)


# ──────────────────────────────────────────────────────────────────────────────
# Git post-checkout hook installer (item 3)
# ──────────────────────────────────────────────────────────────────────────────

_POST_CHECKOUT_HOOK = """\
#!/usr/bin/env sh
# HarnessSync: auto-sync when switching branches
# Installed by: harnesssync install-hook
#
# $1 = previous HEAD, $2 = new HEAD, $3 = flag (1=branch checkout, 0=file checkout)
CHECKOUT_TYPE="$3"
[ "$CHECKOUT_TYPE" != "1" ] && exit 0   # Skip file checkouts

# Only run if harnesssync is available
if ! command -v python3 > /dev/null 2>&1; then
    exit 0
fi

HARNESSSYNC_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"
if [ -z "$HARNESSSYNC_ROOT" ]; then
    exit 0
fi

# Run in background so checkout is not blocked
(cd "$HARNESSSYNC_ROOT" && python3 -m src.orchestrator sync --scope project --non-interactive --quiet 2>/dev/null &)
exit 0
"""


def install_post_checkout_hook(
    repo_dir: Path,
    overwrite: bool = False,
) -> dict[str, object]:
    """Install a git post-checkout hook that auto-syncs on branch switch.

    The hook triggers a background HarnessSync run when the user switches
    branches (not on file checkout), picking up any branch-specific profile
    overrides defined in .harnesssync.

    Args:
        repo_dir: Git repository root.
        overwrite: If True, replace an existing hook. If False, append
                   the HarnessSync section to an existing hook script.

    Returns:
        Dict with keys:
          - ``installed`` (bool): True if the hook was written.
          - ``hook_path`` (Path): Path to the hook file.
          - ``was_existing`` (bool): True if a hook already existed.
          - ``message`` (str): Human-readable status.
    """
    import os as _os
    import stat as _stat

    if not Path(repo_dir).is_dir():
        return {
            "installed": False,
            "hook_path": None,
            "was_existing": False,
            "message": f"Directory does not exist: {repo_dir}",
        }

    try:
        git_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            cwd=str(repo_dir),
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {
            "installed": False,
            "hook_path": None,
            "was_existing": False,
            "message": f"Not a git repository: {repo_dir}",
        }
    if git_dir_result.returncode != 0:
        return {
            "installed": False,
            "hook_path": None,
            "was_existing": False,
            "message": f"Not a git repository: {repo_dir}",
        }

    git_dir = Path(git_dir_result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo_dir / git_dir
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / "post-checkout"

    was_existing = hook_path.exists()
    marker = "# HarnessSync: auto-sync when switching branches"

    if was_existing and not overwrite:
        existing = hook_path.read_text(encoding="utf-8", errors="replace")
        if marker in existing:
            return {
                "installed": True,
                "hook_path": hook_path,
                "was_existing": True,
                "message": "HarnessSync hook already installed — skipped (use overwrite=True to replace).",
            }
        # Append to existing hook
        new_content = existing.rstrip("\n") + "\n\n" + _POST_CHECKOUT_HOOK
        hook_path.write_text(new_content, encoding="utf-8")
    else:
        hook_path.write_text(_POST_CHECKOUT_HOOK, encoding="utf-8")

    # Make executable
    current_mode = hook_path.stat().st_mode
    hook_path.chmod(current_mode | _stat.S_IXUSR | _stat.S_IXGRP | _stat.S_IXOTH)

    action = "updated" if was_existing and not overwrite else "installed"
    return {
        "installed": True,
        "hook_path": hook_path,
        "was_existing": was_existing,
        "message": (
            f"post-checkout hook {action} at {hook_path}. "
            "HarnessSync will now auto-sync when you switch branches."
        ),
    }


def uninstall_post_checkout_hook(repo_dir: Path) -> dict[str, object]:
    """Remove the HarnessSync section from the post-checkout hook.

    If the hook contains only the HarnessSync content, the file is deleted.
    If other content exists, only the HarnessSync section is stripped.

    Args:
        repo_dir: Git repository root.

    Returns:
        Dict with ``removed`` (bool) and ``message`` (str).
    """
    if not Path(repo_dir).is_dir():
        return {"removed": False, "message": f"Not a git repository: {repo_dir}"}

    try:
        git_dir_result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            cwd=str(repo_dir),
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"removed": False, "message": f"Not a git repository: {repo_dir}"}

    if git_dir_result.returncode != 0:
        return {"removed": False, "message": f"Not a git repository: {repo_dir}"}

    git_dir = Path(git_dir_result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = repo_dir / git_dir
    hook_path = git_dir / "hooks" / "post-checkout"

    if not hook_path.exists():
        return {"removed": False, "message": "No post-checkout hook found."}

    content = hook_path.read_text(encoding="utf-8", errors="replace")
    marker = "# HarnessSync: auto-sync when switching branches"
    if marker not in content:
        return {"removed": False, "message": "HarnessSync hook not found in post-checkout."}

    # Strip from the marker line to the end of the HarnessSync block
    lines = content.split("\n")
    new_lines: list[str] = []
    skip = False
    for line in lines:
        if marker in line:
            skip = True
        if not skip:
            new_lines.append(line)

    new_content = "\n".join(new_lines).rstrip("\n")
    if new_content.strip() in ("", "#!/usr/bin/env sh", "#!/bin/sh"):
        hook_path.unlink()
        return {"removed": True, "message": "post-checkout hook removed (file deleted — was HarnessSync-only)."}
    else:
        hook_path.write_text(new_content + "\n", encoding="utf-8")
        return {"removed": True, "message": "HarnessSync section removed from post-checkout hook."}
