from __future__ import annotations

"""New AI harness auto-detector.

Periodically scans PATH and common install locations for AI coding CLIs
that have not yet been added as HarnessSync targets. Surfaces newly
discovered harnesses so users don't forget to configure them.

Detection strategy (item 7):
1. PATH scan: check if the CLI executable is in PATH
2. Config-dir scan: check if the harness config directory exists on disk
   (catches harnesses installed as GUI apps that don't add to PATH)

Version detection (item 27):
Version strings are obtained by running ``<executable> --version`` (or the
harness-specific flag) and parsing the first line of stdout. A short timeout
prevents long hangs on slow CLIs. Results are cached per process lifetime.
"""

import re
import shutil
import subprocess
from pathlib import Path

# Known AI coding CLI executables mapped to their canonical names
_KNOWN_AI_CLIS: dict[str, str] = {
    "codex": "codex",
    "gemini": "gemini",
    "opencode": "opencode",
    "opencode-cli": "opencode",
    "cursor": "cursor",
    "cursor-cli": "cursor",
    "windsurf": "windsurf",
    "windsurf-cli": "windsurf",
    "aider": "aider",
    "continue": "continue",
    "cody": "cody",
    "copilot": "copilot",
    "gh-copilot": "copilot",
    "tabby": "tabby",
    "supermaven": "supermaven",
    "codeium": "codeium",
}

# Config directory patterns per canonical harness name.
# Paths are relative to $HOME. Multiple candidates per harness (tried in order).
_CONFIG_DIR_PATTERNS: dict[str, list[str]] = {
    "codex": [".codex", ".config/codex"],
    "gemini": [".gemini", ".config/gemini-cli"],
    "opencode": [".config/opencode", ".opencode"],
    "cursor": [".cursor", ".config/Cursor", "Library/Application Support/Cursor"],
    "windsurf": [".windsurf", ".config/windsurf", "Library/Application Support/windsurf"],
    "aider": [".aider", ".config/aider"],
    "continue": [".continue", ".config/continue"],
    "cody": [".config/cody", ".cody"],
    "copilot": [".config/gh/copilot", ".copilot"],
}


def _check_config_dir(canonical: str) -> bool:
    """Return True if any known config directory for the harness exists."""
    home = Path.home()
    for pattern in _CONFIG_DIR_PATTERNS.get(canonical, []):
        if (home / pattern).exists():
            return True
    return False


def detect_new_harnesses(already_configured: list[str]) -> list[str]:
    """Scan PATH and config directories for AI coding CLIs not yet configured.

    Detection uses two signals (either is sufficient):
    - Executable found in PATH (CLI-installed tools)
    - Config directory exists in $HOME (GUI-installed tools)

    Args:
        already_configured: List of target names already configured in
                            HarnessSync (e.g. ["codex", "gemini", "opencode"]).

    Returns:
        Sorted list of canonical harness names found but not yet configured.
        Empty list if nothing new is found.
    """
    configured_set = set(already_configured)
    found: set[str] = set()

    # PATH scan
    for exe, canonical in _KNOWN_AI_CLIS.items():
        if canonical in configured_set or canonical in found:
            continue
        if shutil.which(exe):
            found.add(canonical)

    # Config-dir scan (catches GUI apps not in PATH)
    all_canonicals = set(_KNOWN_AI_CLIS.values())
    for canonical in all_canonicals:
        if canonical in configured_set or canonical in found:
            continue
        if _check_config_dir(canonical):
            found.add(canonical)

    # Package manager scan (Homebrew, npm, pip) — catches tools not yet in PATH
    for canonical in _detect_via_package_managers(configured_set | found):
        found.add(canonical)

    return sorted(found)


# Homebrew formula / cask names per canonical harness name
_HOMEBREW_FORMULAS: dict[str, list[str]] = {
    "aider": ["aider"],
    "gemini": ["gemini-cli", "google-gemini-cli"],
    "codex": ["openai-codex"],
    "cursor": ["cursor"],
    "windsurf": ["windsurf"],
    "opencode": ["opencode"],
    "continue": ["continue"],
    "cline": ["cline"],
}

# npm package names per canonical harness name
_NPM_PACKAGES: dict[str, list[str]] = {
    "gemini": ["@google/gemini-cli", "gemini-cli"],
    "codex": ["@openai/codex"],
    "opencode": ["opencode"],
    "cline": ["cline"],
    "cursor": ["cursor-cli"],
    "continue": ["@continuedev/continue"],
}

