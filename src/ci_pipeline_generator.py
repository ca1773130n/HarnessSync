from __future__ import annotations

"""CI/CD Sync Pipeline Generator — emit GitHub Actions workflow YAML.

Generates a ready-to-commit GitHub Actions workflow that auto-syncs
HarnessSync configs whenever CLAUDE.md or skills are committed to main.
Solves the team drift problem: changes pushed to the canonical config repo
are automatically propagated to every developer's harness configs via a
self-hosted runner or their own runner token.

Two workflow modes are supported:

  push-trigger (default):
    Runs on every push to main that touches CLAUDE.md, skills/**, or
    .harnesssync/**. Invokes ``python -m src.orchestrator sync`` on the runner.

  schedule-trigger:
    Runs on a cron schedule (default: every 6 hours).  Useful when the
    source of truth is an external CLAUDE.md that is pulled rather than
    pushed.

Usage::

    gen = CIPipelineGenerator(project_dir=Path("."))
    yaml_text = gen.generate()
    gen.write()   # writes to .github/workflows/harnesssync.yml
    print(gen.generate_summary())
"""

import textwrap
from dataclasses import dataclass, field
from pathlib import Path


# ──────────────────────────────────────────────────────────────────────────────
# Workflow templates
# ──────────────────────────────────────────────────────────────────────────────

_PUSH_TRIGGER_YAML = """\
name: HarnessSync — Auto Sync on Config Change

on:
  push:
    branches: ["{branch}"]
    paths:
      - "CLAUDE.md"
      - "skills/**"
      - ".harnesssync/**"
      - ".claude/CLAUDE.md"
      - ".claude/skills/**"

jobs:
  sync:
    name: Sync Claude Code config to all harnesses
    runs-on: {runner}
    timeout-minutes: 10

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "{python_version}"
          cache: pip

      - name: Install HarnessSync
        run: |
          pip install -e . --quiet
{extra_install}
      - name: Run HarnessSync
        env:{env_block}
          HARNESSSYNC_CI: "true"
        run: |
          python -m src.orchestrator sync --scope all --non-interactive
{commit_step}
"""

_SCHEDULE_TRIGGER_YAML = """\
name: HarnessSync — Scheduled Config Sync

on:
  schedule:
    - cron: "{cron}"
  workflow_dispatch: {{}}

jobs:
  sync:
    name: Sync Claude Code config on schedule
    runs-on: {runner}
    timeout-minutes: 10

    steps:
      - name: Checkout repository
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "{python_version}"
          cache: pip

      - name: Install HarnessSync
        run: |
          pip install -e . --quiet
{extra_install}
      - name: Run HarnessSync
        env:{env_block}
          HARNESSSYNC_CI: "true"
        run: |
          python -m src.orchestrator sync --scope all --non-interactive
{commit_step}
"""

_COMMIT_STEP = """\
      - name: Commit synced configs
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -A
          git diff --cached --quiet || git commit -m "chore: auto-sync harness configs [skip ci]"
          git push
"""

_ENV_LINE = "\n          {key}: ${{{{ secrets.{secret} }}}}"


@dataclass
class CIPipelineConfig:
    """Configuration for the generated workflow.

    Attributes:
        trigger: "push" | "schedule"
        branch: Branch to watch for push trigger (default: "main").
        cron: Cron expression for schedule trigger (default: every 6 hours).
        runner: GitHub Actions runner label (default: "ubuntu-latest").
        python_version: Python version string (default: "3.11").
        auto_commit: Whether to add a step that git-commits synced configs.
        secret_env_vars: Extra secrets to expose as env vars
                         (maps env-var-name -> GitHub secret name).
        extra_packages: Extra pip packages to install before sync.
    """

    trigger: str = "push"
    branch: str = "main"
    cron: str = "0 */6 * * *"
    runner: str = "ubuntu-latest"
    python_version: str = "3.11"
    auto_commit: bool = True
    secret_env_vars: dict[str, str] = field(default_factory=dict)
    extra_packages: list[str] = field(default_factory=list)


