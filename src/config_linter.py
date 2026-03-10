from __future__ import annotations

"""Pre-sync configuration linter.

Validates CLAUDE.md and settings.json before sync and returns a list of
human-readable error/warning strings. Invalid configs are reported but
never block sync — the caller decides how to surface them.

Checks:
- CLAUDE.md: non-empty, no obviously broken markdown code fences
- settings.json: valid JSON, no unknown top-level keys that indicate corruption
- Skill/agent references that point to missing directories
- Sync tags that are unclosed (sync:exclude without sync:end)
"""

import json
import re
from pathlib import Path


# Top-level keys we expect in Claude Code settings.json (non-exhaustive)
_KNOWN_SETTINGS_KEYS = {
    "permissions", "approval_mode", "env", "hooks", "model",
    "autoUpdaterStatus", "userID", "oauthAccount", "theme",
    "preferredNotifChannel", "verbose",
}

# Sync tag pattern (must match sync_filter.py)
_TAG_RE = re.compile(
    r"<!--\s*sync:(exclude|codex-only|gemini-only|opencode-only|end)\s*-->",
    re.IGNORECASE,
)

# Broken markdown: unclosed triple-backtick fences
_FENCE_RE = re.compile(r"^```", re.MULTILINE)


class ConfigLinter:
    """Validates HarnessSync source configuration before sync."""

    def lint(
        self,
        source_data: dict,
        project_dir: Path | None = None,
        cc_home: Path | None = None,
    ) -> list[str]:
        """Run all lint checks against discovered source data.

        Args:
            source_data: Output of ``SourceReader.discover_all()``.
            project_dir: Project root (used for file existence checks).
            cc_home: Claude Code config directory (used for file existence checks).

        Returns:
            List of issue strings. Empty list = no issues found.
        """
        issues: list[str] = []

        issues.extend(self._lint_rules(source_data.get("rules", "")))
        issues.extend(self._lint_settings(source_data.get("settings", {})))
        issues.extend(self._lint_skills(source_data.get("skills", {})))
        issues.extend(self._lint_agents(source_data.get("agents", {})))

        return issues

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _lint_rules(self, rules) -> list[str]:
        """Check combined rules content."""
        issues: list[str] = []

        # rules can be a string (from get_rules()) or a list of dicts
        if isinstance(rules, list):
            texts = [r.get("content", "") for r in rules if isinstance(r, dict)]
            combined = "\n".join(texts)
        else:
            combined = rules or ""

        if not combined.strip():
            # Empty rules is not an error — warn softly
            return []

        # Check for unclosed markdown code fences
        fences = _FENCE_RE.findall(combined)
        if len(fences) % 2 != 0:
            issues.append(
                "CLAUDE.md: unclosed markdown code fence (odd number of ``` markers) — "
                "target harnesses may render incorrectly"
            )

        # Check for unclosed sync tags
        tag_stack: list[str] = []
        for m in _TAG_RE.finditer(combined):
            tag = m.group(1).lower()
            if tag == "end":
                if tag_stack:
                    tag_stack.pop()
                else:
                    issues.append(
                        "CLAUDE.md: <!-- sync:end --> without matching opening tag"
                    )
            else:
                tag_stack.append(tag)

        for unclosed in tag_stack:
            issues.append(
                f"CLAUDE.md: unclosed <!-- sync:{unclosed} --> tag (missing <!-- sync:end -->)"
            )

        return issues

    def _lint_settings(self, settings: dict) -> list[str]:
        """Check settings.json content."""
        issues: list[str] = []
        if not isinstance(settings, dict):
            issues.append("settings.json: content is not a JSON object — will be skipped")
            return issues

        # Warn on keys that look like corruption artifacts
        unexpected = set(settings.keys()) - _KNOWN_SETTINGS_KEYS
        # Filter to truly suspicious keys (long random-looking strings)
        truly_suspicious = [k for k in unexpected if len(k) > 40 or not k.replace("_", "").isalnum()]
        for k in truly_suspicious[:3]:
            issues.append(
                f"settings.json: suspicious key '{k[:60]}' — possible file corruption"
            )

        return issues

    def _lint_skills(self, skills: dict) -> list[str]:
        """Check that skill directories exist."""
        issues: list[str] = []
        for name, path in (skills or {}).items():
            p = Path(path) if not isinstance(path, Path) else path
            if not p.exists():
                issues.append(f"Skill '{name}' references missing directory: {p}")
            elif not (p / "SKILL.md").exists() and not any(p.iterdir()):
                issues.append(f"Skill '{name}' directory is empty: {p}")
        return issues

    def _lint_agents(self, agents: dict) -> list[str]:
        """Check that agent files exist."""
        issues: list[str] = []
        for name, path in (agents or {}).items():
            p = Path(path) if not isinstance(path, Path) else path
            if not p.exists():
                issues.append(f"Agent '{name}' references missing file: {p}")
        return issues