# pip package names per canonical harness name
_PIP_PACKAGES: dict[str, list[str]] = {
    "aider": ["aider-chat"],
    "opencode": ["opencode"],
    "gemini": ["google-genai-cli"],
}


def _detect_via_package_managers(already_found: set[str]) -> list[str]:
    """Detect AI coding tools installed via Homebrew, npm, or pip.

    Checks package manager list outputs (brew list, npm list -g, pip list)
    for known AI harness package names. Only probes package managers that
    are themselves installed (checked via shutil.which first).

    Args:
        already_found: Set of canonical harness names already detected by
                       PATH / config-dir scans (to avoid duplicates).

    Returns:
        Sorted list of newly detected canonical harness names.
    """
    found: set[str] = set()

    # --- Homebrew ---
    if shutil.which("brew"):
        try:
            proc = subprocess.run(
                ["brew", "list", "--formula", "--full-name"],
                capture_output=True, text=True, timeout=10,
            )
            brew_installed = set(proc.stdout.splitlines())
            # Also check casks
            cask_proc = subprocess.run(
                ["brew", "list", "--cask"],
                capture_output=True, text=True, timeout=10,
            )
            brew_installed |= set(cask_proc.stdout.splitlines())

            for canonical, formulas in _HOMEBREW_FORMULAS.items():
                if canonical in already_found or canonical in found:
                    continue
                if any(f in brew_installed for f in formulas):
                    found.add(canonical)
        except (subprocess.TimeoutExpired, OSError):
            pass

    # --- npm (global packages) ---
    npm_exe = shutil.which("npm")
    if npm_exe:
        try:
            proc = subprocess.run(
                [npm_exe, "list", "-g", "--depth=0", "--json"],
                capture_output=True, text=True, timeout=15,
            )
            if proc.returncode == 0 or proc.stdout.strip():
                import json as _json
                try:
                    npm_data = _json.loads(proc.stdout)
                    npm_deps = npm_data.get("dependencies", {})
                    for canonical, pkgs in _NPM_PACKAGES.items():
                        if canonical in already_found or canonical in found:
                            continue
                        if any(p in npm_deps for p in pkgs):
                            found.add(canonical)
                except (_json.JSONDecodeError, AttributeError):
                    pass
        except (subprocess.TimeoutExpired, OSError):
            pass

    # --- pip (user and system) ---
    pip_exe = shutil.which("pip") or shutil.which("pip3")
    if pip_exe:
        try:
            proc = subprocess.run(
                [pip_exe, "list", "--format=columns"],
                capture_output=True, text=True, timeout=15,
            )
            # Extract package names (first column, lowercase)
            pip_installed: set[str] = set()
            for line in proc.stdout.splitlines()[2:]:  # Skip header rows
                parts = line.split()
                if parts:
                    pip_installed.add(parts[0].lower())

            for canonical, pkgs in _PIP_PACKAGES.items():
                if canonical in already_found or canonical in found:
                    continue
                if any(p.lower() in pip_installed for p in pkgs):
                    found.add(canonical)
        except (subprocess.TimeoutExpired, OSError):
            pass

    return sorted(found)


def scan_all() -> dict[str, dict]:
    """Scan PATH, config directories, and package managers for all known AI coding CLIs.

    Returns:
        Dict mapping canonical harness name -> detection info dict:
        {
            "in_path": bool,        # found via PATH scan
            "config_dir": bool,     # found via config directory scan
            "executable": str|None, # executable path if found in PATH
            "via_pkg_mgr": bool,    # found via Homebrew/npm/pip (not yet in PATH)
        }
    """
    result: dict[str, dict] = {}

    all_canonicals = set(_KNOWN_AI_CLIS.values())

    # PATH scan
    path_found: dict[str, str] = {}
    for exe, canonical in _KNOWN_AI_CLIS.items():
        if canonical in path_found:
            continue
        p = shutil.which(exe)
        if p:
            path_found[canonical] = p

    for canonical in all_canonicals:
        in_path = canonical in path_found
        config_dir = _check_config_dir(canonical)
        if in_path or config_dir:
            result[canonical] = {
                "in_path": in_path,
                "config_dir": config_dir,
                "executable": path_found.get(canonical),
                "via_pkg_mgr": False,
            }

    # Package manager scan — adds entries not yet detected by PATH/config-dir
    pkg_mgr_found = _detect_via_package_managers(set(result.keys()))
    for canonical in pkg_mgr_found:
        if canonical not in result:
            result[canonical] = {
                "in_path": False,
                "config_dir": False,
                "executable": None,
                "via_pkg_mgr": True,
            }
        else:
            result[canonical]["via_pkg_mgr"] = True

    return result


