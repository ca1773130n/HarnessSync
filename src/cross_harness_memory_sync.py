from __future__ import annotations

"""Cross-Harness Shared Memory Sync (item 24).

Syncs Claude Code's memory files (.claude/memory/) to equivalent persistent
context mechanisms in other harnesses.  When a user accumulates project
knowledge in Claude Code — user preferences, project context, working notes —
this module ensures that knowledge is available when they switch to another
harness mid-session.

Target harness memory equivalents:
  gemini:    ~/.gemini/context.md (appended as a named section)
  codex:     ~/.codex/memory.md (appended as a named section)
  opencode:  ~/.opencode/memory.md (appended as a named section)
  windsurf:  .windsurf/memories/<name>.md (one file per memory)
  cursor:    .cursor/rules/memory.mdc (bundled as an always-apply rule)
  aider:     read into .aider.conf.yml read_files list (reference only)
  cline:     .roo/memory/<name>.md (one file per memory)
  continue:  .continue/rules/memory.md (bundled)
  zed:       .rules (appended section)
  neovim:    .avante/memory.md (appended section)

Memory file discovery:
  Claude Code stores memory files in:
    ~/.claude/memory/         — user-scoped memories
    <project>/.claude/memory/ — project-scoped memories

  Each file is a Markdown document with an optional YAML frontmatter block.
  The filename (without extension) is used as the memory name.

Usage::

    from src.cross_harness_memory_sync import CrossHarnessMemorySync

    syncer = CrossHarnessMemorySync(project_dir=Path("."))
    results = syncer.sync_to_all()
    for r in results:
        print(r.format())
"""

import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


# ── Constants ────────────────────────────────────────────────────────────────

_MANAGED_START = "<!-- hs:memory-start -->"
_MANAGED_END = "<!-- hs:memory-end -->"
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# Maximum number of memory files to sync (prevents unbounded context growth)
_MAX_MEMORIES = 50

# Maximum size of a single memory file content to sync (bytes)
_MAX_MEMORY_SIZE = 32_768  # 32 KB


# ── Data types ───────────────────────────────────────────────────────────────

@dataclass
class MemoryFile:
    """A single Claude Code memory file."""

    name: str           # Logical name (filename without extension)
    path: Path          # Absolute path to the file
    content: str        # File content (stripped of frontmatter)
    scope: str          # "user" | "project"
    modified_at: str    # ISO 8601 modification timestamp


@dataclass
class MemorySyncResult:
    """Result of syncing memories to a single target harness."""

    target: str
    synced_count: int
    skipped_count: int
    target_path: str
    error: str = ""
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.error

    def format(self) -> str:
        mode = " [DRY RUN]" if self.dry_run else ""
        if self.error:
            return f"  {self.target}: ERROR — {self.error}"
        return (
            f"  {self.target}{mode}: {self.synced_count} memories → {self.target_path}"
            + (f" ({self.skipped_count} skipped)" if self.skipped_count else "")
        )


# ── Memory discovery ─────────────────────────────────────────────────────────

def _strip_frontmatter(content: str) -> str:
    """Remove YAML frontmatter block from memory file content."""
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            return content[end + 4:].lstrip("\n")
    return content


def _read_memory_dir(memory_dir: Path, scope: str) -> list[MemoryFile]:
    """Read all .md memory files from a directory."""
    if not memory_dir.is_dir():
        return []
    memories: list[MemoryFile] = []
    for path in sorted(memory_dir.glob("*.md")):
        if len(memories) >= _MAX_MEMORIES:
            break
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(raw.encode("utf-8")) > _MAX_MEMORY_SIZE:
            continue
        content = _strip_frontmatter(raw).strip()
        if not content:
            continue
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        memories.append(MemoryFile(
            name=path.stem,
            path=path,
            content=content,
            scope=scope,
            modified_at=mtime.strftime(_TIMESTAMP_FORMAT),
        ))
    return memories


def discover_memories(
    project_dir: Path,
    cc_home: Path | None = None,
) -> list[MemoryFile]:
    """Discover Claude Code memory files for a project.

    Searches both user-scoped (~/.claude/memory/) and project-scoped
    (.claude/memory/ in project_dir) locations.

    Args:
        project_dir: Project root directory.
        cc_home: Custom Claude Code home directory (default: ~/.claude/).

    Returns:
        List of MemoryFile objects, project-scoped first, then user-scoped.
    """
    cc_home = cc_home or (Path.home() / ".claude")
    memories: list[MemoryFile] = []
    # Project-scoped memories take priority (listed first)
    memories.extend(_read_memory_dir(project_dir / ".claude" / "memory", "project"))
    memories.extend(_read_memory_dir(cc_home / "memory", "user"))
    return memories


