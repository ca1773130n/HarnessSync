from __future__ import annotations

"""Environment Variable Compatibility Matrix (item 19).

Maps Claude Code environment variable settings to their equivalents in each
harness and flags where no equivalent exists.  ENV translation is currently
opaque — users don't know if ANTHROPIC_MODEL or tool permissions translated.
A clear matrix prevents silent behaviour differences.

The matrix covers two categories:
1. Runtime env vars that affect model/API behaviour (ANTHROPIC_MODEL, etc.)
2. HarnessSync-specific env vars that control sync behaviour

Usage:
    from src.env_var_matrix import EnvVarMatrix

    matrix = EnvVarMatrix()
    report = matrix.analyze(current_env=os.environ)
    print(matrix.format_table(report))

Or from the CLI:
    /sync-env-matrix [--show-missing] [--project-dir PATH]
"""

import os
from dataclasses import dataclass, field
from enum import Enum


class EnvSupport(str, Enum):
    """How well a target harness supports a given env var."""
    NATIVE   = "native"    # Same variable name, same effect
    MAPPED   = "mapped"    # Different variable name, equivalent effect
    PARTIAL  = "partial"   # Partial support — some aspects ignored
    NONE     = "none"      # No equivalent; behaviour silently differs
    INFERRED = "inferred"  # Harness infers the value from other sources


@dataclass
class EnvVarSpec:
    """Specification for one Claude Code environment variable."""
    name: str
    description: str
    category: str  # "model", "api", "tools", "context", "sync"
    # Per-target: (support_level, equivalent_name_or_note)
    targets: dict[str, tuple[EnvSupport, str]] = field(default_factory=dict)


