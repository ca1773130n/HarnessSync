from __future__ import annotations

"""Structured dry-run summary report (Item 27).

Transforms raw orchestrator preview results into a structured, actionable
summary: how many files would change, which are unchanged, why files are
skipped, any warnings, and estimated context size impact per harness.

This replaces the raw "would write X" output with a concise planning tool::

    Dry-Run Summary
    ========================================
      + 3 files would be created
      ~ 2 files would be modified
      = 1 file unchanged
      - 1 file skipped
      1 warning

      Would create:
        + codex/AGENTS.md
        + gemini/GEMINI.md
        + cursor/.cursor/rules/claude-code-rules.mdc

      Would modify:
        ~ opencode/opencode.json

      Skipped:
        - aider/CONVENTIONS.md  [sync:skip annotation]

      Warnings:
        ⚠ drift detected in cursor/.cursor/rules/claude-code-rules.mdc

      Estimated context size impact:
        codex         +1.2 KB
        gemini        +0.8 KB
        cursor        +2.1 KB

      Targets previewed: codex, gemini, opencode, cursor, aider
      (dry-run complete, no files modified)

Usage::

    from src.dry_run_report import DryRunReport

    report = DryRunReport.from_results(results, project_dir=project_dir)
    print(report.format())

    # JSON output (for CI / tooling)
    import json
    print(json.dumps(report.to_dict(), indent=2))
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class FileChange:
    """Represents a single file change in a dry-run preview."""

    path: str
    target: str
    status: str     # "create" | "modify" | "unchanged" | "skipped" | "error"
    reason: str = ""
    size_delta: int = 0  # Bytes delta (positive = larger, negative = smaller)


@dataclass
class DryRunReport:
    """Structured dry-run report built from orchestrator preview results."""

    changes: list[FileChange] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    targets_previewed: list[str] = field(default_factory=list)

    # ── Filtered views ──────────────────────────────────────────────────────

    @property
    def created(self) -> list[FileChange]:
        return [c for c in self.changes if c.status == "create"]

    @property
    def modified(self) -> list[FileChange]:
        return [c for c in self.changes if c.status == "modify"]

    @property
    def unchanged(self) -> list[FileChange]:
        return [c for c in self.changes if c.status == "unchanged"]

    @property
    def skipped(self) -> list[FileChange]:
        return [c for c in self.changes if c.status == "skipped"]

    @property
    def errors(self) -> list[FileChange]:
        return [c for c in self.changes if c.status == "error"]

    @property
    def total_would_change(self) -> int:
        return len(self.created) + len(self.modified)

    # ── Constructors ────────────────────────────────────────────────────────

    @classmethod
    def from_results(
        cls,
        results: dict,
        project_dir: Path | None = None,
        extra_warnings: list[str] | None = None,
    ) -> "DryRunReport":
        """Build a :class:`DryRunReport` from orchestrator ``sync_all()`` results.

        The orchestrator populates ``results[target]["preview"]`` as a dict
        ``{file_path: {status, reason, size_delta}}`` when running in dry-run
        mode.  Falls back to inferring changes from :class:`SyncResult` fields
        when ``"preview"`` is absent.

        Args:
            results: Dict from ``SyncOrchestrator.sync_all()``.
            project_dir: Project root (currently unused; reserved for future
                         relative-path computation).
            extra_warnings: Additional warning strings to include.

        Returns:
            Populated :class:`DryRunReport`.
        """
        changes: list[FileChange] = []
        targets_previewed: list[str] = []
        warnings: list[str] = list(extra_warnings or [])

        for target, target_results in results.items():
            if target.startswith("_") or not isinstance(target_results, dict):
                continue
            targets_previewed.append(target)

            preview = target_results.get("preview")

            if isinstance(preview, dict):
                # Structured preview dict written by _preview_sync()
                for file_path, info in preview.items():
                    if isinstance(info, dict):
                        status = info.get("status", "modify")
                        reason = info.get("reason", "")
                        size_delta = int(info.get("size_delta", 0))
                    else:
                        status = "modify"
                        reason = ""
                        size_delta = 0
                    changes.append(FileChange(
                        path=str(file_path),
                        target=target,
                        status=status,
                        reason=reason,
                        size_delta=size_delta,
                    ))
            else:
                # Fallback: infer from SyncResult fields
                for section, result in target_results.items():
                    if section.startswith("_"):
                        continue
                    if hasattr(result, "synced") and result.synced:
                        changes.append(FileChange(
                            path=f"{target}/{section}",
                            target=target,
                            status="modify",
                        ))
                    for f in getattr(result, "skipped_files", []):
                        changes.append(FileChange(
                            path=str(f),
                            target=target,
                            status="skipped",
                        ))
                    for f in getattr(result, "failed_files", []):
                        changes.append(FileChange(
                            path=str(f),
                            target=target,
                            status="error",
                            reason=str(f),
                        ))

        # Collect warnings from special result keys
        for key in ("_warnings", "_conflicts"):
            val = results.get(key)
            if isinstance(val, list):
                warnings.extend(str(w) for w in val)
            elif isinstance(val, str) and val:
                warnings.append(val)

        return cls(
            changes=changes,
            warnings=warnings,
            targets_previewed=targets_previewed,
        )

    # ── Formatting ──────────────────────────────────────────────────────────

    def format(self, show_files: bool = True, max_files: int = 20) -> str:
        """Format the report for terminal display.

        Args:
            show_files: If ``True``, list individual files under each group.
            max_files: Maximum files to show per group before truncating.

        Returns:
            Formatted multi-line string.
        """
        lines = ["Dry-Run Summary", "=" * 40]

        n_create    = len(self.created)
        n_modify    = len(self.modified)
        n_unchanged = len(self.unchanged)
        n_skipped   = len(self.skipped)
        n_errors    = len(self.errors)
        n_warn      = len(self.warnings)

        def _count_line(n: int, noun_s: str, noun_p: str, icon: str = "") -> str:
            label = noun_s if n == 1 else noun_p
            prefix = f"{icon} " if icon else "  "
            return f"  {prefix}{n} {label}"

        if n_create + n_modify + n_unchanged + n_skipped + n_errors == 0:
            lines.append("  No changes — all targets are already up to date.")
        else:
            if n_create:
                lines.append(_count_line(n_create, "file would be created",
                                         "files would be created", "+"))
            if n_modify:
                lines.append(_count_line(n_modify, "file would be modified",
                                         "files would be modified", "~"))
            if n_unchanged:
                lines.append(_count_line(n_unchanged, "file unchanged",
                                         "files unchanged", "="))
            if n_skipped:
                lines.append(_count_line(n_skipped, "file skipped",
                                         "files skipped", "-"))
            if n_errors:
                lines.append(_count_line(n_errors, "error", "errors", "!"))

        if n_warn:
            lines.append(f"  {n_warn} warning{'s' if n_warn != 1 else ''}")

        if show_files:
            for group, label, icon in [
                (self.created,  "Would create", "+"),
                (self.modified, "Would modify", "~"),
                (self.skipped,  "Skipped",      "-"),
                (self.errors,   "Errors",       "!"),
            ]:
                if not group:
                    continue
                lines.append(f"\n  {label}:")
                for fc in group[:max_files]:
                    reason_str = f"  [{fc.reason}]" if fc.reason else ""
                    lines.append(f"    {icon} {fc.path}{reason_str}")
                if len(group) > max_files:
                    lines.append(f"    ... and {len(group) - max_files} more")

        if self.warnings:
            lines.append("\n  Warnings:")
            for w in self.warnings:
                lines.append(f"    ⚠ {w}")

        # Context size impact
        size_by_target: dict[str, int] = {}
        for fc in self.changes:
            if fc.size_delta:
                size_by_target[fc.target] = size_by_target.get(fc.target, 0) + fc.size_delta
        if size_by_target:
            lines.append("\n  Estimated context size impact:")
            for target, delta in sorted(size_by_target.items()):
                kb = delta / 1024
                sign = "+" if delta >= 0 else ""
                lines.append(f"    {target:<12} {sign}{kb:.1f} KB")

        targets_str = ", ".join(self.targets_previewed) if self.targets_previewed else "none"
        lines.append(f"\n  Targets previewed: {targets_str}")
        lines.append("  (dry-run complete, no files modified)")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialize the report to a plain dict suitable for JSON output.

        Returns:
            Dict with keys: ``summary``, ``changes``, ``warnings``,
            ``targets_previewed``.
        """
        return {
            "summary": {
                "would_create":  len(self.created),
                "would_modify":  len(self.modified),
                "unchanged":     len(self.unchanged),
                "skipped":       len(self.skipped),
                "errors":        len(self.errors),
                "warnings":      len(self.warnings),
                "total_changes": self.total_would_change,
            },
            "changes": [asdict(c) for c in self.changes],
            "warnings": self.warnings,
            "targets_previewed": self.targets_previewed,
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the report to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)
