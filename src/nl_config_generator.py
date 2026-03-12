from __future__ import annotations

"""Natural language to HarnessSync config generator.

Accepts plain-English descriptions of desired AI assistant behavior and
generates the appropriate CLAUDE.md rules, adapted for each target harness.

Example inputs:
    "Avoid console.log, always use structured logging"
    "Never suggest synchronous file I/O in Python, prefer async"
    "All SQL queries must use parameterized statements, no string formatting"

The generator uses pattern matching against a library of behavior categories
to produce concrete rule text without requiring an LLM call — making it
fast, offline-capable, and deterministic.

Generated rules are formatted as HarnessSync-compatible CLAUDE.md sections
with harness-specific annotations where behavior differs.
"""

import re
from dataclasses import dataclass, field


# ──────────────────────────────────────────────────────────────────────────────
# Behavior pattern library
# Each entry maps intent keywords → rule templates + harness notes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class BehaviorRule:
    """A generated config rule from a natural-language description."""
    category: str          # Category tag (e.g. "logging", "security")
    title: str             # Short human-readable title
    rule_text: str         # The actual rule text for CLAUDE.md
    harness_notes: dict[str, str] = field(default_factory=dict)
    # harness_notes: target -> extra note for that harness (e.g. "Codex: enforced via lint hook")
    confidence: str = "high"   # "high" | "medium" | "low"

    def to_claude_md_block(self) -> str:
        """Format as a CLAUDE.md rule block."""
        lines = [f"## {self.title}", "", self.rule_text.strip()]
        if self.harness_notes:
            lines.append("")
            for harness, note in sorted(self.harness_notes.items()):
                lines.append(f"<!-- harness:{harness} -->")
                lines.append(f"Note: {note}")
                lines.append(f"<!-- /harness:{harness} -->")
        return "\n".join(lines)


# Pattern entries: (keywords_regex, BehaviorRule factory)
# Matching is done case-insensitively on the user's input.
_PATTERNS: list[tuple[re.Pattern, BehaviorRule]] = []


def _register(pattern: str, rule: BehaviorRule) -> None:
    _PATTERNS.append((re.compile(pattern, re.IGNORECASE), rule))


# Logging rules
_register(
    r"console\.log|structured.log|no.log.state|avoid.log",
    BehaviorRule(
        category="logging",
        title="Structured Logging Only",
        rule_text=(
            "- Never use `console.log()` for application logging.\n"
            "- Use the project's structured logger (e.g. `logger.info()`, `logger.error()`).\n"
            "- Log messages must include context fields (e.g. `{requestId, userId}`).\n"
            "- Debug-only logs should be gated with `if (process.env.LOG_LEVEL === 'debug')`."
        ),
        harness_notes={
            "cursor": "Enforced via ESLint rule `no-console` in .cursor/rules/",
            "aider": "Add `no-console-log` to CONVENTIONS.md lint section",
        },
        confidence="high",
    ),
)

# SQL injection prevention
_register(
    r"sql|parameterized|no.string.format|injection|prepared.statement",
    BehaviorRule(
        category="security",
        title="SQL Parameterized Queries Required",
        rule_text=(
            "- Never construct SQL queries using string formatting or concatenation.\n"
            "- Always use parameterized queries / prepared statements.\n"
            "- Use the ORM's query builder for dynamic conditions; never interpolate user data.\n"
            "- Flag any raw SQL strings that contain f-string interpolation as a security issue."
        ),
        confidence="high",
    ),
)

# Async I/O
_register(
    r"async.io|synchronous.file|async.file|no.sync|avoid.blocking",
    BehaviorRule(
        category="performance",
        title="Async I/O — No Synchronous Blocking Calls",
        rule_text=(
            "- Never use synchronous file I/O (`fs.readFileSync`, `open()` in async context).\n"
            "- Always use async equivalents (`fs.promises.readFile`, `aiofiles`, `asyncio.to_thread`).\n"
            "- Flag any `await` missing on async function calls as a bug.\n"
            "- Database queries must be async — no blocking ORM calls in async request handlers."
        ),
        harness_notes={
            "aider": "Add async-io rules to CONVENTIONS.md under Performance section",
        },
        confidence="high",
    ),
)

# Error handling
_register(
    r"error.handling|catch.all|never.swallow|log.error|rethrow",
    BehaviorRule(
        category="reliability",
        title="Error Handling — No Silent Failures",
        rule_text=(
            "- Never swallow exceptions silently (`except: pass`, empty catch blocks).\n"
            "- Always log errors with sufficient context before handling or rethrowing.\n"
            "- Re-throw unexpected errors — only catch what you can meaningfully handle.\n"
            "- User-facing errors must map to friendly messages; internal details go to logs only."
        ),
        confidence="high",
    ),
)

