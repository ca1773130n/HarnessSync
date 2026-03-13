from __future__ import annotations

"""Reverse Sync — Import configs from target harnesses back into Claude Code.

Pulls useful configs, skills, rules, and MCP servers from target harnesses
(Codex, Gemini, OpenCode, Cursor, Aider, Windsurf) back into Claude Code's
canonical format.  Users who started on Gemini or Codex before adopting
Claude Code can consolidate their existing configs without manual translation.

Supported import sources and what they map to:
    codex:    AGENTS.md rules → CLAUDE.md additions
              config.toml mcp_servers → .mcp.json additions
              config.toml env → settings.json env additions
    gemini:   GEMINI.md rules → CLAUDE.md additions
              settings.json mcp → .mcp.json additions
              .gemini/.env → settings.json env additions
    opencode: AGENTS.md rules → CLAUDE.md additions
              opencode.json mcp → .mcp.json additions
              opencode.json env → settings.json env additions
    cursor:   .cursor/rules/*.mdc rules → CLAUDE.md additions
              .cursor/mcp.json → .mcp.json additions
    aider:    CONVENTIONS.md rules → CLAUDE.md additions
              .aider.conf.yml settings → CLAUDE.md settings notes
    windsurf: .windsurfrules → CLAUDE.md additions

Merge strategies:
    "append"    — append imported content after existing CLAUDE.md content
    "prepend"   — prepend imported content before existing content
    "replace"   — replace HarnessSync managed section entirely
    "new_file"  — write to a new file (e.g. CLAUDE.imported.md) — never overwrites

Usage:
    from src.reverse_sync import ReverseSync

    rs = ReverseSync(cc_home=Path("~/.claude"), project_dir=Path("."))
    plan = rs.plan(source="gemini")         # preview what would be imported
    print(rs.format_plan(plan))
    result = rs.execute(plan, dry_run=False) # apply

Or from CLI:
    /sync-reverse --from gemini [--merge append] [--dry-run]
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.utils.paths import default_cc_home


# ── Constants ─────────────────────────────────────────────────────────────────

# HarnessSync managed markers used in target harness files
_MANAGED_START = "<!-- Managed by HarnessSync -->"
_MANAGED_END = "<!-- End HarnessSync managed content -->"

# TOML inline value pattern for simple strings
_TOML_STR_RE = re.compile(r'^([a-zA-Z0-9_-]+)\s*=\s*"([^"]*)"')
_TOML_SECTION_RE = re.compile(r'^\[([^\]]+)\]')


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ImportedRule:
    """A rule block extracted from a target harness."""
    source_file: str        # Relative path to the source file
    content: str            # Raw rule text
    section: str = ""       # Section heading if detected


@dataclass
class ImportedMcpServer:
    """An MCP server definition extracted from a target harness."""
    name: str
    config: dict[str, Any]
    source_file: str


@dataclass
class ImportedEnvVar:
    """An environment variable entry extracted from a target harness."""
    key: str
    value: str              # May be a reference like "${VAR}" — never a literal secret
    source_file: str


@dataclass
class ReverseSyncPlan:
    """Full import plan for one target harness."""
    source: str                                 # e.g. "gemini"
    rules: list[ImportedRule] = field(default_factory=list)
    mcp_servers: list[ImportedMcpServer] = field(default_factory=list)
    env_vars: list[ImportedEnvVar] = field(default_factory=list)
    merge_strategy: str = "append"
    already_managed: bool = False               # True if content was written by HarnessSync
    warnings: list[str] = field(default_factory=list)

    @property
    def has_content(self) -> bool:
        return bool(self.rules or self.mcp_servers or self.env_vars)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_managed_block(content: str) -> str:
    """Remove HarnessSync managed blocks from content (they came from us)."""
    pattern = re.compile(
        re.escape(_MANAGED_START) + r".*?" + re.escape(_MANAGED_END) + r"\n?",
        re.DOTALL,
    )
    return pattern.sub("", content).strip()


def _parse_toml_mcp_servers(toml_text: str) -> dict[str, dict[str, Any]]:
    """Extract mcp_servers from a Codex-style config.toml.

    Only handles the simple TOML subset that HarnessSync writes.
    Falls back to an empty dict for unrecognised syntax.

    Returns:
        Dict mapping server_name → config dict.
    """
    servers: dict[str, dict[str, Any]] = {}
    current_section: str | None = None
    current_server: dict[str, Any] = {}

    for raw_line in toml_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        section_m = re.match(r'^\[mcp_servers\."([^"]+)"\]', line)
        if section_m:
            if current_section:
                servers[current_section] = current_server
            current_section = section_m.group(1)
            current_server = {}
            continue

        # End of mcp_servers section — new top-level section
        top_m = re.match(r'^\[([a-zA-Z0-9_-]+)\]$', line)
        if top_m and not line.startswith("[mcp_servers"):
            if current_section:
                servers[current_section] = current_server
                current_section = None
                current_server = {}
            continue

        if current_section is not None:
            kv = re.match(r'^([a-zA-Z0-9_-]+)\s*=\s*(.*)', line)
            if kv:
                key, val_raw = kv.group(1), kv.group(2).strip()
                # Decode simple string / array values
                if val_raw.startswith('"') and val_raw.endswith('"'):
                    current_server[key] = val_raw[1:-1]
                elif val_raw.startswith('[') and val_raw.endswith(']'):
                    # Simple one-line array
                    items = re.findall(r'"([^"]*)"', val_raw)
                    current_server[key] = items
                elif val_raw in ("true", "false"):
                    current_server[key] = val_raw == "true"
                else:
                    current_server[key] = val_raw

    if current_section:
        servers[current_section] = current_server

    return servers


def _parse_mdc_rules(mdc_path: Path) -> str:
    """Extract rule content from a Cursor .mdc file, stripping YAML frontmatter."""
    content = mdc_path.read_text(encoding="utf-8", errors="replace")
    # Strip YAML frontmatter (---…---)
    stripped = content.lstrip()
    if stripped.startswith("---"):
        end = stripped.find("\n---", 3)
        if end != -1:
            content = stripped[end + 4:].lstrip()
    return content.strip()


# ── Per-source importers ──────────────────────────────────────────────────────

class _CodexImporter:
    """Import from a Codex CLI project directory."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def collect_rules(self) -> list[ImportedRule]:
        agents_md = self.project_dir / "AGENTS.md"
        if not agents_md.exists():
            return []
        raw = agents_md.read_text(encoding="utf-8", errors="replace")
        # Only import non-managed content
        clean = _strip_managed_block(raw).strip()
        if not clean:
            return []
        return [ImportedRule(source_file="AGENTS.md", content=clean)]

    def collect_mcp(self) -> list[ImportedMcpServer]:
        config_toml = self.project_dir / ".codex" / "config.toml"
        if not config_toml.exists():
            config_toml = self.project_dir / "config.toml"
        if not config_toml.exists():
            return []
        text = config_toml.read_text(encoding="utf-8", errors="replace")
        servers = _parse_toml_mcp_servers(text)
        return [
            ImportedMcpServer(name=name, config=cfg, source_file=str(config_toml))
            for name, cfg in servers.items()
        ]

    def collect_env(self) -> list[ImportedEnvVar]:
        # Codex env vars are in [env] section of config.toml
        config_toml = self.project_dir / ".codex" / "config.toml"
        if not config_toml.exists():
            config_toml = self.project_dir / "config.toml"
        if not config_toml.exists():
            return []
        text = config_toml.read_text(encoding="utf-8", errors="replace")
        env_vars: list[ImportedEnvVar] = []
        in_env = False
        for line in text.splitlines():
            stripped = line.strip()
            if stripped == "[env]":
                in_env = True
                continue
            if stripped.startswith("[") and stripped != "[env]":
                in_env = False
            if in_env:
                kv = re.match(r'^([A-Z0-9_]+)\s*=\s*"([^"]*)"', stripped)
                if kv:
                    env_vars.append(ImportedEnvVar(
                        key=kv.group(1), value=kv.group(2),
                        source_file=str(config_toml),
                    ))
        return env_vars


