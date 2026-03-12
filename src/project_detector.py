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


# ---------------------------------------------------------------------------
# Rule generation (item 28: AI Rule Generator from Codebase Analysis)
# ---------------------------------------------------------------------------

@dataclass
class GeneratedRule:
    """A single auto-generated CLAUDE.md rule entry."""

    title: str
    body: str
    rationale: str = ""   # Why this rule was suggested

    def to_claude_md_block(self) -> str:
        """Format as a CLAUDE.md rule block with optional rationale comment."""
        lines = [f"## {self.title}", ""]
        lines.append(self.body.strip())
        if self.rationale:
            lines.append("")
            lines.append(f"<!-- rationale: {self.rationale} -->")
        return "\n".join(lines)


# Per-project-type rule templates.
# Maps project_type -> list of GeneratedRule factories (callables with no args).
_RULE_TEMPLATES: dict[str, list[GeneratedRule]] = {
    "nextjs": [
        GeneratedRule(
            title="Next.js App Router Conventions",
            body=(
                "- Use the App Router (app/ directory) for new pages, not Pages Router.\n"
                "- Server Components are the default; add 'use client' only when browser APIs are needed.\n"
                "- Prefer server-side data fetching with async Server Components over useEffect."
            ),
            rationale="Next.js App Router best practices for 13+",
        ),
        GeneratedRule(
            title="TypeScript Strict Mode",
            body=(
                "- Enable strict mode in tsconfig.json.\n"
                "- Avoid `any` type; use `unknown` and narrow with type guards.\n"
                "- All function parameters and return types must be explicitly typed."
            ),
            rationale="TypeScript strict mode detected via tsconfig",
        ),
        GeneratedRule(
            title="Component File Structure",
            body=(
                "- One component per file; filename matches component name.\n"
                "- Co-locate component styles, tests, and types in the same directory.\n"
                "- Export components as named exports, not default exports."
            ),
            rationale="React component organisation standard",
        ),
    ],
    "vite-app": [
        GeneratedRule(
            title="Vite Build Conventions",
            body=(
                "- Use ES module imports exclusively (no CommonJS require()).\n"
                "- Import CSS modules as `import styles from './Component.module.css'`.\n"
                "- Avoid synchronous top-level awaits in entry points."
            ),
            rationale="Vite ESM-first build model",
        ),
    ],
    "nestjs": [
        GeneratedRule(
            title="NestJS Module Conventions",
            body=(
                "- Every feature lives in its own module (feature/feature.module.ts).\n"
                "- Inject dependencies via constructor injection, not property injection.\n"
                "- Use class-validator for DTO validation; never validate manually."
            ),
            rationale="NestJS architecture best practices",
        ),
        GeneratedRule(
            title="NestJS Error Handling",
            body=(
                "- Throw HttpException subclasses (NotFoundException, BadRequestException) from services.\n"
                "- Use global exception filters for unhandled exceptions.\n"
                "- Never return raw Error objects in HTTP responses."
            ),
            rationale="NestJS structured error handling",
        ),
    ],
    "node-api": [
        GeneratedRule(
            title="Node.js Async Patterns",
            body=(
                "- Use async/await instead of callbacks or raw Promises where possible.\n"
                "- Always catch async errors; never let unhandled promise rejections propagate.\n"
                "- Use process.exitCode = 1 for fatal errors; never call process.exit() mid-request."
            ),
            rationale="Node.js async safety patterns",
        ),
        GeneratedRule(
            title="Security Hardening",
            body=(
                "- Validate and sanitize all user input before processing.\n"
                "- Never log full request bodies (may contain credentials).\n"
                "- Use parameterized queries; never concatenate SQL or NoSQL queries from user input."
            ),
            rationale="OWASP Node.js security best practices",
        ),
    ],
    "node": [
        GeneratedRule(
            title="Node.js Module Conventions",
            body=(
                "- Prefer ES modules (import/export) over CommonJS (require/module.exports).\n"
                "- Pin exact Node.js version in .nvmrc or engines field in package.json."
            ),
            rationale="Modern Node.js project hygiene",
        ),
    ],
    "python-lib": [
        GeneratedRule(
            title="Python Type Annotations",
            body=(
                "- All public functions and methods must have full type annotations.\n"
                "- Use `from __future__ import annotations` for Python 3.9 compatibility.\n"
                "- Prefer dataclasses over plain dicts for structured data."
            ),
            rationale="Python typing best practices",
        ),
        GeneratedRule(
            title="Python Package Conventions",
            body=(
                "- Use pyproject.toml as the single source of project metadata.\n"
                "- Export only the public API from __init__.py; keep internals private (_prefix).\n"
                "- Write doctests for all public functions."
            ),
            rationale="Modern Python package structure",
        ),
    ],
    "django": [
        GeneratedRule(
            title="Django ORM Safety",
            body=(
                "- Always use select_related() / prefetch_related() to avoid N+1 queries.\n"
                "- Never call .save() on model instances inside loops; use bulk_update() / bulk_create().\n"
                "- Run database migrations in CI before deploying."
            ),
            rationale="Django ORM performance and safety",
        ),
        GeneratedRule(
            title="Django Security Checklist",
            body=(
                "- Keep DEBUG = False in production.\n"
                "- Use Django's built-in CSRF and XSS protections; never disable them.\n"
                "- Store secrets in environment variables, never in settings.py."
            ),
            rationale="Django production security",
        ),
    ],
    "python": [
        GeneratedRule(
            title="Python Code Quality",
            body=(
                "- Follow PEP 8 for formatting (use ruff or black for auto-formatting).\n"
                "- Use `from __future__ import annotations` for Python 3.9 compatibility.\n"
                "- Prefer explicit over implicit; avoid magic that obscures intent."
            ),
            rationale="Python project conventions",
        ),
    ],
    "go": [
        GeneratedRule(
            title="Go Error Handling",
            body=(
                "- Always handle errors explicitly; never use _ to discard error returns.\n"
                "- Wrap errors with fmt.Errorf('context: %w', err) for stack traces.\n"
                "- Return early on error rather than nesting success paths."
            ),
            rationale="Go idiomatic error handling",
        ),
        GeneratedRule(
            title="Go Interface Design",
            body=(
                "- Keep interfaces small (1–3 methods); prefer many small interfaces over one large one.\n"
                "- Define interfaces in consumer packages, not producer packages.\n"
                "- Accept interfaces, return concrete types."
            ),
            rationale="Go interface best practices",
        ),
    ],
    "rust": [
        GeneratedRule(
            title="Rust Safety Rules",
            body=(
                "- Avoid unsafe blocks; if necessary, document why safety is upheld.\n"
                "- Prefer owned types (String, Vec) in public APIs; use borrows (&str, &[T]) internally.\n"
                "- Run clippy on every change; fix all warnings before committing."
            ),
            rationale="Rust safety and idiomatic usage",
        ),
    ],
    "terraform": [
        GeneratedRule(
            title="Terraform Conventions",
            body=(
                "- Use modules for all reusable infrastructure patterns.\n"
                "- Pin provider versions in required_providers; avoid floating ~> constraints.\n"
                "- Never hard-code secrets; use variable inputs with sensitive = true."
            ),
            rationale="Terraform infrastructure-as-code safety",
        ),
    ],
    "monorepo": [
        GeneratedRule(
            title="Monorepo Boundary Rules",
            body=(
                "- Do not import from sibling packages using relative paths (../other-pkg); use package names.\n"
                "- Keep shared utilities in a dedicated lib/ or packages/shared/ package.\n"
                "- Each package must pass its own tests in isolation before being merged."
            ),
            rationale="Monorepo boundary enforcement",
        ),
    ],
}