# ── Content builders ─────────────────────────────────────────────────────────

def _build_managed_block(memories: list[MemoryFile], title: str = "Shared Memory") -> str:
    """Build the managed content block that will be injected into target files."""
    now = datetime.now(tz=timezone.utc).strftime(_TIMESTAMP_FORMAT)
    lines: list[str] = [
        _MANAGED_START,
        f"<!-- hs:memory-synced-at={now} count={len(memories)} -->",
        "",
        f"## {title}",
        "",
        "> *Synced from Claude Code memory by HarnessSync. Do not edit — changes*",
        "> *will be overwritten on next sync.*",
        "",
    ]
    for mem in memories:
        lines.append(f"### {mem.name} ({mem.scope})")
        lines.append("")
        lines.append(mem.content)
        lines.append("")
    lines.append(_MANAGED_END)
    return "\n".join(lines)


def _inject_or_update_managed_block(existing: str, new_block: str) -> str:
    """Replace or append the managed memory block in an existing file."""
    if _MANAGED_START in existing and _MANAGED_END in existing:
        start_idx = existing.index(_MANAGED_START)
        end_idx = existing.index(_MANAGED_END) + len(_MANAGED_END)
        return existing[:start_idx] + new_block + existing[end_idx:]
    # Append with a separator
    return existing.rstrip("\n") + "\n\n" + new_block + "\n"


# ── Target-specific writers ──────────────────────────────────────────────────

