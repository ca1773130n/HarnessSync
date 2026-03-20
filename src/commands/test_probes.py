from __future__ import annotations

"""Probe extraction and execution for /sync-test.

Derives testable assertions from CLAUDE.md rules and runs them
against target harness config files.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RuleProbe:
    """A single testable assertion derived from a CLAUDE.md rule."""
    source_heading: str       # Section heading in CLAUDE.md
    pattern: re.Pattern       # Regex that must match in target config
    description: str          # Human-readable description
    severity: str = "error"   # "error" | "warning"


@dataclass
class ProbeResult:
    """Result of running one probe against one target."""
    probe: RuleProbe
    matched: bool
    target: str


def extract_probes(rules: list[dict]) -> list[RuleProbe]:
    """Derive RuleProbe objects from a list of source rules.

    For each rule block, extract the first imperative sentence and build
    a loose regex probe that checks for the key terms in the target file.

    Args:
        rules: List of rule dicts from SourceReader (each has 'content' key).

    Returns:
        List of RuleProbe objects.
    """
    probes: list[RuleProbe] = []
    for rule in rules:
        content = rule.get("content", "")
        if not content:
            continue

        # Extract section heading
        heading_match = re.search(r"^#{1,3}\s+(.+?)$", content, re.MULTILINE)
        heading = heading_match.group(1).strip() if heading_match else "(unnamed)"

        # Build probes from imperative lines (bullets, "Always", "Never", "Use")
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Strip markdown list markers
            line = re.sub(r"^[-*]\s+", "", line).strip()
            if len(line) < 15 or len(line) > 200:
                continue
            # Look for strong imperative forms
            if not re.match(
                r"(always|never|use\s|avoid|do\s+not|must|require|prefer|enforce|run\s)",
                line,
                re.IGNORECASE,
            ):
                continue

            # Extract 2-4 key content words (skip stop words)
            _STOP = {
                "a", "an", "the", "and", "or", "in", "on", "at", "to",
                "for", "of", "with", "by", "as", "is", "are", "be",
                "that", "this", "when", "than", "all", "any", "use",
            }
            words = [
                w for w in re.findall(r"[A-Za-z]{4,}", line)
                if w.lower() not in _STOP
            ][:3]
            if len(words) < 2:
                continue

            # Build a loose regex that requires the key words in any order
            pattern_str = r"(?i)" + "".join(
                rf"(?=.*\b{re.escape(w)}\b)" for w in words
            )
            try:
                pat = re.compile(pattern_str, re.DOTALL)
            except re.error:
                continue

            probes.append(RuleProbe(
                source_heading=heading,
                pattern=pat,
                description=f"Rule '{heading}': expects keywords {words!r}",
                severity="warning",
            ))
            # Only generate one probe per rule section to avoid noise
            break

    return probes


def run_probes(
    harness: str,
    config_path: Path,
    probes: list[RuleProbe],
) -> list[ProbeResult]:
    """Run all probes against a single target config file."""
    try:
        content = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []  # Caller handles via HarnessTestResult.error

    results: list[ProbeResult] = []
    for probe in probes:
        matched = bool(probe.pattern.search(content))
        results.append(ProbeResult(probe=probe, matched=matched, target=harness))
    return results


# Map harness name -> candidate config file paths (relative to project_dir or HOME)
HARNESS_CONFIG_PATHS: dict[str, list[str]] = {
    "codex":     ["AGENTS.md", ".codex/AGENTS.md"],
    "gemini":    ["GEMINI.md", ".gemini/GEMINI.md"],
    "opencode":  ["AGENTS.md", ".opencode/AGENTS.md"],
    "cursor":    [".cursor/rules/harnesssync.mdc", ".cursor/rules/CLAUDE.mdc"],
    "aider":     ["CONVENTIONS.md", ".aider/CONVENTIONS.md"],
    "windsurf":  [".windsurfrules", ".windsurf/rules.md"],
    "cline":     [".clinerules", ".cline/rules.md"],
    "continue":  [".continue/config.json", ".continue/rules.md"],
    "zed":       [".zed/settings.json", ".zed/assistant.md"],
    "vscode":    [".vscode/claude.md", ".vscode/CLAUDE.md"],
    "neovim":    [".config/nvim/claude.md", ".claude/neovim-rules.md"],
}


def find_target_file(harness: str, project_dir: Path) -> Path | None:
    """Return the first existing config file for the given harness."""
    candidates = HARNESS_CONFIG_PATHS.get(harness, [])
    for rel in candidates:
        path = project_dir / rel
        if path.exists():
            return path
        # Also try relative to HOME for user-level configs
        home_path = Path.home() / rel
        if home_path.exists():
            return home_path
    return None
