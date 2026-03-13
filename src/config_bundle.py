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
import io
import json
import socket
import zipfile
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

    def export_zip(
        self,
        output_path: Path | None = None,
        include_mcp: bool = True,
        redact_secrets: bool = True,
    ) -> bytes:
        """Export config bundle as a .harness.zip archive.

        The zip contains individual files at their relative paths plus a
        ``bundle.json`` manifest with metadata. Teammates can import with
        ``ConfigBundle.import_zip()``.

        Args:
            output_path: If provided, write the zip file here (should end with
                         ``.harness.zip``).
            include_mcp: Include MCP server configs (env values redacted).
            redact_secrets: Redact sensitive env var values (default: True).

        Returns:
            Raw zip bytes (also written to output_path if provided).
        """
        bundle = self.export(include_mcp=include_mcp, redact_secrets=redact_secrets)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Write each config file at its natural relative path
            for rel, content in bundle.get("files", {}).items():
                zf.writestr(rel, content.encode("utf-8"))

            # Write MCP config as a separate JSON if present
            if bundle.get("mcp_servers"):
                mcp_content = json.dumps(
                    {"mcpServers": bundle["mcp_servers"]}, indent=2, ensure_ascii=False
                )
                zf.writestr(".harness-sync/mcp-servers.json", mcp_content.encode("utf-8"))

            # Write the full JSON manifest for programmatic import
            manifest = {k: v for k, v in bundle.items() if k != "files"}
            manifest["file_list"] = list(bundle.get("files", {}).keys())
            zf.writestr(
                "bundle.json",
                json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
            )

        zip_bytes = buf.getvalue()

        if output_path:
            output_path.write_bytes(zip_bytes)

        return zip_bytes

    def import_zip(
        self,
        zip_source: bytes | Path,
        dry_run: bool = False,
        overwrite: bool = False,
    ) -> list[str]:
        """Import a .harness.zip bundle into the project directory.

        Args:
            zip_source: Raw zip bytes or path to a .harness.zip file.
            dry_run: If True, report what would be written without writing.
            overwrite: If False, skip files that already exist.

        Returns:
            List of result messages (one per file).
        """
        if isinstance(zip_source, Path):
            zip_source = zip_source.read_bytes()

        messages: list[str] = []
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_source))
        except zipfile.BadZipFile as exc:
            return [f"Error: not a valid zip archive ({exc})"]

        with zf:
            names = zf.namelist()
            # Skip the manifest file
            file_names = [n for n in names if n != "bundle.json"]

            for rel in file_names:
                # Skip MCP servers file — handled separately
                if rel == ".harness-sync/mcp-servers.json":
                    continue
                target_path = self.project_dir / rel
                action = "would write" if dry_run else "written"

                if target_path.exists() and not overwrite:
                    messages.append(f"Skipped {rel} (already exists — use --overwrite to replace)")
                    continue

                if dry_run:
                    info = zf.getinfo(rel)
                    messages.append(f"[dry-run] {action}: {rel} ({info.file_size:,} bytes)")
                    continue

                try:
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    data = zf.read(rel)
                    target_path.write_bytes(data)
                    messages.append(f"{action}: {rel}")
                except OSError as e:
                    messages.append(f"Error writing {rel}: {e}")

        if not dry_run and file_names:
            messages.append("\nBundle imported. Run /sync to apply to all harnesses.")

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

    # ------------------------------------------------------------------
    # .harnessbundle archive export/import (item 26)
    # ------------------------------------------------------------------

    def export_harnessbundle(self, output_path: "str | Path | None" = None) -> "Path":
        """Export a portable .harnessbundle archive that teammates can import.

        The .harnessbundle format is a ZIP archive containing:
          - bundle.json   — the canonical bundle manifest (version, files, MCP)
          - CLAUDE.md, AGENTS.md, GEMINI.md, etc. — config files as individual entries
          - .harness-sync/mcp-servers.json — MCP config with secrets redacted

        A teammate can call ``import_harnessbundle(path)`` to extract the bundle
        and immediately replicate the sender's cross-harness AI setup.

        Args:
            output_path: Destination path for the .harnessbundle file.
                         Defaults to ``<project_basename>.harnessbundle`` in the
                         project directory.

        Returns:
            Path to the written .harnessbundle file.
        """
        bundle = self.export()

        if output_path is None:
            bundle_name = self.project_dir.name or "config"
            output_path = self.project_dir / f"{bundle_name}.harnessbundle"
        output_path = Path(output_path)

        with zipfile.ZipFile(output_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            # Write the bundle manifest
            zf.writestr("bundle.json", json.dumps(bundle, indent=2, ensure_ascii=False))

            # Write individual config files for easy inspection
            for rel_path, content in bundle.get("files", {}).items():
                zf.writestr(rel_path, content.encode("utf-8") if isinstance(content, str) else content)

            # Write redacted MCP config separately
            mcp = bundle.get("mcp_servers", {})
            if mcp:
                mcp_json = json.dumps({"mcpServers": mcp}, indent=2, ensure_ascii=False)
                zf.writestr(".harness-sync/mcp-servers.json", mcp_json.encode("utf-8"))

        return output_path

    @classmethod
    def import_harnessbundle(
        cls,
        bundle_path: "str | Path",
        target_dir: "str | Path | None" = None,
        dry_run: bool = False,
    ) -> dict:
        """Import a .harnessbundle archive into a target directory.

        Extracts config files from the bundle and writes them into ``target_dir``,
        allowing a teammate to replicate an AI setup across all harnesses in seconds.

        Secrets are never present in the archive (they are redacted on export),
        so import is safe to run in any directory.

        Args:
            bundle_path: Path to the .harnessbundle file to import.
            target_dir: Directory to write config files into.  Defaults to cwd.
            dry_run: If True, return what would be written without writing anything.

        Returns:
            Dict with keys:
              ``files_written``: list of relative paths written.
              ``mcp_servers``: dict of MCP server configs (with <REDACTED> values).
              ``bundle_meta``: dict of bundle metadata (created_at, creator, etc.).
        """
        bundle_path = Path(bundle_path)
        target_dir = Path(target_dir) if target_dir else Path.cwd()

        if not bundle_path.exists():
            raise FileNotFoundError(f"Bundle not found: {bundle_path}")

        files_written: list[str] = []
        mcp_servers: dict = {}
        bundle_meta: dict = {}

        with zipfile.ZipFile(bundle_path, mode="r") as zf:
            names = set(zf.namelist())

            # Read manifest
            if "bundle.json" in names:
                bundle_meta = json.loads(zf.read("bundle.json").decode("utf-8"))
                mcp_servers = bundle_meta.get("mcp_servers", {})

            # Write individual config files
            for name in names:
                if name in ("bundle.json", ".harness-sync/mcp-servers.json"):
                    continue
                dest = target_dir / name
                if not dry_run:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(zf.read(name))
                files_written.append(name)

        return {
            "files_written": sorted(files_written),
            "mcp_servers": mcp_servers,
            "bundle_meta": {
                k: v for k, v in bundle_meta.items()
                if k not in ("files", "mcp_servers")
            },
        }
