from __future__ import annotations

"""A/B Config Testing across harnesses (item 29).

Lets users define two rule variants and assign them to different harnesses for
a trial period. After the experiment, /sync-ab compare surfaces which variant
felt better based on user annotations and usage signals.

Architecture:
- Variants are stored in ~/.harnesssync/ab-experiments/<name>.json
- Each experiment maps variant IDs ("A" or "B") to a set of target harnesses
- CLAUDE.md rules are partitioned by ``<!-- @ab:A: ... -->`` inline markers
- /sync-ab run applies variant A rules to harness set A, variant B to set B
- /sync-ab compare reads user annotations to surface a preference signal

Variant block syntax in CLAUDE.md:

    <!-- @ab:experiment=myexp:A -->
    - Always use strict TypeScript (variant A)
    <!-- @ab:end -->

    <!-- @ab:experiment=myexp:B -->
    - Use TypeScript with loose checks where needed (variant B)
    <!-- @ab:end -->

Targets mapped to each variant:

    /sync-ab setup --name myexp --a codex,gemini --b cursor,aider

After a week:

    /sync-ab compare --name myexp

Outputs which variant targets had more annotations or rule references.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Default experiments directory
_DEFAULT_EXPERIMENTS_DIR = Path.home() / ".harnesssync" / "ab-experiments"

# CLAUDE.md block markers: <!-- @ab:experiment=NAME:VARIANT --> ... <!-- @ab:end -->
_AB_OPEN_RE = re.compile(
    r"<!--\s*@ab:experiment=([A-Za-z0-9_-]+):([AB])\s*-->",
    re.IGNORECASE,
)
_AB_END_RE = re.compile(r"<!--\s*@ab:end\s*-->", re.IGNORECASE)


@dataclass
class ABExperiment:
    """Configuration for a single A/B experiment."""

    name: str
    variant_a_targets: list[str]   # Harnesses that receive variant A rules
    variant_b_targets: list[str]   # Harnesses that receive variant B rules
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = ""
    # Collected preference signals (added by /sync-ab annotate)
    annotations: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "variant_a_targets": self.variant_a_targets,
            "variant_b_targets": self.variant_b_targets,
            "created_at": self.created_at,
            "notes": self.notes,
            "annotations": self.annotations,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ABExperiment:
        return cls(
            name=data["name"],
            variant_a_targets=data.get("variant_a_targets", []),
            variant_b_targets=data.get("variant_b_targets", []),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            notes=data.get("notes", ""),
            annotations=data.get("annotations", []),
        )


@dataclass
class ABVariantResult:
    """Extracted rules content for one variant of an experiment."""

    experiment_name: str
    variant: str          # "A" or "B"
    rules_content: str    # Extracted rules text for this variant
    targets: list[str]    # Harnesses assigned to this variant


class ABConfigTester:
    """Manages A/B config experiments across harnesses.

    Args:
        experiments_dir: Directory to store experiment JSON files.
                         Defaults to ~/.harnesssync/ab-experiments/
    """

    def __init__(self, experiments_dir: Path | None = None) -> None:
        self.experiments_dir = experiments_dir or _DEFAULT_EXPERIMENTS_DIR

    # ── Experiment lifecycle ───────────────────────────────────────────────

    def create(
        self,
        name: str,
        variant_a_targets: list[str],
        variant_b_targets: list[str],
        notes: str = "",
    ) -> ABExperiment:
        """Create and persist a new A/B experiment.

        Args:
            name: Unique experiment identifier (used in CLAUDE.md markers).
            variant_a_targets: Harness names that will receive variant A rules.
            variant_b_targets: Harness names that will receive variant B rules.
            notes: Optional human-readable description.

        Returns:
            The created ABExperiment.

        Raises:
            ValueError: If an experiment with this name already exists.
        """
        if self._experiment_path(name).exists():
            raise ValueError(
                f"Experiment '{name}' already exists. "
                f"Use delete() before re-creating, or choose a different name."
            )

        exp = ABExperiment(
            name=name,
            variant_a_targets=variant_a_targets,
            variant_b_targets=variant_b_targets,
            notes=notes,
        )
        self._save(exp)
        return exp

    def load(self, name: str) -> ABExperiment | None:
        """Load an experiment by name.

        Returns:
            ABExperiment, or None if not found.
        """
        path = self._experiment_path(name)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ABExperiment.from_dict(data)
        except (json.JSONDecodeError, KeyError):
            return None

    def list_experiments(self) -> list[ABExperiment]:
        """Return all experiments, sorted by creation date (newest first)."""
        if not self.experiments_dir.exists():
            return []
        experiments = []
        for path in self.experiments_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                experiments.append(ABExperiment.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                continue
        return sorted(experiments, key=lambda e: e.created_at, reverse=True)

    def delete(self, name: str) -> bool:
        """Delete an experiment.

        Returns:
            True if deleted, False if not found.
        """
        path = self._experiment_path(name)
        if not path.exists():
            return False
        path.unlink()
        return True

    def add_annotation(
        self,
        name: str,
        preferred_variant: str,
        reason: str = "",
    ) -> bool:
        """Record a preference annotation for an experiment.

        Args:
            name: Experiment name.
            preferred_variant: "A" or "B" — which variant felt better.
            reason: Optional free-text note.

        Returns:
            True if annotation was saved, False if experiment not found.
        """
        exp = self.load(name)
        if exp is None:
            return False
        exp.annotations.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "preferred": preferred_variant.upper(),
            "reason": reason,
        })
        self._save(exp)
        return True

    # ── Rule extraction from CLAUDE.md ────────────────────────────────────

    def extract_variant_rules(self, content: str, name: str) -> dict[str, str]:
        """Extract A and B variant rule blocks for a named experiment.

        Scans ``content`` (CLAUDE.md text) for ``<!-- @ab:experiment=NAME:A -->``
        ... ``<!-- @ab:end -->`` blocks and returns the content inside each.

        Args:
            content: Full CLAUDE.md text.
            name: Experiment name to look for.

        Returns:
            Dict with keys "A" and "B", each containing the extracted rules
            text (empty string if no block found for that variant).
        """
        variants: dict[str, list[str]] = {"A": [], "B": []}
        current_variant: str | None = None
        buffer: list[str] = []

        for line in content.splitlines(keepends=True):
            open_match = _AB_OPEN_RE.search(line)
            end_match = _AB_END_RE.search(line)

            if open_match:
                exp_name, variant = open_match.group(1), open_match.group(2).upper()
                if exp_name.lower() == name.lower() and variant in variants:
                    # Flush any pending buffer first
                    if current_variant and buffer:
                        variants[current_variant].extend(buffer)
                    current_variant = variant
                    buffer = []
                # Skip the marker line itself
            elif end_match and current_variant is not None:
                variants[current_variant].extend(buffer)
                current_variant = None
                buffer = []
            elif current_variant is not None:
                buffer.append(line)

        # Flush any unclosed block
        if current_variant and buffer:
            variants[current_variant].extend(buffer)

        return {v: "".join(lines).strip() for v, lines in variants.items()}

    def apply_variant_to_content(
        self,
        content: str,
        name: str,
        target: str,
        experiment: ABExperiment,
    ) -> str:
        """Return content with only the correct variant block for this target.

        Replaces A/B variant blocks with just the content for the variant
        assigned to ``target``. Targets not in any variant group see neither
        block (they get the surrounding content without the A/B sections).

        Args:
            content: Full CLAUDE.md text.
            name: Experiment name.
            target: Target harness name.
            experiment: Loaded ABExperiment.

        Returns:
            Modified content string.
        """
        target_lower = target.lower()
        if target_lower in [t.lower() for t in experiment.variant_a_targets]:
            keep_variant = "A"
        elif target_lower in [t.lower() for t in experiment.variant_b_targets]:
            keep_variant = "B"
        else:
            # Target is not in this experiment — strip all variant blocks
            keep_variant = None

        lines_out: list[str] = []
        current_variant: str | None = None
        in_kept_block = False

        for line in content.splitlines(keepends=True):
            open_match = _AB_OPEN_RE.search(line)
            end_match = _AB_END_RE.search(line)

            if open_match:
                exp_name, variant = open_match.group(1), open_match.group(2).upper()
                if exp_name.lower() == name.lower():
                    current_variant = variant
                    in_kept_block = (variant == keep_variant)
                else:
                    # Different experiment — pass through unchanged
                    lines_out.append(line)
            elif end_match and current_variant is not None:
                current_variant = None
                in_kept_block = False
            elif current_variant is not None:
                if in_kept_block:
                    lines_out.append(line)
            else:
                lines_out.append(line)

        return "".join(lines_out)

    # ── Analysis ──────────────────────────────────────────────────────────

    def compare(self, name: str) -> dict[str, Any]:
        """Produce a comparison summary for an experiment.

        Returns a dict with:
            experiment: ABExperiment
            annotation_counts: {"A": int, "B": int}
            preferred_variant: "A" | "B" | "tie" | "insufficient_data"
            confidence: "high" | "low" | "none"
            summary: Human-readable summary string
        """
        exp = self.load(name)
        if exp is None:
            return {"error": f"Experiment '{name}' not found"}

        a_count = sum(1 for a in exp.annotations if a.get("preferred") == "A")
        b_count = sum(1 for a in exp.annotations if a.get("preferred") == "B")
        total = a_count + b_count

        if total == 0:
            preferred = "insufficient_data"
            confidence = "none"
        elif a_count == b_count:
            preferred = "tie"
            confidence = "low"
        else:
            preferred = "A" if a_count > b_count else "B"
            ratio = max(a_count, b_count) / total
            confidence = "high" if ratio >= 0.7 else "low"

        lines = [
            f"A/B Experiment: {name}",
            "=" * 50,
            "",
            f"  Variant A targets: {', '.join(exp.variant_a_targets) or '(none)'}",
            f"  Variant B targets: {', '.join(exp.variant_b_targets) or '(none)'}",
            f"  Created: {exp.created_at[:10]}",
            "",
            f"  Preference annotations: A={a_count}  B={b_count}  Total={total}",
        ]

        if preferred == "insufficient_data":
            lines.append("\n  ⚠ No annotations yet. Use /sync-ab annotate to record preferences.")
        elif preferred == "tie":
            lines.append("\n  Result: TIE — equal preference for both variants.")
        else:
            pct = int(max(a_count, b_count) / total * 100)
            lines.append(f"\n  Result: Variant {preferred} preferred ({pct}% of annotations, confidence={confidence})")

        if exp.annotations:
            lines.append("\n  Recent annotations:")
            for ann in exp.annotations[-3:]:
                ts = ann.get("ts", "")[:10]
                reason = f" — {ann['reason']}" if ann.get("reason") else ""
                lines.append(f"    [{ts}] Preferred {ann['preferred']}{reason}")

        return {
            "experiment": exp,
            "annotation_counts": {"A": a_count, "B": b_count},
            "preferred_variant": preferred,
            "confidence": confidence,
            "summary": "\n".join(lines),
        }

    def format_list(self) -> str:
        """Format list of all experiments for display."""
        experiments = self.list_experiments()
        if not experiments:
            return "No A/B experiments found. Create one with /sync-ab setup."

        lines = [f"A/B Config Experiments ({len(experiments)} total)", "=" * 50, ""]
        for exp in experiments:
            a_tgts = ", ".join(exp.variant_a_targets) or "(none)"
            b_tgts = ", ".join(exp.variant_b_targets) or "(none)"
            ann_count = len(exp.annotations)
            lines.append(f"  {exp.name}")
            lines.append(f"    Variant A → {a_tgts}")
            lines.append(f"    Variant B → {b_tgts}")
            lines.append(f"    Annotations: {ann_count}  Created: {exp.created_at[:10]}")
            if exp.notes:
                lines.append(f"    Notes: {exp.notes}")
            lines.append("")
        return "\n".join(lines)

    # ── Private helpers ───────────────────────────────────────────────────

    def _experiment_path(self, name: str) -> Path:
        return self.experiments_dir / f"{name}.json"

    def _save(self, exp: ABExperiment) -> None:
        self.experiments_dir.mkdir(parents=True, exist_ok=True)
        path = self._experiment_path(exp.name)
        path.write_text(json.dumps(exp.to_dict(), indent=2), encoding="utf-8")
