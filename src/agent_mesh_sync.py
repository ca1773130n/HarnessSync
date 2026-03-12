from __future__ import annotations

"""Agent Mesh Sync — export Claude Code multi-agent configuration to other harnesses.

Claude Code supports multi-agent setups: named subagents with roles, trigger
conditions, tool permissions, and orchestration logic defined in agent .md files
and plugin manifests. Other harnesses (Gemini, OpenCode) have their own agent
orchestration formats.

This module reads the Claude Code agent mesh and translates it into target-specific
agent configuration so teams don't have to rebuild pipelines from scratch when
switching harnesses.

Supported targets:
- gemini: GEMINI.md agent sections + gemini_agents.json
- opencode: opencode.json agents array
- codex: AGENTS.md subagent descriptions (partial — no trigger conditions)

Usage:
    from src.agent_mesh_sync import AgentMeshSync

    mesh = AgentMeshSync(cc_home=Path.home() / ".claude", project_dir=Path("."))
    report = mesh.sync_to_targets(["gemini", "opencode"])
    print(mesh.format_report(report))
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


# Translation fidelity per target.  Higher = more faithful.
_FIDELITY: dict[str, float] = {
    "gemini":   0.75,  # Supports named agents + roles; loses tool-permission detail
    "opencode": 0.70,  # JSON agents array; loses trigger conditions
    "codex":    0.45,  # AGENTS.md prose only; no structured trigger/tool support
    "cursor":   0.30,  # .cursor/rules only; minimal agent concept
    "aider":    0.20,  # No agent concept; writes summary to CONVENTIONS.md
    "windsurf": 0.25,  # .windsurfrules section only
}

# Features each target supports from the agent mesh
_FEATURE_SUPPORT: dict[str, dict[str, bool]] = {
    "gemini": {
        "roles": True,
        "trigger_conditions": False,
        "tool_permissions": False,
        "orchestration_logic": False,
        "subagent_descriptions": True,
    },
    "opencode": {
        "roles": True,
        "trigger_conditions": False,
        "tool_permissions": True,
        "orchestration_logic": False,
        "subagent_descriptions": True,
    },
    "codex": {
        "roles": True,
        "trigger_conditions": False,
        "tool_permissions": False,
        "orchestration_logic": False,
        "subagent_descriptions": True,
    },
    "cursor": {
        "roles": False,
        "trigger_conditions": False,
        "tool_permissions": False,
        "orchestration_logic": False,
        "subagent_descriptions": True,
    },
    "aider": {
        "roles": False,
        "trigger_conditions": False,
        "tool_permissions": False,
        "orchestration_logic": False,
        "subagent_descriptions": True,
    },
    "windsurf": {
        "roles": False,
        "trigger_conditions": False,
        "tool_permissions": False,
        "orchestration_logic": False,
        "subagent_descriptions": True,
    },
}


@dataclass
class AgentDefinition:
    """A single agent extracted from Claude Code config."""
    name: str
    description: str
    role: str = ""                     # e.g. "code-reviewer", "test-runner"
    trigger_conditions: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    denied_tools: list[str] = field(default_factory=list)
    subagent_type: str = ""            # from agent frontmatter
    source_file: str = ""


@dataclass
class MeshSyncResult:
    """Result of syncing agent mesh to one target."""
    target: str
    agents_synced: int
    features_lost: list[str]
    fidelity_score: float
    output_files: list[str]
    errors: list[str] = field(default_factory=list)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML-style frontmatter from agent markdown.

    Returns (frontmatter_dict, body_text).
    """
    fm: dict = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            body = parts[2].strip()
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    fm[k.strip()] = v.strip()
    return fm, body


def _extract_trigger_conditions(body: str) -> list[str]:
    """Heuristically extract trigger conditions from agent body text."""
    conditions: list[str] = []
    for line in body.splitlines():
        low = line.lower().strip()
        if any(kw in low for kw in ("trigger", "when to use", "use when", "use this when")):
            # Next non-empty line after trigger header is likely a condition
            idx = body.splitlines().index(line)
            lines = body.splitlines()
            for follow in lines[idx + 1: idx + 6]:
                stripped = follow.strip().lstrip("-* ")
                if stripped:
                    conditions.append(stripped)
                    break
    return conditions