# ── Environment variable registry ─────────────────────────────────────────
# Format: targets = {"target": (EnvSupport, "EQUIVALENT_VAR or note")}
ENV_VAR_REGISTRY: list[EnvVarSpec] = [
    EnvVarSpec(
        name="ANTHROPIC_API_KEY",
        description="Anthropic API key for Claude requests",
        category="api",
        targets={
            "codex":    (EnvSupport.NONE,    "Codex uses OPENAI_API_KEY; no Anthropic key support"),
            "gemini":   (EnvSupport.NONE,    "Gemini uses GEMINI_API_KEY / GOOGLE_API_KEY"),
            "opencode": (EnvSupport.NATIVE,  "ANTHROPIC_API_KEY — OpenCode uses same var"),
            "cursor":   (EnvSupport.NONE,    "Cursor uses its own API key management via settings"),
            "aider":    (EnvSupport.NATIVE,  "ANTHROPIC_API_KEY — Aider passes through to Anthropic"),
            "windsurf": (EnvSupport.NONE,    "Windsurf uses its own key management"),
        },
    ),
    EnvVarSpec(
        name="ANTHROPIC_MODEL",
        description="Default Claude model to use (e.g. claude-3-5-sonnet-20241022)",
        category="model",
        targets={
            "codex":    (EnvSupport.NONE,    "No direct equivalent; model is set in config.toml [model]"),
            "gemini":   (EnvSupport.NONE,    "Gemini uses GOOGLE_GENAI_MODEL or gemini.json model field"),
            "opencode": (EnvSupport.MAPPED,  "ANTHROPIC_MODEL via opencode.json model field"),
            "cursor":   (EnvSupport.NONE,    "Model selected in Cursor UI settings, not env vars"),
            "aider":    (EnvSupport.MAPPED,  "AIDER_MODEL — e.g. AIDER_MODEL=claude-3-5-sonnet-20241022"),
            "windsurf": (EnvSupport.NONE,    "Windsurf model is set in UI, not env vars"),
        },
    ),
    EnvVarSpec(
        name="ANTHROPIC_BASE_URL",
        description="Override Anthropic API base URL (proxy / self-hosted)",
        category="api",
        targets={
            "codex":    (EnvSupport.NONE,    "No proxy URL support via env"),
            "gemini":   (EnvSupport.NONE,    "GOOGLE_API_BASE_URL for Gemini; no Anthropic proxy"),
            "opencode": (EnvSupport.NATIVE,  "ANTHROPIC_BASE_URL passed through"),
            "cursor":   (EnvSupport.NONE,    "No env-based proxy override"),
            "aider":    (EnvSupport.NATIVE,  "ANTHROPIC_BASE_URL — Aider respects this"),
            "windsurf": (EnvSupport.NONE,    "No env-based proxy override"),
        },
    ),
    EnvVarSpec(
        name="CLAUDE_CODE_MAX_TOKENS",
        description="Maximum output tokens per Claude Code response",
        category="context",
        targets={
            "codex":    (EnvSupport.NONE,    "No token limit env var; limited by model default"),
            "gemini":   (EnvSupport.NONE,    "Gemini uses maxOutputTokens in config, not env"),
            "opencode": (EnvSupport.PARTIAL, "opencode.json maxTokens field; not env-driven"),
            "cursor":   (EnvSupport.NONE,    "Not configurable via env vars"),
            "aider":    (EnvSupport.MAPPED,  "AIDER_MAX_TOKENS — partial; only output tokens"),
            "windsurf": (EnvSupport.NONE,    "Not configurable via env vars"),
        },
    ),
    EnvVarSpec(
        name="DISABLE_AUTOUPDATER",
        description="Disable Claude Code auto-update checks (1=disable)",
        category="sync",
        targets={
            "codex":    (EnvSupport.NONE,    "No auto-updater; N/A"),
            "gemini":   (EnvSupport.NONE,    "Gemini CLI handles updates separately; N/A"),
            "opencode": (EnvSupport.NONE,    "No auto-updater env var"),
            "cursor":   (EnvSupport.NONE,    "Cursor updates are managed by the app"),
            "aider":    (EnvSupport.NONE,    "pip manages aider updates; N/A"),
            "windsurf": (EnvSupport.NONE,    "Windsurf updates managed by the app"),
        },
    ),
    EnvVarSpec(
        name="CLAUDE_CODE_USE_BEDROCK",
        description="Route Claude requests through AWS Bedrock",
        category="api",
        targets={
            "codex":    (EnvSupport.NONE,    "No Bedrock support"),
            "gemini":   (EnvSupport.NONE,    "No Bedrock support"),
            "opencode": (EnvSupport.PARTIAL, "Bedrock via custom base URL; not native env flag"),
            "cursor":   (EnvSupport.NONE,    "No Bedrock env flag"),
            "aider":    (EnvSupport.MAPPED,  "Set ANTHROPIC_BASE_URL to Bedrock endpoint"),
            "windsurf": (EnvSupport.NONE,    "No Bedrock env flag"),
        },
    ),
    EnvVarSpec(
        name="CLAUDE_CODE_USE_VERTEX",
        description="Route Claude requests through Google Vertex AI",
        category="api",
        targets={
            "codex":    (EnvSupport.NONE,    "No Vertex support"),
            "gemini":   (EnvSupport.INFERRED,"Gemini natively uses Vertex; GOOGLE_APPLICATION_CREDENTIALS"),
            "opencode": (EnvSupport.PARTIAL, "Vertex via custom base URL; not native env flag"),
            "cursor":   (EnvSupport.NONE,    "No Vertex env flag"),
            "aider":    (EnvSupport.NONE,    "No Vertex env flag"),
            "windsurf": (EnvSupport.NONE,    "No Vertex env flag"),
        },
    ),
    EnvVarSpec(
        name="HTTP_PROXY",
        description="HTTP proxy for outgoing requests",
        category="api",
        targets={
            "codex":    (EnvSupport.NATIVE,  "HTTP_PROXY — standard Node.js env var"),
            "gemini":   (EnvSupport.NATIVE,  "HTTP_PROXY — standard env var"),
            "opencode": (EnvSupport.NATIVE,  "HTTP_PROXY — standard env var"),
            "cursor":   (EnvSupport.PARTIAL, "Cursor uses system proxy settings; env may work"),
            "aider":    (EnvSupport.NATIVE,  "HTTP_PROXY — standard Python env var"),
            "windsurf": (EnvSupport.PARTIAL, "Windsurf uses system proxy settings"),
        },
    ),
    EnvVarSpec(
        name="GEMINI_API_KEY",
        description="Google Gemini API key (used when Gemini is a target)",
        category="api",
        targets={
            "codex":    (EnvSupport.NONE,    "Codex uses OpenAI-compatible keys"),
            "gemini":   (EnvSupport.NATIVE,  "GEMINI_API_KEY — Gemini's primary key var"),
            "opencode": (EnvSupport.NONE,    "OpenCode doesn't use Gemini keys natively"),
            "cursor":   (EnvSupport.NONE,    "Cursor manages API keys via settings UI"),
            "aider":    (EnvSupport.MAPPED,  "GEMINI_API_KEY — Aider supports Gemini models"),
            "windsurf": (EnvSupport.NONE,    "Windsurf manages keys via settings UI"),
        },
    ),
    EnvVarSpec(
        name="NODE_EXTRA_CA_CERTS",
        description="Extra CA certificates for TLS (corporate proxies)",
        category="api",
        targets={
            "codex":    (EnvSupport.NATIVE,  "NODE_EXTRA_CA_CERTS — Node.js standard"),
            "gemini":   (EnvSupport.NATIVE,  "NODE_EXTRA_CA_CERTS — Gemini CLI is Node-based"),
            "opencode": (EnvSupport.NATIVE,  "NODE_EXTRA_CA_CERTS — OpenCode is Node-based"),
            "cursor":   (EnvSupport.PARTIAL, "Cursor uses Electron's cert handling; may honour this"),
            "aider":    (EnvSupport.MAPPED,  "REQUESTS_CA_BUNDLE — Python requests standard"),
            "windsurf": (EnvSupport.PARTIAL, "Windsurf uses Electron cert handling"),
        },
    ),
]


