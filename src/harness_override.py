from __future__ import annotations

"""Per-harness override layer — supplement synced config with harness-specific extras.

Allows users to define config that is ADDED ON TOP of the synced base for a
specific harness, without breaking the sync relationship. The override layer
never replaces synced content — it augments it.

Override files live at:
    ~/.harnesssync/overrides/<harness>.json

Format:
    {
        "rules": "# Extra rules only for this harness\\n\\n- Always use TypeScript",
        "mcp": {
            "my-internal-tool": {
                "command": "uvx my-internal-mcp",
                "args": ["--profile", "work"]
            }
        },
        "settings": {
            "approval_mode": "suggest"
        },
        "description": "Work-only Codex extras — proprietary MCP + stricter rules"
    }

The orchestrator merges overrides after writing synced content, so:
- Override rules are appended after synced rules (with a section marker)
- Override MCP servers are merged into the synced MCP config
- Override settings are shallow-merged, with overrides winning on conflict

This enables legitimate per-harness customization (different capabilities,
team-specific tools, internal services) without breaking sync purity.
"""

import json
import re
import tempfile
from pathlib import Path


_OVERRIDE_MARKER_START = "\n\n<!-- HarnessSync per-harness override: {harness} -->\n"
_OVERRIDE_MARKER_END = "\n<!-- End HarnessSync override: {harness} -->\n"

# Inline harness block pattern: <!-- harness:X -->...<!-- /harness:X -->
# Matches both tightly-spaced and whitespace-padded forms.
_INLINE_BLOCK_RE = re.compile(
    r"<!--\s*harness:(?P<harness>[a-zA-Z0-9_-]+)\s*-->"
    r"(?P<content>.*?)"
    r"<!--\s*/harness:(?P=harness)\s*-->",
    re.DOTALL,
)


def parse_inline_harness_blocks(content: str) -> dict[str, str]:
    """Extract all inline harness-specific blocks from CLAUDE.md content.

    Parses fenced sections of the form::

        <!-- harness:codex -->
        This text is injected only into Codex's config.
        <!-- /harness:codex -->

    Multiple blocks for the same harness are concatenated in order.

    Args:
        content: Raw CLAUDE.md text.

    Returns:
        Dict mapping harness name → extracted block content (stripped).
        Harnesses with no blocks are not included.
    """
    result: dict[str, list[str]] = {}
    for m in _INLINE_BLOCK_RE.finditer(content):
        harness = m.group("harness").lower()
        block = m.group("content").strip()
        if block:
            result.setdefault(harness, []).append(block)
    return {h: "\n\n".join(parts) for h, parts in result.items()}


def extract_inline_block(content: str, harness: str) -> str:
    """Return the concatenated inline block content for *harness* in *content*.

    Convenience wrapper around :func:`parse_inline_harness_blocks` for a
    single harness.

    Args:
        content: Raw CLAUDE.md text.
        harness: Target harness name (case-insensitive).

    Returns:
        Extracted block content, or empty string if none found.
    """
    blocks = parse_inline_harness_blocks(content)
    return blocks.get(harness.lower(), "")


def strip_all_inline_blocks(content: str) -> str:
    """Remove all harness-specific inline blocks from *content*.

    Use this to produce the "default" version of CLAUDE.md that is sent to
    harnesses that have no matching inline block — they receive the base
    content without any harness-specific sections.

    Args:
        content: Raw CLAUDE.md text.

    Returns:
        Content with all ``<!-- harness:X -->…<!-- /harness:X -->`` blocks
        removed.  Surrounding blank lines are collapsed.
    """
    stripped = _INLINE_BLOCK_RE.sub("", content)
    # Collapse runs of 3+ blank lines down to 2
    stripped = re.sub(r"\n{3,}", "\n\n", stripped)
    return stripped.strip()


