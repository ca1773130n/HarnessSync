from __future__ import annotations

"""Sync anomaly detection — surface unexpectedly large or suspicious changes.

Alerts when a sync produces a disproportionately large diff against one or more
target config files. This acts as a safety net before a corrupted or accidentally
truncated CLAUDE.md propagates to all harnesses.

Detection strategy:
  1. **Size ratio**: If > RATIO_THRESHOLD of a target file's content would be
     replaced, flag it as anomalous. Defaults to 0.50 (50% replacement).
  2. **Absolute deletion**: If a target file exists and the incoming content is
     empty (or near-empty), flag it.
  3. **Source shrinkage**: If source content is substantially shorter than the
     last recorded source length, flag it before any writes happen.

Usage:
    detector = SyncAnomalyDetector()
    anomalies = detector.check(source_content, target_files)
    if anomalies:
        print(detector.format_report(anomalies))
        # caller decides whether to abort or warn
"""

from dataclasses import dataclass, field
from pathlib import Path


# Fraction of existing content that would be replaced to trigger an anomaly
RATIO_THRESHOLD: float = 0.50

# Minimum existing file size (bytes) before ratio check applies.
# Small files are noisy — skip ratio checks for files < MIN_FILE_SIZE bytes.
MIN_FILE_SIZE: int = 200

# Minimum source content length (chars) before empty-source check applies.
MIN_SOURCE_CHARS: int = 20