# Rules generated for any project type (universal rules)
_UNIVERSAL_RULES: list[GeneratedRule] = [
    GeneratedRule(
        title="Git Commit Conventions",
        body=(
            "- Use Conventional Commits format: feat:, fix:, docs:, chore:, refactor:, test:.\n"
            "- Keep commit messages under 72 characters in the subject line.\n"
            "- Reference issue numbers in commit bodies, not subjects."
        ),
        rationale="Universal git workflow standard",
    ),
    GeneratedRule(
        title="Code Review Readiness",
        body=(
            "- All PRs must include a test for the changed behaviour.\n"
            "- Remove all debug logging and TODO comments before requesting review.\n"
            "- Run the full test suite locally before pushing."
        ),
        rationale="Code review quality standard",
    ),
]


def generate_rules_for_project(
    project_dir: Path | None = None,
    include_universal: bool = True,
) -> list[GeneratedRule]:
    """Analyze a project directory and return tailored CLAUDE.md rule suggestions.

    Detects the project type using ProjectTypeDetector and returns a list of
    GeneratedRule objects ready to be formatted as CLAUDE.md sections. Also
    scans for secondary signals (test frameworks, linters, CI config) to add
    additional targeted rules.

    Args:
        project_dir: Project root. Defaults to cwd.
        include_universal: Add universal rules (git, code review). Default: True.

    Returns:
        List of GeneratedRule objects, most specific first.
    """
    d = project_dir or Path.cwd()
    detector = ProjectTypeDetector(d)
    profile = detector.detect()

    rules: list[GeneratedRule] = []

    # Add project-type-specific rules
    type_rules = _RULE_TEMPLATES.get(profile.project_type, [])
    rules.extend(type_rules)

    # Add signal-based supplemental rules
    rules.extend(_detect_supplemental_rules(d))

    # Add universal rules last
    if include_universal:
        rules.extend(_UNIVERSAL_RULES)

    return rules


