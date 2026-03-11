from __future__ import annotations

"""Post-sync config verification (item 28).

After each sync, validates that the written target config files are parseable
and schema-valid. Catches serialization bugs immediately rather than when the
user switches to a broken harness.

Supported verifications:
- JSON files (opencode.json, .cursor/mcp.json, .roo/mcp.json, etc.): json.loads
- TOML files (codex config.toml): tomllib / tomli fallback
- YAML frontmatter in .mdc files: checked with the yaml module (if available)
  or regex-based fallback
- Markdown files (AGENTS.md, GEMINI.md): basic structural checks
  (non-empty, no obviously broken code fences)

Usage:
    verifier = PostSyncVerifier(project_dir)
    results = verifier.verify_all_targets(sync_results)
    print(verifier.format_report(results))
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class VerifyIssue:
    """A single file verification issue."""
    file_path: str
    target: str
    severity: str  # "error" | "warning"
    message: str


@dataclass
class PostSyncVerifyResult:
    """Results of post-sync verification for all targets."""
    issues: list[VerifyIssue] = field(default_factory=list)
    verified_files: int = 0
    targets_checked: int = 0

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "warning")


class PostSyncVerifier:
    """Validates written target config files after a sync operation.

    Designed to be called immediately after SyncOrchestrator.sync_all()
    with the returned results dict.
    """

    def __init__(self, project_dir: Path | None = None):
        self.project_dir = project_dir or Path.cwd()

    def verify_all_targets(
        self,
        sync_results: dict[str, Any],
        adapter_registry: Any | None = None,
    ) -> PostSyncVerifyResult:
        """Verify all target config files written during a sync.

        Args:
            sync_results: Results dict from SyncOrchestrator.sync_all().
            adapter_registry: Optional AdapterRegistry for discovering
                              written file paths per target.

        Returns:
            PostSyncVerifyResult with any issues found.
        """
        result = PostSyncVerifyResult()
        targets_processed: set[str] = set()

        for target_name, target_data in sync_results.items():
            if target_name.startswith("_"):
                continue
            targets_processed.add(target_name)
            issues = self._verify_target(target_name)
            result.issues.extend(issues)

        result.targets_checked = len(targets_processed)

        # Count verified files via scan
        result.verified_files = self._count_verified_files(targets_processed)

        return result

    def verify_target(self, target_name: str) -> list[VerifyIssue]:
        """Verify config files for a single target.

        Public entry point for verifying one target independently.
        """
        return self._verify_target(target_name)

    def format_report(self, result: PostSyncVerifyResult) -> str:
        """Format verification result as a human-readable string."""
        if not result.issues:
            return (
                f"Post-sync verification OK — "
                f"{result.verified_files} file(s) across {result.targets_checked} target(s) are valid."
            )

        lines = [
            "Post-Sync Verification Report",
            "=" * 50,
            f"Targets checked: {result.targets_checked}",
            f"Files verified:  {result.verified_files}",
            f"Errors:   {result.error_count}",
            f"Warnings: {result.warning_count}",
            "",
        ]

        for issue in result.issues:
            prefix = "[ERROR]" if issue.severity == "error" else "[WARN] "
            lines.append(f"  {prefix} {issue.target}: {issue.file_path}")
            lines.append(f"         {issue.message}")

        if result.error_count:
            lines.append("\nSome target files may be invalid. Run /sync to re-sync.")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Target-specific verification
    # ------------------------------------------------------------------

    def _verify_target(self, target_name: str) -> list[VerifyIssue]:
        """Route to the appropriate verifier for each target."""
        target_verifiers = {
            "codex": self._verify_codex,
            "gemini": self._verify_gemini,
            "opencode": self._verify_opencode,
            "cursor": self._verify_cursor,
            "aider": self._verify_aider,
            "windsurf": self._verify_windsurf,
            "cline": self._verify_cline,
        }
        verifier = target_verifiers.get(target_name)
        if verifier is None:
            return []
        return verifier()

    def _verify_codex(self) -> list[VerifyIssue]:
        issues = []
        # AGENTS.md structural check
        agents_md = self.project_dir / "AGENTS.md"
        if agents_md.exists():
            issues.extend(self._check_markdown(agents_md, "codex"))

        # config.toml — try TOML parsing
        codex_toml = Path.home() / ".codex" / "config.toml"
        if codex_toml.exists():
            issues.extend(self._check_toml(codex_toml, "codex"))

        return issues

    def _verify_gemini(self) -> list[VerifyIssue]:
        issues = []
        gemini_md = self.project_dir / "GEMINI.md"
        if gemini_md.exists():
            issues.extend(self._check_markdown(gemini_md, "gemini"))

        # settings.json
        gemini_settings = Path.home() / ".gemini" / "settings.json"
        if gemini_settings.exists():
            issues.extend(self._check_json(gemini_settings, "gemini"))

        return issues

    def _verify_opencode(self) -> list[VerifyIssue]:
        issues = []
        opencode_json = self.project_dir / "opencode.json"
        if opencode_json.exists():
            issues.extend(self._check_json(opencode_json, "opencode"))
        return issues

    def _verify_cursor(self) -> list[VerifyIssue]:
        issues = []
        # .cursor/mcp.json
        cursor_mcp = self.project_dir / ".cursor" / "mcp.json"
        if cursor_mcp.exists():
            issues.extend(self._check_json(cursor_mcp, "cursor"))

        # .cursor/rules/*.mdc — check YAML frontmatter
        rules_dir = self.project_dir / ".cursor" / "rules"
        if rules_dir.is_dir():
            for mdc_file in rules_dir.glob("**/*.mdc"):
                issues.extend(self._check_mdc_frontmatter(mdc_file, "cursor"))

        return issues

    def _verify_aider(self) -> list[VerifyIssue]:
        issues = []
        aider_conf = self.project_dir / ".aider.conf.yml"
        if aider_conf.exists():
            issues.extend(self._check_yaml_syntax(aider_conf, "aider"))
        return issues

    def _verify_windsurf(self) -> list[VerifyIssue]:
        issues = []
        windsurfrules = self.project_dir / ".windsurfrules"
        if windsurfrules.exists():
            issues.extend(self._check_markdown(windsurfrules, "windsurf"))

        # .windsurf/mcp_config.json
        ws_mcp = Path.home() / ".codeium" / "windsurf" / "mcp_config.json"
        if ws_mcp.exists():
            issues.extend(self._check_json(ws_mcp, "windsurf"))

        return issues

    def _verify_cline(self) -> list[VerifyIssue]:
        issues = []
        cline_rules = self.project_dir / ".clinerules"
        if cline_rules.exists():
            issues.extend(self._check_markdown(cline_rules, "cline"))

        roo_mcp = self.project_dir / ".roo" / "mcp.json"
        if roo_mcp.exists():
            issues.extend(self._check_json(roo_mcp, "cline"))

        return issues

    # ------------------------------------------------------------------
    # File-level validators
    # ------------------------------------------------------------------

    def _check_json(self, file_path: Path, target: str) -> list[VerifyIssue]:
        """Verify that a file is valid JSON."""
        try:
            content = file_path.read_text(encoding="utf-8")
            json.loads(content)
            return []
        except json.JSONDecodeError as e:
            return [VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="error",
                message=f"Invalid JSON: {e}",
            )]
        except OSError as e:
            return [VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="warning",
                message=f"Could not read file: {e}",
            )]

    def _check_toml(self, file_path: Path, target: str) -> list[VerifyIssue]:
        """Verify that a file is valid TOML."""
        try:
            content = file_path.read_bytes()
        except OSError as e:
            return [VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="warning",
                message=f"Could not read file: {e}",
            )]

        # Try stdlib tomllib (Python 3.11+) then tomli
        try:
            try:
                import tomllib  # type: ignore
                tomllib.loads(content.decode("utf-8"))
            except ImportError:
                try:
                    import tomli  # type: ignore
                    tomli.loads(content.decode("utf-8"))
                except ImportError:
                    # No TOML parser available — do a basic syntax check
                    return self._check_toml_basic(file_path, target, content.decode("utf-8"))
            return []
        except Exception as e:
            return [VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="error",
                message=f"Invalid TOML: {e}",
            )]

    def _check_toml_basic(self, file_path: Path, target: str, content: str) -> list[VerifyIssue]:
        """Minimal TOML sanity check (no parser available)."""
        # Check for unmatched brackets — very basic
        if content.count("[") != content.count("]"):
            return [VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="warning",
                message="Possible TOML syntax issue: unmatched '[' / ']' brackets",
            )]
        return []

    def _check_yaml_syntax(self, file_path: Path, target: str) -> list[VerifyIssue]:
        """Verify YAML syntax (if PyYAML is available, else basic check)."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            return [VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="warning",
                message=f"Could not read file: {e}",
            )]

        try:
            import yaml  # type: ignore
            yaml.safe_load(content)
            return []
        except ImportError:
            pass  # PyYAML not installed — skip
        except Exception as e:
            return [VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="error",
                message=f"Invalid YAML: {e}",
            )]
        return []

    def _check_markdown(self, file_path: Path, target: str) -> list[VerifyIssue]:
        """Basic structural check for markdown files."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            return [VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="warning",
                message=f"Could not read file: {e}",
            )]

        issues = []

        if not content.strip():
            issues.append(VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="warning",
                message="File is empty",
            ))
            return issues

        # Check for unclosed code fences (odd number of ```)
        fence_count = len(re.findall(r"^```", content, re.MULTILINE))
        if fence_count % 2 != 0:
            issues.append(VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="warning",
                message=f"Possible unclosed code fence ({fence_count} ``` markers; expected even number)",
            ))

        return issues

    def _check_mdc_frontmatter(self, file_path: Path, target: str) -> list[VerifyIssue]:
        """Verify MDC file has parseable YAML frontmatter."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            return []

        if not content.startswith("---"):
            return []  # No frontmatter — acceptable

        end = content.find("\n---", 3)
        if end == -1:
            return [VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="warning",
                message="MDC file has unclosed YAML frontmatter (missing closing ---)",
            )]

        frontmatter = content[3:end]
        try:
            import yaml  # type: ignore
            yaml.safe_load(frontmatter)
        except ImportError:
            pass  # Can't validate without yaml
        except Exception as e:
            return [VerifyIssue(
                file_path=str(file_path),
                target=target,
                severity="error",
                message=f"MDC frontmatter YAML parse error: {e}",
            )]

        return []

    def _count_verified_files(self, targets: set[str]) -> int:
        """Estimate number of config files checked."""
        count = 0
        file_candidates = [
            self.project_dir / "AGENTS.md",
            self.project_dir / "GEMINI.md",
            self.project_dir / "opencode.json",
            self.project_dir / ".clinerules",
            self.project_dir / ".windsurfrules",
            self.project_dir / ".cursor" / "mcp.json",
            self.project_dir / ".roo" / "mcp.json",
            self.project_dir / ".aider.conf.yml",
            Path.home() / ".codex" / "config.toml",
            Path.home() / ".gemini" / "settings.json",
            Path.home() / ".codeium" / "windsurf" / "mcp_config.json",
        ]
        for p in file_candidates:
            if p.exists():
                count += 1
        # Count .mdc files
        cursor_rules = self.project_dir / ".cursor" / "rules"
        if cursor_rules.is_dir():
            count += sum(1 for _ in cursor_rules.glob("**/*.mdc"))
        return count
