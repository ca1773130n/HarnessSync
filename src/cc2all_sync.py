#!/usr/bin/env python3
"""
cc2all-sync: Claude Code → All Harnesses Sync Engine

Syncs Claude Code configuration to:
  - OpenAI Codex CLI    (~/.codex/, .codex/)
  - Gemini CLI           (~/.gemini/, project GEMINI.md)
  - OpenCode             (~/.config/opencode/, .opencode/)

Claude Code is the single source of truth.
Supports both user-scope (global) and project-scope sync.

Usage:
  cc2all-sync.py [--scope user|project|all] [--watch] [--project-dir DIR] [--dry-run] [--verbose]
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ─────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────

VERSION = "1.0.0"

# Claude Code paths
CC_HOME = Path.home() / ".claude"
CC_SETTINGS = CC_HOME / "settings.json"
CC_PLUGINS_REGISTRY = CC_HOME / "plugins" / "installed_plugins.json"
CC_PLUGINS_CACHE = CC_HOME / "plugins" / "cache"
CC_SKILLS = CC_HOME / "skills"
CC_AGENTS = CC_HOME / "agents"
CC_COMMANDS = CC_HOME / "commands"
CC_MCP_JSON = Path.home() / ".mcp.json"

# Codex paths
CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
CODEX_SKILLS = CODEX_HOME / "skills"
CODEX_AGENTS_MD = CODEX_HOME / "AGENTS.md"
CODEX_CONFIG_TOML = CODEX_HOME / "config.toml"

# Gemini paths
GEMINI_HOME = Path.home() / ".gemini"
GEMINI_MD = GEMINI_HOME / "GEMINI.md"
GEMINI_SETTINGS = GEMINI_HOME / "settings.json"
GEMINI_EXTENSIONS = GEMINI_HOME / "extensions"

# OpenCode paths
OC_HOME = Path.home() / ".config" / "opencode"
OC_AGENTS_MD = OC_HOME / "AGENTS.md"
OC_SKILLS = OC_HOME / "skills"
OC_AGENTS = OC_HOME / "agents"
OC_COMMANDS = OC_HOME / "commands"
OC_CONFIG = OC_HOME / "opencode.json"

# State file
STATE_DIR = Path.home() / ".cc2all"
STATE_FILE = STATE_DIR / "sync-state.json"
LOG_DIR = STATE_DIR / "logs"

# ─────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────

class Logger:
    COLORS = {
        "reset": "\033[0m", "bold": "\033[1m",
        "red": "\033[31m", "green": "\033[32m",
        "yellow": "\033[33m", "blue": "\033[34m",
        "cyan": "\033[36m", "dim": "\033[2m",
    }

    def __init__(self, verbose=False):
        self.verbose = verbose
        self._counts = {"synced": 0, "skipped": 0, "error": 0, "cleaned": 0}

    def _c(self, color, text):
        return f"{self.COLORS.get(color, '')}{text}{self.COLORS['reset']}"

    def info(self, msg): print(f"  {self._c('green', '✓')} {msg}")
    def warn(self, msg): print(f"  {self._c('yellow', '⚠')} {msg}")
    def error(self, msg): print(f"  {self._c('red', '✗')} {msg}"); self._counts["error"] += 1
    def skip(self, msg):
        if self.verbose: print(f"  {self._c('dim', '·')} {msg}")
        self._counts["skipped"] += 1
    def debug(self, msg):
        if self.verbose: print(f"  {self._c('dim', '  ')} {msg}")
    def header(self, msg): print(f"\n{self._c('bold', self._c('blue', f'[{msg}]'))}")
    def synced(self): self._counts["synced"] += 1
    def cleaned(self): self._counts["cleaned"] += 1

    def summary(self):
        c = self._counts
        parts = []
        if c["synced"]: parts.append(self._c("green", f"{c['synced']} synced"))
        if c["skipped"]: parts.append(self._c("dim", f"{c['skipped']} skipped"))
        if c["cleaned"]: parts.append(self._c("yellow", f"{c['cleaned']} cleaned"))
        if c["error"]: parts.append(self._c("red", f"{c['error']} errors"))
        return ", ".join(parts) if parts else "nothing to do"


log = Logger()


def ensure_dir(path: Path):
    path.mkdir(parents=True, exist_ok=True)


def file_hash(path: Path) -> str:
    """SHA256 of file contents for change detection."""
    if not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.error(f"Failed to read {path}: {e}")
        return {}


def write_json(path: Path, data: dict):
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text(path: Path, content: str):
    ensure_dir(path.parent)
    path.write_text(content, encoding="utf-8")


def safe_symlink(src: Path, dst: Path):
    """Create symlink, replacing existing if needed."""
    if dst.is_symlink():
        if dst.resolve() == src.resolve():
            return False  # already correct
        dst.unlink()
    elif dst.exists():
        shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
    ensure_dir(dst.parent)
    dst.symlink_to(src)
    return True


def load_state() -> dict:
    return read_json(STATE_FILE) if STATE_FILE.exists() else {}


def save_state(state: dict):
    ensure_dir(STATE_DIR)
    write_json(STATE_FILE, state)


# ─────────────────────────────────────────────
# Source: Claude Code Configuration Reader
# ─────────────────────────────────────────────

def get_cc_rules(scope: str, project_dir: Path = None) -> str:
    """Read CLAUDE.md rules. scope: 'user' or 'project'."""
    rules = []
    if scope in ("user", "all"):
        # User-level CLAUDE.md
        user_claude_md = CC_HOME / "CLAUDE.md"
        if user_claude_md.exists():
            rules.append(f"# [User-level rules from ~/.claude/CLAUDE.md]\n\n{user_claude_md.read_text()}")

    if scope in ("project", "all") and project_dir:
        # Project-level CLAUDE.md (walk from project root)
        for claude_md_name in ["CLAUDE.md", "CLAUDE.local.md"]:
            p = project_dir / claude_md_name
            if p.exists():
                rules.append(f"# [Project rules from {p.relative_to(project_dir)}]\n\n{p.read_text()}")
        # Also check .claude/ subdirectory
        p = project_dir / ".claude" / "CLAUDE.md"
        if p.exists():
            rules.append(f"# [Project rules from .claude/CLAUDE.md]\n\n{p.read_text()}")

    return "\n\n---\n\n".join(rules)


def get_cc_skills(scope: str, project_dir: Path = None) -> dict[str, Path]:
    """Discover Claude Code skills. Returns {name: path_to_skill_dir}."""
    skills = {}

    if scope in ("user", "all"):
        # User-level skills
        if CC_SKILLS.is_dir():
            for d in CC_SKILLS.iterdir():
                skill_md = d / "SKILL.md"
                if d.is_dir() and skill_md.exists():
                    skills[d.name] = d

        # Plugin-installed skills
        if CC_PLUGINS_REGISTRY.exists():
            registry = read_json(CC_PLUGINS_REGISTRY)
            plugins_data = registry.get("plugins", {})

            # Handle both dict and list formats
            plugin_entries = []
            if isinstance(plugins_data, dict):
                plugin_entries = plugins_data.values()
            elif isinstance(plugins_data, list):
                plugin_entries = plugins_data

            for plugin_info in plugin_entries:
                if not isinstance(plugin_info, dict):
                    continue
                if plugin_info.get("scope") != "user":
                    continue
                install_path = plugin_info.get("installPath", "")
                if not install_path:
                    continue
                p = Path(install_path)
                # Scan for skills inside the plugin
                skills_dir = p / "skills"
                if skills_dir.is_dir():
                    for d in skills_dir.iterdir():
                        if d.is_dir() and (d / "SKILL.md").exists():
                            skills[d.name] = d

    if scope in ("project", "all") and project_dir:
        proj_skills = project_dir / ".claude" / "skills"
        if proj_skills.is_dir():
            for d in proj_skills.iterdir():
                if d.is_dir() and (d / "SKILL.md").exists():
                    skills[d.name] = d

    return skills


def get_cc_agents(scope: str, project_dir: Path = None) -> dict[str, Path]:
    """Discover Claude Code agent definitions."""
    agents = {}

    if scope in ("user", "all"):
        if CC_AGENTS.is_dir():
            for f in CC_AGENTS.iterdir():
                if f.suffix == ".md":
                    agents[f.stem] = f

    if scope in ("project", "all") and project_dir:
        proj_agents = project_dir / ".claude" / "agents"
        if proj_agents.is_dir():
            for f in proj_agents.iterdir():
                if f.suffix == ".md":
                    agents[f.stem] = f

    return agents


def get_cc_commands(scope: str, project_dir: Path = None) -> dict[str, Path]:
    """Discover Claude Code slash commands."""
    commands = {}

    if scope in ("user", "all"):
        if CC_COMMANDS.is_dir():
            for f in CC_COMMANDS.iterdir():
                if f.suffix == ".md":
                    commands[f.stem] = f

    if scope in ("project", "all") and project_dir:
        proj_cmds = project_dir / ".claude" / "commands"
        if proj_cmds.is_dir():
            for f in proj_cmds.iterdir():
                if f.suffix == ".md":
                    commands[f.stem] = f

    return commands


def get_cc_mcp(scope: str, project_dir: Path = None) -> dict:
    """Read MCP server configurations."""
    servers = {}

    if scope in ("user", "all"):
        # Global MCP
        if CC_MCP_JSON.exists():
            data = read_json(CC_MCP_JSON)
            servers.update(data.get("mcpServers", {}))
        # Also check ~/.claude/.mcp.json
        cc_mcp = CC_HOME / ".mcp.json"
        if cc_mcp.exists():
            data = read_json(cc_mcp)
            servers.update(data.get("mcpServers", {}))

    if scope in ("project", "all") and project_dir:
        proj_mcp = project_dir / ".mcp.json"
        if proj_mcp.exists():
            data = read_json(proj_mcp)
            servers.update(data.get("mcpServers", {}))

    return servers


def get_cc_settings(scope: str, project_dir: Path = None) -> dict:
    """Read Claude Code settings for scope sync."""
    settings = {}
    if scope in ("user", "all"):
        settings.update(read_json(CC_SETTINGS))
    if scope in ("project", "all") and project_dir:
        proj_settings = project_dir / ".claude" / "settings.json"
        if proj_settings.exists():
            proj_data = read_json(proj_settings)
            settings.update(proj_data)
        local_settings = project_dir / ".claude" / "settings.local.json"
        if local_settings.exists():
            local_data = read_json(local_settings)
            settings.update(local_data)
    return settings


# ─────────────────────────────────────────────
# Target: OpenAI Codex
# ─────────────────────────────────────────────

def sync_to_codex(scope: str, project_dir: Path = None, dry_run: bool = False):
    log.header("Codex CLI")

    # Determine target directories
    if scope == "project" and project_dir:
        target_skills = project_dir / ".codex" / "skills"
        target_agents_md = project_dir / ".codex" / "AGENTS.md"  # project only uses .codex/ not .agents/
        target_agents_skills = project_dir / ".agents" / "skills"  # Codex also reads .agents/skills/
    else:
        target_skills = CODEX_SKILLS
        target_agents_md = CODEX_AGENTS_MD
        target_agents_skills = None

    # 1. Rules → AGENTS.md
    rules = get_cc_rules(scope, project_dir)
    if rules:
        header = "# Auto-synced from Claude Code (cc2all)\n# Do not edit — changes will be overwritten\n\n"
        content = header + rules
        if not dry_run:
            write_text(target_agents_md, content)
        log.info(f"Rules → {target_agents_md}")
        log.synced()
    else:
        log.skip("No CLAUDE.md rules found")

    # 2. Skills → symlinks
    skills = get_cc_skills(scope, project_dir)
    synced_skills = set()
    for name, path in skills.items():
        dst = target_skills / name
        if not dry_run:
            if safe_symlink(path, dst):
                log.info(f"Skill: {name} → symlink")
                log.synced()
            else:
                log.skip(f"Skill: {name} (unchanged)")
        else:
            log.info(f"[dry-run] Skill: {name} → {dst}")
        synced_skills.add(name)

    # Also create in .agents/skills/ for Codex compatibility
    if target_agents_skills and not dry_run:
        for name, path in skills.items():
            dst = target_agents_skills / name
            safe_symlink(path, dst)

    # 3. Agents → convert to SKILL.md format (Codex doesn't have agents)
    agents = get_cc_agents(scope, project_dir)
    for name, path in agents.items():
        if name in synced_skills:
            continue
        content = path.read_text()
        # Extract description from frontmatter if present
        desc = f"Agent definition for {name}. Converted from Claude Code agent."
        fm_match = re.search(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if fm_match:
            for line in fm_match.group(1).split("\n"):
                if line.strip().startswith("description:"):
                    desc = line.split(":", 1)[1].strip().strip('"\'')
                    break

        skill_md = f"---\nname: agent-{name}\ndescription: {desc}\n---\n\n{content}"
        dst = target_skills / f"agent-{name}"
        if not dry_run:
            ensure_dir(dst)
            write_text(dst / "SKILL.md", skill_md)
            log.info(f"Agent → Skill: agent-{name}")
            log.synced()
        synced_skills.add(f"agent-{name}")

    # 4. Commands → convert to SKILL.md
    commands = get_cc_commands(scope, project_dir)
    for name, path in commands.items():
        content = path.read_text()
        skill_md = (
            f"---\nname: cmd-{name}\n"
            f"description: Slash command '{name}' converted from Claude Code.\n---\n\n"
            f"# /{name}\n\n{content}"
        )
        dst = target_skills / f"cmd-{name}"
        if not dry_run:
            ensure_dir(dst)
            write_text(dst / "SKILL.md", skill_md)
            log.info(f"Command → Skill: cmd-{name}")
            log.synced()
        synced_skills.add(f"cmd-{name}")

    # 5. MCP → config.toml [mcp_servers]
    mcp_servers = get_cc_mcp(scope, project_dir)
    if mcp_servers:
        toml_target = (project_dir / ".codex" / "config.toml") if (scope == "project" and project_dir) else CODEX_CONFIG_TOML
        toml_content = _build_codex_mcp_toml(mcp_servers, toml_target)
        if not dry_run:
            write_text(toml_target, toml_content)
            log.info(f"MCP servers ({len(mcp_servers)}) → {toml_target}")
            log.synced()

    # 6. Cleanup stale symlinks in target skills dir
    if target_skills.is_dir() and not dry_run:
        for d in target_skills.iterdir():
            if d.is_symlink() and not d.resolve().exists():
                d.unlink()
                log.info(f"Cleaned stale: {d.name}")
                log.cleaned()


def _build_codex_mcp_toml(mcp_servers: dict, existing_toml: Path) -> str:
    """Build/merge MCP section into Codex config.toml."""
    # Read existing config (preserve non-MCP sections)
    existing = ""
    if existing_toml.exists():
        existing = existing_toml.read_text()

    # Remove existing [mcp_servers] sections added by cc2all
    lines = existing.split("\n")
    filtered = []
    in_cc2all_mcp = False
    for line in lines:
        if line.strip() == "# --- cc2all MCP start ---":
            in_cc2all_mcp = True
            continue
        if line.strip() == "# --- cc2all MCP end ---":
            in_cc2all_mcp = False
            continue
        if not in_cc2all_mcp:
            filtered.append(line)

    base = "\n".join(filtered).rstrip()

    # Build MCP TOML sections
    mcp_lines = ["\n# --- cc2all MCP start ---"]
    for name, config in mcp_servers.items():
        cmd = config.get("command", "")
        args = config.get("args", [])
        env = config.get("env", {})

        mcp_lines.append(f'\n[mcp_servers."{name}"]')
        if config.get("type") == "url" or config.get("url"):
            url = config.get("url", "")
            mcp_lines.append(f'type = "url"')
            mcp_lines.append(f'url = "{url}"')
        else:
            mcp_lines.append(f'command = "{cmd}"')
            if args:
                args_str = ", ".join(f'"{a}"' for a in args)
                mcp_lines.append(f'args = [{args_str}]')

        if env:
            mcp_lines.append(f'[mcp_servers."{name}".env]')
            for k, v in env.items():
                mcp_lines.append(f'{k} = "{v}"')

    mcp_lines.append("# --- cc2all MCP end ---")

    return base + "\n" + "\n".join(mcp_lines) + "\n"


# ─────────────────────────────────────────────
# Target: Gemini CLI
# ─────────────────────────────────────────────

def sync_to_gemini(scope: str, project_dir: Path = None, dry_run: bool = False):
    log.header("Gemini CLI")

    # Determine target
    if scope == "project" and project_dir:
        target_md = project_dir / "GEMINI.md"
    else:
        target_md = GEMINI_MD

    # 1. Rules → GEMINI.md
    rules = get_cc_rules(scope, project_dir)

    # 2. Skills → Append skill references to GEMINI.md
    skills = get_cc_skills(scope, project_dir)
    skill_sections = []
    for name, path in skills.items():
        skill_md = path / "SKILL.md"
        if skill_md.exists():
            content = skill_md.read_text()
            # Strip YAML frontmatter for Gemini (it just uses plain markdown)
            content = re.sub(r'^---\s*\n.*?\n---\s*\n', '', content, flags=re.DOTALL)
            skill_sections.append(f"## Skill: {name}\n\n{content}")

    # 3. Agents → Append agent descriptions
    agents = get_cc_agents(scope, project_dir)
    agent_sections = []
    for name, path in agents.items():
        content = path.read_text()
        agent_sections.append(f"## Agent: {name}\n\n{content}")

    # 4. Commands → Brief descriptions
    commands = get_cc_commands(scope, project_dir)
    cmd_section = ""
    if commands:
        cmd_lines = ["## Available Commands\n"]
        for name, path in commands.items():
            first_line = path.read_text().strip().split("\n")[0]
            cmd_lines.append(f"- **/{name}**: {first_line}")
        cmd_section = "\n".join(cmd_lines)

    # Build GEMINI.md
    parts = ["# Auto-synced from Claude Code (cc2all)\n# Do not edit — changes will be overwritten\n"]
    if rules:
        parts.append(rules)
    if skill_sections:
        parts.append("\n---\n\n# Skills\n\n" + "\n\n".join(skill_sections))
    if agent_sections:
        parts.append("\n---\n\n# Agents\n\n" + "\n\n".join(agent_sections))
    if cmd_section:
        parts.append("\n---\n\n" + cmd_section)

    full_content = "\n\n".join(parts)

    if full_content.strip():
        if not dry_run:
            write_text(target_md, full_content)
        log.info(f"GEMINI.md → {target_md}")
        log.synced()
    else:
        log.skip("No content to sync to Gemini")

    # 5. MCP → Gemini settings.json mcpServers
    mcp_servers = get_cc_mcp(scope, project_dir)
    if mcp_servers:
        target_settings = (project_dir / ".gemini" / "settings.json") if (scope == "project" and project_dir) else GEMINI_SETTINGS
        _sync_gemini_mcp(mcp_servers, target_settings, dry_run)


def _sync_gemini_mcp(mcp_servers: dict, target: Path, dry_run: bool):
    """Sync MCP servers to Gemini settings.json format."""
    existing = read_json(target) if target.exists() else {}

    gemini_mcp = {}
    for name, config in mcp_servers.items():
        cmd = config.get("command", "")
        args = config.get("args", [])
        env = config.get("env", {})

        if config.get("type") == "url" or config.get("url"):
            # Gemini uses 'sse' type for remote servers
            gemini_mcp[name] = {
                "command": "npx",
                "args": ["-y", "mcp-remote", config.get("url", "")]
            }
        else:
            entry = {"command": cmd}
            if args:
                entry["args"] = args
            if env:
                entry["env"] = env
            gemini_mcp[name] = entry

    existing["mcpServers"] = gemini_mcp
    if not dry_run:
        write_json(target, existing)
        log.info(f"MCP servers ({len(mcp_servers)}) → {target}")
        log.synced()


# ─────────────────────────────────────────────
# Target: OpenCode
# ─────────────────────────────────────────────

def sync_to_opencode(scope: str, project_dir: Path = None, dry_run: bool = False):
    log.header("OpenCode")

    # OpenCode has built-in Claude Code compatibility:
    #   - Reads ~/.claude/CLAUDE.md as fallback for AGENTS.md
    #   - Reads ~/.claude/skills/ as fallback for skills
    # But we still sync explicitly for:
    #   - Agents (OpenCode has its own format)
    #   - Commands (OpenCode supports them)
    #   - MCP (different config format)
    #   - AGENTS.md (explicit is better than fallback)

    if scope == "project" and project_dir:
        target_agents_md = project_dir / ".opencode" / "AGENTS.md"
        target_skills = project_dir / ".opencode" / "skills"
        target_agents = project_dir / ".opencode" / "agents"
        target_commands = project_dir / ".opencode" / "commands"
        target_config = project_dir / "opencode.json"
    else:
        target_agents_md = OC_AGENTS_MD
        target_skills = OC_SKILLS
        target_agents = OC_AGENTS
        target_commands = OC_COMMANDS
        target_config = OC_CONFIG

    # 1. Rules → AGENTS.md
    rules = get_cc_rules(scope, project_dir)
    if rules:
        header = "# Auto-synced from Claude Code (cc2all)\n# Do not edit — changes will be overwritten\n\n"
        if not dry_run:
            write_text(target_agents_md, header + rules)
        log.info(f"Rules → {target_agents_md}")
        log.synced()
    else:
        log.skip("No rules to sync")

    # 2. Skills → symlinks (OpenCode reads .claude/skills/ as fallback,
    #    but explicit .opencode/skills/ takes precedence)
    skills = get_cc_skills(scope, project_dir)
    for name, path in skills.items():
        dst = target_skills / name
        if not dry_run:
            if safe_symlink(path, dst):
                log.info(f"Skill: {name} → symlink")
                log.synced()
            else:
                log.skip(f"Skill: {name} (unchanged)")

    # 3. Agents → symlinks or copies (OpenCode uses similar .md format)
    agents = get_cc_agents(scope, project_dir)
    for name, path in agents.items():
        dst = target_agents / f"{name}.md"
        if not dry_run:
            ensure_dir(dst.parent)
            # OpenCode agent .md format is compatible, just symlink
            if safe_symlink(path, dst):
                log.info(f"Agent: {name} → symlink")
                log.synced()
            else:
                log.skip(f"Agent: {name} (unchanged)")

    # 4. Commands → symlinks (OpenCode supports commands/ dir)
    commands = get_cc_commands(scope, project_dir)
    for name, path in commands.items():
        dst = target_commands / f"{name}.md"
        if not dry_run:
            ensure_dir(dst.parent)
            if safe_symlink(path, dst):
                log.info(f"Command: {name} → symlink")
                log.synced()
            else:
                log.skip(f"Command: {name} (unchanged)")

    # 5. MCP → opencode.json mcpServers
    mcp_servers = get_cc_mcp(scope, project_dir)
    if mcp_servers:
        _sync_opencode_mcp(mcp_servers, target_config, dry_run)

    # 6. Cleanup stale symlinks
    if not dry_run:
        for target_dir in [target_skills, target_agents, target_commands]:
            if target_dir.is_dir():
                for item in target_dir.iterdir():
                    if item.is_symlink() and not item.resolve().exists():
                        item.unlink()
                        log.info(f"Cleaned stale: {item.name}")
                        log.cleaned()


def _sync_opencode_mcp(mcp_servers: dict, target: Path, dry_run: bool):
    """Sync MCP servers to opencode.json format."""
    existing = read_json(target) if target.exists() else {}

    oc_mcp = {}
    for name, config in mcp_servers.items():
        cmd = config.get("command", "")
        args = config.get("args", [])
        env = config.get("env", {})

        if config.get("type") == "url" or config.get("url"):
            oc_mcp[name] = {
                "type": "remote",
                "url": config.get("url", "")
            }
        else:
            entry = {"command": cmd}
            if args:
                entry["args"] = args
            if env:
                entry["env"] = env
            oc_mcp[name] = entry

    existing["mcpServers"] = oc_mcp

    # Mark as cc2all managed
    existing["_cc2all"] = {"synced_at": datetime.now().isoformat(), "version": VERSION}

    if not dry_run:
        write_json(target, existing)
        log.info(f"MCP servers ({len(mcp_servers)}) → {target}")
        log.synced()


# ─────────────────────────────────────────────
# Project Scope Settings Sync
# ─────────────────────────────────────────────

def sync_project_settings(project_dir: Path, dry_run: bool = False):
    """Sync project-level settings (allowedTools, env, permissions, etc.)."""
    settings = get_cc_settings("project", project_dir)
    if not settings:
        return

    log.header("Project Settings Sync")

    # Extract relevant settings
    env_vars = settings.get("env", {})
    allowed_tools = settings.get("allowedTools", [])

    # Codex: env → [shell_environment_policy] in .codex/config.toml
    if env_vars:
        codex_toml = project_dir / ".codex" / "config.toml"
        existing = codex_toml.read_text() if codex_toml.exists() else ""
        # Remove old cc2all env section
        existing = re.sub(
            r'\n?# --- cc2all env start ---.*?# --- cc2all env end ---\n?',
            '', existing, flags=re.DOTALL
        )
        env_lines = ["\n# --- cc2all env start ---", "[shell_environment_policy]"]
        env_lines.append(f'include_only = [{", ".join(repr(k) for k in env_vars.keys())}]')
        env_lines.append("# --- cc2all env end ---")
        if not dry_run:
            write_text(codex_toml, existing.rstrip() + "\n" + "\n".join(env_lines) + "\n")
        log.info(f"Env vars → Codex config.toml")
        log.synced()

    # Gemini: env → .gemini/.env
    if env_vars:
        gemini_env = project_dir / ".gemini" / ".env"
        env_content = "# Auto-synced from Claude Code (cc2all)\n"
        for k, v in env_vars.items():
            env_content += f"{k}={v}\n"
        if not dry_run:
            write_text(gemini_env, env_content)
        log.info(f"Env vars → Gemini .env")
        log.synced()

    # OpenCode: env → opencode.json env
    if env_vars:
        oc_config_path = project_dir / "opencode.json"
        oc_config = read_json(oc_config_path) if oc_config_path.exists() else {}
        oc_config["env"] = env_vars
        if not dry_run:
            write_json(oc_config_path, oc_config)
        log.info(f"Env vars → OpenCode config")
        log.synced()


# ─────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────

def run_sync(scope: str, project_dir: Path = None, dry_run: bool = False):
    """Main sync entry point."""
    start = time.time()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'─' * 50}")
    print(f"  cc2all sync v{VERSION} — {now}")
    print(f"  scope: {scope}" + (f"  project: {project_dir}" if project_dir else ""))
    print(f"{'─' * 50}")

    if scope in ("user", "all"):
        sync_to_codex("user", dry_run=dry_run)
        sync_to_gemini("user", dry_run=dry_run)
        sync_to_opencode("user", dry_run=dry_run)

    if scope in ("project", "all") and project_dir:
        sync_to_codex("project", project_dir, dry_run=dry_run)
        sync_to_gemini("project", project_dir, dry_run=dry_run)
        sync_to_opencode("project", project_dir, dry_run=dry_run)
        sync_project_settings(project_dir, dry_run=dry_run)

    elapsed = time.time() - start
    print(f"\n{'─' * 50}")
    print(f"  Done in {elapsed*1000:.0f}ms — {log.summary()}")
    print(f"{'─' * 50}\n")

    # Save state
    state = load_state()
    state["last_sync"] = now
    state["scope"] = scope
    state["elapsed_ms"] = int(elapsed * 1000)
    save_state(state)


# ─────────────────────────────────────────────
# Watch mode (fswatch / inotify)
# ─────────────────────────────────────────────

def watch_and_sync(scope: str, project_dir: Path = None):
    """Watch Claude Code config dirs for changes and auto-sync."""
    watch_paths = []

    if scope in ("user", "all"):
        watch_paths.extend([
            str(CC_HOME),
            str(CC_MCP_JSON) if CC_MCP_JSON.exists() else None,
        ])

    if scope in ("project", "all") and project_dir:
        watch_paths.extend([
            str(project_dir / "CLAUDE.md"),
            str(project_dir / "CLAUDE.local.md"),
            str(project_dir / ".claude"),
            str(project_dir / ".mcp.json"),
        ])

    watch_paths = [p for p in watch_paths if p and Path(p).exists()]

    if not watch_paths:
        log.error("No paths to watch. Ensure Claude Code config exists.")
        return

    print(f"👁️  Watching for changes... (Ctrl+C to stop)")
    print(f"   Paths: {', '.join(watch_paths)}")

    # Try fswatch (macOS), fall back to inotifywait (Linux), then polling
    if shutil.which("fswatch"):
        _watch_fswatch(watch_paths, scope, project_dir)
    elif shutil.which("inotifywait"):
        _watch_inotify(watch_paths, scope, project_dir)
    else:
        _watch_polling(watch_paths, scope, project_dir)


def _reset_log():
    global log
    log = Logger(log.verbose)


def _watch_fswatch(paths: list, scope: str, project_dir: Path):
    cmd = ["fswatch", "-r", "-l", "2", "--event", "Updated", "--event", "Created",
           "--event", "Removed", "--event", "Renamed"] + paths
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    try:
        cooldown = 0
        for line in proc.stdout:
            now = time.time()
            if now - cooldown < 3:
                continue
            cooldown = now
            _reset_log()
            run_sync(scope, project_dir)
    except KeyboardInterrupt:
        proc.terminate()


def _watch_inotify(paths: list, scope: str, project_dir: Path):
    cmd = ["inotifywait", "-mrq", "-e", "modify,create,delete,move"] + paths
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    try:
        cooldown = 0
        for line in proc.stdout:
            now = time.time()
            if now - cooldown < 3:
                continue
            cooldown = now
            _reset_log()
            run_sync(scope, project_dir)
    except KeyboardInterrupt:
        proc.terminate()


def _watch_polling(paths: list, scope: str, project_dir: Path):
    """Fallback: poll for changes every 5 seconds."""
    log.warn("No fswatch/inotifywait found, using polling (5s interval)")
    hashes = {}
    for p in paths:
        pp = Path(p)
        if pp.is_file():
            hashes[p] = file_hash(pp)

    try:
        while True:
            time.sleep(5)
            changed = False
            for p in paths:
                pp = Path(p)
                if pp.is_file():
                    h = file_hash(pp)
                    if hashes.get(p) != h:
                        hashes[p] = h
                        changed = True
                elif pp.is_dir():
                    current = str(pp.stat().st_mtime)
                    if hashes.get(p) != current:
                        hashes[p] = current
                        changed = True
            if changed:
                _reset_log()
                run_sync(scope, project_dir)
    except KeyboardInterrupt:
        pass


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def detect_project_dir() -> Path | None:
    """Find project root by walking up to find .git."""
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".git").exists():
            return parent
    return None


def main():
    parser = argparse.ArgumentParser(
        description="cc2all: Sync Claude Code config to Codex, Gemini CLI, and OpenCode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  cc2all-sync.py                       # Auto-detect scope, sync once
  cc2all-sync.py --scope user          # Sync user-level config only
  cc2all-sync.py --scope project       # Sync current project only
  cc2all-sync.py --scope all           # Sync both user and project
  cc2all-sync.py --watch               # Watch for changes and auto-sync
  cc2all-sync.py --watch --scope all   # Watch all scopes
  cc2all-sync.py --dry-run             # Preview changes without writing
        """
    )
    parser.add_argument("--scope", choices=["user", "project", "all"], default="all",
                        help="Sync scope (default: all)")
    parser.add_argument("--watch", "-w", action="store_true",
                        help="Watch for changes and auto-sync")
    parser.add_argument("--project-dir", "-p", type=Path, default=None,
                        help="Project directory (auto-detected if not specified)")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="Preview changes without writing")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show detailed output")
    parser.add_argument("--version", action="version", version=f"cc2all {VERSION}")

    args = parser.parse_args()

    global log
    log = Logger(verbose=args.verbose)

    # Auto-detect project dir
    project_dir = args.project_dir or detect_project_dir()

    if args.scope in ("project", "all") and not project_dir:
        if args.scope == "project":
            log.error("No project detected (no .git found). Use --project-dir or run from a git repo.")
            sys.exit(1)
        # If scope=all but no project, just do user
        args.scope = "user"
        log.warn("No project detected, syncing user-scope only")

    if args.watch:
        run_sync(args.scope, project_dir, args.dry_run)
        watch_and_sync(args.scope, project_dir)
    else:
        run_sync(args.scope, project_dir, args.dry_run)


if __name__ == "__main__":
    main()
