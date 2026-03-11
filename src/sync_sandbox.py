from __future__ import annotations

"""Sync simulation sandbox.

Runs a full sync into a temporary directory, generating the complete file tree
that would be written to each harness target — without touching any real files.
More powerful than --dry-run: the simulated output files are fully written and
can be browsed or inspected before committing to a real sync.

Usage:
    from src.sync_sandbox import SyncSandbox

    sandbox = SyncSandbox(project_dir)
    report = sandbox.run(scope="all")
    print(report.format())
    # browse report.sandbox_dir / "codex" / ... for generated files
    sandbox.cleanup()
"""

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from src.utils.logger import Logger


@dataclass
class SandboxFileEntry:
    """A single file written during a sandbox sync."""

    relative_path: str        # Relative to the harness target root (e.g. "AGENTS.md")
    target: str               # Target name (e.g. "codex")
    size_bytes: int = 0
    is_new: bool = True       # True if the real file doesn't exist yet


@dataclass
class SandboxReport:
    """Full report of a sandbox simulation run."""

    sandbox_dir: Path
    scope: str
    project_dir: Path
    files: list[SandboxFileEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    targets_run: list[str] = field(default_factory=list)

    # Map from target name → sub-directory in sandbox_dir
    target_dirs: dict[str, Path] = field(default_factory=dict)

    def files_for_target(self, target: str) -> list[SandboxFileEntry]:
        """Return all files written for a given target."""
        return [f for f in self.files if f.target == target]

    def format(self, show_contents: bool = False) -> str:
        """Return a human-readable summary of the sandbox output."""
        lines = ["HarnessSync Sandbox Simulation"]
        lines.append("=" * 60)
        lines.append(f"Project:   {self.project_dir}")
        lines.append(f"Scope:     {self.scope}")
        lines.append(f"Sandbox:   {self.sandbox_dir}")
        lines.append(f"Targets:   {', '.join(self.targets_run) or 'none'}")
        lines.append(f"Files:     {len(self.files)} total")
        if self.errors:
            lines.append(f"Errors:    {len(self.errors)}")
        lines.append("")

        for target in self.targets_run:
            target_files = self.files_for_target(target)
            if not target_files:
                continue
            target_dir = self.target_dirs.get(target, self.sandbox_dir / target)
            lines.append(f"  {target.upper()}  ({len(target_files)} file(s))")
            lines.append(f"  Browse: {target_dir}")
            for f in target_files:
                new_marker = " [NEW]" if f.is_new else ""
                lines.append(f"    {f.relative_path:<40} {f.size_bytes:>6} B{new_marker}")
            lines.append("")

        if self.errors:
            lines.append("Errors:")
            for err in self.errors:
                lines.append(f"  {err}")

        lines.append("─" * 60)
        lines.append("Run /sync to apply these changes to your real harness configs.")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "sandbox_dir": str(self.sandbox_dir),
            "scope": self.scope,
            "project_dir": str(self.project_dir),
            "targets_run": self.targets_run,
            "file_count": len(self.files),
            "error_count": len(self.errors),
            "files": [
                {
                    "target": f.target,
                    "path": f.relative_path,
                    "size_bytes": f.size_bytes,
                    "is_new": f.is_new,
                }
                for f in self.files
            ],
            "errors": self.errors,
        }


