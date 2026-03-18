from __future__ import annotations

"""
Conflict detection via SHA256 hash comparison.

Detects manual config edits that would be overwritten by sync operations.
Uses hmac.compare_digest() for secure hash comparison to prevent timing attacks.

Three-way diff (item 11):
When a conflict is detected, ``three_way_diff()`` generates a structured
three-column diff:
  - LEFT  = Claude Code source (what HarnessSync would write)
  - BASE  = Last-synced version (the common ancestor stored as hash)
  - RIGHT = Current target file (what the user manually edited)

Users can then choose per-block: keep theirs / use synced / merge.
The ``resolve_three_way_interactive()`` method presents this UI on a TTY.
"""

import difflib
import hmac
import re
from dataclasses import dataclass
from pathlib import Path

from src.state_manager import StateManager
from src.utils.hashing import hash_file_sha256


# ---------------------------------------------------------------------------
# Semantic Rule Conflict Detection (item 25)
# ---------------------------------------------------------------------------

@dataclass
class SemanticConflict:
    """A pair of rules that appear to contradict each other."""

    rule_a: str          # Excerpt of first rule (≤120 chars)
    line_a: int          # Line number in source file
    rule_b: str          # Excerpt of contradicting rule
    line_b: int          # Line number in source file
    conflict_type: str   # Short category label
    explanation: str     # Human-readable explanation


# Contradiction pattern pairs: (pattern_a, pattern_b, conflict_type, explanation)
# Each pattern is a compiled regex that triggers when matched in DIFFERENT lines.
_CONTRADICTION_PATTERNS: list[tuple[re.Pattern, re.Pattern, str, str]] = [
    (
        re.compile(r"\b(always|never skip|always add|add)\b.{0,40}\bcomment", re.I),
        re.compile(r"\b(avoid|don.t add|no|minimal|sparse|concise)\b.{0,40}\bcomment", re.I),
        "comment_policy",
        "One rule requires comments; another discourages them.",
    ),
    (
        re.compile(r"\buse\b.{0,30}\bTypeScript\b", re.I),
        re.compile(r"\buse\b.{0,30}\bJavaScript\b(?! with TypeScript)", re.I),
        "language_choice",
        "Conflicting language directives: TypeScript vs JavaScript.",
    ),
    (
        re.compile(r"\b(always|prefer|use)\b.{0,30}\bsingle.quot", re.I),
        re.compile(r"\b(always|prefer|use)\b.{0,30}\bdouble.quot", re.I),
        "quote_style",
        "Conflicting quote-style directives.",
    ),
    (
        re.compile(r"\b(always|write|add|include)\b.{0,30}\b(test|tests|unit test)\b", re.I),
        re.compile(r"\b(skip|no|don.t write|avoid)\b.{0,30}\b(test|tests|unit test)\b", re.I),
        "test_policy",
        "Conflicting testing directives: one requires tests, another discourages them.",
    ),
    (
        re.compile(r"\b(never|don.t|avoid)\b.{0,30}\b(console\.log|print|debug)\b", re.I),
        re.compile(r"\b(always|add|use)\b.{0,30}\b(console\.log|print|debug log)\b", re.I),
        "logging_policy",
        "Conflicting log/debug directives.",
    ),
    (
        re.compile(r"\buse\b.{0,30}\b(tabs|tab indent)\b", re.I),
        re.compile(r"\buse\b.{0,30}\b(spaces|space indent)\b", re.I),
        "indentation",
        "Conflicting indentation directives: tabs vs spaces.",
    ),
    (
        re.compile(r"\b(always|prefer)\b.{0,30}\bfunctional\b", re.I),
        re.compile(r"\b(always|prefer)\b.{0,30}\bclass.based\b", re.I),
        "oop_vs_functional",
        "Conflicting paradigm preference: functional vs class-based.",
    ),
    (
        re.compile(r"\b(never|avoid|don.t use)\b.{0,20}\bvar\b", re.I),
        re.compile(r"\buse\b.{0,20}\bvar\b", re.I),
        "var_usage",
        "Conflicting 'var' usage directives.",
    ),
    (
        re.compile(r"\b(verbose|detailed|comprehensive)\b.{0,30}\bresponse", re.I),
        re.compile(r"\b(concise|brief|short|terse)\b.{0,30}\bresponse", re.I),
        "response_style",
        "Conflicting response verbosity: one asks for verbose answers, another for concise.",
    ),
    (
        re.compile(r"\b(never|don.t|avoid)\b.{0,30}\bemoji", re.I),
        re.compile(r"\b(use|add|include)\b.{0,30}\bemoji", re.I),
        "emoji_policy",
        "Conflicting emoji usage directives.",
    ),
]


def _extract_rule_lines(content: str) -> list[tuple[int, str]]:
    """Extract non-empty, non-heading, non-comment lines with their line numbers."""
    lines = []
    for i, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith("<!--"):
            continue
        lines.append((i, stripped))
    return lines