# Type hints / typing
_register(
    r"type.hint|type.annotation|typed|no.any|strict.type",
    BehaviorRule(
        category="code-quality",
        title="Strict Type Annotations Required",
        rule_text=(
            "- All function signatures must include parameter and return type annotations.\n"
            "- Use `from __future__ import annotations` at the top of every Python file.\n"
            "- Avoid `Any` type — use `Union`, `Optional`, or `TypeVar` where ambiguous.\n"
            "- Run `mypy --strict` to validate — type errors are blocking issues."
        ),
        confidence="high",
    ),
)

# Testing / TDD
_register(
    r"test|tdd|coverage|unit.test|always.test|write.test",
    BehaviorRule(
        category="testing",
        title="Test-Driven Development",
        rule_text=(
            "- Write tests before implementation (TDD red-green-refactor cycle).\n"
            "- Every new function or class must have at least one unit test.\n"
            "- Target ≥80% line coverage; new code must not reduce overall coverage.\n"
            "- Tests must be deterministic — no random seeds, no time-dependent assertions."
        ),
        harness_notes={
            "codex": "Run `npm test` or `pytest` after every implementation step",
            "gemini": "Run test suite before marking any task complete",
        },
        confidence="high",
    ),
)

# Security / secrets
_register(
    r"secret|credential|api.key|no.hardcode|env.var",
    BehaviorRule(
        category="security",
        title="No Hardcoded Secrets",
        rule_text=(
            "- Never hardcode API keys, passwords, tokens, or credentials in source files.\n"
            "- Load secrets exclusively from environment variables or a secrets manager.\n"
            "- Flag any string matching a secret pattern (32+ char alphanumeric) as a finding.\n"
            "- `.env` files must be in `.gitignore` — never commit them."
        ),
        confidence="high",
    ),
)

# Code comments / documentation
_register(
    r"comment|document|docstring|rationale|explain.why",
    BehaviorRule(
        category="documentation",
        title="Comments Must Explain Why, Not What",
        rule_text=(
            "- Write comments to explain *why* non-obvious decisions were made, not *what* the code does.\n"
            "- Every public function must have a docstring with Args/Returns/Raises.\n"
            "- Keep comments up-to-date — outdated comments are worse than no comments.\n"
            "- TODOs must include an owner and issue reference: `# TODO(alice): see #123`."
        ),
        confidence="medium",
    ),
)

# Performance / optimization
_register(
    r"performance|n\+1|batch|pagination|cache|avoid.loop",
    BehaviorRule(
        category="performance",
        title="Performance — Avoid N+1 and Unbounded Queries",
        rule_text=(
            "- Never issue queries inside loops — batch or use JOIN/IN instead.\n"
            "- Paginate all list endpoints — never return unbounded result sets.\n"
            "- Cache expensive computations; invalidate on relevant state changes.\n"
            "- Measure before optimizing — include a benchmark or profiling note with perf changes."
        ),
        confidence="high",
    ),
)

# Accessibility
_register(
    r"accessib|aria|a11y|screen.reader|alt.text",
    BehaviorRule(
        category="accessibility",
        title="Accessibility (a11y) Requirements",
        rule_text=(
            "- All interactive elements must have ARIA labels or accessible text.\n"
            "- Images must have meaningful `alt` attributes (empty string for decorative images).\n"
            "- Color alone must not convey information — pair with text or icons.\n"
            "- Run `axe` or `pa11y` in CI — accessibility failures are blocking."
        ),
        confidence="medium",
    ),
)

# Dependency management
_register(
    r"depend|package|import|no.new.dep|lock.file",
    BehaviorRule(
        category="dependencies",
        title="Dependency Management",
        rule_text=(
            "- Do not add new dependencies without a comment explaining the rationale.\n"
            "- Prefer stdlib or existing dependencies over new packages.\n"
            "- Always commit lock files (package-lock.json, uv.lock, go.sum).\n"
            "- Flag transitive dependency license changes as requiring review."
        ),
        confidence="medium",
    ),
)


# Git workflow rules
_register(
    r"git|commit|branch|pr|pull.request|merge|rebase",
    BehaviorRule(
        category="git",
        title="Git Workflow Standards",
        rule_text=(
            "- Use conventional commit messages: feat/fix/chore/docs/test/refactor.\n"
            "- One logical change per commit — do not bundle unrelated changes.\n"
            "- Never force-push to main/master without explicit instruction.\n"
            "- Prefer rebase over merge for integrating upstream changes."
        ),
        harness_notes={
            "aider": "Aider generates its own commit messages — conventional commit "
                     "format rules have limited effect; add --commit-prompt for control",
            "cursor": "Cursor does not manage git commits natively",
        },
        confidence="high",
    ),
)

