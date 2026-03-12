from __future__ import annotations

"""Auto Config Documentation Generator (item 23).

Generates a human-readable Markdown or HTML document explaining every rule,
skill, and MCP server in the user's config — what each does, which harnesses
support it, and inline comments extracted from the config.

/sync-docs generates a living config reference for teams onboarding new
engineers, or for solo users who have accumulated years of config debt and
need a clear picture of what they've built.

Architecture:
    ConfigDocGenerator reads CLAUDE.md, discovers skills and agents in the
    .claude/ directory, reads MCP server configs, and produces a structured
    document. No external dependencies.

Output formats:
    - Markdown (default): human-readable, can be committed to the repo
    - HTML: styled table-of-contents document for sharing

Sections generated:
    1. Rules (from CLAUDE.md sections)
    2. Skills (from .claude/skills/*.md)
    3. Agents (from .claude/agents/*.md)
    4. Commands (from .claude/commands/*.md)
    5. MCP Servers (from .claude.json mcpServers or .mcp.json)
    6. Harness Coverage Matrix (which harnesses support each section)
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.utils.constants import CORE_TARGETS


# Pattern to extract CLAUDE.md sections
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)(?:\s+#+)?$", re.MULTILINE)

# Pattern to extract inline comments (lines starting with # or <!-- ... -->)
_COMMENT_RE = re.compile(r"^\s*<!--\s*(.+?)\s*-->", re.MULTILINE)

# Known harness targets for coverage matrix
_HARNESSES = list(CORE_TARGETS)


@dataclass
class RuleDoc:
    """Documentation for a single CLAUDE.md rule section."""
    heading: str
    level: int            # 1, 2, or 3 (number of # chars)
    body: str             # Section body text
    comments: list[str]   # Extracted inline comments
    harness_notes: dict[str, str] = field(default_factory=dict)
    # harness_notes: harness -> note extracted from <!-- harness:X --> blocks
    line_number: int = 0


@dataclass
class SkillDoc:
    """Documentation for a .claude/skills/*.md skill."""
    name: str
    title: str
    description: str
    file_path: str
    frontmatter: dict = field(default_factory=dict)
    body_snippet: str = ""  # First 300 chars of body


@dataclass
class McpServerDoc:
    """Documentation for a configured MCP server."""
    name: str
    command: str
    args: list[str]
    env_vars: list[str]   # Names only (not values — security)
    transport: str = "stdio"
    description: str = ""


@dataclass
class ConfigDoc:
    """Complete generated documentation."""
    generated_at: str
    project_dir: str
    rules: list[RuleDoc] = field(default_factory=list)
    skills: list[SkillDoc] = field(default_factory=list)
    agents: list[SkillDoc] = field(default_factory=list)
    commands: list[SkillDoc] = field(default_factory=list)
    mcp_servers: list[McpServerDoc] = field(default_factory=list)


def _extract_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and return (parsed_dict, body)."""
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 3)
    if end == -1:
        return {}, content
    fm_text = content[3:end].strip()
    body = content[end + 4:].lstrip("\n")
    parsed: dict = {}
    for line in fm_text.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            parsed[key.strip()] = val.strip()
    return parsed, body


def _split_sections(content: str) -> list[tuple[str, int, int, str]]:
    """Split content into sections.

    Returns:
        List of (heading_text, level, line_number, body) tuples.
    """
    matches = list(_HEADING_RE.finditer(content))
    sections = []
    for i, m in enumerate(matches):
        heading = m.group(2).strip()
        level = len(m.group(1))
        line_number = content[:m.start()].count("\n") + 1
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[start:end].strip()
        sections.append((heading, level, line_number, body))
    return sections


def _extract_harness_notes(body: str) -> dict[str, str]:
    """Extract <!-- harness:X --> ... <!-- /harness:X --> notes from body."""
    notes: dict[str, str] = {}
    open_re = re.compile(r"<!--\s*harness:([a-z0-9_-]+)\s*-->(.+?)<!--\s*/harness:\1\s*-->",
                         re.DOTALL | re.IGNORECASE)
    for m in open_re.finditer(body):
        harness = m.group(1).lower()
        note = m.group(2).strip()
        notes[harness] = note
    return notes