# ---------------------------------------------------------------------------
# Version Detection (Item 27 — Auto-Discovery of Installed Harnesses)
# ---------------------------------------------------------------------------

# Per-harness version flag overrides (default is --version)
_VERSION_FLAGS: dict[str, list[str]] = {
    "aider": ["--version"],
    "gemini": ["--version"],
    "codex": ["--version"],
    "opencode": ["--version"],
    "cursor": ["--version"],
    "windsurf": ["--version"],
    "continue": ["--version"],
    "cody": ["version"],
}

# Timeout (seconds) when probing version
_VERSION_TIMEOUT = 3

# Regex to extract a semver-like string from version output
_SEMVER_RE = re.compile(r"(\d+\.\d+[\.\d+]*)", re.ASCII)

# Simple in-process cache: executable_path -> version string
_version_cache: dict[str, str] = {}


def detect_version(canonical: str, executable: str | None = None) -> str | None:
    """Detect the installed version of a harness CLI.

    Runs ``<executable> --version`` (or the harness-specific flag) and
    extracts the first semver-looking string from stdout/stderr. Results are
    cached for the lifetime of the process.

    Args:
        canonical: Canonical harness name (e.g. "codex").
        executable: Full path to the executable. If None, looked up via PATH.

    Returns:
        Version string (e.g. "1.2.3") or None if unavailable / timed out.
    """
    exe = executable or shutil.which(canonical) or shutil.which(f"{canonical}-cli")
    if not exe:
        return None

    if exe in _version_cache:
        return _version_cache[exe]

    flags = _VERSION_FLAGS.get(canonical, ["--version"])
    cmd = [exe] + flags

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT,
        )
        output = (result.stdout + result.stderr).strip()
        m = _SEMVER_RE.search(output)
        version = m.group(1) if m else None
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        version = None

    _version_cache[exe] = version  # type: ignore[assignment]
    return version


def scan_all_with_versions() -> dict[str, dict]:
    """Scan for all known AI coding CLIs and include their version strings.

    Extends :func:`scan_all` by adding a ``version`` key to each entry.
    Version detection is best-effort: ``None`` if the CLI is a GUI app or
    the ``--version`` flag is not supported.

    Returns:
        Dict mapping canonical harness name -> detection info dict:
        {
            "in_path": bool,
            "config_dir": bool,
            "executable": str|None,
            "version": str|None   # e.g. "1.5.2"
        }
    """
    detected = scan_all()
    for canonical, info in detected.items():
        info["version"] = detect_version(canonical, executable=info.get("executable"))
    return detected


def format_detection_report(detected: dict[str, dict]) -> str:
    """Format a human-readable detection report.

    Args:
        detected: Output of :func:`scan_all_with_versions`.

    Returns:
        Formatted string listing each discovered harness with version and
        detection method.
    """
    if not detected:
        return "No AI coding harnesses detected on this system."

    lines = [f"Detected {len(detected)} AI coding harness(es):", ""]
    for name in sorted(detected):
        info = detected[name]
        version = info.get("version") or "unknown version"
        methods: list[str] = []
        if info.get("in_path"):
            methods.append("PATH")
        if info.get("config_dir"):
            methods.append("config dir")
        method_str = ", ".join(methods) or "unknown"
        exe = info.get("executable") or ""
        exe_part = f" ({exe})" if exe else ""
        lines.append(f"  {name:<14} v{version:<12} via {method_str}{exe_part}")

    return "\n".join(lines)