class CIPipelineGenerator:
    """Generate GitHub Actions workflow YAML for HarnessSync.

    Args:
        project_dir: Project root directory where .github/ lives.
        config: Pipeline configuration. Uses sensible defaults if None.
    """

    WORKFLOW_PATH = Path(".github/workflows/harnesssync.yml")

    def __init__(
        self,
        project_dir: Path | None = None,
        config: CIPipelineConfig | None = None,
    ):
        self.project_dir = project_dir or Path.cwd()
        self.config = config or CIPipelineConfig()

    # ──────────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────────

    def generate(self) -> str:
        """Generate the workflow YAML string.

        Returns:
            Full YAML content ready to write to disk.
        """
        cfg = self.config
        template = (
            _PUSH_TRIGGER_YAML if cfg.trigger == "push" else _SCHEDULE_TRIGGER_YAML
        )

        env_block = self._build_env_block(cfg.secret_env_vars)
        extra_install = self._build_extra_install(cfg.extra_packages)
        commit_step = _COMMIT_STEP if cfg.auto_commit else ""

        return template.format(
            branch=cfg.branch,
            cron=cfg.cron,
            runner=cfg.runner,
            python_version=cfg.python_version,
            env_block=env_block,
            extra_install=extra_install,
            commit_step=commit_step,
        )

    def write(self, overwrite: bool = False) -> Path:
        """Write the workflow YAML to .github/workflows/harnesssync.yml.

        Args:
            overwrite: If False (default), raises FileExistsError when the
                       file already exists so users don't lose customisations.

        Returns:
            Path to the written file.

        Raises:
            FileExistsError: If the file already exists and overwrite=False.
        """
        dest = self.project_dir / self.WORKFLOW_PATH
        if dest.exists() and not overwrite:
            raise FileExistsError(
                f"Workflow already exists at {dest}. "
                "Pass overwrite=True to replace it."
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(self.generate(), encoding="utf-8")
        return dest

    def generate_summary(self) -> str:
        """Return a human-readable summary of what will be generated.

        Returns:
            Multi-line summary string.
        """
        cfg = self.config
        lines = [
            "CI/CD Sync Pipeline — GitHub Actions Workflow",
            "=" * 50,
            "",
            f"  Trigger:         {cfg.trigger}",
        ]
        if cfg.trigger == "push":
            lines.append(f"  Branch:          {cfg.branch}")
            lines.append("  Watch paths:     CLAUDE.md, skills/**, .harnesssync/**")
        else:
            lines.append(f"  Schedule:        {cfg.cron}  (cron)")
        lines += [
            f"  Runner:          {cfg.runner}",
            f"  Python:          {cfg.python_version}",
            f"  Auto-commit:     {'yes' if cfg.auto_commit else 'no'}",
            "",
        ]
        if cfg.secret_env_vars:
            lines.append("  Secrets mapped:")
            for env_key, secret in cfg.secret_env_vars.items():
                lines.append(f"    {env_key} → secrets.{secret}")
            lines.append("")
        if cfg.extra_packages:
            lines.append(f"  Extra packages:  {', '.join(cfg.extra_packages)}")
            lines.append("")
        dest = self.project_dir / self.WORKFLOW_PATH
        lines.append(f"  Output:  {dest}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_env_block(secret_env_vars: dict[str, str]) -> str:
        """Build the ``env:`` block lines for the workflow step."""
        if not secret_env_vars:
            return ""
        lines = []
        for env_key, secret_name in sorted(secret_env_vars.items()):
            lines.append(f"\n          {env_key}: ${{{{ secrets.{secret_name} }}}}")
        return "".join(lines)

    @staticmethod
    def _build_extra_install(packages: list[str]) -> str:
        """Build the extra pip install line."""
        if not packages:
            return ""
        pkg_str = " ".join(packages)
        return f"          pip install {pkg_str} --quiet\n"

    # ──────────────────────────────────────────────────────────────────────────
    # Convenience constructors
    # ──────────────────────────────────────────────────────────────────────────

    @classmethod
    def for_push_trigger(
        cls,
        project_dir: Path | None = None,
        branch: str = "main",
        runner: str = "ubuntu-latest",
        auto_commit: bool = True,
    ) -> "CIPipelineGenerator":
        """Create a generator configured for push-triggered sync."""
        return cls(
            project_dir=project_dir,
            config=CIPipelineConfig(
                trigger="push",
                branch=branch,
                runner=runner,
                auto_commit=auto_commit,
            ),
        )

    @classmethod
    def for_schedule_trigger(
        cls,
        project_dir: Path | None = None,
        cron: str = "0 */6 * * *",
        runner: str = "ubuntu-latest",
    ) -> "CIPipelineGenerator":
        """Create a generator configured for scheduled sync."""
        return cls(
            project_dir=project_dir,
            config=CIPipelineConfig(
                trigger="schedule",
                cron=cron,
                runner=runner,
                auto_commit=False,  # Schedule runs usually just run, not commit
            ),
        )


def detect_existing_workflow(project_dir: Path) -> dict:
    """Check whether a HarnessSync workflow already exists in the project.

    Args:
        project_dir: Project root directory.

    Returns:
        Dict with keys:
          - "exists" (bool): True if the file was found.
          - "path" (Path | None): Absolute path to the workflow file.
          - "trigger" (str): "push" | "schedule" | "unknown" if file exists.
    """
    workflow_path = project_dir / CIPipelineGenerator.WORKFLOW_PATH
    if not workflow_path.exists():
        return {"exists": False, "path": None, "trigger": "none"}

    try:
        content = workflow_path.read_text(encoding="utf-8")
    except OSError:
        return {"exists": True, "path": workflow_path, "trigger": "unknown"}

    if "push:" in content and "paths:" in content:
        trigger = "push"
    elif "schedule:" in content:
        trigger = "schedule"
    else:
        trigger = "unknown"

    return {"exists": True, "path": workflow_path, "trigger": trigger}
