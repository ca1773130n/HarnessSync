from __future__ import annotations

"""Cross-harness rule deduplication analyzer.

Detects when the same rule or instruction exists in CLAUDE.md, AGENTS.md,
GEMINI.md, and other harness config files written in slightly different ways.
Offers to canonicalize them under Claude Code as the single source of truth.

Detection approach:
1. Collect rule content from all harness config files in the project
2. Split each into "rule blocks" (paragraphs or list items)
3. Normalize blocks (lowercase, strip punctuation, collapse whitespace)
4. Compute similarity scores using SequenceMatcher (fuzzy text similarity)
5. Group near-duplicates (similarity >= threshold) into clusters
6. Report clusters with the canonical (longest/most complete) form

The deduplication never modifies files automatically — it outputs a report
and, for each cluster, suggests which version to canonicalize in CLAUDE.md.
"""

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


# Harness config files to scan (relative to project root)
_HARNESS_FILES: dict[str, str] = {
    "claude":    "CLAUDE.md",
    "codex":     "AGENTS.md",
    "gemini":    "GEMINI.md",
    "opencode":  "AGENTS.md",  # opencode also uses AGENTS.md
    "windsurf":  ".windsurfrules",
    "aider":     "CONVENTIONS.md",
}

# Similarity threshold: 0.0 = anything matches, 1.0 = exact only
DEFAULT_SIMILARITY_THRESHOLD = 0.75

# Minimum block length (chars) to consider — skip tiny fragments
MIN_BLOCK_LEN = 30


@dataclass
class RuleBlock:
    """A single rule block extracted from a harness config file."""

    source: str        # Harness name ("claude", "codex", etc.)
    file_path: str     # Relative path of the source file
    text: str          # Original text of the block
    normalized: str    # Normalized text for comparison


@dataclass
class DuplicateCluster:
    """A group of near-duplicate rule blocks across harnesses."""

    blocks: list[RuleBlock] = field(default_factory=list)
    canonical: RuleBlock | None = None    # Suggested canonical version
    min_similarity: float = 1.0

    @property
    def sources(self) -> list[str]:
        return sorted({b.source for b in self.blocks})

    @property
    def is_cross_harness(self) -> bool:
        """True if the cluster spans more than one harness."""
        return len(self.sources) > 1


