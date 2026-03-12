from __future__ import annotations

"""Harness Migration Assistant (item 25).

Guides users through migrating their primary AI coding harness *into* Claude Code.
Reads existing Cursor, Aider, Gemini, OpenCode, Codex, and Windsurf configurations
and maps them to Claude Code equivalents: CLAUDE.md rules, .claude/agents/,
.claude/commands/, and ~/.claude.json MCP servers.

Migration anxiety keeps users stuck in suboptimal harnesses.  This assistant:
1. Scans the project/home dirs for existing harness configs
2. Classifies each config item (rules, agents, MCP servers, settings)
3. Produces a CLAUDE.md-compatible migration proposal
4. Optionally writes the migrated files

Usage:
    from src.migration_assistant import MigrationAssistant

    assistant = MigrationAssistant(project_dir=Path("."))
    plan = assistant.scan()
    print(assistant.format_plan(plan))
    assistant.apply(plan, dry_run=False)

Or from the CLI:
    /sync-migrate --from cursor [--dry-run] [--project-dir PATH]
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MigrationItem:
    """A single config item to migrate."""
    source_harness: str
    source_file: str
    item_type: str          # "rule", "agent", "mcp_server", "setting", "command"
    original_content: str
    proposed_target: str    # Claude Code destination path (relative to project)
    proposed_content: str
    confidence: float       # 0.0–1.0; low confidence → needs manual review
    notes: str = ""


@dataclass
class MigrationPlan:
    """Complete migration plan from a source harness."""
    source_harness: str
    items: list[MigrationItem]
    skipped: list[tuple[str, str]]  # (file, reason)


# ── Source harness readers ─────────────────────────────────────────────────

def _read_cursor_rules(project_dir: Path) -> list[MigrationItem]:
    """Read .cursor/rules/*.mdc files."""
    items: list[MigrationItem] = []
    rules_dir = project_dir / ".cursor" / "rules"
    if not rules_dir.is_dir():
        return items
    for mdc in sorted(rules_dir.glob("*.mdc")):
        try:
            content = mdc.read_text(encoding="utf-8")
        except OSError:
            continue
        # Strip MDC frontmatter
        body = content
        if content.startswith("---"):
            parts = content.split("---", 2)
            body = parts[2].strip() if len(parts) >= 3 else content
        items.append(MigrationItem(
            source_harness="cursor",
            source_file=str(mdc),
            item_type="rule",
            original_content=content,
            proposed_target="CLAUDE.md",
            proposed_content=f"\n## {mdc.stem} (from Cursor)\n\n{body}\n",
            confidence=0.9,
            notes="MDC frontmatter stripped; content inlined into CLAUDE.md",
        ))
    return items


def _read_cursor_mcp(project_dir: Path) -> list[MigrationItem]:
    """Read .cursor/mcp.json."""
    mcp_file = project_dir / ".cursor" / "mcp.json"
    if not mcp_file.exists():
        return []
    try:
        data = json.loads(mcp_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    servers = data.get("mcpServers", {})
    items: list[MigrationItem] = []
    for name, cfg in servers.items():
        items.append(MigrationItem(
            source_harness="cursor",
            source_file=str(mcp_file),
            item_type="mcp_server",
            original_content=json.dumps({name: cfg}, indent=2),
            proposed_target="~/.claude.json",
            proposed_content=json.dumps({name: cfg}, indent=2),
            confidence=0.95,
            notes=f"Add to mcpServers in ~/.claude.json under the project key",
        ))
    return items


def _read_aider_conventions(project_dir: Path) -> list[MigrationItem]:
    """Read CONVENTIONS.md as Aider rules."""
    items: list[MigrationItem] = []
    for candidate in ("CONVENTIONS.md", ".aider.conf.yml"):
        path = project_dir / candidate
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if candidate.endswith(".yml"):
            # Extract model / settings from .aider.conf.yml
            items.append(MigrationItem(
                source_harness="aider",
                source_file=str(path),
                item_type="setting",
                original_content=content,
                proposed_target="CLAUDE.md",
                proposed_content=(
                    "\n## Aider Settings (migrated)\n\n"
                    "<!-- Original .aider.conf.yml content below; review manually -->\n"
                    f"```yaml\n{content}\n```\n"
                ),
                confidence=0.4,
                notes="Aider YAML settings have no direct Claude Code equivalent; manual review needed",
            ))
        else:
            items.append(MigrationItem(
                source_harness="aider",
                source_file=str(path),
                item_type="rule",
                original_content=content,
                proposed_target="CLAUDE.md",
                proposed_content=f"\n## Conventions (from Aider)\n\n{content}\n",
                confidence=0.85,
            ))
    return items


def _read_gemini_rules(project_dir: Path) -> list[MigrationItem]:
    """Read GEMINI.md sections as rules."""
    gemini_md = project_dir / "GEMINI.md"
    if not gemini_md.exists():
        return []
    try:
        content = gemini_md.read_text(encoding="utf-8")
    except OSError:
        return []
    # Split on H2 sections
    sections = re.split(r"\n(##\s+[^\n]+)\n", content)
    items: list[MigrationItem] = []
    if sections:
        # Preamble
        preamble = sections[0].strip()
        if preamble:
            items.append(MigrationItem(
                source_harness="gemini",
                source_file=str(gemini_md),
                item_type="rule",
                original_content=preamble,
                proposed_target="CLAUDE.md",
                proposed_content=f"\n## Gemini Preamble (migrated)\n\n{preamble}\n",
                confidence=0.8,
            ))
        # Sections
        i = 1
        while i < len(sections) - 1:
            heading = sections[i].strip()
            body = sections[i + 1].strip()
            if body:
                items.append(MigrationItem(
                    source_harness="gemini",
                    source_file=str(gemini_md),
                    item_type="rule",
                    original_content=f"{heading}\n{body}",
                    proposed_target="CLAUDE.md",
                    proposed_content=f"\n{heading} (from Gemini)\n\n{body}\n",
                    confidence=0.85,
                ))
            i += 2
    return items


def _read_codex_rules(project_dir: Path) -> list[MigrationItem]:
    """Read AGENTS.md as Codex rules."""
    agents_md = project_dir / "AGENTS.md"
    if not agents_md.exists():
        return []
    try:
        content = agents_md.read_text(encoding="utf-8")
    except OSError:
        return []
    return [MigrationItem(
        source_harness="codex",
        source_file=str(agents_md),
        item_type="rule",
        original_content=content,
        proposed_target="CLAUDE.md",
        proposed_content=f"\n## Codex Rules (migrated from AGENTS.md)\n\n{content}\n",
        confidence=0.85,
    )]


def _read_codex_config(project_dir: Path) -> list[MigrationItem]:
    """Read .codex/config.toml for model/settings."""
    config = project_dir / ".codex" / "config.toml"
    if not config.exists():
        return []
    try:
        content = config.read_text(encoding="utf-8")
    except OSError:
        return []
    # Extract model if present
    model_match = re.search(r'model\s*=\s*"([^"]+)"', content)
    model = model_match.group(1) if model_match else ""
    notes = f"model={model}" if model else "Review config manually"
    return [MigrationItem(
        source_harness="codex",
        source_file=str(config),
        item_type="setting",
        original_content=content,
        proposed_target="CLAUDE.md",
        proposed_content=(
            "\n## Codex Config (migrated)\n\n"
            f"<!-- Original Codex config.toml; model={model or 'unknown'} -->\n"
            "<!-- Add ANTHROPIC_MODEL env var to match Codex model setting -->\n"
        ),
        confidence=0.5,
        notes=notes,
    )]


def _read_opencode_config(project_dir: Path) -> list[MigrationItem]:
    """Read opencode.json for rules and MCP servers."""
    oc_json = project_dir / "opencode.json"
    if not oc_json.exists():
        return []
    try:
        data = json.loads(oc_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    items: list[MigrationItem] = []
    # MCP servers
    for name, cfg in data.get("mcpServers", {}).items():
        items.append(MigrationItem(
            source_harness="opencode",
            source_file=str(oc_json),
            item_type="mcp_server",
            original_content=json.dumps({name: cfg}, indent=2),
            proposed_target="~/.claude.json",
            proposed_content=json.dumps({name: cfg}, indent=2),
            confidence=0.92,
            notes="OpenCode MCP config directly compatible with Claude Code format",
        ))
    return items


def _read_windsurf_rules(project_dir: Path) -> list[MigrationItem]:
    """Read .windsurfrules as rules."""
    ws_rules = project_dir / ".windsurfrules"
    if not ws_rules.exists():
        return []
    try:
        content = ws_rules.read_text(encoding="utf-8")
    except OSError:
        return []
    return [MigrationItem(
        source_harness="windsurf",
        source_file=str(ws_rules),
        item_type="rule",
        original_content=content,
        proposed_target="CLAUDE.md",
        proposed_content=f"\n## Windsurf Rules (migrated)\n\n{content}\n",
        confidence=0.88,
    )]


# ── Main assistant ─────────────────────────────────────────────────────────

_READERS: dict[str, list] = {
    "cursor":    [_read_cursor_rules, _read_cursor_mcp],
    "aider":     [_read_aider_conventions],
    "gemini":    [_read_gemini_rules],
    "codex":     [_read_codex_rules, _read_codex_config],
    "opencode":  [_read_opencode_config],
    "windsurf":  [_read_windsurf_rules],
}


class MigrationAssistant:
    """Guide users through migrating a source harness configuration into Claude Code.

    Args:
        project_dir: Project root to scan.  Defaults to cwd.
        cc_home:     Claude Code home.  Defaults to ~/.claude.
    """

    def __init__(self, project_dir: Path | None = None, cc_home: Path | None = None):
        self.project_dir = project_dir or Path.cwd()
        self.cc_home = cc_home or (Path.home() / ".claude")

    def scan(self, source_harness: str | None = None) -> MigrationPlan:
        """Scan for source harness configs and build a migration plan.

        Args:
            source_harness: Specific harness to migrate from.  If None, auto-detects
                            the first harness with discoverable config.

        Returns:
            MigrationPlan with all migration items.
        """
        harnesses_to_try = [source_harness] if source_harness else list(_READERS.keys())
        items: list[MigrationItem] = []
        skipped: list[tuple[str, str]] = []
        detected = source_harness or "auto"

        for harness in harnesses_to_try:
            readers = _READERS.get(harness, [])
            for reader_fn in readers:
                try:
                    found = reader_fn(self.project_dir)
                    items.extend(found)
                    if found and detected == "auto":
                        detected = harness
                except Exception as exc:
                    skipped.append((harness, str(exc)))

        # De-duplicate CLAUDE.md entries by proposed_content
        seen: set[str] = set()
        deduped: list[MigrationItem] = []
        for item in items:
            key = item.proposed_content.strip()
            if key not in seen:
                seen.add(key)
                deduped.append(item)
            else:
                skipped.append((item.source_file, "duplicate content"))

        return MigrationPlan(source_harness=detected, items=deduped, skipped=skipped)

    def apply(self, plan: MigrationPlan, dry_run: bool = True) -> list[str]:
        """Apply a migration plan, writing output files.

        Args:
            plan:    MigrationPlan from scan().
            dry_run: If True, print what would be written without touching files.

        Returns:
            List of files written (or would-be-written in dry_run mode).
        """
        written: list[str] = []
        claude_md_chunks: list[str] = []
        mcp_servers: dict[str, dict] = {}

        for item in plan.items:
            if item.proposed_target == "CLAUDE.md":
                claude_md_chunks.append(item.proposed_content)
            elif item.proposed_target == "~/.claude.json":
                try:
                    server_data = json.loads(item.proposed_content)
                    mcp_servers.update(server_data)
                except json.JSONDecodeError:
                    pass

        # Write CLAUDE.md
        if claude_md_chunks:
            claude_md = self.project_dir / "CLAUDE.md"
            existing = claude_md.read_text(encoding="utf-8") if claude_md.exists() else ""
            new_content = existing + "\n\n# === Migrated from " + plan.source_harness + " ===\n"
            for chunk in claude_md_chunks:
                new_content += chunk
            if not dry_run:
                claude_md.write_text(new_content, encoding="utf-8")
            written.append(str(claude_md))

        # Merge MCP servers into ~/.claude.json
        if mcp_servers:
            claude_json = self.cc_home / ".claude.json"
            data: dict = {}
            if claude_json.exists():
                try:
                    data = json.loads(claude_json.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            existing_mcp = data.get("mcpServers", {})
            existing_mcp.update(mcp_servers)
            data["mcpServers"] = existing_mcp
            if not dry_run:
                claude_json.write_text(json.dumps(data, indent=2), encoding="utf-8")
            written.append(str(claude_json))

        return written

    def format_plan(self, plan: MigrationPlan) -> str:
        """Return a human-readable migration plan summary."""
        lines = [
            f"Harness Migration Plan: {plan.source_harness} → Claude Code",
            "=" * 55,
            f"Items to migrate: {len(plan.items)}",
            f"Skipped:          {len(plan.skipped)}",
            "",
        ]

        by_type: dict[str, list[MigrationItem]] = {}
        for item in plan.items:
            by_type.setdefault(item.item_type, []).append(item)

        for item_type, type_items in sorted(by_type.items()):
            lines.append(f"\n[{item_type.upper()}]")
            for item in type_items:
                conf_pct = int(item.confidence * 100)
                lines.append(f"  ✓ {Path(item.source_file).name:30s} → {item.proposed_target}  (confidence: {conf_pct}%)")
                if item.notes:
                    lines.append(f"    note: {item.notes}")

        if plan.skipped:
            lines.append("\n[SKIPPED]")
            for src_file, reason in plan.skipped:
                lines.append(f"  ✗ {src_file}: {reason}")

        lines.append("\nRun with --apply to write these changes to disk.")
        return "\n".join(lines)

    # ── Skills scaffold generation ─────────────────────────────────────────

    def generate_skills_scaffold(self, plan: MigrationPlan) -> list[dict]:
        """Generate Claude Code skill scaffold entries from migrated rules.

        Analyses migrated rule items and produces a list of skill scaffold
        definitions — each a dict ready to write as a ``.claude/skills/<name>/``
        directory with a ``SKILL.md`` file.

        The heuristic is:
        - Rules that look like workflows (contain verbs like "always", "run",
          "execute", "generate", "review") are wrapped into named skills.
        - Rules from Cursor ``.mdc`` files get the stem as the skill name.
        - Rules from Aider CONVENTIONS.md get generic ``migrated-rule-N`` names.

        Args:
            plan: MigrationPlan returned by scan().

        Returns:
            List of dicts with keys:
                name: Skill directory name (slug)
                skill_md: Content for SKILL.md
                source: Original source file name
        """
        scaffolds: list[dict] = []
        rule_items = [i for i in plan.items if i.item_type == "rule"]

        for idx, item in enumerate(rule_items, start=1):
            source_path = Path(item.source_file)
            stem = source_path.stem

            # Derive a skill name: prefer file stem unless it's generic
            generic_names = {"CONVENTIONS", "CLAUDE", "GEMINI", "AGENTS", "windsurfrules"}
            if stem.upper() in generic_names or not stem:
                skill_name = f"migrated-rule-{idx:02d}"
            else:
                # Slugify: lowercase, replace non-alphanumeric with hyphens
                import re as _re
                skill_name = _re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")

            # Determine trigger description from content heuristics
            content = item.proposed_content.strip()
            first_line = content.splitlines()[0].lstrip("#- ").strip() if content else ""
            trigger_desc = first_line[:80] if first_line else f"Rules migrated from {source_path.name}"

            skill_md = (
                f"---\n"
                f"name: {skill_name}\n"
                f"description: {trigger_desc}\n"
                f"# Migrated from {item.source_harness} ({source_path.name}) "
                f"by HarnessSync migration assistant\n"
                f"---\n\n"
                f"# {skill_name}\n\n"
                f"{content}\n"
            )

            scaffolds.append({
                "name": skill_name,
                "skill_md": skill_md,
                "source": str(source_path.name),
            })

        return scaffolds

    def apply_skills_scaffold(
        self,
        scaffolds: list[dict],
        dry_run: bool = True,
        skills_dir: Path | None = None,
    ) -> list[str]:
        """Write skill scaffold files to ``.claude/skills/``.

        Args:
            scaffolds: List from generate_skills_scaffold().
            dry_run:   If True, return paths without writing.
            skills_dir: Override for ``.claude/skills/`` directory.

        Returns:
            List of written (or would-be-written) file paths.
        """
        target_dir = skills_dir or (self.project_dir / ".claude" / "skills")
        written: list[str] = []

        for scaffold in scaffolds:
            skill_dir = target_dir / scaffold["name"]
            skill_md_path = skill_dir / "SKILL.md"
            if not dry_run:
                skill_dir.mkdir(parents=True, exist_ok=True)
                skill_md_path.write_text(scaffold["skill_md"], encoding="utf-8")
            written.append(str(skill_md_path))

        return written
