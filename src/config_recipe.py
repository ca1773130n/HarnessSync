from __future__ import annotations

"""Config Recipe Marketplace (item 15).

A curated library of role-based config starters that users can install
with one command.  Each recipe includes CLAUDE.md rules, recommended
skill patterns, and harness-specific notes.

Built-in recipes
----------------
``python-backend``  Python / FastAPI / Django development workflow
``react-frontend``  React / TypeScript front-end development
``ml-researcher``   Machine-learning research (Jupyter, PyTorch, HF)
``devops``          Infrastructure / CI-CD / cloud operations
``general``         Sensible baseline for any project

Usage::

    from src.config_recipe import RecipeRegistry

    reg = RecipeRegistry()
    print(reg.list_recipes())

    recipe = reg.get("python-backend")
    print(recipe.format_preview())
    applied = reg.apply(recipe, target_path=Path("CLAUDE.md"), dry_run=True)
"""

import re
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ConfigRecipe:
    """A named config starter with rules, skill hints, and harness notes."""

    id: str
    name: str
    description: str
    tags: List[str] = field(default_factory=list)

    # CLAUDE.md section content to inject
    rules: str = ""

    # Suggested skill names (informational — not auto-created)
    recommended_skills: List[str] = field(default_factory=list)

    # Per-harness tips (e.g. "aider: add --watch flag")
    harness_notes: Dict[str, str] = field(default_factory=dict)

    def format_preview(self, width: int = 72) -> str:
        """Return a human-readable preview of the recipe."""
        sep = "─" * width
        lines = [
            f"Recipe: {self.name}  [{self.id}]",
            sep,
            self.description,
            "",
            "Rules preview:",
            textwrap.indent(self.rules[:600] + ("…" if len(self.rules) > 600 else ""), "  "),
        ]
        if self.recommended_skills:
            lines += ["", f"Recommended skills: {', '.join(self.recommended_skills)}"]
        if self.harness_notes:
            lines += ["", "Harness-specific notes:"]
            for harness, note in sorted(self.harness_notes.items()):
                lines.append(f"  {harness}: {note}")
        return "\n".join(lines)


@dataclass
class ApplyResult:
    """Result of applying a recipe to a CLAUDE.md file."""

    recipe_id: str
    target_path: Path
    dry_run: bool
    inserted_lines: int = 0
    already_present: bool = False
    error: str = ""

    def format(self) -> str:
        if self.error:
            return f"[ERROR] {self.error}"
        if self.already_present:
            return f"Recipe '{self.recipe_id}' is already present in {self.target_path}."
        if self.dry_run:
            return (
                f"[dry-run] Would insert {self.inserted_lines} lines from recipe "
                f"'{self.recipe_id}' into {self.target_path}."
            )
        return (
            f"Applied recipe '{self.recipe_id}': inserted {self.inserted_lines} lines "
            f"into {self.target_path}."
        )


# ---------------------------------------------------------------------------
# Built-in recipes
# ---------------------------------------------------------------------------

_PYTHON_BACKEND = ConfigRecipe(
    id="python-backend",
    name="Python Backend Dev",
    description="Rules for Python API / backend development (FastAPI, Django, Flask, SQLAlchemy).",
    tags=["python", "backend", "api", "fastapi", "django"],
    rules=textwrap.dedent("""\
        ## Python Backend Rules

        - Use type hints on all public functions and class attributes.
        - Prefer `pathlib.Path` over `os.path` string operations.
        - Never commit secrets or credentials; use environment variables.
        - Write pytest tests for every new public function; use fixtures, not globals.
        - Handle errors explicitly — no bare `except:` clauses.
        - Use `async`/`await` for I/O-bound operations; keep CPU-bound work synchronous.
        - Pin direct dependencies in `requirements.txt`; keep transitive deps in `uv.lock`.
        - Database queries must be parameterised — no f-string SQL.
        - Log with structured JSON at INFO level; use DEBUG for diagnostic detail.
        - Keep each module under 400 lines; split into sub-packages if larger.
    """),
    recommended_skills=["commit", "test-runner", "lint"],
    harness_notes={
        "aider": "Add `--read pyproject.toml` so Aider understands project layout.",
        "cursor": "Enable `.cursor/rules/python.mdc` for Python-specific autocomplete hints.",
    },
)

