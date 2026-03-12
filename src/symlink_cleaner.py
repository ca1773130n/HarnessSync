from __future__ import annotations

"""
Broken symlink detection, health reporting, and repair for all target directories.

Provides SymlinkCleaner for finding, reporting, and removing broken symlinks from
all harness-specific skill/agent/command/rule directories. Implements SAF-05 from
Phase 5 safety validation and extends it to the full set of supported targets.

Based on pathlib documentation's broken symlink detection pattern:
is_symlink() and not exists().

Health report (non-destructive scan) vs. cleanup (destructive removal) are separate
operations. Use health_report() to surface issues in /sync-health, and cleanup() or
auto_repair() to fix them.
"""

from dataclasses import dataclass, field
from pathlib import Path

from src.utils.logger import Logger


@dataclass
class SymlinkStatus:
    """Status of a single symlink discovered during a scan."""

    path: Path
    target: str          # logical harness target name (e.g. "cursor")
    broken: bool         # True if symlink exists but target doesn't
    orphaned: bool       # True if symlink target path has no source equivalent
    link_target: str     # the path the symlink points to (resolved string)


@dataclass
class SymlinkHealthReport:
    """Aggregated health report across all targets."""

    scanned_dirs: list[str] = field(default_factory=list)
    valid_symlinks: list[SymlinkStatus] = field(default_factory=list)
    broken_symlinks: list[SymlinkStatus] = field(default_factory=list)
    missing_dirs: list[str] = field(default_factory=list)

    @property
    def total_symlinks(self) -> int:
        return len(self.valid_symlinks) + len(self.broken_symlinks)

    @property
    def healthy(self) -> bool:
        return len(self.broken_symlinks) == 0

    def format(self, verbose: bool = False) -> str:
        lines: list[str] = ["Symlink Health Report", "=" * 40]
        lines.append(f"Scanned dirs: {len(self.scanned_dirs)}")
        lines.append(f"Total symlinks: {self.total_symlinks}")
        lines.append(f"Valid: {len(self.valid_symlinks)}")
        lines.append(f"Broken: {len(self.broken_symlinks)}")
        if self.missing_dirs:
            lines.append(f"Missing dirs (skipped): {len(self.missing_dirs)}")

        if self.broken_symlinks:
            lines.append("\nBroken symlinks:")
            for s in self.broken_symlinks:
                lines.append(f"  [{s.target}] {s.path}")
                lines.append(f"    → {s.link_target} (missing)")

        if verbose and self.valid_symlinks:
            lines.append("\nValid symlinks:")
            for s in self.valid_symlinks:
                lines.append(f"  [{s.target}] {s.path.name} → {s.link_target}")

        if self.healthy:
            lines.append("\nAll symlinks healthy.")
        else:
            lines.append(
                f"\n{len(self.broken_symlinks)} broken symlink(s) found. "
                "Run /sync-health --repair to fix."
            )
        return "\n".join(lines)


