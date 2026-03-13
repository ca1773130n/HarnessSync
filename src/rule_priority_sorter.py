from __future__ import annotations

"""Rules Priority Sorter — interactive rule ordering with per-harness preview.

Different harnesses interpret rule order differently. Some (like Cursor .mdc
files with ``alwaysApply``) evaluate rules top-down with earlier rules taking
precedence. Others treat rules as an unordered set. This module provides an
interactive CLI tool for reordering rules with a preview of how each harness
would rank them.

Usage::

    sorter = RulePrioritySorter(project_dir)
    sorter.sort_interactive()           # interactive reorder then apply
    sorter.preview_order("cursor")      # show effective order for one target

CLI usage (via /sync command)::

    /sync --sort-rules                  # launch interactive sorter
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from src.utils.constants import CORE_TARGETS


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class RuleBlock:
    """A discrete rule block extracted from CLAUDE.md."""

    heading: str         # Section heading (e.g. "## Testing")
    body: str            # Section body text
    index: int           # Original 0-based position in file
    word_count: int = 0  # Length proxy for estimating importance

    def __post_init__(self) -> None:
        self.word_count = len(self.body.split())

    @property
    def preview(self) -> str:
        """First 80 chars of body for display."""
        first_line = self.body.strip().split("\n")[0]
        return first_line[:80] + ("…" if len(first_line) > 80 else "")

    def render(self) -> str:
        """Reconstruct the rule block as Markdown text."""
        sep = "\n" if self.body.startswith("\n") else "\n\n"
        return f"{self.heading}{sep}{self.body.strip()}\n"


# How each harness interprets rule ordering
# "top_wins"  — first rule wins on conflict (cursor .mdc, codex AGENTS.md)
# "last_wins" — later rules override earlier ones (aider conventions)
# "unordered" — rules treated as an unordered set (gemini, opencode, windsurf)
HARNESS_ORDER_SEMANTICS: dict[str, str] = {
    "cursor":   "top_wins",
    "codex":    "top_wins",
    "aider":    "last_wins",
    "gemini":   "unordered",
    "opencode": "unordered",
    "windsurf": "unordered",
}

# All known targets (derived from HARNESS_ORDER_SEMANTICS, subset of CORE_TARGETS)
_ALL_TARGETS = list(HARNESS_ORDER_SEMANTICS.keys())


# ---------------------------------------------------------------------------
# Rule extraction
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^(#{1,3}[^\n]+)$", re.MULTILINE)


def extract_rule_blocks(content: str) -> list[RuleBlock]:
    """Split CLAUDE.md content into ordered rule blocks.

    Args:
        content: Raw CLAUDE.md text.

    Returns:
        List of RuleBlock objects in document order.
    """
    matches = list(_SECTION_RE.finditer(content))
    if not matches:
        # No headings — treat entire content as a single unnamed block
        return [RuleBlock(heading="(top-level)", body=content, index=0)]

    blocks: list[RuleBlock] = []

    # Content before first heading
    preamble = content[: matches[0].start()].strip()
    if preamble:
        blocks.append(RuleBlock(heading="(preamble)", body=preamble, index=0))

    for i, m in enumerate(matches):
        heading = m.group(1).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[body_start:body_end]
        blocks.append(RuleBlock(heading=heading, body=body, index=len(blocks)))

    return blocks


def rebuild_content(blocks: list[RuleBlock]) -> str:
    """Reconstruct CLAUDE.md text from an ordered list of rule blocks.

    Args:
        blocks: Rule blocks in the desired output order.

    Returns:
        Reassembled Markdown string.
    """
    parts = []
    for block in blocks:
        if block.heading in ("(preamble)", "(top-level)"):
            parts.append(block.body.strip())
        else:
            parts.append(block.render())
    return "\n\n".join(p for p in parts if p) + "\n"


# ---------------------------------------------------------------------------
# Dependency detection
# ---------------------------------------------------------------------------

# Phrase patterns that suggest rule B depends on rule A being applied first.
# Matches phrases like "after X is applied", "requires X", "depends on X",
# "building on X", "assuming X", "given that X", "once X is set".
_DEP_EXPLICIT_RE = re.compile(
    r"\b(?:after|requires?|depends? on|building on|assuming|given that|once)\b"
    r"\s+['\"]?([A-Za-z][A-Za-z0-9 _\-]{2,40})['\"]?",
    re.IGNORECASE,
)

# Reference patterns: rule body mentions another section heading by name
# e.g. "see the Language Detection section", "as defined in Formatting"
_DEP_REFERENCE_RE = re.compile(
    r"\b(?:see|as defined in|per|according to|from|in)\b"
    r"\s+(?:the\s+)?['\"]?([A-Za-z][A-Za-z0-9 _\-]{2,40})['\"]?\s+(?:section|rule|block)?",
    re.IGNORECASE,
)


def detect_rule_dependencies(blocks: list[RuleBlock]) -> dict[str, list[str]]:
    """Detect dependency edges between rule blocks.

    Scans each block's body for phrases that imply it depends on another block
    being applied first. Returns a dependency map where each key is a block
    heading and each value is the list of headings it should come AFTER.

    Dependency signals detected:
    - Explicit: "requires X", "depends on X", "after X is applied"
    - Cross-reference: "see the X section", "as defined in X", "per X"

    Args:
        blocks: Rule blocks extracted from CLAUDE.md.

    Returns:
        Dict mapping dependent_heading -> [prerequisite_heading, ...].
        Only headings that match another block are included.
    """
    heading_set = {b.heading.lstrip("#").strip().lower(): b.heading for b in blocks}

    dependencies: dict[str, list[str]] = {}

    for block in blocks:
        deps: list[str] = []
        text = block.body

        for pattern in (_DEP_EXPLICIT_RE, _DEP_REFERENCE_RE):
            for match in pattern.finditer(text):
                candidate = match.group(1).strip().lower()
                # Check if candidate fuzzy-matches any known heading
                resolved = _fuzzy_match_heading(candidate, heading_set)
                if resolved and resolved != block.heading:
                    if resolved not in deps:
                        deps.append(resolved)

        if deps:
            dependencies[block.heading] = deps

    return dependencies


def _fuzzy_match_heading(candidate: str, heading_set: dict[str, str]) -> str | None:
    """Return the canonical heading if candidate is a substring of a known heading.

    Args:
        candidate: Lowercased candidate string extracted from rule text.
        heading_set: Map of lowercased-heading -> canonical-heading.

    Returns:
        Canonical heading string if matched, else None.
    """
    # Exact match first
    if candidate in heading_set:
        return heading_set[candidate]

    # Substring match (candidate appears in a heading or vice-versa)
    for lower_heading, canonical in heading_set.items():
        clean_heading = lower_heading.lstrip("#").strip()
        if candidate in clean_heading or clean_heading in candidate:
            if len(candidate) >= 4:  # Avoid spurious matches on short words
                return canonical

    return None


def validate_rule_order(blocks: list[RuleBlock]) -> list[tuple[str, str, str]]:
    """Validate that blocks are ordered consistently with their dependencies.

    For ``top_wins`` harnesses (Cursor, Codex), a rule that DEPENDS ON another
    rule must appear AFTER it in the document (so the prerequisite is applied
    first). This function checks that the current order respects detected
    dependencies.

    Args:
        blocks: Rule blocks in current document order.

    Returns:
        List of (dependent_heading, prerequisite_heading, violation_description)
        tuples for each ordering violation. Empty list means order is valid.
    """
    deps = detect_rule_dependencies(blocks)
    index_map = {b.heading: b.index for b in blocks}
    violations: list[tuple[str, str, str]] = []

    for dependent, prereqs in deps.items():
        dep_idx = index_map.get(dependent)
        if dep_idx is None:
            continue
        for prereq in prereqs:
            prereq_idx = index_map.get(prereq)
            if prereq_idx is None:
                continue
            if prereq_idx > dep_idx:
                violations.append((
                    dependent,
                    prereq,
                    f"'{dependent}' depends on '{prereq}' but appears before it in document",
                ))

    return violations


def format_dependency_report(blocks: list[RuleBlock]) -> str:
    """Format a human-readable dependency and ordering report.

    Args:
        blocks: Rule blocks in current document order.

    Returns:
        Multi-line string listing detected dependencies and any ordering issues.
    """
    deps = detect_rule_dependencies(blocks)
    violations = validate_rule_order(blocks)

    lines: list[str] = ["Rule Dependency Analysis", "=" * 40, ""]

    if not deps:
        lines.append("  No inter-rule dependencies detected.")
    else:
        lines.append("  Detected dependencies (rule → requires):")
        for dependent, prereqs in sorted(deps.items()):
            for prereq in prereqs:
                lines.append(f"    {dependent!r} → {prereq!r}")
        lines.append("")

    if violations:
        lines.append("  ⚠ Ordering violations (will affect top_wins harnesses):")
        for dep, prereq, msg in violations:
            lines.append(f"    {msg}")
        lines.append("")
        lines.append(
            "  Run /sync --sort-rules to interactively reorder, "
            "or move the prerequisite rule above the dependent rule."
        )
    else:
        lines.append("  ✓ Rule order is consistent with detected dependencies.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Priority preview
# ---------------------------------------------------------------------------

def preview_order_for_target(blocks: list[RuleBlock], target: str) -> list[str]:
    """Return rule headings in the effective priority order for a target.

    For ``top_wins`` harnesses, the first item in the list has highest
    priority. For ``last_wins`` harnesses, the last item has highest priority.
    For ``unordered`` harnesses, returns rules alphabetically (no ordering
    guarantee exists).

    Args:
        blocks: Rule blocks (already in the user-desired sequence).
        target: Harness name (e.g. "cursor").

    Returns:
        Ordered list of heading strings reflecting effective priority.
    """
    semantics = HARNESS_ORDER_SEMANTICS.get(target, "unordered")
    headings = [b.heading for b in blocks if b.heading not in ("(preamble)",)]

    if semantics == "top_wins":
        return headings  # Index 0 = highest priority
    elif semantics == "last_wins":
        return list(reversed(headings))  # Last item = highest priority
    else:  # unordered
        return sorted(headings)


def format_priority_preview(blocks: list[RuleBlock], targets: list[str] | None = None) -> str:
    """Format a multi-column priority preview table for all (or specified) targets.

    Args:
        blocks: Rule blocks in current order.
        targets: Targets to include. Defaults to all known targets.

    Returns:
        Human-readable table string.
    """
    if targets is None:
        targets = _ALL_TARGETS

    lines = ["Rule priority by harness (higher rank = rule evaluated first):"]
    lines.append("")

    # Column widths
    max_heading = max((len(b.heading) for b in blocks if b.heading != "(preamble)"), default=12)
    col_w = max(max_heading, 20)

    # Header row
    header = f"  {'Rule':<{col_w}}"
    for t in targets:
        semantics = HARNESS_ORDER_SEMANTICS.get(t, "unordered")
        marker = {"top_wins": "(↑ top wins)", "last_wins": "(↓ last wins)", "unordered": "(no order)"}.get(semantics, "")
        header += f"  {t:<14} {marker}"
    lines.append(header)
    lines.append("  " + "-" * (col_w + 18 * len(targets)))

    # Build rank maps for each target
    rank_maps: dict[str, dict[str, int]] = {}
    for t in targets:
        ordered = preview_order_for_target(blocks, t)
        rank_maps[t] = {h: i + 1 for i, h in enumerate(ordered)}

    # Rows — one per rule block, in document order
    for block in blocks:
        if block.heading in ("(preamble)",):
            continue
        row = f"  {block.heading:<{col_w}}"
        for t in targets:
            rank = rank_maps[t].get(block.heading)
            if rank is None:
                row += f"  {'—':<14}"
            else:
                semantics = HARNESS_ORDER_SEMANTICS.get(t, "unordered")
                if semantics == "unordered":
                    row += f"  {'(any)':<14}"
                else:
                    row += f"  #{rank:<13}"
        lines.append(row)

    lines.append("")
    lines.append("  Legend: #1 = highest effective priority for that harness")
    return "\n".join(lines)


def format_rule_win_map(
    blocks: list[RuleBlock],
    targets: list[str] | None = None,
) -> str:
    """Format a cross-harness 'win map' showing which rule wins on conflict.

    When two rules address the same concern but with contradictory guidance,
    which one wins depends on harness order semantics. This map makes that
    explicit: for each pair of adjacent rules, show which one takes effect
    in each target harness.

    Args:
        blocks: Rule blocks in current document order.
        targets: Targets to include. Defaults to all known targets.

    Returns:
        Human-readable win-map string showing per-harness effective priority.
    """
    if targets is None:
        targets = _ALL_TARGETS

    content_blocks = [b for b in blocks if b.heading not in ("(preamble)",)]
    if not content_blocks:
        return "No rule blocks found — add ## headings to CLAUDE.md to enable rule ordering."

    lines = [
        "Rule Win Map — which rule takes precedence in each harness",
        "=" * 66,
        "",
        "Harness order semantics:",
    ]
    for t in targets:
        sem = HARNESS_ORDER_SEMANTICS.get(t, "unordered")
        label = {
            "top_wins": "top rule wins (first-match)",
            "last_wins": "last rule wins (override-style)",
            "unordered": "rules applied as a set (no precedence)",
        }.get(sem, sem)
        lines.append(f"  {t:<14} {label}")

    lines.append("")

    # For each adjacent pair of rule blocks, show which wins per harness
    for i in range(len(content_blocks) - 1):
        rule_a = content_blocks[i]
        rule_b = content_blocks[i + 1]
        lines.append(f"  {rule_a.heading!r}  vs  {rule_b.heading!r}")

        for t in targets:
            sem = HARNESS_ORDER_SEMANTICS.get(t, "unordered")
            if sem == "top_wins":
                winner = rule_a.heading
                reason = "(appears first)"
            elif sem == "last_wins":
                winner = rule_b.heading
                reason = "(appears last)"
            else:
                winner = "tie"
                reason = "(unordered)"

            if winner == "tie":
                lines.append(f"    {t:<14} = (both apply equally)")
            else:
                lines.append(f"    {t:<14} → {winner!r} {reason}")
        lines.append("")

    # Highlight any dependency violations
    violations = validate_rule_order(content_blocks)
    if violations:
        lines.append("  Dependency violations detected:")
        for dep, prereq, explanation in violations:
            lines.append(f"    ✗ {dep!r} should appear before {prereq!r}")
            lines.append(f"      {explanation}")
        lines.append("")

    lines.append("  To reorder rules, edit CLAUDE.md directly or use /sync --sort-rules")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interactive sorter
# ---------------------------------------------------------------------------

class RulePrioritySorter:
    """Interactive CLI tool for reordering CLAUDE.md rule sections.

    Presents a numbered list of rule blocks and lets the user move items
    up/down or specify a new order, with a live preview of how each harness
    would interpret the priority.

    Attributes:
        source_file: Path to the CLAUDE.md (or rules source) being sorted.
        blocks: Current ordered list of rule blocks.
    """

    def __init__(self, source_file: Path | None = None, project_dir: Path | None = None,
                 cc_home: Path | None = None) -> None:
        """Initialise the sorter.

        Args:
            source_file: Path to CLAUDE.md to sort. Auto-detected if None.
            project_dir: Project root for auto-detection. Defaults to cwd.
            cc_home: Claude Code config directory (default: ~/.claude).
        """
        self.project_dir = project_dir or Path.cwd()
        self.cc_home = cc_home if cc_home is not None else Path.home() / ".claude"

        if source_file is not None:
            self.source_file = source_file
        else:
            candidates = [
                self.project_dir / "CLAUDE.md",
                self.project_dir / ".claude" / "CLAUDE.md",
                self.cc_home / "CLAUDE.md",
            ]
            self.source_file = next((p for p in candidates if p.exists()), candidates[0])

        self.blocks: list[RuleBlock] = []
        self._original_blocks: list[RuleBlock] = []

    def load(self) -> bool:
        """Load and parse rule blocks from source_file.

        Returns:
            True if file was found and parsed, False otherwise.
        """
        if not self.source_file.exists():
            return False
        content = self.source_file.read_text(encoding="utf-8", errors="replace")
        self.blocks = extract_rule_blocks(content)
        self._original_blocks = list(self.blocks)
        return True

    def _print_list(self) -> None:
        """Print the current ordered list with index numbers."""
        print("\nCurrent rule order:")
        for i, block in enumerate(self.blocks, 1):
            print(f"  [{i:2}] {block.heading}  ({block.word_count} words)")

    def _print_preview(self, targets: list[str] | None = None) -> None:
        """Print the priority preview table."""
        print()
        print(format_priority_preview(self.blocks, targets))

    def _move(self, from_idx: int, to_idx: int) -> bool:
        """Move a block from one position to another (1-based indices).

        Args:
            from_idx: Current 1-based position.
            to_idx: Target 1-based position.

        Returns:
            True if move was valid and applied.
        """
        n = len(self.blocks)
        if not (1 <= from_idx <= n and 1 <= to_idx <= n and from_idx != to_idx):
            return False
        block = self.blocks.pop(from_idx - 1)
        self.blocks.insert(to_idx - 1, block)
        return True

    def _reorder(self, new_order: list[int]) -> bool:
        """Reorder blocks to match new_order (list of 1-based indices).

        Args:
            new_order: New ordering as list of current indices.

        Returns:
            True if valid and applied.
        """
        n = len(self.blocks)
        if sorted(new_order) != list(range(1, n + 1)):
            return False
        self.blocks = [self.blocks[i - 1] for i in new_order]
        return True

    def apply(self) -> bool:
        """Write the current block order back to source_file.

        Returns:
            True if the file was written successfully.
        """
        try:
            new_content = rebuild_content(self.blocks)
            self.source_file.write_text(new_content, encoding="utf-8")
            return True
        except OSError:
            return False

    def has_changes(self) -> bool:
        """Return True if the block order differs from what was loaded."""
        return [b.heading for b in self.blocks] != [b.heading for b in self._original_blocks]

    def sort_interactive(self, targets: list[str] | None = None) -> bool:
        """Run the interactive sort session.

        Commands accepted at the prompt:
          ``u N``       — move rule N up one position
          ``d N``       — move rule N down one position
          ``m N T``     — move rule N to position T
          ``o 1 2 3…``  — specify complete new order
          ``p``         — show priority preview
          ``p cursor``  — show preview for specific target(s)
          ``s``         — save and exit
          ``q``         — quit without saving

        Args:
            targets: Harnesses to show in preview. Defaults to all.

        Returns:
            True if changes were saved, False if cancelled.
        """
        if not self.load():
            print(f"Error: {self.source_file} not found.")
            return False

        if not sys.stdin.isatty():
            print("sort_interactive requires a TTY.")
            return False

        print(f"\nRule Priority Sorter — {self.source_file}")
        print("Commands:  u N=move up  d N=move down  m N T=move to pos  o 1 2 3…=reorder  p=preview  s=save  q=quit")
        self._print_list()

        while True:
            try:
                raw = input("\nsort> ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled.")
                return False

            if not raw:
                continue

            parts = raw.split()
            cmd = parts[0]

            if cmd == "q":
                print("Quit without saving.")
                return False

            elif cmd == "s":
                if not self.has_changes():
                    print("No changes to save.")
                    return False
                if self.apply():
                    print(f"Saved {len(self.blocks)} rules to {self.source_file}.")
                    return True
                else:
                    print(f"Error: could not write {self.source_file}.")

            elif cmd in ("u", "d"):
                if len(parts) < 2 or not parts[1].isdigit():
                    print("Usage: u N  or  d N")
                    continue
                n = int(parts[1])
                t = n - 1 if cmd == "u" else n + 1
                if self._move(n, t):
                    self._print_list()
                else:
                    print(f"Invalid move: {n} → {t}  (valid range 1–{len(self.blocks)})")

            elif cmd == "m":
                if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
                    print("Usage: m FROM TO")
                    continue
                if self._move(int(parts[1]), int(parts[2])):
                    self._print_list()
                else:
                    print("Invalid positions.")

            elif cmd == "o":
                try:
                    new_order = [int(x) for x in parts[1:]]
                except ValueError:
                    print("Usage: o 1 2 3 4 … (all indices, each once)")
                    continue
                if self._reorder(new_order):
                    self._print_list()
                else:
                    print(f"Must include all {len(self.blocks)} indices exactly once.")

            elif cmd == "p":
                preview_targets = parts[1:] or targets
                # Validate target names
                if preview_targets:
                    preview_targets = [t for t in preview_targets if t in HARNESS_ORDER_SEMANTICS]
                self._print_preview(preview_targets or None)

            else:
                print("Unknown command. Type s=save q=quit p=preview u/d/m/o=reorder.")


# ---------------------------------------------------------------------------
# Standalone helpers
# ---------------------------------------------------------------------------

def sort_rules_for_file(
    source_file: Path,
    new_order: list[int],
    dry_run: bool = False,
) -> str:
    """Programmatically reorder rules in a file.

    Args:
        source_file: Path to CLAUDE.md.
        new_order: New ordering as 1-based index list.
        dry_run: If True, return the result without writing.

    Returns:
        Reordered content string. Empty string on error.
    """
    if not source_file.exists():
        return ""
    content = source_file.read_text(encoding="utf-8", errors="replace")
    blocks = extract_rule_blocks(content)

    try:
        reordered = [blocks[i - 1] for i in new_order]
    except IndexError:
        return ""

    result = rebuild_content(reordered)
    if not dry_run:
        source_file.write_text(result, encoding="utf-8")
    return result