def bootstrap_new_harness(
    harness: str,
    project_dir: "Path",
    cc_home: "Path | None" = None,
    dry_run: bool = False,
    interactive: bool = True,
) -> dict:
    """Bootstrap a newly detected harness from Claude Code config.

    Runs a targeted sync to populate the new harness's config directory
    with rules, MCP servers, and settings translated from CLAUDE.md. This
    eliminates the cold-start problem — newly installed harnesses start
    fully configured rather than blank.

    Args:
        harness: Canonical harness name to bootstrap (e.g. "windsurf").
        project_dir: Project root directory.
        cc_home: Claude Code config home (default: ~/.claude).
        dry_run: If True, show what would be written without writing.
        interactive: If True and stdin is a TTY, confirm before syncing.

    Returns:
        Dict with keys:
            - "harness": str — the harness that was bootstrapped
            - "success": bool — True if bootstrap completed without errors
            - "files_written": list[str] — files created/updated
            - "skipped": bool — True if user declined in interactive mode
            - "error": str | None — error message if failed
            - "dry_run": bool
    """
    import sys
    from pathlib import Path as _Path

    result: dict = {
        "harness": harness,
        "success": False,
        "files_written": [],
        "skipped": False,
        "error": None,
        "dry_run": dry_run,
    }

    # Check if the harness is actually installed
    detected = scan_all()
    if harness not in detected:
        result["error"] = f"Harness '{harness}' not found on this system."
        return result

    if interactive and sys.stdin.isatty():
        version = detected[harness].get("version") or "unknown version"
        print(f"\nNew AI coding harness detected: {harness} (v{version})")
        print(f"Bootstrap it from your Claude Code config? (y/N): ", end="", flush=True)
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer not in ("y", "yes"):
            result["skipped"] = True
            return result

    try:
        from src.orchestrator import SyncOrchestrator

        orch = SyncOrchestrator(
            project_dir=_Path(project_dir),
            scope="all",
            dry_run=dry_run,
            cc_home=_Path(cc_home) if cc_home else None,
            cli_only_targets={harness},
        )

        sync_results = orch.sync_all()

        harness_result = (sync_results or {}).get(harness)
        if harness_result is not None:
            success = getattr(harness_result, "success", False)
            files = getattr(harness_result, "files_written", [])
            result["success"] = success
            result["files_written"] = list(files) if files else []
            if not success:
                result["error"] = getattr(harness_result, "error", "sync failed")
        else:
            result["error"] = f"No sync result returned for {harness}"

    except Exception as e:
        result["error"] = str(e)

    return result


def prompt_bootstrap_new_harnesses(
    already_configured: list[str],
    project_dir: "Path",
    cc_home: "Path | None" = None,
) -> list[dict]:
    """Detect newly installed harnesses and offer to bootstrap each one.

    Scans for harnesses not yet in ``already_configured``, then calls
    :func:`bootstrap_new_harness` interactively for each one found.

    Args:
        already_configured: Harnesses already set up in HarnessSync.
        project_dir: Project root directory.
        cc_home: Claude Code config home (default: ~/.claude).

    Returns:
        List of bootstrap result dicts (one per newly detected harness).
    """
    new_harnesses = detect_new_harnesses(already_configured)
    results = []
    for harness in new_harnesses:
        result = bootstrap_new_harness(
            harness=harness,
            project_dir=project_dir,
            cc_home=cc_home,
            interactive=True,
        )
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Version update tracking (item 26)
# ---------------------------------------------------------------------------

def _load_known_versions(cache_path: "Path") -> dict[str, str]:
    """Load previously-recorded harness versions from cache file.

    Args:
        cache_path: Path to the JSON cache file (typically ~/.harnesssync/versions_cache.json).

    Returns:
        Dict mapping harness_name -> last_seen_version_string.
    """
    if not cache_path.exists():
        return {}
    try:
        import json
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if isinstance(v, str)}
    except (OSError, ValueError):
        return {}


def _save_known_versions(cache_path: "Path", versions: dict[str, str]) -> None:
    """Persist harness versions to cache file.

    Args:
        cache_path: Path to write the JSON cache.
        versions: Dict mapping harness_name -> version_string.
    """
    import json
    import tempfile

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", dir=cache_path.parent, suffix=".tmp", delete=False, encoding="utf-8"
    )
    try:
        json.dump(versions, tmp, indent=2)
        tmp.close()
        Path(tmp.name).replace(cache_path)
    except (OSError, ValueError):
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except OSError:
            pass


