from __future__ import annotations

"""Monorepo per-package sync support.

Discovers sub-packages within a monorepo and applies per-package
HarnessSync configuration overrides. Each package can have its own
``.harnesssync`` or ``.harnesssync-package.json`` file specifying:
- targets: list of harness targets for this package
- only_sections: sections to sync for this package
- skip_sections: sections to skip for this package
- rules_file: custom CLAUDE.md path (default: CLAUDE.md in package dir)
- description: human-readable label for the package

Example .harnesssync-package.json in frontend/:
    {
        "description": "React frontend — Cursor + rules only",
        "targets": ["cursor", "cline"],
        "only_sections": ["rules", "mcp"],
        "rules_file": "CLAUDE.md"
    }

Usage:
    from src.monorepo_sync import MonorepoPackageDiscoverer, run_monorepo_sync

    discoverer = MonorepoPackageDiscoverer(project_dir)
    packages = discoverer.discover()
    results = run_monorepo_sync(project_dir, packages, dry_run=False)
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.logger import Logger

# File names that mark a directory as a monorepo sub-package with its own config
_PACKAGE_CONFIG_NAMES = [
    ".harnesssync-package.json",
    ".harnesssync",           # generic per-project override (already supported)
]

# Directories that commonly contain monorepo sub-packages
_COMMON_PACKAGE_DIRS = ["packages", "apps", "libs", "services", "modules", "components"]

# Stop recursing into these (avoids scanning node_modules etc.)
_EXCLUDED_DIRS = {
    "node_modules", ".git", ".svn", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "target", "out",
}

# Max depth to search for sub-packages
_MAX_DEPTH = 3


@dataclass
class PackageConfig:
    """Per-package sync configuration discovered from .harnesssync-package.json."""

    package_dir: Path
    name: str
    description: str = ""
    targets: list[str] = field(default_factory=list)
    only_sections: list[str] = field(default_factory=list)
    skip_sections: list[str] = field(default_factory=list)
    rules_file: str = "CLAUDE.md"

    @property
    def rules_path(self) -> Path:
        """Absolute path to this package's CLAUDE.md (or custom rules file)."""
        return self.package_dir / self.rules_file

    def has_rules(self) -> bool:
        """Return True if this package has a local rules file."""
        return self.rules_path.is_file()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "package_dir": str(self.package_dir),
            "description": self.description,
            "targets": self.targets,
            "only_sections": self.only_sections,
            "skip_sections": self.skip_sections,
            "rules_file": self.rules_file,
            "has_rules": self.has_rules(),
        }


