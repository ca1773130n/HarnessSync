from __future__ import annotations

"""Cross-harness snippet library.

A curated library of reusable CLAUDE.md rule snippets — each with a canonical
description and per-harness translations. Users pick snippets from the library;
HarnessSync handles format translation to each target.

Item 26: Cross-Harness Snippet Library.

Snippets are short, focused rule blocks (3-20 lines) on a single convention.
Each snippet has:
  - A canonical Claude Code markdown form (for CLAUDE.md)
  - Per-harness translations where the format differs
  - Tags for discovery (#testing, #style, #git, #security, ...)

Usage:
    library = SnippetLibrary()
    snippets = library.search("testing")
    for snippet in snippets:
        print(snippet.name, snippet.tags)

    # Get translation for a specific target
    rules_text = library.render("always-write-tests", target="gemini")

    # List all available snippets
    all_names = library.list_names()

    # Apply snippet to project CLAUDE.md (append if not already present)
    library.apply("always-write-tests", project_dir=Path("."))
"""

from dataclasses import dataclass, field
from pathlib import Path


# Known target names — snippet translations keyed by these names
_KNOWN_TARGETS = (
    "codex",
    "gemini",
    "opencode",
    "cursor",
    "aider",
    "windsurf",
    "cline",
    "continue",
    "zed",
    "neovim",
)


@dataclass
class Snippet:
    """A reusable rule snippet with cross-harness translations.

    Attributes:
        name: Unique slug identifier (e.g. "always-write-tests").
        title: Short human-readable title.
        description: One-line description of what this snippet enforces.
        tags: List of topic tags for search (e.g. ["testing", "quality"]).
        canonical: The canonical Claude Code CLAUDE.md markdown text.
        translations: Per-target overrides where format differs.
                      Targets not listed use ``canonical`` verbatim.
    """

    name: str
    title: str
    description: str
    tags: list[str]
    canonical: str
    translations: dict[str, str] = field(default_factory=dict)

    def render(self, target: str | None = None) -> str:
        """Return the snippet text for the given target.

        Falls back to canonical form if no target-specific translation exists.

        Args:
            target: Target harness name, or None for canonical form.

        Returns:
            Snippet text ready to append to a rules file.
        """
        if target and target in self.translations:
            return self.translations[target]
        return self.canonical

    def matches(self, query: str) -> bool:
        """Return True if query matches name, title, description, or tags."""
        q = query.lower()
        return (
            q in self.name.lower()
            or q in self.title.lower()
            or q in self.description.lower()
            or any(q in tag.lower() for tag in self.tags)
        )

    def already_present(self, content: str) -> bool:
        """Return True if this snippet's canonical marker is already in content.

        Uses a simple heuristic: checks if the first non-blank line of the
        canonical text appears in the content.
        """
        first_line = next(
            (ln for ln in self.canonical.splitlines() if ln.strip()), ""
        )
        return bool(first_line) and first_line in content


# ─────────────────────────────────────────────────────────────────────────────
# Built-in snippet library
# ─────────────────────────────────────────────────────────────────────────────

