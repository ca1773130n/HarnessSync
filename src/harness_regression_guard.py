from __future__ import annotations

"""Harness Regression Guard — detect capability regressions before sync writes.

Before committing sync output to disk, compare it against the previously synced
state and flag any rules or capabilities that would be **removed** from a target.

Solves the accidental regression problem: 'This sync would remove 2 rules from
your Codex config that you added manually. Proceed?'

Usage:
    guard = RegressionGuard(project_dir)
    regressions = guard.check(target_name, new_content_map)
    if regressions:
        report = guard.format_report(regressions)
        print(report)
        if not guard.prompt_confirm(regressions):
            sys.exit(1)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from src.state_manager import StateManager
from src.utils.logger import Logger


# Section header pattern (Markdown H2/H3)
_SECTION_RE = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)

# Rule bullet pattern (lines starting with - or *)
_RULE_RE = re.compile(r"^[-*]\s+.+$", re.MULTILINE)


def _extract_sections(content: str) -> dict[str, str]:
    """Extract named sections from Markdown content.

    Returns a dict mapping section heading -> section body text.
    """
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(content))
    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections[heading] = content[start:end]
    return sections


def _extract_rules(content: str) -> set[str]:
    """Extract bullet-point rules from content as a set of stripped strings."""
    return {m.group(0).lstrip("-* ").strip() for m in _RULE_RE.finditer(content)}


@dataclass
class Regression:
    """A single regression — a rule or section removed from a target config."""

    target: str
    file_path: str
    kind: str               # "section" | "rule" | "file"
    removed_name: str       # Section heading or rule text
    context: str = ""       # Surrounding context for display

    def format(self) -> str:
        if self.kind == "file":
            return f"  [FILE REMOVED]  {self.file_path}"
        if self.kind == "section":
            return f"  [SECTION]  ## {self.removed_name}  ({self.file_path})"
        return f"  [RULE]     - {self.removed_name[:120]}  ({self.file_path})"


@dataclass
class RegressionReport:
    """Aggregate result of a regression check for one target."""

    target: str
    regressions: list[Regression] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.regressions)

    @property
    def has_regressions(self) -> bool:
        return bool(self.regressions)


class RegressionGuard:
    """Compare proposed sync output against previous sync state and flag removals.

    Args:
        project_dir: Project root directory.
        state_manager: Optional StateManager for dependency injection.
    """

    def __init__(self, project_dir: Path, state_manager: StateManager | None = None):
        self.project_dir = project_dir
        self.state_manager = state_manager or StateManager()
        self.logger = Logger()

    def check(
        self,
        target: str,
        new_content_map: dict[str, str],
    ) -> RegressionReport:
        """Check if new_content_map removes anything from the current on-disk state.

        Args:
            target: Target harness name (e.g. "codex", "gemini").
            new_content_map: Dict mapping relative file path -> new content string.
                             Files absent from this map won't be written (not deleted).

        Returns:
            RegressionReport with any detected regressions.
        """
        report = RegressionReport(target=target)

        for rel_path, new_content in new_content_map.items():
            abs_path = self.project_dir / rel_path
            if not abs_path.exists():
                # New file — no regression possible
                continue

            try:
                existing_content = abs_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Skip if file hasn't changed
            if existing_content.strip() == new_content.strip():
                continue

            # Compare sections
            old_sections = _extract_sections(existing_content)
            new_sections = _extract_sections(new_content)
            for heading, body in old_sections.items():
                if heading not in new_sections:
                    report.regressions.append(Regression(
                        target=target,
                        file_path=rel_path,
                        kind="section",
                        removed_name=heading,
                    ))

            # Compare bullet rules within matching sections
            old_rules = _extract_rules(existing_content)
            new_rules = _extract_rules(new_content)
            for rule in old_rules - new_rules:
                # Only flag rules that were in the old content but not in new
                report.regressions.append(Regression(
                    target=target,
                    file_path=rel_path,
                    kind="rule",
                    removed_name=rule,
                ))

        return report

    def check_file_deletions(
        self,
        target: str,
        files_to_write: set[str],
    ) -> RegressionReport:
        """Check if a sync operation would leave tracked files unwritten (deletion risk).

        Args:
            target: Target harness name.
            files_to_write: Set of relative paths that will be written.

        Returns:
            RegressionReport with file-level regressions.
        """
        report = RegressionReport(target=target)
        target_status = self.state_manager.get_target_status(target)
        if not target_status:
            return report

        previously_written = set(target_status.get("file_hashes", {}).keys())
        for path_str in previously_written:
            rel = str(Path(path_str).relative_to(self.project_dir)) if Path(path_str).is_absolute() else path_str
            if rel not in files_to_write and not any(p.endswith(rel) for p in files_to_write):
                report.regressions.append(Regression(
                    target=target,
                    file_path=path_str,
                    kind="file",
                    removed_name=Path(path_str).name,
                ))

        return report

    def format_report(self, report: RegressionReport) -> str:
        """Format a RegressionReport for terminal output."""
        if not report.has_regressions:
            return ""

        lines = [
            f"\n⚠  Regression Guard — {report.target.upper()}: "
            f"{report.count} item(s) would be REMOVED from current config:",
        ]

        by_kind: dict[str, list[Regression]] = {"file": [], "section": [], "rule": []}
        for r in report.regressions:
            by_kind.setdefault(r.kind, []).append(r)

        if by_kind["file"]:
            lines.append(f"\n  Files that would no longer be written ({len(by_kind['file'])}):")
            for r in by_kind["file"][:10]:
                lines.append(r.format())

        if by_kind["section"]:
            lines.append(f"\n  Sections that would be removed ({len(by_kind['section'])}):")
            for r in by_kind["section"][:10]:
                lines.append(r.format())

        if by_kind["rule"]:
            lines.append(f"\n  Rules that would be removed ({len(by_kind['rule'])}):")
            for r in by_kind["rule"][:10]:
                lines.append(r.format())
            if len(by_kind["rule"]) > 10:
                lines.append(f"  ... and {len(by_kind['rule']) - 10} more rules.")

        lines.append("\nProceed? [y/N]")
        return "\n".join(lines)

    def prompt_confirm(self, report: RegressionReport) -> bool:
        """Interactively ask the user to confirm a regressive sync.

        Returns True if the user confirms, False to abort. In non-interactive
        contexts (no TTY) returns False (safe default: abort).
        """
        import sys

        if not report.has_regressions:
            return True

        if not sys.stdin.isatty():
            self.logger.warning(
                f"RegressionGuard: {report.count} regression(s) detected for "
                f"{report.target} — aborting (non-interactive mode)."
            )
            return False

        print(self.format_report(report))
        try:
            answer = input("  Choice [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            return False

        return answer in ("y", "yes")
