from __future__ import annotations

"""
Conflict resolution wizards for HarnessSync.

Contains interactive and automated conflict resolution strategies:
- ConflictResolutionWizard: Interactive TTY wizard with plain-English explanations
- SyncConflictWizard: Non-interactive strategy-based resolver for CI/CD
- TuiConflictWizard: Rich TTY wizard with side-by-side diffs
"""

import difflib
from pathlib import Path

from src.conflict_scanner import ConflictDetector


# ---------------------------------------------------------------------------
# Plain-English conflict explanation helper
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


# ---------------------------------------------------------------------------
# Interactive Conflict Resolution Wizard
# ---------------------------------------------------------------------------

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
            conflicts_by_target: Output of ConflictDetector.check_all() --
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
        print("  s) Use sync source \u2014 let HarnessSync overwrite with the Claude Code version")
        print("  k) Keep target    \u2014 preserve your manual edits, skip this file this sync")
        print("  b) Back-port      \u2014 copy your manual edits back to CLAUDE.md as the new source")
        print("  d) Show diff      \u2014 display a side-by-side diff before deciding")
        print("  ?) Skip for now   \u2014 leave this conflict unresolved (file won't be synced)")
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
                print("\nCancelled \u2014 defaulting to 'skip'.")
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
            # Nothing to back-port -- target is empty outside managed block
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

        return new_content


# ---------------------------------------------------------------------------
# Non-interactive strategy-based conflict resolver
# ---------------------------------------------------------------------------

class SyncConflictWizard:
    """Non-interactive strategy-based conflict resolver for automated pipelines.

    Unlike ``ConflictDetector.resolve_interactive()``, this wizard resolves
    conflicts programmatically using a named strategy -- suitable for CI/CD
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
        Alias for ``"ours"`` -- HarnessSync source is always considered newer.

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
                "synced": "\u2192 overwrite with HarnessSync version",
                "keep":   "\u2192 keep manual edits, skip sync",
                "merged": "\u2192 merge (source first, novel target lines appended)",
            }.get(label, f"\u2192 {label}")
            lines.append(f"  {fp}  {action}")
        lines.append("")
        lines.append(f"Total: {len(three_ways)} file(s) to resolve.")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# TUI Conflict Resolution Wizard
# ---------------------------------------------------------------------------

class TuiConflictWizard:
    """TTY-based interactive conflict resolution wizard with side-by-side diff.

    When a target file has been manually edited since the last sync, this
    wizard surfaces a rich diff showing:
      LEFT  = Claude Code source (what HarnessSync would write)
      RIGHT = Target file (what the user manually edited)

    The user picks per-file: [o]verwrite, [m]erge (union), [k]eep, [s]kip.

    Works with or without a TTY -- falls back to the non-interactive
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
            print("\n  Cancelled \u2014 using 'keep' for remaining files.")
            return "keep"

        if not raw:
            return "overwrite"
        return self.CHOICES.get(raw[0], "overwrite")

    def _print_summary(self, resolutions: dict[str, str]) -> None:
        """Print a one-line summary of all resolutions made."""
        sep = "\u2500" * 55
        print(f"\n{sep}")
        print("  Resolution summary:")
        counts: dict[str, int] = {}
        for action in resolutions.values():
            counts[action] = counts.get(action, 0) + 1
        for action, count in sorted(counts.items()):
            print(f"    {action:<12} {count} file(s)")
        print(f"{sep}\n")