def detect_version_updates(
    cache_dir: "Path | None" = None,
) -> list[dict]:
    """Detect harnesses whose installed version has changed since last check.

    Compares the current installed version of each detected harness against
    the version stored in a local cache file. Returns harnesses that have
    been updated, downgraded, or newly installed since the last call.

    Useful for triggering a re-evaluation of sync capabilities when a harness
    gains new features (e.g. Cursor 0.43 adding .cursor/mcp.json support).

    Args:
        cache_dir: Directory for the version cache file.
                   Default: ~/.harnesssync/

    Returns:
        List of update dicts, each with keys:
          - harness: Canonical harness name
          - old_version: Previously recorded version (or "unknown")
          - new_version: Current installed version
          - kind: "upgraded" | "downgraded" | "new"
          - note: Human-readable description
    """
    from pathlib import Path as _Path

    cache_dir = cache_dir or (_Path.home() / ".harnesssync")
    cache_path = cache_dir / "versions_cache.json"

    known = _load_known_versions(cache_path)
    current_scan = scan_all_with_versions()

    updates: list[dict] = []

    for harness, info in current_scan.items():
        current_ver = info.get("version") or "unknown"
        old_ver = known.get(harness, "")

        if not old_ver:
            # First time we've seen this harness
            if current_ver and current_ver != "unknown":
                updates.append({
                    "harness":     harness,
                    "old_version": "unknown",
                    "new_version": current_ver,
                    "kind":        "new",
                    "note":        f"{harness} detected for the first time (v{current_ver})",
                })
        elif current_ver != old_ver and current_ver != "unknown":
            # Compare: try semantic comparison, fall back to string
            kind = _compare_version_kind(old_ver, current_ver)
            updates.append({
                "harness":     harness,
                "old_version": old_ver,
                "new_version": current_ver,
                "kind":        kind,
                "note":        f"{harness} {kind}: {old_ver} → {current_ver}",
            })

    # Persist the current versions so next call can compare
    merged = dict(known)
    for harness, info in current_scan.items():
        ver = info.get("version")
        if ver and ver != "unknown":
            merged[harness] = ver

    _save_known_versions(cache_path, merged)

    return updates


def _compare_version_kind(old: str, new: str) -> str:
    """Return 'upgraded', 'downgraded', or 'changed' based on version strings.

    Attempts a simple numeric tuple comparison; falls back to 'changed' if
    versions can't be parsed.
    """
    def _parse(v: str) -> tuple:
        parts = []
        for segment in v.lstrip("v").split("."):
            try:
                parts.append(int(segment))
            except ValueError:
                parts.append(0)
        return tuple(parts)

    try:
        old_t = _parse(old)
        new_t = _parse(new)
        if new_t > old_t:
            return "upgraded"
        elif new_t < old_t:
            return "downgraded"
        return "changed"
    except Exception:
        return "changed"


