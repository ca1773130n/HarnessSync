from __future__ import annotations

"""Config Inheritance & Composition — cascading config layers.

Supports a 3-layer inheritance chain for Claude Code configuration:

    base (company-wide)
        └── team (team-specific overrides)
                └── personal (user-specific overrides)

Each layer can extend the one above it, adding rules, overriding settings,
or suppressing inherited rules. The final merged config is what gets synced.

Layer resolution order (personal wins on conflict):
    personal > team > base

Config files are standard CLAUDE.md files (or JSON for settings/MCP) stored
at declared paths. The inheritance chain is declared in .harnesssync:

    {
        "inherit": {
            "base": "~/.claude/base.md",
            "team": "~/.claude/team.md"
        }
    }

Or globally in ~/.harnesssync/inheritance.json:

    {
        "chain": [
            {"name": "company", "path": "/shared/harness/base.md"},
            {"name": "team-backend", "path": "~/team-backend/CLAUDE.md"}
        ]
    }

Rules composition:
- Inherited rules are prefixed with a `<!-- inherited from: <layer> -->` marker
- Rules with `!override` prefix in a child layer suppress the matched rule in parent
- Settings and MCP are shallow-merged (child wins on key conflict)
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


_INHERITANCE_CONFIG_FILE = Path.home() / ".harnesssync" / "inheritance.json"
_PROJECT_INHERIT_KEY = "inherit"

# Marker for inherited content in composed rules
_INHERIT_MARKER = "<!-- inherited from: {layer} -->"
_INHERIT_MARKER_END = "<!-- end inherited from: {layer} -->"

# Prefix in child layer to suppress parent rule
_SUPPRESS_PREFIX = "!override"


@dataclass
class InheritanceLayer:
    """A single layer in the inheritance chain."""

    name: str            # e.g. "company", "team-backend", "personal"
    path: Path           # Path to CLAUDE.md (or directory)
    rules: str = ""      # Loaded rules content
    mcp: dict = field(default_factory=dict)
    settings: dict = field(default_factory=dict)
    loaded: bool = False


@dataclass
class ComposedConfig:
    """Result of composing all inheritance layers."""

    rules: str
    mcp: dict
    settings: dict
    layer_order: list[str]           # Layer names from base to personal
    suppressed_patterns: list[str]   # Rules suppressed by child layers


class ConfigInheritance:
    """Loads and composes a chain of inheritance layers.

    Args:
        project_dir: Project root directory (for project-level .harnesssync config).
        global_config_path: Path to global ~/.harnesssync/inheritance.json.
    """

    def __init__(
        self,
        project_dir: Path | None = None,
        global_config_path: Path | None = None,
    ):
        self.project_dir = project_dir or Path.cwd()
        self.global_config_path = global_config_path or _INHERITANCE_CONFIG_FILE

    def _load_project_inherit(self) -> dict:
        """Read 'inherit' key from .harnesssync in project directory."""
        harnesssync = self.project_dir / ".harnesssync"
        if not harnesssync.exists():
            return {}
        try:
            data = json.loads(harnesssync.read_text(encoding="utf-8"))
            return data.get(_PROJECT_INHERIT_KEY, {})
        except (json.JSONDecodeError, OSError):
            return {}

    def _load_global_chain(self) -> list[dict]:
        """Read global inheritance chain config."""
        if not self.global_config_path.exists():
            return []
        try:
            data = json.loads(self.global_config_path.read_text(encoding="utf-8"))
            return data.get("chain", [])
        except (json.JSONDecodeError, OSError):
            return []

    def resolve_chain(self) -> list[InheritanceLayer]:
        """Build the full inheritance chain from global + project config.

        Global chain layers come first (base → team), then project
        overrides add/replace specific layers.

        Returns:
            List of InheritanceLayer objects, ordered base → personal.
        """
        layers: list[InheritanceLayer] = []

        # Start with global chain
        for entry in self._load_global_chain():
            name = entry.get("name", "")
            path_str = entry.get("path", "")
            if not name or not path_str:
                continue
            path = Path(path_str).expanduser()
            layers.append(InheritanceLayer(name=name, path=path))

        # Project-level overrides / additions
        project_inherit = self._load_project_inherit()
        for layer_name, path_str in project_inherit.items():
            path = Path(path_str).expanduser()
            # Replace if same name already in chain
            existing = next((l for l in layers if l.name == layer_name), None)
            if existing:
                existing.path = path
            else:
                layers.append(InheritanceLayer(name=layer_name, path=path))

        return layers

    def _load_layer(self, layer: InheritanceLayer) -> InheritanceLayer:
        """Load config content from a layer's path."""
        if not layer.path.exists():
            layer.loaded = True
            return layer

        if layer.path.is_dir():
            # Directory — look for CLAUDE.md + .mcp.json + settings.json
            claude_md = layer.path / "CLAUDE.md"
            mcp_json = layer.path / ".mcp.json"
            settings_json = layer.path / "settings.json"
        else:
            # Direct CLAUDE.md file path
            claude_md = layer.path
            mcp_json = layer.path.parent / ".mcp.json"
            settings_json = layer.path.parent / "settings.json"

        if claude_md.exists():
            try:
                layer.rules = claude_md.read_text(encoding="utf-8")
            except OSError:
                pass

        if mcp_json.exists():
            try:
                data = json.loads(mcp_json.read_text(encoding="utf-8"))
                layer.mcp = data.get("mcpServers", data) if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError):
                pass

        if settings_json.exists():
            try:
                layer.settings = json.loads(settings_json.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        layer.loaded = True
        return layer

    def compose(self, personal_rules: str = "", personal_mcp: dict | None = None,
                personal_settings: dict | None = None) -> ComposedConfig:
        """Compose all layers into a single merged config.

        Personal config (the current project) is treated as the top layer,
        taking priority over all inherited layers.

        Args:
            personal_rules: Current CLAUDE.md content (personal/project layer).
            personal_mcp: Current MCP servers dict.
            personal_settings: Current settings dict.

        Returns:
            ComposedConfig with merged rules, mcp, and settings.
        """
        chain = self.resolve_chain()
        if not chain:
            # No inheritance configured — return personal as-is
            return ComposedConfig(
                rules=personal_rules,
                mcp=personal_mcp or {},
                settings=personal_settings or {},
                layer_order=["personal"],
                suppressed_patterns=[],
            )

        # Load all layers
        for layer in chain:
            self._load_layer(layer)

        # Collect suppression patterns from personal rules
        suppressed = _extract_suppressed_patterns(personal_rules)

        # Build composed rules: base first, then each layer, then personal
        rule_parts: list[str] = []
        for layer in chain:
            if not layer.rules.strip():
                continue
            filtered = _apply_suppressions(layer.rules, suppressed)
            if not filtered.strip():
                continue
            marker = _INHERIT_MARKER.format(layer=layer.name)
            end_marker = _INHERIT_MARKER_END.format(layer=layer.name)
            rule_parts.append(f"{marker}\n{filtered.strip()}\n{end_marker}")

        # Personal rules go last (highest priority, no markers)
        clean_personal = _strip_suppress_directives(personal_rules)
        if clean_personal.strip():
            rule_parts.append(clean_personal.strip())

        composed_rules = "\n\n".join(rule_parts)

        # Merge MCP: base → team → personal (personal wins)
        composed_mcp: dict = {}
        for layer in chain:
            composed_mcp.update(layer.mcp)
        if personal_mcp:
            composed_mcp.update(personal_mcp)

        # Merge settings: base → team → personal
        composed_settings: dict = {}
        for layer in chain:
            composed_settings.update(layer.settings)
        if personal_settings:
            composed_settings.update(personal_settings)

        return ComposedConfig(
            rules=composed_rules,
            mcp=composed_mcp,
            settings=composed_settings,
            layer_order=[l.name for l in chain] + ["personal"],
            suppressed_patterns=suppressed,
        )

    def set_global_chain(self, chain: list[dict]) -> None:
        """Persist a new global inheritance chain.

        Args:
            chain: List of {"name": str, "path": str} dicts.
        """
        self.global_config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"chain": chain}
        self.global_config_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def add_layer(self, name: str, path: Path) -> None:
        """Add a new layer to the end of the global chain."""
        chain = self._load_global_chain()
        # Replace if same name
        chain = [e for e in chain if e.get("name") != name]
        chain.append({"name": name, "path": str(path)})
        self.set_global_chain(chain)

    def remove_layer(self, name: str) -> bool:
        """Remove a layer from the global chain by name.

        Returns:
            True if layer was found and removed.
        """
        chain = self._load_global_chain()
        new_chain = [e for e in chain if e.get("name") != name]
        if len(new_chain) == len(chain):
            return False
        self.set_global_chain(new_chain)
        return True

    def format_chain_summary(self) -> str:
        """Return a human-readable summary of the configured inheritance chain."""
        chain = self.resolve_chain()
        if not chain:
            return (
                "No inheritance chain configured.\n"
                f"Global config: {self.global_config_path}\n"
                "Project config: <project>/.harnesssync (inherit key)\n\n"
                "Example: /sync-inherit add company ~/.claude/company-base.md"
            )

        lines = ["Config Inheritance Chain", "=" * 40]
        lines.append(f"Resolution order (base → personal):\n")
        for i, layer in enumerate(chain, 1):
            exists = "✓" if layer.path.exists() else "✗ (not found)"
            lines.append(f"  {i}. [{layer.name}] {layer.path} {exists}")
        lines.append(f"  {len(chain)+1}. [personal] (current project)")
        lines.append("")
        lines.append("Personal rules override all inherited rules.")
        lines.append("Use '!override <pattern>' in your CLAUDE.md to suppress inherited rules.")
        return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers for suppress directives