class AgentMeshReader:
    """Read Claude Code agent definitions from .claude/agents/ or commands/*.md."""

    def __init__(self, cc_home: Path, project_dir: Path | None = None):
        self.cc_home = cc_home
        self.project_dir = project_dir or Path.cwd()

    def read_agents(self) -> list[AgentDefinition]:
        """Return all agent definitions found in known agent locations."""
        agents: list[AgentDefinition] = []
        search_dirs = [
            self.cc_home / "agents",
            self.project_dir / ".claude" / "agents",
            self.project_dir / ".claude" / "commands",
        ]
        for search_dir in search_dirs:
            if not search_dir.is_dir():
                continue
            for md_file in sorted(search_dir.glob("**/*.md")):
                agent = self._parse_agent_file(md_file)
                if agent:
                    agents.append(agent)
        return agents

    def _parse_agent_file(self, path: Path) -> AgentDefinition | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        fm, body = _parse_frontmatter(text)
        name = fm.get("name") or path.stem
        description = fm.get("description") or ""
        if not description and body:
            # First non-empty paragraph as description
            for para in body.split("\n\n"):
                stripped = para.strip()
                if stripped and not stripped.startswith("#"):
                    description = stripped[:300]
                    break
        return AgentDefinition(
            name=name,
            description=description,
            role=fm.get("role", ""),
            subagent_type=fm.get("subagent_type", ""),
            trigger_conditions=_extract_trigger_conditions(body),
            source_file=str(path),
        )


