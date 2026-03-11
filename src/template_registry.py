from __future__ import annotations

"""Config Templates Marketplace — curated CLAUDE.md templates by domain.

A built-in library of battle-tested Claude Code configuration templates
organized by language, framework, team size, and domain. Users browse and
apply templates; HarnessSync translates them to all target harnesses.

Templates are bundled locally (no network required for built-in set) and
can be supplemented by community templates fetched from a remote registry.

Template schema:
    {
        "name": "python-fastapi",
        "title": "Python FastAPI Service",
        "description": "Production FastAPI with async, SQLAlchemy, and Pydantic v2",
        "tags": ["python", "web", "api", "backend"],
        "rules": "# FastAPI rules\\n\\n...",
        "mcp_suggestions": ["postgres", "filesystem"],
        "settings_suggestions": {"approval_mode": "suggest"},
        "author": "HarnessSync team",
        "version": "1.0"
    }
"""

import json
from dataclasses import dataclass, field
from pathlib import Path


_COMMUNITY_REGISTRY_URL = "https://raw.githubusercontent.com/harnesssync/templates/main/registry.json"


@dataclass
class ConfigTemplate:
    """A Claude Code configuration template."""

    name: str
    title: str
    description: str
    tags: list[str]
    rules: str
    mcp_suggestions: list[str] = field(default_factory=list)
    settings_suggestions: dict = field(default_factory=dict)
    author: str = "HarnessSync team"
    version: str = "1.0"

    def matches(self, query: str) -> bool:
        """Return True if query matches name, tags, title, or description."""
        q = query.lower()
        return (
            q in self.name.lower()
            or q in self.title.lower()
            or q in self.description.lower()
            or any(q in tag.lower() for tag in self.tags)
        )


# ──────────────────────────────────────────────────────────────────────────────
# Built-in template library
# ──────────────────────────────────────────────────────────────────────────────