class SymlinkCleaner:
    """
    Broken symlink detector, health reporter, and cleaner for all target directories.

    Features:
    - Detects broken symlinks using is_symlink() + not exists() pattern
    - Covers all supported harness targets (codex, opencode, cursor, windsurf,
      cline, continue, zed, neovim — gemini/aider use inline content, no symlinks)
    - health_report(): non-destructive scan returning SymlinkHealthReport
    - cleanup(): remove broken symlinks for a specific target
    - cleanup_all(): remove broken symlinks across all targets
    - auto_repair(): attempt to re-resolve broken symlinks from source directory
    - Preserves valid symlinks and regular files
    - Handles non-existent directories gracefully
    """

    # Map target names to their symlink-containing directories (relative to project_dir)
    TARGET_DIRS: dict[str, list[str]] = {
        "codex": [
            ".codex/skills/",
        ],
        "opencode": [
            ".opencode/skills/",
            ".opencode/agents/",
            ".opencode/commands/",
        ],
        "cursor": [
            ".cursor/rules/skills/",
            ".cursor/rules/agents/",
        ],
        "windsurf": [
            ".windsurf/memories/",
            ".windsurf/rules/",
        ],
        "cline": [
            ".roo/rules/skills/",
        ],
        "continue": [
            ".continue/rules/",
        ],
        "zed": [
            ".zed/prompts/skills/",
        ],
        "neovim": [
            ".avante/rules/skills/",
        ],
        # Inline-content targets — no symlinks created
        "gemini": [],
        "aider": [],
    }

    def __init__(self, project_dir: Path, logger: Logger = None):
        """
        Initialize symlink cleaner.

        Args:
            project_dir: Project directory (contains .codex/, .cursor/, etc.)
            logger: Optional logger for cleanup operations
        """
        self.project_dir = project_dir
        self.logger = logger or Logger()

    # ------------------------------------------------------------------
    # Health reporting (non-destructive)
    # ------------------------------------------------------------------

    def health_report(
        self,
        targets: list[str] | None = None,
    ) -> SymlinkHealthReport:
        """Scan all target directories and return a health report.

        This is a NON-DESTRUCTIVE operation — no symlinks are removed.

        Args:
            targets: Specific target names to scan (default: all known targets).

        Returns:
            SymlinkHealthReport with valid and broken symlinks separated.
        """
        check_targets = targets or list(self.TARGET_DIRS.keys())
        report = SymlinkHealthReport()

        for target_name in check_targets:
            dirs = self.TARGET_DIRS.get(target_name, [])
            for rel_dir in dirs:
                directory = self.project_dir / rel_dir
                report.scanned_dirs.append(str(directory))

                if not directory.exists() or not directory.is_dir():
                    report.missing_dirs.append(str(directory))
                    continue

                try:
                    for item in directory.rglob("*"):
                        if not item.is_symlink():
                            continue
                        link_target_str = ""
                        try:
                            link_target_str = str(item.readlink())
                        except (OSError, AttributeError):
                            try:
                                import os
                                link_target_str = os.readlink(str(item))
                            except OSError:
                                link_target_str = "<unreadable>"

                        status = SymlinkStatus(
                            path=item,
                            target=target_name,
                            broken=not item.exists(),
                            orphaned=False,
                            link_target=link_target_str,
                        )
                        if status.broken:
                            report.broken_symlinks.append(status)
                        else:
                            report.valid_symlinks.append(status)

                except (OSError, PermissionError) as e:
                    self.logger.warn(f"Error scanning {directory}: {e}")

        return report

    # ------------------------------------------------------------------
    # Broken symlink detection (legacy helper used by cleanup)
    # ------------------------------------------------------------------

    def find_broken_symlinks(self, directory: Path) -> list[Path]:
        """
        Find all broken symlinks in a directory (recursive).

        Args:
            directory: Directory to scan

        Returns:
            List of broken symlink paths

        Note:
            Uses is_symlink() and not exists() pattern per pathlib documentation.
            Does NOT use lexists() which returns True for broken links.
        """
        if not directory.exists() or not directory.is_dir():
            return []

        broken = []

        try:
            for item in directory.rglob("*"):
                # CRITICAL: Use is_symlink() first, then exists()
                # exists() follows symlinks, so broken symlinks return False
                if item.is_symlink() and not item.exists():
                    broken.append(item)

        except (OSError, PermissionError) as e:
            self.logger.warn(f"Error scanning {directory}: {e}")

        return broken

    # ------------------------------------------------------------------
    # Cleanup (destructive removal of broken symlinks)
    # ------------------------------------------------------------------

    def cleanup(self, target_name: str) -> list[Path]:
        """
        Clean broken symlinks for a specific target.

        Args:
            target_name: Target name (e.g. 'codex', 'cursor', 'windsurf')

        Returns:
            List of removed symlink paths

        Note:
            - Targets with no symlink dirs (gemini, aider) return empty list
            - Logs errors but continues processing remaining symlinks
        """
        if target_name not in self.TARGET_DIRS:
            self.logger.warn(f"Unknown target: {target_name}")
            return []

        removed = []

        for rel_dir in self.TARGET_DIRS[target_name]:
            directory = self.project_dir / rel_dir
            broken_links = self.find_broken_symlinks(directory)

            for broken_link in broken_links:
                try:
                    broken_link.unlink()
                    removed.append(broken_link)
                    self.logger.info(
                        f"Removed broken symlink: {broken_link.relative_to(self.project_dir)}"
                    )
                except OSError as e:
                    self.logger.error(f"Failed to remove {broken_link}: {e}")

        return removed

    def cleanup_all(self) -> dict[str, list[Path]]:
        """
        Run cleanup for all targets.

        Returns:
            Dict mapping target_name -> list of removed paths
        """
        results: dict[str, list[Path]] = {}
        for target_name in self.TARGET_DIRS:
            removed = self.cleanup(target_name)
            results[target_name] = removed
        return results

    # ------------------------------------------------------------------
    # Auto-repair (attempt to re-create broken symlinks from source)
    # ------------------------------------------------------------------

    def auto_repair(
        self,
        source_dir: Path,
        targets: list[str] | None = None,
        dry_run: bool = False,
    ) -> dict[str, list[str]]:
        """Attempt to repair broken symlinks by re-pointing them to source_dir.

        For each broken symlink named ``foo.md`` in a target directory, checks
        if ``source_dir/foo.md`` (or ``source_dir/foo/``) exists and recreates
        the symlink if it does.

        Args:
            source_dir: Directory to look for source files (e.g. ~/.claude/skills/).
            targets: Specific targets to repair (default: all).
            dry_run: If True, report what would be repaired without making changes.

        Returns:
            Dict mapping target_name -> list of repair result strings
            (format: "repaired: <path>" or "missing-source: <path>").
        """
        check_targets = targets or list(self.TARGET_DIRS.keys())
        results: dict[str, list[str]] = {}

        for target_name in check_targets:
            repaired: list[str] = []
            for rel_dir in self.TARGET_DIRS.get(target_name, []):
                directory = self.project_dir / rel_dir
                broken_links = self.find_broken_symlinks(directory)

                for broken_link in broken_links:
                    stem = broken_link.stem
                    # Try matching by stem in source_dir
                    source_candidate: Path | None = None
                    for ext in ("", ".md", ".mdc", ".txt"):
                        candidate = source_dir / f"{stem}{ext}"
                        if candidate.exists():
                            source_candidate = candidate
                            break
                    # Also check as directory
                    if source_candidate is None:
                        candidate_dir = source_dir / stem
                        if candidate_dir.is_dir():
                            source_candidate = candidate_dir

                    if source_candidate is None:
                        repaired.append(f"missing-source: {broken_link.name}")
                        continue

                    if dry_run:
                        repaired.append(f"would-repair: {broken_link.name} → {source_candidate}")
                        continue

                    try:
                        broken_link.unlink(missing_ok=True)
                        broken_link.symlink_to(source_candidate)
                        repaired.append(f"repaired: {broken_link.name} → {source_candidate}")
                        self.logger.info(
                            f"Repaired symlink: {broken_link.relative_to(self.project_dir)} → {source_candidate}"
                        )
                    except OSError as e:
                        repaired.append(f"error: {broken_link.name} ({e})")
                        self.logger.error(f"Failed to repair {broken_link}: {e}")

            if repaired:
                results[target_name] = repaired

        return results

    # ------------------------------------------------------------------
    # Convenience: count broken symlinks without removing
    # ------------------------------------------------------------------

    def count_broken(self, targets: list[str] | None = None) -> int:
        """Return the total count of broken symlinks across all scanned dirs.

        Args:
            targets: Specific targets to scan (default: all).

        Returns:
            Integer count of broken symlinks found.
        """
        report = self.health_report(targets=targets)
        return len(report.broken_symlinks)
