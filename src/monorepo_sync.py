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
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


# ──────────────────────────────────────────────────────────────────────────────
# Org-Level Config Federation
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class FederationResult:
    """Result of an org config federation pull."""

    success: bool
    source_repo: str
    files_merged: list[str]
    errors: list[str]
    source_ref: str = ""      # git ref (branch/tag/SHA) pulled from

    @property
    def summary(self) -> str:
        lines = ["Org Config Federation"]
        if self.success:
            lines.append(f"  ✓ Source: {self.source_repo}")
            if self.source_ref:
                lines.append(f"  ✓ Ref:    {self.source_ref}")
            lines.append(f"  ✓ Merged: {len(self.files_merged)} file(s)")
            for f in self.files_merged:
                lines.append(f"    · {f}")
        else:
            lines.append("  ✗ Failed")
            for err in self.errors:
                lines.append(f"  · {err}")
        return "\n".join(lines)


class OrgConfigFederation:
    """Pull org-wide base rules from a central repository and merge locally.

    Implements the federation part of item 19 (Multi-Repo Config Federation):
    a central org repo maintains a base ``CLAUDE.md`` and skills that all
    sub-repos inherit.  Individual repos layer on project-specific rules on
    top of the org base.

    Merge strategy:
    - The org ``CLAUDE.md`` is prepended to the local ``CLAUDE.md`` under a
      clearly delimited ``## Org Rules`` section.
    - If the org rules section already exists, it is replaced in-place so
      re-running federation is idempotent.
    - Skills from the org repo are copied into the local ``~/.claude/skills/``
      directory; existing project-specific skills are not overwritten unless
      ``overwrite_skills=True``.

    Args:
        project_dir: Local project root directory.
        org_repo: URL or local path of the central org repository.
        ref: Branch, tag, or SHA to pull from (default: ``"main"``).
        rules_file: Relative path to the org-level rules file in the repo
                    (default: ``"CLAUDE.md"``).
        cc_home: Claude Code home directory (default: ``~/.claude``).
    """

    # Delimiters embedded in the local CLAUDE.md to mark org-managed content
    _ORG_SECTION_BEGIN = "<!-- harness-sync:org-rules:begin -->"
    _ORG_SECTION_END = "<!-- harness-sync:org-rules:end -->"

    def __init__(
        self,
        project_dir: Path,
        org_repo: str,
        ref: str = "main",
        rules_file: str = "CLAUDE.md",
        cc_home: Path | None = None,
    ):
        self.project_dir = project_dir
        self.org_repo = org_repo
        self.ref = ref
        self.rules_file = rules_file
        self.cc_home = cc_home or Path.home() / ".claude"
        self.logger = Logger()

    def pull(
        self,
        overwrite_skills: bool = False,
        dry_run: bool = False,
    ) -> FederationResult:
        """Pull org config and merge into the local project.

        Args:
            overwrite_skills: If True, org skills overwrite local skills with the
                              same name. Default: False (local skills take precedence).
            dry_run: If True, preview what would be merged without writing.

        Returns:
            FederationResult describing merged files and any errors.
        """
        errors: list[str] = []
        files_merged: list[str] = []
        actual_ref = self.ref

        with tempfile.TemporaryDirectory(prefix="hs-org-fed-") as tmpdir:
            tmp = Path(tmpdir)
            clone_dir = tmp / "org-repo"

            # Shallow clone — we only need the tip of the ref
            rc, stdout, stderr = self._run_git(
                ["clone", "--depth=1", "--branch", self.ref,
                 self.org_repo, str(clone_dir)],
                cwd=tmp,
            )
            if rc != 0:
                # Try without --branch (might be a commit SHA or default branch)
                rc2, _, err2 = self._run_git(
                    ["clone", "--depth=1", self.org_repo, str(clone_dir)],
                    cwd=tmp,
                )
                if rc2 != 0:
                    return FederationResult(
                        success=False,
                        source_repo=self.org_repo,
                        files_merged=[],
                        errors=[f"Could not clone {self.org_repo}: {stderr or err2}"],
                    )

            # Resolve actual commit SHA for the result
            _, sha, _ = self._run_git(
                ["rev-parse", "--short", "HEAD"], cwd=clone_dir
            )
            actual_ref = sha or self.ref

            # Merge org CLAUDE.md
            org_rules_path = clone_dir / self.rules_file
            if org_rules_path.exists():
                org_content = org_rules_path.read_text(encoding="utf-8")
                merged, was_changed = self._merge_org_rules(org_content, dry_run=dry_run)
                if was_changed:
                    files_merged.append(self.rules_file)
                    if not dry_run:
                        local_claude_md = self.project_dir / "CLAUDE.md"
                        local_claude_md.parent.mkdir(parents=True, exist_ok=True)
                        local_claude_md.write_text(merged, encoding="utf-8")

            # Merge org skills
            org_skills_dir = clone_dir / ".claude" / "skills"
            if not org_skills_dir.exists():
                org_skills_dir = clone_dir / "skills"

            if org_skills_dir.is_dir():
                local_skills_dir = self.cc_home / "skills"
                for skill_dir in org_skills_dir.iterdir():
                    if not skill_dir.is_dir():
                        continue
                    skill_md = skill_dir / "SKILL.md"
                    if not skill_md.exists():
                        continue
                    dest_skill_dir = local_skills_dir / skill_dir.name
                    dest_skill_md = dest_skill_dir / "SKILL.md"
                    if dest_skill_md.exists() and not overwrite_skills:
                        continue  # Preserve local skills
                    files_merged.append(f".claude/skills/{skill_dir.name}/SKILL.md")
                    if not dry_run:
                        dest_skill_dir.mkdir(parents=True, exist_ok=True)
                        dest_skill_md.write_text(
                            skill_md.read_text(encoding="utf-8"), encoding="utf-8"
                        )

        return FederationResult(
            success=not errors,
            source_repo=self.org_repo,
            files_merged=files_merged,
            errors=errors,
            source_ref=actual_ref,
        )

    def _merge_org_rules(
        self, org_content: str, dry_run: bool = False
    ) -> tuple[str, bool]:
        """Merge org rules into the local CLAUDE.md.

        Wraps ``org_content`` in org-section delimiters and either inserts it
        at the top of the local file or replaces an existing org section.

        Args:
            org_content: Raw content of the org-level CLAUDE.md.
            dry_run: If True, compute the merged result without side effects.

        Returns:
            Tuple of (merged_text, was_changed).
        """
        org_block = (
            f"{self._ORG_SECTION_BEGIN}\n"
            f"<!-- Managed by HarnessSync org federation — do not edit manually -->\n"
            f"{org_content.strip()}\n"
            f"{self._ORG_SECTION_END}\n"
        )

        local_claude_md = self.project_dir / "CLAUDE.md"
        if local_claude_md.exists():
            local_text = local_claude_md.read_text(encoding="utf-8")
        else:
            local_text = ""

        # Replace existing org section if present
        begin = self._ORG_SECTION_BEGIN
        end = self._ORG_SECTION_END
        if begin in local_text and end in local_text:
            pre = local_text[: local_text.index(begin)]
            post = local_text[local_text.index(end) + len(end):]
            merged = f"{pre}{org_block}{post}"
        else:
            # Prepend at top — project rules follow below
            merged = f"{org_block}\n{local_text}" if local_text else org_block

        was_changed = merged != local_text
        return merged, was_changed

    @staticmethod
    def _run_git(args: list[str], cwd: Path) -> tuple[int, str, str]:
        """Run a git command and return (returncode, stdout, stderr)."""
        try:
            result = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                cwd=str(cwd),
                timeout=30,
            )
            return result.returncode, result.stdout.strip(), result.stderr.strip()
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, "", str(exc)

    def check_for_updates(self) -> bool:
        """Return True if the remote org repo has new commits since last pull.

        Uses ``git ls-remote`` to fetch the remote tip SHA without cloning.
        Compares against the SHA stored in ``.harnesssync-org-state.json``.

        Returns:
            True if remote has newer commits, False if up-to-date or unreachable.
        """
        state_path = self.project_dir / ".harnesssync-org-state.json"
        last_sha = ""
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                last_sha = state.get("last_sha", "")
            except (OSError, json.JSONDecodeError):
                pass

        try:
            result = subprocess.run(
                ["git", "ls-remote", self.org_repo, f"refs/heads/{self.ref}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return False
            lines = result.stdout.strip().splitlines()
            if not lines:
                return False
            remote_sha = lines[0].split()[0]
            if remote_sha and remote_sha != last_sha:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass
        return False

    def record_pull(self, result: FederationResult) -> None:
        """Persist federation state so ``check_for_updates`` can detect drift.

        Args:
            result: The FederationResult from a successful pull.
        """
        state_path = self.project_dir / ".harnesssync-org-state.json"
        state = {
            "last_sha": result.source_ref,
            "last_pull_at": datetime.now(timezone.utc).isoformat(),
            "source_repo": result.source_repo,
            "files_merged": result.files_merged,
        }
        try:
            state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Multi-Workspace Sync Manager (Item 28)
# ---------------------------------------------------------------------------

@dataclass
class WorkspaceEntry:
    """A registered workspace directory with its sync status."""

    path: Path
    name: str
    last_sync_time: float | None = None  # Unix timestamp
    sync_profile: str | None = None      # Named profile override for this workspace
    enabled: bool = True


class MultiWorkspaceSyncManager:
    """Manage HarnessSync across multiple project directories from a single control plane.

    Item 28: Power users with 10+ projects each have separate Claude Code configs
    that diverge. A multi-workspace view makes maintaining consistency across
    projects tractable.

    Workspace registry is stored at ~/.harnesssync/workspaces.json.

    Usage::

        manager = MultiWorkspaceSyncManager()
        manager.register(Path("/work/projectA"), name="projectA")
        manager.register(Path("/work/projectB"), name="projectB", profile="backend")
        statuses = manager.get_all_statuses()
        print(manager.format_dashboard(statuses))
    """

    _REGISTRY_FILE = Path.home() / ".harnesssync" / "workspaces.json"

    def __init__(self, registry_file: Path | None = None):
        self._registry_file = registry_file or self._REGISTRY_FILE

    def _load(self) -> list[dict]:
        if not self._registry_file.exists():
            return []
        try:
            data = json.loads(self._registry_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, entries: list[dict]) -> None:
        self._registry_file.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=self._registry_file.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        ) as tmp:
            json.dump(entries, tmp, indent=2)
            tmp_path = Path(tmp.name)
        tmp_path.replace(self._registry_file)

    def register(
        self,
        workspace_dir: Path,
        name: str | None = None,
        profile: str | None = None,
        enabled: bool = True,
    ) -> WorkspaceEntry:
        """Register a workspace directory.

        Args:
            workspace_dir: Absolute path to the project directory.
            name: Human-readable name (defaults to directory name).
            profile: Named sync profile to use for this workspace.
            enabled: Whether this workspace participates in syncs.

        Returns:
            WorkspaceEntry for the registered workspace.
        """
        abs_path = Path(workspace_dir).resolve()
        name = name or abs_path.name

        entries = self._load()
        # Remove existing entry for same path
        entries = [e for e in entries if e.get("path") != str(abs_path)]
        entries.append({
            "path": str(abs_path),
            "name": name,
            "last_sync_time": None,
            "sync_profile": profile,
            "enabled": enabled,
        })
        self._save(entries)

        return WorkspaceEntry(
            path=abs_path,
            name=name,
            sync_profile=profile,
            enabled=enabled,
        )

    def unregister(self, workspace_dir: Path) -> bool:
        """Remove a workspace from the registry.

        Args:
            workspace_dir: Path to remove.

        Returns:
            True if found and removed, False if not registered.
        """
        abs_path = Path(workspace_dir).resolve()
        entries = self._load()
        new_entries = [e for e in entries if e.get("path") != str(abs_path)]
        if len(new_entries) == len(entries):
            return False
        self._save(new_entries)
        return True

    def list_workspaces(self) -> list[WorkspaceEntry]:
        """Return all registered workspaces.

        Returns:
            List of WorkspaceEntry objects sorted by name.
        """
        entries = self._load()
        result: list[WorkspaceEntry] = []
        for e in entries:
            path_str = e.get("path", "")
            if not path_str:
                continue
            result.append(WorkspaceEntry(
                path=Path(path_str),
                name=e.get("name", Path(path_str).name),
                last_sync_time=e.get("last_sync_time"),
                sync_profile=e.get("sync_profile"),
                enabled=e.get("enabled", True),
            ))
        return sorted(result, key=lambda w: w.name.lower())

    def update_sync_time(self, workspace_dir: Path) -> None:
        """Record a successful sync timestamp for a workspace.

        Args:
            workspace_dir: Path that was synced.
        """
        import time as _time
        abs_path = Path(workspace_dir).resolve()
        entries = self._load()
        for entry in entries:
            if entry.get("path") == str(abs_path):
                entry["last_sync_time"] = _time.time()
                break
        self._save(entries)

    def get_all_statuses(self) -> list[dict]:
        """Return status dicts for all registered workspaces.

        Returns:
            List of status dicts with keys:
                - name: str
                - path: str
                - enabled: bool
                - sync_profile: str | None
                - days_since_sync: float | None
                - has_claude_md: bool
                - drift_status: "fresh" | "stale" | "never" | "unknown"
        """
        import time as _time

        now = _time.time()
        STALE_DAYS = 7

        result: list[dict] = []
        for ws in self.list_workspaces():
            has_claude_md = (ws.path / "CLAUDE.md").is_file()

            if ws.last_sync_time is None:
                days_since = None
                drift = "never"
            else:
                days_since = round((now - ws.last_sync_time) / 86400, 1)
                drift = "stale" if days_since > STALE_DAYS else "fresh"

            result.append({
                "name": ws.name,
                "path": str(ws.path),
                "enabled": ws.enabled,
                "sync_profile": ws.sync_profile,
                "days_since_sync": days_since,
                "has_claude_md": has_claude_md,
                "drift_status": drift,
            })

        return result

    def format_dashboard(self, statuses: list[dict]) -> str:
        """Render a multi-workspace status dashboard.

        Args:
            statuses: Output of get_all_statuses().

        Returns:
            Multi-line formatted string.
        """
        if not statuses:
            return (
                "No workspaces registered.\n"
                "Register with: MultiWorkspaceSyncManager().register(Path('.'))"
            )

        lines = ["Multi-Workspace Sync Dashboard", "=" * 55, ""]
        for s in statuses:
            status_icon = {"fresh": "✓", "stale": "⚠", "never": "○", "unknown": "?"}.get(
                s["drift_status"], "?"
            )
            enabled_mark = "" if s["enabled"] else " [disabled]"
            profile_mark = f" (profile: {s['sync_profile']})" if s["sync_profile"] else ""
            days_str = (
                f"{s['days_since_sync']}d ago"
                if s["days_since_sync"] is not None
                else "never synced"
            )
            claude_mark = "" if s["has_claude_md"] else " [no CLAUDE.md]"
            lines.append(
                f"  {status_icon} {s['name']:<20} {days_str:<15}{profile_mark}{enabled_mark}{claude_mark}"
            )
            lines.append(f"      {s['path']}")
            lines.append("")

        stale = [s for s in statuses if s["drift_status"] == "stale"]
        never = [s for s in statuses if s["drift_status"] == "never"]
        if stale or never:
            lines.append(
                f"  {len(stale)} stale, {len(never)} never-synced workspace(s) need attention."
            )
            lines.append("  Run /sync --workspace <path> for each stale workspace.")

        return "\n".join(lines)