def generate_bootstrap_script(
    harnesses: list[str] | None = None,
    project_dir: "Path | None" = None,
    include_smoke_test: bool = True,
) -> str:
    """Generate a portable shell script that bootstraps target harnesses from scratch.

    The generated script handles the full onboarding flow for each requested
    harness: checks for existing installation, offers to install if missing,
    applies the HarnessSync config, and optionally runs a quick smoke test.

    This is the "team onboarding" artifact — share it with a new developer and
    they can run it once to go from zero to fully configured on all harnesses.

    Args:
        harnesses: Canonical harness names to include (default: all detected).
        project_dir: Project root directory for config paths (default: cwd).
        include_smoke_test: If True, add a verification step per harness.

    Returns:
        A bash-compatible shell script as a string.
    """
    import os as _os

    project_dir_str = str(project_dir) if project_dir else "$(pwd)"
    detected = scan_all()
    if harnesses is None:
        harnesses = sorted(detected.keys()) or ["codex", "gemini", "cursor", "aider"]

    # Install hints per harness
    _install_hints: dict[str, str] = {
        "codex":    "npm install -g @openai/codex",
        "gemini":   "npm install -g @google/gemini-cli",
        "opencode": "npm install -g opencode-ai",
        "cursor":   "# Download Cursor from https://cursor.sh — GUI installer required",
        "aider":    "pip install aider-chat",
        "windsurf": "# Download Windsurf from https://codeium.com/windsurf — GUI installer required",
        "continue": "# Install Continue extension via VS Code Marketplace",
        "cody":     "npm install -g @sourcegraph/cody",
    }

    lines: list[str] = [
        "#!/usr/bin/env bash",
        "# HarnessSync bootstrap script — generated by generate_bootstrap_script()",
        "# Run this script to configure all AI coding harnesses from your Claude Code setup.",
        "# Usage: bash bootstrap-harnesses.sh",
        "",
        "set -euo pipefail",
        "",
        "PLUGIN_ROOT=\"${CLAUDE_PLUGIN_ROOT:-$(dirname \"$0\")}\"",
        f"PROJECT_DIR=\"{project_dir_str}\"",
        "PYTHON=\"$(command -v python3 || command -v python)\"",
        "",
        "echo '=== HarnessSync Harness Bootstrap ==='",
        "echo ''",
        "",
        "# ── Helper ──────────────────────────────────────────────────────────────────",
        "harness_sync() {",
        "  local harness=$1",
        "  echo \"[HarnessSync] Syncing config to $harness...\"",
        "  \"$PYTHON\" \"$PLUGIN_ROOT/src/commands/sync.py\" --targets \"$harness\" \\",
        "      --project-dir \"$PROJECT_DIR\" || {",
        "    echo \"  [WARN] Sync to $harness failed — check /sync-health for details\"",
        "    return 1",
        "  }",
        "  echo \"  [OK] $harness configured\"",
        "}",
        "",
    ]

    for harness in harnesses:
        version_info = detected.get(harness, {})
        is_installed = bool(version_info)
        install_cmd = _install_hints.get(harness, f"# Install {harness} manually")
        version_str = version_info.get("version", "unknown")
        if is_installed:
            version_note = f"# {harness} detected (v{version_str})"
        else:
            version_note = f"# {harness} not detected on this system"

        lines += [
            f"# ── {harness.upper()} {'─' * max(1, 57 - len(harness))}",
            version_note,
        ]

        if not is_installed:
            lines += [
                f"if ! command -v {harness} &>/dev/null; then",
                f"  echo '[HarnessSync] {harness} not found.'",
                f"  echo '  Install with: {install_cmd}'",
                f"  read -rp '  Skip {harness}? (Y/n): ' skip_{harness}",
                f"  if [[ \"${{skip_{harness}:-Y}}\" =~ ^[Nn] ]]; then",
                f"    echo '  Please install {harness} first, then re-run this script.'",
                "    exit 1",
                "  fi",
                f"  echo '  Skipping {harness}.'",
                "else",
                f"  harness_sync {harness}",
            ]
            if include_smoke_test:
                lines += [
                    f"  echo '[HarnessSync] Smoke-testing {harness}...'",
                    f"  \"$PYTHON\" \"$PLUGIN_ROOT/src/commands/sync_smoke_test.py\" \\",
                    f"      --target {harness} --project-dir \"$PROJECT_DIR\" 2>/dev/null \\",
                    f"    && echo '  [OK] {harness} smoke test passed' \\",
                    f"    || echo '  [WARN] {harness} smoke test failed — config may need review'",
                ]
            lines.append("fi")
        else:
            lines += [f"harness_sync {harness}"]
            if include_smoke_test:
                lines += [
                    f"echo '[HarnessSync] Smoke-testing {harness}...'",
                    f"\"$PYTHON\" \"$PLUGIN_ROOT/src/commands/sync_smoke_test.py\" \\",
                    f"    --target {harness} --project-dir \"$PROJECT_DIR\" 2>/dev/null \\",
                    f"  && echo '  [OK] {harness} smoke test passed' \\",
                    f"  || echo '  [WARN] {harness} smoke test failed — config may need review'",
                ]

        lines.append("")

    lines += [
        "echo ''",
        "echo '=== Bootstrap complete ==='",
        "echo 'Run /sync-status to verify all targets are current.'",
        "",
    ]

    return "\n".join(lines)


def format_version_update_report(updates: list[dict]) -> str:
    """Format detected harness version updates as a human-readable report.

    Args:
        updates: List from detect_version_updates().

    Returns:
        Formatted string, or empty string if no updates.
    """
    if not updates:
        return ""

    lines = [f"\nHarnessSync detected {len(updates)} harness version update(s):"]
    for u in updates:
        icon = "↑" if u["kind"] == "upgraded" else ("↓" if u["kind"] == "downgraded" else "★")
        lines.append(f"  {icon}  {u['note']}")

    lines.append(
        "\nNew harness versions may support features not previously available."
    )
    lines.append("Run /sync-status to review compatibility changes.")
    return "\n".join(lines)
