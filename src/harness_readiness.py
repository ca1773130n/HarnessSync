from __future__ import annotations

"""Harness readiness checklist.

Before syncing to a target, generate a checklist of prerequisites:
is the harness installed, is the CLI on PATH, does the config directory exist,
are required env vars set? Output missing items as actionable steps.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ReadinessCheck:
    """A single readiness check result."""
    name: str
    passed: bool
    message: str
    action: str = ""  # Actionable fix if failed


@dataclass
class TargetReadinessReport:
    """Readiness report for a single target harness."""
    target: str
    checks: list[ReadinessCheck] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        """Return True if all required checks pass."""
        return all(c.passed for c in self.checks if c.name.startswith("required:"))

    @property
    def all_pass(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failed(self) -> list[ReadinessCheck]:
        return [c for c in self.checks if not c.passed]


# Target configurations: name -> {cli_executables, config_dirs, env_vars}
TARGET_CONFIGS: dict[str, dict] = {
    "codex": {
        "cli": ["codex"],
        "config_dirs": [Path.home() / ".codex"],
        "env_vars": [],
        "description": "OpenAI Codex CLI",
        "install_hint": "npm install -g @openai/codex",
    },
    "gemini": {
        "cli": ["gemini"],
        "config_dirs": [Path.home() / ".gemini"],
        "env_vars": ["GEMINI_API_KEY"],
        "description": "Google Gemini CLI",
        "install_hint": "npm install -g @google/gemini-cli",
    },
    "opencode": {
        "cli": ["opencode", "opencode-cli"],
        "config_dirs": [Path.home() / ".config" / "opencode"],
        "env_vars": [],
        "description": "OpenCode CLI",
        "install_hint": "npm install -g opencode-ai",
    },
    "cursor": {
        "cli": ["cursor"],
        "config_dirs": [],  # Cursor is primarily an IDE, not CLI
        "env_vars": [],
        "description": "Cursor IDE",
        "install_hint": "Download from https://cursor.sh",
    },
    "aider": {
        "cli": ["aider"],
        "config_dirs": [],
        "env_vars": ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        "description": "Aider AI coding assistant",
        "install_hint": "pip install aider-chat",
    },
    "windsurf": {
        "cli": ["windsurf"],
        "config_dirs": [Path.home() / ".codeium" / "windsurf"],
        "env_vars": [],
        "description": "Windsurf (Codeium) IDE",
        "install_hint": "Download from https://codeium.com/windsurf",
    },
}


class HarnessReadinessChecker:
    """Checks prerequisites for syncing to target harnesses."""

    def check_target(self, target: str, project_dir: Path) -> TargetReadinessReport:
        """Run readiness checks for a single target.

        Args:
            target: Target name (codex, gemini, etc.)
            project_dir: Project root directory

        Returns:
            TargetReadinessReport with all check results
        """
        report = TargetReadinessReport(target=target)
        config = TARGET_CONFIGS.get(target)

        if not config:
            report.checks.append(ReadinessCheck(
                name="required:known_target",
                passed=False,
                message=f"Unknown target '{target}'",
                action=f"Supported targets: {', '.join(TARGET_CONFIGS.keys())}",
            ))
            return report

        # Check 1: CLI on PATH
        cli_found = False
        for cli in config.get("cli", []):
            if shutil.which(cli):
                cli_found = True
                report.checks.append(ReadinessCheck(
                    name="required:cli_on_path",
                    passed=True,
                    message=f"CLI found: {cli} ({shutil.which(cli)})",
                ))
                break

        if not cli_found and config.get("cli"):
            cli_list = " or ".join(config["cli"])
            report.checks.append(ReadinessCheck(
                name="required:cli_on_path",
                passed=False,
                message=f"CLI not found on PATH: {cli_list}",
                action=config.get("install_hint", f"Install {config['description']}"),
            ))

        # Check 2: Config directories
        for config_dir in config.get("config_dirs", []):
            if config_dir.exists():
                report.checks.append(ReadinessCheck(
                    name="config_dir",
                    passed=True,
                    message=f"Config directory exists: {config_dir}",
                ))
            else:
                report.checks.append(ReadinessCheck(
                    name="config_dir",
                    passed=False,
                    message=f"Config directory missing: {config_dir}",
                    action=f"Run {target} once to initialize its config directory",
                ))

        # Check 3: Required environment variables
        for env_var in config.get("env_vars", []):
            val = os.environ.get(env_var, "")
            if val:
                report.checks.append(ReadinessCheck(
                    name=f"env:{env_var}",
                    passed=True,
                    message=f"Environment variable set: {env_var}",
                ))
            else:
                report.checks.append(ReadinessCheck(
                    name=f"env:{env_var}",
                    passed=False,
                    message=f"Environment variable not set: {env_var}",
                    action=f"Set {env_var} in your shell profile or .env file",
                ))

        # Check 4: Project-level config writability
        if project_dir.exists():
            report.checks.append(ReadinessCheck(
                name="project_writable",
                passed=os.access(project_dir, os.W_OK),
                message=f"Project directory writable: {project_dir}",
                action=f"Check permissions on {project_dir}",
            ))

        return report

    def check_all_targets(self, project_dir: Path) -> list[TargetReadinessReport]:
        """Check readiness for all registered targets.

        Args:
            project_dir: Project root directory

        Returns:
            List of TargetReadinessReport for each registered target
        """
        from src.adapters import AdapterRegistry
        targets = AdapterRegistry.list_targets()
        return [self.check_target(t, project_dir) for t in targets]

    def format_report(self, reports: list[TargetReadinessReport]) -> str:
        """Format readiness reports as human-readable text.

        Args:
            reports: List of reports from check_all_targets()

        Returns:
            Formatted report string
        """
        lines: list[str] = []
        lines.append("Harness Readiness Checklist")
        lines.append("=" * 60)
        lines.append("")

        for report in reports:
            cfg = TARGET_CONFIGS.get(report.target, {})
            desc = cfg.get("description", report.target)
            status = "READY" if report.all_pass else ("OK (partial)" if report.ready else "NOT READY")
            lines.append(f"[{status}] {report.target.upper()}  ({desc})")

            for check in report.checks:
                symbol = "✓" if check.passed else "✗"
                lines.append(f"  {symbol} {check.message}")
                if not check.passed and check.action:
                    lines.append(f"    → {check.action}")

            lines.append("")

        return "\n".join(lines)