_BUILTIN_SNIPPETS: list[Snippet] = [
    Snippet(
        name="always-write-tests",
        title="Always Write Tests",
        description="Require tests for every new function or bug fix",
        tags=["testing", "quality", "tdd"],
        canonical="""\
## Testing

- Write tests for every new function and every bug fix before marking the task done
- Tests must pass before submitting any code change
- Prefer unit tests that cover the happy path AND at least one failure case
- Do not mock the database or external services unless explicitly instructed
""",
        translations={
            "aider": """\
# Testing

Always write tests for every new function and bug fix before finishing.
Tests must pass. Cover happy path and at least one failure case.
Do not mock the database unless explicitly instructed.
""",
            "codex": """\
## Testing

- Write tests for every new function and every bug fix
- Tests must pass before submitting
- Cover happy path and at least one failure case
- Do not mock the database unless explicitly instructed
""",
        },
    ),
    Snippet(
        name="conventional-commits",
        title="Conventional Commits",
        description="Enforce Conventional Commits format for all git commits",
        tags=["git", "commits", "style"],
        canonical="""\
## Git Commits

- Use Conventional Commits format: `type(scope): description`
- Valid types: feat, fix, docs, style, refactor, test, chore, perf
- Keep the subject line under 72 characters
- Reference issue numbers in the footer: `Closes #123`
""",
        translations={
            "aider": """\
# Git Commits

Use Conventional Commits: type(scope): description
Types: feat, fix, docs, style, refactor, test, chore, perf
Subject under 72 chars. Reference issues in footer: Closes #123
""",
        },
    ),
    Snippet(
        name="no-commented-code",
        title="No Commented-Out Code",
        description="Delete dead code rather than commenting it out",
        tags=["style", "quality", "cleanup"],
        canonical="""\
## Code Style — Dead Code

- Never comment out code and leave it in the file
- Delete dead code; git history preserves it if needed
- If code must be temporarily disabled, add a TODO with a ticket reference
""",
    ),
    Snippet(
        name="security-input-validation",
        title="Always Validate Input",
        description="Validate all external inputs at system boundaries",
        tags=["security", "validation", "owasp"],
        canonical="""\
## Security — Input Validation

- Validate all input at system boundaries (HTTP requests, CLI args, file reads)
- Never trust user-supplied data; sanitize before use in queries, shell commands, or templates
- Use parameterized queries — never string-interpolate SQL
- Escape output destined for HTML, JSON, or shell contexts
""",
    ),
    Snippet(
        name="no-hardcoded-secrets",
        title="No Hardcoded Secrets",
        description="Never hardcode API keys, passwords, or tokens in source code",
        tags=["security", "secrets", "credentials"],
        canonical="""\
## Security — Secrets

- Never hardcode API keys, passwords, tokens, or connection strings in source files
- Use environment variables or a secrets manager (e.g. Vault, AWS Secrets Manager)
- If you see a hardcoded secret, replace it with an env var reference immediately
- Add secrets patterns to .gitignore and .gitlexclude
""",
    ),
    Snippet(
        name="type-annotations",
        title="Always Add Type Annotations",
        description="Require type annotations on all function signatures",
        tags=["python", "typing", "style"],
        canonical="""\
## Python — Type Annotations

- Add type annotations to every function parameter and return type
- Use `from __future__ import annotations` at the top of every Python file
- Prefer `X | None` over `Optional[X]` (Python 3.10+ style)
- Run `mypy` or `pyright` on changed files before submitting
""",
        translations={
            "aider": """\
# Type Annotations (Python)

Add type annotations to all functions. Use `from __future__ import annotations`.
Prefer `X | None` over `Optional[X]`. Run mypy on changed files.
""",
        },
    ),
    Snippet(
        name="error-handling",
        title="Explicit Error Handling",
        description="Handle errors explicitly; never swallow exceptions silently",
        tags=["quality", "reliability", "errors"],
        canonical="""\
## Error Handling

- Never swallow exceptions silently with bare `except:` or `catch (e) {}`
- Log or re-raise every caught exception with context
- Distinguish between recoverable errors (retry/fallback) and fatal errors (re-raise)
- Add user-facing error messages that explain what went wrong and how to fix it
""",
    ),
    Snippet(
        name="small-functions",
        title="Small, Focused Functions",
        description="Keep functions under 40 lines with a single responsibility",
        tags=["style", "refactoring", "srp"],
        canonical="""\
## Code Style — Function Size

- Keep functions under 40 lines; extract helpers if longer
- Each function does exactly one thing (Single Responsibility Principle)
- Name functions with verbs that describe what they do, not how
- Prefer many small pure functions over one large stateful method
""",
    ),
    Snippet(
        name="dependency-injection",
        title="Use Dependency Injection",
        description="Inject dependencies rather than importing globals",
        tags=["architecture", "testing", "di"],
        canonical="""\
## Architecture — Dependency Injection

- Pass dependencies as constructor parameters or function arguments
- Never import global singletons inside function bodies
- This makes functions testable without patching internals
- Use interfaces/protocols to define dependency contracts
""",
    ),
    Snippet(
        name="documentation-comments",
        title="Document Public APIs",
        description="Add docstrings to all public functions, classes, and modules",
        tags=["docs", "style", "api"],
        canonical="""\
## Documentation

- Add docstrings to every public function, class, and module
- Include: one-line summary, Args section, Returns section, Raises section if applicable
- Keep examples in docstrings runnable (`doctest` style when possible)
- Update docstrings when the function behavior changes
""",
    ),
    Snippet(
        name="immutable-data",
        title="Prefer Immutable Data",
        description="Use immutable data structures where possible",
        tags=["functional", "style", "concurrency"],
        canonical="""\
## Code Style — Immutability

- Prefer immutable data: `const` over `let`, `tuple` over `list`, frozen dataclasses
- Avoid mutating function arguments; return new values instead
- Treat shared state as a last resort; prefer passing data through function parameters
""",
    ),
    Snippet(
        name="async-by-default",
        title="Async First for I/O",
        description="Use async/await for all I/O-bound operations",
        tags=["async", "performance", "python"],
        canonical="""\
## Async / Concurrency

- Use `async def` for all I/O-bound operations (HTTP, database, file system)
- Never call blocking I/O inside an async context without `asyncio.to_thread`
- Prefer `asyncio.gather()` for concurrent independent operations
- Do not `asyncio.run()` inside an already-running event loop
""",
    ),
    Snippet(
        name="review-before-merge",
        title="Require Review Before Merge",
        description="Always request a code review before merging to main",
        tags=["git", "process", "review"],
        canonical="""\
## Git Process

- Open a pull request for every change, even small ones
- Request at least one reviewer before merging to main
- Address all review comments before merging; do not dismiss without response
- Squash or rebase before merging to keep main history clean
""",
    ),
    Snippet(
        name="log-dont-print",
        title="Use Logger, Not Print",
        description="Use structured logging instead of print statements",
        tags=["logging", "observability", "style"],
        canonical="""\
## Logging

- Use the project logger (`from src.utils.logger import Logger`) instead of `print()`
- Log at the appropriate level: debug for tracing, info for state changes, warn for recoverable issues, error for failures
- Never log secrets, tokens, or user-identifying data
- Include structured context in log messages (e.g. `logger.info("sync done", target=target, items=n)`)
""",
        translations={
            "aider": """\
# Logging

Use the project logger, not print(). Choose levels: debug/info/warn/error.
Never log secrets. Include structured context in messages.
""",
        },
    ),
    Snippet(
        name="ci-must-pass",
        title="CI Must Pass Before Merge",
        description="Never merge if any CI check is failing",
        tags=["ci", "process", "quality"],
        canonical="""\
## CI / Continuous Integration

- CI must pass (green) before merging any pull request — no exceptions
- Do not use `--no-verify` or skip CI checks to push faster
- If CI is broken for reasons unrelated to your change, fix CI before merging
- Flaky tests must be quarantined and fixed, not ignored
""",
    ),
]


