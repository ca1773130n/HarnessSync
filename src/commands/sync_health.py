from __future__ import annotations

"""
/sync-health slash command implementation.

Checks whether each target harness is installed, reachable, and functional.
Shows version info, detected capabilities, and known compatibility issues.
Distinguishes between "config files exist" and "harness is actually usable".
"""

import os
import shutil
import subprocess
import sys

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PLUGIN_ROOT)

from pathlib import Path
from src.adapters import AdapterRegistry


# Known CLI executables and version flags per target
_HARNESS_CLI_INFO: dict[str, dict] = {
    "codex": {
        "executables": ["codex"],
        "version_flag": "--version",
        "capabilities": ["rules", "skills", "agents", "commands", "mcp", "settings"],
    },
    "gemini": {
        "executables": ["gemini"],
        "version_flag": "--version",
        "capabilities": ["rules", "skills", "agents", "commands", "mcp", "settings"],
    },
    "opencode": {
        "executables": ["opencode", "opencode-cli"],
        "version_flag": "--version",
        "capabilities": ["rules", "skills", "agents", "commands", "mcp", "settings"],
    },
}


def _detect_executable(target: str) -> tuple[str | None, str | None]:
    """Find the CLI executable for a target and read its version.

    Returns:
        (executable_path, version_string) — either may be None if not found.
    """
    info = _HARNESS_CLI_INFO.get(target, {})
    for exe in info.get("executables", [target]):
        path = shutil.which(exe)
        if path:
            version = _get_version(path, info.get("version_flag", "--version"))
            return path, version
    return None, None


def _get_version(exe_path: str, flag: str) -> str | None:
    """Run ``exe_path flag`` and return first line of output, or None on failure."""
    try:
        result = subprocess.run(
            [exe_path, flag],
            capture_output=True,
            text=True,
            timeout=5,
        )
        output = (result.stdout or result.stderr or "").strip()
        return output.splitlines()[0] if output else None
    except Exception:
        return None


def _check_config_files(target: str, project_dir: Path) -> list[str]:
    """Return list of expected config file paths that actually exist."""
    found = []
    checks: dict[str, list[Path]] = {
        "codex": [
            project_dir / "AGENTS.md",
            project_dir / ".codex" / "config.toml",
        ],
        "gemini": [
            project_dir / "GEMINI.md",
            project_dir / ".gemini" / "settings.json",
        ],
        "opencode": [
            project_dir / "AGENTS.md",
            project_dir / "opencode.json",
        ],
    }
    for p in checks.get(target, []):
        if p.exists():
            found.append(str(p.relative_to(project_dir)))
    return found


def _format_target_health(
    target: str,
    exe_path: str | None,
    version: str | None,
    config_files: list[str],
) -> list[str]:
    """Format health check output for one target."""
    lines: list[str] = []
    installed = exe_path is not None

    status = "✓ installed" if installed else "✗ not found"
    lines.append(f"\n[{target.upper()}] {status}")

    if installed:
        lines.append(f"  Path:    {exe_path}")
        lines.append(f"  Version: {version or 'unknown'}")
    else:
        lines.append(f"  Install: check PATH or install '{target}' CLI")

    if config_files:
        lines.append(f"  Config:  {', '.join(config_files)}")
    else:
        lines.append("  Config:  no config files found (run /sync first)")

    caps = _HARNESS_CLI_INFO.get(target, {}).get("capabilities", [])
    lines.append(f"  Caps:    {', '.join(caps)}")

    return lines


_SUBCOMMANDS = {
    "status": "sync_status",
    "parity": "sync_parity",
}

_USAGE = """\
Usage: /sync-health [SUBCOMMAND] [OPTIONS]

Subcommands:
  (none)    Harness installation + config health dashboard (default)
  status    Sync status and drift detection (alias for /sync-status)
  parity    Feature parity report across targets (alias for /sync-parity)

Options (default subcommand):
  --score       Show config health score and recommendations
  --readiness   Show harness readiness checklist
  --skills      Show skill compatibility report
  --all         Show everything (default)
"""


def main() -> None:
    """Entry point for /sync-health command."""
    import shlex as _shlex
    args_str = " ".join(sys.argv[1:])
    tokens = _shlex.split(args_str) if args_str.strip() else []

    # Subcommand routing: /sync-health status [...] or /sync-health parity [...]
    if tokens and tokens[0] in _SUBCOMMANDS:
        subcommand = tokens.pop(0)
        sys.argv = [f"sync-{subcommand}"] + tokens
        module_name = _SUBCOMMANDS[subcommand]
        import importlib
        mod = importlib.import_module(f"src.commands.{module_name}")
        mod.main()
        return

    if "--help" in tokens or "-h" in tokens:
        print(_USAGE)
        return

    show_skills = "--skills" in tokens
    show_readiness = "--readiness" in tokens
    show_score = "--score" in tokens
    show_all = "--all" in tokens or (not show_skills and not show_readiness and not show_score)

    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd()))
    registered = AdapterRegistry.list_targets()

    print("HarnessSync Health Dashboard")
    print("=" * 60)
    print(f"Project: {project_dir}")

    any_missing = False

    for target in registered:
        exe_path, version = _detect_executable(target)
        config_files = _check_config_files(target, project_dir)
        lines = _format_target_health(target, exe_path, version, config_files)
        for line in lines:
            print(line)
        if exe_path is None:
            any_missing = True

    # New harness auto-detection hint
    try:
        from src.harness_detector import detect_new_harnesses
        new_harnesses = detect_new_harnesses(registered)
        if new_harnesses:
            print("\nNew harnesses detected in PATH (not yet configured):")
            for h in new_harnesses:
                print(f"  + {h}")
            print("  Run /sync-setup to add them.")
    except Exception:
        pass

    if any_missing:
        print(
            "\nTip: Missing harnesses will be skipped during sync. "
            "Install the CLI to enable sync."
        )
    else:
        print("\nAll configured harnesses are installed.")

    # --- Config Health Score ---
    if show_all or show_score:
        print()
        try:
            from src.source_reader import SourceReader
            from src.config_health import ConfigHealthChecker
            reader = SourceReader(scope="all", project_dir=project_dir)
            source_data = reader.discover_all()
            checker = ConfigHealthChecker()
            health_report = checker.check(source_data, project_dir)
            print(checker.format_report(health_report))
        except Exception as e:
            print(f"Config health check failed: {e}")

    # --- Harness Readiness Checklist ---
    if show_all or show_readiness:
        print()
        try:
            from src.harness_readiness import HarnessReadinessChecker
            readiness_checker = HarnessReadinessChecker()
            readiness_reports = readiness_checker.check_all_targets(project_dir)
            print(readiness_checker.format_report(readiness_reports))
        except Exception as e:
            print(f"Readiness check failed: {e}")

    # --- Skill Compatibility ---
    if show_all or show_skills:
        print()
        try:
            from src.source_reader import SourceReader
            from src.skill_compatibility import SkillCompatibilityChecker
            if 'source_data' not in dir():
                reader = SourceReader(scope="all", project_dir=project_dir)
                source_data = reader.discover_all()
            skills = source_data.get("skills", {})
            if skills:
                compat_checker = SkillCompatibilityChecker()
                compat_reports = compat_checker.check_all_skills(skills)
                print(compat_checker.format_report(compat_reports))
            else:
                print("Skill Compatibility: No skills found.")
        except Exception as e:
            print(f"Skill compatibility check failed: {e}")


if __name__ == "__main__":
    main()