def _detect_supplemental_rules(project_dir: Path) -> list[GeneratedRule]:
    """Detect secondary signals and return supplemental rules."""
    supplemental: list[GeneratedRule] = []

    # Testing framework rules
    if _exists_any(project_dir, "jest.config.js", "jest.config.ts", "jest.config.json"):
        supplemental.append(GeneratedRule(
            title="Jest Testing Standards",
            body=(
                "- Test file names must match *.test.ts or *.spec.ts.\n"
                "- Use describe blocks to group related tests.\n"
                "- Mock only at module boundaries; avoid mocking internals."
            ),
            rationale="Jest test configuration detected",
        ))
    elif _exists_any(project_dir, "pytest.ini", "conftest.py", "pyproject.toml"):
        if _file_contains(project_dir, "pyproject.toml", "pytest") or _exists_any(
            project_dir, "pytest.ini", "conftest.py"
        ):
            supplemental.append(GeneratedRule(
                title="Pytest Testing Standards",
                body=(
                    "- Use pytest fixtures for test setup and teardown.\n"
                    "- Name tests as test_<unit>_<scenario>_<expected_result>.\n"
                    "- Avoid mocking the database in integration tests."
                ),
                rationale="pytest configuration detected",
            ))

    # Linting / formatting
    if _exists_any(project_dir, ".eslintrc.js", ".eslintrc.json", "eslint.config.js"):
        supplemental.append(GeneratedRule(
            title="ESLint Compliance",
            body=(
                "- All code must pass ESLint without warnings before commit.\n"
                "- Do not use eslint-disable comments except as a last resort with explanation."
            ),
            rationale="ESLint configuration detected",
        ))

    if _exists_any(project_dir, ".pre-commit-config.yaml"):
        supplemental.append(GeneratedRule(
            title="Pre-commit Hook Compliance",
            body=(
                "- All pre-commit hooks must pass before pushing.\n"
                "- Do not use --no-verify unless explicitly approved by the team lead."
            ),
            rationale=".pre-commit-config.yaml detected",
        ))

    # CI/CD
    if _exists_any(project_dir, ".github/workflows/"):
        supplemental.append(GeneratedRule(
            title="GitHub Actions CI Requirements",
            body=(
                "- All CI checks must pass before merging to main.\n"
                "- Do not merge with force-pushed commits that bypass CI.\n"
                "- Pin GitHub Actions to a specific commit SHA, not a floating tag."
            ),
            rationale=".github/workflows/ detected",
        ))

    return supplemental


def format_generated_rules(rules: list[GeneratedRule]) -> str:
    """Format a list of GeneratedRule objects as a CLAUDE.md-ready string.

    Args:
        rules: Rules to format.

    Returns:
        Markdown string ready to append to CLAUDE.md.
    """
    if not rules:
        return ""
    blocks = [r.to_claude_md_block() for r in rules]
    return "\n\n".join(blocks)