class SemanticConflictDetector:
    """Detect contradictory instructions within a CLAUDE.md (or similar rules file).

    Unlike ConflictDetector (which detects hash-based sync conflicts between
    target files), this class scans a SINGLE source file for internally
    contradictory rules — e.g. "always add comments" in one section and
    "avoid verbose comments" in another.

    Usage::

        detector = SemanticConflictDetector()
        conflicts = detector.scan(content)
        print(detector.format_report(conflicts))
    """

    def scan(self, content: str) -> list[SemanticConflict]:
        """Scan rules content for semantic contradictions.

        Args:
            content: Full text of a rules/config file (e.g. CLAUDE.md).

        Returns:
            List of SemanticConflict entries, deduplicated by conflict_type.
        """
        rule_lines = _extract_rule_lines(content)
        found: list[SemanticConflict] = []
        seen_types: set[str] = set()

        for pat_a, pat_b, ctype, explanation in _CONTRADICTION_PATTERNS:
            if ctype in seen_types:
                continue

            matches_a: list[tuple[int, str]] = [
                (ln, text) for ln, text in rule_lines if pat_a.search(text)
            ]
            matches_b: list[tuple[int, str]] = [
                (ln, text) for ln, text in rule_lines if pat_b.search(text)
            ]

            if matches_a and matches_b:
                # Report the first pair found — skip if both patterns hit the same line
                ln_a, text_a = matches_a[0]
                ln_b, text_b = matches_b[0]
                if ln_a == ln_b:
                    # Try to find a different line for the second pattern
                    alt = [(ln, t) for ln, t in matches_b if ln != ln_a]
                    if not alt:
                        continue
                    ln_b, text_b = alt[0]
                found.append(SemanticConflict(
                    rule_a=text_a[:120],
                    line_a=ln_a,
                    rule_b=text_b[:120],
                    line_b=ln_b,
                    conflict_type=ctype,
                    explanation=explanation,
                ))
                seen_types.add(ctype)

        return found

    def scan_file(self, path: Path) -> list[SemanticConflict]:
        """Scan a rules file for semantic contradictions.

        Args:
            path: Path to rules file (CLAUDE.md, AGENTS.md, etc.)

        Returns:
            List of SemanticConflict entries.
        """
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return []
        return self.scan(content)

    def check_temporal_drift(
        self,
        current_content: str,
        snapshot_content: str,
    ) -> list[SemanticConflict]:
        """Detect semantic drift between current rules and a previously-synced snapshot.

        Identifies rules added to ``current_content`` since the snapshot was
        taken that now logically contradict rules present in the snapshot.
        This catches the "rule #47 contradicts rule #12" problem where rules
        accumulate over time without the user noticing the contradiction.

        Algorithm:
          1. Extract lines present in current but NOT in snapshot (new rules).
          2. For each new rule line, check if it contradicts any snapshot rule
             using the same ``_CONTRADICTION_PATTERNS`` as ``scan()``.
          3. Return conflicts where one side is new (post-snapshot) and the
             other is from the snapshot.

        Args:
            current_content: Current CLAUDE.md content.
            snapshot_content: Previously-synced content (baseline).

        Returns:
            List of SemanticConflict where rule_a is from the snapshot and
            rule_b is the newly-added contradicting rule.
        """
        snapshot_lines = set(l.strip() for l in snapshot_content.splitlines() if l.strip())
        current_rule_lines = _extract_rule_lines(current_content)
        snapshot_rule_lines = _extract_rule_lines(snapshot_content)

        # New rules are lines in current but not in snapshot (by content)
        new_rules = [(ln, text) for ln, text in current_rule_lines
                     if text not in snapshot_lines]

        if not new_rules:
            return []

        conflicts: list[SemanticConflict] = []
        seen_types: set[str] = set()

        for pat_a, pat_b, ctype, explanation in _CONTRADICTION_PATTERNS:
            if ctype in seen_types:
                continue

            # Find snapshot lines matching pattern A
            snap_matches_a = [(ln, t) for ln, t in snapshot_rule_lines if pat_a.search(t)]
            snap_matches_b = [(ln, t) for ln, t in snapshot_rule_lines if pat_b.search(t)]

            # Check if any NEW rule contradicts existing snapshot rules
            new_matches_b = [(ln, t) for ln, t in new_rules if pat_b.search(t)]
            new_matches_a = [(ln, t) for ln, t in new_rules if pat_a.search(t)]

            if snap_matches_a and new_matches_b:
                ln_a, text_a = snap_matches_a[0]
                ln_b, text_b = new_matches_b[0]
                if ln_a != ln_b:
                    conflicts.append(SemanticConflict(
                        rule_a=text_a[:120],
                        line_a=ln_a,
                        rule_b=text_b[:120],
                        line_b=ln_b,
                        conflict_type=f"drift:{ctype}",
                        explanation=f"[TEMPORAL DRIFT] {explanation} "
                                    f"The existing rule (line {ln_a}) was synced weeks ago; "
                                    f"the contradicting rule (line {ln_b}) was added recently.",
                    ))
                    seen_types.add(ctype)

            elif snap_matches_b and new_matches_a:
                ln_a, text_a = new_matches_a[0]
                ln_b, text_b = snap_matches_b[0]
                if ln_a != ln_b:
                    conflicts.append(SemanticConflict(
                        rule_a=text_a[:120],
                        line_a=ln_a,
                        rule_b=text_b[:120],
                        line_b=ln_b,
                        conflict_type=f"drift:{ctype}",
                        explanation=f"[TEMPORAL DRIFT] {explanation} "
                                    f"The new rule (line {ln_a}) contradicts an older "
                                    f"rule (line {ln_b}) that was already synced.",
                    ))
                    seen_types.add(ctype)

        return conflicts

    def format_report(self, conflicts: list[SemanticConflict]) -> str:
        """Format detected conflicts for terminal output.

        Args:
            conflicts: Output of scan() or scan_file().

        Returns:
            Human-readable conflict report.
        """
        if not conflicts:
            return "No semantic rule conflicts detected."

        lines = [
            f"Semantic Rule Conflicts: {len(conflicts)} found",
            "=" * 50,
            "",
        ]
        for c in conflicts:
            lines.append(f"  [{c.conflict_type}] {c.explanation}")
            lines.append(f"    Line {c.line_a}: {c.rule_a!r}")
            lines.append(f"    Line {c.line_b}: {c.rule_b!r}")
            lines.append("")
        lines.append(
            "Fix: review conflicting rules above and consolidate into a single directive."
        )
        return "\n".join(lines)


def _build_merge_template(source: str, current: str, label: str) -> str:
    """Build a conflict merge template with git-style conflict markers."""
    return (
        f"<<<<<<< SYNC SOURCE (HarnessSync would write this)\n"
        f"{source}"
        f"=======\n"
        f"{current}"
        f">>>>>>> CURRENT ({label})\n"
        f"\n"
        f"# Edit the content above: remove the conflict markers and keep what you want.\n"
        f"# Save and close the editor to apply your resolution.\n"
    )