class SyncSandbox:
    """Run a full HarnessSync operation inside a temporary directory.

    Creates isolated per-target subdirectories in a temp dir and runs the
    normal sync adapters against them, so the simulated output files are
    real files that can be browsed.

    Lifecycle:
        sandbox = SyncSandbox(project_dir)
        report = sandbox.run(scope="all")
        print(report.format())
        sandbox.cleanup()   # deletes the temp dir

    Or use as a context manager:
        with SyncSandbox(project_dir) as sandbox:
            report = sandbox.run()
            print(report.format())
    """

    def __init__(
        self,
        project_dir: Path,
        sandbox_dir: Path | None = None,
        keep_sandbox: bool = False,
    ):
        """Initialize the sandbox.

        Args:
            project_dir: Source project root.
            sandbox_dir: Use this directory instead of a temp dir (must exist).
            keep_sandbox: If True, don't delete the sandbox on cleanup().
        """
        self.project_dir = project_dir
        self.keep_sandbox = keep_sandbox
        self.logger = Logger()
        self._sandbox_dir: Path | None = sandbox_dir
        self._temp_dir: tempfile.TemporaryDirectory | None = None

    def _get_sandbox_dir(self) -> Path:
        if self._sandbox_dir is not None:
            self._sandbox_dir.mkdir(parents=True, exist_ok=True)
            return self._sandbox_dir
        # Create a persistent temp dir (NOT auto-deleted) so we can browse it
        tmp = tempfile.mkdtemp(prefix="harnesssync-sandbox-")
        self._sandbox_dir = Path(tmp)
        return self._sandbox_dir

    def run(
        self,
        scope: str = "all",
        only_sections: set[str] | None = None,
        skip_sections: set[str] | None = None,
        only_targets: set[str] | None = None,
        skip_targets: set[str] | None = None,
    ) -> SandboxReport:
        """Run a simulated full sync and return a report.

        Each target adapter is run with its ``project_dir`` pointing at a
        fresh subdirectory inside the sandbox, so all output files are written
        there instead of the real filesystem.

        Args:
            scope: Sync scope ("user" | "project" | "all").
            only_sections: If set, only sync these sections.
            skip_sections: If set, skip these sections.
            only_targets: If set, only simulate these targets.
            skip_targets: If set, skip these targets.

        Returns:
            SandboxReport with all simulated files and any errors.
        """
        from src.adapters import AdapterRegistry
        from src.orchestrator import SyncOrchestrator

        sandbox_root = self._get_sandbox_dir()
        report = SandboxReport(
            sandbox_dir=sandbox_root,
            scope=scope,
            project_dir=self.project_dir,
        )

        # Run one orchestrator per target, each with its own sandboxed project_dir
        for target_name in AdapterRegistry.list_targets():
            if only_targets and target_name not in only_targets:
                continue
            if skip_targets and target_name in skip_targets:
                continue

            # Create an isolated directory for this target
            target_sandbox = sandbox_root / target_name
            target_sandbox.mkdir(parents=True, exist_ok=True)
            report.target_dirs[target_name] = target_sandbox
            report.targets_run.append(target_name)

            try:
                # Read source from real project but write to sandbox target dir.
                # We do this by using the orchestrator with a patched adapter
                # project_dir — achieved by running a single-target orchestrator
                # that writes to target_sandbox instead of self.project_dir.
                orchestrator = SyncOrchestrator(
                    project_dir=target_sandbox,   # adapters write here
                    scope=scope,
                    dry_run=False,                # really write into sandbox
                    only_sections=only_sections or set(),
                    skip_sections=skip_sections or set(),
                    cli_only_targets={target_name},
                    cli_skip_targets=set(),
                )
                # Override the source reader to read from the REAL project dir
                from src.source_reader import SourceReader
                real_reader = SourceReader(scope=scope, project_dir=self.project_dir)
                orchestrator._sandboxed_reader = real_reader  # type: ignore[attr-defined]

                results = orchestrator.sync_all()
                if isinstance(results, dict) and "_error" in results:
                    report.errors.append(f"{target_name}: {results['_error']}")
            except Exception as e:
                report.errors.append(f"{target_name}: {e}")

            # Collect all files written into the sandbox for this target
            for generated in target_sandbox.rglob("*"):
                if not generated.is_file():
                    continue
                rel = generated.relative_to(target_sandbox)
                size = generated.stat().st_size
                real_path = self.project_dir / rel
                is_new = not real_path.exists()
                report.files.append(SandboxFileEntry(
                    relative_path=str(rel),
                    target=target_name,
                    size_bytes=size,
                    is_new=is_new,
                ))

        return report

    def cleanup(self) -> None:
        """Delete the sandbox directory."""
        if self.keep_sandbox:
            return
        if self._sandbox_dir and self._sandbox_dir.exists():
            try:
                shutil.rmtree(self._sandbox_dir)
            except OSError as e:
                self.logger.warn(f"Could not delete sandbox {self._sandbox_dir}: {e}")
            self._sandbox_dir = None

    def __enter__(self) -> "SyncSandbox":
        return self

    def __exit__(self, *_) -> None:
        self.cleanup()