# ──────────────────────────────────────────────────────────────────────────────

def _extract_suppressed_patterns(rules: str) -> list[str]:
    """Extract !override directives from rules content.

    Returns list of patterns/text snippets to suppress in parent layers.

    Example:
        !override database connection pooling
    """
    patterns = []
    for line in rules.splitlines():
        stripped = line.strip()
        if stripped.startswith(_SUPPRESS_PREFIX):
            pattern = stripped[len(_SUPPRESS_PREFIX):].strip()
            if pattern:
                patterns.append(pattern)
    return patterns


def _apply_suppressions(rules: str, patterns: list[str]) -> str:
    """Remove lines/paragraphs matching suppression patterns from rules.

    Args:
        rules: Rules content to filter.
        patterns: Suppression patterns from child layer.

    Returns:
        Filtered rules content.
    """
    if not patterns:
        return rules

    paragraphs = re.split(r"\n{2,}", rules)
    result = []
    for para in paragraphs:
        para_lower = para.lower()
        if any(p.lower() in para_lower for p in patterns):
            continue
        result.append(para)

    return "\n\n".join(result)


def _strip_suppress_directives(rules: str) -> str:
    """Remove !override directives from rules (they're meta-instructions, not content)."""
    lines = [l for l in rules.splitlines() if not l.strip().startswith(_SUPPRESS_PREFIX)]
    return "\n".join(lines)