# Package manager restrictions
_register(
    r"npm|yarn|pnpm|pip|uv|poetry|package.manager|install.package",
    BehaviorRule(
        category="package_management",
        title="Package Manager Restrictions",
        rule_text=(
            "- Always use the project's established package manager (check package.json "
            "or pyproject.toml for the lock file to identify it).\n"
            "- Never mix package managers in the same project.\n"
            "- Propose new dependencies before installing — do not install silently.\n"
            "- Prefer pinned versions over floating ranges for production dependencies."
        ),
        confidence="high",
    ),
)

# File creation restrictions
_register(
    r"no.new.file|don.t.create|avoid.creat|create.only.when|new.file",
    BehaviorRule(
        category="file_management",
        title="File Creation Policy",
        rule_text=(
            "- Prefer editing existing files over creating new ones.\n"
            "- Do not create new files unless explicitly required by the task.\n"
            "- When creating a new file, explain the rationale in the commit message.\n"
            "- Never create markdown stub files or placeholder READMEs unless asked."
        ),
        confidence="high",
    ),
)

# Environment variables
_register(
    r"env.var|environment.variable|\.env|dotenv|never.hardcode.key|no.hardcode",
    BehaviorRule(
        category="env_vars",
        title="Environment Variable Usage",
        rule_text=(
            "- Never hardcode API keys, passwords, or tokens — use environment variables.\n"
            "- Reference secrets via `process.env.VAR_NAME` or equivalent for the language.\n"
            "- Do not commit `.env` files — keep them in `.gitignore`.\n"
            "- Add required env vars to `.env.example` with placeholder values."
        ),
        confidence="high",
    ),
)

# Code review / PR readiness
_register(
    r"code.review|pr.ready|pull.request.ready|review.checklist|before.commit",
    BehaviorRule(
        category="code_review",
        title="Pre-Commit / PR Readiness",
        rule_text=(
            "- Run linter and formatter before committing (`npm run lint`, `ruff check`).\n"
            "- Ensure all tests pass locally before creating a PR.\n"
            "- Self-review the diff for unintended changes before pushing.\n"
            "- Link the PR to the relevant issue or ticket."
        ),
        confidence="medium",
    ),
)

# API design
_register(
    r"api.design|rest.api|endpoint|versioning|backwards.compat|breaking.change",
    BehaviorRule(
        category="api_design",
        title="API Design Standards",
        rule_text=(
            "- Follow RESTful conventions: GET for reads, POST for creates, "
            "PUT/PATCH for updates, DELETE for removes.\n"
            "- Version APIs via URL prefix (`/v1/`) or header — never remove versions "
            "without a deprecation period.\n"
            "- Return consistent error shapes: `{error: string, code: string}`.\n"
            "- Document breaking changes explicitly before implementing."
        ),
        confidence="medium",
    ),
)

# Database / migrations
_register(
    r"database|migration|schema|sql|query|orm|never.drop|no.drop",
    BehaviorRule(
        category="database",
        title="Database and Migration Safety",
        rule_text=(
            "- Never run destructive migrations (DROP TABLE, DELETE without WHERE) "
            "without explicit instruction.\n"
            "- All schema changes must have a corresponding migration file.\n"
            "- Prefer additive migrations — add columns rather than modify existing ones.\n"
            "- Test migrations against a copy of production data before merging."
        ),
        confidence="high",
    ),
)

# Monorepo / workspace awareness
_register(
    r"monorepo|workspace|package.boundary|cross.package|shared.lib",
    BehaviorRule(
        category="monorepo",
        title="Monorepo Boundaries",
        rule_text=(
            "- Do not import across package boundaries without updating "
            "the dependency declarations.\n"
            "- Shared logic belongs in the designated shared package — "
            "do not duplicate it in consumers.\n"
            "- Changes to shared packages require review from all consuming teams.\n"
            "- Run workspace-wide lint/test after any shared package change."
        ),
        confidence="medium",
    ),
)

# Docker / containerization
_register(
    r"docker|container|dockerfile|image|compose|k8s|kubernetes|pod",
    BehaviorRule(
        category="containerization",
        title="Container and Docker Standards",
        rule_text=(
            "- Use multi-stage Dockerfiles to minimize final image size.\n"
            "- Never run processes as root inside containers — use a non-root USER.\n"
            "- Pin base image digests or exact version tags — never use `latest`.\n"
            "- Do not store secrets in Docker images or environment declarations "
            "in docker-compose.yml; use a secrets manager or `.env` file excluded from VCS."
        ),
        harness_notes={
            "aider": "Add container security rules to CONVENTIONS.md under DevOps section",
        },
        confidence="high",
    ),
)