class SnippetLibrary:
    """Library of reusable cross-harness config rule snippets.

    Provides search, retrieval, and application of snippet rules that have
    known-good translations for all supported target harnesses.

    Args:
        extra_snippets: Additional Snippet objects to include alongside
                        the built-in library.
    """

    def __init__(self, extra_snippets: list[Snippet] | None = None) -> None:
        self._snippets: dict[str, Snippet] = {
            s.name: s for s in _BUILTIN_SNIPPETS
        }
        if extra_snippets:
            for s in extra_snippets:
                self._snippets[s.name] = s

    def list_names(self) -> list[str]:
        """Return sorted list of all snippet names."""
        return sorted(self._snippets.keys())

    def get(self, name: str) -> Snippet | None:
        """Return a snippet by name, or None if not found."""
        return self._snippets.get(name)

    def search(self, query: str) -> list[Snippet]:
        """Return snippets matching the query string.

        Matches against name, title, description, and tags (case-insensitive).

        Args:
            query: Search term.

        Returns:
            Matching snippets, sorted by name.
        """
        return sorted(
            (s for s in self._snippets.values() if s.matches(query)),
            key=lambda s: s.name,
        )

    def render(self, name: str, target: str | None = None) -> str | None:
        """Render a snippet for the given target harness.

        Args:
            name: Snippet name.
            target: Target harness (e.g. "codex", "gemini"). None = canonical.

        Returns:
            Rendered snippet text, or None if snippet not found.
        """
        snippet = self.get(name)
        if snippet is None:
            return None
        return snippet.render(target)

    def apply(
        self,
        name: str,
        project_dir: Path,
        target_file: str = "CLAUDE.md",
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Append a snippet to the project's CLAUDE.md if not already present.

        Args:
            name: Snippet name.
            project_dir: Project root directory.
            target_file: File to append to (default: CLAUDE.md).
            dry_run: If True, return what would be written without writing.

        Returns:
            (changed, message) where changed is True if the file was modified.
        """
        snippet = self.get(name)
        if snippet is None:
            return False, f"Snippet '{name}' not found in library."

        rules_file = project_dir / target_file
        existing = rules_file.read_text(encoding="utf-8") if rules_file.exists() else ""

        if snippet.already_present(existing):
            return False, f"Snippet '{name}' is already present in {target_file}."

        text_to_add = "\n" + snippet.canonical.rstrip("\n") + "\n"

        if dry_run:
            return True, f"[DRY RUN] Would append snippet '{name}' to {target_file}."

        with rules_file.open("a", encoding="utf-8") as fh:
            fh.write(text_to_add)

        return True, f"Snippet '{name}' appended to {target_file}."

    def format_catalog(self, tags: list[str] | None = None) -> str:
        """Return a human-readable catalog of available snippets.

        Args:
            tags: If provided, filter to snippets with at least one matching tag.

        Returns:
            Formatted string listing snippets with names, titles, and tags.
        """
        snippets = list(self._snippets.values())
        if tags:
            tag_set = {t.lower() for t in tags}
            snippets = [
                s for s in snippets
                if any(t.lower() in tag_set for t in s.tags)
            ]
        snippets.sort(key=lambda s: s.name)

        if not snippets:
            return "No snippets found."

        lines = [f"{'Name':<30} {'Title':<35} Tags"]
        lines.append("-" * 80)
        for s in snippets:
            tags_str = ", ".join(s.tags[:3])
            lines.append(f"{s.name:<30} {s.title:<35} {tags_str}")
        return "\n".join(lines)

    def portability_report(self, name: str) -> str:
        """Show which targets have custom translations vs use canonical form.

        Args:
            name: Snippet name.

        Returns:
            Formatted portability report string.
        """
        snippet = self.get(name)
        if snippet is None:
            return f"Snippet '{name}' not found."

        lines = [f"Portability report: {name}"]
        lines.append(f"  Title: {snippet.title}")
        lines.append(f"  Tags:  {', '.join(snippet.tags)}")
        lines.append("")
        for target in _KNOWN_TARGETS:
            if target in snippet.translations:
                lines.append(f"  {target:<12} custom translation")
            else:
                lines.append(f"  {target:<12} uses canonical form")
        return "\n".join(lines)