@dataclass
class EnvVarAnalysis:
    """Analysis result for a single env var in the current environment."""
    spec: EnvVarSpec
    is_set: bool
    current_value_masked: str  # Never expose secrets; show "***" or "not set"
    missing_in: list[str]      # Targets with no equivalent
    partial_in: list[str]      # Targets with partial support
    mapped_in: dict[str, str]  # target -> equivalent_var_name


@dataclass
class EnvVarReport:
    """Complete environment variable compatibility report."""
    analyses: list[EnvVarAnalysis]
    total_set: int
    total_missing_translations: int
    targets: list[str]


class EnvVarMatrix:
    """Generate cross-harness environment variable compatibility matrix.

    Args:
        targets: Harness names to include. Defaults to all registered targets.
    """

    ALL_TARGETS = ["codex", "gemini", "opencode", "cursor", "aider", "windsurf"]

    def __init__(self, targets: list[str] | None = None):
        self.targets = targets or self.ALL_TARGETS

    def analyze(self, current_env: dict[str, str] | None = None) -> EnvVarReport:
        """Analyze current environment against the compatibility matrix.

        Args:
            current_env: Environment to check. Defaults to os.environ.

        Returns:
            EnvVarReport with per-var analysis.
        """
        env = current_env if current_env is not None else dict(os.environ)
        analyses: list[EnvVarAnalysis] = []
        total_missing = 0

        for spec in ENV_VAR_REGISTRY:
            is_set = spec.name in env
            raw_val = env.get(spec.name, "")
            # Mask secrets
            masked = self._mask_value(spec.name, raw_val) if raw_val else "not set"

            missing_in: list[str] = []
            partial_in: list[str] = []
            mapped_in: dict[str, str] = {}

            for target in self.targets:
                support_info = spec.targets.get(target)
                if support_info is None:
                    if is_set:
                        missing_in.append(target)
                    continue
                level, note = support_info
                if level == EnvSupport.NONE and is_set:
                    missing_in.append(target)
                    total_missing += 1
                elif level == EnvSupport.PARTIAL and is_set:
                    partial_in.append(target)
                elif level == EnvSupport.MAPPED and is_set:
                    # Extract the mapped var name from the note
                    mapped_var = note.split("—")[0].strip() if "—" in note else note
                    mapped_in[target] = mapped_var

            analyses.append(EnvVarAnalysis(
                spec=spec,
                is_set=is_set,
                current_value_masked=masked,
                missing_in=missing_in,
                partial_in=partial_in,
                mapped_in=mapped_in,
            ))

        return EnvVarReport(
            analyses=analyses,
            total_set=sum(1 for a in analyses if a.is_set),
            total_missing_translations=total_missing,
            targets=self.targets,
        )

    # ── Formatting ─────────────────────────────────────────────────────────

    def format_table(self, report: EnvVarReport, show_all: bool = False) -> str:
        """Return a text table of the compatibility matrix.

        Args:
            report:   Analysis report from analyze().
            show_all: If False, only shows vars that are currently set or have gaps.
        """
        col_w = 8
        targets = report.targets
        header_targets = "  ".join(t[:col_w].ljust(col_w) for t in targets)
        divider = "-" * (28 + len(targets) * (col_w + 2))

        lines = [
            "Environment Variable Compatibility Matrix",
            "=" * len(divider),
            f"{'Variable':<28}  {header_targets}",
            divider,
        ]

        symbol_map = {
            EnvSupport.NATIVE:   "✓ native",
            EnvSupport.MAPPED:   "~ mapped",
            EnvSupport.PARTIAL:  "~ partial",
            EnvSupport.NONE:     "✗ none",
            EnvSupport.INFERRED: "~ infer",
        }

        for analysis in report.analyses:
            if not show_all and not analysis.is_set:
                continue
            spec = analysis.spec
            set_marker = "●" if analysis.is_set else "○"
            row_name = f"{set_marker} {spec.name}"[:26].ljust(28)

            cells: list[str] = []
            for target in targets:
                info = spec.targets.get(target)
                if info is None:
                    cells.append("? unknwn".ljust(col_w))
                else:
                    level, _ = info
                    sym = symbol_map.get(level, "? unk").ljust(col_w)
                    cells.append(sym)
            lines.append(f"{row_name}  {'  '.join(cells)}")

        lines.append(divider)
        lines.append(f"\n● = currently set  ○ = not set")
        lines.append(f"✓ native = same var name  ~ = mapped/partial  ✗ = no equivalent\n")

        if report.total_set > 0:
            lines.append(f"Set vars: {report.total_set}  |  Silent gaps: {report.total_missing_translations}")
        return "\n".join(lines)

    def format_gaps(self, report: EnvVarReport) -> str:
        """Return only the variables with translation gaps for currently-set vars."""
        lines = ["Silent ENV translation gaps (set vars with no harness equivalent):", ""]
        found_any = False
        for a in report.analyses:
            if not a.is_set:
                continue
            if a.missing_in or a.partial_in:
                found_any = True
                lines.append(f"  {a.spec.name} ({a.current_value_masked})")
                if a.missing_in:
                    lines.append(f"    No equivalent in: {', '.join(a.missing_in)}")
                if a.partial_in:
                    lines.append(f"    Partial support in: {', '.join(a.partial_in)}")
                if a.mapped_in:
                    for target, mapped in a.mapped_in.items():
                        lines.append(f"    → {target}: use {mapped}")
        if not found_any:
            lines.append("  No gaps found for currently set variables.")
        return "\n".join(lines)

    # ── Helpers ────────────────────────────────────────────────────────────

    @staticmethod
    def _mask_value(name: str, value: str) -> str:
        """Mask sensitive values; show length hint."""
        secret_patterns = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
        is_secret = any(p in name.upper() for p in secret_patterns)
        if is_secret and value:
            return f"***({len(value)} chars)"
        # Show first 40 chars of non-secret values
        return value[:40] + ("…" if len(value) > 40 else "")


