from __future__ import annotations

"""Per-harness override layer.

Reads override files from ``~/.claude/overrides/<harness>.md`` and appends
them to the canonical rules content *before* sync.  This lets users tune
per-harness instructions (e.g. shorter Codex prompts, extra Gemini flags)
without duplicating the base config.

Override files use the same CLAUDE.md format.  They are appended after the
canonical content with a clearly labelled section header so the boundary is
visible in the target harness.

Override directory layout::

    ~/.claude/overrides/
        codex.md          # appended only to Codex sync
        gemini.md         # appended only to Gemini sync
        cursor.md         # appended only to Cursor sync
        ...

A project-scoped override can also live at
``<project>/.claude/overrides/<harness>.md`` and is merged *after* the user-
scope override (project wins).

Usage (in Orchestrator or adapters)::

    overrides = HarnessOverrides(cc_home=Path.home() / ".claude",
                                 project_dir=Path.cwd())
    merged = overrides.apply(rules_content, target="codex")
"""

from dataclasses import dataclass, field
from pathlib import Path


_OVERRIDE_HEADER = "\n\n<!-- harness-override: {target} -->\n"
_OVERRIDE_FOOTER = "\n<!-- /harness-override: {target} -->\n"


@dataclass
class OverrideSource:
    """A single override file with its origin label."""

    path: Path
    scope: str  # "user" or "project"
    content: str = field(default="", repr=False)


class HarnessOverrides:
    """Loads and applies per-harness override files."""

    def __init__(
        self,
        cc_home: Path | None = None,
        project_dir: Path | None = None,
    ) -> None:
        self._cc_home = cc_home or (Path.home() / ".claude")
        self._project_dir = project_dir

    # ── Public API ────────────────────────────────────────────────────────────

    def apply(self, base_content: str, target: str) -> str:
        """Return *base_content* with any override for *target* appended.

        If no override file exists the original content is returned unchanged.
        """
        sources = self._load_overrides(target)
        if not sources:
            return base_content

        parts = [base_content]
        for src in sources:
            parts.append(
                _OVERRIDE_HEADER.format(target=target)
                + src.content.strip()
                + _OVERRIDE_FOOTER.format(target=target)
            )
        return "".join(parts)

    def list_overrides(self) -> dict[str, list[OverrideSource]]:
        """Return all discovered override files keyed by harness name."""
        results: dict[str, list[OverrideSource]] = {}
        for scope, base in self._override_dirs():
            if not base.is_dir():
                continue
            for f in sorted(base.glob("*.md")):
                target = f.stem.lower()
                src = OverrideSource(path=f, scope=scope)
                try:
                    src.content = f.read_text(encoding="utf-8")
                except OSError:
                    continue
                results.setdefault(target, []).append(src)
        return results

    def get_override(self, target: str) -> str:
        """Return combined override text for *target*, or empty string."""
        sources = self._load_overrides(target)
        if not sources:
            return ""
        return "\n\n".join(s.content.strip() for s in sources if s.content.strip())

    def set_override(self, target: str, content: str, scope: str = "user") -> Path:
        """Write an override file for *target*.

        Args:
            target:  Harness name (e.g. ``"codex"``).
            content: Override content (raw CLAUDE.md text).
            scope:   ``"user"`` (default) or ``"project"``.

        Returns:
            Path to the written file.
        """
        base = self._override_dir_for_scope(scope)
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{target}.md"
        path.write_text(content, encoding="utf-8")
        return path

    def delete_override(self, target: str, scope: str = "user") -> bool:
        """Delete the override file for *target*.  Returns True if deleted."""
        base = self._override_dir_for_scope(scope)
        path = base / f"{target}.md"
        if path.exists():
            path.unlink()
            return True
        return False

    def format_summary(self) -> str:
        """Return a human-readable summary of all configured overrides."""
        overrides = self.list_overrides()
        if not overrides:
            return "No per-harness overrides configured.\n"
        lines = ["Per-harness overrides:", ""]
        for target in sorted(overrides):
            sources = overrides[target]
            for src in sources:
                size = len(src.content)
                lines.append(f"  [{src.scope:7s}] {target:12s}  {src.path}  ({size} chars)")
        lines.append(
            f"\nTotal: {len(overrides)} harness(es) with overrides."
        )
        return "\n".join(lines)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _override_dirs(self) -> list[tuple[str, Path]]:
        dirs = [("user", self._cc_home / "overrides")]
        if self._project_dir:
            dirs.append(("project", self._project_dir / ".claude" / "overrides"))
        return dirs

    def _override_dir_for_scope(self, scope: str) -> Path:
        if scope == "project" and self._project_dir:
            return self._project_dir / ".claude" / "overrides"
        return self._cc_home / "overrides"

    def _load_overrides(self, target: str) -> list[OverrideSource]:
        sources: list[OverrideSource] = []
        for scope, base in self._override_dirs():
            path = base / f"{target}.md"
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if content:
                sources.append(OverrideSource(path=path, scope=scope, content=content))
        return sources