def inject_inline_block(base_content: str, harness: str, block_content: str) -> str:
    """Add or replace the inline block for *harness* in *base_content*.

    If an existing block for *harness* is found it is replaced in place.
    Otherwise the new block is appended at the end of *base_content*.

    Args:
        base_content: Existing CLAUDE.md text.
        harness: Target harness name.
        block_content: New content to place inside the harness block.

    Returns:
        Updated CLAUDE.md text.
    """
    harness_lower = harness.lower()
    tag_open = f"<!-- harness:{harness_lower} -->"
    tag_close = f"<!-- /harness:{harness_lower} -->"
    new_block = f"{tag_open}\n{block_content.strip()}\n{tag_close}"

    # Pattern for existing block (case-insensitive match on the harness name)
    existing_re = re.compile(
        rf"<!--\s*harness:{re.escape(harness_lower)}\s*-->.*?<!--\s*/harness:{re.escape(harness_lower)}\s*-->",
        re.DOTALL | re.IGNORECASE,
    )
    if existing_re.search(base_content):
        return existing_re.sub(new_block, base_content, count=1)

    # Append new block separated by blank lines
    return base_content.rstrip() + "\n\n" + new_block + "\n"

_DEFAULT_OVERRIDES_DIR = Path.home() / ".harnesssync" / "overrides"

# File-based override pattern: CLAUDE.<harness>.md in the project directory.
# This provides an alternative to JSON overrides for rule content — users can
# keep harness-specific additions as plain Markdown next to CLAUDE.md.
# Supported file patterns (tried in order, first match wins):
_FILE_OVERRIDE_PATTERNS = [
    "CLAUDE.{harness}.md",     # canonical: CLAUDE.codex.md, CLAUDE.gemini.md
    ".harness-{harness}.md",   # dotfile alternative
]


