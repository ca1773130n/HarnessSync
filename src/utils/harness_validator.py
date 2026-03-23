from __future__ import annotations

"""Lightweight smoke test for harness binaries after sync.

After writing initial config for a new harness, probe the harness binary
to confirm it loaded the config path and report any errors.
"""

import subprocess
import shutil
from pathlib import Path


# Per-harness probe: (binary, args, expected_fragment_in_output)
# expected_fragment is checked case-insensitively against combined stdout+stderr
_PROBE_COMMANDS: dict[str, tuple[str, list[str], str]] = {
    "codex":    ("codex",    ["--version"],                     "codex"),
    "gemini":   ("gemini",   ["--version"],                     "gemini"),
    "opencode": ("opencode", ["--version"],                     "opencode"),
    "cursor":   ("cursor",   ["--version"],                     "cursor"),
    "aider":    ("aider",    ["--version"],                     "aider"),
    "windsurf": ("windsurf", ["--version"],                     "windsurf"),
    "cline":    ("code",     ["--list-extensions"],             "cline"),
    "continue": ("code",     ["--list-extensions"],             "continue"),
    "zed":      ("zed",      ["--version"],                     "zed"),
    "neovim":   ("nvim",     ["--version"],                     "neovim"),
}

# Config paths that the harness should have received (used for path check)
_CONFIG_PATH_INDICATORS: dict[str, list[str]] = {
    "codex":    ["AGENTS.md", ".codex/AGENTS.md"],
    "gemini":   [".gemini/GEMINI.md"],
    "opencode": [".opencode/AGENTS.md", ".opencode/opencode.json"],
    "cursor":   [".cursor/rules/"],
    "aider":    ["CONVENTIONS.md", ".aider.conf.yml"],
    "windsurf": [".windsurfrules"],
    "cline":    [".clinerules"],
    "continue": [".continue/rules/"],
    "zed":      [".rules"],
    "neovim":   [".avante/rules/"],
}


class HarnessValidator:
    """Smoke-tests a harness binary after initial config is written."""

    def validate(self, harness: str, project_dir: Path) -> dict:
        """Run a lightweight probe of the harness binary.

        Returns a dict with:
          - success: bool
          - binary_found: bool
          - version: str | None
          - config_present: bool
          - message: str
          - errors: list[str]
        """
        result: dict = {
            "success": False,
            "binary_found": False,
            "version": None,
            "config_present": False,
            "message": "",
            "errors": [],
        }

        if harness not in _PROBE_COMMANDS:
            result["message"] = f"No probe defined for harness '{harness}'."
            result["success"] = True  # not an error, just no probe
            return result

        binary, args, expected_fragment = _PROBE_COMMANDS[harness]

        # Check binary exists
        binary_path = shutil.which(binary)
        if not binary_path:
            result["errors"].append(f"Binary '{binary}' not found in PATH.")
            result["message"] = f"Harness '{harness}' binary not found — config written but harness not installed."
            return result

        result["binary_found"] = True

        # Run version probe
        try:
            proc = subprocess.run(
                [binary] + args,
                capture_output=True,
                text=True,
                timeout=10,
            )
            combined = (proc.stdout + proc.stderr).lower()
            if expected_fragment.lower() in combined or proc.returncode == 0:
                # Extract first non-empty line as version string
                for line in (proc.stdout + proc.stderr).splitlines():
                    line = line.strip()
                    if line:
                        result["version"] = line[:80]
                        break
            else:
                result["errors"].append(
                    f"'{binary} {' '.join(args)}' returned code {proc.returncode}: {proc.stderr.strip()[:200]}"
                )
        except subprocess.TimeoutExpired:
            result["errors"].append(f"'{binary}' version probe timed out after 10s.")
        except OSError as e:
            result["errors"].append(f"Failed to run '{binary}': {e}")

        # Check at least one config indicator file exists
        indicators = _CONFIG_PATH_INDICATORS.get(harness, [])
        for rel in indicators:
            candidate = project_dir / rel
            if candidate.exists():
                result["config_present"] = True
                break
        # Also check home-level paths
        if not result["config_present"]:
            _user_dirs: dict[str, Path] = {
                "codex":    Path.home() / ".codex" / "AGENTS.md",
                "gemini":   Path.home() / ".gemini" / "GEMINI.md",
                "opencode": Path.home() / ".config" / "opencode" / "AGENTS.md",
            }
            user_path = _user_dirs.get(harness)
            if user_path and user_path.exists():
                result["config_present"] = True

        if not result["config_present"]:
            result["errors"].append(
                f"No config indicator file found for '{harness}' in {project_dir}. "
                "The harness may not have read the config path."
            )

        result["success"] = result["binary_found"] and result["config_present"] and not result["errors"]
        if result["success"]:
            result["message"] = f"Harness '{harness}' binary found and config is present."
        elif result["binary_found"] and not result["config_present"]:
            result["message"] = f"Binary found but config files missing — sync may have written to wrong path."
        else:
            result["message"] = "; ".join(result["errors"]) if result["errors"] else "Validation failed."

        return result
