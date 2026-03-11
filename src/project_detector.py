from __future__ import annotations

"""Project type detector with smart adapter configuration defaults.

Detects the type of project (Python library, Node API, React app, Go service,
monorepo, etc.) from codebase signals and returns sensible HarnessSync adapter
configuration defaults for that project type.

Detection uses a priority-ordered list of signals:
1. Lock files (package-lock.json, Pipfile.lock, go.sum, Cargo.lock)
2. Framework config files (next.config.js, pyproject.toml, Cargo.toml)
3. Directory structure (src/, packages/, apps/ for monorepos)
4. Key source files (setup.py, manage.py for Django, server.js)

Returned defaults include:
- Recommended sync scope ("project" vs "user")
- Sections to skip by default (e.g. skip skills for simple scripts)
- Suggested sync targets based on project type conventions
- Annotations explaining each default
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProjectTypeProfile:
    """Detected project type with recommended HarnessSync defaults."""

    project_type: str
    description: str
    recommended_scope: str = "project"
    suggested_targets: list[str] = field(default_factory=list)
    suggested_skip_sections: list[str] = field(default_factory=list)
    suggested_only_sections: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confidence: str = "medium"  # low | medium | high

    def to_dict(self) -> dict:
        return {
            "project_type": self.project_type,
            "description": self.description,
            "recommended_scope": self.recommended_scope,
            "suggested_targets": self.suggested_targets,
            "suggested_skip_sections": self.suggested_skip_sections,
            "suggested_only_sections": self.suggested_only_sections,
            "notes": self.notes,
            "confidence": self.confidence,
        }

    def format_report(self) -> str:
        """Return a human-readable summary of the detected profile."""
        lines = [
            f"Detected project type: {self.project_type} ({self.confidence} confidence)",
            f"  {self.description}",
            "",
        ]
        lines.append(f"Recommended sync scope: --scope {self.recommended_scope}")
        if self.suggested_targets:
            lines.append(f"Suggested targets:      {', '.join(self.suggested_targets)}")
        if self.suggested_skip_sections:
            lines.append(f"Suggested skip:         {', '.join(self.suggested_skip_sections)}")
        if self.suggested_only_sections:
            lines.append(f"Suggested only:         {', '.join(self.suggested_only_sections)}")
        if self.notes:
            lines.append("")
            lines.append("Notes:")
            for note in self.notes:
                lines.append(f"  • {note}")
        return "\n".join(lines)


# Detection rules: each rule is (name, description, signals, profile_factory)
# Signals are checked in order; first match wins.


def _exists_any(project_dir: Path, *paths: str) -> bool:
    """Return True if any of the given relative paths exist."""
    return any((project_dir / p).exists() for p in paths)


def _file_contains(project_dir: Path, path: str, needle: str) -> bool:
    """Return True if the file contains the needle string."""
    p = project_dir / path
    if not p.is_file():
        return False
    try:
        return needle in p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False


class ProjectTypeDetector:
    """Detect project type from filesystem signals.

    Args:
        project_dir: Root directory of the project to analyze.
    """

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir or Path.cwd()

    def detect(self) -> ProjectTypeProfile:
        """Detect project type and return recommended HarnessSync defaults.

        Returns:
            ProjectTypeProfile with detected type and recommended config.
        """
        d = self.project_dir

        # --- Monorepo (check first — these contain sub-types) ---
        if self._is_monorepo():
            return ProjectTypeProfile(
                project_type="monorepo",
                description="Multi-package monorepo (Nx, Turborepo, Lerna, Cargo workspace, etc.)",
                recommended_scope="project",
                suggested_targets=["codex", "gemini", "cursor"],
                notes=[
                    "Sync with --scope project so each package gets its own config.",
                    "Consider tag-based selective sync (<!-- sync:codex-only -->) per package.",
                    "For large monorepos, use /sync-all-projects to sync each workspace.",
                ],
                confidence="high",
            )

        # --- React / Next.js ---
        if _exists_any(d, "next.config.js", "next.config.mjs", "next.config.ts"):
            return ProjectTypeProfile(
                project_type="nextjs",
                description="Next.js React application",
                recommended_scope="project",
                suggested_targets=["codex", "cursor", "vscode"],
                notes=[
                    "Cursor IDE is popular with Next.js developers — include it as a target.",
                    "VS Code Copilot is commonly used in React projects.",
                    "Consider syncing skills for React/TypeScript conventions.",
                ],
                confidence="high",
            )

        if _exists_any(d, "vite.config.js", "vite.config.ts"):
            return ProjectTypeProfile(
                project_type="vite-app",
                description="Vite-based frontend application",
                recommended_scope="project",
                suggested_targets=["codex", "cursor", "vscode"],
                notes=[
                    "Vite projects often use TypeScript — sync TS conventions via skills.",
                ],
                confidence="high",
            )

        # --- Node.js API ---
        if _exists_any(d, "package.json"):
            if _exists_any(d, "nest-cli.json") or _file_contains(d, "package.json", '"@nestjs/'):
                return ProjectTypeProfile(
                    project_type="nestjs",
                    description="NestJS Node.js API server",
                    recommended_scope="project",
                    suggested_targets=["codex", "gemini"],
                    notes=[
                        "Sync decorators/DI patterns via CLAUDE.md rules for consistency.",
                    ],
                    confidence="high",
                )
            if _file_contains(d, "package.json", '"express"') or _exists_any(d, "app.js", "server.js"):
                return ProjectTypeProfile(
                    project_type="node-api",
                    description="Node.js/Express API server",
                    recommended_scope="project",
                    suggested_targets=["codex", "gemini", "opencode"],
                    notes=[
                        "Skip skills section if this is a simple scripts-only project.",
                    ],
                    confidence="medium",
                )
            # Generic Node project
            return ProjectTypeProfile(
                project_type="node",
                description="Node.js project",
                recommended_scope="project",
                suggested_targets=["codex", "cursor", "vscode"],
                confidence="medium",
            )

        # --- Python ---
        if _exists_any(d, "pyproject.toml", "setup.py", "setup.cfg", "Pipfile"):
            if _file_contains(d, "pyproject.toml", "[tool.poetry]") or _exists_any(d, "poetry.lock"):
                return ProjectTypeProfile(
                    project_type="python-lib",
                    description="Python package (Poetry-managed)",
                    recommended_scope="project",
                    suggested_targets=["codex", "gemini", "aider"],
                    notes=[
                        "Aider is popular for Python library development — include it.",
                        "Sync type annotation and docstring conventions via CLAUDE.md.",
                    ],
                    confidence="high",
                )
            if _file_contains(d, "manage.py", "django") or _exists_any(d, "manage.py"):
                return ProjectTypeProfile(
                    project_type="django",
                    description="Django web application",
                    recommended_scope="project",
                    suggested_targets=["codex", "gemini", "aider"],
                    notes=[
                        "Django-specific conventions (ORM, migrations, views) should be in rules.",
                        "Aider works well for Django due to its file-diff workflow.",
                    ],
                    confidence="high",
                )
            return ProjectTypeProfile(
                project_type="python",
                description="Python project",
                recommended_scope="project",
                suggested_targets=["codex", "gemini", "aider"],
                notes=[
                    "Aider is a strong choice for Python projects.",
                ],
                confidence="medium",
            )

        # --- Go ---
        if _exists_any(d, "go.mod", "go.sum"):
            return ProjectTypeProfile(
                project_type="go",
                description="Go module",
                recommended_scope="project",
                suggested_targets=["codex", "gemini"],
                notes=[
                    "Sync Go idioms (error handling, interface patterns) via CLAUDE.md.",
                    "Skip skills section — Go projects rarely use CLI skill systems.",
                ],
                suggested_skip_sections=["skills"],
                confidence="high",
            )

        # --- Rust ---
        if _exists_any(d, "Cargo.toml", "Cargo.lock"):
            return ProjectTypeProfile(
                project_type="rust",
                description="Rust project (Cargo)",
                recommended_scope="project",
                suggested_targets=["codex", "gemini"],
                notes=[
                    "Sync borrow checker guidance and unsafe usage rules via CLAUDE.md.",
                ],
                suggested_skip_sections=["skills"],
                confidence="high",
            )

        # --- Mobile ---
        if _exists_any(d, "pubspec.yaml"):
            return ProjectTypeProfile(
                project_type="flutter",
                description="Flutter/Dart mobile application",
                recommended_scope="project",
                suggested_targets=["codex", "cursor"],
                notes=[
                    "Cursor has good Dart/Flutter support — recommend as primary target.",
                ],
                confidence="high",
            )

        if _exists_any(d, "android/", "ios/", "fastlane/"):
            return ProjectTypeProfile(
                project_type="mobile",
                description="Mobile application (iOS/Android)",
                recommended_scope="project",
                suggested_targets=["codex", "cursor"],
                confidence="medium",
            )

        # --- Infrastructure / DevOps ---
        if _exists_any(d, "terraform.tf", "main.tf", ".terraform/"):
            return ProjectTypeProfile(
                project_type="terraform",
                description="Terraform infrastructure project",
                recommended_scope="project",
                suggested_targets=["codex", "gemini"],
                suggested_skip_sections=["skills", "agents", "commands"],
                notes=[
                    "Focus on syncing rules for Terraform naming conventions and security policies.",
                ],
                confidence="high",
            )

        if _exists_any(d, "Dockerfile", "docker-compose.yml", "docker-compose.yaml"):
            return ProjectTypeProfile(
                project_type="docker",
                description="Containerized application",
                recommended_scope="project",
                suggested_targets=["codex", "gemini"],
                confidence="low",
            )

        # --- Fallback ---
        return ProjectTypeProfile(
            project_type="generic",
            description="Generic project (type could not be determined)",
            recommended_scope="all",
            suggested_targets=["codex", "gemini", "opencode"],
            notes=[
                "Could not detect project type from filesystem signals.",
                "Manually configure HarnessSync with /sync-setup.",
            ],
            confidence="low",
        )

    # ------------------------------------------------------------------
    # Monorepo detection helpers
    # ------------------------------------------------------------------

    def _is_monorepo(self) -> bool:
        """Return True if the project looks like a monorepo."""
        d = self.project_dir

        # Explicit monorepo config files
        if _exists_any(d, "nx.json", "lerna.json", "pnpm-workspace.yaml", "rush.json"):
            return True

        # Turborepo
        if _exists_any(d, "turbo.json"):
            return True

        # Cargo workspace
        if _exists_any(d, "Cargo.toml") and _file_contains(d, "Cargo.toml", "[workspace]"):
            return True

        # packages/ or apps/ sub-dirs with their own package.json
        for subdir in ("packages", "apps", "libs", "services"):
            sub = d / subdir
            if sub.is_dir() and any((sub / child / "package.json").exists() for child in _listdir(sub)):
                return True

        return False


def _listdir(path: Path) -> list[str]:
    """Return child directory names, or empty list on error."""
    try:
        return [p.name for p in path.iterdir() if p.is_dir()]
    except OSError:
        return []