_REACT_FRONTEND = ConfigRecipe(
    id="react-frontend",
    name="React / TypeScript Frontend",
    description="Rules for React + TypeScript front-end projects (Vite, Next.js, Tailwind).",
    tags=["react", "typescript", "frontend", "nextjs", "vite"],
    rules=textwrap.dedent("""\
        ## React / TypeScript Frontend Rules

        - Use functional components with hooks; avoid class components.
        - All props must have TypeScript types; prefer `interface` over `type` for objects.
        - Co-locate component tests with the component file (`Button.test.tsx`).
        - Never use `any`; use `unknown` and narrow with type guards instead.
        - CSS: prefer Tailwind utility classes; avoid inline `style={{}}` for layout.
        - State: use `useState`/`useReducer` for local; Zustand or Context for shared state.
        - Async data fetching: use React Query or SWR — no raw `useEffect` for fetches.
        - Accessibility: every interactive element needs an `aria-label` or visible label.
        - Bundle: keep individual chunks under 200 KB gzipped; use dynamic imports.
        - Images: use `next/image` or `<img loading="lazy">` with explicit dimensions.
    """),
    recommended_skills=["commit", "lint", "component-gen"],
    harness_notes={
        "cursor": "Add `.cursor/rules/react.mdc` for JSX/TSX snippet acceleration.",
        "windsurf": "Enable TypeScript strict mode in Windsurf settings for better inference.",
    },
)

_ML_RESEARCHER = ConfigRecipe(
    id="ml-researcher",
    name="ML / AI Researcher",
    description="Rules for machine-learning research workflows (Jupyter, PyTorch, HuggingFace).",
    tags=["ml", "ai", "pytorch", "jupyter", "huggingface", "research"],
    rules=textwrap.dedent("""\
        ## ML / AI Research Rules

        - Pin exact versions for `torch`, `transformers`, and CUDA libraries in `requirements.txt`.
        - Never hardcode paths to datasets or model checkpoints — use config files or env vars.
        - Reproduce experiments: set random seeds (Python, NumPy, PyTorch) at the top of each script.
        - Log hyperparameters and metrics with MLflow or Weights & Biases — no ad-hoc print statements.
        - Large model weights (>10 MB) must not be committed to git; add to `.gitignore`.
        - Notebooks: clear cell output before committing; use `nbstripout` pre-commit hook.
        - Prefer vectorised operations (NumPy/torch) over Python loops over tensors.
        - Document dataset preprocessing steps explicitly in a README or DATASHEET.md.
        - GPU memory: call `torch.cuda.empty_cache()` between evaluation runs in notebooks.
        - Evaluation: report mean ± std over at least 3 random seeds.
    """),
    recommended_skills=["experiment-log", "notebook-clean"],
    harness_notes={
        "aider": "Use `--model gpt-4o` for code-heavy ML tasks; `--model o1` for math proofs.",
        "codex": "Add `DATASETS_PATH` to your `.env` so Codex can reference dataset locations.",
    },
)

_DEVOPS = ConfigRecipe(
    id="devops",
    name="DevOps / Platform Engineering",
    description="Rules for infrastructure, CI/CD, and cloud operations (Terraform, Docker, k8s).",
    tags=["devops", "terraform", "docker", "kubernetes", "ci", "cloud"],
    rules=textwrap.dedent("""\
        ## DevOps / Platform Engineering Rules

        - Infrastructure as Code: all cloud resources defined in Terraform or Pulumi — no manual console changes.
        - Docker: multi-stage builds only; final image must not contain build tools or source code.
        - Secrets: never in env files, Dockerfiles, or CI YAML — use Vault, AWS Secrets Manager, or SOPS.
        - CI pipelines: every PR must pass lint, unit test, and security scan before merge.
        - Kubernetes: all deployments must have resource `requests` and `limits` set.
        - Rollback plan required for every production change; document in the PR description.
        - Monitoring: new services must have a health-check endpoint and be added to the on-call dashboard.
        - Terraform: run `terraform plan` in CI; require manual approval before `apply` to prod.
        - Log retention: production logs must be retained for at least 90 days.
        - Least privilege: IAM roles/service accounts must have only the permissions they need.
    """),
    recommended_skills=["terraform-plan", "docker-build", "helm-diff"],
    harness_notes={
        "aider": "Add `.aider.conf.yml` with `read: [\"*.tf\", \"*.yaml\"]` for full IaC context.",
        "codex": "Include your cloud provider SDK docs URL in AGENTS.md for better completions.",
    },
)