_BUILTIN_TEMPLATES: list[ConfigTemplate] = [
    ConfigTemplate(
        name="python-fastapi",
        title="Python FastAPI Service",
        description="Production-grade FastAPI with async SQLAlchemy, Pydantic v2, and pytest",
        tags=["python", "fastapi", "web", "api", "backend", "async"],
        rules="""\
# Python FastAPI Development Rules

## Code Style
- Always use async/await for route handlers and database operations
- Use Pydantic v2 models for request/response validation — never use dict directly
- Type-hint all function signatures including return types
- Use `from __future__ import annotations` at the top of every Python file

## Database
- Use async SQLAlchemy with `async with session:` context managers
- Never use synchronous SQLAlchemy sessions in async route handlers
- Run all migrations with Alembic before merging to main

## Testing
- Write pytest tests using `pytest-asyncio` for all async routes
- Each route must have at least one happy-path and one error-path test
- Use `httpx.AsyncClient` for route integration tests, not the test client directly

## Error Handling
- Never raise bare exceptions — always use HTTPException with appropriate status codes
- Log errors with structlog including request ID for traceability

## Security
- Never commit API keys, database URLs, or secrets — use environment variables
- Validate all external input with Pydantic before use
""",
        mcp_suggestions=["postgres", "filesystem"],
        settings_suggestions={"approval_mode": "suggest"},
    ),

    ConfigTemplate(
        name="typescript-nextjs",
        title="TypeScript Next.js Application",
        description="Full-stack Next.js 14+ with App Router, Prisma, and Tailwind CSS",
        tags=["typescript", "nextjs", "react", "web", "fullstack", "frontend"],
        rules="""\
# TypeScript Next.js Development Rules

## TypeScript
- Strict mode is enabled — no `any` types unless absolutely unavoidable
- Always use `satisfies` over type assertions when possible
- Prefer interfaces over type aliases for object shapes
- Export types from dedicated `types/` files, not from component files

## Next.js App Router
- Use Server Components by default — only add 'use client' when needed
- Data fetching happens in Server Components or Route Handlers, never in client hooks
- Use `loading.tsx` and `error.tsx` in all route segments
- Keep server-only code out of client bundles (use `server-only` package)

## Database (Prisma)
- Run `prisma generate` after any schema change
- Never write raw SQL when Prisma can handle it
- Use transactions for multi-table writes

## Styling
- Use Tailwind CSS utility classes — no inline styles, no CSS modules unless necessary
- Responsive-first: design for mobile, add breakpoints for larger screens

## Testing
- Component tests with Vitest + Testing Library
- E2E tests with Playwright for critical user flows
""",
        mcp_suggestions=["filesystem", "playwright"],
        settings_suggestions={"approval_mode": "suggest"},
    ),

    ConfigTemplate(
        name="rust-systems",
        title="Rust Systems Programming",
        description="Safe, idiomatic Rust for systems and CLI tools",
        tags=["rust", "systems", "cli", "performance", "backend"],
        rules="""\
# Rust Systems Programming Rules

## Idiomatic Rust
- Use `Result<T, E>` for all fallible operations — never `unwrap()` in library code
- Prefer `?` operator over explicit `match` for error propagation
- Use iterators and combinators instead of explicit loops where readable
- Derive `Debug`, `Clone`, and relevant standard traits on public types

## Memory Safety
- Avoid `unsafe` unless wrapping a C FFI or performance-critical hot path
- Any `unsafe` block must have a SAFETY comment explaining the invariants

## Error Handling
- Define domain errors with `thiserror` derive macros
- Application binaries use `anyhow` for context-rich error chains

## Testing
- Unit tests in the same file as the code (`#[cfg(test)]` modules)
- Integration tests in `tests/` directory
- Run `cargo clippy -- -D warnings` before every commit

## Performance
- Profile before optimizing — no premature optimization
- Use `criterion` for micro-benchmarks on hot paths
""",
        mcp_suggestions=["filesystem"],
    ),

    ConfigTemplate(
        name="go-microservice",
        title="Go Microservice",
        description="Production Go service with standard library + minimal dependencies",
        tags=["go", "golang", "microservice", "backend", "api"],
        rules="""\
# Go Microservice Development Rules

## Code Style
- Follow standard Go formatting (gofmt) — no custom formatters
- Use table-driven tests with `t.Run` for subtests
- All exported symbols must have Go doc comments

## Error Handling
- Always check errors — never ignore with `_`
- Wrap errors with `fmt.Errorf("context: %w", err)` for stack traces
- Return errors upward; log at the top level only

## Concurrency
- Use channels for communication, mutexes for shared state
- Always use `context.Context` for cancellation and deadlines
- Close channels from the sender, not the receiver

## HTTP Services
- Use `net/http` standard library over frameworks for simple services
- Validate and decode request bodies before business logic
- Return appropriate HTTP status codes — 200/201/204/400/404/500

## Dependencies
- Prefer standard library — add third-party deps only when essential
- Run `go mod tidy` before commits
""",
        mcp_suggestions=["filesystem"],
    ),

    ConfigTemplate(
        name="data-science-python",
        title="Python Data Science & ML",
        description="Jupyter-based data science with pandas, sklearn, and MLflow",
        tags=["python", "data-science", "ml", "machine-learning", "jupyter", "pandas"],
        rules="""\
# Python Data Science Rules

## Notebooks
- First cell: imports and configuration only
- Each notebook has a clear title and purpose in the first markdown cell
- Restart kernel and run all before committing — no hidden state
- Store data processing pipelines in `src/`, not notebooks

## Data Handling
- Never modify raw data — always work from copies
- Validate dataframe schemas at ingestion with pandera or similar
- Document data sources and transformation steps in markdown cells

## Experiments
- Track all experiments in MLflow or equivalent (no magic numbers in code)
- Pin random seeds for reproducibility: `np.random.seed(42)`
- Log metrics, params, and artifacts for every experiment run

## Code Quality
- Modular functions in `src/` that notebooks import — not notebook-only code
- Type hints on all functions in `src/`

## Dependencies
- Manage with conda environment or pip requirements.txt with pinned versions
- Never `pip install` in notebook cells — add to requirements.txt
""",
        mcp_suggestions=["filesystem"],
    ),

    ConfigTemplate(
        name="terraform-infrastructure",
        title="Terraform Infrastructure",
        description="Modular Terraform for cloud infrastructure with state management",
        tags=["terraform", "infrastructure", "iac", "devops", "cloud"],
        rules="""\
# Terraform Infrastructure Rules

## Module Structure
- One module per logical resource group — no monolithic main.tf
- Each module has: `main.tf`, `variables.tf`, `outputs.tf`, `README.md`
- Use descriptive resource names: `aws_s3_bucket.app_artifacts`, not `bucket1`

## Variables & Outputs
- All variables have descriptions and types — no untyped variables
- Sensitive variables marked with `sensitive = true`
- Output everything that downstream modules or humans might need

## State Management
- Remote state only (S3 + DynamoDB, GCS, Terraform Cloud)
- Never commit `.tfstate` files
- Use workspaces for environment separation (dev/staging/prod)

## Safety
- Run `terraform plan` and review before `apply`
- Use `prevent_destroy = true` on databases and state buckets
- Tag all resources with environment, owner, and cost-center

## Secrets
- Use AWS SSM Parameter Store, HashiCorp Vault, or equivalent
- Never hardcode credentials in Terraform files
""",
        mcp_suggestions=["filesystem"],
    ),

    ConfigTemplate(
        name="mobile-react-native",
        title="React Native Mobile App",
        description="Cross-platform React Native with Expo and TypeScript",
        tags=["react-native", "mobile", "typescript", "expo", "ios", "android"],
        rules="""\
# React Native Development Rules

## TypeScript
- Strict TypeScript — no `any` types
- Navigation types defined with TypeScript for all screens

## Components
- Functional components only — no class components
- Style with StyleSheet.create — no inline style objects
- Use platform-specific extensions (`Button.ios.tsx`) for platform UI differences

## Performance
- Use `FlatList` or `FlashList` for long lists — never `map` in ScrollView
- Memo expensive components with `React.memo`
- Profile with Flipper before optimizing

## Testing
- Unit tests with Jest + React Native Testing Library
- Never test implementation details — test user-visible behavior

## Navigation
- React Navigation v6+ with typed route params
- Deep link support from day one

## Offline
- Assume intermittent connectivity — cache critical data locally
""",
        mcp_suggestions=["filesystem"],
    ),

    ConfigTemplate(
        name="security-focused",
        title="Security-Focused Development",
        description="Rules emphasizing secure coding practices across any stack",
        tags=["security", "owasp", "devsecops", "compliance"],
        rules="""\
# Security-Focused Development Rules

## Input Validation
- Validate all external input at system boundaries (API, CLI, file)
- Use allowlists, not denylists, for validation
- Parameterize all database queries — no string concatenation in SQL

## Secrets Management
- Never hardcode secrets, API keys, or credentials in source code
- Use environment variables or a secret manager (Vault, AWS SSM)
- Scan for secrets before committing with a pre-commit hook

## Authentication & Authorization
- Verify authentication on every protected endpoint — never trust client
- Use short-lived tokens with refresh mechanisms
- Apply principle of least privilege for service accounts

## Dependencies
- Audit dependencies weekly with `npm audit`, `pip-audit`, or equivalent
- Pin transitive dependencies in lock files
- Review new dependencies for license and security before adding

## Error Handling
- Never expose stack traces or internal details to clients
- Log security events (failed auth, permission denials) for audit trail

## Cryptography
- Use vetted libraries — never implement crypto primitives
- Minimum AES-256, RSA-2048, SHA-256 for new code
""",
    ),

    ConfigTemplate(
        name="monorepo-team",
        title="Monorepo Team Setup",
        description="Rules for large team monorepos with clear ownership and CI gates",
        tags=["monorepo", "team", "enterprise", "nx", "turborepo", "codeowners"],
        rules="""\
# Monorepo Team Development Rules

## Ownership
- Every package/app has a CODEOWNERS entry
- Changes to shared packages require review from all consuming teams

## Commits
- Conventional commits: `feat(scope):`, `fix(scope):`, `docs(scope):`
- Scope matches the affected package name

## Dependencies
- No circular dependencies between packages
- Shared utilities live in `packages/utils/` — not duplicated in apps
- Version bumps in shared packages use changesets

## Testing
- Each package has its own test suite
- Integration tests for cross-package interactions live in `e2e/`
- CI blocks merges with <80% coverage in changed packages

## Build
- Build only affected packages (use Nx affected or Turborepo)
- No global installs in CI — use workspace scripts

## Documentation
- Each public package exports TypeDoc-compatible docs
- Breaking changes documented in CHANGELOG.md before merge
""",
    ),
]