# Input validation / sanitization
_register(
    r"input.valid|validate.input|sanitize|user.input|never.trust|untrusted",
    BehaviorRule(
        category="input_validation",
        title="Input Validation at System Boundaries",
        rule_text=(
            "- Validate and sanitize all user-supplied input at the system boundary "
            "(API handler, form field, CLI argument) before processing.\n"
            "- Reject invalid input with a 400/422 response and a descriptive error message "
            "— never silently truncate or coerce bad data.\n"
            "- Use an established validation library (zod, pydantic, joi) — "
            "do not write custom regex validators for well-known formats.\n"
            "- Never pass raw user input to shell commands, SQL queries, or dynamic code execution."
        ),
        confidence="high",
    ),
)

# Rate limiting / throttling
_register(
    r"rate.limit|throttle|backoff|retry|exponential|429|too.many.request",
    BehaviorRule(
        category="resilience",
        title="Rate Limiting and Retry with Backoff",
        rule_text=(
            "- All outbound API calls must implement retry logic with "
            "exponential backoff and jitter.\n"
            "- Respect `Retry-After` headers from upstream services; "
            "never hammer a 429-returning endpoint.\n"
            "- Set a maximum retry count (≤ 5) and surface a clear error "
            "after exhausting retries.\n"
            "- Implement per-user rate limits on inbound endpoints to prevent abuse."
        ),
        confidence="high",
    ),
)

# Internationalization / i18n
_register(
    r"i18n|internationali|locali|translation|locale|multi.language",
    BehaviorRule(
        category="i18n",
        title="Internationalization (i18n) Standards",
        rule_text=(
            "- Never hardcode user-visible strings — route all text through "
            "the i18n translation layer.\n"
            "- Store locale files in the designated `locales/` or `i18n/` directory.\n"
            "- Use ICU message format for plurals and gendered strings.\n"
            "- Test UI with a pseudo-locale (e.g. `en-XA`) to catch hardcoded strings."
        ),
        confidence="medium",
    ),
)

# Observability / tracing
_register(
    r"observ|opentelemetry|otel|instrument|monitor",
    BehaviorRule(
        category="observability",
        title="Observability and Distributed Tracing",
        rule_text=(
            "- Propagate trace context (W3C TraceContext headers) across all "
            "service boundaries.\n"
            "- Emit structured log events with `traceId` and `spanId` fields.\n"
            "- Record key business metrics (request count, latency p99, error rate) "
            "using the project's metrics library.\n"
            "- Every external I/O call must be wrapped in a span — "
            "do not create spans for pure in-process computation."
        ),
        harness_notes={
            "aider": "Add observability requirements to CONVENTIONS.md under Architecture",
        },
        confidence="medium",
    ),
)

# Concurrency / thread safety
_register(
    r"thread.safe|concurren|race.condition|mutex|atomic|shared.state",
    BehaviorRule(
        category="concurrency",
        title="Thread Safety and Concurrency",
        rule_text=(
            "- Protect shared mutable state with locks or use immutable data structures.\n"
            "- Prefer message-passing (queues, channels) over shared memory for "
            "cross-thread communication.\n"
            "- Document which class members require external synchronization.\n"
            "- Use `threading.local()` or async-context-var equivalents for "
            "per-request state — never use module-level mutable globals."
        ),
        confidence="high",
    ),
)


# ──────────────────────────────────────────────────────────────────────────────
# Generator
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class GenerationResult:
    """Result of natural language config generation."""
    matched_rules: list[BehaviorRule]
    unmatched_phrases: list[str]
    claude_md_block: str

    @property
    def matched_count(self) -> int:
        return len(self.matched_rules)

    def format_summary(self) -> str:
        lines = [
            f"Generated {self.matched_count} rule(s) from your description.",
            "",
        ]
        for rule in self.matched_rules:
            lines.append(f"  [{rule.category}] {rule.title}  ({rule.confidence} confidence)")
        if self.unmatched_phrases:
            lines.append("")
            lines.append("Could not generate rules for:")
            for phrase in self.unmatched_phrases:
                lines.append(f"  - {phrase!r}")
            lines.append(
                "\nTip: Be specific — e.g. 'avoid console.log' instead of 'better logging'."
            )
        return "\n".join(lines)