def _write_appended_section(
    target_path: Path,
    memories: list[MemoryFile],
    title: str = "Shared Memory",
    dry_run: bool = False,
) -> None:
    """Write memories as a managed section appended to a single Markdown file."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    existing = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
    new_block = _build_managed_block(memories, title)
    updated = _inject_or_update_managed_block(existing, new_block)
    if not dry_run:
        target_path.write_text(updated, encoding="utf-8")


def _write_per_file_memories(
    target_dir: Path,
    memories: list[MemoryFile],
    dry_run: bool = False,
) -> None:
    """Write each memory as a separate file in a target directory."""
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=True)
    for mem in memories:
        file_path = target_dir / f"hs-memory-{mem.name}.md"
        content = (
            f"<!-- hs:memory name='{mem.name}' scope='{mem.scope}' "
            f"synced='{mem.modified_at}' -->\n\n"
            f"{mem.content}\n"
        )
        if not dry_run:
            file_path.write_text(content, encoding="utf-8")


def _write_aider_read_files(
    project_dir: Path,
    memories: list[MemoryFile],
    dry_run: bool = False,
) -> str:
    """Add memory files to .aider.conf.yml read_files list.

    Returns the path written (or that would be written in dry-run).
    """
    import yaml as _yaml  # type: ignore[import]

    conf_path = project_dir / ".aider.conf.yml"
    conf: dict = {}
    if conf_path.exists():
        try:
            conf = _yaml.safe_load(conf_path.read_text(encoding="utf-8")) or {}
        except Exception:
            conf = {}

    read_files: list[str] = list(conf.get("read-files", []) or [])

    # Write memory content to a sidecar file and add to read_files
    sidecar = project_dir / ".aider-hs-memory.md"
    sidecar_str = str(sidecar)
    block = _build_managed_block(memories, title="HarnessSync Memory")
    if not dry_run:
        sidecar.write_text(block, encoding="utf-8")
        if sidecar_str not in read_files:
            read_files.append(sidecar_str)
        conf["read-files"] = read_files
        with conf_path.open("w", encoding="utf-8") as f:
            _yaml.dump(conf, f, default_flow_style=False, allow_unicode=True)

    return str(sidecar)


def _write_cursor_mdc(
    project_dir: Path,
    memories: list[MemoryFile],
    dry_run: bool = False,
) -> Path:
    """Write memories as an always-apply .mdc rule file for Cursor."""
    rules_dir = project_dir / ".cursor" / "rules"
    mdc_path = rules_dir / "hs-memory.mdc"
    frontmatter = "---\nalwaysApply: true\ndescription: HarnessSync shared memory\n---\n\n"
    content = frontmatter + _build_managed_block(memories, title="Shared Memory")
    if not dry_run:
        rules_dir.mkdir(parents=True, exist_ok=True)
        mdc_path.write_text(content, encoding="utf-8")
    return mdc_path


# ── Main syncer ──────────────────────────────────────────────────────────────

class CrossHarnessMemorySync:
    """Sync Claude Code memory files to all configured target harnesses.

    Args:
        project_dir: Project root directory.
        cc_home: Custom Claude Code home directory.
        dry_run: If True, compute results but do not write files.
    """

    def __init__(
        self,
        project_dir: Path,
        cc_home: Path | None = None,
        dry_run: bool = False,
    ) -> None:
        self.project_dir = project_dir
        self.cc_home = cc_home or (Path.home() / ".claude")
        self.dry_run = dry_run

    def sync_to_all(self) -> list[MemorySyncResult]:
        """Sync memories to all supported target harnesses.

        Returns:
            List of MemorySyncResult, one per target.
        """
        memories = discover_memories(self.project_dir, self.cc_home)
        if not memories:
            return []

        results: list[MemorySyncResult] = []
        for target, writer in self._target_writers().items():
            result = writer(memories)
            results.append(result)
        return results

    def sync_to_target(self, target: str) -> MemorySyncResult:
        """Sync memories to a specific target harness.

        Args:
            target: Target harness name.

        Returns:
            MemorySyncResult for the target.
        """
        memories = discover_memories(self.project_dir, self.cc_home)
        writers = self._target_writers()
        if target not in writers:
            return MemorySyncResult(
                target=target,
                synced_count=0,
                skipped_count=0,
                target_path="",
                error=f"Target '{target}' is not supported for memory sync.",
            )
        return writers[target](memories)

    def _target_writers(self) -> dict:
        """Return a mapping of target name → writer callable."""
        pd = self.project_dir
        dry = self.dry_run

        def _gemini(memories: list[MemoryFile]) -> MemorySyncResult:
            path = Path.home() / ".gemini" / "context.md"
            try:
                _write_appended_section(path, memories, "Shared Memory from Claude Code", dry)
                return MemorySyncResult("gemini", len(memories), 0, str(path), dry_run=dry)
            except Exception as e:
                return MemorySyncResult("gemini", 0, len(memories), str(path), error=str(e), dry_run=dry)

        def _codex(memories: list[MemoryFile]) -> MemorySyncResult:
            path = Path.home() / ".codex" / "memory.md"
            try:
                _write_appended_section(path, memories, "Shared Memory from Claude Code", dry)
                return MemorySyncResult("codex", len(memories), 0, str(path), dry_run=dry)
            except Exception as e:
                return MemorySyncResult("codex", 0, len(memories), str(path), error=str(e), dry_run=dry)

        def _opencode(memories: list[MemoryFile]) -> MemorySyncResult:
            path = Path.home() / ".opencode" / "memory.md"
            try:
                _write_appended_section(path, memories, "Shared Memory from Claude Code", dry)
                return MemorySyncResult("opencode", len(memories), 0, str(path), dry_run=dry)
            except Exception as e:
                return MemorySyncResult("opencode", 0, len(memories), str(path), error=str(e), dry_run=dry)

        def _windsurf(memories: list[MemoryFile]) -> MemorySyncResult:
            mem_dir = pd / ".windsurf" / "memories"
            try:
                _write_per_file_memories(mem_dir, memories, dry)
                return MemorySyncResult("windsurf", len(memories), 0, str(mem_dir), dry_run=dry)
            except Exception as e:
                return MemorySyncResult("windsurf", 0, len(memories), str(mem_dir), error=str(e), dry_run=dry)

        def _cursor(memories: list[MemoryFile]) -> MemorySyncResult:
            try:
                mdc_path = _write_cursor_mdc(pd, memories, dry)
                return MemorySyncResult("cursor", len(memories), 0, str(mdc_path), dry_run=dry)
            except Exception as e:
                return MemorySyncResult("cursor", 0, len(memories), "", error=str(e), dry_run=dry)

        def _aider(memories: list[MemoryFile]) -> MemorySyncResult:
            try:
                import yaml  # noqa: F401
                sidecar = _write_aider_read_files(pd, memories, dry)
                return MemorySyncResult("aider", len(memories), 0, sidecar, dry_run=dry)
            except ImportError:
                # yaml not installed — skip aider
                return MemorySyncResult(
                    "aider", 0, len(memories), "",
                    error="PyYAML not installed; aider memory sync skipped.",
                    dry_run=dry,
                )
            except Exception as e:
                return MemorySyncResult("aider", 0, len(memories), "", error=str(e), dry_run=dry)

        def _cline(memories: list[MemoryFile]) -> MemorySyncResult:
            mem_dir = pd / ".roo" / "memory"
            try:
                _write_per_file_memories(mem_dir, memories, dry)
                return MemorySyncResult("cline", len(memories), 0, str(mem_dir), dry_run=dry)
            except Exception as e:
                return MemorySyncResult("cline", 0, len(memories), str(mem_dir), error=str(e), dry_run=dry)

        def _continue(memories: list[MemoryFile]) -> MemorySyncResult:
            path = pd / ".continue" / "rules" / "hs-memory.md"
            try:
                _write_appended_section(path, memories, "Shared Memory", dry)
                return MemorySyncResult("continue", len(memories), 0, str(path), dry_run=dry)
            except Exception as e:
                return MemorySyncResult("continue", 0, len(memories), str(path), error=str(e), dry_run=dry)

        def _zed(memories: list[MemoryFile]) -> MemorySyncResult:
            path = pd / ".rules"
            try:
                _write_appended_section(path, memories, "Shared Memory", dry)
                return MemorySyncResult("zed", len(memories), 0, str(path), dry_run=dry)
            except Exception as e:
                return MemorySyncResult("zed", 0, len(memories), str(path), error=str(e), dry_run=dry)

        def _neovim(memories: list[MemoryFile]) -> MemorySyncResult:
            path = pd / ".avante" / "memory.md"
            try:
                _write_appended_section(path, memories, "Shared Memory", dry)
                return MemorySyncResult("neovim", len(memories), 0, str(path), dry_run=dry)
            except Exception as e:
                return MemorySyncResult("neovim", 0, len(memories), str(path), error=str(e), dry_run=dry)

        return {
            "gemini": _gemini,
            "codex": _codex,
            "opencode": _opencode,
            "windsurf": _windsurf,
            "cursor": _cursor,
            "aider": _aider,
            "cline": _cline,
            "continue": _continue,
            "zed": _zed,
            "neovim": _neovim,
        }

    def format_summary(self, results: list[MemorySyncResult]) -> str:
        """Format sync results as a human-readable summary."""
        if not results:
            return "No memories found to sync."
        lines = [
            f"Memory Sync Results ({sum(r.synced_count for r in results)} synced across "
            f"{len(results)} harnesses):",
        ]
        for r in results:
            lines.append(r.format())
        return "\n".join(lines)

    def diff_memories(
        self,
        target: str,
        target_path: Path,
    ) -> list[dict]:
        """Compare Claude Code memory files against the synced content in a target.

        Returns a list of diff entries showing which memories are new, changed,
        or unchanged in the target harness.  Helps users understand what will
        be overwritten before running a full memory sync.

        Args:
            target: Target harness name (e.g. "gemini").
            target_path: Path to the target harness's memory file/directory.

        Returns:
            List of dicts with keys: ``name``, ``status`` (new/changed/unchanged),
            ``source_snippet`` (first 80 chars), ``target_snippet``.
        """
        source_memories = self._discover_memories()
        if not source_memories:
            return []

        diffs: list[dict] = []

        if target_path.is_file():
            try:
                target_content = target_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                target_content = ""
        else:
            target_content = ""

        for mem in source_memories:
            snippet = mem.content[:80].replace("\n", " ").strip()
            in_target = mem.name in target_content or snippet[:40] in target_content
            status = "unchanged" if in_target else ("new" if not target_content else "changed")
            diffs.append({
                "name": mem.name,
                "status": status,
                "source_snippet": snippet,
                "target_snippet": (target_content[:80].replace("\n", " ").strip() if not in_target else snippet),
            })

        return diffs

    def format_diff_summary(self, diffs: list[dict]) -> str:
        """Format memory diff results for terminal display.

        Args:
            diffs: List of diff dicts from :meth:`diff_memories`.

        Returns:
            Human-readable diff summary string.
        """
        if not diffs:
            return "No memory differences found."

        new = [d for d in diffs if d["status"] == "new"]
        changed = [d for d in diffs if d["status"] == "changed"]
        unchanged = [d for d in diffs if d["status"] == "unchanged"]

        lines = [
            "Memory Sync Diff Preview",
            "=" * 50,
            f"  New:       {len(new)}",
            f"  Changed:   {len(changed)}",
            f"  Unchanged: {len(unchanged)}",
            "",
        ]

        for d in new:
            lines.append(f"  + [{d['name']}] {d['source_snippet'][:60]}")
        for d in changed:
            lines.append(f"  ~ [{d['name']}] {d['source_snippet'][:60]}")

        if unchanged and len(unchanged) <= 5:
            for d in unchanged:
                lines.append(f"  = [{d['name']}] (no change)")

        lines.append("")
        lines.append("Run /sync-memory to apply these changes to target harnesses.")
        return "\n".join(lines)
