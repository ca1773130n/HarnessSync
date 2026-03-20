from __future__ import annotations

"""Config variable substitution for CLAUDE.md and skills.

Supports ${VAR} placeholders that are substituted with project-specific
or user-specific values before syncing to each harness.

Built-in variables resolved automatically:
  ${PROJECT_NAME}   -- git repo name (basename of git root) or project_dir name
  ${GIT_USER}       -- git config user.name
  ${GIT_EMAIL}      -- git config user.email
  ${REPO_URL}       -- git remote origin URL
  ${BRANCH}         -- current git branch name
  ${HOME}           -- user home directory

Custom variables can be declared in .harnesssync under "vars":
  {"vars": {"CLIENT": "Acme Corp", "TICKET_PREFIX": "ACME"}}
"""

import json
import os as _os
import re
import subprocess as _subprocess
from pathlib import Path


def _run_git_field(args: list[str], cwd: str | None = None) -> str:
    """Run a git command and return stripped stdout, or empty string on failure."""
    try:
        result = _subprocess.run(
            args, capture_output=True, text=True, timeout=3, cwd=cwd
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (FileNotFoundError, _subprocess.TimeoutExpired, OSError):
        return ""


def _resolve_builtin_vars(project_dir: Path | None = None) -> dict[str, str]:
    """Resolve built-in config variables from git and environment.

    Args:
        project_dir: Project root for git commands. Falls back to cwd.

    Returns:
        Dict of variable name -> resolved value (all strings).
        Variables that cannot be resolved are set to empty string.
    """
    cwd = str(project_dir) if project_dir else None

    git_root = _run_git_field(["git", "rev-parse", "--show-toplevel"], cwd=cwd)
    project_name = Path(git_root).name if git_root else (
        project_dir.name if project_dir else _os.path.basename(_os.getcwd())
    )

    return {
        "PROJECT_NAME": project_name,
        "GIT_USER": _run_git_field(["git", "config", "user.name"], cwd=cwd),
        "GIT_EMAIL": _run_git_field(["git", "config", "user.email"], cwd=cwd),
        "REPO_URL": _run_git_field(
            ["git", "remote", "get-url", "origin"], cwd=cwd
        ),
        "BRANCH": _run_git_field(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd
        ),
        "HOME": str(Path.home()),
    }


def _load_custom_vars(project_dir: Path | None = None) -> dict[str, str]:
    """Load custom variables from .harnesssync 'vars' key.

    Args:
        project_dir: Directory containing .harnesssync config.

    Returns:
        Dict of var_name -> value from config, or empty dict.
    """
    if not project_dir:
        return {}
    harnesssync = project_dir / ".harnesssync"
    if not harnesssync.is_file():
        return {}
    try:
        data = json.loads(harnesssync.read_text(encoding="utf-8"))
        raw = data.get("vars", {})
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return {}


_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def substitute_config_vars(
    content: str,
    project_dir: Path | None = None,
    extra_vars: dict[str, str] | None = None,
) -> tuple[str, list[str]]:
    """Substitute ${VAR} placeholders in config content.

    Resolution order (highest priority wins):
    1. ``extra_vars`` passed directly
    2. Custom vars from .harnesssync ``vars`` key
    3. Built-in vars (PROJECT_NAME, GIT_USER, REPO_URL, BRANCH, HOME, GIT_EMAIL)

    Unresolved placeholders are left as-is (not substituted) so that
    harness-specific ${ENV_VAR} references are preserved for the target tool.

    Args:
        content:     String content with optional ${VAR} placeholders.
        project_dir: Project root for git resolution and .harnesssync loading.
        extra_vars:  Additional variables to inject (highest priority).

    Returns:
        Tuple of (substituted_content, list_of_substituted_var_names).
        The second element lists which variables were actually replaced.
    """
    builtin = _resolve_builtin_vars(project_dir)
    custom = _load_custom_vars(project_dir)
    # Merge: extra_vars > custom > builtin
    merged: dict[str, str] = {**builtin, **custom, **(extra_vars or {})}

    substituted: list[str] = []

    def _replace(m: re.Match) -> str:
        name = m.group(1)
        if name in merged and merged[name]:
            substituted.append(name)
            return merged[name]
        return m.group(0)  # Leave unresolved placeholders intact

    result = _VAR_PATTERN.sub(_replace, content)
    return result, substituted