class NLConfigGenerator:
    """Convert plain-English behavior descriptions into CLAUDE.md rule blocks.

    Usage:
        gen = NLConfigGenerator()
        result = gen.generate("avoid console.log and always use parameterized SQL")
        print(result.claude_md_block)
    """

    def generate(self, description: str) -> GenerationResult:
        """Generate config rules from a natural-language description.

        Splits the description on conjunctions and sentence boundaries, then
        matches each fragment against the pattern library. Returns all matching
        rules plus a combined CLAUDE.md block.

        Args:
            description: Free-text description of desired AI assistant behavior.

        Returns:
            GenerationResult with matched rules and formatted CLAUDE.md text.
        """
        # Split into fragments for multi-intent descriptions
        fragments = re.split(r"[.;,]|\band\b|\balso\b", description, flags=re.IGNORECASE)
        fragments = [f.strip() for f in fragments if f.strip()]

        matched_rules: list[BehaviorRule] = []
        matched_categories: set[str] = set()
        unmatched: list[str] = []

        for fragment in fragments:
            found = False
            for pattern, rule in _PATTERNS:
                if rule.category in matched_categories:
                    continue  # Deduplicate by category
                if pattern.search(fragment):
                    matched_rules.append(rule)
                    matched_categories.add(rule.category)
                    found = True
                    break
            if not found:
                unmatched.append(fragment)

        # Also try the full description against each pattern (catches multi-word matches)
        for pattern, rule in _PATTERNS:
            if rule.category in matched_categories:
                continue
            if pattern.search(description):
                matched_rules.append(rule)
                matched_categories.add(rule.category)

        # Build CLAUDE.md block
        blocks: list[str] = []
        if matched_rules:
            blocks.append(
                "<!-- Generated by HarnessSync NL Config Generator -->\n"
                "<!-- Edit as needed. These rules sync to all configured harnesses. -->"
            )
            for rule in matched_rules:
                blocks.append(rule.to_claude_md_block())

        claude_md_block = "\n\n".join(blocks)

        # Remove fragments that were actually matched
        unmatched_final = [
            f for f in unmatched
            if not any(p.search(f) for p, r in _PATTERNS)
        ]

        return GenerationResult(
            matched_rules=matched_rules,
            unmatched_phrases=unmatched_final,
            claude_md_block=claude_md_block,
        )

    def list_categories(self) -> list[str]:
        """Return all supported behavior categories."""
        seen: set[str] = set()
        cats: list[str] = []
        for _, rule in _PATTERNS:
            if rule.category not in seen:
                cats.append(rule.category)
                seen.add(rule.category)
        return cats

    def parse_exclusion(self, description: str) -> dict:
        """Parse a natural-language exclusion/inclusion rule into a .harnesssync config dict.

        Converts plain-English sync control statements into the structured config
        format accepted by .harnesssync, eliminating the need for users to learn
        the config schema for common customizations.

        Supported patterns:
        - "never sync MCP servers to Aider"
          → {"skip_sections": {"aider": ["mcp"]}}
        - "only sync security rules to Cursor"
          → {"tag_filter": {"cursor": {"include_tags": ["security"]}}}
        - "exclude rules from Codex"
          → {"skip_sections": {"codex": ["rules"]}}
        - "never sync to Aider"
          → {"skip_targets": ["aider"]}
        - "only sync to Gemini and Codex"
          → {"only_targets": ["gemini", "codex"]}
        - "skip MCP for all targets"
          → {"skip_sections": ["mcp"]}

        Args:
            description: Plain-English exclusion/inclusion description.

        Returns:
            Dict compatible with .harnesssync config format. Returns empty dict
            if no pattern matches.
        """
        text = description.lower().strip()

        # Known section aliases → canonical section names
        _SECTION_ALIASES: dict[str, str] = {
            "mcp": "mcp", "mcp servers": "mcp", "mcp server": "mcp",
            "rules": "rules", "rule": "rules",
            "skills": "skills", "skill": "skills",
            "agents": "agents", "agent": "agents",
            "commands": "commands", "command": "commands",
            "settings": "settings", "setting": "settings",
        }

        # Known harness aliases → canonical target names
        _TARGET_ALIASES: dict[str, str] = {
            "aider": "aider", "codex": "codex", "gemini": "gemini",
            "opencode": "opencode", "cursor": "cursor",
            "windsurf": "windsurf", "cline": "cline",
            "continue": "continue", "zed": "zed", "neovim": "neovim",
        }

        def _find_section(t: str) -> str | None:
            for alias, canonical in _SECTION_ALIASES.items():
                if alias in t:
                    return canonical
            return None

        def _find_targets(t: str) -> list[str]:
            found = []
            for alias, canonical in _TARGET_ALIASES.items():
                if alias in t:
                    found.append(canonical)
            return found

        # Pattern: "never sync to <target>" / "skip <target>"
        if re.search(r"never sync to|skip all|exclude all targets|no targets", text):
            targets = _find_targets(text)
            if targets:
                return {"skip_targets": targets}

        # Pattern: "only sync to <targets>"
        if re.search(r"only sync to|only target|restrict to", text):
            targets = _find_targets(text)
            if targets:
                return {"only_targets": targets}

        # Pattern: "never sync <section> to <target>" / "exclude <section> from <target>"
        if re.search(r"never sync .+ to|exclude .+ from|skip .+ for|don.t sync .+ to", text):
            section = _find_section(text)
            targets = _find_targets(text)
            if section and targets:
                result: dict = {"skip_sections": {}}
                for target in targets:
                    result["skip_sections"][target] = [section]
                return result
            if section:
                return {"skip_sections": [section]}

        # Pattern: "only sync <section> to <target>"
        if re.search(r"only sync .+ to|only .+ for|restrict .+ to", text):
            section = _find_section(text)
            targets = _find_targets(text)
            if section and targets:
                return {"only_sections": {t: [section] for t in targets}}
            if section:
                return {"only_sections": [section]}

        # Pattern: "skip <section>" / "exclude <section>" (global)
        if re.search(r"^(?:skip|exclude|never sync|omit|no)\s+\w", text):
            section = _find_section(text)
            if section:
                return {"skip_sections": [section]}

        # Pattern: "only <section>" (global)
        if re.search(r"^only\s+\w", text):
            section = _find_section(text)
            if section:
                return {"only_sections": [section]}

        return {}

    def parse_exclusion_to_harnesssync(self, description: str, project_dir=None) -> str:
        """Parse NL exclusion and format as .harnesssync JSON snippet.

        Convenience wrapper that returns the config as a formatted JSON string
        suitable for appending/merging into the project's .harnesssync file.

        Args:
            description: Plain-English exclusion description.
            project_dir: If provided, attempts to merge with existing config.

        Returns:
            JSON string with the exclusion config, or empty string if no match.
        """
        import json
        config = self.parse_exclusion(description)
        if not config:
            return ""
        return json.dumps(config, indent=2)

    def query_sync_state(
        self,
        question: str,
        project_dir: "Path | None" = None,
        cc_home: "Path | None" = None,
    ) -> str:
        """Answer a natural-language question about the current sync state.

        Users can ask questions like:
          - "which MCP servers are available in Gemini?"
          - "what rules didn't sync to Codex and why?"
          - "which harnesses support skills?"
          - "is file-system MCP synced to Cursor?"

        Answers are derived from static config analysis (no LLM call needed).

        Args:
            question: Plain-English question about sync state.
            project_dir: Project root directory.
            cc_home: Claude Code config home (default: ~/.claude).

        Returns:
            Human-readable answer string.
        """
        from pathlib import Path as _Path

        text = question.lower().strip()

        # Dispatch to the right query handler based on keywords
        if any(k in text for k in ("mcp", "server", "servers")):
            return self._query_mcp(text, project_dir, cc_home)

        if any(k in text for k in ("rule", "rules", "section", "sections")):
            return self._query_rules(text, project_dir, cc_home)

        if any(k in text for k in ("skill", "skills")):
            return self._query_skills(text, project_dir, cc_home)

        if any(k in text for k in ("support", "supports", "compatible", "compatibility")):
            return self._query_compatibility(text, project_dir, cc_home)

        if any(k in text for k in ("sync to", "synced to", "available in", "available on")):
            return self._query_availability(text, project_dir, cc_home)

        if any(k in text for k in ("agent", "agents")):
            return self._query_agents(text, project_dir, cc_home)

        if any(k in text for k in ("command", "commands", "slash")):
            return self._query_commands(text, project_dir, cc_home)

        if any(k in text for k in ("categor", "behavior", "pattern", "rule type")):
            return self._query_categories()

        return (
            "I couldn't interpret that question. Try asking:\n"
            "  - 'which MCP servers are available in Gemini?'\n"
            "  - 'what rules didn't sync to Codex?'\n"
            "  - 'which harnesses support skills?'\n"
            "  - 'which harnesses support agents?'\n"
            "  - 'which commands synced to Cursor?'\n"
            "  - 'what behavior categories are available?'\n"
            "  - 'is <server-name> synced to Cursor?'"
        )

    def _query_mcp(self, text: str, project_dir, cc_home) -> str:
        """Answer questions about MCP server sync state."""
        from pathlib import Path as _Path

        # Determine which harness the user is asking about
        _TARGET_ALIASES = {
            "aider": "aider", "codex": "codex", "gemini": "gemini",
            "opencode": "opencode", "cursor": "cursor",
            "windsurf": "windsurf", "cline": "cline",
            "continue": "continue", "zed": "zed", "neovim": "neovim",
        }
        target = next((v for k, v in _TARGET_ALIASES.items() if k in text), None)

        try:
            from src.source_reader import SourceReader
            reader = SourceReader(
                scope="user",
                project_dir=_Path(project_dir) if project_dir else _Path.cwd(),
                cc_home=_Path(cc_home) if cc_home else None,
            )
            data = reader.read_all()
            mcp_servers = data.get("mcp", {})
        except Exception as e:
            return f"Could not read MCP config: {e}"

        if not mcp_servers:
            return "No MCP servers found in your Claude Code config."

        # Harness MCP support levels
        from src.harness_comparison import _FEATURE_SUPPORT
        mcp_support = _FEATURE_SUPPORT.get("mcp", {})

        if target:
            support = mcp_support.get(target, "none")
            if support == "none":
                return (
                    f"{target.title()} does not support MCP servers.\n"
                    f"MCP configs will not be synced to {target}."
                )
            server_names = list(mcp_servers.keys()) if isinstance(mcp_servers, dict) else []
            if not server_names:
                return f"No MCP servers configured (would sync {len(mcp_servers)} to {target})."
            lines = [f"MCP servers available in {target.title()} ({support} support):"]
            for name in server_names:
                lines.append(f"  ✓ {name}")
            if support == "partial":
                lines.append(f"\n  Note: {target} has partial MCP support — some fields may be omitted.")
            return "\n".join(lines)

        # General: show all harnesses and their MCP support
        server_names = list(mcp_servers.keys()) if isinstance(mcp_servers, dict) else []
        lines = [f"MCP Servers ({len(server_names)} configured):"]
        for name in server_names:
            lines.append(f"  {name}")
        lines.append("\nSupport by harness:")
        for harness, level in sorted(mcp_support.items()):
            icon = {"full": "✓", "partial": "~", "none": "✗"}.get(level, "?")
            lines.append(f"  {icon} {harness:<14} {level}")
        return "\n".join(lines)

    def _query_rules(self, text: str, project_dir, cc_home) -> str:
        """Answer questions about rule sync state."""
        from pathlib import Path as _Path
        _TARGET_ALIASES = {
            "aider": "aider", "codex": "codex", "gemini": "gemini",
            "opencode": "opencode", "cursor": "cursor", "windsurf": "windsurf",
        }
        target = next((v for k, v in _TARGET_ALIASES.items() if k in text), None)

        try:
            from src.source_reader import SourceReader
            reader = SourceReader(
                scope="all",
                project_dir=_Path(project_dir) if project_dir else _Path.cwd(),
                cc_home=_Path(cc_home) if cc_home else None,
            )
            data = reader.read_all()
            rules = data.get("rules", {})
        except Exception as e:
            return f"Could not read rules config: {e}"

        rule_count = len(rules) if isinstance(rules, dict) else (1 if rules else 0)

        if "didn't" in text or "did not" in text or "not sync" in text or "missing" in text:
            if target:
                # Rules that have sync tags excluding this target
                try:
                    from src.sync_filter import filter_rules_for_target
                    if isinstance(rules, dict):
                        filtered = {k: v for k, v in rules.items()
                                    if filter_rules_for_target(str(v), target)}
                        excluded_count = rule_count - len(filtered)
                        if excluded_count == 0:
                            return f"All {rule_count} rules are synced to {target}."
                        return (
                            f"{excluded_count} rule(s) excluded from {target} by sync tags.\n"
                            f"{len(filtered)} rule(s) will be synced."
                        )
                except ImportError:
                    pass
            return f"Could not determine excluded rules for '{target}'."

        lines = [f"Rules summary: {rule_count} rule file(s) configured."]
        if target:
            lines.append(f"All rules sync to {target} (full support).")
        else:
            lines.append("Rules sync to: codex, gemini, opencode, cursor, aider, windsurf (all targets, full support).")
        return "\n".join(lines)

    def _query_skills(self, text: str, project_dir, cc_home) -> str:
        """Answer questions about skill sync state."""
        from src.harness_comparison import _FEATURE_SUPPORT
        skill_support = _FEATURE_SUPPORT.get("skills", {})
        lines = ["Skill support by harness:"]
        for harness, level in sorted(skill_support.items()):
            icon = {"full": "✓", "partial": "~", "none": "✗"}.get(level, "?")
            lines.append(f"  {icon} {harness:<14} {level}")
        return "\n".join(lines)

    def _query_compatibility(self, text: str, project_dir, cc_home) -> str:
        """Answer general compatibility questions."""
        from src.harness_comparison import _FEATURE_SUPPORT
        lines = ["Feature support matrix:"]
        features = list(_FEATURE_SUPPORT.keys())
        targets = sorted({t for f in _FEATURE_SUPPORT.values() for t in f})
        col = max(8, max(len(t) for t in targets) + 1)
        header = f"  {'Feature':<12}" + "".join(f"{t:^{col}}" for t in targets)
        lines.append(header)
        lines.append("  " + "-" * (12 + col * len(targets)))
        icons = {"full": "✓", "partial": "~", "none": "✗"}
        for feature in features:
            row = f"  {feature:<12}"
            for t in targets:
                row += f"{icons.get(_FEATURE_SUPPORT[feature].get(t, 'none'), '?'):^{col}}"
            lines.append(row)
        lines.append("\n  ✓=full  ~=partial  ✗=not supported")
        return "\n".join(lines)

    def _query_availability(self, text: str, project_dir, cc_home) -> str:
        """Answer 'is X available in Y?' style questions."""
        # Try to extract what they're asking about
        _TARGET_ALIASES = {
            "aider": "aider", "codex": "codex", "gemini": "gemini",
            "opencode": "opencode", "cursor": "cursor", "windsurf": "windsurf",
        }
        target = next((v for k, v in _TARGET_ALIASES.items() if k in text), None)
        if not target:
            return "Please specify a harness (e.g. 'available in Gemini')."

        from src.harness_comparison import _FEATURE_SUPPORT
        lines = [f"Feature availability in {target.title()}:"]
        for feature, support_map in sorted(_FEATURE_SUPPORT.items()):
            level = support_map.get(target, "none")
            icon = {"full": "✓", "partial": "~", "none": "✗"}.get(level, "?")
            lines.append(f"  {icon} {feature:<12} {level}")
        return "\n".join(lines)

    def _query_agents(self, text: str, project_dir, cc_home) -> str:
        """Answer questions about agent sync state per harness."""
        from src.harness_comparison import _FEATURE_SUPPORT
        agent_support = _FEATURE_SUPPORT.get("agents", {})

        _TARGET_ALIASES = {
            "aider": "aider", "codex": "codex", "gemini": "gemini",
            "opencode": "opencode", "cursor": "cursor", "windsurf": "windsurf",
        }
        target = next((v for k, v in _TARGET_ALIASES.items() if k in text), None)

        if target:
            level = agent_support.get(target, "none")
            icon = {"full": "✓", "partial": "~", "none": "✗"}.get(level, "?")
            notes = {
                "gemini": "Agent tool bindings are dropped; agent text is inlined into GEMINI.md.",
                "codex": "Agents are inlined into AGENTS.md (no separate agent files).",
                "opencode": "Agents written as OpenCode project files.",
                "cursor": "Agents inlined as .mdc rule blocks in .cursor/rules/.",
                "aider": "Agents have no Aider equivalent — skipped during sync.",
                "windsurf": "Agents inlined as .windsurfrules sections.",
            }
            note = notes.get(target, "")
            lines = [f"{icon} {target.title()} agent support: {level}"]
            if note:
                lines.append(f"  Note: {note}")
            return "\n".join(lines)

        lines = ["Agent support by harness:"]
        for harness, level in sorted(agent_support.items()):
            icon = {"full": "✓", "partial": "~", "none": "✗"}.get(level, "?")
            lines.append(f"  {icon} {harness:<14} {level}")
        return "\n".join(lines)

    def _query_commands(self, text: str, project_dir, cc_home) -> str:
        """Answer questions about slash command sync state per harness."""
        from pathlib import Path as _Path
        from src.harness_comparison import _FEATURE_SUPPORT
        command_support = _FEATURE_SUPPORT.get("commands", {})

        _TARGET_ALIASES = {
            "aider": "aider", "codex": "codex", "gemini": "gemini",
            "opencode": "opencode", "cursor": "cursor", "windsurf": "windsurf",
        }
        target = next((v for k, v in _TARGET_ALIASES.items() if k in text), None)

        # Try to get actual command count from source
        command_count: int | None = None
        try:
            from src.source_reader import SourceReader
            reader = SourceReader(
                scope="all",
                project_dir=_Path(project_dir) if project_dir else _Path.cwd(),
                cc_home=_Path(cc_home) if cc_home else None,
            )
            data = reader.read_all()
            commands = data.get("commands", {})
            command_count = len(commands) if isinstance(commands, dict) else None
        except Exception:
            pass

        count_str = f"{command_count} command(s) configured" if command_count is not None else "commands"

        if target:
            level = command_support.get(target, "none")
            icon = {"full": "✓", "partial": "~", "none": "✗"}.get(level, "?")
            notes = {
                "gemini": "Slash commands converted to plain GEMINI.md instruction blocks.",
                "codex": "Slash commands have no direct Codex equivalent; converted to AGENTS.md notes.",
                "opencode": "Commands have no direct OpenCode equivalent.",
                "cursor": "Commands written as .mdc rule blocks.",
                "aider": "Commands have no Aider equivalent — skipped.",
                "windsurf": "Commands have no Windsurf equivalent — skipped.",
            }
            note = notes.get(target, "")
            lines = [f"{icon} {target.title()} command support: {level} ({count_str})"]
            if note:
                lines.append(f"  Note: {note}")
            return "\n".join(lines)

        lines = [f"Command support by harness ({count_str}):"]
        for harness, level in sorted(command_support.items()):
            icon = {"full": "✓", "partial": "~", "none": "✗"}.get(level, "?")
            lines.append(f"  {icon} {harness:<14} {level}")
        return "\n".join(lines)

    def _query_categories(self) -> str:
        """List all available NL behavior categories."""
        cats = self.list_categories()
        lines = ["Available behavior categories for NL config generation:"]
        for cat in cats:
            lines.append(f"  · {cat}")
        lines.append(
            "\nUse these in plain-English descriptions, e.g. "
            "'enforce async I/O and rate limiting rules'."
        )
        return "\n".join(lines)
