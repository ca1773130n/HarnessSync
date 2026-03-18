from __future__ import annotations

"""Skill Transpiler — convert Claude Code skills to target-harness formats.

Claude Code skills are Markdown files with YAML frontmatter that describe
reusable behaviours.  This module converts them to the closest equivalent
in each target harness, preserving intent even when the format differs.

Supported output formats:
  gemini   → Plain-text system-instruction block (GEMINI.md section)
  codex    → AGENTS.md instruction block
  opencode → AGENTS.md-style markdown instruction block
  cursor   → .cursor/rules/<skill-name>.mdc  (with frontmatter)
  aider    → CONVENTIONS.md section
  windsurf → .windsurfrules section (plain markdown)
  cline    → .clinerules section
  default  → Generic markdown block (used by vscode, continue, zed, neovim)

Usage::

    transpiler = SkillTranspiler()

    # Single skill from a Path:
    result = transpiler.transpile_skill(Path("skills/commit/SKILL.md"), target="gemini")
    print(result.output)

    # All skills in a directory:
    results = transpiler.transpile_all(skills_dir, target="codex")
    for r in results:
        print(r.skill_name, r.fidelity, r.output)
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TranspileResult:
    """Result of transpiling a single skill to a target format."""

    skill_name: str
    target: str
    output: str          # Transpiled content ready to write/append
    fidelity: float      # 0.0–1.0; how well the intent is preserved
    warnings: list[str] = field(default_factory=list)

    def format_summary(self) -> str:
        pct = round(self.fidelity * 100)
        warn_str = f"  Warnings: {'; '.join(self.warnings)}" if self.warnings else ""
        return f"[{self.target}] {self.skill_name}: {pct}% fidelity{warn_str}"


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------

def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from a skill Markdown file.

    Returns:
        (meta, body) where meta is a simple key→value dict (no nested YAML
        parsing — only scalar values are needed for skill frontmatter) and
        body is the Markdown text after the closing ``---``.
    """
    meta: dict[str, str] = {}
    body = content
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            fm_text = content[3:end].strip()
            body = content[end + 4:].strip()
            for line in fm_text.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def _strip_html_comments(text: str) -> str:
    """Remove HTML comment blocks (e.g. <!-- harness:codex --> annotations)."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()


def _first_paragraph(body: str) -> str:
    """Return the first non-empty paragraph from skill body text."""
    for para in body.split("\n\n"):
        para = para.strip()
        if para and not para.startswith("#"):
            return para
    return body.strip()[:500]


def _rewrite_tool_refs(body: str, target: str) -> tuple[str, list[str]]:
    """Replace Claude Code tool names with target-appropriate alternatives.

    Returns:
        (rewritten_body, warnings)
    """
    warnings: list[str] = []

    # Map Claude Code tool names → natural-language equivalents per target
    _TOOL_MAP = {
        "Bash": {"aider": "run shell commands", "default": "execute commands"},
        "Read": {"aider": "read the file", "default": "read the file"},
        "Write": {"aider": "write to a file", "default": "write to the file"},
        "Edit": {"aider": "modify the file", "default": "edit the file"},
        "Glob": {"default": "search for files matching the pattern"},
        "Grep": {"default": "search file contents"},
        "Agent": {"default": "spawn a sub-task"},
        "TodoWrite": {
            "aider": "maintain a TODO.md file",
            "default": "track tasks in a TODO list",
        },
        "WebFetch": {"default": "fetch the URL"},
        "WebSearch": {"default": "search the web"},
    }

    result = body
    for tool_name, replacements in _TOOL_MAP.items():
        replacement = replacements.get(target) or replacements.get("default", tool_name)
        # Only replace when used as a tool reference (e.g. "Use the Bash tool")
        pattern = rf"\bthe\s+{re.escape(tool_name)}\s+tool\b"
        if re.search(pattern, result, re.IGNORECASE):
            result = re.sub(pattern, f"the '{replacement}' approach", result, flags=re.IGNORECASE)
        # Also handle bare "Bash tool" without "the"
        pattern2 = rf"\b{re.escape(tool_name)}\s+tool\b"
        if re.search(pattern2, result, re.IGNORECASE):
            result = re.sub(pattern2, f"'{replacement}'", result, flags=re.IGNORECASE)
        # Hook event names
        for hook in ("PostToolUse", "PreToolUse", "UserPromptSubmit", "SessionStart", "SessionEnd"):
            if hook in result:
                result = result.replace(hook, f"[CC-hook:{hook}]")
                warnings.append(
                    f"Hook event '{hook}' not available in {target} — "
                    "remove or adapt manually"
                )

    return result, warnings


# ---------------------------------------------------------------------------
# Format renderers
# ---------------------------------------------------------------------------

def _render_gemini(meta: dict, body: str, skill_name: str) -> tuple[str, float, list[str]]:
    """Render skill as a GEMINI.md system-instruction section."""
    body, warnings = _rewrite_tool_refs(body, "gemini")
    title = meta.get("name") or skill_name.replace("-", " ").replace("_", " ").title()
    description = meta.get("description", "")
    output_lines = [f"## {title}"]
    if description:
        output_lines.append(f"> {description}")
        output_lines.append("")
    output_lines.append(body)
    fidelity = 0.8 if not warnings else 0.65
    return "\n".join(output_lines), fidelity, warnings


def _render_codex(meta: dict, body: str, skill_name: str) -> tuple[str, float, list[str]]:
    """Render skill as an AGENTS.md instruction block."""
    body, warnings = _rewrite_tool_refs(body, "codex")
    title = meta.get("name") or skill_name.replace("-", " ").replace("_", " ").title()
    description = meta.get("description", "")
    trigger = meta.get("trigger", "")
    output_lines = [f"### {title}"]
    if description:
        output_lines.append(f"<!-- Skill: {description} -->")
    if trigger:
        output_lines.append(f"<!-- Trigger: {trigger} -->")
    output_lines.append("")
    output_lines.append(body)
    fidelity = 0.65 if not warnings else 0.50
    return "\n".join(output_lines), fidelity, warnings


def _render_cursor(meta: dict, body: str, skill_name: str) -> tuple[str, float, list[str]]:
    """Render skill as a Cursor .mdc rule file."""
    body, warnings = _rewrite_tool_refs(body, "cursor")
    description = meta.get("description", "")
    globs = meta.get("globs", "**/*")
    always_apply = meta.get("alwaysApply", "false")
    fm_lines = [
        "---",
        f"description: {description}",
        f"globs: {globs}",
        f"alwaysApply: {always_apply}",
        "---",
        "",
    ]
    fidelity = 0.80 if not warnings else 0.65
    return "\n".join(fm_lines) + body, fidelity, warnings


def _render_aider(meta: dict, body: str, skill_name: str) -> tuple[str, float, list[str]]:
    """Render skill as a CONVENTIONS.md section (Aider)."""
    body, warnings = _rewrite_tool_refs(body, "aider")
    title = meta.get("name") or skill_name.replace("-", " ").replace("_", " ").title()
    description = meta.get("description", "")
    # Aider reads CONVENTIONS.md as plain text — keep Markdown headings
    output_lines = [f"## {title}"]
    if description:
        output_lines.append(f"*{description}*")
        output_lines.append("")
    output_lines.append(body)
    # Skills are text-only in Aider; tool calls stripped → reduced fidelity
    warnings.append(
        "Aider has no skill execution — content folded into CONVENTIONS.md as instructions"
    )
    fidelity = 0.45
    return "\n".join(output_lines), fidelity, warnings


def _render_windsurf(meta: dict, body: str, skill_name: str) -> tuple[str, float, list[str]]:
    """Render skill as a .windsurfrules section."""
    body, warnings = _rewrite_tool_refs(body, "windsurf")
    title = meta.get("name") or skill_name.replace("-", " ").replace("_", " ").title()
    output_lines = [f"## {title}", ""]
    output_lines.append(body)
    fidelity = 0.60 if not warnings else 0.50
    return "\n".join(output_lines), fidelity, warnings


def _render_default(meta: dict, body: str, skill_name: str, target: str) -> tuple[str, float, list[str]]:
    """Generic markdown block (vscode, continue, cline, zed, neovim, opencode)."""
    body, warnings = _rewrite_tool_refs(body, target)
    title = meta.get("name") or skill_name.replace("-", " ").replace("_", " ").title()
    output_lines = [f"## {title}", ""]
    output_lines.append(body)
    fidelity = 0.60 if not warnings else 0.50
    return "\n".join(output_lines), fidelity, warnings


# ---------------------------------------------------------------------------
# Capability stub generation (item 28)
# ---------------------------------------------------------------------------

# Harnesses that cannot execute Claude Code skills natively
_NO_SKILL_SUPPORT: frozenset[str] = frozenset({"neovim", "vscode", "continue", "cline", "zed"})

# Harnesses that have partial skill support (transpile with low fidelity)
_PARTIAL_SKILL_SUPPORT: frozenset[str] = frozenset(
    {"codex", "gemini", "opencode", "windsurf", "aider", "cursor"}
)


def generate_capability_stub(skill_name: str, target: str, invoke_hint: str = "") -> str:
    """Generate a capability-gap stub for harnesses that cannot run a skill.

    When a Claude Code skill has no equivalent in a target harness, this
    function produces a short notice block that:
    - Informs the user that the skill is not available in the harness
    - Provides an actionable redirect (e.g. "switch to Claude Code")
    - Preserves discoverability so the gap is visible instead of silent

    The stub is suitable for embedding in the harness's instruction file
    (AGENTS.md, GEMINI.md, .aider.conf.yml, etc.).

    Args:
        skill_name:  The Claude Code skill identifier (e.g. ``"commit"``).
        target:      Target harness name (e.g. ``"neovim"``).
        invoke_hint: Optional custom message shown when users try to invoke
                     the skill.  Defaults to a generic redirect message.

    Returns:
        A short Markdown string to embed in the harness config.  Returns an
        empty string if the target is known to support skills natively.
    """
    # Full-support targets don't need stubs
    if target in _PARTIAL_SKILL_SUPPORT:
        return ""

    display = skill_name.replace("-", " ").replace("_", " ").title()
    default_hint = (
        f"This skill requires Claude Code — run `claude /{skill_name}` for best results."
    )
    message = invoke_hint or default_hint

    return (
        f"<!-- skill-stub:{skill_name} -->\n"
        f"> **/{display}** is a Claude Code skill not available in {target}.\n"
        f"> {message}\n"
        f"<!-- /skill-stub:{skill_name} -->"
    )


def generate_all_stubs(
    skills: dict[str, str],
    target: str,
) -> dict[str, str]:
    """Generate capability stubs for all skills that lack native support.

    Args:
        skills: Dict mapping skill_name -> skill content (or any truthy value).
        target: Target harness name.

    Returns:
        Dict mapping skill_name -> stub string.  Only includes skills where
        a stub is appropriate (i.e. target has no native skill support).
    """
    return {
        name: stub
        for name in skills
        if (stub := generate_capability_stub(name, target))
    }


# ---------------------------------------------------------------------------
# Main transpiler class
# ---------------------------------------------------------------------------

class SkillTranspiler:
    """Convert Claude Code skills to target-harness-native formats.

    Preserves the intent of each skill even when the exact format differs.
    Claude-Code-specific constructs (tool names, hook events, MCP calls) are
    rewritten to natural-language equivalents or flagged with warnings.

    Usage::

        t = SkillTranspiler()
        result = t.transpile_skill(Path("skills/commit/SKILL.md"), "gemini")
        print(result.output)
    """

    _RENDERERS = {
        "gemini": _render_gemini,
        "codex": _render_codex,
        "opencode": _render_codex,   # same format as Codex AGENTS.md
        "cursor": _render_cursor,
        "aider": _render_aider,
        "windsurf": _render_windsurf,
    }

    def transpile_skill(self, skill_path: Path, target: str) -> TranspileResult:
        """Transpile a single skill file to the target harness format.

        Args:
            skill_path: Path to the SKILL.md file (or directory containing it).
            target: Target harness name (e.g. "gemini", "codex", "aider").

        Returns:
            TranspileResult with output text and fidelity score.
        """
        if skill_path.is_dir():
            skill_path = skill_path / "SKILL.md"

        skill_name = skill_path.parent.name if skill_path.name == "SKILL.md" else skill_path.stem

        if not skill_path.is_file():
            return TranspileResult(
                skill_name=skill_name,
                target=target,
                output="",
                fidelity=0.0,
                warnings=[f"Skill file not found: {skill_path}"],
            )

        try:
            raw = skill_path.read_text(encoding="utf-8")
        except OSError as exc:
            return TranspileResult(
                skill_name=skill_name,
                target=target,
                output="",
                fidelity=0.0,
                warnings=[f"Could not read {skill_path}: {exc}"],
            )

        meta, body = _parse_frontmatter(raw)
        body = _strip_html_comments(body)

        renderer = self._RENDERERS.get(target)
        if renderer:
            output, fidelity, warnings = renderer(meta, body, skill_name)
        else:
            output, fidelity, warnings = _render_default(meta, body, skill_name, target)

        return TranspileResult(
            skill_name=skill_name,
            target=target,
            output=output,
            fidelity=fidelity,
            warnings=warnings,
        )

    def transpile_all(
        self,
        skills_dir: Path,
        target: str,
    ) -> list[TranspileResult]:
        """Transpile all SKILL.md files found under *skills_dir*.

        Args:
            skills_dir: Directory containing skill subdirectories.
            target: Target harness name.

        Returns:
            List of TranspileResult, one per skill found.
        """
        results: list[TranspileResult] = []
        if not skills_dir.is_dir():
            return results

        # Support both flat (skills/SKILL.md) and nested (skills/foo/SKILL.md)
        for skill_md in sorted(skills_dir.rglob("SKILL.md")):
            results.append(self.transpile_skill(skill_md, target))

        return results

    def transpile_all_targets(
        self,
        skills_dir: Path,
        targets: list[str] | None = None,
    ) -> dict[str, list[TranspileResult]]:
        """Transpile all skills to every target harness.

        Args:
            skills_dir: Directory containing skill subdirectories.
            targets: Harness names to transpile to. Defaults to all known targets.

        Returns:
            Dict mapping target_name → list of TranspileResult.
        """
        from src.adapters import AdapterRegistry
        resolved = targets or AdapterRegistry.list_targets()
        return {t: self.transpile_all(skills_dir, t) for t in resolved}

    def format_fidelity_table(self, results: list[TranspileResult]) -> str:
        """Render a summary table showing fidelity per skill per target.

        Args:
            results: Mixed list of TranspileResult objects (any targets).

        Returns:
            Formatted table string.
        """
        if not results:
            return "No transpile results."

        # Group by target
        by_target: dict[str, list[TranspileResult]] = {}
        for r in results:
            by_target.setdefault(r.target, []).append(r)

        lines = ["Skill Transpile Fidelity", "=" * 50]
        for target, target_results in sorted(by_target.items()):
            avg = sum(r.fidelity for r in target_results) / len(target_results)
            lines.append(f"\n  {target} (avg {round(avg * 100)}%):")
            for r in sorted(target_results, key=lambda x: x.skill_name):
                pct = round(r.fidelity * 100)
                warn_flag = " !" if r.warnings else ""
                lines.append(f"    {r.skill_name:<25} {pct:>3}%{warn_flag}")
        return "\n".join(lines)