class MonorepoPackageDiscoverer:
    """Discover and parse per-package HarnessSync configs within a monorepo.

    Searches two ways:
    1. Well-known package directories (packages/, apps/, libs/, etc.)
    2. Any subdirectory containing a .harnesssync-package.json file

    Args:
        project_dir: Root directory of the monorepo.
        max_depth: Maximum directory depth to recurse (default: 3).
    """

    def __init__(self, project_dir: Path, max_depth: int = _MAX_DEPTH):
        self.project_dir = project_dir
        self.max_depth = max_depth
        self.logger = Logger()

    def discover(self) -> list[PackageConfig]:
        """Discover all sub-packages with HarnessSync config.

        Returns:
            List of PackageConfig objects, one per configured sub-package.
        """
        packages: dict[Path, PackageConfig] = {}

        # Search well-known package directories for sub-packages with rules
        for pkg_dir_name in _COMMON_PACKAGE_DIRS:
            parent = self.project_dir / pkg_dir_name
            if not parent.is_dir():
                continue
            for child in sorted(parent.iterdir()):
                if not child.is_dir() or child.name in _EXCLUDED_DIRS:
                    continue
                pkg = self._load_package(child)
                if pkg and child not in packages:
                    packages[child] = pkg

        # Recursively search for .harnesssync-package.json anywhere in the tree
        self._find_package_configs(self.project_dir, depth=0, found=packages)

        return list(packages.values())

    def _find_package_configs(
        self, directory: Path, depth: int, found: dict[Path, PackageConfig]
    ) -> None:
        """Recursively search for .harnesssync-package.json files."""
        if depth >= self.max_depth:
            return
        try:
            children = sorted(directory.iterdir())
        except PermissionError:
            return

        for child in children:
            if not child.is_dir() or child.name in _EXCLUDED_DIRS:
                continue
            if child in found:
                continue
            # Check for package config file
            for config_name in _PACKAGE_CONFIG_NAMES:
                config_path = child / config_name
                if config_path.is_file():
                    pkg = self._load_package(child, config_path)
                    if pkg:
                        found[child] = pkg
                    break
            else:
                # No config found here — recurse deeper
                self._find_package_configs(child, depth + 1, found)

    def _load_package(
        self, package_dir: Path, config_path: Path | None = None
    ) -> PackageConfig | None:
        """Load a PackageConfig from the given directory.

        If config_path is None, auto-detects from _PACKAGE_CONFIG_NAMES.
        Returns None if the directory has no usable config or rules.
        """
        if config_path is None:
            for name in _PACKAGE_CONFIG_NAMES:
                candidate = package_dir / name
                if candidate.is_file():
                    config_path = candidate
                    break

        raw: dict = {}
        if config_path and config_path.is_file():
            try:
                raw = json.loads(config_path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raw = {}
            except (json.JSONDecodeError, OSError) as exc:
                self.logger.warn(f"Could not parse {config_path}: {exc}")
                raw = {}

        # Only include packages that have a rules file (CLAUDE.md) or explicit config
        rules_file = raw.get("rules_file", "CLAUDE.md")
        has_rules = (package_dir / rules_file).is_file()
        has_config = bool(config_path and config_path.is_file())

        if not has_rules and not has_config:
            return None

        name = raw.get("name") or package_dir.name
        return PackageConfig(
            package_dir=package_dir,
            name=name,
            description=raw.get("description", ""),
            targets=raw.get("targets", []),
            only_sections=raw.get("only_sections", []),
            skip_sections=raw.get("skip_sections", []),
            rules_file=rules_file,
        )

    def format_report(self, packages: list[PackageConfig]) -> str:
        """Return a human-readable list of discovered packages."""
        if not packages:
            return "No monorepo sub-packages discovered."
        lines = [f"Discovered {len(packages)} sub-package(s):"]
        for pkg in packages:
            rules_note = "✓ has CLAUDE.md" if pkg.has_rules() else "  no rules file"
            lines.append(f"  {pkg.name:<20} {rules_note}")
            if pkg.description:
                lines.append(f"    {pkg.description}")
            if pkg.targets:
                lines.append(f"    targets: {', '.join(pkg.targets)}")
            if pkg.only_sections:
                lines.append(f"    only: {', '.join(pkg.only_sections)}")
            if pkg.skip_sections:
                lines.append(f"    skip: {', '.join(pkg.skip_sections)}")
        return "\n".join(lines)


def run_monorepo_sync(
    project_dir: Path,
    packages: list[PackageConfig],
    dry_run: bool = False,
    scope: str = "project",
    allow_secrets: bool = False,
) -> dict[str, dict]:
    """Run per-package sync for a monorepo.

    For each package:
    1. Reads the package's own CLAUDE.md (if present)
    2. Applies per-package target/section overrides
    3. Runs sync restricted to that package directory

    Args:
        project_dir: Monorepo root.
        packages: Discovered package configs (from MonorepoPackageDiscoverer).
        dry_run: If True, preview without writing.
        scope: Sync scope.
        allow_secrets: If True, skip secret detection.

    Returns:
        Dict mapping package name → sync results dict.
    """
    from src.orchestrator import SyncOrchestrator

    all_results: dict[str, dict] = {}

    for pkg in packages:
        only_sections = set(pkg.only_sections) if pkg.only_sections else set()
        skip_sections = set(pkg.skip_sections) if pkg.skip_sections else set()
        cli_only_targets = set(pkg.targets) if pkg.targets else None

        orchestrator = SyncOrchestrator(
            project_dir=pkg.package_dir,
            scope=scope,
            dry_run=dry_run,
            allow_secrets=allow_secrets,
            only_sections=only_sections,
            skip_sections=skip_sections,
            cli_only_targets=cli_only_targets,
        )

        try:
            results = orchestrator.sync_all()
            all_results[pkg.name] = results
        except Exception as exc:
            all_results[pkg.name] = {"_error": str(exc)}

    return all_results


def format_monorepo_results(results: dict[str, dict]) -> str:
    """Format multi-package sync results for display."""
    lines = [f"Monorepo Sync Results ({len(results)} package(s))"]
    lines.append("=" * 50)

    for pkg_name, pkg_results in results.items():
        lines.append(f"\n  {pkg_name}")
        if "_error" in pkg_results:
            lines.append(f"    ERROR: {pkg_results['_error']}")
            continue

        synced = skipped = failed = 0
        for target, target_data in pkg_results.items():
            if target.startswith("_") or not isinstance(target_data, dict):
                continue
            for section_result in target_data.values():
                if hasattr(section_result, "synced"):
                    synced += section_result.synced
                    skipped += section_result.skipped
                    failed += section_result.failed

        lines.append(f"    synced: {synced}  skipped: {skipped}  failed: {failed}")

    return "\n".join(lines)
