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

        Shows the diff between (last-synced → current) and (last-synced → source)
        and offers per-file choices:
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
        import sys
        import tempfile

        file_path = three_way["file_path"]
        source_lines = three_way["source_lines"]
        current_lines = three_way["current_lines"]
        diff_source_vs_current = three_way["unified_source_vs_current"]
        diff_base_vs_current = three_way["unified_base_vs_current"]

        print(f"\n{'=' * 70}")
        print(f"THREE-WAY CONFLICT: {file_path}")
        print(f"{'=' * 70}")

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