class RuleDeduplicator:
    """Detects duplicate rules across harness config files.

    Args:
        project_dir: Project root directory.
        similarity_threshold: Minimum similarity score to flag as duplicate.
    """

    def __init__(
        self,
        project_dir: Path | None = None,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ):
        self.project_dir = project_dir or Path.cwd()
        self.threshold = similarity_threshold

    def scan(self) -> list[DuplicateCluster]:
        """Scan harness config files for near-duplicate rule blocks.

        Returns:
            List of DuplicateCluster, each containing 2+ near-duplicate
            blocks from different (or same) harness files. Cross-harness
            clusters appear first.
        """
        blocks = self._collect_blocks()
        clusters = self._cluster_blocks(blocks)
        # Put cross-harness duplicates first
        clusters.sort(key=lambda c: (not c.is_cross_harness, -len(c.blocks)))
        return clusters

    def format_report(self, clusters: list[DuplicateCluster]) -> str:
        """Format duplicate clusters as a human-readable report.

        Args:
            clusters: Output of ``scan()``.

        Returns:
            Multi-line formatted string.
        """
        cross_harness = [c for c in clusters if c.is_cross_harness]
        same_file = [c for c in clusters if not c.is_cross_harness]

        if not clusters:
            return (
                "No duplicate rules detected across harness config files. "
                "Your configs appear well-deduplicated."
            )

        lines = [
            "Cross-Harness Rule Deduplication Report",
            "=" * 50,
            f"Found {len(clusters)} duplicate cluster(s): "
            f"{len(cross_harness)} cross-harness, {len(same_file)} within-file.",
            "",
        ]

        if cross_harness:
            lines.append("CROSS-HARNESS DUPLICATES (canonicalize in CLAUDE.md):")
            lines.append("")
            for i, cluster in enumerate(cross_harness, 1):
                lines.extend(self._format_cluster(i, cluster))

        if same_file:
            lines.append("WITHIN-FILE DUPLICATES:")
            lines.append("")
            for i, cluster in enumerate(same_file, 1):
                lines.extend(self._format_cluster(len(cross_harness) + i, cluster))

        lines.append("")
        if cross_harness:
            lines.append("Recommendation:")
            lines.append(
                "  Move canonical versions of cross-harness rules to CLAUDE.md "
                "and let HarnessSync distribute them. Remove the duplicates from "
                "AGENTS.md, GEMINI.md, etc. to prevent drift."
            )

        return "\n".join(lines)

    def suggest_canonical_content(self, cluster: DuplicateCluster) -> str:
        """Return the suggested canonical text for a cluster.

        Picks the longest non-empty block as the canonical version,
        on the assumption that the most complete phrasing wins.

        Args:
            cluster: A DuplicateCluster from ``scan()``.

        Returns:
            Canonical text string.
        """
        if cluster.canonical:
            return cluster.canonical.text
        if not cluster.blocks:
            return ""
        return max(cluster.blocks, key=lambda b: len(b.text)).text

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_blocks(self) -> list[RuleBlock]:
        """Read all harness config files and split into rule blocks."""
        blocks: list[RuleBlock] = []
        seen_files: set[str] = set()  # Avoid reading same file twice

        for source, rel_path in _HARNESS_FILES.items():
            path = self.project_dir / rel_path
            if not path.exists() or str(path) in seen_files:
                continue
            seen_files.add(str(path))

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            # Strip HarnessSync managed markers before splitting
            text = _strip_managed_markers(text)

            for block_text in _split_blocks(text):
                if len(block_text.strip()) < MIN_BLOCK_LEN:
                    continue
                normalized = _normalize(block_text)
                if not normalized:
                    continue
                blocks.append(RuleBlock(
                    source=source,
                    file_path=rel_path,
                    text=block_text.strip(),
                    normalized=normalized,
                ))

        return blocks

    def _cluster_blocks(self, blocks: list[RuleBlock]) -> list[DuplicateCluster]:
        """Group near-duplicate blocks into clusters via pairwise similarity."""
        n = len(blocks)
        # Union-find for grouping
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            parent[find(x)] = find(y)

        # Compute pairwise similarity (O(n²) — acceptable for typical config sizes)
        for i in range(n):
            for j in range(i + 1, n):
                sim = _similarity(blocks[i].normalized, blocks[j].normalized)
                if sim >= self.threshold:
                    union(i, j)

        # Collect clusters from union-find groups
        from collections import defaultdict
        groups: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            groups[find(i)].append(i)

        clusters: list[DuplicateCluster] = []
        for group_indices in groups.values():
            if len(group_indices) < 2:
                continue  # Not a duplicate

            group_blocks = [blocks[i] for i in group_indices]
            canonical = max(group_blocks, key=lambda b: len(b.text))

            # Compute minimum pairwise similarity for the cluster
            sims = []
            for i, b1 in enumerate(group_blocks):
                for b2 in group_blocks[i + 1:]:
                    sims.append(_similarity(b1.normalized, b2.normalized))
            min_sim = min(sims) if sims else 1.0

            clusters.append(DuplicateCluster(
                blocks=group_blocks,
                canonical=canonical,
                min_similarity=min_sim,
            ))

        return clusters

    def _format_cluster(self, idx: int, cluster: DuplicateCluster) -> list[str]:
        """Format a single cluster for the report."""
        lines = [
            f"  [{idx}] Found in: {', '.join(cluster.sources)}  "
            f"(similarity: {cluster.min_similarity:.0%})",
        ]
        for block in cluster.blocks:
            preview = block.text[:120].replace("\n", " ")
            indicator = " ← canonical" if block is cluster.canonical else ""
            lines.append(f"       [{block.source}:{block.file_path}] {preview!r}{indicator}")
        lines.append("")
        return lines


# ------------------------------------------------------------------
# Module-level utilities
# ------------------------------------------------------------------

_MANAGED_MARKER_RE = re.compile(
    r"<!--\s*Managed by HarnessSync\s*-->.*?<!--\s*End HarnessSync managed content\s*-->",
    re.DOTALL | re.IGNORECASE,
)

_HEADING_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)


def _strip_managed_markers(text: str) -> str:
    """Remove HarnessSync-managed blocks from text before analysis."""
    return _MANAGED_MARKER_RE.sub("", text)


def _split_blocks(text: str) -> list[str]:
    """Split text into rule blocks (paragraphs or list items).

    Splits on double newlines (paragraph boundaries) or heading lines.
    List items beginning with '-' or '*' or numbers are kept as individual blocks.
    """
    # Split on blank lines first
    paragraphs = re.split(r"\n{2,}", text)
    blocks: list[str] = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # If the paragraph is a list, split into individual items
        if re.match(r"^\s*[-*•]\s", para) or re.match(r"^\s*\d+\.\s", para):
            items = re.split(r"\n(?=\s*[-*•\d])", para)
            blocks.extend(item.strip() for item in items if item.strip())
        else:
            blocks.append(para)

    return blocks


def _normalize(text: str) -> str:
    """Normalize text for similarity comparison.

    - Lowercase
    - Collapse whitespace
    - Remove punctuation except apostrophes and hyphens
    - Strip markdown syntax (**, __, `, #)
    """
    text = text.lower()
    # Strip markdown syntax
    text = re.sub(r"[*_`#>]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text)
    # Remove punctuation except - '
    text = re.sub(r"[^\w\s\-']", "", text)
    return text.strip()


def _similarity(a: str, b: str) -> float:
    """Return SequenceMatcher similarity ratio between two strings."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()