@dataclass
class SyncAnomaly:
    """A single detected anomaly."""

    kind: str           # "size_ratio" | "empty_source" | "source_shrinkage"
    target_name: str    # e.g. "codex", "gemini"
    file_path: str      # Absolute path to the target file
    detail: str         # Human-readable description
    severity: str = "warning"  # "warning" | "critical"

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "target_name": self.target_name,
            "file_path": self.file_path,
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass
class SyncAnomalyDetector:
    """Detect anomalous sync changes before they are written to disk.

    Args:
        ratio_threshold: Fraction of existing content replaced before flagging.
                         Default: 0.50 (50%).
        min_file_size:   Minimum existing file size (bytes) for ratio checks.
        state_dir:       Directory where historical source sizes are stored.
                         Default: ~/.harnesssync/anomaly_state/.
    """

    ratio_threshold: float = RATIO_THRESHOLD
    min_file_size: int = MIN_FILE_SIZE
    state_dir: Path = field(default_factory=lambda: Path.home() / ".harnesssync" / "anomaly_state")

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def check(
        self,
        source_content: str,
        target_files: dict[str, str],
    ) -> list[SyncAnomaly]:
        """Check for anomalies before a sync write.

        Args:
            source_content: The full source content that will be written
                            (e.g. filtered CLAUDE.md content for this target).
            target_files:   Dict mapping file_path -> existing file content
                            for every file the sync intends to write.

        Returns:
            List of SyncAnomaly objects. Empty list means no anomalies.
        """
        anomalies: list[SyncAnomaly] = []

        # 1. Empty or near-empty source content
        if len(source_content.strip()) < MIN_SOURCE_CHARS and target_files:
            for file_path in target_files:
                existing = target_files[file_path]
                if len(existing.strip()) > MIN_FILE_SIZE:
                    anomalies.append(SyncAnomaly(
                        kind="empty_source",
                        target_name=_target_from_path(file_path),
                        file_path=file_path,
                        detail=(
                            f"Source content is nearly empty ({len(source_content.strip())} chars) "
                            f"but existing target file has {len(existing)} chars. "
                            "This may indicate a corrupted or truncated CLAUDE.md."
                        ),
                        severity="critical",
                    ))

        # 2. Per-file size ratio check
        for file_path, existing_content in target_files.items():
            existing_bytes = len(existing_content.encode("utf-8"))
            if existing_bytes < self.min_file_size:
                continue  # Skip small files — too noisy

            new_bytes = len(source_content.encode("utf-8"))

            # How much of the existing content would survive?
            # Simple heuristic: compute character-level similarity
            surviving_ratio = _content_similarity(existing_content, source_content)
            replaced_ratio = 1.0 - surviving_ratio

            if replaced_ratio > self.ratio_threshold:
                severity = "critical" if replaced_ratio > 0.80 else "warning"
                anomalies.append(SyncAnomaly(
                    kind="size_ratio",
                    target_name=_target_from_path(file_path),
                    file_path=file_path,
                    detail=(
                        f"{replaced_ratio:.0%} of {file_path} would be replaced "
                        f"(existing: {existing_bytes} bytes → incoming: {new_bytes} bytes). "
                        f"Run with --dry-run to inspect changes before writing."
                    ),
                    severity=severity,
                ))

        return anomalies

    def check_source_shrinkage(
        self,
        source_content: str,
        previous_length: int | None,
    ) -> SyncAnomaly | None:
        """Check if source content shrank dramatically compared to last sync.

        Args:
            source_content: Current source content being synced.
            previous_length: Character length of source content at last sync.
                             None means no historical data — skip check.

        Returns:
            SyncAnomaly if shrinkage is anomalous, otherwise None.
        """
        if previous_length is None or previous_length == 0:
            return None

        current_length = len(source_content)
        if current_length >= previous_length:
            return None

        shrink_ratio = 1.0 - (current_length / previous_length)
        if shrink_ratio > self.ratio_threshold:
            severity = "critical" if shrink_ratio > 0.80 else "warning"
            return SyncAnomaly(
                kind="source_shrinkage",
                target_name="source",
                file_path="CLAUDE.md",
                detail=(
                    f"Source content shrank by {shrink_ratio:.0%} "
                    f"({previous_length} chars → {current_length} chars). "
                    "Check that CLAUDE.md was not accidentally truncated."
                ),
                severity=severity,
            )
        return None

    def record_source_length(self, source_content: str, key: str = "default") -> None:
        """Persist source content length for future shrinkage checks.

        Args:
            source_content: Source content after a successful sync.
            key: Identifier for this source (e.g. "user", "project").
        """
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            state_file = self.state_dir / f"{key}.length"
            state_file.write_text(str(len(source_content)), encoding="utf-8")
        except OSError:
            pass  # State recording is best-effort

    def load_previous_length(self, key: str = "default") -> int | None:
        """Load previously recorded source length.

        Args:
            key: Identifier matching what was passed to record_source_length().

        Returns:
            Integer length, or None if no state file exists.
        """
        state_file = self.state_dir / f"{key}.length"
        try:
            return int(state_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return None

    def format_report(self, anomalies: list[SyncAnomaly]) -> str:
        """Format anomalies as a human-readable warning block.

        Args:
            anomalies: List from check() or including check_source_shrinkage().

        Returns:
            Formatted string, empty if anomalies is empty.
        """
        if not anomalies:
            return ""

        criticals = [a for a in anomalies if a.severity == "critical"]
        warnings = [a for a in anomalies if a.severity == "warning"]

        lines: list[str] = []
        lines.append("")
        lines.append("=" * 60)
        lines.append("⚠  SYNC ANOMALY DETECTED")
        lines.append("=" * 60)
        lines.append(
            f"  {len(criticals)} critical, {len(warnings)} warning(s) — "
            "this sync may produce unexpected large changes."
        )
        lines.append("")

        for a in anomalies:
            icon = "✗" if a.severity == "critical" else "⚠"
            lines.append(f"  {icon} [{a.kind}] {a.file_path}")
            lines.append(f"    {a.detail}")
            lines.append("")

        lines.append("  To inspect: run /sync --dry-run")
        lines.append("  To override: run /sync --allow-anomalies")
        lines.append("=" * 60)
        return "\n".join(lines)


# ------------------------------------------------------------------ #
# Helpers                                                              #
# ------------------------------------------------------------------ #

def _target_from_path(file_path: str) -> str:
    """Infer target name from file path heuristically."""
    p = file_path.lower()
    for name in ("codex", "gemini", "opencode", "cursor", "aider", "windsurf",
                 "cline", "continue", "zed", "neovim"):
        if name in p:
            return name
    return "unknown"


def _content_similarity(a: str, b: str) -> float:
    """Approximate fraction of content from ``a`` that survives in ``b``.

    Uses a line-overlap heuristic: count how many lines in ``a`` also appear
    in ``b``. Fast and good enough for anomaly detection purposes.

    Returns:
        Float in [0.0, 1.0]. 1.0 = identical, 0.0 = no shared lines.
    """
    a_lines = set(line.strip() for line in a.splitlines() if line.strip())
    b_lines = set(line.strip() for line in b.splitlines() if line.strip())
    if not a_lines:
        return 1.0 if not b_lines else 0.0
    shared = a_lines & b_lines
    return len(shared) / len(a_lines)