_GENERAL = ConfigRecipe(
    id="general",
    name="General Purpose",
    description="Sensible baseline rules for any software project.",
    tags=["general", "baseline"],
    rules=textwrap.dedent("""\
        ## General Development Rules

        - Read existing code before modifying it; understand the pattern before extending it.
        - Prefer editing existing files over creating new ones.
        - Write clear commit messages: one subject line, optional body explaining *why*.
        - Never commit commented-out code or debugging print statements.
        - Validate all user inputs at system boundaries; trust internal code.
        - Keep functions small and focused — one responsibility per function.
        - Add error handling at system boundaries (user input, external APIs), not everywhere.
        - Use the project's existing patterns and naming conventions.
        - When uncertain, ask rather than guess.
    """),
    recommended_skills=["commit", "test-runner"],
    harness_notes={},
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_BUILTIN_RECIPES: List[ConfigRecipe] = [
    _PYTHON_BACKEND,
    _REACT_FRONTEND,
    _ML_RESEARCHER,
    _DEVOPS,
    _GENERAL,
]


class RecipeRegistry:
    """Registry of available config recipes with install support.

    Args:
        extra_recipes: Additional :class:`ConfigRecipe` objects to register
                       alongside the built-ins.
    """

    def __init__(self, extra_recipes: Optional[List[ConfigRecipe]] = None) -> None:
        self._recipes: Dict[str, ConfigRecipe] = {r.id: r for r in _BUILTIN_RECIPES}
        for r in (extra_recipes or []):
            self._recipes[r.id] = r

    def list_recipes(self, tag: Optional[str] = None) -> str:
        """Return a formatted list of available recipes.

        Args:
            tag: Optional tag to filter by (e.g. ``"python"``).

        Returns:
            Multi-line string table.
        """
        recipes = list(self._recipes.values())
        if tag:
            recipes = [r for r in recipes if tag.lower() in r.tags]

        if not recipes:
            return f"No recipes found{f' matching tag {tag!r}' if tag else ''}."

        lines = [
            "Available Config Recipes",
            "=" * 55,
            f"  {'ID':<20} {'Name':<28} Tags",
            f"  {'─' * 20} {'─' * 28} {'─' * 20}",
        ]
        for r in sorted(recipes, key=lambda x: x.id):
            tag_str = ", ".join(r.tags[:4])
            lines.append(f"  {r.id:<20} {r.name:<28} {tag_str}")
        lines.append("")
        lines.append("Install with: /sync-recipe install <ID>")
        return "\n".join(lines)

    def get(self, recipe_id: str) -> Optional[ConfigRecipe]:
        """Return a recipe by ID, or None if not found."""
        return self._recipes.get(recipe_id)

    def apply(
        self,
        recipe: ConfigRecipe,
        target_path: Path,
        dry_run: bool = False,
        append: bool = True,
    ) -> ApplyResult:
        """Apply a recipe's rules to a CLAUDE.md file.

        Inserts the recipe's rules block if a marker for this recipe ID is
        not already present.  A ``<!-- recipe:<id> -->`` HTML comment is
        used as a marker so re-runs are idempotent.

        Args:
            recipe:      The recipe to apply.
            target_path: Path to the CLAUDE.md (or any Markdown config file).
            dry_run:     If True, only calculate what would change; don't write.
            append:      If True, append rules to the end of the file; otherwise
                         insert after the first top-level heading.

        Returns:
            :class:`ApplyResult` describing the outcome.
        """
        marker = f"<!-- recipe:{recipe.id} -->"

        # Check if recipe already applied
        existing = ""
        if target_path.is_file():
            try:
                existing = target_path.read_text(encoding="utf-8")
            except OSError as exc:
                return ApplyResult(
                    recipe_id=recipe.id,
                    target_path=target_path,
                    dry_run=dry_run,
                    error=str(exc),
                )

        if marker in existing:
            return ApplyResult(
                recipe_id=recipe.id,
                target_path=target_path,
                dry_run=dry_run,
                already_present=True,
            )

        # Build the block to insert
        block = f"\n{marker}\n{recipe.rules.rstrip()}\n<!-- /recipe:{recipe.id} -->\n"
        block_lines = block.count("\n")

        if dry_run:
            return ApplyResult(
                recipe_id=recipe.id,
                target_path=target_path,
                dry_run=True,
                inserted_lines=block_lines,
            )

        # Write
        try:
            if append or not existing:
                new_content = existing.rstrip("\n") + "\n" + block
            else:
                # Insert after first H1 heading line
                lines = existing.splitlines(keepends=True)
                insert_at = 0
                for i, line in enumerate(lines):
                    if re.match(r"^#\s+", line):
                        insert_at = i + 1
                        break
                lines.insert(insert_at, block)
                new_content = "".join(lines)

            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            return ApplyResult(
                recipe_id=recipe.id,
                target_path=target_path,
                dry_run=False,
                error=str(exc),
            )

        return ApplyResult(
            recipe_id=recipe.id,
            target_path=target_path,
            dry_run=False,
            inserted_lines=block_lines,
        )