class AgentMeshSync:
    """Sync Claude Code agent mesh to other harnesses.

    Args:
        cc_home:     Path to Claude Code home (default: ~/.claude)
        project_dir: Project root directory (default: cwd)
        dry_run:     If True, compute output but don't write files
    """

    def __init__(
        self,
        cc_home: Path | None = None,
        project_dir: Path | None = None,
        dry_run: bool = False,
    ):
        self.cc_home = cc_home or (Path.home() / ".claude")
        self.project_dir = project_dir or Path.cwd()
        self.dry_run = dry_run
        self._reader = AgentMeshReader(self.cc_home, self.project_dir)

    def sync_to_targets(self, targets: list[str] | None = None) -> list[MeshSyncResult]:
        """Sync agent mesh to all specified targets.

        Args:
            targets: List of harness names. Defaults to all supported targets.

        Returns:
            List of MeshSyncResult, one per target.
        """
        if targets is None:
            targets = list(_FIDELITY.keys())
        agents = self._reader.read_agents()
        return [self._sync_one(target, agents) for target in targets]

    def _sync_one(self, target: str, agents: list[AgentDefinition]) -> MeshSyncResult:
        support = _FEATURE_SUPPORT.get(target, {})
        features_lost: list[str] = []
        for feat, supported in support.items():
            if not supported:
                features_lost.append(feat.replace("_", " "))

        output_files: list[str] = []
        errors: list[str] = []

        try:
            if target == "gemini":
                files = self._write_gemini(agents)
            elif target == "opencode":
                files = self._write_opencode(agents)
            elif target == "codex":
                files = self._write_codex(agents)
            elif target == "cursor":
                files = self._write_cursor(agents)
            elif target == "aider":
                files = self._write_aider(agents)
            elif target == "windsurf":
                files = self._write_windsurf(agents)
            else:
                files = []
                errors.append(f"Unknown target: {target}")
            output_files.extend(files)
        except OSError as exc:
            errors.append(str(exc))

        return MeshSyncResult(
            target=target,
            agents_synced=len(agents),
            features_lost=features_lost,
            fidelity_score=_FIDELITY.get(target, 0.0),
            output_files=output_files,
            errors=errors,
        )

    # ── Target writers ─────────────────────────────────────────────────────

    def _write_gemini(self, agents: list[AgentDefinition]) -> list[str]:
        """Append agent sections to GEMINI.md."""
        lines = ["\n## Agent Mesh (synced from Claude Code)\n"]
        for a in agents:
            lines.append(f"### {a.name}")
            if a.role:
                lines.append(f"**Role:** {a.role}")
            if a.description:
                lines.append(f"\n{a.description}\n")
        content = "\n".join(lines)
        out = self.project_dir / "GEMINI.md"
        if not self.dry_run:
            existing = out.read_text(encoding="utf-8") if out.exists() else ""
            # Replace existing agent mesh block if present
            marker = "## Agent Mesh (synced from Claude Code)"
            if marker in existing:
                existing = existing[: existing.index(marker)]
            out.write_text(existing + content, encoding="utf-8")
        return [str(out)]

    def _write_opencode(self, agents: list[AgentDefinition]) -> list[str]:
        """Write agents array to opencode.json."""
        out = self.project_dir / "opencode.json"
        data: dict = {}
        if out.exists():
            try:
                data = json.loads(out.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        data["agents"] = [
            {
                "name": a.name,
                "description": a.description,
                **({"role": a.role} if a.role else {}),
            }
            for a in agents
        ]
        if not self.dry_run:
            out.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return [str(out)]

    def _write_codex(self, agents: list[AgentDefinition]) -> list[str]:
        """Append agent descriptions to AGENTS.md."""
        lines = ["\n## Subagents (synced from Claude Code agent mesh)\n"]
        for a in agents:
            lines.append(f"### {a.name}")
            if a.description:
                lines.append(a.description)
            lines.append("")
        content = "\n".join(lines)
        out = self.project_dir / "AGENTS.md"
        if not self.dry_run:
            existing = out.read_text(encoding="utf-8") if out.exists() else ""
            marker = "## Subagents (synced from Claude Code agent mesh)"
            if marker in existing:
                existing = existing[: existing.index(marker)]
            out.write_text(existing + content, encoding="utf-8")
        return [str(out)]

    def _write_cursor(self, agents: list[AgentDefinition]) -> list[str]:
        """Write agent summary to .cursor/rules/agents.mdc."""
        out = self.project_dir / ".cursor" / "rules" / "agents.mdc"
        lines = ["---", "description: Agent mesh synced from Claude Code", "---", ""]
        for a in agents:
            lines.append(f"## {a.name}")
            if a.description:
                lines.append(a.description)
            lines.append("")
        if not self.dry_run:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("\n".join(lines), encoding="utf-8")
        return [str(out)]

    def _write_aider(self, agents: list[AgentDefinition]) -> list[str]:
        """Append agent summary to CONVENTIONS.md."""
        lines = ["\n## AI Agents (synced from Claude Code)\n"]
        for a in agents:
            lines.append(f"- **{a.name}**: {a.description}")
        content = "\n".join(lines) + "\n"
        out = self.project_dir / "CONVENTIONS.md"
        if not self.dry_run:
            existing = out.read_text(encoding="utf-8") if out.exists() else ""
            marker = "## AI Agents (synced from Claude Code)"
            if marker in existing:
                existing = existing[: existing.index(marker)]
            out.write_text(existing + content, encoding="utf-8")
        return [str(out)]

    def _write_windsurf(self, agents: list[AgentDefinition]) -> list[str]:
        """Append agent summary to .windsurfrules."""
        lines = ["\n# Agent Mesh (synced from Claude Code)\n"]
        for a in agents:
            lines.append(f"- **{a.name}**: {a.description}")
        content = "\n".join(lines) + "\n"
        out = self.project_dir / ".windsurfrules"
        if not self.dry_run:
            existing = out.read_text(encoding="utf-8") if out.exists() else ""
            marker = "# Agent Mesh (synced from Claude Code)"
            if marker in existing:
                existing = existing[: existing.index(marker)]
            out.write_text(existing + content, encoding="utf-8")
        return [str(out)]

    # ── Reporting ──────────────────────────────────────────────────────────

    def format_report(self, results: list[MeshSyncResult]) -> str:
        """Return a human-readable sync report."""
        lines = ["Agent Mesh Sync Report", "=" * 40]
        for r in results:
            score_pct = int(r.fidelity_score * 100)
            status = "✓" if not r.errors else "✗"
            lines.append(f"\n{status} {r.target:12s}  {r.agents_synced} agents  fidelity={score_pct}%")
            if r.features_lost:
                lines.append(f"  Lost:  {', '.join(r.features_lost)}")
            if r.output_files:
                for f in r.output_files:
                    lines.append(f"  → {f}")
            for err in r.errors:
                lines.append(f"  ERROR: {err}")
        return "\n".join(lines)