# ---------------------------------------------------------------------------
# Portability checker — scan synced configs for env var references (item 28)
# ---------------------------------------------------------------------------

import re as _re

# Patterns that identify env var references in config text (e.g. ${VAR}, $VAR)
_ENV_REF_RE = _re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}|\$([A-Z_][A-Z0-9_]{2,})")


@dataclass
class EnvPortabilityIssue:
    """One env var reference in a config that may not be available in a target."""
    var_name: str       # The referenced env var name
    source_file: str    # Config file or field where it was found
    targets_missing: list[str]   # Targets where this var is unavailable
    targets_partial: list[str]   # Targets where support is partial


@dataclass
class EnvPortabilityReport:
    """Report of env var portability issues across synced configs."""
    issues: list[EnvPortabilityIssue] = field(default_factory=list)

    @property
    def total_issues(self) -> int:
        return len(self.issues)

    def is_clean(self) -> bool:
        return not self.issues

    def format(self) -> str:
        """Format as human-readable text."""
        if self.is_clean():
            return "Env Portability: No issues found."

        lines = ["## Env Var Portability Issues", ""]
        for issue in self.issues:
            lines.append(f"  ${issue.var_name}  (in {issue.source_file})")
            if issue.targets_missing:
                lines.append(f"    Not available in: {', '.join(issue.targets_missing)}")
            if issue.targets_partial:
                lines.append(f"    Partial support in: {', '.join(issue.targets_partial)}")
        lines.append(f"\nTotal issues: {self.total_issues}")
        return "\n".join(lines)