class ConfigDocGenerator:
    """Generate documentation from CLAUDE.md, skills, agents, and MCP servers.

    Args:
        project_dir: Project root directory.
        cc_home: Claude Code config home (default: ~/.claude).
    """

    def __init__(self, project_dir: Path, cc_home: Path | None = None):
        self.project_dir = Path(project_dir)
        self.cc_home = cc_home or (Path.home() / ".claude")

    def _parse_rules(self) -> list[RuleDoc]:
        """Parse CLAUDE.md into RuleDoc entries."""
        claude_md = self.project_dir / "CLAUDE.md"
        if not claude_md.exists():
            # Try cc_home
            claude_md = self.cc_home / "CLAUDE.md"
        if not claude_md.exists():
            return []

        content = claude_md.read_text(encoding="utf-8", errors="replace")
        sections = _split_sections(content)
        rules: list[RuleDoc] = []
        for heading, level, line_no, body in sections:
            comments = _COMMENT_RE.findall(body)
            harness_notes = _extract_harness_notes(body)
            # Clean body: remove harness block markers
            clean_body = re.sub(r"<!--\s*/?harness:[^>]+-->", "", body).strip()
            rules.append(RuleDoc(
                heading=heading,
                level=level,
                body=clean_body,
                comments=comments,
                harness_notes=harness_notes,
                line_number=line_no,
            ))
        return rules

    def _parse_skill_files(self, directory: Path) -> list[SkillDoc]:
        """Parse skill/agent/command .md files in a directory."""
        docs: list[SkillDoc] = []
        if not directory.exists():
            return docs
        for path in sorted(directory.glob("**/*.md")):
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            fm, body = _extract_frontmatter(content)
            name = path.stem
            title = fm.get("name", fm.get("title", name))
            description = fm.get("description", "")
            # Extract description from first paragraph if not in frontmatter
            if not description and body:
                first_para = body.split("\n\n")[0].strip()
                if first_para and not first_para.startswith("#"):
                    description = first_para[:200]
            docs.append(SkillDoc(
                name=name,
                title=title,
                description=description,
                file_path=str(path.relative_to(self.project_dir)),
                frontmatter=fm,
                body_snippet=body[:300] if body else "",
            ))
        return docs

    def _parse_mcp_servers(self) -> list[McpServerDoc]:
        """Parse MCP server configs from .claude.json or .mcp.json."""
        servers: dict[str, dict] = {}
        # Try project-level .mcp.json first
        project_mcp = self.project_dir / ".mcp.json"
        if project_mcp.exists():
            try:
                data = json.loads(project_mcp.read_text(encoding="utf-8"))
                servers.update(data.get("mcpServers", {}))
            except (json.JSONDecodeError, OSError):
                pass
        # Try global ~/.claude.json
        global_json = self.cc_home.parent / ".claude.json"
        if global_json.exists():
            try:
                data = json.loads(global_json.read_text(encoding="utf-8"))
                global_mcp = data.get("mcpServers", {})
                for name, cfg in global_mcp.items():
                    if name not in servers:
                        servers[name] = cfg
            except (json.JSONDecodeError, OSError):
                pass

        docs: list[McpServerDoc] = []
        for name, cfg in sorted(servers.items()):
            if not isinstance(cfg, dict):
                continue
            command = cfg.get("command", "")
            args = cfg.get("args", [])
            env = cfg.get("env", {})
            env_var_names = list(env.keys()) if isinstance(env, dict) else []
            transport = cfg.get("transport", "stdio")
            docs.append(McpServerDoc(
                name=name,
                command=command,
                args=args if isinstance(args, list) else [],
                env_vars=env_var_names,
                transport=transport,
            ))
        return docs

    def generate(self) -> ConfigDoc:
        """Generate the full ConfigDoc from all config sources.

        Returns:
            ConfigDoc populated with rules, skills, agents, commands, and MCP servers.
        """
        skills_dir = self.cc_home / "skills"
        agents_dir = self.cc_home / "agents"
        commands_dir = self.cc_home / "commands"

        return ConfigDoc(
            generated_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            project_dir=str(self.project_dir),
            rules=self._parse_rules(),
            skills=self._parse_skill_files(skills_dir),
            agents=self._parse_skill_files(agents_dir),
            commands=self._parse_skill_files(commands_dir),
            mcp_servers=self._parse_mcp_servers(),
        )

    def to_markdown(self, doc: ConfigDoc | None = None) -> str:
        """Render ConfigDoc as Markdown.

        Args:
            doc: ConfigDoc to render. If None, calls generate() first.

        Returns:
            Markdown string.
        """
        if doc is None:
            doc = self.generate()

        lines = [
            f"# HarnessSync Config Reference",
            f"",
            f"*Generated: {doc.generated_at}*  ",
            f"*Project: {doc.project_dir}*",
            f"",
            "---",
            "",
        ]

        # Rules
        if doc.rules:
            lines += ["## Rules (CLAUDE.md)", ""]
            for rule in doc.rules:
                prefix = "#" * (rule.level + 1)
                lines.append(f"{prefix} {rule.heading}")
                if rule.body:
                    lines.append("")
                    # Indent body for readability
                    for body_line in rule.body.splitlines():
                        lines.append(body_line)
                if rule.harness_notes:
                    lines.append("")
                    lines.append("**Harness-specific notes:**")
                    for harness, note in sorted(rule.harness_notes.items()):
                        lines.append(f"- **{harness}**: {note}")
                lines.append("")

        # Skills
        if doc.skills:
            lines += ["## Skills", ""]
            for skill in doc.skills:
                lines.append(f"### {skill.title or skill.name}")
                if skill.description:
                    lines.append("")
                    lines.append(skill.description)
                lines.append(f"  *File: `{skill.file_path}`*")
                lines.append("")

        # Agents
        if doc.agents:
            lines += ["## Agents", ""]
            for agent in doc.agents:
                lines.append(f"### {agent.title or agent.name}")
                if agent.description:
                    lines.append("")
                    lines.append(agent.description)
                lines.append(f"  *File: `{agent.file_path}`*")
                lines.append("")

        # Commands
        if doc.commands:
            lines += ["## Commands", ""]
            for cmd in doc.commands:
                lines.append(f"### /{cmd.name}")
                if cmd.description:
                    lines.append("")
                    lines.append(cmd.description)
                lines.append(f"  *File: `{cmd.file_path}`*")
                lines.append("")

        # MCP Servers
        if doc.mcp_servers:
            lines += ["## MCP Servers", ""]
            for srv in doc.mcp_servers:
                lines.append(f"### {srv.name}")
                lines.append(f"- **Command**: `{srv.command}`")
                if srv.args:
                    lines.append(f"- **Args**: `{' '.join(str(a) for a in srv.args)}`")
                if srv.env_vars:
                    lines.append(f"- **Environment variables**: {', '.join(f'`{v}`' for v in srv.env_vars)}")
                lines.append(f"- **Transport**: {srv.transport}")
                lines.append("")

        # Harness coverage matrix
        lines += ["## Harness Coverage", ""]
        lines.append("| Section | " + " | ".join(h.capitalize() for h in _HARNESSES) + " |")
        lines.append("|---------|" + "|".join(":---------:" for _ in _HARNESSES) + "|")

        section_types = [
            ("Rules", bool(doc.rules), True),
            ("Skills", bool(doc.skills), True),
            ("Agents", bool(doc.agents), False),   # Agent concept varies per harness
            ("Commands", bool(doc.commands), False),
            ("MCP Servers", bool(doc.mcp_servers), True),
        ]
        _HARNESS_AGENT_SUPPORT = {"codex", "gemini", "opencode"}
        _HARNESS_CMD_SUPPORT: set[str] = set()  # No harness fully supports CC commands yet

        for section_name, present, full_support in section_types:
            if not present:
                continue
            cells = []
            for h in _HARNESSES:
                if section_name == "Agents" and h not in _HARNESS_AGENT_SUPPORT:
                    cells.append("partial")
                elif section_name == "Commands" and h not in _HARNESS_CMD_SUPPORT:
                    cells.append("no")
                elif full_support:
                    cells.append("yes")
                else:
                    cells.append("yes")
            lines.append(f"| {section_name} | " + " | ".join(cells) + " |")

        lines.append("")
        return "\n".join(lines)

    def to_html(self, doc: ConfigDoc | None = None) -> str:
        """Render ConfigDoc as a basic HTML document.

        Args:
            doc: ConfigDoc to render. If None, calls generate() first.

        Returns:
            HTML string.
        """
        if doc is None:
            doc = self.generate()

        md = self.to_markdown(doc)
        # Very basic Markdown-to-HTML conversion for headings, code, bold
        html = md
        html = re.sub(r"^#### (.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)
        html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
        html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
        html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
        html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
        html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
        html = re.sub(r"\n", "<br>\n", html)

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>HarnessSync Config Reference</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            max-width: 900px; margin: 0 auto; padding: 2rem; color: #24292f; }}
    h1 {{ border-bottom: 2px solid #d0d7de; padding-bottom: .5rem; }}
    h2 {{ border-bottom: 1px solid #d0d7de; padding-bottom: .3rem; }}
    code {{ background: #f6f8fa; padding: .1rem .3rem; border-radius: 3px;
            font-family: "SFMono-Regular", monospace; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d0d7de; padding: .4rem .8rem; }}
    th {{ background: #f6f8fa; }}
  </style>
</head>
<body>
{html}
</body>
</html>"""

    def write(self, output_path: Path | None = None, fmt: str = "markdown") -> Path:
        """Generate documentation and write to a file.

        Args:
            output_path: Destination file. Defaults to
                         <project_dir>/HARNESSSYNC-DOCS.md (or .html).
            fmt: Output format — "markdown" or "html".

        Returns:
            Path to the written file.
        """
        doc = self.generate()
        if fmt == "html":
            content = self.to_html(doc)
            default_name = "HARNESSSYNC-DOCS.html"
        else:
            content = self.to_markdown(doc)
            default_name = "HARNESSSYNC-DOCS.md"

        if output_path is None:
            output_path = self.project_dir / default_name

        output_path = Path(output_path)
        output_path.write_text(content, encoding="utf-8")
        return output_path