class _GeminiImporter:
    """Import from a Gemini CLI home directory."""

    def __init__(self, gemini_home: Path):
        self.gemini_home = gemini_home

    def collect_rules(self) -> list[ImportedRule]:
        gemini_md = self.gemini_home / "GEMINI.md"
        if not gemini_md.exists():
            return []
        raw = gemini_md.read_text(encoding="utf-8", errors="replace")
        clean = _strip_managed_block(raw).strip()
        if not clean:
            return []
        return [ImportedRule(source_file="GEMINI.md", content=clean)]

    def collect_mcp(self) -> list[ImportedMcpServer]:
        settings_json = self.gemini_home / "settings.json"
        if not settings_json.exists():
            return []
        try:
            data = json.loads(settings_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        mcp_raw = data.get("mcpServers") or data.get("mcp_servers") or {}
        return [
            ImportedMcpServer(name=name, config=cfg, source_file="settings.json")
            for name, cfg in mcp_raw.items()
        ]

    def collect_env(self) -> list[ImportedEnvVar]:
        env_file = self.gemini_home / ".env"
        if not env_file.exists():
            return []
        env_vars: list[ImportedEnvVar] = []
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                env_vars.append(ImportedEnvVar(
                    key=key.strip(), value=val.strip().strip('"'),
                    source_file=".gemini/.env",
                ))
        return env_vars


class _OpenCodeImporter:
    """Import from an OpenCode config directory."""

    def __init__(self, opencode_config: Path):
        self.opencode_config = opencode_config

    def collect_rules(self) -> list[ImportedRule]:
        agents_md = self.opencode_config / "AGENTS.md"
        if not agents_md.exists():
            return []
        raw = agents_md.read_text(encoding="utf-8", errors="replace")
        clean = _strip_managed_block(raw).strip()
        if not clean:
            return []
        return [ImportedRule(source_file="AGENTS.md", content=clean)]

    def collect_mcp(self) -> list[ImportedMcpServer]:
        oc_json = self.opencode_config / "opencode.json"
        if not oc_json.exists():
            return []
        try:
            data = json.loads(oc_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        mcp_raw = data.get("mcp") or data.get("mcpServers") or {}
        return [
            ImportedMcpServer(name=name, config=cfg, source_file="opencode.json")
            for name, cfg in mcp_raw.items()
        ]

    def collect_env(self) -> list[ImportedEnvVar]:
        oc_json = self.opencode_config / "opencode.json"
        if not oc_json.exists():
            return []
        try:
            data = json.loads(oc_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        env_raw = data.get("env") or {}
        return [
            ImportedEnvVar(key=k, value=str(v), source_file="opencode.json")
            for k, v in env_raw.items()
        ]


class _CursorImporter:
    """Import from a Cursor project directory."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def collect_rules(self) -> list[ImportedRule]:
        rules: list[ImportedRule] = []

        # .cursor/rules/*.mdc
        cursor_rules = self.project_dir / ".cursor" / "rules"
        if cursor_rules.is_dir():
            for mdc_file in sorted(cursor_rules.glob("*.mdc")):
                if "harnesssync" in mdc_file.name.lower():
                    continue  # Skip files we wrote
                content = _parse_mdc_rules(mdc_file)
                if content:
                    rules.append(ImportedRule(
                        source_file=str(mdc_file.relative_to(self.project_dir)),
                        content=content,
                        section=mdc_file.stem,
                    ))

        # Legacy .cursorrules
        cursorrules = self.project_dir / ".cursorrules"
        if cursorrules.exists():
            content = _strip_managed_block(
                cursorrules.read_text(encoding="utf-8", errors="replace")
            ).strip()
            if content:
                rules.append(ImportedRule(source_file=".cursorrules", content=content))

        return rules

    def collect_mcp(self) -> list[ImportedMcpServer]:
        mcp_json = self.project_dir / ".cursor" / "mcp.json"
        if not mcp_json.exists():
            return []
        try:
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        mcp_raw = data.get("mcpServers") or {}
        return [
            ImportedMcpServer(name=name, config=cfg, source_file=".cursor/mcp.json")
            for name, cfg in mcp_raw.items()
        ]

    def collect_env(self) -> list[ImportedEnvVar]:
        return []  # Cursor doesn't have a separate env file


class _AiderImporter:
    """Import from Aider config files."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def collect_rules(self) -> list[ImportedRule]:
        rules: list[ImportedRule] = []

        for fname in ("CONVENTIONS.md", ".aider.conf.yml"):
            path = self.project_dir / fname
            if path.exists():
                raw = path.read_text(encoding="utf-8", errors="replace")
                clean = _strip_managed_block(raw).strip()
                if clean:
                    rules.append(ImportedRule(source_file=fname, content=clean))

        return rules

    def collect_mcp(self) -> list[ImportedMcpServer]:
        return []  # Aider has no MCP support

    def collect_env(self) -> list[ImportedEnvVar]:
        return []


class _WindsurfImporter:
    """Import from Windsurf config files."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def collect_rules(self) -> list[ImportedRule]:
        windsurfrules = self.project_dir / ".windsurfrules"
        if not windsurfrules.exists():
            return []
        raw = windsurfrules.read_text(encoding="utf-8", errors="replace")
        clean = _strip_managed_block(raw).strip()
        if not clean:
            return []
        return [ImportedRule(source_file=".windsurfrules", content=clean)]

    def collect_mcp(self) -> list[ImportedMcpServer]:
        return []

    def collect_env(self) -> list[ImportedEnvVar]:
        return []


# ── ReverseSync orchestrator ──────────────────────────────────────────────────

class ReverseSync:
    """Orchestrate reverse sync from a target harness to Claude Code.

    Args:
        cc_home:      Claude Code home directory (default: ~/.claude).
        project_dir:  Project root directory. Defaults to current directory.
    """

    _SOURCE_DIRS: dict[str, str] = {
        "codex":    "~",          # project_dir or home
        "gemini":   "~/.gemini",
        "opencode": "~/.config/opencode",
        "cursor":   "~",          # project_dir
        "aider":    "~",          # project_dir
        "windsurf": "~",          # project_dir
    }

    def __init__(
        self,
        cc_home: Path | None = None,
        project_dir: Path | None = None,
    ) -> None:
        self.cc_home = default_cc_home(cc_home)
        self.project_dir = Path(project_dir or ".").resolve()

    # ── Public API ────────────────────────────────────────────────────────────

    def plan(
        self,
        source: str,
        merge_strategy: str = "append",
    ) -> ReverseSyncPlan:
        """Build an import plan for the given source harness.

        Args:
            source:         Source harness name (e.g. "gemini").
            merge_strategy: How to merge rules into CLAUDE.md.

        Returns:
            ReverseSyncPlan with all discovered items.
        """
        source = source.lower().strip()
        plan = ReverseSyncPlan(source=source, merge_strategy=merge_strategy)

        importer = self._build_importer(source)
        if importer is None:
            plan.warnings.append(
                f"Unsupported source harness '{source}'. "
                f"Supported: {', '.join(sorted(self._SOURCE_DIRS))}"
            )
            return plan

        plan.rules = importer.collect_rules()
        plan.mcp_servers = importer.collect_mcp()
        plan.env_vars = importer.collect_env()

        # Detect if content was written by HarnessSync (managed block present)
        if self._all_content_managed(source):
            plan.already_managed = True
            plan.warnings.append(
                "All discovered rules appear to be HarnessSync-managed. "
                "Import would be a no-op (managed blocks are stripped). "
                "Run with --include-managed to override."
            )

        # Warn about potential secret env vars
        for ev in plan.env_vars:
            if self._looks_like_secret(ev.value):
                plan.warnings.append(
                    f"ENV: {ev.key} may contain a literal secret — "
                    "it will be imported as-is. Review before committing."
                )

        return plan

    def execute(
        self,
        plan: ReverseSyncPlan,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Apply the import plan to Claude Code config files.

        Args:
            plan:    Plan returned by :meth:`plan`.
            dry_run: If True, return what would change without writing.

        Returns:
            Result dict with keys:
              - "rules_written": bool
              - "mcp_added": list of server names
              - "env_added": list of env var keys
              - "dry_run": bool
              - "claude_md_path": str or None
        """
        result: dict[str, Any] = {
            "rules_written": False,
            "mcp_added": [],
            "env_added": [],
            "dry_run": dry_run,
            "claude_md_path": None,
        }

        if plan.rules:
            claude_md = self._apply_rules(plan, dry_run=dry_run)
            result["rules_written"] = True
            result["claude_md_path"] = str(claude_md)

        if plan.mcp_servers:
            added = self._apply_mcp(plan.mcp_servers, dry_run=dry_run)
            result["mcp_added"] = added

        if plan.env_vars:
            added = self._apply_env(plan.env_vars, dry_run=dry_run)
            result["env_added"] = added

        return result

    def format_plan(self, plan: ReverseSyncPlan) -> str:
        """Format a human-readable preview of what would be imported.

        Args:
            plan: Plan returned by :meth:`plan`.

        Returns:
            Multi-line string suitable for terminal display.
        """
        lines = [
            f"Reverse Sync Plan: {plan.source} → Claude Code",
            "=" * 50,
        ]

        if not plan.has_content:
            lines.append("  Nothing to import (no content found in source harness).")
        else:
            if plan.rules:
                lines.append(f"\n  Rules ({len(plan.rules)} file(s)):")
                for r in plan.rules:
                    preview = r.content[:80].replace("\n", " ")
                    lines.append(f"    [{r.source_file}] {preview}…")
                lines.append(f"  Merge strategy: {plan.merge_strategy}")

            if plan.mcp_servers:
                lines.append(f"\n  MCP Servers ({len(plan.mcp_servers)}):")
                for s in plan.mcp_servers:
                    cmd = s.config.get("command", s.config.get("url", "?"))
                    lines.append(f"    - {s.name}  ({cmd})")

            if plan.env_vars:
                lines.append(f"\n  Env Vars ({len(plan.env_vars)}):")
                for ev in plan.env_vars:
                    lines.append(f"    {ev.key}=***")

        if plan.already_managed:
            lines.append("\n  NOTE: Content appears to be HarnessSync-managed already.")

        if plan.warnings:
            lines.append("\n  Warnings:")
            for w in plan.warnings:
                lines.append(f"    ! {w}")

        lines.append("")
        if plan.has_content and not plan.already_managed:
            lines.append("Run with --apply to write changes.")
        return "\n".join(lines)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _build_importer(self, source: str):
        """Return the appropriate importer for *source*, or None if unsupported."""
        gemini_home = Path.home() / ".gemini"
        opencode_config = Path.home() / ".config" / "opencode"

        if source == "codex":
            return _CodexImporter(self.project_dir)
        if source == "gemini":
            return _GeminiImporter(gemini_home)
        if source == "opencode":
            return _OpenCodeImporter(opencode_config)
        if source == "cursor":
            return _CursorImporter(self.project_dir)
        if source == "aider":
            return _AiderImporter(self.project_dir)
        if source == "windsurf":
            return _WindsurfImporter(self.project_dir)
        return None

    def _all_content_managed(self, source: str) -> bool:
        """Check if all rule content in source files was written by HarnessSync."""
        importer = self._build_importer(source)
        if importer is None:
            return False
        # If collect_rules returns nothing after stripping managed blocks, it's all managed
        raw_rules = importer.collect_rules()
        return len(raw_rules) == 0

    def _apply_rules(
        self,
        plan: ReverseSyncPlan,
        dry_run: bool,
    ) -> Path:
        """Merge imported rules into the project CLAUDE.md."""
        claude_md = self.project_dir / "CLAUDE.md"

        # Build import block
        imported_text = "\n\n".join(
            f"<!-- Imported from {r.source_file} via reverse-sync -->\n{r.content}"
            for r in plan.rules
        )
        section = (
            f"\n\n<!-- HarnessSync reverse-sync: imported from {plan.source} -->\n"
            f"{imported_text}\n"
            f"<!-- End reverse-sync: {plan.source} -->\n"
        )

        if dry_run:
            return claude_md

        existing = ""
        if claude_md.exists():
            existing = claude_md.read_text(encoding="utf-8", errors="replace")

        strategy = plan.merge_strategy
        if strategy == "prepend":
            new_content = section.lstrip() + "\n" + existing
        elif strategy == "replace":
            # Replace existing reverse-sync block if present, else append
            replace_re = re.compile(
                r"\n*<!-- HarnessSync reverse-sync: imported from [^>]+ -->"
                r".*?<!-- End reverse-sync: [^>]+ -->\n",
                re.DOTALL,
            )
            if replace_re.search(existing):
                new_content = replace_re.sub(section, existing)
            else:
                new_content = existing + section
        elif strategy == "new_file":
            out_path = self.project_dir / f"CLAUDE.from-{plan.source}.md"
            out_path.write_text(section.strip(), encoding="utf-8")
            return out_path
        else:  # append (default)
            new_content = existing + section

        claude_md.write_text(new_content, encoding="utf-8")
        return claude_md

    def _apply_mcp(
        self,
        servers: list[ImportedMcpServer],
        dry_run: bool,
    ) -> list[str]:
        """Merge imported MCP servers into .mcp.json (project scope)."""
        mcp_json = self.project_dir / ".mcp.json"
        added: list[str] = []

        try:
            existing_data: dict[str, Any] = {}
            if mcp_json.exists():
                existing_data = json.loads(mcp_json.read_text(encoding="utf-8")) or {}

            mcp_servers = existing_data.setdefault("mcpServers", {})

            for server in servers:
                if server.name not in mcp_servers:
                    mcp_servers[server.name] = server.config
                    added.append(server.name)

            if added and not dry_run:
                mcp_json.write_text(
                    json.dumps(existing_data, indent=2) + "\n",
                    encoding="utf-8",
                )
        except (json.JSONDecodeError, OSError):
            pass

        return added

    def _apply_env(
        self,
        env_vars: list[ImportedEnvVar],
        dry_run: bool,
    ) -> list[str]:
        """Merge imported env vars into settings.json (project scope)."""
        settings_json = self.project_dir / ".claude" / "settings.json"
        added: list[str] = []

        try:
            existing_data: dict[str, Any] = {}
            if settings_json.exists():
                existing_data = json.loads(settings_json.read_text(encoding="utf-8")) or {}

            env_section = existing_data.setdefault("env", {})

            for ev in env_vars:
                if ev.key not in env_section:
                    env_section[ev.key] = ev.value
                    added.append(ev.key)

            if added and not dry_run:
                settings_json.parent.mkdir(parents=True, exist_ok=True)
                settings_json.write_text(
                    json.dumps(existing_data, indent=2) + "\n",
                    encoding="utf-8",
                )
        except (json.JSONDecodeError, OSError):
            pass

        return added

    @staticmethod
    def _looks_like_secret(value: str) -> bool:
        """Heuristic: does this value look like a literal secret?"""
        if not value:
            return False
        # Variable references are safe
        if value.startswith("$") or "${" in value:
            return False
        # Long alphanumeric strings are suspicious
        stripped = re.sub(r'[^a-zA-Z0-9]', '', value)
        if len(stripped) > 20 and re.search(r'[A-Z]', stripped) and re.search(r'[0-9]', stripped):
            return True
        return False
