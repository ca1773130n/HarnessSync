from __future__ import annotations

"""Structural validation checks for /sync-test.

Validates that synced target config files are well-formed:
JSON validity, YAML sanity, TOML validity, non-empty checks,
symlink resolution, and truncation detection.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class StructuralCheck:
    """Result of a single structural validation check on a target config file."""

    name: str          # Short check identifier
    passed: bool
    message: str       # Human-readable detail


def validate_json(path: Path) -> list[StructuralCheck]:
    """Validate that a .json file is well-formed."""
    try:
        import json as _json
        text = path.read_text(encoding="utf-8")
        _json.loads(text)
        return [StructuralCheck("valid-json", True, f"{path.name}: valid JSON")]
    except Exception as exc:
        return [StructuralCheck("valid-json", False, f"{path.name}: invalid JSON — {exc}")]


def validate_yaml(path: Path) -> list[StructuralCheck]:
    """Validate that a .yml/.yaml file is well-formed (stdlib only)."""
    try:
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), 1):
            if line.startswith("\t"):
                return [StructuralCheck(
                    "valid-yaml", False,
                    f"{path.name}:{line_no}: YAML files must not use tabs for indentation",
                )]
        return [StructuralCheck("valid-yaml", True, f"{path.name}: YAML structure looks OK")]
    except OSError as exc:
        return [StructuralCheck("valid-yaml", False, f"{path.name}: unreadable — {exc}")]


def validate_toml(path: Path) -> list[StructuralCheck]:
    """Validate that a .toml file is well-formed."""
    try:
        text = path.read_text(encoding="utf-8")
        try:
            import tomllib  # type: ignore[import]
            tomllib.loads(text)
            return [StructuralCheck("valid-toml", True, f"{path.name}: valid TOML")]
        except ImportError:
            pass
        opens = text.count("[")
        closes = text.count("]")
        if opens != closes:
            return [StructuralCheck(
                "valid-toml", False,
                f"{path.name}: mismatched brackets ([={opens} ]={closes})",
            )]
        return [StructuralCheck("valid-toml", True, f"{path.name}: TOML brackets balanced")]
    except OSError as exc:
        return [StructuralCheck("valid-toml", False, f"{path.name}: unreadable — {exc}")]


def validate_non_empty(path: Path) -> StructuralCheck:
    """Check that the file has meaningful content (not empty or stub)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        stripped = text.strip()
        if not stripped:
            return StructuralCheck("non-empty", False, f"{path.name}: file is empty")
        if len(stripped) < 20:
            return StructuralCheck(
                "non-empty", False,
                f"{path.name}: suspiciously short ({len(stripped)} chars) — may be a stub",
            )
        return StructuralCheck("non-empty", True, f"{path.name}: {len(stripped)} chars")
    except OSError as exc:
        return StructuralCheck("non-empty", False, f"{path.name}: unreadable — {exc}")


def validate_symlinks(path: Path) -> list[StructuralCheck]:
    """Check that the file (if a symlink) resolves to an existing target."""
    if not path.is_symlink():
        return []
    resolved = path.resolve()
    if resolved.exists():
        return [StructuralCheck("symlink-resolves", True, f"{path.name}: symlink -> {resolved}")]
    return [StructuralCheck(
        "symlink-resolves", False,
        f"{path.name}: broken symlink -> {resolved} does not exist",
    )]


def validate_no_truncation(path: Path) -> list[StructuralCheck]:
    """Warn when any line is suspiciously long (>8000 chars), which may indicate truncation."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            if len(line) > 8000:
                return [StructuralCheck(
                    "no-truncation", False,
                    f"{path.name}:{line_no}: line is {len(line)} chars — possible runaway concatenation",
                )]
        return [StructuralCheck("no-truncation", True, f"{path.name}: line lengths OK")]
    except OSError:
        return []


def run_structural_checks(config_path: Path) -> list[StructuralCheck]:
    """Run all structural validation checks for a single target config file.

    Checks performed:
    - File is non-empty / not a stub
    - JSON validity (for .json files)
    - YAML basic sanity (for .yml/.yaml files)
    - TOML validity (for .toml files)
    - Symlink resolution (if applicable)
    - No suspiciously long lines (truncation guard)

    Args:
        config_path: Path to the synced target config file.

    Returns:
        List of StructuralCheck results, one per check performed.
    """
    checks: list[StructuralCheck] = []
    suffix = config_path.suffix.lower()

    checks.append(validate_non_empty(config_path))
    checks.extend(validate_symlinks(config_path))
    checks.extend(validate_no_truncation(config_path))

    if suffix == ".json":
        checks.extend(validate_json(config_path))
    elif suffix in (".yml", ".yaml"):
        checks.extend(validate_yaml(config_path))
    elif suffix == ".toml":
        checks.extend(validate_toml(config_path))

    return checks