# Index by name for fast lookup
_INDEX: dict[str, ConfigTemplate] = {t.name: t for t in _BUILTIN_TEMPLATES}


class TemplateRegistry:
    """Browse, search, and apply Claude Code configuration templates.

    Args:
        user_templates_dir: Directory for user-saved custom templates.
                            Defaults to ~/.harnesssync/templates/
    """

    def __init__(self, user_templates_dir: Path | None = None):
        self.user_templates_dir = user_templates_dir or (
            Path.home() / ".harnesssync" / "templates"
        )
        self._user_cache: list[ConfigTemplate] | None = None

    def _load_user_templates(self) -> list[ConfigTemplate]:
        """Load user-saved templates from disk."""
        if self._user_cache is not None:
            return self._user_cache

        templates = []
        if not self.user_templates_dir.exists():
            self._user_cache = templates
            return templates

        for path in sorted(self.user_templates_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                templates.append(ConfigTemplate(
                    name=data.get("name", path.stem),
                    title=data.get("title", path.stem),
                    description=data.get("description", ""),
                    tags=data.get("tags", []),
                    rules=data.get("rules", ""),
                    mcp_suggestions=data.get("mcp_suggestions", []),
                    settings_suggestions=data.get("settings_suggestions", {}),
                    author=data.get("author", "user"),
                    version=data.get("version", "1.0"),
                ))
            except (json.JSONDecodeError, KeyError):
                pass

        self._user_cache = templates
        return templates

    def list_all(self) -> list[ConfigTemplate]:
        """Return all built-in + user templates."""
        return _BUILTIN_TEMPLATES + self._load_user_templates()

    def search(self, query: str) -> list[ConfigTemplate]:
        """Search templates by name, title, description, or tag.

        Args:
            query: Search string (case-insensitive).

        Returns:
            Templates matching the query.
        """
        return [t for t in self.list_all() if t.matches(query)]

    def get(self, name: str) -> ConfigTemplate | None:
        """Get a template by exact name.

        Checks built-in templates first, then user templates.
        """
        if name in _INDEX:
            return _INDEX[name]
        for t in self._load_user_templates():
            if t.name == name:
                return t
        return None

    def list_by_tag(self, tag: str) -> list[ConfigTemplate]:
        """Return templates tagged with the given tag (case-insensitive)."""
        tag_lower = tag.lower()
        return [t for t in self.list_all() if any(
            tag_lower in t_tag.lower() for t_tag in t.tags
        )]

    def save_user_template(self, template: ConfigTemplate) -> Path:
        """Save a user-defined template to disk.

        Args:
            template: Template to save.

        Returns:
            Path to the saved file.
        """
        self.user_templates_dir.mkdir(parents=True, exist_ok=True)
        path = self.user_templates_dir / f"{template.name}.json"
        data = {
            "name": template.name,
            "title": template.title,
            "description": template.description,
            "tags": template.tags,
            "rules": template.rules,
            "mcp_suggestions": template.mcp_suggestions,
            "settings_suggestions": template.settings_suggestions,
            "author": template.author,
            "version": template.version,
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self._user_cache = None  # Invalidate cache
        return path

    def apply_to_claude_md(
        self,
        template: ConfigTemplate,
        claude_md_path: Path,
        mode: str = "append",
    ) -> str:
        """Apply a template's rules to CLAUDE.md.

        Args:
            template: Template to apply.
            claude_md_path: Path to CLAUDE.md.
            mode: "append" (add after existing) | "prepend" | "replace".

        Returns:
            New CLAUDE.md content.
        """
        current = claude_md_path.read_text(encoding="utf-8") if claude_md_path.exists() else ""
        marker = f"<!-- Applied from HarnessSync template: {template.name} -->"

        if mode == "replace":
            new_content = f"# Claude Code Configuration\n\n{template.rules}\n"
        elif mode == "prepend":
            new_content = f"{marker}\n{template.rules}\n\n{current}"
        else:
            # append
            sep = "\n\n" if current.strip() else ""
            new_content = current.rstrip() + sep + f"\n{marker}\n" + template.rules + "\n"

        claude_md_path.parent.mkdir(parents=True, exist_ok=True)
        claude_md_path.write_text(new_content, encoding="utf-8")
        return new_content

    def format_catalog(self, templates: list[ConfigTemplate] | None = None) -> str:
        """Format a readable catalog of templates.

        Args:
            templates: Templates to show (shows all if None).

        Returns:
            Multi-line catalog string.
        """
        templates = templates or self.list_all()
        if not templates:
            return "No templates found."

        lines = [
            f"HarnessSync Config Templates ({len(templates)} available)",
            "=" * 50,
            "",
        ]
        for t in templates:
            tags = ", ".join(t.tags[:5])
            lines.append(f"  {t.name:<30} {t.title}")
            lines.append(f"  {'':30} Tags: {tags}")
            lines.append(f"  {'':30} {t.description[:60]}")
            if t.mcp_suggestions:
                lines.append(f"  {'':30} MCP: {', '.join(t.mcp_suggestions)}")
            lines.append("")

        lines.append(f"Apply with: /sync-template apply <name>")
        lines.append(f"Search with: /sync-template search <query>")
        return "\n".join(lines)