def check_env_portability(
    config_texts: dict[str, str],
    targets: list[str] | None = None,
    current_env: dict[str, str] | None = None,
) -> EnvPortabilityReport:
    """Scan config texts for env var references and check harness portability.

    Finds all ``${VAR}`` and ``$VAR`` references in the provided config
    strings, then checks whether each referenced variable has a native
    or mapped equivalent in each target harness. Variables that are
    only set in the source environment but have no equivalent in a target
    will cause silent failures when those configs are used.

    Args:
        config_texts: Dict mapping a label (e.g. "mcp:my-server env.API_KEY")
                      to a text snippet containing potential env var references.
                      Typically the raw JSON/TOML values of MCP env fields.
        targets: Target harness names to check. Defaults to all known targets.
        current_env: Optional current environment (os.environ). If provided,
                     only variables that are actually set are reported.
                     Pass None to report all referenced variables regardless.

    Returns:
        EnvPortabilityReport with per-variable portability issues.
    """
    if targets is None:
        targets = ["codex", "gemini", "opencode", "cursor", "aider", "windsurf"]

    # Build a lookup: var_name -> EnvVarSpec (for vars we know about)
    known: dict[str, EnvVarSpec] = {spec.name: spec for spec in ENV_VAR_REGISTRY}

    report = EnvPortabilityReport()

    for source_label, text in config_texts.items():
        # Find all env var references in the text
        referenced: set[str] = set()
        for m in _ENV_REF_RE.finditer(text):
            var_name = m.group(1) or m.group(2)
            if var_name:
                referenced.add(var_name)

        for var_name in sorted(referenced):
            # Skip if current_env filter is active and var isn't set
            if current_env is not None and var_name not in current_env:
                continue

            spec = known.get(var_name)
            if spec is None:
                # Unknown var — assume potential portability issue on all targets
                report.issues.append(EnvPortabilityIssue(
                    var_name=var_name,
                    source_file=source_label,
                    targets_missing=list(targets),
                    targets_partial=[],
                ))
                continue

            missing = []
            partial = []
            for target in targets:
                target_info = spec.targets.get(target)
                if target_info is None:
                    missing.append(target)
                else:
                    level, _ = target_info
                    if level == EnvSupport.NONE:
                        missing.append(target)
                    elif level in (EnvSupport.PARTIAL, EnvSupport.MAPPED):
                        partial.append(target)

            if missing or partial:
                report.issues.append(EnvPortabilityIssue(
                    var_name=var_name,
                    source_file=source_label,
                    targets_missing=missing,
                    targets_partial=partial,
                ))

    return report