class HarnessOverride:
    """Per-harness config override manager.

    Args:
        overrides_dir: Directory containing <harness>.json override files.
                       Defaults to ~/.harnesssync/overrides/
    """

    def __init__(self, overrides_dir: Path | None = None):
        self.overrides_dir = overrides_dir or _DEFAULT_OVERRIDES_DIR

    def _override_path(self, harness: str) -> Path:
        return self.overrides_dir / f"{harness}.json"

    def load(self, harness: str) -> dict:
        """Load override config for a harness.

        Args:
            harness: Target harness name (e.g. "codex", "gemini").

        Returns:
            Override dict, or empty dict if no override file exists.
        """
        path = self._override_path(harness)
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, harness: str, override: dict) -> None:
        """Save override config for a harness.

        Args:
            harness: Target harness name.
            override: Override dict to persist.
        """
        self.overrides_dir.mkdir(parents=True, exist_ok=True)
        path = self._override_path(harness)

        # Atomic write via temp file
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.overrides_dir,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            json.dump(override, tmp, indent=2, ensure_ascii=False)
            tmp.write("\n")
            tmp.flush()
            tmp.close()
            Path(tmp.name).replace(path)
        except Exception:
            tmp.close()
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def delete(self, harness: str) -> bool:
        """Remove the override file for a harness.

        Returns:
            True if a file was deleted, False if none existed.
        """
        path = self._override_path(harness)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_overrides(self) -> dict[str, dict]:
        """Return all configured harness overrides as {harness: override_dict}.

        Returns:
            Dict mapping harness name to its override config.
            Empty dict if no overrides directory or no files.
        """
        if not self.overrides_dir.exists():
            return {}
        result = {}
        for path in sorted(self.overrides_dir.glob("*.json")):
            harness = path.stem
            override = self.load(harness)
            if override:
                result[harness] = override
        return result

    def apply_rules_override(self, synced_content: str, harness: str) -> str:
        """Append harness-specific rules to already-synced rules content.

        The override rules are appended in a clearly-marked section so they
        can be identified and removed/replaced on the next sync without
        disturbing the synced base content.

        Args:
            synced_content: The rules content already written by sync.
            harness: Target harness name.

        Returns:
            Content with override rules appended, or original if no override.
        """
        override = self.load(harness)
        extra_rules = override.get("rules", "")
        if not extra_rules or not extra_rules.strip():
            return synced_content

        marker_start = _OVERRIDE_MARKER_START.format(harness=harness)
        marker_end = _OVERRIDE_MARKER_END.format(harness=harness)

        return synced_content + marker_start + extra_rules.strip() + marker_end

    def strip_rules_override(self, content: str, harness: str) -> str:
        """Remove previously-applied override section from rules content.

        Safe to call on content that has no override section.

        Args:
            content: Rules content possibly containing an override section.
            harness: Target harness name.

        Returns:
            Content with the override section removed.
        """
        marker_start = _OVERRIDE_MARKER_START.format(harness=harness)
        marker_end = _OVERRIDE_MARKER_END.format(harness=harness)

        start_idx = content.find(marker_start)
        if start_idx == -1:
            return content

        end_idx = content.find(marker_end, start_idx)
        if end_idx == -1:
            # Malformed — just strip from marker_start to end
            return content[:start_idx].rstrip()

        # Remove from marker_start through the end of marker_end
        return content[:start_idx].rstrip() + content[end_idx + len(marker_end):]

    def apply_mcp_override(self, synced_mcp: dict, harness: str) -> dict:
        """Merge harness-specific MCP servers into synced MCP config.

        Override servers are merged in (override wins on key collision),
        preserving all synced servers not overridden.

        Args:
            synced_mcp: MCP server dict from sync (may be empty).
            harness: Target harness name.

        Returns:
            Merged MCP servers dict.
        """
        override = self.load(harness)
        extra_mcp = override.get("mcp", {})
        if not extra_mcp:
            return synced_mcp

        merged = dict(synced_mcp)
        merged.update(extra_mcp)
        return merged

    def apply_settings_override(self, synced_settings: dict, harness: str) -> dict:
        """Shallow-merge harness-specific settings over synced settings.

        Override values win on conflict. Synced keys not in override are
        preserved unchanged.

        Args:
            synced_settings: Settings dict from sync.
            harness: Target harness name.

        Returns:
            Merged settings dict.
        """
        override = self.load(harness)
        extra_settings = override.get("settings", {})
        if not extra_settings:
            return synced_settings

        merged = dict(synced_settings)
        merged.update(extra_settings)
        return merged

    def set_rules(self, harness: str, rules: str) -> None:
        """Set or replace the rules override for a harness.

        Args:
            harness: Target harness name.
            rules: Markdown rules string to use as override.
        """
        override = self.load(harness)
        override["rules"] = rules
        self.save(harness, override)

    def set_mcp(self, harness: str, server_name: str, config: dict) -> None:
        """Add or update an MCP server in the harness override.

        Args:
            harness: Target harness name.
            server_name: MCP server identifier.
            config: Server config dict.
        """
        override = self.load(harness)
        if "mcp" not in override:
            override["mcp"] = {}
        override["mcp"][server_name] = config
        self.save(harness, override)

    def remove_mcp(self, harness: str, server_name: str) -> bool:
        """Remove a specific MCP server from the harness override.

        Returns:
            True if server was found and removed.
        """
        override = self.load(harness)
        mcp = override.get("mcp", {})
        if server_name not in mcp:
            return False
        del mcp[server_name]
        override["mcp"] = mcp
        self.save(harness, override)
        return True

    def set_description(self, harness: str, description: str) -> None:
        """Set a human-readable description for this override."""
        override = self.load(harness)
        override["description"] = description
        self.save(harness, override)

    # ------------------------------------------------------------------
    # File-Based Override Discovery (CLAUDE.<harness>.md pattern)
    # ------------------------------------------------------------------

    @staticmethod
    def find_file_override(project_dir: Path, harness: str) -> Path | None:
        """Find a CLAUDE.<harness>.md (or .harness-<harness>.md) override file.

        Implements the ``CLAUDE.codex.md`` / ``CLAUDE.gemini.md`` pattern:
        users can place a harness-specific Markdown file next to CLAUDE.md and
        HarnessSync will merge its content on top of the base rules when syncing
        to that target.

        File patterns tried in order (first match wins):
          1. CLAUDE.<harness>.md   — e.g. CLAUDE.codex.md
          2. .harness-<harness>.md — e.g. .harness-codex.md (dotfile form)

        Args:
            project_dir: Project root directory to search in.
            harness: Target harness name (e.g. "codex", "gemini", "cursor").

        Returns:
            Path to the override file, or None if not found.
        """
        for pattern in _FILE_OVERRIDE_PATTERNS:
            candidate = project_dir / pattern.format(harness=harness)
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def load_file_override_rules(project_dir: Path, harness: str) -> str:
        """Load rule content from a CLAUDE.<harness>.md file override.

        Reads the file found by :func:`find_file_override`. Returns an empty
        string if no file override exists, making it safe to call unconditionally.

        Args:
            project_dir: Project root directory.
            harness: Target harness name.

        Returns:
            Content of the file-based override, or empty string.
        """
        path = HarnessOverride.find_file_override(project_dir, harness)
        if path is None:
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def apply_file_override(
        self,
        synced_content: str,
        harness: str,
        project_dir: Path,
    ) -> str:
        """Append file-based override rules (CLAUDE.<harness>.md) after synced content.

        This is an ADDITIVE operation: the file content is appended after the
        synced base and after any JSON-based rules override, in a clearly-marked
        section. The file content is NEVER included when syncing to other targets.

        Use this AFTER ``apply_rules_override()`` so JSON overrides come first
        and file-based overrides come last.

        Args:
            synced_content: Rules content already written (possibly with JSON
                            override appended by apply_rules_override()).
            harness: Target harness name.
            project_dir: Project root to search for CLAUDE.<harness>.md.

        Returns:
            Content with file override appended, or original if no file override.
        """
        extra = self.load_file_override_rules(project_dir, harness)
        if not extra.strip():
            return synced_content

        file_path = self.find_file_override(project_dir, harness)
        file_name = file_path.name if file_path else f"CLAUDE.{harness}.md"

        marker_start = (
            f"\n\n<!-- HarnessSync file-override: {file_name} -->\n"
        )
        marker_end = f"\n<!-- End file-override: {file_name} -->\n"

        return synced_content + marker_start + extra.strip() + marker_end

    @staticmethod
    def discover_file_overrides(project_dir: Path) -> dict[str, Path]:
        """Scan project_dir for all CLAUDE.<harness>.md override files.

        Args:
            project_dir: Project root to scan.

        Returns:
            Dict mapping harness name → override file path for each discovered
            file-based override.
        """
        found: dict[str, Path] = {}
        for pattern in _FILE_OVERRIDE_PATTERNS:
            # Extract harness name by matching existing files against the pattern
            prefix, _, suffix = pattern.partition("{harness}")
            for candidate in project_dir.iterdir():
                if not candidate.is_file():
                    continue
                name = candidate.name
                if name.startswith(prefix) and name.endswith(suffix):
                    harness = name[len(prefix):len(name) - len(suffix)]
                    if harness and harness not in found:
                        found[harness] = candidate
        return found

    def format_summary(self) -> str:
        """Return a formatted summary of all active overrides."""
        overrides = self.list_overrides()
        if not overrides:
            return "No per-harness overrides configured.\n" \
                   f"Override files go in: {self.overrides_dir}/<harness>.json"

        lines = ["Per-Harness Override Summary", "=" * 40]
        for harness, cfg in overrides.items():
            description = cfg.get("description", "")
            lines.append(f"\n{harness}:" + (f" — {description}" if description else ""))

            if "rules" in cfg and cfg["rules"]:
                rule_lines = cfg["rules"].strip().split("\n")
                lines.append(f"  rules: {len(rule_lines)} line(s)")

            mcp = cfg.get("mcp", {})
            if mcp:
                lines.append(f"  mcp: {', '.join(sorted(mcp.keys()))}")

            settings = cfg.get("settings", {})
            if settings:
                lines.append(f"  settings: {', '.join(sorted(settings.keys()))}")

            model = cfg.get("model")
            if model:
                lines.append(f"  model pin: {model}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Model Pinning (Item 4 — Per-Harness Override Layer)
    # ------------------------------------------------------------------
    #
    # Allow pinning a specific model to a harness, independent of whatever
    # model Claude Code is using.  The pinned model is stored as a top-level
    # ``"model"`` key in the override JSON and surfaced via
    # ``apply_model_override()`` so adapters can inject it into their
    # settings output.

    def pin_model(self, harness: str, model: str) -> None:
        """Pin a specific model for a harness override.

        When a model is pinned the adapter will always configure that model
        for this harness, regardless of what Claude Code's own settings say.
        This is useful when different harnesses have different strengths and
        you want consistent, deliberate model selection per tool.

        Example override JSON after pinning::

            {
              "model": "o3",
              "description": "Codex always uses o3 for higher accuracy"
            }

        Args:
            harness: Target harness name (e.g. "codex").
            model: Model identifier to pin (e.g. "o3", "claude-opus-4-6",
                   "gemini-2.0-flash").
        """
        override = self.load(harness)
        override["model"] = model
        self.save(harness, override)

    def unpin_model(self, harness: str) -> bool:
        """Remove the pinned model for a harness.

        Returns:
            True if a model was pinned and removed, False if nothing was pinned.
        """
        override = self.load(harness)
        if "model" not in override:
            return False
        del override["model"]
        self.save(harness, override)
        return True

    def get_pinned_model(self, harness: str) -> str | None:
        """Return the pinned model for a harness, or None if not pinned."""
        return self.load(harness).get("model")

    def apply_model_override(self, synced_settings: dict, harness: str) -> dict:
        """Inject the pinned model into synced settings if one is configured.

        The pinned model is stored under the key ``"model"`` in the returned
        settings dict.  Adapters that support model selection (Codex, Gemini,
        OpenCode) should call this after ``apply_settings_override()`` so the
        model pin takes highest priority.

        Args:
            synced_settings: Settings dict already processed by sync.
            harness: Target harness name.

        Returns:
            Settings dict with ``"model"`` key set to the pinned model, or
            the original dict unchanged if no model is pinned.
        """
        model = self.get_pinned_model(harness)
        if not model:
            return synced_settings
        merged = dict(synced_settings)
        merged["model"] = model
        return merged

    def set_exclude_sections(self, harness: str, sections: list[str]) -> None:
        """Set sections to exclude from sync for a specific harness.

        Item 1 / Item 7: Selective per-harness section control.

        Allows users to skip specific config sections (e.g., skip 'mcp' for
        a harness where MCP setup is managed separately).

        Args:
            harness: Target harness name.
            sections: List of section names to exclude (e.g. ['mcp', 'agents']).
                      Valid values: rules, skills, agents, commands, mcp, settings
        """
        override = self.load(harness)
        override["exclude_sections"] = list(sections)
        self.save(harness, override)

    def get_exclude_sections(self, harness: str) -> list[str]:
        """Return the list of sections excluded from sync for a harness.

        Args:
            harness: Target harness name.

        Returns:
            List of excluded section names, or empty list if none configured.
        """
        override = self.load(harness)
        return list(override.get("exclude_sections", []))

    def should_sync_section(self, harness: str, section: str) -> bool:
        """Return True if the given section should be synced to this harness.

        Checks the per-harness exclude_sections list. Returns True (sync) if
        the section is not in the exclusion list.

        Args:
            harness: Target harness name.
            section: Section name to check (e.g. 'mcp', 'rules').

        Returns:
            True if sync should proceed, False if this section is excluded.
        """
        excluded = self.get_exclude_sections(harness)
        return section not in excluded
