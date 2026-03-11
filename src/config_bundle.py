from __future__ import annotations

"""Shareable config bundle export/import.

Export your entire HarnessSync setup — CLAUDE.md, all adapter translations,
MCP server configs — as a single portable JSON bundle that a colleague can
import. Solves team onboarding: 'import this and you're set across all
harnesses in 30 seconds.'

Bundle format (JSON):
{
    "version": "1",
    "created_at": "2025-03-11T12:00:00",
    "creator": "username@hostname",
    "project_dir": "/path/to/project",  // stripped to basename for portability
    "files": {
        "CLAUDE.md": "<content>",
        "AGENTS.md": "<content>",
        ...
    },
    "mcp_servers": { ... },   // env values redacted
    "settings_summary": {     // non-sensitive settings only
        "approval_mode": "...",
        "shell": "..."
    }
}
"""

import getpass
import json
import socket
from datetime import datetime, timezone
from pathlib import Path


# Files included in a bundle (relative to project root)
_BUNDLE_FILES: list[str] = [
    "CLAUDE.md",
    "CLAUDE.local.md",
    "AGENTS.md",
    "GEMINI.md",
    "CONVENTIONS.md",
    ".windsurfrules",
    ".cursor/rules/claude-code-rules.mdc",
    ".harness-sync/team-profile.json",
]

# Sensitive MCP env keys to redact in bundles
_REDACTED_SENTINEL = "<REDACTED>"
_SECRET_ENV_KEYWORDS = ("key", "secret", "password", "token", "passwd", "pwd")


def _redact_mcp_env(mcp_servers: dict) -> dict:
    """Return a copy of mcp_servers with sensitive env values redacted.

    Args:
        mcp_servers: MCP server configuration dict.

    Returns:
        Deep copy with sensitive env var values replaced by <REDACTED>.
    """
    redacted: dict = {}
    for name, cfg in mcp_servers.items():
        if not isinstance(cfg, dict):
            redacted[name] = cfg
            continue
        cfg_copy = dict(cfg)
        env = cfg_copy.get("env", {})
        if isinstance(env, dict):
            cfg_copy["env"] = {
                k: (_REDACTED_SENTINEL if any(kw in k.lower() for kw in _SECRET_ENV_KEYWORDS) else v)
                for k, v in env.items()
            }
        redacted[name] = cfg_copy
    return redacted


class ConfigBundle:
    """Export and import HarnessSync configuration bundles.

    Args:
        project_dir: Project root directory.
    """

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir

    def export(
        self,
        output_path: Path | None = None,
        include_mcp: bool = True,
        redact_secrets: bool = True,
    ) -> dict:
        """Build and optionally write a config bundle.

        Args:
            output_path: If provided, write the bundle JSON here.
            include_mcp: Include MCP server configs (env values redacted).
            redact_secrets: Redact sensitive env var values (default: True).

        Returns:
            Bundle dict.
        """
        bundle: dict = {
            "version": "1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "creator": self._creator_string(),
            "project_basename": self.project_dir.name,
            "files": {},
        }

        # Collect files
        for rel in _BUNDLE_FILES:
            path = self.project_dir / rel
            if path.is_file():
                try:
                    bundle["files"][rel] = path.read_text(encoding="utf-8")
                except OSError:
                    pass

        # Also include CLAUDE.<target>.md override files if present
        for target in ("codex", "gemini", "opencode", "cursor", "aider", "windsurf"):
            override = self.project_dir / f"CLAUDE.{target}.md"
            if override.is_file():
                try:
                    bundle["files"][f"CLAUDE.{target}.md"] = override.read_text(encoding="utf-8")
                except OSError:
                    pass

        # MCP servers
        if include_mcp:
            mcp = self._collect_mcp()
            if redact_secrets:
                mcp = _redact_mcp_env(mcp)
            bundle["mcp_servers"] = mcp

        if output_path:
            output_path.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")

        return bundle

    def import_bundle(
        self,
        bundle: dict | Path,
        dry_run: bool = False,
        overwrite: bool = False,
    ) -> list[str]:
        """Import a config bundle into the project directory.

        Args:
            bundle: Bundle dict or path to a bundle JSON file.
            dry_run: If True, report what would be written without writing.
            overwrite: If False, skip files that already exist.

        Returns:
            List of result messages (one per file).
        """
        if isinstance(bundle, Path):
            bundle = json.loads(bundle.read_text(encoding="utf-8"))

        if not isinstance(bundle, dict) or bundle.get("version") != "1":
            return ["Error: invalid bundle format (expected version '1')"]

        messages: list[str] = []
        files = bundle.get("files", {})

        for rel, content in files.items():
            target_path = self.project_dir / rel
            action = "would write" if dry_run else "written"

            if target_path.exists() and not overwrite:
                messages.append(f"Skipped {rel} (already exists — use --overwrite to replace)")
                continue

            if dry_run:
                lines = content.count("\n") + 1
                messages.append(f"[dry-run] {action}: {rel} ({lines} lines)")
                continue

            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(content, encoding="utf-8")
                messages.append(f"{action}: {rel}")
            except OSError as e:
                messages.append(f"Error writing {rel}: {e}")

        if not dry_run and files:
            messages.append(
                f"\nBundle imported from {bundle.get('creator', 'unknown')} "
                f"(created {bundle.get('created_at', '?')[:10]}). "
                "Run /sync to apply to all harnesses."
            )

        return messages

    def format_bundle_summary(self, bundle: dict) -> str:
        """Format a human-readable summary of a bundle.

        Args:
            bundle: Bundle dict.

        Returns:
            Formatted summary string.
        """
        files = bundle.get("files", {})
        mcp = bundle.get("mcp_servers", {})
        lines = [
            "Config Bundle Summary",
            "=" * 40,
            f"  Created:  {bundle.get('created_at', '?')[:19]}",
            f"  Creator:  {bundle.get('creator', 'unknown')}",
            f"  Project:  {bundle.get('project_basename', '?')}",
            f"  Files:    {len(files)}",
            f"  MCP:      {len(mcp)} servers",
            "",
            "Files included:",
        ]
        for rel in sorted(files):
            size = len(files[rel])
            lines.append(f"  {rel} ({size:,} chars)")
        if mcp:
            lines.append("")
            lines.append("MCP servers (env secrets redacted):")
            for name in sorted(mcp):
                lines.append(f"  {name}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _creator_string(self) -> str:
        """Return a creator identifier string."""
        try:
            user = getpass.getuser()
        except Exception:
            user = "unknown"
        try:
            host = socket.gethostname()
        except Exception:
            host = "unknown"
        return f"{user}@{host}"

    def _collect_mcp(self) -> dict:
        """Collect MCP server configs from the project's .mcp.json."""
        mcp_path = self.project_dir / ".mcp.json"
        if not mcp_path.is_file():
            return {}
        try:
            data = json.loads(mcp_path.read_text(encoding="utf-8"))
            return data.get("mcpServers", {})
        except (OSError, ValueError):
            return {}