class ConflictDetector:
    """
    Hash-based conflict detection for manual config edits.

    Compares current file hashes against stored hashes from last sync.
    Uses hmac.compare_digest() for secure comparison (prevents timing attacks).
    """

    def __init__(self, state_manager: StateManager = None):
        """
        Initialize ConflictDetector.

        Args:
            state_manager: Optional StateManager for dependency injection.
                          Default: create new StateManager().
        """
        self.state_manager = state_manager or StateManager()

    def check(self, target_name: str) -> list[dict]:
        """
        Check if target config files have been modified outside HarnessSync.

        Args:
            target_name: Target to check ("codex", "gemini", "opencode")

        Returns:
            List of conflict dicts with keys:
                - file_path: Absolute path to modified file
                - stored_hash: Hash from last sync
                - current_hash: Current computed hash (or "" if deleted)
                - target_name: Target name
                - note: "deleted" if file was removed (optional)

            Empty list if no conflicts detected.
        """
        # Get stored state for target
        target_status = self.state_manager.get_target_status(target_name)
        if not target_status:
            # No previous sync - no conflicts possible
            return []

        # Extract file_hashes dict (maps file_path -> stored_hash)
        file_hashes = target_status.get("file_hashes", {})
        conflicts = []

        # Check each tracked file
        for file_path_str, stored_hash in file_hashes.items():
            file_path = Path(file_path_str)

            # Compute current hash
            current_hash = hash_file_sha256(file_path)

            # Check for deletion
            if not current_hash:
                conflicts.append({
                    "file_path": file_path_str,
                    "stored_hash": stored_hash,
                    "current_hash": "",
                    "target_name": target_name,
                    "note": "deleted"
                })
                continue

            # Secure hash comparison (prevents timing attacks)
            # Use hmac.compare_digest instead of == operator
            if not hmac.compare_digest(stored_hash, current_hash):
                conflicts.append({
                    "file_path": file_path_str,
                    "stored_hash": stored_hash,
                    "current_hash": current_hash,
                    "target_name": target_name
                })

        return conflicts

    def check_all(self) -> dict[str, list[dict]]:
        """
        Run conflict check for all targets.

        Returns:
            Dict mapping target_name -> list of conflicts
            Example: {"codex": [...], "gemini": [], "opencode": [...]}
        """
        targets = ["codex", "gemini", "opencode"]
        result = {}

        for target in targets:
            result[target] = self.check(target)

        return result

    def resolve_interactive(self, conflicts: dict[str, list[dict]]) -> dict[str, str]:
        """Prompt the user to resolve each conflict interactively.

        For each conflicted file, asks whether to keep local modifications or
        accept the incoming sync (overwrite). Works only when stdin is a TTY;
        falls back to an empty dict (overwrite all) in non-interactive contexts.

        Args:
            conflicts: Dict from check_all() mapping target -> conflict list.

        Returns:
            Dict mapping file_path -> "keep" | "accept".
            Files absent from the returned dict default to "accept" (overwrite).
        """
        import sys

        if not sys.stdin.isatty():
            return {}

        resolutions: dict[str, str] = {}
        all_conflicts: list[dict] = [
            c for target_conflicts in conflicts.values() for c in target_conflicts
        ]

        if not all_conflicts:
            return resolutions

        print(f"\nHarnessSync detected {len(all_conflicts)} conflict(s) — local modifications "
              "exist that would be overwritten.")

        for conflict in all_conflicts:
            file_path = conflict["file_path"]
            target_name = conflict.get("target_name", "?")
            note = conflict.get("note", "")

            print(f"\n{'=' * 60}")
            print(f"File:   {file_path}")
            print(f"Target: {target_name}")
            if note == "deleted":
                print("Status: deleted after last sync")
            else:
                stored = conflict.get("stored_hash", "")[:12]
                current = conflict.get("current_hash", "")[:12]
                print(f"Status: modified  ({stored}... → {current}...)")

            print()
            print("  k) Keep local  — skip overwriting this file")
            print("  a) Accept sync — allow HarnessSync to overwrite")

            while True:
                try:
                    choice = input("  Choice [k/a]: ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\nResolution cancelled — defaulting to accept all remaining.")
                    return resolutions

                if choice in ("k", "keep"):
                    resolutions[file_path] = "keep"
                    print(f"  → Keeping local: {file_path}")
                    break
                elif choice in ("a", "accept"):
                    resolutions[file_path] = "accept"
                    print(f"  → Will overwrite: {file_path}")
                    break
                else:
                    print("  Enter 'k' to keep local or 'a' to accept sync.")

        return resolutions

    def three_way_diff(
        self,
        source_content: str,
        conflict: dict,
        base_content: str | None = None,
    ) -> dict:
        """Generate a three-way diff for a conflicted file.

        Produces a structured comparison of:
          - source: What HarnessSync would write (from Claude Code)
          - base:   Last-synced content (the common ancestor, if available)
          - current: What's in the target file right now (manually edited)

        Args:
            source_content: The content HarnessSync would write.
            conflict: A conflict dict from ``check()`` (contains file_path).
            base_content: The last-synced content. If None, treated as empty
                          (simulates no common ancestor).

        Returns:
            Dict with keys:
              - file_path: Conflicted file path
              - source_lines: Lines of what sync would write
              - base_lines: Lines of last-synced version (or [])
              - current_lines: Lines of current file
              - unified_source_vs_current: Unified diff source↔current
              - unified_base_vs_current: Unified diff base↔current
              - unified_base_vs_source: Unified diff base↔source
              - has_real_conflict: True if current ≠ source
        """
        file_path = conflict.get("file_path", "")
        fp = Path(file_path)

        current_content = ""
        if fp.exists():
            try:
                current_content = fp.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

        base_content = base_content or ""

        source_lines = source_content.splitlines(keepends=True)
        base_lines = base_content.splitlines(keepends=True)
        current_lines = current_content.splitlines(keepends=True)

        def _udiff(a: list[str], b: list[str], fromfile: str, tofile: str) -> str:
            return "".join(difflib.unified_diff(a, b, fromfile=fromfile, tofile=tofile, lineterm="\n"))

        return {
            "file_path": file_path,
            "source_lines": source_lines,
            "base_lines": base_lines,
            "current_lines": current_lines,
            "unified_source_vs_current": _udiff(source_lines, current_lines, "sync-source", "current"),
            "unified_base_vs_current": _udiff(base_lines, current_lines, "last-synced", "current"),
            "unified_base_vs_source": _udiff(base_lines, source_lines, "last-synced", "sync-source"),
            "has_real_conflict": source_content != current_content,
        }

    def resolve_three_way_interactive(
        self,
        conflict: dict,
        three_way: dict,
    ) -> tuple[str, str]:
        """Present three-way diff in terminal and ask user to resolve.

        Shows a side-by-side colored diff comparing the current file (your
        manual edits) against the HarnessSync source version, then offers
        per-file choices:
          s) Use synced  — accept HarnessSync's version
          k) Keep theirs — preserve the manual edit
          e) Edit manually — write a temp file and open $EDITOR

        Args:
            conflict: Conflict dict from ``check()``.
            three_way: Three-way diff dict from ``three_way_diff()``.

        Returns:
            Tuple of (resolution: "synced" | "keep" | "manual", final_content: str).
        """
        import os
        import subprocess
        import tempfile

        file_path = three_way["file_path"]
        source_lines = three_way["source_lines"]
        current_lines = three_way["current_lines"]
        base_lines = three_way.get("base_lines", [])

        print(f"\n{'=' * 70}")
        print(f"THREE-WAY CONFLICT: {file_path}")
        print(f"{'=' * 70}")

        # Use side-by-side colored diff when supported; fall back to unified diff.
        try:
            from src.diff_formatter import format_side_by_side, _supports_color

            current_text = "".join(current_lines)
            source_text = "".join(source_lines)
            base_text = "".join(base_lines)

            # Primary view: current file (your edits) ↔ what sync would write
            if current_text != source_text:
                print("\n[ Side-by-side: YOUR VERSION  vs  SYNC SOURCE ]")
                print(format_side_by_side(
                    current_text,
                    source_text,
                    label=f"current ↔ sync-source for {file_path}",
                    context_lines=4,
                ))
            else:
                print("\n  (current file matches sync source — no visible conflict)")

            # Secondary view: what changed since last sync (base → current)
            if base_text and base_text != current_text:
                print("\n[ Your edits since last sync: BASE → CURRENT ]")
                print(format_side_by_side(
                    base_text,
                    current_text,
                    label="last-synced → your edits",
                    context_lines=3,
                ))

        except Exception:
            # Graceful fallback to plain unified diffs if side-by-side fails
            diff_base_vs_current = three_way["unified_base_vs_current"]
            print("\n[ Changes: last-synced → manual edits (what YOU changed) ]")
            if diff_base_vs_current.strip():
                print(diff_base_vs_current[:3000])
            else:
                print("  (no diff from base)")

            print("\n[ Changes: last-synced → sync-source (what HARNESSSYNC would write) ]")
            if three_way["unified_base_vs_source"].strip():
                print(three_way["unified_base_vs_source"][:3000])
            else:
                print("  (no diff from base)")

        print("\nChoices:")
        print("  s) Use synced  — overwrite with HarnessSync version")
        print("  k) Keep theirs — preserve your manual edits, skip sync for this file")
        print("  e) Edit        — open a merge in $EDITOR (requires EDITOR env var)")

        while True:
            try:
                choice = input("\n  Choice [s/k/e]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled — defaulting to 'keep'.")
                return "keep", "".join(current_lines)

            if choice in ("s", "synced"):
                return "synced", "".join(source_lines)

            elif choice in ("k", "keep"):
                return "keep", "".join(current_lines)

            elif choice in ("e", "edit"):
                editor = os.environ.get("EDITOR", "vi")
                # Write merge template to temp file
                merge_content = _build_merge_template(
                    "".join(source_lines), "".join(current_lines), file_path
                )
                with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".md", delete=False, encoding="utf-8"
                ) as tf:
                    tf.write(merge_content)
                    tmp_path = tf.name

                try:
                    subprocess.run([editor, tmp_path], check=False)
                    final = Path(tmp_path).read_text(encoding="utf-8")
                except Exception as e:
                    print(f"  Editor failed: {e}. Defaulting to keep.")
                    final = "".join(current_lines)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass

                return "manual", final

            else:
                print("  Enter 's', 'k', or 'e'.")

    def section_conflicts(
        self,
        source_content: str,
        conflict: dict,
    ) -> list[dict]:
        """Detect which individual Markdown sections conflict between source and target.

        Instead of treating the whole file as a single conflict, break it into
        sections and return only the sections that differ. Enables per-section
        resolution ('keep this section from target, use sync for that one').

        Args:
            source_content: What HarnessSync would write (from Claude Code).
            conflict: Conflict dict from ``check()`` (contains file_path).

        Returns:
            List of section-conflict dicts with keys:
              - heading: Section heading text
              - source_body: Section body from sync source
              - current_body: Section body from current file ('' if section absent)
              - status: "added" | "removed" | "modified" | "identical"
        """
        import re

        _SECTION_RE = re.compile(r"^(#{1,3}\s+.+)$", re.MULTILINE)

        file_path = Path(conflict.get("file_path", ""))
        current_content = ""
        if file_path.exists():
            try:
                current_content = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass

        def _split_sections(text: str) -> dict[str, str]:
            matches = list(_SECTION_RE.finditer(text))
            sections: dict[str, str] = {}
            for i, m in enumerate(matches):
                heading = m.group(1).strip()
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                sections[heading] = text[start:end].strip()
            return sections

        source_sections = _split_sections(source_content)
        current_sections = _split_sections(current_content)
        all_headings = sorted(set(source_sections) | set(current_sections))

        result = []
        for heading in all_headings:
            src_body = source_sections.get(heading)
            cur_body = current_sections.get(heading)

            if src_body is not None and cur_body is None:
                status = "added"
            elif src_body is None and cur_body is not None:
                status = "removed"
            elif src_body != cur_body:
                status = "modified"
            else:
                status = "identical"

            if status != "identical":
                result.append({
                    "heading": heading,
                    "source_body": src_body or "",
                    "current_body": cur_body or "",
                    "status": status,
                    "file_path": str(file_path),
                })

        return result

    def resolve_section_interactive(
        self,
        section_conflicts: list[dict],
    ) -> dict[str, str]:
        """Present per-section conflicts and ask user to choose resolution for each.

        Args:
            section_conflicts: List from ``section_conflicts()``.

        Returns:
            Dict mapping section heading -> "source" | "keep" | "skip".
            "source" = use HarnessSync version, "keep" = preserve current.
        """
        import sys

        if not sys.stdin.isatty():
            return {}

        resolutions: dict[str, str] = {}
        total = len(section_conflicts)
        if total == 0:
            return resolutions

        print(f"\n{total} section(s) differ — resolve each:")

        for i, sc in enumerate(section_conflicts, start=1):
            heading = sc["heading"]
            status = sc["status"]
            print(f"\n[{i}/{total}] {heading}  ({status})")

            if status == "added":
                print("  This section exists in sync source but NOT in current file.")
                print("  a) Add it   k) Keep current (skip this section)")
                prompt = "  Choice [a/k]: "
                yes_choice, no_choice = "a", "k"
                yes_resolution, no_resolution = "source", "keep"
            elif status == "removed":
                print("  This section exists in current file but NOT in sync source.")
                print("  r) Remove it (use sync source)   k) Keep current")
                prompt = "  Choice [r/k]: "
                yes_choice, no_choice = "r", "k"
                yes_resolution, no_resolution = "source", "keep"
            else:
                # modified — show brief diff
                import difflib
                diff = difflib.unified_diff(
                    sc["current_body"].splitlines(keepends=True),
                    sc["source_body"].splitlines(keepends=True),
                    fromfile="current",
                    tofile="sync-source",
                    lineterm="\n",
                )
                diff_text = "".join(list(diff)[:20])
                if diff_text:
                    print(diff_text[:800])
                print("  s) Use sync source   k) Keep current")
                prompt = "  Choice [s/k]: "
                yes_choice, no_choice = "s", "k"
                yes_resolution, no_resolution = "source", "keep"

            while True:
                try:
                    choice = input(prompt).strip().lower()
                except (EOFError, KeyboardInterrupt):
                    print("\nCancelled — keeping remaining sections.")
                    return resolutions

                if choice in (yes_choice, "yes", "y"):
                    resolutions[heading] = yes_resolution
                    break
                elif choice in (no_choice, "keep", "k"):
                    resolutions[heading] = no_resolution
                    break
                else:
                    print(f"  Enter '{yes_choice}' or '{no_choice}'.")

        return resolutions

    def apply_section_resolutions(
        self,
        source_content: str,
        current_content: str,
        resolutions: dict[str, str],
    ) -> str:
        """Build merged file content from per-section resolution choices.

        Reconstructs the file by iterating sections in source order and
        substituting each section body based on the resolution decision:
          - "source": use HarnessSync's version of the section
          - "keep":   preserve the user's current version
          - "skip":   omit the section entirely

        Sections with no resolution entry default to "source".

        Args:
            source_content: What HarnessSync would write (canonical order).
            current_content: Current file on disk (user's version).
            resolutions: Dict mapping section heading -> "source" | "keep" | "skip".

        Returns:
            Merged file content string.
        """
        import re

        _SECTION_RE = re.compile(r"^(#{1,3}\s+.+)$", re.MULTILINE)

        def _split_ordered(text: str) -> list[tuple[str, str]]:
            """Return ordered list of (heading, body) pairs."""
            matches = list(_SECTION_RE.finditer(text))
            result = []
            for i, m in enumerate(matches):
                heading = m.group(1).strip()
                start = m.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                body = text[start:end]
                # Preserve leading newline from heading line
                result.append((heading, body))
            return result

        source_sections = _split_ordered(source_content)
        current_sections = dict(_split_ordered(current_content))

        # Sections in source that exist in current — track for "keep-only" sections
        source_headings = {h for h, _ in source_sections}

        output_parts: list[str] = []

        # Content before first heading (preamble)
        first_match = _SECTION_RE.search(source_content)
        if first_match and first_match.start() > 0:
            output_parts.append(source_content[: first_match.start()])

        # Process sections in source order
        for heading, source_body in source_sections:
            resolution = resolutions.get(heading, "source")

            if resolution == "skip":
                continue
            elif resolution == "keep":
                kept_body = current_sections.get(heading, source_body)
                output_parts.append(f"{heading}{kept_body}")
            else:  # "source" (default)
                output_parts.append(f"{heading}{source_body}")

        # Append any "keep" sections that only exist in current (status=removed)
        for heading, current_body in _split_ordered(current_content):
            if heading not in source_headings:
                resolution = resolutions.get(heading, "keep")
                if resolution == "keep":
                    output_parts.append(f"{heading}{current_body}")

        return "".join(output_parts)

    def format_side_by_side_diff(
        self,
        three_way: dict,
        width: int = 80,
        colorize: bool = False,
    ) -> str:
        """Render a side-by-side terminal diff from three_way_diff() output.

        Displays two columns:
          LEFT  = sync source (what HarnessSync would write)
          RIGHT = current file (what the user manually edited)

        Changed lines are prefixed with ``+`` / ``-`` indicators. Each column
        is ``(width // 2 - 2)`` characters wide, truncated with ``…`` if longer.

        Args:
            three_way: Dict from ``three_way_diff()`` containing source_lines,
                       current_lines, and unified_source_vs_current.
            width: Total terminal width in characters. Default: 80.
            colorize: If True, use ANSI escape codes to color removed lines red
                      and added lines green. Disable for non-TTY output.

        Returns:
            Multi-line formatted string suitable for terminal display.
        """
        import difflib
        import os

        # When colorize is explicitly requested, honour it unconditionally.
        # NO_COLOR only applies to programs that auto-detect color support.
        _use_color = colorize

        # ANSI color helpers
        _RED = "\033[31m"
        _GREEN = "\033[32m"
        _CYAN = "\033[36m"
        _BOLD = "\033[1m"
        _RESET = "\033[0m"

        def _c(text: str, code: str) -> str:
            return f"{code}{text}{_RESET}" if _use_color else text

        col_w = max(20, (width // 2) - 3)
        file_path = three_way.get("file_path", "")
        source_lines = [l.rstrip("\n") for l in three_way.get("source_lines", [])]
        current_lines = [l.rstrip("\n") for l in three_way.get("current_lines", [])]

        def _trunc(s: str, w: int) -> str:
            return s if len(s) <= w else s[: w - 1] + "…"

        sep = "─" * width
        header_l = _trunc("SYNC SOURCE (HarnessSync)", col_w)
        header_r = _trunc(f"CURRENT ({file_path})", col_w)
        header = f"  {_c(header_l, _BOLD):<{col_w}}  │  {_c(header_r, _BOLD)}"

        lines: list[str] = [
            sep,
            _c(f"SIDE-BY-SIDE DIFF: {file_path}", _CYAN),
            sep,
            header,
            "─" * width,
        ]

        # Build a line-level diff using SequenceMatcher
        matcher = difflib.SequenceMatcher(
            None, source_lines, current_lines, autojunk=False
        )

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                for k in range(i2 - i1):
                    left = _trunc(source_lines[i1 + k], col_w)
                    right = _trunc(current_lines[j1 + k], col_w)
                    lines.append(f"  {left:<{col_w}}  │  {right}")
            elif tag == "replace":
                # Show deletions on left (red), insertions on right (green)
                left_block = source_lines[i1:i2]
                right_block = current_lines[j1:j2]
                max_len = max(len(left_block), len(right_block))
                for k in range(max_len):
                    left_raw = left_block[k] if k < len(left_block) else ""
                    right_raw = right_block[k] if k < len(right_block) else ""
                    left = _trunc(left_raw, col_w - 2)
                    right = _trunc(right_raw, col_w - 2)
                    l_indicator = "-" if left_raw else " "
                    r_indicator = "+" if right_raw else " "
                    left_col = _c(f"{l_indicator} {left}", _RED) if left_raw else f"  {left}"
                    right_col = _c(f"{r_indicator} {right}", _GREEN) if right_raw else f"  {right}"
                    lines.append(f"{left_col:<{col_w + (len(_RED) + len(_RESET) if _use_color and left_raw else 0) + 1}}  │  {right_col}")
            elif tag == "delete":
                for k in range(i2 - i1):
                    left = _trunc(source_lines[i1 + k], col_w - 2)
                    colored = _c(f"- {left}", _RED)
                    lines.append(f"{colored:<{col_w + (len(_RED) + len(_RESET) if _use_color else 0)}}  │  {'':>{col_w}}")
            elif tag == "insert":
                for k in range(j2 - j1):
                    right = _trunc(current_lines[j1 + k], col_w - 2)
                    colored = _c(f"+ {right}", _GREEN)
                    lines.append(f"  {'':>{col_w - 1}}  │  {colored}")

        lines.append(sep)
        has_conflict = three_way.get("has_real_conflict", True)
        if not has_conflict:
            lines.append("  (no differences — files are identical)")
        else:
            legend_del = _c("- = sync would overwrite", _RED)
            legend_add = _c("+ = your manual edit", _GREEN)
            lines.append(f"  Legend:  {legend_del}  {legend_add}")
            lines.append(
                "  Resolve: s) use sync source  k) keep current  e) edit manually"
            )
        return "\n".join(lines)

    def format_warnings(self, conflicts: dict[str, list[dict]]) -> str:
        """
        Format conflict warnings for user output.

        Args:
            conflicts: Dict from check_all() mapping target -> conflict list

        Returns:
            Formatted warning string showing modified/deleted files per target
        """
        if not conflicts or all(not v for v in conflicts.values()):
            return ""

        lines = []
        for target_name, target_conflicts in conflicts.items():
            if not target_conflicts:
                continue

            lines.append(f"\n⚠ {target_name.upper()}: {len(target_conflicts)} file(s) modified outside HarnessSync:")

            for conflict in target_conflicts:
                file_path = conflict["file_path"]
                note = conflict.get("note", "")

                if note == "deleted":
                    lines.append(f"  · {file_path} (deleted)")
                else:
                    lines.append(f"  · {file_path} (modified)")

        if not lines:
            return ""

        warning = "\n".join(lines)
        warning += "\n\nThese changes will be overwritten. Run with --dry-run to preview changes."

        return warning


# ---------------------------------------------------------------------------
# Item 1 — Interactive Conflict Resolution Wizard
# ---------------------------------------------------------------------------

def _explain_conflict_in_plain_english(
    source_content: str,
    current_content: str,
    file_path: str,
    target: str,
) -> str:
    """Produce a plain-English explanation of what is in conflict.

    Analyses the diff between source and current to explain *why* there is
    a conflict and what the user likely changed, in language that does not
    require reading raw diffs.

    Args:
        source_content: What HarnessSync would write.
        current_content: Current file on disk.
        file_path: Path to the file (for labelling).
        target: Target harness name.

    Returns:
        Multi-line plain-English conflict summary string.
    """
    source_lines = source_content.splitlines()
    current_lines = current_content.splitlines()

    added: list[str] = []
    removed: list[str] = []

    matcher = difflib.SequenceMatcher(None, source_lines, current_lines, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "insert":
            added.extend(current_lines[j1:j2])
        elif tag == "delete":
            removed.extend(source_lines[i1:i2])
        elif tag == "replace":
            removed.extend(source_lines[i1:i2])
            added.extend(current_lines[j1:j2])

    # Filter out blank lines and comment-only lines for human summary
    def _meaningful(lines: list[str]) -> list[str]:
        return [l.strip() for l in lines if l.strip() and not l.strip().startswith("<!--")]

    meaningful_added = _meaningful(added)
    meaningful_removed = _meaningful(removed)

    parts: list[str] = []
    fname = Path(file_path).name

    parts.append(f"Conflict in {fname} ({target}):")

    if not meaningful_added and not meaningful_removed:
        parts.append("  The files differ only in whitespace or comments.")
        return "\n".join(parts)

    # `added`   = lines present in current but not in source (user manually added)
    # `removed` = lines present in source but not in current (sync wants to restore)
    if meaningful_added and not meaningful_removed:
        parts.append(
            f"  You manually added {len(meaningful_added)} line(s) that HarnessSync "
            f"would overwrite. If you sync now, these will be removed."
        )
        for line in meaningful_added[:3]:
            parts.append(f'    Your addition: \u201c{line[:80]}\u201d')
        if len(meaningful_added) > 3:
            parts.append(f"    \u2026 and {len(meaningful_added) - 3} more.")
    elif meaningful_removed and not meaningful_added:
        parts.append(
            f"  You deleted {len(meaningful_removed)} line(s) from the synced config "
            f"that HarnessSync wants to restore."
        )
        for line in meaningful_removed[:3]:
            parts.append(f'    Sync wants to re-add: \u201c{line[:80]}\u201d')
        if len(meaningful_removed) > 3:
            parts.append(f"    \u2026 and {len(meaningful_removed) - 3} more.")
    else:
        parts.append(
            f"  You changed {len(meaningful_added)} line(s) and HarnessSync would "
            f"replace them with {len(meaningful_removed)} different line(s). Specifically:"
        )
        for user_line, sync_line in zip(meaningful_added[:3], meaningful_removed[:3]):
            parts.append(f'    Your version: \u201c{user_line[:60]}\u201d')
            parts.append(f'    Sync version: \u201c{sync_line[:60]}\u201d')
        if max(len(meaningful_added), len(meaningful_removed)) > 3:
            parts.append(f"    \u2026 and more differences.")

    return "\n".join(parts)


class ConflictResolutionWizard:
    """Interactive conflict resolution wizard for HarnessSync.

    Provides a guided terminal UI that:
    1. Explains each conflict in plain English (no raw diffs unless requested).
    2. Shows a side-by-side diff on demand.
    3. Offers resolution choices: keep source, keep target, merge, skip.
    4. Applies resolutions and returns the final content per file.

    This is a higher-level wrapper around ConflictDetector.resolve_three_way_interactive()
    that adds the plain-English explanation layer and a summary at the end.

    Usage::

        wizard = ConflictResolutionWizard(ConflictDetector(project_dir))
        resolved = wizard.run(conflicts, source_data)
        # resolved: dict[file_path -> resolution_choice]
    """

    RESOLUTION_KEEP_SOURCE = "source"   # Use HarnessSync's version
    RESOLUTION_KEEP_TARGET = "keep"     # Preserve manual edits
    RESOLUTION_SKIP = "skip"            # Leave file untouched this sync
    RESOLUTION_BACKPORT = "backport"    # Copy target edits back to CLAUDE.md source

    def __init__(self, detector: "ConflictDetector") -> None:
        self.detector = detector

    def explain_conflict(
        self,
        conflict: dict,
        source_content: str,
        target: str,
    ) -> str:
        """Return a plain-English explanation of the conflict.

        Args:
            conflict: Conflict dict from ConflictDetector.check().
            source_content: What HarnessSync would write to the file.
            target: Target harness name.

        Returns:
            Plain-English summary string.
        """
        file_path = conflict.get("file_path", "")
        current_content = ""
        p = Path(file_path)
        if p.exists():
            try:
                current_content = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        return _explain_conflict_in_plain_english(
            source_content, current_content, file_path, target
        )

    def run_interactive(
        self,
        conflicts_by_target: dict,
        source_contents: dict | None = None,
    ) -> dict:
        """Run the interactive conflict resolution wizard on a TTY.

        Args:
            conflicts_by_target: Output of ConflictDetector.check_all() —
                dict mapping target_name -> list of conflict dicts.
            source_contents: Dict mapping file_path -> source content string.
                             Used for plain-English explanations. Optional.

        Returns:
            Dict mapping (target, file_path) -> resolution choice string:
            "source" | "keep" | "skip"
        """
        import sys

        if not sys.stdin.isatty():
            return {}

        source_contents = source_contents or {}
        resolutions: dict = {}
        total_conflicts = sum(len(v) for v in conflicts_by_target.values())

        if total_conflicts == 0:
            print("No conflicts to resolve.")
            return resolutions

        print(f"\n{'=' * 70}")
        print(f"HarnessSync Conflict Resolution Wizard")
        print(f"{'=' * 70}")
        print(f"Found {total_conflicts} conflict(s) across "
              f"{sum(1 for v in conflicts_by_target.values() if v)} target(s).")
        print("\nFor each conflict, you can:")
        print("  s) Use sync source — let HarnessSync overwrite with the Claude Code version")
        print("  k) Keep target    — preserve your manual edits, skip this file this sync")
        print("  b) Back-port      — copy your manual edits back to CLAUDE.md as the new source")
        print("  d) Show diff      — display a side-by-side diff before deciding")
        print("  ?) Skip for now   — leave this conflict unresolved (file won't be synced)")
        print()

        conflict_num = 0
        for target, conflict_list in conflicts_by_target.items():
            if not conflict_list:
                continue
            for conflict in conflict_list:
                conflict_num += 1
                file_path = conflict.get("file_path", "")
                source = source_contents.get(file_path, "")

                print(f"\n[{conflict_num}/{total_conflicts}] ", end="")
                print(self.explain_conflict(conflict, source, target))

                choice = self._ask_resolution(conflict, source, target)
                resolutions[(target, file_path)] = choice

        print(f"\n{'=' * 70}")
        print(f"Conflict resolution complete.")
        sources = sum(1 for v in resolutions.values() if v == self.RESOLUTION_KEEP_SOURCE)
        keeps = sum(1 for v in resolutions.values() if v == self.RESOLUTION_KEEP_TARGET)
        skips = sum(1 for v in resolutions.values() if v == self.RESOLUTION_SKIP)
        backports = sum(1 for v in resolutions.values() if v == self.RESOLUTION_BACKPORT)
        print(f"  Use sync source: {sources}")
        print(f"  Keep target:     {keeps}")
        print(f"  Back-port:       {backports}")
        print(f"  Skipped:         {skips}")

        return resolutions

    def _ask_resolution(
        self,
        conflict: dict,
        source_content: str,
        target: str,
    ) -> str:
        """Prompt the user for a resolution choice for one conflict.

        Returns one of RESOLUTION_KEEP_SOURCE | RESOLUTION_KEEP_TARGET |
        RESOLUTION_BACKPORT | RESOLUTION_SKIP.
        """
        file_path = conflict.get("file_path", "")

        while True:
            try:
                raw = input("\n  Choice [s=sync, k=keep, b=back-port, d=diff, ?=skip]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nCancelled — defaulting to 'skip'.")
                return self.RESOLUTION_SKIP

            if raw in ("s", "sync", "source"):
                return self.RESOLUTION_KEEP_SOURCE
            elif raw in ("k", "keep"):
                return self.RESOLUTION_KEEP_TARGET
            elif raw in ("b", "back-port", "backport", "bp"):
                return self.RESOLUTION_BACKPORT
            elif raw in ("d", "diff"):
                try:
                    three_way = self.detector.three_way_diff(conflict, source_content)
                    print(self.detector.format_side_by_side_diff(three_way))
                except Exception as exc:
                    print(f"  (diff failed: {exc})")
            elif raw in ("?", "skip"):
                return self.RESOLUTION_SKIP
            else:
                print("  Enter 's', 'k', 'b', 'd', or '?'.")

    def backport_to_source(
        self,
        conflict: dict,
        claude_md_path: "Path",
        dry_run: bool = False,
    ) -> str:
        """Back-port manual target edits into the CLAUDE.md source file.

        When the user chooses to back-port, this method reads the manually
        edited target file and replaces the corresponding section in CLAUDE.md,
        making the manual edits the new authoritative source.

        The replaced section is identified by the HarnessSync managed block
        markers in CLAUDE.md. If no markers are found, the target content is
        appended with a back-port comment.

        Args:
            conflict: Conflict dict with ``file_path`` pointing to the
                      manually edited target file.
            claude_md_path: Path to the CLAUDE.md source file.
            dry_run: If True, return the new content without writing.

        Returns:
            The new CLAUDE.md content string (whether written or not).

        Raises:
            OSError: If either file cannot be read or written.
        """
        from pathlib import Path as _Path
        import re as _re

        target_path = _Path(conflict.get("file_path", ""))
        if not target_path.exists():
            raise OSError(f"Target file not found: {target_path}")
        if not claude_md_path.exists():
            raise OSError(f"CLAUDE.md not found: {claude_md_path}")

        target_content = target_path.read_text(encoding="utf-8")
        claude_content = claude_md_path.read_text(encoding="utf-8")

        # Try to strip existing HarnessSync managed block from target content
        managed_re = _re.compile(
            r"<!--\s*Managed by HarnessSync\s*-->.*?<!--\s*End HarnessSync managed content\s*-->",
            _re.DOTALL | _re.IGNORECASE,
        )
        # Extract the user edits from between managed markers if present
        inner_match = managed_re.search(target_content)
        if inner_match:
            # Keep everything outside the markers (user's manual additions)
            user_edits = target_content[:inner_match.start()].strip()
            after_block = target_content[inner_match.end():].strip()
            if after_block:
                user_edits = (user_edits + "\n\n" + after_block).strip()
        else:
            user_edits = target_content.strip()

        if not user_edits:
            # Nothing to back-port — target is empty outside managed block
            return claude_content

        # Insert the back-ported content into CLAUDE.md with a clear marker
        ts = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z")
        backport_block = (
            f"\n\n<!-- Back-ported from {target_path.name} on {ts} -->\n"
            f"{user_edits}\n"
            f"<!-- End back-port -->\n"
        )
        new_content = claude_content.rstrip() + backport_block

        if not dry_run:
            claude_md_path.write_text(new_content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Sync Conflict Resolution Wizard (item 1)
# ---------------------------------------------------------------------------

class SyncConflictWizard:
    """Non-interactive strategy-based conflict resolver for automated pipelines.

    Unlike ``ConflictDetector.resolve_interactive()``, this wizard resolves
    conflicts programmatically using a named strategy — suitable for CI/CD
    and ``--dry-run`` preview modes where no TTY is available.

    Strategies
    ----------
    ``"ours"``
        Accept the HarnessSync version unconditionally (overwrite target).
    ``"theirs"``
        Keep the manually edited target file (skip sync for this file).
    ``"union"``
        Concatenate unique lines from both versions, deduplicated.
        Source (HarnessSync) lines come first, then novel target-only lines.
    ``"newer"``
        Alias for ``"ours"`` — HarnessSync source is always considered newer.

    Usage::

        wizard = SyncConflictWizard(strategy="union")
        resolved = wizard.auto_resolve(three_way)
        # resolved is the string content to write, or None to skip

    """

    VALID_STRATEGIES = frozenset({"ours", "theirs", "union", "newer"})

    def __init__(self, strategy: str = "ours") -> None:
        if strategy not in self.VALID_STRATEGIES:
            raise ValueError(
                f"Unknown strategy '{strategy}'. "
                f"Valid: {', '.join(sorted(self.VALID_STRATEGIES))}"
            )
        self.strategy = strategy

    def auto_resolve(self, three_way: dict) -> tuple[str, str]:
        """Resolve a conflict dict without user interaction.

        Args:
            three_way: Dict from ``ConflictDetector.three_way_diff()``.
                       Must include ``source_lines`` and ``current_lines``.

        Returns:
            ``(resolution_label, content)`` where:
            - ``resolution_label`` is one of ``"synced"``, ``"keep"``, ``"merged"``
            - ``content`` is the resolved file content as a string

        Raises:
            KeyError: If ``three_way`` is missing required keys.
        """
        source_lines: list[str] = three_way["source_lines"]
        current_lines: list[str] = three_way["current_lines"]

        source_text = "".join(source_lines)
        current_text = "".join(current_lines)

        effective = self.strategy if self.strategy != "newer" else "ours"

        if effective == "ours":
            return "synced", source_text

        if effective == "theirs":
            return "keep", current_text

        # union: source lines first, then novel lines only in current
        source_set = set(l.rstrip("\n") for l in source_lines)
        novel_lines = [
            l for l in current_lines
            if l.rstrip("\n") not in source_set and l.strip()
        ]
        merged = source_text.rstrip()
        if novel_lines:
            merged += "\n\n" + "".join(novel_lines)
        return "merged", merged

    def resolve_many(
        self,
        three_ways: list[dict],
    ) -> list[tuple[str, str, str]]:
        """Resolve a list of three-way diff dicts.

        Args:
            three_ways: List of dicts from ``ConflictDetector.three_way_diff()``.

        Returns:
            List of ``(file_path, resolution_label, content)`` triples.
        """
        results = []
        for tw in three_ways:
            label, content = self.auto_resolve(tw)
            results.append((tw.get("file_path", ""), label, content))
        return results

    def build_resolution_summary(self, three_ways: list[dict]) -> str:
        """Return a human-readable summary of what ``resolve_many`` would do.

        Args:
            three_ways: List of dicts from ``ConflictDetector.three_way_diff()``.

        Returns:
            Multi-line summary string.
        """
        lines = [
            f"Conflict Resolution Preview  (strategy: {self.strategy})",
            "=" * 55,
        ]
        for tw in three_ways:
            label, _ = self.auto_resolve(tw)
            fp = tw.get("file_path", "(unknown)")
            action = {
                "synced": "→ overwrite with HarnessSync version",
                "keep":   "→ keep manual edits, skip sync",
                "merged": "→ merge (source first, novel target lines appended)",
            }.get(label, f"→ {label}")
            lines.append(f"  {fp}  {action}")
        lines.append("")
        lines.append(f"Total: {len(three_ways)} file(s) to resolve.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Item 1 — TUI Conflict Resolution Wizard
# ---------------------------------------------------------------------------

class TuiConflictWizard:
    """TTY-based interactive conflict resolution wizard with side-by-side diff.

    When a target file has been manually edited since the last sync, this
    wizard surfaces a rich diff showing:
      LEFT  = Claude Code source (what HarnessSync would write)
      RIGHT = Target file (what the user manually edited)

    The user picks per-file: [o]verwrite, [m]erge (union), [k]eep, [s]kip.

    Works with or without a TTY — falls back to the non-interactive
    ``SyncConflictWizard`` with strategy="union" when stdin is not a
    terminal.

    Args:
        detector: ConflictDetector to use for three-way diffs.
        auto_strategy: Strategy to use when not on a TTY. Default: 'union'.
        color: Whether to use ANSI color codes in diff output.
    """

    CHOICES = {"o": "overwrite", "m": "merge", "k": "keep", "s": "skip"}

    def __init__(
        self,
        detector: "ConflictDetector | None" = None,
        auto_strategy: str = "union",
        color: bool = True,
    ) -> None:
        self.detector = detector or ConflictDetector()
        self.auto_strategy = auto_strategy
        self.color = color

    @staticmethod
    def _is_tty() -> bool:
        import sys
        return hasattr(sys.stdin, "isatty") and sys.stdin.isatty()

    def run(
        self,
        conflicts: dict[str, list[dict]],
        source_content: str,
    ) -> dict[str, str]:
        """Run the wizard on a dict of detected conflicts.

        Args:
            conflicts: Output from ``ConflictDetector.check_all()``.
            source_content: The Claude Code source (what HarnessSync would write).

        Returns:
            Dict mapping file_path -> resolution ('overwrite'|'merge'|'keep'|'skip').
            'overwrite' means use HarnessSync source; 'keep' means leave target unchanged.
        """
        if not self._is_tty():
            auto = SyncConflictWizard(strategy=self.auto_strategy)
            resolutions: dict[str, str] = {}
            for target_name, target_conflicts in conflicts.items():
                for conflict in target_conflicts:
                    fp = conflict.get("file_path", target_name)
                    three_way = self.detector.three_way_diff(conflict, source_content)
                    label, _ = auto.auto_resolve(three_way)
                    resolutions[fp] = label
            return resolutions

        resolutions: dict[str, str] = {}
        all_conflicts = [
            (conflict.get("file_path", target), conflict)
            for target, clist in conflicts.items()
            for conflict in clist
        ]

        if not all_conflicts:
            return resolutions

        print(f"\n{'=' * 60}")
        print(f"  HarnessSync Conflict Resolution Wizard")
        print(f"  {len(all_conflicts)} file(s) have manual edits")
        print(f"{'=' * 60}\n")

        for idx, (fp, conflict) in enumerate(all_conflicts, 1):
            print(f"\n[{idx}/{len(all_conflicts)}] {fp}")
            print("-" * 55)

            three_way = self.detector.three_way_diff(conflict, source_content)
            self._show_diff(three_way, fp)

            choice = self._prompt_choice(fp)
            resolutions[fp] = choice

        self._print_summary(resolutions)
        return resolutions

    def _show_diff(self, three_way: dict, label: str) -> None:
        """Print a side-by-side diff for the given three-way dict."""
        try:
            diff_text = self.detector.format_side_by_side_diff(
                three_way, color=self.color
            )
            print(diff_text)
        except Exception:
            # Fall back to simple unified diff
            source_lines = three_way.get("source_lines", [])
            current_lines = three_way.get("current_lines", [])
            import difflib
            diff = list(difflib.unified_diff(
                current_lines, source_lines,
                fromfile=f"{label} (current)",
                tofile=f"{label} (HarnessSync)",
                lineterm="",
            ))
            for line in diff[:60]:
                print(line)
            if len(diff) > 60:
                print(f"  ... ({len(diff) - 60} more lines)")

    def _prompt_choice(self, fp: str) -> str:
        """Ask the user to choose a resolution. Returns the resolution string."""
        prompt = (
            "  Resolution: [o]verwrite with HarnessSync source  "
            "[m]erge (union)  [k]eep manual edits  [s]kip\n"
            "  Choice [o/m/k/s, default=o]: "
        )
        try:
            raw = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled — using 'keep' for remaining files.")
            return "keep"

        if not raw:
            return "overwrite"
        return self.CHOICES.get(raw[0], "overwrite")

    def _print_summary(self, resolutions: dict[str, str]) -> None:
        """Print a one-line summary of all resolutions made."""
        print(f"\n{'─' * 55}")
        print("  Resolution summary:")
        counts: dict[str, int] = {}
        for action in resolutions.values():
            counts[action] = counts.get(action, 0) + 1
        for action, count in sorted(counts.items()):
            print(f"    {action:<12} {count} file(s)")
        print(f"{'─' * 55}\n")

        return new_content
